"""일봉 전략의 신규 진입 시간과 지난 봉 셈의 만기일 진입 막기.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 체결·개장 시각을 손으로 넣고, 마스터는
저장소 안의 고정본 조각을 읽습니다.
"""
from __future__ import annotations

from datetime import date, timedelta

from backend.strategy import backtest, engine, paper, runs
from tests.test_strategy_backtest import _봉, _셈, _진입봉
from tests.test_strategy_daily_orders import _안낸신호, _이틀, _일봉, _틱, 주간
from tests.test_strategy_engine import _때, _엔진


def _창(**aux) -> engine.RunEngine:
    엔진 = _엔진(_일봉(entryStart="09:00", entryEnd="14:30", **aux))
    _이틀(엔진)  # 16일 마감에서 매수 진입이 걸려 미뤄집니다.
    엔진.note_open(주간, _때(8, 45, day=17))
    return 엔진


# ── ① 일봉 + 신규 진입 시간 ──────────────────────────────────


def test_일봉은_판정_때_시간창으로_막지_않고_미룬다():
    엔진 = _창()

    assert 엔진._deferred.get("entry") is not None
    assert _안낸신호(엔진) == [], "세션 마감은 시간 밖이어도 판정 때 막지 않습니다."


def test_미룬_진입은_시간_안에_든_첫_체결에_낸다():
    엔진 = _창()

    _틱(엔진, _때(8, 45, day=17), 101.0)
    assert 엔진.book.orders == [], "개장 체결이 시간 전이면 미룬 채 둡니다."
    assert 엔진._deferred.get("entry") is not None and _안낸신호(엔진) == []

    _틱(엔진, _때(9, 0, day=17), 101.0)
    (주문,) = 엔진.book.orders
    assert 주문.side == paper.BUY and 엔진._deferred == {}


def test_그_세션_내내_시간_밖이면_마감에서_버린다():
    엔진 = _창()
    엔진.aux["entryStart"], 엔진.aux["entryEnd"] = "09:00", "09:30"

    _틱(엔진, _때(8, 46, day=17), 101.0)
    _틱(엔진, _때(10, 0, day=17), 101.0)
    엔진.close_session(_때(15, 46, day=17))

    assert 엔진.book.orders == []
    assert f"{engine.UNSENT_HEAD}{engine.WHY_DEFERRED_EXPIRED}" in _안낸신호(엔진)
    assert 엔진.unsent_today(_때(15, 46, day=17)) == 1


def test_세션_끝_정리_시간이면_내지_않고_버린다():
    엔진 = _창()
    엔진._closing_until = _때(15, 45, day=17)  # 끝 정리 중(예: 창이 끝 N분과 겹침)

    _틱(엔진, _때(9, 0, day=17), 101.0)

    assert 엔진.book.orders == [] and 엔진._deferred == {}
    assert _안낸신호(엔진) == [f"{engine.UNSENT_HEAD}{runs.WHY_SESSION_END}"]
    assert 엔진.unsent_today(_때(9, 0, day=17)) == 1


def test_미룬_청산은_시간창과_상관없이_낸다():
    엔진 = _엔진(_일봉(entryStart="09:00", entryEnd="09:30"))
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    엔진._defer("exit", paper.BUY, 99.0, 1)
    엔진.note_open(주간, _때(8, 45, day=17))

    _틱(엔진, _때(8, 46, day=17), 99.0)

    (청산,) = 엔진.book.orders
    assert 청산.side == paper.SELL


def test_내는_날의_거래일로_넘겨_하루_최대를_새로_센다():
    엔진 = _창(maxEntriesPerDay="1")
    엔진.run.intents_today = 1  # 어제 하나 냈음 — 어제 값으로 세면 막힙니다.

    _틱(엔진, _때(9, 0, day=17), 101.0)

    assert len(엔진.book.orders) == 1
    assert 엔진.run.day_key == _때(0, 0, day=17)
    assert 엔진.run.intents_today == 1


def test_분봉_시간창은_그대로_봉_마감_시각이다():
    엔진 = _엔진({**_일봉(entryStart="09:00", entryEnd="14:30"), "baseBar": "1분봉"})

    assert 엔진._in_window(_봉(8, 59, 1, 1, 1, 1)) is True, "09:00 에 닫힙니다."
    assert 엔진._in_window(_봉(14, 29, 1, 1, 1, 1)) is False, "14:30 에 닫힙니다(끝 제외)."
    assert 엔진._in_window_at(_때(9, 0)) is True and 엔진._in_window_at(_때(14, 30)) is False


# ── ② 지난 봉 셈의 만기일 진입 막기 ───────────────────────────


def _막힘(답_엔진_사건) -> list[str]:
    return [one["text"] for one in 답_엔진_사건 if one["kind"] == engine.BLOCKED]


def _셈_사건(expiry):
    잡은: list = []
    원래 = backtest._answer

    def 엿보기(answer, made, fed, minutes):
        잡은.extend(made.events)
        return 원래(answer, made, fed, minutes)

    backtest._answer = 엿보기
    try:
        답 = _셈(_진입봉(_봉(9, 3, 101.0, 101.25, 101.0, 101.25)), expiry=expiry)
    finally:
        backtest._answer = 원래
    return 답, 잡은


def test_만기일_봉부터_진입을_막고_전날까지는_낸다():
    당일, 당일_사건 = _셈_사건(date(2026, 9, 17))
    전날, _ = _셈_사건(date(2026, 9, 18))

    assert 당일["fills"] == 0
    assert f"{engine.UNSENT_HEAD}{runs.WHY_EXPIRY}" in _막힘(당일_사건), "실행과 같은 까닭 글자입니다."
    assert 당일["assumptions"]["expiryBlock"] == "2026-09-17"
    assert 전날["fills"] >= 1


def test_만기일을_모르면_막지_않는다():
    답, 사건 = _셈_사건(None)

    assert 답["fills"] >= 1 and 답["assumptions"]["expiryBlock"] is None
    assert f"{engine.UNSENT_HEAD}{runs.WHY_EXPIRY}" not in _막힘(사건)


def test_고정본_마스터의_남은_날과_만기일은_같은_날을_가리킨다(실마스터):
    """실행은 남은 날(rem_cnt)이 0 이하인 날, 지난 봉 셈은 거래일 ≥ 만기일인 날에 막습니다.

    고정본의 국내 줄은 모두 「만기일 − rem_cnt 일」이 같은 하루(그 판의 날짜)입니다 —
    rem_cnt 는 달력 날 수입니다. 그래서 남은 날 0 인 날이 곧 만기일이고, 두 셈은
    같은 날 막습니다.
    """
    판들 = set()
    for code in ("A016C000", "B016A745", "A066C000", "A756A000"):
        줄 = 실마스터.locate("domestic", code)
        assert 줄 is not None, code
        만기 = date(int(줄["expiry_date"][:4]), int(줄["expiry_date"][4:6]), int(줄["expiry_date"][6:]))
        판들.add(만기 - timedelta(days=int(줄["rem_cnt"])))
    assert len(판들) == 1, f"남은 날이 달력 날 수라면 판 날짜 하나로 모입니다: {판들}"
