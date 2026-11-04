# 전략 파일 만들기 프롬프트 (AI 에 그대로 붙여 넣기)

> 쓰는 법: 아래 `---` 사이를 통째로 복사해 AI(Claude·ChatGPT 등)에 붙여 넣고, 맨 끝 「내 전략」 칸에 전략 설명이나
> 기존 코드(백테스트 파일 등)를 넣으세요. 나온 `.py` 를 「전략주문 › 파이썬 전략」에 올리면 됩니다.
> 사람이 읽는 자세한 설명은 `strategy-file-convention.md` 입니다. 이 프롬프트는 그 문서를 AI 가 틀리지 않게 줄인 것입니다.

---

너는 NH선물 모의투자 앱의 **파이썬 전략 파일**을 쓰는 사람이다. 앱(실행기)이 주문·체결·잔고 대조·기록·안전장치를 모두 맡고,
전략 파일은 **언제 사고팔지(판단)만** 정한다. 아래 약속을 **하나도 어기지 말고** 내 전략을 `.py` 파일로 만들어라.

## 0. 답의 모양

1. 먼저 내 전략이 **1분봉 전략**인지 **실시간 전략**인지 정하고 한 줄로 말한다(1장 표).
2. 완성된 파일 전체를 코드 블록 하나로 준다. 파일 이름을 첫 줄 주석이 아니라 코드 블록 위에 적는다(예: `strategy_myidea.py`).
   - 공용 모듈이 따로 필요하면 그 파일도 각각 코드 블록으로 준다(같은 폴더에 함께 올림).
3. 그 아래에 짧게: 고른 Params 기본값과 까닭, 내 설명에서 **모호해서 네가 정한 것**, 앱 기본 동작에 맡긴 것.
4. 9장 점검표를 스스로 확인하고, 어긴 것이 없다고 한 줄로 적는다.
5. 내 설명이 모자라서 판단 규칙 자체를 지어내야 한다면, 코드 대신 **질문**을 먼저 한다(진입·청산 규칙은 지어내지 않는다).

## 1. 어느 실행기인가

| 전략 | 실행기 | 클래스가 가질 것 |
|---|---|---|
| 1분봉(또는 N분봉)으로 판정 — 대부분 | **1분봉** | `on_minute` |
| 초 단위로 KRX 체결을 보고 MKU 를 주문(leadlag 류) | **실시간** | `on_krx` · `on_quote` · `on_timer` · `filled_entry` · `filled_exit` |

한 클래스에 둘을 섞으면 불러오기 오류다. 한 실행 = 전략 하나 × 주문 종목 하나 × 하루, **늘 1계약, 보유는 한 번에 하나**.

## 2. 반드시 지킬 것 (어기면 불러오기 오류이거나 위험)

- **주문·잔고·계좌 API 를 부르지 않는다.** `requests`·웹소켓·NH 클라이언트·파일 쓰기·네트워크 코드를 넣지 않는다.
  주문은 앱이 한다. 전략은 값을 돌려주기만 한다.
- **import 는 파일 맨 위에서만.** 메서드 안 import 는 실행 중에 실패한다.
  쓸 수 있는 것: 파이썬 표준 라이브러리, 앱에 든 공용 모듈 `strategy`(4장), 같은 폴더에 함께 올린 `.py`.
  `numpy`·`pandas` 같은 외부 패키지는 쓰지 않는다(앱 환경에 없을 수 있음).
- 파일 이름: 영문·숫자·`_`·`-` + `.py`. UTF-8, 256 KB 이하.
- 그 파일에서 **정의한** 전략 클래스(1장의 메서드를 가진 것)는 **딱 하나**. 여럿이면 파일 끝에 `STRATEGY = 고른클래스`.
- 생성자는 `__init__(self, p)` — 인자는 Params 하나. 그리고 `self.p = p` 를 꼭 둔다.
- Params 는 `@dataclass`, **모든 칸에 기본값**(앱은 `Params()` 를 인자 없이 만들고 기본값이 곧 실행 값이다).
- 시각은 모두 `"HHMMSS"` 글자(한국시간). 날짜는 `"YYYYMMDD"`.
- 앱이 쓰는 청산 사유 `"장 마감 정리"` · `"실행 종료 정리"` 는 전략이 쓰지 않는다.
- 이미 있는 파일(예: 접속·주문까지 든 `ws_trader.py`)을 고칠 때는, **판단을 클래스 하나로 나누고 그 클래스가 접속·주문 모듈을
  쓰지 않게** 하면 된다. 앱은 앱에 없는 모듈을 쓰는 부분만 빼고 실행한다. `TICK` 같은 값은 그 모듈에서 가져오지 말고 파일에 직접 적는다.
  새로 쓰는 파일은 판단만 쓴다.
- 전략 코드에서 예외가 나면 실행이 「오류」로 끝난다. `None`·빈 목록·0 나누기를 스스로 막는다.

## 3. 1분봉 전략 약속

### 3-1. 앱이 부르는 것

`on_minute(self, m) -> list` — 1분봉 하나를 받을 때마다 부른다. 이 봉으로 **판정한 것**이 있으면 `Signal` 목록을, 없으면 `[]`.
- 장중: 분이 바뀌고 3초 뒤 직전 1분봉. 시작할 때는 **전날 봉부터** 준비 봉으로 넣는다(지표를 날 넘어 이을지는 전략이 정함).
- `m` 의 칸: `m.date`(`YYYYMMDD`) `m.time`(`HHMMSS`, 그 분의 **시작**) `m.open` `m.high` `m.low` `m.close` `m.volume`(모두 float).
- N분 판정이면 N분째 1분봉에서만 신호를 낸다.

### 3-2. Signal (돌려주는 것)

| 칸 | 뜻 |
|---|---|
| `bar` | 판정 봉 (아래) |
| `side` | `"buy"` · `"sell"` · `None`(진입 안 함) |
| `reason` | 글 — 근거나 진입 안 한 까닭. 기록·화면에 그대로 |
| `stop_ticks` | 손절 폭(틱, **양의 정수**). `side` 가 있으면 꼭 |

`bar` 가 가질 칸: `date` `start`(판정 봉 시작) `end`(판정 봉의 마지막 1분봉 시작) `close`. 있으면 `open` `high` `low` 로 차트에 봉을 그린다.
그 밖의 **숫자 칸**(예: `vwap` `upper` `rsi`)은 지표로 기록·차트에 남는다(NaN·무한대는 빠짐).
dataclass 든 보통 객체든 이름만 맞으면 된다. 공용 모듈의 `Signal(bar, side, reason, stop_ticks)` · `SignalBar` 를 써도 된다.
신호에 `window` 칸(개장 이름, 글자 또는 정수)을 두면 「개장마다 한 번」 진입을 앱이 이어받는다(6장).

### 3-3. Params 필수 6칸

| 칸 | 형식 | 뜻 |
|---|---|---|
| `session_start` | `"HHMMSS"` | 이 시각부터 장중(그 전은 「대기」) |
| `session_end` | `"HHMMSS"` | 판정 시간 끝 |
| `entry_start` | `"HHMMSS"` | 진입 허용 시작(이상) |
| `entry_end` | `"HHMMSS"` | 진입 허용 끝(미만) — 밖의 신호는 버림 |
| `flatten_at` | `"HHMMSS"` | 이 시각부터 앱이 보유를 정리(「장 마감 정리」) |
| `hold_min` | 정수(분) | 진입 뒤 이만큼 지나면 앱이 청산(「시간 청산」) |

- **국내 미국달러선물은 6칸 모두** 있어야 한다. 기본값 예: `session_start="090000"` `session_end="153500"` `entry_start="093000"`
  `entry_end="150000"` `flatten_at="153000"`(모의계좌 주문은 09:00부터, 장은 15:45 마감).
- **해외 MKU 는 `hold_min` 만 꼭** 있으면 되고, 장 시간 5칸이 없으면 앱이 채운다(`session_start`=`entry_start`=`"082500"`,
  `flatten_at`=`"235000"`, `entry_end`=flatten_at, `session_end`=`"235500"`). 직접 적어도 된다.
- 앱이 더 읽는 칸(있으면): `bar_min`(판정 봉 분 — 화면의 「다음 판정」), `max_stops_per_day`(화면의 손절 한도).

### 3-4. 앱의 기본 체결·청산 (전략이 `exit_reason` 을 두지 않을 때)

- 진입: 신호가 나오면 **다음 가격**에 1계약. 진입 시간 밖이거나 보유 중이면 무시.
- 손절 = 진입가 ∓ `stop_ticks` 틱. 익절 = 인스턴스의 `target`(가격, `None` 이면 지금은 없음, 매번 읽음) → 없으면
  `current_vwap` → 둘 다 없으면 익절 없음. 시간 청산 = `hold_min`. `flatten_at` 에 장 마감 정리.

### 3-5. 있으면 앱이 쓰는 것 (없어도 됨)

| 이름 | 어디 | 언제·뜻 |
|---|---|---|
| `target` | 인스턴스(값 또는 property) | 익절 목표 가격 |
| `day` 객체의 `stops` · `in_position` | 인스턴스 | `day.stops` = 그날 손절 수(같은 날 앞선 실행의 손절도 앱이 넣어 줌). 전략이 진입을 막는 데 쓴다 |
| `end_of_day()` | 메서드 | 날이 바뀌어 새 날 첫 봉 직전 |
| `on_entry(…)` | 메서드 | 진입 체결 뒤. 매개변수 이름과 **같은 이름의 진입 신호 칸** 값을 넘긴다(예: `on_entry(self, window)`). 없는 이름에 기본값이 없으면 주문 전에 오류 |
| `on_exit(pnl, stopped)` | 메서드 | 청산 뒤. `pnl` = 그 시장 통화 손익(수수료 전, 국내 원·MKU 달러), `stopped` = 사유가 `"손절"` |
| `exit_reason(…)` · `exit_levels(pos)` | 메서드 | 5장 |
| `STRATEGY` · `TITLE` · `NAME` | 모듈 | 없으면 클래스 자동 · 모듈 문서 첫 줄의 「 — 」 앞 · 파일 이름. `NAME` 은 영문·숫자·`_`·`-` |
| `TICK` · `TICK_VALUE` | 모듈 | 없으면 `0.1` · `1000`(국내 미국달러선물). MKU 는 **`TICK = 0.0001` · `TICK_VALUE = 2.5`** 를 꼭 적는다 |

## 4. 공용 모듈 `strategy` (import 해서 써도 됨)

`from strategy import …` 로 쓸 수 있는 이름(week02 원본): `TICK`(0.1) `TICK_VALUE`(1000) `Params`(VWAP 전략용) `Minute`
`SignalBar`(`date start end open high low close volume vwap sigma upper lower atr`) `Signal`(`bar side reason stop_ticks`)
`DayState`(`realized_pnl stops in_position bars_since_exit`) `SessionVWAP`(`update(m)` `reset()` `vwap` `sigma`)
`WilderATR`(`update(high, low, close)` `value`) `minutes_of(hhmmss)` `hhmmss_of(minutes)` `stop_price` `tick_up` `tick_down`
`take_profit_price` `pnl_ticks`. **틱 계산 함수들은 틱 0.1 을 가정**하므로 MKU 전략에서는 쓰지 말고 직접 계산한다.
`from strategy import TICK` 를 MKU 전략에서 쓰면 틱이 0.1 이 되어 국내로 잡힌다 — MKU 는 파일에 `TICK = 0.0001` 을 직접 둔다.

## 5. 전략이 직접 청산할 때 (`exit_reason`, 1분봉만)

전략 클래스에 `exit_reason` 이 있으면 앱은 **공통 손절·익절·시간 청산을 쓰지 않고** 이것만 묻는다(시간 청산도 직접 챙긴다).

```text
exit_reason(self, clock, price, low, high, pos) -> None | "사유" | ("사유", 기준가)
```

- `clock` `HHMMSS` · `price` 이번 가격 · `low`·`high` 그 분 저가·고가(**가격 하나만 줄 때는 `None`** — 장중 현재가, 리플레이의 시가).
- `pos` 는 보유의 사본 dict: `side`(`"buy"`/`"sell"`) `entry` `entry_time` `entry_date` `signal_time` `stop`(진입가 ∓ stop_ticks)
  `stop_ticks` `signal`(진입 신호 객체 또는 `None`) `window`(있으면).
- 리플레이는 한 분에 두 번 묻는다: 먼저 시가로(`low`·`high` = `None`), 다음에 종가와 저가·고가로.
- 돌려주는 값: `None` 들고 있음 · `"사유"` 지금 가격으로 청산 · `("사유", 기준가)` 그 가격 기준. 기준가는 앱이 `[low, high]`
  (가격 하나면 그 가격)로 묶는다. 사유는 40자 이하 글자, `"손절"` 이면 하루 손절 수에 들어간다. 그 밖의 값은 `TypeError`.
- 앱이 먼저 보는 것: 멈춤 → 청산 확인 대기 → `flatten_at` 정리 → 앞선 청산 재시도 → 그다음에 `exit_reason`.
- `exit_levels(self, pos) -> {"stop": 가격|None, "target": 가격|None}` — 화면 표시 전용(판단에 안 씀).

## 6. 해외 MKU(SGX 미니 원달러) 1분봉

- 모듈에 `TICK = 0.0001`, `TICK_VALUE = 2.5`(1틱 = US$2.5). 손익·수수료는 USD.
- 시간표(한국시간): 장 08:25~20:35 · **휴장 20:35~20:50** · 20:50~. 실행은 23:55 에 끝난다. 휴장엔 앱이 주문을 내지 않고
  진입·청산을 휴장 뒤 첫 가격으로 미룬다 — 전략이 휴장을 따로 다룰 필요는 없다.
- 값은 원 1,000원당 달러(예: 0.7433). 원/달러가 오르면 MKU 는 내린다.
- 개장이 여러 번인 전략은 신호에 `window` 를 두고 `on_entry(self, window)` 로 「그 개장은 진입함」을 기억하게 하라 —
  장중에 다시 켜도 앱이 같은 개장에 두 번 들어가지 않게 이어 준다.

## 7. 실시간 전략 약속 (초 단위, 주문은 MKU 만)

신호는 KRX 미국달러선물 체결·주문은 MKU 호가로 본다. 모듈에 `TICK = 0.0001` 과 `TICK_USD = 2.5`(또는 `TICK_VALUE = 2.5`).
Params 는 `Params` 또는 `LiveParams`(dataclass, 모든 칸 기본값, 필수 칸 없음). `flatten_at`(`"HHMMSS"`)을 두면 실행 끝 = 그 시각 + 5분.

| 앱이 부르는 것 | 언제 | 돌려줄 것 |
|---|---|---|
| `on_krx(self, price, now, hhmmss)` | KRX 체결 하나(체결량 > 0) | 행동 dict 또는 `None` |
| `on_quote(self, bid, ask, now, hhmmss)` | MKU 1단 호가 하나 | 행동 dict 또는 `None` |
| `on_timer(self, now, hhmmss)` | 1초마다 | 행동 dict 또는 `None` |
| `filled_entry(self, side, price, now, hhmmss, ord_no="")` | 진입 체결 뒤 | 없음. `self.pos` 를 세우고 `self.pending = False` |
| `filled_exit(self, price, now, reason)` | 청산 체결 뒤 | dict(있으면 `gross_ticks` `net_ticks` `net_usd` `held_s` 를 기록) · `self.pos = None` · `self.pending = False` |

- `now` 는 **받은 순간의 단조 시계(초, float)** — 구간 계산은 이것으로. `hhmmss` 는 표시·시간대 판단용.
- **행동 dict**: `{"act": "enter" | "exit", "side": 1 | -1, "ref": 기준 호가(>0), "reason": "글", "time": hhmmss}`.
  `side` 는 **MKU 방향**(+1 매수, −1 매도)이고 `True`/`False` 는 안 된다. 기록용 숫자 칸 `dk` `rho` `spread` `expected` `followed` 를 더해도 된다.
  - 보유 중 `enter`, 보유 없이 `exit`, 보유와 같은 방향의 `exit` 는 오류(주문 안 남).
- **`self.pending`**: 행동을 돌려주는 순간 `True` 로 두고, 그동안 새 행동을 내지 않는다. 체결은 `filled_*` 로, **진입이 거절되면
  앱이 `pending = False` 로 되돌린다**(그 신호는 버려짐). 청산이 거절되면 앱이 10초 뒤 같은 사유로 다시 낸다.
- 화면이 읽는 이름(있으면): `pending` · `pos`(dict, `side` `price`) · `stops`(그날 손절 수 — 앱이 앞선 실행 값을 넣어 줌).
- 청산 사유 `"손절"` 이면 하루 손절 수로 센다. 「마감」 청산은 전략이 `flatten_at` 에 직접 낸다(늦으면 실행 끝에 앱이 「실행 종료 정리」).
- 휴장(20:35~20:50)엔 앱이 진입 행동을 버리고 청산은 휴장 뒤로 미룬다. 끊겼다 붙은 시세 공백은 전략이 `now` 차이로 버려야 한다
  (예: `stale_s` 초보다 오래 끊긴 직전 값은 쓰지 않기).

## 8. 지어내지 말 것

- 진입·청산 규칙, 숫자 기준을 내 설명에 없는데 만들지 않는다 → 묻는다. 기본값만 「출발값」으로 정하고 그렇다고 적는다.
- 앱이 하는 일(주문, 체결가 계산, 슬리피지, 수수료, 잔고 확인, 재시도, 휴장 처리, 기록 파일)을 전략에 다시 만들지 않는다.
- 응답 칸 이름·API 를 추측해 쓰지 않는다 — 전략은 위 인자만 받는다.

## 9. 답하기 전 점검표

- [ ] 1분봉/실시간 중 하나만, 해당 메서드 이름과 인자 순서가 위 표와 같다
- [ ] 전략 클래스 하나(또는 `STRATEGY =`), `__init__(self, p)` 에서 `self.p = p`
- [ ] Params 는 `@dataclass`, 모든 칸 기본값. 1분봉 국내는 6칸, MKU 는 `hold_min` 이상
- [ ] 시각은 `"HHMMSS"` 글자로 비교, 분 계산은 직접 변환
- [ ] MKU 면 모듈에 `TICK = 0.0001`, `TICK_VALUE`(또는 `TICK_USD`) `= 2.5`, 틱 0.1 가정 함수 안 씀
- [ ] `side` 가 있는 Signal 에 양의 정수 `stop_ticks` / 실시간 행동은 `act`·`side`(±1)·`ref`(>0)
- [ ] import 는 맨 위, 표준 라이브러리·`strategy`·함께 올릴 파일만. 네트워크·파일·주문 코드 없음
- [ ] 준비 전(지표 부족)·`None` 값에서 예외 없이 `[]` 또는 `side=None` 신호
- [ ] 예약 사유(`"장 마감 정리"` `"실행 종료 정리"`) 안 씀

## 10. 뼈대 (여기서 시작)

**1분봉 — 국내 미국달러선물**

```python
"""전략 이름 — 한 줄 설명."""
from dataclasses import dataclass

from strategy import Signal

TICK = 0.1
TICK_VALUE = 1000


@dataclass(frozen=True)
class Params:
    stop_ticks: int = 5
    hold_min: int = 30
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"


@dataclass
class Bar:
    date: str
    start: str
    end: str
    close: float


class MyStrategy:
    """판단 규칙 한 줄."""

    def __init__(self, p: Params) -> None:
        self.p = p

    def on_minute(self, m) -> list:
        if not (self.p.session_start <= m.time < self.p.session_end):
            return []
        bar = Bar(m.date, m.time, m.time, m.close)
        # 판단: 조건이 맞으면 Signal(bar, "buy" 또는 "sell", "근거", self.p.stop_ticks)
        return [Signal(bar, None, "조건 없음")]
```

**1분봉 — 해외 MKU** (장 시간 칸은 앱이 채움)

```python
"""MKU 전략 이름 — 한 줄 설명."""
from dataclasses import dataclass

TICK = 0.0001
TICK_VALUE = 2.5


@dataclass(frozen=True)
class Params:
    stop_ticks: int = 8
    hold_min: int = 60


@dataclass
class Bar:
    date: str
    start: str
    end: str
    close: float


@dataclass
class Signal:
    bar: Bar
    side: str | None
    reason: str
    stop_ticks: int | None = None


class MyMkuStrategy:
    """판단 규칙 한 줄."""

    def __init__(self, p: Params) -> None:
        self.p = p

    def on_minute(self, m) -> list:
        bar = Bar(m.date, m.time, m.time, m.close)
        return [Signal(bar, None, "조건 없음")]
```

**실시간 (KRX 체결 → MKU 주문)**

```python
"""실시간 전략 이름 — 한 줄 설명."""
from collections import deque
from dataclasses import dataclass

TICK = 0.0001
TICK_USD = 2.5


@dataclass(frozen=True)
class LiveParams:
    lookback_s: float = 45
    sl_ticks: float = 5
    hold_s: float = 300
    entry_start: str = "090000"
    entry_end: str = "152000"
    flatten_at: str = "154000"


class Engine:
    """판단 규칙 한 줄."""

    def __init__(self, p: LiveParams) -> None:
        self.p = p
        self.krx = deque()          # (now, price)
        self.bid = self.ask = None
        self.pos = None             # {"side", "price", "t", "time"}
        self.pending = False
        self.stops = 0

    def on_krx(self, price: float, now: float, hhmmss: str) -> dict | None:
        self.krx.append((now, price))
        while self.krx and now - self.krx[0][0] > self.p.lookback_s:
            self.krx.popleft()
        return None                 # 진입 판단: {"act": "enter", "side": ±1, "ref": 반대 호가, "reason": "…", "time": hhmmss}

    def on_quote(self, bid: float, ask: float, now: float, hhmmss: str) -> dict | None:
        self.bid, self.ask = bid, ask
        return self._exit_check(now, hhmmss)

    def on_timer(self, now: float, hhmmss: str) -> dict | None:
        return self._exit_check(now, hhmmss)

    def _exit_check(self, now: float, hhmmss: str) -> dict | None:
        if not self.pos or self.pending or self.bid is None:
            return None
        side = self.pos["side"]
        ref = self.bid if side > 0 else self.ask
        ticks = side * (ref - self.pos["price"]) / TICK
        reason = ("손절" if ticks <= -self.p.sl_ticks else "시간" if now - self.pos["t"] >= self.p.hold_s
                  else "마감" if hhmmss >= self.p.flatten_at else None)
        if reason is None:
            return None
        self.pending = True
        return {"act": "exit", "side": -side, "ref": ref, "reason": reason, "time": hhmmss}

    def filled_entry(self, side: int, price: float, now: float, hhmmss: str, ord_no: str = "") -> None:
        self.pos = {"side": side, "price": price, "t": now, "time": hhmmss}
        self.pending = False

    def filled_exit(self, price: float, now: float, reason: str) -> dict:
        pos = self.pos
        gross = pos["side"] * (price - pos["price"]) / TICK
        self.stops += reason == "손절"
        self.pos, self.pending = None, False
        return {"gross_ticks": round(gross, 2), "held_s": round(now - pos["t"], 1)}
```

## 내 전략

(여기에 전략 설명을 적거나, 백테스트 코드를 붙여 넣는다. 무엇을 보고 언제 들어가고 언제 나오는지, 종목(국내 미국달러선물 / MKU),
판정 봉(1분·5분·초 단위), 손절·익절·보유 시간, 하루 진입 한도를 적으면 좋다.)

---
