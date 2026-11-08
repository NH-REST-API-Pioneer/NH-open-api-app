# 파이썬 전략 탭 — 모든 선물 (1분봉 실행기) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파이썬 전략 탭의 1분봉 실행기(`LiveRun`)가 국내·해외 어떤 선물이든(설계 4.1 범위) 돌고, 자정을 넘는 장도 실행 하나로 돈다.

**Architecture:** 종목은 스프레드 탭의 `team_spread.legs`/`start` 로 찾은 `Leg` 를 실행에 넘긴다. 장 열림은 운영자 판정을 감싼 공용
함수(`team_pyrun/opening.py`)로 보고, 자정 넘는 실행만 07:00 경계 거래일 시계(`team_pyrun/tradeday.py`)로 시각을 바꿔 전략에 준다.
종목 칸이 빈 실행·판정을 안 꽂은 실행(시험·직접 생성)은 지금 코드 그대로 돈다.

**Tech Stack:** Python 3 · FastAPI · pytest (`uv run pytest`) · ruff · React/TypeScript (`npm run typecheck`·`lint`)

**Spec:** `docs/superpowers/specs/2026-11-09-pyrun-all-futures-design.md` (이하 「설계」). 계획과 설계가 다르면 설계가 이긴다.

## Global Constraints

- 주문은 재전송하지 않는다. 결과를 모르면 잔고·주문내역으로 확인할 때까지 새 주문을 막는다(지금 `MockAccountBroker` 규칙을 바꾸지 않는다).
- 모든 주문은 모의 서버(`paper`)로만. 재시작 시 계좌 실행 자동 재개 안 함.
- 민감 정보(키·토큰·계좌번호)를 코드·기록·시험·문서에 넣지 않는다. 해외 기록은 `OVS_LOG_FIELDS` 밖 값을 가린다(지금 규칙).
- 운영자 폴더 파일을 고치면 그 자리에 `# 팀:` 주석. 이 계획은 운영자 파일을 고치지 않는다(`backend/sessions/` 는 읽기만).
- **import 방향**: `team_spread.start`·`team_spread.feed` 는 `team_pyrun.live` 를 가져다 쓴다. `team_pyrun` 모듈은 이 둘을 **함수 안에서만**
  import 한다(모듈 머리에서 하면 순환). `team_spread.legs` 는 `team_pyrun` 을 안 쓰므로 머리에서 import 해도 된다.
- 거래일 경계는 `team_spread.pnl.TRADING_DAY_STARTS`(07:00) 하나를 쓴다. 문자열로는 `"070000"`.
- 문서·메시지는 한국어, 지금 파일들의 말투. 시각은 한국시간 `HHMMSS` 문자열.
- 끝낼 때마다: `uv run pytest` 전체 통과, `uv run ruff check .`. 화면을 고친 작업은 `cd frontend && npm run typecheck && npm run lint` 도.
- **기존 골든 그대로**: week02 리플레이(국내)·week03 리플레이(MKU ORB)·실시간 리플레이(leadlag) 시험을 고치지 않고 통과해야 한다.
  기존 시험을 고쳐야 하면 그것은 설계 5장의 「바뀌는 것(의도)」 에 든 것뿐이고, 보고에 시험 이름과 까닭을 적는다.

## Review Focus

1. **자정을 넘는 보유** — 23:58 진입 → 00:30 `hold_min` 청산 → 기록의 시각이 `"243000"`·날짜가 거래일. 기대: 한 실행 안에서 이어지고
   `hold_min` 이 맞게 셈. (Task 5 시험)
2. **시간표 모름** — 판정이 `unknown`·예외일 때 시작 거부(시작 때) / 주문 없음(실행 중). 기대: 조용히 주문하거나 조용히 멈춘 실행이 없음. (Task 4)
3. **틱은 같고 틱 가치가 다른 품목** — `TICK 0.0001`·`TICK_VALUE 2.5`(MKU) 전략을 `HO` 에 걸면 거부. 기대: 주문 전 거부, 메시지에 두 값. (Task 2·6)
4. **금요일 밤 → 토요일 새벽 자동 시작** — `session_start "010000"` 예약이 토요일 00:55 에 서고, 월요일 00:55 에는(일요일 거래일이라) 안 섬.
   옛 예약 파일(칸 없음)은 지금처럼. (Task 7)
5. **국내 전략의 07:00 전 시각** — 국내 종목에 `flatten_at "045500"` 같은 전략을 걸면 거부(국내는 주간만). (Task 4)

---

### Task 1: 거래일 시계 (`tradeday.py`) · Params 바꾸기 · `PAPER_FEE`

**Files:**
- Create: `backend/team_pyrun/tradeday.py`
- Modify: `backend/team_pyrun/loader.py` (`Loaded` 에 `paper_fee`, `Loaded.new` 에 `overnight`)
- Test: `tests/test_team_pyrun_tradeday.py`

**Interfaces:**
- Produces (`tradeday.py`):
  - `DAY_STARTS = "070000"` · `DAY_ENDS = "310000"` (다음 날 07:00 을 거래일 시계로)
  - `SCHEDULE_FIELDS = ("session_start", "session_end", "entry_start", "entry_end", "flatten_at")` (= `loader.SCHEDULE_PARAMS`, 그것을 가져다 씀)
  - `shift(hhmmss: str) -> str` — `"070000"` 보다 이르면 24시간 더함(`"013000"`→`"253000"`), 아니면 그대로. 이미 24 이상이면 그대로.
  - `plus_minutes(hhmmss: str, minutes: int) -> str` — 24시 넘어도 계속 셈(`"235800"`+5 → `"240300"`).
  - `is_overnight(params: object, end: str) -> bool` — 설계 4.4: 장 시각 칸 중 하나라도 `< "070000"` 이거나 `end >= "240000"`.
  - `@dataclass(frozen=True) class RunClock: overnight: bool`
    - `label(moment: datetime) -> tuple[str, str]` — (날짜 YYYYMMDD, 시각 HHMMSS). `overnight` False 면 달력 날짜·실제 시각 그대로.
      True 면 거래일(`pnl.trading_date`)과 거래일 시계(00:00~06:59 는 +24).
    - `bar(m: Minute) -> Minute` — 봉의 (date, time) 을 같은 규칙으로(False 면 같은 객체 그대로 돌려줌). `m.date`·`m.time` 은 달력 값.
    - `moment(date: str, clock: str) -> datetime` — 거꾸로: 거래일·거래일 시계 → 한국시간 datetime(`"253000"` → 다음 날 01:30).
  - `shifted_params(params_cls: type) -> type` — 장 시각 칸 중 `< "070000"` 값만 `shift` 한 같은 이름의 하위 클래스(`fill_params` 와 같은 만들기 —
    frozen 같게, `asdict` 에 바꾼 값). 바꿀 칸이 없으면 그대로.
  - `clock_text(hhmmss: str) -> str` — 기록 글용: `"153000"`→`"15:30"`, `"253000"`→`"01:30 (+1)"`.
- Produces (`loader.py`):
  - `Loaded.paper_fee: float | None = None` — 전략 모듈의 `PAPER_FEE`(0 이상 유한수가 아니면 `LoadError`). 없으면 None.
  - `Loaded.params_for(market: Market | None, *, overnight: bool = False) -> type` — `fill_params` 뒤 `overnight` 면 `shifted_params`.
  - `Loaded.new(market=None, *, overnight=False)` 는 `self.strategy_cls(self.params_for(market, overnight=overnight)())`. 기존 호출은 그대로 같음.

- [ ] **Step 1: 실패하는 시험** — `tests/test_team_pyrun_tradeday.py`
  - `shift("065959") == "305959"`, `shift("070000") == "070000"`, `shift("253000") == "253000"`
  - `plus_minutes("235800", 5) == "240300"`, `plus_minutes("153000", 1) == "153100"`
  - `is_overnight(P(flatten_at="045500", ...), end)` True · 모두 09:00~15:30 이고 `end="153100"` 이면 False · 모두 낮인데 `end="240300"` 이면 True
  - `RunClock(False).label(datetime(2026,11,10,1,30,tzinfo=KST)) == ("20261110", "013000")`
  - `RunClock(True).label(그 시각) == ("20261109", "253000")`, `label(2026-11-10 07:00) == ("20261110", "070000")`
  - `RunClock(True).bar(Minute("20261110","013000",...)).date == "20261109"` 이고 `.time == "253000"`; `RunClock(False).bar(m) is m`
  - `RunClock(True).moment("20261109", "253000") == datetime(2026,11,10,1,30, tzinfo=KST)`
  - `shifted_params` — `flatten_at="045500"` 인 frozen dataclass 가 `"285500"` 이 되고 `session_start="223000"` 은 그대로, 클래스 이름 같음, `isinstance` 참
  - `clock_text("253000") == "01:30 (+1)"`, `clock_text("090000") == "09:00"`
  - `load()` 한 전략에 `PAPER_FEE = 15.0` 이면 `loaded.paper_fee == 15.0`, `PAPER_FEE = -1` 이면 `LoadError`, 없으면 None
- [ ] **Step 2:** `uv run pytest tests/test_team_pyrun_tradeday.py -v` → 모두 FAIL(모듈 없음)
- [ ] **Step 3:** `tradeday.py`·`loader.py` 구현. `RunClock.label` 의 거래일은 `team_spread.pnl.trading_date`, 한국시간 변환은 `sessions.hours.to_kst`.
  `PAPER_FEE` 는 `TICK`·`TICK_VALUE` 를 읽는 자리와 같은 곳에서(같은 검사 함수 모양).
- [ ] **Step 4:** 위 시험 PASS, `uv run pytest` 전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 거래일 시계·Params 바꾸기·PAPER_FEE`

### Task 2: 종목 찾기 — 국내 확인 표 넓히기 · `products.py`

**Files:**
- Modify: `backend/team_spread/legs.py` (`_DOMESTIC_DETAIL_NAMES`, 거절 까닭)
- Create: `backend/team_pyrun/products.py`
- Test: `tests/test_team_pyrun_products.py` (스프레드 쪽 기존 `tests/test_team_spread_legs*.py` 는 그대로 통과)

**Interfaces:**
- Consumes: `team_spread.legs.resolve/Leg/LegError/master_rows`, `team_spread.start.load_sources/resolve_legs`(함수 안 import), `live.StartRefused`, `Loaded`
- Produces (`legs.py`): `_DOMESTIC_DETAIL_NAMES` 에 설계 4.1 표 그대로 —
  `A01 코스피200선물 · A05 미니 코스피200선물 · A06 코스닥150선물 · A08 KRX300선물 · A04 코스피200변동성지수선물(VKOSPI) ·
  A65 3년국채선물(KTB) · A66 5년국채선물(5KTB) · A67 10년국채선물(10KTB) · A70 30년국채선물(30KTB) · A75 미국달러선물(USD) ·
  A76 엔선물(JPY) · A77 유로선물(EUR) · A78 위안선물(CNH) · AAG 코스닥 글로벌 지수 · AAL KRX반도체 섹터지수선물`.
  표 밖 국내 품목 거절 메시지에 까닭: 마스터 `kospi_key == "STKFBASE"` 면 「주식선물은 틱이 주가에 따라 바뀌어 받지 않습니다」,
  그 밖은 「이 국내 품목(<뿌리> <name_kor 앞부분>)은 틱 확인 표에 없습니다」.
- Produces (`products.py`):
  - `find_product(spec: str, *, api_module: Any, today: str, master: Callable[[], tuple[list, list]] = legs.master_rows) -> Leg`
    — `load_sources({"main": spec}, …)` → `resolve_legs(…)["main"]`. 거부는 `StartRefused`(메시지에서 「다리 main: 」 머리는 뗀다).
  - `strategy_tick_refusal(leg: Leg, loaded: Loaded) -> str | None` — `TICK`·`TICK_VALUE` 가 `leg.tick`·`leg.tick_value` 와
    `math.isclose(rel_tol=1e-9)` 로 다르면 `"틱·틱가치가 전략 가정과 다릅니다 — 종목 HOZ26 0.0001·4.2 USD, 전략 0.0001·2.5"` 꼴.
  - `domestic_roots() -> list[dict]` — `[{"root": "A01", "name": "코스피200선물"}, …]` (확인 표 순서), 화면용.
  - `account_market(leg: Leg) -> Market` — `DOMESTIC` 또는 `OVERSEAS`.
  - `is_mku(product: str | None) -> bool` — 빠진 장 시간 칸을 채워 주는 품목인가(설계 4.2).

- [ ] **Step 1: 실패하는 시험**
  - 기록 `tests/fixtures/nh/domestic_product-detail/real/domestic/*.json` 의 줄과 마스터 꼴 줄(시험 안에서 만든 dict, `series`·`exp_ym`·`ctrt_size`·`fo_tp`·`cme_tp`)로
    표의 각 뿌리를 `resolve` → 틱·틱 가치가 설계 표 값(예: A01 0.05·12500, A78 0.01·1000, A65 0.01·10000)
  - `kospi_key="STKFBASE"` 줄 → `LegError` 메시지에 「주식선물」, `AA0` → 「틱 확인 표에 없습니다」
  - 야간 줄과 주간 줄이 같이 있으면 주간 줄(`cme_tp day`)
  - `find_product("HO", api_module=가짜, today="20261109", master=가짜)` → `HOZ26`·`FCME`·0.0001·4.2·USD (가짜 api 의 `ovs_product_detail_page` 가 `HO` 세부정보 줄을 줌)
  - `find_product("A75", …)` → `A756B000`·KRW·0.1·1000 · `find_product("MKU", …)` → `MKUX26`·`FSGX`·0.0001·2.5·USD (설계 4.1: 지금 상수와 같음)
  - `strategy_tick_refusal(HO 다리, TICK 0.0001·TICK_VALUE 2.5 전략)` 은 문자열, 같은 값이면 None
- [ ] **Step 2:** FAIL 확인 → **Step 3:** 구현 → **Step 4:** 위 시험·`uv run pytest tests/test_team_spread*` ·전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 종목 찾기 — 국내 확인 표 넓힘, 파이썬 전략용 find_product`

### Task 3: 장 열림 공용 판정 (`opening.py`) — 스프레드 탭도 이것을

**Files:**
- Create: `backend/team_pyrun/opening.py`
- Modify: `backend/team_spread/feed.py` (상수·`is_open`·`order_open` 이 `opening` 을 부르게. 밖으로 보이는 이름은 그대로 남김)
- Test: `tests/test_team_pyrun_opening.py`

**Interfaces:**
- Produces:
  - `Judge = Callable[[str, str, datetime], dict[str, Any]]` · `default_judge(market, sym, now)` (= `sessions_routes.judged`, 함수 안 import)
  - `DOMESTIC_OPEN_STATES = frozenset({"day"})` · `OVERSEAS_OPEN_STATES = frozenset({"open", "open-2", "next-day"})` (feed 에서 옮김)
  - `is_open(judge: Judge, market: str, sym: str, now: datetime) -> bool` — 예외면 False
  - `order_open(judge, market, sym, now) -> bool` — `is_open` 이고 국내면 한국시간 `>= DOMESTIC.session_start("090000")`
  - `known(judge, market, sym, now) -> bool` — 예외 없이 답했고 `source != "unknown"`
  - `span_text(judge, market, sym, now) -> str` — 지금 닫힘의 까닭 글(「휴장 20:35~20:50」·「장 마감」·「장 시간표 모름」), 판정의 `state`·`since`·`until` 로
  - `DayEnd = Callable[[str, str, datetime], datetime | None]` · `default_day_end` (= 해외면 `sessions_routes.trading_day_end`, 국내면 None)
- `team_spread.feed`: `DOMESTIC_OPEN_STATES`·`OVERSEAS_OPEN_STATES` 는 `opening` 것을 다시 내보내고, `LiveFeed.is_open` 은
  `opening.is_open(self._judge, leg.market, leg.sym, now)`, `order_open(feed, leg, now)` 는 지금 꼴 그대로(시험이 쓰는 이름).

- [ ] **Step 1: 실패하는 시험** — 가짜 judge 로: 국내 `day`·08:50 → `is_open` True·`order_open` False, 09:00 → 둘 다 True; 해외 `break` → False;
  `open-2`·`next-day` → True; judge 예외 → False·`known` False; `{"state":"closed","source":"unknown"}` → `known` False;
  `span_text` 가 `break` 의 since/until 로 「휴장 20:35~20:50」
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** 이 시험과 `uv run pytest tests/test_team_spread*` 전체 PASS
- [ ] **Step 5:** 커밋 `refactor(team): 장 열림 판정을 opening 하나로 — 스프레드 탭과 같이 씀`

### Task 4: `LiveRun` — 종목(`Leg`)·장 판정·실행 끝·시작 검사

**Files:**
- Modify: `backend/team_pyrun/live.py`, `backend/team_pyrun/markets.py`
- Test: `tests/test_team_pyrun_live_any.py` (새), 기존 `tests/test_team_pyrun_live*.py` 는 그대로 통과(5장 예외만)

**Interfaces:**
- Consumes: Task 1 `RunClock`·`is_overnight`·`plus_minutes`, Task 2 `Leg`·`account_market`·`is_mku`·`strategy_tick_refusal`, Task 3 `Judge`·`DayEnd`·`order_open`·`known`·`span_text`
- Produces (`markets.py`):
  - `run_end(market: Market, flatten_at: str) -> str` — 국내 `DOMESTIC.end_time`("153100"), 해외 `plus_minutes(flatten_at, 5)`(설계 4.5)
  - `paper_fee_of(market: Market, override: float | None) -> float` — override 가 있으면 그것, 아니면 `market.paper_fee`
- Produces (`live.py`):
  - `@dataclass(frozen=True) class RunPlan: params_cls: type; overnight: bool; end: str; clock: RunClock`
  - `run_plan(loaded: Loaded, market: Market) -> RunPlan` — `params_for(market)` 기본 인스턴스의 `flatten_at` 으로 `run_end` →
    `is_overnight` → overnight 면 `params_for(market, overnight=True)` 로 다시, `end` 도 바꾼 `flatten_at` 으로. registry·autostart·replay 가 같이 씀.
  - `LiveRun.__init__(…, leg: Leg | None = None, judge: Judge | None = None, day_end: DayEnd | None = None)` — 나머지 인자 그대로.
    - `leg` 가 있으면: `self.market = account_market(leg)`, `self.api = adapter_for(self.market, api_module, exch_cd=leg.exchange, cur_cd=leg.currency)`
      (국내는 exch·cur 를 안 넘김), `self.sym = leg.sym`, 통화 `leg.currency`, `_market_refusal = strategy_tick_refusal(leg, loaded)`.
      `prepare` 에서 `api.nearest()`·`api.spec()` 를 부르지 않는다(틱은 `find_product` 가 이미 확인).
    - `leg` 가 없으면 지금 길 그대로(`run_market`, `nearest()`, `spec()`).
    - `self.plan = run_plan(loaded, self.market)`, Runner 는 `loaded.new(self.market, overnight=self.plan.overnight)`.
      종이 수수료는 `paper_fee_of(self.market, loaded.paper_fee)`.
    - `judge` 가 None 이면 **지금 규칙 그대로**(`in_break(market, …)`, 국내는 막힘 없음). 있으면 `_in_break`·`_may_send`·끝내기의 휴장 판정을
      `not order_open(judge, market.id, sym, step 시각)` 또는 `… self.now()` 로(설계 4.3). `may_send` 는 judge 가 있으면 국내에도 꽂음.
      휴장 기록 글의 시각은 `span_text`.
  - 시작 검사(`_prepare`, 조회·주문 전 순서 유지)에 더함:
    - 국내인데 `plan.overnight` → `StartRefused("국내는 주간(08:45~15:45)만 돕니다 — 07:00 전 시각이 있는 전략은 국내 종목에 걸 수 없습니다")`
    - `loaded.params_missing` 이고 `not is_mku(product)` → 거부(지금 국내 문구를 「이 품목은 Params 에 적어야 합니다」로 넓힘). MKU 는 지금처럼 채움.
    - 해외이고 `plan.end > tradeday.DAY_ENDS` → 거부 「실행 끝(…)이 다음 날 07:00 을 넘습니다 — flatten_at 을 당기세요」
    - `judge` 가 있고 `not known(judge, market.id, sym, now)` → 거부 「장 시간표에 이 종목이 없습니다 — 화면 「장 시간」에서 확인하세요」
    - 해외이고 `day_end` 가 있고 `day_end(...)` 가 실행 시계로 `flatten_at` 보다 이르면 거부 「장이 정리 시각(…) 전에 닫힙니다(…)」.
      `day_end` 가 None(창 밖·장 전)이면 이 검사를 건너뜀.
  - 실행 중 판정이 `unknown`·예외로 바뀌면 그동안 주문 없음(위 관문이 이미 막음) + 상태가 바뀔 때만 기록 한 줄 「장 시간표 모름 — 주문 멈춤」.
  - 끝 시각: `step` 의 `clock >= self.market.end_time` 자리를 `clock >= self.plan.end` 로. `END_TIME` 상수는 남김(다른 곳이 씀).
  - `run.json`·`status()`·`summary.json` 에 칸 더함: `product`·`exchange`·`tick`·`tick_value`·`overnight`·`trading_date`·`end`
    (leg 없는 실행은 A75→`"A75"`·`"KRX"`, MKU→`"MKU"`·`"FSGX"`, 틱은 `loaded` 값). `currency` 는 leg 통화.
  - 시작 기록 글 「시장 … · 실행 끝 …」 은 국내 외에도 지금 꼴로, 끝 시각은 `clock_text(plan.end)`.

- [ ] **Step 1: 실패하는 시험** (`tests/test_team_pyrun_live_any.py`, 기존 live 시험의 가짜 api·가짜 시계 꼴을 따름. 해외 가짜는 `exch_cd` 인자를 받음)
  - HO 다리(`Leg("main","HOZ26","HO","overseas","FCME","USD",0.0001,4.2,"202612")`)·`TICK 0.0001`·`TICK_VALUE 4.2`·Params 여섯 칸 전략으로
    종이 실행: `prepare` 가 `nearest`·`spec` 를 안 부르고, 가짜 api 의 `ovs_chart_minute`·`ovs_price` 가 `exch_cd="FCME"` 로 불림, `run.json` 의
    `product "HO"`·`exchange "FCME"`·`currency "USD"`·`end` = `flatten_at`+5분
  - 같은 다리에 `TICK_VALUE 2.5` 전략 → `StartRefused`, 조회 0번
  - HO 다리에 Params 장 시간 칸이 빠진 전략 → 거부. MKU 다리면 지금처럼 채워 시작
  - 판정 가짜가 `unknown` → 시작 거부(모의 계좌·종이 둘 다), 조회·주문 0번
  - 실행 중 판정이 `break` → 그 동안 진입 신호는 대기, 다시 `open` 이면 첫 가격에 진입(지금 MKU 휴장 시험과 같은 흐름을 판정으로)
  - 실행 중 판정이 예외 → 주문 없음, 기록에 「장 시간표 모름 — 주문 멈춤」 한 번
  - `day_end` 가짜가 `flatten_at` 보다 이른 시각 → 거부
  - 국내 다리(`A016C000`, 코스피200)에 `flatten_at "045500"` 전략 → 「국내는 주간」 거부
  - 국내 다리 + judge 가짜(`day`) — 08:59 엔 정리 요청이 와도 주문 없음, 09:00 부터 됨
  - `PAPER_FEE = 15.0` 전략의 종이 체결 수수료 15.0
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** 새 시험·기존 `tests/test_team_pyrun_live*.py`·전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 1분봉 실행 — 아무 선물 종목, 장 판정 관문, 실행 끝 규칙`

### Task 5: `LiveRun`·`Runner` — 자정을 넘는 실행 (거래일 시계)

**Files:**
- Modify: `backend/team_pyrun/live.py` (시각·날짜를 `self.plan.clock` 으로), `backend/team_pyrun/runner.py` (시각 셈이 24시 넘어도 맞게 — 필요한 곳만)
- Test: `tests/test_team_pyrun_live_overnight.py`

**Interfaces:**
- Consumes: Task 4 `RunPlan`, Task 1 `RunClock`
- 바뀌는 것 (overnight 일 때만 값이 달라지고, 아니면 `RunClock(False)` 라 지금과 같은 문자열):
  - `_step`·`_prepare`·`finish`·`_wrap_up`·`_reconcile` 의 `now.strftime("%H%M%S")`·`"%Y%m%d"` → `self.plan.clock.label(now)`
  - 차트 줄 → `self.plan.clock.bar(minute_of(x))` (준비 봉·장중 봉 둘 다). 준비 봉 자르기 `(today, now_min)`·`_feed_minutes` 의 `now_key` 도 같은 시계.
  - `self._seen_minute`(분 바뀜 감지)는 실제 시각 그대로.
  - 브로커 `today=`(예수금 `biz_dt`)는 **시작 때의 달력 날짜 그대로**(판정: 설계 6장 모름 — 지금 값을 바꾸지 않음).
  - 장 판정(`order_open`·`known`·`day_end`)은 실제 시각.
  - `Runner` 의 재시도 시각(`retry_after` 만드는 곳, `runner.py:566` 근처)·`time_exit_at`·`_plus_minute` 가 24시 넘는 값을 `"240000"` 이상으로 이어 셈
    (`datetime.strptime` 으로 시각을 읽는 곳이 있으면 분 셈으로 바꿈).
  - 기록 첫머리에 overnight 면 한 줄: 「자정을 넘는 실행 — 거래일 <날짜>, 시각은 07:00 전이면 +24 (예 01:30 → 253000). 바꾼 Params: flatten_at 045500→285500 …」.

- [ ] **Step 1: 실패하는 시험** (가짜 시계로 2026-11-09 월 22:25 시작, HO 다리, 전략: `session_start "223000"`·`entry_start "223000"`·`entry_end "040000"`·
  `flatten_at "045500"`·`session_end "050000"`·`hold_min 45`, 23:58 봉에서 매수 신호를 내는 시험용 전략)
  - 전략이 받은 봉의 (date, time): 23:59 봉 `("20261109","235900")`, 00:01 봉 `("20261109","240100")`
  - 전략의 `p.flatten_at == "285500"`, `p.session_start == "223000"`
  - 진입 뒤 45분 → 00:4x 에 「시간 청산」, 거래 기록 `entry_time "235900"`대·`exit_time "24…"`, `entry_date == exit_date == "20261109"`
  - 04:55 에 보유가 있으면 「장 마감 정리」, 05:00 에 실행 「끝」(`plan.end == "290000"`)
  - 끝난 `run.json` 의 `trading_date "20261109"`·`overnight true`
  - 자정을 넘지 않는 MKU 전략(23:50 정리)은 준비 봉의 자정 뒤 봉이 지금처럼 달력 날짜 `("20261110","001000")` 꼴로 들어감
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** 새 시험·`tests/test_team_pyrun_runner.py`·`test_team_pyrun_orb.py`·전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 1분봉 실행 — 자정을 넘는 장은 거래일 시계로`

### Task 6: `Registry` — 종목 칸(뿌리·코드), 거래일, 다시 켤 때

**Files:**
- Modify: `backend/team_pyrun/registry.py`
- Test: `tests/test_team_pyrun_registry_any.py`

**Interfaces:**
- Consumes: Task 2 `find_product`·`strategy_tick_refusal`, Task 3 `default_judge`·`default_day_end`, Task 4 `run_plan`·`LiveRun(leg=, judge=, day_end=)`
- Produces:
  - `Registry.__init__(…, judge: Judge | None = None, day_end: DayEnd | None = None, find: Callable[..., Leg] = products.find_product)` —
    `LiveRun` 을 만들 때 그대로 넘김. **앱이 쓰는 `registry()` 공장은 `opening.default_judge`·`opening.default_day_end` 를 넘긴다**
    (시험이 만드는 Registry 는 None → 지금 규칙. 판정: 기존 시험이 실제 시간표 없이 돌게).
  - `Registry.resolve_product(spec: str) -> Leg` — `self._find(spec, api_module=self._api, today=<지금 달력 날짜>)`. 자동 시작(Task 7)도 이것을 씀.
  - `start` 의 1분봉 길(실시간 길은 그대로):
    - `spec.sym` 이 비면 지금 그대로(`run_market`·`_nearest`, leg 없음).
    - 비지 않으면 `market_of` 검사 대신 `leg = self.resolve_product(spec.sym)`(실패는 `StartRefused` 그대로),
      `strategy_tick_refusal` 이면 거부, `market = account_market(leg)`, `sym = leg.sym`. 폴더·조회 전.
    - `plan = run_plan(loaded, market)`; 주말 거부·`today`(폴더 id·`_folders_of`·`count_stops`·`entered_windows`)는 `plan.clock.label(now)` 의 날짜,
      「끝 시각 뒤」 거부는 `label(now)[1] >= plan.end`(문구의 시각은 `clock_text`).
  - `_close`(다시 켤 때): `run.json` 에 `market`·`exchange` 가 있으면 `adapter_for(DOMESTIC|OVERSEAS, self._api, exch_cd=…, cur_cd=…)`, 없으면 지금처럼 `market_of(sym)`.

- [ ] **Step 1: 실패하는 시험** (가짜 `find` 로 조회 없이)
  - `RunSpec(file, "paper", "HO")` → `find` 가 `"HO"` 로 불리고 실행의 `sym "HOZ26"`, `LiveRun` 이 그 leg 를 받음
  - MKU 틱 전략 + `"HO"` → 「틱·틱가치가 전략 가정과 다릅니다」 거부, 폴더 없음
  - 빈 sym 은 `find` 를 안 부름(지금 길)
  - overnight 전략을 토요일 01:00(한국)에 시작 → 주말 거부 아님(거래일 금요일), 폴더 이름이 `20261113_` 로 시작
  - overnight 전략을 화요일 06:59 에 시작 → 「끝 시각 뒤」 거부(거래일 월요일의 끝 `290000` 지남)
  - `run.json` 에 `exchange "FCME"` 인 끝나지 않은 폴더를 `recover` → 해외 어댑터로 잔고 조회(가짜 api 의 해외 잔고 함수가 불림)
  - 스프레드 탭 교차 잠금: HO 모의 계좌 실행이 있으면 같은 `HOZ26` 스프레드 다리 시작이 거부(기존 `_other_busy` 길이 leg 종목으로 동작)
- [ ] **Step 2:** FAIL → **Step 3:** 구현(`registry()` 공장 포함) → **Step 4:** 새 시험·`tests/test_team_pyrun_registry*.py`·전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 실행 세우기 — 품목 뿌리·종목 코드, 거래일, 판정 꽂기`

### Task 7: 매일 자동 시작 — 종목 칸 · 시작 시각 · 거래일

**Files:**
- Modify: `backend/team_pyrun/autostart.py`, `backend/team_pyrun/routes.py` (`ScheduleBody.sym`)
- Test: `tests/test_team_pyrun_autostart_any.py`

**Interfaces:**
- Consumes: Task 4 `run_plan`, Task 1 `RunClock.moment`·`label`, Task 6 `Registry.resolve_product`(`RegistryLike` 약속에 더함)
- Produces:
  - `Schedules.create(file, mode, run_id=None, sym=None)` — `sym` 이 None 이고 `run_id` 가 있으면 그 실행의 `spec.sym`. `sym` 이 있으면 `self.registry.resolve_product(sym)` 로
    leg 를 찾고 `strategy_tick_refusal` 로 틱을 확인해(실패는 둘 다 `ScheduleError`) 시장을 정함. 예약에 칸 더함: `sym`(받은 표기 그대로 — 뿌리면 뿌리), `product`, `overnight`, `end`.
    `at` = `plan.params_cls().session_start` 에서 5분 뺀 실행 시계(`"070000"` 보다 이르면 `"070000"`).
    같은 방식 겹침 검사: `sym` 예약끼리는 같은 `product`, 옛(빈 sym) 예약은 지금처럼 같은 `market`.
  - `fire_time(market)` 는 남김(옛 예약용). 옛 예약(칸 없음)은 지금 값(`at`·`_end_of`)과 달력 날짜로 그대로.
  - 날 셈: 새 예약은 `RunClock(item["overnight"])` 로 — `tick()`·`_next_start`·`_day_done`·`resume` 의 「오늘」·요일·늦음은 거래일·실행 시계로,
    예정 시각은 `RunClock.moment(거래일, at)`.
  - 시작은 `RunSpec(file, mode, item.get("sym") or None)`.
  - `routes.ScheduleBody` 에 `sym: str | None = None`, `POST /schedules` 가 넘김.

- [ ] **Step 1: 실패하는 시험**
  - `session_start "010000"`·overnight HO 예약: `at == "245500"`, `next_start` 가 금요일 거래일이면 토요일 00:55, 그 주 일요일 거래일엔 없음 → 월요일 거래일은 화요일 00:55
  - 토요일 00:55 의 `tick()` 이 `RunSpec(file, mode, "HO")` 로 시작을 부름, 같은 거래일에 두 번 안 부름
  - `session_start "090000"` 국내 전략 옛 예약 파일(칸 없음)을 읽어도 `at "085500"`·지금 `next_start`
  - `session_start "093000"` 국내 전략 새 예약 → `at "092500"`
  - MKU ORB(Params 칸 없음, 채운 08:25) 예약 → `at "082000"` (지금과 같음)
  - HO 예약이 있는데 같은 `product` 의 orders 예약을 또 만들면 `ScheduleError`
  - `POST /schedules {"file":…, "mode":"paper", "sym":"HO"}` 가 201
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** 새 시험·`tests/test_team_pyrun_autostart*.py`·전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 매일 자동 시작 — 종목 칸, session_start 기준 시각, 거래일`

### Task 8: 리플레이 — 아무 품목 · 자정 넘는 하루

**Files:**
- Modify: `backend/team_pyrun/replay.py`
- Test: `tests/test_team_pyrun_replay_any.py` + 합성 csv `tests/fixtures/team_pyrun/bars_1m_HOZ26_20261109.csv`(시험 안에서 만들어도 됨)

**Interfaces:**
- Consumes: Task 4 `run_plan`·`paper_fee_of`, Task 1 `RunClock.bar`
- Produces:
  - `main` 인자: `<전략> <YYYYMMDD> <csv> [--market domestic|overseas] [--currency XXX]`. `--market` 이 있으면 csv 이름의 종목으로 시장 가드를 하지 않고
    그 시장(통화는 `--currency`, 없으면 그 시장 기본). 없으면 지금 그대로(`run_market`).
  - `replay(…, overnight: bool = False)` 대신 `replay` 안에서 `run_plan(loaded, market)` — overnight 면 봉을 `plan.clock.bar` 로 바꾼 뒤
    날 묶기(`<YYYYMMDD>` = 거래일), 하루 끝 정리는 `r.p.flatten_at`. overnight 아니면 지금 코드 그대로(`DEFAULT_FLATTEN`).
  - 종이 수수료는 `paper_fee_of(market, loaded.paper_fee)` (리플레이 기본 인자로 넘어온 값이 있으면 그것 — 지금 시험의 호출 꼴 유지).
  - 휴장 관문은 지금처럼 없음(설계 4.8).
  - 하루 최소 봉 수(설계 4.2): `--market` 을 줬고 csv 종목이 `A75…` 가 아니면 1, 그 밖은 지금처럼 `market.min_day_bars`.

- [ ] **Step 1: 실패하는 시험** — 합성 HO csv(2026-11-09 22:00 ~ 11-10 06:00, 1분봉)·Task 5 의 시험용 전략으로
  `main([전략, "20261109", csv, "--market", "overseas", "--currency", "USD"])` == 0, 기록의 거래가 한 거래일 안(자정 넘어 청산),
  `summary.json` 의 `currency "USD"`; `--market` 없이 `bars_1m_HOZ26_…csv` 면 지금처럼 「시장이 맞지 않습니다」 2
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** 새 시험·week02·week03·leadlag 리플레이 시험·전체 PASS
- [ ] **Step 5:** 커밋 `feat(team): 리플레이 — 아무 품목, 자정 넘는 거래일`

### Task 9: 화면 — 종목 고르기·자정 넘는 시각·예약 종목

**Files:**
- Modify: `backend/team_pyrun/routes.py` (`GET /api/team/pyrun/products`), `frontend/src/data/pyrun.ts`,
  `frontend/src/screens/team/PySymbolPicker.tsx`, `PyRunMain.tsx`·`PyRunChart.tsx`·`PyRunSide.tsx`(시각 글·예약 종목)
- Test: `tests/test_team_pyrun_routes*.py` 에 products 라우트 시험 하나. 화면은 `npm run typecheck`·`npm run lint`

**Interfaces:**
- Produces (백엔드): `GET /api/team/pyrun/products` → `{"domestic": domestic_roots(), "domestic_excluded": "주식선물·일부 섹터지수(세부정보 없음)·야간"}`
- Produces (`pyrun.ts`):
  - `loadProducts(signal?) -> Promise<PyResult<PyProducts>>`, `type PyProducts = { domestic: { root: string; name: string }[]; domestic_excluded: string }`
  - `symVerdict(code, allow, products?)` — `allow 'any'` 일 때: 해외 **선물** 줄 OK, 국내 선물 줄은 앞 세 자리가 `products.domestic` 의 뿌리면 OK,
    그 밖은 까닭(옵션 · 주식선물 · 「틱 확인 표에 없음」). `'usd'`·`'mku'`(실시간 칸)는 지금 그대로.
  - `clockText(hhmmss)` — 백엔드 `tradeday.clock_text` 와 같은 결과(`"253000"`→`"01:30 (+1)"`).
  - `createSchedule(file, mode, runId?, sym?)` — `sym` 이 있으면 몸에 넣음. `PySchedule` 에 `sym?: string | null`.
- 종목 고르기: 품목 줄을 고르면 값 = 품목 뿌리(표시 「HO 최근월물 (자동)」), 종목 줄은 그 코드. 빈 값(「최근월물 (자동)」)은 지금 뜻 그대로.
- 기록·거래 표·차트 축의 시각은 `clockText`. 차트 가로 순서는 (date, time) 문자열 순서 그대로(거래일 시계라 이미 맞음).
- 매일 자동 시작 패널: 예약의 `sym` 을 보임. 「매일 자동 시작」 을 켤 때 지금 실행의 `sym`(사용자가 고른 표기 — 뿌리면 뿌리)을 넘김.

- [ ] **Step 1:** products 라우트 시험(실패) → **Step 2:** 구현 → **Step 3:** `uv run pytest` · `cd frontend && npm run typecheck && npm run lint` PASS
- [ ] **Step 4:** 손으로 한 번: `NH_REPLAY=1 just dev` 로 화면을 띄워 종목 고르기에서 `HO`·`A01` 줄이 고를 수 있고 `A0A`(주식선물) 줄에 까닭이 보이는지 (보고에 결과)
- [ ] **Step 5:** 커밋 `feat(team): 파이썬 전략 화면 — 모든 선물 고르기, 자정 넘는 시각 표시, 예약 종목`

### Task 10: 문서

**Files:**
- Modify: `docs/team/strategy-file-convention.md`, `docs/team/strategy-file-prompt.md`, `docs/team/spread-runner-convention.md`,
  `docs/superpowers/specs/2026-11-09-pyrun-all-futures-design.md`(상태 「구현됨」)
- **`CLAUDE.md` 는 건드리지 않는다** — 저장소가 무시하는 개인 파일(`.gitignore`)이라 컨트롤러가 마지막에 따로 고친다(커밋 안 함).
- Test: 없음 (문서 안 코드 예시는 `uv run python -c` 로 import 되는지만)

- [ ] **Step 1:** 작성 규칙에 장 셋 — 「모든 선물」(종목 칸 뿌리·코드, `TICK`·`TICK_VALUE` 를 품목에 맞게, 국내 확인 표와 빼는 것, `PAPER_FEE`),
  「자정을 넘는 장」(설계 4.4 전부 — 24시 넘는 시각, 거래일 날짜, Params 밖 상수, `strptime` 금지, 07:00 에서 끊김),
  「실행 끝·자동 시작 시각·장 시간표」(4.3·4.5·4.6), 한계(휴일 단축 장, 만기 주간, 겨울 ICE 유럽 07:00~08:00, 해외 당일 주문내역 자정 넘김 — 6장)
- [ ] **Step 2:** 프롬프트 문서에 같은 약속(AI 가 전략 파일을 쓸 때 지킬 것), 스프레드 작성 규칙의 국내 다리 범위
- [ ] **Step 3:** 커밋 `docs(team): 파이썬 전략 — 모든 선물·자정 넘는 장 작성 규칙`
