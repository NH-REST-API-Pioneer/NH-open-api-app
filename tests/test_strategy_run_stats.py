"""실행 줄의 성과 칸 — 규칙이 걸린 수·체결 수·마지막 신호 시각·실현/평가 손익.

**계좌에 닿지 않습니다.** 종이 실행은 지어낸 체결로, 계좌 갈래는 주문을 적기만
하는 가짜 자리로 돌립니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, journal as journal_lib, paper, runs, sim
from backend.strategy import service as service_lib
from tests.test_strategy_engine import (
    _규칙,
    _때,
    _매수_보유,
    _설정,
    _손실_한_번,
    _엔진,
    _넣기,
    _조건,
    _틱,
    주간,
    지연,
)

_칸 = ("signalCount", "fillCount", "lastSignalAt", "realizedPl", "openPl")


def _줄(엔진: engine.RunEngine) -> dict:
    return 엔진.snapshot()["run"]


# ── 손익 둘 ──────────────────────────────────────────────


def test_수수료만_있고_보유가_없으면_평가는_0_이고_수수료는_실현_쪽이다():
    엔진 = _엔진(_설정(lossStreak=""), fee_per_contract=250.0)
    _손실_한_번(엔진, 0)
    줄 = _줄(엔진)

    assert 엔진.ledger.fee == 500.0
    assert 줄["openPl"] == 0.0
    assert 줄["realizedPl"] == pytest.approx(엔진.ledger.realized - 500.0)
    assert 줄["realizedPl"] + 줄["openPl"] == pytest.approx(줄["pl"])


@pytest.mark.parametrize("fee", [0.0, 250.0])
@pytest.mark.parametrize("last", [101.5, 103.0, 99.0])
def test_실현과_평가를_더하면_손익이다(fee, last):
    엔진 = _엔진(_설정(lossStreak=""), fee_per_contract=fee)
    if fee:
        _손실_한_번(엔진, 0)  # 실현 손실과 수수료가 있는 경우도 봅니다.
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 101.5, "time": 1})
    엔진.book.last_price = last
    줄 = _줄(엔진)

    assert 줄["openPl"] == pytest.approx((last - 101.5) * 1.0)
    assert 줄["realizedPl"] + 줄["openPl"] == pytest.approx(줄["pl"])


def test_보유가_있는데_마지막가를_모르면_평가는_모름이다():
    엔진 = _엔진()
    엔진.ledger.add({"side": paper.SELL, "quantity": 2, "price": 100.0, "time": 1})
    엔진.book.last_price = None

    줄 = _줄(엔진)
    assert 줄["openPl"] is None
    assert 줄["realizedPl"] == 0.0


def test_매도_보유의_평가는_내리면_이익이다():
    엔진 = _엔진()
    엔진.ledger.add({"side": paper.SELL, "quantity": 2, "price": 100.0, "time": 1})
    엔진.book.last_price = 99.0

    줄 = _줄(엔진)
    assert 줄["openPl"] == pytest.approx(2.0)
    assert 줄["realizedPl"] + 줄["openPl"] == pytest.approx(줄["pl"])


# ── 신호 수 ──────────────────────────────────────────────


def test_새_실행은_0_에서_시작하고_마지막_신호는_모름이다():
    줄 = _줄(_엔진())

    assert (줄["signalCount"], 줄["fillCount"], 줄["lastSignalAt"]) == (0, 0, None)


def test_규칙이_걸리면_세고_그_순간을_적는다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)  # 10:01 봉이 닫히며 매수 진입이 걸립니다.

    걸림 = [one for one in 엔진.events if one["kind"] == engine.SIGNAL]
    줄 = _줄(엔진)
    assert 줄["signalCount"] == len(걸림) == 1
    assert 줄["lastSignalAt"] == 걸림[-1]["time"] == _때(10, 2)


def test_안_낸_신호도_세고_한_봉에_규칙_둘이면_둘이다():
    설정 = _설정(entryStart="09:00", entryEnd="09:30")  # 10시 봉은 신규 진입 시간 밖입니다.
    설정["rules"]["sellEntry"] = _규칙(_조건())
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    줄 = _줄(엔진)
    assert 줄["signalCount"] == 2
    막힘 = [one for one in 엔진.events if one["kind"] == engine.BLOCKED]
    assert len(막힘) == 2, "둘 다 주문을 내지 않았습니다."
    assert 엔진.book.orders == []


def test_청산_규칙이_걸린_것도_센다():
    설정 = _설정(stopTicks="", takeTicks="")
    설정["rules"]["buyExit"] = _규칙(_조건(op="lt", right="100.5"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book({"asks": [{"price": 101.5, "quantity": 9}], "bids": [{"price": 101.0, "quantity": 9}]}, at=_때(10, 2) + 지연)
    assert 엔진.ledger.position.quantity == 1
    _틱(엔진, _때(10, 3), 100.0)
    _틱(엔진, _때(10, 4), 100.0)  # 10:03 봉이 100 으로 닫혀 매수 청산이 걸립니다.

    줄 = _줄(엔진)
    assert 엔진._exit_reason == engine.RULE_EXIT
    assert 줄["signalCount"] == 2 and 줄["lastSignalAt"] == _때(10, 4)


# ── 잘리는 목록과 상관없이 ─────────────────────────────────


def test_목록이_잘려도_수는_그대로다():
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=10_000_000.0, multiplier=1.0, draft=_설정(lossStreak=""),
    )
    엔진 = engine.RunEngine(run, tick=0.05, history=3)
    for minute in (0, 4, 8):
        _손실_한_번(엔진, minute)

    줄 = _줄(엔진)
    assert len(엔진.fills) == 3 and len(엔진.events) == 3, "목록은 잘렸습니다."
    assert 줄["fillCount"] == 6
    assert 줄["signalCount"] == 3


# ── 체결 수 ──────────────────────────────────────────────


def test_종이_체결은_한_줄에_하나다():
    엔진, _ = _매수_보유()

    assert _줄(엔진)["fillCount"] == len(엔진.fills) == 1


class _적는곳:
    """주문을 적기만 하는 자리. 계좌에 닿지 않습니다."""

    def __init__(self) -> None:
        self.orders: list[dict] = []

    def order(self, **물음):
        self.orders.append(물음)
        return {"id": f"{len(self.orders):010d}"}

    def cancel(self, *, run, order):
        return {"id": order.order_no}


def test_계좌_갈래는_부분_체결도_줄마다_센다():
    보냄 = _적는곳()
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=3, cash=10_000_000.0, multiplier=1.0,
        draft=_설정(orderType="지정가", maxHold="5"), mode=runs.SIM, approved_at=1_000, environment="paper",
    )
    엔진 = engine.RunEngine(run, tick=0.05, book=sim.SimBroker(run, sender=보냄, environment=lambda: "paper"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    (진입,) = 엔진.book.open_orders

    엔진.on_order({"id": 진입.order_no, "status": "partial", "filled": 1, "fillPrice": 101.0}, at=_때(10, 2, 1))
    엔진.on_order({"id": 진입.order_no, "status": "partial", "filled": 1, "fillPrice": 101.0}, at=_때(10, 2, 2))
    엔진.on_order({"id": 진입.order_no, "status": "filled", "filled": 3, "fillPrice": 101.0}, at=_때(10, 2, 3))

    줄 = _줄(엔진)
    assert len(보냄.orders) == 1
    assert 줄["fillCount"] == len(엔진.fills) == 2, "같은 누적 수량을 다시 받은 것은 체결이 아닙니다."
    assert 엔진.ledger.position.quantity == 3
    assert 줄["signalCount"] == 1


# ── 되살린 실행·장부 없는 줄 ────────────────────────────────


def _목록(tmp_path) -> service_lib.RunService:
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
    )


def test_새로_세운_실행의_목록_줄은_0_에서_시작한다(tmp_path):
    실행목록 = _목록(tmp_path)
    실행목록.add(
        run_id="r1", version_id="v1", draft=_설정(), market="domestic", code="A7569000",
        session=주간, qty=1, cash=1.0,
    )

    (줄,) = 실행목록.rows()
    assert (줄["signalCount"], 줄["fillCount"], 줄["lastSignalAt"]) == (0, 0, None)
    assert (줄["realizedPl"], 줄["openPl"]) == (0.0, 0.0)


def test_다시_켜_되살린_실행의_수는_모름이다(tmp_path):
    앞 = _목록(tmp_path)
    앞.add(
        run_id="r1", version_id="v1", draft=_설정(), market="domestic", code="A7569000",
        session=주간, qty=1, cash=1.0,
    )
    앞._engine("r1").signal_count = 7

    뒤 = _목록(tmp_path)  # 같은 파일을 읽는 새 앱입니다.
    (줄,) = 뒤.rows()

    assert (줄["signalCount"], 줄["fillCount"], 줄["lastSignalAt"]) == (None, None, None)
    assert 뒤.snapshot("r1")["run"]["signalCount"] is None
    assert 줄["realizedPl"] + 줄["openPl"] == pytest.approx(줄["pl"]), "손익은 빈 장부의 값입니다."


def test_장부_없이_내는_줄은_다섯_다_모름이다(tmp_path):
    실행목록 = _목록(tmp_path)
    실행목록.add(
        run_id="r1", version_id="v1", draft=_설정(), market="domestic", code="A7569000",
        session=주간, qty=1, cash=1.0,
    )

    줄 = 실행목록.bare_row(실행목록._engine("r1"))
    assert all(줄[이름] is None for 이름 in _칸)
