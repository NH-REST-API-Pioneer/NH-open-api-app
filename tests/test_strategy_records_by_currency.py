"""성과분석 「전체」의 통화별 답(`byCurrency`) — 한 번의 요청으로 통화마다의 성적.

**사용자 홈을 건드리지 않습니다.** 기록 줄은 손으로 짓고, 라우트는 임시 기록 파일과
가짜 저장소·가짜 실행 목록으로 봅니다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import journal as journal_lib, records, runs
from backend.strategy.strategy_routes import get_journal, get_service, get_store
from tests.test_strategy_records import _거래, _때, _조건
from tests.test_strategy_records_currency import _해외

기간 = {"record": "paper", "from": "2026-09-01", "to": "2026-09-30"}


class _세는기록(journal_lib.Journal):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.reads = 0

    def rows(self):
        self.reads += 1
        return super().rows()


class _세는저장소:
    def __init__(self) -> None:
        self.reads = 0

    def read(self):
        self.reads += 1
        return {"versions": []}


class _빈실행목록:
    def engines(self):
        return []


def _기록(tmp_path, 줄들) -> _세는기록:
    기록 = _세는기록(tmp_path / "trades.jsonl")
    for 줄 in 줄들:
        run = runs.Run(id=줄["runId"], version_id="v1", code=줄["code"], session=줄["session"],
                       market=줄["market"], currency=줄.get("currency", ""))
        기록.write("trade", run, {key: 줄[key] for key in ("openedAt", "closedAt", "side", "quantity", "grossPl", "fee", "netPl")})
    return 기록


@pytest.fixture
def 묻기(tmp_path):
    붙인것: dict = {}

    def 붙임(줄들):
        붙인것["기록"] = _기록(tmp_path, 줄들)
        붙인것["저장소"] = _세는저장소()
        app.dependency_overrides[get_journal] = lambda: 붙인것["기록"]
        app.dependency_overrides[get_store] = lambda: 붙인것["저장소"]
        app.dependency_overrides[get_service] = lambda: _빈실행목록()
        손님 = TestClient(app)

        def get(**params):
            답 = 손님.get("/api/strategy/records", params={**기간, **params})
            assert 답.status_code == 200, 답.text
            return 답.json()

        return get, 붙인것

    try:
        yield 붙임
    finally:
        for one in (get_journal, get_store, get_service):
            app.dependency_overrides.pop(one, None)


_세_통화 = [
    _해외(_때(10, 10), "USD", run="a", net=100.0),
    _해외(_때(11, 10), "HKD", run="b", net=800.0),
    _해외(_때(12, 10), "EUR", run="c", net=-30.0),
    _해외(_때(13, 10), None, run="d", net=50.0),  # 통화 칸 없는 옛 줄 — 달러
]


def test_통화별_답은_그_통화로_물었을_때의_답_전체와_같다(묻기):
    get, _ = 묻기(_세_통화)

    전체 = get(market="overseas")

    assert list(전체["byCurrency"]) == 전체["currencies"] == ["EUR", "HKD", "USD"]
    for 통화 in 전체["currencies"]:
        assert 전체["byCurrency"][통화] == get(market="overseas", currency=통화), 통화
    assert [one["net"] for one in 전체["byCurrency"]["USD"]["trades"]] == [100.0, 50.0]


def test_기존_칸은_그대로이고_통화를_섞은_합은_없다(묻기):
    get, _ = 묻기(_세_통화)

    전체 = get(market="overseas")
    달러 = get(market="overseas", currency="USD")

    assert {key: value for key, value in 전체.items() if key != "byCurrency"} == 달러, "통화를 안 물은 답은 달러 답 그대로입니다."
    assert all("byCurrency" not in one for one in 전체["byCurrency"].values())


def test_기록_파일과_저장소는_요청마다_한_번_읽는다(묻기):
    get, 붙인것 = 묻기(_세_통화)

    전체 = get(market="overseas")

    assert len(전체["byCurrency"]) == 3
    assert 붙인것["기록"].reads == 1 and 붙인것["저장소"].reads == 1


def test_통화가_하나여도_싣는다(묻기):
    get, _ = 묻기([_해외(_때(10, 10), "USD", run="a", net=100.0)])

    전체 = get(market="overseas")

    assert list(전체["byCurrency"]) == ["USD"]
    assert 전체["byCurrency"]["USD"] == get(market="overseas", currency="USD")


def test_해외_거래가_없으면_빈_묶음이다(묻기):
    get, _ = 묻기([_거래(_때(10, 10), run="a")])

    전체 = get(market="overseas")

    assert 전체["currencies"] == [] and 전체["byCurrency"] == {}


def test_국내와_통화를_물은_해외에는_칸이_없다(묻기):
    get, _ = 묻기([*_세_통화, _거래(_때(10, 10), run="k")])

    assert "byCurrency" not in get(market="domestic")
    assert "byCurrency" not in get(market="overseas", currency="HKD")


def test_통화마다_같은_셈을_한_번씩_부른다():
    불림: list = []

    def build(ask):
        불림.append(ask.currency)
        return {"currencies": ["HKD", "USD"], "currency": ask.money}

    made = records.with_by_currency(build, _조건(market="overseas"))

    assert 불림 == ["", "HKD", "USD"]
    assert made["byCurrency"] == {
        "HKD": {"currencies": ["HKD", "USD"], "currency": "HKD"},
        "USD": {"currencies": ["HKD", "USD"], "currency": "USD"},
    }
