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


def make(max_qty=None, per_min=10, inherited=None, roll=None):
    feed, book, jr, stop = FakeFeed(), FakeBook(), Jr(), threading.Event()
    ctx = Ctx({"a": A, "b": B}, feed, book, jr, max_qty=max_qty or {"a": 5, "b": 5},
              orders_per_min=per_min, inherited=inherited, stop=stop,
              roll=roll or (lambda n: replace(mk(n), sym=n + "Z27")))
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
    assert jr.rows == [("log", {"name": "z", "value": 2.3, "beta": 0.8})]
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
