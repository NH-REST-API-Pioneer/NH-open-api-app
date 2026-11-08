"""스프레드 주문 장부 — 종이 체결가·수수료, 모의 계좌 체결·거부·결과 모름·대조·다리별 거래소 코드·자물쇠."""
import threading
from datetime import datetime

import pytest

from backend.nh_api.errors import BusinessError, TransportError
from backend.team_pyrun.journal import Journal
from backend.team_spread.book import AccountBook, PaperBook
from backend.team_spread.ctx import Halted, OrderRejected
from backend.team_spread.feed import Quote
from backend.team_spread.legs import Leg, LegError
from tests.test_team_pyrun_markets import FakeOvsApi

NOW = datetime(2026, 11, 9, 10, 15, 0)
SYM_A, SYM_B = "MKUX26", "MKUZ26"
A = Leg("a", SYM_A, "MKU", "overseas", "FSGX", "USD", 0.0001, 2.5, "202611")
B = Leg("b", SYM_B, "MKU", "overseas", "FCME", "USD", 0.0001, 2.5, "202612")
DOM = Leg("d", "A756B000", "A75", "domestic", "KRX", "KRW", 0.1, 1000.0, "20261112")


class Feed:
    def __init__(self, **quotes):
        self.quotes = quotes

    def quote(self, leg):
        return self.quotes.get(leg.name, Quote(0.7447, 0.7446, 0.7448, NOW))

    def now(self):
        return NOW

    def is_open(self, leg, now):
        return leg.name not in getattr(self, "closed", ())

    def history(self, legs, count):
        return []


class ApiFor:
    """다리 종목마다 가짜 api 하나 — `adapter_for` 가 받은 api 모듈 자리에 꽂는다."""

    def __init__(self, fakes):
        self.fakes = fakes


def jr(tmp_path):
    return Journal(tmp_path / "j.jsonl")


def make_fake(sym):
    f = FakeOvsApi()
    f.sym = sym
    return f


def account(tmp_path, fakes=None, feed=None, positions=None):
    """다리 a·b 각각 가짜 하나. 가짜는 MKUX26 로 고정이라 브로커 종목도 그 이름이 되게 sym 을 맞춘 다리를 쓴다."""
    fakes = fakes or {"a": FakeOvsApi(), "b": FakeOvsApi()}
    legs = {"a": Leg("a", "MKUX26", "MKU", "overseas", "FSGX", "USD", 0.0001, 2.5, "202611"),
            "b": Leg("b", "MKUX26", "MKU", "overseas", "FCME", "USD", 0.0001, 2.5, "202612")}
    book = AccountBook(legs, feed or Feed(), jr(tmp_path), api_module=object(), sleep=lambda s: None, today="20261109",
                       positions=positions, now=lambda: NOW)
    # 다리마다 다른 가짜 api 를 꽂는다 — 어댑터 만들기는 진짜 경로(`_broker`)를 그대로 쓰고, 속의 api 만 바꾼다
    for name, leg in legs.items():
        b = book._broker(leg)
        b.api.api = fakes[name]
    book._fees.clear()
    for leg in legs.values():
        book._seed_fee(leg)      # 가짜 api 를 꽂은 뒤 시작 fee 를 심는다
    return book, legs, fakes


# ---------------------------------------------------------------- 종이
def test_종이_매수는_ask_매도는_bid_수수료는_시장값_곱_계약수(tmp_path):
    book = PaperBook(Feed(), jr(tmp_path))
    f = book.order(A, 3, "진입")
    assert (f.leg, f.qty, f.price, f.fee) == ("a", 3, 0.7448, 6.0)
    f = book.order(A, -1, "청산")
    assert (f.qty, f.price, f.fee) == (-1, 0.7446, 2.0)
    assert book.position(A) == 2
    assert book.order(DOM, 2, "x").fee == 1380.0


def test_종이_호가가_없으면_마지막_체결가에서_한_틱_불리하게(tmp_path):
    book = PaperBook(Feed(a=Quote(0.7447, None, None, NOW)), jr(tmp_path))
    assert book.order(A, 1, "x").price == pytest.approx(0.7448)
    assert book.order(A, -1, "x").price == pytest.approx(0.7446)


def test_종이_시세가_전혀_없으면_거부(tmp_path):
    book = PaperBook(Feed(a=Quote(None, None, None, NOW)), jr(tmp_path))
    with pytest.raises(OrderRejected):
        book.order(A, 1, "x")
    assert book.position(A) == 0


def test_종이_멈춤이면_Halted(tmp_path):
    book = PaperBook(Feed(), jr(tmp_path))
    book.halt("까닭")
    book.halt("두 번째")
    assert book.halted == "까닭"
    with pytest.raises(Halted):
        book.order(A, 1, "x")


# ---------------------------------------------------------------- 모의 계좌
def test_계좌_체결은_다리별_종목으로_한_번_주문하고_보유를_갱신(tmp_path):
    book, legs, fakes = account(tmp_path)
    f = book.order(legs["a"], 2, "진입")
    assert (f.leg, f.qty) == ("a", 2) and f.fee == 2.0      # 시작 fee 를 심어 두어 첫 체결도 수수료를 안다
    assert fakes["a"].orders == [("MKUX26", "buy", 2)] and fakes["b"].orders == []
    assert book.position(legs["a"]) == 2
    f = book.order(legs["a"], -2, "청산")
    assert f.qty == -2 and f.fee == 2.0 and book.position(legs["a"]) == 0


def test_계좌_알려진_거부는_OrderRejected_멈춤_아님(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False
    fakes["a"].order_error = BusinessError("overseas_order", "E1", "거부", {})
    with pytest.raises(OrderRejected):
        book.order(legs["a"], 1, "진입")
    assert book.halted is None and book.position(legs["a"]) == 0
    assert len(fakes["a"].orders) == 1


def test_계좌_결과_모름_잔고가_설명하면_잔고를_따라_Fill(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False
    fakes["a"].order_error = TransportError("overseas_order", "응답 없음")
    def lost(sym, side, qty=1):
        fakes["a"].orders.append((sym, side, qty))
        fakes["a"].held = 1       # 사실은 들어갔는데 응답이 없었다
        raise TransportError("overseas_order", "응답 없음")
    fakes["a"].ovs_market_order = lost
    f = book.order(legs["a"], 1, "진입")
    assert (f.qty, f.price) == (1, 0.7448)      # 기준가(반대 호가)
    assert book.position(legs["a"]) == 1 and book.halted is None
    assert len(fakes["a"].orders) == 1


def test_계좌_결과_모름_잔고가_그대로면_멈춤_이후_모든_다리_Halted_브로커_안_부름(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False
    fakes["a"].order_error = TransportError("overseas_order", "응답 없음")
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")
    assert book.halted
    sent = {k: len(v.orders) for k, v in fakes.items()}
    calls = {k: len(v.calls) for k, v in fakes.items()}
    for leg in legs.values():
        with pytest.raises(Halted):
            book.order(leg, 1, "또")
    assert {k: len(v.orders) for k, v in fakes.items()} == sent
    assert {k: len(v.calls) for k, v in fakes.items()} == calls


def test_계좌_결과_모름_잔고가_엉뚱하면_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False
    fakes["a"].order_error = TransportError("overseas_order", "응답 없음")
    fakes["a"].held = 5       # 이 주문으로 설명 안 됨
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")
    assert book.halted


def test_계좌_Fill_수량은_요청을_넘지_않는다_넘는_잔고는_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False
    fakes["a"].order_error = TransportError("overseas_order", "응답 없음")
    fakes["a"].held = 3       # 1계약 주문인데 3 — 설명이 안 된다
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")


def test_계좌_브로커가_예외를_내면_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path)

    class Boom:
        def fill(self, *a, **k):
            raise RuntimeError("기록 실패")
    book._brokers[("a", "MKUX26")] = Boom()
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "x")
    assert book.halted


def test_계좌_reconcile_같으면_None_다르면_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path)
    book.order(legs["a"], 1, "진입")
    assert book.reconcile() is None
    fakes["b"].held = 2
    reason = book.reconcile()
    assert reason and "b" in reason and book.halted == reason
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "x")


def test_계좌_balances와_못_읽으면_LegError(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].held, fakes["b"].held = 2, -1
    assert book.balances() == {"a": 2, "b": -1}
    fakes["b"].oi_pages = []        # 조회가 터지게 (키 없음)
    with pytest.raises(LegError):
        book.balances()


def test_계좌_다리마다_그_다리_거래소_코드의_어댑터(tmp_path):
    book, legs, _ = account(tmp_path)
    assert book._broker(legs["a"]).api.exch_cd == "FSGX"
    assert book._broker(legs["b"]).api.exch_cd == "FCME"
    assert book._broker(legs["b"]).api.cur_cd == "USD"


def test_계좌_주문과_reconcile은_자물쇠로_차례(tmp_path):
    book, legs, fakes = account(tmp_path)
    inside, release = threading.Event(), threading.Event()
    real = fakes["a"].ovs_market_order

    def slow(sym, side, qty=1):
        inside.set()
        assert release.wait(5)
        return real(sym, side, qty)
    fakes["a"].ovs_market_order = slow
    got = {}
    t1 = threading.Thread(target=lambda: book.order(legs["a"], 1, "진입"))
    t1.start()
    assert inside.wait(5)
    t2 = threading.Thread(target=lambda: got.setdefault("r", book.reconcile()))
    t2.start()
    t2.join(0.3)
    assert t2.is_alive() and "r" not in got      # 진행 중인 주문이 끝나기를 기다린다
    release.set()
    t1.join(5)
    t2.join(5)
    assert got["r"] is None and book.position(legs["a"]) == 1    # 주문이 반영된 뒤 대조 → 일치


# ---------------------------------------------------------------- 리뷰 1회 수정
def test_수정1_잔고_관문_거절은_다시_읽어_같으면_OrderRejected_멈춤_아님(tmp_path):
    book, legs, fakes = account(tmp_path)
    reads = {"n": 0}
    real = fakes["a"].ovs_open_interest_page

    def flaky(nxt_key=""):
        reads["n"] += 1
        if reads["n"] == 1:
            raise TransportError("overseas_open_interest", "일시 실패")     # 관문의 첫 읽기만 실패
        return real(nxt_key)
    fakes["a"].ovs_open_interest_page = flaky
    with pytest.raises(OrderRejected):
        book.order(legs["a"], 1, "진입")
    assert book.halted is None and fakes["a"].orders == []


def test_수정1_알려진_거부_뒤_잔고가_움직였으면_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False

    def reject_but_moved(sym, side, qty=1):
        fakes["a"].orders.append((sym, side, qty))
        fakes["a"].held = 4
        raise BusinessError("overseas_order", "E1", "거부", {})
    fakes["a"].ovs_market_order = reject_but_moved
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")
    assert book.halted and "a(MKUX26)" in book.halted


def test_수정2_보내기_직전_장이_닫혔으면_OrderRejected_아무것도_안_보냄(tmp_path):
    feed = Feed()
    feed.closed = ("a",)
    book, legs, fakes = account(tmp_path, feed=feed)
    with pytest.raises(OrderRejected):
        book.order(legs["a"], 1, "진입")
    assert fakes["a"].orders == [] and book.halted is None


def test_수정3_reconcile_못_읽음은_주기_대조는_넘어가고_끝_확인은_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["b"].oi_pages = []        # 읽기가 터진다
    assert book.reconcile() is None and book.halted is None
    reason = book.reconcile(strict=True)
    assert reason and "확인 못 함" in reason and book.halted == reason


def test_수정4_같은_통화_두_다리의_수수료는_누적을_나눠_차이를_낸다(tmp_path):
    total = {"fee": 10.0}       # 같은 통화 예수금은 한 계좌 — 보유는 다리마다지만 fee 누적은 하나

    class SharedFee(FakeOvsApi):
        fee = property(lambda self: total["fee"], lambda self, v: total.__setitem__("fee", v))
    book, legs, _ = account(tmp_path, fakes={"a": SharedFee(), "b": SharedFee()})
    fa = book.order(legs["a"], 1, "a")      # 시작 fee 를 심어 두었으니 첫 체결도 수수료를 안다
    fb = book.order(legs["b"], -1, "b")
    fa2 = book.order(legs["a"], -1, "a")
    assert (fa.fee, fb.fee, fa2.fee) == (2.0, 2.0, 2.0)


def test_수정5_시세를_못_받아도_계좌_주문은_나간다(tmp_path):
    class NoQuote(Feed):
        def quote(self, leg):
            raise RuntimeError("시세 끊김")
    book, legs, fakes = account(tmp_path, feed=NoQuote())
    f = book.order(legs["a"], 1, "진입")
    assert f.qty == 1 and len(fakes["a"].orders) == 1


def test_수정6_멈춤_까닭에_다리_이름과_종목이_있다(tmp_path):
    book, legs, fakes = account(tmp_path)
    fakes["a"].fill = False
    fakes["a"].order_error = TransportError("overseas_order", "응답 없음")
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")
    assert "a(MKUX26)" in book.halted
    import json
    rows = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert any("a(MKUX26)" in r.get("text", "") for r in rows if r["kind"] == "event")


def test_수정6_체결_줄에_다리와_종목이_붙는다(tmp_path):
    book, legs, _ = account(tmp_path)
    book.order(legs["a"], 1, "진입")
    import json
    rows = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert any(r.get("leg") == "a" and r.get("sym") == "MKUX26" and r.get("qty") == 1 for r in rows)


# ---------------------------------------------------------------- 리뷰 2회 수정
def _unread_price(fake):
    """체결은 되지만 주문내역에서 체결가를 읽을 수 없는 가짜 (두 가격 칸이 0)."""
    real = fake.ovs_market_order

    def go(sym, side, qty=1):
        r = real(sym, side, qty)
        for h in fake.history:
            h["exec_pric"] = h["ord_avg_pric"] = "0"
        return r
    fake.ovs_market_order = go


class BarFeed(Feed):
    def __init__(self, close=None, fail=True):
        super().__init__()
        self.close, self.fail = close, fail

    def quote(self, leg):
        if self.fail:
            raise RuntimeError("시세 끊김")
        return super().quote(leg)

    def history(self, legs, count):
        from types import SimpleNamespace as NS
        return [] if self.close is None else [NS(legs={legs[0].name: NS(close=self.close)})]


def test_수정A_체결가를_못_읽고_시세도_실패하면_마지막_봉_종가_price_known_False(tmp_path):
    book, legs, fakes = account(tmp_path, feed=BarFeed(close=0.7500))
    _unread_price(fakes["a"])
    f = book.order(legs["a"], 1, "진입")
    assert f.price == 0.7500 and f.price_known is False and book.halted is None


def test_수정A_읽은_체결가는_price_known_True(tmp_path):
    book, legs, _ = account(tmp_path)
    assert book.order(legs["a"], 1, "진입").price_known is True


def test_수정A_양의_기준가가_하나도_없으면_잔고를_따르고_멈춤_0_Fill_없음(tmp_path):
    book, legs, fakes = account(tmp_path, feed=BarFeed(close=None))
    _unread_price(fakes["a"])
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")
    assert book.position(legs["a"]) == 1
    assert "체결가 모름" in book.halted and "a(MKUX26)" in book.halted


def test_수정A_결과_모름_잔고_따르기에서도_기준가가_없으면_멈춤(tmp_path):
    book, legs, fakes = account(tmp_path, feed=BarFeed(close=None))

    def lost(sym, side, qty=1):
        fakes["a"].orders.append((sym, side, qty))
        fakes["a"].held = 1
        raise TransportError("overseas_order", "응답 없음")
    fakes["a"].ovs_market_order = lost
    with pytest.raises(Halted):
        book.order(legs["a"], 1, "진입")
    assert book.position(legs["a"]) == 1 and "체결가 모름" in book.halted


def test_수정A_0_이하_기준가는_저장하지_않고_다음에도_쓰지_않는다(tmp_path):
    feed = Feed(a=Quote(0.0, 0.0, 0.0, NOW))
    book, legs, _ = account(tmp_path, feed=feed)
    book.order(legs["a"], 1, "진입")
    assert "a" not in book._last_ref
    assert all(v > 0 for v in book._last_ref.values())


def test_수정A_0으로_채운_호가는_없는_값으로_본다(tmp_path):
    book = PaperBook(Feed(a=Quote(0.7447, 0.0, 0.0, NOW)), jr(tmp_path))
    assert book.order(A, 1, "x").price == pytest.approx(0.7448)     # 마지막 + 1틱
    book = PaperBook(Feed(a=Quote(0.0, 0.0, 0.0, NOW)), jr(tmp_path))
    with pytest.raises(OrderRejected):
        book.order(A, 1, "x")


def test_수정B_브로커가_쓴_줄에도_다리와_종목이_붙는다(tmp_path):
    import json
    book, legs, fakes = account(tmp_path)
    book.order(legs["b"], 1, "진입")
    rows = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    broker_rows = [r for r in rows if r["kind"] == "order"]
    assert broker_rows and all(r.get("leg") == "b" and r.get("sym") == "MKUX26" for r in broker_rows)
