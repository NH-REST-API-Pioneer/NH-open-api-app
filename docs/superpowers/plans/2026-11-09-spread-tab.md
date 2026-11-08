# 스프레드 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팀이 올린 실행기 파일(`LEGS` + `run(ctx)`)을 앱이 「중지」까지 날을 넘겨 돌리고, 주문·시세·잔고는 앱 창구 `ctx` 로만 쓰게 하며, 「스프레드」 탭에서 기록·대시보드를 보인다.

**Architecture:** 새 팀 패키지 `backend/team_spread/` 가 실행기 파일을 불러와(파이썬 전략 탭의 불러오기 격리 재사용) 실행마다 스레드에서 `run(ctx)` 를 부른다. `ctx` 는 시세 공급(`Feed`: 장중 = NH 차트·현재가 조회, 재생 = csv)과 주문 장부(`Book`: 종이 / 모의 계좌 = 다리마다 `MockAccountBroker`)를 감싸고, 한도·멈춤·장 쉼·짝 규칙을 건다. 다리 종목 정보는 종목 마스터 + 품목 세부정보에서 찾는다.

**Tech Stack:** Python 3.13 · FastAPI · pytest · React + TypeScript(Vite) · 기존 `backend/team_pyrun/`(broker·markets·journal·apilog·loader·strategy_files·registry 패턴) · 운영자 `backend/master/`·`backend/sessions/`

**Spec:** `docs/superpowers/specs/2026-11-08-spread-tab-design.md` (2판, 2026-11-09). 실행하는 사람은 계획과 설계 문서를 **둘 다** 읽는다.

## Global Constraints

- 모든 NH 호출은 `backend.nh_api.runtime.client().call` 을 거치는 팀 API(`backend/team_pyrun/api.py` 함수, 새 함수도 같은 파일 또는 `team_spread/api.py`)로, **모의(`paper`) 환경에서만** 주문한다.
- **주문은 재전송하지 않는다.** 결과를 모르면 그 실행의 모든 주문을 막고 「확인 필요」(CLAUDE.md 원칙 3).
- 실행기 파일에서 주문·시세·잔고는 `ctx` 로만 — 앱에 없는 모듈을 import 하면 불러오기 오류(파이썬 전략 탭의 「판단 부분만 골라 쓰기」를 쓰지 않는다).
- 운영자 파일을 고치면 고친 줄마다 `# 팀:` 주석. 팀 코드는 `backend/team_spread/` 와 `frontend/src/screens/team/spread/`.
- 라우트는 `/api/team/spread/...`, 쓰는 요청은 파이썬 전략 라우트의 다른 사이트 검사(`refuse_cross_site`)·`require_json` 을 그대로 건다.
- 기록에 계좌·키·토큰을 남기지 않는다(`team_pyrun.journal.scrub`, 해외 `mask_unlisted`·`OVS_LOG_FIELDS`).
- **파이썬 전략 탭 동작 불변** — 공유 코드를 고친 뒤에도 `uv run pytest -q` 전체(지금 3857 통과 · 2 건너뜀)가 통과해야 한다.
- 다리별 최대 보유 기본 **5계약**(실행기 `MAX_QTY` 가 있으면 그 값), 분당 주문 **10건**. 「중지」 뒤 실행기를 기다리는 시간 **30초**. 잔고 대조 주기 **30초**.
- 중지 정리 중 거부된 다리는 **10초 뒤 3번까지** 다시, 그 뒤 멈춤.
- 실행기 폴더 `~/NHFutures/spreads/`(= `config.HOME_DIR / "spreads"`), 기록 `storage.state_dir() / "spreads" / <id>/`.
- 문서·주석·화면 글은 한국어(저장소 말투). 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **`ctx.target` 중 두 번째 다리 결과 모름** — 첫 다리는 체결, 둘째는 응답 없음: 되돌리기를 하지 않고(결과 모름이므로) 즉시 멈춤, 그 뒤 `ctx.order`·`target` 은 `Halted`, 주문 0건. (Task 4 시험)
2. **`ctx.running()` 을 무시하고 도는 실행기** — 「중지」 뒤에도 `ctx.order` 를 부르면 주문은 하나도 안 나가고 `Halted` 가 오르며, 30초 뒤 앱이 정리를 시작한다. (Task 4·7 시험)
3. **짝 중 한 다리만 장이 쉼** — `ctx.target` 은 차이가 있는 다리 중 하나라도 쉬면 **아무 주문도 내지 않고** `OrderRejected`(반쪽 짝 방지); 중지 정리는 「정리 대기」. (Task 4·7 시험)
4. **이어받기 확인과 시작 사이에 잔고가 바뀜** — 화면에 보인 잔고와 시작 때 다시 읽은 잔고가 다르면 시작하지 않는다. (Task 8 시험)
5. **「정리 대기」·보유 중 앱 종료 → 다시 켬** — 주문 없이 「재시작 · 확인 필요」로 닫히고, 이어받기로만 다시 세울 수 있다. (Task 8 시험)

---

### Task 1: 다리 찾기 — 종목 마스터·품목 세부정보에서 `Leg`

**Files:**
- Create: `backend/team_spread/__init__.py`, `backend/team_spread/legs.py`
- Test: `tests/test_team_spread_legs.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Leg: name: str; sym: str; product: str; market: Literal["domestic","overseas"]; exchange: str; currency: str; tick: float; tick_value: float; expiry: str` + `@property point_value -> float` (= tick_value / tick)
  - `class LegError(ValueError)` — 메시지는 화면에 그대로.
  - `resolve(name: str, spec: str, *, overseas_rows: list[dict], domestic_rows: list[dict], overseas_details: list[dict], domestic_details: list[dict]) -> Leg` — 순수 함수. `spec` 은 품목 뿌리(`"HO"`·`"A75"`) 또는 정확한 종목 코드(`"HOZ26"`·`"A756B000"`).
  - `next_month(leg: Leg, *, overseas_rows, domestic_rows) -> str` — 같은 품목의 다음 만기 종목 코드(없으면 `LegError`).
  - `master_rows() -> tuple[list[dict], list[dict]]` — 받아 둔 마스터(가장 최근 날짜)의 (해외 선물 줄, 국내 선물 줄). `api.mku_master_rows` 와 같은 방식(`master_store.load_master`)으로 해외는 `cme_fut`·`etc_fut`(그리고 `MASTER_FILES_BY_NAME` 에 있는 다른 해외 **선물** 파일), 국내는 `fut_opt`·`idx_fut_opt`·`stk_fut_opt` 의 선물 줄.

- [ ] **Step 1: 실패하는 시험**

`tests/fixtures/team_spread/` 에 실제 마스터에서 자른 줄(HO·RB 각 3개 월물, MKU 2개, 미국달러선물 `A75…` 2개)을 csv 또는 dict 목록으로 둔다(마스터 파일에서 그대로 옮김 — 2026-11-04 `cme_fut.mst` `HOZ26;HOZ26;FCME;…;0.000100000;1.000000;1;1;HO;202612;;4.4216;4.200000;`). 품목 세부정보는 `tests/fixtures/nh/overseas_product-detail`·`domestic_product-detail` 기록에서 읽는다.

```python
def test_해외_뿌리는_만기일_기준_최근월물():
    leg = resolve("ho", "HO", **ROWS)
    assert (leg.sym, leg.exchange, leg.market, leg.tick, leg.tick_value) == ("HOZ26", "FCME", "overseas", 0.0001, 4.2)
    assert leg.point_value == 42000 and leg.currency == "USD" and leg.expiry.startswith("202612")

def test_정확한_종목코드도_된다():
    assert resolve("ho", "HOF27", **ROWS).sym == "HOF27"

def test_국내_미국달러선물():
    leg = resolve("usd", "A75", **ROWS)
    assert leg.market == "domestic" and leg.tick == 0.1 and leg.tick_value == 1000 and leg.currency == "KRW"
    assert leg.sym.startswith("A75")

def test_MKU_는_지금_파이썬_전략_탭과_같은_값():
    leg = resolve("mku", "MKU", **ROWS)
    assert (leg.exchange, leg.tick, leg.tick_value) == ("FSGX", 0.0001, 2.5)

@pytest.mark.parametrize("spec", ["XX", "HOZ99", "", "HO/Z26"])
def test_모르는_종목은_LegError(spec): ...

def test_다음_월물(): assert next_month(resolve("ho", "HO", **ROWS), **ROWS2) == "HOF27"
```

- [ ] **Step 2:** `uv run pytest tests/test_team_spread_legs.py -q` → 실패(모듈 없음).
- [ ] **Step 3: 구현** — 해외: `type == "F"` · `trdf == "0"` 줄 중 `comd == 뿌리`(또는 `code == spec`), 최근월물은 `lmon_my == "1"` 줄, 없으면 `yymm` 최소. `exchange = ExchName`, `tick = tsiz`, `tick_value = tval`, `expiry = yymm`. 통화는 해외 품목 세부정보의 그 품목 줄(`prd_cd == comd`) `cur_cd`(모르면 `LegError` — 지어내지 않음).
  국내: `fo_tp == "F"` 선물 줄, 뿌리는 `series` 앞부분(`A75`), 최근월물은 `exp_ym` 최소(이미 지난 것 제외), `expiry = exp_ym`. 틱은 품목 세부정보 줄(`dtl_cd_ko_nm`)에서 그 품목 줄의 `cd_val_inf_1`, 틱 가치 = 틱 × `ctrt_size`(마스터) — 품목 세부정보 `tick_val` 과 다르면 `LegError`. 미국달러선물은 `api.usd_spec` 과 같은 값이어야 한다(시험). 그 품목 줄을 찾지 못하면 `LegError("이 국내 품목의 틱을 찾지 못했습니다")`.
- [ ] **Step 4:** 같은 명령 → 통과. `uv run ruff check backend tests`.
- [ ] **Step 5: 커밋** `feat(team): 스프레드 다리 찾기 — 마스터·품목 세부정보에서 종목·틱·틱가치·통화`

---

### Task 2: 공유 부품 넓히기 — 수량 주문 브로커·거래소 코드 어댑터

**Files:**
- Modify: `backend/team_pyrun/broker.py`, `backend/team_pyrun/markets.py`, `backend/team_pyrun/api.py`
- Test: `tests/test_team_pyrun_markets.py`(추가), `tests/test_team_spread_broker.py`

**Interfaces:**
- Produces:
  - `MockAccountBroker.fill(side, ref_price, clock, why, qty: int = 1) -> float | None` — `qty` 계약 시장가 **한 번**. 체결 뒤 보유 = 주문 전 ± `qty`(`_post`), `blind`·`unresolved` 의 `post` 도 `qty` 반영. 전체체결(`filled`)만 체결로 본다 — 부분체결 상태로 15초가 지나면 `unresolved`(보수적). 기록 글 `시장가 {qty}계약`. 기본값 1 이라 파이썬 전략 탭 동작은 그대로.
  - `adapter_for(market, api_module=default_api, *, exch_cd: str | None = None, cur_cd: str | None = None)` — 해외 어댑터가 `chart_minute`·`price` 에 `exch_cd`(없으면 지금처럼 `FSGX`), `deposit` 에 `cur_cd`(없으면 `USD`)를 넘긴다.
  - `api.ovs_deposit` 이미 `cur_cd` 를 받음 — 그대로.
- Consumes: 없음.

- [ ] **Step 1: 실패하는 시험**
  - `test_수량_3계약_체결_뒤_보유가_3_늘어야_통과` — 가짜 api 로 `fill("buy", px, clk, "진입", qty=3)`, `market_order` 가 `qty=3` 으로 한 번 불리고, `expected()` 가 0→ 잔고 3 이면 체결.
  - `test_수량_주문_결과_모름이면_blind_의_post_는_qty_만큼` — `market_order` 가 `TransportError` → `blind == {"side":"sell","pre":2,"post":0}` (qty=2).
  - `test_해외_어댑터는_거래소_코드를_차트와_현재가에_넘긴다` — `adapter_for(OVERSEAS, fake, exch_cd="FCME").price("HOZ26")` 가 가짜 `ovs_price(sym, exch_cd="FCME")` 를 부름.
- [ ] **Step 2:** 실패 확인.
- [ ] **Step 3: 구현** — 위 인터페이스. `qty < 1` 이면 `ValueError`(주문 안 냄).
- [ ] **Step 4:** `uv run pytest -q`(전체) — 파이썬 전략 탭 시험 모두 통과. ruff.
- [ ] **Step 5: 커밋** `feat(team): 브로커 수량 주문·해외 어댑터 거래소 코드 — 스프레드용으로 넓힘(파이썬 전략 동작 그대로)`

---

### Task 3: 1분봉 맞추기와 시세 공급(`Feed`)

**Files:**
- Create: `backend/team_spread/bars.py`, `backend/team_spread/feed.py`
- Test: `tests/test_team_spread_bars.py`, `tests/test_team_spread_feed.py`

**Interfaces:**
- Consumes: `Leg`(Task 1), `adapter_for(..., exch_cd=)`(Task 2), 운영자 `backend/sessions`(시간표 + `judge_domestic`/`judge_overseas`, `sessions_routes.judged` 참고).
- Produces:
  - `@dataclass(frozen=True) class LegBar: open, high, low, close, volume: float; filled: bool`
  - `@dataclass(frozen=True) class Minute: date: str; time: str; legs: dict[str, LegBar]` (`time` = 그 분의 시작 `HHMMSS`, 한국시간)
  - `align(rows: dict[str, list[dict]]) -> list[Minute]` — 순수. 다리별 차트 줄(`ref_dt` `exch_tm` `open_pric`…; 국내·해외 칸 이름은 기록 `tests/fixtures/nh/*chart-minute*`)을 시각으로 합친다. 한 다리에 봉이 없는 분은 직전 종가로 채우고 `filled=True`(open=high=low=close=직전 종가, volume 0). 모든 다리에 한 번이라도 값이 생기기 전의 분은 버린다. 오래된 것부터.
  - `class Feed(Protocol)`: `history(legs, count) -> list[Minute]` · `next_minute(legs, stop: threading.Event) -> Minute | None`(다음 분이 끝나 봉이 확정될 때까지 기다림, 다리 중 하나라도 장이 쉬면 열릴 때까지 기다림, `stop` 이 서면 `None`) · `quote(leg) -> Quote(last, bid, ask, at)` · `is_open(leg, now) -> bool` · `now() -> datetime` · `sleep(s, stop)`.
  - `class LiveFeed(Feed)` — 차트 조회(`chart_minute(sym, req_qty=…)`), 분 경계 + 3초 뒤 조회(파이썬 전략 `LiveRun` 과 같은 박자), 장 열림은 운영자 세션 판정(모르면 `False`).
  - `class FeedState` 열거 또는 문자열: `"진행 중"` / `"장 쉼"` — `next_minute` 이 기다리는 동안 실행 상태 표시에 씀(콜백 `on_wait(state, legs_closed)`).
- [ ] **Step 1: 실패하는 시험**
  - `align`: 두 다리 봉 시각이 어긋날 때 채움 표시·버림 규칙, 국내 칸(`occurs1_` 접두 포함 여부는 기록 그대로)과 해외 칸 모두.
  - `LiveFeed.next_minute`: 가짜 시계·가짜 api 로 09:00:03 에 09:00 봉을 돌려줌, 한 다리 장 쉼이면 열릴 때까지 `on_wait("장 쉼", ["rb"])` 후 대기, `stop.set()` 이면 `None`.
  - `is_open`: 세션 판정이 `unknown` 이면 `False`.
- [ ] **Step 2–4:** 실패 확인 → 구현 → 통과 + ruff.
- [ ] **Step 5: 커밋** `feat(team): 스프레드 1분봉 맞추기·장중 시세 공급(장 쉼 대기)`

---

### Task 4: 앱 창구 `ctx` — 한도·멈춤·짝 규칙

**Files:**
- Create: `backend/team_spread/ctx.py`
- Test: `tests/test_team_spread_ctx.py`

**Interfaces:**
- Consumes: `Leg`, `Feed`(Task 3).
- Produces:
  - 예외 `class OrderRejected(Exception)`(결과를 아는 실패 — 거부·장 닫힘·한도·중지 뒤), `class Halted(Exception)`(멈춘 실행).
  - `@dataclass(frozen=True) class Fill: leg: str; qty: int; price: float; fee: float | None`
  - `class Book(Protocol)`: `position(leg) -> int` · `order(leg, qty, why) -> Fill`(거부면 `OrderRejected`, 결과 모름이면 `Halted` 를 올리고 장부가 스스로 멈춤 상태) · `halted -> str | None`. (구현은 Task 5)
  - `class Ctx`: 설계 문서 7장 표의 이름 그대로 — `leg(name)` `bars(legs, count)` `next_minute(legs)` `quote(leg)` `position(leg)` `order(leg, qty)` `target(mapping)` `log(name, value, **fields)` `running()` `now()` `sleep(s)` `market_open(leg)` `roll(name)` `inherited`. 다리 인자는 `Leg` 또는 다리 이름 둘 다 받는다.
  - 생성자: `Ctx(legs: dict[str, Leg], feed: Feed, book: Book, journal: Journal, *, max_qty: dict[str, int], orders_per_min: int, inherited: dict | None, stop: threading.Event, roll: Callable[[str], Leg])`
- 규칙(시험으로 고정):
  - `order`: `qty == 0` 이면 아무것도 안 함. 멈춤이면 `Halted`. 중지 뒤(`stop` 섬)면 `OrderRejected("중지됨")`. 장 쉼이면 `OrderRejected("장 쉼")`. `|보유 + qty| > max_qty[leg]` 면 `OrderRejected`. 최근 60초 주문 수 ≥ 상한이면 `OrderRejected`. 통과하면 `book.order`.
  - `target`: 차이가 있는 다리를 적힌 순서대로. **보내기 전에** 차이가 있는 모든 다리의 장 열림·한도를 검사해 하나라도 안 되면 아무것도 안 내고 `OrderRejected`. 보내는 중 뒤 다리가 `OrderRejected` 면 이번 `target` 에서 체결된 다리를 반대 수량으로 한 번 `book.order`(되돌리기) 하고 `OrderRejected` 를 다시 올림 — 되돌리기도 거부면 장부를 멈춤으로 두고 `Halted`. 결과 모름(`Halted`)은 되돌리지 않고 그대로 올림.
  - `log`: 이름·값(수)·칸을 `journal.write("log", …)` 로. 수가 아니면 `TypeError`.
  - `roll(name)`: 그 다리 보유가 0 이 아니면 `OrderRejected`. 아니면 `roll` 콜백으로 새 `Leg` 를 받아 바꾸고 기록.
- [ ] **Step 1: 실패하는 시험** — 위 규칙 하나마다, 그리고 Review Focus 1·2·3. 가짜 `Feed`·가짜 `Book`(주문 기록 목록).
- [ ] **Step 2–4:** 실패 → 구현 → 통과 + ruff.
- [ ] **Step 5: 커밋** `feat(team): 스프레드 앱 창구 ctx — 한도·장 쉼·중지·짝 되돌리기·멈춤`

---

### Task 5: 주문 장부 — 종이와 모의 계좌

**Files:**
- Create: `backend/team_spread/book.py`
- Test: `tests/test_team_spread_book.py`

**Interfaces:**
- Consumes: `Book`·`Fill`·`OrderRejected`·`Halted`(Task 4), `MockAccountBroker.fill(..., qty=)`·`adapter_for(..., exch_cd=, cur_cd=)`(Task 2), `Leg`.
- Produces:
  - `class PaperBook(Book)` — 체결가 = 주문 순간 시세의 반대 호가(매수 ask·매도 bid, 없으면 마지막 체결가 ∓ 1틱), 수수료 = 시장별 종이 값(국내 `DOMESTIC.paper_fee`, 해외 `OVERSEAS.paper_fee` 를 체결 1계약마다). 재생용 `ReplayPaperBook` 은 Task 10.
  - `class AccountBook(Book)` — 다리마다 `MockAccountBroker`(그 다리 시장 어댑터, `sym`, 공유 `Journal`, `expected=lambda: 그 다리 보유`, `halt=self._halt`). `order` → `broker.fill(side, ref, clock, why, qty=abs(qty))`; `None` 이면: `held_back`/`sent=False` 거부 → `OrderRejected`, 결과 모름(`needs_check`·`unknown`) → 그 다리 잔고 대조, 설명되면(`explains`) 보유를 잔고로 따르고 `Fill`, 아니면 멈춤 + `Halted`.
  - `AccountBook.reconcile() -> str | None` — 모든 다리 잔고를 읽어 장부 보유와 다르면 멈춤 까닭(주기 대조와 끝 확인에 씀).
  - `AccountBook.balances() -> dict[str, int]`(이어받기·시작 잔고 0 확인용, 못 읽으면 `LegError` 류 예외).
- [ ] **Step 1: 실패하는 시험** — 종이 체결가·수수료, 계좌: 체결·거부(`OrderRejected`)·결과 모름(`Halted` + 이후 모든 다리 주문 `Halted`)·`reconcile` 불일치 멈춤·다리별 어댑터가 그 다리 거래소 코드를 씀.
- [ ] **Step 2–4.** **Step 5: 커밋** `feat(team): 스프레드 주문 장부 — 종이·모의 계좌(다리마다 브로커, 결과 모름이면 멈춤)`

---

### Task 6: 실행기 파일 불러오기·폴더

**Files:**
- Create: `backend/team_spread/runner_files.py`
- Modify: `backend/team_pyrun/loader.py`(격리 실행을 공개 함수로 꺼냄 — 동작 그대로)
- Test: `tests/test_team_spread_runner_files.py`

**Interfaces:**
- Consumes: `team_pyrun.loader` 의 격리 실행(지금 `_exec_module`) — `exec_isolated(folder: Path, file: str, *, pick: bool = True) -> tuple[ModuleType, str]` 로 꺼내고, 스프레드는 `pick=False`(앱에 없는 모듈이면 그대로 `LoadError`). 파이썬 전략 쪽은 지금과 같이 `pick=True`.
- Produces:
  - `spreads_dir() -> Path`(만들어 둠)
  - `@dataclass(frozen=True) class RunnerFile: file, name, title, legs: dict[str,str], max_qty: int | None, error: str | None, sha256: str | None`
  - `load_runner(folder, file) -> Loaded`(`run` 함수·`LEGS`·`TITLE`·`NAME`·`MAX_QTY`), `scan(folder) -> tuple[list[RunnerFile], list[str]]`(실행기 / 옆 모듈).
  - 약속 위반 → `LoadError` 문장: `LEGS` 없음·dict 아님·비었음·이름이 `[A-Za-z0-9_]+` 아님·값이 글자 아님 / `run` 없음·부를 수 없음·인자가 하나가 아님 / `MAX_QTY` 가 양의 정수 아님 / `NAME` 규칙(파이썬 전략과 같음).
  - 올리기·지우기는 `team_pyrun.strategy_files` 를 폴더만 바꿔 그대로 씀.
- [ ] **Step 1: 실패하는 시험** — 정상 실행기(옆 파일 import 포함), 각 약속 위반 문장, 앱에 없는 모듈 import → `ModuleNotFoundError` 문장 그대로(골라 쓰기 안 함), 파이썬 전략 불러오기 시험은 그대로 통과.
- [ ] **Step 2–4.** **Step 5: 커밋** `feat(team): 스프레드 실행기 파일 불러오기 — LEGS·run(ctx) 약속 검사`

---

### Task 7: 실행 하나 — `SpreadRun` 수명

**Files:**
- Create: `backend/team_spread/run.py`
- Test: `tests/test_team_spread_run.py`

**Interfaces:**
- Consumes: Task 1·3·4·5·6, `team_pyrun.journal`(`Journal`, `scrub`, `summarize` 꼴 참고), `team_pyrun.apilog`(`ApiLog`, `bind`, `purpose`).
- Produces:
  - `@dataclass(frozen=True) class SpreadSpec: file: str; mode: Literal["orders","paper","replay"]; syms: dict[str, str] | None; max_qty: dict[str, int] | None; orders_per_min: int | None; inherit_from: str | None`
  - `class SpreadRun`: `prepare()`(다리 찾기 → 품목 세부정보로 틱 확인 → 시작 잔고: 0 이어야, 이어받기면 `inherit` 값과 같아야 → 과거 봉은 실행기가 `ctx.bars` 로 직접 요청) · `run_forever()`(스레드: `run(ctx)` 를 부르고, 따로 30초마다 `book.reconcile()` 하는 감시) · `request_stop(shutdown: bool = False)` · `status() -> dict` · `state` · `run_id` · `folder` · `order_syms() -> set[str]`.
  - 상태: `준비` `진행 중` `장 쉼` `정리 대기` `확인 필요` `끝` `오류`.
  - `ctx.roll` 콜백 = `legs.next_month` + `legs.resolve`(새 종목), 장부·시세 공급·`run.json` 의 다리 종목을 바꾸고 `leg` 줄을 기록. 같은 종목 모의 실행 검사(Task 8)에도 새 종목이 걸리게 등록을 바꾼다.
  - 끝 규칙(설계 8장): 실행기가 돌려줌 → `끝`(보유가 있으면 앱이 정리 — 「중지」와 같은 정리). 예외 → `오류` + 정리. 「중지」 → `stop` 세움, 30초 기다린 뒤 정리. **정리**: 멈춤이 아니고 모의 계좌면, 모든 다리 장이 열려 있을 때 다리마다 시장가로 0 까지(거부 다리는 10초 뒤 3번까지), 하나라도 쉬면 `정리 대기` 로 기다림. 종이면 마지막 시세로 장부만 0. `shutdown=True` 면 **정리하지 않고** 끝(보유가 있으면 끝 까닭 「앱 종료 · 보유 남음 — 이어받기로 다시」).
  - 기록: `run.json`(머리 칸 + 다리 + 상태), `journal.jsonl`(파이썬 전략과 같은 `kind` 꼴 + `log`·`fill`·`leg`), `api_log.jsonl`, `summary.json` — `days: {YYYYMMDD: {currency: {pnl, fee, fills}}}` 와 `total: {currency: {...}}`, `legs`, `ended_reason`, `inherited`.
  - `status()` 칸(화면 Task 11 이 씀): `id file name title mode state started_at ended_at ended_reason halted legs[{name sym market currency position avg_price last}] pnl_today{cur:…} pnl_total{cur:…} waiting_for[leg…] inherited_from handed_to logs_tail`.
- [ ] **Step 1: 실패하는 시험** — 가짜 Feed·가짜 api 로: 정상 끝·예외 오류·중지 30초 뒤 정리, Review Focus 2·3·5(종료 시 정리 안 함), 정리 대기에서 장 열리면 정리, 정리 거부 3번 뒤 멈춤, 주기 대조 불일치 멈춤, 요약의 날짜·통화별 손익.
- [ ] **Step 2–4.** **Step 5: 커밋** `feat(team): 스프레드 실행 수명 — 중지·오류 정리(짝 함께), 앱 종료 땐 보유 유지, 날짜·통화별 요약`

---

### Task 8: 실행 관리 — 시작·목록·중지·종료·복구·이어받기·두 탭 통틀어 종목 하나

**Files:**
- Create: `backend/team_spread/registry.py`
- Modify: `backend/team_pyrun/registry.py`(같은 종목 모의 실행 검사가 스프레드 실행의 주문 종목도 보게 — 작은 콜백 하나, 동작은 그대로)
- Test: `tests/test_team_spread_registry.py`

**Interfaces:**
- Consumes: `SpreadRun`(Task 7).
- Produces: `SpreadRegistry(root, folder, *, now, active_env, start_thread, api_module, …)` — `start(spec) -> dict` · `list()` · `get(id)` · `folder(id)` · `stop(id)` · `stop_all(timeout=20)`(`request_stop(shutdown=True)`) · `close_starts()` · `recover()` · `inherit_preview(id) -> dict`(지금 계좌 잔고·평균가·앞선 끝 까닭·경고) · `registry()` 싱글턴.
  - 거부(`StartRefused`, 폴더 전): 모드·이름·주말이 아닌 **모의 환경 아님**(orders), 실행기 오류, 다리 찾기 실패, **같은 종목 모의 실행이 이미 있음 — 스프레드·파이썬 전략 통틀어**(`team_pyrun.registry` 와 서로 묻기), 앱 끄는 중.
  - 이어받기: 앞선 실행이 `끝`/`오류`/「재시작 · 확인 필요」 이고 모드 `orders`, 같은 파일·같은 다리 종목, 아직 `handed_to` 없음. 시작 때 잔고를 다시 읽어 `inherit_preview` 가 보인 값과 다르면 거부(Review Focus 4). 성공하면 앞선 `run.json` 에 `handed_to`, 새 실행에 `inherited_from`·`inherited{leg:{qty,avg_price}}`.
  - `recover()`: 파이썬 전략 `recover` 와 같음(주문 없음, 다리마다 잔고, 보유 있거나 못 읽으면 「재시작 · 확인 필요」).
- [ ] **Step 1: 실패하는 시험** — 각 거부, 두 탭 통틀어 같은 종목, 이어받기 성공·거부(잔고 바뀜, 다른 파일, 두 번 이어받기), recover, Review Focus 4·5.
- [ ] **Step 2–4.** **Step 5: 커밋** `feat(team): 스프레드 실행 관리 — 이어받기, 두 탭 통틀어 종목 하나, 복구`

---

### Task 9: 라우트·앱 연결

**Files:**
- Create: `backend/team_spread/routes.py`
- Modify: `backend/main.py`(라우터·켜고 끌 때 훅, `# 팀:`), `tests/conftest.py`(스프레드 싱글턴을 임시 자리로)
- Test: `tests/test_team_spread_routes.py`

**Interfaces:**
- Produces (`/api/team/spread`): `GET /runners` · `POST /runners/reload` · `POST /runners`(올리기 `{file, content, overwrite}`) · `DELETE /runners/{file}` · `GET /convention` · `GET /runs` · `POST /runs`(`{file, mode, syms?, max_qty?, orders_per_min?}`, 모르는 칸 422) · `GET /runs/{id}` · `GET /runs/{id}/journal?after=` · `GET /runs/{id}/api-log?after=` · `GET /runs/{id}/bars`(다리별 가격 + `log` 이름별 점) · `GET /runs/{id}/download` · `POST /runs/{id}/stop` · `GET /runs/{id}/inherit`(미리 보기) · `POST /runs/{id}/inherit`(`{file, expect: {leg: qty}}`).
  - 켤 때: 파이썬 전략 복구 다음에 스프레드 `recover`. 끌 때: 파이썬 전략과 함께 `close_starts` → `stop_all`.
- [ ] **Step 1: 실패하는 시험** — 라우트마다 정상·거부(409 문장)·404·다른 사이트 403·모르는 칸 422, 시작 라우트는 동기 `def`(파이썬 전략 시작 라우트와 같은 까닭).
- [ ] **Step 2–4.** **Step 5: 커밋** `feat(team): 스프레드 라우트와 앱 연결`

---

### Task 10: 재생 — csv 로 같은 실행기를 서버 없이

**Files:**
- Create: `backend/team_spread/replay.py`
- Test: `tests/test_team_spread_replay.py`

**Interfaces:**
- Consumes: `Ctx`, `align`, `Leg`, `SpreadRun` 기록 꼴.
- Produces: `ReplayFeed(Feed)`(csv 봉, 시계 = 봉 시각, `next_minute` = 다음 맞춘 분, 장 쉼 = 봉 없는 구간, `quote` = 그 분 종가로 bid/ask = 종가 ∓ ½틱), `ReplayPaperBook`(다음 분 시가 ± 1틱, 수수료 종이 값), `replay(loaded, csvs: dict[str, Path], legs: dict[str, Leg], out: Path) -> dict`(요약), CLI `python -m backend.team_spread.replay <실행기.py> <다리>=<csv> ... [--legs-from-master]`(다리 정보는 마스터, 마스터가 없으면 `<다리>=<csv>:<tick>:<tick_value>:<currency>` 꼴로 받음).
- [ ] **Step 1: 실패하는 시험** — 짧은 csv 두 개로 "z>2 면 짝" 같은 작은 실행기가 정해진 거래를 냄, 같은 입력 두 번이면 같은 결과, 한 다리 봉이 빈 구간에서 `target` 이 거부됨.
- [ ] **Step 2–4.** **Step 5: 커밋** `feat(team): 스프레드 재생 — 다리별 1분봉 csv`

---

### Task 11: 화면 — 「스프레드」 탭

**Files:**
- Create: `frontend/src/data/spread.ts`, `frontend/src/screens/team/spread/SpreadScreen.tsx`·`SpreadSide.tsx`·`SpreadMain.tsx`·`SpreadChart.tsx`·`spread.css`
- Modify: 메뉴(「전략주문 › 파이썬 전략」을 등록한 곳과 같은 자리)에 「스프레드」
- Test: `frontend` 기존 시험 방식이 있으면 그 꼴로 데이터 모양 시험, 없으면 `just typecheck` + `just lint`

**Interfaces:**
- Consumes: Task 9 라우트, Task 7 `status()` 칸.
- 화면(설계 11장): 파이썬 전략 탭의 자리·클래스(`run-*`, `pyrun-*` 를 본뜸). 왼쪽 실행기 파일 카드(올리기·지우기·다시 읽기·「작성 규칙」)·실행 목록, 오른쪽 머리줄(상태·「중지」, `정리 대기` 면 기다리는 다리)·상태 막대(다리별 종목·보유·평균가·현재가, 통화별 오늘/누적 손익, 멈춤 까닭)·차트(다리 가격 + 고른 `log` 값, 오른쪽 축)·표(체결·사건·API)·날짜별 요약. 「실행 세우기」(파일·방식·다리별 종목 고르기·다리별 최대 보유·분당 주문, 모의 계좌 확인 얼굴). 끝난 실행에 보유가 남았으면 「이어받기」(미리 보기 → 확인 얼굴 → `expect` 와 함께 보냄).
- [ ] **Step 1–4:** 구현 → `just typecheck` · `just lint`(0 오류) · `just build`.
- [ ] **Step 5: 커밋** `feat(team): 화면 — 스프레드 탭`

---

### Task 12: 문서·예제·프롬프트

**Files:**
- Create: `docs/team/spread-runner-convention.md`, `docs/team/examples/spread_rolling_beta.py`
- Modify: `docs/team/strategy-file-prompt.md`(스프레드 실행기 절), 사적 `claude.md`(커밋하지 않음 — 표에 `team_spread/` 줄), 설계 문서 상태를 「구현됨」
- Test: `tests/test_team_spread_docs.py`

- 작성 규칙 문서: 약속(`LEGS`·`run(ctx)`·`TITLE`·`NAME`·`MAX_QTY`), `ctx` 표(설계 7장 그대로의 의미 + 실제 이름), 안전 규칙, 수명(장 쉼·중지 정리·정리 대기·앱 종료·이어받기), 첫 모의 장중 순서(설계 16장), 재생 명령. 화면 「작성 규칙」 이 이 글을 보인다.
- 예제 `spread_rolling_beta.py`: `LEGS = {"ho": "HO", "rb": "RB"}`, 최근 N분 회귀 β·스프레드 z, |z| > 2 면 `ctx.target` 으로 짝, |z| < 0.5 면 풀기, 보유 시간 상한, `ctx.inherited` 로 상태 되살리기, `ctx.log("z", …, beta=…)`. 머리말에 「모양을 보이려는 예제 — 수익 전략 아님」.
- 시험: 예제가 `load_runner` 로 불러와지고, Task 10 재생으로 작은 csv 에서 돈다. 문서의 python 코드 블록이 불러와진다.
- [ ] **Step 1–4.** 전체 `uv run pytest -q`, `just lint`, `just typecheck`.
- [ ] **Step 5: 커밋** `docs(team): 스프레드 실행기 작성 규칙·롤링 β 예제·AI 프롬프트`
