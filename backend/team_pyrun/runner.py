"""파이썬 전략 실행기 — week02 `runner.py` 의 `Runner`·`PaperBroker` 를 전략에 묶이지 않게 옮긴 것.

판정은 전략 객체가 하고(`on_minute` 으로 1분봉을 넣으면 신호가 나옵니다), 실행기가 하는 일은
**신호대로 진입하고, 손절·익절·시간 청산·장 마감 정리를 감시하고, 모두 기록하는 것**입니다.
같은 1분봉을 넣으면 week02 와 같은 거래가 나와야 합니다(`replay.py` 시험이 그걸 지킵니다).

week02 와 다른 점(그 외엔 같게 옮겼습니다):

- 익절 목표는 전략의 `target`, 틱·틱가치는 전략 파일의 `TICK`·`TICK_VALUE`(`Loaded`) 를 인자로 받습니다.
- `signal` 줄은 판정 봉마다 전부 남기고, 지표 칸은 그 봉의 숫자 칸을 모두 담습니다.
- `trade` 줄에 `reason`·`exit_date` 가 있습니다(그날 손절 수 세기용).
- `halted`(멈춤) 가 있으면 진입도 청산도 하지 않습니다. 청산이 안 됐는데 계좌 잔고가 기대와
  다르면(남의 주문이 섞인 것) **다시 주문하지 않고 멈춥니다** — 주문은 재전송하지 않습니다.
- 체결가를 못 받았을 때(`fill` → None) 잔고를 **이 실행의 것으로 따르는 건** 브로커가 그 잔고를 설명할 때뿐입니다
  (`broker.sent`·`broker.explains`). 진입은 이번에 주문을 실제로 보냈고 잔고가 신호 방향 1계약일 때만,
  청산의 잔고 0 은 결과 모름 주문이 그 0 을 설명할 때만. 아니면 남의 포지션이므로 멈춥니다(확인 필요).
  두 이름이 없는 브로커(시험용 가짜)는 week02 처럼 잔고를 따릅니다.

체결을 맡는 쪽은 `Broker` 입니다. 여기엔 종이 체결(`PaperBroker`) 만 있고, 모의계좌 체결은 따로 만듭니다.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from typing import Protocol

from backend.team_pyrun.journal import Journal

PAPER_FEE = 690.0       # 종이 체결 수수료 (1계약 1번 체결) — week02 에서 모의계좌 체결마다 나온 값
PAPER_SLIP_TICKS = 1    # 종이 체결 슬리피지 (틱)
RETRY_SECONDS = 10      # 청산 체결이 확인 안 됐을 때 다시 시도하기까지

#: 신호 줄의 지표 칸에서 뺄 봉 칸 — 나머지 숫자 칸이 지표값이다.
_BAR_FIELDS = frozenset({"date", "start", "end", "open", "high", "low", "close", "volume"})
#: 신호 줄이 이미 쓰는 칸 이름 — 지표 칸이 같은 이름이면 `write` 가 오류를 내거나 값을 덮으므로 지표에서 뺀다.
_SIGNAL_KEYS = frozenset({"kind", "at", "clock", "date", "bar", "close", "side", "reason", "stop_ticks"})


@dataclass(frozen=True)
class Minute:
    """1분봉 하나. time 은 HHMMSS (그 분의 시작 시각)."""

    date: str
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def minute_of(row: dict) -> Minute:
    """차트(분) 응답의 한 줄(접두를 뗀 것)을 1분봉으로."""
    return Minute(row["ref_dt"], row["exch_tm"], float(row["open_pric"]), float(row["high_pric"]),
                  float(row["low_pric"]), float(row["close_pric"]), float(row.get("cum_trd_qty") or 0))


# ---------------------------------------------------------------- 틱 계산
def _digits(tick: float) -> int:
    """틱의 소수 자릿수(0.1 → 1, 0.0001 → 4). 가격을 호가 단위로 반올림할 때 쓴다."""
    return max(0, -Decimal(str(tick)).normalize().as_tuple().exponent)


def _tick_up(price: float, tick: float) -> float:
    """price 이상인 가장 가까운 호가. 이미 호가면 그대로(부동소수 잡음은 6자리에서 버림)."""
    return round(math.ceil(round(price / tick, 6)) * tick, _digits(tick))


def _tick_down(price: float, tick: float) -> float:
    """price 이하인 가장 가까운 호가."""
    return round(math.floor(round(price / tick, 6)) * tick, _digits(tick))


def stop_price(side: str, entry: float, stop_ticks: int, tick: float) -> float:
    """진입가에서 불리한 쪽으로 stop_ticks 틱."""
    d = _digits(tick)
    return round(entry - stop_ticks * tick, d) if side == "buy" else round(entry + stop_ticks * tick, d)


def take_profit_price(side: str, target: float, tick: float) -> float:
    """익절 목표를 **불리한 쪽 호가**로 맞춘 값 — 가격이 여기까지 와야 닿은 것으로 봅니다(매수 보유는 올림, 매도 보유는 내림)."""
    return _tick_up(target, tick) if side == "buy" else _tick_down(target, tick)


def pnl_ticks(side: str, entry: float, exit_: float, tick: float) -> int:
    diff = exit_ - entry if side == "buy" else entry - exit_
    return round(diff / tick)


def _minutes_of(hhmmss: str) -> int:
    return int(hhmmss[:2]) * 60 + int(hhmmss[2:4])


def _won(x: float) -> float | int:
    """원 단위가 딱 떨어지면 정수로(JSON 에 19000.0 대신 19000)."""
    return int(x) if float(x).is_integer() else x


# ---------------------------------------------------------------- 체결 담당
class Broker(Protocol):
    """체결을 맡는 쪽. 체결가를 못 받으면 `fill` 은 None — 그때 실행기가 `position` 으로 실제 상태를 봅니다."""

    mode: str
    last_fill_fee: float | None

    def fill(self, side: str, ref_price: float, clock: str, why: str) -> float | None: ...

    def position(self) -> int | None: ...

    def account(self, clock: str = "", why: str = "") -> dict | None: ...


class PaperBroker:
    """주문을 내지 않고 기준가 ∓ 1틱(불리한 쪽)으로 체결된 것으로 봅니다. 수수료는 체결마다 fee 원.

    **모의계좌 체결이 아닙니다** — 기록에도 `source="paper"` 로 남깁니다."""

    mode = "paper"
    sent = True         # 종이 체결은 언제나 「보낸」 것으로 본다(관문이 없고 None 을 돌려주지 않음)

    def __init__(self, journal: Journal, tick: float, fee: float = PAPER_FEE):
        self.j = journal
        self.tick = tick
        self.fee = fee
        self.last_fill_fee: float | None = fee

    def account(self, clock: str = "", why: str = "") -> dict | None:
        return None

    def fill(self, side: str, ref_price: float, clock: str, why: str) -> float | None:
        slip = PAPER_SLIP_TICKS * self.tick
        px = round(ref_price + slip if side == "buy" else ref_price - slip, _digits(self.tick))
        self.j.write("fill", clock=clock, side=side, price=px, source="paper", fee=self.fee,
                     text=f"종이 체결 · {why}")
        return px

    def position(self) -> int | None:
        return None     # 종이 체결은 실제 잔고가 없음


# ---------------------------------------------------------------- 실행기
class Runner:
    """전략 객체 하나를 돌린다. 시세를 넣어 주는 쪽(리플레이·실시간 반복)이 `feed`·`on_minute_closed`·`on_price` 를 부른다."""

    def __init__(self, strategy, journal: Journal, broker: Broker, tick: float, tick_value: float):
        self.strat = strategy
        self.p = strategy.p
        self.j, self.broker = journal, broker
        self.tick, self.tick_value = tick, tick_value
        self.pos: dict | None = None
        self.pending: dict | None = None      # 판정 봉 신호 → 다음 가격에서 진입
        self.trades: list[dict] = []
        self.live_date: str | None = None     # 이 날의 신호부터 진입 (그 전은 준비)
        self.last_price: float | None = None
        self.retry_after: str = ""            # 청산 체결이 확인 안 됐을 때 다시 시도할 시각 (HHMMSS)
        self.cur_date: str | None = None
        self.halted: str | None = None        # 멈춘 까닭. 있으면 진입·청산 모두 안 함
        self.last_signal: dict | None = None  # 마지막 판정 봉의 신호 줄

    # ---- 시세 넣기
    def feed(self, m: Minute) -> list:
        """1분봉을 전략에 넣습니다. 날이 바뀌면 백테스트처럼 먼저 전날의 덜 닫힌 판정 봉을 닫습니다."""
        if self.cur_date is not None and m.date != self.cur_date:
            self.strat.end_of_day()
        self.cur_date = m.date
        return self.strat.on_minute(m)

    def warmup(self, minutes: list[Minute]) -> None:
        """준비 봉: 전략에 넣기만 하고 진입하지 않음."""
        for m in minutes:
            self.feed(m)
        if minutes:
            self.j.write("event", text=f"준비 봉 {len(minutes)}개 ({minutes[0].date} {minutes[0].time} ~ "
                                       f"{minutes[-1].date} {minutes[-1].time})")

    def on_minute_closed(self, m: Minute) -> None:
        for s in self.feed(m):
            b = s.bar
            fields = asdict(b) if is_dataclass(b) else dict(vars(b))
            ind = {k: round(v, 3) for k, v in fields.items()
                   if k not in _BAR_FIELDS and k not in _SIGNAL_KEYS and isinstance(k, str)
                   and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
            # 차트가 봉을 그리도록 시가·고가·저가도 남긴다(종가는 원래 있음). 지표 칸에서는 빠지는 이름이라 겹치지 않는다
            ohlc = {k: round(v, 4) for k in ("open", "high", "low") if isinstance(v := fields.get(k), (int, float))
                    and not isinstance(v, bool) and math.isfinite(v)}
            self.last_signal = self.j.write("signal", clock=b.end, date=b.date, bar=b.start, close=b.close,
                                            side=s.side, reason=s.reason, stop_ticks=s.stop_ticks, **ohlc, **ind)
            if s.side and self.pos is None and self.pending is None and b.date == self.live_date:
                self.pending = {"side": s.side, "stop_ticks": s.stop_ticks, "signal": b.end}

    def on_price(self, clock: str, price: float, ref_low: float | None = None, ref_high: float | None = None) -> None:
        """가격 한 번. ref_low/high 는 다시 돌리기에서 그 사이 가격 범위를 줄 때 씁니다."""
        lo = price if ref_low is None else ref_low
        hi = price if ref_high is None else ref_high
        self.last_price = price
        if self.halted:
            return      # 멈춘 실행은 진입도 청산도 하지 않는다
        if self.pending and self.pos is None and self.p.entry_start <= clock < self.p.entry_end:
            self._enter(clock, price)
        elif self.pending and not (self.p.entry_start <= clock < self.p.entry_end):
            self.j.write("event", clock=clock, text="진입 시간이 지나 신호를 버림")
            self.pending = None
        if self.halted or self.pos is None or clock < self.retry_after:
            return
        side, pos = self.pos["side"], self.pos
        target = self.strat.target
        if clock >= self.p.flatten_at:
            self._exit(clock, price, "장 마감 정리")
        elif side == "buy" and lo <= pos["stop"]:
            self._exit(clock, min(price, pos["stop"]) if ref_low is None else pos["stop"], "손절")
        elif side == "sell" and hi >= pos["stop"]:
            self._exit(clock, max(price, pos["stop"]) if ref_high is None else pos["stop"], "손절")
        elif target is not None and side == "buy" and hi >= (tp := take_profit_price(side, target, self.tick)):
            self._exit(clock, max(price, tp) if ref_high is None else tp, "익절")
        elif target is not None and side == "sell" and lo <= (tp := take_profit_price(side, target, self.tick)):
            self._exit(clock, min(price, tp) if ref_low is None else tp, "익절")
        elif _minutes_of(clock) - _minutes_of(pos["entry_time"]) >= self.p.hold_min:
            self._exit(clock, price, "시간 청산")

    # ---- 진입·청산
    def _enter(self, clock: str, price: float) -> None:
        e, self.pending = self.pending, None
        px = self.broker.fill(e["side"], price, clock, f"진입 ({e['side']})")
        if px is None:
            held = self.broker.position()
            if held is None:
                self.halt("진입 체결 여부를 잔고로 확인하지 못함")
                return
            if not held:
                self.j.write("event", clock=clock, text="진입 체결 없음 (잔고 0) — 이 신호는 건너뜀")
                return
            if not self._mine(held, sent_needed=True, want=1 if e["side"] == "buy" else -1):
                # 관문에 걸려 안 보냈거나(남의 잔고), 알려진 거절이거나, 방향이 다르다 — 남의 포지션을 인수하지 않는다
                self.halt(f"잔고 불일치 · 기대 {self.expected_position():+d} · 계좌 {held:+d}")
                return
            px = price      # 체결은 됐는데 체결가를 못 받음 → 현재가로 기록하고 보유로 다룸
            self.j.write("event", clock=clock, text=f"체결가 미확인 · 잔고 {held:+d} → 현재가 {px} 로 기록")
        self.pos = {"side": e["side"], "entry": px, "entry_time": clock, "signal_time": e["signal"],
                    "stop_ticks": e["stop_ticks"], "stop": stop_price(e["side"], px, e["stop_ticks"], self.tick),
                    "entry_fee": getattr(self.broker, "last_fill_fee", None)}
        self.strat.on_entry()
        self.j.write("event", clock=clock, text=f"진입 {e['side']} {px} · 손절 {self.pos['stop']} ({e['stop_ticks']}틱)")

    def _exit(self, clock: str, ref: float, reason: str) -> None:
        side = "sell" if self.pos["side"] == "buy" else "buy"
        px = self.broker.fill(side, ref, clock, f"청산 · {reason}")
        if px is None:
            held = self.broker.position()
            if held == 0 and not self._mine(0):
                # 이 실행이 낸 결과 모름 청산이 없다(알려진 거절·관문에 걸려 안 보냄) — 남이 닫은 것. 지어낸 청산을 적지 않는다
                self.halt(f"잔고 불일치 · 기대 {self.expected_position():+d} · 계좌 +0")
                return
            if held == 0:   # 청산은 됐는데 체결가를 못 받음 → 현재가로 기록 (다시 주문하면 반대 포지션이 생김)
                px = ref
                self.j.write("event", clock=clock, text=f"청산 체결가 미확인 · 잔고 0 → {px} 로 기록")
            elif held is not None and held == self.expected_position():
                sec = int(clock[:2]) * 3600 + int(clock[2:4]) * 60 + int(clock[4:6]) + RETRY_SECONDS
                self.retry_after = f"{sec // 3600:02d}{sec % 3600 // 60:02d}{sec % 60:02d}"
                self.j.write("event", clock=clock,
                             text=f"청산 안 됨 ({reason}) · 잔고 {held:+d} — {RETRY_SECONDS}초쯤 뒤 다시 시도")
                return
            else:           # 기대와 다른 잔고(남의 주문이 섞임)이거나 못 읽음 → 더 주문하지 않고 멈춘다
                got = "확인 안 됨" if held is None else f"{held:+d}"
                self.halt(f"잔고 불일치 · 기대 {self.expected_position():+d} · 계좌 {got}")
                return
        ticks = pnl_ticks(self.pos["side"], self.pos["entry"], px, self.tick)
        pnl = _won(ticks * self.tick_value)
        exit_fee = getattr(self.broker, "last_fill_fee", None)
        entry_fee = self.pos.get("entry_fee")
        fee = None if entry_fee is None or exit_fee is None else entry_fee + exit_fee
        t = {**self.pos, "exit": px, "exit_time": clock, "reason": reason, "ticks": ticks,
             "pnl": pnl, "exit_fee": exit_fee, "fee": fee,
             "pnl_after_fee": None if fee is None else pnl - fee,
             "entry_date": self.live_date, "exit_date": self.live_date}
        self.trades.append(t)
        fee_txt = "" if fee is None else f" · 수수료 {fee:,.0f}원 → {t['pnl_after_fee']:+,.0f}원"
        self.j.write("trade", clock=clock, text=f"{reason} {ticks:+d}틱 ({pnl:+,}원){fee_txt}",
                     **{k: t[k] for k in ("side", "entry", "exit", "entry_time", "exit_time", "ticks", "pnl",
                                          "fee", "pnl_after_fee", "reason", "exit_date")})
        self.strat.on_exit(pnl, stopped=reason == "손절")
        self.pos = None

    def _mine(self, held: int, *, sent_needed: bool = False, want: int | None = None) -> bool:
        """체결가 없이 받은 잔고 held 를 이 실행의 체결로 따라도 되는가(`fill` 이 None 을 돌려준 바로 뒤).

        want 가 있으면 잔고가 그 값이어야 하고(진입: 신호 방향 1계약), sent_needed 면 이번 fill 에서 주문을 실제로
        보냈어야 한다. 브로커가 `explains` 를 가지면 그 잔고가 이 실행의 결과 모름 주문으로 설명돼야 한다."""
        if want is not None and held != want:
            return False
        if sent_needed and not getattr(self.broker, "sent", True):
            return False
        explains = getattr(self.broker, "explains", None)
        return explains is None or bool(explains(held))

    def force_flat(self, clock: str) -> None:
        """실행을 끝내며 남은 보유를 마지막 가격으로 정리. 멈춘 실행은 건드리지 않는다(잔고가 어긋나 있다)."""
        if self.halted:
            return
        if self.pos is not None and self.last_price is not None:
            self._exit(clock, self.last_price, "실행 종료 정리")

    # ---- 상태
    def expected_position(self) -> int:
        """실행기가 생각하는 보유 계약 수: 0 · +1(매수) · −1(매도)."""
        if self.pos is None:
            return 0
        return 1 if self.pos["side"] == "buy" else -1

    def halt(self, reason: str) -> None:
        """실행을 멈춘다(첫 까닭만 남김). 이후 진입·청산·정리 주문을 내지 않는다."""
        if self.halted:
            return
        self.halted = reason
        self.j.write("event", text=f"멈춤 · {reason}")

    def snapshot(self) -> dict:
        """화면에 보일 지금 상태."""
        pos = self.pos
        day = [t for t in self.trades if t.get("exit_date") == self.live_date]
        # 하루 손절 수는 전략이 진입을 막는 데 쓰는 값(`day.stops`)을 따른다 — 앞선 실행의 손절도 들어 있다
        own_stops = sum(1 for t in day if t["reason"] == "손절")
        day_stops = getattr(getattr(self.strat, "day", None), "stops", None)
        time_exit = None
        if pos is not None:
            m = _minutes_of(pos["entry_time"]) + self.p.hold_min
            time_exit = f"{m // 60:02d}{m % 60:02d}00"
        return {
            "position": self.expected_position(),
            "entry": None if pos is None else pos["entry"],
            "stop": None if pos is None else pos["stop"],
            "stop_ticks": None if pos is None else pos["stop_ticks"],
            "target": self.strat.target,
            "time_exit_at": time_exit,
            "today_pnl": sum(t["pnl"] for t in day),
            "stops": own_stops if day_stops is None else day_stops,
            "max_stops": getattr(self.p, "max_stops_per_day", None),
            "halted": self.halted,
            "last_signal": self.last_signal,
        }
