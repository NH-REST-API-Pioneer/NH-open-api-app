# 전략 파일 작성 규칙

「전략주문 › 파이썬 전략」에 올리는 `.py` 파일 하나를 어떻게 쓰는지 적은 문서입니다.
week02 의 `strategy.py`(VWAP)·`strategy_bb.py`(볼린저)는 **고치지 않고 그대로 하나만 올려도** 돕니다.
새 전략을 쓸 때는 맨 아래 예제에서 시작하세요.

## 1. 앱이 하는 일과 파일이 하는 일

실행기(체결·감시·기록)는 **앱에 들어 있습니다.** 파일은 **언제 사고팔지만** 정합니다.

| 앱(실행기)이 하는 일 | 파일(전략)이 하는 일 |
|---|---|
| 1분봉을 받아 `on_minute` 에 넣기 (장중: 분이 바뀌고 3초 뒤, 리플레이: 받아 둔 봉) | 1분봉을 받아 지표를 갱신하고, 판정할 때 `Signal` 을 돌려주기 |
| 신호가 나오면 다음 가격에 1계약 진입 (진입 시간 안에서만, 보유 중이면 무시) | 매수·매도·없음과 그 까닭, 손절 틱 정하기 |
| 손절·익절·시간 청산·장 마감 정리 감시와 청산 주문 | (고르면) 익절 목표 가격 알려 주기 |
| 주문 방식(종이 / 모의 계좌), 잔고 대조, 멈춤, 기록·요약·차트 | — |

- 실행 하나 = 전략 파일 하나 × 종목 하나 × 하루입니다. 늘 1계약이고, 한 번에 보유 하나입니다.
- 주문·잔고·재전송 방지 같은 안전장치는 실행기에 있습니다. 파일에서 주문 API 를 부르지 마세요.

## 2. 꼭 있어야 하는 것

### 전략 클래스 하나

- 그 파일에서 정의한 클래스 중 `on_minute` 메서드가 있는 것이 **딱 하나**여야 합니다.
  (`from strategy import VWAPReversion` 처럼 가져온 클래스는 세지 않습니다.)
  여럿이면 파일 끝에 `STRATEGY = 고른클래스` 를 적으세요.
- 앱은 `전략클래스(Params())` 로 인스턴스를 만듭니다 — 생성자 인자는 Params 하나입니다.
- 인스턴스에 꼭 있어야 하는 이름: `on_minute`, `p`(받은 Params).

`on_minute(m) -> list[Signal]` — 1분봉 하나를 받고, 이 봉으로 **판정한 것**이 있으면 `Signal` 들을 돌려줍니다.
판정할 게 없으면 `[]`. 5분 판정이라면 5분째 1분봉에서만 신호를 내면 됩니다.

받는 1분봉 `m` 의 칸:

| 칸 | 뜻 |
|---|---|
| `m.date` | `YYYYMMDD` |
| `m.time` | `HHMMSS` — 그 분의 **시작** 시각 |
| `m.open` `m.high` `m.low` `m.close` | 가격 (float) |
| `m.volume` | 거래량 (float) |

앱은 **전날 봉부터** 넣습니다(준비 봉). 지표를 날을 넘겨 이어 셀지는 전략이 정합니다.

### Signal — 앱이 읽는 칸

| 칸 | 뜻 |
|---|---|
| `side` | `"buy"` · `"sell"` · `None`(진입 신호 없음) |
| `reason` | 신호 근거나 진입하지 않은 까닭 (글) — 기록과 화면에 그대로 남습니다 |
| `stop_ticks` | 손절 폭(틱, 양의 정수). `side` 가 있으면 **꼭** 있어야 합니다 |
| `bar` | 판정 봉 (아래) |

`bar`(판정 봉)에서 앱이 읽는 칸:

| 칸 | 뜻 |
|---|---|
| `bar.date` | `YYYYMMDD` |
| `bar.start` | 판정 봉 시작 `HHMMSS` |
| `bar.end` | 판정 봉의 마지막 1분봉 시작 `HHMMSS` |
| `bar.close` | 종가 |
| `bar.open` `bar.high` `bar.low` | (고르면) 차트에 봉으로 그립니다 |
| 그 밖의 숫자 칸 | 지표로 보고 기록·차트에 남깁니다 (예: `vwap` `upper` `rsi`). NaN·무한대는 뺍니다 |

`Signal`·`bar` 는 dataclass 든 보통 객체든 위 이름만 있으면 됩니다. 기본 공용 모듈의 `Signal`·`SignalBar` 를 써도 됩니다.

### Params — dataclass, 모든 칸에 기본값

앱은 `Params()` 를 인자 없이 만듭니다. 그래서 **모든 칸에 기본값**이 있어야 하고, 기본값이 곧 실행 값입니다.
찾는 순서: ① 이 파일에서 정의한 `Params`(dataclass) → ② 전략 `__init__` 첫 인자의 주석(dataclass, 예: `def __init__(self, p: MyParams)`)
→ ③ 가져온 `Params`(예: `from strategy import Params`). 자기 Params 를 주석으로 밝히면 가져온 `Params` 보다 먼저 쓰입니다.

반드시 있어야 하는 6칸:

| 칸 | 형식 | 뜻 |
|---|---|---|
| `session_start` | `"HHMMSS"` 글 | 이 시각부터 장중으로 봅니다 (그 전은 「대기」) |
| `session_end` | `"HHMMSS"` 글 | 판정 시간의 끝 (예: 마감 단일가 `"153500"`). 리플레이는 이 시각부터의 봉에서 나온 신호를 버립니다 |
| `entry_start` | `"HHMMSS"` 글 | 진입 허용 시작 (이상) |
| `entry_end` | `"HHMMSS"` 글 | 진입 허용 끝 (미만). 밖에서 나온 신호는 버립니다 |
| `flatten_at` | `"HHMMSS"` 글 | 이 시각부터 보유를 정리합니다 (「장 마감 정리」) |
| `hold_min` | 정수 (분) | 진입 뒤 이만큼 지나면 청산합니다 (「시간 청산」) |

앱이 더 읽는 칸(있으면): `bar_min`(판정 봉 분 — 화면의 「다음 판정」 시각), `max_stops_per_day`(화면의 손절 한도 표시).
나머지 칸은 전략 마음대로 씁니다. 실행 기록 맨 앞과 요약에 Params 전체가 남습니다.

## 3. 있으면 쓰는 것 (없어도 됩니다)

| 이름 | 어디에 | 없으면 |
|---|---|---|
| `target` | 인스턴스 (값 또는 property) | `current_vwap` 을 봅니다 |
| `current_vwap` | 인스턴스 | 익절 없이 돕니다 — 목록 줄 밑에 「target·current_vwap 이 없어 익절 없이 돕니다」 알림 |
| `day.stops` | 인스턴스의 `day` 객체 | 전략이 앞선 실행의 손절 수를 받지 못합니다(그날 손절 한도로 진입을 막을 수 없음). 화면의 손절 수는 앞선 실행 + 이 실행이 센 값 |
| `end_of_day()` | 메서드 | 건너뜀 |
| `on_entry()` | 메서드 | 건너뜀 |
| `on_exit(pnl_won, stopped)` | 메서드 | 건너뜀 |
| `STRATEGY` | 모듈 | `on_minute` 클래스를 찾습니다 |
| `TITLE` | 모듈 | 모듈 문서 문자열 첫 줄의 「 — 」 앞(끝의 「.」 은 뺌) → 클래스 문서 문자열 첫 줄 → 클래스 이름 |
| `NAME` | 모듈 | 파일 이름(확장자 뺀 것, 영문·숫자·`_`·`-` 밖의 글자는 `_`) |
| `TICK` · `TICK_VALUE` | 모듈 (`import` 해 온 것도 됨) | `0.1` · `1000` (미국달러선물) |

- **익절 목표** `target`: 가격(float). `None` 이면 지금은 익절하지 않습니다. 매번 읽으므로 봉마다 바꿔도 됩니다.
  닿았는지는 불리한 쪽 호가로 맞춰 봅니다(매수 보유는 올림, 매도 보유는 내림).
  `target` 이 없고 `current_vwap` 이 있으면 그것을 씁니다 — week02 VWAP 전략이 그렇게 돌았습니다.
- **`day.stops`**: 그날 손절 횟수. 같은 날 같은 전략·종목·방식으로 앞서 돈 실행이 있으면 앱이 시작할 때 그 손절 수를
  넣고, 전략이 오늘 첫 봉에서 `day` 를 새로 만들면 다시 넣습니다. 전략은 이 값으로 그날 진입을 막을 수 있습니다.
- **`end_of_day()`**: 날이 바뀌어 새 날의 첫 봉을 넣기 직전에 부릅니다. 돌려준 값은 쓰지 않습니다.
- **`on_entry()`**: 진입이 체결된 뒤. **`on_exit(pnl_won, stopped)`**: 청산 뒤. `pnl_won` 은 원 단위 손익(수수료 전),
  `stopped` 는 손절이면 `True`.
- **`NAME`** 은 실행 기록 폴더 이름에 들어갑니다. 적는다면 영문·숫자·`_`·`-` 만 쓰세요.
- **`TICK`·`TICK_VALUE`**: 손절가·익절가·손익 계산에 씁니다. 장중 실행은 시작할 때 서버의 미국달러선물 상품 정보
  (product-detail)와 비교해 다르면 시작하지 않습니다.

### 해외 MKU 로 돌릴 때 (1분봉 실행)

- **시장은 종목이 정합니다.** 종목 `A75…` 는 국내 미국달러선물, `MKU…` 는 해외 SGX 미니 원달러입니다.
  종목을 비워 두면 파일의 `TICK` 으로 고릅니다 — `TICK = 0.0001`(MKU 틱)이면 해외 마스터의 MKU 최근월물(만기일 기준 근월),
  아니면 미국달러선물 최근월물. **종목의 시장과 `TICK` 이 맞지 않으면**(MKU 틱 전략에 `A75…`, 또는 반대) 조회·주문 없이
  시작하지 않습니다. 시작할 때 해외 품목 정보의 MKU 틱·틱가치(0.0001 · US$2.5)와 `TICK`·`TICK_VALUE` 를 비교합니다.
- **시간표**: 장 08:25~20:35 · 휴장 20:35~20:50 · 20:50~. 실행은 23:55 에 끝납니다(국내 15:31). Params 에
  장 시간 칸이 없으면 해외 시간표로 채웁니다(국내는 칸이 있어야 합니다).
- **휴장(20:35~20:50)엔 주문을 하나도 내지 않습니다.** 그 사이 진입 대기 신호는 기다렸다가 20:50 이후 첫 가격에 진입하고,
  그 사이 정해진 청산(전략의 `exit_reason`, 없으면 앱의 손절·익절·시간 청산)은 **다시 묻지 않고** 20:50 이후 첫 가격에
  그 사유로 청산합니다(휴장 중 손절은 20:50 에 나가도 「손절」로 하루 손절 수에 들어갑니다). 정리 요청·중지 요청도
  휴장이 끝난 뒤 정리합니다. 휴장 중 오류·앱 종료로 끝나면 모의 계좌는 정리하지 않고 「확인 필요」, 종이 실행은
  「종이 보유는 마지막 가격으로 정리 안 함」으로 끝납니다(계좌가 없으므로 확인 필요가 아님).
  리플레이는 week03 백테스트와 같게 휴장을 막지 않습니다.
- **손익·수수료는 USD** 입니다(`summary.json`·화면의 `currency`). 종이 체결은 편도 US$2 · 불리한 쪽 1틱.
- **개장마다 한 번(`window`)** — 신호에 `window` 칸이 있으면 장중에 켜거나 같은 날 다시 세울 때 앱이 이어받습니다:
  준비 봉에서 **오늘** 진입 신호가 난 개장과, 오늘 같은 `NAME`·종목·방식의 앞선 실행이 들어간 개장(`trade`·진입 기록의 `window`)은
  「이미 진입함」입니다. 앱은 그 개장마다 `on_entry(window)` 를 부르고 **바로 `day.in_position` 을 `False`** 로 되돌립니다
  (보유는 없으므로). `on_exit` 는 부르지 않습니다 — 그날 손절 수는 앞선 실행의 실제 손절로 `day.stops` 에 한 번만 넣습니다.
  그래도 그 개장의 진입 신호가 나오면 앱이 대기 신호를 버립니다. `window` 가 없는 전략(week02)은 손절 수만 이어받습니다.

## 4. 기본 공용 모듈 `strategy`

앱에는 week02 `strategy.py` 원본이 그대로 들어 있습니다. 전략 폴더에 `strategy.py` 가 **없으면**
`import strategy` · `from strategy import …` 가 이것을 씁니다. 폴더에 `strategy.py` 가 있으면 **폴더의 것이 먼저**입니다.
기본 공용 모듈은 파일 목록에 나오지 않습니다.

들어 있는 이름:

| 이름 | 무엇 |
|---|---|
| `TICK` · `TICK_VALUE` | `0.1` · `1000` |
| `Params` | VWAP 전략의 Params (6칸 포함) |
| `Minute` | 1분봉 dataclass (`date time open high low close volume`) |
| `SignalBar` | 판정 봉 dataclass (`date start end open high low close volume` + `vwap sigma upper lower atr`) |
| `Signal` | `bar side reason stop_ticks` |
| `DayState` | 하루 상태 (`realized_pnl stops in_position bars_since_exit`) |
| `SessionVWAP` | 세션 VWAP 과 거래량 가중 σ (`update(m)` `reset()` `vwap` `sigma`) |
| `WilderATR` | Wilder ATR (`update(high, low, close)` `value`) |
| `VWAPReversion` | week02 VWAP 밴드 평균회귀 전략 |
| `minutes_of(hhmmss)` · `hhmmss_of(minutes)` | 시각 ↔ 분 |
| `stop_price` · `tick_up` · `tick_down` · `take_profit_price` · `pnl_ticks` | 틱 계산 (틱 0.1 가정) |

## 5. import

- **맨 위에서** import 하세요. 옆 파일(전략 폴더의 공용 모듈)과 기본 `strategy` 모듈은 불러오는 동안에만 보여서,
  메서드 안에서 import 하면 실패합니다.
- 쓸 수 있는 것: 파이썬 표준 라이브러리, 기본 공용 모듈 `strategy`, 전략 폴더의 다른 `.py`(이름으로),
  그리고 **앱이 도는 파이썬 환경에 설치된 패키지**. 내 컴퓨터의 다른 파이썬에 깔린 것은 상관없고,
  앱 환경(`just setup` 으로 만든 환경)에 있어야 합니다. 없으면 목록에 `ModuleNotFoundError` 로 보입니다.

## 6. 올리기 규칙

- 파일 이름: 영문·숫자·`_`·`-` 와 `.py` 만 (예: `strategy_bb.py`). 경로·공백·한글 이름은 받지 않습니다.
- 크기: UTF-8 로 **256 KB** 이하. **UTF-8** 이 아닌 파일은 올리지 않습니다.
- 같은 이름이 있으면 덮어쓸지 묻습니다(대소문자만 다른 이름도 같은 파일로 봅니다).
- 올릴 때는 컴파일도 실행도 하지 않습니다. 목록을 읽을 때 불러 보고, 고장 나면 그 줄에 오류로 보입니다.
- 카드에 보이는 전략 폴더에 직접 복사해 넣어도 같습니다.
- 돌고 있는 실행은 시작할 때 불러온 코드로 계속 갑니다. 파일을 덮어쓰거나 지워도 영향이 없습니다.

## 7. 오류가 나면

| 언제 | 어떻게 보이나 |
|---|---|
| 불러오기 실패 (문법 오류, import 실패, 위 약속 위반) | 목록 줄이 흐려지고 까닭이 붙습니다. 그 파일로는 실행을 세울 수 없습니다 |
| 알림 (익절 목표 없음) | 줄 밑에 흐린 글로 붙습니다. 실행은 세울 수 있습니다 |
| 시작할 때 (준비 봉에서 전략 예외, 틱 불일치, 시작 잔고 있음) | 시작을 거부합니다. 주문은 나가지 않고 실행 목록에 「끝 — 시작 거부: …」로 남습니다 |
| 장중에 전략 코드 예외 (`on_minute`·`target` 등) | 실행을 「오류」로 끝냅니다. 보유가 있으면 정리합니다 |

자주 보는 불러오기 오류:

- 「on_minute 이 있는 전략 클래스가 없습니다」 — 전략 클래스를 정의하지 않았거나 다른 파일에서 가져오기만 했습니다.
- 「전략 클래스가 여러 개입니다 (A, B) — 파일 끝에 「STRATEGY = A」 처럼 하나를 고르세요」
- `Params(dataclass) 를 찾지 못했습니다` — 모듈의 `Params` 도, 전략 `__init__` 첫 인자 주석도 dataclass 가 아닙니다(또는 없습니다).
- `Params 에 없는 이름: …` — 2장의 6칸 중 빠진 것.
- `전략에 없는 이름: …` — 인스턴스에 `on_minute`·`p` 가 없습니다.
- `NAME 은 영문·숫자·_·- 만 쓸 수 있습니다` · `TICK·TICK_VALUE 는 숫자여야 합니다`

## 8. 예제

1분 종가가 이동평균에서 벗어나면 반대로 들어가 평균에서 익절하는 전략입니다. 이대로 `my_strategy.py` 로 올리면 돕니다.
**모양을 보이려는 예제이고 수익 전략이 아닙니다** (2026-10-30 리플레이: 53건, −81,000원).

```python
"""이동평균 되돌림 — 작성 규칙 예제. 1분봉마다 판정합니다."""
from collections import deque
from dataclasses import dataclass

from strategy import TICK, Signal   # 앱에 든 기본 공용 모듈


@dataclass(frozen=True)
class Params:
    period: int = 20            # 평균 낼 1분봉 수
    gap_ticks: int = 5          # 평균에서 이만큼 벗어나면 반대로 진입
    stop_ticks: int = 5         # 손절 (틱)
    hold_min: int = 30          # 시간 청산 (분)
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
    ma: float | None = None     # 숫자 칸은 지표로 기록·차트에 남습니다


class MeanRevert:
    """1분 종가가 이동평균에서 벗어나면 반대로 들어가 평균에서 익절합니다."""

    def __init__(self, p: Params) -> None:
        self.p = p
        self.closes = deque(maxlen=p.period)
        self.target = None          # 익절 목표 = 이동평균

    def on_minute(self, m) -> list:
        if not (self.p.session_start <= m.time < self.p.session_end):
            return []
        self.closes.append(m.close)
        bar = Bar(m.date, m.time, m.time, m.close)
        if len(self.closes) < self.p.period:
            return [Signal(bar, None, "평균 준비 전")]
        bar.ma = self.target = sum(self.closes) / len(self.closes)
        gap = (m.close - bar.ma) / TICK
        if gap >= self.p.gap_ticks:
            return [Signal(bar, "sell", f"평균 위 {gap:.0f}틱", self.p.stop_ticks)]
        if gap <= -self.p.gap_ticks:
            return [Signal(bar, "buy", f"평균 아래 {-gap:.0f}틱", self.p.stop_ticks)]
        return [Signal(bar, None, "평균 근처")]
```

- `STRATEGY`·`TITLE`·`NAME` 이 없으므로 전략은 `MeanRevert`, 이름은 파일 이름(`my_strategy`), 제목은 모듈 문서 첫 줄의 「 — 」 앞(`이동평균 되돌림`)입니다.
- `TICK` 을 기본 공용 모듈에서 가져왔으므로 틱은 0.1, 틱가치는 기본값 1000 입니다.
- `day`·`on_entry`·`on_exit` 가 없으므로 그날 손절 한도나 청산 뒤 대기는 없습니다. 필요하면 week02 `DayState` 처럼 더하세요.

## 9. 전략이 청산을 판단하는 약속 (`exit_reason` · `exit_levels`)

기본은 앱의 공통 청산(진입가 ∓ `stop_ticks` 손절 · `target` 익절 · `hold_min` 시간 청산)입니다. 전략이 **자기 규칙으로**
청산하고 싶으면(예: 기준 범위 끝에서 손절, 목표 틱 익절) 전략 클래스에 `exit_reason` 을 더하세요. 있으면 앱은
공통 손절·익절·시간 청산을 **쓰지 않고** 이것만 묻습니다 — 시간 청산도 전략이 직접 챙겨야 합니다. 없으면 지금까지와 같습니다.

```text
exit_reason(clock, price, low, high, pos) -> None | "사유" | ("사유", 기준가)
```

| 인자 | 뜻 |
|---|---|
| `clock` | `HHMMSS` |
| `price` | 이번 가격 |
| `low` · `high` | 그 분의 저가·고가. **가격 하나만 줄 때는 `None`** (장중 현재가, 리플레이의 시가) |
| `pos` | 보유의 **사본**(바꿔도 앱의 보유는 그대로): `side` `entry` `entry_time` `entry_date` `signal_time` `stop`(진입가 ∓ `stop_ticks` 틱) `stop_ticks` `signal`(진입 신호 객체, 모르면 `None`) `window`(진입 신호에 있으면) |

**두 번 묻습니다 (리플레이).** 한 분을 넣을 때 먼저 그 분 **시가**로(`low`·`high` 는 `None`), 다음에 **종가와 그 분의 저가·고가**로 묻습니다.
시가가 이미 손절가를 지났으면 첫 물음에서 시가로, 아니면 둘째 물음에서 손절가로 청산합니다 — 「손절가를 지나면 `min(시가, 손절가)`」 를
그대로 옮길 수 있습니다. 장중(실시간 현재가)에는 가격 하나로만 묻습니다.

**돌려주는 값**

| 값 | 뜻 |
|---|---|
| `None` | 들고 있음 |
| `"사유"` | 지금 가격(`price`)으로 청산 |
| `("사유", 기준가)` | 그 가격을 기준가로 청산 |

- **기준가는 앱이 묶습니다.** 가격 하나일 때는 언제나 그 가격, 범위(`low`·`high` 숫자)일 때는 `[low, high]` 안으로 맞춥니다.
  바뀌면 `event` 줄이 남습니다 — 전략이 엉뚱한 가격으로 체결을 지어낼 수 없습니다. 기준가는 종이 체결가(∓ 슬리피지)와 체결가를
  못 받았을 때 기록할 가격입니다. **모의 계좌의 실제 주문은 언제나 시장가**입니다.
- 사유는 글자 40자까지. 사유가 `"손절"` 이면 `on_exit(…, stopped=True)` 로 하루 손절 수에 들어갑니다.
- **쓸 수 없는 사유**: `"장 마감 정리"` · `"실행 종료 정리"` (앱이 쓰는 이름 — 기록에서 섞이지 않게). 그 밖에 약속에 없는 값(숫자, 빈 글자,
  기준가 0 이하 등)을 돌려주면 `TypeError` — 장중이면 실행이 「오류」로 끝나고 보유를 정리합니다.

**앱이 먼저인 안전 규칙 (위가 먼저, 앞에 걸리면 전략에 묻지 않음)**

| 순서 | 규칙 |
|---|---|
| 1 | 멈춤(`halted`, 「확인 필요」) — 진입도 청산도 하지 않음 |
| 2 | 청산 체결이 확인 안 돼 기다리는 중 — 아무것도 안 함 |
| 3 | `flatten_at` 이후 — 앱이 「장 마감 정리」 |
| 4 | 앞서 정한 청산이 확인 안 됨 — 10초 뒤 **같은 사유로 다시** (전략에 다시 묻지 않음) |
| 5 | `exit_reason` 이 돌려준 사유 (전략) |
| 끝 | 실행 끝·중지·오류 정리(「실행 종료 정리」) — 언제나 |

해외 휴장(20:35~20:50)엔 주문이 없습니다. 청산은 **판단만** 해서 사유를 정해 두고, 20:50 이후 첫 가격에 그 사유로 냅니다(다시 묻지 않음, 3장).

**화면의 손절·익절** — 전략에 `exit_levels(pos) -> {"stop": 가격|None, "target": 가격|None}` 이 있으면 보유 중 화면이 그 값을 보입니다.
**표시 전용**이라 판단에는 쓰지 않습니다(청산은 `exit_reason` 그대로). 예외가 나거나 수가 아닌 칸이면 원래 값(앱의 손절가·`target`)을 보입니다.

**`on_entry` 인자** — 매개변수가 없으면 `on_entry()`. 있으면 **이름이 같은 진입 신호 칸의 값**을 넘깁니다
(ORB `on_entry(window)` 는 신호의 `window`). 신호에 없는 이름은 기본값이 있으면 기본값, 없으면 `TypeError` —
이 대응은 **진입 주문을 내기 전에** 맞춰 보므로, 틀리면 주문 없이 오류입니다. `*args`·`**kwargs` 에는 아무것도 넘기지 않습니다.
신호에 `window` 가 있으면 보유와 `trade` 줄, 진입 기록에도 남습니다(3장의 「개장마다 한 번」).

**짧은 예제** — 8장 전략에 「손절은 진입가 ∓ `stop_ticks`, 익절은 이동평균, 시간 청산은 직접」 을 `exit_reason` 으로 옮긴 것입니다.
이것도 이대로 올리면 돕니다(시험이 불러옵니다).

```python
"""평균 되돌림 (전략 청산) — 작성 규칙 예제. exit_reason 으로 청산을 직접 판단합니다."""
from collections import deque
from dataclasses import dataclass

from strategy import TICK, Signal   # 앱에 든 기본 공용 모듈


@dataclass(frozen=True)
class Params:
    period: int = 20
    gap_ticks: int = 5
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
    ma: float | None = None


def _min(hhmmss: str) -> int:
    return int(hhmmss[:2]) * 60 + int(hhmmss[2:4])


class MeanRevertExit:
    """평균에서 벗어나면 반대로 들어가고, 손절·평균 도달·시간 청산을 exit_reason 이 정합니다."""

    def __init__(self, p: Params) -> None:
        self.p = p
        self.closes = deque(maxlen=p.period)
        self.ma = None

    def on_minute(self, m) -> list:
        if not (self.p.session_start <= m.time < self.p.session_end):
            return []
        self.closes.append(m.close)
        bar = Bar(m.date, m.time, m.time, m.close)
        if len(self.closes) < self.p.period:
            return [Signal(bar, None, "평균 준비 전")]
        bar.ma = self.ma = sum(self.closes) / len(self.closes)
        gap = (m.close - bar.ma) / TICK
        if gap >= self.p.gap_ticks:
            return [Signal(bar, "sell", f"평균 위 {gap:.0f}틱", self.p.stop_ticks)]
        if gap <= -self.p.gap_ticks:
            return [Signal(bar, "buy", f"평균 아래 {-gap:.0f}틱", self.p.stop_ticks)]
        return [Signal(bar, None, "평균 근처")]

    def exit_reason(self, clock, price, low, high, pos):
        buy = pos["side"] == "buy"
        lo, hi = (price, price) if low is None or high is None else (low, high)
        if (lo <= pos["stop"]) if buy else (hi >= pos["stop"]):
            return "손절", pos["stop"]              # 앱이 [low, high] 안으로 묶습니다
        if self.ma is not None and ((hi >= self.ma) if buy else (lo <= self.ma)):
            return "평균 도달", self.ma
        if _min(clock) - _min(pos["entry_time"]) >= self.p.hold_min:
            return "시간 청산"                      # 공통 시간 청산은 안 쓰므로 직접
        return None

    def exit_levels(self, pos) -> dict:
        return {"stop": pos["stop"], "target": self.ma}   # 화면에만 보임
```

## 10. ORB 를 앱에 올리는 법 (MKU 1분봉)

week03 후보 B(세션 개장 돌파, ORB)를 앱 1분봉 실행기로 돌리는 파일이 저장소에 있습니다.

- 예제: `docs/team/examples/strategy_orb_app.py`
- **파일 세 개를 같은 전략 폴더에 올립니다**(「파일 올리기」를 세 번): `strategy_orb.py`(week03 원본) · `common.py`(week03 원본) · `strategy_orb_app.py`(위 예제).
  앱 목록에는 `strategy_orb_app.py` 가 전략으로 보입니다. `strategy_orb.py`·`common.py` 는 **한 글자도 고치지 않습니다**(시험이 해시로 비교합니다).
- **판정(진입 신호)은 옮기지 않고 물려받습니다.** `OrbApp(SessionBreakout)` — 기준 범위 쌓기·돌파 판정·진입 막기·`on_entry(window)`·`on_exit` 가 원본 그대로입니다.
- **`backtest.py` 에서 옮긴 것**은 ORB 체결·청산 규칙(`run()` 81~176줄)입니다. 앱의 공통 청산이 ORB 와 달라서 `exit_reason`(9장)으로 옮겼습니다:
  손절 = 진입 신호의 **범위 반대편 끝**, 익절 = 진입가 ± `target_ticks`, 기한 = 진입 + `hold_min`(또는 신호의 `exit_by` 가 이르면 그것), 손절 먼저 → 익절.
  옮기고 남은 대응표와 한 가지 다른 점(시가가 이미 익절가를 넘었는데 같은 분 저가가 손절가까지 간 봉)은 예제 파일 머리말에 있습니다.
  화면의 손절·익절 선은 `exit_levels`(범위 끝 · 목표가)입니다.

**MKU 시간표** (한국시간): 장 **08:25** 시작 · **20:35~20:50 휴장**(주문 없음, 판단은 기다림) · **23:50** 보유 정리(`flatten_at`) · **23:55** 실행 끝.
ORB 의 Params 에는 장 시간 칸이 없으므로 해외 실행이 시장 시간표로 채웁니다(`session_start`·`entry_start` 08:25, `flatten_at` 23:50, `session_end` 23:55).
휴장 동안의 규칙은 3장 「해외 MKU 로 돌릴 때」 그대로입니다: 진입 대기는 20:50 이후 첫 가격에, 정해진 청산은 다시 묻지 않고 20:50 이후 첫 가격에 그 사유로.

- **돈은 USD** 입니다(틱 0.0001 = US$2.5). 요약·화면의 손익·수수료 단위가 달러입니다.
- **장중에 켜면(중간 시작)**: 앱이 준비 봉(전날부터)을 넣어 오늘의 개장 상태를 되살립니다. 준비 봉에서 **오늘** 진입 신호가 이미 난 개장과,
  오늘 같은 `NAME`·종목·방식의 앞선 실행이 들어간 개장은 「이미 진입함」입니다 — 앱이 그 개장마다 `on_entry(window)` 를 부르고
  `day.in_position` 을 `False` 로 되돌리며, 그 개장의 진입 신호가 또 나와도 버립니다. 앞선 실행의 손절 수는 `day.stops` 로 이어받습니다.
  (그래서 같은 개장에 두 번 들어가지 않습니다. 보유 자체는 이어받지 않습니다 — 켜는 순간 계좌에 보유가 있으면 시작을 거부합니다.)
- **같은 MKU 모의 실행 하나**: 모의 계좌(`orders`)는 주문하는 종목 하나에 실행 하나입니다. 1분봉이든 실시간(11장)이든 통틀어
  같은 `MKU…` 종목에 둘이 돌 수 없고, 두 번째는 폴더를 만들기 전에 거부됩니다. 「종이」 실행은 계좌를 만지지 않아 이 제한이 없습니다.
- 리플레이: `uv run python -m backend.team_pyrun.replay strategy_orb_app.py <YYYYMMDD> bars_1m_MKUX26.csv` (파일 이름의 `MKUX26` 으로 시장을 정합니다).
  week03 백테스트와 같게 휴장을 막지 않습니다.

## 11. 실시간 전략(leadlag) 약속과 ws_trader 에서 `Engine` 떼어 올리는 법

초 단위 전략(KRX 체결을 보고 MKU 를 주문하는 leadlag)은 1분봉이 아니라 **실시간 실행기**가 돌립니다. 앱이 `Engine` 에 `on_krx`·`on_quote` 가
있으면 실시간 전략으로 알아봅니다(둘 다 `on_minute` 도 있으면 불러오기 오류).

### Engine 약속 (판단만 — 접속·주문은 앱)

| 이름 | 뜻 |
|---|---|
| `Engine(p)` | 생성자 인자는 Params 하나 (`Params` 또는 `LiveParams`, dataclass, **모든 칸 기본값**). 실시간은 필수 칸이 없습니다 |
| `on_krx(price, now, hhmmss)` | KRX 체결 하나 (`now` 는 받은 순간의 단조 시계, 초). 행동 `dict` 또는 `None` |
| `on_quote(bid, ask, now, hhmmss)` | MKU 1단 호가 하나. 행동 `dict` 또는 `None` |
| `on_timer(now, hhmmss)` | 1초마다 |
| `filled_entry(…)` · `filled_exit(…)` | 앱이 체결을 알리는 자리 |
| `p` | 받은 Params |

행동은 `{"act": "enter"|"exit", "side": ±1, "ref": 기준 호가, …}` 입니다. `pending`·`pos`·`stops` 가 있으면 화면이 씁니다.
틱 가치는 모듈의 `TICK_VALUE`, 없으면 `TICK_USD` 로 읽습니다. 앱은 **주문 중인 동안 Engine 이 새 행동을 내지 않는다**고 가정하므로(`pending`),
약속을 어기고 행동을 내면 주문하지 않습니다.

### ws_trader.py 를 그대로 올려도 됩니다 (판단 부분만 골라 씀)

팀원이 쓴 `ws_trader.py` 처럼 **실행기(접속·주문·기록)와 판단이 한 파일**이어도 고치지 않고 그대로 올리면 됩니다.
앱은 파일을 실행하기 **전에** 맨 위 import 를 훑어, 앱에 없는 모듈(`nh_client`·`fee_test`·`ws_probe` 등)이 있으면
**그 모듈을 쓰는 문장만 빼고** 나머지를 원래 순서·줄 번호 그대로 실행합니다(그 밖에는 파일 전체를 실행할 때와 같습니다).

- 빼는 것(실행 안 함): 앱에 없는 모듈의 import · 실행할 때 그 이름을 쓰는 맨 위 문장(예: `CLIENT = NHClient()`) ·
  함수·클래스 안에서 그 이름을 쓰는 정의(예: `Trader`, `Trader` 를 쓰는 `main`) · `if __name__ == "__main__":` — 끝까지 따라갑니다
- 그대로 두는 것: 나머지 전부(`Engine` · `LiveParams` · `TICK` …, 없는 모듈을 안 쓰는 `Recorder` 같은 것도 정의만 됨)
- 목록 줄 밑에 「실행기와 판단이 한 파일 — 판단 Engine 만 씀 · 앱에 없는 모듈(…)을 써서 실행하지 않는 부분: Trader, main, …」 알림
- 판단이 바뀌면(깃허브의 `Engine`·`LiveParams` 수정) 새 `ws_trader.py` 를 다시 올리면 됩니다 — 손으로 떼어 낼 필요가 없습니다
- **불러오지 않는 경우**(조용히 다른 값으로 돌지 않게):
  - 전략 클래스가 앱에 없는 모듈을 쓰면(예: `Engine` 안에서 `nh_client` 로 주문, 또는 옆 파일을 같이 안 올림) —
    「전략 클래스가 앱에 없는 모듈을 씁니다: Engine 이 이름(모듈) …」. 옆 파일이면 같이 올리고, 실행기면 판단 클래스와 나눠 주세요
  - 앱이 읽는 이름(`TICK` `TICK_VALUE` `TICK_USD` `Params` `LiveParams` `STRATEGY` `TITLE` `NAME`)이 그 모듈에 기대면
    (예: `from nh_client import TICK`) — 기본값(0.1)으로 돌면 시장이 바뀌므로 값을 파일에 직접 적어 주세요
- 앱에 있는 모듈만 쓰는 파일은 지금까지처럼 파일 전체를 실행합니다(보통 전략 파일은 달라지지 않음)
- 전략 값은 `LiveParams` 기본값 그대로입니다 — `ws_trader` 의 명령줄 옵션(`--move` 등)은 앱에서 쓰지 않습니다
- 이름은 문법으로 따라갑니다 — `globals()["X"]` 처럼 글자로 찾는 이름은 따라가지 못합니다

### 예제와 ws_trader 에서 떼어 오기 (손으로 할 때)

- 예제: `docs/team/examples/strategy_leadlag.py`. 이대로 올리면 됩니다(표준 라이브러리만 씁니다).
- 내 `ws_trader.py` 에서 직접 떼어 낼 때 **남길 것**(한 글자도 고치지 않음 — 시험이 원문과 글자 그대로 비교합니다):
  `TICK` · `TICK_USD` · `FEE_TICKS` · `LiveParams` · `Engine`.
- **지울 것**:

| 지울 것 | 까닭 |
|---|---|
| `Recorder` | 기록은 앱이 함 (민감 칸은 쓰는 순간 지움). 원문 `raw.jsonl` 은 남기지 않음 |
| `Trader` | 웹소켓 접속·다시 붙기·주문·체결 확인은 앱 실시간 실행기가 함 — 올린 코드는 주문을 낼 수 없음 |
| `main` · `argparse` | 명령줄 대신 앱 「실행 세우기」 |
| `open_raw` · `HERE` | 녹화 읽기는 앱 리플레이가 함 |
| `SILENCE_S` | 끊김 판단은 앱 허브가 함 |
| `websockets` · `nh_client` · `fee_test` · `ws_probe` import | 위를 빼면 쓰이지 않음 |
| `asyncio` · `csv` · `gzip` · `json` · `time` · `datetime` · `Path` · `asdict` import | 위와 같음 |

### 종목: 시세는 KRX, 주문은 MKU

실행을 세울 때 종목이 둘입니다. **신호 종목**(`signal_sym`)은 KRX 미국달러선물 `A75…` 로 **시세만** 봅니다(비우면 국내 최근월물).
**주문 종목**(`sym`)은 `MKU…` 이고 실시간 실행은 MKU 만 주문합니다(전략 `TICK` 이 0.0001 이어야 함). 같은 종목 제한(10장)은 주문 종목에만 걸립니다 —
신호 종목은 막지 않습니다.

### 앱이 하는 일

- 원문을 **받은 순서 그대로** Engine 에 넣습니다: KRX 체결(`tick_div == "1"` 이고 체결량 > 0) → `on_krx`, MKU 호가 → `on_quote`, 1초 타이머 → `on_timer`.
  시각 기준은 받은 순간의 단조 시계입니다. 주문·체결 확인(최대 15초)을 기다리는 동안 쌓인 원문은 확인 뒤 순서대로 넣되,
  체결 결과는 쌓인 원문을 다 넣은 **뒤**에 Engine 에 알립니다(ws_trader 와 같은 판단).
- 「모의 계좌」는 시장가 1계약(주문 전 잔고 관문 · 재전송 금지), 「종이」는 **반대 호가** 체결(수수료 US$2/체결, 슬리피지 없음).
  Engine 의 `ref` 가 반대 호가와 다르면 기록만 하고 반대 호가로 체결합니다.

| 만나는 것 | 앱이 하는 일 |
|---|---|
| **끊겼다 다시 붙음**(공백 표지) | 기록만 합니다. 끊긴 동안의 가짜 충격은 Engine 의 `stale_s` 규칙이 버립니다 |
| **모의↔실전 환경이 바뀜** | 보유 중이면 멈춤(「확인 필요」), 보유가 없으면 끝 |
| **원한 구독이 밀리거나 거절됨** | 위와 같음 (시세 없이 청산 판단을 할 수 없음). 기록용 MKU 체결만 밀린 것이면 기록만 |
| **쌓임 한도(5,000건) 넘음** (`overflow`) | 보유·결과 모름 주문이 있으면 멈춤, 없으면 「끝 — 쌓임 한도」 — 빠진 원문이 있으면 같은 판단을 보장할 수 없음 |
| **체결을 모름**(응답 없음·번호 없음·15초 안에 확인 안 됨) | **멈춤(확인 필요)**. 더 주문하지 않고 끝에도 정리하지 않으며 새로 판단하지 않음 |
| **청산 주문이 거절됨**(결과를 아는 실패) | 잔고를 한 번 보고 앱이 아는 보유와 같으면 10초 뒤 **같은 사유로** 다시. **3번째까지 안 되면** 멈춤(「청산 주문이 3번 거절됨」) |
| **진입 주문이 거절됨** | 그 신호를 버립니다(ws_trader 와 같음) |

멈춘 실행은 Engine 에 더 넣지 않고 주문도 하지 않으며, 중지·끝 시각에 정리 없이 끝납니다(끝 까닭 「정리 안 함 — 확인 필요」).
휴장(20:35~20:50)엔 주문하지 않습니다 — 진입 신호는 버리고, 청산은 들고 있다가 휴장이 끝난 첫 순간에.

**끝 시각** = Params 의 `flatten_at` + 5분(해외 23:55 를 넘지 않음, `flatten_at` 이 없으면 23:55). 그 전에 Engine 이 「마감」 청산을 냅니다.
끝·중지·오류 때 보유가 남아 있고 멈추지 않았으면 앱이 청산 주문을 내고 `filled_exit(…, "실행 종료 정리")` 를 알립니다.

**리플레이(녹화로 다시 돌리기)**

```text
uv run python -m backend.team_pyrun.replay strategy_leadlag.py <YYYYMMDD> <raw.jsonl.gz>
```

week03 `ws_trader.py` 가 남긴 원문 녹화(`results/live/<날짜>/raw.jsonl.gz`)를 앱 실행기와 같은 길로 흘립니다. 서버 접속·주문은 없고 체결은 종이입니다.

## 12. MKU 공통

- **틱·통화**: 틱 0.0001 = **US$2.5**, 통화 USD. 1분봉 전략은 `TICK = 0.0001`·`TICK_VALUE = 2.5` 로 시장이 정해집니다(종목을 비우면 MKU 최근월물).
- **수수료**: 종이는 **체결마다 US$2**(편도), 슬리피지 1틱. 모의 계좌는 서버가 낸 수수료를 예수금에서 읽어 기록합니다.
- **아직 기록으로 확인하지 못한 것**: 해외 주문내역의 **상태 코드**(`ord_sts`: 1 접수 · 3 확인 · 4 부분체결 · 6 전체체결 · 8 자동취소 · 9 거부)와
  주문·잔고·예수금의 **칸 이름**은 운영자 코드(`backend/overseas_futureoption/`)에서 가져온 것이고, 해외 주문·잔고 **응답 기록(`tests/fixtures/nh/`)은 아직 없습니다.**
  국내처럼 실제 응답으로 맞춰 본 적이 없다는 뜻입니다.
- **그래서 첫 장중은 이 순서로 하세요.**
  1. 먼저 **「종이」** 로 한 번 돌려 판단·시간표·휴장 동작을 봅니다(계좌를 만지지 않습니다).
  2. 그다음 **「모의 계좌」** 로 돌리고, **첫 주문의 체결**(체결가·수량·상태·수수료)을 앱 기록과 NH 앱 화면 양쪽으로 맞춰 봅니다.
     체결을 못 읽으면 앱은 새 주문을 내지 않고 「확인 필요」로 멈춥니다 — 이때 기록(`api_log.jsonl`)의 응답 칸 이름을 확인해 상태 코드·칸 이름을 고칩니다.
  3. 같은 종목에 실행이 하나뿐인지(10장) 확인하고 켭니다.
  4. 결과 묶음(zip)을 누구에게 넘기기 전에 `api_log.jsonl`·`journal.jsonl` 에서 계좌번호·이름처럼 보이는 값을 한 번 찾아봅니다.
     해외 응답·요청은 칸 이름은 다 남기고, 앱이 읽는 칸(`markets.OVS_LOG_FIELDS`) 밖의 값은 `***` 로 가려 적습니다.
- 모든 NH 호출은 모의(`paper`) 서버로만 나갑니다. 주문은 재전송하지 않고, 응답이 없으면 주문내역·잔고로 확인될 때까지 새 주문을 막습니다.

## 13. 매일 자동 시작 (전략 파일은 고치지 않음)

실행 하나는 **하루치**입니다 — 전략 `flatten_at`(없으면 시장 끝: 해외 23:55 · 국내 장 마감 정리) 뒤 「끝」. 다음 날
다시 돌리려고 전략 파일을 고칠 필요는 없습니다. 「실행 세우기」에서 **「매일 자동 시작」** 을 켜면 앱이 날마다 새 실행을 세웁니다.

- 언제: 장이 열리는 날(월~금) **장 시작 5분 전** — MKU 08:20, 국내 08:55. 세운 실행은 장이 열릴 때까지 「대기」
- 무엇으로: 같은 전략 파일·같은 방식(종이 / 모의 계좌), 종목은 **그날의 최근월물**(실시간은 KRX 신호 종목도). 파일을 밤새
  고쳤으면 다음 날 실행은 고친 파일로 돕니다
- 거부되면: 5분 뒤 다시, 하루 3번까지(시작 잔고 0 아님 등 거부 규칙은 손으로 누른 시작과 같음)
- **세우지 않는 때**: 앞선 실행이 「확인 필요」·「오류」로 끝났을 때, 결과를 모르는 주문이 남았거나 끝내기(정리·끝 잔고)가
  실패했을 때, 앞선 실행 기록을 못 찾을 때, 앱이 실행을 세우던 중에 꺼졌을 때 → 왼쪽 「매일 자동 시작」 카드에 「멈춤」으로
  남습니다. 계좌·기록을 확인하고 「다시 켜기」 — 그날 시작 시각(08:20 · 08:55)이 지난 뒤 켜면 **다음 장 날부터** 세웁니다
  (켜는 순간 확인 없이 실행이 서지 않게). 앞선 실행이 아직 돌면 그날은 기다립니다
- 모의 계좌 자동 시작은 확인 얼굴이 처음 한 번뿐입니다 — 그 뒤로는 날마다 확인 없이 주문이 나갑니다
- 손으로 세운 다른 실행·월물이 바뀐 날의 지난 월물 잔고는 보지 않습니다(시작 잔고 0 검사는 그날 종목만)
- 하루 중간에 끊긴 실행을 이어 돌리지는 않습니다(주문 재전송 금지 원칙). 그날 이미 세웠으면 앱을 다시 켜도 다시 세우지 않습니다
- 앱을 끌 때는 새 실행부터 막고(자동 시작이 준비 중이던 것도) 돌던 실행을 멈춥니다
- 휴장일은 따로 모릅니다 — 그날도 실행은 서고, 시세가 없으니 거래 없이 끝납니다
- 모의 계좌 자동 시작은 시장마다 하나(국내 하나·해외 하나). 끄기는 카드의 「끄기」
- 서버(또는 맥)가 켜져 있어야 합니다. 맥은 `caffeinate -dims just serve`
