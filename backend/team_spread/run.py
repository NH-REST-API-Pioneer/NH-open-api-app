"""스프레드 실행 하나 — `SpreadRun` 의 수명(준비 → 실행기 스레드 → 중지·끝 → 정리 → 요약). 설계 8·9장.

    prepare()        다리 찾기 → 품목 세부정보로 틱 확인 → 시작 잔고(모의 계좌: 0, 이어받기면 그 값) → ctx.
                     안 되면 `StartRefused`(주문 없음, run.json 은 「끝」 · 「시작 거부: …」로 남음, summary 없음)
    run_forever()    실행 스레드 본문(registry 가 데몬 스레드로). `run(ctx)` 는 또 다른 데몬 스레드에서, 모의 계좌면
                     잔고 감시도 따로 한 스레드에서(보유 중 30초마다 `reconcile()` — 못 읽으면 기록만)
    request_stop(shutdown=False)   「중지」 — ctx 가 바로 주문을 받지 않고 `next_minute`·`sleep` 이 깬다
    finish(reason)   정리·끝 잔고·요약. 두 번 불려도 한 번만 (스레드 없이 부르면 정리 대기 동안 돌아오지 않음)

끝 규칙 (판정 R1·R5)
- 실행기가 돌려주면 「끝」, 예외면 「오류」 — 둘 다 보유가 남았으면 「중지」와 같이 정리한다. 중지 뒤 ctx 가 낸 거부
  (`OrderRejected`)를 실행기가 그대로 던진 것은 오류가 아니라 중지다(`running()` 확인과 주문 사이의 경합).
- 「중지」 → 실행기를 30초 기다린 뒤 정리. 그 안에 안 돌려줘도 ctx 는 이미 주문을 받지 않는다(돌던 스레드는 버려 둠).
- 정리는 `Book` 을 직접 쓴다(ctx 아님). 다리마다 `book.lock` 을 쥔 채 보유를 읽고 주문한다(실행기 쪽 주문과 섞이지 않게).
  - 멈춤(확인 필요)이면 정리하지 않는다.
  - 모의 계좌: 보유한 다리가 모두 열려 있으면 잔고를 엄격히 대조한 뒤 다리마다 시장가로 0 까지. 하나라도 쉬면
    「정리 대기」 — 짝을 그대로 들고 모두 열릴 때까지. 거부된 다리는 열린 다리를 마저 정리한 뒤 10초 뒤 다시,
    3번(처음 + 다시 2번, 파이썬 전략 실시간과 같음) 안 되면 멈춤. 결과를 모르면 장부가 멈춘다.
  - 종이·재생: 계좌가 없어 장이 쉬어도 기다리지 않고 지금 시세로 장부만 0 (앱 종료 때도 — 이어받을 계좌 보유가 없음).
- 앱 종료(`shutdown=True`): 실행기를 기다리지 않고 모의 계좌 보유를 정리하지 않는다(정리 대기 중이었어도).
  보유가 남으면 끝 까닭 「앱 종료 · 보유 남음 — 이어받기로 다시」 — 다시 켤 때 registry `recover` 가 확인 필요로 닫는다.
- 끝 확인은 `reconcile(strict=True)` — 잔고를 못 읽으면 깨끗하게 끝났다고 하지 않는다.

손익 — 체결(`Fill`)로 다리마다 평균가 방식: 줄이는 체결의 (체결가 − 평균가) × 수량 × `point_value`, 수수료는 따로.
날(거래일 = 한국시간 07:00 경계, 운영자 `sessions.service` 의 갈이 시각과 같음 — 해외 밤 장 자정 뒤 체결은 그 장이 연 날)과
실행 전체를 통화별로 `{pnl, fee, net, fills}`. 체결가를 모르는(`price_known` False) 체결이 들어간 손익은 `estimated: true`,
수수료를 모르는 체결은 `fee_unknown` 개수. 이어받은 보유는 이어받은 평균가가 시작 값(평균가가 없으면 그 손익은 추정).

기록: `run.json`(머리 칸 + 다리 + 상태), `journal.jsonl`(장부·ctx 의 `fill`·`order`·`event`·`log`·`roll` + 여기의 `leg`·`gap`),
`api_log.jsonl`(실행기·감시·정리 스레드마다 `bind`), `summary.json`. 모두 쓰는 순간 `scrub`.
"""
from __future__ import annotations

import copy
import math
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from backend.nh_api import runtime
from backend.overseas_futureoption.overseas_hours import PRODUCT_GROUPS
from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun.apilog import ApiLog, bind, purpose
from backend.team_pyrun.broker import error_text
from backend.team_pyrun.journal import Journal, write_summary
from backend.team_pyrun.live import StartRefused, write_run_json
from backend.team_spread.book import AccountBook, PaperBook
from backend.team_spread.ctx import DEFAULT_MAX_QTY, Ctx, Halted, OrderRejected
from backend.team_spread.feed import WAIT_CLOSED, Feed, LiveFeed
from backend.team_spread.legs import Leg, LegError, master_rows, next_month, resolve
from backend.team_spread.runner_files import LoadedRunner

DEFAULT_ORDERS_PER_MIN = 10
MAX_FLATTEN_REJECTS = 3             # 정리 주문이 결과를 아는 거부로 이만큼(처음 + 다시 2번) 안 되면 멈춤
SHUTDOWN_HOLDING = "앱 종료 · 보유 남음 — 이어받기로 다시"
DAY_STARTS = timedelta(hours=7)     # 거래일 경계 07:00 (운영자 `sessions.service.REFRESH_AT`)
LOGS_TAIL = 20
#: 해외 품목 세부정보는 그룹마다 따로 묻는다(판정 R4) — 팀이 쓰는 통화(FG2)·에너지(FG6)를 먼저, 다 찾으면 멈춘다
FIRST_GROUPS = ("FG2", "FG6")
DETAIL_MAX_PAGES = 10
FINISHED = ("끝", "오류")


@dataclass(frozen=True)
class SpreadSpec:
    """무엇을 돌릴지. `syms` = 다리 → 표기(뿌리·종목 코드, 없으면 실행기 `LEGS`), `max_qty` = 다리 → 최대 보유."""

    file: str
    mode: Literal["orders", "paper", "replay"]
    syms: dict[str, str] | None = None
    max_qty: dict[str, int] | None = None
    orders_per_min: int | None = None
    inherit_from: str | None = None


@dataclass(frozen=True)
class Timing:
    """기다림(초). 약속 값: 중지 뒤 실행기 30초 · 보유 중 잔고 대조 30초 · 정리 거부 뒤 10초. 시험만 줄인다."""

    stop_wait: float = 30.0
    reconcile: float = 30.0
    retry: float = 10.0
    poll: float = 1.0       # 상태 살핌·정리 대기 간격


def trading_date(at: datetime) -> str:
    """거래일(YYYYMMDD) — 한국시간 07:00 경계."""
    return (to_kst(at) - DAY_STARTS).strftime("%Y%m%d")


def _iso(at: datetime) -> str:
    return to_kst(at).replace(tzinfo=None).isoformat(timespec="seconds")


def _s(row: dict | None, key: str) -> str:
    return str((row or {}).get(key, "")).strip()


def _where(e: BaseException) -> list[str]:
    """예외 자리(파일:줄 함수)만 — 값·문구는 남기지 않는다."""
    return [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in traceback.extract_tb(e.__traceback__)[-6:]]


# ---------------------------------------------------------------- 다리 찾기 (registry 도 쓴다)
@dataclass(frozen=True)
class Sources:
    """다리 찾기에 쓴 마스터 줄과 품목 세부정보 — 월물 교체 때 다시 쓴다."""

    overseas_rows: list[dict]
    domestic_rows: list[dict]
    overseas_details: list[dict]
    domestic_details: list[dict]

    def kw(self) -> dict[str, list[dict]]:
        return {"overseas_rows": self.overseas_rows, "domestic_rows": self.domestic_rows,
                "overseas_details": self.overseas_details, "domestic_details": self.domestic_details}


def leg_specs(loaded: LoadedRunner, syms: dict[str, str] | None) -> dict[str, str]:
    """다리 → 표기. `syms` 가 실행기에 없는 다리를 말하면 `StartRefused`."""
    extra = sorted(set(syms or {}) - set(loaded.legs))
    if extra:
        raise StartRefused(f"실행기에 없는 다리입니다: {', '.join(extra)}")
    return {name: (syms or {}).get(name) or spec for name, spec in loaded.legs.items()}


def overseas_details(products: set[str], api_module: Any) -> list[dict]:
    """해외 품목 세부정보 — 필요한 품목이 다 나올 때까지 그룹을 차례로, 그룹마다 `nxt_key` 쪽을 따라."""
    got: list[dict] = []
    left = set(products)
    for group in sorted(PRODUCT_GROUPS, key=lambda g: g not in FIRST_GROUPS):
        key, used = "", set()
        for _ in range(DETAIL_MAX_PAGES):
            rows, key = api_module.ovs_product_detail_page(group, key)
            got += rows
            left -= {_s(r, "prd_cd") for r in rows}
            if not key or key in used:
                break
            used.add(key)
        if not left:
            break
    return got


def load_sources(specs: dict[str, str], *, api_module: Any, master: Callable[[], tuple[list, list]]) -> Sources:
    """마스터(파일)와 필요한 품목 세부정보(조회). 해외 표기가 없으면 해외 세부정보를, 국내가 없으면 국내를 묻지 않는다."""
    ovs, dom = master()
    wanted = set(specs.values())
    products = {_s(r, "comd") for r in ovs if _s(r, "code") in wanted or _s(r, "comd") in wanted}
    known = {_s(r, "code") for r in ovs} | {_s(r, "comd") for r in ovs}
    with purpose("품목 세부정보"):
        ovs_details = overseas_details(products, api_module) if products else []
        dom_details = api_module.product_detail() if wanted - known else []
    return Sources(ovs, dom, ovs_details, dom_details)


def check_ticks(legs: dict[str, Leg], details: list[dict]) -> None:
    """해외 다리의 틱·틱 가치(마스터)를 품목 세부정보(`tick_unt`·`tick_val`)와 맞춰 본다 — 다르면 `StartRefused`.
    국내는 `resolve` 가 세부정보 틱으로 이미 맞춰 본다."""
    for leg in legs.values():
        if leg.market != "overseas":
            continue
        row = next((d for d in details if _s(d, "prd_cd") == leg.product), None)
        tick, value = default_api.num(_s(row, "tick_unt")), default_api.num(_s(row, "tick_val"))
        if not tick or not value:
            raise StartRefused(f"{leg.name}({leg.sym}) 의 틱을 품목 세부정보에서 읽지 못했습니다")
        if not (math.isclose(tick, leg.tick, rel_tol=1e-9) and math.isclose(value, leg.tick_value, rel_tol=1e-9)):
            raise StartRefused(f"{leg.name}({leg.sym}) 틱·틱가치가 마스터({leg.tick:g}·{leg.tick_value:g})와 "
                               f"품목 세부정보({tick:g}·{value:g})가 다릅니다")


def resolve_legs(specs: dict[str, str], sources: Sources, *, today: str) -> dict[str, Leg]:
    """표기 → `Leg`, 틱 확인, 두 다리가 같은 종목이면 거부(잔고 관문이 한 계좌 보유를 나눠 볼 수 없음)."""
    legs: dict[str, Leg] = {}
    for name, spec in specs.items():
        try:
            legs[name] = resolve(name, spec, **sources.kw(), today=today)
        except LegError as e:
            raise StartRefused(f"다리 {name}: {e}") from e
    check_ticks(legs, sources.overseas_details)
    syms = [leg.sym for leg in legs.values()]
    if len(set(syms)) != len(syms):
        raise StartRefused(f"두 다리가 같은 종목입니다: {', '.join(syms)}")
    return legs


# ---------------------------------------------------------------- 손익
def _zero() -> dict[str, Any]:
    return {"pnl": 0.0, "fee": 0.0, "fills": 0}


class _Ledger:
    """체결로 센 손익(모듈 설명). 여러 스레드가 부르므로 잠근다."""

    def __init__(self, inherited: dict[str, dict] | None):
        self._lock = threading.Lock()
        #: 다리 → [보유, 평균가 | None, 평균가가 추정인가]
        self.pos: dict[str, list] = {}
        for name, v in (inherited or {}).items():
            avg = v.get("avg_price")
            if int(v.get("qty") or 0):
                self.pos[name] = [int(v["qty"]), None if avg is None else float(avg), avg is None]
        self.days: dict[str, dict[str, dict]] = {}
        self.total: dict[str, dict] = {}

    def add(self, leg: Leg, qty: int, price: float | None, fee: float | None, known: bool, day: str) -> None:
        with self._lock:
            held, avg, est = self.pos.get(leg.name, [0, None, False])
            unknown = not known or price is None
            pnl, flagged, after = 0.0, False, held + qty
            if held and (held > 0) != (qty > 0):          # 줄이는(뒤집는) 체결
                closed = min(abs(held), abs(qty))
                flagged = unknown or est or avg is None
                if avg is not None and price is not None:
                    pnl = (price - avg) * closed * (1 if held > 0 else -1) * leg.point_value
                if after == 0:
                    avg, est = None, False
                elif (after > 0) != (held > 0):           # 뒤집힘 — 남은 몫은 이 체결가
                    avg, est = price, unknown
            else:                                          # 늘리는 체결
                avg = None if price is None or (held and avg is None) else \
                    ((avg or 0.0) * abs(held) + price * abs(qty)) / abs(after)
                est = est or unknown
            self.pos[leg.name] = [after, avg, est]
            fee = None if fee is not None and fee < 0 else fee     # 예수금 하루 누적이 날을 넘겨 줄면 모르는 값
            for b in (self.days.setdefault(day, {}).setdefault(leg.currency, _zero()),
                      self.total.setdefault(leg.currency, _zero())):
                b["pnl"] += pnl
                b["fills"] += 1
                if fee is None:
                    b["fee_unknown"] = b.get("fee_unknown", 0) + 1
                else:
                    b["fee"] += fee
                if flagged:
                    b["estimated"] = True

    @staticmethod
    def _out(b: dict) -> dict:
        out = {"pnl": round(b["pnl"], 2), "fee": round(b["fee"], 2), "net": round(b["pnl"] - b["fee"], 2),
               "fills": b["fills"]}
        out.update({k: b[k] for k in ("fee_unknown", "estimated") if k in b})
        return out

    def snapshot(self) -> tuple[dict, dict]:
        with self._lock:
            days = {d: {c: self._out(b) for c, b in cur.items()} for d, cur in sorted(self.days.items())}
            return days, {c: self._out(b) for c, b in self.total.items()}

    def avg(self, name: str) -> float | None:
        with self._lock:
            got = self.pos.get(name)
            return None if not got or not got[0] or got[1] is None else round(got[1], 10)


# ---------------------------------------------------------------- 대리 (ctx 가 보는 장부·시세, 기록)
class _Recorder:
    """ctx·정리가 쓰는 장부 — 진짜 장부로 보내고 돌아온 체결(또는 예외 뒤 바뀐 보유)을 손익에 센다.
    보유 읽기 → 주문 → 보유 읽기를 `book.lock` 안에서 해 다른 스레드의 주문이 끼지 않는다."""

    def __init__(self, book: Any, record: Callable[[Leg, int, float | None, float | None, bool], None]):
        self._book, self._record = book, record

    @property
    def halted(self) -> str | None:
        return self._book.halted

    def halt(self, reason: str) -> None:
        self._book.halt(reason)

    def position(self, leg: Leg) -> int:
        return self._book.position(leg)

    def order(self, leg: Leg, qty: int, why: str):
        with self._book.lock:
            before = self._book.position(leg)
            try:
                fill = self._book.order(leg, qty, why)
            except BaseException:
                moved = self._book.position(leg) - before
                if moved:       # 장부가 잔고를 따르고 멈춤(체결가 모름) — 가격 없이 센다
                    self._record(leg, moved, None, None, False)
                raise
            self._record(leg, fill.qty, fill.price, fill.fee, fill.price_known)
            return fill


class _Seen:
    """ctx·장부가 보는 시세 — 그대로 넘기며 다리별 마지막 값(봉 종가·현재가)을 기억한다(상태 화면용)."""

    def __init__(self, feed: Feed, last: dict[str, float]):
        self._f, self._last = feed, last

    def _bars(self, minutes: list) -> None:
        for m in minutes[-1:]:
            for name, bar in m.legs.items():
                self._last[name] = bar.close

    def history(self, legs, count):
        got = self._f.history(legs, count)
        self._bars(got)
        return got

    def next_minute(self, legs, stop):
        m = self._f.next_minute(legs, stop)
        if m is not None:
            self._bars([m])
        return m

    def quote(self, leg):
        q = self._f.quote(leg)
        if q.last is not None and q.last > 0:
            self._last[leg.name] = q.last
        return q

    def is_open(self, leg, now):
        return self._f.is_open(leg, now)

    def now(self):
        return self._f.now()

    def sleep(self, seconds, stop):
        self._f.sleep(seconds, stop)


class _RunJournal(Journal):
    """`log` 줄의 마지막 몇 개를 들고 있는 기록(`status()["logs_tail"]`)."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.logs: deque = deque(maxlen=LOGS_TAIL)

    def write(self, kind: str, **data: Any) -> dict:
        rec = super().write(kind, **data)
        if kind == "log":
            self.logs.append(rec)
        return rec


def _live_feed(**kw: Any) -> Feed:
    return LiveFeed(**kw)


# ---------------------------------------------------------------- 실행
class SpreadRun:
    """스프레드 실행 하나. Registry 가 만들고 `prepare()` 뒤 데몬 스레드에서 `run_forever()` 를 돌린다.

    `status()`·`request_stop()`·`order_syms()` 는 잠그지 않는다(정리 대기가 몇 시간이어도 화면이 기다리지 않게)."""

    def __init__(self, run_id: str, folder: Path, loaded: LoadedRunner, spec: SpreadSpec, *,
                 api_module: ModuleType | Any = default_api, now: Callable[[], datetime] = now_kst,
                 sleep: Callable[[float], None] = time.sleep, feed_factory: Callable[..., Feed] = _live_feed,
                 master: Callable[[], tuple[list, list]] = master_rows,
                 active_env: Callable[[], str | None] = runtime.active_environment,
                 inherited: dict[str, dict] | None = None, roll_guard: Callable[[str], None] | None = None,
                 timing: Timing = Timing()):
        self.run_id, self.folder, self.loaded, self.spec = run_id, Path(folder), loaded, spec
        self.now, self.sleep, self.timing = now, sleep, timing
        self._api, self._master, self._active_env, self._roll_guard = api_module, master, active_env, roll_guard
        self.kind = "spread"
        self.orders = spec.mode == "orders"
        #: 이어받은 시작 보유 {다리: {qty, avg_price}} — registry(Task 8)가 확인 순간 다시 읽은 잔고로 채운다
        self.inherited = copy.deepcopy(inherited) if inherited else None
        self.handed_to: str | None = None      # 이 실행을 이어받은 새 실행 id (registry 가 씀)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.j = _RunJournal(self.folder / "journal.jsonl")
        self.apilog = ApiLog(self.folder / "api_log.jsonl", run_id)
        self._last: dict[str, float] = {}
        self.feed = _Seen(feed_factory(now=now, on_wait=self._on_wait, on_gap=self._on_gap,
                                       on_error=self._on_feed_error), self._last)
        self.legs: dict[str, Leg] = {}
        self.sources: Sources | None = None
        self.book: AccountBook | PaperBook | None = None
        self.ctx: Ctx | None = None
        self._rec: _Recorder | None = None
        self._flattened = False                 # 앱이 정리 주문(종이 정리)을 냈다
        self.max_qty: dict[str, int] = {}
        self.orders_per_min = DEFAULT_ORDERS_PER_MIN
        self.ledger = _Ledger(None)            # 이어받은 보유는 prepare 가 값을 검사한 뒤 심는다
        self.state = "준비"
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.ended_reason: str | None = None
        self._waiting: list[str] = []
        self._lock = threading.RLock()          # prepare·finish
        self._state_lock = threading.RLock()    # 상태 바꾸기·run.json 쓰기 (여러 스레드)
        self._prepared = self._finished = self._finishing = False
        self._stop = threading.Event()          # ctx 의 중지 — 실행기 next_minute·sleep 이 깸, ctx 주문 거부
        self._shutdown_evt = threading.Event()  # 앱 종료 — 실행기·정리 대기·다시 시도 기다림을 깸
        self._runner_done = threading.Event()
        self._watch_stop = threading.Event()
        self._runner_error: BaseException | None = None
        self._stop_requested = self._shutdown = False

    # ------------------------------------------------------------ 시작
    def prepare(self) -> None:
        with self._lock, bind(self.apilog):
            if self._prepared or self._finished:
                raise StartRefused("이미 시작했거나 끝난 실행입니다")
            self.started_at = _iso(self.now())
            self._write_run()
            try:
                self._prepare()
            except StartRefused as e:
                self._refuse(str(e))
                raise
            except Exception as e:      # 조회 실패·응답 해석 실패
                msg = f"시작 준비 실패 — {error_text(e)}"
                self._refuse(msg)
                raise StartRefused(msg) from e
            self._prepared = True
            self._set_state("진행 중")

    def _prepare(self) -> None:
        spec, loaded, j = self.spec, self.loaded, self.j
        if spec.mode not in ("orders", "paper", "replay"):
            raise StartRefused(f"모르는 방식입니다: {spec.mode!r}")
        if self.orders and self._active_env() != "paper":
            raise StartRefused("모의투자 환경에서만 모의 계좌 실행을 세울 수 있습니다")
        if (spec.inherit_from or self.inherited) and not self.orders:
            raise StartRefused("이어받기는 모의 계좌 실행만 됩니다")
        specs = leg_specs(loaded, spec.syms)
        self._limits(specs)
        start = self._start_positions(specs)
        self.ledger = _Ledger(self.inherited)
        where = "리플레이 · 서버 접속 없음" if spec.mode == "replay" else "서버 paper"
        j.write("event", text=f"{where} · 주문 {'모의계좌' if self.orders else '종이'} · 스프레드")
        j.write("event", text=f"실행기 {loaded.file} · sha256 {loaded.sha256[:12]} · 다리 {specs} · "
                              f"최대 보유 {self.max_qty} · 분당 주문 {self.orders_per_min}")
        self.sources = load_sources(specs, api_module=self._api, master=self._master)
        self.legs = resolve_legs(specs, self.sources, today=self._today())
        for leg in self.legs.values():
            j.write("leg", leg=leg.name, why="시작", **{k: v for k, v in asdict(leg).items() if k != "name"})
        self._write_run()
        if self.orders:
            book = AccountBook(self.legs, self.feed, j, api_module=self._api, sleep=self.sleep, today=self._today(),
                               positions=start, now=self.now)
            with purpose("시작 잔고"):
                try:
                    held = book.balances()
                except LegError as e:
                    raise StartRefused(f"시작 잔고를 확인하지 못했습니다 — {e}") from e
            for name, leg in self.legs.items():
                want, got = start.get(name, 0), held[name]
                if got != want and spec.inherit_from:
                    raise StartRefused(f"이어받을 잔고가 바뀌었습니다 — {name}({leg.sym}) 기대 {want:+d} · 계좌 {got:+d}. "
                                       "다시 확인하세요")
                if got != want:
                    raise StartRefused(f"{name}({leg.sym}) 잔고 {got:+d}계약이 남아 있습니다 — 정리한 뒤 시작하세요")
            j.write("event", text="시작 잔고 " + " · ".join(f"{n}({lg.sym}) {held[n]:+d}" for n, lg in self.legs.items()))
        else:
            book = PaperBook(self.feed, j, positions=start)
        if self.inherited:
            j.write("event", text=f"이어받음 ← {spec.inherit_from}", inherited=self.inherited)
        self.book = book
        self._rec = _Recorder(book, self._record)
        self.ctx = Ctx(self.legs, self.feed, self._rec, j, max_qty=self.max_qty, orders_per_min=self.orders_per_min,
                       inherited=self.inherited, stop=self._stop, roll=self._roll)

    def _limits(self, specs: dict[str, str]) -> None:
        given = dict(self.spec.max_qty or {})
        extra = sorted(set(given) - set(specs))
        if extra:
            raise StartRefused(f"최대 보유에 실행기에 없는 다리: {', '.join(extra)}")
        for name in specs:
            q = given.get(name, self.loaded.max_qty or DEFAULT_MAX_QTY)
            if isinstance(q, bool) or not isinstance(q, int) or q <= 0:
                raise StartRefused(f"{name} 최대 보유는 양의 정수여야 합니다: {q!r}")
            self.max_qty[name] = q
        per = self.spec.orders_per_min if self.spec.orders_per_min is not None else DEFAULT_ORDERS_PER_MIN
        if isinstance(per, bool) or not isinstance(per, int) or per <= 0:
            raise StartRefused(f"분당 주문 수는 양의 정수여야 합니다: {per!r}")
        self.orders_per_min = per

    def _start_positions(self, specs: dict[str, str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for name, v in (self.inherited or {}).items():
            qty = v.get("qty") if isinstance(v, dict) else None
            avg = v.get("avg_price") if isinstance(v, dict) else None
            bad_avg = avg is not None and (isinstance(avg, bool) or not isinstance(avg, (int, float))
                                           or not math.isfinite(avg) or avg <= 0)
            if name not in specs or isinstance(qty, bool) or not isinstance(qty, int) or bad_avg:
                raise StartRefused(f"이어받을 보유가 맞지 않습니다: {name} {v!r}")
            if qty:
                out[name] = qty
        return out

    def _refuse(self, msg: str) -> None:
        self.j.write("event", text=f"시작 거부 · {msg}")
        self._finished = True
        self.ended_at = _iso(self.now())
        self.ended_reason = f"시작 거부: {msg}"
        with self._state_lock:
            self.state = "끝"
            self._write_run()

    # ------------------------------------------------------------ 실행 스레드
    def run_forever(self) -> None:
        if not self._prepared:
            return
        reason = "중지"
        try:
            with bind(self.apilog):
                self.j.write("event", text="실행기 시작")
                threading.Thread(target=self._run_runner, name=f"spread-runner-{self.run_id}", daemon=True).start()
                if self.orders:
                    threading.Thread(target=self._watch, name=f"spread-watch-{self.run_id}", daemon=True).start()
                reason = self._wait_runner()
        except Exception as e:      # 앱 쪽 버그 — 그래도 정리·기록은 한다
            reason = f"오류: {error_text(e)}"
        finally:
            self.finish(reason)

    def _run_runner(self) -> None:
        try:
            with bind(self.apilog), purpose("실행기"):
                self.loaded.run(self.ctx)
        except BaseException as e:      # sys.exit 도 실행기 오류 — 스레드 밖으로 내지 않는다
            self._runner_error = e
            self.j.write("event", text=f"실행기 예외 · {error_text(e)}", where=_where(e))
        finally:
            self._runner_done.set()

    def _wait_runner(self) -> str:
        """실행기가 돌려주거나 중지가 올 때까지. 중지면 실행기를 `stop_wait` 기다린다(앱 종료면 안 기다림). 끝 까닭을 돌려준다."""
        while not self._runner_done.wait(self.timing.poll):
            self._set_state(self.state)         # 장부가 멈췄으면 「확인 필요」로
            if self._stop_requested:
                break
        if not self._runner_done.is_set() and not self._shutdown:
            self.j.write("event", text=f"중지 — 실행기가 돌려주길 {self.timing.stop_wait:g}초 기다림")
            deadline = time.monotonic() + self.timing.stop_wait
            while not self._runner_done.is_set() and not self._shutdown:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._runner_done.wait(min(left, self.timing.poll))
        if not self._runner_done.is_set():
            self.j.write("event", text="실행기가 돌려주지 않음 — 그대로 두고(ctx 주문은 받지 않음) 앱이 마무리")
        err = self._runner_error
        if err is not None and not (self._stop_requested and isinstance(err, OrderRejected)):
            return f"오류: {error_text(err)}"
        if self._shutdown:
            return "앱 종료"
        return "중지" if self._stop_requested else "실행기가 끝냄"

    def _watch(self) -> None:
        """보유 중 잔고 대조(느슨하게 — 못 읽으면 기록만). 장부 자물쇠가 주문과 섞이지 않게 한다."""
        with bind(self.apilog), purpose("잔고 대조"):
            while not self._watch_stop.wait(self.timing.reconcile):
                book = self.book
                if book is None or book.halted is not None or not self._held():
                    continue
                try:
                    bad = book.reconcile()
                except Exception as e:
                    self.j.write("event", text=f"잔고 대조 실패 — {error_text(e)}")
                    continue
                if bad:
                    self.j.write("event", text=f"확인 필요 — 계좌 잔고가 장부와 달라 주문을 멈춤 ({bad})")
                    self._set_state(self.state)

    # ------------------------------------------------------------ 끝
    def finish(self, reason: str) -> None:
        """정리·끝 잔고·요약을 쓰고 「끝」/「오류」로. 두 번 불려도 한 번만."""
        with self._lock:
            if self._finished:
                return
            self._finishing = True
            with bind(self.apilog):
                try:
                    if self._prepared:
                        reason = self._wrap_up(reason)
                except Exception as e:      # 끝내기가 실패해도 상태는 끝으로
                    self.j.write("event", text="끝내기 처리 실패", error=error_text(e))
                    reason = f"{reason} · 끝내기 처리 실패 ({error_text(e)})"
                finally:
                    self._finished = True
                    self._watch_stop.set()
                    self.ended_at = _iso(self.now())
                    self.ended_reason = reason
                    with self._state_lock:
                        self._waiting = []
                        self.state = "오류" if reason.startswith("오류") else "끝"
                        self._write_run()

    def _wrap_up(self, reason: str) -> str:
        self._stop.set()                # ctx 는 이제 주문을 받지 않는다(실행기가 아직 돌아도)
        book, j = self.book, self.j
        note = None
        if self._held() and book.halted is None:
            if not self.orders:
                note = self._flatten_paper()
            elif not self._shutdown:
                with purpose("정리 주문"):
                    self._flatten_orders()
        self._waiting = []
        if self.orders and book.halted is None:
            with purpose("끝 잔고"):
                if book.reconcile(strict=True) is None:
                    j.write("event", text="끝 잔고 대조 맞음 · " + self._positions_text())
        held = self._held()
        if book.halted is not None:
            reason = f"{reason} · 정리 안 함 — 확인 필요: {book.halted}"
            j.write("event", text=f"정리하지 않고 끝냄 — 보유 {self._positions_text()} 는 그대로. "
                                  f"계좌·주문내역을 직접 확인하세요 ({book.halted})")
        elif held and self.orders and self._shutdown:
            reason = SHUTDOWN_HOLDING if reason in ("앱 종료", "중지", "실행기가 끝냄") else f"{reason} · {SHUTDOWN_HOLDING}"
            j.write("event", text=f"앱 종료 — 보유 {self._positions_text()} 를 정리하지 않고 끝냄(다시 켠 뒤 이어받기)")
        elif note:
            reason = f"{reason} · {note}"
        elif self._flattened and not held:
            reason = f"{reason} · 보유 정리"
        self._write_summary(reason)
        return reason

    def _app_order(self, leg: Leg) -> None:
        """정리 주문 한 다리 — 자물쇠를 쥔 채 보유를 읽고 0 까지."""
        with self.book.lock:
            pos = self.book.position(leg)
            if pos:
                self._rec.order(leg, -pos, "정리")
                self._flattened = True

    def _flatten_paper(self) -> str | None:
        left = []
        for name, leg in self.legs.items():
            try:
                self._app_order(leg)
            except (OrderRejected, Halted) as e:
                left.append(f"{name} {self.book.position(leg):+d} ({e})")
        if left:
            self.j.write("event", text="종이 보유를 정리하지 못함 — " + ", ".join(left))
            return "종이 보유 정리 못 함 — " + ", ".join(left)
        return None

    def _flatten_orders(self) -> None:
        """모의 계좌 정리(모듈 설명). 끝나면 보유 0, 아니면 장부가 멈췄거나 앱 종료."""
        book, rejects, retry_at = self.book, {}, {}
        while book.halted is None and not self._shutdown:
            held = self._held()
            if not held:
                break
            closed = [n for n in held if not self.feed.is_open(self.legs[n], self.feed.now())]
            if closed:
                self._wait_flatten(closed, f"정리 대기 — {', '.join(closed)} 장 쉼, 짝을 그대로 들고 모두 열리길 기다림")
                self._shutdown_evt.wait(self.timing.poll)
                continue
            self._waiting = []
            mono = time.monotonic()
            due = [n for n in held if retry_at.get(n, 0.0) <= mono]
            if due:
                if book.reconcile(strict=True) is not None:       # 정리 주문 전 — 이미 청산됐는데 또 내지 않게
                    break
                for name in due:
                    leg = self.legs[name]
                    try:
                        self._app_order(leg)
                    except OrderRejected as e:
                        if not self.feed.is_open(leg, self.feed.now()):
                            continue                    # 보내기 직전 장이 닫힘 — 거부로 세지 않고 정리 대기로
                        rejects[name] = rejects.get(name, 0) + 1
                        self.j.write("event", text=f"정리 거부 {rejects[name]}번째 · {name}({leg.sym}) — {e}")
                        if rejects[name] >= MAX_FLATTEN_REJECTS:
                            book.halt(f"정리 주문이 {MAX_FLATTEN_REJECTS}번 거절됨 · {name}({leg.sym}) — {e}")
                            return
                        retry_at[name] = time.monotonic() + self.timing.retry
                    except Halted:
                        return
                    except Exception as e:      # 결과를 모른다 — 장부를 멈춘다
                        book.halt(f"정리 중 오류 — 결과 모름 · {name}({leg.sym}) ({error_text(e)})")
                        return
            waiting = [n for n in self._held() if retry_at.get(n, 0.0) > time.monotonic()]
            if waiting:
                self._wait_flatten(waiting, f"정리 다시 기다림 — {', '.join(waiting)} {self.timing.retry:g}초 뒤")
                left = min(retry_at[n] for n in waiting) - time.monotonic()
                self._shutdown_evt.wait(max(0.0, min(left, self.timing.poll)))

    def _wait_flatten(self, names: list[str], text: str) -> None:
        if names != self._waiting:
            self.j.write("event", text=text)
        with self._state_lock:
            self._waiting = list(names)
            self._set_state("정리 대기")

    def _write_summary(self, reason: str) -> None:
        days, total = self.ledger.snapshot()
        data: dict[str, Any] = {
            "id": self.run_id, "mode": self.spec.mode,
            "runner": {"file": self.loaded.file, "name": self.loaded.name, "title": self.loaded.title,
                       "sha256": self.loaded.sha256},
            "legs": [{**asdict(leg), **self._leg_now(leg)} for leg in self.legs.values()],
            "days": days, "total": total, "ended_reason": reason,
            "inherited_from": self.spec.inherit_from, "inherited": self.inherited, "handed_to": self.handed_to,
            "max_qty": self.max_qty, "orders_per_min": self.orders_per_min, "api": self.apilog.stats(),
        }
        if self.book is not None and self.book.halted is not None:
            data["halted"] = self.book.halted
        write_summary(self.folder, data)

    # ------------------------------------------------------------ 요청·알림 (다른 스레드에서)
    def request_stop(self, shutdown: bool = False) -> None:
        """「중지」. `shutdown`(앱 종료)이면 실행기를 기다리지 않고 모의 계좌 보유를 정리하지 않는다."""
        if shutdown:
            self._shutdown = True
            self._shutdown_evt.set()
        self._stop_requested = True
        self._stop.set()

    def _on_wait(self, state: str, closed: list[str]) -> None:
        if self._finishing:         # 끝내는 중엔 정리가 상태를 맡는다
            return
        with self._state_lock:
            self._waiting = list(closed)
            self.j.write("event", text=f"장 쉼 · {', '.join(closed)} — 열릴 때까지 기다림" if state == WAIT_CLOSED
                         else "장 열림 · 진행")
            self._set_state("장 쉼" if state == WAIT_CLOSED else "진행 중")

    def _on_gap(self, first: str, last: str, cause: str) -> None:
        self.j.write("gap", first=first, last=last, cause=cause)

    def _on_feed_error(self, text: str) -> None:
        self.j.write("event", text=f"시세 조회 실패 · {text}")

    def _record(self, leg: Leg, qty: int, price: float | None, fee: float | None, known: bool) -> None:
        self.ledger.add(leg, qty, price, fee, known, trading_date(self.now()))

    def _roll(self, name: str) -> Leg:
        """ctx.roll 콜백 — 다음 월물을 찾아 장부·run.json·기록을 바꾼다. 안 되면 `OrderRejected`(다리는 그대로)."""
        if self._stop.is_set():
            raise OrderRejected("중지됨 — 월물을 바꾸지 않음")
        old, src = self.legs[name], self.sources
        try:
            sym = next_month(old, overseas_rows=src.overseas_rows, domestic_rows=src.domestic_rows)
            new = resolve(name, sym, **src.kw(), today=self._today())
            check_ticks({name: new}, src.overseas_details)
        except (LegError, StartRefused) as e:
            raise OrderRejected(f"월물 교체 안 됨 — {e}") from e
        if any(leg.sym == new.sym for n, leg in self.legs.items() if n != name):
            raise OrderRejected(f"월물 교체 안 됨 — {new.sym} 은 다른 다리의 종목")
        if self._roll_guard is not None:
            self._roll_guard(new.sym)       # 다른 모의 계좌 실행이 그 종목을 주문 중이면 거부 (registry)
        if self.orders:
            with self.book.lock, purpose("월물 교체"):
                self.book.set_leg(new)
                try:
                    held: int | None = self.book.balances().get(name)
                except LegError:
                    held = None
                if held != 0:
                    self.book.set_leg(old)
                    got = "확인 못 함" if held is None else f"{held:+d}계약"
                    raise OrderRejected(f"월물 교체 안 됨 — {new.sym} 잔고 {got}")
        self.legs = {**self.legs, name: new}
        self.j.write("leg", leg=name, why="월물 교체", old=old.sym,
                     **{k: v for k, v in asdict(new).items() if k != "name"})
        self._write_run()
        return new

    def mark_handed_to(self, new_id: str) -> None:
        """이 (끝난) 실행을 새 실행이 이어받았다 — run.json 에 남긴다(registry 가 부름)."""
        self.handed_to = new_id
        self._write_run()

    # ------------------------------------------------------------ 상태
    def order_syms(self) -> set[str]:
        """이 실행이 주문하는(주문할) 종목 — 「같은 종목 모의 계좌 실행은 하나」의 키. 월물 교체 뒤엔 새 종목."""
        if self.legs:
            return {leg.sym for leg in self.legs.values()}
        return set((self.spec.syms or {}).values())

    def _today(self) -> str:
        return to_kst(self.now()).strftime("%Y%m%d")

    def _held(self) -> dict[str, int]:
        book = self.book
        if book is None:
            return {}
        return {n: p for n, leg in self.legs.items() if (p := book.position(leg))}

    def _positions_text(self) -> str:
        return " · ".join(f"{n}({leg.sym}) {self.book.position(leg):+d}" for n, leg in self.legs.items())

    def _leg_now(self, leg: Leg) -> dict[str, Any]:
        return {"position": self.book.position(leg) if self.book else 0, "avg_price": self.ledger.avg(leg.name),
                "last": self._last.get(leg.name)}

    def _head(self) -> dict[str, Any]:
        return {"id": self.run_id, "file": self.loaded.file, "name": self.loaded.name, "title": self.loaded.title,
                "mode": self.spec.mode, "state": self.state, "started_at": self.started_at,
                "ended_at": self.ended_at, "ended_reason": self.ended_reason}

    def status(self) -> dict:
        """화면(Task 11)에 보일 지금 상태(칸 순서 고정)."""
        days, total = self.ledger.snapshot()
        return {
            **self._head(),
            "halted": self.book.halted if self.book else None,
            "legs": [{"name": leg.name, "sym": leg.sym, "market": leg.market, "currency": leg.currency,
                      **self._leg_now(leg)} for leg in self.legs.values()],
            "pnl_today": days.get(trading_date(self.now()), {}), "pnl_total": total,
            "waiting_for": list(self._waiting),
            "inherited_from": self.spec.inherit_from, "handed_to": self.handed_to,
            "logs_tail": list(self.j.logs),
        }

    def _set_state(self, state: str) -> None:
        """끝난 실행은 그대로, 장부가 멈췄으면 「확인 필요」."""
        with self._state_lock:
            if self.state in FINISHED:
                return
            if self.book is not None and self.book.halted is not None:
                state = "확인 필요"
            if state != self.state:
                self.state = state
                self._write_run()

    def _write_run(self) -> None:
        with self._state_lock:
            data: dict[str, Any] = {
                **self._head(), "sha256": self.loaded.sha256, "kind": self.kind,
                "legs": [asdict(leg) for leg in self.legs.values()],
                "max_qty": self.max_qty, "orders_per_min": self.orders_per_min,
                "inherited_from": self.spec.inherit_from, "inherited": self.inherited, "handed_to": self.handed_to,
                "waiting_for": list(self._waiting),
            }
            if self.book is not None and self.book.halted is not None:
                data["halted"] = self.book.halted
            write_run_json(self.folder, data)
