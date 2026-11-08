"""스프레드 실행기에 건네는 앱 창구 `ctx` — 실행기가 시세를 보고 주문하는 유일한 길.

시세는 `Feed`, 주문은 `Book`(Task 5 가 구현) 에 맡기고, 여기서는 모든 실행기에 적용되는 안전 규칙만 맡는다.
- 멈춤(결과 모름) 뒤엔 주문 불가(`Halted`), 중지 뒤에도 주문 불가.
- 장이 쉬는 다리·다리별 최대 보유·분당 주문 수 한도를 넘는 주문은 `OrderRejected`.
- `target` 은 보내기 전에 모든 다리를 미리 검사하고(반쪽 짝 방지), 뒤 다리가 거부되면 앞 다리를 한 번 되돌린다.
  결과를 모르면 되돌리지 않고 멈춘다.
앱 자신의 정리(중지·오류 청산)는 `Book` 을 직접 쓴다 — `Ctx` 는 중지 뒤 주문을 받지 않는 것이 설계다.
"""
from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.team_pyrun.journal import Journal
from backend.team_spread.bars import Minute
from backend.team_spread.feed import Feed, Quote
from backend.team_spread.legs import Leg

DEFAULT_MAX_QTY = 5
RATE_WINDOW = timedelta(seconds=60)


class OrderRejected(Exception):
    """결과를 아는 실패 — 거부·장 닫힘·한도 초과·중지 뒤."""


class Halted(Exception):
    """멈춘 실행 — 결과를 모르는 주문이 있어 더 주문하지 않는다."""


class _Stopped(OrderRejected):
    """중지 뒤 주문 — 중지는 멈춤이 아니다(`Halted` 아님). 주문은 나가지 않는다."""


@dataclass(frozen=True)
class Fill:
    """체결 결과 — qty = 실제 체결 수량, 부호 = 방향(매수 +). 되돌리기가 이 부호에 기댄다.

    `price_known` 이 False 면 체결가를 읽지 못해 `price` 는 기준가(주문 때 가장 신선한 양의 값)다 — 체결가로 믿지 말 것."""
    leg: str
    qty: int
    price: float
    fee: float | None
    price_known: bool = True


class Book(Protocol):
    """주문 장부 — 거부면 `OrderRejected`, 결과 모름이면 `Halted`(장부가 스스로 멈춤 상태).

    멈춤 상태의 단일 근원은 장부다(`halted`, `halt(reason)`). 반환 `Fill.qty` 는 실제 체결 수량이며 부호 = 방향(매수 +).
    """

    @property
    def halted(self) -> str | None: ...
    def halt(self, reason: str) -> None: ...
    def position(self, leg: Leg) -> int: ...
    def order(self, leg: Leg, qty: int, why: str) -> Fill: ...


class Ctx:
    def __init__(self, legs: dict[str, Leg], feed: Feed, book: Book, journal: Journal, *,
                 max_qty: dict[str, int], orders_per_min: int, inherited: dict | None,
                 stop: threading.Event, roll: Callable[[str], Leg]):
        self._legs = dict(legs)
        self._feed = feed
        self._book = book
        self._journal = journal
        self._max_qty = dict(max_qty)
        self._orders_per_min = orders_per_min
        self._inherited = copy.deepcopy(inherited) if inherited is not None else None
        self._stop = stop
        self._roll = roll
        self._sent: list[datetime] = []     # 실행기가 시도한 주문 시각 (분당 한도)

    # ── 다리·시세 ────────────────────────────────────────────
    def _leg(self, leg: Leg | str) -> Leg:
        name = leg.name if isinstance(leg, Leg) else leg
        try:
            cur = self._legs[name]
        except KeyError:
            raise KeyError(f"다리 「{name}」 이 없습니다") from None
        if isinstance(leg, Leg) and leg != cur:
            raise OrderRejected(f"낡은 다리 「{name}」 ({leg.sym}) — 지금은 {cur.sym}, ctx.leg 로 다시 받으세요")
        return cur

    def leg(self, name: str) -> Leg:
        return self._leg(name)

    def bars(self, legs: list[Leg | str], count: int) -> list[Minute]:
        return self._feed.history([self._leg(x) for x in legs], count)

    def next_minute(self, legs: list[Leg | str]) -> Minute | None:
        return self._feed.next_minute([self._leg(x) for x in legs], self._stop)

    def quote(self, leg: Leg | str) -> Quote:
        return self._feed.quote(self._leg(leg))

    def position(self, leg: Leg | str) -> int:
        return self._book.position(self._leg(leg))

    @property
    def inherited(self) -> dict | None:
        return copy.deepcopy(self._inherited) if self._inherited is not None else None

    # ── 시계·상태 ────────────────────────────────────────────
    def running(self) -> bool:
        return not self._stop.is_set() and self._halted() is None

    def now(self) -> datetime:
        return self._feed.now()

    def sleep(self, seconds: float) -> None:
        self._feed.sleep(seconds, self._stop)

    def market_open(self, leg: Leg | str) -> bool:
        return self._feed.is_open(self._leg(leg), self._feed.now())

    def log(self, name: str, value: float, **fields: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"log 값은 수여야 합니다: {name}={value!r}")
        self._journal.write("log", name=name, value=value, **fields)

    def roll(self, name: str) -> Leg:
        old = self._leg(name)
        name = old.name
        if self._book.position(old) != 0:
            raise OrderRejected(f"{name} 보유가 0 이 아니라 월물을 바꿀 수 없습니다")
        new = self._roll(name)
        self._legs[name] = new
        self._journal.write("roll", leg=name, old=old.sym, new=new.sym)
        return new

    # ── 주문 ────────────────────────────────────────────────
    def _halted(self) -> str | None:
        return self._book.halted

    def _halt(self, reason: str) -> None:
        if self._book.halted is None:
            self._book.halt(reason)
        self._journal.write("halt", reason=reason)

    def _recent(self, now: datetime) -> int:
        self._sent = [t for t in self._sent if now - t < RATE_WINDOW]
        return len(self._sent)

    def _check_state(self) -> None:
        reason = self._halted()
        if reason is not None:
            raise Halted(f"멈춤: {reason}")
        if self._stop.is_set():
            raise _Stopped("중지됨")

    def _check_leg(self, leg: Leg, held_after: int) -> None:
        if not self._feed.is_open(leg, self._feed.now()):
            raise OrderRejected(f"장 쉼: {leg.name}")
        limit = self._max_qty.get(leg.name, DEFAULT_MAX_QTY)
        if abs(held_after) > limit:
            raise OrderRejected(f"최대 보유 초과: {leg.name} {held_after} (한도 {limit})")

    def _check_rate(self, extra: int = 1) -> None:
        if self._recent(self._feed.now()) + extra > self._orders_per_min:
            raise OrderRejected(f"분당 주문 한도({self._orders_per_min}) 초과")

    def _send(self, leg: Leg, qty: int, why: str) -> Fill:
        """실행기가 낸 주문 하나 — 모든 검사 뒤 장부로."""
        self._check_state()
        self._check_leg(leg, self._book.position(leg) + qty)
        self._check_rate()
        self._sent.append(self._feed.now())
        try:
            fill = self._book.order(leg, qty, why)
        except OrderRejected:
            raise
        except Halted as e:
            self._halt(str(e) or "결과 모름")
            raise
        except Exception as e:     # 그 밖의 오류는 결과 모름
            self._halt(f"주문 결과 모름: {e!r}")
            raise Halted(f"주문 결과 모름: {e!r}") from e
        if fill.leg != leg.name or fill.qty * qty < 0:
            self._halt(f"체결 결과가 요청과 맞지 않음: 요청 {leg.name} {qty}, 체결 {fill.leg} {fill.qty}")
            raise Halted(self._halted() or "체결 결과 이상")
        return fill

    def order(self, leg: Leg | str, qty: int) -> Fill | None:
        if qty == 0:
            return None
        return self._send(self._leg(leg), qty, "order")

    def target(self, mapping: dict[Leg | str, int]) -> list[Fill]:
        self._check_state()
        steps: list[tuple[Leg, int]] = []
        for key, want in mapping.items():
            leg = self._leg(key)
            diff = want - self._book.position(leg)
            if diff:
                steps.append((leg, diff))
        # 보내기 전에 모두 검사 — 하나라도 안 되면 아무것도 내지 않는다
        for leg, diff in steps:
            self._check_leg(leg, self._book.position(leg) + diff)
        self._check_rate(len(steps))
        fills: list[Fill] = []
        for leg, diff in steps:
            try:
                fills.append(self._send(leg, diff, "target"))
            except OrderRejected as e:
                if fills:
                    self._revert(fills, e)
                raise
        return fills

    def _revert(self, fills: list[Fill], cause: Exception) -> None:
        """이번 target 에서 체결된 다리를 반대로 한 번 — 한도·분당 수에 걸리지 않는다. 안 되면 멈춤."""
        failed: list[str] = []
        for f in reversed(fills):
            if f.qty == 0:
                continue
            leg = self._leg(f.leg)
            try:
                self._book.order(leg, -f.qty, "revert")
            except OrderRejected as e:
                failed.append(f"{f.leg}: {e}")
            except Halted as e:
                self._halt(str(e) or "되돌리기 결과 모름")
                raise
            except Exception as e:
                self._halt(f"되돌리기 결과 모름: {e!r}")
                raise Halted(f"되돌리기 결과 모름: {e!r}") from e
        self._journal.write("revert", legs=[f.leg for f in fills], cause=str(cause), failed=failed)
        if failed:
            reason = "되돌리기 거부 — " + "; ".join(failed)
            self._halt(reason)
            raise Halted(reason) from cause
