"""해외 VWAP 의 세션 — 시간표의 거래 창으로 가릅니다.

**서버에 닿지 않습니다.** 시간표는 손으로 지은 품목 줄이고, 거래일을 답하는 자리는
그 표로 판정하거나 가짜로 끼웁니다.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from backend.sessions import judge
from backend.sessions.hours import KST
from backend.strategy import backtest, engine, rules, runs
from backend.strategy.indicators import Bar
from backend.strategy.service import trading_day_of
from tests.test_strategy_engine import _규칙, _설정

#: 07:00~익일 06:00 한 구간(CME 형)과, 쉼이 있는 세 구간(홍콩 형).
_표 = {
    "products": [
        {
            "exchange": "CME", "productCode": "6A",
            "trading": {"open": "07:00", "close": "06:00", "nextDay": True},
            "second": None, "nextDayTrading": None,
        },
        {
            "exchange": "HKEX", "productCode": "HCEI",
            "trading": {"open": "10:15", "close": "13:00", "nextDay": False},
            "second": {"open": "14:00", "close": "17:30", "nextDay": False},
            "nextDayTrading": {"open": "18:00", "close": "04:00", "nextDay": True},
        },
    ]
}
_CME = {"exch": "01", "comd": "6A"}
_HKEX = {"exch": "HKEX", "comd": "HCEI"}
해외 = "overseas"


def _시(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=KST)


def _ms(day: int, hour: int, minute: int = 0) -> int:
    return int(_시(day, hour, minute).timestamp() * 1000)


def _거래일(contract):
    return lambda timestamp, context="": judge.overseas_trading_day(
        contract, table=_표, at=datetime.fromtimestamp(timestamp / 1000, tz=KST)
    )


# ── 거래일 판정 ──────────────────────────────────────────


def test_자정을_넘는_세션은_시작한_날의_거래일이다():
    def 날(*at):
        return judge.overseas_trading_day(_CME, table=_표, at=_시(*at))

    assert judge.exchange_of("01") == "CME"
    assert 날(16, 23, 59) == date(2026, 9, 16)
    assert 날(17, 0, 1) == date(2026, 9, 16), "자정을 넘겨도 16일 거래일입니다."
    assert 날(17, 6, 30) is None, "06:00~07:00 정비는 창 밖입니다."
    assert 날(17, 7, 0) == date(2026, 9, 17)


def test_시간표에_없는_품목은_달력_날짜다():
    assert judge.overseas_trading_day({"exch": "01", "comd": "없음"}, table=_표, at=_시(17, 0, 1)) == date(2026, 9, 17)
    assert judge.overseas_trading_day(None, table=None, at=_시(17, 0, 1)) == date(2026, 9, 17)


# ── VWAP ─────────────────────────────────────────────────


def _봉(day: int, hour: int, minute: int, price: float, volume: float = 10.0) -> Bar:
    return Bar(_ms(day, hour, minute), price, price, price, price, volume)


def _vwap(bars: list[Bar], day_of) -> list[float | None]:
    series = rules.series_of(
        bars, sessions=[해외] * len(bars), session=해외, wanted=[("vwap", {})], day_of=day_of
    )
    return series.values["vwap"]


def test_해외_VWAP_은_한국_자정에_끊기지_않고_세션_시작에서_끊긴다():
    봉들 = [
        _봉(16, 23, 58, 100.0),
        _봉(16, 23, 59, 102.0),
        _봉(17, 0, 0, 104.0),  # 같은 세션
        _봉(17, 5, 59, 106.0),
        _봉(17, 7, 0, 200.0),  # 새 세션
    ]

    값 = _vwap(봉들, _거래일(_CME))
    assert 값[2] == pytest.approx(102.0), "(100+102+104)/3 — 자정에 다시 서지 않습니다."
    assert 값[3] == pytest.approx(103.0)
    assert 값[4] == pytest.approx(200.0), "07:00 새 세션에서 다시 섭니다."

    옛값 = _vwap(봉들, None)
    assert 옛값[2] == pytest.approx(104.0), "거래일을 안 주면 달력 날짜(지금과 같음)."


def test_창_밖의_봉은_앞_봉의_거래일을_잇는다():
    봉들 = [
        _봉(16, 12, 59, 100.0),
        _봉(16, 13, 30, 110.0),  # 13:00~14:00 쉼 — 창 밖
        _봉(16, 14, 0, 120.0),
    ]

    assert _거래일(_HKEX)(봉들[1].timestamp) is None, "쉼은 창 밖입니다(시간표로 판정)."
    assert _거래일(_HKEX)(봉들[0].timestamp) == date(2026, 9, 16)
    값 = _vwap(봉들, _거래일(_HKEX))
    assert 값 == [pytest.approx(100.0), pytest.approx(105.0), pytest.approx(110.0)]


def test_국내는_거래일_자리가_없어_지금과_같다():
    assert trading_day_of("domestic", "A7569000") is None
    엔진 = engine.RunEngine(
        runs.Run(id="r", version_id="", code="A", session="domestic-day", market="domestic", draft=_설정()),
        tick=0.05,
    )
    assert 엔진.trading_day is None


# ── 판정은 새 봉에 한 번 ──────────────────────────────────


def _vwap_규칙() -> dict:
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(
        {"id": "c1", "left": "close", "op": "gt", "rightKind": "operand", "right": "vwap"}
    )
    return 설정


def test_엔진은_새_봉마다_거래일을_한_번만_묻는다():
    물음: list[int] = []

    def 세기(timestamp: int):
        물음.append(timestamp)
        return _거래일(_CME)(timestamp)

    엔진 = engine.RunEngine(
        runs.Run(id="r", version_id="", code="6A", session=해외, market="overseas", state=runs.ARMED, draft=_vwap_규칙()),
        tick=0.01,
    )
    엔진.trading_day = 세기
    때들 = [_ms(16, 23, 50 + i) for i in range(8)]
    for 때 in 때들:
        엔진.on_trade({"timestamp": 때, "price": 100.0, "quantity": 1}, 해외, at=때)

    닫힌 = len(엔진.bars.bars)
    assert 닫힌 == 7
    assert sorted(물음) == [one.timestamp for one in 엔진.bars.bars], "닫힌 봉마다 한 번입니다."


def test_지난_봉_셈도_봉마다_한_번만_묻는다():
    물음: list[int] = []

    def 세기(timestamp: int):
        물음.append(timestamp)
        return _거래일(_CME)(timestamp)

    봉들 = [_봉(16, 8, minute, 100.0 + minute * 0.01) for minute in range(40)]
    답 = backtest.compute(
        draft=_vwap_규칙(), market="overseas", code="6A", session=해외, bars=봉들, tick=0.01,
        trading_day=세기,
    )

    assert 답["bars"]["count"] > 0
    assert sorted(물음) == [one.timestamp for one in 봉들]
