"""끊길 때 새지 않는지 — 구독 놓기, 접속키 몰아 부르지 않기, 중복 구독.

검토에서 나온 지적 셋을 그대로 붙잡아 둡니다. 셋 다 「평소에는 안 보이다가
연결이 나빠질 때만 나오는」 종류라 시험이 없으면 다시 들어옵니다.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedOK

from backend.nh_api.catalog import Limit
from backend.nh_api.session import create_session
from backend.realtime import realtime_routes
from backend.realtime.feeds import Feed
from backend.realtime.hub import Hub
from backend.realtime.link import AuthGate, Connection
from backend.realtime.ledger import stream_key
from tests.test_realtime_link import INIT_OK, FakeConnect, FakeSocket, 기다린다


def 허브(**kwargs) -> Hub:
    kwargs.setdefault("flush_interval", 0.01)
    kwargs.setdefault("replay_speed", 0.0)
    kwargs.setdefault("session_clock", False)
    return Hub(session=create_session(replay=True), environment="real", **kwargs)


# ── 보내다 실패해도 구독을 놓는다 ────────────────────────────


def test_보내다_실패해도_정리를_막지_않는다():
    """`_stop` 이 예외를 밖으로 내면 구독을 놓는 자리를 건너뜁니다."""

    async def 실행():
        async def 터진다():
            raise WebSocketDisconnect(1006)

        task = asyncio.create_task(터진다())
        await asyncio.sleep(0)
        # 여기서 예외가 새어 나오면 안 됩니다.
        await realtime_routes._stop(task)

    asyncio.run(실행())


def test_보내는_일은_끊김을_만나면_조용히_끝난다():
    class 끊긴소켓:
        async def send_json(self, payload):
            raise WebSocketDisconnect(1006)

    class 화면:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.queue.put_nowait({"type": "quote"})

    async def 실행():
        await realtime_routes._send_forever(끊긴소켓(), 화면())

    asyncio.run(실행())


def test_보내는_일이_먼저_죽어도_구독을_놓는다():
    """브라우저가 닫힌 직후 값이 오면 보내는 쪽이 먼저 죽습니다."""

    async def 실행():
        engine = 허브()
        client = engine.attach("screen")
        await engine.declare("screen", {Feed("domestic-day", "quote", "A7569000"): 1})
        assert engine._subscribed

        async def 터진다():
            raise WebSocketDisconnect(1006)

        sender = asyncio.create_task(터진다())
        await asyncio.sleep(0)

        # 라우트의 정리 순서를 그대로 흉내 냅니다.
        try:
            await realtime_routes._stop(sender)
        finally:
            await engine.detach("screen")

        held = engine._subscribed
        await engine.stop()
        return held, client

    held, _ = asyncio.run(실행())
    assert not held


# ── 화면마다 자기 말로 답한다 ────────────────────────────────


def test_주간과_야간_화면이_각자_자기_구독을_돌려받는다():
    async def 실행():
        engine = 허브()
        engine.attach("day")
        engine.attach("night")
        await engine.declare("day", {Feed("domestic-day", "orders"): 1})
        await engine.declare("night", {Feed("domestic-night", "orders"): 1})
        답 = {
            이름: [
                m
                for m in _비우기(client)
                if m["type"] == "subscriptions"
            ][-1]
            for 이름, client in engine._clients.items()
        }
        await engine.stop()
        return 답

    답 = asyncio.run(실행())

    # NH선물 쪽에서는 하나로 모이지만, 화면은 자기가 보낸 말을 돌려받습니다.
    assert 답["day"]["granted"] == [{"context": "domestic-day", "kind": "orders", "sym": ""}]
    assert 답["night"]["granted"] == [{"context": "domestic-night", "kind": "orders", "sym": ""}]
    assert 답["day"]["rejected"] == []
    assert 답["night"]["rejected"] == []


def test_남의_화면이_밀린_것은_섞이지_않는다():
    async def 실행():
        engine = 허브(limit=1)
        engine.attach("first")
        engine.attach("second")
        await engine.declare("first", {Feed("domestic-day", "quote", "A"): 1})
        await engine.declare("second", {Feed("domestic-day", "quote", "B"): 9})
        답 = {
            이름: [m for m in _비우기(client) if m["type"] == "subscriptions"][-1]
            for 이름, client in engine._clients.items()
        }
        await engine.stop()
        return 답

    답 = asyncio.run(실행())

    assert [f["sym"] for f in 답["first"]["granted"]] == ["A"]
    assert 답["first"]["rejected"] == []
    assert 답["second"]["granted"] == []
    assert [f["sym"] for f in 답["second"]["rejected"]] == ["B"]


def _비우기(client) -> list[dict]:
    made = []
    while not client.queue.empty():
        made.append(client.queue.get_nowait())
    return made


# ── 접속키를 몰아 부르지 않는다 ──────────────────────────────


class 세는제한기:
    """`RateLimiter` 자리에 끼워 넣고 등급만 셉니다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Limit]] = []

    def wait(self, environment: str, market: str, limit: Limit) -> float:
        self.calls.append((environment, market, limit))
        return 0.0


def test_접속키는_한_번에_하나씩_인증_등급으로_받는다():
    한계 = 세는제한기()
    gate = AuthGate(limiter=한계)
    동시 = {"지금": 0, "최대": 0}

    def 키발급() -> str:
        동시["지금"] += 1
        동시["최대"] = max(동시["최대"], 동시["지금"])
        동시["지금"] -= 1
        return "KEY"

    async def 실행():
        await asyncio.gather(
            *[
                gate.take(
                    environment="paper",
                    market="domestic",
                    issue_key=키발급,
                    access_token=lambda: "TOKEN",
                )
                for _ in range(5)
            ]
        )

    asyncio.run(실행())

    # 다섯 번 부르는 동안 한 번에 하나씩만 나갑니다.
    assert 동시["최대"] == 1
    # 발급마다 인증 등급의 간격을 지납니다.
    assert 한계.calls == [("paper", "domestic", Limit.AUTH)] * 5


def test_국내와_해외는_서로의_인증_몫을_깎지_않는다():
    한계 = 세는제한기()
    gate = AuthGate(limiter=한계)

    async def 실행():
        for market in ("domestic", "overseas"):
            await gate.take(
                environment="real",
                market=market,
                issue_key=lambda: "KEY",
                access_token=lambda: "TOKEN",
            )

    asyncio.run(실행())
    assert [call[1] for call in 한계.calls] == ["domestic", "overseas"]


# ── 초기화 중에 건 구독이 두 번 걸리지 않는다 ────────────────


def test_초기화를_기다리는_동안_건_구독이_두_번_걸리지_않는다():
    from backend.realtime.link import LIVE, subscribe_message

    QUOTE = Feed("domestic-day", "quote", "A7569000")

    async def 실행():
        socket = FakeSocket()  # 아직 INIT 을 안 보냅니다.
        상태: list = []
        made = Connection(
            market="domestic",
            environment="paper",
            base_url="https://example.invalid",
            issue_key=lambda: "KEY",
            access_token=lambda: "TOKEN",
            on_data=lambda key, body: None,
            on_state=lambda market, state, detail: 상태.append(state),
            connect=FakeConnect(socket),
            backoff=(0.0,),
        )
        made.start()
        await 기다린다(lambda: len(socket.sent) >= 1)  # session_init 이 나갔습니다.

        # 초기화 응답을 기다리는 사이에 구독을 겁니다.
        await made.add(stream_key(QUOTE), QUOTE)
        socket.push(INIT_OK)

        await 기다린다(lambda: LIVE in 상태)
        await asyncio.sleep(0.05)
        보낸것 = list(socket.sent)
        await made.stop()
        return 보낸것

    보낸것 = asyncio.run(실행())
    구독 = [m for m in 보낸것 if m == subscribe_message(QUOTE, action="A")]
    assert len(구독) == 1


def test_연결을_닫기_전에_구독_해제를_보낸다():
    from backend.realtime.link import LIVE, subscribe_message

    QUOTE = Feed("domestic-day", "quote", "A7569000")

    async def 실행():
        socket = FakeSocket([INIT_OK])
        상태: list = []
        made = Connection(
            market="domestic",
            environment="paper",
            base_url="https://example.invalid",
            issue_key=lambda: "KEY",
            access_token=lambda: "TOKEN",
            on_data=lambda key, body: None,
            on_state=lambda market, state, detail: 상태.append(state),
            connect=FakeConnect(socket),
            backoff=(0.0,),
        )
        made.start()
        await 기다린다(lambda: LIVE in 상태)
        await made.add(stream_key(QUOTE), QUOTE)
        await made.stop()
        return socket

    socket = asyncio.run(실행())
    assert subscribe_message(QUOTE, action="D") in socket.sent
    assert socket.closed


# ── 나가는 길에 거짓 경고를 안 남긴다 ───────────────────────


class 닫으면터지는소켓(FakeSocket):
    """닫는 순간 받는 쪽이 끊김으로 빠지는, 실제 소켓의 모습.

    **두 번째 `close()` 는 곧바로 돌아와야 합니다.** 받는 쪽이 끊김을 만나면
    `async with` 를 빠져나가며 `close()` 를 한 번 더 부르는데, 그 자리에서
    양보하면 그 사이에 정리 쪽의 취소가 먼저 닿아 끊김이 위까지 못 올라갑니다.
    그러면 이 시험은 가드가 있으나 없으나 통과해서 아무것도 지키지 못합니다.
    """

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        # 실제 소켓이 정상적으로 닫힐 때 받는 쪽에 나오는 예외입니다.
        self.push(ConnectionClosedOK(None, None))
        # 받는 쪽이 깨어나 끊김을 만나고, 그것이 위까지 올라갈 틈을 줍니다.
        for _ in range(60):
            await asyncio.sleep(0)

    async def __anext__(self) -> str:
        message = await self.inbound.get()
        if isinstance(message, Exception):
            raise message
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)


def test_우리가_닫는_중에는_다시_붙는다는_경고를_안_남긴다(caplog):
    """나가는 길에 남는 「다시 붙습니다」는 일어나지 않을 일을 적는 것입니다."""
    from backend.realtime.link import LIVE

    async def 실행():
        socket = 닫으면터지는소켓([INIT_OK])
        상태: list = []
        made = Connection(
            market="domestic",
            environment="paper",
            base_url="https://example.invalid",
            issue_key=lambda: "KEY",
            access_token=lambda: "TOKEN",
            on_data=lambda key, body: None,
            on_state=lambda market, state, detail: 상태.append(state),
            connect=FakeConnect(socket),
            backoff=(0.0,),
        )
        made.start()
        await 기다린다(lambda: LIVE in 상태)
        with caplog.at_level("WARNING", logger="backend.realtime.link"):
            await made.stop()
        return socket

    socket = asyncio.run(실행())

    assert socket.closed
    assert "다시 붙습니다" not in caplog.text


def test_우리가_안_닫았으면_경고를_남긴다(caplog):
    class 못붙는연결:
        def __call__(self, url, **_):
            raise ConnectionError("연결 거부")

    async def 실행():
        made = Connection(
            market="domestic",
            environment="paper",
            base_url="https://example.invalid",
            issue_key=lambda: "KEY",
            access_token=lambda: "TOKEN",
            on_data=lambda key, body: None,
            on_state=lambda market, state, detail: None,
            connect=못붙는연결(),
            backoff=(0.05,),
        )
        with caplog.at_level("WARNING", logger="backend.realtime.link"):
            made.start()
            await 기다린다(lambda: "다시 붙습니다" in caplog.text)
            await made.stop()

    asyncio.run(실행())
    assert "다시 붙습니다" in caplog.text


# ── 모아 보내는 일이 한 번 실패해도 멈추지 않는다 ────────────


def test_한_번_실패해도_그_뒤로_계속_보낸다():
    async def 실행():
        engine = 허브(flush_interval=0.01)
        client = engine.attach("screen")
        터진횟수 = {"n": 0}
        원래 = engine.flush

        def 한_번만_터진다():
            터진횟수["n"] += 1
            if 터진횟수["n"] == 1:
                raise RuntimeError("한 번 실패")
            원래()

        engine.flush = 한_번만_터진다  # type: ignore[method-assign]
        await asyncio.sleep(0.1)
        살아있나 = 터진횟수["n"] > 1
        await engine.stop()
        return 살아있나, client

    살아있나, _ = asyncio.run(실행())
    assert 살아있나


# ── 설정이 없으면 이유를 알린다 ──────────────────────────────


def test_설정이_없으면_화면에_이유를_알린다():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.config import ConfigError

    class 설정없는허브:
        def attach(self, name):
            from backend.realtime.hub import Client

            return Client(name)

        async def declare(self, name, wishes):
            raise ConfigError("설정 파일에 인증 정보가 없습니다.")

        async def detach(self, name):
            return None

    app = FastAPI()
    app.include_router(realtime_routes.router)
    app.dependency_overrides[realtime_routes.get_hub] = lambda: 설정없는허브()

    with TestClient(app) as made:
        with made.websocket_connect("/api/stream") as socket:
            socket.send_json(
                {
                    "op": "declare",
                    "feeds": [{"context": "domestic-day", "kind": "quote", "sym": "A"}],
                }
            )
            answer = socket.receive_json()

    assert answer["type"] == "error"
    assert "인증 정보" in answer["detail"]


# ── 다시 걸기는 장부를 바꾸지 않는다 ─────────────────────────


def test_허브의_다시_걸기는_걸린_구독만_청하고_장부는_그대로다(monkeypatch):
    from backend.realtime import replay_link

    야간호가 = Feed("domestic-night", "book", "A016C000")
    안걸린것 = Feed("domestic-night", "quote", "A016C000")
    청한것: list = []

    async def 기록(self, key):
        청한것.append(key)

    monkeypatch.setattr(replay_link.ReplayLink, "refresh", 기록)

    async def 실행():
        engine = 허브()
        engine.attach("화면")
        await engine.declare("화면", {야간호가: 1})
        앞 = (engine._subscribed, dict(engine._granted))
        await engine.refresh([야간호가, 안걸린것])
        뒤 = (engine._subscribed, dict(engine._granted))
        await engine.stop()
        return 앞, 뒤

    앞, 뒤 = asyncio.run(실행())

    assert 청한것 == [stream_key(야간호가)]
    assert 앞 == 뒤


def test_자리가_모자라_밀린_구독은_다시_걸지_않는다(monkeypatch):
    from backend.realtime import replay_link

    야간체결 = Feed("domestic-night", "quote", "A016C000")
    야간호가 = Feed("domestic-night", "book", "A016C000")
    청한것: list = []

    async def 기록(self, key):
        청한것.append(key)

    monkeypatch.setattr(replay_link.ReplayLink, "refresh", 기록)

    async def 실행():
        engine = 허브(limit=1)
        engine.attach("화면")
        await engine.declare("화면", {야간체결: 1, 야간호가: 9})
        앞 = (engine._subscribed, dict(engine._granted))
        await engine.refresh([야간호가])
        뒤 = (engine._subscribed, dict(engine._granted))
        await engine.stop()
        return 앞, 뒤

    앞, 뒤 = asyncio.run(실행())

    assert stream_key(야간호가) not in 앞[0], "상한 1 이라 호가는 밀려 있어야 합니다."
    assert 청한것 == []
    assert 앞 == 뒤
