"""파이썬 전략 실행기 — week02 `runner.py` 의 `Runner`·`PaperBroker` 를 전략에 묶이지 않게 옮긴 것.

판정은 전략 객체가 하고(`on_minute` 으로 1분봉을 넣으면 신호가 나옵니다), 실행기가 하는 일은
**신호대로 진입하고, 손절·익절·시간 청산·장 마감 정리를 감시하고, 모두 기록하는 것**입니다.
같은 1분봉을 넣으면 week02 와 같은 거래가 나와야 합니다(`replay.py` 시험이 그걸 지킵니다).

week02 와 다른 점(그 외엔 같게 옮겼습니다):

- 익절 목표는 전략의 `target`, 없으면 `current_vwap`(week02 `runner.make_strategy` 가 VWAP 전략에 붙이던 것),
  둘 다 없으면 익절 없음(`target_of`). 틱·틱가치는 전략 파일의 `TICK`·`TICK_VALUE`(`Loaded`) 를 인자로 받습니다.
- 전략의 `end_of_day`·`on_entry`·`on_exit`·`exit_reason` 은 없으면 건너뜁니다(`_hook`). 하루 손절 수(`day.stops`)가 없으면
  화면의 손절 수는 이 실행기가 센 값 + 오늘 앞선 실행의 손절(`stops_before`)입니다.
- `signal` 줄은 판정 봉마다 전부 남기고, 지표 칸은 그 봉의 숫자 칸을 모두 담습니다.
- `trade` 줄에 `reason`·`exit_date` 가 있습니다(그날 손절 수 세기용).
- `halted`(멈춤) 가 있으면 진입도 청산도 하지 않습니다. 청산이 안 됐는데 계좌 잔고가 기대와
  다르면(남의 주문이 섞인 것) **다시 주문하지 않고 멈춥니다** — 주문은 재전송하지 않습니다.
- 체결가를 못 받았을 때(`fill` → None) 잔고를 **이 실행의 것으로 따르는 건** 브로커가 그 잔고를 설명할 때뿐입니다
  (`broker.sent`·`broker.explains`). 진입은 이번에 주문을 실제로 보냈고 잔고가 신호 방향 1계약일 때만,
  청산의 잔고 0 은 결과 모름 주문이 그 0 을 설명할 때만. 아니면 남의 포지션이므로 멈춥니다(확인 필요).
  두 이름이 없는 브로커(시험용 가짜)는 week02 처럼 잔고를 따릅니다.

체결을 맡는 쪽은 `Broker` 입니다. 여기엔 종이 체결(`PaperBroker`) 만 있고, 모의계좌 체결은 따로 만듭니다.

**전략이 청산을 판단하는 약속** (고를 수 있음 — 판단은 전략 파일이, 주문·안전·기록은 앱이)

전략에 `exit_reason` 메서드가 있으면 보유 중에 가격이 들어올 때마다 앱이 묻고, 공통 청산 규칙(손절·익절·시간 청산)은
쓰지 않습니다. 없으면 지금(week02) 그대로입니다.

    exit_reason(clock, price, low, high, pos) -> None | "사유" | ("사유", 기준가)

- `clock` HHMMSS · `price` 이번 가격. 리플레이는 한 분에 두 번 부릅니다: 그 분 시가(`low`·`high` 는 None),
  다음에 종가와 그 분 저가·고가.
- `low`·`high` 는 **가격 하나일 때 None** 입니다(장중 현재가, 리플레이의 시가). 그 분의 범위를 줄 때만 숫자입니다.
  week02 의 손절이 「가격 하나면 그 가격, 범위면 손절가」로 체결가를 고르던 구분과 같습니다 — ORB 의
  「손절가를 지나면 `min(시가, 손절가)`」 를 그대로 옮길 수 있게 둡니다.
- `pos` 는 보유의 **사본**(바꿔도 실행기 보유는 그대로): `side` `entry` `entry_time` `entry_date` `signal_time`
  `stop`(진입가 ∓ `stop_ticks` 틱) `stop_ticks` `signal`(진입 신호 객체, 모르면 None) `window`(진입 신호에 있으면).
- 돌려주는 값: None 이면 들고 있음. 사유 문자열이면 지금 가격을 기준가로 청산. `(사유, 기준가)` 면 그 가격을
  기준가로 청산 — 기준가는 종이 체결가(∓ 슬리피지)와 체결가를 못 받았을 때 기록할 가격이고, 모의 계좌의 실제 주문은
  언제나 시장가입니다. **앱이 기준가를 묶습니다**: 가격 하나일 때는 언제나 그 가격, 범위일 때는 `[low, high]` 안으로
  (`min(max(기준가, low), high)`). 바뀌면 `event` 줄을 남깁니다 — 전략이 엉뚱한 가격으로 체결을 지어내지 못하게.
  사유가 `"손절"` 이면 `on_exit(..., stopped=True)`. 사유는 40자까지, 앱이 쓰는 사유(`RESERVED_REASONS`:
  「장 마감 정리」·「실행 종료 정리」)는 쓸 수 없습니다. 그 밖의 값은 `TypeError`(장중이면 「오류」).

앞서는 순서 (위가 먼저, 앞에 걸리면 전략에 묻지 않음)

    | 순서 | 규칙 | 누가 |
    | 1 | `halted`(멈춤) — 진입도 청산도 하지 않음 | 앱 |
    | 2 | 청산 체결이 확인 안 돼 기다리는 중(`retry_after` 전) — 아무것도 안 함 | 앱 |
    | 3 | `flatten_at` 이후 — 「장 마감 정리」 | 앱 |
    | 4 | 앞서 정한 청산이 확인 안 됨 — 10초 뒤 **같은 사유로 다시** (전략에 다시 묻지 않음) | 앱 |
    | 5 | `exit_reason` 이 돌려준 사유 | 전략 |
    | 끝 | 실행 끝·중지·오류 정리(`force_flat`, 「실행 종료 정리」) — `on_price` 밖에서 언제나 | 앱 |

  결과 모름·잔고 불일치(「확인 필요」)·주문 재전송 금지는 청산 주문을 내는 `_exit`·브로커가 그대로 맡습니다.

**화면의 손절·익절** (고를 수 있음, 표시 전용) — 전략에 `exit_levels(pos) -> {"stop": 가격|None, "target": 가격|None}`
이 있으면 보유 중 `snapshot()` 의 `stop`·`target` 을 그 값으로 보입니다(ORB 는 범위 끝 손절과 진입가 + 목표 틱).
**판단에는 쓰지 않습니다** — 청산은 위 규칙·`exit_reason` 그대로. 예외·수가 아닌 칸이면 원래 값(실행기 손절가·`target`).

**신호 꼴** — 신호에 `bar` 가 있으면 그것이 판정 봉(week02), 없고 `minute`(1분봉: `date` `time` `open` …)이
있으면 그 1분봉이 판정 봉입니다. 1분봉이면 기록의 `bar` = 그 분 시작 시각, `clock` = 그 분이 끝난 시각(+1분).
`signal` 줄에는 판정 봉의 숫자 지표 칸(소수 3자리, 틱이 더 잘면 틱 자릿수 + 2 — MKU 6자리)과
시가·고가·저가(소수 4자리, 틱이 더 잘면 틱 자릿수)에 더해, **신호 자신의 숫자·문자 칸**(dataclass 칸,
예: `window` `range_high` `range_low` `target_ticks` `exit_by`, 수는 소수 6자리)을 남깁니다. 예약 칸(`kind` `clock`
`side` `reason` 등)·봉 칸 이름·참거짓·비유한수는 뺍니다.

**`on_entry` 인자** — 매개변수가 없으면 `on_entry()`. 있으면 **이름이 같은 진입 신호 칸의 값**을 넘깁니다
(ORB `on_entry(window)` ← 신호의 `window`). 신호에 없는 이름은 기본값이 있으면 기본값, 없으면 `TypeError` —
이 대응은 **진입 주문을 내기 전에** 맞춰 봅니다(틀리면 주문 없이 오류).
`*args`·`**kwargs` 에는 아무것도 넘기지 않습니다. 진입 신호에 `window` 가 있으면 보유와 `trade` 줄, 진입 `event` 줄에도
남깁니다(같은 날 다시 세운 실행이 개장마다 한 번 규칙을 이어받게 — `journal.entered_windows`).

**주문 막힘 시각(휴장)** — `blocked(clock) -> bool` 을 꽂으면(장중 실행이 해외 휴장 20:35~20:50 으로 꽂음) 그 시각엔
진입·청산 체결(`broker.fill`)을 하나도 부르지 않습니다. 리플레이와 직접 쓰는 Runner 는 None — 지금 그대로입니다
(week03 백테스트는 휴장 봉에서도 기한 청산을 하므로 골든이 그대로 맞습니다).

- 진입 대기 신호는 버리지 않고 기다렸다가, 막힘이 풀린 첫 가격에 진입합니다(진입 시간 안이면).
- 청산 판단은 막힌 동안에도 합니다(전략의 `exit_reason`, 없으면 공통 규칙). 청산하기로 정해지면 그 사유를
  `break_exit` 에 두고 **다시 묻지 않으며**, 막힘이 풀린 첫 가격(그 가격이 기준가)에 그 사유로 청산합니다 —
  그 사이 가격이 돌아왔어도. 순서는 앱의 장 마감 정리(`flatten_at`) 다음, 전략·공통 규칙 앞입니다.
- 청산 재시도(`retry_after`)도 막힌 동안엔 미룹니다. `force_flat` 도 막힌 시각엔 주문하지 않습니다(실행이 「확인 필요」로 끝냄).
  막힘이 풀린 뒤 `force_flat`(정리·중지 요청)이 `break_exit` 를 가진 보유를 닫으면 사유는 「실행 종료 정리」가 아니라
  그 `break_exit`(예: 「손절」 — `on_exit(stopped=True)`, 하루 손절 수에 들어감)입니다.
"""
from __future__ import annotations

import inspect
import math
from dataclasses import asdict, dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Protocol

from backend.team_pyrun.journal import Journal
from backend.team_pyrun.markets import DOMESTIC

# 팀: 국내 값의 출처는 `markets.DOMESTIC` (week02 값 그대로 — 690원, 1틱)
PAPER_FEE = DOMESTIC.paper_fee              # 종이 체결 수수료 (1계약 1번 체결) — week02 에서 모의계좌 체결마다 나온 값
PAPER_SLIP_TICKS = DOMESTIC.paper_slip_ticks    # 종이 체결 슬리피지 (틱)
RETRY_SECONDS = 10      # 청산 체결이 확인 안 됐을 때 다시 시도하기까지

#: 신호 줄의 지표 칸에서 뺄 봉 칸 — 나머지 숫자 칸이 지표값이다.
_BAR_FIELDS = frozenset({"date", "start", "end", "open", "high", "low", "close", "volume"})
#: 익절 목표를 읽는 전략 이름, 이 순서로. 처음 있는 것을 쓴다.
TARGET_NAMES = ("target", "current_vwap")
_MISSING = object()
#: 전략이 청산을 판단하는 메서드 이름(고를 수 있음). 있으면 공통 손절·익절·시간 청산 대신 쓴다 — 모듈 문서.
EXIT_HOOK = "exit_reason"
#: 화면에 보일 손절·익절을 전략이 알려 주는 메서드 이름(고를 수 있음, 표시 전용) — `Runner.snapshot`.
LEVELS_HOOK = "exit_levels"
#: 앱이 스스로 내는 청산의 사유 — 전략의 `exit_reason` 은 이 이름을 돌려줄 수 없다(기록에서 앱 정리와 섞이지 않게).
FLATTEN_REASON, END_REASON = "장 마감 정리", "실행 종료 정리"
RESERVED_REASONS = frozenset({FLATTEN_REASON, END_REASON})
#: 전략 청산 사유의 최대 길이(글자).
MAX_REASON_LEN = 40
#: 신호 자신의 칸에서 뺄 이름 — 판정 봉 객체 칸.
_BAR_HOLDERS = frozenset({"bar", "minute"})

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


def target_of(strategy: object) -> float | None:
    """전략의 익절 목표 — `target`, 없으면 `current_vwap`, 둘 다 없으면 None(익절 없음).

    `target` 이 있으면 값이 None 이어도 그것을 쓴다(아직 목표가 없는 것)."""
    for name in TARGET_NAMES:
        value = getattr(strategy, name, _MISSING)
        if value is not _MISSING:
            return value
    return None


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


def _plus_minute(hhmmss: str) -> str:
    """1분 뒤 HHMM00 (1분봉 시작 시각 → 그 분이 끝난 시각). 23:59 → 240000."""
    t = _minutes_of(hhmmss) + 1
    return f"{t // 60:02d}{t % 60:02d}00"


def _decision_bar(signal: object) -> tuple[object, str, str]:
    """신호의 판정 봉과 (시작, 끝) 시각. `bar` 가 있으면 그것(week02), 없으면 `minute`(1분봉 — 끝은 +1분)."""
    b = getattr(signal, "bar", None)
    if b is not None:
        return b, b.start, b.end
    m = getattr(signal, "minute", None)
    if m is None:
        raise TypeError("신호에 판정 봉(bar 또는 minute)이 없습니다")
    return m, m.time, _plus_minute(m.time)


def _signal_fields(signal: object) -> dict:
    """신호 자신의 숫자·문자 칸(dataclass 면 그 칸, 아니면 속성). 예약 칸·봉 칸·참거짓·비유한수는 뺀다."""
    if is_dataclass(signal) and not isinstance(signal, type):
        items = [(f.name, getattr(signal, f.name, None)) for f in fields(signal)]
    else:
        items = list(getattr(signal, "__dict__", {}).items())
    out: dict = {}
    for k, v in items:
        if not isinstance(k, str) or k in _SIGNAL_KEYS or k in _BAR_FIELDS or k in _BAR_HOLDERS:
            continue
        if isinstance(v, str):
            out[k] = v
        elif isinstance(v, int) and not isinstance(v, bool):
            out[k] = v
        elif isinstance(v, float) and math.isfinite(v):
            out[k] = round(v, 6)
    return out


def _exit_answer(got: object, price: float) -> tuple[str, float] | None:
    """`exit_reason` 의 답을 (사유, 기준가) 로. None 이면 들고 있음. 약속에 없는 값은 `TypeError`."""
    if got is None:
        return None
    def ok(reason: object) -> bool:
        return (isinstance(reason, str) and bool(reason.strip()) and len(reason) <= MAX_REASON_LEN
                and reason.strip() not in RESERVED_REASONS)

    if ok(got):
        return got, price
    if (isinstance(got, tuple) and len(got) == 2 and ok(got[0])
            and isinstance(got[1], (int, float)) and not isinstance(got[1], bool)
            and math.isfinite(got[1]) and got[1] > 0):
        return got[0], float(got[1])
    raise TypeError(f"{EXIT_HOOK} 은 None·사유 문자열·(사유, 기준가) 중 하나를 돌려줘야 합니다: {got!r}")


def _entry_args(fn, signal: object) -> tuple[list, dict]:
    """`on_entry` 에 넘길 값 — 매개변수 이름과 같은 진입 신호 칸의 값(모듈 문서). 위치 전용 인자는 앞에서부터."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):     # 서명을 못 읽는 것(내장 함수 등)은 인자 없이
        return [], {}
    args: list = []
    kwargs: dict = {}
    positional_open = True
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if signal is None or not hasattr(signal, p.name):
            if p.default is p.empty:
                raise TypeError(f"on_entry 의 인자 {p.name} 와 같은 이름의 칸이 진입 신호에 없습니다")
            if p.kind is p.POSITIONAL_ONLY:
                positional_open = False     # 뒤의 위치 전용 인자도 기본값으로 둔다
            continue
        value = getattr(signal, p.name)
        if p.kind is p.POSITIONAL_ONLY:
            if not positional_open:
                raise TypeError(f"on_entry 의 위치 전용 인자 {p.name} 앞의 인자가 진입 신호에 없습니다")
            args.append(value)
        else:
            kwargs[p.name] = value
    return args, kwargs


def _won(x: float) -> float | int:
    """원 단위가 딱 떨어지면 정수로(JSON 에 19000.0 대신 19000)."""
    return int(x) if float(x).is_integer() else x


def _money(x: float, currency: str) -> str:
    """기록 글에 쓰는 금액 — 원은 week02 그대로 `+19,000원`, USD 는 `+22.50 USD`."""
    return f"{x:+,}원" if currency == "KRW" else f"{x:+,.2f} USD"


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

    def __init__(self, journal: Journal, tick: float, fee: float = PAPER_FEE, slip_ticks: int = PAPER_SLIP_TICKS):
        self.j = journal
        self.tick = tick
        self.fee = fee
        self.slip_ticks = slip_ticks      # 불리한 쪽 슬리피지(틱) — 해외 리플레이·종이 실행은 시장 값(`markets.Market`)
        self.last_fill_fee: float | None = fee

    def account(self, clock: str = "", why: str = "") -> dict | None:
        return None

    def fill(self, side: str, ref_price: float, clock: str, why: str) -> float | None:
        slip = self.slip_ticks * self.tick
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
        # 신호 줄 자릿수 — 국내(틱 0.1)는 지표 3·봉 4 그대로, 틱이 잘면(MKU 0.0001) 지표 6·봉 4
        self.ind_digits = max(3, _digits(tick) + 2)
        self.ohlc_digits = max(4, _digits(tick))
        self.pos: dict | None = None
        self.pending: dict | None = None      # 판정 봉 신호 → 다음 가격에서 진입
        self.trades: list[dict] = []
        self.live_date: str | None = None     # 이 날의 신호부터 진입 (그 전은 준비)
        self.last_price: float | None = None
        self.retry_after: str = ""            # 청산 체결이 확인 안 됐을 때 다시 시도할 시각 (HHMMSS)
        self.cur_date: str | None = None
        self.halted: str | None = None        # 멈춘 까닭. 있으면 진입·청산 모두 안 함
        self.last_signal: dict | None = None  # 마지막 판정 봉의 신호 줄
        self.stops_before = 0                 # 오늘 앞선 실행의 손절 수 — 전략에 `day` 가 없을 때 화면의 손절 수에 더한다
        self.entry_signal: object | None = None  # 보유의 진입 신호 객체 — `exit_reason` 의 pos["signal"]
        self.retry_reason: str | None = None  # 확인 안 된 청산의 사유 — 전략이 판단하는 청산은 이 사유로 다시 시도
        self.currency = "KRW"                 # 손익·수수료 통화 — 기록 글에만 씀(값은 TICK_VALUE 단위 그대로)
        #: 주문 막힘 시각(휴장)인가 — 실행이 꽂는다. None 이면 막힘 없음(모듈 문서)
        self.blocked = None
        self.break_exit: str | None = None    # 막힌 동안 정한 청산 사유 — 막힘이 풀린 첫 가격에 이 사유로 청산
        self._block_noted: set[str] = set()   # 막힌 동안 한 번만 남기는 기록 (진입 대기·청산 판단)

    # ---- 시세 넣기
    def feed(self, m: Minute) -> list:
        """1분봉을 전략에 넣습니다. 날이 바뀌면 백테스트처럼 먼저 전날의 덜 닫힌 판정 봉을 닫습니다."""
        if self.cur_date is not None and m.date != self.cur_date:
            self._hook("end_of_day")
        self.cur_date = m.date
        return self.strat.on_minute(m)

    def warmup(self, minutes: list[Minute]) -> list:
        """준비 봉: 전략에 넣기만 하고 진입하지 않음. 그동안 전략이 낸 신호를 돌려준다(장중 시작 때 이미 신호가 난
        개장을 알아보는 데 씀 — `live.LiveRun.prepare`)."""
        signals: list = []
        for m in minutes:
            signals.extend(self.feed(m) or [])
        if minutes:
            self.j.write("event", text=f"준비 봉 {len(minutes)}개 ({minutes[0].date} {minutes[0].time} ~ "
                                       f"{minutes[-1].date} {minutes[-1].time})")
        return signals

    def on_minute_closed(self, m: Minute) -> None:
        for s in self.feed(m):
            b, start, end = _decision_bar(s)        # week02 는 `bar`, 1분봉 신호(ORB)는 `minute`
            bar_fields = asdict(b) if is_dataclass(b) else dict(vars(b))
            ind = {k: round(v, self.ind_digits) for k, v in bar_fields.items()
                   if k not in _BAR_FIELDS and k not in _SIGNAL_KEYS and isinstance(k, str)
                   and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
            # 차트가 봉을 그리도록 시가·고가·저가도 남긴다(종가는 원래 있음). 지표 칸에서는 빠지는 이름이라 겹치지 않는다
            ohlc = {k: round(v, self.ohlc_digits) for k in ("open", "high", "low") if isinstance(v := bar_fields.get(k), (int, float))
                    and not isinstance(v, bool) and math.isfinite(v)}
            # 신호 자신의 칸(ORB 의 window·range_high 등). 봉 지표와 이름이 같으면 신호 칸이 이긴다
            extra = {**ind, **_signal_fields(s)}
            self.last_signal = self.j.write("signal", clock=end, date=b.date, bar=start, close=b.close,
                                            side=s.side, reason=s.reason, stop_ticks=s.stop_ticks, **ohlc, **extra)
            if s.side and self.pos is None and self.pending is None and b.date == self.live_date:
                self.pending = {"side": s.side, "stop_ticks": s.stop_ticks, "signal": end, "obj": s}

    def on_price(self, clock: str, price: float, ref_low: float | None = None, ref_high: float | None = None) -> None:
        """가격 한 번. ref_low/high 는 다시 돌리기에서 그 사이 가격 범위를 줄 때 씁니다."""
        lo = price if ref_low is None else ref_low
        hi = price if ref_high is None else ref_high
        self.last_price = price
        if self.halted:
            return      # 멈춘 실행은 진입도 청산도 하지 않는다
        # 팀: 휴장 — 이 시각엔 체결을 부르지 않는다(모듈 문서 「주문 막힘 시각」)
        blocked = self.blocked is not None and bool(self.blocked(clock))
        if not blocked and self._block_noted:
            self._block_noted = set()       # 막힘이 풀리면 다음 막힘에 다시 한 번 기록
        if self.pending and self.pos is None and self.p.entry_start <= clock < self.p.entry_end:
            if blocked:
                self._note_block("entry", clock, "휴장 중 — 진입 대기 신호는 휴장이 끝난 첫 가격에 진입")
            else:
                self._enter(clock, price)
        elif self.pending and not (self.p.entry_start <= clock < self.p.entry_end):
            self.j.write("event", clock=clock, text="진입 시간이 지나 신호를 버림")
            self.pending = None
        if self.halted or self.pos is None:
            return
        if blocked:
            self._decide_in_break(clock, price, lo, hi, ref_low, ref_high)
            return
        if clock < self.retry_after:
            return
        judge = getattr(self.strat, EXIT_HOOK, None)
        if judge is not None:       # 전략이 청산을 판단한다 — 공통 손절·익절·시간 청산은 쓰지 않음
            self._judged_exit(judge, clock, price, ref_low, ref_high)
            return
        got = self._common_exit(clock, price, lo, hi, ref_low, ref_high)
        if got is not None:
            self._exit(clock, *got)

    def _common_exit(self, clock: str, price: float, lo: float, hi: float,
                     ref_low: float | None, ref_high: float | None) -> tuple[float, str] | None:
        """앱의 공통 청산 규칙(week02) — (기준가, 사유) 또는 None. 막힘(휴장) 뒤 정해 둔 청산이 장 마감 정리 다음에 온다."""
        side, pos = self.pos["side"], self.pos
        target = target_of(self.strat)
        if clock >= self.p.flatten_at:
            return price, FLATTEN_REASON
        if self.break_exit is not None:     # 팀: 휴장 중 정한 청산 — 풀린 첫 가격에
            return price, self.break_exit
        if side == "buy" and lo <= pos["stop"]:
            return (min(price, pos["stop"]) if ref_low is None else pos["stop"]), "손절"
        if side == "sell" and hi >= pos["stop"]:
            return (max(price, pos["stop"]) if ref_high is None else pos["stop"]), "손절"
        if target is not None and side == "buy" and hi >= (tp := take_profit_price(side, target, self.tick)):
            return (max(price, tp) if ref_high is None else tp), "익절"
        if target is not None and side == "sell" and lo <= (tp := take_profit_price(side, target, self.tick)):
            return (min(price, tp) if ref_low is None else tp), "익절"
        if _minutes_of(clock) - _minutes_of(pos["entry_time"]) >= self.p.hold_min:
            return price, "시간 청산"
        return None

    def _judged_exit(self, judge, clock: str, price: float, ref_low: float | None, ref_high: float | None) -> None:
        """전략의 `exit_reason` 으로 청산할지 정한다. 앱의 안전 규칙이 먼저다(모듈 문서의 순서 3·4)."""
        if clock >= self.p.flatten_at:
            self._exit(clock, price, FLATTEN_REASON)
            return
        if self.retry_reason is not None:   # 앞서 정한 청산이 확인 안 됨 — 결정을 되묻지 않고 같은 사유로 다시
            self._exit(clock, price, self.retry_reason)
            return
        if self.break_exit is not None:     # 팀: 휴장 중 정한 청산 — 되묻지 않고 풀린 첫 가격에
            self._exit(clock, price, self.break_exit)
            return
        got = self._judged(judge, clock, price, ref_low, ref_high)
        if got is not None:
            self._exit(clock, *got)

    def _judged(self, judge, clock: str, price: float, ref_low: float | None,
                ref_high: float | None) -> tuple[float, str] | None:
        """전략에 묻고 (묶은 기준가, 사유) 또는 None."""
        got = _exit_answer(judge(clock, price, ref_low, ref_high, self._pos_view()), price)
        if got is None:
            return None
        reason, asked = got
        # 기준가 묶기 — 가격 하나면 그 가격, 범위면 [저가, 고가] 안 (전략이 체결가를 지어내지 못하게)
        ref = price if ref_low is None or ref_high is None else min(max(asked, ref_low), ref_high)
        if ref != asked:
            self.j.write("event", clock=clock, text=f"전략 기준가 {asked:g} → {ref:g} ({reason}) — "
                                                    "가격 범위 밖이라 범위 안으로 묶음")
        return ref, reason

    def _decide_in_break(self, clock: str, price: float, lo: float, hi: float,
                         ref_low: float | None, ref_high: float | None) -> None:
        """막힌(휴장) 시각의 가격 — 청산을 정하기만 하고 주문하지 않는다. 정한 사유는 `break_exit` 에 두고 다시 묻지 않음.

        청산 재시도를 기다리는 중(`retry_reason`)이면 그 사유가 이미 정해져 있어 묻지 않는다."""
        if self.break_exit is not None or self.retry_reason is not None:
            return
        judge = getattr(self.strat, EXIT_HOOK, None)
        if judge is not None:
            got = self._judged(judge, clock, price, ref_low, ref_high)
        else:
            got = self._common_exit(clock, price, lo, hi, ref_low, ref_high)
        if got is None:
            return
        self.break_exit = got[1]
        self.j.write("event", clock=clock, text=f"휴장 중 청산 판단 ({got[1]}) — 휴장이 끝난 첫 가격에 주문")

    def _note_block(self, key: str, clock: str, text: str) -> None:
        if key not in self._block_noted:
            self._block_noted.add(key)
            self.j.write("event", clock=clock, text=text)

    def _pos_view(self) -> dict:
        """`exit_reason` 에 넘기는 보유의 사본 — 진입 날짜와 진입 신호 객체를 더한다."""
        view = dict(self.pos)
        view.setdefault("entry_date", self.live_date)
        view["signal"] = self.entry_signal
        return view

    # ---- 진입·청산
    def _enter(self, clock: str, price: float) -> None:
        e, self.pending = self.pending, None
        sig = e.get("obj")
        fn = getattr(self.strat, "on_entry", None)
        # on_entry 인자 대응은 주문 전에 맞춰 본다 — 틀리면 주문을 내지 않고 오류(체결 뒤 오류면 정리 주문이 또 나간다)
        entry_call = None if fn is None else _entry_args(fn, sig)
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
        window = getattr(sig, "window", None)
        if isinstance(window, (str, int)) and not isinstance(window, bool):
            self.pos["window"] = window     # trade 줄에 남겨 같은 날 다시 세운 실행이 이어받게
        self.entry_signal = sig
        if fn is not None and entry_call is not None:
            args, kwargs = entry_call
            fn(*args, **kwargs)
        # 진입 줄에도 window — trade 없이 끝난 실행(확인 필요·앱 꺼짐)도 같은 날 다시 세운 실행이 이어받게
        tag = {"window": self.pos["window"]} if "window" in self.pos else {}
        self.j.write("event", clock=clock, text=f"진입 {e['side']} {px} · 손절 {self.pos['stop']} ({e['stop_ticks']}틱)",
                     **tag)

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
                self.retry_reason = reason
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
        if self.currency == "KRW":
            fee_txt = "" if fee is None else f" · 수수료 {fee:,.0f}원 → {t['pnl_after_fee']:+,.0f}원"
        else:
            fee_txt = "" if fee is None else f" · 수수료 {fee:,.2f} USD → {t['pnl_after_fee']:+,.2f} USD"
        row = {k: t[k] for k in ("side", "entry", "exit", "entry_time", "exit_time", "ticks", "pnl",
                                 "fee", "pnl_after_fee", "reason", "exit_date")}
        if "window" in t:
            row["window"] = t["window"]
        self.j.write("trade", clock=clock, text=f"{reason} {ticks:+d}틱 ({_money(pnl, self.currency)}){fee_txt}", **row)
        # 보유를 먼저 비운다 — 전략의 on_exit 가 예외를 내도 끝내기 정리가 이미 닫은 보유를 또 닫지 않게
        self.pos = None
        self.retry_after = ""
        self.retry_reason = None
        self.break_exit = None
        self.entry_signal = None
        self._hook("on_exit", pnl, stopped=reason == "손절")

    def _hook(self, name: str, *args, **kwargs) -> None:
        """전략의 고를 수 있는 메서드(`end_of_day` `on_exit`)를 부른다. 없으면 아무것도 하지 않는다.
        (`on_entry` 는 신호 칸을 넘기므로 `_enter` 가 따로 부른다.)"""
        fn = getattr(self.strat, name, None)
        if fn is not None:
            fn(*args, **kwargs)

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
        if self.blocked is not None and self.blocked(clock):
            return      # 팀: 휴장 중엔 정리 주문도 내지 않는다 — 실행이 「확인 필요」로 끝낸다
        if self.pos is not None and self.last_price is not None:
            # 휴장 중 정한 청산이 아직이면 그 사유로 (휴장 중 손절 → 20:50 정리가 「손절」로 세지게). 없으면 실행 종료 정리
            self._exit(clock, self.last_price, self.break_exit or END_REASON)

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

    def _exit_levels(self) -> dict | None:
        """전략의 `exit_levels(pos)` 가 보이는 손절·익절({"stop", "target"} 중 있는 칸). 없거나 실패하면 None.

        **화면 표시용**입니다 — 청산 판단에는 쓰지 않습니다. 화면을 그리다 전략 예외로 실행이 멈추지 않게 예외는
        삼키고 원래 값(실행기의 손절가·`target`)을 보입니다. 칸이 None 이면 None(없음), 수가 아닌 값·비유한수인 칸은
        원래 값을 보입니다."""
        fn = getattr(self.strat, LEVELS_HOOK, None)
        if fn is None:
            return None
        try:
            got = fn(self._pos_view())
        except Exception:       # 화면용 계산이 실행을 멈추게 하지 않는다
            return None
        if not isinstance(got, dict):
            return None

        out: dict = {}
        for k in ("stop", "target"):
            if k not in got:
                continue
            v = got[k]
            if v is None:
                out[k] = None
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue        # 수가 아님 → 원래 값
            try:
                f = float(v)    # 아주 큰 정수는 여기서 OverflowError — 원래 값
            except OverflowError:
                continue
            if math.isfinite(f):
                out[k] = f
        return out

    def snapshot(self) -> dict:
        """화면에 보일 지금 상태."""
        pos = self.pos
        day = [t for t in self.trades if t.get("exit_date") == self.live_date]
        # 하루 손절 수는 전략이 진입을 막는 데 쓰는 값(`day.stops`)을 따른다 — 앞선 실행의 손절도 들어 있다.
        # `day` 가 없는 전략이면 이 실행이 센 손절에 앞선 실행의 손절(`stops_before`)을 더한다
        own_stops = sum(1 for t in day if t["reason"] == "손절") + self.stops_before
        day_stops = getattr(getattr(self.strat, "day", None), "stops", None)
        time_exit = None
        stop = None if pos is None else pos["stop"]
        target = target_of(self.strat)
        levels = self._exit_levels() if pos is not None else None
        if levels is not None:      # 전략이 보이는 손절·익절 — 화면에만 쓴다(판단은 위의 규칙·`exit_reason`)
            stop = levels.get("stop", stop)
            target = levels.get("target", target)
        if pos is not None and getattr(self.strat, EXIT_HOOK, None) is None:   # 전략이 청산을 판단하면 앱의 시간 청산은 없다
            m = _minutes_of(pos["entry_time"]) + self.p.hold_min
            time_exit = f"{m // 60:02d}{m % 60:02d}00"
        return {
            "position": self.expected_position(),
            "entry": None if pos is None else pos["entry"],
            "stop": stop,
            "stop_ticks": None if pos is None else pos["stop_ticks"],
            "target": target,
            "time_exit_at": time_exit,
            "today_pnl": sum(t["pnl"] for t in day),
            "stops": own_stops if day_stops is None else day_stops,
            "max_stops": getattr(self.p, "max_stops_per_day", None),
            "halted": self.halted,
            "last_signal": self.last_signal,
        }
