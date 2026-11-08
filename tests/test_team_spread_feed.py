"""스프레드 시세 공급(`LiveFeed`) 시험 — 시계·쉼·가짜 api·가짜 세션 판정을 모두 넣어 실제로 쉬지 않는다."""
import threading
from datetime import datetime, timedelta

from backend.sessions.hours import KST
from backend.team_spread.feed import CHART_MAX_BARS, LiveFeed
from backend.team_spread.legs import Leg


def leg(name, sym, market="domestic", exchange="KRX"):
    return Leg(name, sym, sym[:2], market, exchange, "KRW" if market == "domestic" else "USD",
               0.1, 10.0, "202612")


HO = leg("ho", "HOZ26", "overseas", "FNYM")
RB = leg("rb", "RBZ26", "overseas", "FNYM")


def row(tm, close, date="20261109"):
    return {"ref_dt": date, "exch_tm": tm, "open_pric": str(close), "high_pric": str(close),
            "low_pric": str(close), "close_pric": str(close), "cum_trd_qty": "3"}


class FakeAdapter:
    def __init__(self, rows, price=None):
        self.rows, self.calls, self._price = rows, [], price or {}

    def chart_minute(self, sym, *, req_qty):
        self.calls.append((sym, req_qty))
        return list(self.rows)

    def price(self, sym):
        return self._price


class Clock:
    """`sleep` 이 시계를 앞으로 보낸다."""

    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds, stop):
        if stop.is_set():
            return
        self.t += timedelta(seconds=seconds)


def at(h, m, s):
    return datetime(2026, 11, 9, h, m, s, tzinfo=KST)


def make(clock, adapters, judge, on_wait=None):
    kw = {"on_wait": on_wait} if on_wait else {}
    return LiveFeed(now=clock.now, sleep=clock.sleep, adapter_of=lambda leg: adapters[leg.name],
                    judge=judge, **kw)


def open_judge(market, sym, now):
    return {"state": "open"}


def test_분이_끝나고_3초_뒤_그_분_봉을_돌려준다():
    clock = Clock(at(9, 0, 30))
    ad = {"ho": FakeAdapter([row("090000", 10.0)]), "rb": FakeAdapter([row("090000", 20.0)])}
    got = make(clock, ad, open_judge).next_minute([HO, RB], threading.Event())
    assert (got.date, got.time) == ("20261109", "090000")
    assert got.legs["ho"].close == 10.0 and got.legs["rb"].close == 20.0
    assert clock.t.minute == 1 and clock.t.second >= 3
    assert ad["ho"].calls[0][0] == "HOZ26"


def test_한_다리에_봉이_없으면_채워서_돌려준다():
    clock = Clock(at(9, 0, 30))
    ad = {"ho": FakeAdapter([row("090000", 10.0), row("085900", 9.0)]), "rb": FakeAdapter([row("085900", 19.0)])}
    got = make(clock, ad, open_judge).next_minute([HO, RB], threading.Event())
    assert got.time == "090000"
    assert got.legs["rb"].filled is True and got.legs["rb"].close == 19.0
    assert got.legs["ho"].filled is False


def test_한_다리가_장_쉼이면_열릴_때까지_기다린다():
    clock = Clock(at(9, 0, 30))
    ad = {"ho": FakeAdapter([row("090000", 10.0), row("090100", 11.0)]),
          "rb": FakeAdapter([row("090000", 20.0), row("090100", 21.0)])}

    def judge(market, sym, now):
        closed = sym == "RBZ26" and now < at(9, 1, 30)
        return {"state": "closed" if closed else "open"}

    waits = []
    feed = make(clock, ad, judge, lambda s, names: waits.append((s, list(names))))
    gaps = []
    feed._on_gap = lambda a, b, c: gaps.append((a, b, c))
    got = feed.next_minute([HO, RB], threading.Event())
    assert waits == [("장 쉼", ["rb"]), ("진행 중", [])]
    assert got.time == "090100"                        # 090000 분은 rb 가 닫힌 채 끝났다 — 쉰 구간
    assert gaps == [("20261109 090000", "20261109 090000", "장 쉼")]
    assert clock.t >= at(9, 1, 30)
    assert all(m.legs[n].filled is False for m in [got] for n in ("ho", "rb"))


def test_stop_이면_바로_None():
    clock = Clock(at(9, 0, 30))
    stop = threading.Event()
    stop.set()
    ad = {"ho": FakeAdapter([]), "rb": FakeAdapter([])}
    assert make(clock, ad, open_judge).next_minute([HO, RB], stop) is None


def test_기다리는_중_stop_이_서면_1초_안에_None():
    clock = Clock(at(9, 0, 30))
    stop = threading.Event()
    sleeps = []

    def sleep(seconds, st):
        sleeps.append(seconds)
        stop.set()

    feed = LiveFeed(now=clock.now, sleep=sleep, adapter_of=lambda leg: FakeAdapter([]), judge=open_judge)
    assert feed.next_minute([HO, RB], stop) is None
    assert max(sleeps) <= 1.0


def test_장_쉼_내내_stop_이면_None():
    clock = Clock(at(9, 0, 30))
    stop = threading.Event()
    n = {"i": 0}

    def sleep(seconds, st):
        n["i"] += 1
        if n["i"] > 3:
            st.set()
        clock.t += timedelta(seconds=seconds)

    feed = LiveFeed(now=clock.now, sleep=sleep, adapter_of=lambda leg: FakeAdapter([]),
                    judge=lambda m, s, now: {"state": "closed"})
    assert feed.next_minute([HO, RB], stop) is None


def test_세션_판정이_unknown_이면_닫힘():
    clock = Clock(at(9, 0, 30))
    for state in ("unknown", "closed", "break", "pre-open", "closing-auction"):
        feed = make(clock, {}, lambda m, s, now, st=state: {"state": st})
        assert feed.is_open(HO, clock.t) is False
    for state in ("open", "open-2", "next-day"):
        feed = make(clock, {}, lambda m, s, now, st=state: {"state": st})
        assert feed.is_open(HO, clock.t) is True


def test_세션_판정이_예외를_던지면_닫힘():
    def boom(m, s, now):
        raise RuntimeError("x")

    assert make(Clock(at(9, 0, 0)), {}, boom).is_open(HO, at(9, 0, 0)) is False


def test_history_는_다리별_차트를_맞춰_돌려준다():
    ad = {"ho": FakeAdapter([row("090100", 12.0), row("090000", 10.0)]),
          "rb": FakeAdapter([row("090100", 22.0), row("090000", 20.0)])}
    got = make(Clock(at(9, 2, 0)), ad, open_judge).history([HO, RB], 50)
    assert [m.time for m in got] == ["090000", "090100"]
    assert ad["ho"].calls == [("HOZ26", 50)]


def test_quote_는_현재가_호가를_읽는다():
    p = {"last_pric": "10.5", "bid_pric": "10.4", "ask_pric": "10.6"}
    ad = {"ho": FakeAdapter([], p)}
    q = make(Clock(at(9, 2, 0)), ad, open_judge).quote(HO)
    assert (q.last, q.bid, q.ask, q.at) == (10.5, 10.4, 10.6, at(9, 2, 0))


def test_domestic_다리는_주간만_열림():
    d = leg("fx", "A756B000")
    for state, want in (("day", True), ("night", False), ("open", False), ("closed", False)):
        feed = make(Clock(at(9, 0, 0)), {}, lambda m, s, now, st=state: {"state": st})
        assert feed.is_open(d, at(9, 0, 0)) is want
    feed = make(Clock(at(9, 0, 0)), {}, lambda m, s, now: {"state": "day"})
    assert feed.is_open(HO, at(9, 0, 0)) is False       # 해외 다리는 day 가 아니다


def _rows(n):
    return [row(f"09{m:02d}00", 10.0 + m) for m in range(n - 1, -1, -1)]     # 최신 먼저


def test_느린_호출자는_놓친_분을_순서대로_따라잡는다():
    clock = Clock(at(9, 0, 30))
    ad = {"ho": FakeAdapter(_rows(4)), "rb": FakeAdapter(_rows(4))}
    feed = make(clock, ad, open_judge)
    stop = threading.Event()
    assert feed.next_minute([HO, RB], stop).time == "090000"
    clock.t = at(9, 4, 10)                               # 3분 동안 부르지 않았다
    got = [feed.next_minute([HO, RB], stop).time for _ in range(3)]
    assert got == ["090100", "090200", "090300"]         # 빠짐·중복 없이 순서대로


def test_조회_실패는_알리고_계속_시도하다가_공백으로_밝힌다():
    clock = Clock(at(9, 0, 30))
    errors, gaps = [], []
    stop = threading.Event()

    class Broken(FakeAdapter):
        def chart_minute(self, sym, *, req_qty):
            raise ConnectionError("끊김")

    def sleep(seconds, st):
        clock.t += timedelta(seconds=seconds)
        if gaps:
            st.set()

    feed = LiveFeed(now=clock.now, sleep=sleep, adapter_of=lambda leg: Broken([]), judge=open_judge,
                    on_gap=lambda a, b, c: gaps.append((a, b, c)), on_error=errors.append)
    assert feed.next_minute([HO, RB], stop) is None
    assert errors == ["ConnectionError: 끊김"]
    assert gaps[0][0] == "20261109 090000" and "끊김" in gaps[0][2]


def test_조회_오류_문구의_토큰은_가려서_알린다():
    clock = Clock(at(9, 0, 30))
    errors, gaps = [], []
    stop = threading.Event()

    class Leaky(FakeAdapter):
        def chart_minute(self, sym, *, req_qty):
            raise PermissionError("인증 실패 Bearer TOKEN123 {'access_token': 'SECRET9'}")

    def sleep(seconds, st):
        clock.t += timedelta(seconds=seconds)
        if gaps:
            st.set()

    feed = LiveFeed(now=clock.now, sleep=sleep, adapter_of=lambda leg: Leaky([]), judge=open_judge,
                    on_gap=lambda a, b, c: gaps.append((a, b, c)), on_error=errors.append)
    feed.next_minute([HO, RB], stop)
    said = " ".join(errors + [g[2] for g in gaps])
    assert errors and gaps and "Bearer ***" in said and "TOKEN123" not in said and "SECRET9" not in said


def test_중간_분에_봉이_없으면_공백을_알린다():
    clock = Clock(at(9, 0, 30))
    gaps = []
    rows_ = [row("090300", 13.0), row("090000", 10.0)]
    feed = LiveFeed(now=clock.now, sleep=clock.sleep, judge=open_judge,
                    adapter_of=lambda leg: FakeAdapter(rows_), on_gap=lambda a, b, c: gaps.append((a, b, c)))
    stop = threading.Event()
    assert feed.next_minute([HO, RB], stop).time == "090000"
    clock.t = at(9, 4, 10)
    assert feed.next_minute([HO, RB], stop).time == "090300"
    assert gaps == [("20261109 090100", "20261109 090200", "차트에 봉 없음")]


def test_닫히기_직전_마지막_분도_돌려준다():
    d = leg("fx", "A756B000")
    clock = Clock(at(15, 44, 30))
    ad = {"fx": FakeAdapter([row("154400", 10.0), row("154300", 9.0)])}
    waits = []
    judge = lambda m, s, now: {"state": "day" if now < at(15, 45, 0) else "closed"}     # noqa: E731
    feed = make(clock, ad, judge, lambda s, n: waits.append((s, n)))
    got = feed.next_minute([d], threading.Event())
    assert got.time == "154400" and clock.t == at(15, 45, 3)       # 15:45:03 에 이미 닫혔어도 15:44 봉은 온전
    assert waits == []


def test_주말_뒤_열리면_쉰_구간을_한_번_밝히고_열린_뒤_첫_분부터():
    d = leg("fx", "A756B000")
    clock = Clock(at(15, 44, 30))                                  # 2026-11-09 월요일을 금요일처럼 쓴다
    reopen = datetime(2026, 11, 14 + 2, 9, 0, 0, tzinfo=KST)       # 다음 월요일 09:00 (16일)
    calls = []

    class Ad(FakeAdapter):
        def chart_minute(self, sym, *, req_qty):
            calls.append(req_qty)
            return [row("090100", 12.0, "20261116"), row("090000", 11.0, "20261116"),
                    row("154400", 10.0, "20261109")]

    def judge(m, s, now):
        return {"state": "day" if (now < at(15, 45, 0) or now >= reopen) else "closed"}

    waits, gaps = [], []
    feed = LiveFeed(now=clock.now, sleep=lambda sec, st: setattr(clock, "t", clock.t + timedelta(seconds=sec * 600)),
                    adapter_of=lambda leg: Ad([]), judge=judge,
                    on_wait=lambda s, n: waits.append(s), on_gap=lambda a, b, c: gaps.append((a, b, c)))
    stop = threading.Event()
    assert feed.next_minute([d], stop).time == "154400"
    got = feed.next_minute([d], stop)
    assert (got.date, got.time) == ("20261116", "090000")          # 쉬기 전 봉(금요일 15:44)은 다시 주지 않는다
    assert waits == ["장 쉼", "진행 중"]
    assert [g[2] for g in gaps] == ["장 쉼"]
    assert gaps[0][0] == "20261109 154500"
    assert max(calls) <= CHART_MAX_BARS


def test_열린_직후_1초_간격으로_봐도_장_쉼_공백은_한_번():
    d = leg("fx", "A756B000")
    clock = Clock(at(15, 44, 30))
    reopen = datetime(2026, 11, 16, 9, 0, 0, tzinfo=KST)
    rows_ = [row("090300", 13.0, "20261116"), row("090200", 12.0, "20261116"), row("090100", 11.0, "20261116"),
             row("090000", 10.0, "20261116"), row("154400", 9.0, "20261109")]
    waits, gaps = [], []

    def sleep(sec, st):
        # 쉬는 동안은 크게 건너뛰고, 열리기 직전부터는 실제처럼 1초씩 간다
        if clock.t < reopen - timedelta(minutes=5):
            clock.t += timedelta(minutes=5)
        else:
            clock.t += timedelta(seconds=sec)

    def judge(m, s, now):
        return {"state": "day" if (now < at(15, 45, 0) or now >= reopen) else "closed"}

    feed = LiveFeed(now=clock.now, sleep=sleep, adapter_of=lambda leg: FakeAdapter(rows_), judge=judge,
                    on_wait=lambda s, n: waits.append(s), on_gap=lambda a, b, c: gaps.append((a, b, c)))
    stop = threading.Event()
    assert feed.next_minute([d], stop).time == "154400"
    got = feed.next_minute([d], stop)
    assert (got.date, got.time) == ("20261116", "090000")
    assert [g[2] for g in gaps] == ["장 쉼"] and gaps[0][0] == "20261109 154500"
    assert gaps[0][1] == "20261116 085900"
    assert feed.next_minute([d], stop).time == "090100"            # 이어서 빠짐없이
    assert [g[2] for g in gaps] == ["장 쉼"]
