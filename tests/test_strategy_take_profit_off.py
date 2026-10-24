"""익절을 쓰지 않는 전략 — 익절 칸을 비워 두면 그 청산이 없습니다.

손절은 꼭 적어야 하지만 익절은 추적 청산처럼 비워 둘 수 있습니다. 비워 둔 전략은
손절·추적 청산·세션 끝 정리·청산 규칙으로만 닫힙니다. **계좌에 닿지 않습니다** —
봉·호가·체결을 손으로 지어 넣습니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, paper, runs, validate
from tests.test_strategy_backtest import _몸, _봉, _셈, _진입봉, 손님  # noqa: F401 — 손님은 픽스처
from tests.test_strategy_engine import _때, _매수_보유, _설정, _엔진, _틱
from tests.test_strategy_store import _설정 as _저장_설정
from tests.test_strategy_store import _자리별

주간 = "domestic-day"


# ── 검사 ─────────────────────────────────────────────────


@pytest.mark.parametrize("값", ["", None, "   "])
def test_익절은_비워_둘_수_있다(값):
    설정 = _저장_설정()
    설정["aux"]["takeTicks"] = 값

    찾은것 = _자리별(설정)

    assert "aux.takeTicks" not in 찾은것
    assert not validate.blocked(list(찾은것.values()))


def test_익절이_없어도_손절은_꼭_적는다():
    설정 = _저장_설정()
    설정["aux"]["takeTicks"] = ""
    설정["aux"]["stopTicks"] = ""

    찾은것 = _자리별(설정)

    assert 찾은것["aux.stopTicks"]["severity"] == validate.ERROR
    assert "aux.takeTicks" not in 찾은것


@pytest.mark.parametrize(
    ("unit", "값", "말"),
    [
        ("", "0", "1 이상의 정수로 적습니다"),
        ("", "1.5", "1 이상의 정수로 적습니다"),
        ("tick", "1001", "틱은 1~1000 사이 정수로 적습니다"),
        ("price", "-1", "0보다 큰 수로 적습니다"),
        ("pct", "51", "%는 0.1~50 사이, 소수 한 자리까지 적습니다"),
        ("atr", "0.4", "ATR 배수는 0.5~10 사이, 소수 한 자리까지 적습니다"),
    ],
)
def test_익절을_적었다면_그_단위의_범위를_지킨다(unit, 값, 말):
    설정 = _저장_설정()
    설정["aux"].update(takeTicks=값, takeUnit=unit)

    하나 = _자리별(설정)["aux.takeTicks"]

    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == 말


@pytest.mark.parametrize(("unit", "값"), [("", "20"), ("pct", "2"), ("atr", "1.5"), ("price", "0.5")])
def test_값이_있는_옛_익절은_그대로_통과한다(unit, 값):
    설정 = _저장_설정()
    설정["aux"].update(takeTicks=값, takeUnit=unit)

    assert "aux.takeTicks" not in _자리별(설정)


@pytest.mark.parametrize("unit", ["tick", "price", "pct", "atr"])
def test_단위만_고르고_값을_비우면_쓰지_않는_것이다(unit):
    설정 = _저장_설정()
    설정["aux"].update(takeTicks="", takeUnit=unit)

    찾은것 = _자리별(설정)

    assert "aux.takeTicks" not in 찾은것 and "aux.takeUnit" not in 찾은것


def test_값을_비워도_모르는_단위는_짚는다():
    """단위 칸은 값과 따로 봅니다 — 추적 청산과 같은 판정입니다."""
    설정 = _저장_설정()
    설정["aux"].update(takeTicks="", takeUnit="모름")

    찾은것 = _자리별(설정)

    assert 찾은것["aux.takeUnit"]["message"] == "단위를 고르세요"
    assert "aux.takeTicks" not in 찾은것


# ── 실행 엔진 ─────────────────────────────────────────────


def _익절_주문(엔진: engine.RunEngine) -> list[dict]:
    """익절로 낸 주문 사건과 익절 체결 줄."""
    사건 = [
        one for one in 엔진.events
        if one["kind"] == engine.ORDER and str(one.get("text", "")).startswith("익절")
    ]
    체결 = [one for one in 엔진.fills if one.get("reason") == engine.TAKE_PROFIT]
    return 사건 + 체결


@pytest.mark.parametrize("unit", ["", "tick", "pct", "price"])
def test_익절이_없으면_올라도_닫지_않고_손절로_닫는다(unit):
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="", takeUnit=unit)  # 101.5 에 1계약, 손절 101.0
    assert 엔진.exit_lines() == [pytest.approx(101.0)], "감시하는 값은 손절 하나입니다."

    for 차례, 값 in enumerate((101.8, 103.0, 110.0, 101.6)):
        _틱(엔진, 때 + 10 * (차례 + 1), 값)
    assert 엔진.run.state == runs.HOLDING, "익절이 없으니 아무리 올라도 들고 있습니다."
    assert 엔진.ledger.position.quantity == 1

    _틱(엔진, 때 + 100, 101.0)
    assert 엔진.run.state == runs.EXITING
    엔진.on_book({"asks": [{"price": 101.05, "quantity": 9}], "bids": [{"price": 101.0, "quantity": 9}]},
                at=때 + 100 + int(paper.DELAY_SECONDS * 1000))

    assert 엔진.ledger.position.quantity == 0
    assert 엔진.fills[-1]["reason"] == engine.STOP_LOSS
    assert _익절_주문(엔진) == []


def test_익절이_있으면_같은_틱에_익절로_닫는다():
    """위 시험의 맞짝 — 같은 흐름에 익절 3틱을 적으면 첫 틱에 익절이 나갑니다."""
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="3")

    _틱(엔진, 때 + 10, 101.8)

    assert 엔진.run.state == runs.EXITING
    assert 엔진._exit_reason == engine.TAKE_PROFIT


def test_익절이_없어도_추적_청산은_돈다():
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="", trailTicks="2")

    _틱(엔진, 때 + 10, 103.0)  # 기준 103.0, 추적선 102.9
    assert 엔진.run.state == runs.HOLDING
    _틱(엔진, 때 + 20, 102.9)

    assert 엔진.run.state == runs.EXITING
    assert 엔진._exit_reason == engine.TRAIL_STOP
    assert _익절_주문(엔진) == []


def test_익절이_없어도_세션_끝_정리는_돈다():
    엔진 = _엔진(_설정(takeTicks="", sessionEndFlat=True, sessionEndMinutes="10"))
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    엔진.book.last_price = 100.0

    assert 엔진.session_end(_때(15, 25), _때(15, 35)) is True
    assert 엔진._exit_reason == engine.SESSION_END
    assert _익절_주문(엔진) == []


def test_매도_보유도_익절이_없으면_내려도_닫지_않는다():
    엔진 = _엔진(_설정(stopTicks="2", takeTicks=""))
    엔진.ledger.add({"side": paper.SELL, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING

    for 값 in (99.0, 90.0, 80.0):
        엔진.book.last_price = 값
        엔진._watch(_때(10, 5))
    assert 엔진._exit_reason == "" and 엔진.run.state == runs.HOLDING

    엔진.book.last_price = 100.1
    엔진._watch(_때(10, 6))
    assert 엔진._exit_reason == engine.STOP_LOSS


# ── 지난 봉으로 돌려 보기 ──────────────────────────────────


def test_돌려_보기는_익절이_없으면_익절_체결이_없다():
    # 진입 101.05(시가 101 + 1틱). 09:03 봉은 손절 100.95 아래로 안 가고 101.20(익절 3틱 자리) 위로 갑니다.
    봉들 = _진입봉(_봉(9, 3, 101.0, 102.0, 101.0, 101.9), _봉(9, 4, 101.9, 101.9, 100.5, 100.6))

    있음 = _셈(봉들, _설정(takeTicks="3"))
    없음 = _셈(봉들, _설정(takeTicks=""))

    assert [one["reason"] for one in 있음["trades"]] == [engine.TAKE_PROFIT], "맞짝 — 익절이 있으면 09:03 에 닫힙니다."
    (거래,) = 없음["trades"]
    assert 거래["reason"] == engine.STOP_LOSS, "익절이 없으니 09:04 의 손절까지 들고 갑니다."
    assert _때(9, 4) <= 거래["closedAt"] < _때(9, 5)
    assert all(one["reason"] != engine.TAKE_PROFIT for one in 없음["trades"])
    assert 없음["assumptions"] == {**있음["assumptions"]}, "익절을 끄는 것은 가정을 바꾸지 않습니다."


def test_돌려_보기_라우트는_익절_빈_전략을_받는다(손님):
    앱, _ = 손님

    답 = 앱.post("/api/strategy/backtest", json=_몸(draft=_설정(takeTicks="")))

    assert 답.status_code == 200, 답.text
    assert all(one["reason"] != engine.TAKE_PROFIT for one in 답.json()["trades"])
