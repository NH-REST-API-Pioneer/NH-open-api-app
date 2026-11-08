"""스프레드 시세 공급 — 다리별 1분봉을 맞춰 주고, 한 다리라도 장이 쉬면 열릴 때까지 기다린다.

`Feed` 는 실행(Task 4 의 `ctx`)이 보는 약속이고, `LiveFeed` 는 실제 차트(분)·현재가 조회로 구현한 것이다.
시계·쉼·조회(어댑터)·세션 판정을 모두 생성자로 받으므로 시험은 실제로 쉬지 않는다.

박자는 파이썬 전략 `LiveRun` 과 같다: 분이 바뀌고 `MINUTE_DELAY_SECONDS`(3초) 뒤에 막 끝난 봉(시작 시각이
그 앞 분)을 조회한다. 기다리는 동안 1초 이하로 끊어 쉬며 `stop` 을 본다.

장 열림은 운영자 세션 판정(`backend.sessions.sessions_routes.judged`)의 `state` 로 본다. 거래 창인 상태
(국내 `day`·`night`, 해외 `open`·`open-2`·`next-day`)만 열림이고, `unknown`·`closed`·`break`·단일가 등
나머지와 판정 오류는 모두 닫힘이다(모르면 거래하지 않는다).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.sessions.hours import now_kst
from backend.team_pyrun import markets
from backend.team_pyrun.api import num
from backend.team_spread.bars import Minute, align
from backend.team_spread.legs import Leg

MINUTE_DELAY_SECONDS = 3    # 분이 바뀌고 이만큼 뒤에 막 끝난 봉을 받음 (live.py 와 같음)
LIVE_BARS = 10              # 장중 조회 봉 개수
GIVE_UP_SECONDS = 20        # 막 끝난 봉이 이 시간 지나도록 안 오면 그 분을 건너뜀
POLL_SECONDS = 1.0

WAIT_CLOSED = "장 쉼"
WAIT_RUNNING = "진행 중"

#: 거래 창인 세션 상태(`backend.sessions.judge`) — 이 밖은 전부 닫힘으로 본다.
OPEN_STATES = frozenset({"day", "night", "open", "open-2", "next-day"})


@dataclass(frozen=True)
class Quote:
    last: float | None
    bid: float | None
    ask: float | None
    at: datetime


class Feed(Protocol):
    def history(self, legs: list[Leg], count: int) -> list[Minute]: ...
    def next_minute(self, legs: list[Leg], stop: threading.Event) -> Minute | None: ...
    def quote(self, leg: Leg) -> Quote: ...
    def is_open(self, leg: Leg, now: datetime) -> bool: ...
    def now(self) -> datetime: ...
    def sleep(self, seconds: float, stop: threading.Event) -> None: ...


def _default_sleep(seconds: float, stop: threading.Event) -> None:
    stop.wait(seconds)


def _default_judge(market: str, sym: str, now: datetime) -> dict[str, Any]:
    from backend.sessions.sessions_routes import judged     # 늦게 가져옴 — 시험은 가짜를 넣는다
    return judged(market, sym, now)


def _default_adapter(leg: Leg):
    market = markets.OVERSEAS if leg.market == "overseas" else markets.DOMESTIC
    return markets.adapter_for(market, exch_cd=leg.exchange if leg.market == "overseas" else None)


def _closed_bar_start(now: datetime) -> datetime:
    """지금 조회할 수 있는 가장 최근에 끝난 봉의 시작 시각 — 분 경계 + 3초 뒤부터 그 앞 분."""
    return (now - timedelta(seconds=MINUTE_DELAY_SECONDS)).replace(second=0, microsecond=0) - timedelta(minutes=1)


class LiveFeed:
    def __init__(self, *, now: Callable[[], datetime] = now_kst,
                 sleep: Callable[[float, threading.Event], None] = _default_sleep,
                 adapter_of: Callable[[Leg], Any] = _default_adapter,
                 judge: Callable[[str, str, datetime], dict[str, Any]] = _default_judge,
                 on_wait: Callable[[str, list[str]], None] | None = None):
        self._now, self._sleep, self._adapter_of, self._judge = now, sleep, adapter_of, judge
        self._on_wait = on_wait or (lambda state, closed: None)
        self._adapters: dict[str, Any] = {}

    def now(self) -> datetime:
        return self._now()

    def sleep(self, seconds: float, stop: threading.Event) -> None:
        self._sleep(seconds, stop)

    def _adapter(self, leg: Leg) -> Any:
        if leg.name not in self._adapters:
            self._adapters[leg.name] = self._adapter_of(leg)
        return self._adapters[leg.name]

    def is_open(self, leg: Leg, now: datetime) -> bool:
        try:
            return str(self._judge(leg.market, leg.sym, now).get("state")) in OPEN_STATES
        except Exception:       # 판정을 못 하면 닫힘 — 모르는 채로 거래하지 않는다
            return False

    def _aligned(self, legs: list[Leg], count: int) -> list[Minute]:
        return align({leg.name: self._adapter(leg).chart_minute(leg.sym, req_qty=count) for leg in legs})

    def history(self, legs: list[Leg], count: int) -> list[Minute]:
        return self._aligned(legs, count)

    def quote(self, leg: Leg) -> Quote:
        body = self._adapter(leg).price(leg.sym)
        return Quote(num(body.get("last_pric")), num(body.get("bid_pric")), num(body.get("ask_pric")), self._now())

    def _closed_legs(self, legs: list[Leg], now: datetime) -> list[str]:
        return [leg.name for leg in legs if not self.is_open(leg, now)]

    def next_minute(self, legs: list[Leg], stop: threading.Event) -> Minute | None:
        """다음에 끝나는 분의 맞춘 1분봉. `stop` 이 서면 None.

        부른 시점에 이미 끝난 봉은 돌려주지 않고 그다음 분을 기다린다. 한 다리라도 장이 쉬면 `on_wait("장 쉼", 쉬는
        다리)` 를 한 번 부르고 열릴 때까지 기다리며, 열리면 `on_wait("진행 중", [])` 를 부르고 그다음 온전한 분부터 다시 센다."""
        last = _closed_bar_start(self._now())        # 이 봉까지는 이미 지난 것
        waiting = False
        while not stop.is_set():
            now = self._now()
            closed = self._closed_legs(legs, now)
            if closed:
                if not waiting:
                    waiting = True
                    self._on_wait(WAIT_CLOSED, closed)
                self._sleep(POLL_SECONDS, stop)
                continue
            if waiting:
                waiting = False
                self._on_wait(WAIT_RUNNING, [])
                last = _closed_bar_start(now)
            target = _closed_bar_start(now)
            if target <= last:
                self._sleep(POLL_SECONDS, stop)
                continue
            key = (target.strftime("%Y%m%d"), target.strftime("%H%M%S"))
            if (now - target).total_seconds() > 60 + GIVE_UP_SECONDS:
                last = target          # 그 분의 봉이 끝내 안 왔다 — 건너뛰고 다음 분을 기다린다
                continue
            try:
                found = next((m for m in self._aligned(legs, LIVE_BARS) if (m.date, m.time) == key), None)
            except Exception:           # 연결·응답 문제로 멈추지 않게 — 다음 초에 다시
                found = None
            if found is not None:
                return found
            self._sleep(POLL_SECONDS, stop)
        return None
