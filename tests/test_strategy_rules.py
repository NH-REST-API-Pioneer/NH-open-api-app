"""조건식 판정.

**봉을 손으로 지어 그 봉에서 걸리는지 봅니다.** 낱말은 화면의 `strategyRules.ts`
와 같아야 하고, 갈리면 사용자가 만든 문장과 엔진이 보는 문장이 달라집니다.
"""
from __future__ import annotations

from datetime import datetime

from backend.sessions.hours import KST
from backend.strategy import rules
from backend.strategy.indicators import Bar


def _bars(closes: list[float]) -> list[Bar]:
    """종가만 다른 봉들. 고·저는 종가에 붙여 둡니다."""
    return [
        Bar(timestamp=at * 60_000, open=close, high=close, low=close, close=close, volume=10.0)
        for at, close in enumerate(closes)
    ]


def _cond(left: str, op: str, right: str, kind: str = "number") -> dict:
    return {"id": "c1", "left": left, "op": op, "rightKind": kind, "right": right}


def _rule(*conds: dict, on: bool = True, join: str = "all") -> dict:
    return {"on": on, "steps": [{"id": "s1", "join": join, "withinBars": 0, "conds": list(conds)}]}


def _단계(window: int, *conds: dict) -> dict:
    return {"id": f"s{window}", "join": "all", "withinBars": window, "conds": list(conds)}


def test_낱말이_화면과_같다():
    """한쪽만 늘면 사용자가 만든 문장을 엔진이 못 읽습니다.

    호가·시간·포지션 여덟과 「같음」은 서버가 먼저 받습니다. 화면은 뒤따릅니다.
    """
    assert len(rules.OPERAND_IDS) == 33
    assert rules.OPERAND_IDS[14:22] == (
        "bid1",
        "ask1",
        "bid1Qty",
        "ask1Qty",
        "positionQty",
        "openPl",
        "clock",
        "barOrder",
    ), "새 값은 끝에 붙어 앞의 차례가 그대로입니다."
    assert rules.OPERAND_IDS[22:] == (
        "ema",
        "ma",
        "rsi",
        "atr",
        "bbMiddle",
        "vwap",
        "macdLine",
        "macdSignal",
        "macdHist",
        "stochK",
        "stochD",
    ), "매개변수를 받는 지표도 끝에 붙습니다."
    assert len(rules.OPERATOR_IDS) == 7
    assert rules.RULE_KEYS == ("buyEntry", "sellEntry", "buyExit", "sellExit")


def test_교차의_양쪽_낱말():
    """오른쪽은 가격 축의 선, 왼쪽은 거기에 가격 넷을 더합니다."""
    assert rules.CROSS_LINE_IDS == (
        "ema20",
        "ema50",
        "ma20",
        "bbUpper",
        "bbLower",
        "ema",
        "ma",
        "bbMiddle",
        "vwap",
    )
    assert set(rules.CROSS_LEFT_IDS) - set(rules.CROSS_LINE_IDS) == {
        "close",
        "open",
        "high",
        "low",
    }


def test_조건이_없는_규칙은_켜져_있어도_안_걸린다():
    """화면 씨앗의 청산 규칙이 이 모양입니다 — 「빈 관문은 늘 통과」로 읽으면
    진입한 그 봉에 바로 청산됩니다."""
    series = rules.series_of(_bars([10, 11, 12]))

    assert rules.fires_at({"on": True, "steps": []}, series, 2) is False
    빈단계 = {"on": True, "steps": [{"id": "s1", "join": "all", "withinBars": 0, "conds": []}]}
    assert rules.fires_at(빈단계, series, 2) is False


def test_꺼진_규칙은_안_걸린다():
    series = rules.series_of(_bars([10, 11, 12]))
    규칙 = _rule(_cond("close", "gt", "5"), on=False)

    assert rules.fires_at(규칙, series, 2) is False


def test_1단계는_새로_참이_된_봉에만_켜진다():
    """한 번 참이 되면 여러 봉 참이라, 그대로 두면 봉마다 주문이 나갑니다."""
    series = rules.series_of(_bars([10, 11, 12, 13]))
    규칙 = _rule(_cond("close", "gt", "11.5"))

    assert rules.fired_bars(규칙, series) == [2], "12 에서 새로 참이 됐습니다."


def test_첫_봉은_전이가_아니다():
    """직전이 없는 것을 거짓으로 세면, 이미 참이던 상태 조건이 시작하자마자 걸립니다."""
    series = rules.series_of(_bars([12, 13, 9, 13]))
    규칙 = _rule(_cond("close", "gt", "11.5"))

    assert rules.fired_bars(규칙, series) == [3], "첫 봉의 12 로는 안 걸립니다."


def test_교차는_직전_봉과_함께_본다():
    # 20봉 평균의 준비 봉(40)을 채운 뒤 지나도록 올렸다가 꺾습니다.
    closes = [100.0] * 40 + [120.0, 121.0]
    series = rules.series_of(_bars(closes))
    올라탐 = _rule(_cond("close", "crossUp", "ma20", kind="operand"))

    assert rules.fired_bars(올라탐, series) == [40], "이미 위에 있으면 교차가 아닙니다."


def test_가격이_선을_뚫는_교차도_센다():
    """화면 씨앗의 평균회귀 갈래가 「종가가 볼린저 하단을 아래로 뚫음」입니다."""
    closes = [100.0] * 45 + [99.0]
    series = rules.series_of(_bars(closes))
    뚫음 = _rule(_cond("close", "crossDown", "bbLower", kind="operand"))

    assert rules.fired_bars(뚫음, series) == [45]


def test_준비_봉은_기간의_두_배다():
    """기간만 차면 값이 나오기는 하지만, 앞쪽 값은 시드에 끌려다닙니다."""
    series = rules.series_of(_bars([100.0] * 45))

    assert series.at("ma20", 38) is None
    assert series.at("ma20", 39) == 100.0
    assert series.at("rsi14", 26) is None
    assert series.at("rsi14", 27) is not None


def test_준비가_안_된_지표는_거짓이다():
    """값을 모르는 것을 참으로 보면 봉이 모자란 채로 주문이 나갑니다."""
    series = rules.series_of(_bars([10, 11, 12]))
    규칙 = _rule(_cond("ema50", "gt", "5"))

    assert rules.fires_at(규칙, series, 2) is False
    assert series.at("ema50", 2) is None


def test_단계_안의_잇는_방법():
    series = rules.series_of(_bars([10, 11, 12]))
    맞음 = _cond("close", "gt", "11.5")
    틀림 = {**_cond("close", "lt", "5"), "id": "c2"}

    assert rules.fires_at(_rule(맞음, 틀림, join="all"), series, 2) is False
    assert rules.fires_at(_rule(맞음, 틀림, join="any"), series, 2) is True


def _두단계(window: int) -> dict:
    return {
        "on": True,
        "steps": [
            _단계(window, _cond("close", "gt", "10.5")),
            _단계(0, _cond("close", "lt", "9.5")),
        ],
    }


def test_순차_단계는_다음_봉부터_센다():
    """같은 봉에서 두 단계가 함께 채워질 수는 없습니다."""
    # 11 에서 1단계, 9 에서 2단계.
    series = rules.series_of(_bars([10, 11, 9]))

    assert rules.fires_at(_두단계(1), series, 2) is True
    # 1단계가 두 봉 앞이면 「1봉 이내」에 안 듭니다.
    멀어진것 = rules.series_of(_bars([10, 11, 10, 9]))
    assert rules.fires_at(_두단계(1), 멀어진것, 3) is False
    assert rules.fires_at(_두단계(2), 멀어진것, 3) is True, "마지막 봉은 포함합니다."


def test_2단계는_전이를_보지_않는다():
    """창이 이미 시간을 잘라 줍니다."""
    두단계 = {
        "on": True,
        "steps": [
            _단계(2, _cond("close", "gt", "10.5")),
            _단계(0, _cond("close", "gt", "10.5")),
        ],
    }
    # 2단계의 판정식은 1단계가 켜진 봉에도 이미 참이라 전이가 아닙니다.
    series = rules.series_of(_bars([10, 11, 12]))

    assert rules.fired_bars(두단계, series) == [2]


def test_만료된_봉에서는_1단계가_켜지지_않는다():
    """만료 봉에서 바로 켜지면 유효기간이 한 봉씩 늘어난 것과 같습니다."""
    # 1단계는 11(t1) 에서 켜지고 창은 t2·t3 입니다. t3 은 1단계 판정식이
    # 거짓(10)→참(11)으로 바뀌는 봉이지만 만료 봉이라 거기서 다시 켜지지 않고,
    # t4 의 9 는 2단계로 읽히지 않습니다.
    series = rules.series_of(_bars([10, 11, 10, 11, 9]))

    assert rules.fired_bars(_두단계(2), series) == []


def test_뒤_단계는_창_안의_첫_참인_봉에서_채워진다():
    세단계 = {
        "on": True,
        "steps": [
            _단계(3, _cond("close", "gt", "10.5")),
            _단계(1, _cond("close", "lt", "9.5")),
            _단계(0, _cond("close", "gt", "11.5")),
        ],
    }
    # 2단계가 참인 봉은 t2·t3 둘입니다. 첫 봉(t2)에서 채워지므로 3단계의 창은
    # t3 하나뿐이고, 12 가 오는 t4 는 이미 창 밖입니다.
    series = rules.series_of(_bars([10, 11, 9, 9, 12]))

    assert rules.fired_bars(세단계, series) == []


def test_발사한_규칙은_다음_봉부터_1단계다():
    series = rules.series_of(_bars([10, 11, 9, 11, 9]))

    assert rules.fired_bars(_두단계(1), series) == [2, 4]


def test_몇_봉_안에가_0_이면_안_걸린다():
    """「다음 봉부터 N봉 이내」가 뜻을 가지려면 1 이상이어야 합니다."""
    series = rules.series_of(_bars([10, 11, 9]))

    assert rules.fires_at(_두단계(0), series, 2) is False


def test_모르는_연산자는_참으로_보지_않는다():
    """조용히 걸리는 것이 가장 나쁩니다."""
    series = rules.series_of(_bars([10, 11, 12]))

    assert rules.fires_at(_rule(_cond("close", "같음", "12")), series, 2) is False
    assert rules.fires_at(_rule(_cond("없는값", "gt", "1")), series, 2) is False


def test_이전_봉_고저는_한_칸_밀려_있다():
    series = rules.series_of(_bars([10, 11, 12]))

    assert series.at("prevHigh", 0) is None
    assert series.at("prevHigh", 2) == 11.0
    assert series.at("prevLow", 2) == 11.0


def test_걸린_규칙을_차례대로_낸다():
    series = rules.series_of(_bars([10, 11, 12]))
    규칙들 = {
        "buyEntry": _rule(_cond("close", "gt", "11.5")),
        "sellEntry": _rule(_cond("close", "lt", "5")),
        "buyExit": {"on": True, "steps": []},
        "sellExit": _rule(_cond("close", "gt", "11.5")),
    }

    assert rules.evaluate(규칙들, series, 2) == ["buyEntry", "sellExit"]


# ── 시간 초과 초기화(resetBars) ─────────────────────────


def _시한(window: int, reset, *, steps: int = 2) -> dict:
    """1단계 「종가 > 10.5」, 2단계 「종가 < 9.5」(, 3단계 「종가 > 11.5」)."""
    단계들 = [
        _단계(window, _cond("close", "gt", "10.5")),
        _단계(window if steps > 2 else 0, _cond("close", "lt", "9.5")),
    ]
    if steps > 2:
        단계들.append(_단계(0, _cond("close", "gt", "11.5")))
    made = {"on": True, "steps": 단계들}
    if reset is not None:
        made["resetBars"] = reset
    return made


def _두_경로가_같다(rule: dict, series: rules.Series) -> list[int]:
    """`fired_bars` 와 봉마다 처음부터 다시 구르는 `fires_at` 이 같은 답인지."""
    한꺼번에 = rules.fired_bars(rule, series)
    봉마다 = [index for index in range(series.length) if rules.fires_at(rule, series, index)]
    assert 한꺼번에 == 봉마다
    return 한꺼번에


def test_시한_경계_봉에서는_발사한다():
    """1단계가 t1 에서 채워지고 시한이 2봉이면 t3 까지 발사할 수 있습니다."""
    series = rules.series_of(_bars([10, 11, 10, 9]))

    assert _두_경로가_같다(_시한(5, 2), series) == [3]


def test_시한을_넘긴_봉에서는_발사하지_않는다():
    """t4 = 1 + 2 + 1 은 시한 밖입니다. 단계 창(5봉)만 있었다면 발사했습니다."""
    series = rules.series_of(_bars([10, 11, 10, 10, 9]))

    assert _두_경로가_같다(_시한(5, None), series) == [4]
    assert _두_경로가_같다(_시한(5, 2), series) == []


def test_시한을_넘긴_봉에서_1단계를_다시_본다():
    """t4 에서 1단계로 돌아가 그 봉의 전이(10→11)로 다시 채워지고, 새 시한은 t4 부터입니다."""
    series = rules.series_of(_bars([10, 11, 10, 10, 11, 9]))

    assert _두_경로가_같다(_시한(5, 2), series) == [5]


def test_실제_기한은_단계_창과_시한_중_이른_쪽이다():
    """단계 창이 더 짧으면 창이 먼저 닫힙니다."""
    series = rules.series_of(_bars([10, 11, 10, 9]))

    assert _두_경로가_같다(_시한(1, 5), series) == []
    assert _두_경로가_같다(_시한(1, None), series) == []


def test_시한은_1단계가_채워진_봉부터_센다():
    """세 단계면 2단계를 채운 봉이 아니라 1단계를 채운 봉부터 셉니다."""
    # 1단계 t1, 2단계 t2. 시한 3봉 → 마지막 단계는 t4 까지.
    안 = rules.series_of(_bars([10, 11, 9, 10, 12]))
    밖 = rules.series_of(_bars([10, 11, 9, 10, 10, 12]))

    assert _두_경로가_같다(_시한(5, 3, steps=3), 안) == [4]
    assert _두_경로가_같다(_시한(5, 3, steps=3), 밖) == []
    assert _두_경로가_같다(_시한(5, None, steps=3), 밖) == [5]


def test_시한이_비었거나_0_이면_제한이_없다():
    series = rules.series_of(_bars([10, 11, 10, 10, 9]))

    for 값 in (None, "", 0, "0"):
        assert _두_경로가_같다(_시한(5, 값), series) == [4], 값


# ── 호가·시간·포지션 값 ─────────────────────────────────


_옛_열 = (
    "close", "open", "high", "low", "ema20", "ema50", "ma20", "rsi14",
    "atr14", "bbUpper", "bbLower", "volume", "prevHigh", "prevLow",
)


def _적은값(values: dict[str, list]) -> dict[int, dict[str, float | None]]:
    """열 이름 → 봉마다의 값을, series_of 가 받는 「봉 시각 → 값들」로."""
    length = len(next(iter(values.values())))
    return {at * 60_000: {name: column[at] for name, column in values.items()} for at in range(length)}


def test_인자_없이_부르면_옛_열은_그대로다():
    """새 인자를 줘도 지표·가격 열은 한 칸도 안 바뀝니다. 적은 값이 없으면 새 열은 비어 있습니다."""
    bars = _bars([10, 11, 12, 11, 10])
    옛 = rules.series_of(bars)
    새 = rules.series_of(
        bars,
        sessions=["domestic-day"] * 5,
        marks=_적은값({"positionQty": [0.0] * 5}),
        session="domestic-day",
    )

    for name in _옛_열:
        assert 옛.values[name] == 새.values[name], name
    for name in rules.RECORDED_IDS + (rules.BAR_ORDER,):
        assert 옛.values[name] == [None] * 5, name


def _때봉(*times: tuple[int, int, int]) -> list[Bar]:
    """(일, 시, 분) 마다 봉 하나."""
    made = []
    for day, hour, minute in times:
        stamp = int(datetime(2026, 9, day, hour, minute, tzinfo=KST).timestamp() * 1000)
        made.append(Bar(timestamp=stamp, open=10, high=10, low=10, close=10, volume=1.0))
    return made


def test_야간은_자정_뒤_시각이_앞_시각보다_뒤다():
    """23:50 봉 다음의 00:30 봉이 「이후」로 읽혀야 합니다."""
    bars = _때봉((17, 23, 50), (18, 0, 30))
    series = rules.series_of(bars, sessions=["domestic-night"] * 2, session="domestic-night")

    밤, 새벽 = series.values["clock"]
    assert (밤, 새벽) == (23 * 60 + 50, 1440 + 30)
    assert 새벽 > 밤
    assert rules.cond_at(_cond("clock", "eq", "00:30"), series, 1)
    assert rules.cond_at(_cond("clock", "gt", "23:50"), series, 1)
    assert not rules.cond_at(_cond("clock", "lt", "23:50"), series, 1)


def test_시각의_오른쪽도_세션의_셈으로_읽는다():
    """같은 「01:00」이 야간 실행에서는 자정 뒤(1500), 주간 실행에서는 60 입니다."""
    assert rules.clock_of(1, 0, "domestic-night") == 1500
    assert rules.clock_of(1, 0, "domestic-day") == 60
    assert rules.clock_of(18, 0, "domestic-night") == 1080, "12시 뒤는 더하지 않습니다."
    bars = _때봉((18, 1, 0))
    야간 = rules.series_of(bars, sessions=["domestic-night"], session="domestic-night")
    assert rules.right_at(_cond("clock", "eq", "01:00"), 야간, 0) == 1500.0
    assert rules.cond_at(_cond("clock", "eq", "01:00"), 야간, 0)


def test_시각은_두_자리_HH_MM_만_읽는다():
    assert rules.parse_clock("09:05") == (9, 5)
    for 틀림 in ("9:05", "24:00", "12:60", "0930", "", None, "09:5"):
        assert rules.parse_clock(틀림) is None, 틀림


def test_같음은_값이_같은_봉에서만_참이다():
    series = rules.series_of(_bars([10, 10, 10]), marks=_적은값({"positionQty": [0.0, 1.0, 2.0]}))

    assert [rules.cond_at(_cond("positionQty", "eq", "1"), series, at) for at in range(3)] == [
        False,
        True,
        False,
    ]


def _보유규칙(op: str, right: str) -> dict:
    return {"on": True, "steps": [_단계(0, _cond("positionQty", op, right))]}


def test_실행_전_봉의_빈_값에서_넘어오는_것은_전이가_아니다():
    """실행을 세운 첫 판정 봉에서 「보유 0」 같은 상태 조건이 바로 걸리면 안 됩니다."""
    series = rules.series_of(
        _bars([10] * 5), marks=_적은값({"positionQty": [None, None, 0.0, 1.0, 0.0]})
    )

    assert _두_경로가_같다(_보유규칙("eq", "0"), series) == [4], "1→0 으로 바뀐 봉에서만 걸립니다."
    assert _두_경로가_같다(_보유규칙("gt", "0"), series) == [3]


def test_빈_값_규칙은_지표만_쓰는_단계를_건드리지_않는다():
    """지표·가격만 쓰는 1단계는 새 열이 비어 있어도 전과 같이 전이를 봅니다."""
    series = rules.series_of(_bars([10, 11, 12]))

    assert _두_경로가_같다(_rule(_cond("close", "gt", "10.5")), series) == [1]


def test_호가_열은_적은_값을_봉_시각으로_찾는다():
    """자리 번호가 아니라 시각으로 찾으므로 적은 값이 없는 봉은 비어 있습니다."""
    bars = _bars([10, 10, 10])
    series = rules.series_of(bars, marks={60_000: {"bid1": 9.9, "ask1": 10.1}})

    assert series.values["bid1"] == [None, 9.9, None]
    assert series.values["ask1"] == [None, 10.1, None]
