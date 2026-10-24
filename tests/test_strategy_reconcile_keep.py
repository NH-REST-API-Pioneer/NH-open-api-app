"""재접속 뒤 대사가 맞으면 대사에 들기 직전 상태로 돌아갑니다.

감시 중이던 실행은 감시를 이어 가고, 사용자가 중지해 둔 실행은 중지 그대로,
주문이 나가 있던 실행은 그 상태 그대로입니다. 어긋나면 확인을 기다리고, 앱을
다시 켜 되살린 실행은 대사 뒤 끝납니다(자동 재개 없음).

**계좌에도 NH선물 서버에도 닿지 않습니다.** 계좌 조회와 봉 조회는 가짜입니다.
"""
from __future__ import annotations

import pytest

from backend.realtime.link import LIVE
from backend.strategy import engine as engine_lib, pump as pump_lib, runs, service as service_lib
from tests.test_strategy_service import _계좌, _계좌보유, _모의목록, _모의물음

시작 = 9_000


def _코드들() -> set[str]:
    return {service_lib.RECONCILE_RESUME_REASON, service_lib.RECONCILE_KEPT_PAUSED_REASON}


def _세운(tmp_path, **물음):
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음(**물음))
    return 실행목록, 실행목록._engine("run1")


def _재접속_대사(실행목록, 엔진) -> dict:
    """펌프가 재접속 뒤 청하는 대사(first=False)."""
    return 실행목록.reconcile(엔진.run.id, 시작)


@pytest.mark.parametrize(
    ("전", "글", "코드"),
    [
        (runs.ARMED, service_lib.RECONCILE_RESUME, service_lib.RECONCILE_RESUME_REASON),
        (runs.HOLDING, service_lib.RECONCILE_RESUME, service_lib.RECONCILE_RESUME_REASON),
        (runs.PAUSED, service_lib.RECONCILE_KEPT_PAUSED, service_lib.RECONCILE_KEPT_PAUSED_REASON),
    ],
)
def test_대사가_맞으면_대사_전_상태로_돌아간다(tmp_path, 전, 글, 코드):
    실행목록, 엔진 = _세운(tmp_path)
    엔진.run.state = 전  # 그 상태에서 연결이 끊겼다 붙은 자리입니다.
    if 전 == runs.HOLDING:
        _보유_넣기(엔진)
        실행목록._account = _계좌(positions=[_계좌보유()])

    줄 = _재접속_대사(실행목록, 엔진)

    assert 줄["state"] == 전
    마지막 = 엔진.events[-1]
    assert (마지막["kind"], 마지막["text"], 마지막["reason"]) == (engine_lib.STATE, 글, 코드)
    assert "why" not in 마지막, "코드는 `reason` 한 칸에만 싣습니다."
    assert service_lib.WHY_NO_RESUME not in [one["text"] for one in 엔진.events]


def _보유_넣기(엔진) -> None:
    from backend.strategy import paper

    엔진._take([{"orderId": "in", "side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1}], 1)


# ── 주문이 나가 있던 실행: 그 주문이 아직 열려 있을 때만 그대로 ──────


class _번호매김:
    """주문마다 새 번호를 주는 보내는 자리. 계좌에 닿지 않습니다."""

    def __init__(self):
        self.sent: list[dict] = []

    def order(self, **물음):
        self.sent.append(물음)
        return {"id": f"{len(self.sent):010d}"}

    def cancel(self, *, run, order):
        return {"id": order.order_no}


def _주문_세운(tmp_path):
    보냄 = _번호매김()
    실행목록 = _모의목록(tmp_path, sender=보냄)
    실행목록.add(**_모의물음())
    엔진 = 실행목록._engine("run1")
    엔진.book.last_price = 100.0
    return 실행목록, 엔진, 보냄


def _체결_알림(엔진, order_no: str, price: float) -> None:
    엔진.on_order(
        {"id": order_no, "status": "filled", "filled": 1, "remaining": 0, "fillPrice": price}, at=시작
    )


def _맞춰_보는_동안(실행목록, 할일) -> None:
    """대사의 계좌 조회 사이에 할 일을 끼우고, 계좌는 맞는 것으로 답합니다."""

    def 맞춰_보기(made, at):
        할일(made)
        return []

    실행목록._compare = 맞춰_보기


def test_진입_주문이_열려_있으면_진입_주문_중으로_돌아간다(tmp_path):
    from backend.strategy import paper

    실행목록, 엔진, _ = _주문_세운(tmp_path)
    엔진._send(paper.BUY, 1, 100.0, "entry", 시작)
    assert 엔진.run.state == runs.ENTERING
    _맞춰_보는_동안(실행목록, lambda made: None)

    assert _재접속_대사(실행목록, 엔진)["state"] == runs.ENTERING


def test_대사_도중에_진입이_채워지면_보유로_돌아가_손절을_본다(tmp_path):
    from backend.strategy import paper

    실행목록, 엔진, 보냄 = _주문_세운(tmp_path)
    엔진._send(paper.BUY, 1, 100.0, "entry", 시작)
    번호 = 엔진.book.orders[-1].order_no
    _맞춰_보는_동안(실행목록, lambda made: _체결_알림(made, 번호, 100.0))

    줄 = _재접속_대사(실행목록, 엔진)

    assert 줄["state"] == runs.HOLDING
    assert 엔진.ledger.position.quantity == 1
    낸수 = len(보냄.sent)
    엔진.on_trade({"timestamp": 시작 + 1, "price": 90.0, "quantity": 1}, "domestic-day", at=시작 + 1)
    assert len(보냄.sent) == 낸수 + 1, "손절선 아래 체결에 청산 주문이 나갑니다."
    assert 엔진.run.state == runs.EXITING


def test_대사_도중에_진입이_일부만_채워져도_보유로_돌아가_손절을_본다(tmp_path):
    """진입 주문이 남아 있어도 보유가 생겼으면 보유입니다 — 평소 부분 체결과 같습니다."""
    from backend.strategy import paper

    실행목록, 엔진, 보냄 = _주문_세운(tmp_path)
    엔진._send(paper.BUY, 2, 100.0, "entry", 시작)
    번호 = 엔진.book.orders[-1].order_no
    _맞춰_보는_동안(
        실행목록,
        lambda made: made.on_order(
            {"id": 번호, "status": "partial", "filled": 1, "remaining": 1, "fillPrice": 100.0}, at=시작
        ),
    )

    줄 = _재접속_대사(실행목록, 엔진)

    assert 엔진.open_entry == 1, "진입 주문이 아직 열려 있습니다."
    assert 줄["state"] == runs.HOLDING
    낸수 = len(보냄.sent)
    엔진.on_trade({"timestamp": 시작 + 1, "price": 90.0, "quantity": 1}, "domestic-day", at=시작 + 1)
    assert len(보냄.sent) > 낸수, "손절 감시가 돕니다."


def _취소_알림(엔진, order_no: str, quantity: int = 1) -> None:
    엔진.on_order(
        {"id": order_no, "status": "cancelled", "filled": 0, "remaining": quantity}, at=시작
    )


@pytest.mark.parametrize(("중지", "끝"), [(False, runs.ARMED), (True, runs.PAUSED)])
def test_대사_도중에_진입이_취소되면_감시로_돌아간다(tmp_path, 중지, 끝):
    """보유도 열린 진입 주문도 없으면 감시입니다. 중지를 눌러 두었으면 중지입니다."""
    from backend.strategy import paper

    실행목록, 엔진, _ = _주문_세운(tmp_path)
    엔진._send(paper.BUY, 1, 100.0, "entry", 시작)
    번호 = 엔진.book.orders[-1].order_no
    엔진.run.pause_requested = 중지
    _맞춰_보는_동안(실행목록, lambda made: _취소_알림(made, 번호))

    줄 = _재접속_대사(실행목록, 엔진)

    assert 엔진.open_entry == 0
    assert 엔진.ledger.position.quantity == 0
    assert 줄["state"] == 끝


def test_청산_주문이_열려_있으면_청산_주문_중으로_돌아간다(tmp_path):
    실행목록, 엔진, _ = _주문_세운(tmp_path)
    _보유_넣기(엔진)
    엔진.run.state = runs.HOLDING
    엔진._close(1, 99.0, "stop", 시작)
    assert 엔진.run.state == runs.EXITING
    _맞춰_보는_동안(실행목록, lambda made: None)

    assert _재접속_대사(실행목록, 엔진)["state"] == runs.EXITING


def test_대사_도중에_청산이_채워지면_감시로_돌아간다(tmp_path):
    실행목록, 엔진, _ = _주문_세운(tmp_path)
    _보유_넣기(엔진)
    엔진.run.state = runs.HOLDING
    엔진._close(1, 99.0, "stop", 시작)
    번호 = 엔진.book.orders[-1].order_no
    _맞춰_보는_동안(실행목록, lambda made: _체결_알림(made, 번호, 99.0))

    줄 = _재접속_대사(실행목록, 엔진)

    assert 줄["state"] == runs.ARMED
    assert 엔진.ledger.position.quantity == 0


def test_대사_도중에_청산이_취소되면_보유로_돌아가_손절을_본다(tmp_path):
    실행목록, 엔진, 보냄 = _주문_세운(tmp_path)
    _보유_넣기(엔진)
    엔진.run.state = runs.HOLDING
    엔진._close(1, 99.0, "stop", 시작)
    assert 엔진.run.state == runs.EXITING
    번호 = 엔진.book.orders[-1].order_no
    _맞춰_보는_동안(실행목록, lambda made: _취소_알림(made, 번호))

    줄 = _재접속_대사(실행목록, 엔진)

    assert 엔진.open_exit == 0
    assert 엔진.ledger.position.quantity == 1
    assert 줄["state"] == runs.HOLDING
    낸수 = len(보냄.sent)
    엔진.on_trade({"timestamp": 시작 + 1, "price": 90.0, "quantity": 1}, "domestic-day", at=시작 + 1)
    assert len(보냄.sent) == 낸수 + 1, "손절선 아래 체결에 청산 주문이 다시 나갑니다."
    assert 엔진.run.state == runs.EXITING


def test_대사_한_번에_한_줄이다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    앞 = len(엔진.events)

    _재접속_대사(실행목록, 엔진)

    새 = [one["text"] for one in 엔진.events[앞:]]
    assert 새 == [service_lib.RECONCILE_START, service_lib.RECONCILE_RESUME]


def test_대사가_어긋나면_확인을_기다린다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    실행목록._account = _계좌(positions=[_계좌보유()])  # 장부에 없는 보유

    줄 = _재접속_대사(실행목록, 엔진)

    assert 줄["state"] == runs.ATTENTION
    assert not [one for one in 엔진.events if one.get("reason") in _코드들()]


def test_처음_시작의_대사는_그대로다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)

    assert 엔진.run.state == runs.ARMED
    assert service_lib.RECONCILE_DONE in [one["text"] for one in 엔진.events]
    assert not [one for one in 엔진.events if one.get("reason") in _코드들()]


def test_다시_켜_되살린_실행은_대사_뒤_끝난다(tmp_path):
    """앱이 꺼져 있던 동안 손절 감시가 돌지 않았습니다 — 자동 재개는 없습니다."""
    _세운(tmp_path)
    다시 = _모의목록(tmp_path)
    다시.load()

    줄 = 다시.reconcile("run1", 시작)

    assert 줄["state"] == runs.ENDED
    assert service_lib.WHY_RESTORED_END in [one["text"] for one in 다시._engine("run1").events]


def test_대사_중에_또_대사가_와도_대사_전_상태를_덮지_않는다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    엔진.run.move(runs.RECONCILE)
    엔진.run.move(runs.RECONCILE)  # 대사 중에 또

    assert 엔진.run.before_reconcile == runs.ARMED
    assert _재접속_대사(실행목록, 엔진)["state"] == runs.ARMED


@pytest.mark.parametrize("전", ["", runs.RECONCILING])
def test_대사_전_상태를_모르는_채_대사_중에_남은_실행은_중지로_내려놓는다(tmp_path, 전):
    """앞 대사가 중간에 멈춰 「대사 중」에 남은 실행입니다. 감시 고리가 끝없이 다시 집지 않습니다."""
    실행목록, 엔진 = _세운(tmp_path)
    엔진.run.state = runs.RECONCILING
    엔진.run.before_reconcile = 전
    assert 실행목록.reconcile_wanted() == ["run1"]

    for run_id in 실행목록.reconcile_wanted():
        실행목록.reconcile(run_id, 시작)

    assert 엔진.run.state == runs.PAUSED
    assert service_lib.WHY_NO_RESUME in [one["text"] for one in 엔진.events]
    assert 실행목록.reconcile_wanted() == [], "다음 박자에는 집지 않습니다."


def test_돌아간_줄의_코드는_둘뿐이고_다른_코드와_겹치지_않는다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    _재접속_대사(실행목록, 엔진)
    엔진.run.state = runs.PAUSED
    _재접속_대사(실행목록, 엔진)

    본것 = {
        one["reason"] for one in 엔진.events if one["kind"] == engine_lib.STATE and "reason" in one
    }

    assert 본것 == _코드들()
    assert not [one for one in 엔진.events if one["kind"] == engine_lib.STATE and "why" in one]
    다른것 = set(engine_lib.BLOCK_REASONS.values()) | {engine_lib.OTHER_REASON}
    assert not _코드들() & (다른것 | {service_lib.ACCOUNT_LOSS_REASON})


# ── 공백 규칙은 그대로: 재접속 뒤 첫 봉 마감 전에는 틱 판정을 쉰다 ──


def test_재접속_뒤_감시로_돌아가도_첫_봉_마감_전에는_틱_판정을_쉰다(tmp_path):
    from tests.test_strategy_tick_eval import _설정 as _틱설정, _시각, _신호, _준비, _체결
    from tests.test_strategy_pump import _허브

    실행목록, 엔진 = _세운(tmp_path, draft=_틱설정("틱", fillCond="FAS"))
    엔진.run.margin = None  # 진입은 막고 신호만 셉니다.
    펌프 = pump_lib.RunPump(실행목록, hub=_허브(), auction=lambda *_, **__: None)
    _준비(펌프)
    펌프.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=_시각(2, 5))
    for run_id in 펌프.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=_시각(2, 6)
    ):
        실행목록.refill(run_id)
        실행목록.reconcile(run_id, _시각(2, 6))
    assert 엔진.run.state == runs.ARMED, "대사가 맞아 감시로 돌아갔습니다."

    _체결(펌프, _시각(2, 10), 100.5)
    assert _신호(엔진) == [], "다시 붙은 봉 안에서는 쉽니다."
    _체결(펌프, _시각(2, 50), 99.0)
    _체결(펌프, _시각(3, 10), 100.5)

    assert [one["time"] for one in _신호(엔진)] == [_시각(3, 10)]
