"""모의투자에서 부를 수 없는 API(`EGW053`) — 조회와 주문의 답.

**NH선물 서버에 붙지 않습니다.** 가짜 전송로 위의 세션이 정해 둔 본문으로 답합니다.
본문 모양은 실제 서버가 준 문장(「해당 API는 모의투자 에서 호출 할수 없습니다.」)을
본뜬 것입니다.
"""
from __future__ import annotations

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from backend.auth.auth_functions import TokenManager
from backend.config import load_config
from backend.domestic_futureoption import domestic_routes
from backend.main import app
from backend.nh_api import error_codes
from backend.nh_api.client import TradeClient
from backend.nh_api.errors import ERROR_CODE_HEADER, ERROR_KIND_HEADER, PAPER_UNAVAILABLE_DETAIL
from backend.nh_api.session import LIVE, Session
from backend.overseas_futureoption import overseas_routes
from tests.test_environment_switch import _설정

모의에서_안됨 = {"errorCode": "EGW053", "errorMessage": "해당 API는 모의투자 에서 호출 할수 없습니다."}
다른_게이트웨이 = {"errorCode": "EGW019", "errorMessage": "잠시 후 다시 시도해주세요."}


class 서버:
    """토큰은 내주고, 나머지는 정해 둔 상태·본문으로 답합니다."""

    def __init__(self, 상태: int, 본문: dict) -> None:
        self.상태 = 상태
        self.본문 = 본문
        self.요청들: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.요청들.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": "T", "token_type": "Bearer", "expires_in": "3600"}
            )
        return httpx.Response(self.상태, json=self.본문)

    def 보낸것(self, 끝: str) -> list[httpx.Request]:
        return [r for r in self.요청들 if r.url.path.endswith(끝)]


@pytest.fixture
def 세우기(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_설정(default="paper"), allow_unicode=True), encoding="utf-8")
    config = load_config(path)
    열린것 = []

    def 만들기(상태: int, 본문: dict):
        handler = 서버(상태, 본문)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        session = Session(mode=LIVE, config=config, client=client, tokens=TokenManager(config, client=client))
        호출부 = TradeClient(session)
        app.dependency_overrides[domestic_routes.get_client] = lambda: 호출부
        app.dependency_overrides[overseas_routes.get_client] = lambda: 호출부
        열린것.append(session)
        return TestClient(app), handler

    try:
        yield 만들기
    finally:
        app.dependency_overrides.pop(domestic_routes.get_client, None)
        app.dependency_overrides.pop(overseas_routes.get_client, None)
        for session in 열린것:
            session.close()


조회들 = [
    ("/api/domestic/price-night", {"sym": "A016C000"}, "/price-night"),
    ("/api/overseas/price", {"syms": [{"exch_cd": "FCME", "sym": "MESZ26"}]}, "/overseas/price"),
]


@pytest.mark.parametrize("상태", [200, 403])
@pytest.mark.parametrize("주소, 몸, 끝", 조회들, ids=["국내_야간_현재가", "해외_현재가"])
def test_모의에서_막힌_조회는_까닭을_헤더로_단다(세우기, 상태, 주소, 몸, 끝):
    앱, handler = 세우기(상태, 모의에서_안됨)

    응답 = 앱.post(주소, json=몸)

    assert 응답.status_code == 502, "화면이 「다시 눌러도 같은 답」으로 읽는 상태 그대로입니다."
    assert 응답.json()["detail"] == PAPER_UNAVAILABLE_DETAIL
    assert 응답.headers[ERROR_KIND_HEADER] == "paper-unavailable"
    assert 응답.headers[ERROR_CODE_HEADER] == "EGW053"
    # 토큰을 다시 받거나 같은 요청을 다시 보내지 않습니다.
    assert len(handler.보낸것("/token")) == 1
    assert len(handler.보낸것(끝)) == 1


def test_야간_옵션_체인도_첫_쪽에서_막히면_다음_쪽을_안_부른다(세우기):
    """쪽을 이어 받는 조회입니다 — 첫 쪽에서 막히면 거기서 끝입니다."""
    앱, handler = 세우기(200, 모의에서_안됨)

    응답 = 앱.post("/api/domestic/option-chain", json={"prd": "01", "exp_mon": "261008", "session": "night"})

    assert 응답.status_code == 502
    assert 응답.json()["detail"] == PAPER_UNAVAILABLE_DETAIL
    assert (응답.headers[ERROR_KIND_HEADER], 응답.headers[ERROR_CODE_HEADER]) == ("paper-unavailable", "EGW053")
    assert len(handler.보낸것("/price-all-option-night")) == 1


@pytest.mark.parametrize("주소, 몸, 끝", 조회들, ids=["국내_야간_현재가", "해외_현재가"])
def test_다른_게이트웨이_거절은_지금과_같다(세우기, 주소, 몸, 끝):
    앱, _ = 세우기(200, 다른_게이트웨이)

    응답 = 앱.post(주소, json=몸)

    assert 응답.status_code == 502
    assert 응답.json()["detail"] != PAPER_UNAVAILABLE_DETAIL
    assert ERROR_KIND_HEADER not in 응답.headers
    assert ERROR_CODE_HEADER not in 응답.headers


def test_업무_거부도_지금과_같다(세우기):
    앱, _ = 세우기(200, {"errorCode": "50013", "errorMessage": "조회할 내역이 없습니다."})

    응답 = 앱.post("/api/domestic/price-night", json={"sym": "A016C000"})

    assert 응답.status_code == 502
    assert ERROR_KIND_HEADER not in 응답.headers


# ── 주문 ─────────────────────────────────────────────────

주문들 = [
    ("/api/domestic/order", {"environment": "paper", "sym": "A016C000", "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"}),
    (
        "/api/domestic/modify",
        {"environment": "paper", "sym": "A016C000", "side": "buy", "ord_qty": 1, "ord_tp_cd": "1",
         "ord_pric": "1000.00", "org_ord_no": "1"},
    ),
    (
        "/api/domestic/cancel",
        {"environment": "paper", "sym": "A016C000", "side": "buy", "ord_qty": 1, "org_ord_no": "1"},
    ),
    (
        "/api/overseas/order",
        {"environment": "paper", "sym": "MESZ26", "side": "buy", "qt_div_cd": "1", "glb_ord_tp_cd": "1", "ord_qty": 1},
    ),
]
주문_이름 = ["국내_신규", "국내_정정", "국내_취소", "해외_주문"]


@pytest.mark.parametrize("주소, 몸", 주문들, ids=주문_이름)
def test_모의에서_막힌_주문은_거절로_답한다(세우기, 주소, 몸):
    """처리되지 않은 것이 확실하므로 「결과를 모름」이 아니라 거절입니다."""
    앱, _ = 세우기(200, 모의에서_안됨)

    응답 = 앱.post(주소, json=몸)

    assert 응답.status_code == 200
    답 = 응답.json()
    assert (답["accepted"], 답["code"], 답["kind"], 답["environment"]) == (
        False,
        "EGW053",
        error_codes.PAPER_UNAVAILABLE,
        "paper",
    )
    assert 답["message"] == 모의에서_안됨["errorMessage"], "문구는 서버가 보낸 그대로입니다."


@pytest.mark.parametrize("주소, 몸", 주문들, ids=주문_이름)
def test_다른_게이트웨이_거절의_주문은_지금처럼_결과를_모른다(세우기, 주소, 몸):
    앱, _ = 세우기(200, 다른_게이트웨이)

    assert 앱.post(주소, json=몸).status_code == 504
