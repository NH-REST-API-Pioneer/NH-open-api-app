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
  정리할지 정하는 첫 보유 읽기도 `book.lock` 안에서 — 실행기 주문이 나가는 중이면 그 체결까지 본다. 끝내기를 시작하면
  (`closing` — `_finishing`·앱 종료) ctx 는 짝 되돌리기를 내지 않고 시세 조회도 내보내지 않는다(남은 반쪽은 여기 정리가 맡거나,
  앱 종료면 장부에 남아 `inheritable`).
  - 멈춤(확인 필요)이면 정리하지 않는다.
  - 모의 계좌: 보유한 다리가 모두 주문할 수 있으면(`feed.order_open` — 국내 다리는 09:00 부터) 잔고를 엄격히 대조한 뒤
    다리마다 시장가로 0 까지. 하나라도 쉬면
    「정리 대기」 — 짝을 그대로 들고 모두 열릴 때까지. 거부된 다리는 열린 다리를 마저 정리한 뒤 10초 뒤 다시,
    3번(처음 + 다시 2번, 파이썬 전략 실시간과 같음) 안 되면 멈춤. 결과를 모르면 장부가 멈춘다.
  - 종이·재생: 계좌가 없어 장이 쉬어도 기다리지 않고 지금 시세로 장부만 0 (앱 종료 때도 — 이어받을 계좌 보유가 없음).
- 앱 종료(`shutdown=True`): 실행기를 기다리지 않고 모의 계좌 보유를 정리하지 않는다(정리 대기 중이었어도, 정리 전 대조
  중에 와도 첫 정리 주문 전에 멈춤). 보유가 남으면 끝 까닭 「앱 종료 · 보유 남음 — 이어받기로 다시」.
- 끝난 run.json·summary.json·`status()` 의 `holding_left`(다리 → 남은 보유)·`inheritable`(모의 계좌가 보유를 남기고 끝남 —
  앱 종료·오류·정리 거부 — 또는 멈춤: 결과 모르는 주문이 장부를 안 움직였어도 계좌엔 있을 수 있어 확인 화면이 실제 잔고를 읽게)
  가 기계용 표시다(판정 R21). registry 는 이것으로 「이어받기」를 보이고, 끝 까닭 글은 사람용이다.
  끝내기 자체가 실패해도 장부를 멈추고 요약·이 칸을 남긴다(보유를 든 채 표시 없이 「끝」이 되지 않게).
- 끝 확인은 `reconcile(strict=True)` — 잔고를 못 읽으면 깨끗하게 끝났다고 하지 않는다.

손익은 `pnl.Ledger`(거래일 07:00 경계·통화별·체결가 모름은 추정), 다리 찾기는 `start`(registry 도 같은 함수).
이어받기 값은 prepare 가 한 번 고른다(판정 R20): `{"from", "ended_reason", "legs": {다리: {"qty", "avg_price"}}}`.
시세 공급의 조회 오류·공백 까닭은 기록 전에 토큰·키 값을 가린다(`apilog.redact`).

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
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from backend.nh_api import runtime
from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun.apilog import ApiLog, bind, purpose, redact
from backend.team_pyrun.broker import error_text
from backend.team_pyrun.journal import Journal, write_summary
from backend.team_pyrun.live import StartRefused, write_run_json
from backend.team_spread.book import AccountBook, PaperBook
from backend.team_spread.ctx import DEFAULT_MAX_QTY, Ctx, Halted, OrderRejected
from backend.team_spread.feed import WAIT_CLOSED, Feed, LiveFeed, order_open
from backend.team_spread.legs import Leg, LegError, master_rows, next_month, resolve
from backend.team_spread.pnl import Ledger, trading_date
from backend.team_spread.runner_files import LoadedRunner
from backend.team_spread.start import Sources, check_ticks, leg_specs, load_sources, resolve_legs

DEFAULT_ORDERS_PER_MIN = 10
MAX_FLATTEN_REJECTS = 3             # 정리 주문이 결과를 아는 거부로 이만큼(처음 + 다시 2번) 안 되면 멈춤
SHUTDOWN_HOLDING = "앱 종료 · 보유 남음 — 이어받기로 다시"
LOGS_TAIL = 20
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


def _iso(at: datetime) -> str:
    return to_kst(at).replace(tzinfo=None).isoformat(timespec="seconds")


def _where(e: BaseException) -> list[str]:
    """예외 자리(파일:줄 함수)만 — 값·문구는 남기지 않는다."""
    return [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in traceback.extract_tb(e.__traceback__)[-6:]]


# ---------------------------------------------------------------- 대리 (ctx 가 보는 장부·시세, 기록)
class _Recorder:
    """ctx·정리가 쓰는 장부 — 진짜 장부로 보내고 돌아온 체결(또는 예외 뒤 바뀐 보유)을 손익에 센다.
    보유 읽기 → 주문 → 보유 읽기를 `book.lock` 안에서 해 다른 스레드의 주문이 끼지 않는다."""

    def __init__(self, book: Any, record: Callable[[Leg, int, float | None, float | None, bool], None]):
        self._book, self._record = book, record

    @property
    def lock(self) -> Any:
        """진짜 장부의 자물쇠 — ctx 가 체결과 그 직후 보유 읽기·되돌리기 확인을 앱 정리와 섞지 않게 쓴다."""
        return self._book.lock

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

    def __init__(self, feed: Feed, last: dict[str, float], journal: Journal | None = None):
        self._f, self._last, self._j = feed, last, journal

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
            self._journal_minute(m)
        return m

    def _journal_minute(self, m) -> None:
        """받은 분봉 한 묶음을 `minute` 줄로 남긴다(차트용 — 다리별 종가와 채운 봉 표시). 준비 봉(`history`)은 남기지 않는다
        (시작 때 한꺼번에 오는 많은 줄이 일지를 채우지 않게). 기록 실패는 실행을 막지 않는다."""
        if self._j is None:
            return
        try:
            self._j.write("minute", date=m.date, time=m.time,
                          legs={n: {"close": b.close, "filled": b.filled} for n, b in m.legs.items()})
        except OSError:
            pass

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
                 timing: Timing = Timing(), legs: dict[str, Leg] | None = None,
                 paper_book: Callable[..., PaperBook] = PaperBook):
        self.run_id, self.folder, self.loaded, self.spec = run_id, Path(folder), loaded, spec
        self.now, self.sleep, self.timing = now, sleep, timing
        self._api, self._master, self._active_env, self._roll_guard = api_module, master, active_env, roll_guard
        self.kind = "spread"
        #: 재생(`replay.py`)만 쓰는 두 자리 — 다리를 마스터·서버 없이 직접 받고, 종이 장부를 바꿔 끼운다
        self._fixed_legs = dict(legs) if legs is not None else None
        self._paper_book = paper_book
        self.orders = spec.mode == "orders"
        #: 이어받기(판정 R20) — registry(Task 8)가 확인 순간 다시 읽은 잔고로 채워 넘긴 값. prepare 가 한 번 고른 뒤
        #: `{"from": 앞선 실행 id, "ended_reason": 글, "legs": {다리: {"qty": int, "avg_price": float | None}}}` 만 남는다
        #: (ctx.inherited·run.json·summary 가 같은 꼴). 고르기 전엔 None
        self._inherited_raw = copy.deepcopy(inherited) if inherited else None
        self.inherited: dict | None = None
        self.inherited_from: str | None = spec.inherit_from
        self.handed_to: str | None = None      # 이 실행을 이어받은 새 실행 id (registry 가 씀)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.j = _RunJournal(self.folder / "journal.jsonl")
        self.apilog = ApiLog(self.folder / "api_log.jsonl", run_id)
        self._last: dict[str, float] = {}
        self.feed = _Seen(feed_factory(now=now, on_wait=self._on_wait, on_gap=self._on_gap,
                                       on_error=self._on_feed_error), self._last, self.j)
        self.legs: dict[str, Leg] = {}
        self.sources: Sources | None = None
        self.book: AccountBook | PaperBook | None = None
        self.ctx: Ctx | None = None
        self._rec: _Recorder | None = None
        self._flattened = False                 # 앱이 정리 주문(종이 정리)을 냈다
        self.max_qty: dict[str, int] = {}
        self.orders_per_min = DEFAULT_ORDERS_PER_MIN
        self.ledger = Ledger(None)            # 이어받은 보유는 prepare 가 값을 검사한 뒤 심는다
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
        if (spec.inherit_from or self._inherited_raw) and not self.orders:
            raise StartRefused("이어받기는 모의 계좌 실행만 됩니다")
        specs = leg_specs(loaded, spec.syms)
        self._limits(specs)
        start = self._inherit(specs)
        self.ledger = Ledger(self.inherited["legs"] if self.inherited else None)
        where = "리플레이 · 서버 접속 없음" if spec.mode == "replay" else "서버 paper"
        j.write("event", text=f"{where} · 주문 {'모의계좌' if self.orders else '종이'} · 스프레드")
        j.write("event", text=f"실행기 {loaded.file} · sha256 {loaded.sha256[:12]} · 다리 {specs} · "
                              f"최대 보유 {self.max_qty} · 분당 주문 {self.orders_per_min}")
        if self._fixed_legs is not None:
            self.sources, self.legs = self._fixed(specs)
        else:
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
                if got != want and self.inherited:
                    raise StartRefused(f"이어받을 잔고가 바뀌었습니다 — {name}({leg.sym}) 기대 {want:+d} · 계좌 {got:+d}. "
                                       "다시 확인하세요")
                if got != want:
                    raise StartRefused(f"{name}({leg.sym}) 잔고 {got:+d}계약이 남아 있습니다 — 정리한 뒤 시작하세요")
            j.write("event", text="시작 잔고 " + " · ".join(f"{n}({lg.sym}) {held[n]:+d}" for n, lg in self.legs.items()))
        else:
            book = self._paper_book(self.feed, j, positions=start)
        if self.inherited:
            j.write("event", text=f"이어받음 ← {self.inherited_from}", inherited=self.inherited)
        self.book = book
        self._rec = _Recorder(book, self._record)
        self.ctx = Ctx(self.legs, self.feed, self._rec, j, max_qty=self.max_qty, orders_per_min=self.orders_per_min,
                       inherited=self.inherited, stop=self._stop, roll=self._roll, closing=self.closing)

    def _fixed(self, specs: dict[str, str]) -> tuple[Sources, dict[str, Leg]]:
        """재생이 직접 준 다리 — 마스터·품목 세부정보를 읽지 않는다(월물 교체는 마스터가 없어 거절됨)."""
        legs = self._fixed_legs
        if self.spec.mode != "replay":
            raise StartRefused("다리를 직접 주는 건 재생만 됩니다")
        if set(legs) != set(specs):
            raise StartRefused(f"다리가 실행기와 맞지 않습니다: {sorted(legs)} ≠ {sorted(specs)}")
        syms = [leg.sym for leg in legs.values()]
        if len(set(syms)) != len(syms):
            raise StartRefused(f"두 다리가 같은 종목입니다: {', '.join(syms)}")
        return Sources([], [], [], []), dict(legs)

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

    def _inherit(self, specs: dict[str, str]) -> dict[str, int]:
        """이어받기 값을 한 번 고르고(판정 R20 꼴, 다른 칸은 버림) 시작 보유(0 아닌 다리)를 돌려준다. 이어받기가 아니면 {}."""
        raw, frm = self._inherited_raw, self.spec.inherit_from
        if raw is None and frm is None:
            return {}
        if not isinstance(raw, dict):
            raise StartRefused("이어받을 보유가 없습니다 — 앞선 실행의 잔고를 다시 확인하세요")
        frm = frm or raw.get("from")
        if not frm or raw.get("from") not in (None, frm):
            raise StartRefused(f"이어받을 실행이 맞지 않습니다: {raw.get('from')!r} ≠ {frm!r}")
        legs = raw.get("legs")
        if not isinstance(legs, dict) or not legs:
            raise StartRefused(f"이어받을 다리가 없습니다: {legs!r}")
        out: dict[str, dict] = {}
        for name, v in legs.items():
            qty = v.get("qty") if isinstance(v, dict) else None
            avg = v.get("avg_price") if isinstance(v, dict) else None
            bad_avg = avg is not None and (isinstance(avg, bool) or not isinstance(avg, (int, float))
                                           or not math.isfinite(avg) or avg <= 0)
            if name not in specs or isinstance(qty, bool) or not isinstance(qty, int) or bad_avg:
                raise StartRefused(f"이어받을 보유가 맞지 않습니다: {name} {v!r}")
            out[name] = {"qty": qty, "avg_price": None if avg is None else float(avg)}
        self.inherited = {"from": frm, "ended_reason": str(raw.get("ended_reason") or ""), "legs": out}
        self.inherited_from = frm
        return {n: v["qty"] for n, v in out.items() if v["qty"]}

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
            self._refresh_state()               # 장부가 멈췄으면 「확인 필요」로
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
                    self._refresh_state()

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
                except Exception as e:      # 끝내기가 실패해도 — 멈춤 표시·요약·남은 보유를 남기고 끝으로 (판정 R22d)
                    why = f"끝내기 처리 실패 ({error_text(e)})"
                    self.j.write("event", text=why, where=_where(e))
                    self._stop.set()
                    if self.book is not None:
                        self.book.halt(why)
                    halted = self.book.halted if self.book is not None else why
                    reason = f"{reason} · 정리 안 함 — 확인 필요: {halted}" + ("" if halted == why else f" · {why}")
                    try:
                        self._write_summary(reason)
                    except Exception as e2:
                        self.j.write("event", text="요약 쓰기 실패", error=error_text(e2))
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
        with book.lock:                 # 실행기 주문이 나가는 중이면 그 체결까지 본 보유로 정한다(놓치고 「정리할 것 없음」이 되지 않게)
            held = self._held()
        if held and book.halted is None:
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
        with book.lock:
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
            closed = [n for n in held if not order_open(self.feed, self.legs[n], self.feed.now())]
            if closed:
                self._wait_flatten(closed, f"정리 대기 — {', '.join(closed)} 장 쉼(국내는 09:00 전 포함), "
                                           "짝을 그대로 들고 모두 주문할 수 있길 기다림")
                self._shutdown_evt.wait(self.timing.poll)
                continue
            self._waiting = []
            mono = time.monotonic()
            due = [n for n in held if retry_at.get(n, 0.0) <= mono]
            if due:
                if book.reconcile(strict=True) is not None:       # 정리 주문 전 — 이미 청산됐는데 또 내지 않게
                    break
                if self._shutdown:      # 대조하는 동안 앱 종료 — 첫 정리 주문 전에 멈춘다(다리 사이에선 멈추지 않음: 반쪽 짝)
                    return
                for name in due:
                    leg = self.legs[name]
                    try:
                        self._app_order(leg)
                    except OrderRejected as e:
                        if not order_open(self.feed, leg, self.feed.now()):
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
            "inherited_from": self.inherited_from, "inherited": self.inherited, "handed_to": self.handed_to,
            "max_qty": self.max_qty, "orders_per_min": self.orders_per_min, "api": self.apilog.stats(),
        }
        if self.book is not None and self.book.halted is not None:
            data["halted"] = self.book.halted
        data.update(self._end_marks())
        write_summary(self.folder, data)

    # ------------------------------------------------------------ 요청·알림 (다른 스레드에서)
    def closing(self) -> bool:
        """앱이 끝내는 중인가 — 끝내기를 시작했거나(`finish`, 중지 뒤 기다림이 지남) 앱 종료. ctx 가 본다."""
        return self._finishing or self._shutdown

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
        self.j.write("gap", first=first, last=last, cause=redact(cause))       # 까닭에 조회 오류 글이 실린다

    def _on_feed_error(self, text: str) -> None:
        self.j.write("event", text=f"시세 조회 실패 · {redact(text)}")        # 인증 오류 글엔 토큰이 실릴 수 있다

    def _record(self, leg: Leg, qty: int, price: float | None, fee: float | None, known: bool) -> None:
        self.ledger.add(leg, qty, price, fee, known, trading_date(self.now()))

    def _roll(self, name: str) -> Leg:
        """ctx.roll 콜백 — 다음 월물을 찾아 장부·run.json·기록을 바꾼다. 안 되면 `OrderRejected`(다리는 그대로).
        멈춘 실행(확인 필요)이면 `Halted` — 결과 모르는 주문이 있는데 종목을 바꾸면 그 주문의 대조가 엉뚱한 종목으로 간다."""
        if self._stop.is_set():
            raise OrderRejected("중지됨 — 월물을 바꾸지 않음")
        self._check_not_halted()
        old, src = self.legs[name], self.sources
        try:
            sym = next_month(old, overseas_rows=src.overseas_rows, domestic_rows=src.domestic_rows)
            new = resolve(name, sym, **src.kw(), today=self._today())
            check_ticks({name: new}, src.overseas_details)
        except (LegError, StartRefused) as e:
            raise OrderRejected(f"월물 교체 안 됨 — {e}") from e
        if any(leg.sym == new.sym for n, leg in self.legs.items() if n != name):
            raise OrderRejected(f"월물 교체 안 됨 — {new.sym} 은 다른 다리의 종목")
        if self._roll_guard is not None:    # 다른 모의 계좌 실행이 그 종목을 주문 중이면 거부 (registry)
            try:
                self._roll_guard(new.sym)
            except OrderRejected:
                raise
            except Exception as e:      # registry 의 StartRefused 등 — 실행기에겐 늘 OrderRejected
                raise OrderRejected(f"월물 교체 안 됨 — {new.sym}: {e}") from e
        if self.orders:
            with self.book.lock, purpose("월물 교체"):
                self._check_not_halted()
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

    def _check_not_halted(self) -> None:
        if self.book is not None and self.book.halted is not None:
            raise Halted(f"멈춤: {self.book.halted} — 월물을 바꾸지 않음")

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
        """화면(Task 11)에 보일 지금 상태(칸 순서 고정). 끝난 실행엔 run.json 과 같은 기계용 칸(`holding_left`·`inheritable`)을
        끝에 붙인다 — 메모리에 남은 끝난 실행도 화면이 「이어받기」·「끝날 때 남은 보유」를 보이게."""
        days, total = self.ledger.snapshot()
        data = {
            **self._head(),
            "halted": self.book.halted if self.book else None,
            "legs": [{"name": leg.name, "sym": leg.sym, "market": leg.market, "currency": leg.currency,
                      **self._leg_now(leg)} for leg in self.legs.values()],
            "pnl_today": days.get(trading_date(self.now()), {}), "pnl_total": total,
            "waiting_for": list(self._waiting),
            "inherited_from": self.inherited_from, "handed_to": self.handed_to,
            "logs_tail": list(self.j.logs),
        }
        if self._finished:
            data.update(self._end_marks())
        return data

    def _refresh_state(self) -> None:
        """지금 상태를 다시 본다(장부 멈춤 → 「확인 필요」). 상태 읽기도 자물쇠 안에서 — 다른 스레드의 「장 쉼」을 덮지 않게."""
        with self._state_lock:
            self._set_state(self.state)

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
                "inherited_from": self.inherited_from, "inherited": self.inherited, "handed_to": self.handed_to,
                "waiting_for": list(self._waiting),
            }
            if self.book is not None and self.book.halted is not None:
                data["halted"] = self.book.halted
            if self._finished:
                data.update(self._end_marks())
            write_run_json(self.folder, data)

    def _end_marks(self) -> dict[str, Any]:
        """끝난 실행의 기계용 칸(판정 R21) — registry(Task 8)는 끝 까닭 글이 아니라 이것을 본다.
        `holding_left` = 끝날 때 장부에 남은 보유, `inheritable` = 모의 계좌 실행이 보유를 남기고 끝남
        (앱 종료·오류·정리 거부 — 「이어받기」로 다시 세울 수 있다) **또는 멈춤** — 결과 모르는 주문이 장부를 안 움직였어도
        계좌엔 들어갔을 수 있다. 확인 화면이 실제 계좌 잔고를 읽어 보이므로 사람이 보고 정한다."""
        left = self._held()
        halted = self.book is not None and self.book.halted is not None
        return {"holding_left": left, "inheritable": self.orders and (bool(left) or halted)}
