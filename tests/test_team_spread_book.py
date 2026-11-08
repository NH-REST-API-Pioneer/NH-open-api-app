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
    assert (f.leg, f.qty) == ("a", 2) and f.fee is None      # 첫 체결은 이전 fee 를 몰라 수수료 모름
    assert fakes["a"].orders == [("MKUX26", "buy", 2)] and fakes["b"].orders == []
    assert book.position(legs["a"]) == 2
    f = book.order(legs["a"], -2, "청산")
    assert f.qty == -2 and f.fee == 2.0 and book.position(legs["a"]) == 0


def test_계좌_알려진_거부는_OrderRejected_멈춤_아님(tmp_path):
    book, legs, fakes = account(tmp_path)
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
