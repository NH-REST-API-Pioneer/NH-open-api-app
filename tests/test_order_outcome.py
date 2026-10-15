"""접수 뒤 거절 확인 — 화면 주문 라우트와 전략 실행(`backend/order_outcome.py`).

**계좌에 닿지 않습니다.** 라우트는 API 마다 정해 둔 답을 내는 호출부로, 전략은
결과를 정해 주는 조회 자리로 돌립니다. 기다리는 시간은 0 으로 둡니다.

재현한 일(모의, 2026-10-12)

- 해외 신규 주문이 접수 답(주문번호)을 받았는데 주문내역에 줄이 없고
  주문오류내역에만 「Not Found Symbol」(-2)이 남았습니다.
- 국내 스프레드 취소가 접수 답을 받았는데 주문내역의 그 줄은 상태 9(거부),
  거부코드 0804 「정정취소잔량없음」이었습니다.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import order_outcome
from backend.domestic_futureoption.domestic_routes import get_client as domestic_client
from backend.main import app
from backend.nh_api.client import ApiResult
from backend.nh_api.errors import BusinessError
from backend.overseas_futureoption.overseas_routes import get_client as overseas_client
from backend.strategy import engine as engine_lib
from backend.strategy import paper, pump as pump_lib, runs, sim
from tests.test_strategy_pump import _허브
from tests.test_strategy_service import _모의목록, _모의물음

국내종목 = "A7569000"
시각 = 10_000


@pytest.fixture
def 확인을_켠다(monkeypatch):
    """두 번 확인하고 기다리지 않습니다."""
    monkeypatch.setattr(order_outcome, "WAITS", (0.0, 0.0))
    monkeypatch.setattr(order_outcome, "sleep", lambda _초: None)


class API별호출부:
    """API 마다 정해 둔 답을 내는 호출부. 같은 API 의 답을 차례로 줄 수도 있습니다."""

    def __init__(self, 답들: dict, *, market: str, replay: bool = False):
        self.답들 = {key: list(value) if isinstance(value, list) else [value] for key, value in 답들.items()}
        self.market = market
        self.보낸것: list[tuple[str, dict]] = []
        self.session = SimpleNamespace(
            config=SimpleNamespace(
                default_environment="paper",
                environments={"paper": SimpleNamespace(configured_markets=("domestic", "overseas"))},
            ),
            is_replay=replay,
        )

    def call(self, api_id, payload, environment=None):
        self.보낸것.append((api_id, dict(payload)))
        차례 = self.답들[api_id]
        답 = 차례.pop(0) if len(차례) > 1 else 차례[0]
        if isinstance(답, Exception):
            raise 답
        return ApiResult(
            api_id=api_id, environment="paper", market=self.market, http_status=200, body=답, headers={}
        )

    def 부른(self, api_id: str) -> int:
        return len([one for one in self.보낸것 if one[0] == api_id])


def _부른다(경로: str, 물음: dict, 호출부, 자리) -> dict:
    app.dependency_overrides[자리] = lambda: 호출부
    try:
        응답 = TestClient(app).post(경로, json=물음)
    finally:
        app.dependency_overrides.pop(자리, None)
    assert 응답.status_code == 200, 응답.text
    return 응답.json()


# ── 국내 ──────────────────────────────────────────────


def _국내내역(*줄들: dict) -> dict:
    return {"Occurs1": list(줄들), "nxt_key": ""}


def _국내줄(번호: str, 상태: str, **더) -> dict:
    return {"occurs1_ord_no": 번호, "occurs1_sym": 국내종목, "occurs1_ord_sts": 상태, **더}


def _국내취소물음() -> dict:
    return {"environment": "paper", "sym": 국내종목, "side": "buy", "ord_qty": 1, "org_ord_no": "9"}


def test_국내_취소가_내역에서_거부면_outcome_은_rejected_이고_줄도_거부다(확인을_켠다):
    호출부 = API별호출부(
        {
            "domestic_cancel": {"ord_no": "0000000010", "msg_cd": "", "msg_cntn": ""},
            "domestic_order-history": _국내내역(
                _국내줄("0000000010", "9", occurs1_rejt_rsn_cd="0804", occurs1_ord_rejt_rsn="정정취소잔량없음"),
            ),
        },
        market="domestic",
    )

    몸 = _부른다("/api/domestic/cancel", _국내취소물음(), 호출부, domestic_client)

    assert 몸["accepted"] is True and 몸["id"] == "0000000010", "접수 번호는 그대로 냅니다."
    assert 몸["outcome"] == {
        "state": "rejected",
        "source": "order-history",
        "code": "0804",
        "message": "정정취소잔량없음",
    }
    assert (몸["status"], 몸["statusCode"], 몸["remaining"], 몸["editable"]) == ("rejected", "9", 0, False), (
        "응답의 「cancelled」를 그대로 믿지 않습니다."
    )
    assert 호출부.부른("domestic_order-error") == 0, "국내 주문오류내역은 주문번호가 없어 보지 않습니다."


def test_국내_신규가_내역에_접수로_보이면_accepted_이고_한_번만_묻는다(확인을_켠다):
    호출부 = API별호출부(
        {
            "domestic_order": {"ord_no": "5959762237", "msg_cd": "", "msg_cntn": ""},
            "domestic_order-history": _국내내역(_국내줄("5959762237", "1")),
        },
        market="domestic",
    )

    몸 = _부른다(
        "/api/domestic/order",
        {"environment": "paper", "sym": 국내종목, "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"},
        호출부,
        domestic_client,
    )

    assert 몸["outcome"] == {"state": "accepted", "source": "order-history"}
    assert (몸["status"], 몸["statusCode"]) == ("accepted", "1"), "접수 줄은 그대로입니다."
    assert 호출부.부른("domestic_order-history") == 1


def test_첫_확인에_없으면_한_번_더_보고_그때_찾은_결과를_쓴다(확인을_켠다):
    호출부 = API별호출부(
        {
            "domestic_cancel": {"ord_no": "0000000011"},
            "domestic_order-history": [
                _국내내역(),
                _국내내역(_국내줄("11", "9", occurs1_rejt_rsn_cd="0804", occurs1_ord_rejt_rsn="정정취소잔량없음")),
            ],
        },
        market="domestic",
    )

    몸 = _부른다("/api/domestic/cancel", _국내취소물음(), 호출부, domestic_client)

    assert 몸["outcome"]["state"] == "rejected", "앞자리 0 채움이 달라도 같은 번호입니다."
    assert 호출부.부른("domestic_order-history") == 2


def test_끝까지_못_찾으면_unknown_이고_접수를_뒤집지_않는다(확인을_켠다):
    호출부 = API별호출부(
        {"domestic_cancel": {"ord_no": "0000000012"}, "domestic_order-history": _국내내역()},
        market="domestic",
    )

    몸 = _부른다("/api/domestic/cancel", _국내취소물음(), 호출부, domestic_client)

    assert 몸["outcome"] == {"state": "unknown"}
    assert 몸["accepted"] is True and 몸["status"] == "cancelled"
    assert 호출부.부른("domestic_order-history") == len(order_outcome.WAITS)


def test_확인_조회가_실패해도_unknown_이고_200_이다(확인을_켠다):
    호출부 = API별호출부(
        {
            "domestic_order": {"ord_no": "5959762237"},
            "domestic_order-history": BusinessError("domestic_order-history", "E9", "조회 불가", {}),
        },
        market="domestic",
    )

    몸 = _부른다(
        "/api/domestic/order",
        {"environment": "paper", "sym": 국내종목, "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"},
        호출부,
        domestic_client,
    )

    assert 몸["outcome"] == {"state": "unknown"} and 몸["accepted"] is True
    assert 몸["status"] == "accepted"


def test_재생_모드에서는_확인하지_않는다(확인을_켠다):
    호출부 = API별호출부(
        {"domestic_order": {"ord_no": "5959762237"}, "domestic_order-history": _국내내역()},
        market="domestic",
        replay=True,
    )

    몸 = _부른다(
        "/api/domestic/order",
        {"environment": "paper", "sym": 국내종목, "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"},
        호출부,
        domestic_client,
    )

    assert 몸["outcome"] == {"state": "unknown"}
    assert 호출부.부른("domestic_order-history") == 0


def test_접수_자리의_거절은_전처럼_확인하지_않는다(확인을_켠다):
    호출부 = API별호출부(
        {
            # 호출부가 `msg_cd` 거부를 업무 거부로 올리는 자리를 흉내 냅니다.
            "domestic_order": BusinessError("domestic_order", "5039", "처리불가", {}),
            "domestic_order-history": _국내내역(),
        },
        market="domestic",
    )

    몸 = _부른다(
        "/api/domestic/order",
        {"environment": "paper", "sym": 국내종목, "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"},
        호출부,
        domestic_client,
    )

    assert 몸["accepted"] is False and 몸["code"] == "5039"
    assert "outcome" not in 몸
    assert 호출부.부른("domestic_order-history") == 0


# ── 해외 ──────────────────────────────────────────────


def _해외주문물음(**더) -> dict:
    물음 = {
        "environment": "paper",
        "sym": "VXMV26",
        "side": "buy",
        "qt_div_cd": "1",
        "glb_ord_tp_cd": "1",
        "ord_qty": 1,
    }
    물음.update(더)
    return 물음


def _해외접수(번호: str) -> dict:
    return {"ord_no": 번호, "err_cd": "00000", "err_msg": "주문이 정상처리 되었습니다."}


def _해외오류(*줄들: dict) -> dict:
    return {"Occurs1": list(줄들), "nrec": str(len(줄들)), "nxt_key": ""}


def _해외내역(*줄들: dict) -> dict:
    return {"Occurs1": list(줄들), "nxt_key": ""}


def test_해외_신규가_주문오류내역에만_남으면_rejected_와_서버_문구다(확인을_켠다):
    호출부 = API별호출부(
        {
            "overseas_order": _해외접수("0000000123"),
            "overseas_order-error": _해외오류(
                {
                    "occurs1_seq_no": "1",
                    "occurs1_sym": "VXMV26",
                    "occurs1_ord_no": "0000000123",
                    "occurs1_msg_cd": "-2",
                    "occurs1_err_msg": "Not Found Symbol: VXMV26",
                }
            ),
            "overseas_order-history": _해외내역(),
        },
        market="overseas",
    )

    몸 = _부른다("/api/overseas/order", _해외주문물음(), 호출부, overseas_client)

    assert 몸["accepted"] is True and 몸["id"] == "0000000123"
    assert 몸["outcome"] == {
        "state": "rejected",
        "source": "order-error",
        "code": "-2",
        "message": "Not Found Symbol: VXMV26",
    }
    assert (몸["status"], 몸["statusCode"], 몸["remaining"], 몸["editable"]) == ("rejected", "9", 0, False)


def test_해외_신규가_내역에_있으면_accepted_다(확인을_켠다):
    호출부 = API별호출부(
        {
            "overseas_order": _해외접수("0000000124"),
            "overseas_order-error": _해외오류(),
            "overseas_order-history": _해외내역(
                {"occurs1_ord_no": "0000000124", "occurs1_sym": "VXMV26", "occurs1_ord_sts": "1"}
            ),
        },
        market="overseas",
    )

    몸 = _부른다("/api/overseas/order", _해외주문물음(sym="FESXZ26"), 호출부, overseas_client)

    assert 몸["outcome"] == {"state": "accepted", "source": "order-history"}
    assert 몸["status"] == "accepted"


def test_해외_내역의_거부_줄은_오류코드와_거부사유로_rejected_다(확인을_켠다):
    호출부 = API별호출부(
        {
            "overseas_order": _해외접수("0000000125"),
            "overseas_order-error": _해외오류(),
            "overseas_order-history": _해외내역(
                {
                    "occurs1_ord_no": "0000000125",
                    "occurs1_ord_sts": "9",
                    "occurs1_err_cd": "7001",
                    "occurs1_rejt_rsn": "증거금 부족",
                }
            ),
        },
        market="overseas",
    )

    몸 = _부른다("/api/overseas/order", _해외주문물음(), 호출부, overseas_client)

    assert 몸["outcome"] == {
        "state": "rejected",
        "source": "order-history",
        "code": "7001",
        "message": "증거금 부족",
    }


def test_해외_취소는_원주문도_취소도_내역에_없으면_accepted_다(확인을_켠다):
    호출부 = API별호출부(
        {
            "overseas_order": _해외접수("0000000201"),
            "overseas_order-error": _해외오류(),
            "overseas_order-history": _해외내역(),
        },
        market="overseas",
    )

    몸 = _부른다(
        "/api/overseas/order",
        _해외주문물음(qt_div_cd="3", glb_ord_tp_cd="2", ord_pric="20.5", org_ord_no="200"),
        호출부,
        overseas_client,
    )

    assert 몸["outcome"] == {"state": "accepted", "source": "order-history"}


def test_해외_취소인데_원주문이_아직_보이면_정하지_않는다(확인을_켠다):
    호출부 = API별호출부(
        {
            "overseas_order": _해외접수("0000000202"),
            "overseas_order-error": _해외오류(),
            "overseas_order-history": _해외내역({"occurs1_ord_no": "0000000200", "occurs1_ord_sts": "3"}),
        },
        market="overseas",
    )

    몸 = _부른다(
        "/api/overseas/order",
        _해외주문물음(qt_div_cd="3", glb_ord_tp_cd="2", ord_pric="20.5", org_ord_no="200"),
        호출부,
        overseas_client,
    )

    assert 몸["outcome"] == {"state": "unknown"}
    assert 호출부.부른("overseas_order-error") == 2 and 호출부.부른("overseas_order-history") == 2


def test_해외_신규는_내역에_없다고_접수로_보지_않는다(확인을_켠다):
    """취소만 「없음」을 접수로 봅니다. 신규가 안 보이면 아직 모르는 것입니다."""
    호출부 = API별호출부(
        {
            "overseas_order": _해외접수("0000000126"),
            "overseas_order-error": _해외오류(),
            "overseas_order-history": _해외내역(),
        },
        market="overseas",
    )

    몸 = _부른다("/api/overseas/order", _해외주문물음(), 호출부, overseas_client)

    assert 몸["outcome"] == {"state": "unknown"}


def test_기본_설정은_두_번_확인한다():
    """시험 전체는 확인을 꺼 두므로, 앱이 쓰는 값은 여기서 봅니다."""
    import importlib

    본래 = importlib.reload(order_outcome)
    try:
        assert len(본래.WAITS) == 2 and all(0 < one <= 3 for one in 본래.WAITS)
    finally:
        importlib.reload(order_outcome)


# ── 전략 실행 ──────────────────────────────────────────


class _차례로보내는곳:
    """주문마다 정해 둔 답(주문번호 또는 예외)을 차례로 냅니다."""

    def __init__(self, *답들):
        self.답들 = list(답들)
        self.sent: list[dict] = []
        self.cancelled: list[str] = []

    def order(self, **물음):
        self.sent.append(물음)
        답 = self.답들.pop(0)
        if isinstance(답, Exception):
            raise 답
        return {"id": 답}

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": f"c{order.order_no}"}


def _세운(tmp_path, 보낸곳, *, state: str = runs.ARMED):
    실행목록 = _모의목록(tmp_path, sender=보낸곳)
    실행목록.add(**_모의물음())
    엔진 = 실행목록._engine("run1")
    엔진.run.state = state
    엔진.feed = "live"
    엔진.last_trade_at = 시각 - 1_000
    남김: list = []
    엔진.record = lambda kind, row: 남김.append((kind, row))
    return 실행목록, 엔진, 남김


def _결과줄(남김) -> list[dict]:
    return [row for kind, row in 남김 if kind == engine_lib.ORDER_ROW]


def test_전략_진입이_접수_뒤_거절되면_거절로_닫고_중지한다(tmp_path, 확인을_켠다):
    실행목록, 엔진, 남김 = _세운(tmp_path, _차례로보내는곳("0000000301"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    assert 엔진.run.state == runs.ENTERING

    assert 실행목록.confirm_wanted(시각) == [("run1", "0000000301")]
    실행목록._outcome = lambda run, order: {
        "state": "rejected", "source": "order-error", "code": "-2", "message": "Not Found Symbol: X",
    }
    assert 실행목록.confirm("run1", "0000000301", 시각 + 700) is True

    assert 엔진.run.state == runs.PAUSED
    assert 엔진.book.open_orders == []
    (결과,) = _결과줄(남김)
    assert 결과["outcome"] == engine_lib.REJECTED
    assert (결과["serverStatus"], 결과["serverCode"], 결과["serverMessage"]) == (
        "rejected", "-2", "Not Found Symbol: X",
    )
    assert 결과["orderNo"] == "0000000301"
    사건 = [one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED]
    assert 사건[-1]["text"] == "주문 거부 -2 — Not Found Symbol: X" and 사건[-1]["code"] == "-2"
    assert 실행목록.confirm_wanted(시각 + 10_000) == []


def test_전략_청산이_접수_뒤_거절되면_확인_필요다(tmp_path, 확인을_켠다):
    실행목록, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000302"), state=runs.HOLDING)
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 405.0, "time": 시각})
    엔진._send(paper.SELL, 1, 405.0, "exit", 시각)
    실행목록._outcome = lambda run, order: {"state": "rejected", "code": "7001", "message": "거부"}

    assert 실행목록.confirm("run1", "0000000302", 시각 + 700) is True
    assert 엔진.run.state == runs.ATTENTION


def test_전략_확인이_못_정하면_다음_확인을_잡고_끝나면_접는다(tmp_path, 확인을_켠다):
    실행목록, 엔진, 남김 = _세운(tmp_path, _차례로보내는곳("0000000303"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    불린: list = []

    def 못찾음(run, order):
        불린.append(order.order_no)
        return None

    실행목록._outcome = 못찾음

    assert 실행목록.confirm("run1", "0000000303", 시각) is False
    assert 실행목록.confirm_wanted(시각) == [("run1", "0000000303")], "두 번째 확인이 남았습니다."
    assert 실행목록.confirm("run1", "0000000303", 시각) is False
    assert 실행목록.confirm_wanted(시각 + 60_000) == []
    assert 불린 == ["0000000303", "0000000303"]
    assert 엔진.run.state == runs.ENTERING and len(엔진.book.open_orders) == 1, "모르면 주문을 닫지 않습니다."
    assert _결과줄(남김) == []


def test_전략_확인이_접수를_보이면_더_묻지_않는다(tmp_path, 확인을_켠다):
    실행목록, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000304"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    실행목록._outcome = lambda run, order: {"state": "accepted", "source": "order-history"}

    assert 실행목록.confirm("run1", "0000000304", 시각) is False
    assert 실행목록.confirm_wanted(시각 + 60_000) == []
    assert 엔진.run.state == runs.ENTERING


def test_펌프가_확인할_주문을_루프_밖에서_확인한다(tmp_path, 확인을_켠다):
    실행목록, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000305"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    실행목록._outcome = lambda run, order: {"state": "rejected", "code": "-2", "message": "없음"}
    펌프 = pump_lib.RunPump(
        실행목록, hub=_허브(), auction=lambda *_, **__: None, replaying=lambda: False
    )

    assert asyncio.run(펌프.confirm_orders(시각)) == 1
    assert 엔진.run.state == runs.PAUSED


def test_재생_중이면_펌프는_조회하지_않고_확인을_접는다(tmp_path, 확인을_켠다):
    실행목록, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000306"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    불린: list = []
    실행목록._outcome = lambda run, order: 불린.append(1)
    펌프 = pump_lib.RunPump(
        실행목록, hub=_허브(), auction=lambda *_, **__: None, replaying=lambda: True
    )

    asyncio.run(펌프.confirm_orders(시각))
    asyncio.run(펌프.confirm_orders(시각))

    assert 불린 == []
    assert 실행목록.confirm_wanted(시각 + 60_000) == []
    assert 엔진.run.state == runs.ENTERING


def test_실시간_알림이_먼저_닫았으면_확인하지_않는다(tmp_path, 확인을_켠다):
    실행목록, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000307"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    엔진.on_order({"id": "0000000307", "status": "rejected", "filled": 0}, at=시각 + 100)

    assert 실행목록.confirm_wanted(시각 + 60_000) == []
    assert 엔진.run.state == runs.PAUSED, "접수 뒤 확인으로 잡았을 때와 끝 상태가 같습니다."
    assert [one["reason"] for one in 엔진.events if one["kind"] == engine_lib.BLOCKED] == [sim.REJECTED]


def test_실시간_알림의_진입_거절은_중지이고_코드를_싣는다(tmp_path):
    """취소로 읽고 감시로 돌아가면 다음 신호에 같은 주문이 다시 나갑니다."""
    보낸곳 = _차례로보내는곳("0000000310")
    _, 엔진, 남김 = _세운(tmp_path, 보낸곳)
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    엔진.on_order(
        {"id": "0000000310", "status": "rejected", "statusCode": "9", "errorCode": "5039", "filled": 0},
        at=시각 + 100,
    )

    assert 엔진.run.state == runs.PAUSED
    사건 = [one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED]
    assert 사건[-1]["reason"] == sim.REJECTED and 사건[-1]["code"] == "5039"
    assert 사건[-1]["text"].startswith("주문 거부 5039")
    (결과,) = _결과줄(남김)
    assert (결과["outcome"], 결과["serverStatus"], 결과["serverCode"]) == (
        engine_lib.REJECTED, "rejected", "5039",
    )
    assert len(보낸곳.sent) == 1


def test_실시간_알림의_청산_거절은_확인_필요다(tmp_path):
    _, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000311"), state=runs.HOLDING)
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 405.0, "time": 시각})
    엔진._send(paper.SELL, 1, 405.0, "exit", 시각)

    엔진.on_order({"id": "0000000311", "status": "rejected", "filled": 0}, at=시각 + 100)

    assert 엔진.run.state == runs.ATTENTION
    사건 = [one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED]
    assert 사건[-1]["reason"] == sim.REJECTED and 사건[-1]["code"] == ""


def test_실시간_알림의_취소는_전처럼_감시로_돌아간다(tmp_path):
    _, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000312"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    엔진.on_order({"id": "0000000312", "status": "cancelled", "filled": 0}, at=시각 + 100)

    assert 엔진.run.state == runs.ARMED
    assert [one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED] == []


def test_같은_거절_알림이_두_번_와도_한_번만_다룬다(tmp_path):
    _, 엔진, _ = _세운(tmp_path, _차례로보내는곳("0000000313"))
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    알림 = {"id": "0000000313", "status": "rejected", "errorCode": "5039", "filled": 0}

    엔진.on_order(알림, at=시각 + 100)
    엔진.on_order(알림, at=시각 + 200)

    assert len([one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED]) == 1


def test_판정_중_즉시_거부는_안_낸_신호로_세지_않는다(tmp_path):
    """주문은 나갔고 계좌가 받지 않은 것입니다. 뒤늦은 거절(알림·확인)과 같게 셉니다."""
    거부 = BusinessError("domestic_order", "5039", "처리불가", {})
    _, 엔진, _ = _세운(tmp_path, _차례로보내는곳(거부))
    앞 = 엔진.unsent_today(시각)

    # 규칙이 걸려 판정하는 동안 낸 진입입니다(`_judging`).
    엔진._judging = True
    try:
        엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    finally:
        엔진._judging = False

    사건 = [one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED]
    assert 사건[-1]["reason"] == sim.REJECTED
    assert 엔진.unsent_today(시각) == 앞


def test_판정_중_앱이_막은_주문은_전처럼_안_낸_신호로_센다(tmp_path):
    _, 엔진, _ = _세운(tmp_path, _차례로보내는곳(sim.NotSent("받지 않는 주문유형")))
    앞 = 엔진.unsent_today(시각)

    엔진._judging = True
    try:
        엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    finally:
        엔진._judging = False

    assert 엔진.unsent_today(시각) == 앞 + 1


def test_진입_거부로_중지할_때_열려_있던_진입_주문을_거둔다(tmp_path):
    """사용자가 「중지」를 누를 때(`service._pause`)와 같은 규칙입니다."""
    거부 = BusinessError("domestic_order", "5039", "처리불가", {})
    보낸곳 = _차례로보내는곳("0000000401", 거부)
    실행목록, 엔진, _ = _세운(tmp_path, 보낸곳)
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    assert 엔진.run.state == runs.ENTERING

    엔진._send(paper.BUY, 1, 405.0, "entry", 시각 + 1)

    assert 보낸곳.cancelled == ["0000000401"]
    assert 엔진.run.state == runs.PAUSED
    (앞주문,) = 엔진.book.orders
    assert 앞주문.cancel_sent and 앞주문.reason == engine_lib.HALT_WITHDRAW_TEXT


def test_확인_필요_중에_온_거절은_계좌로_취소를_내지_않는다(tmp_path, 확인을_켠다):
    보낸곳 = _차례로보내는곳("0000000403", "0000000404")
    실행목록, 엔진, _ = _세운(tmp_path, 보낸곳)
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)
    엔진.run.state = runs.HOLDING
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각 + 1)
    엔진.run.state = runs.ATTENTION
    실행목록._outcome = lambda run, order: {"state": "rejected", "code": "-2", "message": "없음"}

    assert 실행목록.confirm("run1", "0000000404", 시각 + 700) is True

    assert 보낸곳.cancelled == [], "확인 필요 동안에는 어떤 요청도 내지 않습니다."
    assert 엔진.run.state == runs.ATTENTION


def test_청산_거부는_열린_진입_주문을_거두지_않는다(tmp_path):
    거부 = BusinessError("domestic_order", "5039", "처리불가", {})
    보낸곳 = _차례로보내는곳("0000000402", 거부)
    _, 엔진, _ = _세운(tmp_path, 보낸곳)
    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    엔진._send(paper.SELL, 1, 405.0, "exit", 시각 + 1)

    assert 보낸곳.cancelled == []
    assert 엔진.run.state == runs.ATTENTION


def test_보내기_전에_앱이_막으면_거부_앱_검사이고_확인을_청하지_않는다(tmp_path):
    보낸곳 = _차례로보내는곳(sim.NotSent("해외 주문이 받지 않는 주문유형입니다: 최유리"))
    _, 엔진, 남김 = _세운(tmp_path, 보낸곳)

    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    사건 = [one for one in 엔진.events if one["kind"] == engine_lib.BLOCKED]
    assert 사건[-1]["reason"] == sim.NOT_SENT == "app-check"
    assert "거부(앱 검사) — 해외 주문이 받지 않는 주문유형입니다: 최유리" in 사건[-1]["text"]
    assert sim.WHY_NO_REPLY not in 사건[-1]["text"]
    assert 엔진.run.state == runs.PAUSED, "같은 값으로 다시 내도 막히므로 멈춥니다."
    (결과,) = _결과줄(남김)
    assert 결과["outcome"] == engine_lib.REFUSED


def test_해외_주문유형을_못_옮기면_NotSent_이고_계좌로_안_나간다(monkeypatch):
    from backend.overseas_futureoption import overseas_futureoption_functions as api

    불린: list = []
    monkeypatch.setattr(api, "order", lambda *a, **k: 불린.append(1))
    run = runs.Run(
        id="r1", version_id="v1", code="ESZ26", session="overseas", market="overseas",
        mode=runs.SIM, approved_at=1_000, environment="paper", qty=1,
    )

    with pytest.raises(sim.NotSent):
        sim.NhSender().order(
            run=run, side=paper.BUY, quantity=1, order_type="최유리",
            price=None, stop_price=None, fill_condition="",
        )
    assert 불린 == []
    assert issubclass(sim.NotSent, ValueError)


def _해외실행() -> runs.Run:
    return runs.Run(
        id="r1", version_id="v1", code="ESZ26", session="overseas", market="overseas",
        mode=runs.SIM, approved_at=1_000, environment="paper", qty=1,
    )


def test_전략_해외_주문의_err_cd_거절은_업무_거부다(monkeypatch):
    from backend.overseas_futureoption import overseas_futureoption_functions as api

    monkeypatch.setattr(
        api, "order", lambda *a, **k: {"ord_no": "0000000501", "err_cd": "7037", "err_msg": "이미 처리완료된 [주문] 건 입니다"}
    )
    장부 = sim.SimBroker(_해외실행(), sender=sim.NhSender(), environment=lambda: "paper")

    with pytest.raises(sim.SimRefused) as 받음:
        장부.place("o1", side=paper.BUY, quantity=1, order_type="시장가", at=1)

    assert 받음.value.reason == sim.REJECTED and 받음.value.code == "7037"
    assert 장부.orders == [], "거절된 주문을 접수로 장부에 얹지 않습니다."


def test_전략_해외_취소의_err_cd_거절은_취소를_낸_것으로_적지_않는다(monkeypatch):
    from backend.overseas_futureoption import overseas_futureoption_functions as api

    답들 = [
        {"ord_no": "0000000502", "err_cd": "00000"},
        {"ord_no": "0000000503", "err_cd": "7037", "err_msg": "이미 처리완료된 [주문] 건 입니다"},
    ]
    monkeypatch.setattr(api, "order", lambda *a, **k: 답들.pop(0))
    장부 = sim.SimBroker(_해외실행(), sender=sim.NhSender(), environment=lambda: "paper")
    주문 = 장부.place("o1", side=paper.BUY, quantity=1, order_type="시장가", at=1)

    assert 장부.cancel(주문, "시험") is False
    assert 주문.cancel_sent is False and 주문.open
