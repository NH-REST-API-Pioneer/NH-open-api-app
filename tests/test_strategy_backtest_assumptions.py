"""백테스트의 가정 — 일봉 + 신규 진입 시간, 증거금 예산 검사, 세션 끝 정리.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 봉은 손으로 만든 것입니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import backtest, runs, service as service_lib
from backend.strategy.indicators import Bar
from tests.test_strategy_backtest import _봉, _셈, _진입봉
from tests.test_strategy_daily_orders import _일봉
from tests.test_strategy_engine import _때, _설정


def _매도설정() -> dict:
    """매도 진입 규칙만 켠 설정. 09:02 봉이 101 로 닫혀 걸립니다."""
    설정 = _설정()
    설정["rules"]["sellEntry"] = 설정["rules"]["buyEntry"]
    설정["rules"]["buyEntry"] = {"on": False, "steps": []}
    return 설정

주간 = "domestic-day"


def _일봉들() -> list[Bar]:
    """11일 종가 101 로 매수 진입이 걸립니다. 주문은 다음 세션(12일) 첫 체결에 나갑니다."""
    값들 = [(99.0, 99.0), (99.0, 101.0), (101.2, 101.3), (101.3, 101.4)]
    return [
        Bar(_때(0, 0, day=10 + i), o, max(o, c) + 0.1, min(o, c) - 0.1, c, 10)
        for i, (o, c) in enumerate(값들)
    ]


def _일봉셈(**aux) -> dict:
    return backtest.compute(
        draft=_일봉(stopTicks="", takeTicks="", **aux), market="domestic", code="A7569000",
        session=주간, bars=_일봉들(), tick=0.05, margin=1_000.0,
    )


# ── 일봉 + 신규 진입 시간 ─────────────────────────────────


def test_일봉에_신규_진입_시간을_두어도_다음_세션에_진입한다():
    """일봉의 시각은 그날 0시라, 그 시각으로 시간창을 대 보면 늘 창 밖입니다."""
    답 = _일봉셈(entryStart="09:30", entryEnd="15:00")

    assert 답["fills"] == 1
    assert 답["openPosition"]["avgPrice"] == pytest.approx(101.25), "12일 시가 101.2 + 1틱."
    assert 답["assumptions"]["dailyEntryWindow"] == "next-session-open"


def test_신규_진입_시간이_없는_일봉은_그_가정이_없다():
    답 = _일봉셈()

    assert 답["fills"] == 1 and 답["assumptions"]["dailyEntryWindow"] is None


def test_분봉은_신규_진입_시간을_지금처럼_봉_마감_시각으로_본다():
    """09:02 봉이 09:03 에 닫혀 걸립니다 — 09:30 부터인 시간 밖이라 안 냅니다."""
    답 = _셈(_진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2)), _설정(entryStart="09:30"))

    assert 답["fills"] == 0 and 답["assumptions"]["dailyEntryWindow"] is None


# ── 증거금 예산 검사를 건너뛰었는지 ───────────────────────


def _해외셈(*, kind: str = "futures", margin=None, **aux) -> dict:
    return _셈(
        _진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2)),
        _설정(**aux),
        market="overseas",
        session="overseas",
        kind=kind,
        margin=margin,
    )


def test_해외_선물은_예산_검사를_건너뛰었다고_실행과_같은_말로_적는다():
    가정 = _해외셈()["assumptions"]

    assert 가정["budgetUnchecked"] is True
    assert 가정["budgetUncheckedWhy"] == runs.WHY_BUDGET_UNCHECKED == service_lib.WHY_BUDGET_UNCHECKED


def test_국내와_증거금을_아는_해외는_건너뛰지_않는다():
    for 답 in (_셈(_진입봉()), _해외셈(margin=1_000.0)):
        assert (답["assumptions"]["budgetUnchecked"], 답["assumptions"]["budgetUncheckedWhy"]) == (
            False,
            None,
        )


def test_해외_옵션은_매도_진입이_있을_때만_건너뛴다():
    매수만 = _해외셈(kind="option", margin=1_000.0)["assumptions"]
    매도 = _셈(
        _진입봉(),
        _매도설정(),
        market="overseas",
        session="overseas",
        kind="option",
        margin=1_000.0,
    )["assumptions"]

    assert 매수만["budgetUnchecked"] is False
    assert 매도["budgetUnchecked"] is True


def test_예산이_없으면_건너뛸_것도_없다():
    설정 = _설정()
    설정["aux"].pop("marginBudget")
    답 = _셈(_진입봉(), 설정, market="overseas", session="overseas", kind="futures", margin=None)

    assert 답["assumptions"]["budgetUnchecked"] is False


def test_실행과_같은_판정_함수를_쓴다(monkeypatch):
    monkeypatch.setattr(runs, "budget_skipped", lambda run, side: True)

    assert _셈(_진입봉())["assumptions"]["budgetUnchecked"] is True


# ── 세션 끝 정리 ─────────────────────────────────────────


def test_세션_끝_정리를_켜면_어디서_정리하는지_적는다():
    분봉 = _셈(_진입봉(), _설정(sessionEndFlat=True, sessionEndMinutes="10"))
    일봉 = _일봉셈(sessionEndFlat=True, sessionEndMinutes="10")

    assert 분봉["assumptions"]["sessionEndFlat"] == "followed-sessions-only"
    assert 일봉["assumptions"]["sessionEndFlat"] == "not-applied-daily"


def test_세션_끝_정리를_끄면_그_칸이_비어_있다():
    assert _셈(_진입봉())["assumptions"]["sessionEndFlat"] is None
    assert _일봉셈()["assumptions"]["sessionEndFlat"] is None
