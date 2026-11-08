"""장중 실행 — week02 `runner.py` 의 `live()` 를 1초 한 번 부르는 `step()` 으로 나눠 옮긴 것.

실행 하나 = 전략 파일 하나 × 종목 하나 × 하루. 모든 호출은 모의 서버(`environment="paper"`)로 갑니다.
시장(국내 미국달러선물 · 해외 SGX 미니 원달러 MKU)은 `markets` 가 알고, 실행은 그 시장 어댑터로만 1분봉·현재가·
틱 확인·주문·잔고·예수금을 부릅니다(해외 잔고·주문내역은 어댑터가 쪽을 따라감 — 첫 쪽만 보는 `api.ovs_*` 를 직접 부르지 않음).

    prepare()      시작 검사와 준비 봉 (Registry 스레드에서 한 번). 안 되면 `StartRefused`
    step(now)      1초 한 번 — 분이 바뀌고 3초 뒤 1분봉, 매초 현재가, 정리 요청, 잔고 대조
    run_forever()  실행 스레드 본문. 1초마다 step, 끝나면 finish
    finish(reason) 보유 정리·끝 잔고·요약. 두 번 불려도 한 번만

주문 갈래 (`RunSpec.mode`)

    orders  모의계좌에 실제 시장가 주문 (`MockAccountBroker`)
    paper   주문 없이 종이 체결 (`PaperBroker`). 시세(현재가·차트)만 부르고 주문·주문내역·잔고·예수금은 부르지 않음

week02 와 다른 점

- 시작할 때 이 종목 잔고가 있으면 **정리하지 않고 시작을 거부**합니다(누구의 잔고인지 모르므로).
- 실시간 전략(`Loaded.kind == "realtime"`)은 조회·주문 없이 시작을 거부합니다. Params 에 장 시간 칸이 빠진 전략
  (`Loaded.params_missing`)은 MKU 면 해외 시간표로 채우고(`Loaded.new(market)`), 다른 품목이면 week02 처럼 거부합니다.
- 전략 파일의 sha256 과 Params 를 처음 기록에 남깁니다.
- 계좌 잔고를 대조해 실행이 아는 보유와 다르면 **주문을 멈추고 「확인 필요」**로 둡니다: 보유 중 30초마다,
  보유가 바뀌고 5초 뒤, 체결을 못 받은 주문 바로 뒤. 결과를 모르는 주문이 있었으면 보유가 없어도 30초마다.
  대조는 주문이 나갈 수 있는 현재가·정리 요청보다 **먼저** 합니다. 주문 직전엔 브로커가 잔고 관문을 한 번 더 봅니다.
- 멈춘(`halted`) 채로 끝나면 보유를 정리하지 않습니다 — 끝 까닭에 「정리 안 함 — 확인 필요」를 붙입니다.
- 끝낼 때(orders) 정리 주문 전에 잔고를 한 번 대조합니다. 다르면 정리하지 않고 「확인 필요」.
  정리 뒤 끝 잔고가 기대(보통 0)와 다르거나 못 읽어도 「확인 필요」를 붙입니다.
  결과를 모르는 주문이 풀리지 않은 채 끝나면 기록과 summary.json `unresolved_order` 에 남깁니다(잔고가 맞으면 멈추진 않음).
- 조회 실패는 기록하고 다음 초에 다시. 전략 코드 예외는 실행을 「오류」로 끝냅니다(보유는 정리).

시각은 생성자에 넣은 `now()`(한국시간)만 씁니다. 상태(`대기` `진행 중` `확인 필요` `끝` `오류`)가 바뀔 때마다
`run.json` 을 새로 씁니다(임시 파일에 쓰고 바꿔 끼움).

**시장 고르기** — 종목(`leg`, `products.find_product` 가 고른 `Leg`)을 주면 계좌는 종목을 따라(`account_market`),
해외 조회는 그 종목의 거래소·통화(`exch_cd`·`cur_cd`)로 합니다. 틱은 종목 찾기가 품목 세부정보로 이미 확인했으므로
`prepare` 는 최근월물 찾기(`nearest()`)·틱 확인(`spec()`)을 부르지 않고, 전략 `TICK`·`TICK_VALUE` 가 종목과 다르면
조회·주문 없이 거부합니다(`strategy_tick_refusal` — MKU 틱 가치 전략을 HO 에 거는 것 등).
종목을 안 주면 지금 길: `RunSpec.sym` 이 있으면 `markets.market_of(sym)`, 비었으면 전략 `TICK` 으로
(`markets.market_of_tick`: MKU 틱 0.0001 이면 해외 → 해외 마스터의 MKU 최근월물 `nearest_mku`, 아니면 국내 →
`nearest_usd`). **시장 가드**: 종목의 시장과 전략 TICK 의 시장이 다르면(MKU 틱 전략을 `A75…` 에, 또는 반대)
조회·주문 없이 시작을 거부합니다. `run.json`·`status()`·`summary.json` 에 `market`·`currency`(손익·수수료의 통화 —
값은 그 통화, TICK_VALUE 단위)·`product`·`exchange`·`tick`·`tick_value`·`overnight`·`trading_date`·`end` 를 둡니다
(종목 없는 실행은 A75·KRX / MKU·FSGX, 틱은 전략 값).

**실행 끝·시작 검사** (`run_plan`) — 실행 끝은 국내 15:31(모든 품목), 해외 `flatten_at` + 5분(`markets.run_end`).
장 시각 칸이 07:00 보다 이르거나 끝이 24시를 넘으면 자정 넘는 실행(`overnight`, Params 의 07:00 전 시각에 24시간을 더함).
조회·주문 전에 거부하는 것: 국내인데 자정 넘는 전략(국내는 주간만), MKU 가 아닌 품목인데 Params 장 시간 칸이 빠짐,
해외 실행 끝이 다음 날 07:00 을 넘음, 판정이 종목을 모름(`known`), 해외 거래일 마지막 장 끝(`day_end`)이 `flatten_at`
보다 이름(전략 장 시작 시각으로 물어 모르면 건너뜀). 종이 수수료는 전략 `PAPER_FEE`, 없으면 시장 값(`paper_fee_of`).

**자정을 넘는 실행(`plan.overnight`, 설계 4.4)** — 전략과 실행기가 비교하는 시각·날짜를 거래일 시계(`plan.clock`)로 적습니다.
07:00 전 시각은 24를 더하고(00:01 → `"240100"`), 날짜는 그 거래일(자정 뒤 봉도 앞 날짜). 준비 봉·장중 봉(`RunClock.bar`),
준비 봉 자르기, step·끝내기의 시각(진입 창·`hold_min`·재시도·정리·실행 끝 비교, 기록의 `clock`)이 모두 이 시계라 자정을 넘어
한 실행으로 이어집니다. 거래일이 지난 뒤(다음 날 07:00 이후) 온 step 은 시각을 비교하기 전에 날짜로(`_date_passed`)
「장 끝」으로 끝나고(끝 `"310000"` 에도 닿음, 며칠 잠들었다 깨도), 끝내기 기록의 시각은 그 거래일에서 이어 센 값(`"310000"` …,
6자리를 넘으면 `CLOCK_MAX` 로 묶음 — `_label`)입니다. 실제 시각 그대로인 것: 분 바뀜 감지(`_seen_minute`)·잔고 대조 간격,
장 판정(`order_open`·`known`·`day_end` — 거래일 시계는 `plan.clock.moment` 로 되돌려 넘김)·고정 휴장의 지금 시각,
기록의 `at`, 예수금 날짜(`biz_dt` — 시작 때 달력 날짜, 설계 6장 모름). 기록 첫머리에 거래일과 바꾼 Params 를 한 줄 남깁니다.
자정을 넘지 않는 실행은 `RunClock(False)` 라 달력 날짜·실제 시각 그대로입니다. 실행 하나 = 하루라서, 자정 넘지 않는 실행도
시작한 달력 날짜가 지난 뒤 온 step(잠들었다 자정 뒤에 깸)은 「대기」로 다음 장을 기다리지 않고 「장 끝」으로 끝냅니다.

**장 판정(`judge`)** — 꽂으면 아래 「휴장」 규칙의 막힘이 `opening.order_open`(국내 `day` + 09:00 부터, 해외
`open`·`open-2`·`next-day`) 이 아닌 모든 때가 됩니다(쉼·마감·국내 09:00 전·시간표 모름·판정 오류). 보내기 직전 관문
(`may_send`)도 국내까지 꽂고, 기록 글의 까닭은 `opening.span_text`. 실행 중 판정이 종목을 모르게 되면 「장 시간표 모름 —
주문 멈춤」 을 바뀔 때만 한 줄. 안 꽂으면(None) 지금 규칙 — 해외 고정 휴장 20:35~20:50, 국내는 막힘 없음.

**휴장(해외 20:35~20:50)엔 주문이 하나도 나가지 않습니다.** 갈래마다:

    전략·공통 청산 판단    Runner 가 막힌 시각엔 판단만 하고(`break_exit`) 20:50 이후 첫 가격에 그 사유로 청산
    진입 대기 신호         버리지 않고 기다렸다가 20:50 이후 첫 가격에 진입 (Runner)
    청산 재시도            막힌 동안 미룸 (Runner)
    정리 요청(flatten)     요청을 들고 있다가 휴장이 끝난 첫 step 에서 정리
    중지 요청(보유 중)     휴장이 끝난 첫 step 에서 현재가를 한 번 받고 정리한 뒤 끝냄. 휴장 중 정한 청산이
                           있으면 그 사유로(휴장 중 손절 → 「손절」, 하루 손절 수에 들어감)
    앱 종료 중지           `request_stop(shutdown=True)`(registry `stop_all`) — 미루지 않고 바로 끝냄 → 아래 줄
    오류·앱 종료로 끝남     모의 계좌: 정리 주문 없이 멈춤 → 「정리 안 함 — 확인 필요: 휴장 중(20:35~20:50) …」 를
                           run.json·summary.json 에 남김. 종이: 계좌가 없어 「확인 필요」가 아니라
                           「휴장 중 끝 — 종이 보유 +1 는 마지막 가격으로 정리 안 함」(거래 기록에 넣지 않고
                           summary 에 `open_paper_position`). 휴장 중 정한 청산이 남았으면 그 사유를 기록(`break_exit`)

휴장인지는 step 의 시각과 **지금 시각**(`now()`) 둘 다 봅니다 — 20:34:5x 에 시작한 step 이 조회로 늦어져 실제
주문이 20:35 를 넘기지 않게(`Runner.blocked`·끝내기 정리 둘 다). 판단 뒤 브로커 관문의 조회(잔고·주문내역)로 늦어지는
몫은 브로커가 보내기 바로 직전 지금 시각을 한 번 더 봅니다(`may_send` — 걸리면 안 보내고 `held_back`, Runner 가 미룸).

**장중 시작·같은 날 다시 세우기(개장마다 한 번)** — 준비 봉에서 **오늘** 진입 신호(`side`)가 난 개장(신호의
`window`)과, 오늘 같은 NAME·종목·방식의 앞선 실행이 들어간 개장(`windows_before`, registry 가 `journal.entered_windows`
로 셈)은 「이미 진입함」입니다. 준비 봉 뒤 그 개장마다 전략의 `on_entry(window)` 를 불러 되살리고, **바로**
`day.in_position` 을 False 로 되돌립니다(보유는 없으므로). `on_exit` 는 부르지 않습니다 — 그날 손절 수는
`stops_before`(앞선 실행의 실제 손절)로 `day.stops` 에 **한 번만** 넣습니다. 장 전에 켜 오늘 첫 봉에서 전략이 하루를
새로 만들면 손절 수와 개장을 다시 넣고, 그 봉에서 이미 진입한 개장의 대기 신호가 났으면 버립니다.
개장(`window`) 칸이 없는 전략(week02)은 지금처럼 손절 수만 이어받습니다.

**시작 거부(`StartRefused`)여도 `run.json` 은 남습니다** — 상태 「끝」, 끝 까닭 「시작 거부: …」. 화면이 왜
못 시작했는지 보일 수 있게. 주문은 하나도 나가지 않고 `summary.json` 은 쓰지 않습니다.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun import api as default_api
from backend.team_pyrun import tradeday
from backend.team_pyrun.apilog import ApiLog, bind, purpose
from backend.team_pyrun.broker import MockAccountBroker, error_text
from backend.team_pyrun.journal import Journal, summarize, write_summary
from backend.team_pyrun.loader import Loaded
from backend.team_pyrun.markets import (DOMESTIC, Market, adapter_for, in_break, market_of, market_of_tick,
                                        paper_fee_of, run_end)
from backend.team_pyrun.opening import DayEnd, Judge, known, order_open, span_text
from backend.team_pyrun.products import account_market, is_mku, strategy_tick_refusal
from backend.team_pyrun.runner import Minute, PaperBroker, Runner, _entry_args, minute_of
from backend.team_pyrun.tradeday import RunClock, clock_text, is_overnight
from backend.team_spread.legs import Leg

# 팀: 출처는 `markets.DOMESTIC` — 국내 15:30 정리 뒤 이 시각에 끝냄 (week02 와 같음). 실행 끝은 `run_plan(...).end`
END_TIME = DOMESTIC.end_time
#: 종목(`Leg`) 없이 세운 실행의 품목·거래소 — 빈 종목 칸·`A75…`·`MKU…` 만 받으므로 시장으로 정해진다
LEGLESS_PRODUCT = {"domestic": ("A75", "KRX"), "overseas": ("MKU", "FSGX")}
#: 실행 중 판정이 종목을 모르게 됐을 때(`unknown`·예외) 남기는 기록 — 그동안 주문은 판정 관문이 막는다
TIMETABLE_LOST = "장 시간표 모름 — 주문 멈춤"
WARMUP_BARS = 1500          # 준비 봉 개수
LIVE_BARS = 10              # 장중 1분봉 조회 개수
MINUTE_DELAY_SECONDS = 3    # 분이 바뀌고 이만큼 뒤에 막 끝난 1분봉을 받음
RECONCILE_SECONDS = 30      # 보유 중 잔고 대조 간격
RECHECK_SECONDS = 5         # 기대 보유가 바뀐 뒤 잔고를 한 번 더 대조하기까지
STEP_SECONDS = 1.0          # step 간격

#: `status()` 에 들어가는 실행기 상태 칸(`Runner.snapshot`) — 읽다 실패하면 이 칸들을 None 으로 채웁니다.
SNAPSHOT_KEYS = ("position", "entry", "stop", "stop_ticks", "target", "time_exit_at", "today_pnl", "stops",
                 "max_stops", "halted", "last_signal")


@dataclass
class RunSpec:
    """무엇을 돌릴지. `sym` 이 없으면 전략 TICK 의 시장 최근월물(MKU 틱이면 MKU, 아니면 미국달러선물).

    `signal_sym` 은 실시간 실행(`realtime.RealtimeRun`)이 시세로만 보는 KRX 종목(빈칸 = 국내 최근월물).
    1분봉 실행은 쓰지 않습니다. `sym` 은 언제나 **주문하는** 종목입니다."""

    file: str
    #: "replay" 는 녹화 리플레이(`replay.replay_realtime`)만 씀 — 실행 세우기(registry `MODES`)는 여전히 orders·paper 만 받음
    mode: Literal["orders", "paper", "replay"]
    sym: str | None
    signal_sym: str | None = None


class _WindowOnly:
    """`on_entry(window)` 에 개장 이름만 넘기려는 신호 꼴 — `runner._entry_args` 가 이름으로 칸을 찾는다."""

    def __init__(self, window: str | int):
        self.window = window


class StartRefused(Exception):
    """시작 검사에 걸려 실행을 시작하지 않았다. 메시지가 그대로 화면에 간다. 주문은 나가지 않았다."""


def _iso(moment: datetime) -> str:
    """`2026-11-03T09:01:04` 꼴(한국시간, 시간대 꼬리 없음 — journal 과 같은 모양)."""
    return to_kst(moment).replace(tzinfo=None).isoformat(timespec="seconds")


def _minutes(hhmmss: str) -> int:
    return int(hhmmss[:2]) * 60 + int(hhmmss[2:4])


def run_market(sym: str | None, loaded: Loaded) -> tuple[Market, str | None]:
    """(실행의 시장, 거부 까닭 또는 None). 모듈 문서 「시장 고르기」 — registry 와 실행이 같은 규칙을 쓴다.

    종목이 있으면 그 종목의 시장, 없으면 전략 TICK 의 시장. 종목의 시장이 모르는 것이거나 전략 TICK 의 시장과
    다르면 까닭을 돌려준다(이때 시장은 전략 TICK 의 것 — 전략 Params 를 채우는 데만 쓰고 조회는 하지 않음)."""
    by_tick = market_of_tick(loaded.tick)
    if not sym:
        return by_tick, None
    try:
        by_sym = market_of(sym)
    except ValueError as e:
        return by_tick, str(e)
    if by_sym is not by_tick:
        return by_tick, (f"종목의 시장과 전략 틱이 맞지 않습니다 — 종목 {sym} 은 {by_sym.id}({by_sym.currency}), "
                         f"전략 TICK {loaded.tick:g} 는 {by_tick.id}({by_tick.currency})")
    return by_sym, None


def _hhmmss(moment: datetime) -> str:
    return to_kst(moment).strftime("%H%M%S")


@dataclass(frozen=True)
class RunPlan:
    """실행 하나의 시계 계획 — registry·autostart·replay 가 실행과 같은 값을 쓰게 한 곳(`run_plan`)에서 셈.

    `params_cls` 는 빠진 장 시간 칸을 채우고(MKU), 자정 넘는 실행이면 07:00 전 시각에 24시간을 더한 Params.
    `end` 는 실행 끝(거래일 시계 — 24시를 넘으면 `"240300"` 처럼)."""

    params_cls: type
    overnight: bool
    end: str
    clock: RunClock


def _end_of(market: Market, params: object) -> str:
    flatten = getattr(params, "flatten_at", None)
    if not (isinstance(flatten, str) and len(flatten) == 6 and flatten.isdigit()):
        return market.end_time      # flatten_at 이 없는 Params(실시간 전략) — 1분봉 실행은 prepare 가 거부한다
    return run_end(market, flatten)


def run_plan(loaded: Loaded, market: Market) -> RunPlan:
    """채운 Params 기본값의 `flatten_at` 으로 실행 끝(`markets.run_end`) → 자정 넘는 실행인가(`tradeday.is_overnight`)
    → 그렇다면 07:00 전 시각을 바꾼 Params 로 끝도 다시 (설계 4.4·4.5)."""
    cls = loaded.params_for(market)
    end = _end_of(market, cls())
    overnight = is_overnight(cls(), end)
    if overnight:
        cls = loaded.params_for(market, overnight=True)
        end = _end_of(market, cls())
    return RunPlan(params_cls=cls, overnight=overnight, end=end, clock=RunClock(overnight))


#: 거래일에서 이어 센 시각의 끝 — 6자리를 넘지 않게(100시간 넘게 지난 step 은 여기로 묶음, `_trading_clock`)
CLOCK_MAX = "995959"


def _trading_clock(trading_date: str, moment: datetime) -> str:
    """거래일 0시부터 센 시각(HHMMSS, 24시를 넘어 셈) — 다음 날 06:15 → `"301500"`, 다음 날 07:00 → `"310000"`.

    거래일 시계(`RunClock(True).label`)와 07:00 전까지 같고, 07:00 이후(CME 겨울 07:00 끝 등)도 다음 거래일로 넘기지 않는다.
    언제나 6자리 — 거래일 0시보다 이르면 `"000000"`, 100시간 이상이면 `CLOCK_MAX`(문자열 비교·기록이 틀리지 않게)."""
    secs = int((to_kst(moment) - RunClock(True).moment(trading_date, "000000")).total_seconds())
    secs = min(max(secs, 0), 99 * 3600 + 59 * 60 + 59)
    return f"{secs // 3600:02d}{secs % 3600 // 60:02d}{secs % 60:02d}"


# ---------------------------------------------------------------- 1분봉·실시간 실행이 같이 쓰는 것 (주문과 무관)
def write_run_json(folder: Path, data: dict) -> None:
    """`run.json` — 임시 파일에 쓰고 바꿔 끼운다(읽는 쪽이 덜 쓴 파일을 보지 않게)."""
    path = Path(folder) / "run.json"
    tmp = path.with_name(f".run.json.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def run_head(run_id: str, loaded: Loaded, mode: str, sym: str | None, state: str, started_at: str | None,
             ended_at: str | None, ended_reason: str | None) -> dict:
    """`run.json`·`status()` 의 앞 칸(순서 고정) — 두 실행기가 같은 꼴로 쓴다."""
    return {"id": run_id, "file": loaded.file, "name": loaded.name, "title": loaded.title,
            "mode": mode, "sym": sym, "state": state,
            "started_at": started_at, "ended_at": ended_at, "ended_reason": ended_reason}


def strategy_block(loaded: Loaded, params: object) -> dict:
    """`summary.json` 의 `strategy` 칸."""
    return {"file": loaded.file, "name": loaded.name, "title": loaded.title,
            "sha256": loaded.sha256, "params": asdict(params)}


def _window(signal: object) -> str | int | None:
    """신호의 개장 이름(`window`) — 문자·정수만."""
    w = getattr(signal, "window", None)
    return w if isinstance(w, (str, int)) and not isinstance(w, bool) else None


def _signal_date(signal: object) -> str | None:
    """신호 판정 봉의 날짜(`bar` 또는 `minute` 의 `date`). 모르면 None."""
    b = getattr(signal, "bar", None) or getattr(signal, "minute", None)
    return getattr(b, "date", None)


class LiveRun:
    """장중 실행 하나. Registry 가 만들고 `prepare()` 뒤 데몬 스레드에서 `run_forever()` 를 돌린다.

    `step()`·`finish()` 는 잠금 안에서 돌아 서로 겹치지 않습니다. `status()`·`request_*()` 는 잠그지 않습니다
    (체결 확인으로 step 이 15초까지 걸릴 수 있어 화면이 기다리지 않게)."""

    def __init__(self, run_id: str, folder: Path, loaded: Loaded, spec: RunSpec, *,
                 api_module: ModuleType | Any = default_api, now: Callable[[], datetime] = now_kst,
                 sleep: Callable[[float], None] = time.sleep, stops_before: int = 0,
                 windows_before: tuple | list | set | frozenset = (), leg: Leg | None = None,
                 judge: Judge | None = None, day_end: DayEnd | None = None):
        self.run_id, self.folder, self.loaded, self.spec = run_id, Path(folder), loaded, spec
        self.now, self.sleep = now, sleep
        self.kind = "minute"
        self.stops_before = int(stops_before)
        #: 오늘 앞선 실행이 들어간 개장 — prepare 에서 「이미 진입함」으로 되살린다
        self.windows_before: tuple = tuple(sorted(windows_before, key=str))
        #: 종목 찾기(`products.find_product`)가 고른 종목. 없으면 지금 길(`run_market`·`nearest()`·`spec()`)
        self.leg = leg
        #: 장 판정(`opening.Judge`)·해외 거래일 끝(`opening.DayEnd`). judge 가 None 이면 지금 규칙(고정 휴장 `in_break`)
        self.judge, self.day_end = judge, day_end
        # 팀: 시장과 그 어댑터 — 1분봉·현재가·틱·브로커·예수금은 전부 이 어댑터로
        if leg is not None:
            # 계좌는 종목을 따라(국내/해외), 해외 조회는 그 종목의 거래소·통화로. 틱은 종목 찾기가 이미 확인했다
            self.market = account_market(leg)
            self._market_refusal = strategy_tick_refusal(leg, loaded)
            self.api = (adapter_for(self.market, api_module) if self.market.id == "domestic" else
                        adapter_for(self.market, api_module, exch_cd=leg.exchange, cur_cd=leg.currency))
            self.product, self.exchange, self.currency = leg.product, leg.exchange, leg.currency
            self.tick, self.tick_value = leg.tick, leg.tick_value
        else:
            self.market, self._market_refusal = run_market(spec.sym, loaded)
            self.api = adapter_for(self.market, api_module)
            self.product, self.exchange = LEGLESS_PRODUCT[self.market.id]
            self.currency = self.market.currency
            self.tick, self.tick_value = loaded.tick, loaded.tick_value
        #: Params·자정 넘는 실행인가·실행 끝 (모듈 문서 「실행 끝」)
        self.plan = run_plan(loaded, self.market)
        self.trading_date: str | None = None
        self.folder.mkdir(parents=True, exist_ok=True)
        self.j = Journal(self.folder / "journal.jsonl")
        self.apilog = ApiLog(self.folder / "api_log.jsonl", run_id)
        self.orders = spec.mode == "orders"
        # orders 의 MockAccountBroker 는 종목이 정해지는 prepare() 에서 만든다. 종이 수수료는 전략 PAPER_FEE, 없으면 시장 값
        self.broker: MockAccountBroker | PaperBroker | None = None if self.orders else PaperBroker(
            self.j, loaded.tick, fee=paper_fee_of(self.market, loaded.paper_fee),
            slip_ticks=self.market.paper_slip_ticks)
        # 빠진 Params 장 시간 칸은 시장 값으로 채운다(MKU 가 아니면 prepare 가 거부)
        self.runner = Runner(loaded.new(self.market, overnight=self.plan.overnight), self.j, self.broker,
                             loaded.tick, loaded.tick_value)
        self.runner.stops_before = self.stops_before   # 화면의 오늘 손절 수용(전략에 day 가 없을 때)
        self.runner.currency = self.currency
        self.runner.blocked = self._in_break    # 주문이 닫힌 동안엔 체결을 부르지 않음 (step 시각과 지금 시각 둘 다 봄)
        self.sym: str | None = leg.sym if leg is not None else spec.sym
        self.state = "대기"
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.ended_reason: str | None = None
        self.account_start: dict | None = None
        self.account_end: dict | None = None
        self._lock = threading.RLock()
        self._prepared = False
        self._finished = False
        self._stop_requested = False
        self._flatten_requested = False
        self._today = ""
        self._last_fed: tuple[str, str] = ("", "")    # 마지막으로 전략에 넣은 1분봉 (date, time)
        self._seen_minute = ""                         # 1분봉을 받아 넣은 마지막 분 (HHMM)
        self._last_check: datetime | None = None       # 마지막 잔고 대조 시각
        self._last_exp = 0                             # 마지막 step 의 기대 보유
        self._recheck_at: datetime | None = None       # 기대 보유가 바뀐 뒤 한 번 더 대조할 시각
        self._day_obj: object | None = None            # 앞선 손절 수를 넣어 둔 전략의 하루 상태 객체
        self._windows: tuple = ()                      # 「이미 진입함」으로 되살린 개장 (준비 봉 신호 + 앞선 실행)
        self._stop_deferred = False                    # 휴장 중 중지 요청을 미뤘음 — 풀리면 현재가를 받고 정리
        self._shutdown = False                         # 앱 종료 중지 — 휴장이어도 미루지 않고 바로 끝냄(정리는 안 함)
        self._break_noted: set[str] = set()            # 이번 휴장에 「요청을 미룬다」 기록을 남긴 요청 (stop·flatten)
        self._clock_date = ""                          # step 시각(`clock`)의 날짜(자정 넘는 실행은 거래일) — 판정에 넘길 시각을 되살림
        self._timetable_lost = False                   # 실행 중 판정이 종목을 모름(`unknown`·예외) — 바뀔 때만 기록

    # ------------------------------------------------------------ 시작
    def prepare(self) -> None:
        """시작 검사와 준비 봉. 안 되면 `StartRefused`(주문 없음, run.json 은 「끝」으로 남김)."""
        with self._lock, bind(self.apilog):
            if self._prepared or self._finished:
                raise StartRefused("이미 시작했거나 끝난 실행입니다")
            now = to_kst(self.now())
            self.started_at = _iso(now)
            self.trading_date = self.plan.clock.label(now)[0]
            self._write_run()
            try:
                self._prepare(now)
            except StartRefused as e:
                self._refuse(str(e))
                raise
            except Exception as e:      # 조회 실패·응답 해석 실패·준비 봉에서 난 전략 오류
                msg = f"시작 준비 실패 — {error_text(e)}"
                self._refuse(msg)
                raise StartRefused(msg) from e
            self._prepared = True
            self._set_state("대기" if self._label(now)[1] < self.runner.p.session_start else "진행 중")

    def _prepare(self, now: datetime) -> None:
        j, api, loaded, r, plan = self.j, self.api, self.loaded, self.runner, self.plan
        today, clock = self._label(now)     # 실행의 (거래일, 거래일 시계) — 자정 넘지 않는 실행은 달력 그대로
        self._today = today
        self._clock_date = today
        market = self.market
        # 0. 이 실행기로 돌릴 수 있는 전략인가 — 조회·주문 전에 거부
        if loaded.kind != "minute":
            raise StartRefused("실시간 전략(on_krx·on_quote)은 1분봉 실행으로 시작할 수 없습니다")
        if self._market_refusal:        # 시장 가드·틱 확인 — 조회 전에 (모듈 문서 「시장 고르기」)
            raise StartRefused(self._market_refusal)
        if market.id == "domestic" and plan.overnight:
            raise StartRefused("국내는 주간(08:45~15:45)만 돕니다 — 07:00 전 시각이 있는 전략은 국내 종목에 걸 수 없습니다")
        if loaded.params_missing and not is_mku(self.product):
            # 빠진 칸을 시장 시간표로 채우는 것은 MKU 만(week03 ORB) — 다른 품목은 Params 에 적힌 칸으로만 돈다
            raise StartRefused(f"Params 에 장 시간 칸이 없습니다 ({', '.join(loaded.params_missing)}) — "
                               "이 품목은 Params 에 적어야 합니다")
        if market.id == "overseas" and plan.end > tradeday.DAY_ENDS:
            raise StartRefused(f"실행 끝({clock_text(plan.end)})이 다음 날 07:00 을 넘습니다 — flatten_at 을 당기세요")
        # 1. 어디로·무엇을
        j.write("event", text=f"서버 paper · 주문 {'모의계좌' if self.orders else '종이'}")
        if market is not DOMESTIC:
            breaks = ("장 시간표대로" if self.judge is not None else
                      ", ".join(f"{a[:2]}:{a[2:4]}~{b[:2]}:{b[2:4]}" for a, b in market.breaks) or "없음")
            j.write("event", text=f"시장 {market.id} · 통화 {self.currency} · 실행 끝 {clock_text(plan.end)} · 휴장 {breaks}")
        if plan.overnight:
            j.write("event", text=self._overnight_text(today))
        j.write("event", text=f"전략 {loaded.file} · sha256 {loaded.sha256[:12]} · Params {asdict(r.p)}")
        # 2. 종목과 틱 — registry 가 같은 종목 검사에 쓴 종목(`self.sym`)이 먼저. 다시 고르면 월물이 넘어가는 날
        #    검사한 종목과 주문하는 종목이 달라질 수 있다(RealtimeRun 과 같은 규칙)
        sym = self.sym or self.spec.sym
        if not sym:
            with purpose("종목 찾기"):
                sym = api.nearest()
        self.sym = sym
        self._check_timetable(sym, now)     # 장 판정 — NH 조회 없이 (종목 다리면 조회 0번)
        if self.leg is not None:
            tick, value = self.leg.tick, self.leg.tick_value   # 종목 찾기가 품목 세부정보로 이미 확인 (전략 값과도 같음)
        else:
            with purpose("틱 확인"):
                tick, value = api.spec()
            if not (math.isclose(tick, loaded.tick, rel_tol=1e-9)
                    and math.isclose(value, loaded.tick_value, rel_tol=1e-9)):
                raise StartRefused(f"틱·틱가치가 전략 가정과 다릅니다 — 서버 {tick:g}·{value:g}, "
                                   f"전략 {loaded.tick:g}·{loaded.tick_value:g}")
        if market is DOMESTIC:
            j.write("event", text=f"종목 {sym} · 틱 {tick:g} · 틱가치 {value:,.0f}")
        else:
            j.write("event", text=f"종목 {sym} · 틱 {tick:g} · 틱가치 {value:g} {self.currency}")
        self._write_run()
        # 3. 모의계좌: 시작 잔고가 0 이어야 한다
        if self.orders:
            # 보내기 직전 관문 — 해외(고정 휴장), 판정을 꽂았으면 국내도(모의 주문 09:00 부터)
            # 예수금 날짜(`biz_dt`)는 시작 때의 달력 날짜 그대로 — 자정 넘는 실행에 어떤 날짜가 맞는지는 설계 6장 「모름」
            broker = MockAccountBroker(api, sym, j, sleep=self.sleep, today=now.strftime("%Y%m%d"),
                                       expected=r.expected_position, halt=r.halt,
                                       may_send=self._may_send if market.breaks or self.judge is not None else None)
            held = broker.position()
            if held is None:
                raise StartRefused("시작 잔고를 확인하지 못했습니다")
            if held != 0:
                raise StartRefused(f"{sym} 잔고 {held:+d}계약이 남아 있습니다 — 정리한 뒤 시작하세요")
            j.write("event", text=f"시작 잔고 {sym} {held:+d}계약")
            self.account_start = broker.account(clock, "시작 (수수료·확정손익은 하루 누적)")
            if self.account_start:
                broker.last_fee = self.account_start["fee"]
            self.broker = r.broker = broker
        # 4. 준비 봉: 지금 분보다 앞선 것만, 시각순 (봉·자르는 기준 둘 다 실행의 시계)
        now_min = clock[:4] + "00"
        with purpose("준비 봉"):
            got = [plan.clock.bar(minute_of(x)) for x in api.chart_minute(sym, req_qty=WARMUP_BARS)]
        hist = sorted((m for m in got if (m.date, m.time) < (today, now_min)), key=lambda m: (m.date, m.time))
        signals = r.warmup(hist)
        r.live_date = today       # 준비 봉에서 난 오늘 신호로는 진입하지 않음 — 이 뒤로 닫히는 봉부터
        day = getattr(r.strat, "day", None)
        if self.stops_before and day is not None:
            day.stops = self.stops_before
            j.write("event", text=f"오늘 앞선 실행의 손절 {self.stops_before}회를 이어받음 "
                                  f"(한도 {getattr(r.p, 'max_stops_per_day', '?')}회)")
        elif self.stops_before:     # 하루 상태(`day`)가 없는 전략 — 손절 수를 넣을 자리가 없다
            j.write("event", text=f"전략에 하루 상태(day)가 없어 오늘 앞선 실행의 손절 {self.stops_before}회를 이어받지 않음")
        # 개장마다 한 번 — 준비 봉에서 오늘 진입 신호가 난 개장 + 앞선 실행이 들어간 개장 (모듈 문서)
        fired = {w for s in signals if getattr(s, "side", None) and _signal_date(s) == today
                 and (w := _window(s)) is not None}
        self._windows = tuple(sorted(fired | set(self.windows_before), key=str))
        if self._windows:
            self._restore_windows()
            parts = [f"{w}({'준비 봉 신호' if w in fired else ''}{'·' if w in fired and w in self.windows_before else ''}"
                     f"{'앞선 실행' if w in self.windows_before else ''})" for w in self._windows]
            j.write("event", text=f"이미 진입한 개장 — {', '.join(parts)}: 오늘 다시 들어가지 않음",
                    windows=list(self._windows))
        self._day_obj = getattr(r.strat, "day", None)
        self._last_fed = (hist[-1].date, hist[-1].time) if hist else ("", "")
        self._seen_minute = now.strftime("%H%M")       # 분 바뀜 감지는 실제 시각
        self._last_check = now

    def _label(self, now: datetime) -> tuple[str, str]:
        """실행의 (날짜, 시각) — 거래일 시계(`plan.clock.label`, 자정 넘지 않는 실행은 달력 그대로).

        실행 하나 = 하루. 실행의 날짜(`trading_date` — 자정 넘는 실행은 거래일, 아니면 시작 때 달력 날짜)가 지난 뒤면
        (`_date_passed` — 그 step 은 시각을 비교하기 전에 「장 끝」으로 끝남) 끝내기 정리·기록의 시각은 그 날짜에서 이어 센
        시각(`_trading_clock` — 자정 넘는 실행의 다음 날 07:00 → `"310000"`, 자정 넘지 않는 실행의 다음 날 00:10 →
        `"241000"`, 100시간 넘게 지나면 `CLOCK_MAX`). 다음 날 이른 시각으로 되감기지 않고, 날짜는 실행의 날짜라
        `_moment` 가 실제 시각으로 되돌린다."""
        date, clock = self.plan.clock.label(now)
        if self._date_passed(date):
            return self.trading_date, _trading_clock(self.trading_date, now)
        return date, clock

    def _date_passed(self, date: str) -> bool:
        """`date`(실행 시계의 날짜)가 실행의 날짜(`trading_date`)보다 늦은가 — 실행 하나 = 하루, 지났으면 끝낸다."""
        return bool(self.trading_date) and date > self.trading_date

    def _overnight_text(self, trading_date: str) -> str:
        """기록 첫머리 한 줄 — 자정 넘는 실행의 거래일과 07:00 전이라 24시간을 더한 Params 칸(원래 값→바꾼 값)."""
        before, after = self.loaded.params_for(self.market)(), self.runner.p
        changed = [f"{n} {getattr(before, n)}→{getattr(after, n)}" for n in tradeday.SCHEDULE_FIELDS
                   if hasattr(before, n) and getattr(before, n) != getattr(after, n)]
        return (f"자정을 넘는 실행 — 거래일 {trading_date}, 시각은 07:00 전이면 +24 (예 01:30 → 253000). "
                f"바꾼 Params: {', '.join(changed) or '없음'}")

    def _restore_windows(self) -> None:
        """「이미 진입함」 개장을 전략에 되살린다 — `on_entry(window)` 뒤 바로 `day.in_position = False`.

        `on_exit` 는 부르지 않는다(손절 수를 또 세지 않게 — 그날 손절은 `stops_before` 로 한 번만).
        `on_entry` 가 없는 전략이면 되살릴 자리가 없으니 기록만 남기고, 앱이 대기 신호를 버리는 것으로 막는다."""
        r = self.runner
        fn = getattr(r.strat, "on_entry", None)
        day = getattr(r.strat, "day", None)
        if fn is None or day is None or not hasattr(day, "in_position"):
            # on_entry 를 부르면 보유 표지가 켜지는데 앱이 되돌릴 자리(day.in_position)가 없다 — 부르지 않는다
            self.j.write("event", text="전략에 on_entry 나 day.in_position 이 없어 개장을 되살리지 않음 — "
                                       "그 개장의 대기 신호는 앱이 버림")
            return
        for w in self._windows:
            args, kwargs = _entry_args(fn, _WindowOnly(w))     # 인자 대응이 틀리면 TypeError → 시작 거부
            fn(*args, **kwargs)
            day = getattr(r.strat, "day", None)
            if day is not None and hasattr(day, "in_position"):
                day.in_position = False     # 되살리기만 — 이 실행은 보유가 없다

    def _check_timetable(self, sym: str, now: datetime) -> None:
        """시작 때 장 판정 (설계 4.3) — 시간표가 이 종목을 모르면 거부(조용히 주문 안 하는 실행이 서지 않게).
        해외는 그 거래일 마지막 장 끝이 `flatten_at` 보다 이르면 거부. 장 시작 시각이 거래 창 밖이라 끝을 모르면(None) 건너뜀."""
        mid = self.market.id
        if self.judge is not None and not known(self.judge, mid, sym, now):
            raise StartRefused("장 시간표에 이 종목이 없습니다 — 화면 「장 시간」에서 확인하세요")
        if mid != "overseas" or self.day_end is None:
            return
        p, date = self.runner.p, self.trading_date or self._today
        # 지금(장 전 5분이면 창 밖)이 아니라 전략 장 시작 시각으로 묻는다
        end_at = self.day_end(mid, sym, self.plan.clock.moment(date, str(p.session_start)))
        if end_at is None:
            return
        flat, closes = tradeday.shift(str(p.flatten_at)), _trading_clock(date, end_at)
        if closes < flat:
            raise StartRefused(f"장이 정리 시각({clock_text(flat)}) 전에 닫힙니다(장 끝 {clock_text(closes)})")

    def _refuse(self, msg: str) -> None:
        self.j.write("event", text=f"시작 거부 · {msg}")
        self._finished = True
        self.ended_at = _iso(self.now())
        self.ended_reason = f"시작 거부: {msg}"
        self.state = "끝"
        self._write_run()

    # ------------------------------------------------------------ 1초 한 번
    def step(self, now: datetime) -> None:
        """1초 한 번. 끝났거나 아직 준비하지 않은 실행은 아무것도 하지 않는다."""
        with self._lock:
            if not self._prepared or self._finished:
                return
            with bind(self.apilog):
                self._step(to_kst(now))

    def _step(self, now: datetime) -> None:
        r = self.runner
        if self._date_passed(self.plan.clock.label(now)[0]):
            # 실행의 날짜가 지났다(자정 넘는 실행은 다음 날 07:00, 아니면 자정 — 며칠 잠들었다 깬 것 포함). 시각 문자열을
            # 비교하기 전에 날짜로 정해 「장 끝」 — 「대기」로 다음 장을 기다리지 않는다
            self._finish("장 끝", now)
            return
        self._clock_date, clock = self._label(now)     # 거래일 시계 — 판정엔 `_moment` 로 실제 시각을 되살려 넘김
        self._note_timetable(now, clock)
        in_brk = self._in_break(clock)
        held_in_break = in_brk and r.pos is not None and not r.halted
        if not in_brk and self._break_noted:
            self._break_noted = set()
        if clock >= self.plan.end:
            self._finish("장 끝", now)
            return
        if self._stop_requested and held_in_break and not self._shutdown:
            # 팀: 휴장 중엔 정리 주문을 낼 수 없다 — 휴장이 끝난 첫 step 에서 현재가를 받고 정리한 뒤 끝낸다
            self._stop_deferred = True
            self._note_break("stop", clock, "휴장 중 중지 요청 — 휴장이 끝나면 정리하고 끝냄",
                             "중지 요청 — 장이 열리면 정리하고 끝냄")
        elif self._stop_requested:
            if self._stop_deferred and r.pos is not None and not r.halted:
                self._fresh_price(clock)    # 정리 기준가를 휴장 전 가격이 아니라 지금 가격으로 (전략에는 안 넣음)
            self._finish("중지", now)
            return
        if clock < r.p.session_start:
            self._set_state("대기")
            return
        self._set_state("확인 필요" if r.halted else "진행 중")
        try:
            # 조회 실패는 아래 함수들이 안에서 잡는다 — 여기까지 올라오는 예외는 전략·실행기 코드에서 난 것
            self._feed_minutes(now, clock)
            self._reconcile(now, clock)     # 주문이 나갈 수 있는 현재가·정리 요청보다 먼저 대조
            self._feed_price(clock)
            if self._flatten_requested and self._in_break(clock) and r.pos is not None:
                self._note_break("flatten", clock, "휴장 중 정리 요청 — 휴장이 끝난 첫 가격에 정리",
                                 "정리 요청 — 장이 열린 첫 가격에 정리")   # 요청은 들고 있는다
            elif self._flatten_requested:
                self._flatten_requested = False
                self.j.write("event", clock=clock, text="정리 요청 — 보유가 있으면 정리")
                r.force_flat(clock)
            self._reconcile(now, clock)     # 체결을 못 받은 주문(fill → None)이 있었으면 바로 한 번 더
        except Exception as e:
            self._finish(f"오류: {error_text(e)}", now)
            return
        if r.halted:
            self._set_state("확인 필요")

    def _in_break(self, clock: str) -> bool:
        """주문이 닫혔는가(휴장) — step 의 시각과 **지금** 시각(`now()`) 둘 다 본다. 20:34:5x 에 시작한 step 이 조회로
        늦어져 실제 주문이 20:35 를 넘기지 않게(주문 직전 `Runner.blocked` 가 이걸 부름).

        판정(`judge`)을 꽂았으면 두 시각 모두 `opening.order_open` 이어야 열림(국내 09:00 전·쉼·마감·시간표 모름은 닫힘).
        안 꽂았으면 지금 규칙 — 해외 고정 휴장(`in_break`), 국내는 막힘 없음."""
        if self.judge is not None:
            return not (self._order_open(self._moment(clock)) and self._order_open(self.now()))
        if not self.market.breaks:      # 국내 — 휴장이 없다(시계도 부르지 않음, week02 그대로)
            return False
        return in_break(self.market, clock) or in_break(self.market, _hhmmss(self.now()))

    def _may_send(self) -> bool:
        """브로커가 주문을 보내기 **바로 직전** 묻는 것 — 지금 시각(`now()`)에 주문이 열려 있는가
        (판정이 있으면 `order_open`, 없으면 해외 고정 휴장이 아닌가 — 판정이 없으면 해외만 꽂음).

        `Runner.blocked` 는 판단 때 한 번 보지만, 그 뒤 브로커 관문의 조회(잔고·주문내역·재시도)로 20:35 를 넘길 수 있다."""
        if self.judge is not None:
            return self._order_open(self.now())
        return not in_break(self.market, _hhmmss(self.now()))

    def _order_open(self, at: datetime) -> bool:
        return order_open(self.judge, self.market.id, self.sym or "", at)

    def _moment(self, clock: str) -> datetime:
        """step 시각(`clock`)을 판정에 넘길 한국시간으로 — 그 step 의 날짜(`_clock_date`)와 실행 시계로.
        100시간 넘게 지나 묶인 시각(`CLOCK_MAX`)은 되살릴 수 없으므로 지금 시각(`now()`)."""
        if clock >= CLOCK_MAX:
            return to_kst(self.now())
        return self.plan.clock.moment(self._clock_date or self._today, clock)

    def _closed_text(self, clock: str) -> str:
        """주문이 닫힌 까닭 글 — 판정이 있으면 닫힌 쪽 시각의 `opening.span_text`, 없으면 고정 휴장 시각."""
        if self.judge is not None:
            at = self._moment(clock)
            if self._order_open(at):
                at = self.now()         # step 시각엔 열렸고 지금 닫혔다
            return f"장 닫힘({span_text(self.judge, self.market.id, self.sym or '', at)})"
        now_t = _hhmmss(self.now())
        span = next((f"{a[:2]}:{a[2:4]}~{z[:2]}:{z[2:4]}" for a, z in self.market.breaks
                     if a <= clock < z or a <= now_t < z), "휴장")
        return f"휴장 중({span})"

    def _note_timetable(self, now: datetime, clock: str) -> None:
        """실행 중 판정이 종목을 모르게 되거나(`unknown`·예외) 다시 알게 될 때만 기록 한 줄. 그동안 주문은 관문이 막는다."""
        if self.judge is None:
            return
        lost = not known(self.judge, self.market.id, self.sym or "", now)
        if lost != self._timetable_lost:
            self._timetable_lost = lost
            self.j.write("event", clock=clock, text=TIMETABLE_LOST if lost else "장 시간표 다시 확인 — 주문 받음")

    def _note_break(self, key: str, clock: str, text: str, judged: str) -> None:
        """휴장 중 미룬 요청 — 요청마다 휴장 하나에 한 번만 기록. 판정이 있으면 「장 닫힘(까닭) 중 {judged}」."""
        if key not in self._break_noted:
            self._break_noted.add(key)
            self.j.write("event", clock=clock, text=text if self.judge is None else f"{self._closed_text(clock)} 중 {judged}")

    def _feed_minutes(self, now: datetime, clock: str) -> None:
        """분이 바뀌고 3초 뒤: 막 끝난 1분봉(들)을 시각순으로 한 번씩 전략에 넣는다.

        분 바뀜은 실제 시각(`hhmm`)으로 보고, 봉과 「지금 분」(`now_key`)은 실행의 시계(`clock`·`_clock_date`)로 비교한다."""
        hhmm = now.strftime("%H%M")
        if hhmm == self._seen_minute or now.second < MINUTE_DELAY_SECONDS:
            return
        try:
            with purpose("1분봉"):
                got = [self.plan.clock.bar(minute_of(x)) for x in self.api.chart_minute(self.sym, req_qty=LIVE_BARS)]
        except Exception as e:      # 연결·응답 문제로 하루 실행이 멈추지 않게 — 기록하고 다음 초에 다시
            self.j.write("event", clock=clock, text="차트(분) 처리 실패 — 다음 초에 다시", error=error_text(e))
            return
        now_key = (self._clock_date, clock[:4] + "00")
        for m in sorted((m for m in got if self._last_fed < (m.date, m.time) < now_key),
                        key=lambda m: (m.date, m.time)):
            if (m.date, m.time) <= self._last_fed:
                continue            # 같은 봉이 두 번 온 경우
            self.runner.on_minute_closed(m)
            self._last_fed = (m.date, m.time)
            self._carry_stops(m)
            self._drop_entered_window(m)
        self._seen_minute = hhmm

    def _carry_stops(self, m: Minute) -> None:
        """전략이 오늘 첫 봉에서 하루 상태(`day`)를 새로 만들었으면, 앞선 실행의 손절 수를 다시 넣는다.

        장 전에 켜면 준비 봉이 어제 것뿐이라, prepare 에서 넣은 값이 오늘 첫 봉에서 지워지기 때문입니다."""
        day = getattr(self.runner.strat, "day", None)
        if not (self.stops_before or self._windows) or day is None or day is self._day_obj or m.date != self._today:
            return
        self._day_obj = day
        if self.stops_before and getattr(day, "stops", 0) < self.stops_before:
            day.stops = self.stops_before
            self.j.write("event", clock=m.time, text=f"오늘 앞선 실행의 손절 {self.stops_before}회를 다시 넣음 "
                                                     f"(전략이 하루를 새로 시작함)")
        if self._windows:       # 하루를 새로 만들며 지운 「이미 진입함」 개장도 다시 넣는다
            self._restore_windows()
            self.j.write("event", clock=m.time, text=f"이미 진입한 개장 {', '.join(map(str, self._windows))} 를 다시 넣음 "
                                                     f"(전략이 하루를 새로 시작함)")

    def _drop_entered_window(self, m: Minute) -> None:
        """「이미 진입함」 개장의 대기 신호는 버린다 — 오늘 첫 봉에서 전략이 하루를 새로 만들어 되살리기 전에 신호를
        낸 경우, 또는 `on_entry` 가 없어 전략에 되살릴 수 없는 경우를 막는 마지막 자리."""
        pending = self.runner.pending
        if not self._windows or pending is None or m.date != self._today:
            return
        w = _window(pending.get("obj"))
        if w is not None and w in self._windows:
            self.runner.pending = None
            self.j.write("event", clock=m.time, text=f"{w} 개장은 오늘 이미 진입함 — 대기 신호를 버림")

    def _fresh_price(self, clock: str) -> None:
        """현재가 한 번 — 실행기의 마지막 가격만 바꾼다(전략 판단 없음). 실패·0 이면 그대로."""
        try:
            with purpose("현재가"):
                q = self.api.price(self.sym)
            px = self.api.num(q.get("last_pric")) if isinstance(q, dict) else None
        except Exception as e:
            self.j.write("event", clock=clock, text="현재가 처리 실패 — 마지막 가격으로 정리", error=error_text(e))
            return
        if px is not None and px > 0:
            self.runner.last_price = px

    def _feed_price(self, clock: str) -> None:
        """현재가 한 번. 0·빈 값이면 판단하지 않는다."""
        try:
            with purpose("현재가"):
                q = self.api.price(self.sym)
            px = self.api.num(q.get("last_pric")) if isinstance(q, dict) else None
        except Exception as e:
            self.j.write("event", clock=clock, text="현재가 처리 실패 — 다음 초에 다시", error=error_text(e))
            return
        if px is None or px <= 0:
            return
        self.runner.on_price(clock, px)

    def _reconcile(self, now: datetime, clock: str) -> None:
        """모의계좌 잔고와 실행이 아는 보유를 대조한다. 다르면 멈춤(이후 주문 없음) → 「확인 필요」.

        - fill 이 None 을 돌려줬거나(`broker.needs_check`) 결과를 모르는 주문이 있었으면(`broker.unknown`) 바로 한 번
        - 기대 보유가 바뀌면(진입·청산, 0 이 된 때 포함) 5초 뒤 한 번
        - 보유 중이거나 결과를 모른 주문이 있었던 실행이면, 마지막 대조 뒤 30초마다
        - 잔고가 번호 없이 결과를 모르던 주문(`broker.blind`)의 체결 뒤 보유와 같으면 그 주문이 들어간 증거:
          실행기 보유와도 같으면(늦게 체결돼 받아들인 진입) 표시를 풀고, 청산 재시도를 기다리는 중이면
          (`retry_after` 전) 멈추지 않는다 — 재시도 때 브로커가 표시를 풀고 주문 없이 청산으로 기록한다.
          알려진 거절(업무 거부·8·9) 뒤의 청산 재시도에는 이 예외가 없다 — 계좌 0 이면 불일치로 멈춘다(R20)"""
        r, b = self.runner, self.broker
        if not self.orders or r.halted or not isinstance(b, MockAccountBroker):
            return
        exp = r.expected_position()
        if exp != self._last_exp:
            self._last_exp = exp
            self._last_check = now
            self._recheck_at = now + timedelta(seconds=RECHECK_SECONDS)
        urgent = b.unknown or b.needs_check
        soon = self._recheck_at is not None and now >= self._recheck_at
        due = ((exp != 0 or b.had_unknown) and self._last_check is not None
               and (now - self._last_check).total_seconds() >= RECONCILE_SECONDS)
        if not (urgent or soon or due):
            return
        b.unknown = b.needs_check = False
        if soon:
            self._recheck_at = None
        self._last_check = now
        held = b.position()         # purpose 「잔고확인」, 실패는 broker 가 기록하고 None
        if held is None:
            return
        if held == exp:
            if b.blind_landed(held):
                b.lift_blind(clock, held)
            return
        if b.blind_landed(held) and r.pos is not None and clock < r.retry_after:
            self.j.write("event", clock=clock, text=f"계좌 {held:+d} — 결과를 모르던 청산 주문이 반영됨. "
                                                    "재시도 때 주문 없이 청산으로 기록")
            return
        r.halt(f"잔고 불일치 · 기대 {exp:+d} · 계좌 {held:+d}")
        self.j.write("event", clock=clock, text="확인 필요 — 계좌 잔고가 실행과 달라 주문을 멈춤. 계좌를 직접 확인하세요")

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
        self._clock_date, clock = self._label(now)     # 끝내기 정리·기록도 실행의 시계(step 과 같음)
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

    def _wrap_up(self, reason: str, clock: str) -> str:
        """보유 정리·끝 잔고·summary.json. 바뀐 끝 까닭을 돌려준다."""
        r, b, j = self.runner, self.broker, self.j
        paper_left = None
        if not r.halted and r.pos is not None and self._in_break(clock):
            closed = self._closed_text(clock)      # 「휴장 중(20:35~20:50)」 · 판정이면 「장 닫힘(휴장 05:00~06:00)」
            if isinstance(b, MockAccountBroker):
                # 팀: 휴장 중 끝남(오류·앱 종료) — 정리 주문을 내지 않는다. 보유는 계좌에 남으니 확인 필요
                r.halt(f"{closed} 끝 — 정리 주문을 내지 않음 · 보유 {r.expected_position():+d}")
            else:
                # 종이: 계좌가 없어 「확인 필요」가 아니다. 휴장 중엔 종이 체결도 안 하므로 보유는 정리하지 않고 끝낸다
                paper_left = f"{closed} 끝 — 종이 보유 {r.expected_position():+d} 는 마지막 가격으로 정리 안 함"
                j.write("event", clock=clock, text=paper_left + " (계좌 없음 · 거래 기록에 넣지 않음)")
        if paper_left is None and not r.halted and r.pos is not None:
            try:
                if isinstance(b, MockAccountBroker):
                    # 정리 주문 전에 계좌가 실행과 같은지 본다 — 이미 청산됐는데 또 주문하면 반대 포지션이 생긴다
                    held = b.position()
                    if held is not None and held != r.expected_position():
                        r.halt(f"잔고 불일치 · 기대 {r.expected_position():+d} · 계좌 {held:+d}")
                if not r.halted:
                    r.force_flat(clock)
            except Exception as e:
                r.halt(f"정리 중 오류 — {error_text(e)}")
            if r.pos is not None and not r.halted:
                r.halt(f"끝낼 때 청산되지 않음 · 보유 {r.expected_position():+d}")
        if r.break_exit is not None and r.pos is not None:
            # 정리를 해 본 **뒤에도** 휴장 중 정한 청산이 남았을 때만 — 사유를 기록에 남긴다(손절이었는지 나중에 알 수 있게).
            # 미룬 중지가 휴장 뒤 정리로 체결되면 남지 않는다(summary `break_exit` 와 같은 조건)
            j.write("event", clock=clock, text=f"휴장 중 정한 청산({r.break_exit})을 주문하지 못한 채 끝남",
                    break_exit=r.break_exit)
        if isinstance(b, MockAccountBroker):
            held = b.position()
            got = "확인 안 됨" if held is None else f"{held:+d}"
            j.write("event", clock=clock, text=f"끝 잔고 {self.sym} {got}계약")
            if not r.halted and held != r.expected_position():
                # 정리했는데도 계좌가 실행이 아는 보유와 다르다(못 읽은 경우 포함) — 깨끗한 끝으로 보이지 않게
                r.halt(f"끝 잔고 불일치 · 기대 {r.expected_position():+d} · 계좌 {got}")
        if paper_left is not None:
            reason = f"{reason} · {paper_left}"
        if r.halted:
            reason = f"{reason} · 정리 안 함 — 확인 필요: {r.halted}"
            j.write("event", clock=clock, text=f"정리하지 않고 끝냄 — 보유는 그대로 남겨 두었습니다. "
                                               f"계좌에서 직접 확인하세요 ({r.halted})")
        open_order = b.open_unknowns() if isinstance(b, MockAccountBroker) else None
        if open_order is not None:
            j.write("event", clock=clock, text=f"끝낼 때 결과를 모르는 주문이 남아 있음 — 계좌·주문내역을 확인하세요 ({open_order})")
        if isinstance(b, MockAccountBroker):
            self.account_end = b.account(clock, "끝 (수수료·확정손익은 하루 누적)")
        data: dict[str, Any] = {
            "sym": self.sym, "market": self.market.id, "currency": self.currency, **self._product_fields(),
            "trades": r.trades, "summary": summarize(r.trades),
            "account_start": self.account_start, "account_end": self.account_end,
            "api": self.apilog.stats(),
            "strategy": strategy_block(self.loaded, r.p),
        }
        if r.halted:
            data["halted"] = r.halted
        if paper_left is not None:
            data["open_paper_position"] = {k: r.pos.get(k) for k in ("side", "entry", "entry_time", "window") if k in r.pos}
        if r.break_exit is not None and r.pos is not None:
            data["break_exit"] = r.break_exit
        if open_order is not None:
            data["unresolved_order"] = open_order
        write_summary(self.folder, data)
        return reason

    def run_forever(self) -> None:
        """실행 스레드 본문. 1초마다 `step(now())`, 끝나면(예외 포함) `finish`."""
        if not self._prepared:
            return
        try:
            while not self._finished:
                started = self.now()
                self.step(started)
                if self._finished:
                    break
                spent = (to_kst(self.now()) - to_kst(started)).total_seconds()
                self.sleep(max(0.0, STEP_SECONDS - spent))
        except Exception as e:      # 실행기 자체의 버그 — 보유를 정리하고 오류로 끝낸다
            self.finish(f"오류: {error_text(e)}")
        finally:
            self.finish("중지")

    # ------------------------------------------------------------ 요청 (다른 스레드에서)
    def request_stop(self, shutdown: bool = False) -> None:
        """다음 step 에서 끝낸다(보유가 있으면 정리)."""
        if shutdown:
            self._shutdown = True       # 앱 종료 — 휴장이어도 미루지 않는다(정리 없이 「확인 필요」로 끝남)
        self._stop_requested = True

    def request_flatten(self) -> None:
        """다음 step 에서 보유를 정리하고 실행은 계속한다."""
        self._flatten_requested = True

    # ------------------------------------------------------------ 상태
    @property
    def order_sym(self) -> str | None:
        """이 실행이 주문하는 종목 — registry 의 「같은 종목 모의 계좌 실행은 하나」 규칙의 키(실행기 종류와 무관)."""
        return self.sym

    def _next_decision(self, bar_min: int) -> str | None:
        """마지막으로 넣은 1분봉 뒤 다음 판정 봉이 닫히는 시각(HHMMSS). 판정 봉은 session_start 부터 bar_min 분씩."""
        date, t = self._last_fed
        if not t:
            return None
        p = self.runner.p
        start, end = _minutes(p.session_start), _minutes(p.session_end)
        last = _minutes(t)
        if date != self._today or last < start:
            nxt = start + bar_min
        else:
            nxt = start + ((last + 1 - start) // bar_min + 1) * bar_min
        if nxt > end:
            return None
        return f"{nxt // 60:02d}{nxt % 60:02d}00"

    def status(self) -> dict:
        """화면에 보일 지금 상태(칸 순서 고정)."""
        p = self.runner.p
        bar_min = int(getattr(p, "bar_min", 1) or 1)
        try:
            snap = self.runner.snapshot()
        except Exception:           # 전략의 target 등이 예외를 내도 화면은 뜨게
            snap = {k: None for k in SNAPSHOT_KEYS}
            snap["halted"] = self.runner.halted
        return {
            **run_head(self.run_id, self.loaded, self.spec.mode, self.sym, self.state, self.started_at,
                       self.ended_at, self.ended_reason),
            "bar_min": bar_min, "next_decision_at": self._next_decision(bar_min),
            **{k: snap.get(k) for k in SNAPSHOT_KEYS},
            "params": asdict(p),
            "market": self.market.id, "currency": self.currency, "kind": self.kind, **self._product_fields(),
        }

    def _product_fields(self) -> dict:
        """`run.json`·`status()`·`summary.json` 의 종목·시계 칸 (설계 4.7). 다리 없는 실행은 A75·KRX / MKU·FSGX."""
        return {"product": self.product, "exchange": self.exchange, "tick": self.tick, "tick_value": self.tick_value,
                "overnight": self.plan.overnight, "trading_date": self.trading_date, "end": self.plan.end}

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._write_run()

    def _write_run(self) -> None:
        """`run.json` — 임시 파일에 쓰고 바꿔 끼운다(읽는 쪽이 덜 쓴 파일을 보지 않게)."""
        data: dict[str, Any] = {
            **run_head(self.run_id, self.loaded, self.spec.mode, self.sym, self.state, self.started_at,
                       self.ended_at, self.ended_reason),
            "sha256": self.loaded.sha256,
            "market": self.market.id, "currency": self.currency, "kind": self.kind, **self._product_fields(),
        }
        if self.runner.halted:
            data["halted"] = self.runner.halted
        write_run_json(self.folder, data)
