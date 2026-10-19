"""순손익을 모르는 거래만 있는 버전도 목록 성과를 셀 수 있어야 합니다.

승수를 몰라 돈으로 못 센 거래(순손익 칸이 빈 해외 종이 실행)만 있는 버전은 거래 수만
싣고 돈으로 센 칸은 모름(`None`)입니다. 승률을 셀 때 0 으로 나누면 목록 GET 자체가
500 이 됩니다. 한 버전의 셈이 실패해도 다른 버전의 성과와 목록은 그대로 나옵니다.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import records
from backend.strategy import strategy_routes as routes
from backend.strategy.store import StrategyStore
from backend.strategy.strategy_routes import get_master, get_store
from tests.test_strategy_backtest import _마스터, _버전
from tests.test_strategy_records import _거래, _때, _조건

오늘 = date(2026, 9, 30)


def _판(version_id: str) -> dict:
    return {**_버전(), "id": version_id, "groupId": f"g-{version_id}", "record": "앱 시뮬레이션"}


def _모름_거래(version: str) -> dict:
    줄 = _거래(_때(17, 10), version=version, run=f"r-{version}")
    줄["netPl"] = None
    줄["grossPl"] = None
    return 줄


def test_순손익을_모르는_거래만_있으면_거래_수만_싣고_돈_칸은_모름이다():
    성과 = records._perf([_모름_거래("v1"), _모름_거래("v1") | {"closedAt": _때(18, 10)}], _판("v1"))

    assert 성과 == {"pl": None, "winRate": None, "trades": 2, "maxDrawdown": None}


def test_한_버전이_모름이어도_다른_버전_성과는_그대로다():
    줄들 = [_모름_거래("v1"), _거래(_때(17, 11), version="v2", run="r-v2", net=50.0)]

    성과 = records.performances(줄들, [_판("v1"), _판("v2")], today=오늘)

    assert (성과["v1"]["trades"], 성과["v1"]["pl"]) == (1, None)
    assert (성과["v2"]["trades"], 성과["v2"]["pl"], 성과["v2"]["winRate"]) == (1, 50.0, 100.0)


def test_한_버전의_셈이_터져도_그_칸만_비고_나머지는_나오며_기록에_남는다(monkeypatch, caplog):
    원래 = records._perf

    def 골라터짐(rows, version):
        if version.get("id") == "v1" and rows:
            raise ZeroDivisionError("셈 실패")
        return 원래(rows, version)

    monkeypatch.setattr(records, "_perf", 골라터짐)
    줄들 = [_거래(_때(17, 10), version="v1"), _거래(_때(17, 11), version="v2", run="r-v2", net=50.0)]

    성과 = records.performances(줄들, [_판("v1"), _판("v2")], today=오늘)

    assert 성과["v1"]["performance"]["paper"] is None
    assert {이름: 성과["v1"][이름] for 이름 in records.NO_PERF} == records.NO_PERF
    assert 성과["v2"]["performance"]["paper"]["pl"] == 50.0
    줄 = [one for one in caplog.records if "v1" in one.getMessage()]
    assert len(줄) == 1 and 줄[0].levelname == "WARNING" and 줄[0].exc_info


def test_성과분석_답도_순손익_모름_거래가_있어도_돈다():
    줄들 = [_모름_거래("v1"), _거래(_때(17, 11), version="v1", run="r-v1b", net=-20.0)]

    답 = records.dataset(줄들, _조건(), versions=[_판("v1")])

    (전략,) = 답["strategies"]
    assert [one["net"] for one in 답["trades"]] == [None, -20.0]
    assert 답["maxDrawdown"] == 20.0 and 전략["maxDrawdown"] == 20.0
    assert records.dataset([_모름_거래("v1")], _조건(), versions=[_판("v1")])["maxDrawdown"] is None


@pytest.fixture
def 목록손님(tmp_path, monkeypatch):
    저장소 = StrategyStore(tmp_path / "strategies.json")
    for 판 in (_판("v1"), _판("v2")):
        저장소.save(판, None)
    줄들 = [_모름_거래("v1"), _거래(_때(17, 11), version="v2", run="r-v2", net=50.0)]
    monkeypatch.setattr(routes, "_trade_rows", lambda journal: 줄들)
    monkeypatch.setattr(records, "now_kst", lambda: datetime(2026, 9, 30, 12))
    app.dependency_overrides.update({get_store: lambda: 저장소, get_master: _마스터})
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_목록은_모름_버전이_섞여도_200_이고_다른_버전_성과가_있다(목록손님):
    답 = 목록손님.get("/api/strategy/versions")

    assert 답.status_code == 200, 답.text
    줄 = {one["id"]: one for one in 답.json()["versions"]}
    assert (줄["v1"]["trades"], 줄["v1"]["pl"]) == (1, None)
    assert 줄["v2"]["pl"] == 50.0


def test_성과_셈이_통째로_터져도_목록은_나온다(목록손님, monkeypatch):
    def 터짐(rows, versions, **kwargs):
        raise RuntimeError("셈 실패")

    monkeypatch.setattr(records, "performances", 터짐)

    답 = 목록손님.get("/api/strategy/versions")

    assert 답.status_code == 200
    assert {one["id"] for one in 답.json()["versions"]} == {"v1", "v2"}
    assert all("pl" not in one or one["pl"] is None for one in 답.json()["versions"])
