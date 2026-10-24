"""`/api/stream` 과 허브 — 저장해 둔 실시간 자료로 화면까지 흘려보냅니다.

웹소켓을 열려면 `TestClient` 를 `with` 로 감싸야 하는데, 앱 전체를 그렇게 열면
기동 절차가 돌면서 종목 마스터를 실제로 내려받으러 나갑니다. 그래서 여기서는
**이 라우터만 얹은 앱**을 따로 세웁니다. 라우터가 앱에 붙어 있는지는 마지막
시험이 따로 봅니다.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.nh_api.session import create_session
from backend.realtime.feeds import Feed
from backend.realtime.hub import Hub, wishes_of
from backend.realtime.link import CONNECTING, LIVE, RECONNECTING, STOPPED
from backend.realtime.realtime_routes import get_hub, router


def 허브(**kwargs) -> Hub:
    """저장해 둔 자료로 도는 허브. 기다리지 않고 바로 흘려보냅니다."""
    kwargs.setdefault("flush_interval", 0.01)
    kwargs.setdefault("replay_speed", 0.0)
    kwargs.setdefault("session_clock", False)
    return Hub(session=create_session(replay=True), environment="real", **kwargs)


def 앱(engine: Hub) -> FastAPI:
    made = FastAPI()
    made.include_router(router)
    made.dependency_overrides[get_hub] = lambda: engine
    return made


@pytest.fixture
def client():
    engine = 허브()
    with TestClient(앱(engine)) as made:
        yield made, engine


def 받는다(socket, kind: str, limit: int = 60) -> dict:
    """그 종류의 메시지가 올 때까지 읽습니다."""
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") == kind:
            return message
    raise AssertionError(f"{kind} 메시지가 오지 않았습니다.")


def 선언(sym: str = "A7569000", kind: str = "quote", **extra) -> dict:
    feed = {"context": "domestic-day", "kind": kind, "sym": sym, **extra}
    return {"op": "declare", "feeds": [feed]}


# ── 화면이 보내는 말 ─────────────────────────────────────────


def test_구독을_적으면_받아들인_것을_알려_준다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json(선언())
        answer = 받는다(socket, "subscriptions")

    assert answer["granted"] == [
        {"context": "domestic-day", "kind": "quote", "sym": "A7569000"}
    ]
    assert answer["rejected"] == []


def test_저장해_둔_시세가_화면까지_온다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json(선언())
        quote = 받는다(socket, "quote")

    assert quote["sym"] == "A7569000"
    assert quote["context"] == "domestic-day"
    assert quote["patch"]["last"] > 0
    # 체결은 배열로 함께 옵니다.
    assert isinstance(quote["trades"], list)


def test_저장해_둔_호가가_화면까지_온다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json(선언(kind="book"))
        book = 받는다(socket, "book")

    assert book["sym"] == "A7569000"
    assert book["asks"] or book["bids"]


def test_자료가_끝나면_끝났다고_알린다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json(선언())
        for _ in range(200):
            message = socket.receive_json()
            if message.get("state") in ("replay-finished", "replay-empty"):
                assert message["type"] == "status"
                assert message["market"] == "domestic"
                return
    raise AssertionError("자료가 끝났다는 알림이 오지 않았습니다.")


def test_자료가_없는_구독은_없다고_알린다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        # 야간 시세는 구독 기록만 있고 자료 메시지가 한 건도 없습니다.
        socket.send_json(
            {
                "op": "declare",
                "feeds": [{"context": "domestic-night", "kind": "quote", "sym": "A7569000"}],
            }
        )
        for _ in range(60):
            message = socket.receive_json()
            if message.get("state") == "replay-empty":
                assert message["sym"] == "A7569000"
                return
    raise AssertionError("자료가 없다는 알림이 오지 않았습니다.")


def test_기록에_없는_종목은_남의_값_대신_비었다고_알린다(client):
    """관심종목 셋이 한 종목 값으로 같아지던 자리 — 기록 없는 종목은 빈 알림만 옵니다."""
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json(
            {
                "op": "declare",
                "feeds": [
                    {"context": "domestic-day", "kind": "quote", "sym": "A7569000"},
                    {"context": "domestic-day", "kind": "quote", "sym": "C9999999"},
                ],
            }
        )
        받은시세 = set()
        빈알림 = None
        for _ in range(200):
            message = socket.receive_json()
            if message.get("type") == "quote":
                받은시세.add(message["sym"])
            if message.get("state") == "replay-empty":
                빈알림 = message
                break

    assert 빈알림 is not None, "기록 없는 종목이 비었다는 알림이 오지 않았습니다."
    assert 빈알림["sym"] == "C9999999"
    assert "C9999999" not in 받은시세, "다른 종목의 기록이 이 종목 값으로 흘렀습니다."


def test_모르는_요청은_무엇이_틀렸는지_알린다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json({"op": "구독해줘"})
        answer = 받는다(socket, "error")

    assert "구독해줘" in answer["detail"]


def test_구독_모양이_틀리면_알린다(client):
    made, _ = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json({"op": "declare", "feeds": [{"context": "domestic", "kind": "quote"}]})
        answer = 받는다(socket, "error")

    assert answer["detail"]


def test_화면이_나가면_구독을_놓는다(client):
    made, engine = client
    with made.websocket_connect("/api/stream") as socket:
        socket.send_json(선언())
        받는다(socket, "subscriptions")
        assert engine._subscribed

    # 연결이 끊기면 그 화면 몫이 통째로 사라집니다.
    for _ in range(200):
        if not engine._subscribed:
            break
        time.sleep(0.01)
    assert not engine._subscribed


def test_자리가_모자라면_밀려난_것을_알려_준다():
    engine = 허브(limit=1)
    with TestClient(앱(engine)) as made:
        with made.websocket_connect("/api/stream") as socket:
            socket.send_json(
                {
                    "op": "declare",
                    "feeds": [
                        {"context": "domestic-day", "kind": "quote", "sym": "A7569000", "priority": 1},
                        {"context": "domestic-day", "kind": "book", "sym": "A7569000", "priority": 9},
                    ],
                }
            )
            answer = 받는다(socket, "subscriptions")

    assert len(answer["granted"]) == 1
    assert answer["granted"][0]["kind"] == "quote"
    assert answer["rejected"][0]["kind"] == "book"


def test_앱에_실시간_라우트가_붙어_있다():
    """이 라우터가 `/` 정적 파일보다 먼저 등록되어 있어야 배포 모드에서 안 가립니다."""
    from backend.main import app as real_app

    주소 = set()
    for route in real_app.routes:
        붙은것 = getattr(route, "original_router", None)
        for 하나 in getattr(붙은것, "routes", []) if 붙은것 else [route]:
            주소.add(getattr(하나, "path", ""))
    assert "/api/stream" in 주소


# ── 허브 안쪽 ────────────────────────────────────────────────


def test_다시_붙으면_조회로_채우라고_알린다():
    engine = 허브()
    보낸것: list[dict] = []

    async def 실행():
        client = engine.attach("screen")
        engine._on_state("domestic", LIVE, "")
        engine._on_state("domestic", RECONNECTING, "끊겼습니다")
        engine._on_state("domestic", LIVE, "")
        while not client.queue.empty():
            보낸것.append(client.queue.get_nowait())
        await engine.stop()

    asyncio.run(실행())

    상태 = [m for m in 보낸것 if m["type"] == "status"]
    # 처음 붙었을 때는 채울 것이 없습니다.
    assert "refill" not in 상태[0]
    # 다시 붙었을 때만 채우라고 합니다.
    assert 상태[2]["refill"] is True


def _붙자마자_받은_상태(engine: Hub, name: str) -> list[dict]:
    client = engine.attach(name)
    받은것: list[dict] = []
    while not client.queue.empty():
        받은것.append(client.queue.get_nowait())
    return [m for m in 받은것 if m["type"] == "status"]


@pytest.mark.parametrize(
    ("거친상태", "알릴상태", "문구"),
    [
        ([LIVE], LIVE, ""),
        ([LIVE, RECONNECTING], RECONNECTING, "끊겼습니다"),
        ([LIVE, RECONNECTING, LIVE], LIVE, ""),
        ([LIVE, STOPPED], STOPPED, "닫혔습니다"),
    ],
    ids=["받는중", "다시붙는중", "다시붙음", "끊김"],
)
def test_새로_붙은_화면에는_그_시장의_지금_상태를_알린다(거친상태, 알릴상태, 문구):
    """한 번 받았던 시장이라고 「받는 중」으로 알리면, 다시 붙는 동안 붙은 화면만
    끊긴 것을 모릅니다. 다른 화면이 마지막으로 받은 상태와 같아야 합니다."""
    engine = 허브()

    async def 실행():
        for state in 거친상태:
            engine._on_state("domestic", state, 문구 if state == 알릴상태 else "")
        상태 = _붙자마자_받은_상태(engine, "새화면")
        await engine.stop()
        return 상태

    상태 = asyncio.run(실행())

    assert 상태 == [{"type": "status", "market": "domestic", "state": 알릴상태, "detail": 문구}]
    # 새 화면은 끊긴 적이 없습니다. 다시 채우라는 표지를 달지 않습니다.
    assert "refill" not in 상태[0]


def test_첫_연결이_붙는_중이면_새_연결_표지를_함께_알린다():
    """받던 시세가 끊긴 것이 아니라 아직 처음 붙는 중입니다 — 방송과 같은 표지입니다."""
    engine = 허브()

    async def 실행():
        engine._on_state("overseas", CONNECTING, "")
        상태 = _붙자마자_받은_상태(engine, "새화면")
        await engine.stop()
        return 상태

    상태 = asyncio.run(실행())

    assert 상태 == [
        {"type": "status", "market": "overseas", "state": CONNECTING, "detail": "", "fresh": True}
    ]


def test_시장마다_따로_알리고_구독_하나의_알림은_상태로_치지_않는다():
    engine = 허브()

    async def 실행():
        engine._on_state("domestic", LIVE, "")
        engine._on_state("overseas", LIVE, "")
        engine._on_state("overseas", RECONNECTING, "끊겼습니다")
        # 저장본의 끝남은 구독 하나에 대한 알림입니다. 연결은 그대로 받는 중입니다.
        engine._on_state("domestic", "replay-finished", "끝났습니다", "A7569000")
        상태 = _붙자마자_받은_상태(engine, "새화면")
        await engine.stop()
        return 상태

    상태 = asyncio.run(실행())

    assert {m["market"]: m["state"] for m in 상태} == {"domestic": LIVE, "overseas": RECONNECTING}


def test_연결이_모두_닫힌_시장은_알리지_않는다():
    """보는 것이 없어 연결을 내린 시장입니다. 처음부터 안 붙었던 시장과 같습니다."""
    engine = 허브()
    feed = Feed("domestic-day", "quote", "A7569000")

    async def 실행():
        engine.attach("보던화면")
        await engine.declare("보던화면", {feed: 1})
        보는중 = _붙자마자_받은_상태(engine, "둘째화면")
        await engine.declare("보던화면", {})
        닫힌뒤 = _붙자마자_받은_상태(engine, "셋째화면")
        await engine.stop()
        return 보는중, 닫힌뒤

    보는중, 닫힌뒤 = asyncio.run(실행())

    assert [m["state"] for m in 보는중] == [LIVE]
    assert 닫힌뒤 == []


def test_처음_붙는_화면에는_알릴_상태가_없다():
    engine = 허브()

    async def 실행():
        상태 = _붙자마자_받은_상태(engine, "첫화면")
        await engine.stop()
        return 상태

    assert asyncio.run(실행()) == []


def test_밀린_화면_때문에_허브가_멈추지_않는다():
    from backend.realtime.hub import CLIENT_BACKLOG, Client

    async def 실행():
        client = Client("느린화면")
        for i in range(CLIENT_BACKLOG + 10):
            client.send({"type": "quote", "n": i})
        return client

    client = asyncio.run(실행())

    assert client.queue.qsize() == CLIENT_BACKLOG
    # 가장 오래된 것부터 버립니다. 실시간 값은 다음 것이 곧 옵니다.
    assert client.queue.get_nowait()["n"] == 10


def test_등급을_안_적으면_가운데_등급으로_읽는다():
    from backend.realtime.ledger import DEFAULT_PRIORITY

    wishes = wishes_of([{"context": "domestic-day", "kind": "quote", "sym": "A"}])
    assert wishes == {Feed("domestic-day", "quote", "A"): DEFAULT_PRIORITY}


def test_등급이_숫자가_아니면_가운데_등급으로_읽는다():
    from backend.realtime.ledger import DEFAULT_PRIORITY

    wishes = wishes_of(
        [{"context": "domestic-day", "kind": "quote", "sym": "A", "priority": "급함"}]
    )
    assert wishes[Feed("domestic-day", "quote", "A")] == DEFAULT_PRIORITY


def test_구독_목록이_배열이_아니면_막는다():
    with pytest.raises(ValueError):
        wishes_of({"context": "domestic-day"})
