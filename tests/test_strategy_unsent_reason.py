"""주문을 내지 않은 사건 — 글 머리, 까닭 코드(`reason`), 까닭 글(`why`).

**계좌에 닿지 않습니다.** 엔진에 봉을 손으로 넣고, 계좌 갈래는 거절만 하거나
적기만 하는 가짜 자리로 돌립니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, journal as journal_lib, runs, sim
from tests.test_strategy_daily_orders import _이틀, _일봉, _틱, 주간
from tests.test_strategy_engine import _때, _넣기, _설정, _엔진

#: 주문을 내지 않은 사건의 까닭이 **아닌** 까닭 상수와 그 까닭. 새 까닭 상수를
#: 더하면 코드 표(`engine.BLOCK_REASONS`)나 이 목록 가운데 한 곳에 넣어야 합니다.
_막힘_아님 = {
    "WHY_RUNS": "실행을 세울 때의 거절입니다",
    "WHY_SOLD_OPTION": "증거금 설명에 덧붙이는 말입니다",
    "WHY_MULTIPLIER_UNKNOWN": "시작 전 검사의 거절입니다",
    "WHY_BUDGET_UNCHECKED": "증거금 예산 검사를 건너뛴다는 안내입니다",
    # 주문 거절은 거절한 자리가 코드를 적습니다(`sim.SimRefused.reason`).
    "WHY_NOT_APPROVED": "주문 거절입니다",
    "WHY_NOT_ACCOUNT_MODE": "주문 거절입니다",
}


def _까닭_상수(module) -> dict[str, str]:
    return {name: value for name, value in vars(module).items() if name.startswith("WHY_") and isinstance(value, str)}


def _막힘(엔진: engine.RunEngine) -> list[dict]:
    return [one for one in 엔진.events if one["kind"] == engine.BLOCKED]


# ── 코드 표 ───────────────────────────────────────────


def test_막힘_까닭_상수는_모두_코드를_가진다():
    """새 까닭 상수를 더하고 표를 잊으면 여기서 실패합니다."""
    상수 = {**_까닭_상수(runs), **_까닭_상수(engine)}
    빠짐 = [name for name, value in 상수.items() if name not in _막힘_아님 and value not in engine.BLOCK_REASONS]

    assert 빠짐 == []
    assert set(_막힘_아님) <= set(상수), "목록에 없는 이름이 남아 있습니다."


def test_코드_표에는_까닭_상수만_있고_코드는_겹치지_않는다():
    상수글 = set(_까닭_상수(runs).values()) | set(_까닭_상수(engine).values())

    assert set(engine.BLOCK_REASONS) <= 상수글
    코드 = list(engine.BLOCK_REASONS.values())
    assert len(코드) == len(set(코드)) and engine.OTHER_REASON not in 코드


def test_한도_정지_코드는_화면이_가리는_이름이다():
    assert engine.BLOCK_REASONS[runs.WHY_DAILY_LOSS] == "daily-loss"
    assert engine.BLOCK_REASONS[runs.WHY_MARGIN_UNKNOWN] == "margin-unknown"
    assert engine.BLOCK_REASONS[runs.WHY_LOSS_STREAK] == "loss-streak"


# ── 세 자리 ───────────────────────────────────────────


def test_판정에서_막힌_진입은_글_머리와_코드와_까닭을_싣는다():
    남김: list = []
    엔진 = _엔진(_설정(maxHold="0"))
    엔진.record = lambda kind, row: 남김.append((kind, row))

    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)

    (막힘,) = _막힘(엔진)
    assert 막힘["text"] == engine.UNSENT_HEAD + runs.WHY_MAX_HOLD
    assert 막힘["reason"] == "max-hold" and 막힘["why"] == runs.WHY_MAX_HOLD
    assert 막힘["text"].startswith("조건이 참이었지만 주문을 내지 않았습니다 — ")
    (기록,) = [row for kind, row in 남김 if kind == "event" and row["kind"] == engine.BLOCKED]
    assert 기록 is 막힘, "화면에 보이는 줄과 기록에 남는 줄이 같은 줄입니다."


def test_미룬_주문을_버리면_미룬_까닭의_코드를_싣는다():
    엔진 = _엔진(_일봉())
    _이틀(엔진)
    엔진.run.move(runs.PAUSE)
    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 101.0)

    (막힘,) = _막힘(엔진)
    assert 막힘["reason"] == "deferred-state" and 막힘["why"] == engine.WHY_DEFERRED_STATE
    assert 막힘["text"] == engine.UNSENT_HEAD + engine.WHY_DEFERRED_STATE


class _거절장부:
    def __init__(self, refused: sim.SimRefused) -> None:
        self.refused = refused
        self.orders: list = []
        self.last_price = None
        self.gap = False

    @property
    def open_orders(self):
        return []

    def place(self, order_id, **물음):
        raise self.refused

    def on_trade(self, trade, *, at):
        if trade.get("price") is not None:
            self.last_price = float(trade["price"])
        return []

    def on_book(self, book, *, at):
        return []

    def cancel_open(self, reason):
        return []


def test_주문_거절은_거절한_자리의_코드를_싣는다():
    엔진 = _엔진()
    엔진.book = _거절장부(sim.SimRefused(runs.WHY_NOT_APPROVED, reason="not-approved"))

    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)

    (막힘,) = _막힘(엔진)
    assert 막힘["reason"] == "not-approved" and 막힘["why"] == runs.WHY_NOT_APPROVED
    assert 막힘["text"] == engine.UNSENT_HEAD + runs.WHY_NOT_APPROVED


def test_코드_없는_거절은_글이_표와_같아도_other_다():
    """거절의 코드는 글로 짐작하지 않습니다."""
    엔진 = _엔진()
    엔진.book = _거절장부(sim.SimRefused(runs.WHY_DAILY_LOSS))

    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)

    (막힘,) = _막힘(엔진)
    assert 막힘["reason"] == engine.OTHER_REASON and 막힘["why"] == runs.WHY_DAILY_LOSS


def test_표에_없는_까닭은_other_다():
    엔진 = _엔진()

    엔진._say_unsent(1, "처음 보는 까닭")

    (막힘,) = _막힘(엔진)
    assert 막힘["reason"] == engine.OTHER_REASON and 막힘["why"] == "처음 보는 까닭"


def test_막힘이_아닌_사건에는_코드와_까닭_칸이_없다():
    엔진 = _엔진()

    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)

    assert 엔진.events and all("reason" not in one and "why" not in one for one in 엔진.events)


# ── 계좌 갈래의 거절 코드 ─────────────────────────────


def _장부(*, mode=runs.SIM, approved_at=1, environment="paper", sender=None) -> sim.SimBroker:
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=1.0, draft=_설정(), mode=mode, approved_at=approved_at,
        environment="paper",
    )
    보냄 = sender or type("S", (), {"order": lambda self, **물음: {"id": "0000000001"}})()
    return sim.SimBroker(run, sender=보냄, environment=lambda: environment)


def _거절코드(장부: sim.SimBroker) -> str:
    with pytest.raises(sim.SimRefused) as 거절:
        장부.place("o1", side="buy", quantity=1, order_type="시장가", price=None, at=1)
    return 거절.value.reason


def test_계좌_갈래의_거절_자리마다_코드를_적는다():
    class 실패:
        def order(self, **물음):
            raise RuntimeError("끊김")

    class 번호없음:
        def order(self, **물음):
            return {}

    assert _거절코드(_장부(approved_at=0)) == "not-approved"
    assert _거절코드(_장부(environment="real")) == "environment"
    assert _거절코드(_장부(sender=실패())) == "no-reply"
    assert _거절코드(_장부(sender=번호없음())) == "no-order-no"


def test_계좌_갈래가_아닌_실행의_거절_코드():
    장부 = _장부()
    장부.run.mode = runs.PAPER

    assert _거절코드(장부) == "not-account-mode"


# ── 옛 기록 ───────────────────────────────────────────


def test_옛_기록의_막힘_줄은_코드와_까닭_칸_없이_그대로_읽힌다(tmp_path):
    기록 = journal_lib.Journal(tmp_path / "trades.jsonl")
    실행 = runs.Run(id="r1", version_id="v1", code="A7569000", session=주간, market="domestic", draft=_설정())
    기록.write("event", 실행, {"time": 1, "runId": "r1", "kind": engine.BLOCKED, "text": "미발사 — 최대 보유를 넘습니다"})

    (줄,) = 기록.read(run_id="r1", kind="event")

    assert 줄["text"] == "미발사 — 최대 보유를 넘습니다", "옛 줄은 다시 쓰지 않습니다."
    assert "reason" not in 줄 and "why" not in 줄
