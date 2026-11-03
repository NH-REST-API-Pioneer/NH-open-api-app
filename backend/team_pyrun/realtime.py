"""실시간 실행 — leadlag(week03 `ws_trader.py` 의 `Engine`) 같은 **초 단위** 전략을 앱 안에서 돌린다.

판단(진입·청산)은 전략 파일의 `Engine` 이 하고, 이 실행기가 하는 일은 네 가지뿐입니다.

1. 허브가 묶기 전의 원문(`rawfeed.RawFeed`)을 **받은 순서 그대로** Engine 에 넣는다 (ws_trader `Trader.on_dom`·`on_ovs`·`timer` 와 같게).
2. Engine 이 돌려준 행동(`{"act": "enter"|"exit", "side": ±1, "ref": …}`)을 안전하게 체결한다 — MKU 1계약,
   「모의 계좌」는 해외 어댑터 위의 `MockAccountBroker`, 「종이」는 반대 호가.
3. 모두 기록한다(`journal.jsonl` · `summary.json` · `api_log.jsonl` · `run.json`).
4. 1분봉 `LiveRun` 과 같은 생애(prepare → run_forever → finish, 중지·정리 요청, 상태 낱말)를 돈다.

    prepare()        시작 검사 → 원문 구독(마지막에). 안 되면 `StartRefused`(run.json 은 「끝」으로 남김, 주문 없음)
    handle(item)     원문 하나·공백 표지 하나 — 그 시각까지 밀린 1초 타이머를 먼저 돌리고 넣는다 (리플레이도 이 길)
    fire_timer(t)    Engine.on_timer(t, 그 순간 벽시계 HHMMSS) 한 번
    start_timers_at(t)  첫 타이머 시각 — 녹화 리플레이(`replay.replay_realtime`)가 첫 원문 시각으로 둘 때만
    step(now)        1초 한 번 살림 — 밀린 타이머, 끝 시각·중지·정리 요청, 잔고 대조, 청산 재시도, 1분 줄
    run_forever()    실행 스레드 본문. 끝나면(예외 포함) finish, 원문 구독은 언제나 닫음
    finish(reason)   보유 정리(멈춘 실행은 안 함)·끝 잔고·요약. 두 번 불려도 한 번만

## 넣기 (ws_trader 와 같은 규칙, 칸 이름은 `tests/fixtures/nh/KA|FB|FA` 기록으로 확인)

| 원문 | 조건 | 부르는 것 |
|---|---|---|
| KRX `KA` (`signal_sym`) | `tick_div == "1"` 이고 `exec_qty` > 0 | `on_krx(last_pric, recv_monotonic, exch_tm[:6])` |
| MKU `FB` (`sym`) | `bid_pric_1`·`ask_pric_1` 을 수로 읽을 수 있음 | `on_quote(bid, ask, recv_monotonic, ko_exec_tm[:6])` |
| MKU `FA` (`sym`) | 기록용 — 마지막 체결가만 1분 줄에 | 없음 |
| 1초 타이머 | 첫 타이머 = 구독 시작 + 1초(리플레이는 첫 원문 시각), 그 뒤 1초마다 | `on_timer(t, t 순간의 벽시계 HHMMSS)` |

시각 기준은 ws_trader 처럼 **받은 순간의 단조 시계**(`RawMessage.recv_monotonic`, 허브의 `time.monotonic()`)입니다.
타이머는 받은 시각 순서 사이에 끼웁니다 — 원문 하나를 넣기 전에 그 원문의 받은 시각까지 밀린 타이머를 먼저 돌립니다
(week03 `replay_live.py` 와 같은 규칙). 그래서 주문으로 실행 스레드가 막혔다 풀려도 Engine 이 보는 시각은 앞으로만 갑니다.

## 스레드와 쌓임

Engine 은 한 스레드에서만 부릅니다. **실행 스레드 하나**가 원문을 꺼내 넣고, 행동이 나오면 그 자리에서 주문·체결 확인
(최대 15초)을 **기다립니다**. 그동안 허브는 이벤트 루프에서 계속 받아 RawFeed 큐에 쌓고(한도 5,000건 — MKU 호가 + KRX
체결은 초당 수십 건이라 15초에 수백 건), 확인이 끝나면 실행이 쌓인 것을 순서대로 마저 넣습니다.
별도 스레드로 주문을 돌리지 않는 까닭: Engine 을 두 스레드가 만지게 되고, 체결 전후 순서가 흐트러집니다.
한도를 넘으면 RawFeed 가 `overflow` 를 세우고 — 아래 「멈춤」. 꺼낼 때 남아 있던 수의 최댓값은 summary `messages.backlog_max`.

### 체결 확인 동안 쌓인 원문 (ws_trader 와 같은 판단 — 컨트롤러 결정 R14b)

ws_trader 는 KRX 연결·MKU 연결·1초 타이머가 `asyncio.gather` 로 **따로 도는 작업**입니다. 한 작업이 `await act()`(주문·확인)를
기다리는 동안 다른 두 작업은 그대로 Engine 을 부릅니다 — 그때 Engine 은 행동을 낸 순간부터 `pending`(보유도 그대로)이라
판단이 나지 않습니다. 기다리던 작업 자신의 다음 원문은 웹소켓에 남아 있다가 `act` 가 `filled_*` 를 부른 **뒤** 처리되는데,
그때는 진입이면 보유가 있어 진입 판단이 없고, 청산이면 보유가 없어 청산 판단이 없습니다 — 쌓인 원문으로는 어느 쪽이든 판단이 나지 않습니다.

그래서 여기서는 모의 계좌 주문의 결과(`filled_entry`·`filled_exit`, 진입 실패의 `pending = False`)를 Engine 에 **바로 알리지 않고**,
확인이 끝난 순간(`confirm_mono` — ws_trader 가 `pending` 을 푼 순간. 보낸 순간 `sent_mono` 가 아님)보다 앞에 받은 원문과 타이머를
`pending` 인 Engine 에 다 넣은 뒤에 알립니다(그 뒤의 첫 원문·타이머 직전, 원문이 없으면 `timers()`). 그래서
① 쌓인 원문이 ws_trader 에 없던 판단(예: 막 체결된 보유를 쌓인 호가로 손절)을 내지 않고 ② Engine 이 보는 시각이 뒤로 가지 않습니다.
앱 쪽 보유(`self.pos`)·잔고 관문·대조는 확인 즉시 바뀝니다. 알림을 기다리는 동안 Engine 이 그래도 행동을 내면(약속을 어긴 전략) 주문하지 않습니다.
`step` 은 쌓인 원문이 있으면 타이머를 지금까지 앞당기지 않고, 알림을 기다리는 동안엔 청산 재시도·정리 요청을 다음 step 으로 미룹니다.
끝낼 때는 남은 알림을 먼저 합니다. 종이는 기다림이 없어 바로 알립니다(리플레이와 같음).

## 주문 (재전송 없음 · 남의 포지션 안 건드림)

- 진입 행동은 이 실행의 보유가 없을 때만, 청산 행동은 보유가 있고 방향이 보유의 반대일 때만 받습니다. 아니면 전략 오류(「오류」).
- 「모의 계좌」: `MockAccountBroker.fill` 한 번(시장가 1계약 — 주문 전 잔고 관문·`blind`·`unresolved` 규칙 그대로).
  체결가를 받으면 그 값으로 `filled_entry`/`filled_exit`. 체결 시각(`now`)은 확인을 받은 순간의 단조 시계, 알리는 때는
  아래 「체결 확인 동안 쌓인 원문」.
- **체결가를 못 받았을 때(None)** — ws_trader 처럼 「호가로 기록하고 계속」 하지 않습니다.
  - 결과를 모르는 주문이 남았으면(`broker.open_unknowns()` — 응답 없음·번호 없음·15초 안에 확인 안 됨) → **멈춤(확인 필요)**.
    Engine 은 `pending` 그대로(새 판단 없음), 이 실행은 더 주문하지 않고, 끝에도 정리하지 않습니다.
  - 결과를 아는 실패(업무 거부·거부/취소 8·9·관문에 걸려 안 보냄)면 잔고를 한 번 봅니다 — 못 읽거나 실행이 아는 보유와
    다르면 멈춤. 같으면 진입은 그 신호를 버리고(`pending = False`, ws_trader 와 같음), 청산은 **10초 뒤 같은 사유로 다시**
    (1분봉 실행과 같은 규칙, 새 주문이지 응답 없는 주문의 재전송이 아님). 그동안 Engine 은 `pending` 그대로.
    청산이 이렇게 **3번**(처음 + 다시 2번) 안 되면 더 내지 않고 멈춤(확인 필요, 「청산 주문이 3번 거절됨」 기록).
  - fill 자체가 예외를 내면(기록 실패 등) 결과를 모르는 것으로 보고 멈춤.
- 「종이」: 주문 없이 **반대 호가**(매수 → 매도 호가, 매도 → 매수 호가 — 앱이 받은 마지막 1단 호가)로 체결, 수수료 체결마다
  US$2(`market.paper_fee`), 슬리피지 없음(ws_trader 종이 방식). 체결 시각은 그 행동을 낸 원문·타이머의 시각.
  Engine 의 `ref` 가 반대 호가와 다르면 기록만 하고 반대 호가로 체결합니다(전략이 체결가를 지어내지 못하게).
- 휴장(20:35~20:50)엔 주문하지 않습니다: 진입 신호는 버리고, 청산은 들고 있다가 휴장이 끝난 첫 step 에.
- 잔고 대조(모의 계좌, 멈추지 않은 동안): 보유가 바뀌고 5초 뒤 한 번, 보유 중이면 30초마다, 결과 모름 뒤 바로. 다르면 멈춤.

## 멈춤·공백 (컨트롤러 결정 R13)

| 만나는 것 | 하는 일 |
|---|---|
| `RawGap` refill (다시 붙음) | 기록만 — 끊긴 동안의 공백은 Engine 의 `stale_s` 규칙이 다룸 |
| `RawGap` environment (모의/실전 바뀜) | 보유 중이면 멈춤(확인 필요), 보유가 없으면 끝 |
| `RawGap` rejected (원한 구독이 밀림·거절) | 위와 같음 — 시세 없이 청산 판단을 할 수 없음. 밀린 것이 기록용 MKU 체결(FA)뿐이면 기록만 |
| `overflow` (쌓임 한도) | 보유·결과 모름 주문이 있으면 멈춤(확인 필요), 없으면 끝(「끝 — 쌓임 한도」) — 빠진 원문이 있어 같은 판단을 보장할 수 없음 |

멈춘 실행은 Engine 에 더 넣지 않고(원문은 꺼내 버림) 주문도 하지 않으며, 중지나 끝 시각에 정리 없이 끝납니다
(끝 까닭에 「정리 안 함 — 확인 필요」, 1분봉 R14 와 같음). 끝 기록은 보유가 있을 때만 「보유를 남겨 두었다」고 쓰고,
없으면 「이 실행이 아는 보유는 없음(결과 모름 주문이 계좌에 남겼을 수는 있음)」이라고 씁니다.

## 끝

- 끝 시각 = 전략 Params 의 `flatten_at` + 5분(ws_trader `--until` 15:45 자리), 해외 실행 끝 23:55 를 넘지 않음.
  `flatten_at` 이 없으면 23:55. 그 전에 Engine 이 「마감」 청산을 냅니다.
- 끝·중지·오류 때 보유가 남았고 멈추지 않았으면 앱이 청산 주문을 내고 `filled_exit(…, "실행 종료 정리")`.
  모의 계좌는 그 전에 잔고를 한 번 봅니다(다르면 정리 안 함 — 확인 필요).
- 앱 종료 중지(`request_stop(shutdown=True)`)는 휴장이어도 미루지 않습니다(휴장 중 보유면 정리 없이 확인 필요).
  사용자 중지가 휴장 중이고 보유가 있으면 휴장이 끝난 첫 step 에서 정리하고 끝냅니다.
- 원문 구독은 `finish` 와 `run_forever` 의 `finally` 에서 언제나 닫습니다. 밖에서 닫히면(앱 종료 `close_all`) 「중지」로 끝냅니다.

## 기록

`event` · `signal`(Engine 행동마다 — `act` `side` `ref` `reason` `dk` `rho` `spread` `expected` `followed` + 그때 호가·KRX) ·
`order`·`fill`(브로커, 종이는 `source="paper"`) · `trade`(1분봉과 같은 칸 + Engine 의 `gross_ticks` `net_ticks` `net_usd` `held_s`) ·
1분마다 `minute`(`date` `time`(그 분 시작) `krx` `mku_mid` `bid` `ask` `spread_ticks` `mku_last` `last_krx_at` `last_quote_at` `position`).
원문은 남기지 않습니다(용량). 모든 기록은 쓰는 순간 `journal.scrub`.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.nh_api import runtime
from backend.realtime.feeds import Feed
from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun.apilog import ApiLog, bind, purpose
from backend.team_pyrun.broker import MockAccountBroker, error_text
from backend.team_pyrun.journal import Journal, summarize, write_summary
from backend.team_pyrun.live import (SNAPSHOT_KEYS, RunSpec, StartRefused, _hhmmss, _iso, run_head, strategy_block,
                                     write_run_json)
from backend.team_pyrun.loader import Loaded
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, adapter_for, in_break, market_of, market_of_tick
from backend.team_pyrun.rawfeed import GAP_ENVIRONMENT, GAP_REFILL, GAP_REJECTED, RawFeed, RawGap, RawMessage
from backend.team_pyrun.runner import END_REASON, _digits, pnl_ticks

STEP_SECONDS = 1.0          # 살림(step) 간격
TIMER_SECONDS = 1.0         # Engine.on_timer 간격
END_GRACE_MINUTES = 5       # 전략 flatten_at 뒤 이만큼 더 돌고 끝냄 (ws_trader --until)
RECONCILE_SECONDS = 30      # 보유 중 잔고 대조 간격
RECHECK_SECONDS = 5         # 보유가 바뀐 뒤 잔고를 한 번 더 보기까지
RETRY_SECONDS = 10          # 결과를 아는 실패 뒤 청산을 다시 시도하기까지
MAX_EXIT_REJECTS = 3        # 결과를 아는 실패로 청산이 이만큼 안 되면(처음 + 다시 2번) 멈춤
MAX_TIMER_CATCHUP = 600     # 밀린 타이머를 이보다 많이 돌려야 하면 건너뛰고 기록 (잠자기에서 깬 경우 등)
#: Engine.filled_exit 가 돌려주는 칸 — trade 줄에 그대로 남긴다
ENGINE_TRADE_KEYS = ("gross_ticks", "net_ticks", "net_usd", "held_s")
#: signal 줄에 남기는 행동 칸 (그 밖의 칸은 남기지 않음)
SIGNAL_KEYS = ("dk", "rho", "spread", "expected", "followed")


def wants_of(signal_sym: str, sym: str) -> tuple[Feed, ...]:
    """구독할 원문 — KRX 체결(`KA`), MKU 호가(`FB`), MKU 체결(`FA`, 기록용)."""
    return (Feed("domestic-day", "quote", signal_sym), Feed("overseas", "book", sym), Feed("overseas", "quote", sym))


def default_feed_factory(run_id: str, wants: Iterable[Feed]) -> RawFeed:
    """진짜 원문 구독 — 실행 스레드(또는 Registry 의 요청 스레드)에서 만든다(이벤트 루프 스레드 아님)."""
    return RawFeed(run_id, wants)


def _end_at(params: object, market_end: str) -> tuple[str, str | None]:
    """(끝 시각 HHMMSS, 알림 또는 None). `flatten_at` + 5분, 시장 끝 시각을 넘지 않음."""
    flat = getattr(params, "flatten_at", None)
    if not (isinstance(flat, str) and len(flat) == 6 and flat.isdigit()):
        return market_end, f"Params 에 flatten_at(HHMMSS) 이 없어 실행 끝을 {market_end[:2]}:{market_end[2:4]} 로"
    t = int(flat[:2]) * 3600 + int(flat[2:4]) * 60 + int(flat[4:]) + END_GRACE_MINUTES * 60
    end = f"{t // 3600:02d}{t % 3600 // 60:02d}{t % 60:02d}"
    return min(end, market_end), None


def _price(v: Any) -> float | None:
    """0 보다 큰 유한수로 읽히면 그 값. 아니면 None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) and f > 0 else None


class RealtimeRun:
    """실시간 실행 하나. Registry 가 만들고 `prepare()` 뒤 데몬 스레드에서 `run_forever()` 를 돌린다.

    `handle`·`step`·`finish` 는 잠금 안에서 돌아 서로 겹치지 않습니다. `status()`·`request_*()` 는 잠그지 않습니다."""

    def __init__(self, run_id: str, folder: Path, loaded: Loaded, spec: RunSpec, *,
                 api_module: ModuleType | Any = default_api,
                 feed_factory: Callable[[str, Iterable[Feed]], Any] = default_feed_factory,
                 now: Callable[[], datetime] = now_kst, monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 active_env: Callable[[], str | None] = runtime.active_environment, stops_before: int = 0,
                 params: dict[str, Any] | None = None):
        self.run_id, self.folder, self.loaded, self.spec = run_id, Path(folder), loaded, spec
        self.now, self.monotonic, self.sleep = now, monotonic, sleep
        self.feed_factory, self.active_env = feed_factory, active_env
        self.kind = "realtime"
        self.market = OVERSEAS              # 주문하는 종목은 언제나 MKU (KRX 는 시세만)
        self.api = adapter_for(OVERSEAS, api_module)
        self.dom = adapter_for(DOMESTIC, api_module)     # KRX 최근월물 찾기(시작 때만)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.j = Journal(self.folder / "journal.jsonl")
        self.apilog = ApiLog(self.folder / "api_log.jsonl", run_id)
        self.orders = spec.mode == "orders"
        self.tick, self.tick_value = loaded.tick, loaded.tick_value
        # 실시간 전략은 시장이 채우는 Params 칸이 없다. `params` 는 기본 Params 에서 바꿀 칸(리플레이의 기준값 바꿔 보기)
        self.engine = loaded.new() if not params else loaded.strategy_cls(replace(loaded.params_cls(), **params))
        self.p = self.engine.p
        self.stops_before = int(stops_before)
        if self.stops_before and hasattr(self.engine, "stops"):
            self.engine.stops = self.stops_before   # 하루 손절 한도를 앞선 실행과 이어서
        self.end_at, self._end_note = _end_at(self.p, OVERSEAS.end_time)
        self.sym: str | None = spec.sym
        self.signal_sym: str | None = getattr(spec, "signal_sym", None)
        self.broker: MockAccountBroker | None = None
        self.feed: Any = None
        self.state = "대기"
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.ended_reason: str | None = None
        self.account_start: dict | None = None
        self.account_end: dict | None = None
        self.halted: str | None = None
        #: 이 실행의 보유(앱 쪽 기록) — side "buy"/"sell", entry, entry_time, entry_fee, entry_mono
        self.pos: dict | None = None
        self.trades: list[dict] = []
        self.krx: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.mku_last: float | None = None
        self.last_krx_at: str | None = None
        self.last_quote_at: str | None = None
        self.last_signal: dict | None = None
        self.last_dk: float | None = None
        self.last_rho: float | None = None
        #: 받은 원문 수와 쌓임 최댓값(`backlog_max` — 꺼낼 때 큐에 남아 있던 수의 최댓값, 첫 장중에 여유를 재려고)
        self.counts = {"KA": 0, "FB": 0, "FA": 0, "bad": 0, "dropped": 0, "backlog_max": 0}
        self._lock = threading.RLock()
        self._prepared = False
        self._finished = False
        self._finishing = False
        self._stop_requested = False
        self._shutdown = False
        self._flatten_requested = False
        self._today = ""
        self._next_timer = 0.0
        self._minute_key = ""
        self._exit_retry: dict | None = None    # 결과를 아는 실패 뒤 다시 낼 청산 행동
        self._retry_at = 0.0
        self._exit_rejects = 0                  # 이 보유의 청산이 결과를 아는 실패로 안 된 횟수
        #: 체결 확인이 끝났지만 Engine 에 아직 알리지 않은 것 — {"until": 확인 끝 monotonic, "fn": 알리기}
        self._settle: dict | None = None
        self._break_exit: dict | None = None    # 휴장 중 나온 청산 행동 — 휴장이 끝난 첫 step 에
        self._last_check: float | None = None
        self._last_exp = 0
        self._recheck_at: float | None = None
        self._noted: set[str] = set()           # 한 번만 남기는 기록

    # ------------------------------------------------------------ 시작
    def prepare(self) -> None:
        """시작 검사 → 원문 구독. 안 되면 `StartRefused`(주문 없음, 구독 없음, run.json 은 「끝」)."""
        with self._lock, bind(self.apilog):
            if self._prepared or self._finished:
                raise StartRefused("이미 시작했거나 끝난 실행입니다")
            now = to_kst(self.now())
            self.started_at = _iso(now)
            self._write_run()
            try:
                self._prepare(now)
            except StartRefused as e:
                self._close_feed()
                self._refuse(str(e))
                raise
            except Exception as e:      # 조회 실패·구독 실패
                self._close_feed()
                msg = f"시작 준비 실패 — {error_text(e)}"
                self._refuse(msg)
                raise StartRefused(msg) from e
            self._prepared = True
            start = getattr(self.p, "entry_start", "")
            self._set_state("대기" if isinstance(start, str) and now.strftime("%H%M%S") < start else "진행 중")

    def _prepare(self, now: datetime) -> None:
        j, loaded, api = self.j, self.loaded, self.api
        today, clock = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
        self._today = today
        # 0. 조회·주문 전에 거부할 것 (R6 — 종목의 시장)
        if loaded.kind != "realtime":
            raise StartRefused("1분봉 전략(on_minute)은 실시간 실행으로 시작할 수 없습니다")
        if market_of_tick(loaded.tick) is not OVERSEAS:
            raise StartRefused(f"실시간 실행은 MKU 만 주문합니다 — 전략 TICK {loaded.tick:g} 는 MKU 틱(0.0001)이 아닙니다")
        if self.sym:
            self._need_market(self.sym, OVERSEAS, "주문 종목은 MKU… 여야 합니다")
        if self.signal_sym:
            self._need_market(self.signal_sym, DOMESTIC, "신호 종목(KRX)은 A75… 여야 합니다")
        if self.orders and self.active_env() != "paper":
            raise StartRefused("모의투자 환경에서만 모의 계좌 실행을 세울 수 있습니다")
        if clock >= self.end_at:
            raise StartRefused(f"실행 끝 시각({self.end_at[:2]}:{self.end_at[2:4]}) 뒤에는 시작할 수 없습니다")
        # 1. 어디로·무엇을
        j.write("event", text=f"서버 paper · 주문 {'모의계좌' if self.orders else '종이'} · 실시간")
        j.write("event", text=f"시장 {self.market.id} · 통화 {self.market.currency} · 실행 끝 "
                              f"{self.end_at[:2]}:{self.end_at[2:4]} (전략 flatten_at + {END_GRACE_MINUTES}분)")
        if self._end_note:
            j.write("event", text=self._end_note)
        j.write("event", text=f"전략 {loaded.file} · sha256 {loaded.sha256[:12]} · Params {asdict(self.p)}")
        # 2. 종목과 틱
        if not self.sym:
            with purpose("종목 찾기"):
                self.sym = api.nearest()
            self._need_market(self.sym, OVERSEAS, "주문 종목은 MKU… 여야 합니다")
        if not self.signal_sym:
            with purpose("종목 찾기"):
                self.signal_sym = self.dom.nearest()
            self._need_market(self.signal_sym, DOMESTIC, "신호 종목(KRX)은 A75… 여야 합니다")
        with purpose("틱 확인"):
            tick, value = api.spec()
        if not (math.isclose(tick, loaded.tick, rel_tol=1e-9) and math.isclose(value, loaded.tick_value, rel_tol=1e-9)):
            raise StartRefused(f"틱·틱가치가 전략 가정과 다릅니다 — 서버 {tick:g}·{value:g}, "
                               f"전략 {loaded.tick:g}·{loaded.tick_value:g}")
        j.write("event", text=f"주문 종목 {self.sym} · 틱 {tick:g} · 틱가치 {value:g} {self.market.currency} · "
                              f"신호 종목 {self.signal_sym}")
        self._write_run()
        # 3. 모의계좌: 시작 잔고가 0 이어야 한다 (누구의 잔고인지 모르므로 정리하지 않고 거부)
        if self.orders:
            broker = MockAccountBroker(api, self.sym, j, sleep=self.sleep, today=today,
                                       expected=self.expected_position, halt=self.halt)
            held = broker.position()
            if held is None:
                raise StartRefused("시작 잔고를 확인하지 못했습니다")
            if held != 0:
                raise StartRefused(f"{self.sym} 잔고 {held:+d}계약이 남아 있습니다 — 정리한 뒤 시작하세요")
            j.write("event", text=f"시작 잔고 {self.sym} {held:+d}계약")
            self.account_start = broker.account(clock, "시작 (수수료·확정손익은 하루 누적)")
            if self.account_start:
                broker.last_fee = self.account_start["fee"]
            self.broker = broker
        if self.stops_before:
            j.write("event", text=f"오늘 앞선 실행의 손절 {self.stops_before}회를 이어받음")
        # 4. 원문 구독 — 마지막에 (위에서 거부되면 구독하지 않음)
        wants = wants_of(self.signal_sym, self.sym)
        self.feed = self.feed_factory(self.run_id, wants)
        j.write("event", text="원문 구독 " + " · ".join(f"{f.api_id} {f.sym}" for f in wants))
        self._next_timer = self.monotonic() + TIMER_SECONDS
        self._minute_key = now.strftime("%H%M")
        self._last_check = self.monotonic()

    @staticmethod
    def _need_market(sym: str, market, why: str) -> None:
        try:
            got = market_of(sym)
        except ValueError as e:
            raise StartRefused(f"{why}: {e}") from e
        if got is not market:
            raise StartRefused(f"{why} — {sym} 은 {got.id} 시장 종목입니다")

    def _refuse(self, msg: str) -> None:
        self.j.write("event", text=f"시작 거부 · {msg}")
        self._finished = True
        self.ended_at = _iso(self.now())
        self.ended_reason = f"시작 거부: {msg}"
        self.state = "끝"
        self._write_run()

    # ------------------------------------------------------------ 원문 넣기
    def handle(self, item: RawMessage | RawGap) -> None:
        """원문 하나 또는 공백 표지 하나. 그 받은 시각까지 밀린 1초 타이머를 먼저 돌린다."""
        with self._lock:
            if not self._prepared or self._finished:
                return
            with bind(self.apilog):
                try:
                    self._note_backlog()
                    self._check_overflow()
                    if not self._finished:
                        self._catch_up(item.recv_monotonic)
                    if not self._finished:
                        self._handle(item)
                except Exception as e:
                    self._finish(f"오류: {error_text(e)}", to_kst(self.now()))

    def _backlog(self) -> int:
        try:
            return int(getattr(self.feed, "pending", 0) or 0)
        except Exception:
            return 0

    def _note_backlog(self) -> None:
        self.counts["backlog_max"] = max(self.counts["backlog_max"], self._backlog())

    def _check_overflow(self) -> None:
        """쌓임 한도를 넘었으면 — 보유·결과 모름이 있으면 멈춤(확인 필요), 없으면 끝(컨트롤러 결정 R14b)."""
        if self.feed is None or not getattr(self.feed, "overflow", False) or self.halted or self._finished:
            return
        what = "원문이 쌓임 한도를 넘어 일부가 빠짐 — 같은 판단을 보장할 수 없음"
        unknown = self.broker is not None and self.broker.open_unknowns() is not None
        if self.pos is not None or unknown or self._settle is not None:
            self.halt(f"{what} · 주문을 멈춤")
        else:
            self.j.write("event", text=what)
            self._finish(f"끝 — 쌓임 한도: {what}", to_kst(self.now()))

    def _handle(self, item: RawMessage | RawGap) -> None:
        if isinstance(item, RawGap):
            self._on_gap(item)
            return
        if self.halted:
            self.counts["dropped"] += 1     # 멈춘 실행은 판단하지 않는다
            return
        api_id, sym, body, mono = item.api_id, item.sym, item.body, item.recv_monotonic
        if api_id == "KA" and sym == self.signal_sym:
            # ws_trader Trader.on_dom — 틱구분 1 · 체결수량 > 0 만
            if body.get("tick_div") != "1":
                return
            try:
                qty = float(body.get("exec_qty") or 0)
                price = float(body["last_pric"])
            except (KeyError, TypeError, ValueError):
                self._bad(item)
                return
            if not qty:
                return
            if not (math.isfinite(price) and price > 0):
                self._bad(item)
                return
            hh = str(body.get("exch_tm", ""))[:6]
            self.counts["KA"] += 1
            self.krx, self.last_krx_at = price, hh
            self._act(self.engine.on_krx(price, mono, hh), mono, hh)
        elif api_id == "FB" and sym == self.sym:
            # ws_trader Trader.on_ovs — 1단 매수·매도 호가, 못 읽으면 건너뜀
            try:
                bid, ask = float(body["bid_pric_1"]), float(body["ask_pric_1"])
            except (KeyError, TypeError, ValueError):
                return
            hh = str(body.get("ko_exec_tm", ""))[:6]
            self.counts["FB"] += 1
            if math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask:
                self.bid, self.ask, self.last_quote_at = bid, ask, hh
            self._act(self.engine.on_quote(bid, ask, mono, hh), mono, hh)
        elif api_id == "FA" and sym == self.sym:
            try:
                px = float(body["last_pric"])
            except (KeyError, TypeError, ValueError):
                return
            self.counts["FA"] += 1
            if math.isfinite(px) and px > 0:
                self.mku_last = px

    def _bad(self, item: RawMessage) -> None:
        self.counts["bad"] += 1
        if "bad" not in self._noted:
            self._noted.add("bad")
            self.j.write("event", text=f"읽을 수 없는 원문 {item.api_id} {item.sym} — 건너뜀(이후로는 수만 셈)")

    def _on_gap(self, g: RawGap) -> None:
        if g.kind == GAP_REFILL:
            self.j.write("event", text=f"시세 연결이 다시 붙음({g.market}) — 끊긴 동안의 원문은 없음 "
                                       "(오래된 값은 전략의 stale 규칙이 버림)", detail=g.detail)
            return
        if g.kind == GAP_REJECTED and self._record_only(g.detail.get("feeds")):
            self.j.write("event", text="기록용 MKU 체결(FA) 구독이 밀림 — 판단에는 쓰지 않아 계속", detail=g.detail)
            return
        if g.kind in (GAP_ENVIRONMENT, GAP_REJECTED):
            what = ("활성 환경(모의/실전)이 바뀜 — 원문을 믿을 수 없음" if g.kind == GAP_ENVIRONMENT
                    else "원한 실시간 구독이 밀리거나 거절됨 — 시세 없이 판단할 수 없음")
            self.j.write("event", text=what, detail=g.detail)
            unknown = self.broker is not None and self.broker.open_unknowns() is not None
            if self.pos is not None or unknown or self.halted:
                self.halt(what)
            else:
                self._finish(f"끝 — {what}", to_kst(self.now()))
            return
        self.j.write("event", text=f"모르는 공백 표지 {g.kind}", detail=g.detail)

    def _record_only(self, feeds: Any) -> bool:
        """밀린 구독이 전부 기록용 MKU 체결(`overseas`·`quote`)인가. 목록을 못 읽으면 False(판단용으로 본다)."""
        if not isinstance(feeds, list) or not feeds:
            return False
        return all(isinstance(f, dict) and (f.get("context"), f.get("kind"), f.get("sym")) == ("overseas", "quote", self.sym)
                   for f in feeds)

    # ------------------------------------------------------------ 타이머
    def _catch_up(self, upto: float) -> None:
        """받은 시각 `upto` 까지 밀린 1초 타이머를 차례로 돌린다."""
        behind = int((upto - self._next_timer) // TIMER_SECONDS) + 1 if upto >= self._next_timer else 0
        if behind > MAX_TIMER_CATCHUP:
            skip = behind - 1
            self.j.write("event", text=f"타이머 {skip}번이 밀려 건너뜀 (실행 스레드가 {skip:.0f}초 넘게 멈춰 있었음)")
            self._next_timer += skip * TIMER_SECONDS
        while self._next_timer <= upto and not self._finished:
            t = self._next_timer
            self._settle_due(t)     # 확인 끝 시각이 이 타이머보다 앞이면 먼저 알린다
            self._next_timer += TIMER_SECONDS
            if not self.halted and not self._finished:
                self.fire_timer(t)
        self._settle_due(upto)

    def _settle_due(self, upto: float) -> None:
        """미룬 체결 알림 — `upto` 가 확인 끝 시각에 닿았으면 Engine 에 알린다(모듈 문서 「체결 확인 동안 쌓인 원문」)."""
        st = self._settle
        if st is not None and upto >= st["until"]:
            self._settle = None
            st["fn"]()

    def _settle_now(self) -> None:
        """미룬 체결 알림을 지금 — 끝낼 때, 새 주문을 내기 전에."""
        if self._settle is not None:
            st, self._settle = self._settle, None
            st["fn"]()

    def timers(self) -> None:
        """지금(`monotonic()`)까지 밀린 1초 타이머를 돌린다 — 원문이 없을 때 실행 스레드가 부른다."""
        with self._lock:
            if not self._prepared or self._finished:
                return
            with bind(self.apilog):
                try:
                    self._note_backlog()
                    self._check_overflow()
                    if not self._finished:
                        self._catch_up(self.monotonic())
                except Exception as e:
                    self._finish(f"오류: {error_text(e)}", to_kst(self.now()))

    def start_timers_at(self, mono: float) -> None:
        """첫 1초 타이머 시각을 정한다(`prepare` 뒤, 첫 원문 전). 장중은 쓰지 않음(구독 시작 + 1초).

        녹화 리플레이가 week03 `replay_live.py` 처럼 **첫 원문의 받은 시각**에 첫 타이머를 두려고 부른다 —
        타이머 격자가 같아야 시간 청산·마감 청산 시각이 같다."""
        with self._lock:
            self._next_timer = float(mono)

    def _hhmmss_at(self, mono: float) -> str:
        """단조 시계 `mono` 순간의 벽시계 HHMMSS."""
        return (to_kst(self.now()) - timedelta(seconds=self.monotonic() - mono)).strftime("%H%M%S")

    def fire_timer(self, mono: float, hhmmss: str | None = None) -> None:
        """`Engine.on_timer` 한 번 — 시각은 그 순간의 벽시계(ws_trader timer)."""
        hh = hhmmss or self._hhmmss_at(mono)
        self._act(self.engine.on_timer(mono, hh), mono, hh)

    # ------------------------------------------------------------ 행동
    def _act(self, act: Any, mono: float, hh: str) -> None:
        """Engine 이 돌려준 행동을 검사하고 실행한다. 약속에 없는 행동은 `TypeError`(→ 「오류」, 주문 없음)."""
        if act is None:
            return
        if self._settle is not None:
            # 주문을 확인하는 동안 받은 원문 — ws_trader 에선 Engine 이 pending 이라 판단이 나지 않던 때
            self.engine.pending = True
            self.j.write("event", clock=hh, text="주문 확인 중에 받은 원문에서 나온 행동 — 주문하지 않음(Engine 은 pending 이어야 함)")
            return
        if not isinstance(act, dict) or act.get("act") not in ("enter", "exit"):
            raise TypeError(f"전략 행동은 None 또는 act 가 enter·exit 인 dict 여야 합니다: {act!r}")
        side = act.get("side")
        if isinstance(side, bool) or side not in (1, -1):
            raise TypeError(f"전략 행동의 side 는 1 또는 -1 이어야 합니다: {act!r}")
        if _price(act.get("ref")) is None:
            raise TypeError(f"전략 행동의 ref 는 0 보다 큰 수여야 합니다: {act!r}")
        entry = act["act"] == "enter"
        if entry and self.pos is not None:
            raise TypeError("보유 중인데 진입 행동이 나왔습니다 — 주문하지 않음")
        if not entry and self.pos is None:
            raise TypeError("보유가 없는데 청산 행동이 나왔습니다 — 남의 포지션은 건드리지 않음")
        if not entry and side != -self._side_int():
            raise TypeError("청산 행동의 방향이 보유의 반대가 아닙니다 — 주문하지 않음")
        self._signal(act, hh)
        if not entry and (self._exit_retry is not None or self._break_exit is not None):
            self.j.write("event", clock=hh, text="이미 청산을 기다리는 중 — 이 청산 행동은 주문하지 않음")
            return
        if self.halted:
            self.j.write("event", clock=hh, text="멈춘 실행 — 행동을 주문하지 않음")
            return
        clock = _hhmmss(self.now())
        if entry and (self._stop_requested or self._flatten_requested):
            self._skip_entry(hh, "중지·정리 요청 중")
            return
        if self._in_break(clock):
            if entry:
                self._skip_entry(hh, "휴장 중(20:35~20:50)")
            else:
                self._break_exit = act
                self.j.write("event", clock=hh, text=f"휴장 중 청산 판단 ({act.get('reason')}) — 휴장이 끝나면 주문")
            return
        self._execute(act, mono, act.get("reason") or "")

    def _skip_entry(self, hh: str, why: str) -> None:
        self.engine.pending = False
        self.j.write("event", clock=hh, text=f"{why} — 진입 신호를 버림(주문 안 냄)")

    def _signal(self, act: dict, hh: str) -> None:
        extra = {k: act[k] for k in SIGNAL_KEYS if k in act}
        self.last_signal = self.j.write(
            "signal", clock=hh, act=act["act"], side="buy" if act["side"] > 0 else "sell", ref=act["ref"],
            reason=act.get("reason"), time=act.get("time"), bid=self.bid, ask=self.ask, krx=self.krx, **extra)
        if "dk" in act:
            self.last_dk = act["dk"]
        if "rho" in act:
            self.last_rho = act["rho"]

    def _execute(self, act: dict, mono: float, reason: str) -> None:
        """행동 하나를 체결한다(모의 계좌 주문은 **한 번**). 체결을 못 받으면 `_no_fill` 규칙."""
        self._settle_now()          # 앞선 체결 알림이 남았으면 먼저(새 주문 전에 Engine 이 보유를 알게)
        side = "buy" if act["side"] > 0 else "sell"
        entry = act["act"] == "enter"
        clock = _hhmmss(self.now())
        until = None                # 모의 계좌: 확인 끝 시각 — Engine 알림을 그때까지 받은 원문 뒤로 미룬다
        if not self.orders:
            px = self.ask if side == "buy" else self.bid      # 반대 호가 — 앱이 받은 마지막 1단 호가
            if px is None:
                px = float(act["ref"])
            if not math.isclose(px, float(act["ref"]), rel_tol=0, abs_tol=self.tick / 100):
                self.j.write("event", clock=clock, text=f"전략 기준가 {act['ref']} ≠ 반대 호가 {px} — 반대 호가로 체결")
            fee: float | None = self.market.paper_fee
            self.j.write("fill", clock=clock, side=side, price=px, source="paper", fee=fee,
                         text=f"종이 체결(반대 호가) · {'진입' if entry else '청산 · ' + reason}")
            fill_mono = mono
        else:
            why = f"진입 ({side})" if entry else f"청산 · {reason}"
            sent_mono = self.monotonic()        # 주문을 보낸 순간
            try:
                got = self.broker.fill(side, float(act["ref"]), clock, why)
            except Exception as e:      # 브로커 안의 기록 실패 등 — 주문이 나갔는지 모른다
                self.halt(f"주문 처리 중 오류 — 결과 모름 ({error_text(e)})")
                return
            until = fill_mono = self.monotonic()   # 확인이 끝난 순간 = ws_trader 가 pending 을 푼 순간
            self.j.write("event", clock=clock, text=f"주문·확인 {until - sent_mono:.1f}초 — 그동안 받은 원문은 Engine 이 "
                                                    "pending 인 채로 넣고, 그 뒤에 결과를 알림",
                         sent_mono=round(sent_mono, 3), confirm_mono=round(until, 3))
            if got is None:
                self._no_fill(act, entry, clock, until)
                return
            px, fee = got, self.broker.last_fill_fee
        if entry:
            self._entered(act, side, px, fee, fill_mono, clock, until)
        else:
            self._exited(px, fee, fill_mono, clock, reason, until)

    def _later(self, until: float | None, fn) -> None:
        """Engine 에 알리기 — 모의 계좌면 확인 끝 시각까지 받은 원문을 다 넣은 뒤(그때 `_settle_due`), 종이면 바로."""
        if until is None or self._finishing:     # 끝내는 중이면 더 넣을 원문이 없다 — 바로
            fn()
        else:
            self._settle = {"until": until, "fn": fn}

    def _no_fill(self, act: dict, entry: bool, clock: str, until: float | None = None) -> None:
        """모의 계좌 fill 이 None — 호가로 기록하고 계속하지 않는다(모듈 문서 「주문」)."""
        b = self.broker
        what = "진입" if entry else "청산"
        if b.open_unknowns() is not None:
            self.halt(f"{what} 주문 결과 모름 — 계좌·주문내역을 직접 확인하세요")
            return
        held = b.position()
        exp = self.expected_position()
        if held is None:
            self.halt(f"{what} 주문 뒤 잔고를 확인하지 못함")
            return
        if held != exp:
            self.halt(f"잔고 불일치 · 기대 {exp:+d} · 계좌 {held:+d}")
            return
        if entry:
            self.j.write("event", clock=clock, text=f"진입 주문 안 됨 · 잔고 {held:+d} 그대로 — 이 신호는 건너뜀")
            self._later(until, lambda: setattr(self.engine, "pending", False))
        else:
            self._exit_rejects += 1
            if self._exit_rejects >= MAX_EXIT_REJECTS:
                self.j.write("event", clock=clock, text=f"청산 주문이 {self._exit_rejects}번 거절됨 ({act.get('reason')}) — "
                                                        "더 내지 않음, 계좌를 직접 확인하세요")
                self.halt(f"청산이 {self._exit_rejects}번 거절됨 — 보유 {self.expected_position():+d} 남음")
                return
            self._exit_retry = dict(act)
            self._retry_at = self.monotonic() + RETRY_SECONDS
            self.j.write("event", clock=clock, text=f"청산 안 됨 ({act.get('reason')}) · 잔고 {held:+d} — "
                                                    f"{RETRY_SECONDS}초쯤 뒤 같은 사유로 다시 시도")

    def _entered(self, act: dict, side: str, px: float, fee: float | None, mono: float, clock: str,
                 until: float | None = None) -> None:
        # 앱 쪽 보유를 먼저(바로) 적는다 — 잔고 관문·대조·끝내기 정리가 이 보유를 안다. Engine 알림은 미룰 수 있다
        self.pos = {"side": side, "entry": px, "entry_time": clock, "entry_fee": fee, "entry_mono": mono}
        self._exit_rejects = 0
        self._position_changed()
        self.j.write("event", clock=clock, text=f"진입 {side} {px}")
        self._later(until, lambda: self.engine.filled_entry(act["side"], px, mono, act.get("time") or clock, ""))

    def _exited(self, px: float, fee: float | None, mono: float, clock: str, reason: str,
                until: float | None = None) -> None:
        pos, self.pos = self.pos, None
        self._exit_retry = self._break_exit = None
        self._exit_rejects = 0
        self._position_changed()
        ticks = pnl_ticks(pos["side"], pos["entry"], px, self.tick)
        pnl = round(ticks * self.tick_value, 2)
        entry_fee = pos.get("entry_fee")
        total = None if entry_fee is None or fee is None else round(entry_fee + fee, 2)
        t: dict[str, Any] = {
            "side": pos["side"], "entry": pos["entry"], "exit": px, "entry_time": pos["entry_time"],
            "exit_time": clock, "ticks": ticks, "pnl": pnl, "entry_fee": entry_fee, "exit_fee": fee, "fee": total,
            "pnl_after_fee": None if total is None else round(pnl - total, 2), "reason": reason,
            "entry_date": self._today, "exit_date": self._today,
        }
        self._later(until, lambda: self._exit_notify(t, px, mono, clock, reason))

    def _exit_notify(self, t: dict, px: float, mono: float, clock: str, reason: str) -> None:
        """Engine 에 청산 체결을 알리고 trade 줄을 쓴다(Engine 칸 포함). 전략 오류여도 거래 기록은 남긴다."""
        ticks, pnl, total = t["ticks"], t["pnl"], t["fee"]
        err = None
        try:
            got = self.engine.filled_exit(px, mono, reason)
        except Exception as e:      # 전략 오류여도 거래 기록은 남긴다
            err, got = e, None
        got = got if isinstance(got, dict) else {}
        t.update({k: got.get(k) for k in ENGINE_TRADE_KEYS})
        self.trades.append(t)
        fee_txt = "" if total is None else f" · 수수료 {total:,.2f} USD → {t['pnl_after_fee']:+,.2f} USD"
        self.j.write("trade", clock=clock, text=f"{reason} {ticks:+d}틱 ({pnl:+,.2f} USD){fee_txt}", **t)
        if err is not None:
            self.j.write("event", clock=clock, text="전략 filled_exit 오류", error=error_text(err))
            if not self._finishing:
                raise err

    def _position_changed(self) -> None:
        """보유가 바뀐 순간(체결) — 5초 뒤 잔고를 한 번 더 보게 한다(체결은 step 이 아니라 원문 넣기에서 일어나므로)."""
        mono = self.monotonic()
        self._last_exp = self.expected_position()
        self._last_check = mono
        self._recheck_at = mono + RECHECK_SECONDS

    def _side_int(self) -> int:
        return 0 if self.pos is None else (1 if self.pos["side"] == "buy" else -1)

    def _app_exit(self, reason: str) -> None:
        """앱이 스스로 내는 청산(정리 요청·끝) — 반대 호가를 기준가로, Engine 에는 `filled_exit(…, reason)`."""
        if self.pos is None or self.halted:
            return
        self._settle_now()              # 진입 체결 알림이 남았으면 먼저(그 뒤 pending 을 다시 세운다)
        side = -self._side_int()
        ref = (self.bid if side < 0 else self.ask) or self.pos["entry"]
        self.engine.pending = True      # 앱 청산이 끝날 때까지 Engine 이 따로 청산을 내지 않게
        act = {"act": "exit", "side": side, "ref": ref, "reason": reason, "time": _hhmmss(self.now())}
        self._execute(act, self.monotonic(), reason)

    # ------------------------------------------------------------ 1초 한 번 살림
    def step(self, now: datetime) -> None:
        """밀린 타이머 → 끝 시각·중지·정리 요청 → 잔고 대조 → 청산 재시도·휴장 뒤 청산 → 1분 줄."""
        with self._lock:
            if not self._prepared or self._finished:
                return
            with bind(self.apilog):
                try:
                    self._note_backlog()
                    self._check_overflow()
                    # 쌓인 원문이 있으면 타이머를 지금까지 앞당기지 않는다 — 그 원문보다 늦은 타이머가 먼저 들어가면
                    # Engine 시각이 뒤로 간다(쌓인 원문을 넣을 때 `handle` 이 그 받은 시각까지 돌린다)
                    if not self._finished and not self._backlog():
                        self._catch_up(self.monotonic())
                except Exception as e:
                    self._finish(f"오류: {error_text(e)}", to_kst(now))
                    return
                if not self._finished:
                    self._step(to_kst(now))

    def _step(self, now: datetime) -> None:
        clock = now.strftime("%H%M%S")
        in_brk = self._in_break(clock)
        if clock >= self.end_at:
            self._finish("장 끝", now)
            return
        if self._stop_requested:
            if in_brk and self.pos is not None and not self.halted and not self._shutdown:
                self._note("stop-break", clock, "휴장 중 중지 요청 — 휴장이 끝나면 정리하고 끝냄")
            else:
                self._finish("중지", now)
                return
        start = getattr(self.p, "entry_start", "")
        waiting = isinstance(start, str) and clock < start and self.pos is None
        self._set_state("확인 필요" if self.halted else ("대기" if waiting else "진행 중"))
        try:
            mono = self.monotonic()
            self._reconcile(mono, clock)
            busy = self._settle is not None     # 쌓인 원문을 아직 넣는 중 — 주문 일은 다음 step 에
            if not self.halted and not in_brk and not busy:
                if self._break_exit is not None:
                    act, self._break_exit = self._break_exit, None
                    self._execute(self._fresh(act), mono, act.get("reason") or "")
                elif self._exit_retry is not None and mono >= self._retry_at:
                    act, self._exit_retry = self._exit_retry, None
                    self._execute(self._fresh(act), mono, act.get("reason") or "")
            if self._flatten_requested and not busy:
                if self.pos is not None and in_brk:
                    self._note("flatten-break", clock, "휴장 중 정리 요청 — 휴장이 끝나면 정리")
                else:
                    self._flatten_requested = False
                    self.j.write("event", clock=clock, text="정리 요청 — 보유가 있으면 정리")
                    if self._exit_retry is not None or self._break_exit is not None:
                        self.j.write("event", clock=clock, text="이미 청산을 기다리는 중 — 정리 주문은 따로 내지 않음")
                    else:
                        self._app_exit(END_REASON)
            self._reconcile(self.monotonic(), clock)
            self._minute_line(now)
        except Exception as e:
            self._finish(f"오류: {error_text(e)}", now)
            return
        if self.halted:
            self._set_state("확인 필요")

    def _fresh(self, act: dict) -> dict:
        """다시 내는 청산의 기준가를 지금 반대 호가로."""
        side = act["side"]
        ref = (self.ask if side > 0 else self.bid) or act["ref"]
        return {**act, "ref": ref}

    def _note(self, key: str, clock: str, text: str) -> None:
        if key not in self._noted:
            self._noted.add(key)
            self.j.write("event", clock=clock, text=text)

    def _in_break(self, clock: str) -> bool:
        """휴장 중인가 — 부른 시각과 **지금** 시각 둘 다(조회로 늦어져 주문이 20:35 를 넘기지 않게)."""
        return in_break(self.market, clock) or in_break(self.market, _hhmmss(self.now()))

    def _reconcile(self, mono: float, clock: str) -> None:
        """모의 계좌 잔고와 이 실행의 보유를 대조한다. 다르면 멈춤(이후 주문 없음) → 「확인 필요」."""
        b = self.broker
        if not self.orders or self.halted or b is None:
            return
        exp = self.expected_position()
        if exp != self._last_exp:
            self._last_exp = exp
            self._last_check = mono
            self._recheck_at = mono + RECHECK_SECONDS
        urgent = b.unknown or b.needs_check
        soon = self._recheck_at is not None and mono >= self._recheck_at
        due = ((exp != 0 or b.had_unknown) and self._last_check is not None
               and mono - self._last_check >= RECONCILE_SECONDS)
        if not (urgent or soon or due):
            return
        b.unknown = b.needs_check = False
        if soon:
            self._recheck_at = None
        self._last_check = mono
        held = b.position()
        if held is None or held == exp:
            return
        self.halt(f"잔고 불일치 · 기대 {exp:+d} · 계좌 {held:+d}")
        self.j.write("event", clock=clock, text="확인 필요 — 계좌 잔고가 실행과 달라 주문을 멈춤. 계좌를 직접 확인하세요")

    def _minute_line(self, now: datetime) -> None:
        """분이 바뀌면 막 끝난 분의 요약 한 줄(`minute`)."""
        key = now.strftime("%H%M")
        if key == self._minute_key:
            return
        prev, self._minute_key = self._minute_key, key
        bid, ask = self.bid, self.ask
        mid = None if bid is None or ask is None else round((bid + ask) / 2, _digits(self.tick) + 1)
        spread = None if bid is None or ask is None else round((ask - bid) / self.tick)
        self.j.write("minute", clock=now.strftime("%H%M%S"), date=self._today, time=prev + "00", krx=self.krx,
                     mku_mid=mid, bid=bid, ask=ask, spread_ticks=spread, mku_last=self.mku_last,
                     last_krx_at=self.last_krx_at, last_quote_at=self.last_quote_at,
                     position=self.expected_position())

    # ------------------------------------------------------------ 끝
    def finish(self, reason: str) -> None:
        """보유 정리(멈춘 실행은 안 함)·끝 잔고·요약을 쓰고 상태를 「끝」/「오류」로. 두 번 불려도 한 번만."""
        with self._lock:
            if self._finished:
                return
            with bind(self.apilog):
                self._finish(reason, to_kst(self.now()))

    def _finish(self, reason: str, now: datetime) -> None:
        if self._finished:
            return
        self._finished = True
        self._finishing = True
        clock = now.strftime("%H%M%S")
        try:
            if self._prepared:
                reason = self._wrap_up(reason, clock)
        except Exception as e:      # 끝내기 기록이 실패해도 상태는 끝으로 남긴다
            self.j.write("event", clock=clock, text="끝내기 처리 실패", error=error_text(e))
            reason = f"{reason} · 끝내기 처리 실패 ({error_text(e)})"
        finally:
            self.ended_at = _iso(now)
            self.ended_reason = reason
            self.state = "오류" if reason.startswith("오류") else "끝"
            self._write_run()
            self._close_feed()

    def _wrap_up(self, reason: str, clock: str) -> str:
        """보유 정리·끝 잔고·summary.json. 바뀐 끝 까닭을 돌려준다."""
        b, j = self.broker, self.j
        try:
            self._settle_now()      # 미룬 체결 알림(거래 기록 포함)을 먼저
        except Exception as e:
            j.write("event", clock=clock, text="끝낼 때 전략에 체결을 알리다 오류", error=error_text(e))
        paper_left = None
        if not self.halted and self.pos is not None and self._in_break(clock):
            if self.orders:
                self.halt(f"휴장 중(20:35~20:50) 끝 — 정리 주문을 내지 않음 · 보유 {self.expected_position():+d}")
            else:
                paper_left = f"휴장 중(20:35~20:50) 끝 — 종이 보유 {self.expected_position():+d} 는 정리 안 함"
                j.write("event", clock=clock, text=paper_left + " (계좌 없음 · 거래 기록에 넣지 않음)")
        if paper_left is None and not self.halted and self.pos is not None:
            pending = self._break_exit or self._exit_retry
            why = (pending or {}).get("reason") or END_REASON
            try:
                if b is not None:
                    # 정리 주문 전에 계좌가 실행과 같은지 본다 — 이미 청산됐는데 또 주문하면 반대 포지션이 생긴다
                    held = b.position()
                    if held is not None and held != self.expected_position():
                        self.halt(f"잔고 불일치 · 기대 {self.expected_position():+d} · 계좌 {held:+d}")
                if not self.halted:
                    self._exit_retry = self._break_exit = None
                    self._app_exit(why)
            except Exception as e:
                self.halt(f"정리 중 오류 — {error_text(e)}")
            if self.pos is not None and not self.halted:
                self.halt(f"끝낼 때 청산되지 않음 · 보유 {self.expected_position():+d}")
        if b is not None:
            held = b.position()
            got = "확인 안 됨" if held is None else f"{held:+d}"
            j.write("event", clock=clock, text=f"끝 잔고 {self.sym} {got}계약")
            if not self.halted and held != self.expected_position():
                self.halt(f"끝 잔고 불일치 · 기대 {self.expected_position():+d} · 계좌 {got}")
        if paper_left is not None:
            reason = f"{reason} · {paper_left}"
        if self.halted:
            reason = f"{reason} · 정리 안 함 — 확인 필요: {self.halted}"
            if self.pos is not None:
                left = f"보유는 그대로 남겨 두었습니다({self.expected_position():+d})"
            else:   # 보유가 있다고 쓰지 않는다 — 결과를 모르는 주문이 계좌에 남겼을 수는 있다
                left = "이 실행이 아는 보유는 없습니다(결과를 모르는 주문이 있었다면 계좌에 남았을 수 있음)"
            j.write("event", clock=clock, text=f"정리하지 않고 끝냄 — {left}. 계좌에서 직접 확인하세요 ({self.halted})")
        open_order = b.open_unknowns() if b is not None else None
        if open_order is not None:
            j.write("event", clock=clock, text=f"끝낼 때 결과를 모르는 주문이 남아 있음 — 계좌·주문내역을 확인하세요 ({open_order})")
        if b is not None:
            self.account_end = b.account(clock, "끝 (수수료·확정손익은 하루 누적)")
        net = [t["net_usd"] for t in self.trades if isinstance(t.get("net_usd"), (int, float))]
        data: dict[str, Any] = {
            "sym": self.sym, "signal_sym": self.signal_sym, "market": self.market.id,
            "currency": self.market.currency, "kind": self.kind, "end_at": self.end_at,
            "trades": self.trades, "summary": summarize(self.trades),
            "engine_net_usd": round(sum(net), 2), "messages": dict(self.counts),
            "feed_overflow": bool(getattr(self.feed, "overflow", False)),
            "account_start": self.account_start, "account_end": self.account_end,
            "api": self.apilog.stats(), "strategy": strategy_block(self.loaded, self.p),
        }
        if self.halted:
            data["halted"] = self.halted
        if paper_left is not None and self.pos is not None:
            data["open_paper_position"] = {k: self.pos.get(k) for k in ("side", "entry", "entry_time")}
        if open_order is not None:
            data["unresolved_order"] = open_order
        write_summary(self.folder, data)
        return reason

    def _close_feed(self) -> None:
        feed = self.feed
        if feed is None:
            return
        try:
            feed.close()
        except Exception as e:      # 닫기 실패가 끝내기를 막지 않게 (앱 종료 때 close_all 이 한 번 더)
            self.j.write("event", text="원문 구독 닫기 실패", error=error_text(e))

    # ------------------------------------------------------------ 실행 스레드 본문
    def run_forever(self) -> None:
        """원문을 꺼내 넣고(없으면 다음 타이머·살림 시각까지 기다림) 1초마다 step. 끝나면 finish, 구독은 언제나 닫음."""
        if not self._prepared:
            return
        try:
            next_step = self.monotonic()
            while not self._finished:
                mono = self.monotonic()
                # 앱 종료 중지는 다음 살림 시각을 기다리지 않는다
                if mono >= next_step or (self._stop_requested and self._shutdown):
                    self.step(self.now())
                    next_step = max(next_step + STEP_SECONDS, mono)
                    if self._finished:
                        break
                wait = max(0.0, min(next_step, self._next_timer) - self.monotonic())
                item = self.feed.get(timeout=wait)
                if item is None:
                    if getattr(self.feed, "closed", False) and not self._finished:
                        self.finish("중지 · 원문 구독이 닫힘")
                        break
                    self.timers()       # 원문이 없어도 지난 타이머를 돌린다(안 그러면 기다림 없이 돈다)
                    continue
                self.handle(item)
        except Exception as e:      # 실행기 자체의 버그 — 보유를 정리하고 오류로 끝낸다
            self.finish(f"오류: {error_text(e)}")
        finally:
            try:
                self.finish("중지")
            finally:
                self._close_feed()

    # ------------------------------------------------------------ 요청 (다른 스레드에서)
    def request_stop(self, shutdown: bool = False) -> None:
        """다음 step 에서 끝낸다(보유가 있으면 정리). `shutdown` 이면 휴장이어도 미루지 않는다."""
        if shutdown:
            self._shutdown = True
        self._stop_requested = True

    def request_flatten(self) -> None:
        """다음 step 에서 보유를 정리하고 실행은 계속한다."""
        self._flatten_requested = True

    # ------------------------------------------------------------ 상태
    @property
    def order_sym(self) -> str | None:
        """이 실행이 주문하는 종목(MKU) — registry 의 「같은 종목 모의 계좌 실행은 하나」 키. KRX 는 키가 아님."""
        return self.sym

    def expected_position(self) -> int:
        """이 실행이 아는 보유 계약 수: 0 · +1(매수) · −1(매도). 브로커의 잔고 관문이 부른다."""
        return self._side_int()

    def halt(self, reason: str) -> None:
        """멈춘다(첫 까닭만 남김). 이후 Engine 에 넣지 않고 주문하지 않는다. 끝에도 정리하지 않는다."""
        if self.halted:
            return
        self.halted = reason
        self.j.write("event", text=f"멈춤 · {reason}")
        if not self._finished:
            self._set_state("확인 필요")

    def status(self) -> dict:
        """화면에 보일 지금 상태(1분봉 `LiveRun.status` 의 칸 + 실시간 칸)."""
        pos = self.pos
        try:
            params = asdict(self.p)
        except Exception:
            params = None
        snap = {k: None for k in SNAPSHOT_KEYS}
        snap.update({
            "position": self.expected_position(),
            "entry": None if pos is None else pos["entry"],
            "today_pnl": round(sum(t["pnl"] for t in self.trades), 2),
            "stops": getattr(self.engine, "stops", None),
            "max_stops": getattr(self.p, "max_stops_per_day", None),
            "halted": self.halted, "last_signal": self.last_signal,
        })
        return {
            **run_head(self.run_id, self.loaded, self.spec.mode, self.sym, self.state, self.started_at,
                       self.ended_at, self.ended_reason),
            "bar_min": None, "next_decision_at": None,
            **snap,
            "params": params,
            "market": self.market.id, "currency": self.market.currency, "kind": self.kind,
            "signal_sym": self.signal_sym, "end_at": self.end_at,
            "side": None if pos is None else pos["side"],
            "held_s": None if pos is None else round(self.monotonic() - pos["entry_mono"], 1),
            "krx": self.krx, "bid": self.bid, "ask": self.ask, "mku_last": self.mku_last,
            "last_dk": self.last_dk, "last_rho": self.last_rho,
            "last_krx_at": self.last_krx_at, "last_quote_at": self.last_quote_at,
            "pending": bool(getattr(self.engine, "pending", False)),
        }

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._write_run()

    def _write_run(self) -> None:
        data: dict[str, Any] = {
            **run_head(self.run_id, self.loaded, self.spec.mode, self.sym, self.state, self.started_at,
                       self.ended_at, self.ended_reason),
            "sha256": self.loaded.sha256,
            "market": self.market.id, "currency": self.market.currency, "kind": self.kind,
            "signal_sym": self.signal_sym,
        }
        if self.halted:
            data["halted"] = self.halted
        write_run_json(self.folder, data)
