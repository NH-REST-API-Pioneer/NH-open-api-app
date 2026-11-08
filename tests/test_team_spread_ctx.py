"""ctx — 한도·멈춤·장 쉼·짝 되돌리기 (가짜 Feed·Book)."""
import threading
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from backend.team_spread.bars import Minute
from backend.team_spread.ctx import Ctx, Fill, Halted, OrderRejected
from backend.team_spread.feed import Quote
from backend.team_spread.legs import Leg


def mk(name, market="overseas"):
    return Leg(name, name + "Z26", name, market, "FCME", "USD", 0.0001, 4.2, "202612")


A, B = mk("a"), mk("b")


class FakeFeed:
    def __init__(self):
        self.t = datetime(2026, 11, 9, 10, 0, 0)
        self.open = {"a": True, "b": True}
        self.waits = []

    def history(self, legs, count):
        return [Minute("20261109", "1000", {})]

    def next_minute(self, legs, stop):
        self.waits.append(("next", [x.name for x in legs], stop))
        return None

    def quote(self, leg):
        return Quote(1.0, 0.9, 1.1, self.t)

    def is_open(self, leg, now):
        return self.open[leg.name]

    def now(self):
        return self.t

    def sleep(self, seconds, stop):
        self.waits.append(("sleep", seconds, stop))


class FakeBook:
    def __init__(self):
        self.pos = {"a": 0, "b": 0}
        self.orders = []
        self.halted = None
        self.script = {}     # (leg, nth call) -> exception 또는 돌려줄 Fill

    def halt(self, reason):
        self.halted = self.halted or reason

    def position(self, leg):
        return self.pos[leg.name]

    def order(self, leg, qty, why):
        self.orders.append((leg.name, qty, why))
        exc = self.script.get((leg.name, len([o for o in self.orders if o[0] == leg.name])))
        if isinstance(exc, Fill):
            self.pos[leg.name] += exc.qty
            return exc
        if exc is not None:
            if isinstance(exc, Halted):
                self.halted = "결과 모름"
            raise exc
        self.pos[leg.name] += qty
        return Fill(leg.name, qty, 1.0, 0.5)


class Jr:
    def __init__(self):
        self.rows = []

    def write(self, kind, **data):
        self.rows.append((kind, data))


def make(max_qty=None, per_min=10, inherited=None, roll=None, book=None, **kw):
    feed, book, jr, stop = FakeFeed(), book or FakeBook(), Jr(), threading.Event()
    ctx = Ctx({"a": A, "b": B}, feed, book, jr, max_qty=max_qty or {"a": 5, "b": 5},
              orders_per_min=per_min, inherited=inherited, stop=stop,
              roll=roll or (lambda n: replace(mk(n), sym=n + "Z27")), **kw)
    return ctx, feed, book, jr, stop


def test_order_passes_to_book_by_name_or_leg():
    ctx, _, book, _, _ = make()
    ctx.order("a", 2)
    ctx.order(B, -1)
    assert book.orders == [("a", 2, "order"), ("b", -1, "order")]


def test_zero_qty_does_nothing_even_when_stopped():
    ctx, _, book, _, stop = make()
    stop.set()
    assert ctx.order("a", 0) is None
    assert book.orders == []


def test_halted_book_raises_halted():
    ctx, _, book, _, _ = make()
    book.halted = "결과 모름"
    with pytest.raises(Halted):
        ctx.order("a", 1)
    assert book.orders == [] and not ctx.running()


def test_review2_stopped_runner_ignoring_running_gets_no_orders():
    ctx, _, book, _, stop = make()
    stop.set()
    assert not ctx.running()
    for call in (lambda: ctx.order("a", 1), lambda: ctx.target({"a": 1, "b": -1})):
        with pytest.raises(OrderRejected, match="중지됨") as ei:
            call()
        assert not isinstance(ei.value, Halted)
    assert book.orders == [] and book.halted is None


def test_closed_market_rejected():
    ctx, feed, book, _, _ = make()
    feed.open["a"] = False
    with pytest.raises(OrderRejected, match="장 쉼"):
        ctx.order("a", 1)
    assert book.orders == [] and ctx.market_open("a") is False and ctx.market_open(B) is True


def test_max_qty_uses_holding_plus_qty():
    ctx, _, book, _, _ = make(max_qty={"a": 3, "b": 3})
    ctx.order("a", 3)
    with pytest.raises(OrderRejected):
        ctx.order("a", 1)
    ctx.order("a", -6)      # 3 -> -3 허용
    with pytest.raises(OrderRejected):
        ctx.order("a", -1)
    assert len(book.orders) == 2


def test_rate_cap_counts_attempts_in_last_60s():
    ctx, feed, book, _, _ = make(per_min=2)
    ctx.order("a", 1)
    ctx.order("a", 1)
    with pytest.raises(OrderRejected, match="분당"):
        ctx.order("a", 1)
    feed.t += timedelta(seconds=61)
    ctx.order("a", 1)
    assert len(book.orders) == 3


def test_rate_cap_counts_rejected_attempts_by_book():
    ctx, _, book, _, _ = make(per_min=2)
    book.script = {("a", 1): OrderRejected("거부"), ("a", 2): OrderRejected("거부")}
    for _ in range(2):
        with pytest.raises(OrderRejected):
            ctx.order("a", 1)
    with pytest.raises(OrderRejected, match="분당"):
        ctx.order("a", 1)
    assert len(book.orders) == 2


def test_target_sends_diffs_in_written_order():
    ctx, _, book, _, _ = make()
    book.pos["a"] = 1
    fills = ctx.target({"b": -2, "a": 1})
    assert book.orders == [("b", -2, "target")] and len(fills) == 1


def test_review3_target_one_leg_closed_sends_nothing():
    ctx, feed, book, _, _ = make()
    feed.open["b"] = False
    with pytest.raises(OrderRejected, match="장 쉼"):
        ctx.target({"a": 1, "b": -1})
    assert book.orders == []


def test_target_precheck_limits_and_rate():
    ctx, _, book, _, _ = make(max_qty={"a": 5, "b": 1})
    with pytest.raises(OrderRejected):
        ctx.target({"a": 1, "b": -2})
    assert book.orders == []
    ctx2, _, book2, _, _ = make(per_min=1)
    with pytest.raises(OrderRejected, match="분당"):
        ctx2.target({"a": 1, "b": -1})
    assert book2.orders == []


def test_target_second_leg_rejected_reverts_first_once():
    ctx, _, book, _, _ = make()
    book.script = {("b", 1): OrderRejected("거부")}
    with pytest.raises(OrderRejected):
        ctx.target({"a": 2, "b": -2})
    assert book.orders == [("a", 2, "target"), ("b", -2, "target"), ("a", -2, "revert")]
    assert book.pos == {"a": 0, "b": 0} and ctx.running()


def test_revert_not_blocked_by_rate_or_max():
    ctx, _, book, _, _ = make(max_qty={"a": 2, "b": 2}, per_min=2)
    book.script = {("b", 1): OrderRejected("거부")}
    with pytest.raises(OrderRejected):
        ctx.target({"a": 2, "b": -2})
    assert ("a", -2, "revert") in book.orders


def test_revert_rejected_halts():
    ctx, _, book, _, _ = make()
    book.script = {("b", 1): OrderRejected("거부"), ("a", 2): OrderRejected("되돌리기 거부")}
    with pytest.raises(Halted):
        ctx.target({"a": 2, "b": -2})
    assert not ctx.running() and book.halted and "되돌리기 거부" in book.halted
    n = len(book.orders)
    with pytest.raises(Halted):
        ctx.order("a", 1)
    assert len(book.orders) == n


def test_review1_second_leg_unknown_halts_without_revert():
    ctx, _, book, _, _ = make()
    book.script = {("b", 1): Halted("응답 없음")}
    with pytest.raises(Halted):
        ctx.target({"a": 1, "b": -1})
    assert book.orders == [("a", 1, "target"), ("b", -1, "target")]
    with pytest.raises(Halted):
        ctx.order("a", 1)
    with pytest.raises(Halted):
        ctx.target({"a": 0, "b": 0})
    assert len(book.orders) == 2 and not ctx.running()


def test_log_requires_number_and_writes_journal():
    ctx, _, _, jr, _ = make()
    ctx.log("z", 2.3, beta=0.8)
    assert jr.rows == [("log", {"name": "z", "value": 2.3, "beta": 0.8, "t": "2026-11-09T10:00:00"})]
    with pytest.raises(TypeError):
        ctx.log("z", "x")
    with pytest.raises(TypeError):
        ctx.log("z", True)


def test_roll_only_when_flat():
    ctx, _, book, _, _ = make()
    book.pos["a"] = 1
    with pytest.raises(OrderRejected):
        ctx.roll("a")
    book.pos["a"] = 0
    new = ctx.roll("a")
    assert ctx.leg("a") is new and new.sym == "aZ27"


def test_stop_aware_waits_use_stop_event():
    ctx, feed, _, _, stop = make()
    assert ctx.next_minute(["a", B]) is None
    ctx.sleep(5)
    assert feed.waits[0][2] is stop and feed.waits[1] == ("sleep", 5, stop)
    assert ctx.bars(["a"], 3) and ctx.now() == feed.t and ctx.quote("a").last == 1.0


def test_inherited_is_read_only_copy():
    src = {"a": {"qty": 1, "avg_price": 2.0}}
    ctx, *_ = make(inherited=src)
    got = ctx.inherited
    got["a"]["qty"] = 99
    src["a"]["qty"] = 7
    assert ctx.inherited == {"a": {"qty": 1, "avg_price": 2.0}}
    assert make()[0].inherited is None


def test_stale_leg_after_roll_rejected():
    ctx, _, book, _, _ = make()
    old = ctx.leg("a")
    ctx.roll("a")
    with pytest.raises(OrderRejected, match="낡은"):
        ctx.order(old, 1)
    with pytest.raises(OrderRejected):
        ctx.quote(old)
    with pytest.raises(OrderRejected):
        ctx.order(replace(ctx.leg("a"), tick=9.0), 1)
    ctx.order(ctx.leg("a"), 1)
    assert len(book.orders) == 1


def test_roll_accepts_leg_argument():
    ctx, *_ = make()
    assert ctx.roll(A).sym == "aZ27"


def test_wrong_sign_fill_halts_book():
    ctx, _, book, _, _ = make()
    book.script = {("a", 1): Fill("a", -1, 1.0, None)}
    with pytest.raises(Halted):
        ctx.order("a", 1)
    assert book.halted
    with pytest.raises(Halted):
        ctx.order("b", 1)


def test_wrong_leg_fill_halts_book():
    ctx, _, book, _, _ = make()
    book.script = {("a", 1): Fill("b", 1, 1.0, None)}
    with pytest.raises(Halted):
        ctx.order("a", 1)
    assert book.halted


def test_unexpected_exception_in_send_halts():
    ctx, _, book, jr, _ = make()
    book.script = {("a", 1): RuntimeError("boom")}
    with pytest.raises(Halted) as ei:
        ctx.order("a", 1)
    assert isinstance(ei.value.__cause__, RuntimeError) and book.halted
    assert any(k == "halt" for k, _ in jr.rows)


def test_unexpected_exception_in_revert_halts():
    ctx, _, book, _, _ = make()
    book.script = {("b", 1): OrderRejected("거부"), ("a", 2): RuntimeError("boom")}
    with pytest.raises(Halted):
        ctx.target({"a": 2, "b": -2})
    assert book.halted


def test_zero_qty_fill_skipped_in_revert():
    ctx, _, book, _, _ = make()
    book.script = {("a", 1): Fill("a", 0, 0.0, None), ("b", 1): OrderRejected("거부")}
    with pytest.raises(OrderRejected):
        ctx.target({"a": 2, "b": -2})
    assert not any(o[2] == "revert" for o in book.orders)


def test_r11_stop_mid_target_still_reverts_filled_leg():
    ctx, _, book, _, stop = make()
    orig = book.order

    def order_then_stop(leg, qty, why):
        r = orig(leg, qty, why)
        if why == "target":
            stop.set()
        return r
    book.order = order_then_stop
    with pytest.raises(OrderRejected, match="중지됨"):
        ctx.target({"a": 2, "b": -2})
    assert book.orders == [("a", 2, "target"), ("a", -2, "revert")]
    assert book.pos == {"a": 0, "b": 0} and book.halted is None


# ---------------------------------------------------------------- 마지막 검토 고침 (final-findings)
D = mk("d", "domestic")


def make_dom(t):
    feed, book, jr, stop = FakeFeed(), FakeBook(), Jr(), threading.Event()
    feed.open["d"], book.pos["d"], feed.t = True, 0, t
    ctx = Ctx({"a": A, "d": D}, feed, book, jr, max_qty={"a": 5, "d": 5}, orders_per_min=10, inherited=None,
              stop=stop, roll=lambda n: mk(n))
    return ctx, feed, book


def test_F1_국내_다리는_장이_열려도_09시_전엔_주문하지_않는다():
    ctx, feed, book = make_dom(datetime(2026, 11, 9, 8, 50))        # 국내 주간 판정(08:45~)은 열림
    assert ctx.market_open("d") is False and ctx.market_open("a") is True
    with pytest.raises(OrderRejected, match="09:00"):
        ctx.order("d", 1)
    with pytest.raises(OrderRejected, match="09:00"):
        ctx.target({"a": 1, "d": -1})                                # 짝은 아무것도 내지 않는다
    assert book.orders == []
    feed.t = datetime(2026, 11, 9, 9, 0)
    assert ctx.market_open("d") is True
    ctx.target({"a": 1, "d": -1})
    assert book.orders == [("a", 1, "target"), ("d", -1, "target")]


def test_F5_멈춘_뒤나_중지_뒤엔_월물을_바꾸지_않는다():
    calls = []
    ctx, _, book, _, stop = make(roll=lambda n: calls.append(n) or replace(mk(n), sym=n + "Z27"))
    book.halted = "결과 모름"
    with pytest.raises(Halted):
        ctx.roll("a")
    book.halted = None
    stop.set()
    with pytest.raises(OrderRejected, match="중지"):
        ctx.roll("a")
    assert calls == [] and ctx.leg("a") == A


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_F6_log_는_유한한_수만_받는다(bad):
    ctx, _, _, jr, _ = make()
    with pytest.raises(ValueError):
        ctx.log("z", bad)
    with pytest.raises(ValueError):
        ctx.log("z", 1.0, beta=bad)
    with pytest.raises(ValueError):
        ctx.log("z", 1.0, info={"x": [1, bad]})
    assert jr.rows == []


@pytest.mark.parametrize("bad", [1.5, 1.0, True, False, "1", None])
def test_F7_주문_수량은_정수만_아무것도_내기_전에_TypeError(bad):
    ctx, _, book, _, _ = make()
    with pytest.raises(TypeError):
        ctx.order("a", bad)
    with pytest.raises(TypeError):
        ctx.target({"a": 1, "b": bad})
    assert book.orders == []


class _StopAfterA(FakeBook):
    """a 다리가 체결된 순간 앱이 끝내기 시작한다(중지 + 끝내는 중) — 그 뒤 b 는 `중지됨` 으로 거부."""

    def __init__(self):
        super().__init__()
        self.after_a = lambda: None

    def order(self, leg, qty, why):
        fill = super().order(leg, qty, why)
        if leg.name == "a" and why == "target":
            self.after_a()
        return fill


def test_F8_앱이_끝내는_중이면_되돌리기를_건너뛰고_반쪽은_장부에_남긴다():
    closing = {"v": False}
    book = _StopAfterA()
    ctx, _, book, jr, stop = make(book=book, closing=lambda: closing["v"])
    book.after_a = lambda: (stop.set(), closing.update(v=True))
    with pytest.raises(OrderRejected, match="중지") as ei:
        ctx.target({"a": 1, "b": -1})
    assert not isinstance(ei.value, Halted) and book.halted is None
    assert book.orders == [("a", 1, "target")] and book.pos == {"a": 1, "b": 0}     # 되돌리기 주문 없음
    assert any("되돌리기 건너뜀" in str(d.get("text", "")) for _, d in jr.rows)


class _MovesA(FakeBook):
    """b 주문 순간 다른 스레드(앱 정리)가 a 를 이미 0 으로 만들었고, b 는 거부된다."""

    def order(self, leg, qty, why):
        if leg.name == "b":
            self.orders.append((leg.name, qty, why))
            self.pos["a"] = 0
            raise OrderRejected("거부")
        return super().order(leg, qty, why)


def test_F8_체결_뒤_보유가_바뀌었으면_되돌리지_않고_멈춘다():
    ctx, _, book, jr, _ = make(book=_MovesA())
    with pytest.raises(Halted):
        ctx.target({"a": 1, "b": -1})
    assert book.orders == [("a", 1, "target"), ("b", -1, "target")]                  # 눈먼 -1 을 내지 않는다
    assert book.pos["a"] == 0 and book.halted and "되돌리기 건너뜀" in book.halted


def test_F9_끝내는_중엔_시세_조회도_나가지_않는다():
    ctx, feed, _, _, stop = make(closing=lambda: True)
    stop.set()
    seen = []
    feed.quote = lambda leg: seen.append("quote")
    feed.history = lambda legs, count: seen.append("history")
    for call in (lambda: ctx.quote("a"), lambda: ctx.bars(["a"], 3), lambda: ctx.next_minute(["a"])):
        with pytest.raises(OrderRejected, match="중지"):
            call()
    assert seen == [] and feed.waits == []


def test_F9_중지만_했을_때는_시세를_아직_준다():
    ctx, feed, _, _, stop = make(closing=lambda: False)
    stop.set()
    assert ctx.quote("a").last == 1.0 and ctx.bars(["a"], 3)


def test_F13_log_줄에는_ctx_now_시각_t():
    ctx, feed, _, jr, _ = make()
    feed.t = datetime(2026, 11, 9, 10, 15, 30)
    ctx.log("z", 1.5)
    assert jr.rows[-1] == ("log", {"name": "z", "value": 1.5, "t": "2026-11-09T10:15:30"})
    with pytest.raises(ValueError, match="t"):
        ctx.log("z", 1.0, t="내 시각")                    # t 는 앱이 쓰는 칸


def test_F14_이어받은_보유가_최대보다_크면_줄이는_주문만():
    ctx, _, book, _, _ = make(max_qty={"a": 5, "b": 5})
    book.pos["a"] = 7                                    # 이어받음 — 최대 보유 5 보다 크다
    ctx.order("a", -1)                                   # 7 → 6 줄이기는 된다
    ctx.target({"a": 5})                                 # 6 → 5
    book.pos["a"] = 7
    for bad in (1, -14):                                 # 늘리기·0 을 넘어 반대로 한도 밖은 거부
        with pytest.raises(OrderRejected, match="최대 보유"):
            ctx.order("a", bad)
    assert book.orders == [("a", -1, "order"), ("a", -1, "target")]
