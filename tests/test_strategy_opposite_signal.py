"""보유 중 반대 방향 진입 규칙 — 무시·청산·반전(`aux.oppositeSignal`).

**계좌에 닿지 않습니다.** 계좌 갈래는 받아 적기만 하는 가짜 자리로 보내고 체결은
계좌 알림 모양으로 손으로 넣습니다. 종이 장부는 체결·호가를 손으로 넣고, 지난 봉
돌려 보기는 봉을 지어 넣습니다.
"""
from __future__ import annotations

import pytest

from backend.nh_api.errors import BusinessError
from backend.strategy import engine, paper, runs, sim, validate
from backend.strategy.indicators import Bar
from tests.test_strategy_backtest import _봉, _셈, _평평
from tests.test_strategy_engine import _규칙, _때, _설정, _조건, _호가, 지연

주간 = "domestic-day"


class _보내는곳:
    """주문을 받아 적기만 하는 자리. 주문번호를 차례로 매깁니다.

    `거부` 에 몇 번째 주문인지(1 부터)를 적어 두면 그 주문은 계좌가 거부합니다.
    거부된 주문은 `sent` 에 남지 않습니다.
    """

    def __init__(self):
        self.sent: list[dict] = []
        self.cancelled: list[str] = []
        self.거부: set[int] = set()
        self.부름 = 0

    def order(self, **물음):
        self.부름 += 1
        if self.부름 in self.거부:
            raise BusinessError("domestic_order", "5039", "처리불가", {})
        self.sent.append(물음)
        return {"id": f"{len(self.sent):010d}"}

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": order.order_no}


def _양쪽(**aux) -> dict:
    """매수 진입(종가 > 100)·매도 진입(종가 < 99)이 둘 다 켜진 설정. 손절·익절은 끕니다."""
    설정 = _설정(stopTicks="", takeTicks="", **aux)
    설정["rules"]["sellEntry"] = _규칙(_조건(op="lt", right="99"))
    return 설정


def _계좌엔진(qty: int = 1, **aux) -> tuple[engine.RunEngine, _보내는곳]:
    보낸곳 = _보내는곳()
    run = runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.ARMED, qty=qty, cash=10_000_000.0, multiplier=1.0, draft=_양쪽(**aux),
        mode=runs.SIM, approved_at=1, environment="paper",
    )
    book = sim.SimBroker(run, sender=보낸곳, environment=lambda: "paper", tick=0.05)
    return engine.RunEngine(run, tick=0.05, book=book), 보낸곳


def _채움(엔진, 보낸곳, *, filled: int, price: float, at: int, status: str = "filled", nth: int = -1) -> None:
    """보낸 주문 하나에 계좌의 체결 알림을 넣습니다. `filled` 는 누적입니다."""
    번호 = f"{len(보낸곳.sent) + nth + 1:010d}"
    주문 = next(one for one in 엔진.book.orders if one.order_no == 번호)
    엔진.on_order(
        {"id": 번호, "status": status, "filled": filled, "remaining": 주문.quantity - filled, "fillPrice": price},
        at=at,
    )


def _매수보유(엔진, 보낸곳, qty: int = 1) -> None:
    엔진._send(paper.BUY, qty, 101.0, "entry", _때(10, 1))
    _채움(엔진, 보낸곳, filled=qty, price=101.0, at=_때(10, 1, 1))
    assert 엔진.run.state == runs.HOLDING and 엔진.ledger.position.side == paper.BUY


def _걸림(엔진, key: str = "sellEntry", minute: int = 5, price: float = 98.0) -> None:
    """그 진입 규칙 하나가 참인 봉 마감. 다른 규칙은 거짓입니다."""
    봉 = Bar(_때(10, minute), price, price, price, price, 1)
    엔진._entry_rules(봉, _때(10, minute + 1), {key: (None, True)}, set())


def _말(엔진, kind: str) -> list[str]:
    return [one["text"] for one in 엔진.events if one["kind"] == kind]


def _막힘(엔진) -> list[str]:
    return [one["why"] for one in 엔진.events if one["kind"] == engine.BLOCKED]


# ── 설정 칸 ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("값", "읽음"),
    [
        (None, "ignore"), ("", "ignore"), ("ignore", "ignore"), ("exit", "exit"),
        ("reverse", "reverse"), (" reverse ", "reverse"), ("flip", "ignore"), (1, "ignore"),
    ],
)
def test_칸이_없거나_모르는_값은_무시로_읽는다(값, 읽음):
    aux = {} if 값 is None else {"oppositeSignal": 값}
    assert validate.opposite_signal(aux) == 읽음
    assert validate.opposite_signal(None) == "ignore"


def _검사(값) -> list[tuple[str, str]]:
    설정 = _설정()
    설정["rules"]["sellEntry"] = _규칙(_조건(op="lt", right="99"))
    if 값 is not None:
        설정["aux"]["oppositeSignal"] = 값
    return [
        (one["field"], one["message"])
        for one in validate.problems(설정, market="domestic")
        if one["severity"] == validate.ERROR
    ]


@pytest.mark.parametrize("값", [None, "", "ignore", "exit", "reverse"])
def test_허용값과_빈칸은_통과한다(값):
    assert _검사(값) == []


@pytest.mark.parametrize("값", ["flip", "EXIT", 1, True, ["exit"]])
def test_모르는_값은_그_칸을_짚는다(값):
    assert _검사(값) == [("aux.oppositeSignal", validate._OPPOSITE_SIGNAL)]


def test_담기_전에_앞뒤_빈칸을_덜어_낸다():
    설정 = _양쪽(oppositeSignal=" exit ")
    made = validate.normalized({"market": "domestic"}, 설정)
    assert made["aux"]["oppositeSignal"] == "exit"
    assert 설정["aux"]["oppositeSignal"] == " exit ", "받은 설정은 그대로 둡니다."


# ── 무시 ──────────────────────────────────────────────


@pytest.mark.parametrize("aux", [{}, {"oppositeSignal": "ignore"}, {"oppositeSignal": "flip"}])
def test_옛_설정과_무시는_지금처럼_안_낸_신호로_남는다(aux):
    엔진, 보낸곳 = _계좌엔진(**aux)
    _매수보유(엔진, 보낸곳)

    _걸림(엔진)

    assert len(보낸곳.sent) == 1, "진입 하나뿐입니다."
    assert _막힘(엔진) == [runs.WHY_OPPOSITE]
    assert 엔진.run.state == runs.HOLDING


# ── 청산 ──────────────────────────────────────────────


def test_청산은_보유_전량을_버전의_주문유형으로_닫고_들어가지_않는다():
    엔진, 보낸곳 = _계좌엔진(qty=2, oppositeSignal="exit", orderType="지정가", fillCond="FOK")
    _매수보유(엔진, 보낸곳, qty=2)

    _걸림(엔진)

    (청산,) = 보낸곳.sent[1:]
    assert (청산["side"], 청산["quantity"]) == (paper.SELL, 2)
    assert (청산["order_type"], 청산["price"], 청산["fill_condition"]) == ("지정가", 98.0, "FOK"), (
        "청산 규칙과 같은 길 — 버전의 주문유형·체결조건입니다."
    )
    assert _말(엔진, engine.SIGNAL)[-1] == "매도 진입 규칙이 걸렸습니다"
    assert _말(엔진, engine.ORDER)[-1] == "sell 2계약 지정가 98"
    assert 엔진.run.state == runs.EXITING and _막힘(엔진) == []

    _채움(엔진, 보낸곳, filled=2, price=98.0, at=_때(10, 6, 1))

    assert 엔진.fills[-1]["intent"] == "exit" and 엔진.fills[-1]["reason"] == engine.OPPOSITE_EXIT == "opposite"
    assert 엔진.ledger.position.side is None and 엔진.run.state == runs.ARMED
    assert len(보낸곳.sent) == 2, "반대 방향으로는 들어가지 않습니다."


def test_청산이_나가_있으면_다시_걸려도_또_내지_않는다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="exit")
    _매수보유(엔진, 보낸곳)

    _걸림(엔진, minute=5)
    _걸림(엔진, minute=6)

    assert len(보낸곳.sent) == 2, "진입 하나와 청산 하나뿐입니다."


def test_청산은_새_진입의_한도에_막히지_않는다():
    """하루 주문 수를 다 써도 보유는 닫습니다 — 막는 것은 새 진입뿐입니다."""
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="exit")
    _매수보유(엔진, 보낸곳)
    엔진.run.intents_today = runs.DAILY_INTENTS

    _걸림(엔진)

    assert 보낸곳.sent[-1]["side"] == paper.SELL and 엔진.run.state == runs.EXITING


def test_시세가_끊긴_동안에는_닫지_않는다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="exit")
    _매수보유(엔진, 보낸곳)
    엔진.feed = engine.GAP

    _걸림(엔진)

    assert len(보낸곳.sent) == 1 and _막힘(엔진) == [runs.WHY_GAP]


# ── 반전 ──────────────────────────────────────────────


def test_반전은_청산이_다_채워진_뒤_그_체결가로_반대_방향에_들어간다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse", orderType="지정가")
    _매수보유(엔진, 보낸곳)

    _걸림(엔진)
    assert len(보낸곳.sent) == 2, "다 닫히기 전에는 들어가지 않습니다."

    _채움(엔진, 보낸곳, filled=1, price=97.9, at=_때(10, 6, 1))

    진입 = 보낸곳.sent[-1]
    assert len(보낸곳.sent) == 3
    assert (진입["side"], 진입["quantity"], 진입["price"]) == (paper.SELL, 1, 97.9), "가격 기준은 청산 체결가입니다."
    assert 엔진.run.state == runs.ENTERING and 엔진.run.intents_today == 1, "반전의 진입도 의도 하나로 셉니다"
    assert 엔진._reverse is None and _막힘(엔진) == []


def test_반전은_일부만_채워지면_들어가지_않고_한_줄을_남긴다():
    엔진, 보낸곳 = _계좌엔진(qty=2, oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳, qty=2)
    _걸림(엔진)

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1), status="cancelled")

    assert len(보낸곳.sent) == 2
    assert 엔진.ledger.position.size == 1 and 엔진.run.state == runs.HOLDING
    assert _막힘(엔진) == [engine.WHY_REVERSE_DROPPED]
    assert 엔진.events[-1]["reason"] == "reverse-dropped"


def test_반전은_청산이_나눠_채워져도_마지막_체결로_다_닫히면_들어간다():
    엔진, 보낸곳 = _계좌엔진(qty=2, oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳, qty=2)
    _걸림(엔진)

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1), status="partial")
    assert len(보낸곳.sent) == 2 and 엔진.ledger.position.size == 1, "아직 다 닫히지 않았습니다."

    _채움(엔진, 보낸곳, filled=2, price=97.8, at=_때(10, 7, 1))

    진입 = 보낸곳.sent[-1]
    assert len(보낸곳.sent) == 3
    assert (진입["side"], 진입["quantity"]) == (paper.SELL, 2)
    assert 엔진._reverse is None and _막힘(엔진) == []


def test_반전_예약은_사용자_청산이_먼저_닫으면_버린다():
    """반대 신호의 지정가 청산이 나가 있는 동안 사용자가 청산하면, 시장가가 먼저 다
    닫고 남은 지정가가 나중에 취소됩니다. 그 취소에 반전 진입이 붙으면 안 됩니다."""
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse", orderType="지정가")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)
    assert len(보낸곳.sent) == 2 and 엔진._reverse is not None

    엔진.book.last_price = 98.0
    엔진._close(1, 98.0, engine.FLATTEN, _때(10, 6))  # 사용자 청산과 같은 호출
    assert len(보낸곳.sent) == 3
    assert 엔진._reverse is None and _막힘(엔진) == [engine.WHY_REVERSE_DROPPED]

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1))
    assert 엔진.ledger.position.side is None and 엔진.run.state == runs.ARMED
    _채움(엔진, 보낸곳, filled=0, price=98.0, at=_때(10, 7), status="cancelled", nth=-2)

    assert len(보낸곳.sent) == 3, "사용자가 닫은 뒤에는 반전 진입이 나가지 않습니다."


def test_반전은_예약한_청산이_보유를_닫은_주문일_때만_들어간다():
    """예약이 남아 있어도, 보유를 0 으로 만든 체결이 다른 주문이면 들어가지 않습니다."""
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse", orderType="지정가")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)
    예약 = dict(엔진._reverse)
    엔진.book.last_price = 98.0
    엔진._close(1, 98.0, engine.FLATTEN, _때(10, 6))
    엔진._reverse = 예약  # 청산 자리의 버림을 지나쳤다고 칩니다

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1))
    _채움(엔진, 보낸곳, filled=0, price=98.0, at=_때(10, 7), status="cancelled", nth=-2)

    assert len(보낸곳.sent) == 3
    assert _막힘(엔진)[-1] == engine.WHY_REVERSE_DROPPED and 엔진._reverse is None


def test_반대_신호_청산이_거부되면_예약하지_않고_한_줄을_남긴다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    보낸곳.거부 = {2}

    _걸림(엔진)

    assert len(보낸곳.sent) == 1 and 엔진._reverse is None
    assert 엔진.run.state == runs.ATTENTION, "청산 거부는 확인 필요입니다."
    assert engine.WHY_REVERSE_DROPPED in _막힘(엔진)


def test_반전_진입이_거부되면_진입_거부와_같이_중지한다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    보낸곳.거부 = {3}
    _걸림(엔진)

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1))

    assert len(보낸곳.sent) == 2 and 보낸곳.부름 == 3, "진입을 한 번 냈고 거부됐습니다."
    assert 엔진.ledger.position.side is None and 엔진.run.state == runs.PAUSED
    assert 엔진._reverse is None
    assert any(one.get("reason") == sim.REJECTED for one in 엔진.events if one["kind"] == engine.BLOCKED)


def test_반전은_다_닫히기_전에_상태가_바뀌면_버린다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)
    엔진.run.move(runs.FLAG)

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1))

    assert len(보낸곳.sent) == 2
    assert _막힘(엔진) == [engine.WHY_REVERSE_DROPPED]


def test_반전은_다른_규칙이_걸리면_버린다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)

    _걸림(엔진, key="buyEntry", minute=6, price=101.0)
    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 7, 1))

    assert len(보낸곳.sent) == 2
    assert engine.WHY_REVERSE_DROPPED in _막힘(엔진)


def test_반전은_같은_규칙이_다시_걸려도_잇는다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진, minute=5)
    _걸림(엔진, minute=6)

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 7, 1))

    assert 보낸곳.sent[-1]["side"] == paper.SELL and len(보낸곳.sent) == 3
    assert engine.WHY_REVERSE_DROPPED not in _막힘(엔진)


def test_반전은_다_닫히기_전에_세션이_끝나면_버린다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)

    엔진.close_session(_때(15, 45))
    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(15, 46))

    assert len(보낸곳.sent) == 2
    assert _막힘(엔진) == [engine.WHY_REVERSE_DROPPED]


def test_반전의_진입도_재진입_대기를_거친다():
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse", reentryWaitBars="1")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)

    _채움(엔진, 보낸곳, filled=1, price=98.0, at=_때(10, 6, 1))

    assert len(보낸곳.sent) == 2
    assert _막힘(엔진) == [runs.WHY_REENTRY_WAIT]


# ── 일봉 미루기 ─────────────────────────────────────────


@pytest.fixture
def 미룸(monkeypatch):
    """일봉이 세션 마감에서 걸린 자리. 끄면 다음 세션입니다."""
    켬 = {"on": True}
    monkeypatch.setattr(engine.RunEngine, "_deferring", property(lambda self: 켬["on"]))
    return 켬


def test_일봉_반전은_미뤘다가_풀릴_때_닫고_다_닫히면_들어간다(미룸):
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)

    _걸림(엔진)
    assert len(보낸곳.sent) == 1 and 엔진._deferred["exit"]["reverse"] == paper.SELL
    assert _말(엔진, engine.ORDER)[-1] == engine.DEFERRED_TEXT

    미룸["on"] = False
    엔진._release(_때(10, 30))
    assert 보낸곳.sent[-1]["side"] == paper.SELL and len(보낸곳.sent) == 2

    _채움(엔진, 보낸곳, filled=1, price=97.5, at=_때(10, 30, 1))

    assert len(보낸곳.sent) == 3 and 보낸곳.sent[-1]["side"] == paper.SELL
    assert 엔진.fills[-1]["reason"] == engine.OPPOSITE_EXIT


def test_일봉_반전은_풀릴_때_보유가_이미_0_이면_진입만_낸다(미룸):
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)
    미룸["on"] = False
    엔진.ledger.add({"side": paper.SELL, "quantity": 1, "price": 99.0, "time": _때(10, 20)})
    assert 엔진.ledger.position.side is None
    엔진.run.state = runs.ARMED

    엔진._release(_때(10, 30))

    assert 보낸곳.sent[-1]["side"] == paper.SELL and len(보낸곳.sent) == 2
    assert 보낸곳.sent[-1]["quantity"] == 1 and 엔진.run.state == runs.ENTERING


def test_일봉_반전은_풀릴_때_다른_보유면_버린다(미룸):
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="reverse")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)
    미룸["on"] = False
    엔진.ledger.add({"side": paper.SELL, "quantity": 2, "price": 99.0, "time": _때(10, 20)})
    assert 엔진.ledger.position.side == paper.SELL

    엔진._release(_때(10, 30))

    assert len(보낸곳.sent) == 1
    assert _막힘(엔진) == [engine.WHY_DEFERRED_EXIT, engine.WHY_REVERSE_DROPPED]


def test_일봉_청산은_미뤘다가_반대_신호의_까닭으로_닫는다(미룸):
    엔진, 보낸곳 = _계좌엔진(oppositeSignal="exit")
    _매수보유(엔진, 보낸곳)
    _걸림(엔진)
    미룸["on"] = False

    엔진._release(_때(10, 30))
    _채움(엔진, 보낸곳, filled=1, price=97.5, at=_때(10, 30, 1))

    assert len(보낸곳.sent) == 2 and 엔진.fills[-1]["reason"] == engine.OPPOSITE_EXIT
    assert 엔진.run.state == runs.ARMED


# ── 종이 장부 ─────────────────────────────────────────


def _종이(**aux) -> engine.RunEngine:
    return engine.RunEngine(
        runs.Run(
            id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
            state=runs.ARMED, qty=1, cash=10_000_000.0, multiplier=1.0, draft=_양쪽(**aux),
        ),
        tick=0.05,
    )


def _틱(엔진, minute: int, price: float) -> None:
    때 = _때(10, minute)
    엔진.on_trade({"price": price, "quantity": 1, "timestamp": 때}, 주간, at=때)


def _종이_반대신호(엔진) -> None:
    """매수로 들어가 보유한 뒤 매도 진입 규칙이 걸리게 합니다."""
    _틱(엔진, 0, 99.0)
    _틱(엔진, 1, 101.0)
    _틱(엔진, 2, 101.0)  # 봉1(101) 마감 — 매수 진입
    엔진.on_book(_호가(101.5, 101.0), at=_때(10, 2) + 지연)
    assert 엔진.ledger.position.side == paper.BUY
    _틱(엔진, 3, 98.0)
    _틱(엔진, 4, 98.0)  # 봉3(98) 마감 — 매도 진입 규칙이 참


@pytest.mark.parametrize(
    ("방식", "보유", "체결"),
    [("ignore", paper.BUY, 1), ("exit", None, 2), ("reverse", paper.SELL, 3)],
)
def test_종이_장부도_같은_길을_탄다(방식, 보유, 체결):
    엔진 = _종이(oppositeSignal=방식)
    _종이_반대신호(엔진)

    엔진.on_book(_호가(98.5, 98.0), at=_때(10, 4) + 지연)
    엔진.on_book(_호가(98.5, 98.0), at=_때(10, 4) + 2 * 지연)

    assert 엔진.ledger.position.side == 보유
    assert len(엔진.fills) == 체결
    if 방식 != "ignore":
        assert 엔진.fills[1]["reason"] == engine.OPPOSITE_EXIT
    if 방식 == "reverse":
        assert 엔진.fills[2]["intent"] == "entry" and 엔진.fills[2]["side"] == paper.SELL


# ── 지난 봉 돌려 보기 ─────────────────────────────────────


def _돌려(방식: str | None) -> dict:
    설정 = _양쪽() if 방식 is None else _양쪽(oppositeSignal=방식)
    봉들 = _평평(2) + [
        _봉(9, 2, 99.0, 101.0, 99.0, 101.0),  # 101 마감 — 매수 진입, 09:03 시가에 체결
        _봉(9, 3, 101.0, 101.0, 98.0, 98.0),  # 98 마감 — 매도 진입 규칙이 참
        _봉(9, 4, 98.0, 98.2, 97.8, 98.0),  # 시가에 청산, 반전이면 진입
        _봉(9, 5, 98.0, 98.2, 97.8, 98.0),
        _봉(9, 6, 98.0, 98.2, 97.8, 98.0),
    ]
    return _셈(봉들, 설정)


def test_돌려_보기_옛_설정은_반대_신호로_닫지_않는다():
    답 = _돌려(None)
    assert 답["trades"] == [] and 답["fills"] == 1, "매수 보유가 그대로 남습니다."


def test_돌려_보기_청산은_반대_신호로_닫기만_한다():
    답 = _돌려("exit")
    (거래,) = 답["trades"]
    assert 거래["reason"] == engine.OPPOSITE_EXIT and 거래["side"] == paper.BUY
    assert 답["fills"] == 2


def test_돌려_보기_반전은_닫고_반대로_들어간다():
    답 = _돌려("reverse")
    assert 답["trades"][0]["reason"] == engine.OPPOSITE_EXIT
    assert 답["fills"] == 3, "청산 뒤 매도 진입이 채워집니다."
