"""백테스트도 실행을 세울 때와 같은 자리에서 주문당 수량을 봅니다.

최대 보유를 넘는 수량으로 셈하면 첫 주문부터 한도를 넘어 오류 없이 거래가 0 으로
나옵니다. 실행 시작은 그 수량을 막으므로, 백테스트도 같은 말(`WHY_QTY`)로 막습니다.

**셈을 돌리지 않고 막습니다** — 지난 봉 조회도 하지 않습니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import backtest, runs, service as service_lib, validate
from tests.test_strategy_backtest import _몸, 손님  # noqa: F401 — 시험 고정값
from tests.test_strategy_engine import _설정
from tests.test_strategy_service import _모의목록

주소 = "/api/strategy/backtest"


def _줄들(답) -> list[tuple[str, str]]:
    return [(one["field"], one["message"]) for one in 답.json()["detail"]["problems"]]


def test_주문당_수량이_최대_보유를_넘으면_두_칸에_다_적는다(손님):
    """최대 보유 칸은 저장 검사가, 수량 칸은 시작 검사가 냅니다. 화면이 칸마다 붙입니다."""
    앱, _ = 손님

    답 = 앱.post(주소, json=_몸(draft=_설정(perOrder="2", maxHold="1")))

    assert 답.status_code == 400
    줄들 = _줄들(답)
    assert ("aux.maxHold", "최대 보유는 주문당 수량 이상으로 적습니다") in 줄들
    assert ("qty", service_lib.WHY_QTY) in 줄들


def test_주문당_수량이_최대_보유와_같으면_셈한다(손님):
    앱, _ = 손님

    답 = 앱.post(주소, json=_몸(draft=_설정(perOrder="2", maxHold="2")))

    assert 답.status_code == 200, 답.text
    assert [one["quantity"] for one in 답.json()["trades"]] == [2]


@pytest.mark.parametrize("수량", [3, 0])
def test_보낸_수량이_범위_밖이면_수량_칸_하나로_400(손님, 수량):
    앱, _ = 손님

    답 = 앱.post(주소, json=_몸(draft=_설정(perOrder="1", maxHold="2"), qty=수량))

    assert 답.status_code == 400
    assert _줄들(답) == [("qty", service_lib.WHY_QTY)]


def test_막히면_셈도_봉_조회도_하지_않는다(손님, monkeypatch):
    앱, 목록 = 손님
    불린 = []
    monkeypatch.setattr(backtest, "run_one", lambda work: 불린.append(work) or {})

    답 = 앱.post(주소, json=_몸(draft=_설정(perOrder="1", maxHold="2"), qty=3))

    assert 답.status_code == 400
    assert 불린 == [] and 목록.asked == []


def test_실행_시작과_백테스트가_같은_말로_막는다(tmp_path, 손님):
    앱, _ = 손님
    실행목록 = _모의목록(tmp_path)
    설정 = _설정(perOrder="1", maxHold="2", fillCond="FAS")

    시작 = 실행목록.start_problems(
        draft=설정, market="domestic", code="A7569000", session="국내 주간", qty=3,
        cash=1.0, fee_per_contract=0.0, mode=runs.PAPER,
    )
    셈 = 앱.post(주소, json=_몸(draft=설정, qty=3))

    assert [one for one in 시작 if one["field"] == "qty"] == [
        {"field": "qty", "severity": validate.ERROR, "message": service_lib.WHY_QTY}
    ]
    assert _줄들(셈) == [("qty", service_lib.WHY_QTY)]
    assert not hasattr(backtest, "WHY_QTY"), "수량 문구는 한 벌입니다."
