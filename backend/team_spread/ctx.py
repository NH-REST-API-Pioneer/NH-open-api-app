"""스프레드 실행기에 건네는 앱 창구 `ctx` — 실행기가 시세를 보고 주문하는 유일한 길.

시세는 `Feed`, 주문은 `Book`(Task 5 가 구현) 에 맡기고, 여기서는 모든 실행기에 적용되는 안전 규칙만 맡는다.
- 멈춤(결과 모름) 뒤엔 주문·월물 교체 불가(`Halted`), 중지 뒤에도 주문·월물 교체 불가.
- 수량은 정수(`int`, 참/거짓 아님)만 — 아니면 아무것도 내기 전에 `TypeError`.
- 장이 쉬는 다리(국내 다리는 09:00 전도 — `feed.order_open`)·다리별 최대 보유·분당 주문 수 한도를 넘는 주문은 `OrderRejected`.
  최대 보유보다 큰 보유(이어받음)는 0 쪽으로 줄이는 주문만 받는다.
- `target` 은 보내기 전에 모든 다리를 미리 검사하고(반쪽 짝 방지), 뒤 다리가 거부되면 앞 다리를 한 번 되돌린다.
  결과를 모르면 되돌리지 않고 멈춘다. 되돌리기는 장부 자물쇠 안에서 그 다리 보유가 체결 직후 값 그대로일 때만 내고
  (아니면 멈춤), 앱이 끝내는 중(`closing`)이면 내지 않는다(남은 반쪽은 앱 정리가 맡거나 장부에 남아 이어받기로 보임).
- 앱이 끝내는 중(`closing` — 중지 뒤 기다림이 지나 끝내기 시작·앱 종료)이면 시세 조회(`quote`·`bars`·`next_minute`)도
  내보내지 않고 중지 거부(`OrderRejected("중지됨 …")`) — 중지를 무시하고 도는 실행기가 NH 를 계속 부르지 않게.
- `log` 는 유한한 수만(NaN·무한대는 `ValueError` — 기록·응답 JSON 을 깨지 않게), 줄에 `ctx.now()` 시각 `t` 를 붙인다.
앱 자신의 정리(중지·오류 청산)는 `Book` 을 직접 쓴다 — `Ctx` 는 중지 뒤 주문을 받지 않는 것이 설계다.
"""
from __future__ import annotations

import contextlib
import copy
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.sessions.hours import to_kst
from backend.team_pyrun.journal import Journal
from backend.team_spread.bars import Minute
from backend.team_spread.feed import Feed, Quote, order_open
from backend.team_spread.legs import Leg

DEFAULT_MAX_QTY = 5
RATE_WINDOW = timedelta(seconds=60)


class OrderRejected(Exception):
    """결과를 아는 실패 — 거부·장 닫힘·한도 초과·중지 뒤."""


class Halted(Exception):
    """멈춘 실행 — 결과를 모르는 주문이 있어 더 주문하지 않는다."""


class _Stopped(OrderRejected):
    """중지 뒤 주문(·끝내는 중의 시세 조회) — 중지는 멈춤이 아니다(`Halted` 아님). 주문·조회는 나가지 않는다."""


def _iso(at: datetime) -> str:
    return to_kst(at).replace(tzinfo=None).isoformat(timespec="seconds")


def _non_finite(obj: Any, path: str = "") -> str | None:
    """`obj`(dict·list 안까지) 에서 처음 만난 NaN·무한대 실수의 자리. 없으면 None."""
    if isinstance(obj, float):
        return None if math.isfinite(obj) else (path or "값")
    if isinstance(obj, dict):
        items = obj.items()
    elif isinstance(obj, (list, tuple)):
        items = enumerate(obj)
    else:
        return None
    for k, v in items:
        if (bad := _non_finite(v, f"{path}.{k}" if path else str(k))) is not None:
            return bad
    return None


def _check_qty(qty: Any) -> None:
    """주문 수량은 정수만 — 1.5·True 가 장부·브로커(`abs`·`str`)까지 가면 이상한 수량이 나간다."""
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise TypeError(f"주문 수량은 정수(int)여야 합니다: {qty!r}")


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
                 stop: threading.Event, roll: Callable[[str], Leg], closing: Callable[[], bool] | None = None):
        self._legs = dict(legs)
        self._feed = feed
        self._book = book
        self._journal = journal
        self._max_qty = dict(max_qty)
        self._orders_per_min = orders_per_min
        self._inherited = copy.deepcopy(inherited) if inherited is not None else None
        self._stop = stop
        self._roll = roll
        #: 앱이 끝내는 중인가(`SpreadRun` 이 줌) — 되돌리기를 건너뛰고 시세 조회를 내보내지 않는다
        self._closing = closing or (lambda: False)
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

    def _check_data(self) -> None:
        """앱이 끝내는 중이면 시세 조회도 내보내지 않는다(중지를 무시하는 실행기가 NH 를 계속 부르지 않게)."""
        if self._closing():
            raise _Stopped("중지됨 — 실행이 끝나 시세를 조회하지 않습니다")

    def bars(self, legs: list[Leg | str], count: int) -> list[Minute]:
        self._check_data()
        return self._feed.history([self._leg(x) for x in legs], count)

    def next_minute(self, legs: list[Leg | str]) -> Minute | None:
        self._check_data()
        return self._feed.next_minute([self._leg(x) for x in legs], self._stop)

    def quote(self, leg: Leg | str) -> Quote:
        self._check_data()
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
        """그 다리로 지금 주문할 수 있나(국내 다리는 09:00 부터 — 주간 판정 08:45~08:59 는 봉만 옴)."""
        return order_open(self._feed, self._leg(leg), self._feed.now())

    def log(self, name: str, value: float, **fields: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"log 값은 수여야 합니다: {name}={value!r}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"log 값은 유한한 수여야 합니다(NaN·무한대 아님): {name}={value!r}")
        if (bad := _non_finite(fields)) is not None:
            raise ValueError(f"log 칸에 NaN·무한대가 있습니다: {name} · {bad}")
        if "t" in fields:
            raise ValueError("log 칸 이름 t 는 앱이 씁니다(ctx.now() 시각) — 다른 이름을 쓰세요")
        self._journal.write("log", name=name, value=value, **fields, t=_iso(self._feed.now()))

    def roll(self, name: str) -> Leg:
        self._check_state()
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

    def _check_leg(self, leg: Leg, held_before: int, held_after: int) -> None:
        now = self._feed.now()
        if not order_open(self._feed, leg, now):
            if leg.market == "domestic" and self._feed.is_open(leg, now):
                raise OrderRejected(f"주문 시간 전: {leg.name} — 국내 모의계좌 주문은 09:00 부터")
            raise OrderRejected(f"장 쉼: {leg.name}")
        limit = self._max_qty.get(leg.name, DEFAULT_MAX_QTY)
        # 한도보다 큰 보유(이어받음)는 0 쪽으로 줄이는 주문만 — 0 을 넘어 반대쪽으로 한도 밖은 새 노출이라 거부
        reducing = held_before != 0 and abs(held_after) <= abs(held_before) and held_after * held_before >= 0
        if abs(held_after) > limit and not reducing:
            raise OrderRejected(f"최대 보유 초과: {leg.name} {held_after} (한도 {limit})")

    def _check_rate(self, extra: int = 1) -> None:
        if self._recent(self._feed.now()) + extra > self._orders_per_min:
            raise OrderRejected(f"분당 주문 한도({self._orders_per_min}) 초과")

    def _lock(self) -> Any:
        """장부 자물쇠(재진입 가능) — 체결과 그 직후 보유 읽기·되돌리기 직전 보유 확인을 앱의 정리와 섞지 않게. 없으면 빈 것."""
        lock = getattr(self._book, "lock", None)
        return lock if lock is not None else contextlib.nullcontext()

    def _send(self, leg: Leg, qty: int, why: str) -> Fill:
        """실행기가 낸 주문 하나 — 모든 검사 뒤 장부로. 검사부터 보내기까지 장부 자물쇠 안 — 앱이 끝내기를 시작해
        (중지 표시 뒤) 보유를 읽은 다음에 검사를 통과한 주문이 끼어들지 않게."""
        _check_qty(qty)
        with self._lock():
            self._check_state()
            held = self._book.position(leg)
            self._check_leg(leg, held, held + qty)
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
        _check_qty(qty)
        if qty == 0:
            return None
        return self._send(self._leg(leg), qty, "order")

    def target(self, mapping: dict[Leg | str, int]) -> list[Fill]:
        self._check_state()
        wants: list[tuple[Leg, int]] = []
        for key, want in mapping.items():
            leg = self._leg(key)
            _check_qty(want)
            wants.append((leg, want))
        steps: list[tuple[Leg, int]] = []
        for leg, want in wants:
            diff = want - self._book.position(leg)
            if diff:
                steps.append((leg, diff))
        # 보내기 전에 모두 검사 — 하나라도 안 되면 아무것도 내지 않는다
        for leg, diff in steps:
            held = self._book.position(leg)
            self._check_leg(leg, held, held + diff)
        self._check_rate(len(steps))
        done: list[tuple[Fill, int]] = []     # (체결, 그 체결 직후 그 다리 보유)
        for leg, diff in steps:
            try:
                with self._lock():
                    fill = self._send(leg, diff, "target")
                    after = self._book.position(leg)
            except OrderRejected as e:
                if done:
                    self._revert(done, e)
                raise
            done.append((fill, after))
        return [f for f, _ in done]

    def _revert(self, done: list[tuple[Fill, int]], cause: Exception) -> None:
        """이번 target 에서 체결된 다리를 반대로 한 번 — 한도·분당 수에 걸리지 않는다. 안 되면 멈춤.

        장부 자물쇠 안에서 그 다리 보유가 체결 직후 값 그대로일 때만 낸다 — 그 사이 앱 정리가 그 다리를 이미 움직였으면
        눈먼 반대 주문이 반대 보유를 만든다(내지 않고 멈춤). 앱이 끝내는 중이면 내지 않는다(남은 반쪽은 앱 정리가 맡거나
        장부에 남아 끝난 실행의 `inheritable` 로 보인다, 판정 R21)."""
        failed: list[str] = []
        skipped: list[str] = []
        for f, after in reversed(done):
            if f.qty == 0:
                continue
            leg = self._leg(f.leg)
            with self._lock():
                if self._closing():
                    skipped.append(f.leg)
                    continue
                held = self._book.position(leg)
                if held != after:
                    reason = (f"되돌리기 건너뜀 — {f.leg} 보유가 체결 뒤 {after:+d} 에서 {held:+d} 로 바뀜 "
                              "(반대 주문을 내지 않음, 계좌를 확인하세요)")
                    self._journal.write("event", text=reason)
                    self._halt(reason)
                    raise Halted(reason) from cause
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
        if skipped:
            self._journal.write("event", text=f"되돌리기 건너뜀 — 앱이 끝내는 중 · {', '.join(skipped)} 보유는 그대로 "
                                              "(앱 정리가 맡거나, 앱 종료면 이어받기로)")
        self._journal.write("revert", legs=[f.leg for f, _ in done], cause=str(cause), failed=failed, skipped=skipped)
        if failed:
            reason = "되돌리기 거부 — " + "; ".join(failed)
            self._halt(reason)
            raise Halted(reason) from cause
