"""실시간 원문 받기 — 허브가 화면용으로 묶기 전의 메시지를 **받은 순서 그대로** 실행 스레드에 넘긴다.

leadlag 같은 실시간 전략은 1초 안의 선후(KRX 체결 `KA` 와 MKU 호가 `FB` 중 무엇이 먼저 왔나)로
판단한다. 운영자 허브(`backend/realtime/hub.py`)가 화면에 보내는 값은 100ms 씩 묶은 것이라
(`coalesce.py` — 호가는 마지막 것만, 체결·호가 사이 순서 없음) 그 판단에 못 쓴다. 그래서 허브의
원문 자리(`Hub._on_data`, 묶기 전)에 `# 팀:` 갈고리(`Hub.raw_listeners`)를 두고 여기서 받는다.

## 스레드와 루프

    NH 웹소켓 ─▶ [이벤트 루프] Hub._on_data ─▶ RawFeed._on_raw ─▶ SimpleQueue ─▶ [실행 스레드] get()

- 허브는 FastAPI 이벤트 루프에서만 돈다. 구독 세우기(`attach`·`declare`)와 놓기(`detach`)는
  루프의 일이라 `run_coroutine_threadsafe` 로 루프에 맡기고 끝날 때까지 기다린다.
  루프 참조는 앱이 뜰 때 `routes.pyrun_startup()` 이 `bind_loop()` 로 잡아 둔다.
- `_on_raw` 는 루프에서 불린다. **넣기만 한다** — `SimpleQueue.put` 은 막히지 않고, 여기서 난
  예외는 허브로 올리지 않는다(기록만).
- 실행 스레드는 `get(timeout)` 으로 꺼낸다. 루프를 막는 일(주문·체결 확인)은 실행 스레드의 몫이다.
- 묶음 쪽 큐(`Client.queue`)는 루프의 작은 일감(`_drain`)이 비운다 — 비우지 않으면 200 건에서
  오래된 것부터 버리느라 헛일을 한다. 비우면서 구독 답(`subscriptions`)과 시장 연결 상태(`status`)만
  마지막 것을 적어 둔다(실행이 「구독이 밀렸다」「끊겼다 다시 붙었다」를 알 수 있게).

## 쌓임 한도

실행이 늦어 꺼내지 못한 것이 `limit`(기본 5,000) 건에 이르면 `overflow` 를 세우고 **그 뒤로는 넣지 않는다.**
이미 빠진 메시지가 있으니 같은 판단을 보장할 수 없다 — 실행(7번 작업)은 이 표시를 보면 「확인 필요」로 멈춘다.
한 번 선 표시는 내려가지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections.abc import Iterable
from typing import Any, NamedTuple

from backend.realtime import hub as hub_module
from backend.realtime.feeds import Feed
from backend.realtime.ledger import DEFAULT_PRIORITY, StreamKey, stream_key

logger = logging.getLogger(__name__)

#: 꺼내지 않고 쌓아 둘 수 있는 원문 수. 넘으면 `overflow`.
DEFAULT_LIMIT = 5000

#: 루프에 맡긴 구독 세우기·놓기를 기다리는 시간(초).
LOOP_TIMEOUT = 10.0

#: 허브 클라이언트 이름 앞자리. 화면(uuid)·운영자 펌프(`strategy`) 이름과 겹치지 않게 한다.
CLIENT_PREFIX = "team-pyrun:"

_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """허브가 도는 이벤트 루프를 적어 둔다. 앱이 뜰 때(`routes.pyrun_startup`) 부른다."""
    global _loop
    _loop = loop


def unbind_loop() -> None:
    """앱이 꺼질 때 루프 참조를 놓는다."""
    global _loop
    _loop = None


class RawMessage(NamedTuple):
    """허브가 받은 원문 하나. `recv_monotonic` 은 허브가 받은 순간의 `time.monotonic()`."""

    market: str
    api_id: str
    sym: str
    body: dict[str, Any]
    recv_monotonic: float


class RawFeed:
    """실행 하나의 원문 구독. 실행 스레드에서 만들고, 꺼내고, 닫는다.

    만들면 바로 구독을 세운다(루프에서 `attach` → 원문 구독자 등록 → `declare`). 원문 구독자를
    `declare` 보다 먼저 꽂아, 구독이 걸리자마자 오는 첫 메시지도 놓치지 않는다.
    """

    def __init__(
        self,
        run_id: str,
        wants: Iterable[Feed],
        *,
        hub: Any = None,
        loop: asyncio.AbstractEventLoop | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        self.run_id = run_id
        self.client_name = f"{CLIENT_PREFIX}{run_id}"
        self.wants: tuple[Feed, ...] = tuple(dict.fromkeys(wants))
        self._keys: frozenset[StreamKey] = frozenset(stream_key(feed) for feed in self.wants)
        self.limit = max(1, int(limit))
        self._hub = hub
        self._loop = loop if loop is not None else _loop
        self._queue: queue.SimpleQueue[RawMessage] = queue.SimpleQueue()
        # 넣는 쪽(루프)만 세는 쌓인 수. 꺼내는 쪽은 `_taken` 을 센다 — 둘의 차가 지금 쌓인 수.
        self._put = 0
        self._taken = 0
        self._count_lock = threading.Lock()
        #: 한도를 넘겨 메시지를 버리기 시작했는지. 한 번 서면 내려가지 않는다.
        self.overflow = False
        self._closed = False
        self._drainer: asyncio.Task[None] | None = None
        #: 허브가 마지막으로 보낸 구독 답(`{"granted", "rejected", "failed"}`). 아직 없으면 None.
        self.subscriptions: dict[str, Any] | None = None
        #: 시장마다 마지막 연결 상태 알림(`{"state", "detail", "refill"?, ...}`).
        self.status: dict[str, dict[str, Any]] = {}

        if self._loop is None:
            raise RuntimeError("허브 이벤트 루프를 모릅니다 — 앱 시작(`pyrun_startup`) 전에는 원문을 받을 수 없습니다.")
        if _on_loop(self._loop):
            # 루프 스레드에서 루프 일을 기다리면 영영 안 끝난다.
            raise RuntimeError("RawFeed 는 실행 스레드에서 만들어야 합니다(이벤트 루프 스레드에서는 막힙니다).")
        try:
            asyncio.run_coroutine_threadsafe(self._open(), self._loop).result(LOOP_TIMEOUT)
        except BaseException:
            # 반쯤 세운 구독을 남기지 않는다.
            self.close()
            raise

    # ── 실행 스레드 쪽 ──────────────────────────────────────

    def get(self, timeout: float | None = None) -> RawMessage | None:
        """다음 원문. `timeout` 초 안에 없거나 닫혔으면 None."""
        if self._closed:
            return None
        try:
            made = self._queue.get(timeout=timeout) if timeout is None or timeout > 0 else self._queue.get_nowait()
        except queue.Empty:
            return None
        if self._closed:
            return None
        with self._count_lock:
            self._taken += 1
        return made

    @property
    def pending(self) -> int:
        """꺼내지 않고 쌓인 수(대략)."""
        with self._count_lock:
            return self._put - self._taken

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """구독을 놓는다(`detach` + 원문 구독자 빼기). 그 뒤로는 아무것도 안 온다. 두 번 불러도 된다."""
        if self._closed and self._drainer is None:
            return
        self._closed = True
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(self._shut(), loop)
                if not _on_loop(loop):
                    future.result(LOOP_TIMEOUT)
            except Exception:
                logger.exception("원문 구독(%s)을 놓지 못했습니다", self.run_id)
        # 이미 쌓인 것도 버린다 — 닫은 뒤에 꺼내지지 않게.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    # ── 이벤트 루프 쪽 ──────────────────────────────────────

    @property
    def hub(self) -> Any:
        if self._hub is None:
            self._hub = hub_module.hub()
        return self._hub

    async def _open(self) -> None:
        engine = self.hub
        client = engine.attach(self.client_name)
        engine.raw_listeners.append(self._on_raw)
        self._drainer = asyncio.create_task(self._drain(client))
        await engine.declare(self.client_name, {feed: DEFAULT_PRIORITY for feed in self.wants})

    async def _shut(self) -> None:
        engine = self._hub
        if engine is None:
            return
        try:
            engine.raw_listeners.remove(self._on_raw)
        except ValueError:
            pass
        drainer, self._drainer = self._drainer, None
        if drainer is not None:
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)
        await engine.detach(self.client_name)

    async def _drain(self, client: Any) -> None:
        """묶음 큐를 비운다. 구독 답과 연결 상태만 적어 둔다."""
        while True:
            payload = await client.queue.get()
            try:
                kind = payload.get("type")
                if kind == "subscriptions":
                    self.subscriptions = {
                        "granted": list(payload.get("granted") or []),
                        "rejected": list(payload.get("rejected") or []),
                        "failed": list(payload.get("failed") or []),
                    }
                elif kind == "status" and payload.get("market"):
                    self.status[str(payload["market"])] = dict(payload)
            except Exception:  # noqa: BLE001 — 비우기가 멈추면 묶음 큐가 찬다.
                logger.exception("원문 구독(%s)의 묶음 큐를 비우다 실패했습니다", self.run_id)

    def _on_raw(self, market: str, api_id: str, sym: str, body: dict[str, Any], recv_monotonic: float) -> None:
        """허브 원문 갈고리. 루프에서 받은 순서대로 불린다. **넣기만 하고 터지지 않는다.**"""
        try:
            if self._closed or self.overflow or (market, api_id, sym) not in self._keys:
                return
            with self._count_lock:
                if self._put - self._taken >= self.limit:
                    self.overflow = True
                    logger.warning("원문 구독(%s)이 %d 건 쌓여 더 받지 않습니다(overflow)", self.run_id, self.limit)
                    return
                self._put += 1
            # 사본 — 다른 구독자·허브가 쥔 dict 와 나눠 쓰지 않는다.
            self._queue.put(RawMessage(market, api_id, sym, dict(body), recv_monotonic))
        except Exception:  # noqa: BLE001 — 허브로 올리지 않는다.
            logger.exception("원문 구독(%s)에 넣지 못했습니다", self.run_id)


def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False
