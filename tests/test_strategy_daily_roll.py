"""일봉 실행의 거래일 넘김 — 그 실행 세션이 열린 뒤 첫 체결에서, 하루 손실 기준은 어제 종가로.

**계좌에 닿지 않습니다.** 체결·개장 시각을 손으로 넣습니다.
"""
from __future__ import annotations

from datetime import datetime

from backend.sessions.hours import KST
from backend.strategy import backtest, engine, paper, runs, sim
from backend.strategy.indicators import Bar
from tests.test_strategy_daily_orders import _일봉, _틱, 야간, 주간
from tests.test_strategy_engine import _때, _엔진
from tests.test_strategy_vwap_day import _CME, _거래일

해외 = "overseas"


def _자정(day: int) -> int:
    return int(datetime(2026, 9, day, tzinfo=KST).timestamp() * 1000)


def _이틀_조용히(엔진: engine.RunEngine, 어제_종가: float = 99.0) -> None:
    """15일·16일 일봉을 닫습니다. 규칙(종가 > 100 으로 바뀜)은 안 걸립니다."""
    _틱(엔진, _때(10, 0, day=15), 99.0)
    엔진.close_session(_때(15, 46, day=15))
    _틱(엔진, _때(10, 0, day=16), 어제_종가)
    엔진.close_session(_때(15, 46, day=16))


def test_미룬_것이_없어도_개장_뒤_첫_체결에서_거래일을_넘긴다():
    엔진 = _엔진(_일봉())
    _이틀_조용히(엔진)
    assert 엔진.run.day_key == _자정(16)
    엔진.run.intents_today = 3

    _틱(엔진, _때(18, 30, day=16), 99.0, 야간)
    _틱(엔진, _때(8, 40, day=17), 99.0)
    assert 엔진.run.day_key == _자정(16), "야간·개장 전 체결로는 넘기지 않습니다."

    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 99.0)
    assert 엔진.run.day_key == _자정(17) and 엔진.run.intents_today == 0


def test_밤사이_갭은_오늘_하루_손실이다():
    """어제 종가 101 에서 오늘 98 로 열렸습니다. 기준이 어제 종가라 −3 이 오늘 몫입니다."""
    엔진 = _엔진(_일봉(), daily_loss=2.0)
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    _이틀_조용히(엔진, 어제_종가=101.0)
    엔진.note_open(주간, _때(8, 45, day=17))

    _틱(엔진, _때(8, 46, day=17), 98.0)

    assert 엔진.run.day_key == _자정(17)
    assert runs.day_profit(엔진.run, 엔진.ledger, 98.0) == -3.0, "(98 − 101) × 1"
    엔진.run.state = runs.ARMED  # 한도만 봅니다(보유 중이라는 막힘보다 앞서게)
    assert runs.entry_block(
        엔진.run, 엔진.ledger, side=paper.BUY, open_entry=0, max_hold=5, add_while_open=True,
        gap=False, expiring=False, last_price=98.0,
    ) == runs.WHY_DAILY_LOSS, "갭 손실이 하루 손실 한도에 잡힙니다."


def test_시간표를_몰라_개장_시각이_없으면_마감_봉에서_넘긴다():
    엔진 = _엔진(_일봉())
    _이틀_조용히(엔진)

    _틱(엔진, _때(10, 0, day=17), 99.0)
    assert 엔진.run.day_key == _자정(16)
    엔진.close_session(_때(15, 46, day=17))
    assert 엔진.run.day_key == _자정(17)


def test_잔고_줄은_거래일마다_한_번이다():
    기록: list = []
    엔진 = _엔진(_일봉())
    엔진.record = lambda kind, row: 기록.append((kind, dict(row)))
    _이틀_조용히(엔진)
    엔진.note_open(주간, _때(8, 45, day=17))
    _틱(엔진, _때(8, 46, day=17), 99.0)
    _틱(엔진, _때(10, 0, day=17), 99.5)
    엔진.close_session(_때(15, 46, day=17))

    날들 = [row["day"] for kind, row in 기록 if kind == engine.DAY_ROW]
    assert 날들 == ["2026-09-15", "2026-09-16", "2026-09-17"]


def test_계좌_갈래는_넘길_때_대사를_청한다():
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=1.0, draft=_일봉(), mode=runs.SIM, approved_at=1, environment="paper",
    )
    보냄 = type("S", (), {"order": lambda self, **물음: {"id": "1"}, "cancel": lambda self, **물음: {"id": "1"}})()
    엔진 = engine.RunEngine(run, tick=0.05, book=sim.SimBroker(run, sender=보냄, environment=lambda: "paper"))
    _이틀_조용히(엔진)
    엔진.audit_wanted = False
    엔진.note_open(주간, _때(8, 45, day=17))

    _틱(엔진, _때(8, 46, day=17), 99.0)

    assert 엔진.audit_wanted is True


def test_해외_일봉은_시간표_거래일로_넘긴다():
    엔진 = engine.RunEngine(
        runs.Run(id="r1", version_id="v1", code="6AZ26", session=해외, market="overseas",
                 state=runs.ARMED, draft=_일봉()),
        tick=0.0001,
    )
    엔진.trading_day = _거래일(_CME)
    엔진.run.day_key = _자정(15)
    엔진.note_open(해외, _때(7, 0, day=16))

    _틱(엔진, _때(0, 30, day=17), 0.65, 해외)  # KST 자정 뒤지만 16일 거래일

    assert 엔진.run.day_key == _자정(16)


def test_지난_봉_셈의_일봉도_실행_엔진과_같은_답이다(monkeypatch):
    값들 = [99.0, 99.0, 101.0, 100.5, 98.0, 102.0, 101.0, 99.0]
    봉들 = [
        Bar(_때(0, 0, day=1 + i), v, v + 0.5, v - 0.5, v, 10) for i, v in enumerate(값들)
    ]

    def 셈():
        return backtest.compute(
            draft=_일봉(stopTicks="", takeTicks="", dailyLoss="1"), market="domestic", code="A7569000",
            session=주간, bars=봉들, tick=0.05, margin=1_000.0,
        )

    빠른 = 셈()

    class 그냥(engine.RunEngine):
        def __init__(self, run, *, every, trading_day=None, **kwargs):
            super().__init__(run, **kwargs)
            self.trading_day = trading_day

    monkeypatch.setattr(backtest, "BacktestEngine", 그냥)
    assert 셈() == 빠른
    assert 빠른["signals"] > 0
