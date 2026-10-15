"""끝나지 않은 실행이 붙은 전략 버전은 서버가 지우지 않습니다.

전략 목록 화면이 삭제 단추를 잠그지만, API 를 바로 부르거나 화면이 실행 목록을
아직 못 받았을 때도 같은 규칙이어야 합니다. 종료(`ended`)가 아닌 실행이 하나라도
있으면 409 이고 버전은 그대로 남습니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 실행은 종이 실행으로만 세웁니다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import strategy_routes as routes
from backend.strategy.store import StrategyStore
from backend.strategy.strategy_routes import get_master, get_service, get_store
from tests.test_strategy_backtest import _버전
from tests.test_strategy_backtest import _마스터 as _백테스트마스터
from tests.test_strategy_service import _더하기, 실행목록  # noqa: F401 — 시험 고정값


@pytest.fixture
def 손님(tmp_path, 실행목록):
    저장소 = StrategyStore(tmp_path / "strategies.json")
    app.dependency_overrides.update(
        {
            get_service: lambda: 실행목록,
            get_store: lambda: 저장소,
            get_master: _백테스트마스터,
        }
    )
    try:
        앱 = TestClient(app, raise_server_exceptions=False)
        담음 = 앱.put("/api/strategy/versions/v1", json={"version": _버전()})
        assert 담음.status_code == 200, 담음.text
        yield 앱, 실행목록, 저장소
    finally:
        app.dependency_overrides.clear()


def _세움(앱: TestClient, run_id: str, version_id: str = "v1") -> None:
    답 = 앱.post("/api/strategy/runs", json=_더하기(id=run_id, versionId=version_id))
    assert 답.status_code == 200, 답.text


def _남은_버전(저장소: StrategyStore) -> list[str]:
    return [row["id"] for row in 저장소.read()["versions"]]


def _막힘(답, 개수: int) -> None:
    글 = f"끝나지 않은 실행 {개수}개가 있어 지울 수 없습니다 — 먼저 종료하세요"
    assert 답.status_code == 409, 답.text
    assert 답.json()["detail"] == {
        "message": 글,
        "problems": [{"field": "runs", "severity": "error", "message": 글}],
    }


def test_중지한_실행이_있으면_409_이고_버전은_남는다(손님):
    앱, _, 저장소 = 손님
    _세움(앱, "run1")
    assert 앱.post("/api/strategy/runs/run1/stop").status_code == 200
    assert [row["state"] for row in 앱.get("/api/strategy/runs").json()["runs"]] == ["paused"]

    _막힘(앱.delete("/api/strategy/versions/v1"), 1)
    assert _남은_버전(저장소) == ["v1"]


def test_돌고_있는_실행_둘이면_개수가_2_다(손님):
    앱, _, 저장소 = 손님
    _세움(앱, "run1")
    _세움(앱, "run2")
    상태 = [row["state"] for row in 앱.get("/api/strategy/runs").json()["runs"]]
    assert len(상태) == 2 and "ended" not in 상태 and "paused" not in 상태

    _막힘(앱.delete("/api/strategy/versions/v1"), 2)
    assert _남은_버전(저장소) == ["v1"]


def test_종료한_실행만_있으면_지운다(손님):
    앱, _, 저장소 = 손님
    _세움(앱, "run1")
    assert 앱.post("/api/strategy/runs/run1/end").status_code == 200
    assert [row["state"] for row in 앱.get("/api/strategy/runs").json()["runs"]] == ["ended"]

    답 = 앱.delete("/api/strategy/versions/v1")

    assert 답.status_code == 200, 답.text
    assert _남은_버전(저장소) == []


def test_실행이_없으면_지운다(손님):
    앱, _, 저장소 = 손님

    답 = 앱.delete("/api/strategy/versions/v1")

    assert 답.status_code == 200, 답.text
    assert _남은_버전(저장소) == []


def test_다른_버전의_실행은_세지_않는다(손님):
    앱, _, 저장소 = 손님
    _세움(앱, "run1", version_id="v9")

    답 = 앱.delete("/api/strategy/versions/v1")

    assert 답.status_code == 200, 답.text
    assert _남은_버전(저장소) == []


def test_없는_버전은_그_id_의_실행이_남아_있어도_404_다(손님):
    앱, _, 저장소 = 손님
    _세움(앱, "run1", version_id="v9")
    assert 앱.post("/api/strategy/runs/run1/stop").status_code == 200

    답 = 앱.delete("/api/strategy/versions/v9")

    assert 답.status_code == 404, 답.text
    assert 답.json()["detail"]["message"] == routes._NOT_FOUND
    assert _남은_버전(저장소) == ["v1"]


def test_실행_목록을_못_읽으면_500_이고_지우지_않는다(손님, monkeypatch):
    앱, 실행목록, 저장소 = 손님

    def _터짐():
        raise OSError("실행 파일을 읽지 못함")

    monkeypatch.setattr(실행목록, "engines", _터짐)

    답 = 앱.delete("/api/strategy/versions/v1")

    assert 답.status_code == 500, 답.text
    assert 답.json()["detail"]["message"] == routes._NOT_DELETED
    assert _남은_버전(저장소) == ["v1"]
