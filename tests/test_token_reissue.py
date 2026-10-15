"""토큰 다시 받기 — 폐기하고 같은 키로 새로 받은 뒤 그 시장의 실시간만 다시 붙입니다.

**어떤 시험도 NH선물 서버에 붙지 않습니다.** 가짜 전송로 위의 세션과 임시 토큰
파일만 씁니다 — 실제 폐기는 같은 컴퓨터의 다른 실행이 쓰는 토큰까지 죽입니다.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import timedelta

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from backend import config as config_module
from backend import main as main_module
from backend.auth.auth_functions import TokenManager
from backend.auth.token_store import TokenStore, key_of
from backend.config import load_config
from backend.main import app
from backend.nh_api import runtime
from backend.nh_api.session import LIVE, REPLAY_FLAG, Session
from backend.realtime import hub as hub_module
from backend.realtime.feeds import Feed
from backend.realtime.hub import Hub
from backend.realtime.link import LIVE as STREAM_LIVE
from tests.test_environment_switch import _설정, 서버
from tests.test_realtime_link import INIT_OK, FakeConnect, FakeSocket, 기다린다

주소 = "/api/auth/reissue"


class 번호토큰서버(서버):
    """발급할 때마다 다른 토큰을 줍니다(`TOKEN-1`, `TOKEN-2` …). `같은토큰` 이면 늘 같은 글자."""

    def __init__(self, *, 같은토큰: bool = False) -> None:
        super().__init__()
        self.번호 = 0
        self.같은토큰 = 같은토큰

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token") and self.거절 is None:
            self.요청들.append(request)
            self.번호 += 1
            글자 = "TOKEN-SAME" if self.같은토큰 else f"TOKEN-{self.번호}"
            return httpx.Response(
                200, json={"access_token": 글자, "token_type": "Bearer", "expires_in": "3600"}
            )
        return super().__call__(request)


@pytest.fixture
def 자리(tmp_path, monkeypatch):
    """임시 설정 + 임시 토큰 파일을 쓰는 가짜 전송로 세션을 앱의 접속 자리로 둡니다."""
    monkeypatch.delenv(REPLAY_FLAG, raising=False)
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    보관 = TokenStore(tmp_path / "tokens.json")

    def 세우기(handler: 서버 | None = None, **설정) -> tuple[서버, Session]:
        path.write_text(yaml.safe_dump(_설정(**설정), allow_unicode=True), encoding="utf-8")
        handler = handler or 번호토큰서버()
        config = load_config(path)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        session = Session(
            mode=LIVE, config=config, client=client, tokens=TokenManager(config, client=client, store=보관)
        )
        runtime.use(session)
        return handler, session

    try:
        yield 세우기, 보관
    finally:
        runtime.reset()
        asyncio.run(hub_module.reset())
        main_module._reissuing.clear()


def _폐기들(handler) -> list[str]:
    return [r.headers.get("Authorization", "") for r in handler.보낸것("/revoke")]


def _다시받기(market="domestic", environment="paper"):
    return TestClient(app).post(주소, json={"environment": environment, "market": market})


# ── 차례 ──────────────────────────────────────────────────


def test_가진_토큰을_폐기하고_같은_키로_새로_받는다(자리):
    세우기, 보관 = 자리
    handler, session = 세우기(default="paper")
    session.tokens.token("domestic", "paper")  # TOKEN-1

    응답 = _다시받기()

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert (몸["environment"], 몸["market"]) == ("paper", "domestic")
    assert (몸["revoked"], 몸["revokeFailed"], 몸["sameToken"], 몸["stream"]) == (True, False, False, "idle")
    assert 몸["reissuedAt"].endswith("+09:00") and 몸["expiresAt"].endswith("+09:00")
    assert _폐기들(handler) == ["Bearer TOKEN-1"]
    폐기 = handler.보낸것("/revoke")[0]
    assert json.loads(폐기.content)["appkey"] == "PAPERDOM", "같은 키로 폐기합니다."
    assert len(handler.보낸것("/token")) == 2
    assert 보관.read()[key_of("paper", "domestic")].access_token == "TOKEN-2"
    assert session.tokens.token("domestic", "paper").access_token == "TOKEN-2"
    assert len(handler.보낸것("/token")) == 2, "새 토큰을 담아 두어 다시 받지 않습니다."


def test_가진_토큰이_없으면_폐기없이_받기만_한다(자리):
    세우기, _ = 자리
    handler, _ = 세우기(default="paper")

    몸 = _다시받기().json()

    assert (몸["revoked"], 몸["revokeFailed"], 몸["sameToken"]) == (False, False, False)
    assert handler.보낸것("/revoke") == []
    assert len(handler.보낸것("/token")) == 1


def test_파일에만_있는_토큰도_폐기한다(자리):
    """앱을 다시 켜 메모리는 비었고 파일에만 남은 경우입니다."""
    세우기, 보관 = 자리
    handler, session = 세우기(default="paper")
    session.tokens.token("domestic", "paper")  # 파일에도 TOKEN-1
    session.tokens.clear()

    몸 = _다시받기().json()

    assert 몸["revoked"] is True
    assert _폐기들(handler) == ["Bearer TOKEN-1"]


@pytest.mark.parametrize("실패", ["거절", "시간_초과"])
def test_폐기가_실패해도_새로_받는다(자리, 실패):
    세우기, 보관 = 자리
    handler, session = 세우기(default="paper")
    session.tokens.token("domestic", "paper")

    def 막기(request):
        if not request.url.path.endswith("/revoke"):
            return None
        if 실패 == "거절":
            return httpx.Response(500, json={"message": "no"})
        raise httpx.ReadTimeout("느림", request=request)

    handler.거절 = 막기
    응답 = _다시받기()

    assert 응답.status_code == 200
    assert (응답.json()["revoked"], 응답.json()["revokeFailed"]) == (False, True)
    assert key_of("paper", "domestic") in 보관.read(), "새로 받은 토큰을 담아 둡니다."
    assert len(handler.보낸것("/token")) == 2


def test_새_토큰이_옛_토큰과_같으면_알린다(자리):
    """이용 내역 변경이 반영되지 않았을 수 있다는 뜻입니다."""
    세우기, _ = 자리
    handler, session = 세우기(번호토큰서버(같은토큰=True), default="paper")
    session.tokens.token("domestic", "paper")

    assert _다시받기().json()["sameToken"] is True


@pytest.mark.parametrize(
    "답, 상태, 문장",
    [
        ("거절", 502, main_module.REISSUE_REFUSED),
        ("끊김", 504, main_module.REISSUE_UNREACHABLE),
    ],
)
def test_새로_받지_못하면_자리를_비우고_실패로_답한다(자리, 답, 상태, 문장):
    세우기, 보관 = 자리
    handler, session = 세우기(default="paper")
    session.tokens.token("domestic", "paper")

    def 막기(request):
        if not request.url.path.endswith("/token"):
            return None
        if 답 == "거절":
            return httpx.Response(401, json={"message": "no"})
        raise httpx.ConnectError("끊김", request=request)

    handler.거절 = 막기
    응답 = _다시받기()

    assert 응답.status_code == 상태
    assert 응답.json()["detail"] == 문장
    assert key_of("paper", "domestic") not in 보관.read()
    assert session.tokens._cached(("paper", "domestic"), margin=timedelta(0)) is None


# ── 거절 ──────────────────────────────────────────────────


def test_지금_쓰는_환경이_아니면_받지_않는다(자리):
    세우기, _ = 자리
    handler, _ = 세우기(default="paper", real_domestic=True)

    응답 = _다시받기(environment="real")

    assert 응답.status_code == 400
    assert 응답.json()["detail"] == main_module.REISSUE_NOT_ACTIVE
    assert handler.요청들 == []


def test_인증_정보가_없는_시장은_받지_않는다(자리):
    세우기, _ = 자리
    handler, _ = 세우기(default="real", real_domestic=True, real_overseas=False)

    응답 = _다시받기(market="overseas", environment="real")

    assert 응답.status_code == 400
    assert "인증 정보가 없어" in 응답.json()["detail"]
    assert handler.요청들 == []


def test_모양이_틀리면_422():
    for 몸 in ({"environment": "paper", "market": "lme"}, {"environment": "demo", "market": "domestic"}, {}):
        assert TestClient(app).post(주소, json=몸).status_code == 422, 몸


def test_재생_모드에서는_받지_않는다(자리, monkeypatch):
    세우기, _ = 자리
    handler, _ = 세우기(default="paper")
    monkeypatch.setenv(REPLAY_FLAG, "1")

    응답 = _다시받기()

    assert 응답.status_code == 409
    assert 응답.json()["detail"] == main_module.REPLAY_NO_REISSUE
    assert handler.요청들 == []


def test_같은_자리를_받는_중이면_겹쳐_받지_않는다(자리):
    세우기, _ = 자리
    handler, _ = 세우기(default="paper")
    main_module._reissuing.add(("paper", "domestic"))

    응답 = _다시받기()

    assert 응답.status_code == 409
    assert 응답.json()["detail"] == main_module.REISSUE_BUSY
    assert handler.요청들 == []
    # 다른 시장은 막지 않습니다.
    assert _다시받기(market="overseas").status_code == 200


def test_토큰_글자는_답에도_기록에도_없다(자리, caplog):
    세우기, _ = 자리
    handler, session = 세우기(default="paper")
    session.tokens.token("domestic", "paper")
    handler.거절 = lambda r: httpx.Response(500) if r.url.path.endswith("/revoke") else None

    with caplog.at_level("DEBUG"):
        응답 = _다시받기()

    assert "TOKEN-" not in 응답.text
    assert "TOKEN-" not in caplog.text


# ── 잠금은 자리마다 ─────────────────────────────────────────


def test_한_시장을_다시_받는_동안_다른_시장은_기다리지_않는다(자리):
    """국내 폐기가 서버에서 멈춰 있어도 해외 토큰은 곧바로 옵니다."""
    세우기, _ = 자리
    handler, session = 세우기(default="paper")
    session.tokens.token("domestic", "paper")
    붙잡힘 = threading.Event()
    놓아줌 = threading.Event()

    def 멈춤(request):
        if request.url.path.endswith("/revoke"):
            붙잡힘.set()
            놓아줌.wait(5)
        return None

    handler.거절 = 멈춤
    일꾼 = threading.Thread(target=lambda: session.tokens.reissue("domestic", "paper"))
    일꾼.start()
    try:
        assert 붙잡힘.wait(2), "국내 폐기가 시작되어야 합니다."
        해외 = threading.Thread(target=lambda: session.tokens.token("overseas", "paper"))
        해외.start()
        해외.join(1)
        assert not 해외.is_alive(), "해외 토큰이 국내 폐기를 기다렸습니다."
    finally:
        놓아줌.set()
        일꾼.join(5)


# ── 실시간 ─────────────────────────────────────────────────


def test_그_시장의_실시간만_다시_붙고_환경_알림은_없다(자리):
    세우기, _ = 자리
    handler, session = 세우기(default="paper")
    소켓들 = [FakeSocket([INIT_OK]) for _ in range(3)]
    connect = FakeConnect(*소켓들)
    국내 = Feed("domestic-day", "quote", "A7569000")
    해외 = Feed("overseas", "quote", "MESZ26")

    async def 실행():
        engine = Hub(session=session, connect=connect, flush_interval=0.01, session_clock=False)
        client = engine.attach("screen")
        await engine.declare("screen", {국내: 1, 해외: 1})
        await 기다린다(lambda: len(connect.urls) == 2)
        await 기다린다(
            lambda: sum(m.get("state") == STREAM_LIVE for m in list(client.queue._queue)) >= 2
        )
        while not client.queue.empty():
            client.queue.get_nowait()
        해외그룹 = engine._groups["overseas"]

        답 = await engine.reconnect_market("domestic")
        await 기다린다(lambda: len(connect.urls) == 3)
        await 기다린다(lambda: any(m.get("state") == STREAM_LIVE for m in list(client.queue._queue)))
        받은것 = []
        while not client.queue.empty():
            받은것.append(client.queue.get_nowait())
        같은해외 = engine._groups["overseas"] is 해외그룹
        await engine.stop()
        return 답, 받은것, 같은해외

    답, 받은것, 같은해외 = asyncio.run(실행())

    assert 답 == "reconnected"
    assert 같은해외, "해외 연결은 그대로입니다."
    assert not [m for m in 받은것 if m["type"] == "environment"]
    assert {m["market"] for m in 받은것 if m["type"] == "status"} == {"domestic"}
    # 국내 접속키를 두 번(처음·다시), 해외는 한 번 받았습니다.
    받은키 = [r.headers.get("Authorization", "") for r in handler.보낸것("/web-socket-key")]
    assert len(받은키) == 3
    먼저닫힌 = [소켓 for 소켓 in 소켓들 if 소켓.closed]
    assert len(먼저닫힌) >= 1


def test_구독이_없으면_실시간은_할_일이_없다(자리):
    세우기, _ = 자리
    _, session = 세우기(default="paper")

    async def 실행():
        engine = Hub(session=session, connect=FakeConnect(), flush_interval=0.01, session_clock=False)
        try:
            return await engine.reconnect_market("domestic")
        finally:
            await engine.stop()

    assert asyncio.run(실행()) == "idle"


def test_기동과_전환_경로에는_다시_받기가_없다():
    import inspect

    for 함수 in (main_module.lifespan, main_module._switch_environment, runtime.activate):
        assert "reissue" not in inspect.getsource(함수), 함수.__name__
