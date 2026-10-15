"""값을 비워 둔 거리 칸은 단위가 ATR 이어도 ATR 을 기다리지 않습니다.

익절·추적 청산은 비워 두면 그 청산을 쓰지 않습니다. 단위 칸에 ATR 이 남아 있어도
쓰지 않는 청산이므로 ATR(14) 를 세지 않고, 그 준비 봉만큼 진입을 늦추지도 않습니다.
값을 적은 ATR 칸이 하나라도 있으면 전처럼 ATR 이 설 때까지 진입을 막습니다.
**계좌에 닿지 않습니다** — 봉을 손으로 지어 넣습니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, rules, runs
from backend.strategy.indicators import Bar
from tests.test_strategy_backtest import _봉, _셈, _진입봉
from tests.test_strategy_engine import _때, _설정, _엔진

_ATR = rules.operand_key(*engine.ATR_FOR_UNIT)


def _ATR_을_센다(엔진: engine.RunEngine) -> bool:
    return any(rules.operand_key(*one) == _ATR for one in 엔진._wanted)


def _봉_하나() -> Bar:
    return Bar(_때(10, 0), 1, 1, 1, 1, 1)


# ── 실행 엔진 ─────────────────────────────────────────────


@pytest.mark.parametrize("값", ["", None, "   "])
@pytest.mark.parametrize(("value_key", "unit_key"), [("takeTicks", "takeUnit"), ("trailTicks", "trailUnit")])
def test_값이_빈_ATR_칸은_ATR_을_기다리지_않는다(값, value_key, unit_key):
    기준 = _엔진(_설정(**{value_key: ""}))
    엔진 = _엔진(_설정(**{value_key: 값, unit_key: "atr"}))

    assert 엔진._uses_atr is False
    assert not _ATR_을_센다(엔진), "쓰지 않는 청산의 ATR 은 세지 않습니다."
    assert 엔진.warmup == 기준.warmup, "ATR(14) 의 준비 봉을 더하지 않습니다."
    assert 엔진._entry_gate(_봉_하나()) is None


def test_값이_빠진_ATR_칸도_ATR_을_기다리지_않는다():
    """칸 자체가 없는 전략 — 빈 글자와 같은 뜻입니다."""
    설정 = _설정(takeUnit="atr")
    del 설정["aux"]["takeTicks"]

    엔진 = _엔진(설정)

    assert 엔진._uses_atr is False
    assert not _ATR_을_센다(엔진)


@pytest.mark.parametrize(
    "aux",
    [
        {"stopTicks": "1", "stopUnit": "atr"},
        {"stopTicks": "1", "stopUnit": "atr", "takeTicks": "", "takeUnit": "atr"},
        {"takeTicks": "2", "takeUnit": "atr"},
    ],
)
def test_값이_있는_ATR_칸이_있으면_ATR_을_기다린다(aux):
    엔진 = _엔진(_설정(**aux))

    assert 엔진._uses_atr is True
    assert _ATR_을_센다(엔진)
    assert 엔진.warmup >= rules.warmup_of(*engine.ATR_FOR_UNIT)
    assert 엔진._entry_gate(_봉_하나()) == runs.WHY_ATR_NOT_READY
    엔진._atr = 1.0
    assert 엔진._entry_gate(_봉_하나()) is None


def test_빈_ATR_익절과_틱_손절이면_손절_거리는_틱이다():
    엔진 = _엔진(_설정(stopTicks="2", takeTicks="", takeUnit="atr"))

    assert 엔진._uses_atr is False
    assert 엔진._distance("stopTicks", "stopUnit", 100.0) == pytest.approx(0.1), "2틱 × 0.05."
    assert 엔진._distance("takeTicks", "takeUnit", 100.0) is None, "익절은 쓰지 않습니다."


# ── 지난 봉으로 돌려 보기 ──────────────────────────────────


def test_돌려_보기는_빈_ATR_익절이면_첫_신호에_진입한다():
    # 준비 봉 셋 뒤 09:02 봉이 첫 신호입니다. ATR(14) 를 기다리면 진입하지 못합니다.
    봉들 = _진입봉(_봉(9, 3, 101.0, 101.1, 101.0, 101.05))

    답 = _셈(봉들, _설정(takeTicks="", takeUnit="atr"))

    assert 답["signals"] == 1
    assert 답["fills"] >= 1, "첫 신호의 진입이 09:03 봉 시가에 체결됩니다."


def test_돌려_보기는_값이_있는_ATR_손절이면_ATR_전에는_진입하지_않는다():
    """위 시험의 맞짝 — 같은 봉에 값을 적은 ATR 손절이면 ATR 이 서기 전이라 막힙니다."""
    봉들 = _진입봉(_봉(9, 3, 101.0, 101.1, 101.0, 101.05))

    답 = _셈(봉들, _설정(stopTicks="1", stopUnit="atr"))

    assert 답["fills"] == 0
    assert 답["trades"] == []


def test_돌려_보기는_빈_ATR_익절과_틱_손절이면_틱_손절로_닫는다():
    # 진입 101.05(시가 101 + 1틱). 손절 2틱 = 100.95, 1틱 불리하게 100.90 에 닫힙니다.
    봉들 = _진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2))

    답 = _셈(봉들, _설정(stopTicks="2", takeTicks="", takeUnit="atr"))

    (거래,) = 답["trades"]
    assert 거래["entryPrice"] == pytest.approx(101.05)
    assert 거래["reason"] == engine.STOP_LOSS
    assert 거래["exitPrice"] == pytest.approx(100.90)
