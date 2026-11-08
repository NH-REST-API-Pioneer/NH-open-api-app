"""1분봉 장중 실행 — 아무 선물 종목(`Leg`)·장 판정 관문(`judge`)·실행 끝 규칙·시작 검사.

가짜 api(해외는 `exch_cd` 를 받음)·가짜 시계·가짜 판정(`judge`)·가짜 거래일 끝(`day_end`)으로만 봅니다.
NH 서버로는 아무것도 나가지 않습니다.
"""
from datetime import datetime

import pytest

from backend.sessions.hours import KST
from backend.team_pyrun import tradeday
from backend.team_pyrun.live import LiveRun, RunPlan, RunSpec, StartRefused, run_plan
from backend.team_pyrun.loader import load
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, paper_fee_of, run_end
from backend.team_spread.legs import Leg
from tests.test_team_pyrun_live import STRATEGY_SRC, FakeApi, at, bar
from tests.test_team_pyrun_live_overseas import MKU_SRC, FakeLive, go, journal, names, ovs_bar, read_json, texts

TODAY = "20261103"
HO = Leg("main", "HOZ26", "HO", "overseas", "FCME", "USD", 0.0001, 4.2, "202612")
MKU_LEG = Leg("main", "MKUX26", "MKU", "overseas", "FSGX", "USD", 0.0001, 2.5, "202611")
KOSPI = Leg("main", "A016C000", "A01", "domestic", "KRX", "KRW", 0.05, 12500.0, "20261210")

#: HO 시험 전략 — MKU 시험 전략에 Params 여섯 칸을 적고 틱 가치를 HO 값으로
HO_SRC = (MKU_SRC.replace("TICK_VALUE = 2.5", "TICK_VALUE = 4.2")
          .replace('NAME = "fakemku"', 'NAME = "fakeho"')
          .replace('    flatten_at: str = "235000"\n',
                   '    session_start: str = "090000"\n'
                   '    session_end: str = "233500"\n'
                   '    entry_start: str = "090000"\n'
                   '    entry_end: str = "230000"\n'
                   '    flatten_at: str = "233000"\n'))

#: 국내 코스피200 시험 전략 — 장 시작 08:45 (모의 주문은 09:00 부터)
KOSPI_SRC = (STRATEGY_SRC.replace("TICK = 0.1", "TICK = 0.05").replace("TICK_VALUE = 1000", "TICK_VALUE = 12500")
             .replace('    session_start: str = "090000"\n', '    session_start: str = "084500"\n')
             .replace('    entry_start: str = "090000"\n', '    entry_start: str = "084500"\n'))


class FakeHO(FakeLive):
    """해외 가짜 — 1분봉·현재가가 `exch_cd` 를 받아 적는다. 잔고·주문내역 줄의 종목은 `sym`."""

    sym = HO.sym

    def ovs_open_interest_page(self, nxt_key=""):
        rows, nxt = super().ovs_open_interest_page(nxt_key)
        return [{**r, "sym": self.sym} for r in rows], nxt

    def ovs_order_history_page(self, nxt_key=""):
        rows, nxt = super().ovs_order_history_page(nxt_key)
        return [{**r, "sym": self.sym} for r in rows], nxt

    def ovs_chart_minute(self, sym, *, req_qty, exch_cd=None):
        self.calls.append(("ovs_chart_minute", sym, req_qty, exch_cd))
        return [dict(r) for r in self.chart]

    def ovs_price(self, sym, exch_cd=None):
        self.calls.append(("ovs_price", sym, exch_cd))
        return {"last_pric": self.last, "sym": sym}


class FakeKospi(FakeApi):
    """국내 가짜 — 잔고 줄의 종목이 코스피200."""

    def open_interest(self):
        rows = super().open_interest()
        return [{**r, "sym": KOSPI.sym} for r in rows]


class FakeJudge:
    """운영자 판정 가짜. `state`·`source` 를 바꿔 가며, `error` 가 있으면 그것을 올린다."""

    def __init__(self, state="open", source="table"):
        self.state, self.source = state, source
        self.error: Exception | None = None
        self.calls: list[tuple] = []

    def __call__(self, market, sym, now):
        self.calls.append((market, sym, now))
        if self.error is not None:
            raise self.error
        return {"state": self.state, "source": self.source,
                "since": "2026-11-03T05:00:00+09:00", "until": "2026-11-03T06:00:00+09:00"}


def write(tmp_path, src, file):
    folder = tmp_path / "strategies"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(src, encoding="utf-8")
    return load(folder, file)


def make_any(tmp_path, *, leg=HO, src=HO_SRC, file="fakeho.py", mode="paper", start="085000", fake=None,
             judge=None, day_end=None, sym=None):
    loaded = write(tmp_path, src, file)
    clock = {"now": at(start)}
    if fake is None:
        fake = FakeKospi() if leg is not None and leg.market == "domestic" else FakeHO(clock)
    fake.clock = clock
    if leg is not None:
        fake.sym = leg.sym
    out = tmp_path / "run"
    run = LiveRun(f"{TODAY}_{loaded.name}_{mode}", out, loaded, RunSpec(file=file, mode=mode, sym=sym),
                  api_module=fake, now=lambda: clock["now"], sleep=lambda s: None,
                  leg=leg, judge=judge, day_end=day_end)
    return run, fake, out, clock


def entered_ho(tmp_path, *, at_bar="100000", **kw):
    """`at_bar` 봉에서 매수 신호 → 다음 분 04초에 진입까지 간 HO 실행."""
    run, fake, out, clock = make_any(tmp_path, **kw)
    run.prepare()
    run.runner.strat.script = {at_bar: ("서울", "buy")}
    fake.chart = [ovs_bar(at_bar)]
    go(run, clock, at_bar[:2] + f"{int(at_bar[2:4]) + 1:02d}04")
    assert run.runner.pos is not None
    return run, fake, out, clock


# ---------------------------------------------------------------- markets: 실행 끝·종이 수수료
def test_run_end_국내는_1531_해외는_정리_5분_뒤():
    assert run_end(DOMESTIC, "153000") == "153100"
    assert run_end(DOMESTIC, "100000") == "153100"
    assert run_end(OVERSEAS, "235000") == "235500"
    assert run_end(OVERSEAS, "235800") == "240300"
    assert run_end(OVERSEAS, "285500") == "290000"


def test_paper_fee_of_는_전략_값이_먼저():
    assert paper_fee_of(OVERSEAS, None) == 2.0
    assert paper_fee_of(DOMESTIC, None) == 690.0
    assert paper_fee_of(OVERSEAS, 15.0) == 15.0
    assert paper_fee_of(OVERSEAS, 0.0) == 0.0          # 0 도 전략이 적은 값


# ---------------------------------------------------------------- run_plan
def test_run_plan_국내_week02_는_그대로(tmp_path):
    plan = run_plan(write(tmp_path, STRATEGY_SRC, "fake.py"), DOMESTIC)
    assert isinstance(plan, RunPlan)
    assert (plan.overnight, plan.end, plan.clock) == (False, "153100", tradeday.RunClock(False))
    assert plan.params_cls().flatten_at == "153000"


def test_run_plan_MKU_는_채운_flatten_에_5분(tmp_path):
    plan = run_plan(write(tmp_path, MKU_SRC, "fakemku.py"), OVERSEAS)
    assert (plan.overnight, plan.end) == (False, "235500")
    p = plan.params_cls()
    assert (p.session_start, p.flatten_at, p.session_end) == ("082500", "235000", "235500")


def test_run_plan_자정_넘는_전략은_시각을_바꾸고_끝도_바꾼_flatten_으로(tmp_path):
    src = (HO_SRC.replace('session_start: str = "090000"', 'session_start: str = "223000"')
           .replace('session_end: str = "233500"', 'session_end: str = "050000"')
           .replace('entry_start: str = "090000"', 'entry_start: str = "223000"')
           .replace('entry_end: str = "230000"', 'entry_end: str = "040000"')
           .replace('flatten_at: str = "233000"', 'flatten_at: str = "045500"'))
    plan = run_plan(write(tmp_path, src, "fakeho.py"), OVERSEAS)
    assert (plan.overnight, plan.end, plan.clock) == (True, "290000", tradeday.RunClock(True))
    p = plan.params_cls()
    assert (p.session_start, p.session_end, p.entry_start, p.entry_end, p.flatten_at) == (
        "223000", "290000", "223000", "280000", "285500")


def test_run_plan_해외_끝이_24시를_넘으면_자정_넘는_실행(tmp_path):
    src = HO_SRC.replace('flatten_at: str = "233000"', 'flatten_at: str = "235800"')
    plan = run_plan(write(tmp_path, src, "fakeho.py"), OVERSEAS)
    assert (plan.overnight, plan.end) == (True, "240300")


def test_run_plan_국내_07시_전_시각은_자정_넘는_실행(tmp_path):
    src = STRATEGY_SRC.replace('flatten_at: str = "153000"', 'flatten_at: str = "045500"')
    plan = run_plan(write(tmp_path, src, "fake.py"), DOMESTIC)
    assert (plan.overnight, plan.end) == (True, "153100")


# ---------------------------------------------------------------- 아무 해외 종목 (HO)
def test_HO_종이_실행은_종목_찾기의_틱을_믿고_exch_cd_로_조회한다(tmp_path):
    run, fake, out, clock = make_any(tmp_path, start="085000")
    run.prepare()
    assert run.sym == "HOZ26" and run.market is OVERSEAS
    # 최근월물 찾기·틱 확인은 하지 않는다 (find_product 가 이미 함)
    assert not {"mku_master_rows", "ovs_product_detail"} & set(names(fake))
    assert ("ovs_chart_minute", "HOZ26", 1500, "FCME") in fake.calls
    fake.chart = [ovs_bar("090000")]
    go(run, clock, "090104")
    assert ("ovs_chart_minute", "HOZ26", 10, "FCME") in fake.calls
    assert ("ovs_price", "HOZ26", "FCME") in fake.calls
    j = read_json(out / "run.json")
    assert (j["product"], j["exchange"], j["currency"], j["market"]) == ("HO", "FCME", "USD", "overseas")
    assert (j["tick"], j["tick_value"], j["overnight"], j["trading_date"], j["end"]) == (
        0.0001, 4.2, False, TODAY, "233500")
    s = run.status()
    assert (s["product"], s["exchange"], s["end"], s["currency"]) == ("HO", "FCME", "233500", "USD")
    assert any("실행 끝 23:35" in x for x in texts(out))


def test_HO_실행은_정리_5분_뒤에_끝난다(tmp_path):
    run, fake, out, clock = entered_ho(tmp_path)
    go(run, clock, "233000")
    assert run.runner.pos is None and run.runner.trades[-1]["reason"] == "장 마감 정리"
    go(run, clock, "233459")
    assert run.state == "진행 중"
    go(run, clock, "233500")
    assert run.state == "끝" and run.ended_reason == "장 끝"
    s = read_json(out / "summary.json")
    assert (s["product"], s["exchange"], s["tick_value"], s["end"], s["overnight"], s["trading_date"]) == (
        "HO", "FCME", 4.2, "233500", False, TODAY)
    # 9틱이 아니라 HO 틱 가치(4.2)로 셈
    t = s["trades"][0]
    assert t["pnl"] == pytest.approx(t["ticks"] * 4.2)


def test_HO_에_MKU_틱_가치_전략이면_조회_전에_거부(tmp_path):
    src = HO_SRC.replace("TICK_VALUE = 4.2", "TICK_VALUE = 2.5")
    for mode in ("paper", "orders"):
        run, fake, out, clock = make_any(tmp_path / mode, src=src, mode=mode)
        with pytest.raises(StartRefused, match="틱·틱가치가 전략 가정과 다릅니다") as e:
            run.prepare()
        assert "4.2" in str(e.value) and "2.5" in str(e.value)
        assert fake.calls == [] and fake.orders == []
        assert read_json(out / "run.json")["state"] == "끝"


def test_HO_에_장_시간_칸이_빠진_전략은_거부(tmp_path):
    src = MKU_SRC.replace("TICK_VALUE = 2.5", "TICK_VALUE = 4.2")
    run, fake, out, clock = make_any(tmp_path, src=src, file="fakemku.py")
    with pytest.raises(StartRefused, match=r"Params 에 장 시간 칸이 없습니다 .*이 품목은 Params 에 적어야 합니다"):
        run.prepare()
    assert fake.calls == []


def test_MKU_다리는_빠진_장_시간_칸을_지금처럼_채운다(tmp_path):
    run, fake, out, clock = make_any(tmp_path, leg=MKU_LEG, src=MKU_SRC, file="fakemku.py", start="082000")
    run.prepare()
    p = run.runner.p
    assert (p.session_start, p.flatten_at, p.session_end) == ("082500", "235000", "235500")
    j = read_json(out / "run.json")
    assert (j["product"], j["exchange"], j["end"]) == ("MKU", "FSGX", "235500")
    assert ("ovs_chart_minute", "MKUX26", 1500, "FSGX") in fake.calls


def test_PAPER_FEE_가_있으면_종이_수수료로(tmp_path):
    src = HO_SRC.replace("TICK = 0.0001", "TICK = 0.0001\nPAPER_FEE = 15.0")
    run, fake, out, clock = entered_ho(tmp_path, src=src)
    assert run.broker.fee == 15.0
    fake.last = "0.7510"
    go(run, clock, "100500")
    run.finish("중지")
    assert run.runner.trades[0]["fee"] == pytest.approx(30.0)      # 체결 두 번 × 15
    assert fake.orders == []


# ---------------------------------------------------------------- 장 판정 관문
def test_판정이_종목을_모르면_시작_거부_조회_주문_없음(tmp_path):
    for mode in ("paper", "orders"):
        judge = FakeJudge(source="unknown", state="closed")
        run, fake, out, clock = make_any(tmp_path / mode, mode=mode, judge=judge)
        with pytest.raises(StartRefused, match="장 시간표에 이 종목이 없습니다"):
            run.prepare()
        assert fake.calls == [] and fake.orders == []
        assert judge.calls and judge.calls[0][:2] == ("overseas", "HOZ26")


def test_판정이_예외면_시작_거부(tmp_path):
    judge = FakeJudge()
    judge.error = RuntimeError("시간표 없음")
    run, fake, out, clock = make_any(tmp_path, mode="orders", judge=judge)
    with pytest.raises(StartRefused, match="장 시간표에 이 종목이 없습니다"):
        run.prepare()
    assert fake.calls == []


def test_판정이_break_인_동안_진입_대기_다시_open_이면_첫_가격에_진입(tmp_path):
    judge = FakeJudge()
    run, fake, out, clock = make_any(tmp_path, mode="orders", judge=judge, start="085000")
    run.prepare()
    run.runner.strat.script = {"100000": ("서울", "buy")}
    fake.chart = [ovs_bar("100000")]
    judge.state = "break"
    go(run, clock, "100104")
    assert run.runner.pending is not None and fake.orders == []
    for t in ("100200", "100500", "101000"):
        go(run, clock, t)
    assert fake.orders == [] and run.runner.pending is not None
    judge.state = "open"
    go(run, clock, "101001")
    assert [o[1] for o in fake.orders] == ["buy"] and run.runner.pos["entry_time"] == "101001"
    assert fake.order_clocks == ["101001"]


def test_판정이_break_면_정리_요청도_미루고_열리면_정리(tmp_path):
    judge = FakeJudge()
    run, fake, out, clock = entered_ho(tmp_path, mode="orders", judge=judge)
    judge.state = "break"
    go(run, clock, "103000")
    run.request_flatten()
    go(run, clock, "103001")
    assert len(fake.orders) == 1 and run.runner.pos is not None
    assert any("정리 요청" in x and "휴장 05:00~06:00" in x for x in texts(out))
    judge.state = "open"
    go(run, clock, "103002")
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.pos is None


def test_판정이_break_인_채_끝나면_정리하지_않고_확인_필요(tmp_path):
    judge = FakeJudge()
    run, fake, out, clock = entered_ho(tmp_path, mode="orders", judge=judge)
    judge.state = "break"
    clock["now"] = at("103000")
    run.finish("중지")
    assert len(fake.orders) == 1
    assert "정리 안 함 — 확인 필요" in run.ended_reason and "휴장 05:00~06:00" in run.ended_reason


def test_실행_중_판정이_예외면_주문_없고_기록은_한_번(tmp_path):
    judge = FakeJudge()
    run, fake, out, clock = make_any(tmp_path, mode="orders", judge=judge)
    run.prepare()
    run.runner.strat.script = {"100000": ("서울", "buy")}
    fake.chart = [ovs_bar("100000")]
    judge.error = RuntimeError("시간표 깨짐")
    for t in ("100104", "100105", "100200", "100300"):
        go(run, clock, t)
    assert fake.orders == [] and run.runner.pending is not None
    assert texts(out).count("장 시간표 모름 — 주문 멈춤") == 1
    judge.error = None
    go(run, clock, "100301")
    assert [o[1] for o in fake.orders] == ["buy"]
    assert texts(out).count("장 시간표 모름 — 주문 멈춤") == 1


def test_보내기_직전_판정이_닫히면_보내지_않는다(tmp_path):
    judge = FakeJudge()
    run, fake, out, clock = make_any(tmp_path, mode="orders", judge=judge)
    run.prepare()
    assert run.broker.may_send is not None
    assert run.broker.may_send() is True
    judge.state = "closed"
    assert run.broker.may_send() is False


# ---------------------------------------------------------------- 거래일 끝 검사 (해외)
def _ends_at(when: datetime, seen: list):
    def day_end(market, sym, now):
        seen.append((market, sym, now))
        return when
    return day_end


def test_거래일_끝이_정리_시각보다_이르면_거부(tmp_path):
    seen: list = []
    end = datetime(2026, 11, 3, 22, 0, tzinfo=KST)
    run, fake, out, clock = make_any(tmp_path, judge=FakeJudge(), day_end=_ends_at(end, seen))
    with pytest.raises(StartRefused, match=r"장이 정리 시각\(23:30\) 전에 닫힙니다") as e:
        run.prepare()
    assert "22:00" in str(e.value)
    assert fake.calls == []
    # 지금 시각이 아니라 전략 장 시작(09:00) 시각으로 묻는다
    assert seen == [("overseas", "HOZ26", datetime(2026, 11, 3, 9, 0, tzinfo=KST))]


def test_MKU_처럼_다음_날_새벽에_끝나면_거부하지_않는다(tmp_path):
    seen: list = []
    end = datetime(2026, 11, 4, 6, 15, tzinfo=KST)
    run, fake, out, clock = make_any(tmp_path / "a", leg=MKU_LEG, src=MKU_SRC, file="fakemku.py",
                                     judge=FakeJudge(), day_end=_ends_at(end, seen), start="082000")
    run.prepare()
    assert run.state == "대기"
    assert seen[0][2] == datetime(2026, 11, 3, 8, 25, tzinfo=KST)
    late: list = []
    run2, fake2, out2, _ = make_any(tmp_path / "b", leg=MKU_LEG, src=MKU_SRC, file="fakemku.py",
                                    judge=FakeJudge(), day_end=_ends_at(datetime(2026, 11, 3, 22, 0, tzinfo=KST), late),
                                    start="082000")
    with pytest.raises(StartRefused, match=r"장이 정리 시각\(23:50\) 전에 닫힙니다"):
        run2.prepare()
    assert fake2.calls == []


def test_다음_날_07시에_끝나는_장도_거부하지_않는다(tmp_path):
    # CME 겨울 — 08:00~다음 날 07:00. 거래일 시계로 "310000" 이라 정리 23:30 보다 늦다
    end = datetime(2026, 11, 4, 7, 0, tzinfo=KST)
    run, fake, out, clock = make_any(tmp_path, judge=FakeJudge(), day_end=_ends_at(end, []))
    run.prepare()
    assert run.state == "대기"


def test_거래일_끝을_모르면_검사를_건너뜀(tmp_path):
    run, fake, out, clock = make_any(tmp_path, judge=FakeJudge(), day_end=lambda m, s, n: None)
    run.prepare()
    assert run.state == "대기"


def test_해외_실행_끝이_다음_날_07시를_넘으면_거부(tmp_path):
    src = (HO_SRC.replace('session_start: str = "090000"', 'session_start: str = "223000"')
           .replace('session_end: str = "233500"', 'session_end: str = "065900"')
           .replace('entry_start: str = "090000"', 'entry_start: str = "223000"')
           .replace('entry_end: str = "230000"', 'entry_end: str = "040000"')
           .replace('flatten_at: str = "233000"', 'flatten_at: str = "065800"'))
    run, fake, out, clock = make_any(tmp_path, src=src, start="222000")
    assert run.plan.end == "310300"
    with pytest.raises(StartRefused, match=r"실행 끝\(07:03 \(\+1\)\)이 다음 날 07:00 을 넘습니다 — flatten_at 을 당기세요"):
        run.prepare()
    assert fake.calls == []


# ---------------------------------------------------------------- 국내 다리
def test_국내_다리에_07시_전_시각_전략은_거부(tmp_path):
    src = KOSPI_SRC.replace('flatten_at: str = "153000"', 'flatten_at: str = "045500"')
    run, fake, out, clock = make_any(tmp_path, leg=KOSPI, src=src, file="fake.py", mode="orders")
    with pytest.raises(StartRefused, match="국내는 주간\\(08:45~15:45\\)만 돕니다 — 07:00 전 시각이 있는 전략은 "
                                           "국내 종목에 걸 수 없습니다"):
        run.prepare()
    assert fake.calls == [] and fake.orders == []


def test_국내_다리는_틱_확인_없이_그_종목으로(tmp_path):
    run, fake, out, clock = make_any(tmp_path, leg=KOSPI, src=KOSPI_SRC, file="fake.py")
    run.prepare()
    assert run.sym == "A016C000" and run.market is DOMESTIC
    assert "domestic_product-detail" not in fake.calls and "domestic_price-all-futures" not in fake.calls
    j = read_json(out / "run.json")
    assert (j["product"], j["exchange"], j["currency"], j["tick"], j["tick_value"], j["end"]) == (
        "A01", "KRX", "KRW", 0.05, 12500.0, "153100")


def test_국내_다리_판정_day_라도_0900_전엔_주문_없음(tmp_path):
    judge = FakeJudge(state="day")
    run, fake, out, clock = make_any(tmp_path, leg=KOSPI, src=KOSPI_SRC, file="fake.py", mode="orders",
                                     judge=judge, start="084000")
    run.prepare()
    b = run.broker
    assert b.may_send is not None                       # 국내도 판정이 있으면 보내기 직전 관문을 꽂는다
    run.runner.strat.script = {"085000": "buy"}
    fake.chart = [bar("085000")]
    go(run, clock, "085104")
    assert run.runner.pending is not None and fake.orders == []
    go(run, clock, "085900")
    run.request_flatten()
    go(run, clock, "085901")
    clock["now"] = at("085959")
    assert b.may_send() is False and run._in_break("085959")
    go(run, clock, "085959")
    assert fake.orders == []
    go(run, clock, "090000")
    assert [o[1] for o in fake.orders] == ["buy"] and run.runner.pos["entry_time"] == "090000"
    run.request_flatten()
    go(run, clock, "090001")
    assert [o[1] for o in fake.orders] == ["buy", "sell"]


def test_국내_다리_판정이_없으면_지금처럼_막지_않는다(tmp_path):
    run, fake, out, clock = make_any(tmp_path, leg=KOSPI, src=KOSPI_SRC, file="fake.py", mode="orders",
                                     start="084000")
    run.prepare()
    assert run.broker.may_send is None and not run._in_break("085000")


# ---------------------------------------------------------------- 다리 없는 실행의 새 칸
def test_다리_없는_국내_실행의_새_칸(tmp_path):
    from tests.test_team_pyrun_live import make_run
    run, fake, out = make_run(tmp_path, mode="paper")
    run.prepare()
    j = read_json(out / "run.json")
    assert (j["product"], j["exchange"], j["currency"], j["tick"], j["tick_value"]) == ("A75", "KRX", "KRW", 0.1, 1000)
    assert (j["overnight"], j["trading_date"], j["end"]) == (False, TODAY, "153100")
    s = run.status()
    assert (s["product"], s["exchange"], s["end"]) == ("A75", "KRX", "153100")
    run.finish("중지")
    summ = read_json(out / "summary.json")
    assert (summ["product"], summ["exchange"], summ["end"], summ["trading_date"]) == ("A75", "KRX", "153100", TODAY)


def test_다리_없는_MKU_실행의_새_칸과_이른_정리(tmp_path):
    from tests.test_team_pyrun_live_overseas import make_ovs
    src = MKU_SRC.replace('flatten_at: str = "235000"', 'flatten_at: str = "220000"')
    run, fake, out, clock = make_ovs(tmp_path, mode="paper", src=src)
    run.prepare()
    j = read_json(out / "run.json")
    assert (j["product"], j["exchange"], j["currency"], j["end"]) == ("MKU", "FSGX", "USD", "220500")
    go(run, clock, "220459")
    assert run.state == "진행 중"
    go(run, clock, "220500")
    assert run.state == "끝" and run.ended_reason == "장 끝"


def test_새_칸은_시작_거부여도_run_json_에(tmp_path):
    src = HO_SRC.replace("TICK_VALUE = 4.2", "TICK_VALUE = 2.5")
    run, fake, out, clock = make_any(tmp_path, src=src)
    with pytest.raises(StartRefused):
        run.prepare()
    j = read_json(out / "run.json")
    assert (j["product"], j["exchange"], j["trading_date"]) == ("HO", "FCME", TODAY)


def test_journal_은_계좌번호를_남기지_않는다(tmp_path):
    run, fake, out, clock = entered_ho(tmp_path, mode="orders", judge=FakeJudge())
    run.finish("중지")
    assert "123456789" not in (out / "journal.jsonl").read_text(encoding="utf-8")
    assert [r for r in journal(out) if r["kind"] == "trade"]
