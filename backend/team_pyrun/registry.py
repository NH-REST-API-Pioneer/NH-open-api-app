"""실행 관리 — 실행을 세우고(시작 거부 규칙), 기록 폴더 이름을 정하고, 목록을 내고, 앱을 끌 때·켤 때 정리한다.

    start(spec)      거부 규칙을 지나면 전략 종류(`Loaded.kind`)대로 `LiveRun`(1분봉) 또는 `RealtimeRun`(실시간)을 만들어
                     `prepare()`(부른 스레드에서) 뒤 데몬 스레드로 돌린다
    list()           도는 실행의 `status()` + `root` 아래 폴더의 `run.json` (최근 시작순, 중복 없음)
    get / folder     실행 객체 / 기록 폴더 (id 는 폴더 이름 — `[0-9A-Za-z_]+` 만, 아니면 `KeyError`)
    stop / flatten   요청만 하고 바로 돌아온다 (실제 정리는 실행 스레드의 다음 step)
    request_stop_all 앱을 끌 때 첫 단계 — 새 시작을 막고 모두에게 앱 종료 중지만 알린다(기다리지 않음). 스프레드 탭과 함께 끌 때
                     둘 다 먼저 알린 뒤 함께 기다린다(`team_spread.routes.team_stop_begin` — 한쪽을 기다리는 동안 다른 쪽이 매매하지 않게)
    stop_all         앱을 끌 때 — 모두에게 중지를 요청하고 한 마감 시각 안에서 스레드를 기다린다
    recover          앱을 켤 때 — 끝나지 않은 채 남은 폴더를 「끝·재시작」으로 닫는다 (주문은 보내지 않는다).
                     잔고 어댑터는 `run.json` 의 `market`·`exchange`(해외는 `currency` 도)로 — 그 칸이 없는 옛 기록은 `market_of(sym)`
    resolve_product  종목 칸(품목 뿌리·종목 코드) → `Leg` (`find`, 기본 `products.find_product`). 매일 자동 시작도 씀

시작 거부(`StartRefused`) — 폴더를 만들기 **전에** 걸리는 것(주말·끝 시각 뒤·모의 환경 아님·같은 종목 주문 실행·
이상한 파일/종목 이름·찾지 못한 종목·종목의 시장(또는 틱·틱가치)과 전략 틱이 맞지 않음·신호 종목 규칙·실시간 종목 칸의
품목 뿌리·계획만으로 보이는 거부 `live.plan_refusal`)은 폴더를 남기지 않고 메시지만 돌려줍니다. 폴더를 만든 **뒤**
`prepare()` 에서 걸리는 것(시작 잔고·틱 불일치·07:00 에 걸친 시작 등)은 `run.json`(상태 「끝」, 까닭 「시작 거부: …」)이
남습니다.

| 규칙 | 1분봉(`LiveRun`) | 실시간(`RealtimeRun`) |
|---|---|---|
| 방식 | `orders`·`paper` 만 | 같음 |
| 주말 | 거부 — 실행의 날짜로(자정 넘는 전략은 거래일: 토요일 새벽 = 금요일) | 거부 (달력 날짜) |
| 모의 환경 아님 | `orders` 거부 (`paper` 는 됨) | 같음 |
| 끝 시각 뒤 | 실행 끝(`run_plan(...).end`) — 국내 15:31 · 해외 `flatten_at` + 5분, 실행의 시계로 | 전략 `flatten_at` + 5분(해외 23:55 를 넘지 않음, 없으면 23:55) |
| 주문 종목(`sym`) | 빈칸 · `A75…`/`MKU…` 코드(지금 길) · 품목 뿌리나 다른 코드(종목 찾기 — 아래) | `MKU…` 종목 코드만 — 뿌리 `MKU` 는 거부 (전략 TICK 이 MKU 틱이어야) |
| 신호 종목(`signal_sym`) | 주면 거부 (1분봉은 안 씀) | `A75…` 종목 코드만(뿌리 `A75` 는 거부), 빈칸(None·"") = 국내 최근월물 |
| 계획만으로 보이는 거부 | `live.plan_refusal` — 국내 자정 넘음·MKU 아닌 품목의 빠진 장 시간 칸·해외 끝 07:00 넘음 (끝 시각 검사 앞) | — |
| 같은 종목 모의 계좌 실행 | 주문 종목 하나에 하나 — 두 종류를 통틀어 | 같음 (신호 종목은 키가 아님) |

**1분봉 실행의 종목 칸(설계 4.1)** — 세 갈래, 모두 폴더·실행 조회 전에 정합니다.

- **빈칸**: 지금 길 — 시장은 `live.run_market`(전략 TICK — MKU 틱이면 해외), 최근월물은 그 시장 어댑터의 `nearest()`
  (국내 `nearest_usd`, 해외 마스터의 `nearest_mku`). 다리(`Leg`) 없음.
- **정확한 `A75…`·`MKU…` 코드**(세 글자 뿌리는 아님 — 지금 종목 고르기가 보내는 것): 지금 길 그대로 — `run_market` 의
  시장 가드(종목의 시장 ≠ 전략 TICK 의 시장이면 거부), 최근월물은 `nearest()`, 틱은 `prepare` 가 서버로 확인. 마스터·
  품목 세부정보를 새로 읽지 않습니다(설계 5장 — 지금과 같아야 함). 찾은 값도 지금 상수와 같습니다.
- **품목 뿌리(`HO`·`A01`, `A75`·`MKU` 포함)와 다른 종목 코드**: `resolve_product` 로 찾은 `Leg` 가 실행의 종목(뿌리면 그날
  달력 날짜의 최근월물). 전략 `TICK`·`TICK_VALUE` 가 그 종목과 다르면 거부(`products.strategy_tick_refusal`), 계좌는 종목을
  따라(`products.account_market`). 찾기가 거부하면 그 글 그대로, 다른 예외는 「종목을 찾지 못했습니다 — …」.

**실행의 날짜·시계** — 1분봉은 `live.run_plan(loaded, 시장)` 의 시계로 셉니다. 자정을 넘는 전략은 거래일(07:00 에 바뀜)과
거래일 시계(07:00 전 +24)라 토요일 01:00 은 금요일 거래일의 `"250000"` 이고, 화요일 06:59 는 월요일 거래일의 `"305900"`
입니다. 주말 거부·끝 시각 뒤 거부(문구의 시각은 `tradeday.clock_text` — 「05:00 (+1)」)·폴더 날짜·「오늘 앞선 실행」
(손절 수·들어간 개장)이 이 날짜입니다. 자정을 넘지 않는 전략은 달력 그대로라 지금과 같습니다. 그래서 주말 거부는 전략을
불러온 뒤에 봅니다. 실시간 실행은 달력 날짜 그대로입니다.

**장 판정** — 1분봉 실행에 `judge`·`day_end`·`master_knows` 를 그대로 넘깁니다(`LiveRun(judge=, day_end=, master_knows=)`).
시험이 직접 만드는 `Registry` 는 None(지금 규칙), 앱의 `registry()` 만 운영자 판정(`opening.default_judge`·`default_day_end`)과
마스터 확인(`opening.default_master_knows` — 판정이 종목을 모를 때 거부 글을 가름)을 꽂습니다.

**07:00 에 걸친 시작** — 폴더 이름·앞선 손절 수는 여기서 센 거래일로 정하고, 그 거래일을 `LiveRun(trading_date=)` 로
넘깁니다. 실행 준비가 센 거래일이 다르면(06:59:58 에 시작해 준비가 07:00:01) 준비가 거부합니다.

**같은 종목 모의 계좌 실행은 하나** — 키는 실행이 **주문하는 종목**(`order_sym`)이고 실행기 종류(1분봉·실시간)와
상관없습니다. 실시간 실행이 시세로만 보는 종목(leadlag 의 KRX)은 키가 아닙니다.

기록 폴더 이름: `<YYYYMMDD>_<NAME>_<orders|paper>[_<종목>][_<n>]`.

- 날짜는 실행의 날짜(자정 넘는 전략은 거래일).
- 종목은 사용자가 `spec.sym` 을 줬고 실행의 종목이 **최근월물과 다를 때만** 붙입니다(안 줬거나 최근월물이면 안 붙음).
  빈칸·`A75…`/`MKU…` 코드의 최근월물은 `start` 에서 먼저 시장 어댑터의 `nearest()` 로 알아냅니다 — 같은 종목 검사·앞선
  손절 수 세기에도 종목을 알아야 해서 `prepare()` 뒤가 아니라 폴더를 정하기 전에 한 번 더 조회합니다(시세 조회라 주문과
  무관). 종목 찾기로 고른 종목은 뿌리를 줬으면 그것이 최근월물(안 붙음), 코드를 줬으면 최근월물인지 모르므로(더 조회하지
  않음) 붙습니다 — 최근월물을 모를 때 붙이는 지금 규칙과 같습니다.
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

import contextlib
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
from backend.team_pyrun import opening, products
from backend.team_pyrun.apilog import ApiLog, bind, purpose
from backend.team_pyrun.broker import error_text
from backend.team_pyrun.journal import Journal, count_stops, entered_windows, summarize, write_summary
from backend.team_pyrun.live import LEGLESS_PRODUCT, LiveRun, RunSpec, StartRefused, plan_refusal, run_market, run_plan
from backend.team_pyrun.loader import Loaded, LoadError, load, strategies_dir
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, Market, MarketAdapter, adapter_for, market_of
from backend.team_pyrun.opening import DayEnd, Judge, MasterKnows
from backend.team_pyrun.products import account_market, strategy_tick_refusal
from backend.team_pyrun.realtime import RealtimeRun, _end_at, default_feed_factory
from backend.team_pyrun.tradeday import clock_text
from backend.team_spread.legs import Leg

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


def legacy_code(sym: str) -> bool:
    """정확한 미국달러선물(`A75…`)·MKU(`MKU…`) 종목 코드인가 — 1분봉 실행이 지금 길(다리 없음)로 도는 종목 칸.

    세 글자 품목 뿌리(`A75`·`MKU`)는 아니다(뿌리는 `resolve_product` 가 그날의 최근월물로 고른다). 매일 자동 시작
    (`autostart.Schedules.create`)도 이 함수로 같은 갈래를 고른다 — 두 곳이 갈라지지 않게 하나만 둔다."""
    if len(sym) <= len(USD_PREFIX):
        return False
    try:
        market_of(sym)
    except ValueError:
        return False
    return True


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
                 feed_factory: Callable[..., Any] = default_feed_factory,
                 other_busy: Callable[[str], str | None] | None = None, cross_lock: Any = None,
                 judge: Judge | None = None, day_end: DayEnd | None = None,
                 find: Callable[..., Leg] = products.find_product, master_knows: MasterKnows | None = None):
        # 팀: 스프레드 탭과 「같은 종목 모의 계좌 실행은 하나」를 통틀어 지키는 갈고리 — 없으면 동작은 그대로.
        #   other_busy(sym) = 다른 쪽이 그 종목을 주문 중이면 거부 글, 아니면 None (다른 쪽 잠금은 잡지 않는다)
        #   cross_lock = 두 쪽이 검사+등록을 한 줄로 서게 하는 공용 잠금 (자기 잠금 → 공용 잠금 순서)
        self._other_busy, self._cross = other_busy, cross_lock or contextlib.nullcontext()
        # 1분봉 실행에 그대로 넘기는 장 판정·해외 거래일 끝·판정이 모를 때 글을 가르는 마스터 확인(None = 지금 규칙,
        # 앱의 `registry()` 는 운영자 판정·마스터)과 종목 칸 찾기(`products.find_product` — 시험은 가짜)
        self._judge, self._day_end, self._find = judge, day_end, find
        self._master_knows = master_knows
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
    WEEKEND = "주말에는 실행을 시작할 수 없습니다 (토·일은 장이 없습니다)"
    NO_NEAREST = "최근월물을 알 수 없습니다 — 잠시 뒤 다시 시작하세요"

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
        # 주말 거부는 전략을 불러온 뒤 — 자정을 넘는 1분봉 전략은 거래일로 센다(토요일 새벽 = 금요일 거래일)
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
            if not legacy_code(signal_sym):     # 뿌리 `A75` 는 종목이 아니다 — 원문 구독·시세가 그 이름으로 가지 않게
                raise StartRefused("신호 종목(KRX)은 미국달러선물 종목 코드(A756B000 등)를 적어야 합니다 — "
                                   "품목 뿌리는 받지 않습니다")
        try:
            loaded = load(self.strategies, spec.file)
        except LoadError as e:
            raise StartRefused(f"전략 파일을 불러오지 못했습니다 — {e}") from e
        realtime = loaded.kind == "realtime"
        if signal_sym is not None and not realtime:
            raise StartRefused("신호 종목은 실시간 전략(on_krx·on_quote)에서만 씁니다 — 1분봉 전략은 비워 두세요")
        spec = RunSpec(spec.file, spec.mode, spec.sym, signal_sym)
        # 폴더·실행 조회 전에 걸리는 것과 (종목 다리, 주문 종목, 최근월물, 실행의 날짜). 조회(종목 찾기·최근월물)는 잠금 밖 —
        # 느려도 다른 시작을 막지 않게
        if realtime:
            leg, (sym, nearest, today) = None, self._realtime_target(spec, loaded, now)
        else:
            leg, sym, nearest, today = self._minute_target(spec, loaded, now)
        with self._lock, self._cross:
            if self._closing:                           # 준비 조회 중에 앱을 끄기 시작했다 — 등록하지 않는다
                raise StartRefused(self.CLOSING)
            if spec.mode == "orders" and self._other_busy is not None and (msg := self._other_busy(sym)):  # 팀:
                raise StartRefused(msg)
            if spec.mode == "orders" and sym is not None:
                for other in self._runs.values():
                    # 키 = 주문하는 종목 (실행기 종류와 무관 — 실시간 실행도 같은 이름 `order_sym` 을 가진다)
                    if (other.spec.mode == "orders" and other.state in BUSY_STATES
                            and getattr(other, "order_sym", other.sym) == sym):
                        raise StartRefused(f"같은 종목 {sym} 의 모의 계좌 실행이 이미 있습니다 ({other.run_id}) — "
                                           "끝낸 뒤에 시작하세요")
            run_id = self._new_id(today, loaded.name, spec, sym, nearest)
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
                                  sleep=self._sleep, stops_before=stops_before, windows_before=windows_before,
                                  leg=leg, judge=self._judge, day_end=self._day_end,
                                  master_knows=self._master_knows, trading_date=today)
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

    def _realtime_target(self, spec: RunSpec, loaded: Loaded, now: datetime) -> tuple[str, str | None, str]:
        """실시간 실행의 (주문 종목, 최근월물, 실행의 날짜) — 지금 규칙 그대로(달력 날짜·`market_of`·`_realtime_end`)."""
        if now.weekday() >= 5:
            raise StartRefused(self.WEEKEND)
        if spec.sym is not None:
            # 틱·틱가치는 시장마다 그 품목 줄(국내 `usd_spec`, 해외 `mku_spec`)로만 확인한다 — 다른 종목은 받지 않는다
            try:
                market_of(spec.sym)
            except ValueError as e:
                raise StartRefused("미국달러선물(A75…)·SGX 미니 원달러(MKU…) 종목만 실행할 수 있습니다") from e
            if not legacy_code(spec.sym):
                # 실시간 길은 품목을 찾지 않는다 — 뿌리 `MKU` 가 그대로 주문 종목이 되면 주문이 「MKU」로 나가고
                # 잔고 줄(`MKUX26`)과 맞지 않아 잔고 관문이 보지 못한다
                raise StartRefused("실시간 실행은 MKU 종목 코드(MKUX26 등)를 적어야 합니다 — 품목 뿌리는 받지 않습니다")
        market, refusal = run_market(spec.sym, loaded)
        if refusal:                                     # 시장 가드 — 폴더도 조회도 없이
            raise StartRefused(refusal)
        if market is DOMESTIC:                          # 실시간 실행은 MKU 만 주문한다 (KRX 는 시세만)
            raise StartRefused(f"실시간 실행은 MKU 만 주문합니다 — 전략 TICK {loaded.tick:g} 는 MKU 틱(0.0001)이 아닙니다")
        end = self._realtime_end(loaded, market)
        if now.strftime("%H%M%S") >= end:
            raise StartRefused(f"실행 끝 시각({end[:2]}:{end[2:4]}) 뒤에는 실행을 시작할 수 없습니다")
        nearest = self._nearest(market)
        sym = spec.sym or nearest
        if sym is None:     # 종목을 모르면 같은 종목 검사·손절 이어받기를 할 수 없다 — 열어 두고 가지 않는다
            raise StartRefused(self.NO_NEAREST)
        return sym, nearest, now.strftime("%Y%m%d")

    def _minute_target(self, spec: RunSpec, loaded: Loaded, now: datetime) -> tuple[Leg | None, str, str | None, str]:
        """1분봉 실행의 (종목 다리, 주문 종목, 최근월물, 실행의 날짜) — 설계 4.1·4.4·4.5.

        지금 길(다리 없음 — `run_market`·`_nearest`, 틱은 `prepare` 의 서버 틱 확인): 종목 칸이 비었거나(전략 TICK 의 시장)
        정확한 미국달러선물·MKU 종목 코드(`legacy_code` — 지금 종목 고르기가 보내는 것. 마스터·품목 세부정보를 새로 읽지
        않게). 그 밖(품목 뿌리 — `A75`·`MKU` 포함 — 와 다른 종목 코드)은 `resolve_product` 로 찾은 `Leg` 가 실행의 종목이고,
        전략 `TICK`·`TICK_VALUE` 가 그 종목과 다르면 거부한다. 계획만으로 보이는 거부(`live.plan_refusal`)를 주말·끝 시각
        검사보다 먼저 본다. 주말·「끝 시각 뒤」는 실행의 시계(`run_plan(...).clock`) — 자정을 넘는 전략은 거래일(07:00 에
        바뀜)과 거래일 시계(07:00 전 +24)로, 아니면 달력 그대로. 돌려준 거래일은 `LiveRun(trading_date=)` 로 넘긴다."""
        leg: Leg | None = None
        if spec.sym and not legacy_code(spec.sym):
            leg = self.resolve_product(spec.sym)        # 마스터·품목 세부정보 조회 (주문과 무관)
            if (refusal := strategy_tick_refusal(leg, loaded)):
                raise StartRefused(refusal)
            if not ID_PATTERN.fullmatch(leg.sym):       # 폴더 이름에 들어간다
                raise StartRefused(f"종목 코드가 올바르지 않습니다: {leg.sym!r}")
            market = account_market(leg)
        else:
            market, refusal = run_market(spec.sym, loaded)
            if refusal:                                 # 시장 가드 — 종목의 시장과 전략 틱의 시장이 다름. 폴더도 조회도 없이
                raise StartRefused(refusal)
        try:
            plan = run_plan(loaded, market)
        except Exception as e:      # Params 시각 칸이 이상함 — 실행 생성에서와 같은 거부로, 폴더 전에
            raise StartRefused(f"전략을 만들지 못했습니다 — {type(e).__name__}: {e}") from e
        # 계획만으로 보이는 거부(국내 자정 넘음·MKU 아닌 품목의 빠진 장 시간 칸·07:00 넘는 끝) — 실행 준비와 같은 글로,
        # 끝 시각 검사보다 먼저(빠진 칸을 시장 값으로 채운 끝 시각 글이 진짜 까닭을 가리지 않게)·폴더 전에
        product = leg.product if leg is not None else LEGLESS_PRODUCT[market.id][0]
        if (why := plan_refusal(loaded, market, product, plan)):
            raise StartRefused(why)
        today, clock = plan.clock.label(now)
        if datetime.strptime(today, "%Y%m%d").weekday() >= 5:
            raise StartRefused(self.WEEKEND)
        if clock >= plan.end:
            end_what = "장이 끝난 시각" if market is DOMESTIC else "실행 끝 시각"
            raise StartRefused(f"{end_what}({clock_text(plan.end)}) 뒤에는 실행을 시작할 수 없습니다")
        if leg is None:
            nearest = self._nearest(market)
            sym = spec.sym or nearest
            if sym is None:     # 종목을 모르면 같은 종목 검사·손절 이어받기를 할 수 없다 — 열어 두고 가지 않는다
                raise StartRefused(self.NO_NEAREST)
            return None, sym, nearest, today
        # 폴더 이름용 최근월물 — 뿌리를 줬으면 고른 종목이 그것. 종목 코드면 모른다(조회를 더 하지 않음) → 이름에 종목이 붙는다
        nearest = leg.sym if spec.sym == leg.product else None
        return leg, leg.sym, nearest, today

    def resolve_product(self, spec: str) -> Leg:
        """종목 칸(품목 뿌리 `HO`·`A01` 또는 종목 코드 `HOZ26`) → `Leg`. 최근월물은 **지금 달력 날짜**로 고른다.

        못 찾으면 `StartRefused`(찾기의 글 그대로, 그 밖의 예외는 「종목을 찾지 못했습니다 — …」). 조회(마스터 파일·품목
        세부정보)라 registry 잠금 밖에서 부른다. 매일 자동 시작도 이것으로 그날의 최근월물을 고른다."""
        today = to_kst(self._now()).strftime("%Y%m%d")
        try:
            return self._find(spec, api_module=self._api, today=today)
        except StartRefused:
            raise
        except Exception as e:
            raise StartRefused(f"종목을 찾지 못했습니다 — {error_text(e)}") from e

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

    def _new_id(self, today: str, name: str, spec: RunSpec, sym: str, nearest: str | None) -> str:
        """폴더 이름(= id). 종목 칸을 줬고 실행의 종목(`sym`)이 최근월물과 다를 때만 그 종목을 붙인다. 이미 있으면 `_2`, `_3` …"""
        base = f"{today}_{name.replace('-', '_')}_{spec.mode}"
        if spec.sym and sym != nearest:
            base += f"_{sym}"
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

    def busy_sym(self, sym: str) -> str | None:
        """그 종목을 주문 중인 모의 계좌 실행의 id(없으면 None) — 스프레드 탭이 묻는다. 잠그지 않는다(스냅샷만 읽음)."""
        for other in list(self._runs.values()):
            if (other.spec.mode == "orders" and other.state in BUSY_STATES
                    and getattr(other, "order_sym", other.sym) == sym):
                return other.run_id
        return None

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

    def request_stop_all(self) -> None:
        """앱을 끌 때 첫 단계 — `close_starts` 하고 모든 실행(준비 중 포함)에 `request_stop(shutdown=True)` 만 한다.
        기다리지도 끝내지도 않는다 — 뒤이은 `stop_all` 이 기다린다(다시 알려도 같다)."""
        self.close_starts()
        with self._lock:
            runs = list(self._runs.values())
            self._stop_asked |= set(self._preparing)
        for run in runs:
            run.request_stop(shutdown=True)

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
                ad = self._recorded_adapter(data, sym)       # 해외는 쪽을 따라간 잔고(첫 쪽만 보지 않음)
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

    def _recorded_adapter(self, data: dict, sym: str) -> MarketAdapter:
        """다시 켤 때 잔고를 볼 어댑터 — 종목 코드를 다시 해석하지 않고 `run.json` 의 `market`·`exchange`(해외는 `currency` 도)로
        (설계 4.7). 그 칸이 없는 옛 기록(실시간 실행 포함)은 지금처럼 `market_of(sym)`."""
        market, exchange = data.get("market"), data.get("exchange")
        if market == "domestic" and exchange:
            return adapter_for(DOMESTIC, self._api)
        if market == "overseas" and exchange:
            return adapter_for(OVERSEAS, self._api, exch_cd=str(exchange), cur_cd=data.get("currency") or None)
        return adapter_for(market_of(sym), self._api)


_registry: Registry | None = None
_registry_lock = threading.Lock()


def registry() -> Registry:
    """앱에 하나뿐인 `Registry`(`state_dir()/pyruns`, 전략 폴더). 처음 부를 때 만든다.

    1분봉 실행의 장 판정은 여기서만 운영자 시간표(`opening.default_judge`·`default_day_end`)와 마스터 확인
    (`opening.default_master_knows`)을 꽂는다 — 시험이 직접 만드는 `Registry` 는 판정 없이(지금 규칙) 돈다(판정 R2)."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = Registry(storage.state_dir() / "pyruns", strategies_dir(),
                                 other_busy=_spread_busy, cross_lock=CROSS_LOCK,
                                 judge=opening.default_judge, day_end=opening.default_day_end,
                                 find=products.find_product, master_knows=opening.default_master_knows)
        return _registry


#: 파이썬 전략·스프레드 두 레지스트리가 「같은 종목 하나」 검사와 등록을 한 줄로 서게 하는 공용 잠금
CROSS_LOCK = threading.RLock()


def peek_registry() -> Registry | None:
    """이미 만들어졌으면 그것(만들지 않음) — 스프레드 쪽이 묻는 데 쓴다."""
    return _registry


def _spread_busy(sym: str) -> str | None:
    """스프레드 탭이 그 종목을 주문 중이면 거부 글. 늦게 불러오고(순환 import 피함) 스프레드 레지스트리를 새로 만들지 않는다."""
    from backend.team_spread import registry as spread

    other = spread.peek_registry()
    run_id = other.busy_sym(sym) if other is not None else None
    if run_id is None:
        return None
    return f"같은 종목 {sym} 의 스프레드 모의 계좌 실행이 이미 있습니다 ({run_id}) — 끝낸 뒤에 시작하세요"
