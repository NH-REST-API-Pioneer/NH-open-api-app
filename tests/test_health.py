"""`/api/health` 가 어느 쪽으로 돌고 있는지, 어느 환경인지 알려주는지.

`TestClient(app)` 을 `with` 없이 씁니다. `with` 로 감싸면 서버 기동 절차가
돌면서 마스터를 실제로 내려받으러 나갑니다.

**접속 자리는 시험이 만든 세션으로 둡니다.** 활성 환경을 답하려면 접속 자리가
설정을 읽어야 하는데, 그대로 두면 시험을 돌린 사람의 설정 파일을 읽습니다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.nh_api import runtime
from backend.nh_api.session import LIVE, REPLAY, REPLAY_FLAG, create_session, current_mode

client = TestClient(app)


@pytest.fixture
def 재생_접속자리():
    session = create_session(replay=True)
    runtime.use(session)
    try:
        yield session
    finally:
        runtime.reset()


def test_재생_모드로_뜰_때는_마스터를_받지_않는다(monkeypatch, 재생_접속자리, tmp_path):
    """받아 둔 파일만 읽습니다 — 서버에 닿지 않는 곳에서 띄우는 방식입니다."""
    import asyncio

    from backend import main as 진입점
    from backend.master import master_service
    from backend.master.master_service import MasterService

    임시 = MasterService(tmp_path)
    부른것 = []
    monkeypatch.setattr(임시, "reload", lambda: 부른것.append("reload"))
    monkeypatch.setattr(임시, "refresh", lambda **_: 부른것.append("refresh"))
    monkeypatch.setattr(master_service, "service", 임시)

    asyncio.run(진입점._prepare_master())
    assert 부른것 == ["reload"]


def test_실서버_모드로_뜰_때는_마스터를_받는다(monkeypatch, tmp_path):
    import asyncio

    from backend import main as 진입점
    from backend.master import master_service
    from backend.master.master_service import MasterService
    from backend.nh_api.session import replay_config

    # 실서버 모드 접속 자리를 시험용 설정으로 만듭니다 — 아무 데도 붙지 않습니다.
    runtime.use(create_session(replay=False, config=replay_config()))
    임시 = MasterService(tmp_path)
    부른것 = []
    monkeypatch.setattr(임시, "reload", lambda: 부른것.append("reload"))
    monkeypatch.setattr(임시, "refresh", lambda **_: 부른것.append("refresh"))
    monkeypatch.setattr(master_service, "service", 임시)
    try:
        asyncio.run(진입점._prepare_master())
    finally:
        runtime.reset()
    assert 부른것 == ["reload", "refresh"]


def test_기본은_실서버(monkeypatch, 재생_접속자리):
    monkeypatch.delenv(REPLAY_FLAG, raising=False)
    응답 = client.get("/api/health")
    assert 응답.status_code == 200
    assert 응답.json() == {"status": "ok", "mode": LIVE, "active_environment": "paper"}


def test_재생_모드면_그렇게_알린다(monkeypatch, 재생_접속자리):
    monkeypatch.setenv(REPLAY_FLAG, "1")
    응답 = client.get("/api/health")
    assert 응답.json() == {"status": "ok", "mode": REPLAY, "active_environment": "paper"}
    # 응답이 어느 환경의 것인지는 헤더에도 실립니다.
    assert 응답.headers["x-nh-environment"] == "paper"


def test_설정을_못_읽으면_환경은_모름이다(monkeypatch, tmp_path):
    """실서버 모드에서 설정 파일이 없으면 접속 자리를 못 만듭니다. 실전으로
    가정하지 않고 `null` 로 답하고, 헤더도 안 붙입니다."""
    from backend import config

    monkeypatch.delenv(REPLAY_FLAG, raising=False)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "없음.yaml")
    runtime.reset()
    try:
        응답 = client.get("/api/health")
    finally:
        runtime.reset()

    assert 응답.status_code == 200
    assert 응답.json()["active_environment"] is None
    assert "x-nh-environment" not in 응답.headers


def test_켜는_값(monkeypatch):
    for 값 in ("1", "true", "TRUE", "yes", "on"):
        assert current_mode({REPLAY_FLAG: 값}) == REPLAY
    for 값 in ("", "0", "false", "no", "off"):
        assert current_mode({REPLAY_FLAG: 값}) == LIVE
    assert current_mode({}) == LIVE
