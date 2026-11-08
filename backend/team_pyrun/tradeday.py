"""거래일 시계 — 자정을 넘는 장을 한 실행으로 다루는 순수 함수들.

거래일은 07:00 에 바뀝니다(`team_spread.pnl.TRADING_DAY_STARTS`). 00:00~06:59 의 시각은 24시간을 더해
`"253000"`(= 다음 날 01:30) 처럼 적어, 전날 밤 22:30 에 시작한 장과 새벽 01:30 이 한 줄로 이어지고 문자열 비교가 맞습니다.
전략의 `Params` 시각(`HHMMSS` 문자열)도 같은 규칙으로 바꿔 줍니다(`shifted_params`).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from backend.sessions.hours import KST, to_kst
from backend.team_pyrun.loader import SCHEDULE_PARAMS
from backend.team_pyrun.runner import Minute
from backend.team_spread.pnl import trading_date

DAY_STARTS = "070000"      # 거래일이 바뀌는 시각
DAY_ENDS = "310000"        # 다음 날 07:00 을 거래일 시계로 적은 것
SCHEDULE_FIELDS = SCHEDULE_PARAMS


def shift(hhmmss: str) -> str:
    """`"070000"` 보다 이르면 24시간을 더한다(`"013000"` → `"253000"`). 아니면 그대로(이미 24 이상이어도)."""
    if len(hhmmss) != 6 or not hhmmss.isdigit():
        raise ValueError(f"HHMMSS 6자리 숫자가 아닙니다: {hhmmss!r}")
    if hhmmss < DAY_STARTS:
        return f"{int(hhmmss[:2]) + 24:02d}{hhmmss[2:]}"
    return hhmmss


def plus_minutes(hhmmss: str, minutes: int) -> str:
    """분을 더한다. 24시를 넘어도 계속 센다(`"235800"` + 5 → `"240300"`)."""
    total = int(hhmmss[:2]) * 3600 + int(hhmmss[2:4]) * 60 + int(hhmmss[4:]) + minutes * 60
    return f"{total // 3600:02d}{total % 3600 // 60:02d}{total % 60:02d}"


def is_overnight(params: object, end: str) -> bool:
    """자정을 넘는 실행인가 — 장 시각 칸 중 하나라도 07:00 보다 이르거나, 끝 시각이 24시 이후."""
    if end >= "240000":
        return True
    return any(str(getattr(params, n)) < DAY_STARTS for n in SCHEDULE_FIELDS if hasattr(params, n))


@dataclass(frozen=True)
class RunClock:
    """달력 시각 ↔ (거래일, 거래일 시계). `overnight` 가 False 면 달력 그대로."""

    overnight: bool

    def label(self, moment: datetime) -> tuple[str, str]:
        """(날짜 YYYYMMDD, 시각 HHMMSS). 시간대 없는 값은 한국시간으로 본다."""
        at = to_kst(moment)
        if not self.overnight:
            return at.strftime("%Y%m%d"), at.strftime("%H%M%S")
        return trading_date(at), shift(at.strftime("%H%M%S"))

    def bar(self, m: Minute) -> Minute:
        """봉의 (date, time) 을 같은 규칙으로. `m.date`·`m.time` 은 달력 값."""
        if not self.overnight:
            return m
        if m.time >= DAY_STARTS:
            return m
        day = datetime.strptime(m.date, "%Y%m%d") - timedelta(days=1)
        return replace(m, date=day.strftime("%Y%m%d"), time=shift(m.time))

    def moment(self, date: str, clock: str) -> datetime:
        """거꾸로 — 거래일·거래일 시계 → 한국시간 datetime(`"253000"` → 다음 날 01:30)."""
        base = datetime.strptime(date, "%Y%m%d").replace(tzinfo=KST)
        return base + timedelta(hours=int(clock[:2]), minutes=int(clock[2:4]), seconds=int(clock[4:]))


def shifted_params(params_cls: type) -> type:
    """장 시각 칸 중 `< "070000"` 인 값만 `shift` 한 같은 이름의 하위 클래스(`loader.fill_params` 와 같은 만들기).

    바꿀 칸이 없으면 그대로 돌려준다."""
    base = params_cls()
    values = {n: shift(str(getattr(base, n))) for n in SCHEDULE_FIELDS
              if hasattr(base, n) and str(getattr(base, n)) < DAY_STARTS}
    if not values:
        return params_cls
    frozen = params_cls.__dataclass_params__.frozen
    return dataclasses.make_dataclass(
        params_cls.__name__, [(n, str, field(default=v)) for n, v in values.items()],
        bases=(params_cls,), frozen=frozen, module=params_cls.__module__)


def clock_text(hhmmss: str) -> str:
    """기록 글용 — `"153000"` → `"15:30"`, `"253000"` → `"01:30 (+1)"`."""
    hour = int(hhmmss[:2])
    text = f"{hour % 24:02d}:{hhmmss[2:4]}"
    return text + " (+1)" if hour >= 24 else text
