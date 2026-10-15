"""검증 엔진 루프.

**봉과 호가를 손으로 지어 넣고 무엇이 나오는지 봅니다.** 조회도 구독도 부르지
않는 자리라 시험이 값을 다 만들어 줄 수 있습니다.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from backend.sessions.hours import KST
from backend.strategy import engine, paper, rules, runs

주간 = "domestic-day"
야간 = "domestic-night"
지연 = int(paper.DELAY_SECONDS * 1000)


def _때(hour: int, minute: int, second: int = 0, milli: int = 0, day: int = 17) -> int:
    made = datetime(2026, 9, day, hour, minute, second, tzinfo=KST)
    return int(made.timestamp() * 1000) + milli


def _조건(left="close", op="gt", right="100", kind="number") -> dict:
    return {"id": "c1", "left": left, "op": op, "rightKind": kind, "right": right}


def _규칙(*conds: dict) -> dict:
    return {"on": True, "steps": [{"id": "s1", "join": "all", "withinBars": 0, "conds": list(conds)}]}


def _설정(**aux) -> dict:
    묶음 = {
        "orderType": "시장가",
        "priceBasis": "신호가",
        "stopBasis": "",
        "fillCond": "FAS",
        "stopTicks": "2",
        "takeTicks": "3",
        "perOrder": "1",
        "maxHold": "5",
        "session": "국내 주간",
        "addWhileOpen": False,
        "dailyLoss": "300000",
        "marginBudget": "10000000",
    }
    묶음.update(aux)
    return {
        "memo": "",
        "baseBar": "1분봉",
        "evalMode": "마감",
        "rules": {
            "buyEntry": _규칙(_조건()),
            "sellEntry": {"on": False, "steps": []},
            "buyExit": {"on": False, "steps": []},
            "sellExit": {"on": False, "steps": []},
        },
        "aux": 묶음,
    }


def _엔진(draft=None, **덮어쓰기) -> engine.RunEngine:
    물음 = {
        "id": "r1",
        "version_id": "v1",
        "code": "A7569000",
        "session": 주간,
        "market": "domestic",
        "state": runs.ARMED,
        "qty": 1,
        "cash": 10_000_000.0,
        "multiplier": 1.0,
        "draft": draft if draft is not None else _설정(),
    }
    물음.update(덮어쓰기)
    return engine.RunEngine(runs.Run(**물음), tick=0.05)


def _호가(ask: float, bid: float, quantity: int = 9) -> dict:
    return {
        "asks": [{"price": ask, "quantity": quantity}],
        "bids": [{"price": bid, "quantity": quantity}],
    }


def _체결(price: float, quantity: int = 1) -> dict:
    return {"price": price, "quantity": quantity}


def _넣기(엔진: engine.RunEngine, minute: int, price: float, context: str = 주간) -> None:
    때 = _때(10, minute)
    엔진.on_trade({**_체결(price), "timestamp": 때}, context, at=때)


def _갈래(엔진: engine.RunEngine) -> list[str]:
    return [one["kind"] for one in 엔진.events]


# ── 주문 가격 ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("side", "basis", "값"),
    [
        (paper.BUY, "신호가", 400.0),
        (paper.BUY, "신호가 + 1틱", 400.05),
        (paper.BUY, "신호가 − 1틱", 399.95),
        (paper.SELL, "신호가 + 1틱", 399.95),
        (paper.SELL, "신호가 − 1틱", 400.05),
    ],
)
def test_오프셋은_공격_부호다(side, basis, 값):
    """`+1틱` 은 체결되기 쉬운 쪽입니다 — 매수는 위, 매도는 아래."""
    assert engine.order_price(400.0, side, basis, 0.05) == pytest.approx(값)


def test_격자에_안_맞으면_공격_방향으로_맞춘다():
    """반대로 맞추면 한 틱 차이로 안 채워지는 주문이 됩니다."""
    assert engine.order_price(400.03, paper.BUY, "신호가", 0.05) == pytest.approx(400.05)
    assert engine.order_price(400.03, paper.SELL, "신호가", 0.05) == pytest.approx(400.0)


# ── 한 봉 시나리오 ───────────────────────────────────────


def test_진입하고_익절까지_간다():
    """봉이 닫히며 규칙이 걸리고, 시장가로 채워지고, 익절이 틱마다 본 값에 닿습니다."""
    엔진 = _엔진()

    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)  # 봉0(종가 99) 닫힘 — 아직 준비 중
    _넣기(엔진, 2, 101.0)  # 봉1(종가 101) 닫힘 — 여기서 걸립니다

    assert engine.SIGNAL in _갈래(엔진)
    assert 엔진.run.state == runs.ENTERING

    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(101.5, 101.0), at=때)

    assert 엔진.run.state == runs.HOLDING
    assert 엔진.ledger.position.quantity == 1
    assert 엔진.ledger.position.avg_price == 101.5, "매도호가를 먹었습니다."

    # 평균가 101.5 에서 익절은 3틱 = 0.15 위인 101.65 입니다.
    엔진.on_trade({**_체결(101.6), "timestamp": 때 + 100}, 주간, at=때 + 100)
    assert 엔진.run.state == runs.HOLDING, "아직 안 닿았습니다."

    엔진.on_trade({**_체결(101.65), "timestamp": 때 + 200}, 주간, at=때 + 200)
    assert 엔진.run.state == runs.EXITING

    엔진.on_book(_호가(101.7, 101.65), at=때 + 200 + 지연)

    assert 엔진.run.state == runs.ARMED
    assert 엔진.ledger.position.quantity == 0
    (거래,) = 엔진.ledger.trades
    assert 거래["avgEntry"] == 101.5 and 거래["avgExit"] == 101.65
    assert [one["intent"] for one in 엔진.fills] == ["entry", "exit"]
    assert [one["reason"] for one in 엔진.fills] == [engine.ENTRY_REASON, engine.TAKE_PROFIT]


def test_준비_봉이_모자라면_판정하지_않는다():
    """가짜 신호를 내지 않습니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(_조건(left="ema20", op="gt", right="1"))
    엔진 = _엔진(설정)

    for minute in range(5):
        _넣기(엔진, minute, 100.0 + minute)

    assert 엔진.warmup == 40, "EMA20 은 40봉이 필요합니다."
    assert engine.READY in _갈래(엔진)
    assert engine.SIGNAL not in _갈래(엔진)
    assert _갈래(엔진).count(engine.READY) == 1, "한 번만 알립니다."


def test_다른_창의_봉은_판정하지_않는다():
    """야간으로 도는 실행은 주간 봉을 지표에만 씁니다."""
    엔진 = _엔진(session=야간)

    _넣기(엔진, 0, 99.0, 주간)
    _넣기(엔진, 1, 101.0, 주간)
    _넣기(엔진, 2, 101.0, 주간)

    assert len(엔진.bars.bars) == 2
    assert engine.SIGNAL not in _갈래(엔진)
    assert 엔진.run.state == runs.ARMED


def test_공백이면_판정도_체결도_안_한다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    엔진.on_status(False, at=_때(10, 0, 30))

    _넣기(엔진, 1, 101.0)

    공백들 = [one["text"] for one in 엔진.events if one["kind"] == engine.GAP]
    assert "데이터 공백" in 공백들[0]
    assert "다시 들어옵니다" in 공백들[1], "체결이 오면 복구입니다."
    assert 엔진.feed != engine.GAP


def test_체결이_안_와_든_공백만_끊김을_적을_수_있다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    엔진.tick_clock(_때(10, 0, int(runs.GAP_SECONDS)))
    assert 엔진.quiet_since == _때(10, 0, int(runs.GAP_SECONDS))

    엔진.note_feed_lost(_때(10, 2, 0))
    assert [one["text"] for one in 엔진.events][-1] == engine.FEED_LOST

    # 체결이 다시 오면 그 공백은 끝났습니다.
    _넣기(엔진, 3, 100.0)
    assert 엔진.quiet_since == 0
    엔진.note_feed_lost(_때(10, 4, 0))
    assert [one["text"] for one in 엔진.events].count(engine.FEED_LOST) == 1


def test_연결이_끊긴_공백에는_끊김을_따로_적지_않는다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    엔진.on_status(False, at=_때(10, 0, 30))

    엔진.note_feed_lost(_때(10, 2, 0))
    assert engine.FEED_LOST not in [one["text"] for one in 엔진.events]


def test_누적_거래량은_수만_받는다():
    엔진 = _엔진()
    엔진.on_volume(120)
    엔진.on_volume(True)
    엔진.on_volume("130")
    assert 엔진.last_volume == 120


def test_체결이_오래_없으면_공백으로_본다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)

    엔진.tick_clock(_때(10, 0, int(runs.GAP_SECONDS) - 1))
    assert engine.GAP not in _갈래(엔진)

    엔진.tick_clock(_때(10, 0, int(runs.GAP_SECONDS)))
    assert engine.GAP in _갈래(엔진)
    assert 엔진.feed == engine.GAP


def test_같은_틱에_둘_다면_손절이다():
    """어느 쪽이 먼저였는지 모르는데 좋은 쪽을 고르면 성적이 부풀어 오릅니다."""
    엔진 = _엔진(_설정(stopTicks="1", takeTicks="1"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(101.0, 101.0), at=때)
    assert 엔진.ledger.position.avg_price == 101.0

    # 손절가 100.95, 익절가 101.05 — 아래로 닿습니다.
    엔진.on_trade({**_체결(100.95), "timestamp": 때 + 10}, 주간, at=때 + 10)

    assert 엔진.fills == [] or 엔진.run.state == runs.EXITING
    마지막 = [one for one in 엔진.events if one["kind"] == engine.ORDER][-1]
    # 이벤트는 산문이라 말로 적습니다 — 값은 체결 줄이 싣습니다.
    assert engine.REASON_LABELS[engine.STOP_LOSS] in 마지막["text"]


def test_청산이_나간_봉에서는_진입을_보지_않는다():
    # 틱 감시가 먼저 걸리지 않게 손절·익절을 멀리 둡니다 — 그 차례는 아래 시험이 봅니다.
    설정 = _설정(stopTicks="1000", takeTicks="1000")
    설정["rules"]["buyExit"] = _규칙(_조건(op="gt", right="100"))
    엔진 = _엔진(설정)
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 99.0, "time": 1})
    엔진.run.state = runs.HOLDING

    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    신호 = [one["text"] for one in 엔진.events if one["kind"] == engine.SIGNAL]
    assert 신호 == ["매수 청산 규칙이 걸렸습니다"], "우리끼리 쓰는 이름은 화면에 안 섭니다."
    assert 엔진.run.state == runs.EXITING


def test_막힌_의도는_까닭을_남긴다():
    엔진 = _엔진(_설정(maxHold="0"))

    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    막힌것 = [one["text"] for one in 엔진.events if one["kind"] == engine.BLOCKED]
    assert 막힌것 == [f"{engine.UNSENT_HEAD}{runs.WHY_MAX_HOLD}"]
    assert 엔진.run.state == runs.ARMED, "의도가 안 나갔으니 상태도 그대로입니다."
    assert 엔진.run.intents_today == 0, "막힌 것은 세지 않습니다."


def test_세션이_끝나면_열린_봉을_닫고_대기_주문을_취소한다():
    """**종이 주문은 거둡니다.** 지어낸 주문이라 내보낼 곳이 없고, 거두지 않으면
    다음 세션 첫 호가에 채워져 현실에 없던 체결이 성적에 들어갑니다.
    """
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)
    assert 엔진.book.open_orders, "불리한 지정가라 줄을 섭니다."

    엔진.close_session(_때(15, 45))

    assert 엔진.book.open_orders == []
    assert 엔진.run.state == runs.ARMED
    assert _갈래(엔진)[-1] == engine.SESSION


def _모의엔진() -> engine.RunEngine:
    """모의 갈래의 엔진. **장부는 종이 장부 그대로입니다** — 세션을 닫는 자리가
    보는 것은 `virtual` 하나라, 계좌를 물리지 않고도 그 갈림을 볼 수 있습니다.
    """
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가"), mode=runs.SIM)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)
    assert 엔진.book.open_orders, "불리한 지정가라 줄을 섭니다."
    return 엔진


def test_모의_주문은_세션이_끝나도_우리가_안_거둔다():
    """그 취소는 **계좌로 나가는 요청**입니다. 장이 닫혔는지는 우리 시계로
    판정한 것이라, 그 판정이 틀리면 살아 있는 주문을 우리가 없앱니다.
    """
    엔진 = _모의엔진()

    엔진.close_session(_때(15, 45))

    assert len(엔진.book.open_orders) == 1, "우리가 거두지 않습니다."
    assert 엔진.run.state == runs.ENTERING, "나가 있는 주문을 기다리는 자리 그대로입니다."
    말들 = [one["text"] for one in 엔진.events]
    assert any("미체결 1건" in one for one in 말들), "무슨 일인지 한 줄은 남습니다."
    assert _갈래(엔진)[-1] == engine.SESSION


def test_세션을_넘긴_모의_주문이_채워지면_보유가_된다():
    """상태를 그대로 두었으니 다음 세션 체결이 제자리로 갑니다 —
    `(entering, entry-filled) → holding`.
    """
    엔진 = _모의엔진()
    엔진.close_session(_때(15, 45))

    때 = _때(9, 1, day=18)
    엔진.on_trade({**_체결(101.0), "timestamp": 때}, 주간, at=때)

    assert 엔진.ledger.position.quantity == 1
    assert 엔진.run.state == runs.HOLDING


def test_화면이_그리는_한_벌을_낸다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)

    한벌 = 엔진.snapshot()

    assert set(한벌) == {"run", "fills", "events", "curve", "trades", "openOrders", "conditions"}
    assert 한벌["run"]["model"] == paper.MODEL
    assert "paperOnly" not in 한벌["run"]
    assert 한벌["run"]["environment"] is None, "종이 실행은 선 환경이 없습니다."
    assert [one["time"] for one in 한벌["curve"]] == [_때(10, 0)]


def test_지어낸_체결에_가상_표지를_단다():
    """진행 화면의 체결과 섞이면 안 됩니다."""
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(101.5, 101.0), at=_때(10, 2) + 지연)

    (체결,) = 엔진.fills
    assert 체결["virtual"] is True and 체결["runId"] == "r1"
    assert 체결["time"] == _때(10, 2) + 지연, "체결 시각은 모형이 채운 순간입니다."


def test_세션_경계의_마지막_봉은_제_세션으로_판정한다():
    """새로 온 체결의 맥락으로 보면 야간 실행이 마지막 주간 봉을 제 봉으로 읽습니다."""
    엔진 = _엔진(session=야간)

    _넣기(엔진, 0, 99.0, 주간)
    _넣기(엔진, 1, 101.0, 주간)
    # 야간 체결이 오면서 **주간** 봉이 닫힙니다.
    _넣기(엔진, 2, 101.0, 야간)

    assert 엔진.bars.sessions == [주간, 주간]
    assert engine.SIGNAL not in _갈래(엔진), "닫힌 것은 주간 봉이라 야간 실행이 안 봅니다."
    assert 엔진.run.state == runs.ARMED


def test_제_세션_봉이_닫히면_판정한다():
    """앞 시험과 같은 흐름인데 실행이 주간이면 걸립니다."""
    엔진 = _엔진(session=주간)

    _넣기(엔진, 0, 99.0, 주간)
    _넣기(엔진, 1, 101.0, 주간)
    _넣기(엔진, 2, 101.0, 야간)

    assert engine.SIGNAL in _갈래(엔진)
    assert 엔진.run.state == runs.ENTERING


def test_STOP_진입에는_스탑_가격을_싣는다():
    """없이 보내면 영영 안 켜지는 주문이 됩니다."""
    엔진 = _엔진(_설정(orderType="STOP-M", stopBasis="신호가 + 1틱"))

    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    (주문,) = 엔진.book.orders
    assert 주문.order_type == "STOP-M"
    assert 주문.price is None, "STOP-M 은 값을 안 받습니다."
    assert 주문.stop_price == pytest.approx(101.05), "신호가 101 에서 한 틱 위입니다."
    assert 주문.armed is False, "마지막 체결가가 닿아야 켜집니다."


def test_일봉은_거래일_경계에서_하루치를_다시_연다():
    """야간과 그 다음 주간이 한 봉이고, 거래일이 바뀔 때 건수·하루 손익이 열립니다."""
    설정 = _설정()
    설정["baseBar"] = "일봉"
    엔진 = _엔진(설정, session=야간)

    엔진.on_trade({"timestamp": _때(19, 0), "price": 99.0, "quantity": 1}, 야간, at=_때(19, 0))
    엔진.on_trade(
        {"timestamp": _때(10, 0, day=18), "price": 101.0, "quantity": 1},
        주간,
        at=_때(10, 0, day=18),
    )
    assert 엔진.bars.bars == [], "아직 그 거래일이 안 끝났습니다."

    엔진.on_trade(
        {"timestamp": _때(19, 0, day=18), "price": 103.0, "quantity": 1},
        야간,
        at=_때(19, 0, day=18),
    )

    (봉,) = 엔진.bars.bars
    assert (봉.open, 봉.close) == (99.0, 101.0), "야간에 열어 다음 주간에 닫습니다."
    assert 엔진.run.day_key == _때(0, 0, day=18), "닫힌 봉의 거래일로 하루를 엽니다."


def test_일봉_실행은_다른_창의_봉도_판정한다():
    """일봉은 거래일이 단위라 창으로 가리지 않습니다."""
    설정 = _설정()
    설정["baseBar"] = "일봉"
    엔진 = _엔진(설정, session=야간)

    # 주간 체결로만 세운 일봉인데, 야간 실행도 그것을 봅니다.
    엔진.on_trade({"timestamp": _때(10, 0), "price": 99.0, "quantity": 1}, 주간, at=_때(10, 0))
    엔진.on_trade(
        {"timestamp": _때(10, 0, day=18), "price": 101.0, "quantity": 1},
        주간,
        at=_때(10, 0, day=18),
    )
    엔진.on_trade(
        {"timestamp": _때(10, 0, day=19), "price": 101.0, "quantity": 1},
        주간,
        at=_때(10, 0, day=19),
    )

    assert engine.SIGNAL in _갈래(엔진), "제 창이 아니어도 판정합니다."


# ── 모의 계좌 실행 ───────────────────────────────────────


class _거절하는장부:
    """무엇을 내든 거절하는 장부. 「확인 필요」로 가는지 봅니다."""

    def __init__(self, why: str):
        self.why = why
        self.orders: list = []
        self.last_price = None
        self.gap = False

    @property
    def open_orders(self):
        return []

    def place(self, order_id, **물음):
        from backend.strategy import sim

        raise sim.SimRefused(self.why)

    def on_trade(self, trade, *, at):
        price = trade.get("price")
        if price is not None:
            self.last_price = float(price)
        return []

    def on_book(self, book, *, at):
        return []

    def cancel(self, order, reason):
        return False

    def cancel_open(self, reason):
        return []


def test_주문을_못_내면_확인_필요로_간다():
    """상태를 안 옮기면 엔진은 다음 봉에도 같은 주문을 냅니다."""
    엔진 = _엔진()
    엔진.book = _거절하는장부(runs.WHY_NOT_APPROVED)

    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    assert 엔진.run.state == runs.ATTENTION
    막힌것 = [one["text"] for one in 엔진.events if one["kind"] == engine.BLOCKED]
    assert 막힌것 == [f"{engine.UNSENT_HEAD}{runs.WHY_NOT_APPROVED}"]


def test_확인_필요에서는_더_판정하지_않는다():
    엔진 = _엔진()
    엔진.book = _거절하는장부(runs.WHY_NOT_APPROVED)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    assert 엔진.run.state == runs.ATTENTION

    # 다시 걸리려면 거짓으로 내려갔다 올라와야 합니다(1단계는 전이만 봅니다).
    _넣기(엔진, 3, 99.0)
    _넣기(엔진, 4, 102.0)
    _넣기(엔진, 5, 102.0)

    막힌것 = [one for one in 엔진.events if one["kind"] == engine.BLOCKED]
    assert [one["text"] for one in 막힌것] == [
        f"{engine.UNSENT_HEAD}{runs.WHY_NOT_APPROVED}",
        f"{engine.UNSENT_HEAD}{runs.WHY_STATE}",
    ], "두 번째부터는 상태가 막습니다."


def test_계좌_알림을_장부에_넣는다():
    """종이 실행은 이 자리를 안 씁니다 — 채우는 것이 우리라서입니다."""
    엔진 = _엔진()
    받은것 = []
    엔진.book.on_order = lambda event, *, at: 받은것.append(event) or []

    엔진.on_order({"id": "0000012345", "filled": 1}, at=1_000)

    assert [one["id"] for one in 받은것] == ["0000012345"]


def test_종이_장부는_알림을_안_받는다():
    엔진 = _엔진()

    엔진.on_order({"id": "0000012345", "filled": 1}, at=1_000)

    assert 엔진.fills == [], "아무 일도 없습니다."


def test_거래일이_바뀌면_모의_실행이_대사를_청한다():
    """계좌 값은 날이 바뀌면 다시 맞춰 보아야 합니다(§13-4).

    **엔진은 표시만 합니다** — 판정 한가운데에서 계좌를 부르면 그 실행의 봉이
    응답을 기다리는 동안 멈춥니다.
    """
    설정 = _설정()
    설정["baseBar"] = "일봉"
    엔진 = _엔진(설정, session=야간, mode=runs.SIM)

    엔진.on_trade({"timestamp": _때(19, 0), "price": 99.0, "quantity": 1}, 야간, at=_때(19, 0))
    엔진.on_trade(
        {"timestamp": _때(19, 0, day=18), "price": 101.0, "quantity": 1},
        야간,
        at=_때(19, 0, day=18),
    )
    assert 엔진.audit_wanted is False, "거래일을 처음 적는 것은 경계가 아닙니다."

    엔진.on_trade(
        {"timestamp": _때(19, 0, day=19), "price": 103.0, "quantity": 1},
        야간,
        at=_때(19, 0, day=19),
    )

    assert 엔진.audit_wanted is True


def test_종이_실행은_거래일이_바뀌어도_안_청한다():
    """맞춰 볼 계좌가 없습니다."""
    설정 = _설정()
    설정["baseBar"] = "일봉"
    엔진 = _엔진(설정, session=야간)

    for day, price in ((17, 99.0), (18, 101.0), (19, 103.0)):
        엔진.on_trade(
            {"timestamp": _때(19, 0, day=day), "price": price, "quantity": 1},
            야간,
            at=_때(19, 0, day=day),
        )

    assert 엔진.run.day_key, "거래일은 세고 있습니다."
    assert 엔진.audit_wanted is False


def test_체결_줄의_까닭은_값이고_말이_아니다():
    """체결 줄에는 **값**이 실리고 사람이 읽는 말은 화면이 옮깁니다.

    「진입 · 조건 충족」처럼 갈래와 까닭을 붙여 세우는 규칙이 화면 것이라,
    백엔드가 말을 정해 보내면 두 자리가 어긋납니다. 진입도 청산과 한 갈래의
    값이라 비워 두지 않습니다 — 비우면 왜 들어갔는지 말하지 않는 줄이 됩니다.
    """
    엔진 = _엔진()

    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(101.5, 101.0), at=_때(10, 2) + 지연)

    체결 = 엔진.fills[-1]
    assert 체결["intent"] == "entry"
    assert 체결["reason"] == engine.ENTRY_REASON == "signal"
    assert set(engine.REASON_LABELS) == {
        engine.ENTRY_REASON,
        engine.STOP_LOSS,
        engine.TRAIL_STOP,
        engine.TAKE_PROFIT,
        engine.RULE_EXIT,
        engine.FLATTEN,
        engine.SESSION_END,
    }, "일곱 다 옮길 말이 있어야 이벤트 문장이 영어로 새지 않습니다."


# ── 아직 안 채워진 주문 ──────────────────────────────────


def _줄서는_엔진() -> engine.RunEngine:
    """불리한 지정가로 진입해 주문이 줄을 선 엔진."""
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)
    return 엔진


def test_아직_안_채워진_주문을_줄로_낸다():
    """화면의 「가상 미체결」이 그릴 줄입니다 — 받을 칸이 없으면 늘 비어 있습니다."""
    엔진 = _줄서는_엔진()

    (줄,) = 엔진.open_orders

    assert 줄["orderId"] == 엔진.book.open_orders[0].id
    assert 줄["runId"] == "r1"
    assert 줄["side"] == paper.BUY
    assert 줄["intent"] == "entry"
    assert 줄["reason"] == engine.ENTRY_REASON
    assert 줄["quantity"] == 1 and 줄["remaining"] == 1
    assert 줄["price"] == 101.0, "지정가는 건 값이 실립니다."
    assert 줄["stopPrice"] is None
    assert 줄["orderType"] == "지정가"
    assert 줄["status"] == paper.WAITING
    assert 줄["virtual"] is True, "계좌 미체결과 한 표에 섞이지 않습니다."
    assert 줄["time"] == _때(10, 2), "낸 시각입니다 — 채워진 시각이 아닙니다."


def test_한_벌에_함께_싣는다():
    엔진 = _줄서는_엔진()

    한벌 = 엔진.snapshot()

    assert [one["orderId"] for one in 한벌["openOrders"]] == [엔진.book.open_orders[0].id]


def test_채워지면_목록에서_빠진다():
    """**지금 상태 전부**라 이어 붙이면 안 됩니다 — 채워진 주문이 표에 남습니다."""
    엔진 = _줄서는_엔진()
    assert 엔진.open_orders

    # 줄 선 지정가는 체결 흐름이 덜어 냅니다. 건 값을 관통했으니 잔량 전부입니다.
    # 손절가(100.90)는 안 건드립니다 — 닿으면 그 자리에 청산 주문이 새로 섭니다.
    때 = _때(10, 3)
    엔진.on_trade({**_체결(100.95), "timestamp": 때}, 주간, at=때)

    assert 엔진.open_orders == []
    assert 엔진.fills, "빠진 자리에 체결 줄이 섰습니다."


def test_부분체결은_남은_수량을_따로_낸다():
    """「3 중 1 남음」을 적으려면 낸 수량과 남은 수량이 둘 다 있어야 합니다."""
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가", perOrder="3"), qty=3)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)
    # 건 값에 두 계약만 거래됐습니다 — 관통이 아니라 닿은 것이라 그만큼만.
    때 = _때(10, 3)
    엔진.on_trade({**_체결(101.0, quantity=2), "timestamp": 때}, 주간, at=때)

    (줄,) = 엔진.open_orders

    assert 줄["quantity"] == 3 and 줄["remaining"] == 1
    assert 줄["status"] == paper.PARTIAL


def test_청산_주문은_청산으로_적는다():
    """진입과 청산이 한 표에 서는데 갈래가 없으면 어느 것이 무엇인지 모릅니다."""
    설정 = _설정(orderType="지정가", priceBasis="신호가", stopTicks="1000", takeTicks="1000")
    설정["rules"]["buyExit"] = _규칙(_조건(op="gt", right="100"))
    엔진 = _엔진(설정)
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 99.0, "time": 1})
    엔진.run.state = runs.HOLDING
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    (줄,) = 엔진.open_orders

    assert 줄["intent"] == "exit"
    assert 줄["reason"] == engine.RULE_EXIT
    assert 줄["side"] == paper.SELL, "보유를 닫는 쪽입니다."


def test_시장가는_가격을_비워_낸다():
    """0 으로 내면 화면이 「0원에 걸었다」로 읽습니다."""
    엔진 = _엔진()
    엔진._send(paper.BUY, 1, 101.0, "entry", _때(10, 2))

    (줄,) = 엔진.open_orders

    assert 줄["orderType"] == "시장가"
    assert 줄["price"] is None and 줄["stopPrice"] is None


# ── 방향별 가격 기준 ─────────────────────────────────────


def _규칙_청산_엔진(**aux) -> engine.RunEngine:
    """지정가로 사고, 종가가 100 아래로 내려가는 봉에서 청산 규칙으로 팝니다."""
    설정 = _설정(orderType="지정가", stopTicks="100", takeTicks="100", **aux)
    설정["rules"]["buyExit"] = _규칙(_조건(op="lt", right="100"))
    return _엔진(설정)


def _규칙_청산까지(엔진: engine.RunEngine) -> tuple[float, float]:
    """진입 주문 가격과 청산 주문 가격."""
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)  # 봉1(101) 닫힘 — 진입
    (진입,) = 엔진.open_orders
    엔진.on_book(_호가(101.0, 100.95), at=_때(10, 2) + 지연)
    assert 엔진.run.state == runs.HOLDING

    _넣기(엔진, 3, 99.0)  # 봉2(101) 닫힘
    _넣기(엔진, 4, 99.0)  # 봉3(99) 닫힘 — 청산 규칙
    (청산,) = 엔진.open_orders
    assert 청산["side"] == paper.SELL and 청산["intent"] == "exit"
    return 진입["price"], 청산["price"]


def test_주문_방향마다_가격_기준을_따로_쓴다():
    """매수 보유를 닫는 매도 청산도 **매도** 기준입니다 — 기준은 규칙이 아니라 주문 방향의 것입니다."""
    엔진 = _규칙_청산_엔진(
        priceBasis="신호가", buyPriceBasis="신호가 + 1틱", sellPriceBasis="신호가 − 1틱"
    )

    진입, 청산 = _규칙_청산까지(엔진)

    assert 진입 == pytest.approx(101.05), "매수 +1틱 = 위로 한 칸."
    assert 청산 == pytest.approx(99.05), "매도 −1틱 = 위로 한 칸(수동 쪽)."


def test_방향_칸이_비면_공용_기준을_쓴다():
    엔진 = _규칙_청산_엔진(priceBasis="신호가 + 1틱", buyPriceBasis="신호가", sellPriceBasis="")

    진입, 청산 = _규칙_청산까지(엔진)

    assert 진입 == pytest.approx(101.0)
    assert 청산 == pytest.approx(98.95), "매도 +1틱 = 아래로 한 칸."


# ── 추적 청산 ────────────────────────────────────────────


def _매수_보유(**aux) -> tuple[engine.RunEngine, int]:
    """시장가로 101.5 에 1계약 삽니다. 돌려주는 시각 뒤로 체결을 이어 넣습니다."""
    엔진 = _엔진(_설정(**aux))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(101.5, 101.0), at=때)
    assert 엔진.ledger.position.quantity == 1 and 엔진.ledger.position.avg_price == 101.5
    return 엔진, 때


def _틱(엔진: engine.RunEngine, 때: int, price: float) -> None:
    엔진.on_trade({**_체결(price), "timestamp": 때}, 주간, at=때)


def _청산_까닭(엔진: engine.RunEngine) -> str:
    return 엔진._exit_reason


def test_추적_청산은_오른_만큼_따라가다_되돌면_닫는다():
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2")

    _틱(엔진, 때 + 10, 101.8)  # 기준 101.8, 추적선 101.7
    _틱(엔진, 때 + 20, 101.75)
    assert 엔진.run.state == runs.HOLDING, "아직 2틱 안 됐습니다."

    _틱(엔진, 때 + 30, 101.7)
    assert 엔진.run.state == runs.EXITING
    마지막 = [one for one in 엔진.events if one["kind"] == engine.ORDER][-1]
    assert 마지막["text"].startswith("추적 청산 — ")
    엔진.on_book(_호가(101.75, 101.7), at=때 + 30 + 지연)

    assert 엔진.ledger.position.quantity == 0
    assert 엔진.fills[-1]["reason"] == engine.TRAIL_STOP == "trail"
    assert 엔진.fills[-1]["side"] == paper.SELL


def test_추적_청산은_평균가에서_출발한다():
    """오르기 전이면 보유 평균가에서 2틱 내려간 곳이 추적선입니다."""
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2")

    _틱(엔진, 때 + 10, 101.45)
    assert 엔진.run.state == runs.HOLDING
    _틱(엔진, 때 + 20, 101.4)
    assert 엔진.run.state == runs.EXITING
    assert _청산_까닭(엔진) == engine.TRAIL_STOP


def test_매도_보유의_추적_청산은_거울이다():
    설정 = _설정(stopTicks="10", takeTicks="100", trailTicks="2")
    설정["rules"]["buyEntry"] = {"on": False, "steps": []}
    설정["rules"]["sellEntry"] = _규칙(_조건(op="lt", right="100"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 101.0)
    _넣기(엔진, 1, 99.0)
    _넣기(엔진, 2, 99.0)  # 봉1(99) 닫힘 — 매도 진입
    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(99.5, 99.0), at=때)
    assert 엔진.ledger.position.quantity == -1 and 엔진.ledger.position.avg_price == 99.0

    _틱(엔진, 때 + 10, 98.7)  # 기준 98.7, 추적선 98.8
    _틱(엔진, 때 + 20, 98.75)
    assert 엔진.run.state == runs.HOLDING
    _틱(엔진, 때 + 30, 98.8)
    assert 엔진.run.state == runs.EXITING
    엔진.on_book(_호가(98.8, 98.75), at=때 + 30 + 지연)

    assert 엔진.fills[-1]["reason"] == engine.TRAIL_STOP
    assert 엔진.fills[-1]["side"] == paper.BUY
    assert 엔진.ledger.position.quantity == 0


def test_손절과_추적이_같은_틱이면_손절이다():
    엔진, 때 = _매수_보유(stopTicks="2", takeTicks="100", trailTicks="2")

    _틱(엔진, 때 + 10, 101.4)  # 손절선 101.4, 추적선 101.4

    assert 엔진.run.state == runs.EXITING
    assert _청산_까닭(엔진) == engine.STOP_LOSS


def test_추적과_익절이_같은_틱이면_추적이다():
    """**차례만 굳히는 시험입니다 — 기준을 직접 앉힙니다.**

    틱 흐름으로는 닿지 않는 자리입니다. 기준이 평균가에서 출발하므로 추적선이
    익절선보다 위에 오려면 앞 틱이 이미 익절선을 넘었어야 하고, 그 틱에 익절이
    먼저 나갑니다. 그래도 두 선이 겹치면 추적이 먼저라는 차례는 코드에 있어야 합니다.
    """
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="3", trailTicks="2")
    엔진._trail_best = 102.0  # 추적선 101.9

    _틱(엔진, 때 + 10, 101.7)  # 익절선 101.65, 추적선 101.9 — 둘 다 닿습니다.

    assert 엔진.run.state == runs.EXITING
    assert _청산_까닭(엔진) == engine.TRAIL_STOP


def test_한_주문이_나눠_채워지면_평균가에서_출발한다():
    """101.5 와 101.7 에 한 계약씩 — 출발점은 첫 체결가도 높은 값도 아닌 평균 101.6 입니다."""
    엔진 = _엔진(_설정(stopTicks="10", takeTicks="100", trailTicks="2"), qty=2)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    두단 = {
        "asks": [{"price": 101.5, "quantity": 1}, {"price": 101.7, "quantity": 1}],
        "bids": [{"price": 101.0, "quantity": 9}],
    }
    엔진.on_book(두단, at=때)
    assert 엔진.ledger.position.quantity == 2
    assert 엔진.ledger.position.avg_price == pytest.approx(101.6)

    _틱(엔진, 때 + 10, 101.55)  # 추적선 101.5 — 높은 값(101.7)에서 출발했다면 여기서 닫힙니다.
    assert 엔진.run.state == runs.HOLDING
    assert 엔진._trail_best == pytest.approx(101.6)

    _틱(엔진, 때 + 20, 101.5)  # 첫 체결가(101.5)에서 출발했다면 101.4 까지 안 닫힙니다.
    assert 엔진.run.state == runs.EXITING
    assert _청산_까닭(엔진) == engine.TRAIL_STOP


def test_진입_주문이_시간을_두고_나눠_채워져도_평균가에서_출발한다():
    """두 조각이 따로 온 호가에서 채워집니다. 그 사이의 체결은 기준에 들지 않습니다.

    첫 조각 뒤에는 기준이 비어 있고, 둘째 조각(같은 방향)이 와도 「더 유리할
    때만」 비교가 빈 기준을 건드리지 않습니다 — 첫 감시가 평균가로 세웁니다.
    """
    엔진 = _엔진(_설정(stopTicks="10", takeTicks="100", trailTicks="2"), qty=2)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(101.5, 101.0, quantity=1), at=때)
    assert 엔진.ledger.position.quantity == 1 and 엔진.run.state == runs.ENTERING
    assert 엔진._trail_best is None

    _틱(엔진, 때 + 10, 101.9)  # 진입 중에는 감시하지 않습니다.
    assert 엔진._trail_best is None

    엔진.on_book(_호가(101.7, 101.0, quantity=1), at=때 + 20)
    assert 엔진.ledger.position.quantity == 2 and 엔진.run.state == runs.HOLDING
    assert 엔진._trail_best is None

    _틱(엔진, 때 + 30, 101.55)
    assert 엔진._trail_best == pytest.approx(101.6)
    assert 엔진.run.state == runs.HOLDING


def test_추가_진입은_기준을_내리지_않는다():
    """평균가가 나빠져도 따라온 거리를 버리지 않습니다."""
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2", addWhileOpen=True)
    _틱(엔진, 때 + 10, 101.8)  # 기준 101.8
    엔진._take([{"orderId": "더", "side": paper.BUY, "quantity": 1, "price": 101.2, "time": 때}], 때)

    assert 엔진.ledger.position.avg_price == pytest.approx(101.35)
    assert 엔진._trail_best == pytest.approx(101.8)


def test_추가_진입으로_평균가가_기준을_넘으면_평균가로_옮긴다():
    """추적선이 평균가 뒤에 처지지 않게 합니다. 체결가(102.5)가 아니라 평균가(102.0)입니다."""
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2", addWhileOpen=True)
    _틱(엔진, 때 + 10, 101.6)  # 기준 101.6
    엔진._take([{"orderId": "더", "side": paper.BUY, "quantity": 1, "price": 102.5, "time": 때}], 때)

    assert 엔진.ledger.position.avg_price == pytest.approx(102.0)
    assert 엔진._trail_best == pytest.approx(102.0)


def test_청산이_나간_뒤에는_추적이_두_번_내지_않는다():
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2")
    _틱(엔진, 때 + 10, 101.4)
    주문수 = len(엔진.book.orders)

    _틱(엔진, 때 + 20, 101.0)
    _틱(엔진, 때 + 30, 100.5)

    assert len(엔진.book.orders) == 주문수
    assert 엔진.run.state == runs.EXITING


def test_시세가_끊겼다_돌아온_첫_틱이_선_너머면_바로_닫는다():
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2")
    _틱(엔진, 때 + 10, 101.8)
    엔진.on_status(False, at=때 + 20)
    assert 엔진.feed == engine.GAP

    _틱(엔진, 때 + 30, 101.6)

    assert 엔진.feed != engine.GAP
    # 끊긴 뒤 첫 체결의 청산은 그 체결 값에 바로 채웁니다(paper 가정 9).
    assert 엔진.run.state == runs.ARMED and 엔진.ledger.position.quantity == 0
    청산 = 엔진.fills[-1]
    assert 청산["price"] == 101.6 and 청산["time"] == 때 + 30
    assert 청산["reason"] == engine.TRAIL_STOP


def test_청산이_다_안_돼_보유로_돌아와도_기준은_그대로다():
    엔진 = _엔진(_설정(stopTicks="10", takeTicks="100", trailTicks="2"), qty=2)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(101.5, 101.0), at=때)
    assert 엔진.ledger.position.quantity == 2

    _틱(엔진, 때 + 10, 101.8)  # 기준 101.8, 추적선 101.7
    _틱(엔진, 때 + 20, 101.7)
    assert 엔진.run.state == runs.EXITING
    엔진.on_book(_호가(101.75, 101.7, quantity=1), at=때 + 20 + 지연)  # 1계약만
    엔진.close_session(때 + 30)  # 남은 청산 주문을 거둡니다
    assert 엔진.run.state == runs.HOLDING and 엔진.ledger.position.quantity == 1

    assert 엔진._trail_best == pytest.approx(101.8)
    _틱(엔진, 때 + 40, 101.7)
    assert 엔진.run.state == runs.EXITING, "평균가에서 다시 출발했다면 101.6 까지 안 닫힙니다."


def test_보유가_없어지면_기준을_지운다():
    엔진, 때 = _매수_보유(stopTicks="10", takeTicks="100", trailTicks="2")
    _틱(엔진, 때 + 10, 101.4)
    엔진.on_book(_호가(101.45, 101.4), at=때 + 10 + 지연)

    assert 엔진.ledger.position.quantity == 0
    assert 엔진._trail_best is None


# ── 연속 손실 한도 ───────────────────────────────────────


def _손실_한_번(엔진: engine.RunEngine, minute: int, day: int = 17) -> None:
    """99·99·101·101 로 진입하고, 2틱 손절로 0.1 잃고 나옵니다."""
    for step, price in enumerate((99.0, 99.0, 101.0, 101.0)):
        때 = _때(10, minute + step, day=day)
        엔진.on_trade({**_체결(price), "timestamp": 때}, 주간, at=때)
    때 = _때(10, minute + 3, day=day) + 지연
    엔진.on_book(_호가(101.5, 101.0), at=때)
    엔진.on_trade({**_체결(101.4), "timestamp": 때 + 10}, 주간, at=때 + 10)
    엔진.on_book(_호가(101.5, 101.4), at=때 + 10 + 지연)
    assert 엔진.ledger.position.quantity == 0 and 엔진.run.state == runs.ARMED


def _안낸신호(엔진: engine.RunEngine) -> list[str]:
    return [one["text"] for one in 엔진.events if one["kind"] == engine.BLOCKED]


def test_연속_손실_한도에_닿으면_새_진입을_막고_다음_거래일에_푼다():
    엔진 = _엔진(_설정(lossStreak="2"))
    _손실_한_번(엔진, 0)
    _손실_한_번(엔진, 4)
    assert [one["netPl"] < 0 for one in 엔진.ledger.trades] == [True, True]

    for step, price in enumerate((99.0, 99.0, 101.0, 101.0)):
        _넣기(엔진, 8 + step, price)

    assert _안낸신호(엔진) == [engine.UNSENT_HEAD + runs.WHY_LOSS_STREAK]
    assert 엔진.run.state == runs.ARMED
    assert runs.loss_streak(엔진.run, 엔진.ledger) == 2

    # 다음 거래일 — 첫 봉이 닫히며 다시 셉니다.
    for step, price in enumerate((99.0, 99.0, 101.0, 101.0)):
        때 = _때(10, step, day=18)
        엔진.on_trade({**_체결(price), "timestamp": 때}, 주간, at=때)

    assert 엔진.run.state == runs.ENTERING
    assert runs.loss_streak(엔진.run, 엔진.ledger) == 0


def test_연속_손실_한도에_닿아도_청산은_나간다():
    """막는 것은 새 진입뿐입니다. 들고 있는 것을 닫는 길은 한도를 안 봅니다."""
    엔진, 때 = _매수_보유(lossStreak="1")
    엔진.ledger.trades.append({"netPl": -1.0})  # 한도에 닿은 채로 들고 있습니다.

    _틱(엔진, 때 + 10, 101.4)

    assert 엔진.run.state == runs.EXITING
    assert _청산_까닭(엔진) == engine.STOP_LOSS


# ── 새 칸이 없는 옛 버전 ─────────────────────────────────


def _한_바퀴(설정) -> tuple[list, list, list]:
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    엔진.on_book(_호가(101.5, 101.0), at=때)
    _틱(엔진, 때 + 10, 101.6)
    _틱(엔진, 때 + 20, 101.45)
    _틱(엔진, 때 + 30, 101.65)
    엔진.on_book(_호가(101.7, 101.65), at=때 + 30 + 지연)
    return 엔진.fills, 엔진.events, 엔진.ledger.trades


def test_새_칸이_없거나_빈_옛_버전은_전과_같이_돈다():
    """새 칸이 없을 때와 비었을 때, 0 일 때 체결·이벤트·거래가 한 글자도 안 다릅니다."""
    옛것 = _한_바퀴(_설정())
    빈것 = _설정(buyPriceBasis="", sellPriceBasis="", trailTicks="", lossStreak="")
    빈것["rules"]["buyEntry"]["resetBars"] = ""
    영 = _설정(trailTicks="0", lossStreak="0")
    영["rules"]["buyEntry"]["resetBars"] = 0

    assert _한_바퀴(빈것) == 옛것
    assert _한_바퀴(영) == 옛것
    fills, _, trades = 옛것
    assert [one["reason"] for one in fills] == [engine.ENTRY_REASON, engine.TAKE_PROFIT]
    assert len(trades) == 1


# ── 체결 당시 지표 ───────────────────────────────────────


def _봉값과_같다(엔진: engine.RunEngine, snapshot: dict) -> None:
    """실린 값이 그 봉(`barTime`)의 series 값과 같은지."""
    series = rules.series_of(엔진.bars.bars)
    index = next(at for at, bar in enumerate(엔진.bars.bars) if bar.timestamp == snapshot["barTime"])
    for name, value in snapshot["values"].items():
        assert value == series.at(name, index), name


def test_진입_체결에_판정한_봉의_값을_싣는다():
    엔진, _ = _매수_보유()

    (진입,) = 엔진.fills
    assert 진입["snapshot"]["barTime"] == _때(10, 1), "판정한 봉(종가 101)의 시작 시각입니다."
    assert 진입["snapshot"]["values"] == {"close": 101.0}
    _봉값과_같다(엔진, 진입["snapshot"])


def test_값의_이름은_규칙_넷의_피연산자와_종가다():
    """켜짐과 상관없이 단계 전부를 봅니다. 수로 적은 오른쪽은 빼고 값을 견준 오른쪽은 넣습니다."""
    규칙들 = {
        "buyEntry": {
            "on": True,
            "steps": [
                {
                    "id": "s1",
                    "join": "all",
                    "withinBars": 3,
                    "conds": [
                        _조건(left="ema20", op="crossUp", right="ema50", kind="operand"),
                        _조건(left="rsi14", op="gte", right="55"),
                    ],
                },
                {
                    "id": "s2",
                    "join": "all",
                    "withinBars": 0,
                    "conds": [_조건(left="close", op="gt", right="prevHigh", kind="operand")],
                },
            ],
        },
        # 꺼진 규칙도 셉니다.
        "sellEntry": {**_규칙(_조건(left="atr14", op="gte", right="3")), "on": False},
        "buyExit": _규칙(_조건(left="close", op="crossDown", right="bbLower", kind="operand")),
        "sellExit": {"on": True, "steps": []},
    }

    # 이름은 값 열의 이름입니다. 옛 이름으로 적은 조건도 「ema(20)」 꼴로 싣고,
    # 차례는 적힌 이름의 자리 그대로입니다.
    assert engine._snapshot_ids(규칙들) == (
        "close",
        "ema(20)",
        "ema(50)",
        "rsi(14)",
        "atr(14)",
        "bbLower(20,2)",
        "prevHigh",
    )


def test_가격만_쓰는_옛_설정은_종가만_싣는다():
    assert _엔진()._snap_ids == ("close",)
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(_조건(left="high", op="gt", right="prevHigh", kind="operand"))
    assert _엔진(설정)._snap_ids == ("close", "high", "prevHigh")


@pytest.mark.parametrize(
    ("aux", "price", "까닭"),
    [
        ({"stopTicks": "2"}, 101.4, engine.STOP_LOSS),
        ({"stopTicks": "10", "trailTicks": "2"}, 101.4, engine.TRAIL_STOP),
        ({"stopTicks": "10", "takeTicks": "3"}, 101.65, engine.TAKE_PROFIT),
    ],
)
def test_틱에서_나간_청산은_마지막으로_닫힌_봉의_값이다(aux, price, 까닭):
    엔진, _ = _매수_보유(**aux)
    때 = _때(10, 3)
    _틱(엔진, 때, 101.5)  # 봉2(10:02) 닫힘 — 새 신호는 없습니다(전이가 아님).
    _틱(엔진, 때 + 10, price)
    assert _청산_까닭(엔진) == 까닭
    엔진.on_book(_호가(102.0, price), at=때 + 10 + 지연)

    청산 = 엔진.fills[-1]
    assert 청산["reason"] == 까닭
    assert 청산["snapshot"]["barTime"] == _때(10, 2)
    _봉값과_같다(엔진, 청산["snapshot"])


def test_다른_창의_봉이_마지막이면_틱_청산은_그_봉의_값이다():
    """판정하는 창의 마지막 봉을 고르면 청산한 순간보다 오래된 값이 실립니다."""
    엔진, _ = _매수_보유(stopTicks="2")
    때 = _때(10, 3)
    엔진.on_trade({**_체결(101.5), "timestamp": 때}, 야간, at=때)  # 주간 봉(10:02) 닫힘
    엔진.on_trade({**_체결(101.5), "timestamp": 때 + 60_000}, 야간, at=때 + 60_000)  # 야간 봉(10:03) 닫힘
    assert 엔진.bars.sessions[-1] == 야간 and 엔진.bars.bars[-1].timestamp == 때

    엔진.on_trade({**_체결(101.4), "timestamp": 때 + 60_010}, 야간, at=때 + 60_010)
    assert _청산_까닭(엔진) == engine.STOP_LOSS
    엔진.on_book(_호가(101.5, 101.4), at=때 + 60_010 + 지연)

    assert 엔진.fills[-1]["snapshot"]["barTime"] == 때, "판정 창(주간)의 10:02 봉이 아닙니다."
    _봉값과_같다(엔진, 엔진.fills[-1]["snapshot"])


def test_사용자_청산도_마지막으로_닫힌_봉의_값이다():
    엔진, 때 = _매수_보유()
    엔진._close(1, 101.2, engine.FLATTEN, 때 + 10)
    엔진.on_book(_호가(101.5, 101.2), at=때 + 10 + 지연)

    청산 = 엔진.fills[-1]
    assert 청산["reason"] == engine.FLATTEN
    assert 청산["snapshot"]["barTime"] == _때(10, 1)


def test_규칙_청산은_판정한_봉의_값이다():
    엔진 = _규칙_청산_엔진(priceBasis="신호가")
    _규칙_청산까지(엔진)
    엔진.on_book(_호가(99.5, 99.0), at=_때(10, 4) + 지연)

    청산 = 엔진.fills[-1]
    assert 청산["reason"] == engine.RULE_EXIT
    assert 청산["snapshot"]["barTime"] == _때(10, 3), "종가 99 로 닫혀 청산 규칙이 걸린 봉입니다."
    _봉값과_같다(엔진, 청산["snapshot"])


def test_계좌_알림으로_온_체결에도_싣는다():
    """모의 실행의 체결은 계좌 알림으로 옵니다. 같은 자리를 지나 같은 값이 붙습니다."""
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    (주문,) = 엔진.open_orders
    엔진.book.on_order = lambda event, *, at: [
        {"orderId": 주문["orderId"], "execNo": "n1", "time": at, "price": 101.0, "quantity": 1, "side": paper.BUY}
    ]

    엔진.on_order({"id": "0000012345"}, at=_때(10, 2, 30))

    assert 엔진.fills[-1]["snapshot"] == {"barTime": _때(10, 1), "values": {"close": 101.0}}


def test_우리가_내지_않은_주문의_체결은_값이_없음이다():
    """칸은 둡니다 — 칸이 없는 옛 기록과 「이 체결에는 값이 없다」를 가려 읽습니다."""
    엔진 = _엔진()
    엔진.book.on_order = lambda event, *, at: [
        {"orderId": "0000099999", "execNo": "n1", "time": at, "price": 101.0, "quantity": 1, "side": paper.BUY}
    ]

    엔진.on_order({"id": "0000099999"}, at=1_000)

    assert "snapshot" in 엔진.fills[-1]
    assert 엔진.fills[-1]["snapshot"] is None


def test_나눠_채워진_조각은_같은_값을_갖는다():
    엔진 = _엔진(qty=2)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    두단 = {
        "asks": [{"price": 101.5, "quantity": 1}, {"price": 101.7, "quantity": 1}],
        "bids": [{"price": 101.0, "quantity": 9}],
    }
    엔진.on_book(두단, at=_때(10, 2) + 지연)

    첫, 둘 = 엔진.fills
    assert 첫["execNo"] != 둘["execNo"]
    assert 첫["snapshot"] == 둘["snapshot"] == {"barTime": _때(10, 1), "values": {"close": 101.0}}


def test_준비_전_지표는_칸을_두고_값이_없음이다():
    설정 = _설정()
    설정["rules"]["buyExit"] = _규칙(_조건(left="ema20", op="lt", right="1"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)

    값 = 엔진._snapshot_now()

    assert 값["barTime"] == _때(10, 0)
    assert 값["values"] == {"close": 99.0, "ema(20)": None}


def test_봉이_하나도_없으면_시각도_값도_없음이다():
    assert _엔진()._snapshot_now() == {"barTime": None, "values": {"close": None}}


def test_기록에_못_싣는_수는_없음으로_바꾼다():
    assert engine._finite(float("nan")) is None
    assert engine._finite(float("inf")) is None
    assert engine._finite(-float("inf")) is None
    assert engine._finite(101.5) == 101.5


def test_체결_줄은_NaN_없이_JSON_으로_담긴다():
    fills, _, _ = _한_바퀴(_설정())

    for 줄 in fills:
        json.dumps(줄, allow_nan=False)


def test_거절된_주문은_값을_남기지_않는다():
    엔진 = _엔진()
    엔진.book = _거절하는장부(runs.WHY_NOT_APPROVED)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    assert 엔진.run.state == runs.ATTENTION
    assert 엔진._snap == {}


def test_끝난_주문의_값은_비운다():
    엔진, 때 = _매수_보유(takeTicks="3")
    assert 엔진._snap == {}, "진입 주문이 다 채워져 끝났습니다."
    _틱(엔진, 때 + 10, 101.65)
    assert len(엔진._snap) == 1, "청산 주문이 나가 있습니다."
    엔진.on_book(_호가(101.7, 101.65), at=때 + 10 + 지연)

    assert 엔진._snap == {} and 엔진._purpose == {}


def test_세션이_끝나_거둔_주문의_값도_비운다():
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(105.0, 104.0), at=_때(10, 2) + 지연)
    assert len(엔진._snap) == 1

    엔진.close_session(_때(15, 45))

    assert 엔진._snap == {}


def test_봉_상한에서_앞이_잘려도_시각으로_가리킨다():
    """자리 번호로 가리키면 앞이 잘릴 때마다 다른 봉을 가리킵니다."""
    엔진 = _엔진()
    엔진.bars.limit = 3
    for minute, price in enumerate((99.0, 99.0, 99.0, 99.0, 101.0, 101.0)):
        _넣기(엔진, minute, price)
    assert len(엔진.bars.bars) == 3
    엔진.on_book(_호가(101.5, 101.0), at=_때(10, 5) + 지연)

    (진입,) = 엔진.fills
    assert 진입["snapshot"]["barTime"] == _때(10, 4)
    assert 진입["snapshot"]["values"] == {"close": 101.0}


# ── 봉마다 적는 호가·포지션 값 ──────────────────────────


def _열(엔진: engine.RunEngine, name: str) -> dict[int, float | None]:
    """판정에 쓰는 한 벌에서 그 열을 봉 시각 → 값으로."""
    series = 엔진._series()
    return {bar.timestamp: series.values[name][at] for at, bar in enumerate(엔진.bars.bars)}


def _조회봉(minute: int, close: float) -> dict:
    때 = _때(10, minute)
    return {"timestamp": 때, "open": close, "high": close, "low": close, "close": close, "volume": 5}


def test_호가는_장부에_넘기기_전에_1호가를_적는다():
    """매도는 먼 값부터, 매수는 가까운 값부터 옵니다. 종이 장부와 같은 규칙으로 읽습니다."""
    엔진 = _엔진()
    _넣기(엔진, 0, 100.0)
    엔진.on_book(
        {
            "asks": [{"price": 102.0, "quantity": 3}, {"price": 101.5, "quantity": 7}],
            "bids": [{"price": 101.0, "quantity": 4}, {"price": 100.5, "quantity": 9}],
        },
        at=_때(10, 0, 30),
    )
    assert 엔진._quote == {"bid1": 101.0, "ask1": 101.5, "bid1Qty": 4.0, "ask1Qty": 7.0}

    _넣기(엔진, 1, 100.0)  # 봉0 닫힘

    적은것 = 엔진._marks[_때(10, 0)]
    assert (적은것["bid1"], 적은것["ask1"], 적은것["bid1Qty"], 적은것["ask1Qty"]) == (
        101.0,
        101.5,
        4.0,
        7.0,
    )


def test_호가를_못_받은_봉은_호가가_비고_보유는_있다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 99.0)

    적은것 = 엔진._marks[_때(10, 0)]
    assert [적은것[name] for name in rules.BOOK_IDS] == [None] * 4
    assert (적은것["positionQty"], 적은것["openPl"]) == (0.0, 0.0), "보유가 없으면 0 입니다."


def test_봉을_닫은_체결로_난_진입은_닫힌_봉에_들지_않는다():
    """봉을 닫는 체결은 다음 봉의 첫 체결입니다. 그것으로 채워진 보유는 다음 봉의 것입니다."""
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가", stopTicks="100"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)  # 봉1 닫힘 — 101 에 사는 지정가
    때 = _때(10, 2) + 지연
    _틱(엔진, 때, 101.0)  # 주문이 켜집니다
    엔진.on_book(_호가(101.5, 100.5), at=때 + 10)  # 줄을 섭니다 — 앞 순위 없음
    assert 엔진.ledger.position.quantity == 0

    _넣기(엔진, 3, 100.9)  # 관통 1계약 — 채워지면서 봉2 를 닫습니다
    assert 엔진.ledger.position.quantity == 1
    assert 엔진._marks[_때(10, 2)]["positionQty"] == 0.0
    assert 엔진._marks[_때(10, 2)]["openPl"] == 0.0

    _넣기(엔진, 4, 101.2)  # 봉3(종가 100.9) 닫힘
    assert 엔진._marks[_때(10, 3)]["positionQty"] == 1.0
    assert 엔진._marks[_때(10, 3)]["openPl"] == pytest.approx(-0.1), "그 봉 종가로 셉니다."


def test_평가손익은_마지막_체결가가_아니라_그_봉_종가로_센다():
    엔진, 때 = _매수_보유(stopTicks="100", takeTicks="100")  # 101.5 에 1계약
    _틱(엔진, 때 + 10, 102.0)  # 봉2 의 마지막 값
    _넣기(엔진, 3, 105.0)  # 봉2 를 닫는 체결(다음 봉의 첫 값)

    assert 엔진._marks[_때(10, 2)]["openPl"] == pytest.approx(0.5)


def test_시세가_끊긴_채_닫힌_봉에는_호가를_적지_않는다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    엔진.on_book(_호가(99.5, 99.0), at=_때(10, 0, 10))
    엔진.on_status(False, at=_때(10, 0, 20))

    엔진.close_session(_때(10, 0, 30))

    적은것 = 엔진._marks[_때(10, 0)]
    assert [적은것[name] for name in rules.BOOK_IDS] == [None] * 4
    assert 적은것["positionQty"] == 0.0


def test_세션_끝에_닫힌_봉도_적는다():
    엔진 = _엔진()
    _넣기(엔진, 0, 99.0)
    엔진.on_book(_호가(99.5, 99.0), at=_때(10, 0, 10))

    엔진.close_session(_때(10, 0, 30))

    assert 엔진._marks[_때(10, 0)]["bid1"] == 99.0


def _열린_엔진(**덮어쓰기) -> engine.RunEngine:
    """10:00 에 연 주간 세션을 아는 엔진."""
    엔진 = _엔진(**덮어쓰기)
    엔진.note_open(주간, _때(10, 0))
    return 엔진


def test_봉_순서는_개장부터_센_시계_칸이다():
    """10:02 에 체결이 없었어도 10:03 봉은 넷째 칸입니다."""
    엔진 = _열린_엔진()
    for minute in (0, 1, 3, 4):
        _넣기(엔진, minute, 99.0)

    assert list(_열(엔진, "barOrder").values()) == [1.0, 2.0, 4.0]


def test_실행을_늦게_세워도_같은_봉은_같은_번호다():
    """개장이 10:00 이면 10:05 에 세운 실행에서도 10:05 봉은 여섯째입니다."""
    일찍 = _열린_엔진()
    늦게 = _열린_엔진()
    for minute in range(8):
        _넣기(일찍, minute, 99.0)
    for minute in range(5, 8):
        _넣기(늦게, minute, 99.0)

    for 때, 번호 in _열(늦게, "barOrder").items():
        assert 번호 == _열(일찍, "barOrder")[때]
    assert _열(늦게, "barOrder")[_때(10, 5)] == 6.0


def test_개장_시각을_모르면_봉_순서는_없음이다():
    엔진 = _엔진()
    for minute in range(3):
        _넣기(엔진, minute, 99.0)

    assert list(_열(엔진, "barOrder").values()) == [None, None]
    assert not 엔진.open_known(_때(10, 1), 주간)


def test_개장_전의_봉은_봉_순서가_없다():
    엔진 = _엔진()
    엔진.note_open(주간, _때(10, 2))
    for minute in range(4):
        _넣기(엔진, minute, 99.0)

    assert list(_열(엔진, "barOrder").values()) == [None, None, 1.0]


def _긴봉_순서(base_bar: str, 체결들: list[tuple[int, int]]) -> dict[str, float | None]:
    """개장 08:45 인 주간 세션에서, (시, 분) 체결들로 세운 봉의 번호를 「HH:MM → 번호」로."""
    엔진 = _엔진({**_설정(), "baseBar": base_bar})
    엔진.note_open(주간, _때(8, 45))
    for hour, minute in 체결들:
        때 = _때(hour, minute)
        엔진.on_trade({**_체결(99.0), "timestamp": 때}, 주간, at=때)
    엔진.close_session(_때(15, 45))
    return {
        datetime.fromtimestamp(때 / 1000, tz=KST).strftime("%H:%M"): 번호
        for 때, 번호 in _열(엔진, "barOrder").items()
    }


@pytest.mark.parametrize(
    ("base_bar", "기대"),
    [
        # 30분봉의 08:30 칸이 08:45~09:00 체결을 담습니다 — 그 칸이 1번입니다.
        ("30분봉", {"08:30": 1.0, "09:00": 2.0, "09:30": 3.0}),
        ("60분봉", {"08:00": 1.0, "09:00": 2.0}),
        # 칸 경계가 개장과 맞는 봉 길이는 전과 같습니다.
        ("15분봉", {"08:45": 1.0, "09:00": 2.0, "09:15": 3.0, "09:30": 4.0}),
    ],
)
def test_개장을_담은_칸이_첫_봉이다(base_bar, 기대):
    체결들 = [(8, 50), (9, 5), (9, 20), (9, 40)]

    assert _긴봉_순서(base_bar, 체결들) == 기대


def test_봉_상한에서_앞이_잘려도_봉_순서와_기록이_맞물린다():
    엔진 = _열린_엔진()
    엔진.bars.limit = 3
    for minute in range(6):
        _넣기(엔진, minute, 99.0)

    assert [bar.timestamp for bar in 엔진.bars.bars] == [_때(10, 2), _때(10, 3), _때(10, 4)]
    assert set(엔진._marks) <= {bar.timestamp for bar in 엔진.bars.bars}
    assert len(엔진._marks) <= len(엔진.bars.bars)
    assert list(_열(엔진, "barOrder").values()) == [3.0, 4.0, 5.0], "잘린 봉부터 세지 않습니다."


def test_이른_봉이_뒤채워져도_지난_봉_번호는_그대로다():
    엔진 = _열린_엔진()
    for minute in (5, 6, 7):
        _넣기(엔진, minute, 99.0)
    앞 = _열(엔진, "barOrder")

    엔진.seed([_조회봉(0, 98.0), _조회봉(1, 98.0), _조회봉(2, 98.0)], 주간)

    뒤 = _열(엔진, "barOrder")
    for 때, 번호 in 앞.items():
        assert 뒤[때] == 번호
    assert 뒤[_때(10, 0)] == 1.0


def test_가운데를_메운_뒤채움은_번호를_바꾸지_않고_값은_비어_있다():
    엔진 = _열린_엔진()
    for minute in (0, 1, 5, 6):
        _넣기(엔진, minute, 99.0)
    앞 = _열(엔진, "barOrder")
    적은것 = dict(엔진._marks)

    엔진.seed([_조회봉(2, 98.0), _조회봉(3, 98.0), _조회봉(4, 98.0), _조회봉(5, 97.0)], 주간)

    뒤 = _열(엔진, "barOrder")
    for 때, 번호 in 앞.items():
        assert 뒤[때] == 번호
    assert 뒤[_때(10, 3)] == 4.0
    assert set(엔진._marks) <= {bar.timestamp for bar in 엔진.bars.bars}
    assert 엔진._marks[_때(10, 5)] == 적은것[_때(10, 5)], "같은 칸의 봉이 바뀌어도 적은 값은 둡니다."
    assert _열(엔진, "positionQty")[_때(10, 3)] is None, "뒤채운 봉에는 적은 값이 없습니다."


def test_실행을_세운_첫_판정_봉에서_보유_조건이_바로_걸리지_않는다():
    """준비 봉(조회)에는 보유 값이 없습니다. 거기서 넘어온 「보유 0」은 전이가 아닙니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"] = _규칙(_조건(left="positionQty", op="eq", right="0"))
    엔진 = _엔진(설정)
    엔진.seed([_조회봉(0, 99.0), _조회봉(1, 99.0), _조회봉(2, 99.0)], 주간)

    for minute in (3, 4, 5):
        _넣기(엔진, minute, 99.0)

    assert engine.SIGNAL not in _갈래(엔진)
    assert 엔진.run.state == runs.ARMED


def test_체결_당시_값에_새_값도_실린다():
    설정 = _설정()
    설정["rules"]["buyExit"] = _규칙(_조건(left="positionQty", op="gt", right="5"))
    엔진 = _엔진(설정)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(101.5, 101.0), at=_때(10, 2) + 지연)

    (진입,) = 엔진.fills
    assert list(진입["snapshot"]["values"]) == ["close", "positionQty"]
    assert 진입["snapshot"]["values"]["positionQty"] == 0.0
    json.dumps(진입, allow_nan=False)


# ── 체결 줄의 수수료·미체결 줄의 주문번호 ──────────────


def test_체결_줄에_수수료를_싣고_기록_줄에도_같은_값이_간다():
    엔진 = _엔진(fee_per_contract=1500.0)
    기록 = []
    엔진.record = lambda kind, row: 기록.append((kind, dict(row)))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book(_호가(101.5, 101.0), at=_때(10, 2) + 지연)

    (진입,) = 엔진.fills
    assert 진입["fee"] == 1500.0
    (기록된것,) = [row for kind, row in 기록 if kind == engine.FILL]
    assert 기록된것["fee"] == 진입["fee"]


def test_수수료_설정이_0_이면_0_이다():
    엔진, _ = _매수_보유()

    (진입,) = 엔진.fills
    assert 진입["fee"] == 0.0 and isinstance(진입["fee"], float)


def test_실행_누계는_체결_수수료의_합이다():
    엔진 = _엔진(_설정(lossStreak=""), fee_per_contract=250.0)
    _손실_한_번(엔진, 0)
    _손실_한_번(엔진, 4)

    assert len(엔진.fills) == 4
    assert 엔진.ledger.fee == pytest.approx(sum(one["fee"] for one in 엔진.fills))


def test_나눠_들고_나눠_낸_거래의_수수료는_네_체결의_합이다():
    엔진 = _엔진(_설정(takeTicks="3", stopTicks="100"), qty=2, fee_per_contract=100.0)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    때 = _때(10, 2) + 지연
    엔진.on_book(
        {"asks": [{"price": 101.6, "quantity": 1}, {"price": 101.5, "quantity": 1}], "bids": []},
        at=때,
    )
    _틱(엔진, 때 + 10, 101.8)  # 평균 101.55 에서 익절선 101.7 을 넘습니다.
    assert 엔진.run.state == runs.EXITING
    엔진.on_book(
        {"asks": [], "bids": [{"price": 101.8, "quantity": 1}, {"price": 101.75, "quantity": 1}]},
        at=때 + 10 + 지연,
    )

    assert [one["quantity"] for one in 엔진.fills] == [1, 1, 1, 1]
    assert [one["fee"] for one in 엔진.fills] == [100.0] * 4, "조각마다 제 수량만큼입니다."
    (거래,) = 엔진.ledger.trades
    assert 거래["fee"] == pytest.approx(sum(one["fee"] for one in 엔진.fills))


def test_계좌_알림으로_온_체결에도_엔진이_센_수수료를_싣는다():
    """알림이 같은 이름의 값을 실어 와도 장부의 셈이 이깁니다 — 누계와 맞아야 합니다."""
    엔진 = _엔진(fee_per_contract=300.0)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    (주문,) = 엔진.open_orders
    엔진.book.on_order = lambda event, *, at: [
        {
            "orderId": 주문["orderId"],
            "orderNo": "0000012345",
            "execNo": "n1",
            "time": at,
            "price": 101.0,
            "quantity": 1,
            "side": paper.BUY,
            "fee": 999.0,
        }
    ]

    엔진.on_order({"id": "0000012345"}, at=_때(10, 2, 30))

    assert 엔진.fills[-1]["fee"] == 300.0
    assert 엔진.fills[-1]["orderNo"] == "0000012345"
    assert 엔진.ledger.fee == 300.0


def test_모의_주문의_미체결_줄에_계좌_주문번호를_싣는다():
    from backend.strategy import sim

    엔진 = _엔진(mode=runs.SIM)
    주문 = sim.SimOrder(id="r1-1", side=paper.BUY, quantity=1, order_type="지정가", order_no="0000012345")

    assert 엔진._order_row(주문)["orderNo"] == "0000012345"
    assert 엔진._order_row(sim.SimOrder(id="r1-2", side=paper.BUY, quantity=1, order_type="지정가"))[
        "orderNo"
    ] is None, "번호가 비면 빈 글자가 아니라 없음입니다."


def test_종이_주문의_미체결_줄에는_주문번호가_없음이다():
    엔진 = _엔진(_설정(orderType="지정가", priceBasis="신호가"))
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)

    (줄,) = 엔진.open_orders
    assert "orderNo" in 줄 and 줄["orderNo"] is None


def test_해외_선물은_계약당_값을_증거금_칸_없음으로_낸다():
    해외 = _엔진(market="overseas", session="overseas", code="ESZ26", kind="futures", margin=None)
    assert (해외.per_contract, 해외.per_contract_basis) == (None, engine.BASIS_NO_MARGIN_FIELD)

    # 국내 선물은 값이 비어도 근거는 그대로입니다 — 표를 아직 못 받은 것입니다.
    국내 = _엔진(kind="futures", margin=None)
    assert (국내.per_contract, 국내.per_contract_basis) == (None, engine.BASIS_MARGIN)

    # 해외도 값이 있으면 그 값입니다.
    앎 = _엔진(market="overseas", session="overseas", code="ESZ26", kind="futures", margin=5_000.0)
    assert (앎.per_contract, 앎.per_contract_basis) == (5_000.0, engine.BASIS_MARGIN)
