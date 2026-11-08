"""스프레드 실행 관리 — 시작 거부 규칙, 폴더 이름, 목록, 중지, 앱 끌 때·켤 때, 이어받기, 두 탭 통틀어 종목 하나.

`team_pyrun.registry` 를 따른다(거부는 폴더를 만들기 **전에**, 한 잠금 안에서 검사+등록, 준비 중 중지, `close_starts` → `stop_all`).

    start(spec, expect=None)   거부 규칙을 지나면 `SpreadRun` 을 만들어 `prepare()`(부른 스레드) 뒤 데몬 스레드로 돌린다
    list / get / folder        pyrun 과 같다
    stop(id)                   요청만 하고 돌아온다 (스레드가 없는 실행만 바로 `finish("중지")`)
    stop_all(timeout)          앱을 끌 때 — 모두에게 `request_stop(shutdown=True)`, 한 마감 시각 안에서 스레드를 기다린다
                               (`finish` 는 부르지 않는다 — 정리 대기에 막힐 수 있다. 못 끝낸 폴더는 다음에 `recover` 가 닫는다)
    recover()                  앱을 켤 때 — 끝나지 않은 채 남은 폴더를 주문 없이 닫는다
    inherit_preview(id)        이어받기 확인 화면의 값 — 지금 계좌 잔고·평균가·앞선 끝 까닭·경고

시작 거부(`StartRefused`, 폴더 전): 방식(orders·paper 만) · 주말 · 모의 환경 아님(orders) · 실행기 파일 이름·오류 · 다리 찾기 실패 ·
같은 종목 모의 계좌 실행이 이미 있음(**스프레드·파이썬 전략 통틀어**) · 이어받기 조건 · 앱 끄는 중.
다리는 폴더를 만들기 전에 정확한 종목 코드까지 찾는다 — 같은 종목 검사와 폴더 이름이 진짜 종목으로 한다.

**두 탭 통틀어 종목 하나** — 키는 실행이 주문하는 종목이다. 이쪽은 파이썬 전략 쪽을 `other_busy`(pyrun 의 `busy_sym`)로 묻고,
파이썬 쪽은 이쪽의 `busy_sym` 을 묻는다. 서로의 잠금은 잡지 않고(교착 방지) 공용 잠금(`team_pyrun.registry.CROSS_LOCK`)
안에서 검사+등록을 한 줄로 세운다(자기 잠금 → 공용 잠금 순서).
**월물 교체**(`roll_guard`)는 같은 잠금 안에서 다른 주문 실행을 보고, 통과하면 그 실행의 새 종목을 **예약**한다
(`_reserved` — 실행의 `order_syms()` 가 새 종목을 보이기 전에도 다른 시작이 그 종목을 못 잡게).

**이어받기**(사람이 하는 재개, 설계 8장) 조건: 앞선 실행이 끝났고(`run.json` 상태 끝·오류) 방식 orders · `inheritable`(기계용 칸 —
끝 까닭 글을 보지 않는다) · 아직 `handed_to` 없음 · 같은 실행기 파일 · 같은 다리 종목. 다리 종목은 따로 주지 않으면 **앞선 실행의
run.json 다리 종목**을 쓴다(월물을 바꿨거나 그 사이 최근월물이 바뀌어도 미리 보기와 같은 종목) — 직접 준 종목이 앞선 것과 다르면 거부.
화면이 `inherit_preview` 로 보인 잔고를 `expect` 로 돌려주면, 시작 때 잔고를 다시 읽어 다르면 거부한다. 성공하면 앞선 실행에
`handed_to` 를 남긴다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import storage
from backend.nh_api import runtime
from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun.apilog import ApiLog, bind, purpose
from backend.team_pyrun.broker import error_text
from backend.team_pyrun.journal import Journal, write_summary
from backend.team_pyrun.live import StartRefused, write_run_json
from backend.team_pyrun.loader import LoadError
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, adapter_for
from backend.team_spread.legs import Leg, master_rows
from backend.team_spread.run import FINISHED, SpreadRun, SpreadSpec, Timing, _live_feed
from backend.team_spread.runner_files import load_runner, spreads_dir
from backend.team_spread.start import leg_specs, load_sources, resolve_legs

ID_PATTERN = re.compile(r"[0-9A-Za-z_]+")
logger = logging.getLogger(__name__)
MODES = ("orders", "paper")
RESTART_HOLD = "재시작 · 확인 필요"
RESTART_FLAT = "재시작"
CLOSING = "앱을 끄는 중이라 새 실행을 세우지 않습니다"


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _account_avg(positions: list[dict], sym: str) -> float | None:
    """잔고 줄의 계좌 평균가(`avg_pric`) — 그 종목 줄을 수량으로 가중. 칸이 없거나 양수가 아니면 None."""
    total, weight = 0.0, 0
    for row in positions:
        if str(row.get("sym", "")).strip() != sym:
            continue
        qty = int(default_api.num(row.get("opint_qty")) or 0)
        avg = default_api.num(row.get("avg_pric"))
        if not qty:
            continue
        if avg is None or avg <= 0:
            return None
        total, weight = total + avg * qty, weight + qty
    return total / weight if weight else None


def read_positions(legs: dict[str, Leg], api_module: Any) -> dict[str, tuple[int, float | None]]:
    """다리마다 (계좌 순보유, 계좌 평균가) — 시장 어댑터로, 해외는 쪽을 따라간다. 못 읽으면 예외."""
    out: dict[str, tuple[int, float | None]] = {}
    for name, leg in legs.items():
        ad = (adapter_for(OVERSEAS, api_module, exch_cd=leg.exchange, cur_cd=leg.currency)
              if leg.market == "overseas" else adapter_for(DOMESTIC, api_module))
        rows = ad.open_interest()
        qty = ad.net_position(rows, leg.sym)
        out[name] = (qty, _account_avg(rows, leg.sym) if qty else None)
    return out


def read_balances(legs: dict[str, Leg], api_module: Any) -> dict[str, int]:
    """다리마다 계좌 순보유. 못 읽으면 예외."""
    return {n: q for n, (q, _) in read_positions(legs, api_module).items()}


def _legs_of(data: dict) -> dict[str, Leg]:
    return {d["name"]: Leg(**d) for d in data.get("legs") or []}


class SpreadRegistry:
    """스프레드 실행 관리. 앱에 하나(`registry()`)."""

    def __init__(self, root: Path, folder: Path, *, now: Callable[[], datetime] = now_kst,
                 active_env: Callable[[], str | None] = runtime.active_environment, start_thread: bool = True,
                 api_module: ModuleType | Any = default_api, sleep: Callable[[float], None] = time.sleep,
                 feed_factory: Callable[..., Any] = _live_feed,
                 master: Callable[[], tuple[list, list]] = master_rows, timing: Timing = Timing(),
                 other_busy: Callable[[str], str | None] | None = None, cross_lock: Any = None):
        self.root, self.folder_of_runners = Path(root), Path(folder)
        self._now, self._active_env, self._start_thread = now, active_env, start_thread
        self._api, self._sleep, self._feed_factory = api_module, sleep, feed_factory
        self._master, self._timing = master, timing
        self._other_busy = other_busy
        self._cross = cross_lock if cross_lock is not None else threading.RLock()
        self._lock = threading.Lock()
        self._runs: dict[str, SpreadRun] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._preparing: set[str] = set()
        self._stop_asked: set[str] = set()
        self._reserved: dict[str, set[str]] = {}       # 월물 교체가 예약한 새 종목 (실행 id → 종목)
        self._claimed: set[str] = set()                # 이어받기 중이거나 이어받힌 앞선 실행 id
        self._closing = False

    # ------------------------------------------------------------ 두 탭 통틀어 종목 하나
    def _busy_runs(self):
        return [r for r in list(self._runs.values()) if r.spec.mode == "orders" and r.state not in FINISHED]

    def busy_sym(self, sym: str, *, skip: str | None = None) -> str | None:
        """그 종목을 주문하는(예약한) 모의 계좌 실행의 id. 잠그지 않는다(스냅샷)."""
        for run in self._busy_runs():
            if run.run_id != skip and (sym in run.order_syms() or sym in self._reserved.get(run.run_id, ())):
                return run.run_id
        return None

    def _check_free(self, syms, *, skip: str | None = None) -> None:
        for sym in sorted(syms):
            mine = self.busy_sym(sym, skip=skip)
            if mine:
                raise StartRefused(f"같은 종목 {sym} 의 모의 계좌 실행이 이미 있습니다 ({mine}) — 끝낸 뒤에 시작하세요")
            if self._other_busy is not None and (msg := self._other_busy(sym)):
                raise StartRefused(msg)

    def _roll_guard(self, run_id: str) -> Callable[[str], None]:
        def guard(new_sym: str) -> None:
            with self._lock, self._cross:
                self._check_free([new_sym], skip=run_id)
                self._reserved[run_id] = {new_sym}      # 실행이 새 종목을 보이기 전에도 다른 시작이 못 잡게
        return guard

    # ------------------------------------------------------------ 시작
    def close_starts(self) -> None:
        with self._lock:
            self._closing = True

    def start(self, spec: SpreadSpec, expect: dict[str, int] | None = None) -> dict:
        """실행을 세우고 그 `status()` 를 돌려준다. 거부되면 `StartRefused`.
        `expect` = 이어받기 확인 화면이 보인 다리별 잔고 — 이어받기에는 꼭 필요하다."""
        if self._closing:
            raise StartRefused(CLOSING)
        if spec.mode not in MODES:
            raise StartRefused(f"실행 방식이 올바르지 않습니다: {spec.mode!r} (orders 또는 paper)")
        now = to_kst(self._now())
        if now.weekday() >= 5:
            raise StartRefused("주말에는 실행을 시작할 수 없습니다 (토·일은 장이 없습니다)")
        if spec.mode == "orders" and self._active_env() != "paper":
            raise StartRefused("모의투자 환경에서만 모의 계좌 실행을 세울 수 있습니다")
        if Path(spec.file).name != spec.file or not spec.file.endswith(".py"):
            raise StartRefused(f"실행기 파일 이름이 올바르지 않습니다: {spec.file!r}")
        if spec.inherit_from is not None and (spec.mode != "orders" or not isinstance(spec.inherit_from, str)
                                              or not ID_PATTERN.fullmatch(spec.inherit_from)):
            raise StartRefused("이어받기는 모의 계좌 실행만, 앞선 실행 id 가 있어야 합니다")
        if spec.inherit_from:       # 이어받기 — 다리 종목은 앞선 실행의 것(직접 준 다리만 그것으로, 다르면 아래에서 거부)
            spec = replace(spec, syms={**self._prev_syms(spec.inherit_from), **(spec.syms or {})} or None)
        for name, value in (spec.syms or {}).items():
            if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
                raise StartRefused(f"다리 {name} 의 종목 표기가 올바르지 않습니다: {value!r}")
        try:
            loaded = load_runner(self.folder_of_runners, spec.file)
        except LoadError as e:
            raise StartRefused(f"실행기 파일을 불러오지 못했습니다 — {e}") from e
        today = now.strftime("%Y%m%d")
        specs = leg_specs(loaded, spec.syms)
        try:       # 잠금 밖 — 조회가 느려도 다른 시작을 막지 않게
            sources = load_sources(specs, api_module=self._api, master=self._master)
            legs = resolve_legs(specs, sources, today=today)
        except StartRefused:
            raise
        except Exception as e:
            raise StartRefused(f"다리를 찾지 못했습니다 — {error_text(e)}") from e
        spec = replace(spec, syms={n: leg.sym for n, leg in legs.items()})           # 정확한 종목 코드
        inherited, claimed = None, None
        if spec.inherit_from:
            data = self._inheritable(spec.inherit_from, spec.file, {n: leg.sym for n, leg in legs.items()})
            claimed = spec.inherit_from
            with self._lock:
                if claimed in self._claimed:
                    raise StartRefused("이미 다른 실행이 이어받았거나 이어받는 중입니다")
                self._claimed.add(claimed)
        try:
            if spec.inherit_from:
                inherited = self._confirm_inherit(spec.inherit_from, data, legs, expect)
            run_id = self._register(spec, loaded, today, legs, inherited)
        except BaseException:
            if claimed:
                with self._lock:
                    self._claimed.discard(claimed)
            raise
        run = self._runs[run_id]
        return self._prepare_and_go(run, claimed)

    def _register(self, spec: SpreadSpec, loaded, today: str, legs: dict[str, Leg], inherited: dict | None) -> str:
        with self._lock, self._cross:
            if self._closing:
                raise StartRefused(CLOSING)
            if spec.mode == "orders":
                self._check_free({leg.sym for leg in legs.values()})
            run_id = self._new_id(today, loaded.name, spec.mode)
            try:
                run = SpreadRun(run_id, self.root / run_id, loaded, spec, api_module=self._api, now=self._now,
                                sleep=self._sleep, feed_factory=self._feed_factory, master=self._master,
                                active_env=self._active_env, inherited=inherited,
                                roll_guard=self._roll_guard(run_id) if spec.mode == "orders" else None, timing=self._timing)
            except Exception as e:
                shutil.rmtree(self.root / run_id, ignore_errors=True)
                raise StartRefused(f"실행을 만들지 못했습니다 — {type(e).__name__}: {e}") from e
            self._runs[run_id] = run          # 준비 중에도 같은 종목 검사에 걸리도록 잠금 안에서 등록
            self._preparing.add(run_id)
        return run_id

    def _prepare_and_go(self, run: SpreadRun, claimed: str | None) -> dict:
        run_id = run.run_id
        try:
            run.prepare()
        except StartRefused:
            with self._lock:
                self._runs.pop(run_id, None)         # run.json(끝·시작 거부)은 폴더에 남았다
                self._preparing.discard(run_id)
                self._stop_asked.discard(run_id)
                self._reserved.pop(run_id, None)
                if claimed:
                    self._claimed.discard(claimed)
            raise
        if claimed:
            self._hand_over(claimed, run_id)
        with self._lock:
            stop_asked = run_id in self._stop_asked
            if self._start_thread and not stop_asked:
                thread = threading.Thread(target=run.run_forever, name=f"spread-{run_id}", daemon=True)
                self._threads[run_id] = thread
                thread.start()
                self._preparing.discard(run_id)
        if stop_asked:        # 준비 중에 중지 요청 — 스레드 없이 여기서 끝낸다(주문 없음)
            try:
                run.finish("중지")
            finally:
                with self._lock:
                    self._preparing.discard(run_id)
                    self._stop_asked.discard(run_id)
        elif not self._start_thread:
            with self._lock:
                self._preparing.discard(run_id)
        return run.status()

    def _new_id(self, today: str, name: str, mode: str) -> str:
        base = f"{today}_{name.replace('-', '_')}_{mode}"
        run_id, n = base, 2
        while (self.root / run_id).exists() or run_id in self._runs:
            run_id, n = f"{base}_{n}", n + 1
        return run_id

    # ------------------------------------------------------------ 이어받기
    def _inheritable(self, prev_id: str, file: str, syms: dict[str, str]) -> dict:
        """앞선 실행이 이어받을 수 있는지 — 아니면 `StartRefused`. 앞선 `run.json` 을 돌려준다."""
        try:
            folder = self.folder(prev_id)
        except KeyError:
            raise StartRefused(f"이어받을 실행을 찾지 못했습니다: {prev_id}") from None
        data = _read_json(folder / "run.json")
        live = self._runs.get(prev_id)
        if data is None:
            raise StartRefused(f"이어받을 실행의 기록을 읽지 못했습니다: {prev_id}")
        if data.get("state") not in FINISHED or (live is not None and live.state not in FINISHED):
            raise StartRefused("아직 끝나지 않은 실행은 이어받을 수 없습니다")
        if data.get("mode") != "orders":
            raise StartRefused("이어받기는 모의 계좌 실행만 됩니다")
        if data.get("inheritable") is not True:
            raise StartRefused("이 실행은 이어받을 보유가 없습니다")
        if data.get("handed_to") or (live is not None and live.handed_to):
            raise StartRefused(f"이미 {data.get('handed_to') or live.handed_to} 이(가) 이어받았습니다")
        if data.get("file") != file:
            raise StartRefused(f"다른 실행기 파일입니다: 앞선 {data.get('file')} ≠ {file}")
        for other in self.root.iterdir():       # handed_to 를 쓰기 전에 죽었어도 — 새 실행의 기록이 앞선 실행을 가리킨다
            theirs = _read_json(other / "run.json") or {}
            refused = str(theirs.get("ended_reason") or "").startswith("시작 거부")     # 시작을 거부당한 실행은 이어받지 못했다
            if other.name != prev_id and theirs.get("inherited_from") == prev_id and not refused:
                raise StartRefused(f"이미 {other.name} 이(가) 이어받았습니다")
        prev = {d.get("name"): d.get("sym") for d in data.get("legs") or []}
        if prev != syms:
            raise StartRefused(f"다리 종목이 다릅니다: 앞선 {prev} ≠ {syms}")
        return data

    def _prev_syms(self, prev_id: str) -> dict[str, str]:
        """앞선 실행 run.json 의 다리 → 종목. 못 읽으면 {} (이어받기 검사 `_inheritable` 이 까닭을 밝혀 거부한다)."""
        try:
            data = _read_json(self.folder(prev_id) / "run.json") or {}
        except KeyError:
            return {}
        return {d["name"]: d["sym"] for d in data.get("legs") or []
                if isinstance(d, dict) and isinstance(d.get("name"), str) and isinstance(d.get("sym"), str)}

    def _prev_avg(self, prev_id: str) -> dict[str, float | None]:
        summary = _read_json(self.root / prev_id / "summary.json") or {}
        return {d.get("name"): d.get("avg_price") for d in summary.get("legs") or [] if isinstance(d, dict)}

    def inherit_preview(self, run_id: str) -> dict:
        """이어받기 확인 화면 — 지금 계좌 잔고·평균가·앞선 끝 까닭·경고. 이어받을 수 없으면 `StartRefused`(까닭 글)."""
        head = self._head(run_id)
        data = self._inheritable(run_id, str(head.get("file")), {d["name"]: d["sym"] for d in head.get("legs") or []})
        legs = _legs_of(data)
        try:
            with purpose("이어받기 확인"):
                held = read_positions(legs, self._api)
        except Exception as e:
            raise StartRefused(f"계좌 잔고를 읽지 못했습니다 — {error_text(e)}") from e
        avg = self._prev_avg(run_id)
        reason = str(data.get("ended_reason") or "")
        warning = None
        if data.get("halted"):
            warning = (f"앞선 실행이 주문 결과를 모른 채 멈췄습니다 — 주문내역을 먼저 확인하세요 ({data['halted']})")
        elif data.get("balance_unread"):
            warning = "다시 켤 때 계좌 잔고를 읽지 못해 닫았습니다 — 아래 잔고가 맞는지 계좌에서 먼저 확인하세요"
        return {"id": run_id, "file": data.get("file"), "ended_reason": reason, "warning": warning,
                "syms": {n: leg.sym for n, leg in legs.items()},
                "legs": {n: {"sym": leg.sym, "qty": held[n][0], "avg_price": self._avg(held[n][1], avg.get(n))}
                         for n, leg in legs.items()}}

    @staticmethod
    def _avg(account: float | None, prev: Any) -> float | None:
        """평균가 — 계좌 잔고의 것이 먼저, 없을 때만 앞선 실행의 기록."""
        if account is not None:
            return account
        return float(prev) if isinstance(prev, (int, float)) and not isinstance(prev, bool) and prev > 0 else None

    def _head(self, run_id: str) -> dict:
        return _read_json(self.folder(run_id) / "run.json") or {}

    def _confirm_inherit(self, prev_id: str, data: dict, legs: dict[str, Leg], expect: dict[str, int] | None) -> dict:
        """시작 순간 잔고를 다시 읽어 화면이 보인 값(`expect`)과 같을 때만 `SpreadRun` 에 넘길 값(판정 R20)을 만든다."""
        if (not isinstance(expect, dict) or set(expect) != set(legs)
                or any(isinstance(v, bool) or not isinstance(v, int) for v in expect.values())):
            raise StartRefused("이어받기는 확인 화면에서 본 다리별 잔고(expect, 정수)가 있어야 합니다")
        try:
            with purpose("이어받기 확인"):
                pos = read_positions(legs, self._api)
            held = {n: q for n, (q, _) in pos.items()}
        except Exception as e:
            raise StartRefused(f"계좌 잔고를 읽지 못했습니다 — {error_text(e)}") from e
        diff = {n: (expect[n], held[n]) for n in legs if expect[n] != held[n]}
        if diff:
            raise StartRefused("확인한 뒤 계좌 잔고가 바뀌었습니다 — 다시 확인하세요 (" + ", ".join(
                f"{n} 보인 {a:+d} · 지금 {b:+d}" for n, (a, b) in diff.items()) + ")")
        avg = self._prev_avg(prev_id)
        return {"from": prev_id, "ended_reason": str(data.get("ended_reason") or ""),
                "legs": {n: {"qty": held[n], "avg_price": self._avg(pos[n][1], avg.get(n))} for n in legs}}

    def _hand_over(self, prev_id: str, new_id: str) -> None:
        live = self._runs.get(prev_id)
        try:
            if live is not None:
                live.mark_handed_to(new_id)
                return
            folder = self.root / prev_id
            for name in ("run.json", "summary.json"):
                data = _read_json(folder / name)
                if data is not None:
                    data["handed_to"] = new_id
                    _write_json(folder / name, data)
        except Exception as e:      # 새 실행은 이미 보유를 안고 있다 — 메모리 표지(_claimed)가 두 번째 이어받기를 막는다
            logger.warning("handed_to 기록 실패 — %s", error_text(e))

    # ------------------------------------------------------------ 조회
    def list(self) -> list[dict]:
        rows: dict[str, dict] = {}
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir()):
                data = _read_json(folder / "run.json") if folder.is_dir() else None
                if data is not None:
                    data.setdefault("id", folder.name)
                    rows[folder.name] = data
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            rows[run.run_id] = run.status()
        return sorted(rows.values(), key=lambda r: r.get("started_at") or "", reverse=True)

    def get(self, run_id: str) -> SpreadRun | None:
        return self._runs.get(run_id)

    def folder(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not ID_PATTERN.fullmatch(run_id):
            raise KeyError(run_id)
        path = self.root / run_id
        if not path.is_dir():
            raise KeyError(run_id)
        return path

    # ------------------------------------------------------------ 요청
    def _alive(self, run_id: str) -> bool:
        thread = self._threads.get(run_id)
        return thread is not None and thread.is_alive()

    def stop(self, run_id: str) -> None:
        """중지 요청 — 바로 돌아온다. 스레드가 없는 실행(시험)만 여기서 바로 끝낸다."""
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        run.request_stop()
        with self._lock:
            if run_id in self._preparing:
                self._stop_asked.add(run_id)
                return
        if not self._alive(run_id) and run.state not in FINISHED:
            run.finish("중지")

    def stop_all(self, timeout: float = 20.0) -> list[str]:
        """앱을 끌 때. `request_stop(shutdown=True)` 를 모두에게 하고 마감 시각 안에서 스레드를 기다린다.
        `finish` 는 부르지 않는다. 끝내지 못한 실행의 id 를 돌려준다(다음에 켤 때 `recover` 가 닫는다)."""
        deadline = time.monotonic() + timeout
        self.close_starts()
        with self._lock:
            runs = list(self._runs.items())
            self._stop_asked |= set(self._preparing)
        for _, run in runs:
            run.request_stop(shutdown=True)
        pending: list[str] = []
        for run_id, run in runs:
            thread = self._threads.get(run_id)
            if thread is not None and thread.is_alive():
                thread.join(max(0.0, deadline - time.monotonic()))
                if thread.is_alive():
                    pending.append(run_id)
            elif run.state not in FINISHED:
                pending.append(run_id)
        return pending

    # ------------------------------------------------------------ 앱을 켤 때
    def recover(self) -> list[str]:
        """끝나지 않은 채 남은 폴더(앱이 꺼졌거나 죽은 것)를 주문 없이 닫고 닫은 id 를 돌려준다."""
        closed: list[str] = []
        if not self.root.is_dir():
            return closed
        for folder in sorted(self.root.iterdir()):
            data = _read_json(folder / "run.json") if folder.is_dir() else None
            if data is None or data.get("state") in FINISHED:
                continue
            with self._lock:
                if folder.name in self._runs:
                    continue
            try:
                self._close(folder, data)
            except Exception as e:
                Journal(folder / "journal.jsonl").write("event", text="재시작 정리 실패", error=error_text(e))
                continue
            closed.append(folder.name)
        return closed

    def _close(self, folder: Path, data: dict) -> None:
        j = Journal(folder / "journal.jsonl")
        apilog = ApiLog(folder / "api_log.jsonl", folder.name)
        ended, left, unread = RESTART_FLAT, {}, False
        legs = _legs_of(data) if data.get("mode") == "orders" else {}
        if legs:
            held: dict[str, int] = {}
            try:
                with bind(apilog), purpose("잔고확인"):
                    held = read_balances(legs, self._api)
            except Exception as e:
                unread = True
                j.write("event", text="재시작으로 닫음 — 잔고 확인 실패 (정리 주문은 보내지 않음, 계좌에서 확인하세요)",
                        error=error_text(e))
            left = {n: q for n, q in held.items() if q}
            if held:
                j.write("event", text="재시작으로 닫음 — 잔고 " + " · ".join(f"{n}({legs[n].sym}) {q:+d}"
                                                                     for n, q in held.items()) + " (정리 주문은 보내지 않음)")
            if left or unread:
                ended = RESTART_HOLD
        inheritable = bool(left or unread)
        ended_at = to_kst(self._now()).replace(tzinfo=None).isoformat(timespec="seconds")
        if not (folder / "summary.json").exists():
            write_summary(folder, {
                "id": folder.name, "mode": data.get("mode"),
                "runner": {k: data.get(k) for k in ("file", "name", "title", "sha256")},
                "legs": data.get("legs") or [], "ended_reason": ended, "holding_left": left,
                "inheritable": inheritable, "inherited_from": data.get("inherited_from"),
                "handed_to": data.get("handed_to"), "api": apilog.stats(),
            })
        data.update(state="끝", ended_reason=ended, ended_at=ended_at, holding_left=left, inheritable=inheritable,
                    waiting_for=[])
        if unread:
            data["balance_unread"] = True
        write_run_json(folder, data)


_registry: SpreadRegistry | None = None
_registry_lock = threading.Lock()


def peek_registry() -> SpreadRegistry | None:
    """이미 만들어졌으면 그것(만들지 않음) — 파이썬 전략 쪽이 묻는 데 쓴다."""
    return _registry


def _pyrun_busy(sym: str) -> str | None:
    from backend.team_pyrun import registry as pyrun

    other = pyrun.peek_registry()
    run_id = other.busy_sym(sym) if other is not None else None
    if run_id is None:
        return None
    return f"같은 종목 {sym} 의 파이썬 전략 모의 계좌 실행이 이미 있습니다 ({run_id}) — 끝낸 뒤에 시작하세요"


def registry() -> SpreadRegistry:
    """앱에 하나뿐인 `SpreadRegistry`(`state_dir()/spreads`, 실행기 폴더). 처음 부를 때 만든다."""
    global _registry
    with _registry_lock:
        if _registry is None:
            from backend.team_pyrun.registry import CROSS_LOCK

            _registry = SpreadRegistry(storage.state_dir() / "spreads", spreads_dir(), other_busy=_pyrun_busy,
                                       cross_lock=CROSS_LOCK)
        return _registry
