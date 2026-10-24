"""재생 모드의 인증.

접속 토큰과 웹소켓 접속키는 수집된 응답이 없어 만들어 냅니다. 그래서
「저장 응답을 돌려준다」가 아니라 「만들어 낸 값을 돌려준다」가 맞고,
받는 쪽이 그 사실을 알 수 있어야 합니다.
"""
from backend.auth.auth_functions import issue_websocket_key
from backend.nh_api.fixtures import FixtureStore
from backend.nh_api.replay import (
    MATCH_SYNTHETIC,
    SYNTHETIC_TOKEN,
    SYNTHETIC_WEBSOCKET_KEY,
    replay_base_url,
    replay_client,
)
from backend.nh_api.session import REPLAY, create_session


def test_접속_토큰은_만들어_낸_값이다():
    with create_session(replay=True) as session:
        assert session.mode == REPLAY
        토큰 = session.tokens.token("domestic")

    assert 토큰.access_token == SYNTHETIC_TOKEN
    # 값만 보고도 실제 토큰이 아님을 알 수 있어야 한다.
    assert "NOT-ISSUED-BY-NH" in 토큰.access_token
    assert 토큰.authorization.startswith("Bearer ")
    assert 토큰.is_valid()


def test_웹소켓_접속키도_만들어_낸_값이다():
    with create_session(replay=True) as session:
        키 = session.tokens.websocket_key("domestic")
    assert 키 == SYNTHETIC_WEBSOCKET_KEY


def test_만들어_낸_응답임을_헤더로_알린다():
    store = FixtureStore.load()
    with replay_client(store) as client:
        토큰 = client.post(
            f"{replay_base_url('paper')}/auth-service/v1/token",
            data={"grant_type": "client_credentials", "appkey": "x", "appsecret": "y"},
        )
        키 = client.get(f"{replay_base_url('paper')}/permission/v1/web-socket-key")
        폐기 = client.post(f"{replay_base_url('paper')}/auth-service/v1/revoke", json={})

    for 응답 in (토큰, 키, 폐기):
        assert 응답.status_code == 200
        assert 응답.headers["x-nh-replay-match"] == MATCH_SYNTHETIC
        # 만들어 낸 응답에는 어느 기록에서 왔다는 표시가 없다.
        assert "x-nh-replay-record" not in 응답.headers


def test_수집된_웹소켓_키_기록이_있어도_만들어_낸_값을_쓴다():
    """수집된 값은 실제 키가 아니라 자리를 채운 문자열이라 쓰지 않는다."""
    store = FixtureStore.load()
    수집된것 = store.find_http(
        method="GET", path="/permission/v1/web-socket-key", environment="real"
    )
    assert 수집된것, "웹소켓 키 기록이 반입되어 있어야 한다"

    with create_session(replay=True, fixtures=store) as session:
        키 = issue_websocket_key(
            session.tokens.token("domestic"),
            session.base_url(),
            client=session.client,
        )
    assert 키 == SYNTHETIC_WEBSOCKET_KEY


def test_재생_모드는_재생_주소만_본다():
    with create_session(replay=True) as session:
        for 환경 in ("paper", "real"):
            assert session.base_url(환경) == replay_base_url(환경)
            assert "futures.co.kr" not in session.base_url(환경)
