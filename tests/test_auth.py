"""인증 모듈 테스트. 실제 서버 대신 응답을 모의한다."""
from datetime import datetime, timedelta

import httpx
import pytest

from backend.auth.auth_functions import (
    AuthError,
    Token,
    TokenManager,
    issue_token,
    issue_websocket_key,
    revoke_token,
)
from backend.config import load_config

CONFIG = """
default_environment: paper
paper:
  domestic:
    app_key: "PAPERDOM"
    app_secret: "PAPERDOMSECRET"
  overseas:
    app_key: "PAPEROVS"
    app_secret: "PAPEROVSSECRET"
real:
  domestic:
    app_key: "REALDOM"
    app_secret: "REALDOMSECRET"
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return load_config(path)


def client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def token_response(access_token="TOKEN", expires_at=None, **extra):
    # 빈 문자열을 그대로 보내는 경우를 표현할 수 있어야 하므로 None 만 기본값으로 대체한다.
    if expires_at is None:
        expires_at = f"{datetime.now() + timedelta(days=1):%Y-%m-%d %H:%M:%S}"
    body = {
        "access_token": access_token,
        "token_type": "Bearer",
        "scopes": "read",
        "expires_in": "86400",
        "expires_at": expires_at,
    }
    body.update(extra)
    return httpx.Response(200, json=body)


# --- 토큰 발급 ---------------------------------------------------------------


def test_토큰을_발급받는다(config):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["content_type"] = request.headers.get("Content-Type")
        return token_response(access_token="ISSUED")

    market = config.market("domestic")
    token = issue_token(market, config.environment().base_url, client=client_returning(handler))

    assert token.access_token == "ISSUED"
    assert token.token_type == "Bearer"
    assert token.authorization == "Bearer ISSUED"
    assert seen["url"].endswith("/auth-service/v1/token")
    assert "client_credentials" in seen["body"]
    assert "PAPERDOM" in seen["body"]


def test_토큰_발급은_form_형식으로_보낸다(config):
    # 토큰 발급 엔드포인트는 JSON 본문을 읽지 못한다.
    seen = {}

    def handler(request):
        seen["content_type"] = request.headers.get("Content-Type")
        seen["body"] = request.content.decode()
        return token_response()

    issue_token(
        config.market("domestic"),
        config.environment().base_url,
        client=client_returning(handler),
    )

    assert seen["content_type"] == "application/x-www-form-urlencoded"
    assert seen["body"].startswith("grant_type=client_credentials")


def test_시장마다_다른_인증정보를_보낸다(config):
    sent = []

    def handler(request):
        sent.append(request.content.decode())
        return token_response()

    client = client_returning(handler)
    base_url = config.environment().base_url
    issue_token(config.market("domestic"), base_url, client=client)
    issue_token(config.market("overseas"), base_url, client=client)

    assert "PAPERDOM" in sent[0]
    assert "PAPEROVS" in sent[1]


def test_만료_시각을_읽는다(config):
    def handler(request):
        return token_response(expires_at="2030-01-02 03:04:05")

    token = issue_token(
        config.market("domestic"), config.environment().base_url, client=client_returning(handler)
    )

    assert token.expires_at == datetime(2030, 1, 2, 3, 4, 5)


def test_만료_시각을_읽을_수_없으면_expires_in으로_계산한다(config):
    def handler(request):
        return token_response(expires_at="", expires_in="120")

    before = datetime.now()
    token = issue_token(
        config.market("domestic"), config.environment().base_url, client=client_returning(handler)
    )

    assert timedelta(seconds=110) < token.expires_at - before < timedelta(seconds=130)


def test_토큰이_없는_응답은_거부한다(config):
    def handler(request):
        return httpx.Response(200, json={"token_type": "Bearer"})

    with pytest.raises(AuthError, match="access_token"):
        issue_token(
            config.market("domestic"),
            config.environment().base_url,
            client=client_returning(handler),
        )


def test_오류_응답은_상태코드와_함께_알려준다(config):
    def handler(request):
        return httpx.Response(401, text="invalid appkey")

    with pytest.raises(AuthError) as exc:
        issue_token(
            config.market("domestic"),
            config.environment().base_url,
            client=client_returning(handler),
        )

    assert "401" in str(exc.value)
    assert "invalid appkey" in str(exc.value)


# --- 유효성 판단 -------------------------------------------------------------


def test_만료가_지났으면_유효하지_않다():
    token = Token("T", "Bearer", datetime.now() - timedelta(seconds=1))
    assert token.is_valid() is False


def test_만료가_가까우면_유효하지_않다():
    token = Token("T", "Bearer", datetime.now() + timedelta(seconds=30))

    assert token.is_valid(margin=timedelta(minutes=1)) is False
    assert token.is_valid(margin=timedelta(seconds=5)) is True


# --- TokenManager ------------------------------------------------------------


def test_같은_조합은_토큰을_재사용한다(config):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return token_response()

    manager = TokenManager(config, client=client_returning(handler))
    first = manager.token("domestic")
    second = manager.token("domestic")

    assert first is second
    assert len(calls) == 1


def test_시장과_환경마다_토큰을_따로_보관한다(config):
    issued = []

    def handler(request):
        issued.append(request.content.decode())
        return token_response(access_token=f"TOKEN{len(issued)}")

    manager = TokenManager(config, client=client_returning(handler))
    paper_domestic = manager.token("domestic", "paper")
    paper_overseas = manager.token("overseas", "paper")
    real_domestic = manager.token("domestic", "real")

    assert len({paper_domestic.access_token, paper_overseas.access_token, real_domestic.access_token}) == 3
    assert len(issued) == 3


def test_만료가_가까우면_다시_발급받는다(config):
    issued = []

    def handler(request):
        issued.append(1)
        # 첫 발급은 곧 만료되고, 두 번째는 넉넉하게 남아 있다.
        seconds = 10 if len(issued) == 1 else 3600
        return token_response(
            access_token=f"TOKEN{len(issued)}",
            expires_at=f"{datetime.now() + timedelta(seconds=seconds):%Y-%m-%d %H:%M:%S}",
        )

    manager = TokenManager(config, client=client_returning(handler))
    first = manager.token("domestic")
    second = manager.token("domestic")

    assert first.access_token == "TOKEN1"
    assert second.access_token == "TOKEN2"
    assert len(issued) == 2


def test_환경을_생략하면_기본_환경을_쓴다(config):
    sent = []

    def handler(request):
        sent.append(request.content.decode())
        return token_response()

    manager = TokenManager(config, client=client_returning(handler))
    manager.token("domestic")

    assert "PAPERDOM" in sent[0]


def test_인증_헤더를_만들어준다(config):
    def handler(request):
        return token_response(access_token="ISSUED")

    manager = TokenManager(config, client=client_returning(handler))

    assert manager.headers("domestic") == {"Authorization": "Bearer ISSUED"}


def test_폐기하면_보관중인_토큰을_버린다(config):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return token_response()

    manager = TokenManager(config, client=client_returning(handler))
    manager.token("domestic")
    manager.revoke("domestic")
    manager.token("domestic")

    assert paths == [
        "/auth-service/v1/token",
        "/auth-service/v1/revoke",
        "/auth-service/v1/token",
    ]


# --- 웹소켓 접속키 -----------------------------------------------------------


def test_웹소켓_접속키를_발급받는다(config):
    seen = {}

    def handler(request):
        if request.url.path.endswith("/token"):
            return token_response(access_token="ISSUED")
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"access_key": "WSKEY"})

    manager = TokenManager(config, client=client_returning(handler))

    assert manager.websocket_key("domestic") == "WSKEY"
    assert seen["auth"] == "Bearer ISSUED"
    assert seen["path"] == "/permission/v1/web-socket-key"


def test_웹소켓_접속키가_없는_응답은_거부한다(config):
    def handler(request):
        return httpx.Response(200, json={})

    token = Token("T", "Bearer", datetime.now() + timedelta(hours=1))

    with pytest.raises(AuthError, match="access_key"):
        issue_websocket_key(token, "https://example.test", client=client_returning(handler))


# --- 폐기 ---------------------------------------------------------------------


def test_폐기_요청은_앱키와_토큰을_함께_보낸다(config):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers.get("Authorization")
        seen["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={})

    token = Token("REVOKEME", "Bearer", datetime.now() + timedelta(hours=1))
    revoke_token(
        config.market("domestic"),
        config.environment().base_url,
        token,
        client=client_returning(handler),
    )

    assert seen["path"] == "/auth-service/v1/revoke"
    assert "PAPERDOM" in seen["body"]
    assert seen["auth"] == "Bearer REVOKEME"
    # 폐기는 발급과 달리 JSON 만 받는다.
    assert seen["content_type"] == "application/json"
