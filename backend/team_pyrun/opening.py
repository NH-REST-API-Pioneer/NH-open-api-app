"""장 열림 공용 판정 — 파이썬 전략 실행과 스프레드 탭이 같은 규칙을 쓴다.

운영자 세션 판정(`sessions_routes.judged`)의 `state` 로 본다. 거래 창인 상태만 열림이고, 나머지와 판정 오류는 닫힘
(모르면 거래하지 않는다). 국내는 주간(`day`)만, 해외는 `open`·`open-2`·`next-day`.
주문은 국내면 모의계좌가 받는 09:00(`markets.DOMESTIC.session_start`) 부터.

판정 함수(`Judge`)는 인자로 받는다 — 시험은 가짜를 넣는다. 운영자 모듈은 기본 함수 안에서만 가져온다.
`team_spread` 는 가져오지 않는다(그쪽이 이 모듈을 쓴다).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.sessions.hours import to_kst
from backend.team_pyrun import markets

Judge = Callable[[str, str, datetime], dict[str, Any]]
DayEnd = Callable[[str, str, datetime], "datetime | None"]

DOMESTIC_OPEN_STATES = frozenset({"day"})
OVERSEAS_OPEN_STATES = frozenset({"open", "open-2", "next-day"})


def default_judge(market: str, sym: str, now: datetime) -> dict[str, Any]:
    from backend.sessions.sessions_routes import judged     # 늦게 가져옴 — 시험은 가짜를 넣는다
    return judged(market, sym, now)


def default_day_end(market: str, sym: str, now: datetime) -> datetime | None:
    """해외 종목의 지금 거래일 마지막 구간 끝. 국내는 없음."""
    if market != "overseas":
        return None
    from backend.sessions.sessions_routes import trading_day_end
    return trading_day_end(market, sym, now)


def is_open(judge: Judge, market: str, sym: str, now: datetime) -> bool:
    try:
        states = DOMESTIC_OPEN_STATES if market == "domestic" else OVERSEAS_OPEN_STATES
        return str(judge(market, sym, now).get("state")) in states
    except Exception:       # 판정을 못 하면 닫힘 — 모르는 채로 거래하지 않는다
        return False


def order_window_open(market: str, now: datetime) -> bool:
    """주문 창 — 국내는 한국시간 09:00(`markets.DOMESTIC.session_start`) 부터, 해외는 항상."""
    return market != "domestic" or to_kst(now).strftime("%H%M%S") >= markets.DOMESTIC.session_start


def order_open(judge: Judge, market: str, sym: str, now: datetime) -> bool:
    return is_open(judge, market, sym, now) and order_window_open(market, now)


def known(judge: Judge, market: str, sym: str, now: datetime) -> bool:
    try:
        return str(judge(market, sym, now).get("source")) != "unknown"
    except Exception:
        return False


def _hhmm(value: Any) -> str | None:
    try:
        return to_kst(datetime.fromisoformat(str(value))).strftime("%H:%M")
    except (TypeError, ValueError):
        return None


def span_text(judge: Judge, market: str, sym: str, now: datetime) -> str:
    """지금 닫힌 까닭 글 — 기록용."""
    try:
        made = judge(market, sym, now)
    except Exception:
        return "장 시간표 모름"
    if str(made.get("source")) == "unknown":
        return "장 시간표 모름"
    if str(made.get("state")) == "break":
        a, b = _hhmm(made.get("since")), _hhmm(made.get("until"))
        if a and b:
            return f"휴장 {a}~{b}"
        return "휴장"
    return "장 마감"
