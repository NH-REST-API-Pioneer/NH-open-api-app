"""세션 끝 정리·신규 진입 시간·청산 뒤 대기·하루 최대 진입·손절 단위.

**계좌에 닿지 않습니다.** 봉·호가·체결을 손으로 지어 넣고, 세션 판정과 보내는 곳은
가짜로 끼웁니다. 칸을 비워 둔 옛 전략은 앞 판과 같게 돕니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, journal as journal_lib, paper, pump as pump_lib, runs, sim, validate
from backend.strategy import service as service_lib
from backend.strategy.indicators import Bar
from tests.test_strategy_engine import _때, _설정, _엔진, _넣기, _줄서는_엔진

주간 = "domestic-day"
야간 = "domestic-night"


def _보유한(**aux) -> engine.RunEngine:
    """평균가 100 에 1계약 들고 있는 엔진. 틱은 0.05 입니다."""
    엔진 = _엔진(_설정(**aux))
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    return 엔진


def _닿나(엔진: engine.RunEngine, price: float) -> str:
    """마지막 체결가가 `price` 일 때 나간 청산의 까닭. 안 나갔으면 빈 글자입니다."""
    엔진._exit_reason = ""
    엔진.book.last_price = price
    엔진._watch(_때(10, 5))
    return 엔진._exit_reason


def _매도보유(**aux) -> engine.RunEngine:
    엔진 = _엔진(_설정(**aux))
    엔진.ledger.add({"side": paper.SELL, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    return 엔진


# ── 단위 ──────────────────────────────────────────────────


def test_틱_단위는_앞_판과_같은_셈이다():
    """단위 칸이 없으면 틱이고, 거리는 틱 수 × 틱입니다."""
    엔진 = _보유한(stopTicks="2", takeTicks="3")

    assert 엔진._distance("stopTicks", "stopUnit", 100.0) == pytest.approx(0.1)
    assert _닿나(_보유한(stopTicks="2", takeTicks="3"), 99.95) == ""
    assert _닿나(_보유한(stopTicks="2", takeTicks="3"), 99.9) == engine.STOP_LOSS
    assert _닿나(_보유한(stopTicks="2", takeTicks="3"), 100.15) == engine.TAKE_PROFIT


@pytest.mark.parametrize(
    ("unit", "value", "안닿음", "닿음"),
    [
        ("price", "0.5", 99.55, 99.5),
        ("pct", "1", 99.05, 99.0),
    ],
)
def test_매수_손절은_단위의_거리만큼_아래에서_닫는다(unit, value, 안닿음, 닿음):
    aux = {"stopTicks": value, "stopUnit": unit, "takeTicks": "100"}

    assert _닿나(_보유한(**aux), 안닿음) == ""
    assert _닿나(_보유한(**aux), 닿음) == engine.STOP_LOSS


@pytest.mark.parametrize(("unit", "value", "안닿음", "닿음"), [("price", "0.5", 100.45, 100.5), ("pct", "1", 100.95, 101.0)])
def test_매도_손절은_단위의_거리만큼_위에서_닫는다(unit, value, 안닿음, 닿음):
    aux = {"stopTicks": value, "stopUnit": unit, "takeTicks": "100"}

    assert _닿나(_매도보유(**aux), 안닿음) == ""
    assert _닿나(_매도보유(**aux), 닿음) == engine.STOP_LOSS


def test_익절도_단위를_따른다():
    aux = {"stopTicks": "100", "takeTicks": "2", "takeUnit": "pct"}

    assert _닿나(_보유한(**aux), 101.95) == ""
    assert _닿나(_보유한(**aux), 102.0) == engine.TAKE_PROFIT


def test_ATR_단위는_마지막_판정_봉의_ATR_배수다():
    aux = {"stopTicks": "1.5", "stopUnit": "atr", "takeTicks": "100"}
    엔진 = _보유한(**aux)
    엔진._atr = 2.0

    assert 엔진._distance("stopTicks", "stopUnit", 100.0) == pytest.approx(3.0)
    엔진._exit_reason = ""
    엔진.book.last_price = 97.05
    엔진._watch(_때(10, 5))
    assert 엔진._exit_reason == ""
    엔진.book.last_price = 97.0
    엔진._watch(_때(10, 5))
    assert 엔진._exit_reason == engine.STOP_LOSS


def test_ATR_단위는_ATR_이_서기_전에는_진입을_막는다():
    엔진 = _엔진(_설정(stopTicks="1", stopUnit="atr"))

    assert 엔진.warmup >= 28, "ATR(14) 의 준비 봉을 함께 기다립니다."
    bar = Bar(_때(10, 0), 1, 1, 1, 1, 1)
    assert 엔진._entry_gate(bar) == runs.WHY_ATR_NOT_READY
    엔진._atr = 1.0
    assert 엔진._entry_gate(bar) is None


def test_추적_청산의_퍼센트는_가장_유리했던_값의_퍼센트다():
    aux = {"stopTicks": "100", "takeTicks": "1000", "trailTicks": "1", "trailUnit": "pct"}
    엔진 = _보유한(**aux)
    엔진.book.last_price = 110.0
    엔진._watch(_때(10, 5))  # 가장 유리했던 값 110
    엔진._exit_reason = ""

    엔진.book.last_price = 108.95
    엔진._watch(_때(10, 6))
    assert 엔진._exit_reason == "", "선(108.9)에 아직 안 닿았습니다."

    엔진.book.last_price = 108.9
    엔진._watch(_때(10, 7))
    assert 엔진._exit_reason == engine.TRAIL_STOP, "110 의 1% 인 1.1 되돌면 닫습니다."


# ── 세션 끝 정리 ───────────────────────────────────────────


def test_세션_끝_정리는_보유를_닫고_한_번만_하고_끝까지_진입을_막는다():
    엔진 = _보유한()
    엔진.book.last_price = 100.0
    끝 = _때(15, 35)

    assert 엔진.session_end(_때(15, 25), 끝) is True
    assert 엔진._exit_reason == engine.SESSION_END
    assert 엔진.session_end(_때(15, 26), 끝) is False, "같은 세션에 두 번 하지 않습니다."
    assert 엔진._entry_gate(Bar(_때(15, 30), 1, 1, 1, 1, 1)) == runs.WHY_SESSION_END
    assert 엔진._entry_gate(Bar(_때(15, 35), 1, 1, 1, 1, 1)) is None


def test_세션_끝_정리는_진입_미체결을_거둔다():
    엔진 = _줄서는_엔진()
    assert 엔진.book.open_orders

    엔진.session_end(_때(10, 3), _때(10, 30))

    assert 엔진.book.open_orders == []
    assert 엔진.run.state == runs.ARMED


def test_계좌_갈래의_세션_끝_청산이_막히면_확인_필요다():
    class _안받는곳:
        def order(self, **물음):
            raise AssertionError("승인이 없어 보내기 전에 막혀야 합니다.")

    엔진 = _엔진(mode=runs.SIM, environment="paper", approved_at=0)
    엔진.book = sim.SimBroker(엔진.run, sender=_안받는곳(), environment=lambda: "paper")
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING

    엔진.session_end(_때(15, 25), _때(15, 35))

    assert 엔진.run.state == runs.ATTENTION


class _적는곳:
    """주문·취소를 적기만 하는 자리. 계좌에 닿지 않습니다. 주문번호는 차례로 매깁니다."""

    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.cancelled: list[str] = []

    def order(self, **물음):
        self.orders.append(물음)
        return {"id": f"{len(self.orders):010d}"}

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": order.order_no}


def _계좌엔진(**aux) -> tuple[engine.RunEngine, _적는곳]:
    보냄 = _적는곳()
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=10_000_000.0, multiplier=1.0,
        draft=_설정(orderType="지정가", **aux), mode=runs.SIM, approved_at=1_000, environment="paper",
    )
    엔진 = engine.RunEngine(run, tick=0.05, book=sim.SimBroker(run, sender=보냄, environment=lambda: "paper"))
    return 엔진, 보냄


def _정리_알림(엔진: engine.RunEngine) -> int:
    return sum(1 for one in 엔진.events if one["kind"] == engine.SESSION and "세션 끝 정리" in one["text"])


def test_정리_뒤_늦게_채워진_진입은_다음_박자에_닫는다():
    엔진, 보냄 = _계좌엔진()
    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)
    (진입,) = 엔진.book.open_orders
    assert 엔진.run.state == runs.ENTERING
    끝 = _때(15, 35)

    엔진.session_end(_때(15, 25), 끝)
    assert 보냄.cancelled == [진입.order_no], "진입 미체결에 취소를 냈습니다."
    assert 엔진.run.state == runs.ENTERING, "계좌 확인 전에는 내려놓지 않습니다."

    # 취소가 닿기 전에 채워졌습니다.
    엔진.on_order({"id": 진입.order_no, "status": "filled", "filled": 1, "fillPrice": 101.0}, at=_때(15, 25, 1))
    assert 엔진.run.state == runs.HOLDING and 엔진.ledger.position.side == paper.BUY

    assert 엔진.session_end(_때(15, 25, 2), 끝) is True
    assert len(보냄.orders) == 2 and 엔진._exit_reason == engine.SESSION_END
    assert 엔진.run.state == runs.EXITING
    assert _정리_알림(엔진) == 1, "취소·알림은 세션마다 한 번입니다."


def test_정리_뒤_취소가_확인되면_진입_대기로_돌아간다():
    엔진, 보냄 = _계좌엔진()
    for minute, price in enumerate((99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)
    (진입,) = 엔진.book.open_orders
    끝 = _때(15, 35)

    엔진.session_end(_때(15, 25), 끝)
    엔진.on_order({"id": 진입.order_no, "status": "cancelled", "filled": 0}, at=_때(15, 25, 1))

    assert 엔진.run.state == runs.ARMED
    assert 엔진.session_end(_때(15, 25, 2), 끝) is False, "보유도 거둘 것도 없으면 할 일이 없습니다."
    assert len(보냄.orders) == 1


def test_청산이_나가_있는_동안은_다시_내지_않고_거절되면_확인_필요다():
    """청산이 계좌에서 거절되면 같은 청산을 다시 내지 않고 사용자를 기다립니다.

    다시 내면 같은 까닭으로 같은 거절이 되풀이됩니다(접수 자리의 청산 거부와 같은 규칙).
    """
    엔진, 보냄 = _계좌엔진()
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    엔진.book.last_price = 100.0
    끝 = _때(15, 35)

    엔진.session_end(_때(15, 25), 끝)
    엔진.session_end(_때(15, 25, 1), 끝)
    엔진.session_end(_때(15, 25, 2), 끝)
    assert len(보냄.orders) == 1, "청산이 나가 있는 동안 두 번 내지 않습니다."
    assert 엔진.run.state == runs.EXITING

    (청산,) = 엔진.book.open_orders
    엔진.on_order({"id": 청산.order_no, "status": "rejected", "filled": 0}, at=_때(15, 25, 3))
    assert 엔진.run.state == runs.ATTENTION

    엔진.session_end(_때(15, 25, 4), 끝)
    assert len(보냄.orders) == 1, "확인 필요 동안에는 청산을 다시 내지 않습니다."
    assert _정리_알림(엔진) == 1


def test_종이_갈래는_정리_뒤_생긴_보유도_닫는다():
    엔진 = _엔진(_설정())
    엔진.book.last_price = 100.0
    끝 = _때(15, 35)
    assert 엔진.session_end(_때(15, 25), 끝) is True

    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.run.state = runs.HOLDING
    assert 엔진.session_end(_때(15, 26), 끝) is True
    assert 엔진._exit_reason == engine.SESSION_END and 엔진.run.state == runs.EXITING
    assert 엔진.session_end(_때(15, 27), 끝) is False, "청산이 나가 있는 동안 두 번 내지 않습니다."
    assert len(엔진.book.open_orders) == 1
    assert _정리_알림(엔진) == 1


def test_펌프는_끝_N분_전_창에서만_세션_끝_정리를_부른다(tmp_path):
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(
        run_id="r1", version_id="v1", draft=_설정(sessionEndFlat=True, sessionEndMinutes="10"),
        market="domestic", code="A7569000", session=주간, qty=1, cash=1.0,
    )
    끝 = _때(15, 35)
    부름: list[int] = []
    엔진 = 실행목록._engine("r1")
    엔진.session_end = lambda at, until: 부름.append(at) or True
    돌리는것 = pump_lib.RunPump(
        실행목록, hub=None, judge=lambda *a: True, closing=lambda *a: 끝, replaying=lambda: False
    )

    돌리는것._session_ends(_때(15, 24))
    돌리는것._session_ends(_때(15, 25))
    돌리는것._session_ends(_때(15, 35))

    assert 부름 == [_때(15, 25)], "끝 10분 전부터 끝 전까지만 부릅니다."


# ── 신규 진입 시간 ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("base", "start", "end", "hour", "minute", "안"),
    [
        # 1분봉: 08:59 봉은 09:00 에 닫힙니다.
        ("1분봉", "09:00", "14:30", 8, 59, True),  # 시작 포함
        ("1분봉", "09:00", "14:30", 8, 58, False),
        ("1분봉", "09:00", "14:30", 14, 28, True),
        ("1분봉", "09:00", "14:30", 14, 29, False),  # 14:30 에 닫힘 — 끝 제외
        ("1분봉", "09:00", "", 15, 0, True),  # 끝을 비우면 세션 끝까지
        ("1분봉", "", "10:00", 9, 0, True),
        # 15분봉: 08:45 봉은 09:00 에 닫혀 들어갑니다.
        ("15분봉", "09:00", "14:30", 8, 45, True),
        ("15분봉", "09:00", "14:30", 8, 30, False),
        # 60분봉: 14:00 봉은 15:00 에 닫힙니다 — 봉 시작이 창 안이어도 주문은 창 밖입니다.
        ("60분봉", "09:00", "14:30", 13, 0, True),
        ("60분봉", "09:00", "14:30", 14, 0, False),
        ("60분봉", "09:00", "15:00", 14, 0, False),  # 15:00 에 닫힘 — 끝 제외
        ("60분봉", "09:00", "15:01", 14, 0, True),
        ("60분봉", "09:00", "14:30", 8, 0, True),  # 09:00 에 닫힘 — 시작 포함
    ],
)
def test_신규_진입_시간은_봉이_닫히는_시각으로_본다(base, start, end, hour, minute, 안):
    엔진 = _엔진({**_설정(entryStart=start, entryEnd=end), "baseBar": base})

    assert 엔진._in_window(Bar(_때(hour, minute), 1, 1, 1, 1, 1)) is 안


def test_일봉은_판정하는_순간으로_본다():
    엔진 = _엔진({**_설정(entryStart="09:00", entryEnd="14:30"), "baseBar": "일봉"})
    봉 = Bar(_때(0, 0), 1, 1, 1, 1, 1)

    엔진.last_trade_at = _때(14, 29)
    assert 엔진._in_window(봉) is True
    엔진.last_trade_at = _때(14, 30)
    assert 엔진._in_window(봉) is False


def test_야간_신규_진입_시간은_자정을_넘어_잇는다():
    엔진 = _엔진(_설정(entryStart="22:00", entryEnd="02:00"), session=야간)

    assert 엔진._in_window(Bar(_때(21, 59), 1, 1, 1, 1, 1)) is True  # 22:00 에 닫힘
    assert 엔진._in_window(Bar(_때(23, 0), 1, 1, 1, 1, 1)) is True
    assert 엔진._in_window(Bar(_때(1, 58, day=18), 1, 1, 1, 1, 1)) is True
    assert 엔진._in_window(Bar(_때(1, 59, day=18), 1, 1, 1, 1, 1)) is False  # 02:00 에 닫힘
    assert 엔진._in_window(Bar(_때(21, 58), 1, 1, 1, 1, 1)) is False


def test_끝이_시작보다_이르면_다음_날까지다():
    엔진 = _엔진(_설정(entryStart="14:00", entryEnd="09:30"))

    assert 엔진._in_window(Bar(_때(15, 0), 1, 1, 1, 1, 1)) is True
    assert 엔진._in_window(Bar(_때(9, 0), 1, 1, 1, 1, 1)) is True
    assert 엔진._in_window(Bar(_때(11, 0), 1, 1, 1, 1, 1)) is False


def test_신규_진입_시간_밖이면_막고_까닭을_적는다():
    엔진 = _엔진(_설정(entryStart="09:00", entryEnd="09:30"))
    for minute, price in enumerate((99.0, 101.0, 101.5)):
        _넣기(엔진, minute, price)  # 10:01 봉에서 걸립니다.

    막힘 = [one["text"] for one in 엔진.events if one["kind"] == engine.BLOCKED]
    assert 막힘 and runs.WHY_ENTRY_WINDOW in 막힘[0]


# ── 청산 뒤 대기·하루 최대 ──────────────────────────────────


def test_보유가_0이_되면_대기_봉을_세운다():
    엔진 = _보유한(reentryWaitBars="2")
    엔진._take([{"orderId": "x", "side": paper.SELL, "quantity": 1, "price": 101.0, "time": 2}], 2)

    assert 엔진._wait_left == 2
    assert 엔진._entry_gate(Bar(_때(10, 0), 1, 1, 1, 1, 1)) == runs.WHY_REENTRY_WAIT


def test_대기는_판정_봉마다_하나씩_줄어든다():
    엔진 = _엔진()
    엔진._wait_left = 2
    for minute, price in enumerate((90.0, 91.0, 92.0, 93.0)):
        _넣기(엔진, minute, price)  # 판정 봉 둘(1분·2분 봉)

    assert 엔진._wait_left == 0


def test_하루_최대_진입에_닿으면_막는다():
    엔진 = _엔진(_설정(maxEntriesPerDay="2"))
    엔진.run.intents_today = 2

    assert 엔진._entry_gate(Bar(_때(10, 0), 1, 1, 1, 1, 1)) == runs.WHY_DAILY_ENTRIES
    엔진.run.intents_today = 1
    assert 엔진._entry_gate(Bar(_때(10, 0), 1, 1, 1, 1, 1)) is None


def test_옛_전략은_실행_필터가_막지_않는다():
    엔진 = _엔진()

    assert 엔진._entry_gate(Bar(_때(3, 0), 1, 1, 1, 1, 1)) is None


# ── 검증 ─────────────────────────────────────────────────────


def _문제(**aux) -> list[str]:
    return [one["message"] for one in validate.problems(_설정(**aux), market="domestic")]


@pytest.mark.parametrize(
    ("aux", "말"),
    [
        ({"stopTicks": "1000"}, None),
        ({"stopTicks": "1001"}, validate._TICK_RANGE),
        ({"stopTicks": "0.5", "stopUnit": "price"}, None),
        ({"stopTicks": "0", "stopUnit": "price"}, validate._POSITIVE_NUMBER),
        ({"stopTicks": "0.1", "stopUnit": "pct"}, None),
        ({"stopTicks": "50.1", "stopUnit": "pct"}, validate._PCT_RANGE),
        ({"stopTicks": "1.25", "stopUnit": "pct"}, validate._PCT_RANGE),
        ({"stopTicks": "0.5", "stopUnit": "atr"}, None),
        ({"stopTicks": "10.5", "stopUnit": "atr"}, validate._ATR_RANGE),
        ({"stopUnit": "몰라"}, validate._UNIT),
        ({"sessionEndFlat": True, "sessionEndMinutes": "60"}, None),
        ({"sessionEndFlat": True, "sessionEndMinutes": "61"}, validate._SESSION_END_MINUTES),
        ({"sessionEndFlat": True}, validate._SESSION_END_MINUTES),
        ({"entryStart": "09:00", "entryEnd": "09:00"}, validate._WINDOW_SAME),
        ({"entryStart": "9시"}, validate._CLOCK_FORMAT),
        ({"reentryWaitBars": "0"}, None),
        ({"reentryWaitBars": "51"}, validate._WAIT_RANGE),
        ({"maxEntriesPerDay": "20"}, None),
        ({"maxEntriesPerDay": "21"}, validate._MAX_ENTRIES),
    ],
)
def test_실행_필터와_단위의_범위(aux, 말):
    assert _문제(**aux) == ([] if 말 is None else [말])


def test_단위_목록은_엔진과_같다():
    assert validate.EXIT_UNITS == engine.UNITS


def test_옛_전략은_검증을_그대로_지난다():
    assert _문제() == []


def test_세션_밖_진입_시간은_실행을_세울_때_막는다(tmp_path):
    from backend.sessions import judge as judge_lib

    def 판정(market, code, moment):
        # 08:45~15:45 주간만 열려 있다고 답합니다.
        inside = (8, 45) <= (moment.hour, moment.minute) < (15, 45)
        return {"source": "api", "state": "day" if inside else judge_lib.CLOSED, "session": "day" if inside else None}

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
        judged=판정,
    )

    def 문제(start, end):
        return [
            one["field"]
            for one in 실행목록.start_problems(
                draft=_설정(entryStart=start, entryEnd=end), market="domestic", code="A7569000",
                session=주간, qty=1, cash=1.0, fee_per_contract=0.0,
            )
        ]

    assert 문제("09:00", "15:45") == [], "끝은 구간에서 빠지므로 1분 앞이 세션 안이면 됩니다."
    assert 문제("08:00", "15:00") == ["aux.entryStart"]
    assert 문제("09:00", "16:00") == ["aux.entryEnd"]


def test_주말에_세워도_다음_거래일의_세션으로_본다(tmp_path, monkeypatch):
    from datetime import datetime

    from backend.sessions import judge as judge_lib
    from backend.sessions.hours import KST

    # 토요일 아침에 세웁니다. 주말에는 판정이 늘 닫힘입니다.
    monkeypatch.setattr(service_lib, "now_kst", lambda: datetime(2026, 9, 19, 8, 0, tzinfo=KST))
    물은날: list[str] = []

    def 판정(market, code, moment):
        물은날.append(moment.strftime("%m-%d"))
        inside = moment.weekday() < 5 and (8, 45) <= (moment.hour, moment.minute) < (15, 45)
        return {"source": "api", "state": "day" if inside else judge_lib.CLOSED, "session": "day" if inside else None}

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
        judged=판정,
    )

    def 문제(start, end):
        return [
            one["field"]
            for one in 실행목록.start_problems(
                draft=_설정(entryStart=start, entryEnd=end), market="domestic", code="A7569000",
                session=주간, qty=1, cash=1.0, fee_per_contract=0.0,
            )
        ]

    assert 문제("09:00", "14:30") == [], "월요일의 세션으로 봅니다."
    assert "09-21" in 물은날, "토·일을 넘겨 월요일까지 물었습니다."
    assert 문제("08:00", "14:30") == ["aux.entryStart"], "어느 날에도 세션 밖이면 막습니다."


def test_시간표를_모르면_첫_날에_그치고_막지_않는다(tmp_path):
    from backend.sessions import judge as judge_lib

    물음: list[int] = []

    def 판정(market, code, moment):
        물음.append(1)
        return {"source": judge_lib.UNKNOWN, "state": judge_lib.UNKNOWN, "session": None}

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
        judged=판정,
    )
    문제 = 실행목록.start_problems(
        draft=_설정(entryStart="03:00", entryEnd="04:00"), market="domestic", code="A7569000",
        session=주간, qty=1, cash=1.0, fee_per_contract=0.0,
    )

    assert [one["field"] for one in 문제 if one["field"].startswith("aux.entry")] == []
    assert len(물음) == 2, "시작·끝 시각마다 첫 날 한 번만 묻습니다."
