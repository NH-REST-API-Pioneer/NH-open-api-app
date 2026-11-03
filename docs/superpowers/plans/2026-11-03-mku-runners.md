# MKU 해외 자동매매 (ORB 1분봉 · leadlag 실시간) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3주차 MKU 전략 두 개를 앱의 파이썬 전략 실행기로 해외 모의 계좌(또는 종이)에서 돌린다. ORB 는 1분봉 실행기를 해외로 넓혀서, leadlag 는 새 실시간(초 단위) 실행기로 돌린다. 판단(진입·청산)은 전략 파일이 하고, 주문·안전·기록은 앱이 맡는다.

**Architecture:** `backend/team_pyrun/` 에 시장 묶음(`markets.py`: 국내 미국달러선물·해외 MKU의 API·시간표·통화)을 두고, 1분봉 실행기(`runner.py`·`live.py`)와 새 실시간 실행기(`realtime.py`)가 이 묶음과 기존 `MockAccountBroker`·`Journal`·`ApiLog` 를 함께 쓴다. 실시간 시세는 운영자 허브(`backend/realtime/hub.py`)의 묶기 전 원문을 `# 팀:` 갈고리로 받아 실행 스레드에 순서대로 넘긴다.

**Tech Stack:** Python 3.13 · FastAPI · asyncio(허브) + threading(실행) · pytest / React · TypeScript

**Spec:** `docs/superpowers/specs/2026-11-03-mku-runners-design.md`
**week03 원본(내려받은 사본, 실행 금지·읽기만):** `/private/tmp/claude-501/-Users-yoon-eunseok-Documents-NH-open-api-app/dc4e8c54-cca4-4737-bfac-be63429aeb4f/scratchpad/week03/`
(`strategy_orb.py` `common.py` `backtest.py` `nh_client.py` `leadlag/ws_trader.py` `leadlag/replay_live.py` `leadlag/nh_client.py`). 데이터·결과는 `gh api repos/NH-REST-API-Pioneer/pioneer-1st-6team-NFT/contents/week03/<path> -H "Accept: application/vnd.github.raw"` 로 받는다 — `results/data/bars_1m_MKUX26.csv`, `results/backtest_orb/start_all.json`, `leadlag/results/live/<날짜>/`.

## Global Constraints

- 운영자 파일을 고친 자리엔 전부 `# 팀:`(TS 는 `// 팀:`). 팀 코드는 `backend/team_pyrun/`, `frontend/src/screens/team/`, `frontend/src/data/pyrun.ts`, `tests/test_team_pyrun_*.py`, `docs/team/`.
- NH 호출은 전부 `environment="paper"`. 주문은 재전송 금지 — 기존 `MockAccountBroker` 의 `blind`·`unresolved`·주문 전 잔고 관문·「확인 필요」 규칙을 해외 주문에도 그대로. 조회만 재시도(최대 3회).
- 응답 칸 이름은 `tests/fixtures/nh/` 기록 → 없으면 운영자 `backend/overseas_futureoption/` 의 해석 코드 → week03 `nh_client.py` 순으로 확인(추측 금지). 해외 주문·주문내역·잔고·예수금은 기록이 없다.
- 기록에 남기지 않는 칸은 기존 `journal.scrub` 규칙 그대로(쓰는 순간).
- MKU: 틱 0.0001 = US$2.5, 통화 USD, 종이 수수료 편도 US$2(체결마다), 종이 슬리피지 1틱. 국내: 기존 값 그대로.
- 해외 시간표(한국 시간): 장 08:25~20:35 · 휴장 20:35~20:50 · 20:50~; 해외 1분봉 실행 끝 `235500`; 휴장 중 주문 없음. 국내 실행 끝 `153100` 그대로.
- 같은 MKU 종목의 `orders` 실행은 1분봉·실시간 통틀어 하나. leadlag 의 KRX 종목(시세용)은 막지 않음.
- week02 국내 골든 유지: `strategy_bb.py` 10/30 3건 +54,000원, `strategy.py` 5건 −21,000원.
- 상태 낱말 그대로: `대기` `진행 중` `확인 필요` `끝` `오류`. 배지: `모의 계좌` `종이` `리플레이` + 새 `실시간`.
- 검사: `uv run pytest -q`(현재 3461 passed, 2 skipped, 1 Starlette 경고) · `uv run ruff check .` · `cd frontend && npm run typecheck && npx eslint src/screens/team src/data/pyrun.ts`.
- 커밋 메시지 끝에 빈 줄 + `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **허브 큐가 느린 소비자에게 밀려 원문을 잃음** → 갈고리는 허브 이벤트 루프를 막지 않고(넣기만), 실행 스레드가 순서대로 꺼냄. 쌓임이 한도를 넘으면 그 실행을 `확인 필요`로 멈추고 기록(조용히 잃지 않음). → Task 6 `test_원문_갈고리가_밀리면_실행을_멈춘다`.
2. **휴장(20:35~20:50) 중 보유·청산 요청** → 주문하지 않고 20:50 첫 가격 때 청산. → Task 5 `test_휴장_중_청산은_재개_뒤에`.
3. **앱 재시작 중 실시간 실행이 돌고 있었음** → 종료 때 정리, 못 했으면 다음 시작 때 「끝(재시작)」과 잔고 기록(1분봉과 같은 `recover`). → Task 9 `test_실시간_실행도_재시작_정리`.
4. **KRX 시세가 끊긴 채(국내 장 마감) MKU 만 들어옴** → Engine 의 `stale_s` 규칙에 맡기되, 실행은 멈추지 않고 화면에 마지막 KRX 수신 시각을 보임. → Task 7 `test_KRX_가_끊겨도_실행은_계속`.
5. **ORB·leadlag 를 같은 MKU 로 둘 다 모의 계좌 시작(탭 두 개)** → 두 번째 거부. → Task 9 `test_같은_MKU_모의_실행은_실행기_종류와_상관없이_하나`.

---

### Task 1: 해외 API 계층 (`api.py` 넓히기)

**Files:** Modify `backend/team_pyrun/api.py` · Test `tests/test_team_pyrun_api_overseas.py`

**Interfaces — Produces** (모두 `client=None` 키워드, `environment="paper"`, 국내 함수와 같은 꼴):
- `ovs_chart_minute(sym, *, req_qty: int, exch_cd="FSGX") -> list[dict]` — 요청 값은 week03 `nh_client.ovs_chart_minute` 와 운영자 해외 차트 래퍼에서 확인. 줄은 접두 뗀 dict(`ref_dt` `exch_tm` `open_pric` `high_pric` `low_pric` `close_pric` 등 — 칸 이름 확인).
- `ovs_price(sym, *, exch_cd="FSGX") -> dict` (마지막 체결가 칸 확인), `ovs_product_detail() -> list[dict]`, `mku_spec(rows) -> tuple[float, float]`(틱 단위, 틱 가치 — `tick_unt`/`tick_val` 확인),
  `nearest_mku(...) -> str`(최근월물 — 운영자 해외 종목 마스터 또는 `overseas_product-expiry` 로; 방법은 구현자 판단, 근거를 주석에),
  `ovs_market_order(sym, side, qty=1) -> dict`(**재시도 없음**), `ovs_order_history() -> list[dict]`, `ovs_open_interest() -> list[dict]`, `ovs_net_position(rows, sym) -> int`, `ovs_deposit(cur_cd="USD") -> dict`.
- 체결 확인에 필요한 칸·상태 코드(국내 `ord_sts` `"6"`·`"8"/"9"`, `avg_exec_pric`/`exec_pric` 에 해당하는 해외 칸)를 모듈 상수로: `OVS_FILLED`, `OVS_REJECTED`, `ovs_fill_price(row) -> float|None`.

- [ ] Step 1: 시험 — 요청 값(MockTransport 가 받은 json), 줄 접두 떼기, 주문 ConnectTimeout → 서버 1회, 조회 EGW036 → 재시도, `ovs_net_position`(매수/매도 구분 칸 확인), `mku_spec` 이 `tests/fixtures/nh/overseas_product-detail/` 의 MKU 줄에서 (0.0001, 2.5).
- [ ] Step 2: 실패 확인 → Step 3: 구현 → Step 4: 통과 + `ruff`
- [ ] Step 5: 기록 없는 해외 주문 계열 칸은 근거(운영자 파일:줄 또는 week03 파일:줄)를 함수 docstring 에 적는다.
- [ ] Step 6: 커밋 `feat(team): 해외 API 계층 — MKU 차트·현재가·주문·주문내역·잔고·예수금`

### Task 2: 시장 묶음 (`markets.py`) — 브로커·실행이 시장을 몰라도 되게

**Files:** Create `backend/team_pyrun/markets.py` · Modify `broker.py`(필요한 만큼) · Test `tests/test_team_pyrun_markets.py`

**Interfaces — Produces:**
- `@dataclass(frozen=True) Market(id: "domestic"|"overseas", currency: "KRW"|"USD", end_time: str, session_start: str, breaks: tuple[tuple[str,str],...], paper_fee: float, paper_slip_ticks: int)` 와 `DOMESTIC`, `OVERSEAS` 상수(값은 Global Constraints).
- `market_of(sym: str) -> Market` — `A75…` → 국내, `MKU…` → 해외, 그 외 `ValueError`.
- `in_break(market, hhmmss) -> bool`.
- `adapter(market, api_module=api)` — **기존 `MockAccountBroker` 가 부르는 이름**(`market_order` `order_history` `open_interest` `net_position` `deposit`, 체결 칸 해석)과 1분봉 실행이 부르는 이름(`chart_minute` `price` `num` `rows`, 틱 확인용 spec)을 그 시장 함수로 잇는 객체. 국내 어댑터는 지금 `api` 와 똑같이 동작해야 한다(기존 시험 무변경 통과).
- `MockAccountBroker` 의 체결 상태·체결가 해석을 어댑터에서 받게 하는 최소 수정(주문 경로 논리는 건드리지 않음 — 리뷰 포인트).

- [ ] 시험: 국내 어댑터로 기존 `tests/test_team_pyrun_live.py`·`registry` 가 그대로 통과 / 해외 어댑터로 브로커가 `ovs_market_order` 를 1회만 부르고 체결 확인·잔고 관문·`blind` 가 같은 규칙으로 동작(가짜 해외 api) / `market_of` / `in_break`.
- [ ] 커밋 `feat(team): 시장 묶음 — 국내·해외 API·시간표·통화를 한 자리에`

### Task 3: 1분봉 실행기 약속 넓히기 (청산 판단·신호 꼴·Params 채우기·실행기 종류)

**Files:** Modify `backend/team_pyrun/runner.py`, `loader.py` · Test `tests/test_team_pyrun_runner.py`(추가), `tests/test_team_pyrun_loader.py`(추가)

**Interfaces — Produces:**
- 전략이 청산 판단 함수를 가지면(이름·인자는 구현자가 정해 문서화 — 예: `exit_reason(price, low, high, clock, pos) -> str | None`, `pos` 는 `side` `entry` `entry_time` `entry_date` `signal`(진입 신호 객체) `stop` 등) `Runner.on_price` 가 공통 손절·익절·시간 규칙 대신 그 함수를 쓴다. 장 마감(`flatten_at`)·실행 끝·`halted`·결과 모름 규칙은 앱이 계속 앞선다. 없으면 지금 동작 그대로(골든 유지).
- 신호 꼴: `bar` 가 없고 `minute` 이 있으면 그걸 판정 봉으로. 기록 칸 = 신호의 숫자·문자 dataclass 칸 전부(예약 칸·비유한수 제외 규칙은 기존과 같게) + `bar`/`minute` 의 OHLC.
- `on_entry` 인자: 매개변수가 없으면 `on_entry()`, 있으면 이름이 같은 신호 칸 값을 넘김(ORB `window`). 규칙을 docstring 에.
- `trade` 줄에 진입 신호의 `window`(있으면) 를 남김.
- loader: `REQUIRED_PARAMS` 를 시장 시간표로 채울 수 있게 — 없는 칸은 `Loaded` 가 아니라 실행 시작 때 `Market` 으로 채움(값: 시작 `session_start`, 진입 끝 = 청산 시각, 청산 = Params 의 `flatten_at` 또는 해외 `235000`/국내 기존). `Loaded.kind: "minute"|"realtime"` — `on_minute` 있으면 minute, `on_krx`/`on_quote` 있으면 realtime, 둘 다면 `LoadError`. 실시간 전략의 필수 이름: `on_krx` `on_quote` `on_timer` `filled_entry` `filled_exit`, Params dataclass(`LiveParams` 도 인정 — 전략 클래스 `__init__` 첫 인자 주석 규칙 재사용).
- `TICK_VALUE` 대신 `TICK_USD` 도 인정(leadlag).
- [ ] 시험: 청산 판단 함수가 있는 가짜 전략 → 공통 규칙 안 씀, `"손절"` 반환 시 청산·`on_exit(stopped=True)`; 장 마감은 전략이 None 이어도 청산; `on_entry(window)` 에 신호 값; `minute` 꼴 신호 기록; Params 채우기; `kind` 판별 세 경우; week02 골든 두 개 그대로.
- [ ] 커밋 `feat(team): 1분봉 실행기 — 전략이 청산을 판단하는 약속, 신호·Params 넓히기`

### Task 4: ORB 앱용 파일 + MKU 리플레이 골든

**Files:** Create `docs/team/examples/strategy_orb_app.py`; Create `tests/fixtures/team_pyrun/week03/{strategy_orb.py,common.py,bars_1m_MKUX26.csv,start_all.json}`(원본 그대로 복사); Modify `backend/team_pyrun/replay.py`(시장·수수료 인자); Test `tests/test_team_pyrun_orb.py`

- 앱용 ORB 파일: `from strategy_orb import Params, SessionBreakout`(판정 코드 **고치지 않음**) + `backtest.py` 의 ORB 체결·청산 규칙을 Task 3 의 청산 판단 함수로 옮김 — 손절 = 진입 신호의 범위 반대편 끝(`range_low`/`range_high`), 익절 = 진입가 + `target_ticks`(불리한 쪽 호가), 시간 = `hold_min`·`exit_by` 중 먼저, 23:50 마감. 진입은 다음 분(실행기 pending 규칙). 파일 맨 위에 「이 파일은 무엇을 어디서 옮겼나」를 적음.
- replay: `replay(loaded, date|None, minutes, folder, *, market, fee, slip_ticks)` — 여러 날 csv 를 날마다 이어 돌림(week03 `backtest.run` 처럼 날짜가 바뀌면 새날). 해외 리플레이는 `market=OVERSEAS`.
- 골든: week03 `results/backtest_orb/start_all.json`(기간 20261012~20261102, 37건, net_pnl US$87.5, 수수료 0, 슬리피지 1틱) 과 **거래 목록이 같다**(진입·청산 시각·가격·사유). 처음에 다르면 week03 `backtest.py` 의 체결 규칙(그 분 시가 체결, 손절 `min(open, stop)` 등)과 우리 리플레이 순서를 비교해 진단하고, 그래도 남는 차이는 DONE_WITH_CONCERNS 로 값·원인 보고(골든 값 몰래 바꾸지 않음). 내려받은 코드 실행 금지.
- 장중 시작·같은 날 재시작(스펙 5절): 준비 봉 동안 진입 신호 난 window 와 같은 날 앞선 실행(같은 NAME·종목·방식) `trade` 의 window 는 다시 들어가지 않는다. 그날 손절 수는 한 번만 센다(이중 집계 금지). week02 전략의 `stops_before` 동작은 그대로. 구현 위치는 `live.py` 준비 단계 — Task 5 와 함께 해도 되지만 시험은 여기 둔다.
- [ ] 시험: 골든 / `strategy_orb_app.py` 를 `common.py` 와 같이 tmp 전략 폴더에서 불러옴(`kind == "minute"`, 이름 `strategy_orb_app`) / 준비 봉 신호 window 재진입 없음 / 앞선 실행 window 이어받기 / 손절 이중 집계 없음.
- [ ] 커밋 `feat(team): ORB 앱용 파일과 MKU 리플레이 골든`

### Task 5: 해외 1분봉 장중 실행 (`live.py`·`registry.py` 시장 반영)

**Files:** Modify `backend/team_pyrun/live.py`, `registry.py` · Test `tests/test_team_pyrun_live_overseas.py`

- `RunSpec.sym` 으로 `market_of` 를 정하고(빈칸이면 전략 종류·파일의 `TICK` 으로 — MKU 틱이면 해외 최근월물, 아니면 국내 최근월물; 규칙 문서화), `LiveRun` 이 `Market` 과 어댑터로 1분봉·현재가·틱 확인·브로커·예수금을 부른다. 끝 시각 = `market.end_time`. 휴장 중엔 `on_price` 의 주문을 보류하고 휴장이 끝난 첫 가격에서 처리(신호 pending·청산 둘 다). `run.json`·`status()`·`summary.json` 에 `market` `currency`.
- registry: 시작 거부 시각을 시장별 끝 시각으로, 주말 거부 그대로, `orders` 실행 하나 규칙의 키 = 주문 종목(실행기 종류 무관, Task 9 에서 실시간도 같은 키 사용).
- [ ] 시험: 가짜 해외 api 로 08:24 대기 → 08:26 분봉·현재가 / 틱 다르면 거부 / 휴장 중 손절가 지남 → 20:50 첫 가격에 청산 주문 1회 / 23:55 끝 / USD 표기 / 국내 시험 무변경.
- [ ] 커밋 `feat(team): 해외 MKU 1분봉 장중 실행 — 시간표·휴장·USD`

### Task 6: 허브 원문 갈고리 (`backend/realtime/hub.py` `# 팀:`)

**Files:** Modify `backend/realtime/hub.py`(최소) · Create `backend/team_pyrun/rawfeed.py` · Test `tests/test_team_pyrun_rawfeed.py`

- 허브의 원문 수신 자리(`_on_data`, 묶기 전)에 「원문 구독자」 목록을 두고 받은 순서 그대로 `(market, api_id, sym, body, recv_monotonic)` 를 넘긴다. 구독자 호출은 넣기만(`queue.SimpleQueue` 등, 막지 않음). 운영자 동작(묶음·화면)은 그대로.
- `rawfeed.RawFeed(run_id, wants: list[Feed])`: 허브 이벤트 루프에서 `attach(run_id)`+`declare(wants)` 로 구독을 세우고(운영자 `RunPump` 와 같은 방식 — 묶음 큐는 비워 버림), 원문 구독자로 등록, 스레드가 `get(timeout)` 으로 꺼냄. `close()` 는 `detach`+구독 해제. 루프 참조는 앱 시작 때 잡아 둠(`run_coroutine_threadsafe`).
- 쌓임 한도(예: 5,000)를 넘으면 그 RawFeed 에 `overflow` 표시 → 실행이 `확인 필요`로 멈춤(Review Focus 1).
- [ ] 시험: 가짜 허브 데이터 순서 보존(KA·FB 섞인 순서 그대로) / 묶음 동작 기존 시험 무변경 / detach 뒤 원문 안 옴 / 한도 넘김 → overflow.
- [ ] 커밋 `feat(team): 허브 원문 갈고리 — 실시간 실행이 묶기 전 시세를 순서대로 받게`

### Task 7: 실시간 실행기 (`realtime.py`)

**Files:** Create `backend/team_pyrun/realtime.py` · Test `tests/test_team_pyrun_realtime.py`

- `RealtimeRun(run_id, folder, loaded, spec, *, api_module, feed_factory, now, monotonic, sleep)` — `LiveRun` 과 같은 겉모양(`prepare` `step`/`run_forever` `request_stop` `request_flatten` `finish` `status` `state` `run.json`, `ApiLog` bind). 공통 부분(상태 파일·요약·apilog bind 등)은 `live.py` 에서 꺼내 같이 쓰되 1분봉 동작은 바꾸지 않는다.
- 넣기(스펙 6-1, ws_trader `on_dom`/`on_ovs`/`timer` 와 같게): KA(`tick_div=="1"`·체결수량>0) → `on_krx(last_pric, recv_monotonic, exch_tm[:6])`; FB 1단 → `on_quote(bid, ask, recv_monotonic, ko_exec_tm[:6])`; 1초마다 `on_timer`. 칸 이름은 `tests/fixtures/nh/KA|FB` 기록으로 확인.
- 행동 실행: `orders` → 해외 어댑터의 `MockAccountBroker.fill`(결과 모름 → 「확인 필요」, ws_trader 의 「호가로 기록하고 계속」 아님), 체결가로 `filled_entry`/`filled_exit`; `paper` → 반대 호가(`ref`) 체결, 수수료 편도 US$2. 주문·체결 확인은 원문 꺼내기를 막지 않게(별도 스레드 또는 실행 스레드에서 하되 그동안 원문은 RawFeed 에 쌓임 — 한도 안).
- 끝: 전략 Params `flatten_at` + 5분, 중지·오류. 보유 남으면 앱이 청산 주문 → `filled_exit(…, "실행 종료 정리")`. 「확인 필요」면 청산 안 함(기존 R14).
- 기록: `event` `signal`(진입·청산 신호 때, `dk` `rho` `spread` `expected` `followed`) `order` `fill` `trade`(`gross_ticks` `net_ticks` `net_usd` `held_s` + 기존 칸) 와 1분마다 `minute` 줄(`krx` `mku_mid` `spread_ticks` `last_krx_at`). 원문 저장 안 함.
- [ ] 시험(가짜 RawFeed·가짜 api·손으로 넣는 시계): 진입 행동 → 주문 1회·`filled_entry` / 결과 모름 → 확인 필요·추가 주문 없음 / 종이 체결가 = 반대 호가·수수료 / 청산 행동 / 끝 정리 / KRX 끊겨도 계속(Review 4) / overflow → 확인 필요 / 개인정보 없음.
- [ ] 커밋 `feat(team): 실시간 실행기 — 원문 시세를 Engine 에 넣고 MKU 를 안전하게 주문`

### Task 8: leadlag 예제 파일 + 리플레이 골든

**Files:** Create `docs/team/examples/strategy_leadlag.py`(ws_trader 에서 `TICK` `TICK_USD` `FEE_TICKS` `LiveParams` `Engine` 만, 표준 라이브러리만) · Create `tests/fixtures/team_pyrun/week03/leadlag/`(녹화 `raw.jsonl.gz`·`summary.json`·`events.csv` 받을 수 있으면) · Modify `replay.py`(실시간 리플레이) · Test `tests/test_team_pyrun_leadlag.py`

- 실시간 리플레이: 녹화 원문을 ws_trader `replay_live.py` 와 같은 규칙(KA·FB 만, 시각 = `recv_ts`, 종이 체결 = 신호 순간 반대 호가)으로 `RealtimeRun` 의 넣기 경로에 흘린다(같은 코드 경로를 써야 의미 있음).
- 골든: 받은 녹화 날짜의 `replay_live.py` 기준 결과(그 날 `summary.json`/`events.csv` 의 거래)와 같은 진입·청산. 녹화가 너무 작거나 없으면 손으로 만든 순서로 진입 1·손절 1·시간 청산 1 을 시험하고 그 사실을 보고.
- [ ] 시험: 예제 파일이 loader 에서 `kind == "realtime"` / 골든 / ws_trader `Engine` 과 예제 `Engine` 소스가 판단 메서드에서 같음(복사 확인).
- [ ] 커밋 `feat(team): leadlag 실시간 예제 파일과 녹화 리플레이`

### Task 9: 실행 관리·라우트 연결

**Files:** Modify `backend/team_pyrun/registry.py`, `routes.py`, `live.py`(필요시) · Test `tests/test_team_pyrun_registry.py`·`routes.py`(추가)

- `RunSpec` 에 `signal_sym: str | None`(실시간의 KRX 종목, 빈칸=국내 최근월물). `loaded.kind` 로 `LiveRun`/`RealtimeRun` 선택. 주문 종목 하나 규칙(Review 5), 시장별 끝 시각 거부, 모의 환경 아니면 orders 거부, `recover` 가 실시간 실행 폴더도 닫음(Review 3), `stop_all` 이 실시간 실행도 정리.
- 라우트: `POST /runs` body 에 `signal_sym` 선택 칸. `status` 에 `kind` `market` `currency` 와 실시간 칸(`krx` `bid` `ask` `last_dk` `last_rho` `held_s` `last_krx_at`). `/bars` 는 실시간 실행이면 `minute` 줄로 (`krx`·`mku_mid`) + 표시(진입·청산). CSRF·Host 가드 그대로 적용.
- [ ] 시험: 같은 MKU orders 두 번째 거부(1분봉·실시간 조합 둘 다) / 실시간 recover / 실시간 status·bars 모양 / 해외 끝 시각 뒤 시작 거부.
- [ ] 커밋 `feat(team): 실시간·해외 실행을 실행 관리와 라우트에 연결`

### Task 10: 화면

**Files:** Modify `frontend/src/data/pyrun.ts`, `frontend/src/screens/team/*`(`PySymbolPicker` 포함)

- 종목 고르기: 고를 수 있는 종목 = 국내 `A75…` + 해외 `MKU…`(다른 해외는 「이 실행기는 미국달러선물·MKU 만 됩니다」). 전략이 실시간이면 칸 두 개 — 「신호 종목(KRX)」·「주문 종목(MKU)」, 둘 다 빈칸 = 최근월물. 1분봉 전략은 칸 하나.
- 배지 `실시간`, 금액에 통화(USD 는 `US$` 두 자리), 상태 막대 실시간 칸(스펙 6-3), 차트: 1분봉 실행은 `range_high`/`range_low` 선, 실시간은 `minute` 줄 MKU 중간값 선 + KRX 선(오른쪽 축) + 진입·청산 표시. 기존 디자인·토큰만.
- [ ] 검사 typecheck·eslint. 가능하면 `NH_REPLAY=1` 로 8010/5174 에 띄워 ORB 리플레이 폴더·실시간 리플레이 폴더가 화면에 뜨는지 확인(사용자 :8000 금지).
- [ ] 커밋 `feat(team): 화면 — MKU·실시간 실행 표시`

### Task 11: 문서·마무리

**Files:** Modify `docs/team/strategy-file-convention.md`(+화면 「작성 규칙」은 같은 파일), `claude.md`(개인, 커밋 안 함), spec 상태 줄

- 작성 규칙 문서에 장 추가: ① 전략이 청산을 판단하는 약속(함수 꼴·`pos` 칸·앱이 앞서는 안전 규칙) ② ORB 를 앱에 올리는 법(`strategy_orb.py`+`common.py`+`strategy_orb_app.py`, 예제 경로) ③ 실시간 전략 약속과 **ws_trader 에서 Engine 떼어 올리는 법**(지울 것·남길 것 목록, 예제 경로) ④ MKU 시간표·휴장·USD·「같은 MKU 모의 실행 하나」.
- 문서 안 예제 코드 블록이 실제로 불러와지는지 시험(기존 방식 확장).
- [ ] 전체 검사 + 개인정보 grep(기존과 같게, 서버 기록 폴더가 아니라 시험 tmp 폴더로).
- [ ] 커밋 `docs(team): MKU·실시간 전략 작성 규칙`
