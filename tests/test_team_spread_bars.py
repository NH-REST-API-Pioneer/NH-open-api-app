"""스프레드 1분봉 맞추기(`align`) 시험 — 순수 함수. 줄 칸은 기록(`tests/fixtures/nh/*chart-minute`)과 같다."""
from backend.team_spread.bars import LegBar, Minute, align


def row(tm, close, *, date="20261109", open_=None, vol="5"):
    """접두(`occurs1_`)를 뗀 차트 줄 — 국내·해외 모두 `ref_dt` `exch_tm` `*_pric` `cum_trd_qty`."""
    o = close if open_ is None else open_
    return {"ref_dt": date, "exch_tm": tm, "open_pric": str(o), "high_pric": str(close + 1),
            "low_pric": str(o - 1), "close_pric": str(close), "cum_trd_qty": vol}


def test_같은_분은_다리별_봉을_합친다():
    got = align({"ho": [row("090100", 12.0), row("090000", 10.0)], "rb": [row("090100", 22.0), row("090000", 20.0)]})
    assert [m.time for m in got] == ["090000", "090100"]          # 오래된 것부터
    assert got[1] == Minute("20261109", "090100", {
        "ho": LegBar(12.0, 13.0, 11.0, 12.0, 5.0, False),
        "rb": LegBar(22.0, 23.0, 21.0, 22.0, 5.0, False)})


def test_한_다리에_봉이_없는_분은_직전_종가로_채운다():
    got = align({"ho": [row("090200", 14.0), row("090100", 12.0), row("090000", 10.0)],
                 "rb": [row("090200", 24.0), row("090000", 20.0)]})
    assert got[1].legs["rb"] == LegBar(20.0, 20.0, 20.0, 20.0, 0.0, True)
    assert got[1].legs["ho"].filled is False
    assert got[2].legs["rb"].filled is False


def test_모든_다리에_값이_생기기_전의_분은_버린다():
    got = align({"ho": [row("090100", 12.0), row("090000", 10.0), row("085900", 9.0)],
                 "rb": [row("090100", 22.0)]})
    assert [m.time for m in got] == ["090100"]


def test_날짜가_다르면_날짜_먼저_정렬한다():
    got = align({"a": [row("000100", 2.0, date="20261110"), row("235900", 1.0, date="20261109")],
                 "b": [row("000100", 4.0, date="20261110"), row("235900", 3.0, date="20261109")]})
    assert [(m.date, m.time) for m in got] == [("20261109", "235900"), ("20261110", "000100")]


def test_같은_봉이_두_번_오면_한_번만():
    got = align({"a": [row("090000", 1.0), row("090000", 1.0)], "b": [row("090000", 2.0)]})
    assert len(got) == 1


def test_줄이_없으면_빈_목록():
    assert align({}) == []
    assert align({"a": [], "b": [row("090000", 1.0)]}) == []
