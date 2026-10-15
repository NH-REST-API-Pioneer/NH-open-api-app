"""활성 환경 — 화면이 믿는 환경과 서버가 쓰는 환경이 어긋나지 않는지.

**어떤 시험도 NH선물 서버에 붙지 않습니다.** 접속 자리는 가짜 전송로 위의 세션이고,
설정 파일은 임시 폴더에 만듭니다. 실시간 연결도 대본대로 답하는 소켓입니다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from backend import config as config_module
from backend import orders
from backend.auth.auth_functions import TokenManager
from backend.config import load_config
from backend.main import app
from backend.nh_api import runtime
from backend.nh_api.session import LIVE, REPLAY_FLAG, Session, create_session
from backend.realtime import hub as hub_module
from backend.realtime.feeds import Feed
from backend.realtime.hub import Hub
from backend.realtime.link import LIVE as STREAM_LIVE
from tests.test_realtime_link import INIT_OK, FakeConnect, FakeSocket, 기다린다

PAPER_HOST = "paper.test"
REAL_HOST = "real.test"

현재가 = {"sym_exch": "A7569000", "last_pric": "1338.50", "trd_qty": "6850"}
주문응답 = {"ord_no": "5959762237", "msg_cd": "", "msg_cntn": ""}


def _설정(*, default="paper", real_domestic=True, real_overseas=False) -> dict:
    """임시 설정. 모의는 두 시장, 실전은 시험이 고르는 만큼."""
    made = {
        "default_environment": default,
        "paper": {
            "base_url": f"https://{PAPER_HOST}",
            "domestic": {"app_key": "PAPERDOM", "app_secret": "PAPERDOMSECRET"},
            "overseas": {"app_key": "PAPEROVS", "app_secret": "PAPEROVSSECRET"},
        },
        "real": {"base_url": f"https://{REAL_HOST}"},
    }
    if real_domestic:
        made["real"]["domestic"] = {"app_key": "REALDOM", "app_secret": "REALDOMSECRET"}
    if real_overseas:
        made["real"]["overseas"] = {"app_key": "REALOVS", "app_secret": "REALOVSSECRET"}
    return made


class 서버:
    """요청을 받아 두고 정해 둔 응답을 돌려줍니다. 어느 환경(호스트)으로 왔는지 남깁니다."""

    def __init__(self) -> None:
        self.요청들: list[httpx.Request] = []
        # 시험이 끼우는 거절 규칙. 요청을 받아 응답을 돌려주면 그것으로 답합니다.
        self.거절: Callable[[httpx.Request], httpx.Response | None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.요청들.append(request)
        if self.거절 is not None:
            refused = self.거절(request)
            if refused is not None:
                return refused
        path = request.url.path
        if path.endswith("/token"):
            appkey = parse_qs(request.content.decode())["appkey"][0]
            return httpx.Response(
                200,
                json={
                    "access_token": f"TOKEN-{request.url.host}-{appkey}",
                    "token_type": "Bearer",
                    "expires_in": "3600",
                },
            )
        if path.endswith("/web-socket-key"):
            return httpx.Response(200, json={"access_key": f"WSKEY-{request.url.host}"})
        if path.endswith("/order"):
            return httpx.Response(200, json=주문응답)
        return httpx.Response(200, json=현재가)

    def 보낸것(self, path_suffix: str) -> list[httpx.Request]:
        return [r for r in self.요청들 if r.url.path.endswith(path_suffix)]


def _세션(config, handler) -> Session:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Session(
        mode=LIVE, config=config, client=client, tokens=TokenManager(config, client=client)
    )


@pytest.fixture(autouse=True)
def 빈_실행목록(tmp_path, monkeypatch):
    """**앞선 시험이 세워 둔 실행도 안 봅니다.**

    환경 전환은 도는 실행이 하나라도 있으면 거절합니다(결정 13). 파일은
    `conftest` 가 이미 임시 자리로 돌려 두었지만, 그것은 **자리**를 옮길 뿐이라
    한 판 안에서 앞선 시험이 앱의 실행 목록에 엔진을 세워 두면 여기까지 따라
    옵니다. 목록 자체를 새로 세워 그 길도 끊습니다.

    거절을 보는 시험 둘은 제 목록을 따로 세워 끼우므로 이 자리와 무관합니다.
    """
    from backend.strategy import journal as journal_lib
    from backend.strategy import runs as runs_lib
    from backend.strategy import service as strategy_service

    monkeypatch.setattr(
        strategy_service,
        "service",
        strategy_service.RunService(
            store=runs_lib.RunStore(tmp_path / "strategy-runs.json"),
            journal=journal_lib.Journal(tmp_path / "strategy-trades.jsonl"),
        ),
    )


@pytest.fixture
def 실서버_자리(tmp_path, monkeypatch):
    """임시 설정 파일 + 가짜 전송로 세션을 앱의 접속 자리로 둡니다."""
    monkeypatch.delenv(REPLAY_FLAG, raising=False)
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)

    def 세우기(**설정) -> tuple[서버, Session]:
        path.write_text(yaml.safe_dump(_설정(**설정), allow_unicode=True), encoding="utf-8")
        handler = 서버()
        session = _세션(load_config(path), handler)
        runtime.use(session)
        return handler, session

    try:
        yield 세우기, path
    finally:
        runtime.reset()
        asyncio.run(hub_module.reset())


def _파일의_기본환경(path) -> str:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["default_environment"]


# ── 읽기 ────────────────────────────────────────────────────


def test_활성_환경은_접속_자리의_값이다(실서버_자리):
    세우기, _ = 실서버_자리
    세우기(default="real")

    응답 = TestClient(app).get("/api/config")

    assert 응답.status_code == 200
    assert 응답.json()["active_environment"] == "real"
    assert 응답.headers["x-nh-environment"] == "real"


# ── 전환 ────────────────────────────────────────────────────


def test_전환하면_파일과_접속_자리가_함께_바뀐다(실서버_자리):
    세우기, path = 실서버_자리
    handler, session = 세우기(default="paper")
    앱 = TestClient(app)

    응답 = 앱.put("/api/config", json={"default_environment": "real"})

    assert 응답.status_code == 200
    assert 응답.json() == {"saved": True, "checks": [], "active_environment": "real"}
    assert 응답.headers["x-nh-environment"] == "real"
    assert _파일의_기본환경(path) == "real"
    assert session.config.default_environment == "real"

    # 그 뒤 조회는 실전 주소로, 실전 키로 받은 토큰을 붙여 나갑니다.
    조회 = 앱.post("/api/domestic/price", json={"sym": "A7569000"})
    assert 조회.status_code == 200
    assert 조회.headers["x-nh-environment"] == "real"
    나간것 = handler.보낸것("/domestic/price")[-1]
    assert 나간것.url.host == REAL_HOST
    assert 나간것.headers["Authorization"] == f"Bearer TOKEN-{REAL_HOST}-REALDOM"
    # 전환만으로는 토큰을 발급받지 않습니다 — 조회가 처음 물을 때 한 번입니다.
    assert [r.url.host for r in handler.보낸것("/token")] == [REAL_HOST]


def test_전환은_양방향이다(실서버_자리):
    세우기, path = 실서버_자리
    handler, session = 세우기(default="real")
    앱 = TestClient(app)

    assert 앱.put("/api/config", json={"default_environment": "paper"}).status_code == 200
    앱.post("/api/domestic/price", json={"sym": "A7569000"})
    assert 앱.put("/api/config", json={"default_environment": "real"}).status_code == 200
    앱.post("/api/domestic/price", json={"sym": "A7569000"})

    assert [r.url.host for r in handler.보낸것("/domestic/price")] == [PAPER_HOST, REAL_HOST]
    assert _파일의_기본환경(path) == "real"
    # 두 환경의 토큰은 따로 받고, 돌아왔을 때 다시 받지 않습니다.
    assert [r.url.host for r in handler.보낸것("/token")] == [PAPER_HOST, REAL_HOST]


def test_대상_환경에_인증_정보가_없으면_바꾸지_않는다(실서버_자리):
    세우기, path = 실서버_자리
    handler, session = 세우기(default="paper", real_domestic=False)

    응답 = TestClient(app).put("/api/config", json={"default_environment": "real"})

    assert 응답.status_code == 400
    assert "실전" in 응답.json()["detail"]
    assert _파일의_기본환경(path) == "paper"
    assert session.config.default_environment == "paper"
    assert handler.요청들 == [], "다른 환경으로 우회해 부르지 않습니다."


def test_시장_하나만_있어도_전환할_수_있다(실서버_자리):
    """국내만 쓰는 사람도 실전으로 옮길 수 있어야 합니다."""
    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper", real_domestic=False, real_overseas=True)

    응답 = TestClient(app).put("/api/config", json={"default_environment": "real"})

    assert 응답.status_code == 200
    assert 응답.json()["active_environment"] == "real"


def test_같은_값으로_전환하면_아무_일도_없다(실서버_자리):
    세우기, path = 실서버_자리
    handler, _ = 세우기(default="paper")
    앞 = path.read_text(encoding="utf-8")

    응답 = TestClient(app).put("/api/config", json={"default_environment": "paper"})

    assert 응답.status_code == 200
    assert 응답.json()["active_environment"] == "paper"
    assert path.read_text(encoding="utf-8") == 앞
    assert handler.요청들 == []


def test_빈_요청은_거절한다(실서버_자리):
    세우기, _ = 실서버_자리
    세우기()
    assert TestClient(app).put("/api/config", json={}).status_code == 400
    없는환경 = {"default_environment": "stage"}
    assert TestClient(app).put("/api/config", json=없는환경).status_code == 422
    # 인증 정보 항목 이름이 틀린 것은 전과 같이 400 입니다.
    틀린이름 = {"environments": {"paper": {"lme": {"app_key": "x"}}}}
    assert TestClient(app).put("/api/config", json=틀린이름).status_code == 400


def test_다른_전환이_진행_중이면_기다리라고_한다(실서버_자리):
    세우기, path = 실서버_자리
    _, session = 세우기(default="paper")
    assert runtime.begin_switch()
    try:
        응답 = TestClient(app).put("/api/config", json={"default_environment": "real"})
    finally:
        runtime.end_switch()

    assert 응답.status_code == 409
    assert session.config.default_environment == "paper"
    assert _파일의_기본환경(path) == "paper"


def test_재생_모드는_파일을_안_건드린다(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.setenv(REPLAY_FLAG, "1")
    session = create_session(replay=True)
    runtime.use(session)
    try:
        응답 = TestClient(app).put("/api/config", json={"default_environment": "real"})
    finally:
        runtime.reset()
        asyncio.run(hub_module.reset())

    assert 응답.status_code == 200
    assert 응답.json()["active_environment"] == "real"
    assert session.config.default_environment == "real"
    assert not path.exists()


# ── 인증 정보를 저장하면 접속 자리도 새 키를 쓴다 ─────────────


def test_키를_저장하면_옛_설정으로_토큰을_받지_않는다(실서버_자리):
    세우기, _ = 실서버_자리
    handler, session = 세우기(default="paper")
    앱 = TestClient(app)
    앱.post("/api/domestic/price", json={"sym": "A7569000"})  # 옛 키로 토큰 하나

    응답 = 앱.put(
        "/api/config",
        json={"environments": {"paper": {"domestic": {"app_key": "PAPERDOM2"}}}},
    )
    assert 응답.status_code == 200
    # 저장 때의 접속 확인이 새 키로 한 번 발급받고, 그 토큰이 보관되어
    # 다음 조회는 다시 발급받지 않습니다.
    assert 응답.json()["checks"] == [{"environment": "paper", "market": "domestic", "ok": True}]
    앱.post("/api/domestic/price", json={"sym": "A7569000"})

    발급 = [parse_qs(r.content.decode())["appkey"][0] for r in handler.보낸것("/token")]
    assert 발급 == ["PAPERDOM", "PAPERDOM2"]
    assert session.config.market("domestic", "paper").app_key == "PAPERDOM2"
    # 활성 환경은 그대로입니다 — 키 저장은 환경을 바꾸지 않습니다.
    assert 응답.json()["active_environment"] == "paper"


def test_접속_확인은_접속_자리의_전송로로만_간다(실서버_자리):
    """확인이 거절되면 저장은 남고 `ok` 만 거짓입니다."""
    세우기, _ = 실서버_자리
    handler, session = 세우기(default="paper")

    def 거절(request):
        if request.url.path.endswith("/token") and b"BADKEY" in request.content:
            return httpx.Response(400, json={"errorCode": "EAU025"})
        return None

    handler.거절 = 거절
    응답 = TestClient(app).put(
        "/api/config",
        json={"environments": {"paper": {"overseas": {"app_key": "BADKEY", "app_secret": "S"}}}},
    )

    assert 응답.status_code == 200
    assert 응답.json()["checks"] == [{"environment": "paper", "market": "overseas", "ok": False}]
    assert session.config.market("overseas", "paper").app_key == "BADKEY", "저장은 남습니다."


def test_재생_모드에서는_인증_정보를_저장하지_않는다(tmp_path, monkeypatch):
    """사용자 설정 파일을 안 건드리고 거절합니다 — 만들어 낸 토큰으로 확인하지도, 실서버에 가지도 않습니다."""
    from backend.nh_api.fixtures import load_fixtures
    from backend.nh_api.replay import ReplayTransport
    from backend.nh_api.session import REPLAY, replay_config

    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.setenv(REPLAY_FLAG, "1")
    store = load_fixtures()
    전송 = ReplayTransport(store)
    client = httpx.Client(transport=전송)
    config = replay_config()
    session = Session(
        mode=REPLAY, config=config, client=client, tokens=TokenManager(config, client=client), fixtures=store
    )
    runtime.use(session)
    try:
        응답 = TestClient(app).put(
            "/api/config",
            json={"environments": {"paper": {"domestic": {"app_key": "K", "app_secret": "S"}}}},
        )
    finally:
        runtime.reset()

    assert 응답.status_code == 409
    assert "저장하지 않습니다" in 응답.json()["detail"]
    assert not path.exists(), "설정 파일을 만들지도 쓰지도 않습니다."
    assert 전송.log == [], "토큰 발급을 청하지 않습니다 — 만들어 낸 것으로도."


def test_모든_키를_비운_저장은_옛_키로_확인하지_않는다(실서버_자리):
    """파일에 남은 인증 정보가 없으면 접속 자리는 옛 설정을 들지만, 그 키로 「확인됨」을 내지 않습니다."""
    세우기, path = 실서버_자리
    handler, session = 세우기(default="paper", real_domestic=False)
    빈칸 = {"app_key": "", "app_secret": ""}

    응답 = TestClient(app).put(
        "/api/config", json={"environments": {"paper": {"domestic": 빈칸, "overseas": 빈칸}}}
    )

    assert 응답.status_code == 200
    assert 응답.json()["checks"] == []
    assert handler.보낸것("/token") == [], "옛 키로 발급받지 않습니다."
    assert session.config.market("domestic", "paper").app_key == "PAPERDOM", "접속 자리는 옛 설정 그대로"


def test_재생_세션에서는_확인_자체가_빈_배열이다(monkeypatch):
    """라우트가 먼저 거절하지만, 확인 함수도 재생이면 만들어 낸 발급으로 답하지 않습니다."""
    from backend import main as main_module

    session = create_session(replay=True)
    runtime.use(session)
    try:
        assert main_module._check_credentials({"paper": {"domestic": {"app_key": "K"}}}) == []
    finally:
        runtime.reset()


def test_접속_자리를_못_만들면_확인할_것이_없다(tmp_path, monkeypatch):
    """키 하나만 넣어 인증 정보가 아직 완성되지 않은 첫 저장."""
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.delenv(REPLAY_FLAG, raising=False)
    runtime.reset()
    try:
        응답 = TestClient(app).put(
            "/api/config",
            json={"environments": {"paper": {"domestic": {"app_key": "ONLYKEY"}}}},
        )
    finally:
        runtime.reset()

    assert 응답.status_code == 200
    assert 응답.json()["checks"] == []
    assert 응답.json()["active_environment"] is None


def test_키_저장과_전환을_한_번에_하면_새_키로_검증한다(실서버_자리):
    """실전 키를 넣으면서 실전으로 옮기는 한 번의 저장."""
    세우기, path = 실서버_자리
    handler, session = 세우기(default="paper", real_domestic=False)

    응답 = TestClient(app).put(
        "/api/config",
        json={
            "environments": {"real": {"domestic": {"app_key": "REALDOM", "app_secret": "S"}}},
            "default_environment": "real",
        },
    )

    assert 응답.status_code == 200
    assert 응답.json()["checks"] == [{"environment": "real", "market": "domestic", "ok": True}]
    assert [r.url.host for r in handler.보낸것("/token")] == [REAL_HOST]
    assert 응답.json()["active_environment"] == "real"
    assert session.config.default_environment == "real"
    assert _파일의_기본환경(path) == "real"


# ── 주문은 화면이 믿는 환경과 대조한다 ─────────────────────────


class 적어두는호출부:
    def __init__(self, environment="paper"):
        self.보낸것 = []
        self.session = _가짜세션(environment)

    def call(self, api_id, payload, environment=None):
        self.보낸것.append(api_id)
        from backend.nh_api.client import ApiResult

        return ApiResult(
            api_id=api_id,
            environment=self.session.config.default_environment,
            market=api_id.split("_")[0],
            http_status=200,
            body=주문응답,
            headers={},
        )


def _가짜세션(environment):
    from types import SimpleNamespace

    return SimpleNamespace(
        config=SimpleNamespace(default_environment=environment), is_replay=False
    )


국내주문 = {"sym": "A7569000", "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"}
해외주문 = {"sym": "ESZ26", "side": "buy", "qt_div_cd": "1", "glb_ord_tp_cd": "1", "ord_qty": 1}


def _주문라우트():
    from backend.domestic_futureoption import domestic_routes
    from backend.overseas_futureoption import overseas_routes

    return (
        ("/api/domestic/order", 국내주문, domestic_routes.get_client),
        ("/api/domestic/modify", {**국내주문, "org_ord_no": "1"}, domestic_routes.get_client),
        (
            "/api/domestic/cancel",
            {"sym": "A7569000", "side": "buy", "ord_qty": 1, "org_ord_no": "1"},
            domestic_routes.get_client,
        ),
        ("/api/overseas/order", 해외주문, overseas_routes.get_client),
    )


@pytest.mark.parametrize("주소, 본문, 의존성", _주문라우트())
def test_화면_환경이_서버와_다르면_주문을_보내지_않는다(주소, 본문, 의존성):
    호출부 = 적어두는호출부(environment="real")
    app.dependency_overrides[의존성] = lambda: 호출부
    try:
        응답 = TestClient(app).post(주소, json={**본문, "environment": "paper"})
    finally:
        app.dependency_overrides.pop(의존성, None)

    assert 응답.status_code == 400
    assert "모의" in 응답.json()["detail"] and "실전" in 응답.json()["detail"]
    assert 응답.headers["x-nh-environment"] == "real"
    assert 호출부.보낸것 == [], "NH선물로 나가면 안 됩니다."


@pytest.mark.parametrize("주소, 본문, 의존성", _주문라우트())
def test_화면_환경이_서버와_같으면_주문이_나간다(주소, 본문, 의존성):
    호출부 = 적어두는호출부(environment="real")
    app.dependency_overrides[의존성] = lambda: 호출부
    try:
        응답 = TestClient(app).post(주소, json={**본문, "environment": "real"})
    finally:
        app.dependency_overrides.pop(의존성, None)

    assert 응답.status_code == 200
    assert 응답.json()["environment"] == "real"
    assert len(호출부.보낸것) == 1


@pytest.mark.parametrize("주소, 본문, 의존성", _주문라우트())
def test_환경_칸이_없으면_주문을_받지_않는다(주소, 본문, 의존성):
    호출부 = 적어두는호출부()
    app.dependency_overrides[의존성] = lambda: 호출부
    try:
        assert TestClient(app).post(주소, json=본문).status_code == 422
        assert TestClient(app).post(주소, json={**본문, "environment": "live"}).status_code == 422
    finally:
        app.dependency_overrides.pop(의존성, None)
    assert 호출부.보낸것 == []


@pytest.mark.parametrize("주소, 본문, 의존성", _주문라우트())
def test_전환_중에는_주문을_받지_않는다(주소, 본문, 의존성):
    호출부 = 적어두는호출부(environment="paper")
    app.dependency_overrides[의존성] = lambda: 호출부
    assert runtime.begin_switch()
    try:
        응답 = TestClient(app).post(주소, json={**본문, "environment": "paper"})
    finally:
        runtime.end_switch()
        app.dependency_overrides.pop(의존성, None)

    assert 응답.status_code == 409
    assert 응답.json()["detail"] == orders.SWITCHING
    assert 호출부.보낸것 == []


def test_거부의_차례는_전환_중_못_읽음_불일치다():
    """전환 중에는 대조 결과 자체를 믿을 수 없어 그것이 먼저입니다."""
    from types import SimpleNamespace

    못읽음 = SimpleNamespace(session=_가짜세션(None))
    assert orders.refusal(못읽음, "paper") == (500, orders.UNKNOWN_ENVIRONMENT)
    assert orders.refusal(SimpleNamespace(session=_가짜세션("real")), "paper")[0] == 400
    assert orders.refusal(SimpleNamespace(session=_가짜세션("real")), "real") is None
    assert runtime.begin_switch()
    try:
        assert orders.refusal(못읽음, "paper") == (409, orders.SWITCHING)
    finally:
        runtime.end_switch()


# ── 응답 헤더는 요청이 나간 환경을 적는다 ──────────────────────


def test_응답_헤더는_요청이_나간_환경이다(실서버_자리):
    """전환 직전에 나간 요청의 응답에는 옛 환경이 찍혀야 화면이 버릴 수 있습니다."""
    세우기, _ = 실서버_자리
    handler, session = 세우기(default="paper")
    앱 = TestClient(app)

    앞 = 앱.post("/api/domestic/price", json={"sym": "A7569000"})
    앱.put("/api/config", json={"default_environment": "real"})
    뒤 = 앱.post("/api/domestic/price", json={"sym": "A7569000"})

    assert 앞.headers["x-nh-environment"] == "paper"
    assert 뒤.headers["x-nh-environment"] == "real"
    # 헤더는 응답 시점의 활성 환경이 아니라 그 요청이 나간 환경입니다.
    from backend.nh_api.client import last_environment

    last_environment.set("paper")
    try:
        fake = httpx.Response(200)
        runtime.stamp_environment(fake)
        assert fake.headers["x-nh-environment"] == "paper"
    finally:
        last_environment.set(None)


# ── 실시간 연결을 갈아 끼운다 ───────────────────────────────


def test_전환하면_실시간_연결만_새_환경으로_다시_연다(tmp_path):
    """붙어 있는 화면은 그대로, NH선물 쪽 연결만 새로 엽니다."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(_설정(default="paper", real_domestic=True), allow_unicode=True),
        encoding="utf-8",
    )
    handler = 서버()
    session = _세션(load_config(path), handler)
    첫소켓, 둘째소켓 = FakeSocket([INIT_OK]), FakeSocket([INIT_OK])
    connect = FakeConnect(첫소켓, 둘째소켓)
    QUOTE = Feed("domestic-day", "quote", "A7569000")

    async def 실행():
        engine = Hub(session=session, connect=connect, flush_interval=0.01, session_clock=False)
        client = engine.attach("screen")
        await engine.declare("screen", {QUOTE: 1})
        await 기다린다(lambda: any(m.get("state") == STREAM_LIVE for m in list(client.queue._queue)))
        while not client.queue.empty():
            client.queue.get_nowait()

        session.reload(_바꾼설정(session.config, "real"))
        await engine.reconnect()
        await 기다린다(lambda: len(connect.urls) == 2)
        await 기다린다(
            lambda: any(
                m.get("state") == STREAM_LIVE and m.get("refill") for m in list(client.queue._queue)
            )
        )
        받은것 = []
        while not client.queue.empty():
            받은것.append(client.queue.get_nowait())
        아직붙음 = "screen" in engine._clients
        await engine.stop()
        return 받은것, 아직붙음

    받은것, 아직붙음 = asyncio.run(실행())
    session.close()

    assert 아직붙음, "화면은 그대로 붙어 있어야 합니다."
    assert 받은것[0] == {"type": "environment", "active": "real"}
    상태들 = [(m["state"], m.get("refill")) for m in 받은것 if m["type"] == "status"]
    assert ("stopped", None) in 상태들
    assert (STREAM_LIVE, True) in 상태들, "다시 붙었으니 조회로 채우라고 알립니다."
    assert [m for m in 받은것 if m["type"] == "subscriptions"], "선언은 그대로 다시 답합니다."
    # 첫 연결은 모의 주소, 둘째 연결은 실전 주소입니다. 접속키도 실전에서 받았습니다.
    assert connect.urls[0].startswith(f"wss://{PAPER_HOST}/")
    assert connect.urls[1].startswith(f"wss://{REAL_HOST}/")
    assert 첫소켓.closed
    assert [r.url.host for r in handler.보낸것("/web-socket-key")] == [PAPER_HOST, REAL_HOST]
    # 새 연결에도 같은 구독이 다시 걸립니다.
    from backend.realtime.link import ACTION_SUBSCRIBE, subscribe_message

    assert subscribe_message(QUOTE, action=ACTION_SUBSCRIBE) in 둘째소켓.sent


def _바꾼설정(config, environment):
    import dataclasses

    return dataclasses.replace(config, default_environment=environment)


def test_돌고_있는_전략_실행이_있으면_안_바꾼다(실서버_자리, monkeypatch, tmp_path):
    """모의와 실전은 다른 계좌라, 판정 중인 실행은 그 경계를 모른 채 이어 갑니다."""
    from backend.strategy import journal as journal_lib
    from backend.strategy import runs as runs_lib
    from backend.strategy import service as strategy_service

    세우기, path = 실서버_자리
    세우기(default="paper")
    실행목록 = strategy_service.RunService(
        store=runs_lib.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("빈것", (), {"locate": lambda self, market, code: None})(),
        hours=type("빈것", (), {"cached": lambda self, market: None})(),
    )
    실행목록._stand(
        runs_lib.Run(
            id="r1",
            version_id="v1",
            code="A7569000",
            session="domestic-day",
            market="domestic",
            state=runs_lib.ARMED,
        )
    )
    실행목록._loaded = True
    monkeypatch.setattr(strategy_service, "service", 실행목록)

    응답 = TestClient(app).put("/api/config", json={"default_environment": "real"})

    assert 응답.status_code == 400
    assert 응답.json()["detail"] == strategy_service.WHY_SWITCH.format(count=1)
    assert _파일의_기본환경(path) == "paper", "파일도 그대로입니다."


def test_중지한_실행은_전환을_막지_않는다(실서버_자리, monkeypatch, tmp_path):
    from backend.strategy import journal as journal_lib
    from backend.strategy import runs as runs_lib
    from backend.strategy import service as strategy_service

    세우기, path = 실서버_자리
    세우기(default="paper")
    실행목록 = strategy_service.RunService(
        store=runs_lib.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("빈것", (), {"locate": lambda self, market, code: None})(),
        hours=type("빈것", (), {"cached": lambda self, market: None})(),
    )
    실행목록._stand(
        runs_lib.Run(
            id="r1",
            version_id="v1",
            code="A7569000",
            session="domestic-day",
            market="domestic",
            state=runs_lib.PAUSED,
        )
    )
    실행목록._loaded = True
    monkeypatch.setattr(strategy_service, "service", 실행목록)

    응답 = TestClient(app).put("/api/config", json={"default_environment": "real"})

    assert 응답.status_code == 200
    assert _파일의_기본환경(path) == "real"


# -- 키가 바뀐 자리의 옛 토큰 폐기 ------------------------------------------------


def _폐기들(handler) -> list[tuple[str, str]]:
    """받은 폐기 요청의 (appkey, Authorization)."""
    import json as _json

    return [
        (_json.loads(r.content)["appkey"], r.headers.get("Authorization", ""))
        for r in handler.보낸것("/revoke")
    ]


def _저장(json) -> "httpx.Response":
    return TestClient(app).put("/api/config", json={"environments": json})


def test_키가_바뀌면_옛_토큰을_옛_키로_폐기하고_파일에서_지운다(실서버_자리):
    from backend.auth import token_store as 보관

    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    TestClient(app).post("/api/domestic/price", json={"sym": "A7569000"})  # 옛 키로 토큰 하나
    보관.TokenStore().put(
        보관.key_of("paper", "domestic"),
        보관.Stored("TOKEN-paper.test-PAPERDOM", "Bearer", _먼_훗날(), 보관.fingerprint("PAPERDOM")),
    )

    응답 = _저장({"paper": {"domestic": {"app_key": "PAPERDOM2"}}})

    assert 응답.status_code == 200
    assert _폐기들(handler) == [("PAPERDOM", "Bearer TOKEN-paper.test-PAPERDOM")]
    폐기 = handler.보낸것("/revoke")[0]
    assert 폐기.url.host == PAPER_HOST
    import json as _json

    assert _json.loads(폐기.content)["appsecret"] == "PAPERDOMSECRET", "옛 Secret 으로 보냅니다."
    assert 보관.key_of("paper", "domestic") not in 보관.TokenStore().read()


@pytest.mark.parametrize(
    "바꿈",
    [{"app_key": "PAPERDOM"}, {"app_secret": "NEWSECRET"}],
    ids=["같은_키", "Secret_만"],
)
def test_키가_같으면_폐기하지_않는다(실서버_자리, 바꿈):
    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    TestClient(app).post("/api/domestic/price", json={"sym": "A7569000"})

    assert _저장({"paper": {"domestic": 바꿈}}).status_code == 200
    assert handler.보낸것("/revoke") == []


def test_시장을_비우면_옛_토큰을_폐기한다(실서버_자리):
    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    TestClient(app).post("/api/domestic/price", json={"sym": "A7569000"})

    응답 = _저장({"paper": {"domestic": {"app_key": "", "app_secret": ""}}})

    assert 응답.status_code == 200
    assert _폐기들(handler) == [("PAPERDOM", "Bearer TOKEN-paper.test-PAPERDOM")]


def test_받아_둔_토큰이_없으면_폐기도_발급도_없다(실서버_자리):
    """폐기하려고 새로 발급받지 않습니다."""
    from backend.auth import token_store as 보관

    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    보관.TokenStore().drop(보관.key_of("paper", "domestic"))

    응답 = _저장({"paper": {"domestic": {"app_key": "PAPERDOM2"}}})

    assert 응답.status_code == 200
    assert handler.보낸것("/revoke") == []
    # 발급은 저장 뒤 새 키 확인 한 번뿐입니다 — 옛 키로는 받지 않습니다.
    assert [parse_qs(r.content.decode())["appkey"][0] for r in handler.보낸것("/token")] == ["PAPERDOM2"]


def _먼_훗날():
    from datetime import datetime, timedelta

    return datetime.now() + timedelta(hours=6)


@pytest.mark.parametrize("만료", [False, True], ids=["살아_있음", "만료됨"])
def test_파일에만_있는_토큰도_폐기한다_만료된_것은_빼고(실서버_자리, 만료):
    """앱을 다시 켜서 메모리는 비었고 파일에만 남은 경우입니다."""
    from datetime import datetime, timedelta

    from backend.auth import token_store as 보관

    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    언제 = datetime.now() - timedelta(minutes=1) if 만료 else _먼_훗날()
    보관.TokenStore().put(
        보관.key_of("paper", "overseas"),
        보관.Stored("FILE-TOKEN", "Bearer", 언제, 보관.fingerprint("PAPEROVS")),
    )

    assert _저장({"paper": {"overseas": {"app_key": "PAPEROVS2"}}}).status_code == 200

    assert _폐기들(handler) == ([] if 만료 else [("PAPEROVS", "Bearer FILE-TOKEN")])
    assert 보관.key_of("paper", "overseas") not in 보관.TokenStore().read()


def test_파일_토큰이_다른_키의_것이면_폐기하지_않는다(실서버_자리):
    from backend.auth import token_store as 보관

    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    보관.TokenStore().put(
        보관.key_of("paper", "overseas"),
        보관.Stored("OTHER", "Bearer", _먼_훗날(), 보관.fingerprint("SOMEONE-ELSE")),
    )

    assert _저장({"paper": {"overseas": {"app_key": "PAPEROVS2"}}}).status_code == 200
    assert handler.보낸것("/revoke") == []


@pytest.mark.parametrize("실패", ["거절", "시간_초과"])
def test_폐기가_실패해도_저장은_된다(실서버_자리, 실패):
    from backend.auth import token_store as 보관

    세우기, path = 실서버_자리
    handler, _ = 세우기(default="paper")
    TestClient(app).post("/api/domestic/price", json={"sym": "A7569000"})
    보관.TokenStore().put(
        보관.key_of("paper", "domestic"),
        보관.Stored("TOKEN-paper.test-PAPERDOM", "Bearer", _먼_훗날(), 보관.fingerprint("PAPERDOM")),
    )

    def 막기(request):
        if not request.url.path.endswith("/revoke"):
            return None
        if 실패 == "거절":
            return httpx.Response(500, json={"message": "no"})
        raise httpx.ReadTimeout("느림", request=request)

    handler.거절 = 막기
    응답 = _저장({"paper": {"domestic": {"app_key": "PAPERDOM2"}}})

    assert 응답.status_code == 200
    assert len(handler.보낸것("/revoke")) == 1
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["paper"]["domestic"]["app_key"] == "PAPERDOM2"
    assert 보관.key_of("paper", "domestic") not in 보관.TokenStore().read()


def test_두_자리가_바뀌면_자리마다_제_옛_키로_폐기한다(실서버_자리):
    세우기, _ = 실서버_자리
    handler, _ = 세우기(default="paper")
    앱 = TestClient(app)
    앱.post("/api/domestic/price", json={"sym": "A7569000"})
    앱.post("/api/overseas/price", json={"syms": [{"exch_cd": "FCME", "sym": "MESZ26"}]})

    응답 = _저장({"paper": {"domestic": {"app_key": "PAPERDOM2"}, "overseas": {"app_key": "PAPEROVS2"}}})

    assert 응답.status_code == 200
    assert sorted(_폐기들(handler)) == [
        ("PAPERDOM", "Bearer TOKEN-paper.test-PAPERDOM"),
        ("PAPEROVS", "Bearer TOKEN-paper.test-PAPEROVS"),
    ]


def test_재생_세션이면_폐기하지_않는다(monkeypatch, tmp_path):
    """라우트가 먼저 409 로 막지만(위 시험), 폐기 함수도 재생 세션이면 아무것도 부르지 않습니다."""
    from backend import main as main_module

    불린것 = []
    monkeypatch.setattr(main_module, "revoke_token", lambda *a, **k: 불린것.append(a))
    def _아무_설정():
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(_설정()), encoding="utf-8")
        return path

    가짜 = type("세션", (), {"is_replay": True})()
    monkeypatch.setattr(runtime, "held_session", lambda: 가짜)
    main_module._revoke_replaced(load_config(_아무_설정()), {"paper": {"domestic": {"app_key": "X"}}})

    assert 불린것 == []


def test_기동_전환_종료_경로에는_폐기가_없다():
    import inspect

    from backend import main as main_module

    for 함수 in (main_module.lifespan, main_module._switch_environment, runtime.activate):
        원문 = inspect.getsource(함수)
        assert "revoke" not in 원문, 함수.__name__

