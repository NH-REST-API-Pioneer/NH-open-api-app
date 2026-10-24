"""취소를 냈는데 확인 알림이 안 온 주문 — 대사가 닫습니다(셋 다 맞을 때만).

**계좌에 닿지 않습니다.** 주문·취소는 적기만 하는 가짜 자리이고, 계좌 조회는 가짜로
끼운 답입니다. 표본(해외 모의, 지정가 진입 → 중지 → 주문내역에 없음)을 그대로 짓습니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine as engine_lib, journal as journal_lib, paper, runs, sim
from backend.strategy import service as service_lib
from tests.test_strategy_engine import _넣기, _설정
from tests.test_strategy_service import (
    _계좌보유,
    _계좌주문,
    _마스터,
    _모의목록,
    _모의물음,
    _보내는곳,
    _시간표,
)


class _계좌판:
    """대사가 읽는 계좌 — 시험 도중 바꿀 수 있게 담아 둡니다."""

    def __init__(self) -> None:
        self.orders: list = []
        self.positions: list = []

    def __call__(self, run):
        return {"orders": list(self.orders), "positions": list(self.positions)}


def _증거금_아는_목록(tmp_path, account):
    """계약당 증거금을 아는 모의 실행 목록. 모르면 진입이 한도 검사에서 막힙니다."""
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표([{
            "productCode": "01", "kind": "futures", "session": "day",
            "tick": "0.05", "contractInitialMargin": "2500000",
        }]),
        fetch=lambda run, minutes, count: [],
        account=account,
        sender=_보내는곳(),
        environment=lambda: "paper",
    )


def _걸어_두고_멈춤(tmp_path):
    """지정가 진입이 걸린 뒤 중지해 취소를 냅니다. 계좌는 처음엔 그 주문이 있습니다."""
    계좌 = _계좌판()
    목록 = _증거금_아는_목록(tmp_path, 계좌)
    목록.add(**_모의물음(draft=_설정(orderType="지정가", priceBasis="신호가 − 1틱", fillCond="FAS")))
    엔진 = 목록._engine("run1")
    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)
    (주문,) = 엔진.book.open_orders
    계좌.orders = [_계좌주문(order_no=주문.order_no)]
    목록.pause("run1", 10)
    assert 주문.cancel_sent and 주문.open
    return 목록, 엔진, 주문, 계좌


def _결과줄(목록) -> list[dict]:
    return 목록.journal.read(run_id="run1", kind="order")


def test_취소를_냈고_주문내역에_없고_보유가_맞으면_취소로_닫는다(tmp_path):
    목록, 엔진, 주문, 계좌 = _걸어_두고_멈춤(tmp_path)
    계좌.orders = []  # 계좌 주문내역 어디에도 없음

    줄 = 목록.reconcile("run1", 20)

    assert 줄["state"] != runs.ATTENTION
    assert 주문.status == sim.CANCELLED and not 엔진.book.open_orders
    (결과,) = _결과줄(목록)
    assert 결과["outcome"] == engine_lib.CANCELLED and 결과["closedBy"] == "reconcile"
    assert 결과["why"] == "신규 진입 중지로 취소했습니다", "낸 취소의 까닭 그대로입니다."


def test_취소를_안_낸_주문이_없으면_그대로_불일치다(tmp_path):
    계좌 = _계좌판()
    목록 = _증거금_아는_목록(tmp_path, 계좌)
    목록.add(**_모의물음(draft=_설정(orderType="지정가", priceBasis="신호가 − 1틱", fillCond="FAS")))
    엔진 = 목록._engine("run1")
    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)
    (주문,) = 엔진.book.open_orders

    줄 = 목록.reconcile("run1", 20)

    assert 줄["state"] == runs.ATTENTION and 주문.open
    말들 = [one["text"] for one in 엔진.events]
    assert any(service_lib.WHY_ORDER_GONE.format(no=주문.order_no) in one for one in 말들)


def test_보유가_어긋나면_닫지_않고_불일치다(tmp_path):
    """취소가 닿기 전에 채워졌는데 주문내역이 늦은 경우입니다."""
    목록, 엔진, 주문, 계좌 = _걸어_두고_멈춤(tmp_path)
    계좌.orders = []
    계좌.positions = [_계좌보유(quantity=1)]

    줄 = 목록.reconcile("run1", 20)

    assert 줄["state"] == runs.ATTENTION and 주문.open
    말들 = " ".join(one["text"] for one in 엔진.events)
    assert service_lib.WHY_ORDER_GONE.format(no=주문.order_no) in 말들


def test_다른_종목_줄에라도_그_번호가_있으면_닫지_않는다(tmp_path):
    목록, 엔진, 주문, 계좌 = _걸어_두고_멈춤(tmp_path)
    계좌.orders = [_계좌주문(order_no=주문.order_no, code="다른종목")]

    줄 = 목록.reconcile("run1", 20)

    assert 줄["state"] == runs.ATTENTION and 주문.open


def test_표본_재현_확인_필요에서_확인하면_중지로_내려가_끝내고_지운다(tmp_path):
    목록, 엔진, 주문, 계좌 = _걸어_두고_멈춤(tmp_path)
    계좌.orders = []
    엔진.run.state = runs.ATTENTION  # 대사가 「확인 필요」로 남긴 상태

    assert 목록.acknowledge("run1", 30)["state"] == runs.PAUSED
    assert 목록.end("run1", 40)["state"] == runs.ENDED
    목록.delete("run1")
    assert 목록.rows() == []


def test_원주문번호로_온_취소_확인으로_닫고_체결은_그_길로_짝짓지_않는다():
    run = runs.Run(
        id="r1", version_id="v1", code="MESZ26", session="overseas", market="overseas",
        state=runs.ARMED, qty=2, cash=1.0, draft=_설정(), mode=runs.SIM, approved_at=1, environment="paper",
    )
    보냄 = type("S", (), {"order": lambda self, **물음: {"id": "0000000227"}})()
    장부 = sim.SimBroker(run, sender=보냄, environment=lambda: "paper")
    주문 = 장부.place("o1", side=paper.BUY, quantity=2, order_type="지정가", price=7765.75, at=1)

    체결 = 장부.on_order({"id": "0000000300", "originalOrderNo": "0000000227", "filled": 1, "cancelled": 0}, at=2)
    assert 체결 == [] and 주문.filled == 0 and 주문.open, "새 번호의 체결 알림은 원주문번호로 짝짓지 않습니다."

    장부.on_order({"id": "0000000301", "originalOrderNo": "0000000227", "status": "confirmed", "cancelled": 1}, at=3)
    assert 주문.open, "남은 수량을 다 덮지 않는 취소 수량이면 닫지 않습니다."

    장부.on_order({"id": "0000000302", "originalOrderNo": "0000000227", "status": "confirmed", "cancelled": 2}, at=4)
    assert 주문.status == sim.CANCELLED and 주문.closed_by == ""


def test_되살린_계좌_실행은_지금처럼_대사_뒤_끝난다(tmp_path):
    runs.RunStore(tmp_path / "runs.json").save([
        runs.Run(id="run1", version_id="v1", code="A7569000", session="domestic-day", market="domestic",
                 state=runs.HOLDING, draft=_설정(), mode=runs.SIM, approved_at=1, environment="paper")
    ])
    목록 = _모의목록(tmp_path)

    assert 목록.reconcile("run1", 10)["state"] == runs.ENDED
