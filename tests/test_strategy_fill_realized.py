"""체결 줄의 실현손익(`realized`) — 그 체결로 장부 실현손익이 늘어난 몫.

**계좌에 닿지 않습니다.** 체결은 손으로 넣고, 계좌 갈래는 주문을 적기만 하는 가짜
자리로 돌립니다.
"""
from __future__ import annotations

import json

import pytest

from backend.strategy import backtest, engine, journal as journal_lib, paper, pump as pump_lib, runs, sim
from tests.test_strategy_backtest import _물결, _셈
from tests.test_strategy_engine import _설정, _엔진

매수, 매도 = paper.BUY, paper.SELL


def _체결(엔진: engine.RunEngine, side: str, quantity: int, price: float, at: int) -> dict:
    엔진._take([{"orderId": f"o{at}", "side": side, "quantity": quantity, "price": price, "time": at}], at)
    return 엔진.fills[-1]


def test_진입은_null_이고_부분_청산은_조각마다_그_몫이다():
    엔진 = _엔진(_설정())

    assert _체결(엔진, 매수, 2, 100.0, 1)["realized"] is None
    첫 = _체결(엔진, 매도, 1, 110.0, 2)["realized"]
    둘 = _체결(엔진, 매도, 1, 105.0, 3)["realized"]

    assert (첫, 둘) == (pytest.approx(10.0), pytest.approx(5.0))
    assert 첫 + 둘 == pytest.approx(엔진.ledger.realized), "체결 줄을 더하면 장부 누계입니다."


def test_본전_청산은_0_이다():
    엔진 = _엔진(_설정())
    _체결(엔진, 매수, 1, 100.0, 1)

    줄 = _체결(엔진, 매도, 1, 100.0, 2)

    assert 줄["realized"] == 0.0 and 줄["realized"] is not None


def test_뒤집기는_닫은_몫만이다():
    엔진 = _엔진(_설정())
    _체결(엔진, 매수, 1, 100.0, 1)

    줄 = _체결(엔진, 매도, 3, 104.0, 2)

    assert 줄["realized"] == pytest.approx(4.0), "닫힌 1계약 몫만 — 새로 연 2계약은 안 듭니다."
    assert 엔진.ledger.position.quantity == -2


def test_승수를_곱하고_수수료는_빼지_않는다():
    엔진 = _엔진(_설정(), multiplier=250_000.0, fee_per_contract=500.0)
    _체결(엔진, 매도, 1, 400.0, 1)

    줄 = _체결(엔진, 매수, 1, 399.5, 2)

    assert 줄["realized"] == pytest.approx(0.5 * 250_000.0)
    assert 줄["fee"] == 500.0, "수수료는 따로 칸에 있습니다."


def test_다시_더해_들어간_거래도_다_닫히면_체결_합이_거래_총손익이다():
    """체결 줄은 그 순간의 평균가로, 거래 줄은 거래 전체의 평균 진입·청산가로 셉니다.

    평균가 셈은 진입 원가를 그대로 옮겨 가므로, 거래가 다 닫히면 두 셈은 같은 수
    (모든 청산액 − 모든 진입액)입니다. 일부 청산 뒤 다시 더해 들어간 거래도 같습니다.
    """
    기록: list = []
    엔진 = _엔진(_설정())
    엔진.record = lambda kind, row: 기록.append((kind, dict(row)))

    줄들 = [
        _체결(엔진, 매수, 2, 100.0, 1),
        _체결(엔진, 매도, 1, 110.0, 2),
        _체결(엔진, 매수, 1, 120.0, 3),
        _체결(엔진, 매도, 2, 110.0, 4),
    ]

    합 = sum(one["realized"] or 0.0 for one in 줄들)
    (거래,) = [row for kind, row in 기록 if kind == "trade"]
    assert 합 == pytest.approx(엔진.ledger.realized)
    assert 합 == pytest.approx(거래["grossPl"]) == pytest.approx(10.0)


def test_목록_방송_기록이_같은_값이다():
    기록: list = []
    엔진 = _엔진(_설정())
    엔진.record = lambda kind, row: 기록.append((kind, json.loads(json.dumps(row, default=str))))
    _체결(엔진, 매수, 1, 100.0, 1)
    _체결(엔진, 매도, 1, 103.0, 2)

    한벌 = 엔진.snapshot()["fills"][-1]["realized"]
    방송 = pump_lib._fills(엔진)[-1]["realized"]
    (남긴것,) = [row for kind, row in 기록 if kind == engine.FILL and row.get("realized") is not None]

    assert 한벌 == 방송 == 남긴것["realized"] == pytest.approx(3.0)


def test_칸이_없는_옛_체결_줄은_모름이다(tmp_path):
    길 = tmp_path / "trades.jsonl"
    길.write_text(json.dumps({"kind": "fill", "runId": "r1", "price": 100.0, "quantity": 1}) + "\n", encoding="utf-8")

    (줄,) = journal_lib.Journal(길).read(kind="fill")

    assert 줄.get("realized") is None


def test_계좌_갈래도_같은_셈이다():
    보냄 = type("S", (), {"n": 0})()

    def 주문(**물음):
        보냄.n += 1
        return {"id": f"{보냄.n:010d}"}

    보냄.order = 주문
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session="domestic-day", market="domestic",
        state=runs.ARMED, qty=1, cash=1.0, draft=_설정(), mode=runs.SIM, approved_at=1, environment="paper",
    )
    엔진 = engine.RunEngine(run, tick=0.05, book=sim.SimBroker(run, sender=보냄, environment=lambda: "paper"))
    진입 = 엔진.book.place("e", side=매수, quantity=1, order_type="시장가", at=1)
    엔진.on_order({"id": 진입.order_no, "status": "filled", "filled": 1, "fillPrice": 100.0}, at=2)
    청산 = 엔진.book.place("x", side=매도, quantity=1, order_type="시장가", at=3)
    엔진.on_order({"id": 청산.order_no, "status": "filled", "filled": 1, "fillPrice": 102.5}, at=4)

    assert [one["realized"] for one in 엔진.fills] == [None, pytest.approx(2.5)]


def test_지난_봉_셈의_체결_줄도_실행_엔진과_같다(monkeypatch):
    잡은: dict[str, list] = {}
    원래 = backtest._answer

    def 엿보기(이름):
        def 안(answer, made, fed, minutes):
            잡은[이름] = [one.get("realized") for one in made.fills]
            return 원래(answer, made, fed, minutes)
        return 안

    from tests.test_strategy_backtest import _네_규칙

    monkeypatch.setattr(backtest, "_answer", 엿보기("빠른"))
    _셈(_물결(200), _네_규칙())

    class 그냥(engine.RunEngine):
        def __init__(self, run, *, every, trading_day=None, **kwargs):
            super().__init__(run, **kwargs)
            self.trading_day = trading_day

    monkeypatch.setattr(backtest, "BacktestEngine", 그냥)
    monkeypatch.setattr(backtest, "_answer", 엿보기("그냥"))
    _셈(_물결(200), _네_규칙())

    assert 잡은["빠른"] == 잡은["그냥"]
    assert any(one is not None for one in 잡은["빠른"]), "청산 체결이 있어야 비교가 됩니다."
