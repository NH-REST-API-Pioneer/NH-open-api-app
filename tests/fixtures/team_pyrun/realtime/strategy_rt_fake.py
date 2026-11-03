"""실시간 시험 전략 — week03 ws_trader `Engine` 약속을 따르는 작은 손 전략(시험 전용, 실제 leadlag 아님).

판단은 일부러 단순합니다: KRX 체결이 **바로 앞 체결보다** `move_won` 원 넘게 움직이면 MKU 를 반대로 따라 들어갑니다
(KRX 상승 = 원화 약세 = MKU 매도). 청산은 ws_trader 와 같은 규칙(익절·손절·보유 시간·`flatten_at`), 손익 계산
(`filled_exit`)도 ws_trader 그대로입니다. 받은 순서를 `seen` 에 적어 시험이 넣기 순서를 볼 수 있게 합니다.
"""
from dataclasses import dataclass

TICK = 0.0001
TICK_USD = 2.5
FEE_TICKS = 2.0 / TICK_USD        # 수수료 편도 $2
NAME = "rtfake"


@dataclass
class LiveParams:
    move_won: float = 0.5
    sl_ticks: float = 5
    tp_ticks: float | None = None
    hold_s: float = 300
    cooldown_s: float = 0
    max_stops_per_day: int = 3
    entry_start: str = "090000"
    entry_end: str = "152000"
    flatten_at: str = "154000"


class Engine:
    """판단만 한다. 시세를 넣으면 할 일(진입·청산)을 돌려준다."""

    def __init__(self, p: LiveParams):
        self.p = p
        self.bid = self.ask = None
        self.pos: dict | None = None
        self.pending = False
        self.stops = 0
        self.resume_at = 0.0
        self.last_krx = None
        self.seen: list[tuple] = []

    # ---- 시세 ----
    def on_krx(self, price: float, now: float, hhmmss: str) -> dict | None:
        self.seen.append(("krx", now, hhmmss, price))
        prev, self.last_krx = self.last_krx, price
        p = self.p
        if self.pos or self.pending or now < self.resume_at or self.stops >= p.max_stops_per_day:
            return None
        if prev is None or self.bid is None or not (p.entry_start <= hhmmss <= p.entry_end):
            return None
        dk = round(price - prev, 2)
        if abs(dk) < p.move_won:
            return None
        side = -1 if dk > 0 else 1
        spread = round((self.ask - self.bid) / TICK)
        self.pending = True
        return {"act": "enter", "side": side, "ref": self.ask if side > 0 else self.bid,
                "dk": dk, "expected": 10.0, "followed": 1.0, "rho": 0.1, "spread": spread, "time": hhmmss}

    def on_quote(self, bid: float, ask: float, now: float, hhmmss: str) -> dict | None:
        self.seen.append(("quote", now, hhmmss, (bid, ask)))
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        self.bid, self.ask = bid, ask
        return self._exit(now, hhmmss)

    def on_timer(self, now: float, hhmmss: str) -> dict | None:
        self.seen.append(("timer", now, hhmmss, None))
        return self._exit(now, hhmmss)

    # ---- 청산 (ws_trader 와 같은 규칙) ----
    def _exit(self, now: float, hhmmss: str) -> dict | None:
        if not self.pos or self.pending or self.bid is None:
            return None
        p, pos = self.p, self.pos
        mark = self.bid if pos["side"] > 0 else self.ask
        pnl = round(pos["side"] * (mark - pos["price"]) / TICK, 6)
        reason = ""
        if p.tp_ticks is not None and pnl >= p.tp_ticks:
            reason = "익절"
        elif pnl <= -p.sl_ticks:
            reason = "손절"
        elif now - pos["t"] >= p.hold_s:
            reason = "시간"
        elif hhmmss >= p.flatten_at:
            reason = "마감"
        if not reason:
            return None
        self.pending = True
        return {"act": "exit", "side": -pos["side"], "ref": mark, "reason": reason, "time": hhmmss}

    def filled_entry(self, side: int, price: float, now: float, hhmmss: str, ord_no: str = "") -> None:
        self.pos = {"side": side, "price": price, "t": now, "time": hhmmss, "ord_no": ord_no}
        self.pending = False

    def filled_exit(self, price: float, now: float, reason: str) -> dict:
        pos = self.pos
        gross = pos["side"] * (price - pos["price"]) / TICK
        net = gross - 2 * FEE_TICKS
        self.stops += reason == "손절"
        self.pos, self.pending = None, False
        self.resume_at = now + self.p.cooldown_s
        return {"gross_ticks": round(gross, 2), "net_ticks": round(net, 2), "net_usd": round(net * TICK_USD, 2),
                "held_s": round(now - pos["t"], 1)}
