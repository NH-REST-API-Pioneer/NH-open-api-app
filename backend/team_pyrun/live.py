"""장중 실행 — week02 `runner.py` 의 `live()` 를 1초 한 번 부르는 `step()` 으로 나눠 옮긴 것.

실행 하나 = 전략 파일 하나 × 종목 하나 × 하루. 모든 호출은 모의 서버(`environment="paper"`)로 갑니다.

    prepare()      시작 검사와 준비 봉 (Registry 스레드에서 한 번). 안 되면 `StartRefused`
    step(now)      1초 한 번 — 분이 바뀌고 3초 뒤 1분봉, 매초 현재가, 정리 요청, 잔고 대조
    run_forever()  실행 스레드 본문. 1초마다 step, 끝나면 finish
    finish(reason) 보유 정리·끝 잔고·요약. 두 번 불려도 한 번만

주문 갈래 (`RunSpec.mode`)

    orders  모의계좌에 실제 시장가 주문 (`MockAccountBroker`)
    paper   주문 없이 종이 체결 (`PaperBroker`). 시세(현재가·차트)만 부르고 주문·주문내역·잔고·예수금은 부르지 않음

week02 와 다른 점

- 시작할 때 이 종목 잔고가 있으면 **정리하지 않고 시작을 거부**합니다(누구의 잔고인지 모르므로).
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
from backend.team_pyrun.apilog import ApiLog, bind, purpose
from backend.team_pyrun.broker import MockAccountBroker, error_text
from backend.team_pyrun.journal import Journal, summarize, write_summary
from backend.team_pyrun.loader import Loaded
from backend.team_pyrun.runner import Minute, PaperBroker, Runner, minute_of

END_TIME = "153100"         # 15:30 정리 뒤 이 시각에 끝냄 (week02 와 같음)
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
    """무엇을 돌릴지. `sym` 이 없으면 미국달러선물 최근월물."""

    file: str
    mode: Literal["orders", "paper"]
    sym: str | None


class StartRefused(Exception):
    """시작 검사에 걸려 실행을 시작하지 않았다. 메시지가 그대로 화면에 간다. 주문은 나가지 않았다."""


def _iso(moment: datetime) -> str:
    """`2026-11-03T09:01:04` 꼴(한국시간, 시간대 꼬리 없음 — journal 과 같은 모양)."""
    return to_kst(moment).replace(tzinfo=None).isoformat(timespec="seconds")


def _minutes(hhmmss: str) -> int:
    return int(hhmmss[:2]) * 60 + int(hhmmss[2:4])


class LiveRun:
    """장중 실행 하나. Registry 가 만들고 `prepare()` 뒤 데몬 스레드에서 `run_forever()` 를 돌린다.

    `step()`·`finish()` 는 잠금 안에서 돌아 서로 겹치지 않습니다. `status()`·`request_*()` 는 잠그지 않습니다
    (체결 확인으로 step 이 15초까지 걸릴 수 있어 화면이 기다리지 않게)."""

    def __init__(self, run_id: str, folder: Path, loaded: Loaded, spec: RunSpec, *,
                 api_module: ModuleType | Any = default_api, now: Callable[[], datetime] = now_kst,
                 sleep: Callable[[float], None] = time.sleep, stops_before: int = 0):
        self.run_id, self.folder, self.loaded, self.spec = run_id, Path(folder), loaded, spec
        self.api, self.now, self.sleep = api_module, now, sleep
        self.stops_before = int(stops_before)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.j = Journal(self.folder / "journal.jsonl")
        self.apilog = ApiLog(self.folder / "api_log.jsonl", run_id)
        self.orders = spec.mode == "orders"
        # orders 의 MockAccountBroker 는 종목이 정해지는 prepare() 에서 만든다
        self.broker: MockAccountBroker | PaperBroker | None = None if self.orders else PaperBroker(self.j, loaded.tick)
        self.runner = Runner(loaded.new(), self.j, self.broker, loaded.tick, loaded.tick_value)
        self.runner.stops_before = self.stops_before   # 화면의 오늘 손절 수용(전략에 day 가 없을 때)
        self.sym: str | None = spec.sym
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

    # ------------------------------------------------------------ 시작
    def prepare(self) -> None:
        """시작 검사와 준비 봉. 안 되면 `StartRefused`(주문 없음, run.json 은 「끝」으로 남김)."""
        with self._lock, bind(self.apilog):
            if self._prepared or self._finished:
                raise StartRefused("이미 시작했거나 끝난 실행입니다")
            now = to_kst(self.now())
            self.started_at = _iso(now)
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
            self._set_state("대기" if now.strftime("%H%M%S") < self.runner.p.session_start else "진행 중")

    def _prepare(self, now: datetime) -> None:
        j, api, loaded, r = self.j, self.api, self.loaded, self.runner
        today, clock = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
        self._today = today
        # 1. 어디로·무엇을
        j.write("event", text=f"서버 paper · 주문 {'모의계좌' if self.orders else '종이'}")
        j.write("event", text=f"전략 {loaded.file} · sha256 {loaded.sha256[:12]} · Params {asdict(r.p)}")
        # 2. 종목과 틱
        sym = self.spec.sym
        if not sym:
            with purpose("종목 찾기"):
                sym = api.nearest_usd(api.all_futures())
        self.sym = sym
        with purpose("틱 확인"):
            tick, value = api.usd_spec(api.product_detail())
        if not (math.isclose(tick, loaded.tick, rel_tol=1e-9) and math.isclose(value, loaded.tick_value, rel_tol=1e-9)):
            raise StartRefused(f"틱·틱가치가 전략 가정과 다릅니다 — 서버 {tick:g}·{value:g}, "
                               f"전략 {loaded.tick:g}·{loaded.tick_value:g}")
        j.write("event", text=f"종목 {sym} · 틱 {tick:g} · 틱가치 {value:,.0f}")
        self._write_run()
        # 3. 모의계좌: 시작 잔고가 0 이어야 한다
        if self.orders:
            broker = MockAccountBroker(api, sym, j, sleep=self.sleep, today=today,
                                       expected=r.expected_position, halt=r.halt)
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
        # 4. 준비 봉: 지금 분보다 앞선 것만, 시각순
        now_min = now.strftime("%H%M") + "00"
        with purpose("준비 봉"):
            got = [minute_of(x) for x in api.chart_minute(sym, req_qty=WARMUP_BARS)]
        hist = sorted((m for m in got if (m.date, m.time) < (today, now_min)), key=lambda m: (m.date, m.time))
        r.warmup(hist)
        r.live_date = today       # 준비 봉에서 난 오늘 신호로는 진입하지 않음 — 이 뒤로 닫히는 봉부터
        day = getattr(r.strat, "day", None)
        if self.stops_before and day is not None:
            day.stops = self.stops_before
            j.write("event", text=f"오늘 앞선 실행의 손절 {self.stops_before}회를 이어받음 "
                                  f"(한도 {getattr(r.p, 'max_stops_per_day', '?')}회)")
        elif self.stops_before:     # 하루 상태(`day`)가 없는 전략 — 손절 수를 넣을 자리가 없다
            j.write("event", text=f"전략에 하루 상태(day)가 없어 오늘 앞선 실행의 손절 {self.stops_before}회를 이어받지 않음")
        self._day_obj = getattr(r.strat, "day", None)
        self._last_fed = (hist[-1].date, hist[-1].time) if hist else ("", "")
        self._seen_minute = now.strftime("%H%M")
        self._last_check = now

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
        clock = now.strftime("%H%M%S")
        if clock >= END_TIME:
            self._finish("장 끝", now)
            return
        if self._stop_requested:
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
            if self._flatten_requested:
                self._flatten_requested = False
                self.j.write("event", clock=clock, text="정리 요청 — 보유가 있으면 정리")
                r.force_flat(clock)
            self._reconcile(now, clock)     # 체결을 못 받은 주문(fill → None)이 있었으면 바로 한 번 더
        except Exception as e:
            self._finish(f"오류: {error_text(e)}", now)
            return
        if r.halted:
            self._set_state("확인 필요")

    def _feed_minutes(self, now: datetime, clock: str) -> None:
        """분이 바뀌고 3초 뒤: 막 끝난 1분봉(들)을 시각순으로 한 번씩 전략에 넣는다."""
        hhmm = now.strftime("%H%M")
        if hhmm == self._seen_minute or now.second < MINUTE_DELAY_SECONDS:
            return
        try:
            with purpose("1분봉"):
                got = [minute_of(x) for x in self.api.chart_minute(self.sym, req_qty=LIVE_BARS)]
        except Exception as e:      # 연결·응답 문제로 하루 실행이 멈추지 않게 — 기록하고 다음 초에 다시
            self.j.write("event", clock=clock, text="차트(분) 처리 실패 — 다음 초에 다시", error=error_text(e))
            return
        now_key = (now.strftime("%Y%m%d"), hhmm + "00")
        for m in sorted((m for m in got if self._last_fed < (m.date, m.time) < now_key),
                        key=lambda m: (m.date, m.time)):
            if (m.date, m.time) <= self._last_fed:
                continue            # 같은 봉이 두 번 온 경우
            self.runner.on_minute_closed(m)
            self._last_fed = (m.date, m.time)
            self._carry_stops(m)
        self._seen_minute = hhmm

    def _carry_stops(self, m: Minute) -> None:
        """전략이 오늘 첫 봉에서 하루 상태(`day`)를 새로 만들었으면, 앞선 실행의 손절 수를 다시 넣는다.

        장 전에 켜면 준비 봉이 어제 것뿐이라, prepare 에서 넣은 값이 오늘 첫 봉에서 지워지기 때문입니다."""
        day = getattr(self.runner.strat, "day", None)
        if not self.stops_before or day is None or day is self._day_obj or m.date != self._today:
            return
        self._day_obj = day
        if getattr(day, "stops", 0) < self.stops_before:
            day.stops = self.stops_before
            self.j.write("event", clock=m.time, text=f"오늘 앞선 실행의 손절 {self.stops_before}회를 다시 넣음 "
                                                     f"(전략이 하루를 새로 시작함)")

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

    def _wrap_up(self, reason: str, clock: str) -> str:
        """보유 정리·끝 잔고·summary.json. 바뀐 끝 까닭을 돌려준다."""
        r, b, j = self.runner, self.broker, self.j
        if not r.halted and r.pos is not None:
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
        if isinstance(b, MockAccountBroker):
            held = b.position()
            got = "확인 안 됨" if held is None else f"{held:+d}"
            j.write("event", clock=clock, text=f"끝 잔고 {self.sym} {got}계약")
            if not r.halted and held != r.expected_position():
                # 정리했는데도 계좌가 실행이 아는 보유와 다르다(못 읽은 경우 포함) — 깨끗한 끝으로 보이지 않게
                r.halt(f"끝 잔고 불일치 · 기대 {r.expected_position():+d} · 계좌 {got}")
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
            "sym": self.sym, "trades": r.trades, "summary": summarize(r.trades),
            "account_start": self.account_start, "account_end": self.account_end,
            "api": self.apilog.stats(),
            "strategy": {"file": self.loaded.file, "name": self.loaded.name, "title": self.loaded.title,
                         "sha256": self.loaded.sha256, "params": asdict(r.p)},
        }
        if r.halted:
            data["halted"] = r.halted
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
    def request_stop(self) -> None:
        """다음 step 에서 끝낸다(보유가 있으면 정리)."""
        self._stop_requested = True

    def request_flatten(self) -> None:
        """다음 step 에서 보유를 정리하고 실행은 계속한다."""
        self._flatten_requested = True

    # ------------------------------------------------------------ 상태
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
            "id": self.run_id, "file": self.loaded.file, "name": self.loaded.name, "title": self.loaded.title,
            "mode": self.spec.mode, "sym": self.sym, "state": self.state,
            "started_at": self.started_at, "ended_at": self.ended_at, "ended_reason": self.ended_reason,
            "bar_min": bar_min, "next_decision_at": self._next_decision(bar_min),
            **{k: snap.get(k) for k in SNAPSHOT_KEYS},
            "params": asdict(p),
        }

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._write_run()

    def _write_run(self) -> None:
        """`run.json` — 임시 파일에 쓰고 바꿔 끼운다(읽는 쪽이 덜 쓴 파일을 보지 않게)."""
        data: dict[str, Any] = {
            "id": self.run_id, "file": self.loaded.file, "name": self.loaded.name, "title": self.loaded.title,
            "mode": self.spec.mode, "sym": self.sym, "state": self.state,
            "started_at": self.started_at, "ended_at": self.ended_at, "ended_reason": self.ended_reason,
            "sha256": self.loaded.sha256,
        }
        if self.runner.halted:
            data["halted"] = self.runner.halted
        path = self.folder / "run.json"
        tmp = path.with_name(f".run.json.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
