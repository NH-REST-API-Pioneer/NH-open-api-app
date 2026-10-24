"""지표의 매개변수와 새 지표 — MACD·스토캐스틱·VWAP.

새 식은 **손으로 센 값**과 견줍니다. 매개변수가 생기기 전의 이름으로 적은 전략은
판정·준비 봉·값이 매개변수의 기본값으로 센 것과 같아야 합니다.
"""
from __future__ import annotations

import random
from datetime import datetime

import pytest

from backend.sessions.hours import KST
from backend.strategy import engine, indicators, rules, validate
from backend.strategy.indicators import Bar
from tests.test_strategy_engine import _규칙, _설정, _조건

주간 = "domestic-day"
야간 = "domestic-night"


def _봉(high: float, low: float, close: float, volume: float = 1.0, at: int = 0) -> Bar:
    return Bar(timestamp=at, open=close, high=high, low=low, close=close, volume=volume)


def _종가봉(closes: list[float]) -> list[Bar]:
    return [_봉(c, c, c, 1.0, at * 60_000) for at, c in enumerate(closes)]


def _때(day: int, hour: int, minute: int) -> int:
    return int(datetime(2026, 9, day, hour, minute, tzinfo=KST).timestamp() * 1000)


# ── 새 식: 손 셈 ─────────────────────────────────────────────


def test_MACD_는_DIF_DEA_막대를_손_셈과_같게_낸다():
    """단기 2·장기 3·신호 2. EMA 는 SMA 로 시작합니다."""
    선, 신호, 막대 = indicators.macd([10, 11, 12, 11, 13, 14], 2, 3, 2)

    # EMA(2): 10.5, 11.5, 11.1667, 12.3889, 13.4630 / EMA(3): 11, 11, 12, 13
    assert 선[:2] == [None, None]
    assert 선[2:] == pytest.approx([0.5, 1 / 6, 0.388889, 0.462963], rel=1e-5)
    # DEA: 첫 두 DIF 의 평균 1/3 에서 시작합니다.
    assert 신호[:3] == [None, None, None]
    assert 신호[3:] == pytest.approx([1 / 3, 0.370370, 0.432099], rel=1e-5)
    assert 막대[3] == pytest.approx(1 / 6 - 1 / 3, rel=1e-5)
    assert 막대[5] == pytest.approx(0.462963 - 0.432099, rel=1e-4), "2 를 곱하지 않습니다."


def test_스토캐스틱은_원값을_두_번_평균한다():
    봉들 = [
        _봉(10, 8, 9),
        _봉(11, 9, 10),
        _봉(12, 10, 11),
        _봉(12, 9, 9),
        _봉(13, 11, 12),
    ]

    k, d = indicators.stochastic(봉들, 3, 2, 2)

    # 원값: 75(11−8)/(12−8), 0(9−9)/(12−9), 75(12−9)/(13−9)
    assert k[:3] == [None, None, None]
    assert k[3:] == pytest.approx([37.5, 37.5])
    assert d[:4] == [None] * 4
    assert d[4] == pytest.approx(37.5)


def test_스토캐스틱은_고저가_같으면_가운데_50이다():
    k, _ = indicators.stochastic([_봉(5, 5, 5)] * 3, 3, 1, 1)

    assert k[2] == 50.0


def test_VWAP_은_세션마다_다시_세고_거래량이_없으면_모름이다():
    봉들 = [
        _봉(12, 8, 10, 2),  # 전형가 10
        _봉(15, 9, 12, 1),  # 전형가 12
        _봉(30, 30, 30, 0),  # 거래량 0 — 누적은 그대로
        _봉(21, 19, 20, 4),  # 새 세션
        _봉(5, 5, 5, 0),  # 새 세션, 거래량 0
    ]

    값 = indicators.vwap(봉들, ["a", "a", "a", "b", "c"])

    assert 값[0] == pytest.approx(10.0)
    assert 값[1] == pytest.approx((10 * 2 + 12 * 1) / 3)
    assert 값[2] == pytest.approx((10 * 2 + 12 * 1) / 3)
    assert 값[3] == pytest.approx(20.0), "세션이 바뀌면 처음부터 셉니다."
    assert 값[4] is None, "누적 거래량이 0 이면 나눌 수 없습니다."


def test_VWAP_세션은_거래일과_창으로_가르고_야간은_자정을_넘어_잇는다():
    봉들 = [
        Bar(_때(17, 15, 0), 10, 10, 10, 10, 1),  # 주간
        Bar(_때(17, 18, 0), 20, 20, 20, 20, 1),  # 야간 시작 — 새 세션
        Bar(_때(18, 1, 0), 30, 30, 30, 30, 1),  # 자정 뒤 — 같은 야간
    ]
    시리즈 = rules.series_of(봉들, sessions=[주간, 야간, 야간], wanted=[("vwap", {})])

    assert 시리즈.at("vwap", 0) == pytest.approx(10.0)
    assert 시리즈.at("vwap", 1) == pytest.approx(20.0)
    assert 시리즈.at("vwap", 2) == pytest.approx(25.0)


# ── 옛 이름 ──────────────────────────────────────────────────


def test_옛_이름은_읽을_때_지표와_매개변수로_옮긴다():
    assert rules.resolve("ema20") == ("ema", {"period": 20})
    assert rules.resolve("bbLower") == ("bbLower", {"period": 20, "multiplier": 2.0})
    assert rules.resolve("ema", {"period": "5"}) == ("ema", {"period": 5})
    assert rules.resolve("macdLine") == ("macdLine", {"fast": 12, "slow": 26, "signal": 9})
    assert rules.resolve("close") == ("close", {})
    assert rules.operand_key("bbUpper", {"period": 20, "multiplier": 2.5}) == "bbUpper(20,2.5)"
    assert rules.legacy_table()["ema50"] == {"id": "ema", "params": {"period": 50}}


def test_옮긴_열은_옛_열과_봉마다_같다():
    봉들 = _종가봉([100 + random.Random(7).uniform(-5, 5) for _ in range(200)])
    시리즈 = rules.series_of(봉들)

    for old, (new, params) in rules.LEGACY_OPERANDS.items():
        assert 시리즈.values[old] == 시리즈.values[rules.operand_key(new, params)]


def _옛과_새():
    옛 = _규칙(_조건(left="ema20", op="crossUp", right="ema50", kind="operand"))
    새 = _규칙(
        {
            "id": "c1",
            "left": "ema",
            "leftParams": {"period": 20},
            "op": "crossUp",
            "rightKind": "operand",
            "right": "ema",
            "rightParams": {"period": 50},
        }
    )
    return 옛, 새


def test_옛_전략의_판정은_전후가_같다():
    흔들림 = random.Random(3)
    값 = 100.0
    closes = []
    for _ in range(400):
        값 += 흔들림.uniform(-2, 2)
        closes.append(값)
    봉들 = _종가봉(closes)
    옛, 새 = _옛과_새()

    앞 = rules.fired_bars(옛, rules.series_of(봉들))
    뒤 = rules.fired_bars(새, rules.series_of(봉들, wanted=rules.wanted_of({"buyEntry": 새})))

    assert 앞, "시험이 뜻을 가지려면 걸리는 봉이 있어야 합니다."
    assert 앞 == 뒤
    # 매개변수가 생기기 전의 식(고정 기간 EMA)으로 바로 세운 열과도 같습니다.
    예전 = rules.Series(
        values={
            "ema(20)": indicators.warmed(indicators.ema(closes, 20), 20),
            "ema(50)": indicators.warmed(indicators.ema(closes, 50), 50),
        },
        length=len(closes),
    )
    assert rules.fired_bars(옛, 예전) == 앞


def test_옛_전략의_준비_봉은_전후가_같다():
    옛, 새 = _옛과_새()
    볼린저 = _규칙(_조건(left="close", op="crossDown", right="bbLower", kind="operand"))

    assert engine._warmup_of({"buyEntry": 옛}) == 100 == engine._warmup_of({"buyEntry": 새})
    assert engine._warmup_of({"buyEntry": 볼린저}) == 40, "볼린저(20, 2)는 20×2 입니다."
    assert engine._warmup_of({"buyEntry": _규칙(_조건(left="rsi14", op="gte", right="55"))}) == 28


def test_새_지표의_준비_봉은_매개변수로_센다():
    macd = _규칙({"id": "c", "left": "macdLine", "op": "gt", "rightKind": "number", "right": "0"})
    stoch = _규칙({"id": "c", "left": "stochK", "leftParams": {"period": 14, "k": 3, "d": 3},
                   "op": "lte", "rightKind": "number", "right": "20"})
    vwap = _규칙({"id": "c", "left": "close", "op": "gt", "rightKind": "operand", "right": "vwap"})

    assert engine._warmup_of({"buyEntry": macd}) == (26 + 9) * 2
    assert engine._warmup_of({"buyEntry": stoch}) == (14 + 3 + 3) * 2
    assert engine._warmup_of({"buyEntry": vwap}) == 2, "VWAP 은 준비 봉이 없습니다."


def test_같은_지표는_한_번만_센다():
    규칙들 = {
        "buyEntry": _규칙(
            {"id": "a", "left": "ema", "leftParams": {"period": 5}, "op": "gt", "rightKind": "number", "right": "1"},
            {"id": "b", "left": "close", "op": "gt", "rightKind": "operand", "right": "ema", "rightParams": {"period": 5}},
        ),
        "sellEntry": _규칙(_조건(left="ema20", op="gt", right="1")),
        "buyExit": _규칙({"id": "c", "left": "ema", "op": "gt", "rightKind": "number", "right": "1"}),
    }

    assert sorted(rules.operand_key(*one) for one in rules.wanted_of(규칙들)) == ["ema(20)", "ema(5)"]


# ── 체결 줄·조건 표의 이름 ──────────────────────────────────


def test_체결_줄의_이름은_매개변수를_담는다():
    규칙들 = {
        "buyEntry": _규칙(
            {"id": "a", "left": "ema", "leftParams": {"period": 5}, "op": "crossUp",
             "rightKind": "operand", "right": "ema", "rightParams": {"period": 20}},
            {"id": "b", "left": "macdHist", "op": "gt", "rightKind": "number", "right": "0"},
        ),
    }

    assert engine._snapshot_ids(규칙들) == ("close", "ema(20)", "ema(5)", "macdHist(12,26,9)")


def test_조건_표의_조건_줄에_매개변수를_싣는다():
    시리즈 = rules.series_of(_종가봉([10.0] * 30), wanted=[("ema", {"period": 5})])
    조건 = {"left": "ema", "leftParams": {"period": 5}, "op": "gt", "rightKind": "number", "right": "1"}

    줄 = rules.cond_row(조건, 시리즈, 29)

    assert 줄["leftParams"] == {"period": 5} and 줄["rightParams"] is None
    assert 줄["leftValue"] == pytest.approx(10.0)
    assert rules.cond_row(_조건(left="ema20"), 시리즈, 29)["leftParams"] == {"period": 20}


# ── 검증 ─────────────────────────────────────────────────────


def _설정과(*conds: dict) -> dict:
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(*conds)
    return 설정


def _문제들(*conds: dict) -> list[str]:
    return [one["message"] for one in validate.problems(_설정과(*conds), market="domestic")]


def test_옛_이름으로_적은_전략은_그대로_받는다():
    assert _문제들(_조건(left="ema20", op="crossUp", right="ema50", kind="operand")) == []
    assert _문제들(_조건(left="close", op="crossDown", right="bbLower", kind="operand")) == []


@pytest.mark.parametrize(
    ("params", "좋음"),
    [
        ({"period": 2}, True),
        ({"period": 200}, True),
        ({"period": 1}, False),
        ({"period": 201}, False),
        ({"period": 5.5}, False),
    ],
)
def test_기간은_2_부터_200_까지_정수다(params, 좋음):
    문제 = _문제들({"id": "c", "left": "ema", "leftParams": params, "op": "gt", "rightKind": "number", "right": "1"})

    assert (문제 == []) is 좋음
    if not 좋음:
        assert 문제 == [validate._PERIOD_RANGE]


@pytest.mark.parametrize(("배수", "좋음"), [(0.5, True), (5, True), (2.5, True), (0.4, False), (5.1, False), (2.25, False)])
def test_볼린저_배수는_0_5_부터_5_까지_소수_한_자리다(배수, 좋음):
    문제 = _문제들(
        {"id": "c", "left": "close", "op": "gt", "rightKind": "operand", "right": "bbUpper",
         "rightParams": {"period": 20, "multiplier": 배수}}
    )

    assert (문제 == []) is 좋음


def test_MACD_단기는_장기보다_짧다():
    문제 = _문제들({"id": "c", "left": "macdLine", "leftParams": {"fast": 26, "slow": 26, "signal": 9},
                 "op": "gt", "rightKind": "number", "right": "0"})

    assert 문제 == [validate._FAST_SLOW]


@pytest.mark.parametrize(("k", "좋음"), [(1, True), (50, True), (0, False), (51, False)])
def test_스토캐스틱_평활은_1_부터_50_까지다(k, 좋음):
    문제 = _문제들({"id": "c", "left": "stochK", "leftParams": {"period": 9, "k": k, "d": 3},
                 "op": "lte", "rightKind": "number", "right": "20"})

    assert (문제 == []) is 좋음


def test_MACD_끼리는_같은_설정이어야_한다():
    같음 = {"fast": 12, "slow": 26, "signal": 9}
    다름 = {"fast": 5, "slow": 26, "signal": 9}

    def 교차(오른쪽):
        return {"id": "c", "left": "macdLine", "leftParams": 같음, "op": "crossUp",
                "rightKind": "operand", "right": "macdSignal", "rightParams": 오른쪽}

    assert _문제들(교차(같음)) == []
    assert _문제들(교차(다름)) == [validate._SHARED_PARAMS]


@pytest.mark.parametrize(
    ("left", "lp", "right", "rp", "좋음"),
    [
        ("ema", {"period": 5}, "ema", {"period": 20}, True),
        ("close", None, "vwap", None, True),
        ("stochK", None, "stochD", None, True),
        ("rsi", {"period": 6}, "rsi", {"period": 14}, True),
        ("ema", {"period": 20}, "ema20", None, False),  # 같은 값
        ("rsi", None, "close", None, False),
        ("rsi", None, "ema", None, False),
        ("macdLine", None, "stochK", None, False),
    ],
)
def test_교차는_같은_축의_짝에만_선다(left, lp, right, rp, 좋음):
    조건 = {"id": "c", "left": left, "op": "crossUp", "rightKind": "operand", "right": right}
    if lp:
        조건["leftParams"] = lp
    if rp:
        조건["rightParams"] = rp

    assert (_문제들(조건) == []) is 좋음


# ── 옛 이름에 매개변수가 함께 오면 ───────────────────────────


def test_옛_이름에_매개변수가_오면_새_지표로_옮기고_매개변수가_이긴다():
    """옛 이름을 둔 채 기간만 고친 조건이 열을 못 찾아 조용히 죽지 않습니다."""
    조건 = {"id": "c", "left": "ema20", "leftParams": {"period": 5}, "op": "gt", "rightKind": "number", "right": "1"}

    assert rules.resolve("ema20", {"period": 5}) == ("ema", {"period": 5})
    assert rules.side_key(조건, "left") == "ema(5)"
    시리즈 = rules.series_of(_종가봉([10.0] * 20), wanted=rules.wanted_of({"buyEntry": _규칙(조건)}))
    assert 시리즈.at("ema(5)", 19) == pytest.approx(10.0), "값이 서야 합니다."
    assert rules.cond_at(조건, 시리즈, 19) is True


def test_옛_이름에_붙은_매개변수도_범위를_본다():
    문제 = _문제들({"id": "c", "left": "ema20", "leftParams": {"period": 1}, "op": "gt",
                 "rightKind": "number", "right": "1"})

    assert 문제 == [validate._PERIOD_RANGE]
