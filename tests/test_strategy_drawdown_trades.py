"""최대 낙폭은 거래(청산 시각) 차례로 셉니다.

닫힌 거래의 순손익(실현 − 수수료)을 청산 시각 차례로 더한 곡선에서, 앞선 가장 높은
값(시작 0)에서 가장 많이 내려간 크기입니다. 하루 단위로 묶으면 같은 날 벌었다 잃은
것이 지워져 낙폭이 0 으로 보였습니다. 목록의 최근 30일 성과와 성과분석 답(전략별·
합계)이 같은 셈입니다.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.strategy import records
from tests.test_strategy_records import _거래, _때, _조건

판 = {
    "id": "v1",
    "groupId": "g1",
    "name": "추세",
    "version": "v1",
    "market": "domestic",
    "record": "앱 시뮬레이션",
}


def _하루_뒤섞인() -> list[dict]:
    """10/1 에 +2, 10/7 에 0·+3.75·+11.25·+1.25·−5 — 하루로 묶으면 낙폭 0, 거래 순이면 5."""
    줄들 = [_거래(_때(1, 10, month=10), net=2.0)]
    for 분, 값 in enumerate((0.0, 3.75, 11.25, 1.25, -5.0)):
        줄들.append(_거래(_때(7, 10, 분, month=10), net=값))
    return 줄들


def _시월() -> records.Query:
    return _조건(start=date(2026, 10, 1), end=date(2026, 10, 31))


def test_같은_날_벌었다_잃은_것도_낙폭이다():
    assert records.trade_drawdown(_하루_뒤섞인()) == pytest.approx(5.0)


def test_하루_단위로는_0_이던_자료가_목록과_답_모두_5_다():
    줄들 = _하루_뒤섞인()

    목록 = records.performances(줄들, [판], today=date(2026, 10, 7))["v1"]
    답 = records.dataset(줄들, _시월(), versions=[판])

    assert 목록["maxDrawdown"] == pytest.approx(5.0)
    (전략,) = 답["strategies"]
    assert 전략["maxDrawdown"] == pytest.approx(5.0)
    assert 답["maxDrawdown"] == pytest.approx(5.0)
    assert 답["drawdownBasis"] == records.DRAWDOWN_BASIS == "trades-realized"


def test_잃은_거래가_없으면_0_이다():
    줄들 = [_거래(_때(1 + 날, 10, month=10), net=값) for 날, 값 in enumerate((1.0, 0.0, 2.5))]

    assert records.trade_drawdown(줄들) == 0.0


def test_첫_거래부터_잃으면_그_크기다():
    """기록 전(0)을 첫 고점으로 봅니다."""
    줄들 = [_거래(_때(1, 10, month=10), net=-3.0), _거래(_때(1, 11, month=10), net=1.0)]

    assert records.trade_drawdown(줄들) == pytest.approx(3.0)


def test_같은_청산_시각은_들어온_차례와_상관없이_같은_답이다():
    """차례가 답을 바꾸는 자료입니다 — a(−5)·b(+5) 면 5, b·a 면 6."""
    같은때 = _때(2, 10, month=10)
    셋 = [
        _거래(같은때, net=-5.0, run="a"),
        _거래(같은때, net=5.0, run="b"),
        _거래(_때(2, 11, month=10), net=-1.0, run="c"),
    ]

    assert records.trade_drawdown(셋) == records.trade_drawdown(list(reversed(셋)))
    assert records.trade_drawdown(셋) == pytest.approx(5.0), "열쇠 차례(a 먼저)로 고정합니다."


def test_순손익을_모르는_거래는_빼고_거래가_없으면_없음이다():
    모름 = _거래(_때(1, 10, month=10), net=-9.0)
    모름["netPl"] = None

    assert records.trade_drawdown([모름]) is None
    assert records.trade_drawdown([모름, _거래(_때(1, 11, month=10), net=-2.0)]) == pytest.approx(2.0)
    빈답 = records.dataset([], _시월(), versions=[판])
    assert 빈답["maxDrawdown"] is None and 빈답["drawdownBasis"] == records.DRAWDOWN_BASIS


def test_전략마다_제_거래로만_센다():
    줄들 = _하루_뒤섞인() + [_거래(_때(3, 10, month=10), net=-7.0, version="v2", run="r2")]
    둘째 = {**판, "id": "v2", "groupId": "g2", "name": "역추세"}

    답 = records.dataset(줄들, _시월(), versions=[판, 둘째])

    낙폭 = {one["id"]: one["maxDrawdown"] for one in 답["strategies"]}
    assert 낙폭 == {"v1": pytest.approx(5.0), "v2": pytest.approx(7.0)}
