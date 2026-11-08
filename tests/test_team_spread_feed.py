"""스프레드 시세 공급(`LiveFeed`) 시험 — 시계·쉼·가짜 api·가짜 세션 판정을 모두 넣어 실제로 쉬지 않는다."""
import threading
from datetime import datetime, timedelta

from backend.sessions.hours import KST
from backend.team_spread.feed import LiveFeed
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
    ad = {"ho": FakeAdapter([row("090100", 10.0), row("090200", 11.0)]),
          "rb": FakeAdapter([row("090100", 20.0), row("090200", 21.0)])}

    def judge(market, sym, now):
        closed = sym == "RBZ26" and now < at(9, 1, 30)
        return {"state": "closed" if closed else "open"}

    waits = []
    got = make(clock, ad, judge, lambda s, names: waits.append((s, list(names)))).next_minute(
        [HO, RB], threading.Event())
    assert waits == [("장 쉼", ["rb"]), ("진행 중", [])]
    assert got.time == "090100" or got.time == "090200"
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
    for state in ("day", "night", "open", "open-2", "next-day"):
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
