"""실시간 원문 받기 — 허브가 화면용으로 묶기 전의 메시지를 **받은 순서 그대로** 실행 스레드에 넘긴다.

leadlag 같은 실시간 전략은 1초 안의 선후(KRX 체결 `KA` 와 MKU 호가 `FB` 중 무엇이 먼저 왔나)로
판단한다. 운영자 허브(`backend/realtime/hub.py`)가 화면에 보내는 값은 100ms 씩 묶은 것이라
(`coalesce.py` — 호가는 마지막 것만, 체결·호가 사이 순서 없음) 그 판단에 못 쓴다. 그래서 허브의
원문 자리(`Hub._on_data`, 묶기 전)에 `# 팀:` 갈고리(`Hub.raw_listeners`)를 두고 여기서 받는다.

## 스레드와 루프

    NH 웹소켓 ─▶ [이벤트 루프] Hub._on_data ─▶ RawFeed._on_raw ─▶ SimpleQueue ─▶ [실행 스레드] get()
                 [이벤트 루프] Client.send  ─▶ RawFeed._on_hub ─┘ (공백 표지만)

- 허브는 FastAPI 이벤트 루프에서만 돈다. 구독 세우기(`attach`·`declare`)와 놓기(`detach`)는
  루프의 일이라 `run_coroutine_threadsafe` 로 루프에 맡기고 끝날 때까지 기다린다.
  루프 참조는 앱이 뜰 때 `routes.pyrun_startup()` 이 `bind_loop()` 로 잡아 둔다.
- `_on_raw` 는 루프에서 불린다. **넣기만 한다** — `SimpleQueue.put` 은 막히지 않고, 여기서 난
  예외는 허브로 올리지 않는다(기록만).
- 허브가 이 클라이언트에 보내는 묶음 메시지는 큐에 쌓지 않는다. 허브 클라이언트의 `send` 를
  이 객체의 `_on_hub` 로 바꿔 끼워 **보내는 그 자리에서** 받는다 — 시세 묶음(`quote`·`book`·`orders`)은
  버리고, 연결 상태·환경·구독 답만 읽는다. 같은 루프에서 원문과 같은 차례로 불리므로 아래 공백 표지가
  원문 사이의 정확한 자리에 들어간다(큐를 나중에 비우는 방식이면 표지가 늦게 끼어든다).
- 실행 스레드는 `get(timeout)` 으로 꺼낸다. 루프를 막는 일(주문·체결 확인)은 실행 스레드의 몫이다.

## 공백 표지 (`RawGap`)

원문과 **같은 큐에 받은 차례대로** 들어간다. 실행(7번 작업)은 만나는 대로 멈추거나 처리한다.

| `kind` | 언제 |
|---|---|
| `refill` | 시장 연결이 끊겼다 다시 붙었다(`status` `live` + `refill`). 끊긴 동안의 메시지는 없다 |
| `environment` | 활성 환경(모의/실전)이 바뀌었다. 연결이 새 환경으로 다시 붙는다 |
| `rejected` | 원한 구독이 허브 답의 `rejected`·`failed` 에 들었다(자리 밀림·서버 거절). 원문이 안 온다 |

`rejected` 는 밀린 구독 묶음이 **바뀔 때만** 한 번 넣는다(허브는 누가 선언할 때마다 답한다).
저장본의 종목별 알림(`replay-finished`·`replay-empty`)은 연결 상태가 아니라 `replay_notes` 에 따로 적는다.

## 쌓임 한도

실행이 늦어 꺼내지 못한 것이 `limit`(기본 5,000) 건에 이르면 `overflow` 를 세우고 **그 뒤로는 원문을 넣지 않는다.**
이미 빠진 메시지가 있으니 같은 판단을 보장할 수 없다 — 실행은 이 표시를 보면 「확인 필요」로 멈춘다.
한 번 선 표시는 내려가지 않는다. 공백 표지는 드물어 한도와 상관없이 넣는다.

## 구독 등급

허브 장부는 스무 자리를 등급이 **작은 수**부터 나눈다(`ledger.Ledger.grant`). 화면 관심 목록(3)이나
기본값(5)에 밀려 실행 도중 원문이 끊기면 안 되므로 가장 센 등급 `ledger.MIN_PRIORITY`(1)로 선언한다.

## 정리

열린 RawFeed 는 모듈 목록에 적어 둔다. 앱이 꺼질 때 `routes.pyrun_shutdown` 이 실행을 모두 멈춘 뒤
`close_all()` 로 남은 것을 닫는다 — 실행이 `close()` 를 빠뜨려도 허브에 구독이 남지 않게.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Iterable
from typing import Any, NamedTuple

from backend.realtime import hub as hub_module
from backend.realtime.feeds import Feed
from backend.realtime.ledger import MIN_PRIORITY, StreamKey, stream_key
from backend.realtime.link import LIVE

logger = logging.getLogger(__name__)

#: 꺼내지 않고 쌓아 둘 수 있는 원문 수. 넘으면 `overflow`.
DEFAULT_LIMIT = 5000

#: 루프에 맡긴 구독 세우기·놓기를 기다리는 시간(초).
LOOP_TIMEOUT = 10.0

#: 허브 클라이언트 이름 앞자리. 화면(uuid)·운영자 펌프(`strategy`) 이름과 겹치지 않게 한다.
CLIENT_PREFIX = "team-pyrun:"

#: 공백 표지 종류.
GAP_REFILL = "refill"
GAP_ENVIRONMENT = "environment"
GAP_REJECTED = "rejected"

_loop: asyncio.AbstractEventLoop | None = None

#: 열려 있는 RawFeed. `close_all()` 이 남은 것을 닫는다.
_open_feeds: dict[int, RawFeed] = {}
_open_lock = threading.Lock()

#: `close()` 가 막혀 있는 `get()` 을 깨우려고 넣는 표.
_CLOSED = object()


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """허브가 도는 이벤트 루프를 적어 둔다. 앱이 뜰 때(`routes.pyrun_startup`) 부른다."""
    global _loop
    _loop = loop


def unbind_loop() -> None:
    """앱이 꺼질 때 루프 참조를 놓는다."""
    global _loop
    _loop = None


def close_all() -> list[str]:
    """열려 있는 RawFeed 를 모두 닫는다. 닫은 실행 id 를 돌려준다. **루프 스레드가 아닌 곳에서** 부른다."""
    with _open_lock:
        feeds = list(_open_feeds.values())
    closed = []
    for feed in feeds:
        try:
            feed.close()
            closed.append(feed.run_id)
        except Exception:  # noqa: BLE001 — 하나 때문에 나머지를 남기지 않는다.
            logger.exception("원문 구독(%s)을 닫지 못했습니다", feed.run_id)
    return closed


class RawMessage(NamedTuple):
    """허브가 받은 원문 하나. `recv_monotonic` 은 허브가 받은 순간의 `time.monotonic()`."""

    market: str
    api_id: str
    sym: str
    body: dict[str, Any]
    recv_monotonic: float


class RawGap(NamedTuple):
    """원문 사이에 끼는 공백 표지. `kind` 는 `refill`·`environment`·`rejected`(머리말 표)."""

    kind: str
    market: str
    detail: dict[str, Any]
    recv_monotonic: float


class RawFeed:
    """실행 하나의 원문 구독. 실행 스레드에서 만들고, 꺼내고, 닫는다.

    만들면 바로 구독을 세운다(루프에서 `attach` → `send` 바꿔 끼우기 → 원문 구독자 등록 → `declare`).
    원문 구독자를 `declare` 보다 먼저 꽂아, 구독이 걸리자마자 오는 첫 메시지도 놓치지 않는다.
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
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        # 넣은 수와 꺼낸 수. 둘의 차가 지금 쌓인 수.
        self._put = 0
        self._taken = 0
        self._count_lock = threading.Lock()
        #: 한도를 넘겨 원문을 버리기 시작했는지. 한 번 서면 내려가지 않는다.
        self.overflow = False
        self._closed = False
        self._attached = False
        #: 허브가 마지막으로 보낸 구독 답(`{"granted", "rejected", "failed"}`). 아직 없으면 None.
        self.subscriptions: dict[str, Any] | None = None
        #: 시장마다 마지막 **연결** 상태 알림. 통째로 갈아 끼운다(다른 스레드가 도는 중에 안 바뀌게).
        self.status: dict[str, dict[str, Any]] = {}
        #: 저장본의 종목별 알림 `(market, sym) → 알림`. 연결 상태와 따로 둔다.
        self.replay_notes: dict[tuple[str, str], dict[str, Any]] = {}
        # 마지막으로 표지를 넣은 밀린 구독 묶음.
        self._rejected: frozenset[tuple[str, str, str]] = frozenset()

        if self._loop is None:
            raise RuntimeError("허브 이벤트 루프를 모릅니다 — 앱 시작(`pyrun_startup`) 전에는 원문을 받을 수 없습니다.")
        if _on_loop(self._loop):
            # 루프 스레드에서 루프 일을 기다리면 영영 안 끝난다.
            raise RuntimeError("RawFeed 는 실행 스레드에서 만들어야 합니다(이벤트 루프 스레드에서는 막힙니다).")
        with _open_lock:
            _open_feeds[id(self)] = self
        try:
            asyncio.run_coroutine_threadsafe(self._open(), self._loop).result(LOOP_TIMEOUT)
        except BaseException:
            # 반쯤 세운 구독을 남기지 않는다.
            self.close()
            raise

    # ── 실행 스레드 쪽 ──────────────────────────────────────

    def get(self, timeout: float | None = None) -> RawMessage | RawGap | None:
        """다음 원문 또는 공백 표지. `timeout` 초 안에 없거나 닫혔으면 None.

        `timeout=None` 으로 기다리는 중에 `close()` 되면 깨어나 None 을 돌려준다.
        """
        if self._closed:
            return None
        try:
            made = self._queue.get(timeout=timeout) if timeout is None or timeout > 0 else self._queue.get_nowait()
        except queue.Empty:
            return None
        if made is _CLOSED or self._closed:
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
        first = not self._closed
        self._closed = True
        loop = self._loop
        if self._attached and loop is not None and not loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(self._shut(), loop)
                if not _on_loop(loop):
                    future.result(LOOP_TIMEOUT)
            except Exception:
                logger.exception("원문 구독(%s)을 놓지 못했습니다", self.run_id)
        if not self._attached:
            with _open_lock:
                _open_feeds.pop(id(self), None)
        if first:
            # 이미 쌓인 것은 버리고, 기다리는 `get()` 을 깨운다.
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put(_CLOSED)

    # ── 이벤트 루프 쪽 ──────────────────────────────────────

    @property
    def hub(self) -> Any:
        if self._hub is None:
            self._hub = hub_module.hub()
        return self._hub

    async def _open(self) -> None:
        if self._closed:
            # 루프가 늦게 돌려 생성이 이미 시간 초과로 닫혔다 — 아무것도 세우지 않는다(남은 구독이 생기지 않게).
            return
        engine = self.hub
        client = engine.attach(self.client_name)
        self._attached = True
        # 붙자마자 허브가 담아 둔 연결 상태를 먼저 읽고, 그 뒤로는 보내는 자리에서 받는다.
        while not client.queue.empty():
            self._on_hub(client.queue.get_nowait())
        client.send = self._on_hub
        engine.raw_listeners.append(self._on_raw)
        await engine.declare(self.client_name, {feed: MIN_PRIORITY for feed in self.wants})

    async def _shut(self) -> None:
        engine = self._hub
        try:
            if engine is None:
                return
            try:
                engine.raw_listeners.remove(self._on_raw)
            except ValueError:
                pass
            await engine.detach(self.client_name)
        finally:
            self._attached = False
            with _open_lock:
                _open_feeds.pop(id(self), None)

    def _on_hub(self, payload: dict[str, Any]) -> None:
        """허브가 이 클라이언트에 보내는 묶음 메시지. 시세는 버리고, 공백이면 표지를 넣는다. 터지지 않는다."""
        try:
            if self._closed:
                return
            kind = payload.get("type")
            if kind == "status":
                self._on_status(payload)
            elif kind == "environment":
                self._mark(GAP_ENVIRONMENT, "", {"active": payload.get("active")})
            elif kind == "subscriptions":
                self._on_subscriptions(payload)
        except Exception:  # noqa: BLE001 — 허브로 올리지 않는다.
            logger.exception("원문 구독(%s)이 허브 알림을 읽지 못했습니다", self.run_id)

    def _on_status(self, payload: dict[str, Any]) -> None:
        market = str(payload.get("market") or "")
        if not market:
            return
        if payload.get("sym"):
            # 저장본의 종목별 알림(끝남·없음). 연결 상태가 아니다.
            self.replay_notes = {**self.replay_notes, (market, str(payload["sym"])): dict(payload)}
            return
        self.status = {**self.status, market: dict(payload)}
        if payload.get("state") == LIVE and payload.get("refill"):
            self._mark(GAP_REFILL, market, {"detail": payload.get("detail")})

    def _on_subscriptions(self, payload: dict[str, Any]) -> None:
        answer = {
            "granted": list(payload.get("granted") or []),
            "rejected": list(payload.get("rejected") or []),
            "failed": list(payload.get("failed") or []),
        }
        self.subscriptions = answer
        mine = {(feed.context, feed.kind, feed.sym) for feed in self.wants}
        out = frozenset(
            key
            for item in answer["rejected"] + answer["failed"]
            if isinstance(item, dict)
            for key in [(item.get("context"), item.get("kind"), item.get("sym"))]
            if key in mine
        )
        if out != self._rejected:
            self._rejected = out
            if out:
                failed = [item for item in answer["failed"] if isinstance(item, dict)]
                self._mark(
                    GAP_REJECTED,
                    "",
                    {
                        "feeds": [dict(zip(("context", "kind", "sym"), key, strict=True)) for key in sorted(out)],
                        "failed": failed,
                    },
                )

    def _mark(self, kind: str, market: str, detail: dict[str, Any]) -> None:
        with self._count_lock:
            self._put += 1
        self._queue.put(RawGap(kind, market, detail, time.monotonic()))

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
