"""허브 원문 갈고리(`hub.py` `# 팀:`)와 `team_pyrun.rawfeed.RawFeed`.

허브는 FastAPI 이벤트 루프 위에서 돌고, 실행은 스레드에서 돈다. 시험도 그 모양 그대로
**루프를 다른 스레드에 띄우고** 시험 스레드(= 실행 스레드)에서 RawFeed 를 쓴다.
NH 연결은 가짜 연결(`가짜연결`)로 바꾸고, 메시지 도착은 루프에서 `_on_data` 를 부르는 것으로 흉내 낸다
(진짜 연결도 `_receive` 에서 이 자리를 부른다).
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from backend.realtime.feeds import Feed
from backend.realtime.hub import Hub, MarketGroup
from backend.team_pyrun import rawfeed
from backend.team_pyrun.rawfeed import RawFeed, RawMessage

KRX = "A756B000"
MKU = "MKUX26"
KA = ("domestic", "KA", KRX)
FB = ("overseas", "FB", MKU)
FA = ("overseas", "FA", MKU)


class 가짜연결:
    """NH선물 연결 대신. 구독을 받아 적기만 한다."""

    def __init__(self, market: str) -> None:
        self.market = market
        self.keys: set = set()
        self.failures: dict = {}

    def __len__(self) -> int:
        return len(self.keys)

    def start(self) -> None:
        pass

    async def add(self, key, feed) -> None:
        self.keys.add(key)

    async def remove(self, key) -> None:
        self.keys.discard(key)

    async def refresh(self, key) -> None:
        pass

    async def stop(self) -> None:
        self.keys.clear()


class 가짜허브(Hub):
    def _group(self, market: str) -> MarketGroup:
        return MarketGroup(market, capacity=20, make_link=lambda: 가짜연결(market))


@pytest.fixture
def loop():
    """앱의 이벤트 루프 자리. 다른 스레드에서 돈다."""
    made = asyncio.new_event_loop()
    thread = threading.Thread(target=made.run_forever, daemon=True)
    thread.start()
    yield made
    made.call_soon_threadsafe(made.stop)
    thread.join(timeout=5)
    made.close()


@pytest.fixture
def hub(loop):
    async def make():
        return 가짜허브(environment="paper", session_clock=False, flush_interval=0.01)

    engine = asyncio.run_coroutine_threadsafe(make(), loop).result(5)
    yield engine
    asyncio.run_coroutine_threadsafe(engine.stop(), loop).result(5)


def 루프에서(loop, fn, *args):
    """루프에서 `fn(*args)` 을 부르고 끝날 때까지 기다린다."""

    async def go():
        return fn(*args)

    return asyncio.run_coroutine_threadsafe(go(), loop).result(5)


def 도착(loop, hub, messages):
    """메시지들을 **이 순서로** 허브 원문 자리에 넣는다(루프에서 한 번에)."""

    def go():
        for key, body in messages:
            hub._on_data(key, body)

    루프에서(loop, go)


def 받기(feed: RawFeed, n: int, timeout: float = 2.0) -> list[RawMessage]:
    out = []
    for _ in range(n):
        one = feed.get(timeout=timeout)
        assert one is not None, f"{len(out)}건 받고 끊겼다"
        out.append(one)
    return out


def 원하는것() -> list[Feed]:
    return [Feed("domestic-day", "quote", KRX), Feed("overseas", "book", MKU)]


def ka(price: str, seq: int) -> dict:
    return {"curr_pric": price, "tick_div": "1", "exch_tm": "090000", "seq": seq}


def fb(bid: str, ask: str, seq: int) -> dict:
    return {"bid_pric1": bid, "ask_pric1": ask, "ko_exec_tm": "090000", "seq": seq}


# ── 순서 ────────────────────────────────────────────────


def test_KA_FB_섞인_순서를_받은_그대로_넘긴다(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        sent = [
            (KA, ka("1400.1", 1)),
            (FB, fb("1400.05", "1400.15", 2)),
            (FB, fb("1400.06", "1400.16", 3)),
            (KA, ka("1400.2", 4)),
            (KA, ka("1400.3", 5)),
            (FB, fb("1400.07", "1400.17", 6)),
        ]
        도착(loop, hub, sent)
        got = 받기(feed, len(sent))
        assert [(m.market, m.api_id, m.sym) for m in got] == [key for key, _ in sent]
        assert [m.body for m in got] == [body for _, body in sent]
        stamps = [m.recv_monotonic for m in got]
        assert stamps == sorted(stamps)
        assert all(abs(s - time.monotonic()) < 60 for s in stamps)
        assert feed.get(timeout=0.05) is None
        assert not feed.overflow
    finally:
        feed.close()


def test_원하지_않은_구독의_원문은_넘기지_않는다(loop, hub):
    # 화면이 같은 MKU 의 체결(FA)을 보고 있어도 RawFeed 는 자기가 원한 것만 받는다.
    screen = 루프에서(loop, hub.attach, "화면")
    asyncio.run_coroutine_threadsafe(
        hub.declare("화면", {Feed("overseas", "quote", MKU): 1}), loop
    ).result(5)
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        도착(loop, hub, [(FA, {"seq": 1}), (FB, fb("1", "2", 2)), (FA, {"seq": 3})])
        got = 받기(feed, 1)
        assert got[0].api_id == "FB" and got[0].body["seq"] == 2
        assert feed.get(timeout=0.05) is None
    finally:
        feed.close()
    assert screen is not None


def test_허브는_원문의_사본을_넘긴다(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        body = ka("1400.1", 1)
        도착(loop, hub, [(KA, body)])
        got = 받기(feed, 1)[0]
        got.body["curr_pric"] = "바뀜"
        assert body["curr_pric"] == "1400.1"
    finally:
        feed.close()


# ── 운영자 동작 그대로 ───────────────────────────────────


def test_화면은_여전히_묶은_값을_받는다(loop, hub):
    screen = 루프에서(loop, hub.attach, "화면")
    asyncio.run_coroutine_threadsafe(
        hub.declare("화면", {Feed("overseas", "book", MKU): 1}), loop
    ).result(5)
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        도착(loop, hub, [(FB, {"bid_pric1": "1.0", "ask_pric1": "1.1"}),
                         (FB, {"bid_pric1": "1.2", "ask_pric1": "1.3"})])
        assert len(받기(feed, 2)) == 2

        async def 책_기다리기():
            deadline = time.monotonic() + 2
            books = []
            while time.monotonic() < deadline:
                try:
                    one = await asyncio.wait_for(screen.queue.get(), 0.1)
                except TimeoutError:
                    if books:
                        break
                    continue
                if one.get("type") == "book":
                    books.append(one)
            return books

        books = asyncio.run_coroutine_threadsafe(책_기다리기(), loop).result(5)
        # 묶음: 100ms 안에 온 두 호가는 마지막 하나만.
        assert len(books) == 1
        assert books[0]["sym"] == MKU
    finally:
        feed.close()


def test_구독자가_터져도_허브는_묶음과_다른_구독자를_이어_간다(loop, hub, caplog):
    def boom(*args):
        raise RuntimeError("구독자 고장")

    루프에서(loop, hub.raw_listeners.append, boom)
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        도착(loop, hub, [(KA, ka("1", 1)), (KA, ka("2", 2))])
        assert [m.body["seq"] for m in 받기(feed, 2)] == [1, 2]
        assert "원문 구독자" in caplog.text
    finally:
        feed.close()
        루프에서(loop, hub.raw_listeners.remove, boom)


def test_원문_구독자가_없으면_아무것도_안_한다(loop, hub):
    assert hub.raw_listeners == []
    도착(loop, hub, [(KA, ka("1", 1))])  # 터지지 않는다


# ── 구독 ────────────────────────────────────────────────


def test_실행_id_이름으로_붙어_선언하고_묶음은_비워_버린다(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        assert feed.client_name in hub._clients
        assert "run1" in feed.client_name
        client = hub._clients[feed.client_name]
        assert set(client.feeds) == set(원하는것())
        # 묶음 큐가 비워지는지: 묶인 시세가 와도 쌓이지 않는다.
        도착(loop, hub, [(KA, ka(str(i), i)) for i in range(300)])
        받기(feed, 300)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (client.queue.qsize() or feed.subscriptions is None):
            time.sleep(0.02)
        assert client.queue.qsize() == 0
        assert feed.subscriptions is not None
        assert {tuple(sorted(f.items())) for f in feed.subscriptions["granted"]} == {
            tuple(sorted(f.as_dict().items())) for f in 원하는것()
        }
    finally:
        feed.close()


def test_close_뒤에는_원문이_안_오고_구독도_놓는다(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    name = feed.client_name
    도착(loop, hub, [(KA, ka("1", 1))])
    feed.close()
    도착(loop, hub, [(KA, ka("2", 2)), (FB, fb("1", "2", 3))])
    assert feed.get(timeout=0.05) is None
    assert name not in hub._clients
    assert hub.raw_listeners == []
    assert hub._subscribed == frozenset()
    feed.close()  # 두 번 불러도 된다


def test_close_뒤_남은_것도_버린다(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    도착(loop, hub, [(KA, ka("1", 1)), (KA, ka("2", 2))])
    feed.close()
    assert feed.get(timeout=0.05) is None


# ── 쌓임 한도 ───────────────────────────────────────────


def test_한도를_넘기면_overflow_를_세우고_더_넣지_않는다(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop, limit=3)
    try:
        도착(loop, hub, [(KA, ka(str(i), i)) for i in range(5)])
        assert feed.overflow
        got = [feed.get(timeout=0.2) for _ in range(4)]
        assert [m.body["seq"] for m in got[:3]] == [0, 1, 2]
        assert got[3] is None
        # 비운 뒤에도 overflow 는 그대로 — 이미 빠진 메시지가 있다.
        도착(loop, hub, [(KA, ka("9", 9))])
        assert feed.get(timeout=0.05) is None
        assert feed.overflow
    finally:
        feed.close()


def test_기본_한도는_5000(loop, hub):
    feed = RawFeed("run1", 원하는것(), hub=hub, loop=loop)
    try:
        assert feed.limit == rawfeed.DEFAULT_LIMIT == 5000
    finally:
        feed.close()


# ── 루프 ────────────────────────────────────────────────


def test_루프를_모르면_세우지_않는다(hub, monkeypatch):
    monkeypatch.setattr(rawfeed, "_loop", None)
    with pytest.raises(RuntimeError):
        RawFeed("run1", 원하는것(), hub=hub)


def test_루프_스레드에서_부르면_막히지_않고_거절한다(loop, hub):
    async def inside():
        with pytest.raises(RuntimeError):
            RawFeed("run1", 원하는것(), hub=hub, loop=loop)
        return True

    assert asyncio.run_coroutine_threadsafe(inside(), loop).result(5)


def test_앱이_뜰_때_루프를_잡고_꺼질_때_놓는다(monkeypatch):
    from backend.team_pyrun import routes as routes_mod

    async def no_recover():
        return None

    monkeypatch.setattr(routes_mod, "_recover", no_recover)
    monkeypatch.setattr(rawfeed, "_loop", None)

    async def life():
        task = routes_mod.pyrun_startup()
        await task
        seen = rawfeed._loop
        await routes_mod.pyrun_shutdown(None)
        return seen, asyncio.get_running_loop()

    seen, running = asyncio.run(life())
    assert seen is running
    assert rawfeed._loop is None
