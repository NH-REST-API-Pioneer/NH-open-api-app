"""성과분석 답의 전략 묶음 낙폭(`groups`).

묶음의 낙폭은 그 묶음에 속한 버전들의 거래를 **합쳐** 청산 시각 차례로 셉니다
(`records.group_drawdowns`). 버전 낙폭을 더하거나 그중 큰 값을 고르는 셈이 아닙니다.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.strategy import records
from tests.test_strategy_records import _거래, _때, _조건
from tests.test_strategy_records_currency import _해외


def _판(version_id: str, group: str) -> dict:
    return {
        "id": version_id,
        "groupId": group,
        "name": "추세",
        "version": version_id,
        "market": "domestic",
        "record": "앱 시뮬레이션",
    }


판들 = [_판("v1", "g1"), _판("v2", "g1"), _판("v3", "g2")]


def _시월(**덮어쓰기) -> records.Query:
    return _조건(start=date(2026, 10, 1), end=date(2026, 10, 31), **덮어쓰기)


def _줄들() -> list[dict]:
    """g1 = v1(−3, −3: 낙폭 6) + v2(사이에 +3: 낙폭 0) → 합친 곡선 −3·0·−3 이라 3.

    버전 낙폭의 합(6)·최대(6)와 다른 값이 나오는 자료입니다. g2 는 v3 하나(−10).
    """
    return [
        _거래(_때(1, 10, month=10), net=-3.0, version="v1", strategy="g1", run="a"),
        _거래(_때(2, 10, month=10), net=3.0, version="v2", strategy="g1", run="b"),
        _거래(_때(2, 11, month=10), net=-10.0, version="v3", strategy="g2", run="c"),
        _거래(_때(3, 10, month=10), net=-3.0, version="v1", strategy="g1", run="a"),
    ]


def _묶음(답: dict) -> dict:
    return {one["groupId"]: one["maxDrawdown"] for one in 답["groups"]}


def test_묶음_낙폭은_버전들의_거래를_합친_곡선의_낙폭이다():
    답 = records.dataset(_줄들(), _시월(), versions=판들)

    버전 = {one["id"]: one["maxDrawdown"] for one in 답["strategies"]}
    assert 버전 == {"v1": pytest.approx(6.0), "v2": 0.0, "v3": pytest.approx(10.0)}
    assert _묶음(답)["g1"] == pytest.approx(3.0)
    assert _묶음(답)["g1"] not in (버전["v1"] + 버전["v2"], max(버전["v1"], 버전["v2"]))
    assert 답["drawdownBasis"] == records.DRAWDOWN_BASIS


def test_버전이_하나뿐인_묶음은_그_버전의_낙폭이다():
    답 = records.dataset(_줄들(), _시월(), versions=판들)

    (v3,) = [one for one in 답["strategies"] if one["id"] == "v3"]
    assert _묶음(답)["g2"] == v3["maxDrawdown"] == pytest.approx(10.0)


def test_묶음은_전략_줄에_처음_나온_차례로_한_번씩_싣는다():
    답 = records.dataset(_줄들(), _시월(), versions=판들)

    assert [one["groupId"] for one in 답["groups"]] == ["g1", "g2"]
    assert all(set(one) == {"groupId", "maxDrawdown"} for one in 답["groups"])


def test_순손익을_모르는_거래만_있는_묶음은_없음이다():
    줄들 = _줄들()
    for 줄 in 줄들:
        if 줄["versionId"] == "v3":
            줄["netPl"] = None
            줄["grossPl"] = None

    답 = records.dataset(줄들, _시월(), versions=판들)

    assert _묶음(답)["g2"] is None
    assert _묶음(답)["g1"] == pytest.approx(3.0)


def test_전략이_없으면_빈_목록이다():
    답 = records.dataset([], _시월(), versions=판들)

    assert 답["strategies"] == [] and 답["groups"] == []


def test_묶음을_모르는_버전은_어느_묶음에도_들지_않는다():
    줄 = _거래(_때(1, 10, month=10), net=-4.0, version="v9", strategy=None, run="z")

    답 = records.dataset([줄], _시월(), versions=[])

    assert [one["groupId"] for one in 답["strategies"]] == [None]
    assert 답["groups"] == []


def test_통화마다의_답에도_그_통화_거래로만_센_묶음_낙폭이_있다():
    """통화를 더하지 않습니다 — 같은 묶음이라도 통화마다 따로 셉니다."""
    해외판 = [{**_판("v1", "g1"), "market": "overseas"}, {**_판("v2", "g1"), "market": "overseas"}]
    줄들 = [
        _해외(_때(1, 10, month=10), "USD", net=-4.0, version="v1", strategy="g1", run="a"),
        _해외(_때(2, 10, month=10), "HKD", net=-7.0, version="v2", strategy="g1", run="b"),
    ]
    물음 = _시월(market="overseas")

    답 = records.with_by_currency(lambda one: records.dataset(줄들, one, versions=해외판), 물음)

    assert _묶음(답) == {"g1": pytest.approx(4.0)}, "통화를 안 물은 답은 달러 줄만 셉니다."
    assert set(답["byCurrency"]) == {"USD", "HKD"}
    assert _묶음(답["byCurrency"]["USD"]) == {"g1": pytest.approx(4.0)}
    assert _묶음(답["byCurrency"]["HKD"]) == {"g1": pytest.approx(7.0)}
