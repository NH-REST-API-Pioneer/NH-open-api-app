"""서버가 거절한 실시간 구독 — 연결이 실패로 들고, 허브가 화면에 알립니다.

거절 답의 모양은 실서버에서 받은 것 그대로입니다(시세 사용 신청을 하지 않은
거래소의 종목을 걸었을 때).
"""
from __future__ import annotations

import asyncio

from backend.nh_api.session import create_session
from backend.realtime.feeds import Feed
from backend.realtime.hub import Hub, MarketGroup
from backend.realtime.ledger import stream_key
from backend.realtime.link import LIVE, Connection
from tests.test_realtime_link import INIT_OK, FakeConnect, FakeSocket, 기다린다

거절글 = (
    "해당 종목은 시세사용신청 후 조회 가능합니다. (HTS:9726화면 / WTS:실시간 시세신청) "
    "[action_sym::BRNZ26][미신청거래소::BRN]"
)
체결 = Feed("overseas", "quote", "BRNZ26")
호가 = Feed("overseas", "book", "BRNZ26")
다른종목 = Feed("overseas", "quote", "6EZ26")


def 거절(action_code: str | None = "FA", sym: str | None = "BRNZ26", action: str = "A") -> dict:
    data: dict = {"action": action}
    if action_code is not None:
        data["action_code"] = action_code
    if sym is not None:
        data["action_sym"] = sym
    return {"code": "RT_FAIL", "msg": 거절글, "data": data}


def 받음(action_code: str = "FA", sym: str = "BRNZ26", action: str = "A") -> dict:
    return {
        "code": "RT_INIT",
        "msg": "",
        "data": {"action": action, "action_code": action_code, "action_sym": sym},
    }


def 해외연결(connect: FakeConnect, 알림: list) -> tuple[Connection, list]:
    states: list = []
    made = Connection(
        market="overseas",
        environment="real",
        base_url="https://example.invalid",
        issue_key=lambda: "KEY-ONE-TIME",
        access_token=lambda: "TOKEN",
        on_data=lambda key, body: None,
        on_state=lambda market, state, detail: states.append((market, state)),
        on_failure=lambda: 알림.append(dict(made.failures)),
        connect=connect,
        backoff=(0.0,),
    )
    return made, states


def 해본다(feeds: list[Feed], 대본: list[dict], *, 뒤에=None) -> tuple[dict, list]:
    """구독을 걸고 서버 답을 흘려 본 뒤의 실패 기록과 알림."""

    async def 실행():
        socket = FakeSocket([INIT_OK])
        알림: list = []
        made, states = 해외연결(FakeConnect(socket), 알림)
        made.start()
        await 기다린다(lambda: ("overseas", LIVE) in states)
        for feed in feeds:
            await made.add(stream_key(feed), feed)
        for message in 대본:
            socket.push(message)
        await asyncio.sleep(0.05)
        if 뒤에 is not None:
            await 뒤에(made, socket)
        남은것 = made.failures
        # 닫을 때 기록을 지우며 한 번 더 알리므로, 그 앞까지의 알림만 봅니다.
        알린것 = list(알림)
        await made.stop()
        return 남은것, 알린것

    return asyncio.run(실행())


# ── 연결: 거절 답을 구독에 짝짓기 ────────────────────────────


def test_거절_답을_그_구독의_실패로_든다():
    남은것, 알림 = 해본다([체결, 호가], [거절("FA")])

    assert 남은것 == {stream_key(체결): ("RT_FAIL", 거절글)}
    assert 알림 == [{stream_key(체결): ("RT_FAIL", 거절글)}]


def test_체결과_호가가_각각_거절되면_둘_다_든다():
    남은것, _ = 해본다([체결, 호가], [거절("FA"), 거절("FB")])

    assert set(남은것) == {stream_key(체결), stream_key(호가)}


def test_받아들인_답은_실패로_들지_않는다():
    남은것, 알림 = 해본다([체결], [받음("FA")])

    assert 남은것 == {}
    assert 알림 == []


def test_data_가_없으면_글의_종목으로_짝짓는다():
    답 = {"code": "RT_FAIL", "msg": 거절글}

    남은것, _ = 해본다([체결, 호가, 다른종목], [답])

    # 실시간 이름을 모르니 그 종목의 구독을 전부 가리킵니다.
    assert set(남은것) == {stream_key(체결), stream_key(호가)}


def test_data_에_종목이_없고_글에만_있으면_실시간_이름과_글의_종목으로_짝짓는다():
    남은것, _ = 해본다([체결, 호가], [거절("FB", sym=None)])

    assert set(남은것) == {stream_key(호가)}


def test_어느_구독인지_모르는_제어_메시지는_기록만_남긴다(caplog):
    with caplog.at_level("WARNING"):
        남은것, 알림 = 해본다([체결], [{"code": "RT_FAIL", "msg": "까닭 모름"}])

    assert 남은것 == {}
    assert 알림 == []
    assert any("RT_FAIL" in r.getMessage() and "까닭 모름" in r.getMessage() for r in caplog.records)


def test_걸지_않은_구독의_거절은_들지_않는다():
    남은것, _ = 해본다([다른종목], [거절("FA")])

    assert 남은것 == {}


def test_해제에_대한_거절은_들지_않는다():
    남은것, _ = 해본다([체결], [거절("FA", action="D")])

    assert 남은것 == {}


def test_같은_거절이_다시_와도_한_번만_알린다():
    _, 알림 = 해본다([체결], [거절("FA"), 거절("FA")])

    assert len(알림) == 1


def test_뒤에_받아들여지면_실패를_지운다():
    남은것, 알림 = 해본다([체결], [거절("FA"), 받음("FA")])

    assert 남은것 == {}
    assert 알림[-1] == {}


def test_다시_걸면_실패를_지우고_새로_걸어_본다():
    async def 다시걸기(made, socket):
        await made.refresh(stream_key(체결))

    남은것, 알림 = 해본다([체결], [거절("FA")], 뒤에=다시걸기)

    assert 남은것 == {}
    assert 알림[-1] == {}


def test_그만_보면_실패를_지운다():
    async def 그만보기(made, socket):
        await made.remove(stream_key(체결))

    남은것, 알림 = 해본다([체결, 호가], [거절("FA")], 뒤에=그만보기)

    assert 남은것 == {}
    assert 알림[-1] == {}


def test_다른_종목의_받아들임_답은_실패를_지우지_않는다():
    """이 연결에 없는 구독(막 내린 구독의 늦은 답 등)의 `RT_INIT` 입니다."""
    남은것, 알림 = 해본다([체결], [거절("FA"), 받음("FA", sym="6EZ26")])

    assert 남은것 == {stream_key(체결): ("RT_FAIL", 거절글)}
    assert len(알림) == 1


def test_국내_짝_코드의_받아들임_답은_실패를_지우지_않는다():
    """국내 체결은 선언하지 않은 야간 짝(`KC`)도 함께 등록되어 그 `RT_INIT` 이 늘 옵니다."""
    주간 = Feed("domestic-day", "quote", "A016C000")
    다른 = Feed("domestic-day", "quote", "A0169000")
    글 = "거절 [action_sym::A0169000]"

    async def 실행():
        socket = FakeSocket([INIT_OK])
        알림: list = []
        states: list = []
        made = Connection(
            market="domestic",
            environment="real",
            base_url="https://example.invalid",
            issue_key=lambda: "KEY-ONE-TIME",
            access_token=lambda: "TOKEN",
            on_data=lambda key, body: None,
            on_state=lambda market, state, detail: states.append((market, state)),
            on_failure=lambda: 알림.append(dict(made.failures)),
            connect=FakeConnect(socket),
            backoff=(0.0,),
        )
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        for feed in (주간, 다른):
            await made.add(stream_key(feed), feed)
        socket.push({"code": "RT_FAIL", "msg": 글,
                     "data": {"action": "A", "action_code": "KA", "action_sym": "A0169000"}})
        socket.push(받음("KC", sym="A016C000"))
        await asyncio.sleep(0.05)
        남은것 = made.failures
        알린것 = list(알림)
        await made.stop()
        return 남은것, 알린것

    남은것, 알림 = asyncio.run(실행())

    assert 남은것 == {stream_key(다른): ("RT_FAIL", 글)}
    assert len(알림) == 1


def test_글로_짝지은_여러_구독의_실패를_한꺼번에_지운다():
    """종목만으로 짝지은 실패 둘이 그 종목의 받아들임 답 하나로 함께 풀립니다."""
    남은것, 알림 = 해본다(
        [체결, 호가],
        [{"code": "RT_FAIL", "msg": 거절글}, {"code": "RT_INIT", "msg": "[action_sym::BRNZ26]"}],
    )

    assert 남은것 == {}
    assert 알림[-1] == {}


def test_다시_붙으면_실패를_지우고_전부_새로_건다():
    async def 실행():
        첫소켓 = FakeSocket([INIT_OK])
        둘째소켓 = FakeSocket([INIT_OK])
        알림: list = []
        made, states = 해외연결(FakeConnect(첫소켓, 둘째소켓), 알림)
        made.start()
        await 기다린다(lambda: ("overseas", LIVE) in states)
        await made.add(stream_key(체결), 체결)
        첫소켓.push(거절("FA"))
        await 기다린다(lambda: bool(made.failures))
        첫소켓.push(None)  # 서버가 닫습니다.
        await 기다린다(lambda: any(m["body"].get("action_sym") == "BRNZ26" for m in 둘째소켓.sent))
        남은것 = made.failures
        await made.stop()
        return 남은것, 알림

    남은것, 알림 = asyncio.run(실행())

    assert 남은것 == {}
    assert 알림 == [{stream_key(체결): ("RT_FAIL", 거절글)}, {}]


# ── 허브: 화면에 알리기 ─────────────────────────────────────


def 허브와_소켓() -> tuple[Hub, FakeSocket]:
    socket = FakeSocket([INIT_OK])
    engine = Hub(
        session=create_session(replay=True),
        environment="real",
        flush_interval=0.01,
        session_clock=False,
    )

    def 연결묶음(market: str) -> MarketGroup:
        def make_link() -> Connection:
            return Connection(
                market=market,
                environment="real",
                base_url="https://example.invalid",
                issue_key=lambda: "KEY-ONE-TIME",
                access_token=lambda: "TOKEN",
                on_data=engine._on_data,
                on_state=engine._on_state,
                on_failure=engine._on_failure,
                connect=FakeConnect(socket),
                backoff=(0.0,),
            )

        return MarketGroup(market, capacity=20, make_link=make_link)

    engine._group = 연결묶음  # type: ignore[method-assign]
    return engine, socket


def 구독답(client) -> list[dict]:
    made = []
    while not client.queue.empty():
        message = client.queue.get_nowait()
        if message["type"] == "subscriptions":
            made.append(message)
    return made


def test_허브가_거절된_구독을_failed_와_rejected_로_다시_답한다():
    async def 실행():
        engine, socket = 허브와_소켓()
        client = engine.attach("screen")
        await engine.declare("screen", {체결: 1, 다른종목: 1})
        await 기다린다(lambda: len(socket.sent) >= 3)  # 초기화 + 구독 둘
        처음 = 구독답(client)
        socket.push(거절("FA"))
        await 기다린다(lambda: not client.queue.empty())
        뒤 = 구독답(client)
        await engine.stop()
        return 처음, 뒤

    처음, 뒤 = asyncio.run(실행())

    assert 처음[-1]["failed"] == []
    assert len(처음[-1]["granted"]) == 2
    assert 뒤 == [
        {
            "type": "subscriptions",
            "granted": [다른종목.as_dict()],
            "rejected": [체결.as_dict()],
            "failed": [{**체결.as_dict(), "code": "RT_FAIL", "message": 거절글}],
        }
    ]


def test_허브는_받아들인_답에는_다시_답하지_않는다():
    async def 실행():
        engine, socket = 허브와_소켓()
        client = engine.attach("screen")
        await engine.declare("screen", {체결: 1})
        await 기다린다(lambda: len(socket.sent) >= 2)
        구독답(client)
        socket.push(받음("FA"))
        await asyncio.sleep(0.05)
        뒤 = 구독답(client)
        await engine.stop()
        return 뒤

    assert asyncio.run(실행()) == []


def test_실패는_그_구독을_선언한_화면에만_실린다():
    async def 실행():
        engine, socket = 허브와_소켓()
        보는쪽 = engine.attach("brent")
        다른쪽 = engine.attach("euro")
        await engine.declare("brent", {체결: 1})
        await engine.declare("euro", {다른종목: 1})
        await 기다린다(lambda: len(socket.sent) >= 3)
        구독답(보는쪽)
        구독답(다른쪽)
        socket.push(거절("FA"))
        await 기다린다(lambda: not 다른쪽.queue.empty())
        답 = (구독답(보는쪽)[-1], 구독답(다른쪽)[-1])
        await engine.stop()
        return 답

    보는쪽, 다른쪽 = asyncio.run(실행())

    assert [f["sym"] for f in 보는쪽["failed"]] == ["BRNZ26"]
    assert 보는쪽["granted"] == []
    assert 다른쪽["failed"] == []
    assert 다른쪽["granted"] == [다른종목.as_dict()]


def test_실패한_구독을_다른_구독으로_바꿔_선언해도_새_구독이_밀렸다는_답은_안_나간다():
    """구독을 맞추는 도중 옛 구독 목록으로 답하면 펌프가 새 실행을 「한도 초과」로 내립니다."""

    async def 실행():
        engine, socket = 허브와_소켓()
        client = engine.attach("screen")
        await engine.declare("screen", {체결: 1})
        await 기다린다(lambda: len(socket.sent) >= 2)
        구독답(client)
        socket.push(거절("FA"))
        await 기다린다(lambda: not client.queue.empty())
        구독답(client)
        await engine.declare("screen", {다른종목: 1})
        await asyncio.sleep(0.05)
        답 = 구독답(client)
        await engine.stop()
        return 답

    답 = asyncio.run(실행())

    assert [m for m in 답 if 다른종목.as_dict() in m["rejected"]] == [], 답
    assert 답[-1]["granted"] == [다른종목.as_dict()]
    assert 답[-1]["failed"] == []


def test_다시_걸어_실패가_풀리면_한_번_답하고_아무것도_안_바뀌면_답하지_않는다():
    async def 실행():
        engine, socket = 허브와_소켓()
        client = engine.attach("screen")
        await engine.declare("screen", {체결: 1, 다른종목: 1})
        await 기다린다(lambda: len(socket.sent) >= 3)
        구독답(client)
        await engine.refresh([다른종목])
        그대로 = 구독답(client)
        socket.push(거절("FA"))
        await 기다린다(lambda: not client.queue.empty())
        구독답(client)
        await engine.refresh([체결])
        풀린뒤 = 구독답(client)
        await engine.stop()
        return 그대로, 풀린뒤

    그대로, 풀린뒤 = asyncio.run(실행())

    assert 그대로 == []
    assert len(풀린뒤) == 1
    assert 풀린뒤[0]["failed"] == []
    assert 풀린뒤[0]["rejected"] == []
