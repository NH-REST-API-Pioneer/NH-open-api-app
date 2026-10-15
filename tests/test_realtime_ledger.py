"""구독 장부와 스무 자리 나누기."""
from __future__ import annotations

from backend.realtime.feeds import Feed
from backend.realtime.ledger import Ledger, stream_key


def quote(sym: str, context: str = "domestic-day") -> Feed:
    return Feed(context, "quote", sym)


def test_한_화면이_원하는_것을_통째로_적는다():
    book = Ledger()
    book.declare("screen", {quote("A"): 1, quote("B"): 1})
    assert len(book.grant().granted) == 2

    # 다시 적으면 앞서 적은 것은 지워집니다 — 늘리고 줄이는 방식이 아닙니다.
    book.declare("screen", {quote("A"): 1})
    assert len(book.grant().granted) == 1


def test_같은_종목을_여럿이_봐도_구독은_하나다():
    book = Ledger()
    book.declare("header", {quote("A"): 1})
    book.declare("chart", {quote("A"): 3})

    grant = book.grant()
    assert len(grant.granted) == 1
    assert book.watchers(stream_key(quote("A"))) == 2


def test_화면이_나가면_그_몫이_사라진다():
    book = Ledger()
    book.declare("header", {quote("A"): 1})
    book.declare("home", {quote("B"): 4})

    book.release("home")
    assert {key[2] for key in book.grant().granted} == {"A"}


def test_주간과_야간의_주문알림은_한_자리만_쓴다():
    book = Ledger()
    book.declare("day", {Feed("domestic-day", "orders"): 1})
    book.declare("night", {Feed("domestic-night", "orders"): 1})

    assert len(book.grant().granted) == 1


def test_자리가_모자라면_등급이_낮은_것부터_밀린다():
    book = Ledger()
    book.limit = 3
    book.declare(
        "screen",
        {quote("A"): 1, quote("B"): 2, quote("C"): 4, quote("D"): 9},
    )

    grant = book.grant()
    assert {key[2] for key in grant.granted} == {"A", "B", "C"}
    assert [feed.sym for feed in grant.rejected] == ["D"]


def test_같은_등급이면_먼저_온_것이_남는다():
    book = Ledger()
    book.limit = 2
    book.declare("screen", {quote("A"): 5, quote("B"): 5})
    book.declare("screen", {quote("A"): 5, quote("B"): 5, quote("C"): 5})

    grant = book.grant()
    assert {key[2] for key in grant.granted} == {"A", "B"}
    assert [feed.sym for feed in grant.rejected] == ["C"]


def test_한_화면이라도_급하게_보면_그_구독이_급하다():
    book = Ledger()
    book.limit = 1
    book.declare("home", {quote("A"): 9})
    book.declare("header", {quote("A"): 1, quote("B"): 5})

    grant = book.grant()
    # A 를 급하게 보는 화면이 있으므로 A 가 남습니다.
    assert {key[2] for key in grant.granted} == {"A"}


def test_주문알림은_자리_경쟁에_들어가지_않는다():
    book = Ledger()
    book.limit = 2
    book.declare(
        "screen",
        {
            Feed("domestic-day", "orders"): 9,
            Feed("overseas", "orders"): 9,
            quote("A"): 1,
            quote("B"): 1,
        },
    )

    grant = book.grant()
    kinds = sorted(feed.kind for feed in grant.granted.values())
    # 등급이 가장 낮아도 주문 알림 둘은 남습니다.
    assert kinds.count("orders") == 2
    assert grant.rejected


def test_등급은_범위_안으로_당겨_쓴다():
    book = Ledger()
    book.limit = 1
    book.declare("screen", {quote("A"): -5, quote("B"): 100})

    # -5 는 가장 높은 등급으로, 100 은 가장 낮은 등급으로 당겨집니다.
    assert {key[2] for key in book.grant().granted} == {"A"}


def test_아무도_안_보면_순서_기록도_비운다():
    book = Ledger()
    book.declare("screen", {quote("A"): 1})
    book.grant()
    book.release("screen")
    book.grant()

    assert book._seen == {}
