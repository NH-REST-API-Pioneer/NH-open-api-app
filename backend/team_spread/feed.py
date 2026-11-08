"""스프레드 시세 공급 — 다리별 1분봉을 맞춰 주고, 한 다리라도 장이 쉬면 열릴 때까지 기다린다.

`Feed` 는 실행(Task 4 의 `ctx`)이 보는 약속이고, `LiveFeed` 는 실제 차트(분)·현재가 조회로 구현한 것이다.
시계·쉼·조회(어댑터)·세션 판정을 모두 생성자로 받으므로 시험은 실제로 쉬지 않는다.

박자는 파이썬 전략 `LiveRun` 과 같다: 분이 바뀌고 `MINUTE_DELAY_SECONDS`(3초) 뒤에 막 끝난 봉(시작 시각이
그 앞 분)을 조회한다. 기다리는 동안 1초 이하로 끊어 쉬며 `stop` 을 본다.

장 열림은 운영자 세션 판정(`backend.sessions.sessions_routes.judged`)의 `state` 로 본다. 거래 창인 상태
(국내 `day`·`night`, 해외 `open`·`open-2`·`next-day`)만 열림이고, `unknown`·`closed`·`break`·단일가 등
나머지와 판정 오류는 모두 닫힘이다(모르면 거래하지 않는다).

`is_open` 은 **봉(데이터)** 의 열림이고, 주문은 `order_open` 으로 본다 — 국내 다리는 주간 판정이 08:45 부터 열려도
모의계좌 주문은 09:00(`markets.DOMESTIC.session_start`) 부터라, 그 앞 15분은 봉만 받고 주문·정리는 하지 않는다.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import markets
from backend.team_pyrun.api import num
from backend.team_pyrun.broker import error_text
from backend.team_spread.bars import Minute, align
from backend.team_spread.legs import Leg

MINUTE_DELAY_SECONDS = 3    # 분이 바뀌고 이만큼 뒤에 막 끝난 봉을 받음 (live.py 와 같음)
LIVE_BARS = 10              # 장중 조회 봉 개수
GIVE_UP_SECONDS = 20        # 막 끝난 봉이 이 시간 지나도록 안 오면 그 분을 건너뜀
POLL_SECONDS = 1.0
#: 한 번에 요청하는 봉 수의 상한 — 팀이 이미 쓰는 가장 큰 요청(`live.WARMUP_BARS` 준비 봉)과 같다. 열린 세션 하나 안의 따라잡기엔 충분하다.
CHART_MAX_BARS = 1500

WAIT_CLOSED = "장 쉼"
WAIT_RUNNING = "진행 중"

#: 거래 창인 세션 상태(`backend.sessions.judge`) — 이 밖은 전부 닫힘으로 본다.
#: 국내는 주간(`day`)만: 팀의 국내 `chart_minute` 는 주간 봉만 받아(`nght_tp "1"`) 야간에 열린 다리를 기다리면 봉이 영영 안 온다(v1).
DOMESTIC_OPEN_STATES = frozenset({"day"})
OVERSEAS_OPEN_STATES = frozenset({"open", "open-2", "next-day"})


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


def order_open(feed: Feed, leg: Leg, now: datetime) -> bool:
    """그 다리로 지금 주문할 수 있나 — 장 열림(`feed.is_open`)이고, 국내 다리는 모의계좌 주문이 되는 09:00
    (`markets.DOMESTIC.session_start`) 부터. ctx 의 주문 검사·`ctx.market_open`·계좌 장부의 보내기 직전 관문·앱 정리가 이것을 쓴다."""
    if not feed.is_open(leg, now):
        return False
    return leg.market != "domestic" or to_kst(now).strftime("%H%M%S") >= markets.DOMESTIC.session_start


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
                 on_wait: Callable[[str, list[str]], None] | None = None,
                 on_gap: Callable[[str, str, str], None] | None = None,
                 on_error: Callable[[str], None] | None = None):
        self._now, self._sleep, self._adapter_of, self._judge = now, sleep, adapter_of, judge
        self._on_wait = on_wait or (lambda state, closed: None)
        self._on_gap = on_gap or (lambda first, last, cause: None)
        self._on_error = on_error or (lambda text: None)
        self._adapters: dict[str, Any] = {}
        self._last_delivered: datetime | None = None   # 돌려준(또는 공백으로 선언한) 마지막 봉의 시작 시각
        self._last_error = ""

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
            states = DOMESTIC_OPEN_STATES if leg.market == "domestic" else OVERSEAS_OPEN_STATES
            return str(self._judge(leg.market, leg.sym, now).get("state")) in states
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

    def _gap(self, first: datetime, last: datetime, cause: str) -> None:
        """건너뛴 분을 눈에 보이게 알린다 — 조용히 버리는 분은 없다."""
        self._on_gap(first.strftime("%Y%m%d %H%M%S"), last.strftime("%Y%m%d %H%M%S"), cause)

    def _minute_open(self, legs: list[Leg], start: datetime) -> bool:
        """그 분(시작 `start`)이 끝나는 순간에 모든 다리가 열려 있었나 — 15:44 봉은 15:45 에 닫혀도 온전한 봉이다."""
        end = start + timedelta(seconds=59)
        return all(self.is_open(leg, end) for leg in legs)

    def next_minute(self, legs: list[Leg], stop: threading.Event) -> Minute | None:
        """끝난 분의 맞춘 1분봉을 **빠짐없이 순서대로** 하나씩. `stop` 이 서면 None.

        처음 부르면 다음에 끝나는 분부터, 이후엔 마지막으로 돌려준 분 바로 뒤의 가장 오래된 끝난 분을 차트에서 따라잡아
        돌려준다(부르는 쪽이 느려도 분을 건너뛰지 않음). 분을 넘기는 건 돌려줄 때와 공백을 밝힐 때(`on_gap`)뿐이다.

        장 쉼: 모든 다리가 열려 있던 분은 지금 한 다리가 닫혔어도 돌려준다(닫히는 순간의 마지막 분). 더 돌려줄 분이
        없고 한 다리라도 닫혀 있으면 `on_wait("장 쉼", 쉬는 다리)` 를 한 번 부르고 기다린다. 열리면 `on_wait("진행 중", [])`
        를 부르고, 쉬던 구간 전체를 `on_gap(.., "장 쉼")` 한 번으로 밝힌 뒤 열린 뒤의 첫 분부터 돌려준다(쉬기 전 봉은 다시 주지 않음).
        조회 실패는 `on_error` 로 알리고 다음 초에 다시 한다."""
        if self._last_delivered is None:
            self._last_delivered = _closed_bar_start(self._now())     # 이 봉까지는 이미 지난 것
        waiting = False
        while not stop.is_set():
            now = self._now()
            closed = self._closed_legs(legs, now)
            if waiting and not closed:
                waiting = False
                self._on_wait(WAIT_RUNNING, [])
            target = _closed_bar_start(now)
            pending = self._last_delivered + timedelta(minutes=1)
            deliverable = pending <= target and self._minute_open(legs, pending)
            if not deliverable:
                if closed and pending > target and self._minute_open(legs, pending):
                    pass        # (아래 sleep/continue 는 `if not deliverable` 단계에 있어야 맞다 — 안쪽으로 옮기면 이 갈래가 바로 조회로 흐른다)
                    # 닫히기 직전 마지막 분이 아직 확정 전 — 그 봉을 돌려준 뒤에 쉼으로 들어간다
                elif closed:
                    if not waiting:
                        waiting = True
                        self._on_wait(WAIT_CLOSED, closed)
                elif pending <= target and self._minute_open(legs, target):
                    # 쉬는 구간이 끝났다 — 쉬던 마지막 분을 찾아 한 번에 공백으로 밝히고 그 뒤부터 센다
                    end = target
                    while end > pending and self._minute_open(legs, end):
                        end -= timedelta(minutes=1)
                    self._gap(pending, end, "장 쉼")
                    self._last_delivered = end
                    continue
                self._sleep(POLL_SECONDS, stop)
                continue
            count = min(CHART_MAX_BARS, LIVE_BARS + int((target - self._last_delivered).total_seconds() // 60))
            found: list[tuple[datetime, Minute]] = []
            try:
                for m in self._aligned(legs, count):
                    at = datetime.strptime(m.date + m.time, "%Y%m%d%H%M%S").replace(tzinfo=now.tzinfo)
                    if self._last_delivered < at <= target:
                        found.append((at, m))
                self._last_error = ""
            except Exception as e:      # 연결·응답 문제로 멈추지 않게 — 알리고 다음 초에 다시
                text = error_text(e)    # 팀: 인증 오류 문구엔 토큰이 실릴 수 있다 — 가리고(300자) 알린다(공백 까닭에도 이 글)
                if text != self._last_error:
                    self._last_error = text
                    self._on_error(text)
            if found:
                at, minute = min(found, key=lambda x: x[0])
                if at > pending:
                    self._gap(pending, at - timedelta(minutes=1), "차트에 봉 없음")
                self._last_delivered = at
                return minute
            # 봉이 안 온다 — 80초가 지난 분까지는 공백으로 밝히고 넘긴다(끝난 지 얼마 안 된 분은 더 기다림)
            stale = (now - timedelta(seconds=GIVE_UP_SECONDS + 60, microseconds=1)).replace(second=0, microsecond=0)
            end = min(stale, target)
            if end >= pending:
                cause = "봉이 오지 않음" + (f" — 마지막 조회 오류 {self._last_error}" if self._last_error else "")
                self._gap(pending, end, cause)
                self._last_delivered = end
                continue
            self._sleep(POLL_SECONDS, stop)
        return None
