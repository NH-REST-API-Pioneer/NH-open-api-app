"""`/api/stream` — 화면이 실시간을 받아 가는 자리.

**주소에 시장 칸이 없습니다.** `/api/{시장}/{API 이름}` 은 NH선물 서버에 그대로
물어보는 조회·주문 API 의 규칙입니다. 여기는 한 연결로 국내와 해외를 함께
받으므로 그 규칙에 들어가지 않습니다. `/api/health`, `/api/ui` 와 같은 자리입니다.

**웹소켓입니다.** 화면이 보는 종목은 계속 바뀝니다 — 종목을 옮기고, 2분할을
켜고, 관심종목을 고칩니다. 한쪽으로만 흐르는 방식으로는 그 변경을 다른 길로
보내야 하고, 그러면 「어느 연결의 구독인가」를 따로 이어 붙여야 합니다. 새로
고침 한 번에 그 짝이 어긋납니다. 받는 길과 바꾸는 길이 같아야 어긋날 것이
없습니다.

주고받는 말의 모양은 `hub` 첫머리에 있습니다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from backend.config import ConfigError
from backend.realtime.hub import Client, Hub, hub, wishes_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream", tags=["stream"])

DECLARE = "declare"


def get_hub() -> Hub:
    """앱이 쓰는 허브. 테스트는 이 자리를 바꿔 끼웁니다."""
    return hub()


@router.websocket("")
async def stream(socket: WebSocket, engine: Hub = Depends(get_hub)) -> None:
    """화면 하나와 이어집니다.

    이 연결이 끊기면 이 화면이 걸어 둔 구독은 **통째로 놓입니다.** 화면이
    해제를 빠뜨려도 아무도 안 보는 구독이 남지 않습니다.
    """
    await socket.accept()
    name = uuid4().hex
    client = engine.attach(name)

    sender = asyncio.create_task(_send_forever(socket, client))
    try:
        try:
            while True:
                message = await socket.receive_json()
                await _handle(engine, name, message)
        except WebSocketDisconnect:
            pass
        except (ValueError, TypeError) as exc:
            # 읽을 수 없는 말이 왔습니다. 무엇이 틀렸는지 알리고 끊습니다.
            await _say(socket, {"type": "error", "detail": str(exc)})
        except ConfigError as exc:
            # 인증 정보가 없어 실시간을 열 수 없습니다. 이유를 알리지 않으면
            # 화면에는 그냥 닫힌 연결만 보이고, 무엇을 해야 할지 알 수 없습니다.
            await _say(socket, {"type": "error", "detail": str(exc)})
        finally:
            await _stop(sender)
    finally:
        # **무슨 일이 있어도** 이 화면 몫의 구독은 놓습니다. 여기를 건너뛰면
        # 아무도 안 보는 구독이 남고, 스무 자리 중 한 칸이 새는 채로
        # 새로고침으로도 없어지지 않습니다.
        await engine.detach(name)


async def _handle(engine: Hub, name: str, message: Any) -> None:
    if not isinstance(message, dict):
        raise ValueError("보내는 말은 객체여야 합니다.")
    op = str(message.get("op") or "")
    if op != DECLARE:
        raise ValueError(f"모르는 요청입니다: {op!r}")
    await engine.declare(name, wishes_of(message.get("feeds")))


async def _send_forever(socket: WebSocket, client: Client) -> None:
    """보낼 것이 생기면 보냅니다. 연결이 닫히면 조용히 끝냅니다.

    여기서 나간 예외가 정리 단계로 새어 나가면 구독을 놓는 자리를 건너뛰게
    되므로, 보내다 끊긴 것은 여기서 끝냅니다.
    """
    try:
        while True:
            payload = await client.queue.get()
            await socket.send_json(payload)
    except (WebSocketDisconnect, RuntimeError, OSError):
        return


async def _stop(task: asyncio.Task[None]) -> None:
    """보내는 일을 끝냅니다. 어떻게 끝났든 여기서 삼킵니다."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        # 이미 끝난 일의 실패입니다. 이것 때문에 정리를 멈추지 않습니다.
        logger.debug("화면으로 보내는 일이 실패한 채로 끝났습니다.", exc_info=True)


async def _say(socket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await socket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect, OSError):
        pass
