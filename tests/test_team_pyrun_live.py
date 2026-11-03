"""모의 계좌 체결(`broker.py`)·장중 실행(`live.py`) 시험.

NH 서버 대신 가짜 `api_module`(함수 이름은 `backend/team_pyrun/api.py` 와 같음)이 정해 둔 줄을 돌려주고,
받은 주문을 적습니다. 가짜 호출도 `apilog.observe` 로 알려서, 운영자 `TradeClient` 처럼 실행별
`api_log.jsonl` 에 「왜 불렀는지」가 남는지 함께 봅니다. 시각은 손으로 넣고, 실제로 쉬지 않습니다.
"""
import json
from datetime import datetime

import pytest

from backend.nh_api.errors import BusinessError, TransportError
from backend.sessions.hours import KST
from backend.team_pyrun import api as real_api
from backend.team_pyrun import apilog
from backend.team_pyrun.broker import MockAccountBroker
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import END_TIME, LiveRun, RunSpec, StartRefused
from backend.team_pyrun.loader import load

SYM = "A756B000"
TODAY = "20261103"

STRATEGY_SRC = '''
"""시험 전략 — `script` 에 적힌 분에 신호를 내거나 예외를 던진다."""
from dataclasses import dataclass

TICK = 0.1
TICK_VALUE = 1000
NAME = "fake"
TITLE = "시험 전략"


@dataclass
class Params:
    bar_min: int = 1
    max_stops_per_day: int = 2
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "090000"
    entry_end: str = "150000"
    flatten_at: str = "153000"
    hold_min: int = 120


@dataclass
class Bar:
    date: str
    start: str
    end: str
    close: float


@dataclass
class Sig:
    bar: Bar
    side: object
    reason: str
    stop_ticks: object = None


class Day:
    def __init__(self):
        self.stops = 0


class Fake:
    def __init__(self, p):
        self.p = p
        self.seen = []
        self.script = {}
        self.day = Day()
        self.date = None
        self.target = None
        self.exits = []

    def on_minute(self, m):
        if m.date != self.date:
            self.date = m.date
            self.day = Day()
        self.seen.append((m.date, m.time))
        act = self.script.get(m.time)
        if act == "raise":
            raise RuntimeError("전략 고장")
        if not (self.p.session_start <= m.time < self.p.session_end):
            return []
        return [Sig(Bar(m.date, m.time, m.time, m.close), act, "시험", 10 if act else None)]

    def end_of_day(self):
        return []

    def on_entry(self):
        pass

    def on_exit(self, pnl, stopped):
        self.exits.append((pnl, stopped))
        self.day.stops += int(stopped)


STRATEGY = Fake
'''


def at(hhmmss: str, date: str = TODAY) -> datetime:
    return datetime(int(date[:4]), int(date[4:6]), int(date[6:]), int(hhmmss[:2]), int(hhmmss[2:4]),
                    int(hhmmss[4:6]), tzinfo=KST)


def bar(time: str, close: float = 1335.0, date: str = TODAY) -> dict:
    return {"ref_dt": date, "exch_tm": time, "open_pric": str(close), "high_pric": str(close),
            "low_pric": str(close), "close_pric": str(close), "cum_trd_qty": "10"}


class FakeApi:
    """`api.py` 와 같은 이름의 함수들. 정해 둔 값을 돌려주고 받은 주문을 적는다.

    `fill` 이 True 면 주문마다 주문내역에 전체체결(6) 줄을 넣고 잔고를 움직이며 예수금 fee 를 690 올린다."""

    rows = staticmethod(real_api.rows)
    num = staticmethod(real_api.num)
    nearest_usd = staticmethod(real_api.nearest_usd)
    usd_spec = staticmethod(real_api.usd_spec)
    net_position = staticmethod(real_api.net_position)

    def __init__(self):
        self.calls: list[str] = []
        self.orders: list[tuple] = []
        self.chart: list[dict] = []
        self.last = "1335.0"
        self.held = 0
        self.fee = 0.0
        self.history: list[dict] = []
        self.fill = True
        self.order_error: Exception | None = None
        self.tick = ("0.1", "1000")
        self.held_seq: list = []      # 있으면 잔고 조회마다 하나씩 꺼내 잔고로 씀 (반영이 늦는 잔고 흉내, 예외면 그 조회 실패)
        self.oi_error: Exception | None = None

    def _seen(self, api_id: str, body=None) -> None:
        self.calls.append(api_id)
        apilog.observe({"api_id": api_id, "env": "paper", "request": {}, "http": 200, "ms": 1.0,
                        "waited_ms": 0, "body": body})

    def count(self, api_id: str) -> int:
        return self.calls.count(api_id)

    def chart_minute(self, sym, *, req_qty):
        self._seen("domestic_chart-minute")
        return [dict(r) for r in self.chart]

    def price(self, sym):
        self._seen("domestic_price", {"last_pric": self.last})
        return {"last_pric": self.last}

    def all_futures(self, prd="75"):
        self._seen("domestic_price-all-futures")
        return [{"sym_exch": SYM, "sym_nm": "미국달러 F 202611", "exp_mon": "26/11"},
                {"sym_exch": "A756C000", "sym_nm": "미국달러 F 202612", "exp_mon": "26/12"}]

    def product_detail(self):
        self._seen("domestic_product-detail")
        return [{"dtl_cd_ko_nm": "미국달러선물(USD)", "cd_val_inf_1": self.tick[0], "tick_val": self.tick[1]}]

    def deposit(self, biz_dt):
        self._seen("domestic_deposit")
        return {"fee": f"{self.fee:018.3f}", "fut_cls_pl_amt": "0", "pl_tot_pric": "0",
                "ord_psb_tot_amt": "100000000", "ac_no": "123456789"}

    def open_interest(self):
        self._seen("domestic_open-interest")
        if self.oi_error is not None:
            raise self.oi_error
        if self.held_seq:
            v = self.held_seq.pop(0)
            if isinstance(v, Exception):      # 이 한 번만 조회 실패
                raise v
            self.held = v
        if not self.held:
            return []
        return [{"sym": SYM, "trd_div": "1" if self.held > 0 else "2", "opint_qty": str(abs(self.held)),
                 "ac_no": "123456789"}]

    def order_history(self):
        self._seen("domestic_order-history")
        return [dict(r) for r in self.history]

    def market_order(self, sym, side, qty=1, exec_cnd="1"):
        self._seen("domestic_order")
        self.orders.append((sym, side, qty, exec_cnd))
        no = f"{len(self.orders):010d}"
        if self.fill:
            self.held += qty if side == "buy" else -qty
            self.fee += 690.0
            px = float(self.last) + (0.1 if side == "buy" else -0.1)
            self.history.insert(0, {"ord_no": no.lstrip("0"), "ord_sts": "6", "ord_sts_nm": "전체체결",
                                    "avg_exec_pric": "00000000000000.000000000",
                                    "exec_pric": f"{px:.1f}", "exec_qty": "1", "exch_exec_tm": "090104000",
                                    "ac_no": "123456789", "user_ip_addr": "10.0.0.1"})
        if self.order_error is not None:
            raise self.order_error
        return {"ord_no": no, "msg_cd": "", "msg_cntn": ""}


def make_run(tmp_path, *, mode="orders", start="085000", stops_before=0, fake=None, sleeps=None):
    folder = tmp_path / "strategies"
    folder.mkdir(exist_ok=True)
    (folder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    loaded = load(folder, "fake.py")
    fake = fake or FakeApi()
    clock = {"now": at(start)}
    out = tmp_path / "run"
    run = LiveRun("20261103_fake_orders", out, loaded, RunSpec(file="fake.py", mode=mode, sym=None),
                  api_module=fake, now=lambda: clock["now"],
                  sleep=(sleeps.append if sleeps is not None else (lambda s: None)), stops_before=stops_before)
    return run, fake, out


def journal(out):
    return Journal(out / "journal.jsonl").read()


def run_json(out):
    return json.loads((out / "run.json").read_text(encoding="utf-8"))


def api_log(out):
    return [json.loads(x) for x in (out / "api_log.jsonl").read_text(encoding="utf-8").splitlines()]


def entered(tmp_path, **kw):
    """09:00 봉에서 매수 신호 → 09:01:04 에 모의 주문·체결까지 간 실행."""
    run, fake, out = make_run(tmp_path, **kw)
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    run.step(at("090104"))
    return run, fake, out


# ---------------------------------------------------------------- 시작 검사
def test_시작_잔고가_있으면_거부한다(tmp_path):
    run, fake, out = make_run(tmp_path)
    fake.held = 1
    with pytest.raises(StartRefused, match=r"A756B000 잔고 \+1계약이 남아 있습니다"):
        run.prepare()
    assert fake.orders == [] and fake.count("domestic_order") == 0
    j = run_json(out)                      # 화면이 까닭을 보일 수 있게 run.json 은 남는다
    assert j["state"] == "끝" and "잔고 +1계약" in j["ended_reason"]
    assert run.state == "끝"
    run.step(at("090104"))                 # 거부된 실행은 아무것도 하지 않는다
    run.finish("중지")
    assert fake.orders == [] and not (out / "summary.json").exists()


def test_시작_잔고를_못_읽으면_거부한다(tmp_path):
    run, fake, out = make_run(tmp_path)

    def boom():
        raise TransportError("domestic_open-interest", "시간 초과")
    fake.open_interest = boom
    with pytest.raises(StartRefused, match="시작 잔고를 확인하지 못했습니다"):
        run.prepare()
    assert fake.orders == []


def test_틱이_다르면_거부한다(tmp_path):
    run, fake, out = make_run(tmp_path)
    fake.tick = ("0.2", "2000")
    with pytest.raises(StartRefused, match="틱·틱가치가 전략 가정과 다릅니다"):
        run.prepare()
    assert fake.orders == [] and fake.count("domestic_open-interest") == 0
    assert run_json(out)["state"] == "끝"


def test_준비_조회가_실패해도_StartRefused_로_알린다(tmp_path):
    run, fake, out = make_run(tmp_path)

    def boom(prd="75"):
        raise TransportError("domestic_price-all-futures", "시간 초과")
    fake.all_futures = boom
    with pytest.raises(StartRefused, match="TransportError"):
        run.prepare()
    assert fake.orders == [] and run_json(out)["state"] == "끝"


def test_준비_기록과_준비_봉(tmp_path):
    run, fake, out = make_run(tmp_path, start="091030", stops_before=1)
    fake.chart = [bar("091000"), bar("090900"), bar("150000", date="20261102"), bar("090800")]
    run.prepare()
    texts = [r["text"] for r in journal(out) if r["kind"] == "event"]
    assert texts[0] == "서버 paper · 주문 모의계좌"
    assert texts[1].startswith(f"전략 fake.py · sha256 {run.loaded.sha256[:12]} · Params ")
    assert any("손절 1회" in t for t in texts)
    # 지금 분(09:10)은 아직 안 닫혔으므로 빼고, 시각순으로
    assert run.runner.strat.seen == [("20261102", "150000"), (TODAY, "090800"), (TODAY, "090900")]
    assert run.runner.live_date == TODAY and run.runner.strat.day.stops == 1
    assert run.sym == SYM and run.state == "진행 중"
    assert [r for r in journal(out) if r["kind"] == "account"]          # 예수금 줄
    assert "ac_no" not in (out / "journal.jsonl").read_text(encoding="utf-8")
    purposes = {r["purpose"] for r in api_log(out)}
    assert {"준비 봉", "잔고확인", "예수금"} <= purposes


# ---------------------------------------------------------------- 장중 반복
def test_장_전엔_기다리고_장중엔_분봉과_현재가를_넣는다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()
    before = list(fake.calls)
    run.step(at("085930"))
    assert run.state == "대기" and fake.calls == before
    assert run_json(out)["state"] == "대기"
    fake.chart = [bar("090000")]
    run.step(at("090104"))
    new = fake.calls[len(before):]
    assert new.count("domestic_chart-minute") == 1 and new.count("domestic_price") == 1
    assert run.state == "진행 중" and run_json(out)["state"] == "진행 중"
    run.step(at("090105"))                 # 같은 분 안에서는 차트를 다시 안 부른다
    new = fake.calls[len(before):]
    assert new.count("domestic_chart-minute") == 1 and new.count("domestic_price") == 2
    assert {"1분봉", "현재가"} <= {r["purpose"] for r in api_log(out)}


def test_분이_바뀌어도_3초_전엔_분봉을_부르지_않는다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()
    n = fake.count("domestic_chart-minute")
    run.step(at("090102"))
    assert fake.count("domestic_chart-minute") == n
    run.step(at("090103"))
    assert fake.count("domestic_chart-minute") == n + 1


def test_1분봉은_새것만_시각순으로_넣는다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()
    fake.chart = [bar("090200"), bar("090000"), bar("090100"), bar("090100"), bar("090300")]
    run.step(at("090305"))
    assert run.runner.strat.seen == [(TODAY, "090000"), (TODAY, "090100"), (TODAY, "090200")]
    run.step(at("090405"))                 # 다음 분: 이미 넣은 봉은 다시 넣지 않는다
    assert run.runner.strat.seen == [(TODAY, "090000"), (TODAY, "090100"), (TODAY, "090200"),
                                     (TODAY, "090300")]


def test_차트_조회가_실패하면_기록하고_다음_초에_다시(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()
    real_chart = fake.chart_minute

    def boom(sym, *, req_qty):
        raise TransportError("domestic_chart-minute", "시간 초과")
    fake.chart_minute = boom
    run.step(at("090104"))
    assert run.state == "진행 중"
    assert any("차트(분) 처리 실패 — 다음 초에 다시" in r.get("text", "") for r in journal(out))
    fake.chart_minute = real_chart
    fake.chart = [bar("090000")]
    run.step(at("090105"))                 # 같은 분이라도 실패했으니 다시 부른다
    assert run.runner.strat.seen == [(TODAY, "090000")]


def test_현재가가_0이면_판단하지_않는다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    fake.last = "0000000000.000"
    run.step(at("090104"))
    assert run.runner.pending is not None             # 신호는 났지만
    assert run.runner.last_price is None and fake.orders == [] and run.runner.pos is None


def test_현재가_조회가_실패해도_계속한다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()

    def boom(sym):
        raise TransportError("domestic_price", "시간 초과")
    fake.price = boom
    run.step(at("090104"))
    assert run.state == "진행 중"
    assert any("현재가 처리 실패 — 다음 초에 다시" in r.get("text", "") for r in journal(out))


# ---------------------------------------------------------------- 모의 주문
def test_신호가_나면_모의_주문을_내고_체결을_확인한다(tmp_path):
    run, fake, out = entered(tmp_path)
    assert fake.orders == [(SYM, "buy", 1, "1")]
    fills = [r for r in journal(out) if r["kind"] == "fill"]
    assert len(fills) == 1 and fills[0]["source"] == "order-history" and fills[0]["price"] == 1335.1
    assert fills[0]["fee"] == 690.0                       # 예수금 fee 차이
    orders = [r for r in journal(out) if r["kind"] == "order"]
    assert orders[0]["ok"] is True and orders[0]["ord_no"] == "0000000001"
    assert run.runner.pos["side"] == "buy" and run.runner.pos["entry"] == 1335.1
    assert run.runner.pos["entry_fee"] == 690.0
    assert run.status()["position"] == 1
    text = (out / "journal.jsonl").read_text(encoding="utf-8") + (out / "api_log.jsonl").read_text(encoding="utf-8")
    assert "123456789" not in text and "10.0.0.1" not in text
    by = {}
    for r in api_log(out):
        by.setdefault(r["api_id"], set()).add(r["purpose"])
    assert by["domestic_order"] == {"진입"} and "체결확인" in by["domestic_order-history"]
    assert "예수금" in by["domestic_deposit"]


def test_주문_응답이_없으면_다시_보내지_않는다(tmp_path):
    fake = FakeApi()
    fake.order_error = TransportError("domestic_order", "시간 초과")   # 주문은 들어갔는데 응답을 못 받음
    run, fake, out = entered(tmp_path, fake=fake)
    assert len(fake.orders) == 1
    order = [r for r in journal(out) if r["kind"] == "order"][0]
    assert order["ok"] is False and order["unknown"] is True
    assert run.runner.pos is not None and run.runner.pos["entry"] == 1335.0   # 현재가로 보유 기록
    assert run.runner.halted is None
    assert run.broker.blind is None              # 잔고 +1 = 그 주문 체결 뒤 보유 → 바로 대조에서 표시가 풀림
    for t in ("090105", "090106", "090200", "090305"):
        run.step(at(t))
    assert len(fake.orders) == 1
    fake.last = "1300.0"                         # 손절은 정상으로 나간다
    run.step(at("090306"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.pos is None


def test_주문_응답이_없고_잔고도_0이면_신호를_버리고_다시_보내지_않는다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    run, fake, out = entered(tmp_path, fake=fake)
    assert len(fake.orders) == 1 and run.runner.pos is None and run.runner.pending is None
    run.step(at("090105"))
    assert len(fake.orders) == 1


def test_주문_뒤_잔고가_반대면_바로_확인_필요(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.held = 0
    fake.order_error = TransportError("domestic_order", "시간 초과")
    run, fake, out = make_run(tmp_path, fake=fake)
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    real_order = fake.market_order

    def order_then_short(*a, **k):
        fake.held = -1                     # 남의 주문이 섞여 계좌는 매도 1
        return real_order(*a, **k)
    fake.market_order = order_then_short
    run.step(at("090104"))
    assert run.runner.halted and "잔고 불일치" in run.runner.halted
    assert run.state == "확인 필요" and run_json(out)["state"] == "확인 필요"
    fake.last = "1300.0"                   # 손절가를 지나도
    run.step(at("090105"))
    assert len(fake.orders) == 1


def test_업무_거부는_알려진_거절로_적는다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = BusinessError("domestic_order", "1234", "주문 가능 수량 부족", {})
    run, fake, out = entered(tmp_path, fake=fake)
    order = [r for r in journal(out) if r["kind"] == "order"][0]
    assert order["ok"] is False and not order.get("unknown")
    assert len(fake.orders) == 1 and run.runner.pos is None


def test_보유_중_잔고가_어긋나면_확인_필요로_멈춘다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.step(at("090110"))                 # 진입 5초 뒤 한 번 대조 (맞음)
    n_oi = fake.count("domestic_open-interest")
    run.step(at("090120"))                 # 그 뒤 30초 안 됨 → 대조 안 함
    assert fake.count("domestic_open-interest") == n_oi
    fake.held = 2                          # 남의 주문이 섞임
    run.step(at("090140"))
    assert run.state == "확인 필요" and run_json(out)["state"] == "확인 필요"
    assert "잔고 불일치" in run.runner.halted and "+2" in run.runner.halted
    assert any("멈춤" in r.get("text", "") for r in journal(out))
    assert any(r["purpose"] == "잔고확인" for r in api_log(out))
    fake.last = "1300.0"                   # 손절가(1334.1)를 지나도
    for t in ("090135", "090136", "090205"):
        run.step(at(t))
    assert len(fake.orders) == 1 and run.state == "확인 필요"


def test_보유_중_잔고가_맞으면_계속한다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.step(at("090134"))
    assert run.state == "진행 중" and run.runner.halted is None


def test_손절가를_지나면_청산_주문을_낸다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.last = "1334.0"                   # 손절 1334.1 아래
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert run.runner.pos is None and run.runner.trades[0]["reason"] == "손절"
    assert any(r["api_id"] == "domestic_order" and r["purpose"] == "청산" for r in api_log(out))


# ---------------------------------------------------------------- 끝내기
def test_전략_예외면_정리하고_오류로_끝난다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.runner.strat.script["090100"] = "raise"
    fake.chart = [bar("090000"), bar("090100")]
    run.step(at("090204"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]       # 보유 청산 주문 1회
    assert run.state == "오류" and run.ended_reason.startswith("오류: RuntimeError: 전략 고장")
    assert run_json(out)["state"] == "오류"
    assert (out / "summary.json").exists()
    run.step(at("090205"))                                        # 끝난 실행은 더 하지 않는다
    run.finish("중지")
    assert len(fake.orders) == 2


def test_끝나면_요약에_API_통계와_전략이_들어간다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.finish("중지")
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["sym"] == SYM and len(s["trades"]) == 1 and s["summary"]["trades"] == 1
    assert s["trades"][0]["reason"] == "실행 종료 정리"
    assert s["api"]["calls"]["domestic_order"] == 2 and s["api"] == run.apilog.stats()
    assert s["strategy"] == {"file": "fake.py", "name": "fake", "title": "시험 전략",
                             "sha256": run.loaded.sha256, "params": run.status()["params"]}
    assert s["account_start"]["fee"] == 0.0 and s["account_end"]["fee"] == 1380.0
    assert "halted" not in s
    j = run_json(out)
    assert j["state"] == "끝" and j["ended_reason"] == "중지" and j["ended_at"]
    assert set(j) >= {"id", "file", "name", "title", "mode", "sym", "state", "started_at", "ended_at",
                      "ended_reason", "sha256"}
    assert j["id"] == "20261103_fake_orders" and j["mode"] == "orders"
    run.finish("다시")                       # 두 번 불려도 한 번만
    assert len(fake.orders) == 2 and run_json(out)["ended_reason"] == "중지"


def test_멈춘_채로_끝나면_정리하지_않고_확인_필요를_남긴다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.held = 2
    run.step(at("090134"))
    assert run.runner.halted
    run.finish("중지")
    assert len(fake.orders) == 1                                  # 정리 주문 없음
    assert run.state == "끝"
    assert "정리 안 함 — 확인 필요" in run.ended_reason and run.ended_reason.startswith("중지")
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert "잔고 불일치" in s["halted"]
    j = run_json(out)
    assert "잔고 불일치" in j["halted"] and "확인 필요" in j["ended_reason"]
    assert any("확인" in r.get("text", "") and "남겨" in r.get("text", "") for r in journal(out))


def test_멈춘_까닭이_잔고와_상관없어도_정리하지_않는다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.runner.halt("진입 체결 여부를 잔고로 확인하지 못함")      # 계좌는 기대(+1)와 같아도
    run.finish("장 끝")
    assert len(fake.orders) == 1 and run.state == "끝"
    assert run.ended_reason == "장 끝 · 정리 안 함 — 확인 필요: 진입 체결 여부를 잔고로 확인하지 못함"


def test_끝낼_때_잔고가_어긋나면_정리하지_않는다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.held = 0                          # 계좌는 이미 0 인데 실행기는 +1 로 안다
    run.finish("중지")
    assert len(fake.orders) == 1 and "확인 필요" in run.ended_reason


def test_장_끝_시각이면_끝낸다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.step(at(END_TIME))
    assert run.state == "끝" and len(fake.orders) == 2 and run.ended_at


def test_중지_요청과_정리_요청(tmp_path):
    run, fake, out = entered(tmp_path)
    run.request_flatten()
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.pos is None
    assert run.state == "진행 중"                                  # 정리 뒤에도 실행은 계속
    run.request_stop()
    run.step(at("090111"))
    assert run.state == "끝" and run.ended_reason == "중지"


def test_종이_실행은_주문도_계좌_조회도_안_한다(tmp_path):
    run, fake, out = make_run(tmp_path, mode="paper")
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    run.step(at("090104"))
    fake.last = "1334.0"
    run.step(at("090140"))
    run.finish("중지")
    banned = {"domestic_order", "domestic_order-history", "domestic_open-interest", "domestic_deposit"}
    assert banned.isdisjoint(fake.calls)
    fills = [r for r in journal(out) if r["kind"] == "fill"]
    assert fills and {f["source"] for f in fills} == {"paper"}
    assert journal(out)[0]["text"] == "서버 paper · 주문 종이"
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["account_start"] is None


def test_run_forever_는_장_끝까지_돌고_정리한다(tmp_path):
    sleeps: list[float] = []
    run, fake, out = make_run(tmp_path, sleeps=sleeps)
    run.prepare()
    times = iter([at("090104"), at("090104"), at("090105"), at("090105"), at(END_TIME), at(END_TIME)])
    run.now = lambda: next(times)
    run.run_forever()
    assert run.state == "끝" and run.ended_reason == "장 끝"
    assert sleeps == [1.0, 1.0]
    assert (out / "summary.json").exists()


def test_run_forever_에서_예상_못한_예외도_끝낸다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.prepare()

    def bad_step(now):
        raise KeyError("버그")
    run.step = bad_step
    run.run_forever()
    assert run.state == "오류" and "KeyError" in run.ended_reason


# ---------------------------------------------------------------- 화면 상태
def test_status_칸(tmp_path):
    run, fake, out = entered(tmp_path)
    s = run.status()
    assert list(s) == ["id", "file", "name", "title", "mode", "sym", "state", "started_at", "ended_at",
                       "ended_reason", "bar_min", "next_decision_at", "position", "entry", "stop",
                       "stop_ticks", "target", "time_exit_at", "today_pnl", "stops", "max_stops", "halted",
                       "last_signal", "params", "market", "currency"]
    assert (s["market"], s["currency"]) == ("domestic", "KRW")
    assert (s["id"], s["mode"], s["sym"], s["state"], s["bar_min"]) == (
        "20261103_fake_orders", "orders", SYM, "진행 중", 1)
    assert s["next_decision_at"] == "090200"               # 09:00 봉 다음 판정 봉은 09:01 시작 → 09:02 마감
    assert s["started_at"] == "2026-11-03T08:50:00" and s["params"]["bar_min"] == 1


def test_다음_판정_시각은_판정_봉_마감에_맞춘다(tmp_path):
    run, fake, out = make_run(tmp_path)
    run.runner.strat.p.bar_min = 5
    assert run.status()["next_decision_at"] is None        # 아직 넣은 봉 없음
    run.prepare()
    fake.chart = [bar("090000"), bar("090100"), bar("090200")]
    run.step(at("090305"))
    assert run.status()["next_decision_at"] == "090500"
    fake.chart = [bar("090300"), bar("090400")]
    run.step(at("090505"))
    assert run.status()["next_decision_at"] == "091000"


def test_앞선_손절은_오늘_첫_봉에서_전략이_하루를_새로_시작해도_이어진다(tmp_path):
    run, fake, out = make_run(tmp_path, start="084000", stops_before=2)
    fake.chart = [bar("153000", date="20261102")]           # 장 전에 켜서 준비 봉은 어제 것뿐
    run.prepare()
    assert run.runner.strat.day.stops == 2
    fake.chart = [bar("153000", date="20261102"), bar("084500")]
    run.step(at("090005"))                                   # 오늘 첫 봉에서 전략이 Day() 를 새로 만든다
    assert run.runner.strat.day.stops == 2


# ---------------------------------------------------------------- MockAccountBroker 단독
def test_브로커_체결_확인은_0점5초씩_최대_30번(tmp_path):
    fake = FakeApi()
    fake.fill = False                       # 주문은 받았지만 주문내역에 안 나타남
    sleeps: list[float] = []
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=sleeps.append, today=TODAY)
    assert b.mode == "mock-account"
    assert b.fill("buy", 1335.0, "090104", "진입 (buy)") is None
    assert sleeps == [0.5] * 30 and fake.count("domestic_order-history") == 30
    assert len(fake.orders) == 1 and b.unknown is True
    rows = Journal(tmp_path / "j.jsonl").read()
    assert any("15초 안에 전체체결 확인 안 됨" in r.get("text", "") for r in rows)


def test_브로커_거부_상태는_None(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.history = [{"ord_no": "1", "ord_sts": "8", "ord_sts_nm": "거부", "ord_rejt_rsn": "증거금 부족",
                     "ac_no": "123456789"}]
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None, today=TODAY)
    assert b.fill("buy", 1335.0, "090104", "진입 (buy)") is None
    assert b.unknown is False
    assert "123456789" not in (tmp_path / "j.jsonl").read_text(encoding="utf-8")


def test_브로커_position_실패는_None(tmp_path):
    fake = FakeApi()

    def boom():
        raise TransportError("domestic_open-interest", "시간 초과")
    fake.open_interest = boom
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None, today=TODAY)
    assert b.position() is None
    fake2 = FakeApi()
    fake2.held = -2
    assert MockAccountBroker(fake2, SYM, Journal(tmp_path / "k.jsonl"), today=TODAY).position() == -2


def test_브로커_avg_exec_pric_가_있으면_그걸_쓴다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.history = [{"ord_no": "1", "ord_sts": "6", "avg_exec_pric": "1335.25", "exec_pric": "1335.1"}]
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None, today=TODAY)
    assert b.fill("buy", 1335.0, "090104", "진입 (buy)") == 1335.25


def _hooked(fake, tmp_path, expected=0):
    """실행처럼 기대 보유·멈춤 갈고리를 꽂은 브로커와, 멈춤 까닭 목록."""
    halts: list[str] = []
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None, today=TODAY,
                          expected=lambda: expected, halt=halts.append)
    return b, halts


def test_브로커는_결과를_모르는_주문이_주문내역에_없으면_멈춘다(tmp_path):
    fake = FakeApi()
    fake.fill = False                       # 접수됐지만 주문내역에 안 나타남 (첫 쪽에 없을 수도)
    b, halts = _hooked(fake, tmp_path)
    assert b.fill("sell", 1335.0, "100000", "청산 · 손절") is None
    assert b.unresolved == "0000000001"
    assert b.fill("sell", 1335.0, "100010", "청산 · 손절") is None      # 10초 뒤 재시도 자리
    assert len(fake.orders) == 1 and b.unknown is True and b.needs_check is True
    assert len(halts) == 1 and "찾지 못함" in halts[0]                   # 손절이 조용히 막히지 않게 멈춤


def test_브로커는_결과_없는_주문을_두_번까지_기다리고_세_번째엔_멈춘다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    b, halts = _hooked(fake, tmp_path)
    b.fill("sell", 1335.0, "100000", "청산 · 손절")
    fake.history = [{"ord_no": "1", "ord_sts": "1", "ord_sts_nm": "접수"}]      # 아직 결과 없음
    for i, t in enumerate(("100010", "100020")):
        assert b.fill("sell", 1335.0, t, "청산 · 손절") is None and halts == [], i
    assert b.fill("sell", 1335.0, "100030", "청산 · 손절") is None
    assert len(fake.orders) == 1 and len(halts) == 1 and "3번" in halts[0]


def test_브로커는_앞선_주문이_늦게_체결됐어도_잔고가_그_주문_체결_뒤_보유이고_기대와_같으면_주문을_낸다(tmp_path):
    # 수정 4회차: 방향이 달라도 그 주문의 pre·post 로 판단한다. 진입 매수(pre 0 → post 1)가 15초 안에 확인 안 됐지만
    # 잔고 +1 을 보고 실행기가 보유로 받아들인(기대 +1) 뒤의 청산 매도 — 잔고 = post = 기대 → 보냄
    fake = FakeApi()
    fake.fill = False
    exp = {"v": 0}
    halts: list[str] = []
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None, today=TODAY,
                          expected=lambda: exp["v"], halt=halts.append)
    assert b.fill("buy", 1335.0, "100000", "진입 (buy)") is None
    assert (b.unresolved, b.unresolved_pre, b.unresolved_post) == ("0000000001", 0, 1)
    fake.held = 1                            # 늦게 체결된 진입이 잔고에 보임
    exp["v"] = 1                             # 실행기가 잔고 +1 을 보고 보유로 받아들임
    fake.history = [{"ord_no": "1", "ord_sts": "6", "exec_pric": "1335.0"}]
    fake.fill = True
    assert b.fill("sell", 1335.0, "100010", "청산 · 손절") == 1334.9
    assert len(fake.orders) == 2 and b.unresolved is None and b.blind is None and halts == []
    assert any("앞선 buy 주문 체결이 잔고(+1)에 반영됨" in r.get("text", "")
               for r in Journal(tmp_path / "j.jsonl").read())


def test_브로커는_앞선_주문이_늦게_체결돼_잔고가_달라졌으면_주문하지_않는다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    b, halts = _hooked(fake, tmp_path, expected=1)
    fake.held = 1
    b.fill("sell", 1335.0, "100000", "청산 · 손절")
    fake.history = [{"ord_no": "1", "ord_sts": "6", "exec_pric": "1335.0"}]
    fake.held = 0                            # 그 청산이 늦게 체결돼 계좌는 0
    assert b.fill("sell", 1335.0, "100010", "청산 · 손절") is None
    assert len(fake.orders) == 1


def test_브로커_잔고_관문_기대와_다르거나_못_읽으면_보내지_않는다(tmp_path):
    fake = FakeApi()
    b, halts = _hooked(fake, tmp_path, expected=0)
    fake.held = 1                            # 진입 전인데 계좌에 +1 (앞선 주문이 늦게 들어옴)
    assert b.fill("buy", 1335.0, "100000", "진입 (buy)") is None
    assert fake.orders == [] and b.needs_check is True and b.unknown is True
    fake.held = 0
    fake.oi_error = TransportError("domestic_open-interest", "시간 초과")
    assert b.fill("buy", 1335.0, "100100", "진입 (buy)") is None
    assert fake.orders == []
    fake.oi_error = None
    assert b.fill("buy", 1335.0, "100200", "진입 (buy)") == 1335.1
    assert len(fake.orders) == 1


def test_브로커는_앞선_주문이_거부로_확인되면_새_주문을_낸다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    b = MockAccountBroker(fake, SYM, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None, today=TODAY)
    b.fill("sell", 1335.0, "100000", "청산 · 손절")
    fake.history = [{"ord_no": "1", "ord_sts": "9", "ord_sts_nm": "취소"}]
    b.fill("sell", 1335.0, "100010", "청산 · 손절")
    assert len(fake.orders) == 2 and b.unresolved == "0000000002"


def test_청산이_15초_안에_확인_안_되면_재시도해도_겹쳐_주문하지_않는다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.fill = False                       # 청산 주문은 접수됐지만 결과를 모름, 잔고는 그대로 +1
    fake.last = "1334.0"
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.retry_after == "090120"
    run.step(at("090120"))                  # 10초 뒤 재시도 자리 — 앞선 주문이 주문내역에 없으니 멈춤
    run.step(at("090131"))
    assert len(fake.orders) == 2 and run.runner.pos is not None
    assert "찾지 못함" in run.runner.halted and run.state == "확인 필요"


# ---------------------------------------------------------------- 수정 1회차: 결과를 모르는 주문 뒤 겹쳐 주문하지 않기
def _exit_unknown(tmp_path):
    """09:01:10 손절 청산 주문이 응답 없음(TransportError) — 실제로는 접수됐지만 잔고 반영이 늦어 +1 로 읽힘."""
    run, fake, out = entered(tmp_path)
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    fake.last = "1334.0"
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.retry_after == "090120"
    assert run.runner.pos is not None and run.runner.halted is None
    fake.order_error = None
    return run, fake, out


def test_청산_응답이_없고_잔고가_늦게_0이_되면_재시도에서_주문없이_청산으로_기록한다(tmp_path):
    run, fake, out = _exit_unknown(tmp_path)
    fake.held = 0                           # 앞선 청산이 이제 잔고에 반영됨
    run.step(at("090115"))
    run.step(at("090120"))                  # 재시도 자리: 잔고 관문이 0 을 보고 보내지 않음
    assert len(fake.orders) == 2
    assert run.runner.pos is None and len(run.runner.trades) == 1 and run.runner.trades[0]["exit"] == 1334.0
    assert run.runner.halted is None and run.state == "진행 중"
    assert run.broker.blind is None                                  # 들어간 것이 확인돼 표시가 풀림
    run.step(at("090200"))
    assert len(fake.orders) == 2
    run.runner.strat.script["090200"] = "sell"                       # 표시가 풀렸으니 새 신호는 주문된다
    fake.chart = [bar("090200")]
    fake.last = "1335.0"
    run.step(at("090304"))
    assert [o[1] for o in fake.orders] == ["buy", "sell", "sell"]


def test_청산_재시도_대기_중_계좌가_0으로_읽혀도_멈추지_않고_재시도에서_기록한다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    fake.last = "1334.0"
    # 090110: 대조(5초 뒤) +1 · 관문 +1 · 주문 뒤 실행기 확인 +1 · 바로 대조 0(이제 반영됨)
    fake.held_seq = [1, 1, 1, 0]
    run.step(at("090110"))
    assert run.runner.halted is None and run.runner.pos is not None
    fake.order_error = None
    run.step(at("090120"))
    assert len(fake.orders) == 2 and run.runner.pos is None and run.runner.halted is None


def test_청산_재시도_대기_중_정리_요청도_새_주문을_내지_않고_확인_필요(tmp_path):
    run, fake, out = _exit_unknown(tmp_path)  # 잔고는 아직 +1 로 읽힘
    run.request_flatten()
    run.step(at("090112"))
    assert len(fake.orders) == 2 and run.runner.pos is not None
    assert run.runner.halted and "결과를 모르는 sell 주문 뒤 잔고가 그대로" in run.runner.halted
    assert run.state == "확인 필요"
    fake.held = 0
    run.step(at("090122"))
    assert len(fake.orders) == 2


def test_진입_응답이_없어_신호를_버린_뒤_늦게_체결되면_새_진입을_내지_않는다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    run, fake, out = entered(tmp_path, fake=fake)
    assert len(fake.orders) == 1 and run.runner.pos is None           # 잔고 0 → 신호 버림
    fake.order_error = None
    fake.fill = True
    fake.held = 1                                                     # 앞선 진입이 늦게 체결됨
    run.runner.strat.script["090100"] = "buy"
    fake.chart = [bar("090000"), bar("090100")]
    run.step(at("090204"))                                            # 새 진입 신호
    assert len(fake.orders) == 1
    assert run.runner.halted and "잔고 불일치" in run.runner.halted and run.state == "확인 필요"


def test_업무_거부로_주문이_None_이어도_바로_잔고를_대조한다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = BusinessError("domestic_order", "1234", "주문 가능 수량 부족", {})
    run, fake, out = make_run(tmp_path, fake=fake)
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    fake.held_seq = [0, 0, -1]               # 관문 0 · 실행기 확인 0 · 바로 대조 -1 (남의 주문)
    run.step(at("090104"))
    assert run.runner.halted and "-1" in run.runner.halted and len(fake.orders) == 1


def test_보유가_바뀌면_5초_뒤_한_번_대조한다_청산으로_0이_된_때도(tmp_path):
    run, fake, out = entered(tmp_path)
    n = fake.count("domestic_open-interest")
    run.step(at("090108"))
    assert fake.count("domestic_open-interest") == n
    run.step(at("090109"))
    assert fake.count("domestic_open-interest") == n + 1
    fake.last = "1334.0"
    run.step(at("090150"))                   # 손절 청산 → 기대 0
    assert run.runner.pos is None
    fake.held = 1                            # 계좌엔 아직(또는 남의 주문으로) +1
    fake.last = "1335.0"
    run.step(at("090154"))
    assert run.runner.halted is None
    run.step(at("090155"))                   # 0 이 되고 5초 뒤 대조
    assert run.runner.halted and "기대 +0" in run.runner.halted and "+1" in run.runner.halted


def test_끝_잔고가_기대와_다르면_확인_필요로_남긴다(tmp_path):
    run, fake, out = entered(tmp_path)
    real = fake.market_order

    def flatten_then_someone_buys(*a, **k):
        res = real(*a, **k)
        fake.held = 1                        # 정리는 체결됐지만 계좌엔 +1 이 남음
        return res
    fake.market_order = flatten_then_someone_buys
    run.finish("중지")
    assert len(fake.orders) == 2 and run.state == "끝"
    assert run.ended_reason == "중지 · 정리 안 함 — 확인 필요: 끝 잔고 불일치 · 기대 +0 · 계좌 +1"
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert "끝 잔고 불일치" in s["halted"] and "끝 잔고 불일치" in run_json(out)["halted"]


def test_끝_잔고를_못_읽으면_확인_필요로_남긴다(tmp_path):
    run, fake, out = entered(tmp_path)
    real = fake.market_order

    def flatten_then_balance_fails(*a, **k):
        res = real(*a, **k)
        fake.oi_error = TransportError("domestic_open-interest", "시간 초과")
        return res
    fake.market_order = flatten_then_balance_fails
    run.finish("장 끝")
    assert len(fake.orders) == 2
    assert "확인 필요: 끝 잔고 불일치" in run.ended_reason and "확인 안 됨" in run.ended_reason


# ---------------------------------------------------------------- 수정 2회차: 결과를 모르는 주문은 증거가 있을 때까지 막는다 (R19·R20)
def test_청산_응답이_없고_잔고가_계속_그대로면_재시도하지_않고_확인_필요(tmp_path):
    run, fake, out = _exit_unknown(tmp_path)  # 잔고 +1 이 재시도 때까지 그대로
    assert run.broker.blind == {"side": "sell", "pre": 1, "post": 0}
    for t in ("090115", "090120", "090130", "090200"):
        run.step(at(t))
    assert len(fake.orders) == 2                                     # 더 보낸 주문 없음
    assert run.state == "확인 필요" and "잔고가 그대로(+1)" in run.runner.halted
    run.finish("중지")
    assert len(fake.orders) == 2 and "확인 필요" in run.ended_reason


def test_진입_응답이_없고_잔고가_0인데_새_신호가_나면_주문하지_않고_확인_필요(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    run, fake, out = entered(tmp_path, fake=fake)
    assert len(fake.orders) == 1 and run.runner.pos is None and run.broker.blind["post"] == 1
    fake.order_error = None
    fake.fill = True
    run.runner.strat.script["090100"] = "buy"
    fake.chart = [bar("090000"), bar("090100")]
    run.step(at("090204"))                                            # 잔고는 여전히 0
    assert len(fake.orders) == 1
    assert run.state == "확인 필요" and "잔고가 그대로(+0)" in run.runner.halted


def test_청산이_15초_안에_확인_안_되고_주문내역은_체결인데_잔고가_그대로면_멈춘다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.fill = False                       # 청산 매도는 접수, 15초 안에 주문내역에 안 나타남
    fake.last = "1334.0"
    run.step(at("090110"))
    assert run.broker.unresolved == "0000000002" and run.broker.unresolved_side == "sell"
    fake.history = [{"ord_no": "2", "ord_sts": "6", "exec_pric": "1334.0"}]   # 그 매도가 체결됨, 잔고는 +1 그대로
    run.step(at("090120"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]           # 두 번째 매도 없음
    assert run.state == "확인 필요" and "주문내역은 sell 주문" in run.runner.halted


def test_브로커_같은_방향_앞선_주문이_체결됐으면_잔고가_그대로여도_보내지_않고_멈춘다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    b, halts = _hooked(fake, tmp_path, expected=1)
    fake.held = 1
    b.fill("sell", 1335.0, "100000", "청산 · 손절")
    fake.history = [{"ord_no": "1", "ord_sts": "6", "exec_pric": "1335.0"}]
    assert b.fill("sell", 1335.0, "100010", "청산 · 손절") is None
    assert len(fake.orders) == 1 and len(halts) == 1 and "주문내역은 sell" in halts[0]


def test_브로커_번호_없는_결과_모름_주문은_잔고_증거가_올_때까지_모든_주문을_막는다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    b, halts = _hooked(fake, tmp_path, expected=0)
    assert b.fill("buy", 1335.0, "100000", "진입 (buy)") is None
    assert b.blind == {"side": "buy", "pre": 0, "post": 1}
    fake.order_error = None
    fake.held = 0
    assert b.fill("buy", 1335.0, "100100", "진입 (buy)") is None    # 잔고 그대로 → 멈춤, 주문 없음
    assert len(fake.orders) == 1 and len(halts) == 1
    fake.oi_error = TransportError("domestic_open-interest", "시간 초과")
    assert b.fill("buy", 1335.0, "100200", "진입 (buy)") is None    # 못 읽음 → 주문 없음
    assert len(fake.orders) == 1 and b.blind is not None
    fake.oi_error = None
    fake.held = 1                                                    # 이제 체결 뒤 보유가 보임 → 표시 풀림
    assert b.fill("buy", 1335.0, "100300", "진입 (buy)") is None    # 지금 주문은 잔고 관문(+1 ≠ 0)이 막음
    assert b.blind is None and len(fake.orders) == 1


def test_응답_없는_주문이_번호_없이_응답만_와도_표시한다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    b, halts = _hooked(fake, tmp_path, expected=0)
    fake.market_order = lambda *a, **k: (fake.orders.append(a), {"ord_no": "", "msg_cd": "X"})[1]
    assert b.fill("buy", 1335.0, "100000", "진입 (buy)") is None
    assert b.blind == {"side": "buy", "pre": 0, "post": 1}


def test_알려진_거절_뒤_청산_재시도_대기_중_계좌가_0이면_불일치로_멈춘다(tmp_path):
    run, fake, out = entered(tmp_path)
    fake.fill = False
    fake.order_error = BusinessError("domestic_order", "1234", "거부", {})
    fake.last = "1334.0"
    # 090110: 대조(5초 뒤) +1 · 관문 +1 · 거절 뒤 실행기 확인 +1 · 바로 대조 0 (이 실행이 낸 체결이 아님)
    fake.held_seq = [1, 1, 1, 0]
    run.step(at("090110"))
    assert run.broker.blind is None and len(fake.orders) == 2
    assert run.runner.halted and "잔고 불일치" in run.runner.halted and run.runner.trades == []


# ---------------------------------------------------------------- 수정 3회차: 가격 없는 체결·같은 방향 늦은 체결·끝에 남은 결과 모름 주문
def test_전체체결인데_체결가가_비면_기준가로_청산을_기록하고_재시도하지_않는다(tmp_path):
    run, fake, out = entered(tmp_path)
    real = fake.market_order

    def filled_without_price(*a, **k):
        res = real(*a, **k)
        fake.history[0].update(avg_exec_pric="00000000000000.000000000", exec_pric="")
        fake.held = 1                        # 체결됐지만 잔고 반영이 늦음
        return res
    fake.market_order = filled_without_price
    fake.last = "1334.0"
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert run.runner.pos is None and run.runner.retry_after == ""
    t = run.runner.trades[0]
    assert (t["exit"], t["reason"]) == (1334.0, "손절")
    fill = [r for r in journal(out) if r["kind"] == "fill"][-1]
    assert fill["price"] == 1334.0 and fill["price_read"] is False
    assert any("체결가를 읽지 못함 — 기준가 1334.0" in r.get("text", "") for r in journal(out))
    run.step(at("090111"))
    fake.held = 0
    for x in ("090120", "090121", "090130"):
        run.step(at(x))
    assert len(fake.orders) == 2 and run.runner.halted is None


def test_같은_방향_앞선_주문_체결이_이미_잔고에_있으면_멈추지_않고_새_주문을_낸다(tmp_path):
    run, fake, out = entered(tmp_path)
    real = fake.market_order

    def accepted_not_in_history(*a, **k):
        fake.fill = False
        res = real(*a, **k)
        fake.held = 0                        # 청산 매도는 들어가 잔고 0, 주문내역엔 아직 없음
        return res
    fake.market_order = accepted_not_in_history
    fake.last = "1334.0"
    run.step(at("090110"))
    assert run.broker.unresolved == "0000000002" and run.runner.pos is None   # 잔고 0 → 청산으로 기록
    assert (run.broker.unresolved_pre, run.broker.unresolved_post) == (1, 0)
    fake.market_order = real
    fake.fill = True
    fake.history = [{"ord_no": "2", "ord_sts": "6", "exec_pric": "1334.0"}]   # 이제 그 매도가 체결로 보임
    run.runner.strat.script["090100"] = "sell"                                # 같은 방향(매도) 진입 신호
    fake.chart = [bar("090000"), bar("090100")]
    fake.last = "1335.0"
    run.step(at("090204"))
    assert run.runner.halted is None
    assert [o[1] for o in fake.orders] == ["buy", "sell", "sell"] and run.runner.pos["side"] == "sell"
    assert run.broker.unresolved is None


def test_끝날_때_번호_없는_결과_모름_주문이_남아_있으면_요약에_보인다(tmp_path):
    fake = FakeApi()
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    run, fake, out = entered(tmp_path, fake=fake)      # 잔고 0 그대로, 더 주문할 일 없음
    run.finish("장 끝")
    assert run.state == "끝" and run.ended_reason == "장 끝"           # 잔고는 맞으니 멈추지 않는다
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["unresolved_order"] == {"side": "buy", "pre": 0, "post": 1} and "halted" not in s
    assert any("결과를 모르는 주문이 남아 있음" in r.get("text", "") for r in journal(out))


def test_끝날_때_번호_있는_결과_모름_주문이_남아_있으면_요약에_보인다(tmp_path):
    fake = FakeApi()
    fake.fill = False                                    # 접수됐지만 15초 안에 결과 없음, 잔고 0
    run, fake, out = entered(tmp_path, fake=fake)
    assert run.runner.pos is None
    run.finish("중지")
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["unresolved_order"] == {"ord_no": "0000000001", "side": "buy", "pre": 0, "post": 1}
    assert run.state == "끝"


def test_끝날_때_결과_모름_주문이_없으면_요약에_칸이_없다(tmp_path):
    run, fake, out = entered(tmp_path)
    run.finish("중지")
    assert "unresolved_order" not in json.loads((out / "summary.json").read_text(encoding="utf-8"))


def test_전체체결인데_체결가가_비고_잔고가_10초_넘게_늦어도_두_번째_매도는_없다(tmp_path):
    run, fake, out = entered(tmp_path)
    real = fake.market_order

    def filled_without_price(*a, **k):
        res = real(*a, **k)
        fake.history[0].update(avg_exec_pric="0", exec_pric="0")
        fake.held = 1                        # 잔고 반영이 재시도 시각(+10초)을 넘겨 늦음
        return res
    fake.market_order = filled_without_price
    fake.last = "1334.0"
    for x in ("090110", "090115", "090120", "090121", "090130"):
        run.step(at(x))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]           # 같은 청산을 두 번 내지 않는다
    assert len(run.runner.trades) == 1


# ---------------------------------------------------------------- 수정 4회차: 체결(6)로 보인 결과 모름 주문은 방향과 상관없이 pre·post 로만
def test_같은_방향_체결인데_잔고를_못_읽고_계속_그대로면_두_번째_매도는_없다(tmp_path):
    """A: 손절 매도 #2 가 15초 안에 확인 안 됨(pre +1 → post 0). 재시도 자리에서 주문내역은 #2 체결인데
    그때 잔고 조회가 한 번 실패하고, 그 뒤 잔고는 두 재시도 자리를 넘겨 +1 로 늦는다."""
    run, fake, out = entered(tmp_path)
    fake.fill = False
    fake.last = "1334.0"
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and run.runner.retry_after == "090120"
    assert (run.broker.unresolved, run.broker.unresolved_pre, run.broker.unresolved_post) == ("0000000002", 1, 0)
    fake.history = [{"ord_no": "2", "ord_sts": "6", "exec_pric": "1334.0"}]
    fake.fill = True                         # 두 번째 매도가 나가면 체결돼 보이게
    real_hist = fake.order_history
    failed = {"done": False}

    def hist_then_balance_fails_once():
        rows = real_hist()
        if not failed["done"]:
            failed["done"] = True
            fake.held_seq = [TransportError("domestic_open-interest", "시간 초과")]   # 바로 다음 잔고 조회만 실패
        return rows
    fake.order_history = hist_then_balance_fails_once
    run.step(at("090120"))                   # 주문내역 6 · 잔고 못 읽음 → 막고 표시는 남김
    assert len(fake.orders) == 2 and failed["done"]
    for x in ("090121", "090130", "090131", "090140", "090150"):
        run.step(at(x))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]           # 같은 청산을 두 번 내지 않는다
    assert run.runner.halted and run.state == "확인 필요"
    assert run.broker.blind == {"side": "sell", "pre": 1, "post": 0, "ord_no": "0000000002"}   # 표시는 남아 있음
    run.finish("중지")
    assert len(fake.orders) == 2
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["unresolved_order"]["ord_no"] == "0000000002"


def test_다른_방향_앞선_매수가_체결로_보여도_잔고가_그_전_그대로면_매도하지_않고_멈춘다(tmp_path):
    """B: 진입 매수 #1 이 15초 안에 확인 안 됨, 그때 잔고 0 → 신호 건너뜀(기대 0 = pre). 대조가 +1 을 보기 전에
    매도 신호 — 주문내역은 #1 체결, 잔고는 아직 0. 실행기가 모르는 매수 체결이 있으니 매도를 보내면 안 된다."""
    fake = FakeApi()
    fake.fill = False
    run, fake, out = entered(tmp_path, fake=fake)
    assert len(fake.orders) == 1 and run.runner.pos is None
    assert (run.broker.unresolved, run.broker.unresolved_pre, run.broker.unresolved_post) == ("0000000001", 0, 1)
    fake.history = [{"ord_no": "1", "ord_sts": "6", "exec_pric": "1335.1"}]
    fake.fill = True
    run.runner.strat.script["090100"] = "sell"
    fake.chart = [bar("090000"), bar("090100")]
    run.step(at("090204"))
    assert [o[1] for o in fake.orders] == ["buy"]                    # 매도 없음
    assert run.state == "확인 필요" and "주문내역은 buy 주문 0000000001 체결" in run.runner.halted


def test_브로커_다른_방향_체결인데_잔고를_못_읽으면_체결_뒤_보유가_보일_때까지_막는다(tmp_path):
    """B 의 잔고 못 읽음 갈래: 표시를 버리지 않고 blind 로 바꿔 계속 막는다."""
    fake = FakeApi()
    fake.fill = False
    b, halts = _hooked(fake, tmp_path, expected=0)
    b.fill("buy", 1335.0, "100000", "진입 (buy)")
    fake.history = [{"ord_no": "1", "ord_sts": "6", "exec_pric": "1335.1"}]
    fake.fill = True
    fake.held_seq = [TransportError("domestic_open-interest", "시간 초과")]
    assert b.fill("sell", 1335.0, "100010", "진입 (sell)") is None
    assert len(fake.orders) == 1 and halts == []
    fake.oi_error = TransportError("domestic_open-interest", "시간 초과")
    assert b.fill("sell", 1335.0, "100020", "진입 (sell)") is None   # 또 못 읽음 → 막음
    assert len(fake.orders) == 1 and halts == []
    fake.oi_error = None
    fake.held = 0
    assert b.fill("sell", 1335.0, "100030", "진입 (sell)") is None   # 잔고 그대로(= 기대) → 멈춤
    assert len(fake.orders) == 1 and len(halts) == 1
    assert b.unresolved is None and b.blind == {"side": "buy", "pre": 0, "post": 1, "ord_no": "0000000001"}


def test_다른_방향_앞선_매수_체결이_잔고에_보이지만_실행기가_모르면_관문이_막고_대조가_멈춘다(tmp_path):
    """잔고 = 그 주문 체결 뒤 보유(+1) 면 표시는 풀리지만, 실행기 기대(0)와 다르니 잔고 관문이 막고 대조가 멈춘다."""
    fake = FakeApi()
    fake.fill = False
    run, fake, out = entered(tmp_path, fake=fake)
    fake.history = [{"ord_no": "1", "ord_sts": "6", "exec_pric": "1335.1"}]
    fake.fill = True
    run.runner.strat.script["090100"] = "sell"
    fake.chart = [bar("090000"), bar("090100")]
    fake.held_seq = [0, 1]                   # 30초 대조는 아직 0, 주문 직전엔 +1 이 보임
    run.step(at("090204"))
    assert [o[1] for o in fake.orders] == ["buy"]                    # 매도 없음
    assert run.broker.unresolved is None and run.broker.blind is None
    assert run.state == "확인 필요" and "잔고 불일치" in run.runner.halted


# ---------------------------------------------------------------- 최종 리뷰 수정: 이 실행이 열지 않은 포지션은 받아들이지 않는다
def _buy_signal_run(tmp_path, fake=None):
    """준비를 마치고 09:00 봉 매수 신호를 기다리는 실행(아직 주문 없음)."""
    run, fake, out = make_run(tmp_path, fake=fake)
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    return run, fake, out


def test_남의_매수_잔고가_있을_때_매수_신호면_주문도_인수도_없이_확인_필요(tmp_path):
    """평평한 실행(기대 0)인데 계좌에 남의 +1 — 잔고 관문이 막아 주문이 안 나갔으니 그 +1 은 이 실행의 것이 아니다."""
    run, fake, out = _buy_signal_run(tmp_path)
    run.step(at("090010"))
    fake.held = 1                               # 사용자가 일반주문 화면에서 1계약 매수
    run.step(at("090104"))                      # 매수 신호 → 진입 시도
    assert fake.orders == []
    assert run.runner.pos is None and run.runner.trades == []
    assert run.runner.halted == "잔고 불일치 · 기대 +0 · 계좌 +1"
    assert run.state == "확인 필요" and run_json(out)["state"] == "확인 필요"
    for t in ("090110", "090140", "090210"):
        run.step(at(t))
    fake.last = "1300.0"                        # 남의 포지션 기준 손절가를 지나도
    run.step(at("090211"))
    run.finish("중지")
    assert fake.orders == [] and run.runner.trades == []


def test_남의_반대_잔고가_있을_때_매수_신호면_주문도_인수도_없이_확인_필요(tmp_path):
    run, fake, out = _buy_signal_run(tmp_path)
    fake.held = -1                              # 남의 매도 1 (평평한 실행은 대조하지 않으니 주문 직전 관문이 처음 본다)
    run.step(at("090104"))
    assert fake.orders == [] and run.runner.pos is None
    assert run.runner.halted == "잔고 불일치 · 기대 +0 · 계좌 -1"


def test_응답_없는_매수_뒤_계좌가_반대면_실행기가_보유로_적지_않고_멈춘다(tmp_path):
    """주문은 나갔지만(결과 모름) 계좌가 −1 — 이 매수로는 될 수 없는 잔고다. 매수 보유로 적으면 안 된다."""
    fake = FakeApi()
    fake.fill = False
    fake.order_error = TransportError("domestic_order", "시간 초과")
    run, fake, out = _buy_signal_run(tmp_path, fake=fake)
    real_order = fake.market_order

    def order_then_short(*a, **k):
        fake.held = -1
        return real_order(*a, **k)
    fake.market_order = order_then_short
    run.step(at("090104"))
    assert len(fake.orders) == 1
    assert run.runner.pos is None and run.runner.trades == []
    assert run.runner.halted == "잔고 불일치 · 기대 +0 · 계좌 -1"
    run.finish("중지")
    assert len(fake.orders) == 1


def test_알려진_거절_청산_뒤_계좌가_0이면_청산으로_적지_않고_멈춘다(tmp_path):
    """업무 거부(접수 안 됨이 확인된 것) 뒤 계좌 0 — 이 실행의 청산이 아니다. 기준가로 거래를 지어내지 않는다."""
    run, fake, out = entered(tmp_path)
    fake.fill = False
    fake.order_error = BusinessError("domestic_order", "1234", "거부", {})
    fake.last = "1334.0"
    fake.held_seq = [1, 1, 0]                   # 5초 대조 +1 · 관문 +1 · 거절 뒤 실행기 확인 0
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert run.runner.trades == [] and run.runner.pos is not None
    assert run.runner.halted == "잔고 불일치 · 기대 +1 · 계좌 +0"
    assert not [r for r in journal(out) if r["kind"] == "trade"]


def test_주문_없이_막힌_청산에서_계좌가_0이면_청산으로_적지_않고_멈춘다(tmp_path):
    """남이 이 실행의 보유를 닫음: 관문이 0 을 보고 주문을 안 냈고, 결과 모름 주문도 없다."""
    run, fake, out = entered(tmp_path)
    fake.last = "1334.0"
    fake.held_seq = [1, 0, 0]                   # 5초 대조 +1 · 관문 0 · 실행기 확인 0
    run.step(at("090110"))
    assert [o[1] for o in fake.orders] == ["buy"]
    assert run.runner.trades == [] and run.runner.halted == "잔고 불일치 · 기대 +1 · 계좌 +0"


def test_종이_실행에서_on_exit_가_예외면_거래는_하나뿐이고_두_번_닫지_않는다(tmp_path):
    """청산을 적은 뒤 전략의 on_exit 가 고장 나도 보유는 이미 비어 있어야 한다 — 끝내기 정리가 또 닫아 거래를 지어내지 않게."""
    run, fake, out = make_run(tmp_path, mode="paper")
    run.prepare()
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    run.step(at("090104"))
    assert run.runner.pos is not None

    def boom(pnl, stopped):
        raise RuntimeError("on_exit 고장")
    run.runner.strat.on_exit = boom
    fake.last = "1300.0"                        # 손절
    run.step(at("090105"))
    assert run.state == "오류" and "on_exit 고장" in run.ended_reason
    assert [t["reason"] for t in run.runner.trades] == ["손절"]
    assert [r["reason"] for r in journal(out) if r["kind"] == "trade"] == ["손절"]
    assert run.runner.pos is None


def test_국내_실행은_Params_시간_칸이_없으면_시작_거부(tmp_path):
    src = (STRATEGY_SRC.replace('    session_start: str = "090000"\n', "")
           .replace('    entry_end: str = "150000"\n', ""))
    src = src.replace("self.p.session_start <= m.time < self.p.session_end", "True")
    folder = tmp_path / "strategies"
    folder.mkdir()
    (folder / "short.py").write_text(src, encoding="utf-8")
    loaded = load(folder, "short.py")
    assert loaded.params_missing == ("session_start", "entry_end")
    fake = FakeApi()
    out = tmp_path / "run"
    run = LiveRun("20261103_fake_orders", out, loaded, RunSpec(file="short.py", mode="orders", sym=None),
                  api_module=fake, now=lambda: at("085000"), sleep=lambda s: None)
    with pytest.raises(StartRefused, match=r"Params 에 장 시간 칸이 없습니다 \(session_start, entry_end\)"):
        run.prepare()
    assert fake.calls == [] and fake.orders == []          # 조회도 주문도 하지 않고 거부
    j = run_json(out)
    assert j["state"] == "끝" and j["ended_reason"].startswith("시작 거부: Params 에 장 시간 칸이 없습니다")
    run.step(at("090104"))
    assert fake.orders == []


def test_실시간_전략은_1분봉_실행으로_시작하지_않는다(tmp_path):
    folder = tmp_path / "strategies"
    folder.mkdir()
    (folder / "engine.py").write_text('''
from dataclasses import dataclass

@dataclass
class LiveParams:
    flatten_at: str = "154000"

class Engine:
    def __init__(self, p: LiveParams):
        self.p = p
    def on_krx(self, price, now, hhmmss): return None
    def on_quote(self, bid, ask, now, hhmmss): return None
    def on_timer(self, now, hhmmss): return None
    def filled_entry(self, side, price, now, hhmmss, ord_no=""): pass
    def filled_exit(self, price, now, reason): return {}
''', encoding="utf-8")
    loaded = load(folder, "engine.py")
    fake = FakeApi()
    run = LiveRun("20261103_engine_orders", tmp_path / "run", loaded, RunSpec(file="engine.py", mode="paper", sym=None),
                  api_module=fake, now=lambda: at("085000"), sleep=lambda s: None)
    with pytest.raises(StartRefused, match="실시간 전략"):
        run.prepare()
    assert fake.calls == []
