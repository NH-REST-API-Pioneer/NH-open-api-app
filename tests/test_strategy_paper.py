"""종이거래 체결 모형 `paper-v1`.

**호가와 체결을 손으로 지어 넣습니다.** 모양은 허브가 내는 것 그대로입니다 —
매도는 먼 값부터, 매수는 가까운 값부터 옵니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import paper

기준 = 1_000_000
지연 = int(paper.DELAY_SECONDS * 1000)


def _호가(asks: list[tuple[float, int]], bids: list[tuple[float, int]]) -> dict:
    """허브 모양 — `asks` 는 먼 값부터, `bids` 는 가까운 값부터."""
    return {
        "asks": [{"price": price, "quantity": qty} for price, qty in reversed(asks)],
        "bids": [{"price": price, "quantity": qty} for price, qty in bids],
    }


def _체결(price: float, quantity: int = 1) -> dict:
    return {"price": price, "quantity": quantity}


@pytest.fixture
def 장부():
    return paper.PaperBook()


def test_모형이_못_다루는_주문유형():
    """호가 다섯 단계만으로는 어느 값에 들어갔을지 고를 수 없습니다."""
    assert paper.supported("지정가") is True
    assert paper.supported("시장가") is True
    assert paper.supported("조건부지정가") is False
    assert paper.supported("최유리지정가") is False


def test_지연이_지나기_전에는_안_채운다(장부):
    """의도를 낸 순간의 값으로 채우면 실제보다 좋은 값이 나옵니다."""
    주문 = 장부.place("o1", side=paper.BUY, quantity=1, order_type="시장가", at=기준)

    이른것 = 장부.on_book(_호가([(101.0, 5)], [(100.0, 5)]), at=기준 + 지연 - 1)
    늦은것 = 장부.on_book(_호가([(101.0, 5)], [(100.0, 5)]), at=기준 + 지연)

    assert 이른것 == []
    assert [one["price"] for one in 늦은것] == [101.0]
    assert 주문.status == paper.FILLED


def test_시장가는_단계마다_한_줄씩_먹는다(장부):
    """한 가격에 다 채워지는 모형은 슬리피지를 지웁니다."""
    장부.place("o1", side=paper.BUY, quantity=7, order_type="시장가", at=기준)

    채운것 = 장부.on_book(
        _호가([(101.0, 2), (102.0, 3), (103.0, 9)], [(100.0, 5)]), at=기준 + 지연
    )

    assert [(one["price"], one["quantity"]) for one in 채운것] == [
        (101.0, 2),
        (102.0, 3),
        (103.0, 2),
    ]


def test_표시_잔량을_다_먹고도_남으면_기다렸다_이어_먹는다(장부):
    주문 = 장부.place("o1", side=paper.BUY, quantity=5, order_type="시장가", at=기준)

    먼저 = 장부.on_book(_호가([(101.0, 2)], [(100.0, 9)]), at=기준 + 지연)
    assert 주문.status == paper.PARTIAL and 주문.remaining == 3

    나중 = 장부.on_book(_호가([(101.5, 3)], [(100.0, 9)]), at=기준 + 지연 + 100)

    assert [one["quantity"] for one in 먼저 + 나중] == [2, 3]
    assert 주문.status == paper.FILLED


def test_매도_시장가는_매수호가를_먹는다(장부):
    장부.place("o1", side=paper.SELL, quantity=3, order_type="시장가", at=기준)

    채운것 = 장부.on_book(_호가([(101.0, 9)], [(100.0, 2), (99.0, 5)]), at=기준 + 지연)

    assert [(one["price"], one["quantity"]) for one in 채운것] == [(100.0, 2), (99.0, 1)]


def test_지정가가_도착할_때_이미_유리하면_먹는다(장부):
    """반대 최우선가가 지정가보다 유리한 경우입니다."""
    장부.place("o1", side=paper.BUY, quantity=4, order_type="지정가", price=102.0, at=기준)

    채운것 = 장부.on_book(
        _호가([(101.0, 2), (102.0, 1), (103.0, 9)], [(100.0, 5)]), at=기준 + 지연
    )

    assert [(one["price"], one["quantity"]) for one in 채운것] == [(101.0, 2), (102.0, 1)]
    assert [one["price"] for one in 채운것 if one["price"] > 102.0] == [], "지정가를 넘겨 먹지 않습니다."


def test_불리한_지정가는_줄을_선다(장부):
    """도착 순간 그 가격에 서 있던 잔량이 먼저 채워져야 이 주문 차례입니다."""
    주문 = 장부.place("o1", side=paper.BUY, quantity=2, order_type="지정가", price=100.0, at=기준)
    장부.on_book(_호가([(101.0, 5)], [(100.0, 3), (99.0, 5)]), at=기준 + 지연)

    assert 주문.queue_ahead == 3, "그 가격에 이미 3 계약이 서 있습니다."

    # 닿기만 한 체결 둘 — 앞 순위를 덜어 낼 뿐입니다.
    assert 장부.on_trade(_체결(100.0, 2), at=기준 + 지연 + 10) == []
    assert 주문.filled == 0

    채운것 = 장부.on_trade(_체결(100.0, 3), at=기준 + 지연 + 20)

    assert [(one["price"], one["quantity"]) for one in 채운것] == [(100.0, 2)]
    assert 주문.status == paper.FILLED


def test_닿기만_해서는_안_채워진다(장부):
    """「가격이 닿았다」만으로 체결하지 않습니다."""
    주문 = 장부.place("o1", side=paper.BUY, quantity=1, order_type="지정가", price=100.0, at=기준)
    장부.on_book(_호가([(101.0, 5)], [(100.0, 50)]), at=기준 + 지연)

    장부.on_trade(_체결(100.0, 10), at=기준 + 지연 + 10)

    assert 주문.filled == 0 and 주문.status == paper.WAITING


def test_관통해도_앞_순위가_남으면_못_채운다(장부):
    """이 주문의 값을 지난 체결이라도 그 수량은 앞 순위가 먼저 가져갑니다(가정 7)."""
    주문 = 장부.place("o1", side=paper.BUY, quantity=4, order_type="지정가", price=100.0, at=기준)
    장부.on_book(_호가([(101.0, 5)], [(100.0, 99)]), at=기준 + 지연)

    채운것 = 장부.on_trade(_체결(99.5, 1), at=기준 + 지연 + 10)

    assert 채운것 == [] and 주문.filled == 0


def test_관통은_지난_체결_수량만큼만_채운다(장부):
    """앞 순위가 없으면 지난 체결 1계약만큼만 이 주문 몫입니다 — 잔량 전부가 아닙니다."""
    주문 = 장부.place("o1", side=paper.BUY, quantity=10, order_type="지정가", price=100.0, at=기준)
    장부.on_book(_호가([(101.0, 5)], [(99.0, 9)]), at=기준 + 지연)
    assert 주문.queue_ahead == 0

    채운것 = 장부.on_trade(_체결(99.5, 1), at=기준 + 지연 + 10)

    assert [(one["price"], one["quantity"]) for one in 채운것] == [(100.0, 1)]
    assert 주문.remaining == 9 and 주문.status == paper.PARTIAL


def test_매도_지정가는_반대_방향으로_본다(장부):
    주문 = 장부.place("o1", side=paper.SELL, quantity=2, order_type="지정가", price=100.0, at=기준)
    장부.on_book(_호가([(100.0, 3), (101.0, 5)], [(99.0, 5)]), at=기준 + 지연)

    assert 주문.queue_ahead == 3, "매도는 매도호가에 줄을 섭니다."
    채운것 = 장부.on_trade(_체결(100.5, 5), at=기준 + 지연 + 10)

    assert [(one["price"], one["quantity"]) for one in 채운것] == [(100.0, 2)], "위로 관통 5계약, 앞 순위 3 뒤 2."


def test_FOK_은_전량이_안_되면_채운_것도_되돌린다(장부):
    주문 = 장부.place(
        "o1",
        side=paper.BUY,
        quantity=5,
        order_type="지정가",
        price=102.0,
        fill_condition="FOK",
        at=기준,
    )

    채운것 = 장부.on_book(_호가([(101.0, 2), (103.0, 9)], [(100.0, 5)]), at=기준 + 지연)

    assert 채운것 == []
    assert (주문.status, 주문.filled, 주문.fills) == (paper.CANCELLED, 0, [])
    assert "FOK" in 주문.reason


def test_FAK_은_되는_만큼_채우고_잔량을_취소한다(장부):
    주문 = 장부.place(
        "o1",
        side=paper.BUY,
        quantity=5,
        order_type="지정가",
        price=102.0,
        fill_condition="FAK",
        at=기준,
    )

    채운것 = 장부.on_book(_호가([(101.0, 2), (103.0, 9)], [(100.0, 5)]), at=기준 + 지연)

    assert [one["quantity"] for one in 채운것] == [2]
    assert (주문.status, 주문.filled) == (paper.CANCELLED, 2)
    assert "FAK" in 주문.reason


def test_STOP_은_마지막_체결가가_닿아야_발동한다(장부):
    주문 = 장부.place(
        "o1", side=paper.BUY, quantity=2, order_type="STOP-M", stop_price=105.0, at=기준
    )

    # 안 닿았습니다 — 호가가 와도 먹지 않습니다.
    장부.on_trade(_체결(104.0), at=기준 + 지연)
    assert 장부.on_book(_호가([(104.5, 9)], [(104.0, 9)]), at=기준 + 지연 + 10) == []
    assert 주문.armed is False

    장부.on_trade(_체결(105.0), at=기준 + 지연 + 20)
    채운것 = 장부.on_book(_호가([(105.5, 9)], [(105.0, 9)]), at=기준 + 지연 + 30)

    assert 주문.armed is True
    assert [(one["price"], one["quantity"]) for one in 채운것] == [(105.5, 2)]


def test_한_호가의_여러_단계를_먹으면_체결번호가_갈린다(장부):
    """**같은 밀리초에 여러 줄이 납니다.** 시각을 열쇠로 쓰면 화면에서 하나로
    뭉쳐, 세 계약이 한 계약으로 보입니다.
    """
    장부.place("o1", side=paper.BUY, quantity=3, order_type="시장가", at=기준)
    때 = 기준 + 지연

    채운것 = 장부.on_book(_호가([(100.0, 1), (100.5, 2)], [(99.0, 9)]), at=때)

    assert [one["quantity"] for one in 채운것] == [1, 2], "단계마다 한 줄입니다."
    assert [one["time"] for one in 채운것] == [때, 때], "같은 밀리초입니다."
    assert [one["execNo"] for one in 채운것] == ["o1#1", "o1#2"]


def test_공백_동안에는_아무것도_안_채운다(장부):
    """끊긴 구간의 값을 모르는데 채우면 없던 체결이 생깁니다."""
    주문 = 장부.place("o1", side=paper.BUY, quantity=1, order_type="시장가", at=기준)
    장부.gap = True

    assert 장부.on_book(_호가([(101.0, 5)], [(100.0, 5)]), at=기준 + 지연) == []
    assert 장부.on_trade(_체결(101.0), at=기준 + 지연) == []
    assert 주문.status == paper.WAITING

    장부.gap = False
    assert 장부.on_book(_호가([(101.0, 5)], [(100.0, 5)]), at=기준 + 지연 + 10) != []


def test_공백_중에도_마지막_체결가는_따라간다(장부):
    """손절 감시가 다시 볼 값입니다. 채우지 않는 것과 안 보는 것은 다릅니다."""
    장부.gap = True

    장부.on_trade(_체결(107.0), at=기준)

    assert 장부.last_price == 107.0


def test_세션이_끝나면_대기_주문을_취소한다(장부):
    """밤새 걸어 둔 주문이 아침에 채워지는 모양은 실제와 다릅니다."""
    장부.place("o1", side=paper.BUY, quantity=1, order_type="지정가", price=1.0, at=기준)
    장부.place("o2", side=paper.BUY, quantity=1, order_type="시장가", at=기준)
    장부.on_book(_호가([(101.0, 5)], [(100.0, 5)]), at=기준 + 지연)

    끊은것 = 장부.cancel_open("세션이 끝나 취소했습니다")

    assert [one.id for one in 끊은것] == ["o1"], "이미 채워진 주문은 건드리지 않습니다."
    assert 장부.open_orders == []


def test_종이_체결은_시장의_마지막_가격을_흔들지_않는다(장부):
    """모형이 지어낸 값이라 STOP 발동과 손절 감시가 그것을 보면 안 됩니다."""
    장부.place("o1", side=paper.BUY, quantity=1, order_type="시장가", at=기준)
    장부.on_trade(_체결(100.0), at=기준 + 지연)

    장부.on_book(_호가([(120.0, 5)], [(100.0, 5)]), at=기준 + 지연 + 10)

    assert 장부.last_price == 100.0


def test_수수료는_계약당이다():
    assert paper.fee_of(3, 2000.0) == 6000.0
    assert paper.fee_of(0, 2000.0) == 0.0


def test_증거금을_모르면_계약_수도_모른다():
    """0 으로 답하면 「한 계약도 못 든다」는 뜻이 됩니다."""
    assert paper.max_contracts(10_000_000, 2_500_000) == 4
    assert paper.max_contracts(10_000_000, 4_000_000) == 2, "남는 돈으로 한 계약을 더 들지 않습니다."
    assert paper.max_contracts(10_000_000, None) is None, "해외는 아직 증거금 칸이 없습니다."
    assert paper.max_contracts(None, 2_500_000) is None
