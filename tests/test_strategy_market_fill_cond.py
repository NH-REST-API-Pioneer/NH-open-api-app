"""국내 시장가 주문의 체결조건.

국내 서버는 시장가 주문에 FOK·FAK 를 받지 않습니다. 전략 저장과 실행 시작이 그 조합을
미리 막아, 진입 신호 때가 되어서야 주문이 거부되는 일이 없게 합니다. 지정가는 세 가지를
다 받습니다. 해외 주문에는 체결조건 칸이 없어 이 규칙이 없습니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.**
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import service as service_lib, validate
from backend.strategy.store import StrategyStore
from backend.strategy.strategy_routes import get_master, get_service, get_store
from tests.test_strategy_backtest import _버전
from tests.test_strategy_backtest import _마스터 as _백테스트마스터
from tests.test_strategy_service import _설정, _모의목록, _모의물음, 실행목록  # noqa: F401 — 시험 고정값

체결조건 = "aux.fillCond"


def _체결조건_말(found: list[dict[str, str]]) -> list[str]:
    return [one["message"] for one in found if one["field"] == 체결조건]


# ── 검사 ───────────────────────────────────────────


@pytest.mark.parametrize("조건", ["FOK", "FAK"])
def test_국내_시장가에_FAS_밖의_체결조건은_막는다(조건):
    found = validate.problems(_설정(orderType="시장가", fillCond=조건), market="domestic")

    assert _체결조건_말(found) == [validate.MARKET_FILL_COND_WHY]
    assert validate.blocked(found)


def test_국내_시장가_FAS_는_통과한다():
    found = validate.problems(_설정(orderType="시장가", fillCond="FAS"), market="domestic")

    assert _체결조건_말(found) == []
    assert not validate.blocked(found)


@pytest.mark.parametrize("유형", ["지정가", "조건부지정가", "최유리지정가"])
@pytest.mark.parametrize("조건", ["FAS", "FOK", "FAK"])
def test_시장가가_아닌_국내_주문유형은_체결조건을_전처럼_받는다(유형, 조건):
    found = validate.problems(_설정(orderType=유형, fillCond=조건), market="domestic")

    assert _체결조건_말(found) == []


def test_모르는_체결조건은_고르라는_말_하나만_단다():
    found = validate.problems(_설정(orderType="시장가", fillCond="IOC"), market="domestic")

    assert _체결조건_말(found) == [validate.FILL_COND_WHY]


def test_해외_시장가에는_체결조건_규칙이_없다():
    """해외 주문 명세에는 체결조건 칸이 없습니다. 남은 값은 담기 전에 비웁니다."""
    설정 = _설정(orderType="시장가", fillCond="FAK", session="해외 CME")

    assert validate.MARKET_FILL_COND_WHY not in _체결조건_말(
        validate.problems(설정, market="overseas")
    )
    다듬음 = validate.normalized({"market": "overseas"}, 설정)
    assert 다듬음["aux"]["fillCond"] == ""
    assert _체결조건_말(validate.problems(다듬음, market="overseas")) == []


# ── 저장 ───────────────────────────────────────────


@pytest.fixture
def 손님(tmp_path, 실행목록):
    저장소 = StrategyStore(tmp_path / "strategies.json")
    app.dependency_overrides.update(
        {get_service: lambda: 실행목록, get_store: lambda: 저장소, get_master: _백테스트마스터}
    )
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def test_시장가_FAK_는_저장되지_않고_까닭을_답한다(손님):
    답 = 손님.put(
        "/api/strategy/versions/v1",
        json={"version": _버전(), "draft": _설정(orderType="시장가", fillCond="FAK")},
    )

    assert 답.status_code == 400, 답.text
    assert {"field": 체결조건, "severity": "error", "message": validate.MARKET_FILL_COND_WHY} in (
        답.json()["detail"]["problems"]
    )


@pytest.mark.parametrize(("유형", "조건"), [("시장가", "FAS"), ("지정가", "FAK")])
def test_허용되는_조합은_저장된다(손님, 유형, 조건):
    답 = 손님.put(
        "/api/strategy/versions/v1",
        json={"version": _버전(), "draft": _설정(orderType=유형, fillCond=조건)},
    )

    assert 답.status_code == 200, 답.text


# ── 시작 ───────────────────────────────────────────
#
# 이 규칙 전에 담아 둔 설정은 시작할 때 막힙니다.


def test_시장가_FAK_로는_실행을_시작하지_않는다(tmp_path):
    실행 = _모의목록(tmp_path)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행.add(**_모의물음(draft=_설정(orderType="시장가", fillCond="FAK")))

    assert _체결조건_말(터짐.value.problems) == [validate.MARKET_FILL_COND_WHY]
    assert 실행.rows() == []


@pytest.mark.parametrize(("유형", "조건"), [("시장가", "FAS"), ("지정가", "FAK")])
def test_허용되는_조합으로는_실행을_시작한다(tmp_path, 유형, 조건):
    실행 = _모의목록(tmp_path)

    줄 = 실행.add(**_모의물음(draft=_설정(orderType=유형, fillCond=조건)))

    assert 줄["id"] and len(실행.rows()) == 1
