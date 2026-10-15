"""기록 파일의 거래일 잔고 줄과 주문 결과 줄 — 엔진이 쓰는 자리.

봉과 호가를 손으로 지어 넣고 엔진이 기록에 무엇을 남기는지 봅니다. 모의
계좌는 계좌에 닿지 않는 대역(`_보내는곳`)을 끼운 모의 장부로 돕니다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.sessions.hours import KST
from backend.strategy import engine, paper, runs, sim

주간 = "domestic-day"
지연 = int(paper.DELAY_SECONDS * 1000)


def _때(hour: int, minute: int, second: int = 0, day: int = 17) -> int:
    return int(datetime(2026, 9, day, hour, minute, second, tzinfo=KST).timestamp() * 1000)


def _설정(**aux) -> dict:
    묶음 = {
        "orderType": "시장가",
        "priceBasis": "신호가",
        "stopBasis": "",
        "fillCond": "",
        "stopTicks": "100",
        "takeTicks": "100",
        "perOrder": "1",
        "maxHold": "5",
        "session": "국내 주간",
        "addWhileOpen": False,
        "dailyLoss": "300000",
        "marginBudget": "1000000",
    }
    묶음.update(aux)
    return {
        "memo": "",
        "baseBar": "1분봉",
        "evalMode": "마감",
        "rules": {
            "buyEntry": {
                "on": True,
                "steps": [
                    {
                        "id": "s1",
                        "join": "all",
                        "withinBars": 0,
                        "conds": [{"id": "c1", "left": "close", "op": "gt", "rightKind": "number", "right": "100"}],
                    }
                ],
            },
            "sellEntry": {"on": False, "steps": []},
            "buyExit": {"on": False, "steps": []},
            "sellExit": {"on": False, "steps": []},
        },
        "aux": 묶음,
    }


def _엔진(draft=None, book=None, **덮어쓰기) -> tuple[engine.RunEngine, list]:
    물음 = {
        "id": "r1",
        "version_id": "v1",
        "code": "A7569000",
        "session": 주간,
        "market": "domestic",
        "state": runs.ARMED,
        "qty": 1,
        "cash": 10_000_000.0,
        "multiplier": 1.0,
        "draft": draft if draft is not None else _설정(),
    }
    물음.update(덮어쓰기)
    기록: list = []
    엔진 = engine.RunEngine(
        runs.Run(**물음), tick=0.05, book=book, record=lambda kind, row: 기록.append((kind, dict(row)))
    )
    return 엔진, 기록


def _줄(기록: list, kind: str) -> list[dict]:
    return [row for 갈래, row in 기록 if 갈래 == kind]


def _체결(엔진, 때: int, price: float) -> None:
    엔진.on_trade({"price": price, "quantity": 1, "timestamp": 때}, 주간, at=때)


def _호가(ask: float, bid: float, quantity: int = 9) -> dict:
    return {"asks": [{"price": ask, "quantity": quantity}], "bids": [{"price": bid, "quantity": quantity}]}


def _사서_든다(엔진, day: int = 17) -> int:
    """10:00 99 → 10:01 101 → 10:02 101 로 진입하고 101.5 에 채웁니다."""
    _체결(엔진, _때(10, 0, day=day), 99.0)
    _체결(엔진, _때(10, 1, day=day), 101.0)
    _체결(엔진, _때(10, 2, day=day), 101.0)
    때 = _때(10, 2, day=day) + 지연
    엔진.on_book(_호가(101.5, 101.0), at=때)
    assert 엔진.ledger.position.quantity == 1
    return 때


# ── 거래일 잔고 줄 ───────────────────────────────────────


def test_세션이_끝나면_그_거래일의_잔고_줄을_한_번_쓴다():
    엔진, 기록 = _엔진()
    때 = _사서_든다(엔진)
    _체결(엔진, 때 + 10, 102.0)

    엔진.close_session(_때(15, 45))
    _체결(엔진, _때(10, 0, day=18), 103.0)
    _체결(엔진, _때(10, 1, day=18), 103.0)  # 다음 거래일 첫 봉이 닫힘

    (줄,) = _줄(기록, engine.DAY_ROW)
    assert 줄["day"] == "2026-09-17" and 줄["late"] is False
    assert 줄["position"] == 1 and 줄["avgPrice"] == 101.5
    assert 줄["closePrice"] == 102.0
    assert 줄["unrealized"] == pytest.approx(0.5)
    assert 줄["equity"] == pytest.approx(줄["realized"] - 줄["fee"] + 줄["unrealized"])


def test_세션_끝을_못_받은_날은_다음_거래일_첫_봉에서_늦게_쓴다():
    """값은 앞 봉을 닫을 때 잡아 둔 것입니다 — 새 날의 가격과 체결이 섞이지 않습니다."""
    엔진, 기록 = _엔진(_설정(stopTicks="2"), fee_per_contract=100.0)
    때 = _사서_든다(엔진)
    _체결(엔진, 때 + 10, 102.0)  # 17일 마지막 봉(10:02)의 종가

    # 18일 첫 체결 — 17일 봉을 닫고, 손절선(101.4)을 넘겨 청산을 냅니다.
    첫 = _때(9, 0, day=18)
    _체결(엔진, 첫, 101.0)
    엔진.on_book(_호가(101.5, 101.0), at=첫 + 지연)
    assert 엔진.ledger.position.quantity == 0 and 엔진.ledger.realized < 0
    _체결(엔진, _때(9, 1, day=18), 101.0)  # 18일 첫 봉이 닫힘 — 여기서 17일 줄을 씀

    (줄,) = _줄(기록, engine.DAY_ROW)
    assert 줄["day"] == "2026-09-17" and 줄["late"] is True
    assert 줄["closePrice"] == 102.0, "새 날 첫 체결가(101.0)가 아니라 전날 마지막 봉 종가입니다."
    assert 줄["unrealized"] == pytest.approx(0.5)
    assert 줄["realized"] == 0.0, "새 날의 청산 손실이 섞이지 않습니다."
    assert 줄["fee"] == 100.0, "진입 수수료만입니다(새 날 청산 수수료 없음)."
    assert 줄["position"] == 1


def test_증거금_사용률은_그날_최대이고_예산이_없으면_없음이다():
    엔진, 기록 = _엔진(margin=100_000.0, margin_budget=1_000_000.0)
    _사서_든다(엔진)
    엔진.close_session(_때(15, 45))
    (줄,) = _줄(기록, engine.DAY_ROW)
    assert 줄["marginPeak"] == pytest.approx(0.1), "1계약 × 10만 ÷ 100만."

    없음, 기록2 = _엔진(margin=100_000.0, margin_budget=None)
    _사서_든다(없음)
    없음.close_session(_때(15, 45))
    (줄2,) = _줄(기록2, engine.DAY_ROW)
    assert 줄2["marginPeak"] is None, "0 이 아니라 모름입니다."


def test_봉이_하나도_안_닫힌_날은_잔고_줄을_안_쓴다():
    엔진, 기록 = _엔진()

    엔진.close_session(_때(15, 45))

    assert _줄(기록, engine.DAY_ROW) == []


# ── 주문 결과 줄 ─────────────────────────────────────────


def test_채워진_주문은_체결_결과_줄을_남긴다():
    엔진, 기록 = _엔진()
    _사서_든다(엔진)

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.FILLED
    assert (줄["intent"], 줄["reason"], 줄["quantity"], 줄["filled"]) == ("entry", "signal", 1, 1)
    assert 줄["orderNo"] is None and 줄["serverMessage"] is None


def test_세션이_끝나_거둔_종이_주문은_취소_결과이고_까닭은_앱의_문장이다():
    엔진, 기록 = _엔진(_설정(orderType="지정가"))
    _체결(엔진, _때(10, 0), 99.0)
    _체결(엔진, _때(10, 1), 101.0)
    _체결(엔진, _때(10, 2), 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)

    엔진.close_session(_때(15, 45))

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.CANCELLED
    assert 줄["why"] == "세션이 끝나 취소했습니다"
    assert 줄["serverStatus"] is None and 줄["serverMessage"] is None


def test_일부만_채워지고_닫힌_주문은_부분_결과다():
    엔진, 기록 = _엔진(qty=2)
    _체결(엔진, _때(10, 0), 99.0)
    _체결(엔진, _때(10, 1), 101.0)
    _체결(엔진, _때(10, 2), 101.0)
    엔진.on_book(_호가(101.5, 101.0, quantity=1), at=_때(10, 2) + 지연)

    엔진.close_session(_때(15, 45))

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert (줄["outcome"], 줄["filled"], 줄["quantity"]) == (engine.PARTIAL, 1, 2)


class _막는장부:
    orders: list = []
    last_price = None
    gap = False
    open_orders: list = []

    def place(self, order_id, **물음):
        raise sim.SimRefused(runs.WHY_NOT_APPROVED)

    def on_trade(self, trade, *, at):
        return []

    def on_book(self, book, *, at):
        return []

    def cancel_open(self, reason):
        return []


def test_접수_전에_막힌_주문도_결과_줄이다():
    엔진, 기록 = _엔진(book=_막는장부())
    _체결(엔진, _때(10, 0), 99.0)
    _체결(엔진, _때(10, 1), 101.0)
    _체결(엔진, _때(10, 2), 101.0)

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.REFUSED
    assert 줄["why"] == runs.WHY_NOT_APPROVED and 줄["orderNo"] is None
    assert 줄["serverMessage"] is None


class _보내는곳:
    """주문을 받아 적기만 하는 자리. 계좌에 닿지 않습니다."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def order(self, **물음):
        return {"id": "0000012345"}

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": order.order_no}


def _모의엔진() -> tuple[engine.RunEngine, list]:
    실행 = {"mode": runs.SIM, "approved_at": 1_000, "environment": "paper"}
    run_args = {
        "id": "r1",
        "version_id": "v1",
        "code": "A7569000",
        "session": 주간,
        "market": "domestic",
        "state": runs.ARMED,
        "qty": 1,
        "cash": 10_000_000.0,
        "multiplier": 1.0,
        "draft": _설정(orderType="지정가"),
        **실행,
    }
    run = runs.Run(**run_args)
    장부 = sim.SimBroker(run, sender=_보내는곳(), environment=lambda: "paper")
    기록: list = []
    엔진 = engine.RunEngine(run, tick=0.05, book=장부, record=lambda kind, row: 기록.append((kind, dict(row))))
    _체결(엔진, _때(10, 0), 99.0)
    _체결(엔진, _때(10, 1), 101.0)
    _체결(엔진, _때(10, 2), 101.0)
    assert len(장부.orders) == 1
    return 엔진, 기록


def test_모의_계좌가_거절하면_거절_결과이고_서버_문장은_비어_있다():
    엔진, 기록 = _모의엔진()

    엔진.on_order({"id": "0000012345", "status": "rejected", "filled": 0}, at=_때(10, 3))

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.REJECTED
    assert 줄["serverStatus"] == "rejected" and 줄["serverMessage"] is None
    assert 줄["orderNo"] == "0000012345"
    (주문,) = 엔진.book.orders
    assert 주문.status == sim.CANCELLED, "주문 상태 판정은 전과 같습니다."


def test_모의_계좌가_취소로_답하면_취소_결과다():
    엔진, 기록 = _모의엔진()

    엔진.on_order({"id": "0000012345", "status": "cancelled", "filled": 0}, at=_때(10, 3))

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert (줄["outcome"], 줄["serverStatus"]) == (engine.CANCELLED, "cancelled")


def test_모의_중지_취소는_계좌_확인이_온_뒤에_결과를_쓴다():
    """보낸 순간에 「취소」로 적으면, 확인 전에 체결되거나 거절된 주문이 틀린 결과로 남습니다."""
    엔진, 기록 = _모의엔진()
    (주문,) = 엔진.book.orders
    assert 엔진.book.cancel(주문, "신규 진입 중지로 취소했습니다")

    엔진._forget(주문.id, _때(10, 3))
    assert _줄(기록, engine.ORDER_ROW) == [], "확인 전에는 쓰지 않습니다."

    엔진.on_order({"id": "0000012345", "status": "filled", "filled": 1, "fillPrice": 101.0}, at=_때(10, 4))

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.FILLED, "확인 전에 채워졌으면 채워진 결과입니다."
    assert 엔진._cancel_wait == {}


def test_종이_중지_취소는_그_자리에서_결과를_쓴다():
    엔진, 기록 = _엔진(_설정(orderType="지정가"))
    _체결(엔진, _때(10, 0), 99.0)
    _체결(엔진, _때(10, 1), 101.0)
    _체결(엔진, _때(10, 2), 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)
    (주문,) = 엔진.book.open_orders

    assert 엔진.book.cancel(주문, "신규 진입 중지로 취소했습니다")
    엔진._forget(주문.id, _때(10, 3))

    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.CANCELLED and 줄["why"] == "신규 진입 중지로 취소했습니다"


def test_알림의_상태_글자_원문을_남긴다():
    run = runs.Run(id="r1", version_id="v1", code="A", session=주간, market="domestic", mode=runs.SIM, approved_at=1, environment="paper")
    장부 = sim.SimBroker(run, sender=_보내는곳(), environment=lambda: "paper")
    주문 = 장부.place("o1", side=paper.BUY, quantity=1, order_type="지정가", price=100.0, at=1)

    장부.on_order({"id": 주문.order_no, "status": "rejected", "filled": 0}, at=2)

    assert 주문.last_status == "rejected" and 주문.status == sim.CANCELLED


def test_서비스의_중지_경로도_모의_취소는_확인_뒤에_쓴다(tmp_path):
    """중지 단추가 지나는 서비스 경로(`RunService.pause`)에서도 확인 전에는 결과 줄이 없습니다."""
    from backend.strategy import journal as journal_lib
    from backend.strategy import service as service_lib

    엔진, 기록 = _모의엔진()
    목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        fetch=lambda *args: [],
    )
    목록._loaded = True
    목록._engines[엔진.run.id] = 엔진
    목록._order.append(엔진.run.id)

    목록.pause(엔진.run.id, _때(10, 3))

    assert 엔진.book.sender.cancelled == ["0000012345"], "취소는 보냈습니다."
    assert _줄(기록, engine.ORDER_ROW) == [], "확인 전에는 쓰지 않습니다."
    엔진.on_order({"id": "0000012345", "status": "cancelled", "filled": 0}, at=_때(10, 4))
    (줄,) = _줄(기록, engine.ORDER_ROW)
    assert 줄["outcome"] == engine.CANCELLED and 줄["why"] == "신규 진입 중지로 취소했습니다"
