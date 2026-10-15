"""체결을 봉으로 세우기.

**봉을 손으로 지어 넣습니다.** 시각은 한국시간으로 만들고, 허브가 내는 체결
모양(`timestamp`·`price`·`quantity`)을 그대로 씁니다.
"""
from __future__ import annotations

from datetime import datetime

from backend.sessions.hours import KST
from backend.strategy import bars

주간 = "domestic-day"
야간 = "domestic-night"


def _때(hour: int, minute: int, second: int = 0, day: int = 17) -> int:
    return int(datetime(2026, 9, day, hour, minute, second, tzinfo=KST).timestamp() * 1000)


def _체결(
    hour: int, minute: int, price: float, quantity: int = 1, second: int = 0, day: int = 17
) -> dict:
    return {"timestamp": _때(hour, minute, second, day), "price": price, "quantity": quantity}


def test_기준_봉_이름이_화면과_같다():
    assert bars.minutes_of("5분봉") == 5
    assert bars.minutes_of("60분봉") == 60
    assert bars.minutes_of(bars.DAILY_BAR) is None, "일봉은 분으로 세지 않습니다."
    assert bars.minutes_of("3분봉") is None


def test_분봉_자리는_정각에서_끊는다():
    """15분봉이면 :00·:15·:30·:45 입니다."""
    때 = _때(10, 7, 30)

    assert bars.slot_of(때, 5) == _때(10, 5)
    assert bars.slot_of(때, 15) == _때(10, 0)
    assert bars.slot_of(때, 60) == _때(10, 0)


def test_야간_체결은_다음_거래일에_든다():
    """세션 표와 같은 규칙입니다."""
    assert bars.day_slot_of(_때(23, 30), 야간) == _때(0, 0, day=18)
    assert bars.day_slot_of(_때(2, 30, day=18), 야간) == _때(0, 0, day=18), "자정을 넘긴 뒤입니다."
    assert bars.day_slot_of(_때(10, 0), 주간) == _때(0, 0)


def test_같은_자리_체결은_봉을_키운다():
    만드는것 = bars.BarBuilder("5분봉")

    assert 만드는것.add(_체결(10, 0, 100.0, 2), 주간) == []
    만드는것.add(_체결(10, 1, 103.0, 1), 주간)
    만드는것.add(_체결(10, 4, 99.0, 3), 주간)

    (봉,) = 만드는것.close()
    assert (봉.open, 봉.high, 봉.low, 봉.close) == (100.0, 103.0, 99.0, 99.0)
    assert 봉.volume == 6.0
    assert 봉.timestamp == _때(10, 0)


def test_다음_자리_체결이_앞_봉을_닫는다():
    만드는것 = bars.BarBuilder("5분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)

    닫힌것 = 만드는것.add(_체결(10, 5, 101.0), 주간)

    assert [one.timestamp for one in 닫힌것] == [_때(10, 0)]
    assert 만드는것.open_bar is not None and 만드는것.open_bar.timestamp == _때(10, 5)


def test_비는_분은_봉이_되지_않는다():
    """유효기간 N봉은 실제로 생긴 봉으로 셉니다."""
    만드는것 = bars.BarBuilder("5분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)
    만드는것.add(_체결(10, 40, 101.0), 주간)
    만드는것.close()

    assert [one.timestamp for one in 만드는것.bars] == [_때(10, 0), _때(10, 40)]


def test_세션이_바뀌면_봉을_잇지_않는다():
    """앞 창의 마지막 봉과 다음 창의 첫 봉은 다른 봉입니다."""
    만드는것 = bars.BarBuilder("60분봉")
    만드는것.add(_체결(18, 30, 100.0), 야간)

    닫힌것 = 만드는것.add(_체결(18, 40, 101.0), 주간)
    만드는것.close()

    assert len(닫힌것) == 1, "자리는 같아도 창이 달라 닫힙니다."
    assert 만드는것.sessions == [야간, 주간]
    assert len(만드는것.bars) == 2


def test_판정할_봉을_세션으로_고른다():
    """야간으로 도는 실행은 야간 봉만 판정하고 주간 봉은 지표에만 씁니다."""
    만드는것 = bars.BarBuilder("60분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)
    만드는것.add(_체결(19, 0, 101.0), 야간)
    만드는것.close()

    assert 만드는것.judged(야간) == [1]
    assert 만드는것.judged(주간) == [0]


def test_열린_봉이_없으면_닫아도_빈_봉이_안_선다():
    만드는것 = bars.BarBuilder("5분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)

    assert len(만드는것.close()) == 1
    assert 만드는것.close() == []
    assert len(만드는것.bars) == 1


def _조회봉(hour: int, minute: int, close: float, volume: int = 5) -> dict:
    return {
        "timestamp": _때(hour, minute),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
    }


def test_조회_봉을_시각으로_맞물려_넣는다():
    """겹치는 자리는 조회 봉이 이깁니다 — 거래소가 적어 둔 것입니다."""
    만드는것 = bars.BarBuilder("5분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)
    만드는것.close()

    만드는것.seed([_조회봉(9, 50, 98), _조회봉(9, 55, 99), _조회봉(10, 0, 1)], 주간)

    assert [one.timestamp for one in 만드는것.bars] == [_때(9, 50), _때(9, 55), _때(10, 0)]
    assert 만드는것.bars[-1].close == 1.0, "같은 자리는 조회 봉이 덮습니다."
    assert 만드는것.sessions == [주간, 주간, 주간]


def test_가운데_끊긴_구간도_채운다():
    """끊겼다 다시 붙으면 빈 자리가 앞이 아니라 가운데나 뒤에 생깁니다."""
    만드는것 = bars.BarBuilder("5분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)
    만드는것.add(_체결(10, 20, 104.0), 주간)  # 10:05~10:15 를 놓쳤습니다.
    만드는것.close()
    assert [one.timestamp for one in 만드는것.bars] == [_때(10, 0), _때(10, 20)]

    만드는것.seed([_조회봉(10, 5, 101), _조회봉(10, 10, 102), _조회봉(10, 15, 103)], 주간)

    assert [one.close for one in 만드는것.bars] == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert len(만드는것.sessions) == 5


def test_안_닫힌_봉은_조회_봉이_못_건드린다():
    """아직 자라는 중인 봉입니다 — 조회 봉에는 그 자리가 없거나 반쪽입니다."""
    만드는것 = bars.BarBuilder("5분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)

    만드는것.seed([_조회봉(10, 0, 1)], 주간)

    assert 만드는것.open_bar is not None and 만드는것.open_bar.close == 100.0
    assert [one.close for one in 만드는것.bars] == [1.0], "닫힌 자리는 조회 봉이 채웁니다."


def test_시각이나_가격이_없는_체결은_버리고_센다():
    만드는것 = bars.BarBuilder("5분봉")

    만드는것.add({"price": 100.0, "quantity": 1}, 주간)
    만드는것.add({"timestamp": _때(10, 0), "quantity": 1}, 주간)
    만드는것.seed([{"close": 1}, "줄이 아님"], 주간)

    assert 만드는것.dropped == 4
    assert 만드는것.bars == [] and 만드는것.open_bar is None


def test_일봉은_거래일_하나다():
    만드는것 = bars.BarBuilder(bars.DAILY_BAR)
    만드는것.add(_체결(19, 0, 100.0), 야간)
    만드는것.add(_체결(2, 0, 102.0, day=18), 야간)
    만드는것.close()

    (봉,) = 만드는것.bars
    assert 봉.timestamp == _때(0, 0, day=18)
    assert (봉.open, 봉.close) == (100.0, 102.0)


def test_담아_둘_봉_수를_넘기면_앞에서_버린다():
    만드는것 = bars.BarBuilder("1분봉", limit=2)
    for minute in range(4):
        만드는것.add(_체결(10, minute, 100.0 + minute), 주간)
    만드는것.close()

    assert [one.close for one in 만드는것.bars] == [102.0, 103.0]
    assert len(만드는것.sessions) == 2, "맥락도 함께 줄어듭니다."


def test_지표가_설_만큼_모였는지():
    만드는것 = bars.BarBuilder("1분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)
    만드는것.close()

    assert 만드는것.ready(1) is True
    assert 만드는것.ready(2) is False


def test_분봉을_받을_구간은_넉넉히_잡는다():
    """비는 분은 봉이 되지 않아 시계로 센 구간에는 늘 봉이 모자랍니다."""
    지금 = datetime(2026, 9, 17, 10, 0, tzinfo=KST)

    assert bars.minute_span(100, 5, now=지금) == ("20260915", "20260917")
    시작, 끝 = bars.minute_span(1000, 1, now=지금)
    assert 끝 == "20260917" and 시작 < "20260917"


def test_일봉은_창이_바뀌어도_안_닫는다():
    """「일봉 = 거래일 하나」이고 국내 야간은 다음 거래일에 속합니다."""
    만드는것 = bars.BarBuilder(bars.DAILY_BAR)

    만드는것.add(_체결(19, 0, 100.0), 야간)
    닫힌것 = 만드는것.add(_체결(2, 0, 102.0, day=18), 야간)
    이어진것 = 만드는것.add(_체결(10, 0, 104.0, day=18), 주간)
    만드는것.close()

    assert 닫힌것 == [] and 이어진것 == [], "야간과 그 다음 주간이 한 봉입니다."
    (봉,) = 만드는것.bars
    assert (봉.open, 봉.close) == (100.0, 104.0)
    assert 만드는것.sessions == [야간], "그 거래일의 첫 체결이 온 창을 적습니다."


def test_분봉은_창이_바뀌면_닫는다():
    """앞 창의 마지막 봉과 다음 창의 첫 봉은 다른 봉입니다."""
    만드는것 = bars.BarBuilder("60분봉")
    만드는것.add(_체결(18, 30, 100.0), 야간)

    닫힌것 = 만드는것.add(_체결(18, 40, 101.0), 주간)

    assert len(닫힌것) == 1


def test_일봉은_판정할_봉을_창으로_가리지_않는다():
    만드는것 = bars.BarBuilder(bars.DAILY_BAR)
    만드는것.add(_체결(19, 0, 100.0), 야간)
    만드는것.close()
    만드는것.add(_체결(10, 0, 104.0, day=18), 주간)
    만드는것.close()

    assert 만드는것.daily is True
    assert 만드는것.judged(주간) == [0, 1]
    assert 만드는것.judged(야간) == [0, 1]


def test_분봉은_제_창의_봉만_고른다():
    만드는것 = bars.BarBuilder("60분봉")
    만드는것.add(_체결(10, 0, 100.0), 주간)
    만드는것.add(_체결(19, 0, 101.0), 야간)
    만드는것.close()

    assert 만드는것.daily is False
    assert 만드는것.judged(야간) == [1]


def test_일봉_구간은_주말만큼_넉넉히_잡는다():
    """주말과 휴장일에는 봉이 서지 않습니다."""
    지금 = datetime(2026, 9, 17, 10, 0, tzinfo=KST)

    시작, 끝 = bars.day_span(40, now=지금)

    assert 끝 == "20260917"
    assert 시작 < "20260801", "40 거래일이면 두 달 남짓 거슬러야 합니다."


def test_거래일이_바뀌면_일봉이_닫힌다():
    """창으로는 안 갈라도 거래일이 바뀌면 갈립니다."""
    만드는것 = bars.BarBuilder(bars.DAILY_BAR)
    만드는것.add(_체결(19, 0, 100.0), 야간)
    만드는것.add(_체결(10, 0, 104.0, day=18), 주간)

    # 다음 거래일의 야간입니다 — 18일 저녁은 19일 거래일입니다.
    닫힌것 = 만드는것.add(_체결(19, 0, 106.0, day=18), 야간)

    assert [one.timestamp for one in 닫힌것] == [_때(0, 0, day=18)]
    assert 만드는것.open_bar is not None
    assert 만드는것.open_bar.timestamp == _때(0, 0, day=19)


def test_조회_일봉에는_부르는_쪽이_준_창을_적는다():
    """응답은 그 구간의 값일 뿐 어느 창에서 왔는지 말해 주지 않습니다."""
    만드는것 = bars.BarBuilder(bars.DAILY_BAR)
    만드는것.add(_체결(19, 0, 100.0), 야간)
    만드는것.close()

    만드는것.seed(
        [
            {
                "timestamp": _때(0, 0, day=15),
                "open": 98,
                "high": 99,
                "low": 97,
                "close": 98,
                "volume": 5,
            }
        ],
        주간,
    )

    assert [one.timestamp for one in 만드는것.bars] == [_때(0, 0, day=15), _때(0, 0, day=18)]
    assert 만드는것.sessions == [주간, 야간], "조회 봉은 준 창, 실시간 봉은 첫 체결의 창."
    assert 만드는것.judged(주간) == [0, 1], "일봉은 창으로 안 가립니다."
