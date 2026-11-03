# 파이썬 전략 자동매매 — 설계

작성 2026-11-02 · 상태: 구현됨 (2026-11-03, 브랜치 feat/python-strategy-runner)

## 1. 왜 만드는가

팀은 전략을 **파이썬 파일**로 씁니다(예: week02 `strategy_bb.py` — 볼린저+RSI, `strategy.py` — VWAP).
week02 에서는 이 파일을 `runner.py`(명령줄, REST 폴링)로 돌리고, 결과를 `results/runs/<날짜>_<전략>_<모드>/`
의 `journal.jsonl` · `summary.json` 으로 남겨 매주 과제(`weekNN/results/`)에 제출했습니다.

이 앱(운영자 프로그램 포크)에도 전략 엔진이 있지만 **화면에서 조건식을 조합하는 방식**이라 이 파이썬 전략을
넣을 수 없습니다. 그래서:

- 전략 `.py` 파일을 정해진 폴더에 넣으면 앱이 그 전략으로 **자동매매**(모의 계좌 또는 종이)를 돌리고,
- 전략이 **무엇을 보고 어떻게 판단하는지**를 대시보드에 보여 주고,
- 실행이 끝나면 **결과와 API 로그를 내려받아** 그대로 과제 폴더에 넣을 수 있게 합니다.

API 로그는 두 용도입니다 — 장 끝난 뒤 **문제 추적**, 과제 평가 「API 활용 25점」 **증빙**.

지금은 자동매매를 돌리고 있지 않습니다(week02 runner 도 멈춘 상태). 이 기능이 그 자리를 대신합니다.

## 2. 목표 · 하지 않을 것 · 실패로 볼 것

**목표**
1. week02 전략 파일을 (거의) 고치지 않고 넣어 돌릴 수 있다. 판정 봉 크기·지표·진입 조건은 전략 파일이 정한다.
2. 실행기의 동작은 week02 `runner.py` 와 같다 — 같은 1분봉을 넣으면 같은 신호, 같은 청산 규칙.
3. 대시보드: 기존 「전략 진행」 화면 형식 그대로, 전략주문 아래 새 하위 탭 「파이썬 전략」.
4. 끝난 실행의 결과(zip: `journal.jsonl` · `summary.json` · `api_log.jsonl`)를 화면에서 내려받는다.
   형식은 week02 와 같아서 week02 `summarize_runs.py` 로도 읽힌다.

**하지 않을 것**
- 앱의 조건식 전략 엔진(`backend/strategy/`)과 합치기. 「전략 진행」 목록에 섞지 않는다.
- 전략 파일을 화면에서 편집·업로드. 파일은 폴더에 직접 넣는다.
- 실전 계좌 주문. 모의 계좌와 종이만.
- 서버 재시작 시 돌던 계좌 실행 자동 재개(원칙 3 「주문 재전송 금지」와 충돌). 재시작 후엔 잔고 확인만 하고 끝낸다.
- 해외(SGX MKU 등)·복수 종목. 처음엔 국내 미국달러선물 한 종목. 구조는 막지 않되 만들지 않는다.
- 백테스트 화면. 백테스트는 지금처럼 week 폴더의 스크립트로.

**실패로 볼 것** (돌아가도 실패)
- 응답을 못 받은 주문을 다시 보내 **중복 주문**이 나감.
- 내려받은 결과·로그에 계좌번호·이름·IP·토큰이 남음.
- 종이 체결을 모의 계좌 체결처럼 표시·기록함.
- 같은 1분봉에서 week02 runner 와 다른 신호가 나옴(전략 판정을 앱이 바꿔 버림).
- 파일 하나가 잘못돼(문법 오류 등) 앱 전체나 다른 실행이 멈춤.

## 3. 사용자가 정한 것

| 정한 것 | 내용 |
|---|---|
| 판정 봉 | 전략 파일이 정한다(`Params.bar_min`). 앱은 **막 끝난 1분봉**만 `on_minute` 에 넣는다 |
| 청산 규칙 | week02 방식 그대로 — **실행기가 공통으로** 손절·익절·시간 청산·장 마감 정리를 판단, 전략은 값만 준다 |
| 결과 | 실행 끝(장 끝·중지)나면 json 결과 + API 로그를 앱에서 내려받기 |
| API 로그 | 문제 추적 + 「API 활용」 증빙 둘 다 |
| 운영자 코드 | 필요하면 고쳐도 된다(고친 자리 `# 팀:` 표시) |
| 대시보드 | 지금 앱 디자인 형식 유지. 위치는 시안 A — 전략주문 › 「파이썬 전략」 새 하위 탭 |

## 4. 전략 파일 약속 (week02 에서 읽어 낸 것)

전략 모듈은 다음을 갖춘다. week02 `strategy_bb.py` 는 이미 모두 갖췄다.

```python
class Params:            # dataclass. 아래 칸은 실행기가 읽는다
    session_start: str   # "090000"
    session_end: str     # "153500"
    entry_start: str     # 진입 허용 시작
    entry_end: str       # 진입 허용 끝
    flatten_at: str      # 장 마감 정리 시각
    hold_min: int        # 시간 청산(분)
    # 나머지 칸(bar_min, band_k …)은 화면에 그대로 보여 주기만 한다

class <전략>:            # 생성자 (params: Params)
    p: Params
    target: float | None            # 익절 목표 — 실행기가 매 가격마다 읽음
    day: DayState                   # stops 등. 같은 날 다시 켤 때 손절 수를 이어받는 자리
    def on_minute(self, m: Minute) -> list[Signal]
    def end_of_day(self) -> list[Signal]
    def on_entry(self) -> None
    def on_exit(self, pnl_won: float, stopped: bool) -> None

Signal: bar(판정 봉: date/start/end/OHLCV + 지표 칸), side("buy"|"sell"|None), reason(str), stop_ticks(int|None)
Minute: date, time(HHMMSS, 봉 시작), open, high, low, close, volume
```

- **모듈 안에서 어느 클래스가 전략인가**: 모듈 상단 상수 `STRATEGY = <클래스>`, `TITLE = "볼린저 밴드 + RSI"`,
  `NAME = "bb"`(기록 폴더 이름에 쓰는 짧은 이름 — week02 의 `bb`·`vwap` 과 같게)를 둔다(제 판단). week02 파일엔 없으므로
  세 줄 추가가 필요하다.
- **한 모듈이 공용 모듈이면서 전략일 수 있다.** week02 VWAP 전략(`VWAPReversion`)은 공용 모듈 `strategy.py` 안에 있으므로
  `strategy.py` 에 `STRATEGY`·`TITLE`·`NAME = "vwap"` 을 두고, 익절 목표 `current_vwap` 을 `target` 으로도 읽히게
  프로퍼티 한 줄을 더한다. `STRATEGY` 가 없는 모듈(`backtest*.py` 등)만 목록에서 빠진다.
- 지표 칸은 판정 봉(`Signal.bar`)에 들어 있는 숫자 칸을 **이름 그대로** 기록·표시한다(`upper` `middle` `lower` `rsi` `atr` `vwap` `sigma` …).
  차트는 이름으로 그리는 법을 안다: `upper/middle/lower`·`vwap` → 가격 위 선, `rsi` → 아래 보조 창. 모르는 칸은 표에만.
- `Minute`·틱 상수 등은 전략 폴더의 공용 모듈(week02 `strategy.py`)에서 가져온다 — 전략 파일끼리 `from strategy import …`
  로 서로 부른다. **앱은 전략 폴더를 하나의 격리된 이름공간으로 불러야 한다**(아래 6-1).

## 5. 전체 그림

```
~/NHFutures/strategies/*.py ──▶ 불러오기(격리) ──▶ PyRun(실행 하나, 스레드 하나)
                                                       │ 1분봉·현재가 조회 / 주문·주문내역·잔고·예수금
                                                       ▼
                                   backend.nh_api TradeClient.call()  ── # 팀: 갈고리 ──▶ api_log.jsonl
                                                       │
                     journal.jsonl · summary.json ◀────┘
                                                       │
                   /api/team/pyrun/...  ◀── 화면 「파이썬 전략」 탭 (폴링)
```

## 6. 백엔드

팀 코드는 `backend/team_pyrun/`(이름은 빌더 판단) 아래에 둔다. 운영자 폴더엔 갈고리 몇 줄만.

### 6-1. 전략 폴더와 불러오기
- 폴더: `~/NHFutures/strategies/` (저장소 밖, 앱의 다른 상태와 같은 곳). 없으면 만든다.
- 목록: 폴더의 `*.py` 중 `STRATEGY` 를 가진 모듈만 「전략」, 나머지(`strategy.py` 같은 공용 모듈·`backtest*.py`)는 무시.
  하지만 공용 모듈은 전략이 import 할 수 있어야 한다.
- 불러올 때 문법 오류·약속 위반(필수 칸 없음)은 그 파일 줄에 까닭을 띄우고 다른 파일·실행엔 영향 없음.
- **이름 충돌 주의**: week02 공용 모듈 이름이 `strategy` 다. 앱엔 `backend.strategy` 패키지가 있고, 흔한 이름이라
  `sys.path` 에 폴더를 그냥 끼우면 다른 것과 섞일 수 있다. 실행마다 전략 폴더를 격리해 불러오는 방법은 빌더가 정한다
  (예: 불러오는 동안만 경로를 앞에 두고, 불러온 뒤 그 폴더 출신 모듈을 `sys.modules` 에서 실행 고유 이름으로 옮겨 둠).
- 파일이 실행 중 바뀌어도 돌던 실행은 처음 불러온 것으로 계속 간다. 새 실행부터 새 파일.
- 실행 시작 때 파일 내용의 해시를 `journal` 첫 `event` 에 남긴다(어느 판으로 돌았나).

### 6-2. 실행기 — week02 `runner.py` 를 옮긴다
동작은 week02 `runner.py` 의 `Runner` · `MockAccountBroker` · `PaperBroker` · `live()` 와 같게. 참고 원본:
`https://github.com/NH-REST-API-Pioneer/pioneer-1st-6team-NFT/tree/main/week02` (`runner.py`, `nh_client.py`, `summarize_runs.py`).

- **모드**: `orders`(모의 계좌 시장가 주문, 주문내역으로 체결 확인) · `paper`(주문 없이 현재가 ∓1틱, 수수료 690원 가정).
  **앱 접속 환경이 모의(paper)가 아니면 `orders` 실행은 시작을 거부한다.**
- **시작**: 컴퓨터 시간대 KST 확인 → 미국달러 최근월물 찾기(종목 선택 칸이 비면) → 품목 상세로 틱 0.1·틱가치 1,000원
  확인(전략 공용 모듈의 `TICK`·`TICK_VALUE` 와 다르면 시작 거부) → `orders` 면 잔고 확인, 이 종목 잔고가 남아 있으면
  **시작을 거부하고 화면에 알림**(제 판단 — week02 는 자동 정리했지만, 앱에선 다른 실행·수동 주문의 잔고일 수 있다) →
  예수금 기록 → 1분봉 1,500개로 준비(이때 신호로는 진입 안 함) → 그날 앞선 같은 전략 실행의 손절 수 이어받기.
- **장 전**: 시작을 장 전에 눌렀으면 `session_start` 까지 기다린다(상태 「대기」).
- **루프(1초)**: 분이 바뀌고 3초 뒤 막 끝난 1분봉을 받아 `on_minute` → 신호는 `pending` → 매초 현재가로 진입 /
  장 마감 정리 → 손절 → 익절 → 시간 청산. week02 순서·규칙 그대로.
- **주문 안전**: 재전송 없음. 체결 확인은 주문내역 0.5초 간격 최대 15초, 안 되면 잔고로 실제 상태 판단.
  청산이 안 됐고 잔고가 남아 있으면 10초 뒤 다시 청산 시도(week02 와 같음). `TransportError`(응답 없음)는
  처리 여부를 모르므로 **잔고로 확인될 때까지 새 주문을 막는다**.
- **끝**: `END_TIME`(15:31) · 중지 · 청산 · 오류 → 보유 있으면 시장가 정리, 끝 잔고·예수금 기록, `summary.json` 작성,
  상태 「끝」. 중지는 「정리하고 끝」 하나(제 판단). 「청산」은 보유만 닫고 실행은 계속.
- **동시 실행**: `orders` 실행은 **종목당 하나**만(week02 README 의 VWAP·볼린저 주문 섞임 문제). `paper` 는 여러 개 가능.
- **다른 곳의 주문 — 막지 않고 알아채서 멈춘다**(사용자 결정). 같은 모의 계좌·같은 종목에 앱의 일반주문 화면이나 조건식
  전략이 주문을 내도 운영자 주문 경로는 건드리지 않는다. 대신:
  - 시작 때 그 종목 잔고가 0 이 아니면 시작 거부(위).
  - 실행이 기대하는 보유(실행 장부: 0 또는 ±1)와 계좌 잔고가 다르면 — 진입·청산 확인 때, 그리고 보유 중 30초마다(제 판단)
    잔고를 봐서 — **새 주문을 멈추고 상태 「확인 필요」**로 두고 화면에 알린다. 「청산 다시 시도」도 하지 않는다(남의 포지션을
    닫거나 반대 포지션을 만들 수 있음). 사용자가 확인 후 「중지」(정리 없이 끝 — 잔고는 직접 처리)를 누른다.
  - 「실행 시작 확인창」에 「이 종목을 다른 곳에서 주문하지 마세요」 문구.
- **서버 재시작**: 돌던 실행은 상태 파일로 알아보고 `orders` 였으면 잔고를 한 번 확인해 기록한 뒤 「끝(재시작)」으로 닫는다.
- 앱의 실시간 허브(웹소켓)는 쓰지 않고 **REST 폴링**(week02 와 같은 데이터 출처 → 백테스트와 같은 봉).
- **API 계층은 팀 코드다**(CLAUDE.md 원칙 2, 평가 「API 활용」). 팀 파일 `api.py` 가 요청 값 만들기·응답 해석·오류 처리를
  맡고, 운영자 쪽은 전송·토큰·호출 제한인 `backend.nh_api.runtime.client().call(api_id, payload)` 만 쓴다. 운영자 래퍼
  (`domestic_futureoption_functions`)는 쓰지 않고 요청 칸 확인용 참고로만 본다. 쓰는 API: `domestic_chart-minute`
  `domestic_price` `domestic_order` `domestic_order-history` `domestic_open-interest` `domestic_deposit`
  `domestic_price-all-futures` `domestic_product-detail`. 응답 필드명은 `tests/fixtures/nh/<api_id>/` 기록과 week02 코드로
  확인(추측 금지).
- 이 설계는 CLAUDE.md 「다음 작업」의 예전 계획(①·③ — 자동 시작·재시작 뒤 보유 이어 가기)을 대신한다.

### 6-3. 기록 파일 — `~/NHFutures/state/pyruns/<YYYYMMDD>_<NAME>_<orders|paper>[_<n>]/`
- **실행 하나 = 폴더 하나**(제 판단). 같은 날 같은 이름·모드 폴더가 이미 있으면 `_2`, `_3` … 을 붙인다. 그래서 동시에 도는
  종이 실행 둘이 한 journal 에 섞이지 않고, 폴더마다 `summary.json` 하나라 week02 `summarize_runs.py` 가 모든 실행을 읽는다.
  (week02 는 같은 날 다시 켜면 같은 폴더에 이어 쓰고 `summary_HHMMSS.json` 을 따로 써서 두 번째 실행이 요약에서 빠졌다.)
- 종목이 최근월물이 아니면 폴더 이름에 종목을 넣는다(`…_bb_paper_A756C000`).
- 「그날 손절 수 이어받기」는 같은 날·같은 `NAME`·같은 종목의 앞선 폴더들의 `trade` 줄에서 센다.
- `journal.jsonl` — week02 와 **같은 kind·칸**: `event` `account` `signal` `order` `fill` `trade`.
  `signal` 은 week02 처럼 진입 신호와 「신호 후보」뿐 아니라 **판정 봉마다 전부** 남긴다(대시보드 「지금 판단」·차트용).
  week02 `summarize_runs.py` 가 읽을 수 있어야 한다.
- `summary.json` — week02 와 같은 칸(`sym` `trades` `summary` `account_start` `account_end`) + `api`(아래 6-4 통계) + `strategy`(파일명·해시·Params).
- `api_log.jsonl` — 6-4.
- 개인정보 삭제: `ac_no` `ac_nm` `user_ip_addr` `ord_id` 와 토큰·키는 **쓰는 순간** 지운다(week02 `scrub`). 내려받을 때 다시 지우지 않아도 되게.

### 6-4. API 로그 — 운영자 `TradeClient.call()` 에 갈고리
- `backend/nh_api/client.py` 의 `call()` 에 `# 팀:` 표시 갈고리: 호출마다(성공·실패·예외 모두) 기록자에게 한 건 넘긴다.
  넘기는 것: 시각, `api_id`, 환경, 요청 payload, HTTP 상태, 응답 코드·메시지, 걸린 ms, 호출 제한으로 기다린 초
  (`RateLimiter.wait` 반환값), 토큰 재발급 후 다시 보냈는지, 예외 종류, 응답 본문.
- **기록 대상은 파이썬 전략 실행이 부른 호출만**: 실행 스레드에서 `contextvars` 로 「지금 실행 id·용도」를 세팅,
  갈고리는 그 값이 있을 때만 그 실행의 `api_log.jsonl` 에 쓴다. 화면이 부른 호출은 남기지 않는다.
- 한 줄 칸: `at` `run` `purpose`(준비봉·1분봉·현재가·진입·청산·체결확인·잔고확인·예수금·품목확인) `api_id` `env`
  `request` `http` `code` `message` `ms` `waited_ms` `reissued` `ok` `error` `body`.
- `body` 는 주문·주문내역·잔고·예수금·품목, 그리고 **실패한 호출** 은 전체(삭제 규칙 적용). 현재가·1분봉 성공은 본문 대신
  요약(현재가 값 / 받은 봉 수·첫·끝 시각). 하루 현재가 호출 2만여 건이라 본문을 다 남기면 수백 MB.
- `summary.json` 의 `api`: API별 호출 수·실패 수·오류 코드별 수·평균/최대 ms·기다린 총 시간·재발급 수.

### 6-5. 라우트 — `/api/team/pyrun/...`
- `GET strategies` 폴더의 전략 목록(파일명, `TITLE`, Params 기본값, 불러오기 오류)
- `POST strategies/reload`
- `GET runs` / `POST runs`(전략 파일, 모드, 종목 — 빈 칸이면 최근월물) / `GET runs/{id}`(상태·보유·손절가·익절 목표·
  시간 청산 시각·오늘 손익·손절 수/한도·마지막 판정·Params)
- `GET runs/{id}/journal?after=<줄번호>` 화면이 이어 받기
- `GET runs/{id}/bars` 판정 봉 + 지표 칸(차트용, journal `signal` 에서 만들어도 됨)
- `POST runs/{id}/stop` · `POST runs/{id}/flatten`
- `GET runs/{id}/download` → zip(`<폴더이름>/journal.jsonl, summary.json, api_log.jsonl`). 진행 중에도 받을 수 있되 이름에 `_partial`.
- `orders` 시작은 화면이 확인창(운영자 앱의 주문 확인 문구 형식)을 거친 뒤에만.

## 7. 화면 — 전략주문 › 「파이썬 전략」

형식은 기존 「전략 진행」(`frontend/src/screens/strategy/StrategyRun*`, `RunSide`, `RunMain`, `RunHead`)과 같은 레이아웃·
CSS 토큰. 새 파일은 `frontend/src/screens/team/`. 시안은 대화 중 보여 준 것(왼쪽 250px, 오른쪽 상세).

- **왼쪽 ① 전략 파일**: 폴더 경로 안내, 파일 목록(제목·파일명·오류), 「폴더 다시 읽기」, 「+ 실행 세우기」(모드·종목 고르는 작은 폼).
- **왼쪽 ② 실행 목록**: 이름, 파일·종목, 배지(모의 계좌 / 종이, 대기·진행 중·끝). 끝난 실행 줄에 「⬇ 결과」.
- **오른쪽 ③ 머리줄·상태 막대**: 제목·배지·파일·종목·판정 봉·다음 판정 시각, 버튼 「⬇ 결과 내려받기」·중지·청산.
  막대: 보유(방향·수량·평균가) · 손절가(틱) · 익절 목표 · 시간 청산 시각 · 오늘 손익 · 오늘 손절/한도.
- **④ 차트**: 판정 봉 캔들 + 지표선(이름 규칙 4장) + 진입·청산 표시 + 손절가 선, RSI 등은 아래 창. 앱의 기존 차트 컴포넌트
  재사용 여부는 빌더 판단.
- **⑤ 지금 판단**: 마지막 판정 봉의 종가·지표·`reason`, 그리고 Params 표.
- **⑥ 아래 표 탭**: 신호 / 주문·체결 / 거래 / 이벤트 / API 로그. 종이 실행의 체결은 「종이 체결」로 분명히.
- 화면은 폴링(1~2초)으로 충분. 브라우저를 닫아도 실행은 백엔드에서 계속.

## 8. 시험

- 전략 판정 동일성: week02 의 저장된 1분봉으로 앱 실행기 리플레이(종이) 결과가 week02 `runner.py --replay` 와 같은지.
  week02 결과(`results/runs/20261030_bb_replay`)를 기준값으로 삼아도 된다. 리플레이 경로는 시험용으로만 있어도 됨.
- 불러오기: 문법 오류 파일, 약속 위반 파일, 공용 모듈 import, 이름 충돌.
- 주문 안전: 주문 응답 없음 → 재전송 안 함·새 주문 막힘, 체결 미확인 → 잔고로 판단, 청산 미체결 재시도.
- 개인정보 삭제: journal·api_log·summary 에 금지 칸이 없음.
- API 로그: 실행 호출만 남고 화면 호출은 안 남음, 토큰 재발급·호출 제한 대기·예외가 남음.
- 기존 테스트(`just test`, 3150개) 그대로 통과, `just lint` · `just typecheck`.

## 9. 빌더에게 맡기는 것
- 패키지·파일 이름, 실행 스레드 구조(스레드 vs asyncio), 상태 파일 형식.
- 전략 폴더 격리 불러오기 방법.
- 차트를 기존 컴포넌트로 그릴지 새로 그릴지.
- 화면 폴링 간격·표 페이지 나누기.

## 10. 제 판단으로 정한 것 (사용자 확인 필요)
- 전략 모듈에 `STRATEGY`·`TITLE`·`NAME` 세 줄 추가 약속, VWAP(`strategy.py`)엔 `target` 프로퍼티 한 줄 더.
- 실행 하나 = 기록 폴더 하나(같은 날 다시 켜면 `_2` …). week02 의 「같은 폴더에 이어 쓰기」와 다름.
- `orders` 시작 때 이 종목 잔고가 남아 있으면 자동 정리 대신 **시작 거부**.
- 중지 = 정리하고 끝. 청산 = 보유만 닫고 계속.
- `orders` 실행은 종목당 하나.
- 보유 중 잔고 대조 30초 간격, 어긋나면 「확인 필요」로 멈추고 이때의 중지는 정리 없이 끝.
- 파일 위치 `~/NHFutures/strategies/`, 기록 위치 `~/NHFutures/state/pyruns/`.
- 판정 봉마다 `signal` 줄을 전부 남김(week02 는 신호·후보만).
