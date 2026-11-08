"""장 열림 공용 판정 — 가짜 judge 로."""
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.team_pyrun import opening

KST = ZoneInfo("Asia/Seoul")


def at(h, m, s=0):
    return datetime(2026, 11, 9, h, m, s, tzinfo=KST)


def fake(state, **extra):
    return lambda market, sym, now: {"state": state, "source": "table", **extra}


def boom(market, sym, now):
    raise RuntimeError("시간표 없음")


def test_domestic_data_vs_order():
    j = fake("day")
    assert opening.is_open(j, "domestic", "A75X", at(8, 50))
    assert not opening.order_open(j, "domestic", "A75X", at(8, 50))
    assert opening.order_open(j, "domestic", "A75X", at(9, 0))


def test_domestic_night_closed():
    assert not opening.is_open(fake("night"), "domestic", "A75X", at(9, 30))


def test_overseas_states():
    assert not opening.is_open(fake("break"), "overseas", "MKUX26", at(20, 40))
    for s in ("open", "open-2", "next-day"):
        assert opening.is_open(fake(s), "overseas", "MKUX26", at(10, 0))
        assert opening.order_open(fake(s), "overseas", "MKUX26", at(8, 30))


def test_judge_error_is_closed_and_unknown():
    assert not opening.is_open(boom, "overseas", "X", at(10, 0))
    assert not opening.order_open(boom, "overseas", "X", at(10, 0))
    assert not opening.known(boom, "overseas", "X", at(10, 0))
    assert opening.span_text(boom, "overseas", "X", at(10, 0)) == "장 시간표 모름"


def test_known_false_on_unknown_source():
    j = lambda m, s, n: {"state": "closed", "source": "unknown"}  # noqa: E731
    assert not opening.known(j, "overseas", "X", at(10, 0))
    assert opening.span_text(j, "overseas", "X", at(10, 0)) == "장 시간표 모름"
    assert opening.known(fake("open"), "overseas", "X", at(10, 0))


def test_span_text_break_and_closed():
    j = fake("break", since="2026-11-09T20:35:00+09:00", until="2026-11-09T20:50:00+09:00")
    assert opening.span_text(j, "overseas", "MKUX26", at(20, 40)) == "휴장 20:35~20:50"
    assert opening.span_text(fake("closed"), "overseas", "MKUX26", at(7, 0)) == "장 마감"


def test_default_day_end_domestic_none():
    assert opening.default_day_end("domestic", "A75X", at(10, 0)) is None


def test_order_window_open():
    from datetime import timezone
    assert not opening.order_window_open("domestic", at(8, 59, 59))
    assert opening.order_window_open("domestic", at(9, 0))
    assert opening.order_window_open("overseas", at(3, 0))
    utc = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)    # = 09:00 KST
    assert opening.order_window_open("domestic", utc)
    assert not opening.order_window_open("domestic", datetime(2026, 11, 8, 23, 59, tzinfo=timezone.utc))
