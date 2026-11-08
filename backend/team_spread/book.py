"""스프레드 주문 장부 — 종이(`PaperBook`)와 모의 계좌(`AccountBook`). `Ctx` 의 모든 주문이 여기로 온다.

- 멈춤 상태의 단일 근원은 장부다. 한 번 멈추면 **모든 다리**의 `order` 가 브로커를 부르지 않고 `Halted`.
- `Fill.qty` 는 실제 체결 수량(부호 = 방향). 요청 수량보다 클 수 없다 — 브로커는 통째로 체결하거나 `None`.
- 주문·대조·잔고 읽기는 한 자물쇠 아래서 차례로 한다(앱의 정리·대조가 다른 스레드에서 와도 나가는 주문과 섞이지 않게).

`AccountBook` 은 다리마다 `MockAccountBroker` 를 하나씩 둔다(그 다리 시장 어댑터·거래소 코드·종목). 브로커가 `None` 을 돌려주면
`live.py`·`realtime.py` 와 같은 규칙으로 읽는다(`broker.py` 모듈 설명).
- 보내기 직전 휴장(`held_back`) → 안 보냄이 확실 → `OrderRejected`
- 결과 모름(`unknown`·`open_unknowns`) → 그 다리 잔고를 본다. `explains(잔고)` 면 잔고를 따라 `Fill`(가격은 기준가), 아니면 멈춤 + `Halted`
- 안 보냈는데 알려진 거절도 아님(잔고 관문에 걸림 등) → 잔고가 기대와 다르거나 못 읽은 것 → 멈춤 + `Halted`
- 보냈고 서버가 거부·취소를 확인함 → `OrderRejected`
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from types import ModuleType
from typing import Any

from backend.sessions.hours import now_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun.broker import MockAccountBroker, error_text
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, Market, adapter_for
from backend.team_spread.ctx import Fill, Halted, OrderRejected
from backend.team_spread.feed import Feed
from backend.team_spread.legs import Leg, LegError


def market_of_leg(leg: Leg) -> Market:
    return DOMESTIC if leg.market == "domestic" else OVERSEAS


def _clock(at: datetime) -> str:
    return at.strftime("%H%M%S")


class _BookBase:
    def __init__(self, feed: Feed, journal: Journal, *, positions: dict[str, int] | None = None):
        self._feed, self._journal = feed, journal
        self._pos: dict[str, int] = dict(positions or {})     # 다리 이름 → 순보유
        self._halted: str | None = None
        #: 주문·대조·잔고 읽기를 차례로. 브로커가 주문 도중 `halt` 를 부르므로 재진입 가능해야 한다
        self.lock = threading.RLock()

    @property
    def halted(self) -> str | None:
        return self._halted

    def halt(self, reason: str) -> None:
        """멈춤 — 처음 까닭을 지킨다. 락 없이 불러도 안전(문자열 대입 하나)."""
        if self._halted is None:
            self._halted = reason
            self._journal.write("event", text=f"장부 멈춤 · {reason}")

    def position(self, leg: Leg) -> int:
        return self._pos.get(leg.name, 0)

    def _opposite(self, leg: Leg, qty: int) -> tuple[float, bool]:
        """주문 순간 시세의 반대 호가(매수 ask·매도 bid). 없으면 마지막 체결가 ∓ 슬리피지 틱. (가격, 호가였나)"""
        try:
            q = self._feed.quote(leg)
        except Exception as e:      # 아직 아무것도 보내지 않았다
            raise OrderRejected(f"{leg.name} 시세를 받지 못함 ({error_text(e)})") from e
        buy = qty > 0
        px = q.ask if buy else q.bid
        if px is not None:
            return float(px), True
        if q.last is None:
            raise OrderRejected(f"{leg.name} 시세가 없어 주문하지 않음")
        slip = market_of_leg(leg).paper_slip_ticks * leg.tick
        return float(q.last) + (slip if buy else -slip), False

    def _check(self, qty: int) -> None:
        if self._halted is not None:
            raise Halted(self._halted)
        if qty == 0:
            raise OrderRejected("수량 0 주문")


class PaperBook(_BookBase):
    """종이 장부 — 체결가 = 반대 호가(없으면 마지막 ∓ 1틱), 수수료 = 시장별 종이 값 × 계약 수."""

    def order(self, leg: Leg, qty: int, why: str) -> Fill:
        with self.lock:
            self._check(qty)
            px, from_quote = self._opposite(leg, qty)
            fee = market_of_leg(leg).paper_fee * abs(qty)
            self._pos[leg.name] = self.position(leg) + qty
            self._journal.write("fill", clock=_clock(self._feed.now()), leg=leg.name, qty=qty, price=px, fee=fee,
                                source="paper", text=f"종이 체결({'반대 호가' if from_quote else '마지막 체결가 ∓ 슬리피지'}) · {why}")
            return Fill(leg.name, qty, px, fee)


class AccountBook(_BookBase):
    """모의 계좌 장부 — 다리마다 `MockAccountBroker`. 주문은 한 번만, 결과를 모르면 멈춘다."""

    def __init__(self, legs: dict[str, Leg], feed: Feed, journal: Journal, *, api_module: ModuleType | Any = default_api,
                 sleep: Callable[[float], None] | None = None, today: str | None = None,
                 positions: dict[str, int] | None = None, now: Callable[[], datetime] = now_kst):
        super().__init__(feed, journal, positions=positions)
        self._legs = dict(legs)
        self._api, self._today, self._now = api_module, today, now
        self._sleep = sleep
        self._brokers: dict[tuple[str, str], MockAccountBroker] = {}

    def set_leg(self, leg: Leg) -> None:
        """월물 교체 등으로 다리가 바뀜 — 이후 주문·대조는 새 종목으로."""
        with self.lock:
            self._legs[leg.name] = leg

    def _broker(self, leg: Leg) -> MockAccountBroker:
        key = (leg.name, leg.sym)
        if key not in self._brokers:
            market = market_of_leg(leg)
            adapter = (adapter_for(market, self._api, exch_cd=leg.exchange, cur_cd=leg.currency)
                       if market is OVERSEAS else adapter_for(market, self._api))
            kw: dict[str, Any] = {} if self._sleep is None else {"sleep": self._sleep}
            self._brokers[key] = MockAccountBroker(
                adapter, leg.sym, self._journal, today=self._today, expected=lambda n=leg.name: self._pos.get(n, 0),
                halt=self.halt, **kw)
        return self._brokers[key]

    # ── 주문 ────────────────────────────────────────────────
    def order(self, leg: Leg, qty: int, why: str) -> Fill:
        with self.lock:
            self._check(qty)
            ref, _ = self._opposite(leg, qty)
            b = self._broker(leg)
            side = "buy" if qty > 0 else "sell"
            clock = _clock(self._now())
            try:
                px = b.fill(side, ref, clock, why, qty=abs(qty))
            except Exception as e:      # 브로커 안의 뜻밖의 오류 — 주문이 나갔는지 모른다
                self.halt(f"{leg.name} 주문 처리 중 오류 — 결과 모름 ({error_text(e)})")
                raise Halted(self._halted) from e
            if px is not None:
                fee = b.last_fill_fee
                self._pos[leg.name] = self.position(leg) + qty
                return Fill(leg.name, qty, px, fee)
            return self._no_fill(leg, b, qty, ref, clock, why)

    def _no_fill(self, leg: Leg, b: MockAccountBroker, qty: int, ref: float, clock: str, why: str) -> Fill:
        """브로커가 `None` — 위 모듈 설명의 규칙으로 읽는다."""
        if self._halted is not None:        # 브로커가 스스로 멈춤(일부 체결 가능 등)
            raise Halted(self._halted)
        if b.held_back:
            raise OrderRejected(f"{leg.name} 주문 보류 — 보내기 직전 휴장 시작 (보내지 않음)")
        unknown = b.unknown or b.open_unknowns() is not None
        if not unknown:
            if b.sent:
                b.needs_check = False
                raise OrderRejected(f"{leg.name} 주문 거부됨 · {why}")
            self._stop(f"{leg.name} 주문 전 잔고 관문에 걸림 — 잔고가 기대와 다르거나 읽지 못함")
        held = b.position()
        pre = self.position(leg)
        if held is None:
            self._stop(f"{leg.name} 결과를 모르는 주문 뒤 잔고를 읽지 못함")
        moved = held - pre
        if not b.explains(held) or moved == 0 or (moved > 0) != (qty > 0) or abs(moved) > abs(qty):
            self._stop(f"{leg.name} 결과를 모르는 주문 — 잔고 {held:+d} (기대 {pre:+d}) 가 그 주문으로 설명되지 않음")
        b.unknown = b.needs_check = False
        self._pos[leg.name] = held
        self._journal.write("event", clock=clock, leg=leg.name, qty=moved, price=ref,
                            text=f"결과를 모르던 주문이 잔고({held:+d})에 반영됨 — 잔고를 따름, 체결가는 기준가 {ref}")
        return Fill(leg.name, moved, ref, b.last_fill_fee)

    def _stop(self, reason: str) -> None:
        self.halt(reason)
        raise Halted(self._halted)

    # ── 잔고 ────────────────────────────────────────────────
    def balances(self) -> dict[str, int]:
        """모든 다리의 계좌 순보유. 하나라도 못 읽으면 `LegError`(호출자가 시작을 거절한다)."""
        with self.lock:
            got: dict[str, int] = {}
            for name, leg in self._legs.items():
                held = self._broker(leg).position()
                if held is None:
                    raise LegError(f"{name}({leg.sym}) 계좌 잔고를 읽지 못했습니다")
                got[name] = held
            return got

    def reconcile(self) -> str | None:
        """계좌 잔고와 장부 보유를 대조 — 다르면 멈추고 까닭을 돌려준다. 같거나 못 읽으면 None(못 읽음은 기록만)."""
        with self.lock:
            if self._halted is not None:
                return self._halted
            for name, leg in self._legs.items():
                held = self._broker(leg).position()
                if held is None:
                    self._journal.write("event", text=f"{name} 잔고 대조 못 함 — 읽지 못함")
                    continue
                exp = self.position(leg)
                if held != exp:
                    reason = f"잔고 불일치 · {name} 기대 {exp:+d} · 계좌 {held:+d}"
                    self.halt(reason)
                    return reason
            return None
