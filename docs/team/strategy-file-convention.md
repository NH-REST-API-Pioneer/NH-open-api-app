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
  그 사유로 청산합니다. 정리 요청·중지 요청도 휴장이 끝난 뒤 정리합니다. 휴장 중 오류로 끝나면 정리하지 않고 「확인 필요」.
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
