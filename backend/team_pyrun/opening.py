"""장 열림 공용 판정 — 파이썬 전략 실행과 스프레드 탭이 같은 규칙을 쓴다.

운영자 세션 판정(`sessions_routes.judged`)의 `state` 로 본다. 거래 창인 상태만 열림이고, 나머지와 판정 오류는 닫힘
(모르면 거래하지 않는다). 국내는 주간(`day`)만, 해외는 `open`·`open-2`·`next-day`.
주문은 국내면 모의계좌가 받는 09:00(`markets.DOMESTIC.session_start`) 부터.

판정 함수(`Judge`)는 인자로 받는다 — 시험은 가짜를 넣는다. 운영자 모듈은 기본 함수 안에서만 가져온다.
`team_spread` 는 가져오지 않는다(그쪽이 이 모듈을 쓴다).

판정이 종목을 모르면(`known` 거짓) 시작을 거부한다. 그 글(`unknown_text`)은 운영자 종목 마스터 색인에 그 종목(의 품목)
줄이 있는지(`MasterKnows`, 앱은 `default_master_knows`)로 가른다 — 없으면 앱이 뜬 직후 마스터를 아직 못 읽은 것이라
「종목 마스터를 아직 읽지 못했습니다」, 있으면 「장 시간표에 이 종목이 없습니다」. 어느 쪽이든 거부다(모르면 거래하지 않는다).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.sessions.hours import to_kst
from backend.team_pyrun import markets

Judge = Callable[[str, str, datetime], dict[str, Any]]
DayEnd = Callable[[str, str, datetime], "datetime | None"]
#: (시장, 종목) → 운영자 종목 마스터 색인에 그 종목(의 품목) 줄이 있는가 — 시험은 가짜를 넣는다
MasterKnows = Callable[[str, str], bool]

DOMESTIC_OPEN_STATES = frozenset({"day"})
OVERSEAS_OPEN_STATES = frozenset({"open", "open-2", "next-day"})
#: 장이 열리기 전 상태(국내 `pre-open`·`pre-night`) — 닫힌 까닭 글은 「장 시작 전」
PRE_OPEN_STATES = frozenset({"pre-open", "pre-night"})

#: 판정이 종목을 모를 때의 시작 거부 글 — 마스터는 그 종목을 아는데 시간표가 모름 / 마스터 색인에 그 종목 줄이 없음
TIMETABLE_UNKNOWN = "장 시간표에 이 종목이 없습니다 — 화면 「장 시간」에서 확인하세요"
MASTER_UNREAD = "종목 마스터를 아직 읽지 못했습니다 — 잠시 뒤 다시 시작하세요"


def default_judge(market: str, sym: str, now: datetime) -> dict[str, Any]:
    from backend.sessions.sessions_routes import judged     # 늦게 가져옴 — 시험은 가짜를 넣는다
    return judged(market, sym, now)


def default_day_end(market: str, sym: str, now: datetime) -> datetime | None:
    """해외 종목의 지금 거래일 마지막 구간 끝. 국내는 없음."""
    if market != "overseas":
        return None
    from backend.sessions.sessions_routes import trading_day_end
    return trading_day_end(market, sym, now)


def default_master_knows(market: str, sym: str) -> bool:
    """운영자 종목 마스터 색인(`master_service.service.product_of`)에 그 종목(의 품목) 줄이 있는가.
    색인을 아직 못 읽었으면 None 이라 거짓 — 운영자 판정도 그때는 `unknown` 이다."""
    from backend.master import master_service      # 늦게 가져옴 — 시험은 가짜를 넣는다
    return master_service.service.product_of(market, sym) is not None


def unknown_text(master_knows: MasterKnows | None, market: str, sym: str) -> str:
    """판정이 종목을 모를 때 시작 거부 글. 마스터 확인을 꽂았고 그 종목 줄이 없으면(확인이 예외여도) `MASTER_UNREAD`,
    아니면 `TIMETABLE_UNKNOWN`. 글만 가른다 — 부르는 쪽은 어느 쪽이든 거부한다."""
    if master_knows is not None:
        try:
            has = bool(master_knows(market, sym))
        except Exception:       # 마스터를 못 보면 모르는 것 — 마스터 쪽 글로(거부는 그대로)
            has = False
        if not has:
            return MASTER_UNREAD
    return TIMETABLE_UNKNOWN


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
    """지금 닫힌 까닭 글 — 기록용. 국내 주간(`day`)인데 09:00 전이면 「주문 시작 전(09:00)」, 장 전 상태(`pre-open`·
    `pre-night`)면 「장 시작 전」, 쉼(`break`)이면 「휴장 …」, 나머지는 「장 마감」."""
    try:
        made = judge(market, sym, now)
    except Exception:
        return "장 시간표 모름"
    if str(made.get("source")) == "unknown":
        return "장 시간표 모름"
    state = str(made.get("state"))
    if state == "break":
        a, b = _hhmm(made.get("since")), _hhmm(made.get("until"))
        if a and b:
            return f"휴장 {a}~{b}"
        return "휴장"
    if market == "domestic" and state in DOMESTIC_OPEN_STATES and not order_window_open(market, now):
        start = markets.DOMESTIC.session_start
        return f"주문 시작 전({start[:2]}:{start[2:4]})"
    if state in PRE_OPEN_STATES:
        return "장 시작 전"
    return "장 마감"
