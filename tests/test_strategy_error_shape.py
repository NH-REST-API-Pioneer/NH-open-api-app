"""/api/strategy 의 오류 답은 한 모양입니다 — `{"detail": {"message": 글, "problems": [...]}}`.

짚을 칸이 없으면 `problems` 는 빈 목록입니다. 우리 쪽에서 일이 안 된 500 도 같은
모양에 한국어 한 문장이고, 예외 원문은 답에 싣지 않고 기록에만 남깁니다. 요청 모양
자체가 틀린 FastAPI 의 422(목록)는 그대로입니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.**
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import backtest, journal as journal_lib, limits, records
from backend.strategy import service as service_lib
from backend.strategy import strategy_routes as routes
from backend.strategy.store import StrategyStore
from backend.strategy.strategy_routes import (
    get_journal,
    get_limits,
    get_master,
    get_service,
    get_store,
)
from tests.test_strategy_backtest import _몸, _버전
from tests.test_strategy_backtest import _마스터 as _백테스트마스터
from tests.test_strategy_service import _더하기, 실행목록  # noqa: F401 — 시험 고정값

비밀 = "비밀-원문-예외글"


@pytest.fixture
def 손님(tmp_path, 실행목록):
    저장소 = StrategyStore(tmp_path / "strategies.json")
    한도 = limits.LimitStore(tmp_path / "strategy-limits.json")
    기록 = journal_lib.Journal(tmp_path / "trades.jsonl")
    app.dependency_overrides.update(
        {
            get_service: lambda: 실행목록,
            get_store: lambda: 저장소,
            get_limits: lambda: 한도,
            get_journal: lambda: 기록,
            get_master: _백테스트마스터,
        }
    )
    try:
        yield TestClient(app, raise_server_exceptions=False), 실행목록, 저장소, 한도, 기록
    finally:
        app.dependency_overrides.clear()


def _모양(답, 상태: int, 글: str | None = None) -> dict:
    assert 답.status_code == 상태, 답.text
    속 = 답.json()["detail"]
    assert isinstance(속, dict) and set(속) == {"message", "problems"}
    assert isinstance(속["message"], str) and 속["message"]
    assert isinstance(속["problems"], list)
    if 글 is not None:
        assert 속["message"] == 글
    assert 비밀 not in 답.text, "예외 원문은 답에 싣지 않습니다."
    return 속


def _터짐(*args, **kwargs):
    raise OSError(비밀)


def _크게터짐(*args, **kwargs):
    raise RuntimeError(비밀)


# ── 404 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("방법", "주소"),
    [
        ("get", "/api/strategy/runs/없음"),
        ("post", "/api/strategy/runs/없음/stop"),
        ("post", "/api/strategy/runs/없음/resume"),
        ("post", "/api/strategy/runs/없음/close"),
        ("post", "/api/strategy/runs/없음/end"),
        ("post", "/api/strategy/runs/없음/acknowledge"),
        ("delete", "/api/strategy/runs/없음"),
    ],
)
def test_없는_실행은_404_한_모양이다(손님, 방법, 주소):
    앱 = 손님[0]

    _모양(getattr(앱, 방법)(주소), 404, service_lib.WHY_NOT_FOUND)


def test_없는_전략을_지우면_404_한_모양이다(손님):
    _모양(손님[0].delete("/api/strategy/versions/없음"), 404, routes._NOT_FOUND)


# ── 400 ─────────────────────────────────────────────────


def test_주소와_본문의_전략이_다르면_400_이고_id_칸을_짚는다(손님):
    답 = 손님[0].put(
        "/api/strategy/versions/v1", json={"version": {"id": "v2", "market": "domestic"}}
    )

    속 = _모양(답, 400, routes._ID_MISMATCH)
    assert [one["field"] for one in 속["problems"]] == ["id"]


def test_실행_동작의_거절은_400_한_모양이다(손님):
    앱 = 손님[0]
    앱.post("/api/strategy/runs", json=_더하기())

    _모양(앱.post("/api/strategy/runs/run1/close"), 400, service_lib.WHY_NOTHING)
    _모양(앱.delete("/api/strategy/runs/run1"), 400, service_lib.WHY_NOT_ENDED)


def test_시작을_막을_칸이_있으면_400_에_problems_다(손님):
    몸 = _더하기()
    몸["cash"] = 0

    속 = _모양(손님[0].post("/api/strategy/runs", json=몸), 400, service_lib.NOT_STARTED)
    assert [one["field"] for one in 속["problems"]] == ["cash"]


def test_전체_중지의_모르는_갈래는_400_이고_modes_칸을_짚는다(손님):
    속 = _모양(손님[0].post("/api/strategy/stop-all", json={"modes": ["종이"]}), 400)

    assert [one["field"] for one in 속["problems"]] == ["modes"]


def test_기록_조회_조건이_틀리면_400_한_모양이다(손님):
    _모양(손님[0].get("/api/strategy/records?record=paper"), 400, records.WHY_MARKET)


def test_한도를_담을_수_없으면_400_에_problems_다(손님):
    속 = _모양(손님[0].put("/api/strategy/limits", json={"KRW": {"dailyLoss": -1}}), 400)

    assert 속["problems"]


# ── 백테스트 409·504·502 ─────────────────────────────────


def test_백테스트가_돌고_있으면_409_한_모양이다(손님):
    assert backtest._busy.acquire(blocking=False)
    try:
        _모양(손님[0].post("/api/strategy/backtest", json=_몸()), 409, backtest.BUSY)
    finally:
        backtest._busy.release()


def test_백테스트가_시간을_넘기면_504_한_모양이다(손님, monkeypatch):
    def 넘침(work):
        raise backtest.BacktestError(backtest.WHY_TIME.format(seconds=3), status=504)

    monkeypatch.setattr(backtest, "run_one", 넘침)

    _모양(손님[0].post("/api/strategy/backtest", json=_몸()), 504)


def test_백테스트_봉을_못_받으면_502_이고_원문은_안_싣는다(손님, monkeypatch, caplog):
    실행목록 = 손님[1]
    monkeypatch.setattr(실행목록, "_fetch", _크게터짐)
    monkeypatch.setattr(실행목록, "engines", lambda: [])

    _모양(손님[0].post("/api/strategy/backtest", json=_몸()), 502, backtest.WHY_BARS)
    assert 비밀 in caplog.text, "원문은 기록에 남깁니다."


# ── 500 — 우리 쪽에서 일이 안 됨 ─────────────────────────


def test_전략을_담다_파일이_안_되면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[2], "save", _터짐)

    _모양(
        손님[0].put("/api/strategy/versions/v1", json={"version": _버전()}),
        500,
        routes._NOT_SAVED,
    )


def test_전략을_지우다_파일이_안_되면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[2], "delete", _터짐)

    _모양(손님[0].delete("/api/strategy/versions/v1"), 500, routes._NOT_DELETED)


def test_한도를_담다_파일이_안_되면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[3], "save", _터짐)

    _모양(
        손님[0].put("/api/strategy/limits", json={"KRW": {"dailyLoss": 1000}}),
        500,
        routes._LIMITS_NOT_SAVED,
    )


def test_실행을_세우다_파일이_안_되면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[1], "_save", _터짐)

    _모양(손님[0].post("/api/strategy/runs", json=_더하기()), 500, routes._RUN_NOT_SAVED)


def test_실행_동작에서_파일이_안_되면_500_한_모양이다(손님, monkeypatch):
    앱, 실행목록 = 손님[0], 손님[1]
    앱.post("/api/strategy/runs", json=_더하기())
    monkeypatch.setattr(실행목록, "_save", _터짐)

    _모양(앱.post("/api/strategy/runs/run1/stop"), 500, routes._RUN_NOT_SAVED)


def test_계좌와_맞춰_보다_터지면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[1], "audit_all", _크게터짐)

    _모양(손님[0].post("/api/strategy/reconcile"), 500, routes._NOT_RECONCILED)


def test_전체_중지가_터지면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[1], "stop_all", _크게터짐)

    _모양(손님[0].post("/api/strategy/stop-all"), 500, routes._NOT_STOPPED)


def test_기록_파일을_못_읽으면_500_한_모양이다(손님, monkeypatch):
    monkeypatch.setattr(손님[4], "rows", _크게터짐)

    _모양(
        손님[0].get("/api/strategy/records?record=paper&market=domestic"),
        500,
        routes._RECORDS_UNREAD,
    )


# ── FastAPI 자체 422 는 그대로 ───────────────────────────


def test_요청_모양이_틀린_422_는_목록_그대로다(손님):
    답 = 손님[0].post("/api/strategy/runs", json={"id": "run1"})

    assert 답.status_code == 422 and isinstance(답.json()["detail"], list)
