"""성과분석의 해외 통화 거름 — 통화가 다른 손익을 한 합에 더하지 않습니다.

**사용자 홈을 건드리지 않습니다.** 기록 줄은 손으로 짓고, 라우트는 임시 기록 파일로 봅니다.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import journal as journal_lib, records, runs
from backend.strategy.strategy_routes import get_journal
from tests.test_strategy_records import _거래, _때, _조건


def _해외(closed, currency=None, **덮어쓰기):
    줄 = _거래(closed, market="overseas", session="overseas", **덮어쓰기)
    if currency is not None:
        줄["currency"] = currency
    return 줄


def test_통화를_물으면_그_통화_줄만_세고_답의_통화도_그것이다():
    줄들 = [
        _해외(_때(10, 10), "USD", run="a", net=100.0),
        _해외(_때(11, 10), "HKD", run="b", net=800.0),
        _해외(_때(12, 10), None, run="c", net=50.0),  # 옛 줄 — 달러로 읽습니다
    ]

    홍콩 = records.dataset(줄들, _조건(market="overseas", currency="HKD"))
    달러 = records.dataset(줄들, _조건(market="overseas", currency="USD"))

    assert [one["net"] for one in 홍콩["trades"]] == [800.0] and 홍콩["currency"] == "HKD"
    assert [one["net"] for one in 달러["trades"]] == [100.0, 50.0] and 달러["currency"] == "USD"


def test_안_물으면_달러_줄만_세고_통화_목록은_거름과_상관없다():
    줄들 = [_해외(_때(10, 10), "USD", run="a", net=100.0), _해외(_때(11, 10), "HKD", run="b", net=800.0)]

    전체 = records.dataset(줄들, _조건(market="overseas"))
    홍콩 = records.dataset(줄들, _조건(market="overseas", currency="HKD"))

    assert 전체["currency"] == "USD"
    assert [one["net"] for one in 전체["trades"]] == [100.0], "홍콩달러 손익을 달러 합에 섞지 않습니다."
    assert 전체["currencies"] == 홍콩["currencies"] == ["HKD", "USD"]


def test_통화_목록은_기간_시장_기록_갈래로만_고른다():
    줄들 = [
        _해외(_때(10, 10), "USD", run="a"),
        _해외(_때(10, 10, month=8), "EUR", run="b"),  # 기간 밖
        _해외(_때(11, 10), "HKD", run="c", record="sim"),  # 다른 기록 갈래
        _거래(_때(12, 10), run="d"),  # 국내
    ]

    assert records.dataset(줄들, _조건(market="overseas"))["currencies"] == ["USD"]
    assert records.dataset(줄들, _조건())["currencies"] == ["KRW"]


def test_통화_조건은_해외의_세_글자만_받는다():
    with pytest.raises(records.RecordsError):
        records.query_of(record="paper", market="domestic", start=None, end=None, currency="KRW")
    with pytest.raises(records.RecordsError):
        records.query_of(record="paper", market="overseas", start=None, end=None, currency="달러")
    물음 = records.query_of(record="paper", market="overseas", start=None, end=None, currency="hkd",
                          today=date(2026, 9, 30))
    assert 물음.currency == "HKD"


def test_도는_실행의_평가손익도_그_통화만_더한다():
    class 장부:
        def __init__(self, value):
            self.value = value

        def unrealized(self, last):
            return self.value

    def 엔진(currency, value):
        run = runs.Run(id=currency, version_id="v", code="X", session="overseas", market="overseas",
                       mode="paper", currency=currency)
        return type("E", (), {"run": run, "ledger": 장부(value), "book": type("B", (), {"last_price": 1.0})()})()

    물음 = _조건(market="overseas", currency="HKD", end=date(2026, 9, 30))
    assert records.open_pl_of([엔진("USD", 10.0), 엔진("HKD", 7.0)], 물음, today=date(2026, 9, 30)) == 7.0


def test_라우트가_통화를_받고_틀리면_400_이다(tmp_path):
    기록 = journal_lib.Journal(tmp_path / "trades.jsonl")
    for 줄 in (_해외(_때(10, 10), "USD", run="a"), _해외(_때(11, 10), "HKD", run="b")):
        run = runs.Run(id=줄["runId"], version_id="v1", code=줄["code"], session="overseas",
                       market="overseas", currency=줄["currency"])
        기록.write("trade", run, {key: 줄[key] for key in ("openedAt", "closedAt", "side", "quantity", "grossPl", "fee", "netPl")})
    app.dependency_overrides[get_journal] = lambda: 기록
    try:
        손님 = TestClient(app)
        답 = 손님.get("/api/strategy/records", params={
            "record": "paper", "market": "overseas", "from": "2026-09-01", "to": "2026-09-30", "currency": "HKD"})
        틀림 = 손님.get("/api/strategy/records", params={"record": "paper", "market": "domestic", "currency": "USD"})
    finally:
        app.dependency_overrides.pop(get_journal, None)

    assert 답.status_code == 200, 답.text
    assert 답.json()["currency"] == "HKD" and len(답.json()["trades"]) == 1
    assert 답.json()["currencies"] == ["HKD", "USD"]
    assert 틀림.status_code == 400
    assert 틀림.json()["detail"] == {"message": records.WHY_CURRENCY, "problems": []}
