"""실행 관리 — 실행을 세우고(시작 거부 규칙), 기록 폴더 이름을 정하고, 목록을 내고, 앱을 끌 때·켤 때 정리한다.

    start(spec)      거부 규칙을 지나면 전략 종류(`Loaded.kind`)대로 `LiveRun`(1분봉) 또는 `RealtimeRun`(실시간)을 만들어
                     `prepare()`(부른 스레드에서) 뒤 데몬 스레드로 돌린다
    list()           도는 실행의 `status()` + `root` 아래 폴더의 `run.json` (최근 시작순, 중복 없음)
    get / folder     실행 객체 / 기록 폴더 (id 는 폴더 이름 — `[0-9A-Za-z_]+` 만, 아니면 `KeyError`)
    stop / flatten   요청만 하고 바로 돌아온다 (실제 정리는 실행 스레드의 다음 step)
    stop_all         앱을 끌 때 — 모두에게 중지를 요청하고 한 마감 시각 안에서 스레드를 기다린다
    recover          앱을 켤 때 — 끝나지 않은 채 남은 폴더를 「끝·재시작」으로 닫는다 (주문은 보내지 않는다)

시작 거부(`StartRefused`) — 폴더를 만들기 **전에** 걸리는 것(주말·장 끝·모의 환경 아님·같은 종목 주문 실행·
이상한 파일/종목 이름·미국달러선물(`A75…`)·MKU(`MKU…`)가 아닌 종목·종목의 시장과 전략 틱이 맞지 않음·신호 종목 규칙)은
폴더를 남기지 않고 메시지만 돌려줍니다. 폴더를 만든 **뒤** `prepare()` 에서 걸리는 것(시작 잔고·틱 불일치 등)은 `run.json`
(상태 「끝」, 까닭 「시작 거부: …」)이 남습니다.

| 규칙 | 1분봉(`LiveRun`) | 실시간(`RealtimeRun`) |
|---|---|---|
| 방식 | `orders`·`paper` 만 | 같음 |
| 주말 | 거부 | 거부 |
| 모의 환경 아님 | `orders` 거부 (`paper` 는 됨) | 같음 |
| 끝 시각 뒤 | 시장 끝 시각 — 국내 15:31 · 해외 23:55 | 전략 `flatten_at` + 5분(해외 23:55 를 넘지 않음, 없으면 23:55) |
| 주문 종목(`sym`) | `A75…` 또는 `MKU…`, 전략 TICK 의 시장과 같아야 | `MKU…` 만 (전략 TICK 이 MKU 틱이어야) |
| 신호 종목(`signal_sym`) | 주면 거부 (1분봉은 안 씀) | `A75…` 만, 빈칸(None·"") = 국내 최근월물 |
| 같은 종목 모의 계좌 실행 | 주문 종목 하나에 하나 — 두 종류를 통틀어 | 같음 (신호 종목은 키가 아님) |

**시장** — 실행의 시장은 `live.run_market`(종목이 있으면 종목의 시장, 없으면 전략 TICK — MKU 틱이면 해외)로 정하고,
「장 끝」 거부 시각은 그 시장의 끝 시각입니다(국내 15:31, 해외 23:55). 주말 거부는 그대로입니다. 최근월물은 그 시장
어댑터의 `nearest()`(국내 `nearest_usd`, 해외 마스터의 `nearest_mku`)로 알아냅니다.

**같은 종목 모의 계좌 실행은 하나** — 키는 실행이 **주문하는 종목**(`order_sym`)이고 실행기 종류(1분봉·실시간)와
상관없습니다. 실시간 실행이 시세로만 보는 종목(leadlag 의 KRX)은 키가 아닙니다.

기록 폴더 이름: `<YYYYMMDD>_<NAME>_<orders|paper>[_<종목>][_<n>]`.

- 종목은 사용자가 `spec.sym` 을 줬고 **최근월물과 다를 때만** 붙입니다(안 줬거나 최근월물이면 안 붙음).
  최근월물은 `start` 에서 먼저 시장 어댑터의 `nearest()` 로 알아냅니다 — 같은 종목 검사·앞선 손절 수 세기에도
  종목을 알아야 해서 `prepare()` 뒤가 아니라 폴더를 정하기 전에 한 번 더 조회합니다(시세 조회라 주문과 무관).
- `NAME` 에는 `-` 가 있을 수 있으나 id 는 `[0-9A-Za-z_]+` 만 쓸 수 있어, 폴더 이름에서는 `-` 를 `_` 로 바꿉니다
  (`run.json` 의 `name` 은 그대로).
- 같은 이름이 이미 있으면(폴더든 도는 실행이든) `_2`, `_3` …

준비 중인 실행(`prepare()` 가 `LiveRun` 의 잠금을 쥐고 네트워크를 부르는 동안)에는 `stop`·`stop_all` 이 `request_stop()` 만 합니다 —
직접 `finish()` 를 부르면 그 잠금에서 기다리게 되므로. 준비가 끝난 `start()` 가 중지 요청을 보면 스레드를 시작하지 않고
스스로 끝냅니다(주문 없음).

**앱을 끌 때(`stop_all`)** — 두 종류 모두 `request_stop(shutdown=True)`(휴장이어도 미루지 않는 중지)를 받고, 한 마감 시각
(기본 20초) 안에서 스레드를 기다립니다. 체결 확인 중이던 실행이 그 뒤 정리 주문까지 하면 20초를 넘길 수 있고, 그 실행은
기다리지 않고 돌려줍니다(데몬 스레드라 앱과 함께 멈춤). 그렇게 끝을 못 쓴 폴더는 다음에 켤 때 `recover` 가 잔고 한 번으로
닫고, 잔고가 0 이 아니거나 못 읽으면 끝 까닭이 「재시작 · 확인 필요」입니다. 실시간 원문 구독은 `routes.pyrun_shutdown` 이
`stop_all` 뒤에 `rawfeed.close_all` 로 한 번 더 닫습니다.

스레드 규칙: `finish()` 는 체결 확인 때문에 15초 넘게 걸릴 수 있어, 실행 스레드가 살아 있는 동안엔 요청·종료
스레드에서 직접 부르지 않고 `request_stop()` 만 합니다. 스레드가 없는 실행(`start_thread=False`, 시험)만 바로 `finish("중지")`.
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
from backend.team_pyrun.journal import Journal, count_stops, entered_windows, summarize, write_summary
from backend.team_pyrun.live import LiveRun, RunSpec, StartRefused, run_market
from backend.team_pyrun.loader import Loaded, LoadError, load, strategies_dir
from backend.team_pyrun.markets import DOMESTIC, Market, adapter_for, market_of
from backend.team_pyrun.realtime import RealtimeRun, _end_at, default_feed_factory

#: 실행 id(= 폴더 이름)·종목 코드가 쓸 수 있는 글자 — 경로 문자가 섞이지 못하게 한다.
ID_PATTERN = re.compile(r"[0-9A-Za-z_]+")
logger = logging.getLogger(__name__)

#: 받는 종목 코드의 앞부분 — 미국달러선물(`A75` + 연도 + 월 + `000`). 해외 MKU(`MKU…`)는 `markets.market_of` 가 받는다.
USD_PREFIX = "A75"
#: `RunSpec.mode` 로 쓸 수 있는 값 — 폴더 이름에 들어가므로 이 둘만 받는다.
MODES = ("orders", "paper")
#: 같은 종목의 주문 실행이 이미 있다고 보는 상태.
BUSY_STATES = ("대기", "진행 중", "확인 필요")
#: 끝난 상태 — `recover()` 가 건드리지 않는다.
FINISHED_STATES = ("끝", "오류")

#: 실행 하나 — 1분봉 또는 실시간. 둘 다 prepare·run_forever·finish·request_stop(shutdown)·request_flatten·status·
#: order_sym·state·spec·run_id·folder 를 가진다.
Run = LiveRun | RealtimeRun


def _read_run_json(folder: Path) -> dict | None:
    """폴더의 `run.json`. 없거나 깨졌거나 모양이 다르면 None(목록·정리는 그런 폴더를 건너뛴다)."""
    try:
        data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Registry:
    """실행 관리. 앱에 하나(`registry()`)."""

    def __init__(self, root: Path, strategies: Path, *, now: Callable[[], datetime] = now_kst,
                 active_env: Callable[[], str | None] = runtime.active_environment, start_thread: bool = True,
                 api_module: ModuleType | Any = default_api, sleep: Callable[[float], None] = time.sleep,
                 feed_factory: Callable[..., Any] = default_feed_factory):
        self.root, self.strategies = Path(root), Path(strategies)
        self._now, self._active_env, self._start_thread = now, active_env, start_thread
        self._api, self._sleep = api_module, sleep
        self._feed_factory = feed_factory              # 실시간 실행의 원문 구독 (시험은 가짜)
        self._lock = threading.Lock()                  # 시작 검사 + 폴더 정하기를 한 줄로
        self._runs: dict[str, Run] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._preparing: set[str] = set()              # 준비 중(스레드를 시작하기 전)인 실행 id
        self._stop_asked: set[str] = set()             # 준비 중에 중지 요청이 들어온 실행 id
        self._closing = False                          # 앱을 끄는 중 — 새 실행을 받지 않는다(`close_starts`)

    # ------------------------------------------------------------ 시작
    CLOSING = "앱을 끄는 중이라 새 실행을 세우지 않습니다"

    def close_starts(self) -> None:
        """앱을 끌 때 `stop_all` **전에** 부른다 — 그 뒤로 오는 `start` 는 거부. 이미 등록된 실행은 `stop_all` 이 본다
        (등록과 이 표지 검사가 같은 잠금 안이라, 표지 뒤에 등록되는 실행은 없다). 자동 시작 루프가 준비 조회 중이던 시작도 막힌다."""
        with self._lock:
            self._closing = True

    def start(self, spec: RunSpec) -> dict:
        """실행을 세우고 그 `status()` 를 돌려준다. 거부되면 `StartRefused`(전략 파일·생성 실패 포함)."""
        if self._closing:
            raise StartRefused(self.CLOSING)
        if spec.mode not in MODES:
            raise StartRefused(f"실행 방식이 올바르지 않습니다: {spec.mode!r} (orders 또는 paper)")
        now = to_kst(self._now())
        if now.weekday() >= 5:
            raise StartRefused("주말에는 실행을 시작할 수 없습니다 (토·일은 장이 없습니다)")
        if spec.mode == "orders" and self._active_env() != "paper":
            raise StartRefused("모의투자 환경에서만 모의 계좌 실행을 세울 수 있습니다")
        if Path(spec.file).name != spec.file or not spec.file.endswith(".py"):
            raise StartRefused(f"전략 파일 이름이 올바르지 않습니다: {spec.file!r}")
        if spec.sym is not None and not ID_PATTERN.fullmatch(spec.sym):
            raise StartRefused(f"종목 코드가 올바르지 않습니다: {spec.sym!r}")
        signal_sym = spec.signal_sym or None           # 빈칸("") = 국내 최근월물(실행이 prepare 에서 찾음)
        if signal_sym is not None:
            if not ID_PATTERN.fullmatch(signal_sym):
                raise StartRefused(f"신호 종목 코드가 올바르지 않습니다: {signal_sym!r}")
            try:
                signal_market = market_of(signal_sym)
            except ValueError:
                signal_market = None
            if signal_market is not DOMESTIC:
                raise StartRefused(f"신호 종목(KRX)은 미국달러선물(A75…)이어야 합니다: {signal_sym}")
        if spec.sym is not None:
            # 틱·틱가치는 시장마다 그 품목 줄(국내 `usd_spec`, 해외 `mku_spec`)로만 확인한다 — 다른 종목은 받지 않는다
            try:
                market_of(spec.sym)
            except ValueError as e:
                raise StartRefused("미국달러선물(A75…)·SGX 미니 원달러(MKU…) 종목만 실행할 수 있습니다") from e
        try:
            loaded = load(self.strategies, spec.file)
        except LoadError as e:
            raise StartRefused(f"전략 파일을 불러오지 못했습니다 — {e}") from e
        realtime = loaded.kind == "realtime"
        if signal_sym is not None and not realtime:
            raise StartRefused("신호 종목은 실시간 전략(on_krx·on_quote)에서만 씁니다 — 1분봉 전략은 비워 두세요")
        market, refusal = run_market(spec.sym, loaded)
        if refusal:                                     # 시장 가드 — 폴더도 조회도 없이
            raise StartRefused(refusal)
        if realtime and market is DOMESTIC:             # 실시간 실행은 MKU 만 주문한다 (KRX 는 시세만)
            raise StartRefused(f"실시간 실행은 MKU 만 주문합니다 — 전략 TICK {loaded.tick:g} 는 MKU 틱(0.0001)이 아닙니다")
        end, end_what = (self._realtime_end(loaded, market), "실행 끝 시각") if realtime else (market.end_time, "장이 끝난 시각")
        if now.strftime("%H%M%S") >= end:
            raise StartRefused(f"{end_what}({end[:2]}:{end[2:4]}) 뒤에는 실행을 시작할 수 없습니다")
        spec = RunSpec(spec.file, spec.mode, spec.sym, signal_sym)
        nearest = self._nearest(market)                 # 잠금 밖 — 조회가 느려도 다른 시작을 막지 않게
        sym = spec.sym or nearest
        if sym is None:     # 종목을 모르면 같은 종목 검사·손절 이어받기를 할 수 없다 — 열어 두고 가지 않는다
            raise StartRefused("최근월물을 알 수 없습니다 — 잠시 뒤 다시 시작하세요")
        today = now.strftime("%Y%m%d")
        with self._lock:
            if self._closing:                           # 준비 조회 중에 앱을 끄기 시작했다 — 등록하지 않는다
                raise StartRefused(self.CLOSING)
            if spec.mode == "orders" and sym is not None:
                for other in self._runs.values():
                    # 키 = 주문하는 종목 (실행기 종류와 무관 — 실시간 실행도 같은 이름 `order_sym` 을 가진다)
                    if (other.spec.mode == "orders" and other.state in BUSY_STATES
                            and getattr(other, "order_sym", other.sym) == sym):
                        raise StartRefused(f"같은 종목 {sym} 의 모의 계좌 실행이 이미 있습니다 ({other.run_id}) — "
                                           "끝낸 뒤에 시작하세요")
            run_id = self._new_id(today, loaded.name, spec, nearest)
            earlier = self._folders_of(today, loaded.name, sym, spec.mode)
            stops_before = count_stops(earlier, today)
            windows_before = entered_windows(earlier, today)    # 개장마다 한 번 — 앞선 실행이 들어간 개장
            try:    # 전략 생성자(`loaded.new()`)가 여기서 불린다 — 고장 나도 빈 폴더를 남기지 않고 거부로
                run: Run
                if realtime:
                    # 원문 구독(RawFeed)은 prepare 가 만든다 — 그 prepare 는 아래에서 **부른 스레드**(라우트의 스레드 풀)에서 돈다
                    run = RealtimeRun(run_id, self.root / run_id, loaded, spec, api_module=self._api,
                                      feed_factory=self._feed_factory, now=self._now, sleep=self._sleep,
                                      active_env=self._active_env, stops_before=stops_before)
                else:
                    run = LiveRun(run_id, self.root / run_id, loaded, spec, api_module=self._api, now=self._now,
                                  sleep=self._sleep, stops_before=stops_before, windows_before=windows_before)
            except Exception as e:
                shutil.rmtree(self.root / run_id, ignore_errors=True)
                raise StartRefused(f"전략을 만들지 못했습니다 — {type(e).__name__}: {e}") from e
            run.sym = sym                               # 준비가 끝나기 전에도 같은 종목 검사가 풀린 종목으로 비교하게
            self._runs[run_id] = run                    # 준비 중에도 같은 종목 검사에 걸리도록 잠금 안에서 등록
            self._preparing.add(run_id)
        try:
            run.prepare()                               # 부른 스레드에서. 오래 걸려도 잠금은 이미 풀었다
        except StartRefused:
            with self._lock:
                self._runs.pop(run_id, None)            # run.json(끝·시작 거부)은 폴더에 남았다
                self._preparing.discard(run_id)
                self._stop_asked.discard(run_id)
            raise
        with self._lock:
            stop_asked = run_id in self._stop_asked
            if self._start_thread and not stop_asked:
                thread = threading.Thread(target=run.run_forever, name=f"pyrun-{run_id}", daemon=True)
                self._threads[run_id] = thread
                thread.start()
                self._preparing.discard(run_id)
        if stop_asked:      # 준비 중에 중지 요청이 왔다 — 스레드 없이 여기서 끝낸다(주문 없음). 그동안은 준비 중으로 남겨 둔다
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

    @staticmethod
    def _realtime_end(loaded: Loaded, market: Market) -> str:
        """실시간 실행의 끝 시각(HHMMSS) — 실행과 같은 규칙(`realtime._end_at`, 전략 기본 Params 의 flatten_at + 5분)."""
        # 폴더를 만들기 전에 거르는 미리 보기일 뿐 — 실제 Params 로 하는 확정 검사는 `RealtimeRun.prepare()` 의 끝 시각 검사다
        try:
            params = loaded.params_cls()
        except Exception:           # 기본 Params 를 못 만들면 실행 생성에서 거부된다 — 여기선 시장 끝 시각으로
            return market.end_time
        return _end_at(params, market.end_time)[0]

    def _nearest(self, market: Market) -> str | None:
        """그 시장의 최근월물 종목. 조회가 안 되면 경고를 남기고 None(종목도 안 준 시작은 `start` 가 거부한다)."""
        try:
            return adapter_for(market, self._api).nearest()
        except Exception as e:
            logger.warning("최근월물 조회 실패 — %s", error_text(e))
            return None

    def _new_id(self, today: str, name: str, spec: RunSpec, nearest: str | None) -> str:
        """폴더 이름(= id). 이미 있으면 `_2`, `_3` …"""
        base = f"{today}_{name.replace('-', '_')}_{spec.mode}"
        if spec.sym and spec.sym != nearest:
            base += f"_{spec.sym}"
        run_id, n = base, 2
        while (self.root / run_id).exists() or run_id in self._runs:
            run_id, n = f"{base}_{n}", n + 1
        return run_id

    def _folders_of(self, today: str, name: str, sym: str | None, mode: str) -> list[Path]:
        """오늘 같은 전략·같은 종목·**같은 방식**으로 돌았던 폴더들(손절 수를 이어받을 곳). 새 폴더는 아직 없다.

        방식(`run.json` 의 `mode`)이 다르면 세지 않는다(R28) — 종이 실행의 손절이 모의 계좌 실행의 하루 손절 한도를
        쓰지 않고, 반대도 마찬가지."""
        if sym is None or not self.root.is_dir():
            return []
        out = []
        for folder in sorted(self.root.iterdir()):
            if not (folder.is_dir() and folder.name.startswith(f"{today}_")):
                continue
            data = _read_run_json(folder)
            if data is not None and data.get("name") == name and data.get("sym") == sym and data.get("mode") == mode:
                out.append(folder)
        return out

    # ------------------------------------------------------------ 조회
    def list(self) -> list[dict]:
        """도는 실행의 `status()` 와 폴더의 `run.json` 을 합쳐 최근 시작순으로. 못 읽는 폴더는 건너뛴다."""
        rows: dict[str, dict] = {}
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir()):
                data = _read_run_json(folder) if folder.is_dir() else None
                if data is not None:
                    data.setdefault("id", folder.name)
                    rows[folder.name] = data
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            rows[run.run_id] = run.status()             # 도는 것은 폴더 기록보다 최신
        return sorted(rows.values(), key=lambda r: r.get("started_at") or "", reverse=True)

    def get(self, run_id: str) -> Run | None:
        """이 앱에서 세운 실행(끝난 것 포함). 모르면 None."""
        return self._runs.get(run_id)

    def folder(self, run_id: str) -> Path:
        """기록 폴더. id 가 `[0-9A-Za-z_]+` 가 아니거나 폴더가 없으면 `KeyError`(폴더 밖을 가리킬 수 없다)."""
        if not isinstance(run_id, str) or not ID_PATTERN.fullmatch(run_id):
            raise KeyError(run_id)
        path = self.root / run_id
        if not path.is_dir():
            raise KeyError(run_id)
        return path

    # ------------------------------------------------------------ 요청
    def _run(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _alive(self, run_id: str) -> bool:
        thread = self._threads.get(run_id)
        return thread is not None and thread.is_alive()

    def stop(self, run_id: str) -> None:
        """중지를 요청하고 바로 돌아온다(보유가 있으면 실행 스레드가 다음 step 에서 정리).
        스레드가 없는 실행(시험)만 여기서 바로 끝낸다."""
        run = self._run(run_id)
        run.request_stop()
        with self._lock:
            if run_id in self._preparing:       # 준비 중 — 잠금에서 기다리지 않는다. 준비를 마친 start() 가 끝낸다
                self._stop_asked.add(run_id)
                return
        if not self._alive(run_id) and run.state not in FINISHED_STATES:
            run.finish("중지")

    def flatten(self, run_id: str) -> None:
        """보유 정리를 요청하고 바로 돌아온다(실행은 계속)."""
        self._run(run_id).request_flatten()

    def stop_all(self, timeout: float = 20.0) -> list[str]:
        """앱을 끌 때. 1분봉·실시간 모두에게 앱 종료 중지(`request_stop(shutdown=True)`)를 요청하고 하나의 마감 시각
        (`timeout` 초) 안에서 스레드를 기다린다. 마감까지 안 끝난 실행의 id 를 돌려준다(그 실행은 건드리지 않는다 —
        스레드가 마저 끝내거나, 앱과 함께 멈추면 다음에 켤 때 `recover` 가 「재시작」/「재시작 · 확인 필요」로 닫는다)."""
        deadline = time.monotonic() + timeout
        with self._lock:
            runs = list(self._runs.items())
            preparing = set(self._preparing)
            self._stop_asked |= preparing
        for _, run in runs:
            # 앱 종료 — 휴장이어도 미루지 않는 중지(정리할 수 없으면 「확인 필요」를 run.json·summary 에 남기고 끝남)
            run.request_stop(shutdown=True)
        pending: list[str] = []
        for run_id, run in runs:
            if run_id in preparing:                     # 준비 중 — 기다리지도 직접 끝내지도 않는다
                pending.append(run_id)
                continue
            thread = self._threads.get(run_id)
            if thread is not None and thread.is_alive():
                thread.join(max(0.0, deadline - time.monotonic()))
                if thread.is_alive():
                    pending.append(run_id)
            elif run.state not in FINISHED_STATES:
                run.finish("중지")                       # 스레드가 없다 — 직접 끝내도 누구도 기다리게 하지 않는다
        return pending

    # ------------------------------------------------------------ 앱을 켤 때
    def recover(self) -> list[str]:
        """끝나지 않은 채 남은 폴더(앱이 꺼졌거나 죽은 것)를 닫고 닫은 id 를 돌려준다. **주문은 보내지 않는다.**

        1분봉·실시간 폴더 모두 같다(`run.json` 의 `kind` 와 무관). orders 는 그 종목 시장의 어댑터로 잔고를 한 번 조회해
        (해외는 쪽을 따라감 — 첫 쪽만 보는 `api.ovs_*` 를 직접 부르지 않음) `journal.jsonl` 에 남기고(못 읽으면 「확인 실패」 —
        잔고가 0 이 아니거나 못 읽으면 끝 까닭은 「재시작 · 확인 필요」), `summary.json` 이 없으면
        `trade` 줄로 만든다. 끝에 `run.json` 을 상태 「끝」·까닭 「재시작」으로 바꾼다 — 그래서 중간에 죽어도 다음에 다시 한다."""
        closed: list[str] = []
        if not self.root.is_dir():
            return closed
        for folder in sorted(self.root.iterdir()):
            data = _read_run_json(folder) if folder.is_dir() else None
            if data is None or data.get("state") in FINISHED_STATES:
                continue
            # run.json 을 **읽은 뒤에** 잠금 안에서 이 앱의 실행인지 본다: 실행은 등록(잠금 안)된 다음에야 run.json 을 쓰므로
            # (`start` → `prepare`), run.json 을 읽을 수 있었다면 그 실행은 이미 `_runs` 에 있다. 앱이 뜬 직후의 `POST /runs` 가
            # 세운 실행(상태 「대기」)을 「끝·재시작」으로 닫지 않는다.
            with self._lock:
                if folder.name in self._runs:
                    continue
            try:
                self._close(folder, data)
            except Exception as e:      # 폴더 하나가 안 닫혀도 나머지는 닫는다
                Journal(folder / "journal.jsonl").write("event", text="재시작 정리 실패", error=error_text(e))
                continue
            closed.append(folder.name)
        return closed

    def _close(self, folder: Path, data: dict) -> None:
        j, run_id, sym = Journal(folder / "journal.jsonl"), folder.name, data.get("sym")
        apilog = ApiLog(folder / "api_log.jsonl", run_id)
        ended = "재시작"
        if data.get("mode") == "orders":
            try:
                if not sym:
                    raise ValueError("종목을 모릅니다")
                ad = adapter_for(market_of(sym), self._api)   # 해외는 쪽을 따라간 잔고(첫 쪽만 보지 않음)
                with bind(apilog), purpose("잔고확인"):
                    held = ad.net_position(ad.open_interest(), sym)
                j.write("event", text=f"재시작으로 닫음 — 잔고 {sym} {held:+d}계약 (정리 주문은 보내지 않음, 계좌에서 확인하세요)")
                if held:
                    ended = "재시작 · 확인 필요"      # 보유가 남아 있다 — 깨끗한 끝으로 보이지 않게
            except Exception as e:
                ended = "재시작 · 확인 필요"          # 잔고를 못 읽었다
                j.write("event", text="재시작으로 닫음 — 잔고 확인 실패 (정리 주문은 보내지 않음, 계좌에서 확인하세요)",
                        error=error_text(e))
        if not (folder / "summary.json").exists():
            trades = [{k: v for k, v in row.items() if k != "kind"} for row in j.read() if row.get("kind") == "trade"]
            write_summary(folder, {
                "sym": sym, "market": data.get("market"), "currency": data.get("currency"),
                "kind": data.get("kind") or "minute", "signal_sym": data.get("signal_sym"),
                "trades": trades, "summary": summarize(trades),
                "account_start": None, "account_end": None, "api": apilog.stats(),
                "strategy": {k: data.get(k) for k in ("file", "name", "title", "sha256")},
                "ended_reason": ended,
            })
        data.update(state="끝", ended_reason=ended,
                    ended_at=to_kst(self._now()).replace(tzinfo=None).isoformat(timespec="seconds"))
        path = folder / "run.json"
        tmp = path.with_name(f".run.json.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


_registry: Registry | None = None
_registry_lock = threading.Lock()


def registry() -> Registry:
    """앱에 하나뿐인 `Registry`(`state_dir()/pyruns`, 전략 폴더). 처음 부를 때 만든다."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = Registry(storage.state_dir() / "pyruns", strategies_dir())
        return _registry
