"""스프레드 주문 장부 — 종이(`PaperBook`)와 모의 계좌(`AccountBook`). `Ctx` 의 모든 주문이 여기로 온다.

- 멈춤 상태의 단일 근원은 장부다. 한 번 멈추면 **모든 다리**의 `order` 가 브로커를 부르지 않고 `Halted`.
- `Fill.qty` 는 실제 체결 수량(부호 = 방향). 요청 수량보다 클 수 없다 — 브로커는 통째로 체결하거나 `None`.
- 주문·대조·잔고 읽기는 한 자물쇠 아래서 차례로 한다(앱의 정리·대조가 다른 스레드에서 와도 나가는 주문과 섞이지 않게).

`AccountBook` 은 다리마다 `MockAccountBroker` 를 하나씩 둔다(그 다리 시장 어댑터·거래소 코드·종목). 브로커가 `None` 을 돌려주면
`live.py`·`realtime.py` 와 같은 규칙으로 읽는다(`broker.py` 모듈 설명).
- 보내기 직전 휴장(`held_back`, 관문은 `feed.order_open` — 국내 다리는 09:00 전도 휴장) → 안 보냄이 확실 → `OrderRejected`
- 결과 모름(`open_unknowns()` 가 있음) → 그 다리 잔고를 본다. `explains(잔고)` 면 잔고를 따라 `Fill`(가격은 기준가), 아니면 멈춤 + `Halted`
- 그 밖(서버 거부·취소, 잔고 관문에 걸려 안 보냄 등) → 그 다리 잔고를 다시 읽는다. 읽지 못하거나 장부와 다르면 멈춤 + `Halted`,
  장부와 같으면 `OrderRejected`(짝 주문이 앞 다리를 되돌릴 수 있게)
- 계좌 주문은 시세 없이도 나간다(시장가) — 기준가는 반대 호가 → 마지막 체결가 → 직전 기준가 → 마지막 봉 종가 순.
- 수수료는 (시장, 통화)마다 예수금 fee 누적 하나를 모든 다리가 나눠 쓰며, 자물쇠 안에서 차례로 차이를 낸다.
  예수금(하루 누적)의 날짜는 주문 순간 `now()` 의 한국 날짜를 따르고, 날이 바뀌면 그날 누적을 다시 읽어 심는다(판정 R18 —
  실행은 날을 넘겨 돈다. 시작 날로 묶어 두면 다음 날 체결의 fee 차이가 0·낡은 값이 된다).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from types import ModuleType
from typing import Any

from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun.broker import MockAccountBroker, error_text
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, Market, adapter_for
from backend.team_spread.ctx import Fill, Halted, OrderRejected
from backend.team_spread.feed import Feed, order_open
from backend.team_spread.legs import Leg, LegError


def market_of_leg(leg: Leg) -> Market:
    return DOMESTIC if leg.market == "domestic" else OVERSEAS


def _clock(at: datetime) -> str:
    return at.strftime("%H%M%S")


class _LegJournal:
    """브로커가 쓰는 기록에 다리 이름·종목을 붙이는 대리 — 공유 기록에서 어느 다리 줄인지 보이게.
    체결 줄의 `price_read` 도 기억한다(체결가를 못 읽어 기준가로 적었는지).

    체결 줄에는 종이·잔고 줄과 같은 칸을 더 붙인다 — `qty`(부호 있는 이번 주문 수량, 매수 +; 브로커는 통째로 체결만 체결로
    보므로 주문 수량 = 체결 수량)와 `price_known`(체결가를 읽었나). 화면의 체결 표·차트가 이 칸을 본다."""

    def __init__(self, journal: Journal, leg: Leg):
        self._journal, self._leg = journal, leg
        self.price_read: bool | None = None
        self.qty: int | None = None         # 지금 나가는 주문의 부호 있는 수량 (`AccountBook.order` 가 채움)

    def write(self, kind: str, **data: Any) -> dict:
        if kind == "fill":
            self.price_read = data.get("price_read")
            if self.qty is not None:
                data.setdefault("qty", self.qty)
            data.setdefault("price_known", data.get("price_read") is not False)
        return self._journal.write(kind, leg=self._leg.name, sym=self._leg.sym, **data)


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
        if px is not None and px > 0:       # 0 이하(0 으로 채운 칸 포함)는 없는 값
            return float(px), True
        if q.last is None or q.last <= 0:
            raise OrderRejected(f"{leg.name} 시세가 없어 주문하지 않음")
        slip = market_of_leg(leg).paper_slip_ticks * leg.tick
        return float(q.last) + (slip if buy else -slip), False

    def _tag(self, leg: Leg) -> str:
        return f"{leg.name}({leg.sym})"

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
        self._fees: dict[tuple[str, str], float | None] = {}     # (시장, 통화) → 예수금 fee 누적 (다리들이 나눠 씀)
        self._fee_day: dict[tuple[str, str], str] = {}           # (시장, 통화) → 그 누적을 읽은 예수금 날짜
        self._last_ref: dict[str, float] = {}                    # 다리 이름 → 마지막으로 쓴 (양의) 기준가
        self._legj: dict[tuple[str, str], _LegJournal] = {}

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
            self._legj[key] = _LegJournal(self._journal, leg)
            self._brokers[key] = MockAccountBroker(
                adapter, leg.sym, self._legj[key], today=self._today or self._day(),
                expected=lambda n=leg.name: self._pos.get(n, 0),
                halt=lambda r, lg=leg: self.halt(f"{self._tag(lg)} {r}"),
                may_send=lambda lg=leg: order_open(self._feed, lg, self._feed.now()), **kw)
            self._seed_fee(leg)
        return self._brokers[key]

    def _day(self) -> str:
        """예수금 날짜 — 지금(`now()`)의 한국 날짜."""
        return to_kst(self._now()).strftime("%Y%m%d")

    def _seed_fee(self, leg: Leg) -> None:
        """live.py 의 account_start 처럼 시작 fee 를 심는다 — (시장, 통화)·예수금 날짜마다 한 번. 못 읽으면 None(다음에 다시)."""
        fk = self._fee_key(leg)
        b = self._brokers[(leg.name, leg.sym)]
        if self._fees.get(fk) is None or self._fee_day.get(fk) != b.today:
            snap = b.account()
            self._fees[fk] = snap["fee"] if snap else None
            self._fee_day[fk] = b.today

    @staticmethod
    def _fee_key(leg: Leg) -> tuple[str, str]:
        return (leg.market, leg.currency)

    def _ref_price(self, leg: Leg, qty: int) -> float | None:
        """계좌 주문의 기준가 — 시세를 못 받아도 거절하지 않는다(시장가라 값이 필요 없고, 되돌리기가 막히면 한 다리만 남는다).
        가장 신선한 양의 값: 지금 시세 → 마지막 봉 종가 → 마지막으로 쓴 기준가. 없으면 None (0 이하는 쓰지 않는다)."""
        try:
            px: float | None = self._opposite(leg, qty)[0]
        except Exception:
            px = None
        if px is None:
            try:
                bars = self._feed.history([leg], 1)
                close = float(bars[-1].legs[leg.name].close) if bars else None
                px = close if close is not None and close > 0 else None
            except Exception:
                px = None
        if px is None:
            px = self._last_ref.get(leg.name)
        if px is not None and px > 0:
            self._last_ref[leg.name] = px
            return px
        return None

    # ── 주문 ────────────────────────────────────────────────
    def order(self, leg: Leg, qty: int, why: str) -> Fill:
        with self.lock:
            self._check(qty)
            ref = self._ref_price(leg, qty)
            b = self._broker(leg)
            lj = self._legj[(leg.name, leg.sym)]
            lj.price_read, lj.qty = None, qty
            fk = self._fee_key(leg)
            side = "buy" if qty > 0 else "sell"
            clock = _clock(self._now())
            try:
                self._fee_today(b, leg, fk)
                px = b.fill(side, ref if ref is not None else 0.0, clock, why, qty=abs(qty))
            except Exception as e:      # 브로커 안의 뜻밖의 오류 — 주문이 나갔는지 모른다
                self._stop(f"{self._tag(leg)} 주문 처리 중 오류 — 결과 모름 ({error_text(e)})", e)
            if b.last_fee is not None:
                self._fees[fk] = b.last_fee
            if px is not None:
                self._pos[leg.name] = self.position(leg) + qty
                known = lj.price_read is not False
                if not known and ref is None:       # 체결가를 못 읽었는데 기준가도 없다 — 0.0 을 전략에 주지 않는다
                    self._journal.write("event", clock=clock, leg=leg.name, sym=leg.sym, qty=qty, fee=b.last_fill_fee,
                                        text=f"체결 {self._tag(leg)} {qty:+d} · {why} — 체결가 모름")
                    self._stop(f"체결가 모름 · {self._tag(leg)} (잔고는 따름)")
                self._journal.write("event", clock=clock, leg=leg.name, sym=leg.sym, qty=qty, price=px, fee=b.last_fill_fee,
                                    price_known=known, text=f"체결 {self._tag(leg)} {qty:+d} · {why}")
                return Fill(leg.name, qty, px, b.last_fill_fee, known)
            return self._no_fill(leg, b, qty, ref, clock, why)

    def _fee_today(self, b: MockAccountBroker, leg: Leg, fk: tuple[str, str]) -> None:
        """주문 전 — 예수금 날짜를 오늘로, 날이 바뀌었으면 그날 누적을 다시 심고(판정 R18), 다른 다리가 올린 fee 까지 포함한
        그날 누적에서 차이를 내게 브로커에 넣는다(모르면 None — 이 체결 수수료도 모름)."""
        day = self._day()
        if b.today != day or self._fee_day.get(fk) != day:
            b.today = day
            self._journal.write("event", leg=leg.name, sym=leg.sym, text=f"예수금 날짜 {day} — 수수료 누적을 그날 값으로 다시 읽음")
            self._seed_fee(leg)
        b.last_fee = self._fees.get(fk)

    def _no_fill(self, leg: Leg, b: MockAccountBroker, qty: int, ref: float | None, clock: str, why: str) -> Fill:
        """브로커가 `None` — 위 모듈 설명의 규칙으로 읽는다(`realtime._no_fill` 과 같게 `open_unknowns()` 로 가른다)."""
        tag = self._tag(leg)
        if self._halted is not None:        # 브로커가 스스로 멈춤(일부 체결 가능 등)
            raise Halted(self._halted)
        if b.held_back:
            raise OrderRejected(f"{tag} 주문 보류 — 보내기 직전 장이 닫힘 (보내지 않음)")
        held = b.position()
        pre = self.position(leg)
        if b.open_unknowns() is None:
            b.unknown = b.needs_check = False
            if held is None:
                self._stop(f"{tag} 주문 뒤 잔고를 읽지 못함")
            if held != pre:
                self._stop(f"{tag} 잔고 불일치 · 기대 {pre:+d} · 계좌 {held:+d}")
            raise OrderRejected(f"{tag} 주문 안 됨 · {why}")
        if held is None:
            self._stop(f"{tag} 결과를 모르는 주문 뒤 잔고를 읽지 못함")
        moved = held - pre
        if not b.explains(held) or moved == 0 or (moved > 0) != (qty > 0) or abs(moved) > abs(qty):
            self._stop(f"{tag} 결과를 모르는 주문 — 잔고 {held:+d} (기대 {pre:+d}) 가 그 주문으로 설명되지 않음")
        b.unknown = b.needs_check = False
        self._pos[leg.name] = held
        if ref is None:         # 체결가도 기준가도 모른다 — 보유는 따르되 전략에 0.0 을 주지 않고 멈춘다
            self._journal.write("fill", clock=clock, leg=leg.name, sym=leg.sym, qty=moved, fee=b.last_fill_fee,
                                source="balance", price_known=False, text=f"결과를 모르던 주문이 잔고({held:+d})에 반영됨 — 체결가 모름")
            self._stop(f"체결가 모름 · {tag} (잔고는 따름)")
        self._journal.write("fill", clock=clock, leg=leg.name, sym=leg.sym, qty=moved, price=ref, fee=b.last_fill_fee,
                            source="balance", price_known=False,
                            text=f"결과를 모르던 주문이 잔고({held:+d})에 반영됨 — {tag} 잔고를 따름, 체결가는 기준가 {ref}")
        return Fill(leg.name, moved, ref, b.last_fill_fee, False)

    def _stop(self, reason: str, cause: BaseException | None = None) -> None:
        self.halt(reason)
        raise Halted(self._halted) from cause

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

    def reconcile(self, *, strict: bool = False) -> str | None:
        """계좌 잔고와 장부 보유를 대조 — 다르면 멈추고 까닭을 돌려준다. 같으면 None.

        못 읽은 다리가 있으면: 주기 대조(기본)는 기록만 하고 넘어가고, `strict=True`(끝 확인)는 「확인 못 함」으로 멈춘다 —
        끝 확인이 잔고를 못 읽고도 깨끗하게 끝났다고 하지 않게."""
        with self.lock:
            if self._halted is not None:
                return self._halted
            for name, leg in self._legs.items():
                held = self._broker(leg).position()
                if held is None:
                    if strict:
                        reason = f"잔고 확인 못 함 · {self._tag(leg)} 계좌 잔고를 읽지 못함"
                        self.halt(reason)
                        return reason
                    self._journal.write("event", text=f"{self._tag(leg)} 잔고 대조 못 함 — 읽지 못함")
                    continue
                exp = self.position(leg)
                if held != exp:
                    reason = f"잔고 불일치 · {self._tag(leg)} 기대 {exp:+d} · 계좌 {held:+d}"
                    self.halt(reason)
                    return reason
            return None
