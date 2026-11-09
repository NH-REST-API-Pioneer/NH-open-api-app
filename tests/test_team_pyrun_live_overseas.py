"""해외 MKU 1분봉 장중 실행(`live.py`·`registry.py` 시장 반영) 시험.

가짜 해외 api(`api.py` 의 `ovs_*` 이름만 가짐 — 국내 함수를 부르면 바로 `AttributeError`)로 시간표·휴장·USD 표기·
시장 가드·장중 시작/같은 날 재시작을 봅니다. 시각은 손으로 넣고, 가짜는 주문을 받은 시각을 적어
**휴장(20:35~20:50) 중엔 주문이 하나도 없음**을 확인합니다. NH 서버로는 아무것도 나가지 않습니다.
"""
import json
import shutil
from pathlib import Path

import pytest

from backend.team_pyrun import api as real_api
from backend.team_pyrun import live, markets, replay, runner
from backend.team_pyrun.journal import Journal, entered_windows
from backend.team_pyrun.live import LiveRun, RunSpec, StartRefused
from backend.team_pyrun.loader import load
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, in_break
from backend.team_pyrun.registry import Registry
from backend.team_spread.legs import Leg
from tests.test_team_pyrun_live import STRATEGY_SRC, FakeApi, at
from tests.test_team_pyrun_markets import FakeOvsApi

MKU = "MKUX26"
TODAY = "20261103"
HERE = Path(__file__).parent
WEEK03 = HERE / "fixtures/team_pyrun/week03"
ORB_APP = HERE.parent / "backend/team_pyrun/guide/examples/strategy_orb_app.py"

#: 해외 시험 전략 — `script` 의 분에 (개장, 방향) 신호를 낸다. Params 에 장 시간 칸이 없다(해외 시간표로 채움).
MKU_SRC = '''
"""해외 시험 전략."""
from dataclasses import dataclass

TICK = 0.0001
TICK_VALUE = 2.5
NAME = "fakemku"


@dataclass
class Params:
    hold_min: int = 600
    max_stops_per_day: int = 2
    flatten_at: str = "235000"


@dataclass
class Sig:
    minute: object
    window: str
    side: object
    reason: str
    stop_ticks: object = None


class Day:
    def __init__(self):
        self.stops = 0
        self.in_position = False


class Strat:
    def __init__(self, p):
        self.p = p
        self.script = {}
        self.day = Day()
        self.date = None
        self.entered = set()
        self.exits = []
        self.asked = []
        self.deadline = None
        self.raise_at = None
        self.target = None

    def on_minute(self, m):
        if m.date != self.date:
            self.date = m.date
            self.day = Day()
            self.entered = set()
        if m.time == self.raise_at:
            raise RuntimeError("전략 고장")
        act = self.script.get(m.time)
        if act is None:
            return []
        window, side = act
        if side and (window in self.entered or self.day.in_position
                     or self.day.stops >= self.p.max_stops_per_day):
            side = None
        return [Sig(m, window, side, "시험", 20 if side else None)]

    def on_entry(self, window):
        self.day.in_position = True
        self.entered.add(window)

    def on_exit(self, pnl, stopped):
        self.day.in_position = False
        self.day.stops += int(stopped)
        self.exits.append((pnl, stopped))

    def exit_reason(self, clock, price, low, high, pos):
        self.asked.append(clock)
        if pos["side"] == "buy" and price <= pos["stop"]:
            return "손절"
        if pos["side"] == "sell" and price >= pos["stop"]:
            return "손절"
        if self.deadline and clock >= self.deadline:
            return "시간 청산"
        return None


STRATEGY = Strat
'''

#: 같은 전략인데 청산 판단 함수가 없어 앱의 공통 청산 규칙(손절·익절·시간)을 쓰는 것
MKU_COMMON_SRC = MKU_SRC.replace("    def exit_reason(", "    def _not_used(").replace('NAME = "fakemku"',
                                                                                     'NAME = "fakemkuc"')


def ovs_bar(time: str, close: float = 0.7500, date: str = TODAY, *, high=None, low=None) -> dict:
    hi = close if high is None else high
    lo = close if low is None else low
    return {"ref_dt": date, "exch_tm": time, "open_pric": f"{close:.4f}", "high_pric": f"{hi:.4f}",
            "low_pric": f"{lo:.4f}", "close_pric": f"{close:.4f}", "cum_trd_qty": "10", "glb_biz_dt": date}


#: 해외 마스터 `etc_fut.mst` 의 MKU 줄 꼴 (칸 이름은 OVERSEAS_FUTURES_FIELDS)
MASTER = [
    {"code": "MKUX26", "comd": "MKU", "type": "F", "trdf": "0", "yymm": "202611", "lmon": "1", "lmon_my": "1"},
    {"code": "MKUZ26", "comd": "MKU", "type": "F", "trdf": "0", "yymm": "202612", "lmon": "0", "lmon_my": "0"},
]


class FakeLive(FakeOvsApi):
    """해외 이름만 가진 가짜 + 1분봉·현재가·최근월물. 주문 받은 시각(`order_clocks`)을 적는다."""

    nearest_mku = staticmethod(real_api.nearest_mku)

    def __init__(self, clock=None):
        super().__init__()
        self.chart: list[dict] = []
        self.last = "0.7500"
        self.clock = clock
        self.order_clocks: list[str] = []
        self.detail = ("00000000000000000000.000100000", "00000000000000002.50000000")

    def ovs_chart_minute(self, sym, *, req_qty):
        self.calls.append(("ovs_chart_minute", sym, req_qty))
        return [dict(r) for r in self.chart]

    def ovs_product_detail(self):
        self.calls.append(("ovs_product_detail",))
        return [{"prd_cd": "KU", "tick_unt": "0.00005", "tick_val": "6.25"},
                {"prd_cd": "MKU", "tick_unt": self.detail[0], "tick_val": self.detail[1]}]

    def mku_master_rows(self):
        self.calls.append(("mku_master_rows",))
        return [dict(r) for r in MASTER]

    def ovs_market_order(self, sym, side, qty=1):
        if self.clock is not None:
            self.order_clocks.append(self.clock["now"].strftime("%H%M%S"))
        return super().ovs_market_order(sym, side, qty)


def make_ovs(tmp_path, *, mode="orders", start="082000", src=MKU_SRC, file="fakemku.py", sym=None, fake=None,
             stops_before=0, windows_before=()):
    folder = tmp_path / "strategies"
    folder.mkdir(exist_ok=True)
    (folder / file).write_text(src, encoding="utf-8")
    loaded = load(folder, file)
    clock = {"now": at(start)}
    fake = fake or FakeLive(clock)
    fake.clock = clock
    out = tmp_path / "run"
    run = LiveRun(f"{TODAY}_fakemku_{mode}", out, loaded, RunSpec(file=file, mode=mode, sym=sym),
                  api_module=fake, now=lambda: clock["now"], sleep=lambda s: None,
                  stops_before=stops_before, windows_before=windows_before)
    return run, fake, out, clock


def go(run, clock, hhmmss: str) -> None:
    """시계를 옮기고 그 시각에 step 한 번."""
    clock["now"] = at(hhmmss)
    run.step(clock["now"])


def journal(out):
    return Journal(out / "journal.jsonl").read()


def texts(out):
    return [r.get("text", "") for r in journal(out)]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def names(fake):
    return [c[0] for c in fake.calls]


def entered_buy(tmp_path, *, at_bar="200000", **kw):
    """`at_bar` 봉에서 서울 매수 신호 → 그 다음 분 04초에 모의 주문·체결까지 간 해외 실행."""
    run, fake, out, clock = make_ovs(tmp_path, **kw)
    run.prepare()
    run.runner.strat.script = {at_bar: ("서울", "buy")}
    fake.chart = [ovs_bar(at_bar)]
    nxt = runner._plus_minute(at_bar)
    go(run, clock, nxt[:4] + "04")
    assert run.runner.pos is not None and run.runner.pos["side"] == "buy"
    return run, fake, out, clock


# ---------------------------------------------------------------- 시장 값의 출처
def test_국내_값은_markets_가_출처():
    assert live.END_TIME == DOMESTIC.end_time == "153100"
    assert runner.PAPER_FEE == DOMESTIC.paper_fee == 690.0
    assert runner.PAPER_SLIP_TICKS == DOMESTIC.paper_slip_ticks == 1
    assert (OVERSEAS.tick, OVERSEAS.tick_value) == (0.0001, 2.5)
    assert (DOMESTIC.tick, DOMESTIC.tick_value) == (0.1, 1000)


def test_빈_종목의_시장은_전략_TICK_으로():
    assert markets.market_of_tick(0.0001) is OVERSEAS
    assert markets.market_of_tick(0.1) is DOMESTIC
    assert markets.market_of_tick(0.2) is DOMESTIC        # MKU 틱이 아니면 국내(서버 틱 확인이 거부한다)


# ---------------------------------------------------------------- 시간표
def test_0824_대기_0826_분봉과_현재가(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="082000")
    run.prepare()
    assert run.sym == MKU and run.state == "대기" and run.market is OVERSEAS
    # 빈 종목 → MKU 틱 전략이라 해외 마스터의 최근월물
    assert ("mku_master_rows",) in fake.calls
    # 장 시간 칸은 해외 시간표로 채워졌다
    p = run.runner.p
    assert (p.session_start, p.entry_start, p.entry_end, p.flatten_at, p.session_end) == (
        "082500", "082500", "235000", "235000", "235500")
    before = len(fake.calls)
    go(run, clock, "082430")
    assert run.state == "대기" and len(fake.calls) == before
    fake.chart = [ovs_bar("082500")]
    go(run, clock, "082604")
    new = names(fake)[before:]
    assert new.count("ovs_chart_minute") == 1 and new.count("ovs_price") == 1
    assert run.runner.strat.date == TODAY and run.state == "진행 중"
    # 국내 함수는 하나도 부르지 않았다 (가짜에 없어서 불렀으면 AttributeError)
    assert not any(n.startswith(("domestic", "all_futures", "price", "chart_minute")) for n in names(fake))


def test_해외는_국내_끝_시각_뒤에도_돌고_2355에_끝난다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path, at_bar="153000")
    go(run, clock, "160000")
    assert run.state == "진행 중"
    fake.last = "0.7505"
    go(run, clock, "235000")                     # Params flatten_at(23:50) — 앱의 장 마감 정리
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert run.runner.trades[-1]["reason"] == "장 마감 정리"
    go(run, clock, "235459")
    assert run.state == "진행 중"
    go(run, clock, "235500")
    assert run.state == "끝" and run.ended_reason == "장 끝"
    assert read_json(out / "run.json")["state"] == "끝"


def test_틱이_다르면_거부한다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path)
    fake.detail = ("0.00005", "6.25")
    with pytest.raises(StartRefused, match="틱·틱가치가 전략 가정과 다릅니다"):
        run.prepare()
    assert fake.orders == [] and fake.count("ovs_open_interest_page") == 0


def test_시작_잔고는_쪽을_따라간_잔고로_본다(tmp_path):
    fake = FakeLive()
    fake.oi_pages = {"": ([], "k2"), "k2": ([{"sym": MKU, "trd_tp": "1", "opint_qty": "1"}], "")}
    run, fake, out, clock = make_ovs(tmp_path, fake=fake)
    with pytest.raises(StartRefused, match=r"MKUX26 잔고 \+1계약"):
        run.prepare()
    assert fake.calls.count(("ovs_open_interest_page", "k2")) == 1


# ---------------------------------------------------------------- 시장 가드 (R6)
def test_MKU_틱_전략을_A75_종목에_걸면_조회_전에_거부(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, sym="A756B000")
    with pytest.raises(StartRefused, match="종목의 시장과 전략 틱이 맞지 않습니다"):
        run.prepare()
    assert fake.calls == [] and fake.orders == []
    assert read_json(out / "run.json")["state"] == "끝"


def test_국내_틱_전략을_MKU_종목에_걸면_조회_전에_거부(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, src=STRATEGY_SRC, file="fake.py", sym=MKU, fake=FakeApi())
    with pytest.raises(StartRefused, match="종목의 시장과 전략 틱이 맞지 않습니다"):
        run.prepare()
    assert fake.calls == [] and fake.orders == []


def test_모르는_시장의_종목은_조회_전에_거부(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, sym="KUX26")
    with pytest.raises(StartRefused, match="시장을 알 수 없는 종목코드"):
        run.prepare()
    assert fake.calls == []


# ---------------------------------------------------------------- 휴장 (20:35~20:50)
def test_휴장_중_손절가를_지나면_2050_첫_가격에_청산_주문_한_번(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    stop = run.runner.pos["stop"]
    assert stop == pytest.approx(0.7481)                       # 진입가 0.7501 − 20틱
    fake.last = "0.7470"                                       # 손절가 아래
    for t in ("203500", "203600", "204000", "204959"):
        go(run, clock, t)
    assert [o[1] for o in fake.orders] == ["buy"]              # 휴장 중엔 주문 없음
    assert run.runner.pos is not None
    assert any("휴장 중" in x and "손절" in x for x in texts(out))
    fake.last = "0.7490"                                       # 휴장이 끝난 첫 가격은 손절가 위로 돌아왔어도
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy", "sell"]      # 휴장 중 정한 청산을 그 가격에 한 번
    assert run.runner.pos is None and run.runner.trades[-1]["reason"] == "손절"
    assert run.runner.trades[-1]["exit_time"] == "205000"
    for t in ("205001", "205002", "205104"):
        go(run, clock, t)
    assert len(fake.orders) == 2
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)
    assert run.runner.strat.day.stops == 1                     # on_exit 로 한 번
    from backend.team_pyrun.journal import count_stops
    assert count_stops([out], TODAY) == 1                       # 휴장 중 정해 20:50 에 나간 손절도 하루 손절로 셈


def test_휴장_중_공통_규칙_손절도_2050_첫_가격에(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path, src=MKU_COMMON_SRC, file="fakemkuc.py")
    fake.last = "0.7470"
    go(run, clock, "203600")
    assert len(fake.orders) == 1
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert run.runner.trades[-1]["reason"] == "손절"
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)


def test_휴장_중_기한_청산도_휴장_끝_첫_가격에(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    run.runner.strat.deadline = "204000"
    go(run, clock, "204000")
    assert len(fake.orders) == 1 and run.runner.pos is not None
    asked = len(run.runner.strat.asked)
    go(run, clock, "204500")
    assert len(run.runner.strat.asked) == asked                # 정한 뒤엔 다시 묻지 않는다
    go(run, clock, "205000")
    assert run.runner.trades[-1]["reason"] == "시간 청산" and len(fake.orders) == 2


def test_휴장_직전_신호는_휴장이_끝난_첫_가격에_진입(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path)
    run.prepare()
    run.runner.strat.script = {"203400": ("런던", "buy")}
    fake.chart = [ovs_bar("203400")]
    go(run, clock, "203504")                                   # 20:34 봉 → 대기 신호, 그런데 휴장
    assert run.runner.pending is not None and fake.orders == []
    for t in ("203600", "204500", "204959"):
        go(run, clock, t)
    assert fake.orders == [] and run.runner.pending is not None
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy"] and run.runner.pos["entry_time"] == "205000"
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)


def test_휴장_중_중지와_정리_요청은_휴장이_끝난_뒤에_정리(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    go(run, clock, "204000")
    run.request_flatten()
    go(run, clock, "204001")
    run.request_stop()
    for t in ("204002", "204500", "204959"):
        go(run, clock, t)
    assert len(fake.orders) == 1 and run.state != "끝"
    assert any("휴장 중 정리 요청" in x for x in texts(out)) and any("휴장 중 중지 요청" in x for x in texts(out))
    fake.last = "0.7510"
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.state == "끝"
    assert run.runner.trades[-1]["exit"] == pytest.approx(0.7509)  # 휴장이 끝난 첫 가격(가짜 체결 = 현재가 − 1틱)
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)


def test_휴장_중_오류로_끝나면_정리하지_않고_확인_필요(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    run.runner.strat.raise_at = "203600"
    fake.chart = [ovs_bar("203600")]
    go(run, clock, "203704")
    assert run.state == "오류" and len(fake.orders) == 1
    assert "정리 안 함 — 확인 필요" in run.ended_reason and "휴장" in run.ended_reason
    s = read_json(out / "summary.json")
    assert "휴장" in s["halted"]


def test_휴장_중_finish_도_주문하지_않는다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    clock["now"] = at("204500")
    run.finish("중지")                                          # 앱 종료 등 — 휴장 중이면 주문하지 않고 확인 필요
    assert len(fake.orders) == 1 and "휴장" in run.ended_reason


# ---------------------------------------------------------------- USD 표기
def test_run_json_status_summary_에_시장과_통화(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    j = read_json(out / "run.json")
    assert (j["market"], j["currency"], j["kind"]) == ("overseas", "USD", "minute")
    s = run.status()
    assert (s["market"], s["currency"]) == ("overseas", "USD")
    fake.last = "0.7511"
    go(run, clock, "200500")
    run.finish("중지")
    summ = read_json(out / "summary.json")
    assert (summ["market"], summ["currency"]) == ("overseas", "USD")
    t = summ["trades"][0]
    # 진입 0.7501 → 청산 0.7510(현재가 − 1틱) = 9틱 × US$2.5
    assert t["ticks"] == 9 and t["pnl"] == pytest.approx(22.5)
    assert summ["summary"]["net_pnl"] == pytest.approx(22.5)
    assert run.status()["today_pnl"] == pytest.approx(22.5)
    trade_row = next(r for r in journal(out) if r["kind"] == "trade")
    assert "USD" in trade_row["text"] and "원" not in trade_row["text"]
    assert "123456789" not in (out / "journal.jsonl").read_text(encoding="utf-8")


def test_종이_실행은_US2_수수료와_1틱_슬리피지_주문_없음(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path, mode="paper")
    assert run.runner.pos["entry"] == pytest.approx(0.7501)     # 현재가 0.7500 + 1틱
    fake.last = "0.7511"
    go(run, clock, "200500")
    run.finish("중지")
    t = run.runner.trades[0]
    assert t["fee"] == pytest.approx(4.0) and t["exit"] == pytest.approx(0.7510)
    assert fake.orders == []
    assert not {"ovs_market_order", "ovs_open_interest_page", "ovs_order_history_page", "ovs_deposit"} & set(names(fake))
    assert read_json(out / "summary.json")["currency"] == "USD"


def test_국내_실행의_시장과_통화(tmp_path):
    from tests.test_team_pyrun_live import make_run
    run, fake, out = make_run(tmp_path)
    run.prepare()
    j = read_json(out / "run.json")
    assert (j["market"], j["currency"], j["kind"]) == ("domestic", "KRW", "minute")
    assert run.status()["currency"] == "KRW"


# ---------------------------------------------------------------- 장중 시작·같은 날 재시작 (R2)
def test_준비_봉에서_신호가_난_개장은_늦게_들어가지_않는다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="093030")
    run.runner.strat.script = {"091500": ("서울", "buy"), "091600": ("서울", "buy"), "093000": ("서울", "buy")}
    fake.chart = [ovs_bar("091500"), ovs_bar("091600"), ovs_bar("092900")]
    run.prepare()
    assert run.runner.strat.entered == {"서울"}
    assert run.runner.strat.day.in_position is False             # 되살리기만 하고 보유는 없다
    assert any("서울" in x and "준비 봉" in x for x in texts(out))
    fake.chart = [ovs_bar("093000")]
    go(run, clock, "093104")
    assert fake.orders == [] and run.runner.pending is None and run.runner.pos is None


def test_어제_준비_봉의_신호는_오늘_개장을_막지_않는다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="093030")
    run.runner.strat.script = {"091500": ("서울", "buy")}
    fake.chart = [ovs_bar("091500", date="20261102")]
    run.prepare()
    run.runner.strat.script = {"093000": ("서울", "buy")}
    fake.chart = [ovs_bar("093000")]
    go(run, clock, "093104")
    assert [o[1] for o in fake.orders] == ["buy"]


def test_앞선_실행이_들어간_개장은_다시_들어가지_않는다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="100030", windows_before=("서울",))
    fake.chart = [ovs_bar("095900")]
    run.prepare()
    assert run.runner.strat.entered == {"서울"} and run.runner.strat.day.in_position is False
    run.runner.strat.script = {"100000": ("서울", "buy"), "100100": ("런던", "buy")}
    fake.chart = [ovs_bar("100000")]
    go(run, clock, "100104")
    assert fake.orders == []
    fake.chart = [ovs_bar("100100")]
    go(run, clock, "100204")                                     # 다른 개장은 된다
    assert [o[1] for o in fake.orders] == ["buy"] and run.runner.pos["window"] == "런던"


def test_장_전에_켜도_오늘_첫_봉에서_다시_넣는다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="080000", windows_before=("서울",), stops_before=1)
    fake.chart = [ovs_bar("230000", date="20261102")]
    run.prepare()
    run.runner.strat.script = {"093000": ("서울", "buy")}
    fake.chart = [ovs_bar("230000", date="20261102"), ovs_bar("093000")]
    go(run, clock, "093104")                                     # 오늘 첫 봉에서 전략이 하루를 새로 만든다
    assert run.runner.strat.entered == {"서울"} and run.runner.strat.day.stops == 1
    assert fake.orders == []


def test_손절은_한_번만_센다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="100030", windows_before=("서울",), stops_before=1)
    fake.chart = [ovs_bar("095900")]
    run.prepare()
    assert run.runner.strat.day.stops == 1 and run.status()["stops"] == 1     # on_exit 로 또 세지 않는다
    run.runner.strat.script = {"100100": ("런던", "buy")}
    fake.chart = [ovs_bar("100100")]
    go(run, clock, "100204")
    fake.last = "0.7400"
    go(run, clock, "100205")
    assert run.runner.trades[-1]["reason"] == "손절"
    assert run.runner.strat.day.stops == 2 and run.status()["stops"] == 2


def test_개장이_없는_전략은_week02_처럼_손절만_이어받는다(tmp_path):
    from tests.test_team_pyrun_live import make_run
    run, fake, out = make_run(tmp_path, start="091030", stops_before=1)
    run.prepare()
    assert run.runner.strat.day.stops == 1
    assert not any("개장" in x for x in texts(out))


def test_entered_windows_는_trade_와_진입_기록에서(tmp_path):
    a = tmp_path / "a"
    j = Journal(a / "journal.jsonl")
    j.write("trade", reason="손절", exit_date=TODAY, window="서울")
    j.write("trade", reason="익절", exit_date="20261102", window="뉴욕")       # 어제
    j.write("event", text="진입 buy 0.7501", window="런던")                    # 진입만 하고 trade 없이 끝남
    j.write("trade", reason="손절", exit_date=TODAY)                          # window 없음
    assert entered_windows([a, tmp_path / "없음"], TODAY) == {"서울", "런던"}


def test_진입_기록에_window_가_남는다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    ev = [r for r in journal(out) if r["kind"] == "event" and r.get("text", "").startswith("진입 ")]
    assert ev and ev[0]["window"] == "서울"


# ---------------------------------------------------------------- 실제 ORB 파일로 (R2)
def _orb_folder(tmp_path):
    d = tmp_path / "strategies"
    d.mkdir(exist_ok=True)
    for src in (ORB_APP, WEEK03 / "strategy_orb.py", WEEK03 / "common.py"):
        shutil.copy(src, d / src.name)
    return d


def _orb_run(tmp_path, start, **kw):
    loaded = load(_orb_folder(tmp_path), "strategy_orb_app.py")
    clock = {"now": at(start)}
    fake = FakeLive(clock)
    run = LiveRun(f"{TODAY}_orb_orders", tmp_path / "run", loaded, RunSpec("strategy_orb_app.py", "orders", None),
                  api_module=fake, now=lambda: clock["now"], sleep=lambda s: None, **kw)
    return run, fake, clock


def _seoul_range():
    """서울 09:00~09:14 범위 0.7480~0.7500(20틱)."""
    return [ovs_bar(f"09{i:02d}00", 0.7490, high=0.7500, low=0.7480) for i in range(15)]


def test_ORB_범위_돌파_뒤에_켜면_늦게_들어가지_않는다(tmp_path):
    run, fake, clock = _orb_run(tmp_path, "092030")
    fake.chart = _seoul_range() + [ovs_bar(f"09{i}00", 0.7502) for i in range(15, 20)]   # 09:15 돌파
    run.prepare()
    assert any(r.entered for r in run.runner.strat.ranges if r.name == "서울")
    assert run.runner.strat.day.in_position is False
    fake.chart = [ovs_bar("092000", 0.7503)]
    go(run, clock, "092104")
    assert fake.orders == [] and run.runner.pos is None
    assert "이미 진입함" in run.runner.last_signal["reason"]


def test_ORB_같은_날_앞선_실행이_서울에서_손절했으면_다시_안_들어가고_손절은_한_번(tmp_path):
    run, fake, clock = _orb_run(tmp_path, "091430", windows_before=("서울",), stops_before=1)
    fake.chart = _seoul_range()[:14]
    run.prepare()
    assert run.runner.strat.day.stops == 1
    fake.chart = [_seoul_range()[14], ovs_bar("091500", 0.7502)]
    go(run, clock, "091604")
    assert fake.orders == [] and "이미 진입함" in run.runner.last_signal["reason"]
    assert run.runner.strat.day.stops == 1


def test_ORB_처음_켠_날은_돌파에_들어간다(tmp_path):
    run, fake, clock = _orb_run(tmp_path, "091430")
    fake.chart = _seoul_range()[:14]
    run.prepare()
    fake.chart = [_seoul_range()[14], ovs_bar("091500", 0.7502)]
    go(run, clock, "091604")
    assert [o[1] for o in fake.orders] == ["buy"] and run.runner.pos["window"] == "서울"


# ---------------------------------------------------------------- registry
def no_master_find(spec, *, api_module, today):
    """시험 `Registry` 의 종목 찾기 — 실제 마스터(`~/NHFutures/master`)·품목 세부정보를 읽지 않고 모르는 종목으로 거부."""
    raise StartRefused(f"종목 「{spec}」 을 마스터에서 찾지 못했습니다 (시험)")


def make_reg(tmp_path, *, now="100000", fake=None, src=MKU_SRC, file="fakemku.py", find=no_master_find):
    folder = tmp_path / "strategies"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(src, encoding="utf-8")
    (folder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    clock = {"now": at(now)}
    fake = fake or FakeLive(clock)
    fake.clock = clock
    reg = Registry(tmp_path / "pyruns", folder, now=lambda: clock["now"], active_env=lambda: "paper",
                   start_thread=False, api_module=fake, sleep=lambda s: None, find=find)
    return reg, fake, clock


def test_registry_해외는_해외_끝_시각까지_시작할_수_있다(tmp_path):
    reg, fake, clock = make_reg(tmp_path, now="160000")
    status = reg.start(RunSpec("fakemku.py", "paper", None))
    assert status["sym"] == MKU and status["market"] == "overseas" and status["currency"] == "USD"
    reg2, fake2, _ = make_reg(tmp_path / "late", now="235500")
    with pytest.raises(StartRefused, match="23:55"):
        reg2.start(RunSpec("fakemku.py", "paper", None))
    assert fake2.calls == []
    reg3, fake3, _ = make_reg(tmp_path / "late2", now="235459")
    assert reg3.start(RunSpec("fakemku.py", "paper", MKU))["state"] == "진행 중"


def test_registry_국내_전략은_여전히_1531_에_거부(tmp_path):
    reg, fake, clock = make_reg(tmp_path, now="153100", fake=FakeApi())
    with pytest.raises(StartRefused, match="15:31"):
        reg.start(RunSpec("fake.py", "paper", None))


def test_registry_주말은_그대로_거부(tmp_path):
    reg, fake, clock = make_reg(tmp_path)
    clock["now"] = at("100000", "20261107")
    with pytest.raises(StartRefused, match="주말"):
        reg.start(RunSpec("fakemku.py", "paper", None))
    assert fake.calls == []


def test_registry_시장과_틱이_다르면_폴더_전에_거부(tmp_path):
    # 설계 4.1(의도한 바뀜): A75…·MKU… 밖의 코드(큰 계약 KU)는 종목 찾기로 품목을 알고, 틱 확인은 그 품목의 틱·틱가치와 비교
    ku = Leg("main", "KUX26", "KU", "overseas", "FSGX", "USD", 0.00005, 6.25, "202611")
    reg, fake, clock = make_reg(tmp_path, find=lambda spec, **kw: ku)
    for spec in (RunSpec("fakemku.py", "orders", "A756B000"), RunSpec("fake.py", "orders", MKU)):
        with pytest.raises(StartRefused, match="종목의 시장과 전략 틱이 맞지 않습니다"):
            reg.start(spec)
    with pytest.raises(StartRefused, match="틱·틱가치가 전략 가정과 다릅니다 — 종목 KUX26"):
        reg.start(RunSpec("fakemku.py", "paper", "KUX26"))
    assert fake.calls == [] and not (tmp_path / "pyruns").exists()


def test_registry_같은_MKU_종목_주문_실행은_하나(tmp_path):
    reg, fake, clock = make_reg(tmp_path)
    first = reg.start(RunSpec("fakemku.py", "orders", None))
    assert first["sym"] == MKU
    with pytest.raises(StartRefused, match="같은 종목 MKUX26"):
        reg.start(RunSpec("fakemku.py", "orders", MKU))
    other = reg.start(RunSpec("fakemku.py", "orders", "MKUZ26"))        # 다른 월물은 된다
    assert other["id"] == f"{TODAY}_fakemku_orders_MKUZ26"
    assert reg.start(RunSpec("fakemku.py", "paper", MKU))["mode"] == "paper"


def test_registry_앞선_실행의_window_와_손절을_넘긴다(tmp_path):
    reg, fake, clock = make_reg(tmp_path)
    root = tmp_path / "pyruns"
    prev = root / f"{TODAY}_fakemku_orders"
    prev.mkdir(parents=True)
    (prev / "run.json").write_text(json.dumps({"id": prev.name, "name": "fakemku", "sym": MKU, "mode": "orders",
                                               "state": "끝", "started_at": "2026-11-03T09:00:00"}), encoding="utf-8")
    Journal(prev / "journal.jsonl").write("trade", reason="손절", exit_date=TODAY, window="서울", pnl=-50.0)
    other = root / f"{TODAY}_fakemku_paper"        # 다른 방식은 넘기지 않는다
    other.mkdir()
    (other / "run.json").write_text(json.dumps({"id": other.name, "name": "fakemku", "sym": MKU, "mode": "paper",
                                                "state": "끝", "started_at": "2026-11-03T09:00:00"}), encoding="utf-8")
    Journal(other / "journal.jsonl").write("trade", reason="손절", exit_date=TODAY, window="런던", pnl=-50.0)
    status = reg.start(RunSpec("fakemku.py", "orders", None))
    run = reg.get(status["id"])
    assert run.windows_before == ("서울",) and run.stops_before == 1
    assert run.runner.strat.entered == {"서울"} and run.runner.strat.day.stops == 1


def test_registry_재시작_정리는_해외_잔고를_쪽을_따라_본다(tmp_path):
    reg, fake, clock = make_reg(tmp_path)
    folder = tmp_path / "pyruns" / f"{TODAY}_fakemku_orders"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"id": folder.name, "name": "fakemku", "sym": MKU, "mode": "orders",
                                                 "state": "진행 중", "started_at": "2026-11-03T09:00:00"}),
                                     encoding="utf-8")
    fake.oi_pages = {"": ([], "k2"), "k2": ([{"sym": MKU, "trd_tp": "2", "opint_qty": "1"}], "")}
    assert reg.recover() == [folder.name]
    assert any("잔고 MKUX26 -1계약" in x for x in texts(folder))
    assert fake.orders == []


# ---------------------------------------------------------------- 리플레이의 하루 봉 수 거르기
def test_load_minutes_는_해외_날을_250봉으로_거르지_않는다(tmp_path):
    csv_path = tmp_path / "bars.csv"
    rows = ["ref_dt,exch_tm,open_pric,high_pric,low_pric,close_pric,cum_trd_qty"]
    rows += [f"20261031,{h:02d}{m:02d}00,0.75,0.75,0.75,0.75,1" for h in range(0, 2) for m in range(60)]   # 120봉
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert replay.load_minutes(csv_path) == []                       # 국내 기본은 그대로 250봉 미만을 뺀다
    assert len(replay.load_minutes(csv_path, market=OVERSEAS)) == 120


def test_해외_마스터_줄(monkeypatch):
    from types import SimpleNamespace

    from backend.master import master_store

    table = SimpleNamespace(rows_as_dicts=lambda: iter([*MASTER, {"code": "KUX26", "comd": "KU"}]))
    monkeypatch.setattr(master_store, "load_master", lambda m, base_dir=None: SimpleNamespace(
        ok=True, table=table, error=None, master=m))
    rows = real_api.mku_master_rows()
    assert [r["code"] for r in rows] == ["MKUX26", "MKUZ26"]
    assert real_api.nearest_mku(rows) == MKU
    monkeypatch.setattr(master_store, "load_master", lambda m, base_dir=None: SimpleNamespace(
        ok=False, table=None, error="받아 둔 파일이 없습니다.", master=m))
    with pytest.raises(ValueError, match="마스터"):
        real_api.mku_master_rows()


def test_휴장_전후를_초마다_돌려도_휴장_중_주문은_없다(tmp_path):
    """보유 중 손절가를 오가는 가격 + 정리 요청 + 휴장 직전 대기 신호 — 20:33~20:52 를 1초씩."""
    run, fake, out, clock = entered_buy(tmp_path, at_bar="203000")
    run.runner.strat.script = {"203400": ("런던", "buy")}
    fake.chart = [ovs_bar("203400")]
    for sec in range(20 * 3600 + 33 * 60, 20 * 3600 + 52 * 60):
        t = f"{sec // 3600:02d}{sec % 3600 // 60:02d}{sec % 60:02d}"
        # 휴장 전엔 손절가 위, 휴장 중엔 손절가를 오가고, 휴장 뒤엔 손절가 위
        fake.last = "0.7470" if in_break(OVERSEAS, t) and sec % 7 < 3 else "0.7500"
        if t == "203800":
            run.request_flatten()
        go(run, clock, t)
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)
    assert fake.order_clocks == ["203104", "205000"]            # 진입, 그리고 휴장이 끝난 첫 가격의 청산 한 번
    assert run.runner.trades[-1]["reason"] == "손절" and run.runner.pos is None


def test_해외_리플레이_기록에도_시장과_통화(tmp_path):
    folder = tmp_path / "strategies"
    folder.mkdir()
    (folder / "fakemku.py").write_text(MKU_SRC, encoding="utf-8")
    loaded = load(folder, "fakemku.py")
    from backend.team_pyrun.runner import Minute
    out = tmp_path / "out"
    replay.replay(loaded, TODAY, [Minute(TODAY, "090000", 0.75, 0.75, 0.75, 0.75, 1)], out, sym=MKU,
                  market=OVERSEAS, fee=2.0)
    assert (read_json(out / "run.json")["currency"], read_json(out / "summary.json")["market"]) == ("USD", "overseas")


# ---------------------------------------------------------------- 고침 1차 (리뷰)
def test_앱_종료_중지는_휴장이어도_미루지_않고_확인_필요로_끝난다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    go(run, clock, "204000")
    run.request_stop(shutdown=True)
    go(run, clock, "204001")
    assert run.state == "끝" and len(fake.orders) == 1                # 정리 주문 없음
    assert "정리 안 함 — 확인 필요: 휴장 중(20:35~20:50)" in run.ended_reason
    assert read_json(out / "run.json")["ended_reason"] == run.ended_reason
    assert "휴장" in read_json(out / "summary.json")["halted"]


def test_stop_all_은_앱_종료_중지를_보낸다(tmp_path):
    reg, fake, clock = make_reg(tmp_path)
    run = reg.get(reg.start(RunSpec("fakemku.py", "orders", None))["id"])
    got: list = []
    real = run.request_stop
    run.request_stop = lambda **kw: (got.append(kw), real(**kw))
    reg.stop_all(timeout=0.1)
    assert got == [{"shutdown": True}] and run._shutdown is True


def test_재시작_정리는_잔고가_0이면_확인_필요를_붙이지_않는다(tmp_path):
    reg, fake, clock = make_reg(tmp_path)
    folder = tmp_path / "pyruns" / f"{TODAY}_fakemku_orders"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"id": folder.name, "name": "fakemku", "sym": MKU, "mode": "orders",
                                                 "state": "진행 중", "started_at": "2026-11-03T09:00:00"}),
                                     encoding="utf-8")
    reg.recover()
    assert read_json(folder / "run.json")["ended_reason"] == "재시작"
    fake.oi_pages = {"": ([{"sym": MKU, "trd_tp": "2", "opint_qty": "1"}], "")}
    (folder / "run.json").write_text(json.dumps({"id": folder.name, "name": "fakemku", "sym": MKU, "mode": "orders",
                                                 "state": "진행 중", "started_at": "2026-11-03T09:00:00"}),
                                     encoding="utf-8")
    reg.recover()
    assert read_json(folder / "run.json")["ended_reason"] == "재시작 · 확인 필요"


class SlowPrice(FakeLive):
    """현재가 조회가 오래 걸려, 돌아올 때 시계가 `after` 로 넘어가 있는 가짜."""

    after: str | None = None

    def ovs_price(self, sym):
        got = super().ovs_price(sym)
        if self.after is not None:
            self.clock["now"] = at(self.after)
        return got


def test_step_은_휴장_전이어도_조회로_늦어져_휴장이면_주문하지_않는다(tmp_path):
    fake = SlowPrice()
    run, fake, out, clock = entered_buy(tmp_path, fake=fake)
    fake.last, fake.after = "0.7470", "203500"                       # 20:34:59 step, 현재가가 20:35:00 에 돌아옴
    go(run, clock, "203459")
    assert len(fake.orders) == 1 and run.runner.break_exit == "손절"   # 휴장으로 보고 판단만
    fake.after = None
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)


def test_끝내기도_지금_시각이_휴장이면_정리하지_않는다(tmp_path):
    class SlowChart(FakeLive):
        slow = False

        def ovs_chart_minute(self, sym, *, req_qty):
            if self.slow:
                self.clock["now"] = at("203500")
            return super().ovs_chart_minute(sym, req_qty=req_qty)

    run, fake, out, clock = entered_buy(tmp_path, fake=SlowChart())
    fake.slow = True
    run.runner.strat.raise_at = "203300"
    fake.chart = [ovs_bar("203300")]
    go(run, clock, "203458")                                         # 전략 오류 — step 시각은 휴장 전, 지금은 휴장
    assert run.state == "오류" and len(fake.orders) == 1 and "휴장" in run.ended_reason


#: 하루 상태에 보유 표지(`in_position`)가 없는 전략 — 앱이 on_entry 로 되살리지 않는다
MKU_NOPOS_SRC = (MKU_SRC.replace("        self.in_position = False\n", "")
                 .replace("or self.day.in_position", "or getattr(self.day, 'in_position', False)")
                 .replace('NAME = "fakemku"', 'NAME = "fakemkun"'))


def test_보유_표지가_없는_전략은_on_entry_로_되살리지_않고_앱이_신호를_버린다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path, start="100030", src=MKU_NOPOS_SRC, file="fakemkun.py",
                                     windows_before=("서울",))
    fake.chart = [ovs_bar("095900")]
    run.prepare()
    assert run.runner.strat.entered == set()                          # on_entry 를 부르지 않았다
    assert any("되살리지 않음" in x for x in texts(out))
    run.runner.strat.script = {"100000": ("서울", "buy")}
    fake.chart = [ovs_bar("100000")]
    go(run, clock, "100104")
    assert fake.orders == [] and any("서울 개장은 오늘 이미 진입함" in x for x in texts(out))


def test_휴장_중_손절_뒤_미룬_중지는_손절로_세진다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    fake.last = "0.7470"
    go(run, clock, "204000")                                          # 휴장 중 손절 판단
    run.request_stop()
    go(run, clock, "204001")
    assert len(fake.orders) == 1
    go(run, clock, "205000")                                          # 미룬 중지 → 정리, 사유는 손절
    assert run.state == "끝" and run.runner.trades[-1]["reason"] == "손절"
    assert run.runner.strat.day.stops == 1 and run.runner.strat.exits[-1][1] is True
    from backend.team_pyrun.journal import count_stops
    assert count_stops([out], TODAY) == 1


def test_휴장_중_정한_청산이_남은_채_끝나면_사유를_기록한다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    fake.last = "0.7470"
    go(run, clock, "204000")
    run.request_stop(shutdown=True)
    go(run, clock, "204001")
    ev = [r for r in journal(out) if r.get("break_exit")]
    assert ev and ev[0]["break_exit"] == "손절"
    assert read_json(out / "summary.json")["break_exit"] == "손절"


def test_휴장_중_끝난_종이_실행은_확인_필요가_아니다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path, mode="paper")
    clock["now"] = at("204500")
    run.finish("중지")
    assert run.state == "끝" and "확인 필요" not in run.ended_reason
    assert "종이 보유 +1 는 마지막 가격으로 정리 안 함" in run.ended_reason
    s = read_json(out / "summary.json")
    assert "halted" not in s and s["trades"] == [] and s["open_paper_position"]["side"] == "buy"
    assert fake.orders == []


def test_리플레이_명령줄은_시장을_csv_종목과_전략_틱으로(tmp_path, monkeypatch):
    folder = tmp_path / "strategies"
    folder.mkdir()
    (folder / "fakemku.py").write_text(MKU_SRC, encoding="utf-8")
    monkeypatch.setattr(replay.storage, "state_dir", lambda env=None: tmp_path / "state")
    seen: list = []
    real = replay.load_minutes
    monkeypatch.setattr(replay, "load_minutes", lambda p, **kw: (seen.append(kw.get("market")), real(p, **kw))[1])
    data = tmp_path / "bars_1m_MKUX26.csv"
    rows = ["ref_dt,exch_tm,open_pric,high_pric,low_pric,close_pric,cum_trd_qty"]
    rows += [f"{TODAY},09{m:02d}00,0.75,0.75,0.75,0.75,1" for m in range(10)]      # 10봉 — 해외는 빼지 않음
    data.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert replay.main([str(folder / "fakemku.py"), TODAY, str(data)]) == 0
    out = tmp_path / "state" / "pyruns" / f"{TODAY}_fakemku_replay"
    run_j = read_json(out / "run.json")
    assert (run_j["sym"], run_j["market"], run_j["currency"]) == (MKU, "overseas", "USD") and seen == [OVERSEAS]
    # 국내 종목 csv 에 MKU 틱 전략 — 시장 가드로 거부
    bad = tmp_path / f"bars_1m_A756B000_{TODAY}.csv"
    bad.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert replay.main([str(folder / "fakemku.py"), TODAY, str(bad)]) == 2


# ---------------------------------------------------------------- 최종 검토 고침 (I2·M1·M2)
def test_미룬_중지가_휴장_뒤_청산되면_주문하지_못했다는_줄이_없다(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path)
    fake.last = "0.7470"
    go(run, clock, "204000")                                          # 휴장 중 손절 판단
    run.request_stop()
    go(run, clock, "204001")
    go(run, clock, "205000")                                          # 미룬 중지 → 정리 주문 체결
    assert run.state == "끝" and [o[1] for o in fake.orders] == ["buy", "sell"]
    assert not any("주문하지 못한 채 끝남" in x for x in texts(out))
    assert "break_exit" not in read_json(out / "summary.json")


def test_미룬_중지의_청산이_안_되어_보유가_남으면_그_줄이_남는다(tmp_path):
    from backend.nh_api.errors import BusinessError
    run, fake, out, clock = entered_buy(tmp_path)
    fake.last = "0.7470"
    go(run, clock, "204000")
    run.request_stop()
    go(run, clock, "204001")
    fake.fill = False
    fake.order_error = BusinessError("overseas_order", "E1", "거부", {})
    go(run, clock, "205000")                                          # 정리 주문이 거부됨 — 보유가 남는다
    assert run.state == "끝" and run.runner.pos is not None
    ev = [r for r in journal(out) if "주문하지 못한 채 끝남" in r.get("text", "")]
    assert ev and ev[0]["break_exit"] == "손절"
    assert read_json(out / "summary.json")["break_exit"] == "손절"


class SlowBalance(FakeLive):
    """잔고 조회가 오래 걸려, 켜 두면(`after`) 돌아올 때 시계가 그 시각으로 넘어가 있는 가짜 — 브로커 관문 안에서."""

    after: str | None = None

    def ovs_open_interest_page(self, nxt_key=""):
        got = super().ovs_open_interest_page(nxt_key)
        if self.after is not None:
            self.clock["now"] = at(self.after)
        return got


def test_청산_판단_뒤_관문_조회로_휴장이_되면_주문하지_않고_휴장_뒤에_청산(tmp_path):
    run, fake, out, clock = entered_buy(tmp_path, fake=SlowBalance())
    go(run, clock, "203440")                                          # 잔고 대조를 미리 — 20:34:58 에는 대조 안 함
    fake.last, fake.after = "0.7470", "203500"
    go(run, clock, "203458")                                          # 손절 판단은 휴장 전, 관문 잔고 조회 뒤엔 휴장
    assert len(fake.orders) == 1 and run.runner.pos is not None
    assert run.runner.break_exit == "손절" and not run.runner.halted
    assert any("주문 보류" in x for x in texts(out))
    b = run.broker
    assert b.blind is None and b.unresolved is None and not b.had_unknown
    fake.after = None
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.trades[-1]["reason"] == "손절"
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)


def test_진입_뒤_관문_조회로_휴장이_되면_신호를_들고_휴장_뒤에_진입(tmp_path):
    fake = SlowBalance()
    run, fake, out, clock = make_ovs(tmp_path, fake=fake)
    run.prepare()
    run.runner.strat.script = {"203300": ("런던", "buy")}
    fake.chart = [ovs_bar("203300")]
    fake.after = "203500"
    go(run, clock, "203404")
    assert fake.orders == [] and run.runner.pending is not None and run.runner.pos is None
    assert not run.runner.halted
    fake.after = None
    go(run, clock, "205000")
    assert [o[1] for o in fake.orders] == ["buy"] and run.runner.pos["entry_time"] == "205000"
    assert not any(in_break(OVERSEAS, c) for c in fake.order_clocks)


def test_registry_가_정한_종목을_prepare_가_다시_고르지_않는다(tmp_path):
    run, fake, out, clock = make_ovs(tmp_path)
    run.sym = "MKUZ26"                                                # registry 가 같은 종목 검사에 쓴 종목
    run.prepare()
    assert run.sym == "MKUZ26" and "mku_master_rows" not in names(fake)
    assert ("ovs_chart_minute", "MKUZ26", live.WARMUP_BARS) in fake.calls
