"""지표 계산 한 벌.

**손으로 센 값과 맞춥니다.** 계산법을 고르는 자리(EMA 시작값·RSI 평활·BB 표본·
ATR TR)라, 다른 방법으로 바꾸면 여기서 드러나야 합니다.
"""
from __future__ import annotations

from backend.strategy import indicators
from backend.strategy.indicators import Bar


def _bar(at: int, high: float, low: float, close: float, open_: float | None = None) -> Bar:
    return Bar(
        timestamp=at * 60_000,
        open=close if open_ is None else open_,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_준비_봉은_기간의_두_배다():
    assert indicators.warmup_bars(14) == 28
    assert indicators.warmup_bars(20) == 40
    # 0 이나 음수를 받아도 최소 한 봉은 셉니다.
    assert indicators.warmup_bars(0) == indicators.WARMUP_FACTOR


def test_준비_봉이_차기_전은_지운다():
    """식은 기간만 차면 값을 내지만, 앞쪽 값은 시드에 끌려다닙니다."""
    나온것 = indicators.sma(list(range(10)), 3)

    지운것 = indicators.warmed(나온것, 3)

    assert 나온것[2] is not None, "식은 세 봉이면 값을 냅니다."
    assert 지운것[:5] == [None] * 5, "믿으려면 여섯 봉이 필요합니다."
    assert 지운것[5] == 나온것[5], "그 뒤는 그대로 둡니다."


def test_단순_이동평균은_봉이_찰_때부터_나온다():
    나온것 = indicators.sma([1, 2, 3, 4, 5], 3)

    assert 나온것[:2] == [None, None], "봉이 모자란 앞쪽은 0 이 아니라 없음입니다."
    assert 나온것[2] == 2.0 and 나온것[3] == 3.0 and 나온것[4] == 4.0


def test_지수_이동평균은_단순평균으로_시작한다():
    """첫 값을 종가 하나로 잡으면 앞쪽이 한참 흔들립니다."""
    값들 = [10.0, 11.0, 12.0, 13.0, 14.0]

    나온것 = indicators.ema(값들, 3)

    assert 나온것[:2] == [None, None]
    # 3봉째는 단순평균 (10+11+12)/3 = 11.
    assert 나온것[2] == 11.0
    # 그 뒤는 2/(3+1) = 0.5 씩. (13−11)×0.5+11 = 12.
    assert 나온것[3] == 12.0
    assert 나온것[4] == 13.0


def test_지수_이동평균은_봉이_모자라면_전부_없음이다():
    assert indicators.ema([1.0, 2.0], 5) == [None, None]


def test_상대강도지수는_Wilder_평활이다():
    """다섯 봉 연속 상승이면 내림이 하나도 없어 100 입니다."""
    오름 = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]

    나온것 = indicators.rsi(오름, 5)

    assert 나온것[:5] == [None] * 5
    assert 나온것[5] == 100.0


def test_상대강도지수_손으로_센_값():
    """오르내림이 섞인 여섯 봉. 기간 3 으로 손으로 셉니다."""
    값들 = [10.0, 11.0, 10.5, 11.5, 11.0, 12.0]

    나온것 = indicators.rsi(값들, 3)

    # 처음 세 변화: +1, −0.5, +1 → 평균 이익 2/3, 평균 손실 0.5/3.
    assert 나온것[3] is not None
    assert round(나온것[3], 4) == round(100 - 100 / (1 + (2 / 3) / (0.5 / 3)), 4)
    # 다음 봉(−0.5): 이익 (2/3×2)/3, 손실 (0.5/3×2 + 0.5)/3.
    이익 = (2 / 3 * 2) / 3
    손실 = (0.5 / 3 * 2 + 0.5) / 3
    assert round(나온것[4], 4) == round(100 - 100 / (1 + 이익 / 손실), 4)


def test_볼린저는_모집단_표준편차다():
    """표본(n−1)으로 세면 같은 이름의 밴드가 조금 넓어집니다."""
    값들 = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]

    상단, 중심, 하단 = indicators.bollinger(값들, 8, 2.0)

    # 이 여덟 값은 모집단 표준편차가 딱 2 입니다(교과서 예).
    assert 중심[7] == 5.0
    assert 상단[7] == 9.0 and 하단[7] == 1.0
    assert 상단[:7] == [None] * 7


def test_참_범위는_첫_봉만_고저다():
    봉들 = [_bar(0, 12, 10, 11), _bar(1, 13, 11, 12), _bar(2, 15, 11, 14)]

    나온것 = indicators.true_range(봉들)

    assert 나온것[0] == 2.0, "전 봉 종가가 없어 고−저입니다."
    # 둘째 봉: max(13−11, |13−11|, |11−11|) = 2.
    assert 나온것[1] == 2.0
    # 셋째 봉: max(15−11, |15−12|, |11−12|) = 4.
    assert 나온것[2] == 4.0


def test_평균_참_범위는_Wilder_평활이다():
    봉들 = [_bar(0, 12, 10, 11), _bar(1, 13, 11, 12), _bar(2, 15, 11, 14), _bar(3, 16, 14, 15)]

    나온것 = indicators.atr(봉들, 3)

    assert 나온것[:2] == [None, None]
    # 첫 값은 TR 셋의 단순 평균 (2+2+4)/3.
    assert round(나온것[2], 6) == round((2 + 2 + 4) / 3, 6)
    # 넷째 봉 TR = max(16−14, |16−14|, |14−14|) = 2. (앞값×2 + 2)/3.
    assert round(나온것[3], 6) == round((나온것[2] * 2 + 2) / 3, 6)


def test_봉이_모자라면_전부_없음이다():
    봉들 = [_bar(0, 12, 10, 11)]

    assert indicators.atr(봉들, 14) == [None]
    assert indicators.rsi([11.0], 14) == [None]
    assert indicators.bollinger([11.0], 20, 2.0)[0] == [None]
