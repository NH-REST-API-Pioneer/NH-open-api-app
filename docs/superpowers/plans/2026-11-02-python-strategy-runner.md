# 파이썬 전략 자동매매 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `~/NHFutures/strategies/` 에 넣은 week02 형식 파이썬 전략을 앱 백엔드가 모의 계좌(또는 종이)로 자동매매하고, 전략주문 › 「파이썬 전략」 탭에서 판단 과정을 보여 주며, 끝난 실행의 `journal.jsonl`·`summary.json`·`api_log.jsonl` 을 zip 으로 내려받게 한다.

**Architecture:** 팀 패키지 `backend/team_pyrun/` 이 week02 `runner.py` 를 옮겨 온 실행기(스레드 하나 = 실행 하나, REST 폴링)를 가진다. API 요청·해석은 팀 `api.py` 가 `runtime.client().call()` 위에서 하고, 운영자 `TradeClient.call()` 에 `# 팀:` 갈고리를 달아 실행이 부른 호출만 `api_log.jsonl` 로 남긴다. 화면은 기존 「전략 진행」 형식을 따른 `frontend/src/screens/team/` 이 `/api/team/pyrun/...` 를 폴링한다.

**Tech Stack:** Python 3.13 · FastAPI · httpx(운영자 클라이언트) · pytest / React · TypeScript · Vite (화면 테스트 러너 없음 → typecheck·eslint·실제 화면 확인)

**Spec:** `docs/superpowers/specs/2026-11-02-python-strategy-runner-design.md`
**week02 원본:** `https://github.com/NH-REST-API-Pioneer/pioneer-1st-6team-NFT/tree/main/week02` — `runner.py` `nh_client.py` `strategy.py` `strategy_bb.py` `backtest.py`(`summarize`). 받는 법: `gh api repos/NH-REST-API-Pioneer/pioneer-1st-6team-NFT/contents/week02/<path> -H "Accept: application/vnd.github.raw"`

## Global Constraints

- 운영자 파일을 고친 자리엔 전부 `# 팀:` 주석. 팀 코드는 `backend/team_pyrun/`, `frontend/src/screens/team/`, `frontend/src/data/pyrun.ts`, `tests/test_team_pyrun_*.py`.
- NH 호출은 전부 `environment="paper"`(모의 서버). 실전으로 나가는 길을 만들지 않는다.
- 주문은 재전송 금지. `TransportError`·`GatewayError`(처리 여부 모름) 뒤엔 잔고로 확인될 때까지 새 주문 없음. 조회만 재시도(최대 3회, `RETRY` 종류·`TransportError`).
- 기록에 남기지 않는 칸: `ac_no` `ac_nm` `user_ip_addr` `ord_id`(앞에 `occurs1_` 가 붙은 꼴 포함), 토큰·키(`access_token` `authorization` `app_key` `app_secret` `appkey` `appsecret`). **쓰는 순간** 지운다.
- 상수: 종이 슬리피지 1틱, 종이 수수료 690원/체결, `END_TIME = "153100"`, 체결 확인 0.5초×30회, 청산 재시도 10초 뒤, 보유 중 잔고 대조 30초, 준비 봉 1,500개, 1분봉은 분이 바뀌고 3초 뒤.
- 시각은 `backend.sessions.hours.now_kst()`(컴퓨터 시간대 무관).
- 기록 폴더 `storage.state_dir() / "pyruns" / <YYYYMMDD>_<NAME>_<orders|paper>[_<종목 — 최근월물이 아니면>][_<n>]`, 실행 id = 폴더 이름. 전략 폴더 `config.HOME_DIR / "strategies"`.
- 상태 낱말(화면에 그대로): `대기` `진행 중` `확인 필요` `끝` `오류`.
- 검사: `uv run pytest` 전체 통과(현재 3150 passed, 2 skipped), `uv run ruff check .`, `cd frontend && npm run typecheck && npm run lint`.

## Review Focus

1. **전략 파일이 장중에 예외를 던짐**(`on_minute` 안의 버그) → 그 실행만 `오류` 로 끝나고 보유는 시장가로 정리, 다른 실행·앱은 그대로. → Task 6 `test_전략_예외면_정리하고_오류로_끝난다`.
2. **앱 종료(Ctrl+C·서버 재시작) 중 보유** → 종료 때 돌던 실행마다 정리 후 `끝`, 정리가 안 됐으면 다음 시작 때 「끝(재시작)」과 잔고 기록. → Task 7 `test_종료하면_돌던_실행을_정리한다`, `test_재시작하면_끝나지_않은_실행을_닫는다`.
3. **차트(분) 응답의 빠진 분·중복·순서 뒤섞임** → 이미 넣은 분은 다시 안 넣고, 시각순으로, 아직 안 끝난 분은 안 넣음. → Task 6 `test_1분봉은_새것만_시각순으로_넣는다`.
4. **현재가가 비었거나 0(장 시작 직후)** → 그 초는 건너뜀, 진입·청산 판단 안 함. → Task 6 `test_현재가가_0이면_판단하지_않는다`.
5. **시작 버튼 두 번(탭 두 개)** → 같은 종목 `orders` 실행은 하나만, 두 번째는 거부. 주말·15:31 이후 시작도 거부. → Task 7 `test_같은_종목_주문_실행은_하나만`, `test_주말이나_장_끝난_뒤엔_시작_거부`.

---

### Task 1: 전략 폴더 불러오기 (`loader.py`) + 시험용 week02 전략

**Files:**
- Create: `backend/team_pyrun/__init__.py`, `backend/team_pyrun/loader.py`
- Create: `tests/fixtures/team_pyrun/strategies/strategy.py`, `.../strategy_bb.py` (week02 원본 복사 + 아래 줄 추가), `.../backtest_dummy.py`(`STRATEGY` 없는 모듈), `.../broken.py`(문법 오류), `.../no_target.py`(약속 위반: `target` 없음)
- Test: `tests/test_team_pyrun_loader.py`

**Interfaces:**
- Produces:
  - `strategies_dir() -> Path` = `config.HOME_DIR / "strategies"` (없으면 만듦)
  - `@dataclass(frozen=True) StrategyFile(file: str, name: str|None, title: str|None, params: dict|None, error: str|None)`
  - `scan(folder: Path) -> list[StrategyFile]` — `*.py` 중 `STRATEGY` 가 있거나 불러오기에 실패한 것. `STRATEGY` 없는 정상 모듈은 빠짐. 파일 이름순.
  - `@dataclass(frozen=True) Loaded(file, name, title, sha256: str, strategy_cls: type, params_cls: type, tick: float, tick_value: float)` 와 `Loaded.new() -> object`(= `strategy_cls(params_cls())`)
  - `load(folder: Path, file: str) -> Loaded`, 실패는 `LoadError(str)`
  - `REQUIRED_PARAMS = ("session_start","session_end","entry_start","entry_end","flatten_at","hold_min")`, 전략 인스턴스 필수: `on_minute` `end_of_day` `on_entry` `on_exit` `day` `p` `target`. 모듈 필수: `STRATEGY` `TITLE` `NAME` `TICK` `TICK_VALUE`.

- [ ] **Step 1: 시험용 전략 파일 준비**
  week02 `strategy.py`·`strategy_bb.py` 를 그대로 복사하고 각 파일 끝에 추가:
  - `strategy_bb.py`: `STRATEGY = BBRSIReversion`, `TITLE = "볼린저 밴드 + RSI 평균회귀"`, `NAME = "bb"`
  - `strategy.py`: `VWAPReversion` 클래스에 `@property def target(self): return self.current_vwap`, 모듈 끝에 `STRATEGY = VWAPReversion`, `TITLE = "VWAP 밴드 평균회귀"`, `NAME = "vwap"`
  - 다른 줄은 바꾸지 않는다(「거의 고치지 않는다」의 증거).

- [ ] **Step 2: 실패하는 시험 작성** — `tests/test_team_pyrun_loader.py`
```python
FOLDER = Path(__file__).parent / "fixtures/team_pyrun/strategies"

def test_전략이_있는_파일만_목록에_선다():
    got = {f.file: f for f in scan(FOLDER)}
    assert set(got) == {"broken.py", "no_target.py", "strategy.py", "strategy_bb.py"}
    assert got["strategy_bb.py"].name == "bb" and got["strategy_bb.py"].error is None
    assert got["strategy_bb.py"].params["bar_min"] == 5
    assert got["strategy.py"].name == "vwap"
    assert "SyntaxError" in got["broken.py"].error
    assert "target" in got["no_target.py"].error

def test_공용_모듈을_불러_쓰는_전략도_불러온다():
    bb = load(FOLDER, "strategy_bb.py")
    assert (bb.tick, bb.tick_value, bb.name) == (0.1, 1000, "bb")
    s = bb.new()
    assert s.p.bar_min == 5 and s.target is None

def test_불러온_뒤_sys_modules_에_strategy_가_남지_않는다():
    before = sys.modules.get("strategy")
    load(FOLDER, "strategy_bb.py")
    assert sys.modules.get("strategy") is before

def test_두_번_불러도_서로_다른_모듈이다():
    a, b = load(FOLDER, "strategy_bb.py"), load(FOLDER, "strategy_bb.py")
    assert a.strategy_cls is not b.strategy_cls   # 파일이 바뀌어도 돌던 실행은 처음 것 그대로

def test_없는_파일은_LoadError():
    with pytest.raises(LoadError): load(FOLDER, "nope.py")
```

- [ ] **Step 3: 실패 확인** — `uv run pytest tests/test_team_pyrun_loader.py -q` → `ModuleNotFoundError: backend.team_pyrun`

- [ ] **Step 4: 구현** — 불러오기는 모듈 전역 `threading.Lock` 안에서:
  1) `sys.path` 와 「폴더 안 `*.py` 의 이름들」에 해당하는 `sys.modules` 항목을 저장하고 지운다, 2) 폴더를 `sys.path[0]` 에 넣는다,
  3) 대상 파일을 `importlib.util.spec_from_file_location(f"team_pyrun_{uuid4().hex}", path)` 로 실행, 4) `finally` 에서 `sys.path` 원복,
  `__file__` 이 폴더 안인 모듈을 `sys.modules` 에서 빼고 저장해 둔 항목을 되돌린다. 예외는 `f"{type(e).__name__}: {e}"` 로 `LoadError`.
  약속 검사는 위 Interfaces 목록대로, 빠진 이름을 메시지에 넣는다. `sha256` 은 파일 바이트.

- [ ] **Step 5: 통과 확인** — `uv run pytest tests/test_team_pyrun_loader.py -q` → 5 passed

- [ ] **Step 6: 커밋**
```bash
git add backend/team_pyrun tests/fixtures/team_pyrun tests/test_team_pyrun_loader.py
git commit -m "feat(team): 파이썬 전략 폴더 불러오기"
```

---

### Task 2: 기록 (`journal.py`)

**Files:**
- Create: `backend/team_pyrun/journal.py`
- Test: `tests/test_team_pyrun_journal.py`

**Interfaces:**
- Produces:
  - `scrub(obj: Any) -> Any` — Global Constraints 의 금지 칸 제거(중첩 dict/list, `occurs1_` 접두 꼴도)
  - `class Journal(path: Path)`: `write(kind: str, **data) -> dict`(한 줄 `{"kind","at": now_kst ISO 초, **scrub(data)}`, 바로 flush), `read(after: int = 0) -> list[dict]`(after 번째 줄 다음부터), `count() -> int`
  - `summarize(trades: list[dict]) -> dict` — week02 `backtest.summarize` 를 **그대로** 옮김(칸·반올림 같게)
  - `count_stops(folders: Iterable[Path], date: str) -> int` — 각 폴더 `journal.jsonl` 의 `kind=="trade"` 이고 `reason=="손절"` 이고 `exit_date==date` 인 줄 수. 파일 없음·깨진 줄은 무시.
  - `write_summary(folder: Path, data: dict) -> Path` — `summary.json`(indent=1, ensure_ascii=False)

- [ ] **Step 1: 실패하는 시험**
```python
def test_계좌_식별정보와_토큰은_쓰기_전에_지운다(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    j.write("event", raw={"occurs1_ac_no": "1", "ac_nm": "x", "ord_no": "7", "Occurs1": [{"occurs1_user_ip_addr": "ip"}]},
            authorization="Bearer t")
    text = (tmp_path / "journal.jsonl").read_text()
    for k in ("ac_no", "ac_nm", "user_ip_addr", "authorization", "Bearer"): assert k not in text
    assert '"ord_no": "7"' in text

def test_이어_읽기(tmp_path):
    j = Journal(tmp_path / "j.jsonl"); [j.write("event", text=str(i)) for i in range(3)]
    assert [r["text"] for r in j.read(after=1)] == ["1", "2"] and j.count() == 3

def test_요약은_week02_와_같은_칸():
    s = summarize([{"pnl": 21000, "reason": "익절", "exit_date": "20261030", "fee": 1380.0},
                   {"pnl": -5000, "reason": "손절", "exit_date": "20261030", "fee": 1380.0}])
    assert s == {"trades": 2, "wins": 1, "win_rate": 0.5, "net_pnl": 16000, "profit_factor": 4.2,
                 "avg_win": 21000, "avg_loss": -5000, "max_drawdown": 5000.0,
                 "by_reason": {"익절": 1, "손절": 1}, "by_day": {"20261030": 16000},
                 "fee_total": 2760.0, "net_pnl_after_fee": 13240.0}

def test_그날_손절_수는_여러_폴더를_합쳐_센다(tmp_path): ...  # 두 폴더에 손절 1·1, 다른 날 손절 1 → 2
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_team_pyrun_journal.py -q` → ImportError
- [ ] **Step 3: 구현** (`now_kst().isoformat(timespec="seconds")` 에서 시간대 꼬리 `+09:00` 는 떼어 week02 꼴 `2026-10-30T09:24:33` 로)
- [ ] **Step 4: 통과 확인** — 4 passed
- [ ] **Step 5: 커밋** `git commit -m "feat(team): 실행 기록 jsonl·요약"`

---

### Task 3: 실행기 핵심 + 종이 체결 + 리플레이 (`runner.py`)

week02 `runner.py` 의 `Runner`·`PaperBroker`·`replay()` 를 전략에 묶이지 않게 옮긴다.

**Files:**
- Create: `backend/team_pyrun/runner.py`, `backend/team_pyrun/replay.py`
- Create: `tests/fixtures/team_pyrun/bars_1m_A756B000_20261030.csv` (week02 `results/data/` 의 같은 파일)
- Test: `tests/test_team_pyrun_runner.py`

**Interfaces:**
- Consumes: `Loaded` (Task 1), `Journal`·`summarize` (Task 2)
- Produces (`runner.py`):
  - `@dataclass(frozen=True) Minute(date, time, open, high, low, close, volume)`; `minute_of(row: dict) -> Minute` (접두 뗀 차트 줄: `ref_dt` `exch_tm` `open_pric` `high_pric` `low_pric` `close_pric` `cum_trd_qty`)
  - `stop_price(side, entry, stop_ticks, tick)`, `take_profit_price(side, target, tick)`, `pnl_ticks(side, entry, exit_, tick) -> int` — week02 `strategy.py` 의 같은 이름 함수를 `tick` 인자로
  - `class Broker(Protocol)`: `mode: str`, `last_fill_fee: float|None`, `fill(side, ref_price, clock, why) -> float|None`, `position() -> int|None`, `account(clock="", why="") -> dict|None`
  - `class PaperBroker(journal, tick, fee=690.0)` — `mode="paper"`, 체결가 = 기준가 ∓ `tick`(불리한 쪽), `fill` 줄 `source="paper"`, `text="종이 체결 · …"`
  - `class Runner(strategy, journal, broker, tick, tick_value)`:
    `feed(m)`, `warmup(minutes)`, `on_minute_closed(m)`, `on_price(clock, price, ref_low=None, ref_high=None)`, `force_flat(clock)`,
    `expected_position() -> int`(0 / +1 / −1), `halt(reason: str)`, 속성 `pos` `pending` `trades` `live_date` `last_price` `halted: str|None` `last_signal: dict|None`,
    `snapshot() -> dict`(`position` `entry` `stop` `stop_ticks` `target` `time_exit_at` `today_pnl` `stops` `max_stops` `halted` `last_signal`)
- Produces (`replay.py`): `replay(loaded: Loaded, date: str, minutes: list[Minute], folder: Path) -> dict` — week02 `replay()` 와 같은 순서(그 분 시가로 `on_price` → 종가+고저로 `on_price` → `on_minute_closed`), 끝에 `force_flat("153000")`, `summary.json` 기록. `load_minutes(csv: Path) -> list[Minute]` (week02 `backtest.load_minutes`, 하루 250봉 미만 날 제외).
  - `python -m backend.team_pyrun.replay <전략파일> <YYYYMMDD> <csv>` → `storage.state_dir()/pyruns/<날짜>_<NAME>_replay/` 에 기록(화면 확인·과제 비교용)

week02 와 다른 점(그 외엔 같게):
- 익절 목표는 `strategy.target`, 틱은 `Loaded.tick`/`tick_value`.
- `signal` 줄은 **판정 봉마다 전부**(조건 `if s.side or "신호" in s.reason` 없앰). 지표 칸은 `asdict(bar)` 중 `date start end open high low close volume` 을 뺀 숫자 칸 전부(반올림 3자리, None 제외). `last_signal` 에 같은 dict.
- `trade` 줄에 `reason` 칸 추가(손절 수 세기용).
- `halted` 가 있으면 `on_price` 는 진입·청산 모두 안 함. `_exit` 에서 체결 실패 뒤 잔고가 0 이면 week02 처럼 기록, `== expected_position()` 이면 10초 뒤 재시도, 그 외(남의 주문이 섞임)나 `None` 이면 `halt("잔고 불일치 · 기대 {e:+d} · 계좌 {h}")`. `_enter` 에서 체결 실패 뒤 잔고 `None` 이면 `halt`.

- [ ] **Step 1: 실패하는 시험 — week02 리플레이와 같은 거래**
```python
DATA = Path(__file__).parent / "fixtures/team_pyrun/bars_1m_A756B000_20261030.csv"

def _trades(file, tmp_path):
    r = replay(load(FOLDER, file), "20261030", load_minutes(DATA), tmp_path)
    return [(t["side"], t["entry"], t["exit"], t["reason"], t["entry_time"], t["exit_time"]) for t in r["trades"]], r

def test_볼린저_리플레이는_week02_와_같다(tmp_path):
    got, r = _trades("strategy_bb.py", tmp_path)
    assert got == [("sell", 1339.6, 1337.7, "익절", "093500", "101700"),
                   ("buy", 1334.9, 1336.7, "익절", "121000", "124000"),
                   ("buy", 1334.1, 1335.8, "익절", "142500", "144400")]
    assert r["summary"]["net_pnl"] == 54000

def test_VWAP_리플레이는_week02_와_같다(tmp_path):
    got, r = _trades("strategy.py", tmp_path)
    assert [g[3] for g in got] == ["익절", "익절", "익절", "손절", "손절"] and r["summary"]["net_pnl"] == -21000

def test_판정_봉마다_signal_줄이_선다(tmp_path):
    _trades("strategy_bb.py", tmp_path)
    sig = [x for x in Journal(tmp_path / "journal.jsonl").read() if x["kind"] == "signal" and x["date"] == "20261030"]
    assert len(sig) == 79                       # 5분봉 09:00, 09:05 … 15:30 시작
    assert {"upper", "middle", "lower", "rsi", "atr"} <= set(sig[-1])

def test_멈춘_실행은_청산도_진입도_안_한다(): ...   # halted 뒤 손절가를 지나도 fill 호출 0회 (가짜 broker)
def test_청산_뒤_잔고가_기대와_다르면_다시_청산하지_않고_멈춘다(): ...  # fill→None, position→+2 (기대 +1) → halted, 재시도 없음
```
  기준값은 week02 저장소 `results/runs/20261030_bb_replay/summary.json`·`20261030_vwap_replay/summary.json`. **처음에 맞지 않으면** week02 `runner.py --replay 20261030 --data <같은 csv>` 를 직접 돌려 기준값부터 확인하고(그 실행이 다른 csv 를 썼을 수 있음), 확인한 값으로 시험을 고친다. `78` 도 같은 방법으로 확인.

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_team_pyrun_runner.py -q` → ImportError
- [ ] **Step 3: 구현** — week02 `Runner` 본문을 옮기고 위 「다른 점」만 바꾼다.
- [ ] **Step 4: 통과 확인** — 5 passed
- [ ] **Step 5: 커밋** `git commit -m "feat(team): week02 실행기를 옮긴 파이썬 전략 실행기·리플레이"`

---

### Task 4: API 로그 갈고리 (`nh_api/client.py` + `apilog.py`)

**Files:**
- Modify: `backend/nh_api/client.py` — `TradeClient.call()` (124~218행 근처)
- Create: `backend/team_pyrun/apilog.py`
- Test: `tests/test_team_pyrun_apilog.py`

**Interfaces:**
- Produces (`client.py`, `# 팀:`): 모듈 전역 `call_observer: Callable[[dict], None] | None = None`. `call()` 이 호출마다(성공·예외 모두) 한 번 부른다. 넘기는 dict:
  `{"api_id","env","request","http","body","ms","waited_ms","reissued": bool,"error": None|"<예외 클래스>: <message>","code","message"}`
  (`waited_ms` = `self._limiter.wait(...)` 반환값×1000, `code/message` = `error_codes.failure_of(body)` 또는 예외의 `code`/`detail`). 관찰자 안의 예외는 삼키고 `logger.exception` 만 — 호출 결과를 바꾸지 않는다.
- Produces (`apilog.py`):
  - `bind(run_log: "ApiLog")` / `purpose(name: str)` — `contextvars` 컨텍스트 매니저. 바인딩이 없으면 아무것도 안 남김.
  - `class ApiLog(path: Path, run_id: str)`: `record(call: dict) -> None` (스레드 안전), `stats() -> dict`
  - `FULL_BODY_APIS = {"domestic_order","domestic_order-history","domestic_open-interest","domestic_deposit","domestic_product-detail","domestic_price-all-futures"}`. 그 외 성공 호출은 `body` 대신 `summary`: 현재가 `{"last_pric": …}`, 차트 `{"rows": n, "first": "<ref_dt exch_tm>", "last": "…"}`.
  - 한 줄 칸: `at run purpose api_id env request http code message ms waited_ms reissued ok error` + `body` 또는 `summary`. `scrub` 적용.
  - `stats()` → `{"calls": {api_id: n}, "failures": {api_id: n}, "codes": {code: n}, "ms_avg": {api_id: x}, "ms_max": {api_id: x}, "waited_ms_total": x, "reissued": n}`
  - 앱 시작 때 `client.call_observer = apilog.observe` 로 꽂는다(Task 8 `main.py`). `observe(call)` 은 현재 바인딩의 `ApiLog.record` 로 넘김.

- [ ] **Step 1: 실패하는 시험** — `tests/test_trade_client.py` 의 `만들기`·`서버` 방식(MockTransport) 그대로
```python
def test_실행이_부른_호출만_남는다(config, tmp_path, monkeypatch):
    monkeypatch.setattr(client_module, "call_observer", apilog.observe)
    api, _ = 만들기(config, {"/trade/v1/domestic/price": httpx.Response(200, json={"last_pric": "1338.50"})})
    log = ApiLog(tmp_path / "api_log.jsonl", "r1")
    api.call("domestic_price", {"sym": "A756B000"})                 # 바인딩 없음 → 안 남음
    with apilog.bind(log), apilog.purpose("현재가"):
        api.call("domestic_price", {"sym": "A756B000"})
    rows = [json.loads(l) for l in (tmp_path / "api_log.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["purpose"] == "현재가" and rows[0]["summary"] == {"last_pric": "1338.50"}
    assert "body" not in rows[0] and rows[0]["ok"] is True

def test_실패와_토큰_재발급과_대기가_남는다(...): ...   # 첫 응답 401 → reissued True; BusinessError → ok False, code, body 전체
def test_응답을_못_받은_호출도_남는다(...): ...          # httpx.ConnectTimeout → error "TransportError: …", http None
def test_관찰자가_터져도_호출은_그대로다(...): ...        # observer 가 raise → call() 결과 정상
def test_통계(tmp_path): ...                            # record 세 번 → calls/failures/codes/ms_avg/ms_max
```
- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_team_pyrun_apilog.py -q` → FAIL
- [ ] **Step 3: 구현** — `call()` 본문을 `try/except/finally` 로 감싸 시작 시각(`time.perf_counter`)·대기·재발급 여부·마지막 `response`/예외를 모아 `finally` 에서 관찰자에 넘김. 기존 동작·예외 종류는 그대로.
- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_team_pyrun_apilog.py tests/test_trade_client.py -q` → 전부 통과
- [ ] **Step 5: 커밋** `git commit -m "feat(team): TradeClient 호출 관찰 갈고리와 실행별 API 로그"`

---

### Task 5: 팀 API 계층 (`api.py`)

week02 `nh_client.py` 의 요청 값·해석을 운영자 `runtime.client().call()` 위로 옮긴다.

**Files:**
- Create: `backend/team_pyrun/api.py`
- Test: `tests/test_team_pyrun_api.py`

**Interfaces:**
- Produces (모두 `client: TradeClient | None = None` 키워드, 기본 `runtime.client()`, `environment="paper"`):
  - `rows(body) -> list[dict]`(week02 `rows`, `occurs1_` 떼기), `num(v) -> float|None`
  - `chart_minute(sym, *, req_qty: int) -> list[dict]` — payload 정확히 `{"nght_tp":"1","sym":sym,"inq_strt_dt":"00000000","strt_tm":"000000","inq_ed_dt":"99999999","ed_tm":"235959","req_qty":str(req_qty),"dcnt":"1","cidx_yn":"0","nxt_key":"99999999","fut_cidx_exp_mod":"0"}`
  - `price(sym) -> dict`(본문 그대로, `last_pric`), `all_futures(prd="75") -> list[dict]`, `product_detail() -> list[dict]`, `deposit(biz_dt) -> dict`, `open_interest() -> list[dict]`(`{"nxt_key": ""}`),
    `order_history() -> list[dict]`(`{"trd_div":"0","exec_div":"0","trd_tm_div_cd":"1","ord_div_cd":"0","nxt_key":""}`)
  - `market_order(sym, side: "buy"|"sell", qty=1, exec_cnd="1") -> dict` — `{"sym","trd_div": {"buy":"1","sell":"2"}[side],"ord_tp_cd":"2","ord_qty","ord_pric":"0","exec_cnd_cd"}`. **재시도 없음.**
  - 조회 함수는 `TransportError` 또는 `error_codes.kind_of(code) == RETRY` 면 1초·2초 쉬고 최대 3회. 주문은 한 번.
  - `nearest_usd(rows) -> str` — `sym_exch` 가 `A75` 로 시작하고 `sym_nm` 에 「플렉스」 없는 것 중 `exp_mon` 최소의 `sym_exch`
  - `usd_spec(rows) -> tuple[float, float]` — `dtl_cd_ko_nm == "미국달러선물(USD)"` 줄의 (`cd_val_inf_1`, `tick_val`)
  - `net_position(rows, sym) -> int` — `sym` 같은 줄의 `opint_qty`, `trd_div=="1"` 이면 +, 아니면 −

- [ ] **Step 1: 실패하는 시험** — 응답 본문은 `tests/fixtures/nh/<api_id>/` 기록을 읽어 MockTransport 로 돌려준다.
```python
def test_요청_값은_week02_와_같다(config): ...   # 각 함수 호출 후 서버가 받은 json == 위 payload
def test_차트_줄은_접두를_뗀다(config):
    got = chart_minute("A756B000", req_qty=10, client=api)
    assert {"ref_dt", "exch_tm", "close_pric"} <= set(got[0])
def test_주문은_응답이_없어도_다시_보내지_않는다(config): ...   # ConnectTimeout → TransportError, 서버 횟수 1
def test_조회는_호출_제한이면_다시_묻는다(config, monkeypatch): ...  # 첫 응답 EGW036 → 두 번째 성공, sleep 패치
def test_최근월물과_틱(): ...   # fixtures 의 price-all-futures(prd 75 기록이 없으면 손으로 만든 줄)·product-detail
def test_순보유(): assert net_position([{"sym":"A","opint_qty":"2","trd_div":"1"},{"sym":"A","opint_qty":"1","trd_div":"2"}], "A") == 1
```
  필드명이 기록과 다르면(예: `opint_qty`) 기록을 따르고 시험을 고친다 — 원칙 6. `domestic_open-interest` 공개 기록은 빈 응답뿐이므로 줄 모양은 week02 코드 기준.
- [ ] **Step 2: 실패 확인** → ImportError
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: 커밋** `git commit -m "feat(team): 팀 API 계층 — 차트·현재가·주문·주문내역·잔고·예수금"`

---

### Task 6: 모의 계좌 체결 + 장중 실행 (`broker.py`, `live.py`)

**Files:**
- Create: `backend/team_pyrun/broker.py`, `backend/team_pyrun/live.py`
- Test: `tests/test_team_pyrun_live.py`

**Interfaces:**
- Consumes: `api` (Task 5), `Runner`·`PaperBroker`·`minute_of` (Task 3), `Journal` (Task 2), `ApiLog`·`bind`·`purpose` (Task 4), `Loaded` (Task 1)
- Produces (`broker.py`): `class MockAccountBroker(api_module, sym, journal, exec_cnd="1", sleep=time.sleep)` — week02 `MockAccountBroker` 그대로(`mode="mock-account"`, 체결 확인 `ord_sts=="6"` 이면 `avg_exec_pric` 없으면 `exec_pric`, `"8"/"9"` 거부, 0.5초×30회, 수수료 = 예수금 `fee` 차이). 추가: 주문에서 `TransportError`/`GatewayError` → `order` 줄 `ok=False, unknown=True`, `None` 반환(재전송 없음). `position()` 은 `api.net_position(api.open_interest(), sym)`, 실패면 `None`.
- Produces (`live.py`):
  - `@dataclass RunSpec(file: str, mode: Literal["orders","paper"], sym: str|None)`
  - `class StartRefused(Exception)`
  - `class LiveRun(run_id: str, folder: Path, loaded: Loaded, spec: RunSpec, *, api_module=api, now=now_kst, sleep=time.sleep, stops_before: int = 0)`:
    `prepare() -> None`(시작 검사·준비 봉, 실패는 `StartRefused`), `step(now: datetime) -> None`(1초 한 번), `run_forever() -> None`(스레드 본문),
    `request_stop()`, `request_flatten()`, `finish(reason: str) -> None`, `status() -> dict`, 속성 `state` `sym` `started_at` `ended_at` `ended_reason`
  - 상태 파일 `folder/run.json` = `{"id","file","name","title","mode","sym","state","started_at","ended_at","ended_reason","sha256"}` — 상태가 바뀔 때마다 씀.

  `prepare()` 순서(week02 `live()` 와 같게, 다른 점 굵게):
  1. `event` 「서버 paper · 주문 {모의계좌|종이}」, **`event` 「전략 {file} · sha256 {앞 12자} · Params {…}」**
  2. 종목: `spec.sym` 또는 `nearest_usd(all_futures())`. 틱: `usd_spec(product_detail())` 이 `(loaded.tick, loaded.tick_value)` 와 다르면 `StartRefused("틱·틱가치가 전략 가정과 다릅니다 …")`
  3. `orders`: `position()` 이 `None` → `StartRefused("시작 잔고를 확인하지 못했습니다")`, **0 이 아니면 `StartRefused("{sym} 잔고 {n:+d}계약이 남아 있습니다 — 정리한 뒤 시작하세요")`**, 예수금 `account` 줄
  4. 준비 봉: `chart_minute(sym, req_qty=1500)` 중 `(date,time) < (오늘, 지금 분)` 만, 시각순 → `warmup`. `live_date = 오늘`. `strategy.day.stops = stops_before`(0 이 아니면 `event`)

  `step(now)`:
  - `now ≥ END_TIME` 또는 stop 요청 → `finish(...)`
  - `now < session_start` → `state="대기"` 만
  - 분이 바뀌고 `now.second ≥ 3` → `purpose("1분봉")` 로 `chart_minute(sym, req_qty=10)` → 마지막 넣은 `(date,time)` 보다 뒤이고 지금 분보다 앞인 것만 시각순 `on_minute_closed`
  - `purpose("현재가")` 로 `price(sym)` → `num(last_pric)` 가 0·None 이면 건너뜀, 아니면 `on_price(clock, px)`
  - flatten 요청 → `force_flat` 후 계속
  - `orders` 이고 보유 중이고 마지막 대조 뒤 30초 → `purpose("잔고확인")` 로 `position()`; `None` 이 아니고 `!= expected_position()` 이면 `halt(...)`, `state="확인 필요"`, `event`
  - 조회 예외는 `event`(「… 처리 실패 — 다음 초에 다시」)만 남기고 계속. **전략 코드 예외(`on_minute`·`target` 등)는 `finish("오류: …")`**
  - 진입·청산·체결확인·예수금 호출은 각각 `purpose("진입"|"청산"|"체결확인"|"예수금")` 아래에서.
  `finish(reason)`: `halted` 가 아니면 `force_flat`, `orders` 면 끝 잔고·예수금 기록, `write_summary(folder, {"sym","trades","summary","account_start","account_end","api": self.apilog.stats(),"strategy": {"file","name","title","sha256","params"}})`, `state = "오류"` if reason 이 「오류」로 시작 else `"끝"`. 두 번 불려도 한 번만.
  `self.apilog = ApiLog(folder/"api_log.jsonl", run_id)` 를 생성자에서 만들고, `prepare()`·`step()`·`finish()` 는 모두 `with bind(self.apilog):` 안에서 호출을 낸다(준비 단계 호출도 로그에 남도록 — `prepare` 는 Registry 스레드, 나머지는 실행 스레드에서 돈다).
  `run_forever()`: 1초마다 `step(now())`, `finally: finish("중지")` (이미 끝났으면 무시).

- [ ] **Step 1: 실패하는 시험** — 가짜 `api_module`(함수 이름은 Task 5 와 같고, 정해 둔 줄을 돌려주고 받은 주문을 적는 객체)과 손으로 넣는 `now`.
```python
def test_시작_잔고가_있으면_거부한다(tmp_path): ...            # open_interest → +1 → StartRefused, 주문 0회
def test_틱이_다르면_거부한다(tmp_path): ...
def test_장_전엔_기다리고_장중엔_분봉과_현재가를_넣는다(tmp_path): ...  # 08:59:30 → state 대기, chart 호출 0 / 09:01:04 → chart 1·price 1
def test_1분봉은_새것만_시각순으로_넣는다(tmp_path): ...        # 응답 [0902,0900,0901,0901,0903(지금 분)] → 0900,0901,0902 한 번씩
def test_현재가가_0이면_판단하지_않는다(tmp_path): ...
def test_신호가_나면_모의_주문을_내고_체결을_확인한다(tmp_path): ... # order_history ord_sts "6" → fill 줄 source order-history, pos 생김
def test_주문_응답이_없으면_다시_보내지_않는다(tmp_path): ...      # market_order raise TransportError, position +1 → 현재가로 보유 기록, 주문 1회
def test_보유_중_잔고가_어긋나면_확인_필요로_멈춘다(tmp_path): ... # 30초 뒤 position +2 → state 확인 필요, 이후 손절가 지나도 주문 0
def test_전략_예외면_정리하고_오류로_끝난다(tmp_path): ...        # on_minute raise → 보유 청산 주문 1회, state 오류, summary.json 있음
def test_끝나면_요약에_API_통계와_전략이_들어간다(tmp_path): ...
```
- [ ] **Step 2: 실패 확인** → ImportError
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_team_pyrun_live.py -q`
- [ ] **Step 5: 커밋** `git commit -m "feat(team): 모의 계좌 체결과 장중 실행 루프"`

---

### Task 7: 실행 관리 (`registry.py`)

**Files:**
- Create: `backend/team_pyrun/registry.py`
- Test: `tests/test_team_pyrun_registry.py`

**Interfaces:**
- Consumes: `LiveRun`·`RunSpec`·`StartRefused` (Task 6), `load`·`strategies_dir` (Task 1), `count_stops` (Task 2)
- Produces:
  - `class Registry(root: Path, strategies: Path, *, now=now_kst, active_env=runtime.active_environment, start_thread=True)`
    - `start(spec: RunSpec) -> dict`(그 실행 `status()`) — 거부(`StartRefused`): 토·일, `now ≥ END_TIME`, `orders` 인데 `active_env() != "paper"`(「모의투자 환경에서만 모의 계좌 실행을 세울 수 있습니다」), 같은 `sym` 의 `orders` 실행이 `대기/진행 중/확인 필요` 로 이미 있음. 폴더 이름 규칙(Global Constraints, 이미 있으면 `_2` …), `stops_before = count_stops(같은 날·같은 NAME·같은 종목 폴더들, 오늘)`. `prepare()` 를 부른 스레드에서 끝낸 뒤 데몬 스레드로 `run_forever`. 동시 `start` 는 `threading.Lock` 으로 줄 세움.
    - `list() -> list[dict]` — 도는 것 + `root` 아래 폴더의 `run.json`(최근 시작순)
    - `get(run_id) -> LiveRun | None`, `folder(run_id) -> Path`(없으면 `KeyError`; `run_id` 는 `^[0-9A-Za-z_]+$` 만)
    - `stop(run_id)`, `flatten(run_id)`, `stop_all(timeout: float = 20.0)`(앱 종료)
    - `recover()` — 앱 시작 때: `run.json` 이 `끝/오류` 가 아닌 폴더마다 `orders` 면 잔고 한 번 조회해 `event`, `state="끝"`, `ended_reason="재시작"`, `summary.json` 이 없으면 `journal` 의 `trade` 줄로 만든다
  - `registry() -> Registry` — 모듈 싱글턴(`storage.state_dir()/"pyruns"`, `strategies_dir()`)

- [ ] **Step 1: 실패하는 시험** (`start_thread=False`, 가짜 api)
```python
def test_같은_종목_주문_실행은_하나만(tmp_path): ...
def test_종이_실행은_여러_개_세울_수_있고_폴더가_따로다(tmp_path):   # 20261103_bb_paper, 20261103_bb_paper_2
def test_주말이나_장_끝난_뒤엔_시작_거부(tmp_path): ...             # 토 10:00, 평일 15:31
def test_모의_환경이_아니면_주문_실행_거부(tmp_path): ...           # active_env "real"
def test_그날_앞선_실행의_손절을_이어받는다(tmp_path): ...
def test_종료하면_돌던_실행을_정리한다(tmp_path): ...               # 보유 중 stop_all → 청산 주문 1회, state 끝
def test_재시작하면_끝나지_않은_실행을_닫는다(tmp_path): ...         # run.json state 진행 중 → recover() → 끝·재시작, summary 생김
def test_실행_id_로_폴더_밖을_가리킬_수_없다(tmp_path): ...          # "../x" → KeyError
```
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: 커밋** `git commit -m "feat(team): 파이썬 전략 실행 관리 — 시작 거부 규칙·재시작 정리"`

---

### Task 8: 라우트 + 앱 연결 (`routes.py`, `main.py`)

**Files:**
- Create: `backend/team_pyrun/routes.py`
- Modify: `backend/main.py` — `include_router`(190~197행 옆), `lifespan`(86행~): 시작 때 `client.call_observer = apilog.observe` 와 `registry().recover()`, 끝날 때 `registry().stop_all()` — 모두 `# 팀:`
- Test: `tests/test_team_pyrun_routes.py`

**Interfaces:**
- Consumes: `registry()` (Task 7), `scan`·`strategies_dir` (Task 1), `Journal` (Task 2)
- Produces — `APIRouter(prefix="/api/team/pyrun")`:
  - `GET /strategies` → `{"folder": str, "strategies": [StrategyFile…]}`; `POST /strategies/reload` → 같은 것
  - `GET /runs` → `{"runs": [status…]}`; `POST /runs` body `{"file","mode","sym"?}` → 201 `status` / 거부 409 `{"detail": 거부 문장}`
  - `GET /runs/{id}` → `status()`(끝난 실행은 `run.json` + `summary.json` 의 `summary`)
  - `GET /runs/{id}/journal?after=0` → `{"rows": […], "next": n}`; `GET /runs/{id}/api-log?after=0` 같은 꼴
  - `GET /runs/{id}/bars` → `{"bars": [signal 줄에서: date start open high low close + 지표 칸], "marks": [fill·trade 에서: time side price kind]}`
  - `POST /runs/{id}/stop`, `POST /runs/{id}/flatten` → 204
  - `GET /runs/{id}/download` → `application/zip`, 파일명 `<id>.zip`(진행 중이면 `<id>_partial.zip`), 안에 `<id>/journal.jsonl`, `<id>/summary.json`(있으면), `<id>/api_log.jsonl`
  - 없는 id 404. `status()` 칸(화면이 씀): `id file name title mode sym state started_at ended_at ended_reason bar_min next_decision_at position entry stop stop_ticks target time_exit_at today_pnl stops max_stops halted last_signal params`

- [ ] **Step 1: 실패하는 시험** — `fastapi.testclient.TestClient(app)`, `registry` 를 `tmp_path` 로 바꾼 싱글턴으로 패치, Task 3 리플레이로 만든 끝난 실행 폴더를 깔고:
```python
def test_전략_목록(client): ...
def test_끝난_실행을_zip_으로_받는다(client):
    r = client.get("/api/team/pyrun/runs/20261030_bb_replay/download")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(z.namelist()) >= {"20261030_bb_replay/journal.jsonl", "20261030_bb_replay/summary.json"}
def test_차트용_봉과_표시(client): ...
def test_이어_읽기(client): ...
def test_시작_거부는_409(client): ...
def test_없는_실행은_404(client): ...
```
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인 + 전체** — `uv run pytest -q` → 기존 3150 + 새 시험 전부 통과, `uv run ruff check .` 깨끗
- [ ] **Step 5: 커밋** `git commit -m "feat(team): 파이썬 전략 라우트와 앱 연결"`

---

### Task 9: 화면 — 전략주문 › 「파이썬 전략」

시안(대화 중 보여 준 것: 왼쪽 250px ①전략 파일 ②실행 목록, 오른쪽 ③머리줄·상태 막대 ④차트 ⑤지금 판단 ⑥아래 표)을 기존 「전략 진행」 클래스·토큰으로 그린다. 새 CSS 는 `pyrun.css` 에, 색·간격은 기존 변수만.

**Files:**
- Create: `frontend/src/data/pyrun.ts`, `frontend/src/screens/team/PyRunScreen.tsx`, `PyRunSide.tsx`, `PyRunMain.tsx`, `PyRunChart.tsx`, `pyrun.css`
- Modify: `frontend/src/data/strategyStore.ts:43` `STRATEGY_TABS` 끝에 `'파이썬 전략'`(`// 팀:`), `frontend/src/screens/strategy/StrategyScreen.tsx:253` 분기에 `tab === '파이썬 전략' ? <PyRunScreen />`(`{/* 팀: */}`)

**Interfaces:**
- Consumes: Task 8 라우트
- Produces (`pyrun.ts`): 타입 `PyStrategyFile` `PyRunStatus` `PyJournalRow` `PyBars`, 함수 `loadStrategies()` `reloadStrategies()` `loadRuns()` `startRun(file, mode, sym?)` `loadRun(id)` `loadJournal(id, after)` `loadApiLog(id, after)` `loadBars(id)` `stopRun(id)` `flattenRun(id)` `downloadUrl(id) => \`/api/team/pyrun/runs/${id}/download\``, 훅 `usePyRun(id)`(2초 폴링, 화면을 떠나면 멈춤)

화면 규칙:
- 실행 목록 배지: `orders` → 「모의 계좌」, `paper` → 「종이」, 상태 낱말 그대로. 끝난 줄에 「⬇ 결과」(`<a href={downloadUrl(id)} download>`).
- 「+ 실행 세우기」 폼: 전략 파일(오류 있는 파일은 고를 수 없음)·모드·종목(빈칸 = 최근월물). `orders` 는 확인창 — 「모의 계좌로 실제 주문이 나갑니다. 실행 중엔 이 종목을 다른 곳(일반주문·조건식 전략)에서 주문하지 마세요.」 거부(409)는 그 문장을 그대로 띄움.
- 상태 막대: 보유(방향·수량·평균가) · 손절가(틱) · 익절 목표 · 시간 청산 · 오늘 손익 · 오늘 손절/한도. `확인 필요` 면 막대 위에 `halted` 문장과 「중지」만 활성.
- 차트: 판정 봉 캔들 + `upper/middle/lower`·`vwap` 가격 위 선, `rsi` 아래 창, 진입 ▲▼·청산 ●, 보유 중 손절가 점선. 기존 차트 컴포넌트를 쓸지는 구현자 판단(`frontend/src/screens/trade/ChartView.tsx` 참고).
- 아래 탭: 신호 / 주문·체결 / 거래 / 이벤트 / API 로그. 종이 실행의 체결은 「종이 체결」.

- [ ] **Step 1: `pyrun.ts` 와 화면 작성**
- [ ] **Step 2: 검사** — `cd frontend && npm run typecheck && npm run lint` → 오류 0
- [ ] **Step 3: 실제 화면 확인** — `uv run python -m backend.team_pyrun.replay strategy_bb.py 20261030 tests/fixtures/team_pyrun/bars_1m_A756B000_20261030.csv` 로 끝난 실행 하나를 만들고(전략 폴더에 시험용 파일 복사), `just dev` → http://localhost:5173 › 전략주문 › 파이썬 전략에서: 실행 목록에 `20261030_bb_replay`, 차트에 밴드·RSI·진입 3번·청산 3번, 10/30 신호 79줄, 「⬇ 결과」로 zip 이 받아짐. 화면 캡처를 남긴다.
- [ ] **Step 4: 커밋** `git commit -m "feat(team): 전략주문 › 파이썬 전략 화면"`

---

### Task 10: 마무리 — 문서와 전체 검사

**Files:**
- Modify: `claude.md`(개인 파일, 커밋 안 됨) — 「현재 구조」에 `backend/team_pyrun/` 표, 명령에 `uv run pytest tests/test_team_pyrun_*.py`·리플레이 명령, 「다음 작업」에서 이 일 지움
- Modify: `docs/superpowers/specs/2026-11-02-python-strategy-runner-design.md` 상태 줄 → 「구현됨」
- Create: `~/NHFutures/strategies/README.txt` 는 만들지 않는다(YAGNI) — 대신 화면 ① 안내 문구가 약속(`STRATEGY` `TITLE` `NAME`, `target`)을 한 줄로 말한다

- [ ] **Step 1: 전체 검사** — `uv run pytest -q && uv run ruff check . && (cd frontend && npm run typecheck && npm run lint)` → 모두 통과
- [ ] **Step 2: 개인정보 검사** — `grep -rE "ac_no|ac_nm|user_ip_addr|access_token" ~/NHFutures/state/pyruns/*/` 결과 없음(Task 9 에서 만든 폴더)
- [ ] **Step 3: 커밋** `git commit -m "docs(team): 파이썬 전략 자동매매 구현 반영"`
