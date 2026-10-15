"""시장 참고 자료를 받는 환경 — 해외 품목별 세부정보·해외 만기일·국내 투자자 매매동향.

실전 인증 정보가 있으면 실전에서, 없으면 모의에서 받고, 둘 다 없으면 부르지
않고 실패합니다. 응답의 `x-nh-environment` 헤더는 받은 환경이 아니라 활성
환경입니다. 고르는 규칙은 `backend.nh_api.reference` 에 있습니다.

**어떤 시험도 NH선물 서버에 붙지 않습니다.** 부른 환경만 적어 두는 호출부나
반입해 둔 응답(재생 세션)으로 돕니다.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.config import CONFIG_PATH, Config, ConfigError, EnvironmentConfig, MarketConfig
from backend.domestic_futureoption import domestic_routes
from backend.main import app
from backend.nh_api import runtime
from backend.nh_api.client import TradeClient, last_environment
from backend.nh_api.fixtures import FixtureStore, load_fixtures
from backend.master import master_service
from backend.nh_api.reference import MissingMarketKeys, reference_environment, source_environment
from backend.nh_api.replay import MATCH_API, MATCH_CROSS_ENVIRONMENT, MATCH_EXACT, MATCH_HEADER
from backend.nh_api.session import create_session
from backend.overseas_futureoption import overseas_product_service, overseas_routes
from backend.overseas_futureoption.overseas_product_service import ProductService
from backend.sessions import service as session_service
from backend.sessions.hours import KST

DETAIL = "overseas_product-detail"
EXPIRY = "overseas_product-expiry"
TREND = "domestic_trend-investor"

BOTH = ("domestic", "overseas")


def _설정(*, real=(), paper=(), default="paper"):
    """환경마다 인증 정보가 찬 시장만 값을 넣은 설정. 나머지 시장은 비어 있습니다."""

    def 환경(name, markets):
        def 시장(market):
            key = "k" if market in markets else ""
            return MarketConfig(name, market, key, key)

        return EnvironmentConfig(
            name=name, base_url="http://없음", domestic=시장("domestic"), overseas=시장("overseas")
        )

    return Config(
        default_environment=default,
        environments={"paper": 환경("paper", paper), "real": 환경("real", real)},
    )


class _가짜호출부:
    """NH선물에 붙지 않는 호출부. 어느 API 를 어느 환경으로 불렀는지만 적어 둡니다."""

    def __init__(self, config):
        self.session = SimpleNamespace(config=config, is_replay=False)
        self.calls: list[tuple[str, str | None]] = []

    def call(self, api_id, payload=None, *, environment=None):
        # 진짜 호출부처럼 부른 환경을 적습니다 — 응답 헤더가 이 값을 씁니다.
        last_environment.set(environment)
        self.calls.append((api_id, environment))
        return SimpleNamespace(body={"Occurs1": [], "nxt_key": ""})


def _at(year, month, day, hour=9):
    return datetime(year, month, day, hour, tzinfo=KST)


@pytest.fixture
def 앱에_붙이기():
    """라우트가 쓰는 호출부를 바꿔 끼웁니다. 끝나면 되돌립니다."""
    붙인것 = []

    def 붙이기(호출부):
        for get_client in (overseas_routes.get_client, domestic_routes.get_client):
            app.dependency_overrides[get_client] = lambda: 호출부
            붙인것.append(get_client)
        return TestClient(app)

    try:
        yield 붙이기
    finally:
        for get_client in 붙인것:
            app.dependency_overrides.pop(get_client, None)


def _만기(앱):
    return 앱.post("/api/overseas/product-expiry", json={"sym": "MESU26"})


def _매매동향(앱):
    return 앱.post("/api/domestic/trend-investor", json={"prd": "75"})


# ── 고르는 규칙 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("real", "paper", "market", "expected"),
    [
        (BOTH, BOTH, "overseas", "real"),
        (("domestic",), BOTH, "overseas", "paper"),
        (("domestic",), BOTH, "domestic", "real"),
        ((), ("domestic",), "domestic", "paper"),
    ],
)
def test_실전_인증_정보가_있으면_실전_없으면_모의(real, paper, market, expected):
    assert source_environment(_설정(real=real, paper=paper), market) == expected


def test_어느_환경에도_없으면_고르지_않고_실패한다():
    with pytest.raises(ConfigError):
        source_environment(_설정(real=("domestic",)), "overseas")


def test_블록을_나가면_헤더에_적힐_환경이_되돌아간다():
    호출부 = _가짜호출부(_설정(real=BOTH, paper=BOTH, default="paper"))
    # 앞서 적힌 값이 없으면 활성 환경으로 돌아갑니다.
    last_environment.set(None)
    with reference_environment(호출부, "overseas") as environment:
        호출부.call(DETAIL, environment=environment)
        assert last_environment.get() == "real"
    assert last_environment.get() == "paper"
    # 앞서 적힌 값이 있으면 그 값으로 돌아갑니다.
    last_environment.set("real")
    with reference_environment(호출부, "overseas"):
        호출부.call(DETAIL, environment="paper")
    assert last_environment.get() == "real"
    # 부르다 실패해도 되돌립니다.
    last_environment.set(None)
    with pytest.raises(RuntimeError):
        with reference_environment(호출부, "overseas") as environment:
            호출부.call(DETAIL, environment=environment)
            raise RuntimeError("부르다 실패")
    assert last_environment.get() == "paper"


# ── 해외 품목별 세부정보(하루 캐시) ──────────────────────────


@pytest.mark.parametrize(
    ("real", "paper", "expected"),
    [(BOTH, BOTH, "real"), (("domestic",), BOTH, "paper")],
)
def test_품목_표는_고른_환경에서_받고_표에_적는다(real, paper, expected):
    호출부 = _가짜호출부(_설정(real=real, paper=paper))
    made = ProductService().products(api=호출부, now=_at(2026, 10, 12))
    assert made["environment"] == expected
    assert 호출부.calls == [(DETAIL, expected)]


def test_품목_표는_해외_인증_정보가_어디에도_없으면_부르지_않는다():
    호출부 = _가짜호출부(_설정(real=("domestic",), paper=("domestic",)))
    service = ProductService()
    with pytest.raises(ConfigError):
        service.products(api=호출부, now=_at(2026, 10, 12))
    assert 호출부.calls == []
    assert service.cached() is None


def test_품목_표는_환경을_바꿔도_한_벌이다():
    """활성 환경이 모의든 실전이든 실전에서 받고, 바꿨다고 다시 받지 않습니다."""
    service = ProductService()
    모의 = _가짜호출부(_설정(real=BOTH, paper=BOTH, default="paper"))
    first = service.products(api=모의, now=_at(2026, 10, 12, 9))
    실전 = _가짜호출부(_설정(real=BOTH, paper=BOTH, default="real"))
    second = service.products(api=실전, now=_at(2026, 10, 12, 10))
    assert (first["environment"], second["environment"]) == ("real", "real")
    assert second["source"] == "cache"
    assert 모의.calls == [(DETAIL, "real")] and 실전.calls == []


def test_품목_표_응답의_환경_헤더는_활성_환경이다(앱에_붙이기, monkeypatch):
    호출부 = _가짜호출부(_설정(real=BOTH, paper=BOTH, default="paper"))
    monkeypatch.setattr(overseas_product_service, "service", ProductService())
    응답 = 앱에_붙이기(호출부).post("/api/overseas/product-detail", json={})
    assert 응답.status_code == 200
    assert 응답.json()["environment"] == "real"
    assert 응답.headers["x-nh-environment"] == "paper"
    assert 호출부.calls == [(DETAIL, "real")]


def test_시험에서는_호출부_없이_품목_표를_실서버로_받지_못한다():
    """실서버 세션이 잡혀 있어도 호출부 없이 부른 품목 표 받기는 나가기 전에 멈춥니다."""
    session = create_session(replay=False, config=_설정(real=BOTH))
    runtime.use(session)
    try:
        with pytest.raises(AssertionError, match="실서버"):
            ProductService().products(now=_at(2026, 10, 12))
    finally:
        runtime.reset()


# ── 해외 만기일·국내 투자자 매매동향(라우트) ─────────────────


@pytest.mark.parametrize(
    ("ask", "api_id"), [(_만기, EXPIRY), (_매매동향, TREND)], ids=["만기일", "매매동향"]
)
@pytest.mark.parametrize(
    ("real", "paper", "active", "expected"),
    [
        (BOTH, BOTH, "paper", "real"),
        (BOTH, BOTH, "real", "real"),
        ((), BOTH, "paper", "paper"),
    ],
    ids=["모의활성_실전키있음", "실전활성", "실전키없음"],
)
def test_라우트는_고른_환경에서_받고_헤더는_활성_환경이다(
    앱에_붙이기, ask, api_id, real, paper, active, expected
):
    호출부 = _가짜호출부(_설정(real=real, paper=paper, default=active))
    응답 = ask(앱에_붙이기(호출부))
    assert 응답.status_code == 200
    assert 응답.json()["environment"] == expected
    assert 응답.headers["x-nh-environment"] == active
    assert 호출부.calls == [(api_id, expected)]


def _해외_품목표(앱):
    return 앱.post("/api/overseas/product-detail", json={})


def _해외_장운영(앱):
    return 앱.post("/api/overseas/market-operations")


def _국내_품목표(앱):
    return 앱.post("/api/domestic/product-detail")


@pytest.mark.parametrize(
    ("ask", "market"),
    [
        (_만기, "overseas"),
        (_매매동향, "domestic"),
        (_해외_품목표, "overseas"),
        (_해외_장운영, "overseas"),
        (_국내_품목표, "domestic"),
    ],
    ids=["만기일", "매매동향", "해외품목표", "해외장운영", "국내품목표"],
)
def test_라우트는_그_시장_인증_정보가_어디에도_없으면_부르지_않고_503_으로_무엇을_넣을지_말한다(
    앱에_붙이기, monkeypatch, ask, market
):
    """**기다려도 안 되는 자리입니다.** 서버 오류(500)가 아니라 설정을 채우면 풀리는
    자리라 503 과 함께 어느 파일의 어느 항목인지를 답합니다."""
    # 받아 둔 표가 없는 새 자리로 시작합니다 — 다른 시험이 받아 둔 표로 답하면 이 길을 못 봅니다.
    monkeypatch.setattr(overseas_product_service, "service", ProductService())
    monkeypatch.setattr(session_service, "service", session_service.SessionService())
    다른시장 = tuple(m for m in BOTH if m != market)
    호출부 = _가짜호출부(_설정(real=다른시장, paper=다른시장))

    응답 = ask(앱에_붙이기(호출부))

    assert 응답.status_code == 503
    문구 = 응답.json()["detail"]
    assert 문구 == str(MissingMarketKeys(market))
    assert str(CONFIG_PATH) in 문구
    assert f"> {market} 항목" in 문구
    assert "잠시 뒤" not in 문구
    assert 호출부.calls == []


@pytest.mark.parametrize(
    ("ask", "market", "api_id"),
    [(_국내_품목표, "domestic", "domestic_product-detail"), (_해외_장운영, "overseas", None)],
    ids=["국내품목표", "해외장운영"],
)
def test_인증_정보를_넣으면_시간표를_기다리지_않고_바로_받는다(
    앱에_붙이기, monkeypatch, ask, market, api_id
):
    """시간표는 받기 실패를 잠시 기억하지만, 인증 정보가 없던 것은 기억하지 않습니다 —
    「넣어 주세요」를 따라 넣었는데 같은 답이 몇 분 더 서면 안 됩니다."""
    monkeypatch.setattr(session_service, "service", session_service.SessionService())
    다른시장 = tuple(m for m in BOTH if m != market)
    없음 = _가짜호출부(_설정(real=다른시장, paper=다른시장))
    assert ask(앱에_붙이기(없음)).status_code == 503

    있음 = _가짜호출부(_설정(real=BOTH, paper=BOTH))
    ask(앱에_붙이기(있음))

    assert 있음.calls, "넣은 뒤 첫 요청에서 NH선물에 물어야 합니다."
    assert all(environment == "real" for _, environment in 있음.calls)
    if api_id is not None:
        assert 있음.calls[0][0] == api_id


def test_해외_종목_품목값은_인증_정보가_없으면_안_죽고_까닭을_낸다(앱에_붙이기, monkeypatch):
    """종목 하나의 품목 값은 답 모양을 하나로 지키고 `why` 로 말합니다(국내와 같은 결)."""
    monkeypatch.setattr(overseas_product_service, "service", ProductService())
    monkeypatch.setattr(master_service.service, "index", lambda: object())
    monkeypatch.setattr(
        master_service.service,
        "product_of",
        lambda market, sym: {"product_code": "MES", "kind": "futures"},
    )
    호출부 = _가짜호출부(_설정(real=("domestic",), paper=("domestic",)))

    응답 = 앱에_붙이기(호출부).post("/api/overseas/product-info", json={"sym": "MESU26"})

    assert 응답.status_code == 200
    made = 응답.json()
    assert made["whyCode"] == "no_keys"
    assert made["why"] == overseas_routes._NO_KEYS
    assert "잠시 뒤" not in made["why"]
    assert 호출부.calls == []


def test_시간표_기동_로딩은_인증_정보가_없어도_조용히_넘어간다(caplog):
    """앱은 그대로 뜹니다. 국내만 쓰는 사람에게는 늘 있는 일이라 경고 한 줄입니다."""
    service = session_service.SessionService()
    호출부 = _가짜호출부(_설정(real=("domestic",), paper=("domestic",)))

    with caplog.at_level("WARNING"):
        service.refresh_all(api=호출부)

    assert service.cached("overseas") is None
    assert service.cached("domestic") is not None
    해외 = [r for r in caplog.records if "overseas 시간표를 받지 않습니다" in r.getMessage()]
    assert len(해외) == 1 and 해외[0].exc_info is None


# ── 재생(반입해 둔 응답) ──────────────────────────────────────


def _모의로_바꾼_저장소(api_id):
    """그 API 의 기록을 전부 모의 환경 것으로 바꾼 저장소. 실전 기록이 없는 경우입니다."""
    기록 = [
        dataclasses.replace(f, environment="paper")
        for f in load_fixtures().http
        if f.api_id == api_id
    ]
    assert 기록 and all(f.environment == "paper" for f in 기록)
    return FixtureStore(기록, Path("메모리"))


@pytest.mark.parametrize(
    ("ask", "api_id"), [(_만기, EXPIRY), (_매매동향, TREND)], ids=["만기일", "매매동향"]
)
@pytest.mark.parametrize("paper_only", [False, True], ids=["실전기록", "모의기록만"])
def test_재생은_실전_기록을_먼저_없으면_모의_기록으로_답한다(앱에_붙이기, ask, api_id, paper_only):
    """재생 설정은 두 환경 모두 인증 정보가 차 있어 실전으로 묻습니다."""
    session = create_session(
        replay=True, fixtures=_모의로_바꾼_저장소(api_id) if paper_only else None
    )
    try:
        응답 = ask(앱에_붙이기(TradeClient(session)))
    finally:
        session.close()
    assert 응답.status_code == 200
    assert 응답.json()["environment"] == "real"
    # 같은 환경의 기록이면 요청이 통째로 같지 않아도 `api`(같은 API 의 다른 요청)입니다.
    같은환경 = (MATCH_EXACT, MATCH_API)
    if paper_only:
        assert 응답.headers[MATCH_HEADER] == MATCH_CROSS_ENVIRONMENT
    else:
        assert 응답.headers[MATCH_HEADER] in 같은환경
    # 재생 설정의 활성 환경입니다.
    assert 응답.headers["x-nh-environment"] == session.config.default_environment
