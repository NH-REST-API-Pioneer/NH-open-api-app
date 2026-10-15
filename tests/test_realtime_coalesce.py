"""모았다가 한 번에 보내기."""
from __future__ import annotations

from backend.realtime.coalesce import Coalescer
from backend.realtime.feeds import Feed
from backend.realtime.ledger import stream_key

QUOTE = Feed("domestic-day", "quote", "A7569000")
BOOK = Feed("domestic-day", "book", "A7569000")
ORDERS = Feed("domestic-day", "orders")


def tick(price: str, quantity: str = "1", clock: str = "090000") -> dict:
    return {
        "tick_div": "1",
        "last_pric": price,
        "exec_qty": quantity,
        "exch_tm": clock,
        "exec_div": "1",
    }


def test_시세는_마지막_값만_남고_체결은_전부_모인다():
    mixer = Coalescer()
    mixer.add(QUOTE, tick("100"))
    mixer.add(QUOTE, tick("101"))
    mixer.add(QUOTE, tick("102"))

    (key, message), = mixer.drain()
    assert key == stream_key(QUOTE)
    assert message["patch"]["last"] == 102
    assert [trade["price"] for trade in message["trades"]] == [100, 101, 102]


def test_체결이_아닌_메시지도_시세는_갈아_끼운다():
    mixer = Coalescer()
    mixer.add(QUOTE, {"tick_div": "0", "last_pric": "100", "exec_qty": "0"})

    (_, message), = mixer.drain()
    assert message["patch"]["last"] == 100
    assert message["trades"] == []


def test_호가는_마지막_모습만_남는다():
    mixer = Coalescer()
    mixer.add(BOOK, {"ask_pric_1": "10", "ask_qty_1": "1"})
    mixer.add(BOOK, {"ask_pric_1": "11", "ask_qty_1": "2"})

    (_, message), = mixer.drain()
    assert message["asks"] == [{"price": 11, "quantity": 2}]


def test_주문알림은_한_건도_버리지_않는다():
    mixer = Coalescer()
    for status in ("1", "3", "6"):
        mixer.add(ORDERS, {"ord_no": "7", "ord_sts": status, "trd_div": "1"})

    (_, message), = mixer.drain()
    assert [event["statusCode"] for event in message["events"]] == ["1", "3", "6"]


def test_꺼내고_나면_비워진다():
    mixer = Coalescer()
    mixer.add(QUOTE, tick("100"))
    assert mixer.drain()
    assert mixer.drain() == []
    assert len(mixer) == 0


def test_그만_본_구독의_남은_값은_버린다():
    mixer = Coalescer()
    mixer.add(QUOTE, tick("100"))
    mixer.add(BOOK, {"ask_pric_1": "10", "ask_qty_1": "1"})

    mixer.drop(stream_key(QUOTE))
    kinds = [message["type"] for _, message in mixer.drain()]
    assert kinds == ["book"]


def test_주문알림은_그만_봐도_버리지_않는다():
    """화면이 그만 보겠다고 한 것과 체결이 안 일어난 것은 다릅니다."""
    mixer = Coalescer()
    mixer.add(ORDERS, {"ord_no": "7", "ord_sts": "6"})

    mixer.drop(stream_key(ORDERS))
    assert [message["type"] for _, message in mixer.drain()] == ["orders"]


def test_주간과_야간의_주문알림이_한_자리에_모인다():
    mixer = Coalescer()
    mixer.add(Feed("domestic-day", "orders"), {"ord_no": "1", "ord_sts": "1"})
    mixer.add(Feed("domestic-night", "orders"), {"ord_no": "2", "ord_sts": "1"})

    drained = mixer.drain()
    assert len(drained) == 1
    assert len(drained[0][1]["events"]) == 2
    assert drained[0][1]["market"] == "domestic"


def test_바뀐_것이_없으면_보내지_않는다():
    mixer = Coalescer()
    mixer.add(QUOTE, {})
    assert mixer.drain() == []


def test_야간_시세는_모아_보내도_현물가와_베이시스가_null_로_나간다():
    """주간과 야간 시세는 다른 구독이라 한 자리에서 섞이지 않습니다 — 야간 메시지만으로
    현물가·베이시스 칸이 `null` 로 나가야 화면이 주간에 받아 둔 값을 지웁니다."""
    야간 = Feed("domestic-night", "quote", "A016C000")
    주간 = Feed("domestic-day", "quote", "A016C000")
    assert stream_key(야간) != stream_key(주간)

    mixer = Coalescer()
    mixer.add(야간, {**tick("1102.20"), "und_last_pric": "560.74", "mkt_bas": "541.46"})
    mixer.add(야간, {**tick("1101.85"), "und_last_pric": "560.74", "mkt_bas": "541.11"})

    (_, message), = mixer.drain()
    assert message["patch"]["last"] == 1101.85
    assert "spot" in message["patch"] and message["patch"]["spot"] is None
    assert "basisActual" in message["patch"] and message["patch"]["basisActual"] is None

