"""NH선물 실시간 연결 — 세션 초기화, Ping-Pong, 구독, 재접속."""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.realtime import link as link_module
from backend.realtime.feeds import Feed
from backend.realtime.ledger import stream_key
from backend.realtime.link import LIVE, RECONNECTING, Connection, api_id_of, subscribe_message

QUOTE = Feed("domestic-day", "quote", "A7569000")
ORDERS = Feed("domestic-day", "orders")

INIT_OK = {"code": "INIT", "msg": "INIT_SUCCESS"}
PINGPONG = {"code": "pingpong", "msg": "pingpong"}


def 자료(price: str = "100") -> dict:
    return {
        "header": {"action_code": "KA", "action_sym": "A7569000"},
        "body": {"tick_div": "1", "last_pric": price, "exec_qty": "1"},
    }


class FakeSocket:
    """대본대로 답하는 웹소켓."""

    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.inbound: asyncio.Queue = asyncio.Queue()
        for message in inbound or []:
            self.inbound.put_nowait(message)
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        return json.dumps(await self.inbound.get())

    def __aiter__(self) -> FakeSocket:
        return self

    async def __anext__(self) -> str:
        message = await self.inbound.get()
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)

    async def close(self) -> None:
        self.closed = True

    def push(self, message: dict | None) -> None:
        self.inbound.put_nowait(message)


class FakeConnect:
    """`websockets.connect` 자리에 끼웁니다."""

    def __init__(self, *sockets: FakeSocket) -> None:
        self.sockets = list(sockets)
        self.urls: list[str] = []
        self.options: list[dict] = []

    def __call__(self, url: str, **options: object) -> "FakeConnect._Session":
        self.urls.append(url)
        self.options.append(dict(options))
        # 대본이 떨어지면 아무것도 오지 않는 연결을 내줍니다. 재접속이
        # 그 자리에서 조용히 기다리고, 테스트가 끝없이 돌지 않습니다.
        socket = self.sockets.pop(0) if self.sockets else FakeSocket()
        return FakeConnect._Session(socket)

    class _Session:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_: object) -> None:
            await self.socket.close()


def 연결(connect: FakeConnect, **kwargs) -> tuple[Connection, list, list]:
    data: list = []
    states: list = []
    made = Connection(
        market="domestic",
        environment="paper",
        base_url="https://example.invalid",
        issue_key=lambda: "KEY-ONE-TIME",
        access_token=lambda: "TOKEN",
        on_data=lambda key, body: data.append((key, body)),
        on_state=lambda market, state, detail: states.append((market, state)),
        connect=connect,
        backoff=kwargs.pop("backoff", (0.0,)),
        **kwargs,
    )
    return made, data, states


async def 기다린다(check, limit: float = 2.0) -> None:
    """조건이 참이 될 때까지. 안 되면 시간이 지나 실패합니다."""
    deadline = asyncio.get_running_loop().time() + limit
    while asyncio.get_running_loop().time() < deadline:
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("기다리던 일이 일어나지 않았습니다.")


# ── 이름 가르기 ──────────────────────────────────────────────


def test_국내와_해외의_주문체결을_계좌로_가른다():
    # 둘 다 메시지에는 `O1` 로 옵니다. 계좌가 갈라 줘야 정해집니다.
    assert api_id_of("domestic", "O1") == "O1_K"
    assert api_id_of("overseas", "O1") == "O1"
    assert api_id_of("domestic", "KA") == "KA"
    assert api_id_of("domestic", "없는것") is None


def test_구독_메시지_모양():
    assert subscribe_message(QUOTE, action="A") == {
        "header": {"api_ver": "1", "action": "A"},
        "body": {"action_code": "KA", "action_sym": "A7569000"},
    }


def test_주문알림_구독에는_종목_칸이_없다():
    made = subscribe_message(ORDERS, action="A")
    assert made["body"] == {"action_code": "O1"}
    assert "action_sym" not in made["body"]


def test_한_연결이_지는_구독_수를_바꿀_수_있다():
    assert link_module.per_connection_limit({}) == 20
    assert link_module.per_connection_limit({"NH_STREAM_PER_CONNECTION": "1"}) == 1
    # 0 이나 음수를 넣어도 최소 하나는 걸 수 있어야 합니다.
    assert link_module.per_connection_limit({"NH_STREAM_PER_CONNECTION": "0"}) == 1
    # 숫자가 아니면 기본값으로 돌아갑니다.
    assert link_module.per_connection_limit({"NH_STREAM_PER_CONNECTION": "많이"}) == 20


# ── 연결 ────────────────────────────────────────────────────


def test_세션을_접근토큰으로_열고_접속키는_주소에만_붙인다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        connect = FakeConnect(socket)
        made, _, states = 연결(connect)
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.stop()
        return socket, connect

    socket, connect = asyncio.run(실행())

    init = socket.sent[0]
    assert init["body"]["action_code"] == "session_init"
    assert init["body"]["session_token"] == "TOKEN"
    assert init["header"] == {"api_ver": "1", "action": "0"}

    # 접속키는 주소에만 있고, 주소는 `wss` 로 바뀝니다.
    assert connect.urls[0].startswith("wss://example.invalid/trade/ws-stream?access_key=")
    assert "KEY-ONE-TIME" not in json.dumps(socket.sent)


def test_초기화를_기다리는_동안_온_핑퐁도_되돌린다():
    async def 실행():
        socket = FakeSocket([PINGPONG, INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.stop()
        return socket

    socket = asyncio.run(실행())
    assert PINGPONG in socket.sent


def test_받는_동안_온_핑퐁을_되돌린다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        socket.push(PINGPONG)
        await 기다린다(lambda: PINGPONG in socket.sent)
        await made.stop()
        return socket

    assert PINGPONG in asyncio.run(실행()).sent


def test_구독을_걸면_자료가_들어온다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, data, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.add(stream_key(QUOTE), QUOTE)
        socket.push(자료("101"))
        await 기다린다(lambda: bool(data))
        await made.stop()
        return socket, data

    socket, data = asyncio.run(실행())

    assert socket.sent[1] == subscribe_message(QUOTE, action="A")
    key, body = data[0]
    assert key == stream_key(QUOTE)
    assert body["last_pric"] == "101"


def test_웹소켓_핑_프레임을_보내지_않는다():
    """라이브러리 기본 핑(20초)을 국내 서버가 받으면 연결을 닫습니다 — 세션은 pingpong 되돌림으로."""

    async def 실행():
        connect = FakeConnect(FakeSocket([INIT_OK]))
        made, _, states = 연결(connect)
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.stop()
        return connect.options

    (옵션,) = asyncio.run(실행())
    assert 옵션["ping_interval"] is None
    assert 옵션["ping_timeout"] is None


def test_pingpong_은_대소문자를_가리지_않고_받은_그대로_되돌린다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        socket.push({"code": "PINGPONG", "msg": "PINGPONG"})
        await 기다린다(lambda: len(socket.sent) >= 2)
        await made.stop()
        return socket.sent

    보낸것 = asyncio.run(실행())
    assert {"code": "PINGPONG", "msg": "PINGPONG"} in 보낸것


def test_서버가_한동안_조용하면_죽은_연결로_보고_다시_붙는다():
    """핑 프레임을 안 보내므로 끊긴 줄을 이 감시로 압니다."""

    async def 실행():
        first = FakeSocket([INIT_OK])
        second = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(first, second), idle_timeout=0.05)
        made.start()
        await 기다린다(lambda: states.count(("domestic", LIVE)) >= 2)
        await made.stop()
        return states, first

    states, first = asyncio.run(실행())
    assert ("domestic", RECONNECTING) in states
    assert first.closed


def test_서버가_닫으면_닫힘_코드를_기록에_남긴다(caplog):
    async def 실행():
        socket = FakeSocket([INIT_OK])
        socket.close_code = 1000
        socket.close_reason = "bye"
        made, _, states = 연결(FakeConnect(socket, FakeSocket([INIT_OK])))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        socket.push(None)
        await 기다린다(lambda: ("domestic", RECONNECTING) in states)
        await made.stop()

    with caplog.at_level("WARNING"):
        asyncio.run(실행())
    남은것 = [r.getMessage() for r in caplog.records]
    assert any("서버가 닫았습니다" in 문구 and "1000" in 문구 and "bye" in 문구 for 문구 in 남은것), 남은것


def test_걸지_않은_구독의_자료는_버린다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, data, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        socket.push(자료())
        await asyncio.sleep(0.05)
        await made.stop()
        return data

    assert asyncio.run(실행()) == []


def test_해제하면_해제_메시지를_보낸다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.add(stream_key(QUOTE), QUOTE)
        await made.remove(stream_key(QUOTE))
        await made.stop()
        return socket

    socket = asyncio.run(실행())
    assert subscribe_message(QUOTE, action="D") in socket.sent


# ── 재접속 ──────────────────────────────────────────────────


def test_끊기면_새_키로_다시_붙고_구독을_다시_건다():
    async def 실행():
        first = FakeSocket([INIT_OK])
        second = FakeSocket([INIT_OK])
        connect = FakeConnect(first, second)
        made, _, states = 연결(connect)
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.add(stream_key(QUOTE), QUOTE)

        # 서버가 끊었습니다.
        first.push(None)
        await 기다린다(lambda: len(connect.urls) >= 2)
        await 기다린다(lambda: len(second.sent) >= 2)
        await made.stop()
        return connect, second, states

    connect, second, states = asyncio.run(실행())

    # 연결마다 접속키를 새로 받습니다.
    assert len(connect.urls) >= 2
    # 서버는 무엇을 보고 있었는지 기억하지 않으므로 다시 겁니다.
    assert subscribe_message(QUOTE, action="A") in second.sent
    assert [state for _, state in states].count(LIVE) >= 2


def test_초기화가_거부되면_다시_붙는다():
    async def 실행():
        거부 = FakeSocket([{"code": "INIT", "msg": "INIT_FAIL"}])
        정상 = FakeSocket([INIT_OK])
        connect = FakeConnect(거부, 정상)
        made, _, states = 연결(connect)
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.stop()
        return connect

    assert len(asyncio.run(실행()).urls) >= 2


def test_붙기_전에_건_구독도_붙을_때_함께_걸린다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        # 아직 안 붙었는데 구독을 걸었습니다. 보낼 곳이 없어도 장부에는 남고,
        # 붙는 순간 함께 걸려야 합니다.
        await made.add(stream_key(QUOTE), QUOTE)
        assert socket.sent == []

        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await 기다린다(lambda: len(socket.sent) >= 2)
        await made.stop()
        return socket

    assert subscribe_message(QUOTE, action="A") in asyncio.run(실행()).sent


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://api.example.invalid", "wss://api.example.invalid"),
        ("http://localhost:8000", "ws://localhost:8000"),
        ("wss://already.invalid", "wss://already.invalid"),
    ],
)
def test_접속_주소를_웹소켓_주소로_바꾼다(base, expected):
    assert link_module._ws_base(base) == expected


# ── 짝 함께 등록 ────────────────────────────────────────────
#
# 국내 체결·호가는 같은 종목의 주간·야간이 서버에서 한 등록으로 묶여, 한쪽을
# 해제하면 짝도 조용히 끊기고 남은 쪽만 다시 걸어서는 돌아오지 않습니다.
# 그래서 연결은 짝을 늘 함께 등록하고, 둘 다 필요 없을 때만 함께 해제합니다.

종목 = "A056A000"
주간체결 = Feed("domestic-day", "quote", 종목)
주간호가 = Feed("domestic-day", "book", 종목)
야간체결 = Feed("domestic-night", "quote", 종목)
야간호가 = Feed("domestic-night", "book", 종목)
해외체결 = Feed("overseas", "quote", "ESZ26")
해외호가 = Feed("overseas", "book", "ESZ26")
주문알림 = Feed("domestic-night", "orders")


def 해제(feed: Feed) -> dict:
    return subscribe_message(feed, action="D")


def 구독(feed: Feed) -> dict:
    return subscribe_message(feed, action="A")


def 걸고_해본다(걸것: list[Feed], 할일) -> tuple[list[dict], frozenset]:
    """붙은 연결에 구독을 걸고 `할일` 을 한 뒤, 그 사이에 보낸 것과 남은 구독을 냅니다."""

    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        for feed in 걸것:
            await made.add(stream_key(feed), feed)
        앞 = len(socket.sent)
        await 할일(made)
        보낸것 = socket.sent[앞:]
        남은것 = made.keys
        await made.stop()
        return 보낸것, 남은것

    return asyncio.run(실행())


@pytest.mark.parametrize(("거는것", "짝"), [(주간체결, 야간체결), (야간호가, 주간호가)])
def test_한쪽만_걸어도_짝을_함께_등록한다(거는것, 짝):
    보낸것, 남은것 = 걸고_해본다([], lambda made: made.add(stream_key(거는것), 거는것))

    assert 보낸것 == [구독(거는것), 구독(짝)]
    # 걸어 달라고 한 것은 하나뿐입니다. 짝은 서버에만 등록됩니다.
    assert 남은것 == frozenset({stream_key(거는것)})


def test_짝이_이미_등록돼_있으면_걸어도_아무것도_보내지_않는다():
    보낸것, 남은것 = 걸고_해본다([주간체결], lambda made: made.add(stream_key(야간체결), 야간체결))

    assert 보낸것 == []
    assert 남은것 == frozenset({stream_key(주간체결), stream_key(야간체결)})


@pytest.mark.parametrize(
    ("푸는것", "짝"),
    [
        (주간호가, 야간호가),
        (야간호가, 주간호가),
        (주간체결, 야간체결),
        (야간체결, 주간체결),
    ],
)
def test_짝이_아직_필요하면_해제를_보내지_않는다(푸는것, 짝):
    보낸것, 남은것 = 걸고_해본다([푸는것, 짝], lambda made: made.remove(stream_key(푸는것)))

    assert 보낸것 == []
    assert 남은것 == frozenset({stream_key(짝)})


@pytest.mark.parametrize(("거는것", "짝"), [(주간호가, 야간호가), (야간체결, 주간체결)])
def test_짝_둘_다_필요_없어지면_둘_다_해제한다(거는것, 짝):
    보낸것, 남은것 = 걸고_해본다([거는것], lambda made: made.remove(stream_key(거는것)))

    assert 보낸것 == [해제(거는것), 해제(짝)]
    assert 남은것 == frozenset()


def test_짝을_하나씩_풀면_마지막에_둘_다_해제한다():
    async def 둘_다_푼다(made):
        await made.remove(stream_key(야간체결))
        await made.remove(stream_key(주간체결))

    보낸것, 남은것 = 걸고_해본다([주간체결, 야간체결], 둘_다_푼다)

    assert 보낸것 == [해제(주간체결), 해제(야간체결)]
    assert 남은것 == frozenset()


def test_해제한_뒤_다시_필요해지면_짝_둘_다_다시_등록한다():
    async def 풀었다_다시_건다(made):
        await made.remove(stream_key(주간체결))
        await made.add(stream_key(주간체결), 주간체결)

    보낸것, 남은것 = 걸고_해본다([주간체결], 풀었다_다시_건다)

    assert 보낸것 == [해제(주간체결), 해제(야간체결), 구독(주간체결), 구독(야간체결)]
    assert 남은것 == frozenset({stream_key(주간체결)})


def test_종류가_다른_구독은_짝이_아니다():
    # 주간 호가를 풀어도 주간 체결과 그 짝은 그대로입니다.
    보낸것, 남은것 = 걸고_해본다([주간체결, 주간호가], lambda made: made.remove(stream_key(주간호가)))

    assert 보낸것 == [해제(주간호가), 해제(야간호가)]
    assert 남은것 == frozenset({stream_key(주간체결)})


def test_해외와_주문알림은_전처럼_하나씩_걸고_푼다():
    보낸것, _ = 걸고_해본다([], lambda made: made.add(stream_key(해외체결), 해외체결))
    assert 보낸것 == [구독(해외체결)]

    보낸것, _ = 걸고_해본다([해외체결, 해외호가], lambda made: made.remove(stream_key(해외체결)))
    assert 보낸것 == [해제(해외체결)]

    보낸것, _ = 걸고_해본다([], lambda made: made.add(stream_key(주문알림), 주문알림))
    assert 보낸것 == [구독(주문알림)]

    보낸것, _ = 걸고_해본다([주문알림, 야간호가], lambda made: made.remove(stream_key(주문알림)))
    assert 보낸것 == [해제(주문알림)]


def test_다른_종목의_구독은_건드리지_않는다():
    다른야간호가 = Feed("domestic-night", "book", "A016C000")
    보낸것, 남은것 = 걸고_해본다(
        [주간호가, 다른야간호가], lambda made: made.remove(stream_key(주간호가))
    )

    assert 보낸것 == [해제(주간호가), 해제(야간호가)]
    assert 남은것 == frozenset({stream_key(다른야간호가)})


def test_짝으로만_등록한_구독의_자료는_버린다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, data, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.add(stream_key(주간체결), 주간체결)
        socket.push({"header": {"action_code": "KC", "action_sym": 종목}, "body": {"last_pric": "1"}})
        socket.push({"header": {"action_code": "KA", "action_sym": 종목}, "body": {"last_pric": "2"}})
        await 기다린다(lambda: bool(data))
        await asyncio.sleep(0.05)
        await made.stop()
        return data

    data = asyncio.run(실행())
    assert [(key, body["last_pric"]) for key, body in data] == [(stream_key(주간체결), "2")]


def test_다시_붙으면_짝도_함께_건다():
    async def 실행():
        first = FakeSocket([INIT_OK])
        second = FakeSocket([INIT_OK])
        connect = FakeConnect(first, second)
        made, _, states = 연결(connect)
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.add(stream_key(주간체결), 주간체결)
        first.push(None)
        await 기다린다(lambda: len(second.sent) >= 3)
        await made.stop()
        return second

    second = asyncio.run(실행())
    assert second.sent[1:3] == [구독(주간체결), 구독(야간체결)]


def test_닫을_때는_짝까지_해제한다():
    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await made.add(stream_key(주간호가), 주간호가)
        앞 = len(socket.sent)
        await made.stop()
        return socket.sent[앞:]

    assert asyncio.run(실행()) == [해제(주간호가), 해제(야간호가)]


def test_등록은_짝까지_센다():
    async def 실행():
        made, _, _ = 연결(FakeConnect())
        await made.add(stream_key(주간체결), 주간체결)
        await made.add(stream_key(해외체결), 해외체결)
        return made.keys, made.registered, len(made)

    keys, registered, count = asyncio.run(실행())
    assert keys == frozenset({stream_key(주간체결), stream_key(해외체결)})
    assert registered == keys | {stream_key(야간체결)}
    # 연결이 지는 구독 수(자리 셈)는 걸어 달라고 한 것만 셉니다.
    assert count == 2


def test_끊겨_있는_동안의_해제는_아무것도_보내지_않는다():
    async def 실행():
        socket = FakeSocket()  # 초기화 답을 보내지 않아 붙지 않은 채입니다.
        made, _, _ = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: len(socket.sent) >= 1)  # 세션 초기화만 나갔습니다.
        await made.add(stream_key(주간호가), 주간호가)
        await made.add(stream_key(야간호가), 야간호가)
        await made.remove(stream_key(주간호가))
        보낸것 = list(socket.sent)
        남은것 = made.keys
        await made.stop()
        return 보낸것, 남은것

    보낸것, 남은것 = asyncio.run(실행())

    assert [m["header"]["action"] for m in 보낸것] == [link_module.ACTION_INIT]
    # 붙을 때 남은 구독이 짝과 함께 걸립니다(`_session`).
    assert 남은것 == frozenset({stream_key(야간호가)})


def test_다시_걸기는_해제하고_구독한_뒤_짝도_다시_건다():
    보낸것, 남은것 = 걸고_해본다(
        [주간호가, 야간호가], lambda made: made.refresh(stream_key(야간호가))
    )

    assert 보낸것 == [해제(야간호가), 구독(야간호가), 구독(주간호가)]
    # 구독 목록은 그대로입니다 — 새 자리를 쓰지 않습니다.
    assert 남은것 == frozenset({stream_key(주간호가), stream_key(야간호가)})


def test_짝으로만_등록한_것도_다시_걸기에서_다시_건다():
    보낸것, 남은것 = 걸고_해본다([주간체결], lambda made: made.refresh(stream_key(주간체결)))

    assert 보낸것 == [해제(주간체결), 구독(주간체결), 구독(야간체결)]
    assert 남은것 == frozenset({stream_key(주간체결)})


def test_걸려_있지_않은_구독의_다시_걸기는_할_일이_없다():
    보낸것, 남은것 = 걸고_해본다([주간호가], lambda made: made.refresh(stream_key(야간호가)))

    assert 보낸것 == []
    assert 남은것 == frozenset({stream_key(주간호가)})


def test_끊겨_있는_동안의_다시_걸기는_아무것도_보내지_않는다():
    async def 실행():
        socket = FakeSocket()  # 초기화 답을 보내지 않아 붙지 않은 채입니다.
        made, _, _ = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: len(socket.sent) >= 1)
        await made.add(stream_key(주간호가), 주간호가)
        await made.add(stream_key(야간호가), 야간호가)
        await made.refresh(stream_key(야간호가))
        보낸것 = list(socket.sent)
        남은것 = made.keys
        await made.stop()
        return 보낸것, 남은것

    보낸것, 남은것 = asyncio.run(실행())

    assert [m["header"]["action"] for m in 보낸것] == [link_module.ACTION_INIT]
    assert 남은것 == frozenset({stream_key(주간호가), stream_key(야간호가)})


# ── 서버의 구독 답 ──────────────────────────────────────────


def test_구독_답을_어느_요청의_답인지와_함께_기록에_남긴다(caplog):
    답 = {
        "code": "RT_INIT",
        "data": {"action": "A", "action_code": "KC", "action_sym": 종목},
        "msg": "",
    }

    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        made.start()
        await 기다린다(lambda: ("domestic", LIVE) in states)
        socket.push(답)
        socket.push({"code": "ZZ999", "msg": "모르는 답"})
        await asyncio.sleep(0.05)
        await made.stop()

    with caplog.at_level("WARNING"):
        asyncio.run(실행())
    남은것 = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("RT_INIT" in 문구 and "code=KC" in 문구 and 종목 in 문구 for 문구 in 남은것), 남은것
    assert any("ZZ999" in 문구 and "모르는 답" in 문구 for 문구 in 남은것), 남은것


def test_주간에서_야간으로_바꿔_선언해도_서버에는_아무것도_안_나간다():
    from backend.realtime.hub import MarketGroup

    async def 실행():
        socket = FakeSocket([INIT_OK])
        made, _, states = 연결(FakeConnect(socket))
        group = MarketGroup("domestic", capacity=20, make_link=lambda: made)
        await group.apply({stream_key(주간체결): 주간체결})
        await 기다린다(lambda: ("domestic", LIVE) in states)
        await 기다린다(lambda: len(socket.sent) >= 3)
        앞 = len(socket.sent)
        await group.apply({stream_key(야간체결): 야간체결})
        보낸것 = socket.sent[앞:]
        처음 = socket.sent[1:앞]
        남은것 = made.keys
        await group.stop()
        return 처음, 보낸것, 남은것

    처음, 보낸것, 남은것 = asyncio.run(실행())
    assert 처음 == [구독(주간체결), 구독(야간체결)]
    assert 보낸것 == []
    assert 남은것 == frozenset({stream_key(야간체결)})


# ── 다시 붙는 간격 ──────────────────────────────────────────


class 가짜시계:
    """시간을 실제로 흘려보내지 않고 기다린 값만 적습니다."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


def 간격_연결(connect: FakeConnect, 시계: 가짜시계) -> tuple[Connection, list]:
    made, _, states = 연결(
        connect,
        backoff=link_module.BACKOFF,
        clock=시계,
        sleep=시계.sleep,
    )
    return made, states


def test_기본_간격은_1초부터_60초까지():
    assert link_module.BACKOFF == (0.0, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
    assert link_module.SETTLED_AFTER == 60.0
    assert link_module.UNSETTLED_WINDOW == 600.0


def test_서버가_짧은_주기로_정상_닫힘을_보내면_간격이_단계적으로_벌어져_상한에_닿는다(caplog):
    """1.2초마다 code=1000 으로 닫혀도 쉬지 않고 다시 붙지 않습니다."""

    async def 실행():
        시계 = 가짜시계()
        sockets = [FakeSocket([INIT_OK]) for _ in range(10)]
        for socket in sockets:
            socket.close_code = 1000
            socket.close_reason = ""
        # 열한 번째 접속도 초기화 답을 받아 붙은 채로 멈춥니다.
        connect = FakeConnect(*sockets, FakeSocket([INIT_OK]))
        made, _ = 간격_연결(connect, 시계)
        made.start()
        for 차례, socket in enumerate(sockets):
            await 기다린다(lambda: len(connect.urls) == 차례 + 1 and made.state == LIVE)
            시계.now += 1.2
            socket.push(None)
            await 기다린다(lambda: len(시계.waits) == 차례 + 1)
        await 기다린다(lambda: len(connect.urls) == 11 and made.state == LIVE)
        await made.stop()
        return 시계.waits, connect.urls

    with caplog.at_level("WARNING"):
        waits, urls = asyncio.run(실행())
    assert waits == [1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 60.0, 60.0, 60.0, 60.0]
    # 닫힌 열 번 뒤에 다시 붙은 것까지 열한 번만 붙었습니다.
    assert len(urls) == 11
    남은것 = [r.getMessage() for r in caplog.records if "서버가 닫았습니다" in r.getMessage()]
    assert len(남은것) == 10
    assert "1.2초 동안 붙어 있었고 1초 뒤 다시 붙습니다" in 남은것[0]
    assert "1.2초 동안 붙어 있었고 60초 뒤 다시 붙습니다" in 남은것[-1]


def test_오래_붙어_있다가_정상으로_닫히면_바로_다시_붙는다(caplog):
    async def 실행():
        시계 = 가짜시계()
        first = FakeSocket([INIT_OK])
        first.close_code = 1000
        first.close_reason = "bye"
        connect = FakeConnect(first, FakeSocket([INIT_OK]))
        made, _ = 간격_연결(connect, 시계)
        made.start()
        await 기다린다(lambda: made.state == LIVE)
        시계.now += 61.0
        first.push(None)
        await 기다린다(lambda: len(connect.urls) == 2 and made.state == LIVE)
        await made.stop()
        return 시계.waits

    with caplog.at_level("WARNING"):
        assert asyncio.run(실행()) == []
    assert "61.0초 동안 붙어 있었고 0초 뒤 다시 붙습니다" in caplog.text


def test_우리가_닫으면_닫았다고_남기고_다시_붙지_않는다(caplog):
    """이 앱이 닫아도 정상 닫힘(code=1000)으로 끝나므로 서버가 닫은 것으로 적히면 안 됩니다."""

    class 닫히면_끝나는_소켓(FakeSocket):
        async def close(self) -> None:
            self.closed = True
            self.close_code = 1000
            self.close_reason = ""
            self.push(None)

    async def 실행():
        socket = 닫히면_끝나는_소켓([INIT_OK])
        connect = FakeConnect(socket, FakeSocket([INIT_OK]))
        made, _, states = 연결(connect)
        made.start()
        await 기다린다(lambda: made.state == LIVE)
        await made.stop()
        await asyncio.sleep(0.05)
        return connect.urls, states

    with caplog.at_level("INFO"):
        urls, states = asyncio.run(실행())
    assert len(urls) == 1
    assert ("domestic", RECONNECTING) not in states
    # 로깅 설정이 없을 때의 기본 수준(WARNING)에서도 남도록 WARNING 으로 적습니다.
    닫음 = [r for r in caplog.records if "실시간 연결을 닫았습니다" in r.getMessage()]
    assert [r.levelname for r in 닫음] == ["WARNING"]
    assert "서버가 닫았습니다" not in caplog.text
    assert "다시 붙습니다" not in caplog.text


def test_짧게_끊긴_횟수는_최근_10분_것만_센다():
    pacer = link_module.Pacer()
    assert pacer.after(now=10.0, lasted=1.0, failed=False) == 1.0
    assert pacer.after(now=20.0, lasted=1.0, failed=False) == 2.0
    # 10분 넘게 붙어 있었으면 앞의 짧은 끊김은 범위 밖이라 바로 다시 붙습니다.
    assert pacer.after(now=700.0, lasted=680.0, failed=False) == 0.0


def test_오래_붙어_있었어도_앞의_짧은_끊김이_10분_안이면_간격을_줄이지_않는다():
    pacer = link_module.Pacer()
    assert pacer.after(now=10.0, lasted=1.0, failed=False) == 1.0
    assert pacer.after(now=20.0, lasted=1.0, failed=False) == 2.0
    assert pacer.after(now=100.0, lasted=79.0, failed=False) == 2.0


def test_오류로_끊기면_오래_붙어_있었어도_한_번으로_센다():
    pacer = link_module.Pacer()
    assert pacer.after(now=3600.0, lasted=3600.0, failed=True) == 1.0
