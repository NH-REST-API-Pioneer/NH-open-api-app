"""일봉 신호의 주문은 다음 거래 창의 첫 체결에 나갑니다.

**계좌에 닿지 않습니다.** 체결·호가·개장 시각을 손으로 넣고, 계좌 갈래는 주문을
적기만 하는 가짜 자리로 돌립니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import backtest, engine, paper, runs, sim
from backend.strategy.indicators import Bar
from tests.test_strategy_engine import _규칙, _때, _설정, _엔진, _조건, _호가, 지연

주간 = "domestic-day"
야간 = "domestic-night"


def _일봉(**aux) -> dict:
    return {**_설정(**aux), "baseBar": "일봉"}


def _틱(엔진: engine.RunEngine, 때: int, price: float, context: str = 주간) -> None:
    엔진.on_trade({"timestamp": 때, "price": price, "quantity": 1}, context, at=때)


def _이틀(엔진: engine.RunEngine) -> None:
    """15일 99 로, 16일 101 로 닫습니다. 16일 마감에서 매수 진입이 걸립니다."""
    _틱(엔진, _때(10, 0, day=15), 99.0)
    엔진.close_session(_때(15, 46, day=15))
    _틱(엔진, _때(10, 0, day=16), 101.0)
    엔진.close_session(_때(15, 46, day=16))


def _미룸(엔진: engine.RunEngine) -> list[str]:
    return [one["text"] for one in 엔진.events if one["text"] == engine.DEFERRED_TEXT]


def _안낸신호(엔진: engine.RunEngine) -> list[str]:
    return [one["text"] for one in 엔진.events if one["kind"] == engine.BLOCKED]


# ── 종이 ─────────────────────────────────────────────────


def test_일봉_진입은_마감에서_미뤘다가_다음_거래_창_첫_체결에_낸다():
    엔진 = _엔진(_일봉())
    _이틀(엔진)

    assert 엔진.book.orders == [], "마감에서는 내지 않습니다."
    assert _미룸(엔진) == [engine.DEFERRED_TEXT]
    assert 엔진.run.state == runs.ARMED

    _틱(엔진, _때(18, 30, day=16), 101.0, 야간)
    assert 엔진.book.orders == [], "주간 실행에 야간 체결이 와도 내지 않습니다."
    _틱(엔진, _때(8, 40, day=17), 101.0)
    assert 엔진.book.orders == [], "개장 시각을 받기 전(동시호가)에는 내지 않습니다."

    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 44, day=17), 101.0)
    assert 엔진.book.orders == [], "개장 시각 앞의 체결에서는 내지 않습니다."
    _틱(엔진, _때(8, 45, day=17), 101.0)
    (주문,) = 엔진.book.orders
    assert 주문.side == paper.BUY and 엔진.run.state == runs.ENTERING

    엔진.on_book(_호가(101.5, 101.0), at=_때(8, 45, day=17) + 지연)
    assert 엔진.ledger.position.quantity == 1 and 엔진.run.state == runs.HOLDING
    _틱(엔진, _때(9, 0, day=17), 101.5)
    assert len(엔진.book.orders) == 1, "한 번만 냅니다."


def test_일봉_청산_규칙도_다음_거래_창에서_낸다():
    설정 = _일봉(stopTicks="", takeTicks="")
    설정["rules"]["buyExit"] = _규칙(_조건(op="lt", right="100"))
    엔진 = _엔진(설정)
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 101.0, "time": 1})
    엔진.run.state = runs.HOLDING
    _틱(엔진, _때(10, 0, day=15), 101.0)
    엔진.close_session(_때(15, 46, day=15))
    _틱(엔진, _때(10, 0, day=16), 99.0)
    엔진.close_session(_때(15, 46, day=16))

    assert 엔진.book.orders == [] and 엔진.run.state == runs.HOLDING
    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 99.5)

    (주문,) = 엔진.book.orders
    assert 주문.side == paper.SELL and 엔진.run.state == runs.EXITING
    assert 엔진._exit_reason == engine.RULE_EXIT


def test_시세가_끊긴_뒤에는_다시_붙은_첫_체결에서_낸다():
    엔진 = _엔진(_일봉())
    _이틀(엔진)
    엔진.note_open(주간, _때(8, 45, day=17))
    엔진.tick_clock(_때(8, 45, day=17) + 엔진.gap_ms + 10**9)
    assert 엔진.feed == engine.GAP
    assert 엔진.book.orders == []

    _틱(엔진, _때(9, 0, day=17), 101.0)
    assert 엔진.feed != engine.GAP and len(엔진.book.orders) == 1


def test_같은_갈래는_갈아_끼우고_청산을_먼저_낸다():
    엔진 = _엔진(_일봉())
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    엔진._defer("entry", paper.BUY, 100.0, 1)
    엔진._defer("entry", paper.BUY, 101.0, 2)
    엔진._defer("exit", paper.BUY, 101.0, 3)
    assert set(엔진._deferred) == {"entry", "exit"} and 엔진._deferred["entry"]["signal"] == 101.0

    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 101.0)

    (청산,) = 엔진.book.orders
    assert 청산.side == paper.SELL, "청산이 먼저 나갔고, 진입은 청산 중이라 내지 않았습니다."
    assert _안낸신호(엔진) == [f"{engine.UNSENT_HEAD}{engine.WHY_DEFERRED_STATE}"]
    assert 엔진._deferred == {}


def test_그_사이_중지했으면_내지_않고_안_낸_신호로_센다():
    엔진 = _엔진(_일봉())
    _이틀(엔진)
    엔진.run.move(runs.PAUSE)
    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 101.0)

    assert 엔진.book.orders == []
    assert _안낸신호(엔진) == [f"{engine.UNSENT_HEAD}{engine.WHY_DEFERRED_STATE}"]
    assert 엔진.unsent_today(_때(8, 46, day=17)) == 1
    assert 엔진._deferred == {}


@pytest.mark.parametrize(("ask", "채움"), [(99.0, True), (103.0, False)])
def test_지정가는_판정한_봉의_종가로_세고_갭이면_곧바로_채우거나_기다린다(ask, 채움):
    엔진 = _엔진(_일봉(orderType="지정가", priceBasis="신호가"))
    _이틀(엔진)
    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), ask)

    (주문,) = 엔진.book.orders
    assert 주문.price == pytest.approx(101.0), "어제 종가 101 입니다."
    엔진.on_book(_호가(ask, ask - 0.05), at=_때(8, 46, day=17) + 지연)
    assert (엔진.ledger.position.quantity == 1) is 채움
    assert 주문.open is not 채움


# ── 계좌 갈래 ─────────────────────────────────────────────


class _적는곳:
    def __init__(self) -> None:
        self.orders: list[dict] = []

    def order(self, **물음):
        self.orders.append(물음)
        return {"id": f"{len(self.orders):010d}"}

    def cancel(self, *, run, order):
        return {"id": order.order_no}


def test_계좌_갈래는_마감에서_안_보내고_개장_뒤_첫_체결에서_보낸다():
    보냄 = _적는곳()
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=10_000_000.0, multiplier=1.0, draft=_일봉(),
        mode=runs.SIM, approved_at=1_000, environment="paper",
    )
    엔진 = engine.RunEngine(run, tick=0.05, book=sim.SimBroker(run, sender=보냄, environment=lambda: "paper"))
    _이틀(엔진)
    assert 보냄.orders == [], "장이 닫힌 뒤에는 보내지 않습니다."

    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 101.0)
    assert len(보냄.orders) == 1


def test_다음_세션에_못_낸_미룬_주문은_그_세션_마감에서_버린다():
    보냄 = _적는곳()
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=10_000_000.0, multiplier=1.0, draft=_일봉(),
        mode=runs.SIM, approved_at=1_000, environment="paper",
    )
    엔진 = engine.RunEngine(run, tick=0.05, book=sim.SimBroker(run, sender=보냄, environment=lambda: "paper"))
    _이틀(엔진)
    _틱(엔진, _때(10, 0, day=17), 101.0)  # 개장 시각을 못 받은 날 — 내지 않습니다.
    엔진.close_session(_때(15, 46, day=17))

    assert _안낸신호(엔진) == [f"{engine.UNSENT_HEAD}{engine.WHY_DEFERRED_EXPIRED}"]
    assert 엔진.unsent_today(_때(15, 46, day=17)) == 1
    assert 엔진._deferred == {}

    엔진.note_open(주간, _때(8, 45, day=18))
    _틱(엔진, _때(8, 46, day=18), 101.0)
    assert 보냄.orders == [], "묵은 신호는 다음 날에도 나가지 않습니다."


# ── 분봉은 그대로 ─────────────────────────────────────────


def test_분봉_마지막_봉의_신호는_마감에서_거둔다():
    엔진 = _엔진(_설정())
    _틱(엔진, _때(15, 43), 99.0)
    _틱(엔진, _때(15, 44), 101.0)  # 15:43 봉이 닫힘
    엔진.close_session(_때(15, 46))  # 15:44 봉이 닫히며 걸리고, 그 주문은 거둡니다.

    assert 엔진._deferred == {}
    (주문,) = 엔진.book.orders
    assert 주문.status == paper.CANCELLED
    assert 엔진.run.state == runs.ARMED


# ── 지난 봉 셈 ────────────────────────────────────────────


def test_지난_봉_셈에서도_일봉_신호는_다음_봉_시가에_채운다():
    값들 = [(99.0, 99.0), (99.0, 101.0), (101.2, 101.3), (101.3, 101.4)]
    봉들 = [
        Bar(_때(0, 0, day=10 + i), o, max(o, c) + 0.1, min(o, c) - 0.1, c, 10)
        for i, (o, c) in enumerate(값들)
    ]

    답 = backtest.compute(
        draft=_일봉(stopTicks="", takeTicks=""), market="domestic", code="A7569000", session=주간,
        bars=봉들, tick=0.05, margin=1_000.0,
    )

    assert 답["assumptions"]["dailyOrders"] == "next-session-first-trade"
    assert 답["fills"] == 1 and 답["openPosition"]["avgPrice"] == pytest.approx(101.25), "12일 시가 101.2 + 1틱."
