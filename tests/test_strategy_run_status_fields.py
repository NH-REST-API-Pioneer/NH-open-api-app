"""실행 줄의 상태 칸 — 1호가와 시각, 묶인 돈·남은 돈, 예상 주문가.

**계좌에 닿지 않습니다.** 종이 엔진에 체결·호가를 손으로 넣고, 실행 목록은
시험용 마스터·시간표로 세웁니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, paper, pump as pump_lib, runs, service as service_lib
from tests.test_strategy_engine import _규칙, _때, _설정, _엔진, _조건, _호가
from tests.test_strategy_pump import _허브
from tests.test_strategy_service import _물음, 실행목록  # noqa: F401 — 시험 준비물

주간 = "domestic-day"
새칸 = (
    "marginBudget", "marginUsed", "marginLeft",
    "bid1", "ask1", "bid1Qty", "ask1Qty", "quoteAt", "expectedOrder",
)


def _체결(엔진, price: float, minute: int = 0) -> int:
    때 = _때(10, minute)
    엔진.on_trade({"price": price, "quantity": 1, "timestamp": 때}, 주간, at=때)
    return 때


# ── 1호가 ─────────────────────────────────────────────


def test_호가를_받기_전에는_칸이_모두_비어_있다():
    assert _엔진().quote_now == {name: None for name in engine.QUOTE_FIELDS}


def test_받은_1호가와_그_시각을_낸다():
    엔진 = _엔진()
    _체결(엔진, 100.0)
    때 = _때(10, 0, 5)

    엔진.on_book(_호가(100.1, 100.0, quantity=7), at=때)

    assert 엔진.quote_now == {"bid1": 100.0, "ask1": 100.1, "bid1Qty": 7.0, "ask1Qty": 7.0, "quoteAt": 때}


def test_시세가_끊긴_동안은_호가를_비운다():
    엔진 = _엔진()
    _체결(엔진, 100.0)
    엔진.on_book(_호가(100.1, 100.0), at=_때(10, 0, 5))

    엔진.on_status(False, at=_때(10, 0, 6))

    assert 엔진.feed == engine.GAP
    assert 엔진.quote_now == {name: None for name in engine.QUOTE_FIELDS}


# ── 묶인 돈 ───────────────────────────────────────────


def test_묶인_돈은_보유와_열린_진입에_계약당_값을_곱한다():
    엔진 = _엔진()
    엔진.ledger.add({"side": paper.BUY, "quantity": 2, "price": 100.0, "time": 1})

    assert runs.margin_used(엔진.ledger, 1, 2_500_000.0) == 7_500_000.0
    assert runs.margin_used(엔진.ledger, 1, 2_500_000.0, adding=1) == 10_000_000.0
    assert runs.margin_used(엔진.ledger, 0, None) is None, "계약당 값을 모르면 모릅니다."


def _예산실행(budget: float) -> runs.Run:
    return runs.Run(
        id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
        state=runs.HOLDING, qty=1, cash=10_000_000.0, margin=2_500_000.0, margin_budget=budget,
    )


@pytest.mark.parametrize(("open_entry", "막힘"), [(0, None), (1, runs.WHY_BUDGET)])
def test_진입_검사는_묶인_돈과_같은_셈으로_예산을_본다(open_entry, 막힘):
    실행 = _예산실행(5_000_000.0)
    장부 = runs.Ledger()
    장부.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})

    까닭 = runs.entry_block(
        실행, 장부, side=paper.BUY, open_entry=open_entry, max_hold=9, add_while_open=True,
        gap=False, expiring=False, last_price=100.0,
    )

    assert 까닭 == 막힘
    assert (runs.margin_used(장부, open_entry, 2_500_000.0, adding=실행.qty) > 5_000_000.0) == (막힘 is not None)


def test_계약당_값을_모르면_진입_검사는_지금처럼_막는다():
    실행 = _예산실행(5_000_000.0)
    실행.margin = None

    까닭 = runs.entry_block(
        실행, runs.Ledger(), side=paper.BUY, open_entry=0, max_hold=9, add_while_open=True,
        gap=False, expiring=False, last_price=100.0,
    )

    assert 까닭 == runs.WHY_MARGIN_UNKNOWN


def test_줄의_묶인_돈과_남은_돈(실행목록):  # noqa: F811
    실행목록.add(**_물음())
    엔진 = 실행목록._engine("run1")
    줄 = 실행목록.rows()[0]
    assert 줄["perContract"] == 2_500_000.0
    assert (줄["marginBudget"], 줄["marginUsed"], 줄["marginLeft"]) == (10_000_000.0, 0.0, 10_000_000.0)

    _체결(엔진, 100.0)
    엔진._send(paper.BUY, 1, 100.0, "entry", _때(10, 0, 1))
    줄 = 실행목록.rows()[0]
    assert 줄["openEntry"] == 1
    assert (줄["marginUsed"], 줄["marginLeft"]) == (2_500_000.0, 7_500_000.0), "열린 진입도 묶입니다."

    엔진.on_book(_호가(100.05, 100.0), at=_때(10, 0, 1) + int(paper.DELAY_SECONDS * 1000) + 1)
    줄 = 실행목록.rows()[0]
    assert (줄["position"], 줄["openEntry"]) == (1, 0)
    assert (줄["marginUsed"], 줄["marginLeft"]) == (2_500_000.0, 7_500_000.0)


def test_계약당_값을_모르면_묶인_돈과_남은_돈이_비어_있다(실행목록):  # noqa: F811
    실행목록.add(**_물음())
    엔진 = 실행목록._engine("run1")
    엔진.run.margin = None
    실행목록._keep_margin = lambda made, facts: None

    줄 = 실행목록.rows()[0]

    assert 줄["perContract"] is None
    assert 줄["marginBudget"] == 10_000_000.0
    assert 줄["marginUsed"] is None and 줄["marginLeft"] is None


def test_예산이_없으면_남은_돈은_비어_있다(실행목록):  # noqa: F811
    실행목록.add(**_물음())
    실행목록._engine("run1").run.margin_budget = None

    줄 = 실행목록.rows()[0]

    assert 줄["marginBudget"] is None and 줄["marginUsed"] == 0.0 and 줄["marginLeft"] is None


# ── 예상 주문가 ─────────────────────────────────────────


def _양쪽(**aux) -> dict:
    설정 = _설정(**aux)
    설정["rules"]["sellEntry"] = _규칙(_조건(op="lt", right="99"))
    return 설정


@pytest.mark.parametrize(
    "aux",
    [
        {"orderType": "시장가"},
        {"orderType": "지정가", "priceBasis": "신호가 + 1틱"},
        {"orderType": "지정가", "buyPriceBasis": "신호가 − 1틱", "sellPriceBasis": "신호가"},
        {"orderType": "STOP-M", "stopBasis": "신호가 + 1틱"},
        {"orderType": "STOP-L", "priceBasis": "신호가", "stopBasis": "신호가 − 1틱"},
    ],
    ids=["시장가", "지정가", "방향별_기준", "STOP-M", "STOP-L"],
)
def test_예상_주문가는_지금_가격으로_실제_주문과_같은_값이다(aux):
    엔진 = _엔진(_양쪽(**aux))
    _체결(엔진, 100.03)

    예상 = 엔진.expected_prices()

    assert set(예상) == {paper.BUY, paper.SELL, "exit"}
    assert 예상["exit"] is None, "보유가 없으면 청산 칸은 비어 있습니다."
    for side in (paper.BUY, paper.SELL):
        엔진._send(side, 1, 100.03, "entry", _때(10, 0, 1))
        낸것 = 엔진.book.orders[-1]
        assert 예상[side] == {"orderType": aux["orderType"], "price": 낸것.price, "stopPrice": 낸것.stop_price}
        엔진.book.cancel(낸것, "시험")
    if aux["orderType"] in engine.NO_PRICE:
        assert 예상[paper.BUY]["price"] is None


def test_규칙이_없는_방향도_늘_낸다():
    설정 = _설정(orderType="지정가", priceBasis="신호가")
    설정["rules"]["sellEntry"] = {"on": True, "steps": [{"id": "s1", "join": "all", "withinBars": 0, "conds": []}]}
    엔진 = _엔진(설정)
    _체결(엔진, 100.0)

    예상 = 엔진.expected_prices()

    assert set(예상) == {paper.BUY, paper.SELL, "exit"}
    assert 예상[paper.SELL] == {"orderType": "지정가", "price": 100.0, "stopPrice": None}


@pytest.mark.parametrize(
    ("aux", "보유방향"),
    [
        ({"orderType": "시장가"}, paper.BUY),
        ({"orderType": "지정가", "buyPriceBasis": "신호가 + 1틱", "sellPriceBasis": "신호가 − 1틱"}, paper.BUY),
        ({"orderType": "지정가", "buyPriceBasis": "신호가 + 1틱", "sellPriceBasis": "신호가 − 1틱"}, paper.SELL),
        ({"orderType": "STOP-L", "priceBasis": "신호가", "stopBasis": "신호가 + 1틱"}, paper.SELL),
    ],
    ids=["시장가", "지정가_매수보유", "지정가_매도보유", "STOP-L_매도보유"],
)
def test_보유_중_청산_칸은_청산_규칙이_실제로_내는_주문과_같다(aux, 보유방향):
    엔진 = _엔진(_설정(**aux), state=runs.HOLDING)
    _체결(엔진, 100.03)
    엔진.ledger.add({"side": 보유방향, "quantity": 2, "price": 100.0, "time": 1})

    예상 = 엔진.expected_prices()
    엔진._close(2, 100.03, engine.RULE_EXIT, _때(10, 0, 1))
    낸것 = 엔진.book.orders[-1]

    assert 예상["exit"] == {
        "side": 낸것.side, "orderType": 낸것.order_type, "price": 낸것.price, "stopPrice": 낸것.stop_price,
    }
    assert 낸것.side != 보유방향 and 낸것.quantity == 2
    assert {k: v for k, v in 예상["exit"].items() if k != "side"} == 예상[낸것.side], "같은 셈입니다."


def test_마지막_체결가를_모르면_값이_비어_있다():
    엔진 = _엔진(_양쪽())
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})

    assert 엔진.expected_prices() == {paper.BUY: None, paper.SELL: None, "exit": None}


# ── 줄의 칸 ───────────────────────────────────────────


def test_값을_못_꺼낸_줄에도_새_칸이_있고_비어_있다(실행목록):  # noqa: F811
    실행목록.add(**_물음())

    줄 = 실행목록.bare_row(실행목록._engine("run1"))

    assert all(name in 줄 and 줄[name] is None for name in 새칸)
    assert set(줄) == set(실행목록.rows()[0]), "성한 줄과 칸이 같습니다."
    assert set(새칸) <= set(service_lib._UNKNOWN)


def test_조회_줄과_방송_줄이_같은_칸이다(실행목록):  # noqa: F811
    실행목록.add(**_물음())
    엔진 = 실행목록._engine("run1")
    _체결(엔진, 100.0)
    엔진.on_book(_호가(100.05, 100.0), at=_때(10, 0, 5))
    허브 = _허브()
    펌프 = pump_lib.RunPump(실행목록, hub=허브, auction=lambda *_, **__: None)

    방송 = 펌프.beat(at=_때(10, 0, 6))
    (방송줄,) = 방송["runs"]
    조회줄 = 실행목록.snapshot("run1")["run"]

    assert set(방송줄) == set(조회줄)
    for name in 새칸:
        assert 방송줄[name] == 조회줄[name], name
    assert 방송줄["bid1"] == 100.0 and 방송줄["ask1"] == 100.05
    assert 방송줄["quoteAt"] == _때(10, 0, 5)
    시장가 = {"orderType": "시장가", "price": None, "stopPrice": None}
    assert 방송줄["expectedOrder"] == {paper.BUY: 시장가, paper.SELL: 시장가, "exit": None}
