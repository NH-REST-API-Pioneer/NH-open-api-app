"""검증 화면의 조건 표 — 봉 마감마다 규칙이 무엇을 기다리고 조건마다 어떤지.

**판정을 다시 하지 않습니다.** 표는 판정이 그 봉에서 한 번 굴린 결과를 옮긴
것이라, 체결 줄에 실린 값·다음 봉의 판정과 어긋나지 않아야 합니다.
"""
from __future__ import annotations

from backend.strategy import engine, rules, runs
from tests.test_strategy_engine import _갈래, _규칙, _넣기, _때, _설정, _엔진, _조건

주간 = "domestic-day"


def _두단계(window: int = 1, reset: int = 0) -> dict:
    """종가 100 초과가 되고, 그 뒤 `window` 봉 안에 종가 200 초과가 되면 걸리는 규칙."""
    made = {
        "on": True,
        "steps": [
            {"id": "s1", "join": "all", "withinBars": window, "conds": [_조건(right="100")]},
            {"id": "s2", "join": "all", "withinBars": 0, "conds": [_조건(right="200")]},
        ],
    }
    if reset:
        made["resetBars"] = reset
    return made


def _표(엔진) -> dict:
    return 엔진.conditions


def _규칙줄(엔진, key: str = "buyEntry") -> dict:
    return next(one for one in _표(엔진)["rules"] if one["rule"] == key)


# ── 수명 ────────────────────────────────────────────────────


def test_첫_판정_봉_전에는_표가_없다():
    엔진 = _엔진()

    assert 엔진.conditions is None
    assert 엔진.snapshot()["conditions"] is None


def test_판정한_봉의_값과_참을_싣는다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.5)  # 1분 봉(종가 101)이 닫힙니다.

    표 = _표(엔진)
    assert (표["state"], 표["barTime"]) == (engine.TABLE_READY, _때(10, 1))
    줄 = _규칙줄(엔진)
    assert 줄["judged"] is True and 줄["fired"] is True
    (조건,) = 줄["stepsDetail"][0]["conds"]
    assert (조건["leftValue"], 조건["rightValue"], 조건["now"], 조건["before"]) == (101.0, 100.0, True, False)
    assert 엔진.snapshot()["conditions"] is 표


def test_체결_줄에_실리는_값과_같은_봉이면_같은_값이다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.5)

    (묶음,) = 엔진._snap.values()
    assert 묶음["barTime"] == _표(엔진)["barTime"]
    (조건,) = _규칙줄(엔진)["stepsDetail"][0]["conds"]
    assert 묶음["values"]["close"] == 조건["leftValue"]


def test_표는_봉마다_통째로_갈아_끼우고_쌓지_않는다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 98.0)
    _넣기(엔진, 2, 97.0)
    앞 = _표(엔진)
    _넣기(엔진, 3, 96.0)

    assert _표(엔진) is not 앞, "제자리에서 고치지 않습니다."
    assert 앞["barTime"] == _때(10, 1), "앞 표는 그대로 남습니다."
    assert _표(엔진)["barTime"] == _때(10, 2)


def test_표는_기록에_쓰지_않는다():
    기록: list = []
    엔진 = _엔진()
    엔진.record = lambda kind, row: 기록.append((kind, row))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.5)

    assert 엔진.conditions is not None
    assert all("conditions" not in row and "stepsDetail" not in str(row) for _, row in 기록)


# ── 판정 한 벌 ───────────────────────────────────────────────


def test_봉_하나에_규칙마다_한_번만_굴린다(monkeypatch):
    설정 = _설정()
    설정["rules"]["sellEntry"] = _규칙(_조건(op="lt", right="50"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 98.0)

    원래 = rules.stage_at
    부름: list[str] = []

    def 세기(rule, series, index):
        부름.append(index)
        return 원래(rule, series, index)

    monkeypatch.setattr(rules, "stage_at", 세기)
    _넣기(엔진, 2, 97.0)  # 1분 봉이 닫힙니다.

    assert len(부름) == 2, "켜진 규칙 둘 — 판정과 표가 한 번의 굴림을 나눠 씁니다."


def test_판정이_안_본_규칙은_judged_가_거짓이다():
    설정 = _설정()
    설정["rules"]["buyExit"] = _규칙(_조건(op="lt", right="50"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 98.0)
    _넣기(엔진, 2, 97.0)

    assert _규칙줄(엔진, "buyEntry")["judged"] is True
    assert _규칙줄(엔진, "buyExit")["judged"] is False, "보유가 없으면 청산 규칙은 안 봅니다."


# ── 보이는 상태 = 다음 봉의 판정 ─────────────────────────────


def test_창이_끝나는_봉과_그_다음_봉은_1단계_대기다():
    설정 = _설정()
    설정["rules"]["buyEntry"] = _두단계(window=1)
    엔진 = _엔진(설정)
    for minute, price in enumerate((99.0, 101.0, 150.0, 150.0, 150.0)):
        _넣기(엔진, minute, price)
        if minute == 2:
            # 1단계가 1분 봉(101)에서 채워졌습니다. 남은 봉 하나(2분 봉)입니다.
            줄 = _규칙줄(엔진)
            assert (줄["waitingStep"], 줄["barsLeft"]) == (2, 1)
        if minute == 3:
            # 2분 봉(150)이 창의 마지막 봉이었고 못 채웠습니다.
            줄 = _규칙줄(엔진)
            assert (줄["waitingStep"], 줄["barsLeft"], 줄["resetLeft"]) == (1, None, None)
        if minute == 4:
            assert _규칙줄(엔진)["waitingStep"] == 1


def test_남은_봉_1_이면_다음_봉에서_채울_수_있다():
    설정 = _설정()
    설정["rules"]["buyEntry"] = _두단계(window=1)
    엔진 = _엔진(설정)
    for minute, price in enumerate((99.0, 101.0, 250.0, 250.0)):
        _넣기(엔진, minute, price)

    assert _규칙줄(엔진)["fired"] is True, "남은 1봉 안에 2단계가 채워졌습니다."
    assert engine.SIGNAL in _갈래(엔진)


def test_규칙_시한도_이_봉_뒤에_남은_봉_수다():
    설정 = _설정()
    설정["rules"]["buyEntry"] = _두단계(window=5, reset=3)
    엔진 = _엔진(설정)
    for minute, price in enumerate((99.0, 101.0, 150.0)):
        _넣기(엔진, minute, price)

    줄 = _규칙줄(엔진)
    assert (줄["waitingStep"], 줄["barsLeft"], 줄["resetLeft"]) == (2, 3, 3)


# ── 1단계가 왜 안 걸렸나 ────────────────────────────────────


def test_1단계가_이미_참이면_단계_줄이_그렇게_말한다():
    엔진 = _엔진()
    for minute, price in enumerate((101.0, 102.0, 103.0, 104.0)):
        _넣기(엔진, minute, price)

    단계 = _규칙줄(엔진)["stepsDetail"][0]
    assert (단계["stepNow"], 단계["stepBefore"], 단계["beforeUnknown"]) == (True, True, False)
    assert _규칙줄(엔진)["fired"] is False


def test_모르는_연산자는_참도_거짓도_아니다():
    시리즈 = rules.Series(values={"close": [1.0, 2.0]}, length=2)

    assert rules.cond_state({"left": "close", "op": "몰라", "rightKind": "number", "right": "1"}, 시리즈, 1) is None
    assert rules.cond_state({"left": "ema20", "op": "gt", "rightKind": "number", "right": "1"}, 시리즈, 1) is None


# ── 준비 중·끊김·다른 창 ───────────────────────────────────


def test_준비_중인_봉은_표지와_모름이다():
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(_조건(left="ema20", op="gt", right="1"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 98.0)

    표 = _표(엔진)
    assert (표["state"], 표["need"], 표["have"]) == (engine.TABLE_WARMUP, 40, 1)
    줄 = _규칙줄(엔진)
    (조건,) = 줄["stepsDetail"][0]["conds"]
    assert (조건["leftValue"], 조건["rightValue"], 조건["now"], 조건["before"]) == (None, None, None, None)
    assert (줄["fired"], 줄["judged"]) == (None, False)


def test_시세가_끊긴_봉은_표지와_모름이다():
    엔진 = _엔진()
    for minute, price in enumerate((99.0, 98.0, 97.0, 96.0)):
        _넣기(엔진, minute, price)
    assert _표(엔진)["state"] == engine.TABLE_READY, "준비 봉은 찼습니다."
    엔진.on_status(False, at=_때(10, 3, 30))

    # 끊긴 채로 봉이 닫히는 자리를 곧바로 지나 봅니다.
    엔진._on_bar(엔진.bars.bars[-1], 주간, _때(10, 3, 31))

    표 = _표(엔진)
    assert 표["state"] == engine.TABLE_GAP
    (조건,) = _규칙줄(엔진)["stepsDetail"][0]["conds"]
    assert (조건["leftValue"], 조건["now"]) == (None, None)


def test_다른_창의_봉은_표를_바꾸지_않는다():
    엔진 = _엔진(session="domestic-night")
    _넣기(엔진, 0, 99.0, 주간)
    _넣기(엔진, 1, 101.0, 주간)
    _넣기(엔진, 2, 101.0, 주간)

    assert 엔진.conditions is None


# ── 이벤트 둘 ────────────────────────────────────────────────


def test_시작할_때_이미_참이면_규칙마다_한_번_알린다():
    """직전 봉이 알려져 있고 참인 갈래 — 지표·가격 조건의 흔한 경우입니다."""
    엔진 = _엔진()
    for minute, price in enumerate((101.0, 102.0, 103.0, 104.0, 105.0)):
        _넣기(엔진, minute, price)

    assert _갈래(엔진).count(engine.ALREADY_TRUE) == 1
    (한줄,) = [one for one in 엔진.events if one["kind"] == engine.ALREADY_TRUE]
    assert 한줄["text"] == engine.RULE_LABELS["buyEntry"]


def test_직전_값을_몰라도_시작할_때_이미_참이면_한_번_알린다():
    """호가·보유처럼 실행이 적는 값은 실행 전의 봉에 없습니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(_조건(left="positionQty", op="eq", right="0"))
    엔진 = _엔진(설정)
    엔진.seed(
        [
            {"time": _때(9, 58), "open": 99.0, "high": 99.0, "low": 99.0, "close": 99.0, "volume": 1},
            {"time": _때(9, 59), "open": 99.0, "high": 99.0, "low": 99.0, "close": 99.0, "volume": 1},
        ],
        주간,
    )
    for minute, price in enumerate((99.0, 99.0, 99.0)):
        _넣기(엔진, minute, price)

    단계 = [one for one in _표(엔진)["rules"] if one["rule"] == "buyEntry"][0]["stepsDetail"][0]
    assert 단계["stepNow"] is True
    assert _갈래(엔진).count(engine.ALREADY_TRUE) == 1


def test_안_낸_신호는_한_봉에_한_줄이고_날이_바뀌면_0_이다():
    엔진 = _엔진(_설정(maxHold="0"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.5)  # 1분 봉이 걸리지만 최대 보유 0 이라 안 냅니다.

    막힘 = [one for one in 엔진.events if one["kind"] == engine.BLOCKED]
    assert len(막힘) == 1 and runs.WHY_MAX_HOLD in 막힘[0]["text"]
    assert _규칙줄(엔진)["fired"] is True
    assert 엔진.unsent_today(_때(10, 5)) == 1
    assert 엔진.unsent_today(_때(10, 5, day=18)) == 0, "다음 날은 0 부터입니다."
    assert 엔진.snapshot()["run"]["unsentToday"] in (0, 1), "줄에도 오늘 수가 실립니다."


def test_손절이_막혀도_안_낸_신호_수에는_안_든다():
    """「안 낸 신호」는 규칙이 걸렸는데 안 낸 것입니다. 손절·익절의 막힘은 이벤트만 남깁니다."""
    from backend.strategy import paper, sim

    class _안받는곳:
        def order(self, **물음):
            raise AssertionError("승인이 없어 보내기 전에 막혀야 합니다.")

    엔진 = _엔진(mode=runs.SIM, environment="paper", approved_at=0)
    엔진.book = sim.SimBroker(엔진.run, sender=_안받는곳(), environment=lambda: "paper")
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": _때(10, 0)})

    엔진._close(1, 99.0, engine.STOP_LOSS, _때(10, 0, 5))

    assert _갈래(엔진).count(engine.BLOCKED) == 1, "막힘 이벤트는 그대로 남습니다."
    assert 엔진.unsent_today(_때(10, 0, 5)) == 0
