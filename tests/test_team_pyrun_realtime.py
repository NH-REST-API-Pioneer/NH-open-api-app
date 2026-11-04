"""실시간 실행기(`backend/team_pyrun/realtime.py`) 시험.

가짜 원문 구독(`가짜원문` — 큐에 RawMessage·RawGap 을 넣어 둠), 가짜 해외 api(`FakeLive` — `ovs_*` 이름만 가짐),
손으로 넣는 시계(벽시계·단조 시계)로 돌립니다. 전략은 ws_trader `Engine` 약속을 따르는 작은 손 전략
(`tests/fixtures/team_pyrun/realtime/strategy_rt_fake.py`)입니다. NH 서버로는 아무것도 나가지 않습니다.
"""
from __future__ import annotations

import json
import shutil
from collections import deque
from datetime import timedelta
from pathlib import Path

import pytest

from backend.nh_api.errors import BusinessError, TransportError
from backend.team_pyrun import realtime
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import RunSpec, StartRefused
from backend.team_pyrun.loader import load
from backend.team_pyrun.rawfeed import GAP_ENVIRONMENT, GAP_REFILL, GAP_REJECTED, RawGap, RawMessage
from backend.team_pyrun.realtime import RealtimeRun
from tests.test_team_pyrun_live import STRATEGY_SRC, at
from tests.test_team_pyrun_live_overseas import FakeLive
from tests.test_team_pyrun_rawfeed import hub, loop, 도착  # noqa: F401 — 진짜 RawFeed 시험의 루프·허브 고정물

HERE = Path(__file__).parent
FAKE_FILE = HERE / "fixtures/team_pyrun/realtime/strategy_rt_fake.py"
MKU = "MKUX26"
KRX = "A756B000"
TODAY = "20261103"


# ---------------------------------------------------------------- 가짜들
class 시계:
    """벽시계(한국시간)와 단조 시계를 같이 옮긴다."""

    def __init__(self, hhmmss: str):
        self.wall = at(hhmmss)
        self.mono = 1000.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds

    def to(self, hhmmss: str) -> None:
        self.advance((at(hhmmss) - self.wall).total_seconds())


class 가짜원문:
    """RawFeed 대신. `get` 은 쌓인 것을 차례로 주고, 비면 시계를 `timeout` 만큼 옮기고 None."""

    def __init__(self, clock: 시계, limit: int = 5000):
        self.clock, self.limit = clock, limit
        self.items: deque = deque()
        self.overflow = False
        self.closed = False
        self.wants = None
        self.run_id = None
        self.gets = 0

    def put(self, item) -> None:
        if isinstance(item, RawMessage) and len(self.items) >= self.limit:
            self.overflow = True
            return
        self.items.append(item)

    def get(self, timeout=None):
        self.gets += 1
        if self.closed:
            return None
        if self.items:
            return self.items.popleft()
        self.clock.advance(1.0 if timeout is None else max(timeout, 0.001))
        return None

    @property
    def pending(self) -> int:
        return len(self.items)

    def close(self) -> None:
        self.closed = True


def ka(clock: 시계, price: float, *, tick_div="1", qty="1", exch_tm=None) -> RawMessage:
    body = {"last_pric": f"{price:.2f}", "tick_div": tick_div, "exec_qty": qty,
            "exch_tm": exch_tm or clock.wall.strftime("%H%M%S") + "12"}
    return RawMessage("domestic", "KA", KRX, body, clock.mono)


def fb(clock: 시계, bid: float, ask: float, *, ko=None) -> RawMessage:
    body = {"bid_pric_1": f"{bid:.4f}", "ask_pric_1": f"{ask:.4f}", "ko_exec_tm": ko or clock.wall.strftime("%H%M%S"),
            "exch_tm": "999999", "cust_acnt_no": "123456789"}
    return RawMessage("overseas", "FB", MKU, body, clock.mono)


def fa(clock: 시계, price: float) -> RawMessage:
    body = {"last_pric": f"{price:.4f}", "exec_qty": "1", "ko_exec_tm": clock.wall.strftime("%H%M%S")}
    return RawMessage("overseas", "FA", MKU, body, clock.mono)


def gap(clock: 시계, kind: str, **detail) -> RawGap:
    return RawGap(kind, "", detail, clock.mono)


def make_rt(tmp_path, *, mode="orders", start="085900", src=None, file="strategy_rt_fake.py", sym=MKU,
            signal_sym=KRX, fake=None, env="paper", stops_before=0):
    folder = tmp_path / "strategies"
    folder.mkdir(exist_ok=True)
    if src is None:
        shutil.copy(FAKE_FILE, folder / file)
    else:
        (folder / file).write_text(src, encoding="utf-8")
    loaded = load(folder, file)
    clock = 시계(start)
    feed = 가짜원문(clock)
    fake = fake or FakeLive()
    fake.last = "0.7500"
    made = []

    def factory(run_id, wants):
        feed.run_id, feed.wants = run_id, list(wants)
        made.append(feed)
        return feed

    def sleep(seconds):
        clock.advance(seconds)

    out = tmp_path / "run"
    run = RealtimeRun(f"{TODAY}_rtfake_{mode}", out, loaded,
                      RunSpec(file=file, mode=mode, sym=sym, signal_sym=signal_sym),
                      api_module=fake, feed_factory=factory, now=clock.now, monotonic=clock.monotonic,
                      sleep=sleep, active_env=lambda: env, stops_before=stops_before)
    return run, fake, feed, clock, out


def rows(out, kind=None):
    got = Journal(out / "journal.jsonl").read()
    return [r for r in got if kind is None or r["kind"] == kind]


def texts(out):
    return [r.get("text", "") for r in rows(out)]


def orders_of(fake):
    return [c for c in fake.calls if c[0] == "ovs_market_order"]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def started(tmp_path, **kw):
    """09:00:00 에 준비를 마치고 호가 하나를 넣은 실행."""
    run, fake, feed, clock, out = make_rt(tmp_path, start="090000", **kw)
    run.prepare()
    clock.advance(1)
    run.handle(fb(clock, 0.7499, 0.7501))
    return run, fake, feed, clock, out


def enter_sell(run, clock, *, settle=True):
    """KRX 가 0.6원 올라 MKU 매도 진입 신호가 나게 넣는다. `settle` 이면 바로 뒤 타이머로 Engine 에 체결을 알리게 한다
    (모의 계좌는 확인이 끝난 시각까지 받은 원문을 다 넣은 뒤에 알린다 — 그 뒤 원문·타이머가 와야 알림)."""
    clock.advance(1)
    run.handle(ka(clock, 1400.0))
    clock.advance(1)
    run.handle(ka(clock, 1400.6))
    if settle:
        run.timers()


# ---------------------------------------------------------------- 시작 검사
def test_1분봉_전략은_조회_없이_거부(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, src=STRATEGY_SRC, file="fake.py")
    with pytest.raises(StartRefused, match="1분봉"):
        run.prepare()
    assert fake.calls == []
    assert feed.wants is None
    assert read_json(out / "run.json")["state"] == "끝"


@pytest.mark.parametrize("sym,signal_sym,why", [
    ("A756B000", KRX, "MKU"), (MKU, MKU, "A75"), ("KUX26", KRX, "시장"),
])
def test_종목의_시장이_틀리면_조회_없이_거부(tmp_path, sym, signal_sym, why):
    run, fake, feed, clock, out = make_rt(tmp_path, sym=sym, signal_sym=signal_sym)
    with pytest.raises(StartRefused, match=why):
        run.prepare()
    assert fake.calls == []
    assert feed.wants is None


def test_모의_환경이_아니면_모의_계좌_방식을_거부(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, env="real")
    with pytest.raises(StartRefused, match="모의"):
        run.prepare()
    assert fake.calls == []


def test_종이_방식은_환경과_상관없이_시작하지만_잔고는_보지_않는다(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, mode="paper", env="real")
    run.prepare()
    names = {c[0] for c in fake.calls}
    assert names == {"ovs_product_detail"}


def test_MKU_잔고가_있으면_거부하고_구독하지_않는다(tmp_path):
    fake = FakeLive()
    fake.held = -1
    run, fake, feed, clock, out = make_rt(tmp_path, fake=fake)
    with pytest.raises(StartRefused, match="잔고"):
        run.prepare()
    assert orders_of(fake) == []
    assert feed.wants is None


def test_틱이_다르면_거부(tmp_path):
    fake = FakeLive()
    fake.detail = ("0.00005", "6.25")
    run, fake, feed, clock, out = make_rt(tmp_path, fake=fake)
    with pytest.raises(StartRefused, match="틱"):
        run.prepare()
    assert feed.wants is None


def test_시작하면_KRX_체결과_MKU_호가·체결을_구독하고_run_json_에_실시간(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, start="085900")
    run.prepare()
    assert [(f.context, f.kind, f.sym) for f in feed.wants] == [
        ("domestic-day", "quote", KRX), ("overseas", "book", MKU), ("overseas", "quote", MKU)]
    assert feed.run_id == run.run_id
    data = read_json(out / "run.json")
    assert (data["kind"], data["market"], data["currency"], data["state"]) == ("realtime", "overseas", "USD", "대기")
    assert data["sym"] == MKU and data["signal_sym"] == KRX
    assert run.order_sym == MKU
    assert run.end_at == "154500"       # 전략 flatten_at 15:40 + 5분


def test_종목을_비우면_최근월물로(tmp_path):
    class 국내도(FakeLive):
        def all_futures(self, prd="75"):
            self.calls.append(("all_futures",))
            return [{"sym": KRX}]

        def nearest_usd(self, futures):
            return futures[0]["sym"]

    run, fake, feed, clock, out = make_rt(tmp_path, sym=None, signal_sym=None, fake=국내도())
    run.prepare()
    assert (run.sym, run.signal_sym) == (MKU, KRX)


# ---------------------------------------------------------------- 넣기 규칙
def test_KA_는_틱구분_1·체결수량_있는_것만_FB_는_1단_호가를_받은_순서대로(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    eng = run.engine
    eng.seen.clear()
    m1 = ka(clock, 1400.0, tick_div="0")
    m2 = ka(clock, 1400.1, qty="0")
    m3 = ka(clock, 1400.2, exch_tm="090002345")
    m4 = RawMessage("overseas", "FB", MKU, {"bid_pric_1": "", "ask_pric_1": "0.75"}, clock.mono)
    m5 = fb(clock, 0.7498, 0.7500, ko="090002999")
    m6 = fa(clock, 0.7499)
    for m in (m1, m2, m3, m4, m5, m6):
        run.handle(m)
    assert eng.seen == [("krx", clock.mono, "090002", 1400.2), ("quote", clock.mono, "090002", (0.7498, 0.75))]
    assert (run.krx, run.bid, run.ask) == (1400.2, 0.7498, 0.75)


def test_1초마다_on_timer_를_벽시계_시각과_받은_순서_사이에(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    eng = run.engine
    eng.seen.clear()
    t0 = run._next_timer
    clock.advance(2.5)          # 타이머 두 번이 이 메시지보다 앞선다
    run.handle(ka(clock, 1400.0))
    kinds = [(k, now) for k, now, *_ in eng.seen]
    assert kinds == [("timer", t0), ("timer", t0 + 1), ("krx", clock.mono)]
    hh = [s[2] for s in eng.seen if s[0] == "timer"]
    assert hh == [(clock.wall - timedelta(seconds=clock.mono - t)).strftime("%H%M%S") for t in (t0, t0 + 1)]


# ---------------------------------------------------------------- 모의 계좌 주문
def test_진입_행동이면_주문_한_번과_체결가로_filled_entry(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    fake.last = "0.7500"
    enter_sell(run, clock)
    assert [c[2] for c in orders_of(fake)] == ["sell"]
    assert run.engine.pos["price"] == pytest.approx(0.7499)       # 가짜 체결가 = last - 1틱
    assert run.engine.pending is False
    sig = rows(out, "signal")[-1]
    assert sig["act"] == "enter" and sig["side"] == "sell"
    for k in ("dk", "rho", "spread", "expected", "followed"):
        assert k in sig
    assert sig["dk"] == 0.6
    assert [r["side"] for r in rows(out, "order")] == ["sell"]
    fill = rows(out, "fill")[-1]
    assert fill["source"] == "order-history" and fill["price"] == pytest.approx(0.7499)
    assert run.status()["position"] == -1


def test_진입_결과를_모르면_확인_필요·추가_주문_없음·끝에도_정리_안_함(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    fake.order_error = TransportError("overseas_order", "응답 없음")
    enter_sell(run, clock)
    assert len(orders_of(fake)) == 1
    assert run.halted and "결과 모름" in run.halted
    assert run.engine.pending is True       # 호가로 기록하고 계속하지 않는다
    assert run.engine.pos is None
    run.step(clock.now())
    assert run.state == "확인 필요"
    fake.order_error = None
    for px in (1401.5, 1402.5, 1399.0):     # 더 큰 신호가 와도
        clock.advance(1)
        run.handle(ka(clock, px))
    run.request_stop()
    run.step(clock.now())
    assert len(orders_of(fake)) == 1
    assert run.state == "끝" and "확인 필요" in run.ended_reason
    summary = read_json(out / "summary.json")
    assert summary["halted"] and summary["unresolved_order"]["side"] == "sell"


def test_15초_안에_체결_확인이_안_되면_확인_필요(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    fake.status = "1"       # 접수만, 체결 안 됨
    enter_sell(run, clock)
    assert len(orders_of(fake)) == 1
    assert run.halted
    assert run.engine.pending is True


def test_알려진_거절이면_신호를_건너뛰고_다음_신호는_새로_주문(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    fake.fill = False
    fake.order_error = BusinessError("overseas_order", "E0001", "증거금 부족", {})
    enter_sell(run, clock)
    assert len(orders_of(fake)) == 1
    assert run.halted is None
    assert run.engine.pending is False and run.engine.pos is None
    fake.fill, fake.order_error = True, None
    clock.advance(1)
    run.handle(ka(clock, 1401.2))
    run.timers()
    assert len(orders_of(fake)) == 2
    assert run.engine.pos is not None


def test_청산_행동이면_청산_주문_한_번과_trade_줄(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)          # 매도 0.7499
    fake.last = "0.7505"
    clock.advance(3)
    run.handle(fb(clock, 0.7504, 0.7506))      # 매도 보유 — 청산 쪽 호가 0.7506 → -7틱 → 손절
    run.timers()
    assert [c[2] for c in orders_of(fake)] == ["sell", "buy"]
    assert run.engine.pos is None and run.pos is None
    t = rows(out, "trade")[-1]
    assert t["reason"] == "손절" and t["side"] == "sell"
    assert t["entry"] == pytest.approx(0.7499) and t["exit"] == pytest.approx(0.7506)
    assert t["ticks"] == -7 and t["pnl"] == pytest.approx(-17.5)
    for k in ("gross_ticks", "net_ticks", "net_usd", "held_s", "fee", "exit_date"):
        assert k in t
    assert t["gross_ticks"] == pytest.approx(-7.0) and t["net_usd"] == pytest.approx(-21.5)
    assert t["fee"] == pytest.approx(4.0)       # 가짜 예수금 fee 가 체결마다 2 오름
    assert t["held_s"] == pytest.approx(3.5)      # 진입 체결 확인 뒤 3초 + 청산 확인 0.5초
    sig = [r for r in rows(out, "signal") if r["act"] == "exit"][-1]
    assert sig["reason"] == "손절"


def test_청산이_알려진_거절이면_10초_뒤_같은_사유로_한_번_더(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    fake.fill = False
    fake.order_error = BusinessError("overseas_order", "E0001", "증거금 부족", {})
    clock.advance(1)
    run.handle(fb(clock, 0.7504, 0.7506))
    assert len(orders_of(fake)) == 2 and run.pos is not None and run.halted is None
    for _ in range(5):              # 그 사이 호가·타이머가 와도 다시 주문하지 않는다
        clock.advance(1)
        run.handle(fb(clock, 0.7504, 0.7506))
        run.step(clock.now())
    assert len(orders_of(fake)) == 2
    fake.fill, fake.order_error = True, None
    clock.advance(6)
    run.step(clock.now())
    run.timers()
    assert len(orders_of(fake)) == 3
    assert rows(out, "trade")[-1]["reason"] == "손절"


def test_청산이_3번_거절되면_더_내지_않고_확인_필요(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    fake.fill = False
    fake.order_error = BusinessError("overseas_order", "E0001", "증거금 부족", {})
    clock.advance(1)
    run.handle(fb(clock, 0.7504, 0.7506))      # 1번째
    for _ in range(4):
        clock.advance(11)
        run.step(clock.now())                  # 2·3번째, 그 뒤로는 없음
    assert len(orders_of(fake)) == 1 + 3
    assert run.halted and "3번" in run.halted
    assert any("3번 거절" in t for t in texts(out))
    run.finish("중지")
    assert len(orders_of(fake)) == 4


def test_청산_결과를_모르면_확인_필요·끝에_정리_안_함(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    fake.order_error = TransportError("overseas_order", "응답 없음")
    clock.advance(1)
    run.handle(fb(clock, 0.7504, 0.7506))
    assert len(orders_of(fake)) == 2 and run.halted
    run.finish("중지")
    assert len(orders_of(fake)) == 2
    assert "확인 필요" in run.ended_reason


# ---------------------------------------------------------------- 종이
def test_종이_체결가는_반대_호가·수수료_체결마다_2달러·주문_없음(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    enter_sell(run, clock)          # 매도 → 매수 호가 0.7499
    assert run.engine.pos["price"] == pytest.approx(0.7499)
    clock.advance(2)
    run.handle(fb(clock, 0.7494, 0.7496))       # 매도 보유 — 매도 호가 0.7496 → +3틱 (익절 없음)
    clock.advance(400)              # 보유 시간 300초 → 시간 청산, 그 시각 매도 호가 0.7496
    run.step(clock.now())
    fills = rows(out, "fill")
    assert [(f["source"], f["side"], f["price"], f["fee"]) for f in fills] == [
        ("paper", "sell", 0.7499, 2.0), ("paper", "buy", 0.7496, 2.0)]
    t = rows(out, "trade")[-1]
    assert t["reason"] == "시간" and t["ticks"] == 3 and t["fee"] == pytest.approx(4.0)
    assert t["pnl"] == pytest.approx(7.5) and t["net_usd"] == pytest.approx(3.5)
    assert orders_of(fake) == []
    assert not any(c[0].startswith(("ovs_open_interest", "ovs_order_history", "ovs_deposit")) for c in fake.calls)
    assert "모의계좌" not in " ".join(f.get("text", "") for f in fills)


def test_종이는_전략이_지어낸_기준가가_아니라_반대_호가로_체결(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    real = run.engine.on_krx

    def fake_ref(price, now, hh):
        act = real(price, now, hh)
        if act:
            act["ref"] = 0.9000         # 반대 호가(매수 호가 0.7499)와 다른 값
        return act

    run.engine.on_krx = fake_ref
    enter_sell(run, clock)
    assert rows(out, "fill")[-1]["price"] == 0.7499
    assert run.engine.pos["price"] == 0.7499
    assert any("반대 호가로 체결" in t for t in texts(out))


# ---------------------------------------------------------------- 끝
def test_중지하면_보유를_정리하고_filled_exit_실행_종료_정리(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.request_stop()
    run.step(clock.now())
    assert [c[2] for c in orders_of(fake)] == ["sell", "buy"]
    assert rows(out, "trade")[-1]["reason"] == "실행 종료 정리"
    assert run.engine.pos is None
    assert run.state == "끝" and run.ended_reason == "중지"
    s = read_json(out / "summary.json")
    assert s["kind"] == "realtime" and s["currency"] == "USD" and s["summary"]["trades"] == 1
    assert "backlog_max" in s["messages"]
    assert feed.closed


def test_끝_시각_flatten_at_더하기_5분에_남은_보유를_정리(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.engine._exit = lambda now, hh: None        # 전략이 청산하지 않는 경우
    clock.to("154459")
    run.step(clock.now())
    assert run.state != "끝"
    clock.to("154500")
    run.step(clock.now())
    assert run.state == "끝" and run.ended_reason.startswith("장 끝")
    assert rows(out, "trade")[-1]["reason"] == "실행 종료 정리"
    assert len(orders_of(fake)) == 2


def test_정리_요청은_청산만_하고_계속(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.request_flatten()
    run.step(clock.now())
    run.timers()
    assert rows(out, "trade")[-1]["reason"] == "실행 종료 정리"
    assert run.state == "진행 중" and run.pos is None


def test_앱_종료_중지는_미루지_않는다_휴장_중이면_주문_없이_확인_필요(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.engine._exit = lambda now, hh: None
    clock.to("203600")
    run.request_stop(shutdown=True)
    run.step(clock.now())
    assert run.state == "끝"
    assert len(orders_of(fake)) == 1
    assert "확인 필요" in run.ended_reason and "휴장" in run.ended_reason


def test_휴장_중_진입_신호는_버리고_주문하지_않는다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    run.engine.p.entry_end = "235000"
    clock.to("203600")
    run.handle(fb(clock, 0.7499, 0.7501))
    enter_sell(run, clock)
    assert orders_of(fake) == []
    assert run.engine.pending is False


# ---------------------------------------------------------------- 시세 끊김·공백
def test_KRX_가_끊겨도_MKU_호가와_타이머로_청산은_계속(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    for _ in range(30):             # KRX 는 더 안 옴
        clock.advance(1)
        run.handle(fb(clock, 0.7498, 0.7500))
        run.step(clock.now())
    assert run.halted is None and run.state == "진행 중"
    clock.advance(300)
    run.step(clock.now())           # 타이머로 시간 청산
    run.timers()
    assert rows(out, "trade")[-1]["reason"] == "시간"


def test_쌓임_한도를_넘으면_확인_필요·보유는_정리_안_함(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    feed.overflow = True
    clock.advance(1)
    run.handle(fb(clock, 0.7504, 0.7506))      # 손절 호가지만 판단하지 않는다
    assert run.halted and "쌓임" in run.halted
    run.step(clock.now())
    assert run.state == "확인 필요"
    run.finish("중지")
    assert len(orders_of(fake)) == 1
    assert "확인 필요" in run.ended_reason


def test_보유가_없을_때_쌓임_한도를_넘으면_끝(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    feed.overflow = True
    clock.advance(1)
    run.handle(fb(clock, 0.7499, 0.7501))
    assert run.state == "끝" and run.halted is None
    assert "쌓임 한도" in run.ended_reason and "확인 필요" not in run.ended_reason
    assert not any("보유는 그대로" in t for t in texts(out))
    assert feed.closed


def test_멈췄는데_보유가_없으면_보유를_남겼다고_쓰지_않는다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    fake.order_error = TransportError("overseas_order", "응답 없음")
    enter_sell(run, clock)
    run.finish("중지")
    assert "확인 필요" in run.ended_reason
    assert not any("보유는 그대로" in t for t in texts(out))
    assert any("이 실행이 아는 보유는 없" in t for t in texts(out))


def test_보유_중_환경이_바뀌면_확인_필요(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.handle(gap(clock, GAP_ENVIRONMENT, active="real"))
    assert run.halted and run.state == "확인 필요"
    clock.advance(1)
    run.handle(fb(clock, 0.7504, 0.7506))
    assert len(orders_of(fake)) == 1


@pytest.mark.parametrize("kind", [GAP_ENVIRONMENT, GAP_REJECTED])
def test_보유_없을_때_환경_변경·구독_거절이면_끝(tmp_path, kind):
    run, fake, feed, clock, out = started(tmp_path)
    run.handle(gap(clock, kind, feeds=[]))
    assert run.state == "끝" and run.halted is None
    assert feed.closed


def test_기록용_MKU_체결_구독만_밀리면_계속하고_판단용이면_멈춤(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.handle(gap(clock, GAP_REJECTED, feeds=[{"context": "overseas", "kind": "quote", "sym": MKU}]))
    assert run.halted is None and run.state == "진행 중"
    run.handle(gap(clock, GAP_REJECTED, feeds=[{"context": "overseas", "kind": "quote", "sym": MKU},
                                               {"context": "overseas", "kind": "book", "sym": MKU}]))
    assert run.halted and run.state == "확인 필요"


def test_다시_붙음은_기록만(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    run.handle(gap(clock, GAP_REFILL, detail="재접속"))
    assert run.state == "진행 중" and run.halted is None
    assert any("다시 붙" in t for t in texts(out))


def test_잔고가_실행과_다르면_확인_필요(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    fake.held = 0                   # 누가 계좌에서 정리함
    clock.advance(6)
    run.step(clock.now())
    assert run.halted and "잔고 불일치" in run.halted
    clock.advance(1)
    run.handle(fb(clock, 0.7504, 0.7506))
    assert len(orders_of(fake)) == 1


# ---------------------------------------------------------------- 오류
def test_전략이_예외를_내면_오류로_끝내고_보유는_정리(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)

    def boom(*a):
        raise RuntimeError("전략 고장")

    run.engine.on_quote = boom
    clock.advance(1)
    run.handle(fb(clock, 0.7499, 0.7501))
    assert run.state == "오류"
    assert [c[2] for c in orders_of(fake)] == ["sell", "buy"]
    assert rows(out, "trade")[-1]["reason"] == "실행 종료 정리"


def test_보유가_없는데_청산_행동이면_주문_없이_오류(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    run.engine.on_timer = lambda now, hh: {"act": "exit", "side": 1, "ref": 0.75, "reason": "x", "time": hh}
    clock.advance(2)
    run.step(clock.now())
    assert run.state == "오류"
    assert orders_of(fake) == []


# ---------------------------------------------------------------- 기록
def test_1분마다_minute_줄(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    run.handle(ka(clock, 1400.3, exch_tm="090001"))
    run.handle(fb(clock, 0.7498, 0.7501, ko="090001"))
    clock.to("090100")
    run.step(clock.now())
    clock.advance(1)
    run.step(clock.now())
    got = rows(out, "minute")
    assert len(got) == 1
    m = got[0]
    assert (m["time"], m["krx"], m["mku_mid"], m["spread_ticks"]) == ("090000", 1400.3, 0.74995, 3)
    assert (m["last_krx_at"], m["last_quote_at"]) == ("090001", "090001")


def test_기록에_계좌_식별정보가_없다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock)
    run.request_stop()
    run.step(clock.now())
    for name in ("journal.jsonl", "summary.json", "api_log.jsonl", "run.json"):
        path = out / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert "123456789" not in text and "10.0.0.1" not in text
            assert "cust_acnt_no" not in text and "user_ip_addr" not in text


# ---------------------------------------------------------------- 체결 확인 중 쌓임
def test_체결_확인_15초_동안_온_원문은_쌓였다가_순서대로_들어간다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    fake.status = "1"               # 처음엔 접수만
    arrived = []
    polls = {"n": 0}
    real_sleep = run.sleep

    def sleep_and_arrive(seconds):
        real_sleep(seconds)
        polls["n"] += 1
        for i in range(10):         # 초당 20건 — 실제보다 빠르게
            m = fb(clock, 0.7499, 0.7501 + (0.0001 if i % 2 else 0))
            arrived.append(m.recv_monotonic)
            feed.put(m)
        if polls["n"] == 29:        # 14.5초 뒤 체결
            for r in fake.history:
                r["ord_sts"] = "6"
            fake.held = -1
            fake.fee += 2.0

    run.sleep = sleep_and_arrive
    run.broker.sleep = sleep_and_arrive
    enter_sell(run, clock, settle=False)
    assert run.pos is not None and run.halted is None       # 앱 보유는 바로
    assert run.engine.pos is None and run.engine.pending    # Engine 에는 쌓인 것을 넣은 뒤에 알림
    assert feed.pending == len(arrived) == 290 and not feed.overflow
    run.engine.seen.clear()
    while feed.items:
        run.handle(feed.get(0))
    quotes = [s[1] for s in run.engine.seen if s[0] == "quote"]
    assert quotes == arrived
    times = [s[1] for s in run.engine.seen]
    assert times == sorted(times)   # 타이머도 받은 시각 순서 사이에
    assert len(orders_of(fake)) == 1


def test_체결_확인_동안_쌓인_원문은_ws_trader_처럼_pending_으로_들어가고_그_뒤에_체결을_알린다(tmp_path):
    """ws_trader 는 KRX·MKU·타이머가 따로 도는 작업이라, 한쪽이 주문을 기다리는 동안 다른 쪽 원문은 Engine 이
    `pending`(보유 없음)인 채로 받는다. 그 원문으로는 판단이 나지 않고, `filled_entry` 는 확인이 끝난 시각에 불린다."""
    run, fake, feed, clock, out = started(tmp_path)
    fake.status = "1"
    calls = []
    eng = run.engine
    real_entry = eng.filled_entry
    eng.filled_entry = lambda side, px, now, hh, no="": (calls.append(("filled_entry", now)), real_entry(side, px, now, hh, no))
    polls = {"n": 0}

    def sleep_and_arrive(seconds):
        clock.advance(seconds)
        polls["n"] += 1
        feed.put(fb(clock, 0.7505, 0.7507))     # 매도 보유라면 손절(-8틱)일 호가
        if polls["n"] == 10:
            for r in fake.history:
                r["ord_sts"] = "6"
            fake.held = -1
            fake.fee += 2.0
            clock.advance(0.1)                  # 확인이 끝난 시각은 마지막 원문보다 뒤

    run.broker.sleep = sleep_and_arrive
    enter_sell(run, clock, settle=False)
    done = clock.mono
    eng.seen.clear()
    while feed.items:
        run.handle(feed.get(0))
    assert len(orders_of(fake)) == 1            # 쌓인 손절 호가로는 청산하지 않는다(ws_trader 와 같음)
    assert eng.pos is None and eng.pending       # 아직 확인 끝 시각 뒤의 원문이 없다
    clock.advance(0.5)
    run.handle(fb(clock, 0.7505, 0.7507))        # 확인 뒤 처음 온 호가 — 이제 체결을 알리고 판단
    assert calls == [("filled_entry", done)]
    assert [c[2] for c in orders_of(fake)] == ["sell", "buy"]
    # Engine 이 본 시각은 뒤로 가지 않는다(쌓인 원문 < 체결 알림 ≤ 그 뒤 원문)
    times = [s[1] for s in eng.seen]
    assert times == sorted(times) and max(t for t in times[:-1]) < done <= times[-1]


def test_쌓인_원문이_있으면_step_이_타이머를_앞당기지_않는다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    for _ in range(5):
        clock.advance(1)
        feed.put(fb(clock, 0.7499, 0.7501))
    run.engine.seen.clear()
    run.step(clock.now())           # 실행 스레드가 쌓인 것을 꺼내기 전에 살림 시각이 옴
    while feed.items:
        run.handle(feed.get(0))
    run.timers()
    times = [x[1] for x in run.engine.seen]
    assert times == sorted(times) and len([x for x in run.engine.seen if x[0] == "quote"]) == 5


def test_타이머로만_시간이_가도_체결을_알린다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path)
    enter_sell(run, clock, settle=False)          # 확인 0.5초
    assert run.engine.pos is None
    clock.advance(1)
    run.timers()
    assert run.engine.pos is not None


def test_진짜_RawFeed_로_체결_확인_동안_루프가_받은_원문도_넘치지_않고_순서대로(tmp_path, loop, hub):
    """이벤트 루프 스레드가 원문을 받는 동안 실행 스레드(이 시험 스레드)는 체결 확인에 묶여 있다."""
    import time as _time

    folder = tmp_path / "strategies"
    folder.mkdir()
    shutil.copy(FAKE_FILE, folder / "strategy_rt_fake.py")
    loaded = load(folder, "strategy_rt_fake.py")
    m0 = _time.monotonic()
    wall0 = at("090000")
    fake = FakeLive()
    fake.last = "0.7500"
    fake.status = "1"
    sent: list[float] = []
    polls = {"n": 0}

    def now():
        return wall0 + timedelta(seconds=_time.monotonic() - m0)

    def sleep(seconds):
        # 체결 확인 0.5초마다 — 그동안 허브에 MKU 호가 10건(초당 20건)이 루프에서 들어온다
        polls["n"] += 1
        k0 = len(sent)
        batch = [(("overseas", "FB", MKU), {"bid_pric_1": f"{0.7400 + (k0 + i) * 0.00001:.5f}",
                                             "ask_pric_1": "0.7501", "ko_exec_tm": "090010"}) for i in range(10)]
        도착(loop, hub, batch)
        sent.extend(float(b["bid_pric_1"]) for _, b in batch)
        if polls["n"] == 30:        # 마지막 확인에서 체결
            for r in fake.history:
                r["ord_sts"] = "6"
            fake.held = -1
            fake.fee += 2.0         # 예수금 수수료도 바로 반영(다시 보기 1초 없음)

    out = tmp_path / "run"
    run = RealtimeRun("rt_real_feed", out, loaded, RunSpec("strategy_rt_fake.py", "orders", MKU, signal_sym=KRX),
                      api_module=fake, feed_factory=lambda rid, wants: realtime.RawFeed(rid, wants, hub=hub, loop=loop),
                      now=now, monotonic=_time.monotonic, sleep=sleep, active_env=lambda: "paper")
    run.prepare()
    try:
        도착(loop, hub, [(("overseas", "FB", MKU), {"bid_pric_1": "0.7499", "ask_pric_1": "0.7501", "ko_exec_tm": "090001"}),
                        (("domestic", "KA", KRX), {"last_pric": "1400.00", "tick_div": "1", "exec_qty": "1", "exch_tm": "090001"}),
                        (("domestic", "KA", KRX), {"last_pric": "1400.60", "tick_div": "1", "exec_qty": "1", "exch_tm": "090002"})])
        for _ in range(2):
            run.handle(run.feed.get(timeout=2))
        run.handle(run.feed.get(timeout=2))     # 진입 → 체결 확인 30번(그동안 300건이 쌓인다)
        assert run.pos is not None and run.halted is None
        assert run.feed.pending == 300 and not run.feed.overflow
        run.engine.seen.clear()
        while run.feed.pending:
            run.handle(run.feed.get(timeout=1))
        got = [s[3][0] for s in run.engine.seen if s[0] == "quote"]
        assert len(got) == 300
        assert got == sent          # 루프가 받은 순서 그대로
        times = [s[1] for s in run.engine.seen]
        assert times == sorted(times)
        assert len(orders_of(fake)) == 1
    finally:
        run.finish("중지")
    assert run.feed.closed


# ---------------------------------------------------------------- 실행 스레드 본문
def test_run_forever_는_원문을_비우고_끝_시각에_끝내며_구독을_닫는다(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, mode="paper", start="153955")
    run.prepare()
    clock.advance(0.5)              # 살림 시각과 타이머 시각이 어긋나게 (늦은 step 처럼)
    feed.put(fb(clock, 0.7499, 0.7501))
    run.run_forever()
    assert run.state == "끝" and run.ended_reason.startswith("장 끝")
    assert feed.closed
    assert read_json(out / "summary.json")["kind"] == "realtime"
    assert any(s[0] == "timer" for s in run.engine.seen)
    # 5분 5초를 도는 동안 기다림 없이 도는 바퀴가 없어야 한다(타이머·살림 시각까지 기다림 — 초당 몇 번)
    assert feed.gets < 3 * 310
    timers = [s[1] for s in run.engine.seen if s[0] == "timer"]
    assert len(timers) >= 300 and all(b - a == pytest.approx(1.0) for a, b in zip(timers, timers[1:]))


def test_쌓인_수의_최댓값을_summary_에(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    for _ in range(7):
        feed.put(fb(clock, 0.7499, 0.7501))
    while feed.items:
        run.handle(feed.get(0))
    run.finish("중지")
    assert read_json(out / "summary.json")["messages"]["backlog_max"] == 6   # 하나 꺼낸 뒤 남은 수


def test_구독이_밖에서_닫히면_끝낸다(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, mode="paper", start="090000")
    run.prepare()
    feed.close()
    run.run_forever()
    assert run.state == "끝" and "구독" in run.ended_reason


def test_앞선_실행의_손절_수를_전략에_넣는다(tmp_path):
    run, fake, feed, clock, out = make_rt(tmp_path, mode="paper", stops_before=2)
    run.prepare()
    assert run.engine.stops == 2
    assert run.status()["stops"] == 2


def test_status_는_실시간_칸을_가진다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, mode="paper")
    enter_sell(run, clock)
    s = run.status()
    for k in ("kind", "market", "currency", "krx", "bid", "ask", "last_dk", "last_rho", "held_s", "last_krx_at",
              "position", "entry", "today_pnl", "stops", "max_stops", "halted", "params", "signal_sym"):
        assert k in s
    assert s["kind"] == "realtime" and s["position"] == -1 and s["last_dk"] == 0.6


def test_모듈은_기본_구독_만들기를_가진다():
    assert callable(realtime.default_feed_factory)


# ---------------------------------------------------------------- 최종 검토 고침 (M1) — 보내기 직전 휴장
class 느린잔고(FakeLive):
    """잔고 조회가 오래 걸려, 켜 두면(`jump`) 돌아올 때 시계가 그 시각으로 넘어가 있는 가짜 — 브로커 관문 안에서."""

    def __init__(self):
        super().__init__()
        self.jump = None

    def ovs_open_interest_page(self, nxt_key=""):
        got = super().ovs_open_interest_page(nxt_key)
        if self.jump is not None:
            self.jump()
        return got


def _late_day(run):
    """휴장 근처까지 도는 실행으로 — 진입·끝 시각을 밤으로 늦춘다."""
    run.engine.p.entry_end = "235000"
    run.engine.p.flatten_at = "235000"
    run.end_at = "235500"


def test_진입_판단_뒤_관문_조회로_휴장이_되면_주문하지_않고_신호를_버린다(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, fake=느린잔고())
    _late_day(run)
    clock.to("203456")
    run.handle(fb(clock, 0.7499, 0.7501))
    clock.advance(1)
    run.handle(ka(clock, 1400.0))
    fake.jump = lambda: clock.to("203500")
    clock.advance(1)
    run.handle(ka(clock, 1400.6))                       # 20:34:58 진입 판단 → 관문 잔고 조회 뒤 20:35
    fake.jump = None
    run.timers()
    assert orders_of(fake) == [] and run.halted is None and run.pos is None
    assert run.engine.pending is False
    assert any("주문 보류" in t for t in texts(out))
    b = run.broker
    assert b.blind is None and b.unresolved is None and not b.had_unknown


def test_청산_판단_뒤_관문_조회로_휴장이_되면_휴장이_끝나고_청산(tmp_path):
    run, fake, feed, clock, out = started(tmp_path, fake=느린잔고())
    _late_day(run)
    enter_sell(run, clock)
    run.engine._exit = lambda now, hh: None             # 전략 청산은 끄고 정리 요청으로 청산
    clock.to("203440")
    run.step(clock.now())                               # 잔고 대조를 미리
    assert len(orders_of(fake)) == 1
    run.request_flatten()
    fake.jump = lambda: clock.to("203500")
    clock.to("203458")
    run.step(clock.now())
    fake.jump = None
    assert len(orders_of(fake)) == 1 and run.pos is not None and run.halted is None
    assert any("주문 보류" in t for t in texts(out))
    clock.to("205000")
    run.step(clock.now())
    run.timers()
    assert [c[2] for c in orders_of(fake)] == ["sell", "buy"] and run.pos is None
