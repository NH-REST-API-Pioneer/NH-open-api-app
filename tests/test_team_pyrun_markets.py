"""시장 묶음(`markets.py`) 시험 — 시장 고르기·휴장·어댑터, 그리고 해외 어댑터 위의 `MockAccountBroker`.

해외 주문 경로가 국내와 **같은 규칙**(주문 한 번·체결 확인·잔고 관문·`blind`·`unresolved`·「확인 필요」)으로
도는지 가짜 해외 api 로 봅니다. 가짜는 `api.py` 의 `ovs_*` 이름만 가지고 있어서, 어댑터가 국내 함수를
부르면 바로 드러납니다. 실제로 쉬지 않고, NH 서버로는 아무것도 나가지 않습니다.
"""
import json

import pytest

from backend.nh_api.errors import BusinessError, TransportError
from backend.team_pyrun import api as real_api
from backend.team_pyrun import markets
from backend.team_pyrun.broker import MockAccountBroker
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, PagesLeft, adapter, as_adapter, in_break, market_of
from tests.test_team_pyrun_live import SYM as KRX_SYM
from tests.test_team_pyrun_live import TODAY, FakeApi, at, bar, make_run

MKU = "MKUX26"


def lines(path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


class FakeOvsApi:
    """`api.py` 의 해외(`ovs_`) 이름만 가진 가짜. 받은 호출과 주문을 적는다.

    `fill` 이 True 면 주문마다 주문내역에 전체체결(6) 줄을 넣고 잔고를 움직이며 예수금 fee 를 US$2 올린다.
    칸 이름은 `api.py` 해외 함수 설명의 근거(운영자 overseas_account·week03)와 같다."""

    rows = staticmethod(real_api.rows)
    num = staticmethod(real_api.num)
    ovs_net_position = staticmethod(real_api.ovs_net_position)
    ovs_fill_price = staticmethod(real_api.ovs_fill_price)
    mku_spec = staticmethod(real_api.mku_spec)
    OVS_FILLED = real_api.OVS_FILLED
    OVS_REJECTED = real_api.OVS_REJECTED

    def __init__(self):
        self.calls: list[tuple] = []
        self.orders: list[tuple] = []
        self.held = 0
        self.fee = 0.0
        self.last = "0.7447"
        self.history: list[dict] = []
        self.fill = True
        self.status = "6"               # 주문마다 넣는 주문내역 줄의 상태
        self.reply: dict | None = None  # 있으면 주문 답을 이것으로
        self.order_error: Exception | None = None
        self.oi_pages: list | None = None    # 있으면 잔고 쪽들 {키: (줄, 다음 키)}
        self.hist_pages: list | None = None  # 있으면 주문내역 쪽들 {키: (줄, 다음 키)}

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def ovs_chart_minute(self, sym, *, req_qty):
        self.calls.append(("ovs_chart_minute", sym, req_qty))
        return []

    def ovs_price(self, sym):
        self.calls.append(("ovs_price", sym))
        return {"last_pric": self.last, "sym": sym}

    def ovs_product_detail(self):
        self.calls.append(("ovs_product_detail",))
        return [{"prd_cd": "KU", "tick_unt": "0.00005", "tick_val": "6.25"},
                {"prd_cd": "MKU", "tick_unt": "00000000000000000000.000100000", "tick_val": "00000000000000002.50000000"}]

    def ovs_deposit(self, cur_cd="USD", *, biz_dt=""):
        self.calls.append(("ovs_deposit", cur_cd, biz_dt))
        return {"fee": f"{self.fee:018.2f}", "fut_fee": f"{self.fee:.2f}", "cls_pl_amt": "0",
                "ord_psb_amt": "50000", "cust_acnt_no": "123456789"}

    def ovs_open_interest_page(self, nxt_key=""):
        self.calls.append(("ovs_open_interest_page", nxt_key))
        if self.oi_pages is not None:
            return self.oi_pages[nxt_key]
        if not self.held:
            return [], ""
        return [{"sym": MKU, "trd_tp": "1" if self.held > 0 else "2", "opint_qty": str(abs(self.held)),
                 "cust_acnt_no": "123456789"}], ""

    def ovs_order_history_page(self, nxt_key=""):
        self.calls.append(("ovs_order_history_page", nxt_key))
        if self.hist_pages is not None:
            return self.hist_pages[nxt_key]
        return [dict(r) for r in self.history], ""

    def ovs_market_order(self, sym, side, qty=1):
        self.calls.append(("ovs_market_order", sym, side, qty))
        self.orders.append((sym, side, qty))
        no = f"{len(self.orders):010d}"
        if self.fill:
            if self.status == "6":
                self.held += qty if side == "buy" else -qty
                self.fee += 2.0
            px = float(self.last) + (0.0001 if side == "buy" else -0.0001)
            self.history.insert(0, {"ord_no": no, "sym": sym, "ord_sts": self.status, "trd_tp": "1",
                                    "exec_qty": "1", "exec_pric": f"{px:.4f}", "ord_avg_pric": f"{px:.4f}",
                                    "exec_tm": "20261103101500", "err_cd": "", "rejt_rsn": "",
                                    "cust_acnt_no": "123456789", "user_ip_addr": "10.0.0.1"})
        if self.order_error is not None:
            raise self.order_error
        if self.reply is not None:
            return dict(self.reply)
        return {"ord_no": no, "err_cd": "00000", "err_msg": "주문이 정상처리 되었습니다.", "sym": sym}


def ovs_broker(tmp_path, fake, *, exp=None, halts=None):
    """해외 어댑터 위의 브로커. `exp` 는 실행기가 아는 보유(목록 첫 칸), `halts` 는 멈춤 까닭을 모은다."""
    exp = exp if exp is not None else [0]
    halts = halts if halts is not None else []
    return MockAccountBroker(adapter(OVERSEAS, fake), MKU, Journal(tmp_path / "j.jsonl"), sleep=lambda s: None,
                             today=TODAY, expected=lambda: exp[0], halt=halts.append)


# ---------------------------------------------------------------- 시장 값
def test_시장_값은_전역_약속과_같다():
    assert (DOMESTIC.id, DOMESTIC.currency, DOMESTIC.end_time) == ("domestic", "KRW", "153100")
    assert (DOMESTIC.paper_fee, DOMESTIC.paper_slip_ticks, DOMESTIC.breaks) == (690.0, 1, ())
    assert DOMESTIC.session_start == "090000"
    assert (OVERSEAS.id, OVERSEAS.currency, OVERSEAS.end_time) == ("overseas", "USD", "235500")
    assert OVERSEAS.session_start == "082500"
    assert OVERSEAS.breaks == (("203500", "205000"),)
    assert (OVERSEAS.paper_fee, OVERSEAS.paper_slip_ticks) == (2.0, 1)


def test_시장_값은_바꿀_수_없다():
    with pytest.raises(AttributeError):
        OVERSEAS.end_time = "120000"


def test_종목코드로_시장을_고른다():
    assert market_of("A756B000") is DOMESTIC
    assert market_of("MKUX26") is OVERSEAS
    assert market_of(" MKUZ26 ") is OVERSEAS


@pytest.mark.parametrize("sym", ["KUX26", "", "MESU26", "a756B000", "XA75"])
def test_모르는_종목코드는_ValueError(sym):
    with pytest.raises(ValueError):
        market_of(sym)


def test_해외_휴장은_20시35분부터_20시50분_전까지():
    assert not in_break(OVERSEAS, "203459")
    assert in_break(OVERSEAS, "203500")
    assert in_break(OVERSEAS, "204959")
    assert not in_break(OVERSEAS, "205000")
    assert not in_break(OVERSEAS, "100000")


def test_국내는_휴장이_없다():
    assert not any(in_break(DOMESTIC, t) for t in ("090000", "120000", "203500", "153000"))


# ---------------------------------------------------------------- 어댑터 고르기
def test_어댑터는_시장을_안다():
    assert adapter(DOMESTIC).market is DOMESTIC
    assert adapter(OVERSEAS).market is OVERSEAS
    assert adapter(DOMESTIC).api is real_api and adapter(OVERSEAS).api is real_api


def test_이미_어댑터면_그대로_모듈이면_국내_어댑터로_감싼다():
    a = adapter(OVERSEAS, FakeOvsApi())
    assert as_adapter(a) is a
    fake = FakeApi()
    wrapped = as_adapter(fake)
    assert wrapped.market is DOMESTIC and wrapped.api is fake


def test_브로커는_모듈을_받아도_국내_어댑터로_쓴다(tmp_path):
    fake = FakeApi()
    b = MockAccountBroker(fake, KRX_SYM, Journal(tmp_path / "j.jsonl"), today=TODAY)
    assert b.api.market is DOMESTIC and b.api.api is fake


# ---------------------------------------------------------------- 국내 어댑터 — 지금 api 그대로
def test_국내_어댑터는_api_함수를_그대로_부른다():
    fake = FakeApi()
    fake.held = 1
    a = adapter(DOMESTIC, fake)
    assert a.net_position(a.open_interest(), KRX_SYM) == 1
    a.market_order(KRX_SYM, "buy", 1, "3")
    assert fake.orders[-1] == (KRX_SYM, "buy", 1, "3")
    assert a.order_history()[0]["ord_sts"] == "6"
    assert a.deposit(TODAY)["fee"] is not None
    assert a.price(KRX_SYM) == {"last_pric": fake.last}
    assert a.chart_minute(KRX_SYM, req_qty=5) == []
    assert a.spec() == (0.1, 1000.0)
    assert a.nearest_usd(a.all_futures()) == KRX_SYM
    assert a.usd_spec(a.product_detail()) == (0.1, 1000.0)
    assert a.num("0001.5") == 1.5 and a.rows({"Occurs1": [{"occurs1_x": 1}]}) == [{"x": 1}]
    assert fake.calls == ["domestic_open-interest", "domestic_order", "domestic_order-history", "domestic_deposit",
                          "domestic_price", "domestic_chart-minute", "domestic_product-detail",
                          "domestic_price-all-futures", "domestic_product-detail"]


def test_국내_어댑터의_체결_칸_해석은_week02_그대로():
    a = adapter(DOMESTIC, FakeApi())
    assert (a.filled, a.rejected) == ("6", ("8", "9"))
    assert a.account_keys == ("fee", "fut_cls_pl_amt", "pl_tot_pric", "ord_psb_tot_amt")
    row = {"avg_exec_pric": "00000000000000.000000000", "exec_pric": "1335.1", "exch_exec_tm": "090104000",
           "ord_sts_nm": "전체체결", "ord_rejt_rsn": "잔고 부족"}
    assert a.fill_price(row) == 1335.1                       # avg 0 이면 exec_pric
    assert a.fill_price({"avg_exec_pric": "1335.2", "exec_pric": "1335.1"}) == 1335.2
    assert a.fill_price({"avg_exec_pric": "0", "exec_pric": ""}) is None
    assert (a.fill_time(row), a.status_name(row), a.reject_reason(row)) == ("090104000", "전체체결", "잔고 부족")
    assert a.order_log({"msg_cd": "00000", "msg_cntn": "정상", "err_cd": "x"}) == {"msg_cd": "00000", "msg_cntn": "정상"}


def test_국내_어댑터를_실행에_꽂아도_week02_와_같이_진입하고_정리한다(tmp_path):
    fake = FakeApi()
    run, _, out = make_run(tmp_path, fake=adapter(DOMESTIC, fake))
    run.prepare()
    assert run.sym == KRX_SYM and run.broker.api.api is fake          # 어댑터를 감싸지 않고 그대로
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    run.step(at("090104"))
    assert fake.orders == [(KRX_SYM, "buy", 1, "1")] and run.runner.pos is not None
    run.finish("중지")
    assert fake.orders[-1] == (KRX_SYM, "sell", 1, "1") and fake.held == 0
    order = next(r for r in lines(out / "journal.jsonl") if r["kind"] == "order")
    assert "msg_cd" in order and "err_cd" not in order


# ---------------------------------------------------------------- 해외 어댑터 — ovs_ 함수로
def test_해외_어댑터는_ovs_함수만_부른다():
    fake = FakeOvsApi()
    a = adapter(OVERSEAS, fake)
    a.market_order(MKU, "sell", 1, "1")
    assert fake.orders == [(MKU, "sell", 1)]               # 해외 시장가에는 체결조건 칸이 없다
    assert a.price(MKU)["last_pric"] == "0.7447"
    assert a.chart_minute(MKU, req_qty=7) == []
    assert a.spec() == (0.0001, 2.5)                       # KU 줄이 아니라 MKU 줄
    assert a.deposit(TODAY)["fee"] is not None
    assert [c[0] for c in fake.calls] == ["ovs_market_order", "ovs_price", "ovs_chart_minute",
                                          "ovs_product_detail", "ovs_deposit"]
    assert fake.calls[-1] == ("ovs_deposit", "USD", TODAY)
    assert fake.calls[2] == ("ovs_chart_minute", MKU, 7)


def test_해외_어댑터는_국내_함수를_갖지_않는다():
    a = adapter(OVERSEAS, FakeOvsApi())
    for name in ("nearest_usd", "all_futures", "usd_spec", "product_detail"):
        assert not hasattr(a, name)


def test_해외_어댑터의_체결_칸_해석():
    a = adapter(OVERSEAS, FakeOvsApi())
    assert (a.filled, a.rejected) == (real_api.OVS_FILLED, real_api.OVS_REJECTED)
    assert a.account_keys[0] == "fee"
    row = {"exec_pric": "0", "ord_avg_pric": "0.7448", "exec_tm": "20261103101500", "ord_sts": "9",
           "rejt_rsn": "증거금 부족", "err_cd": "E1234"}
    assert a.fill_price(row) == 0.7448
    assert a.fill_time(row) == "20261103101500"
    assert a.status_name(row) == "거부" and a.status_name({"ord_sts": "8"}) == "자동취소"
    assert a.status_name({"ord_sts": "6"}) == "전체체결" and a.status_name({"ord_sts": "?"}) == "?"
    assert a.reject_reason(row) == "E1234 증거금 부족"
    assert a.order_log({"err_cd": "00000", "err_msg": "정상", "msg_cd": "x"}) == {"err_cd": "00000", "err_msg": "정상"}


# ---------------------------------------------------------------- 해외 쪽 넘기기 (R5)
def _oi(qty, side="1"):
    return {"sym": MKU, "trd_tp": side, "opint_qty": str(qty)}


def test_해외_잔고는_다음_키를_따라_모든_쪽을_합친다():
    fake = FakeOvsApi()
    fake.oi_pages = {"": ([_oi(1)], "K1"), "K1": ([{"sym": "MKUZ26", "trd_tp": "1", "opint_qty": "3"}], "")}
    a = adapter(OVERSEAS, fake)
    got = a.open_interest()
    assert len(got) == 2 and a.net_position(got, MKU) == 1
    assert fake.calls == [("ovs_open_interest_page", ""), ("ovs_open_interest_page", "K1")]


def test_같은_키가_되돌아오면_끝이고_겹친_쪽은_두_번_세지_않는다():
    fake = FakeOvsApi()
    fake.oi_pages = {"": ([_oi(1)], "K1"), "K1": ([_oi(1)], "K1")}   # 끝 쪽에도 키를 주고 같은 줄이 다시 옴
    a = adapter(OVERSEAS, fake)
    assert a.net_position(a.open_interest(), MKU) == 1
    fake.oi_pages = {"": ([_oi(1)], "K1"), "K1": ([], "")}             # 끝 표지로 부르니 빈 쪽
    assert a.net_position(a.open_interest(), MKU) == 1


def test_쪽_상한을_넘겨도_남으면_PagesLeft():
    fake = FakeOvsApi()
    fake.oi_pages = {("" if i == 0 else f"K{i}"): ([_oi(1)] if i == 0 else [{"sym": f"X{i}", "trd_tp": "1",
                                                                              "opint_qty": "1"}], f"K{i + 1}")
                     for i in range(markets.OVS_MAX_PAGES + 1)}
    a = adapter(OVERSEAS, fake)
    with pytest.raises(PagesLeft):
        a.open_interest()
    assert fake.count("ovs_open_interest_page") == markets.OVS_MAX_PAGES


def test_주문내역도_쪽을_따라가고_남으면_PagesLeft():
    fake = FakeOvsApi()
    fake.hist_pages = {"": ([{"ord_no": "1"}], "K1"), "K1": ([{"ord_no": "2"}], "")}
    a = adapter(OVERSEAS, fake)
    assert [r["ord_no"] for r in a.order_history()] == ["1", "2"]
    fake.hist_pages = {("" if i == 0 else f"K{i}"): ([{"ord_no": str(i)}], f"K{i + 1}")
                       for i in range(markets.OVS_MAX_PAGES + 1)}
    with pytest.raises(PagesLeft):
        a.order_history()


def test_잔고_쪽이_남으면_브로커_잔고는_모름(tmp_path):
    fake = FakeOvsApi()
    fake.oi_pages = {("" if i == 0 else f"K{i}"): ([{"sym": f"X{i}", "trd_tp": "1", "opint_qty": "1"}], f"K{i + 1}")
                     for i in range(markets.OVS_MAX_PAGES + 1)}
    b = ovs_broker(tmp_path, fake)
    assert b.position() is None
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None   # 잔고를 모르면 관문이 막는다
    assert fake.orders == [] and b.sent is False and b.needs_check


# ---------------------------------------------------------------- 해외 주문 경로 — 국내와 같은 규칙
def test_해외_체결은_주문_한_번_체결가_exec_pric_수수료는_fee_차이(tmp_path):
    fake = FakeOvsApi()
    b = ovs_broker(tmp_path, fake)
    b.last_fee = 0.0
    px = b.fill("buy", 0.7447, "101500", "진입 · 시험")
    assert px == 0.7448 and fake.count("ovs_market_order") == 1
    assert b.last_fill_fee == 2.0 and b.sent and not b.needs_check
    recs = lines(tmp_path / "j.jsonl")
    order = next(r for r in recs if r["kind"] == "order")
    assert order["err_cd"] == "00000" and order["err_msg"] == "주문이 정상처리 되었습니다."
    assert "msg_cd" not in order and order["ok"] is True
    fill = next(r for r in recs if r["kind"] == "fill")
    assert (fill["price"], fill["exec_tm"], fill["fee"], fill["source"]) == (0.7448, "20261103101500", 2.0,
                                                                            "order-history")
    assert "cust_acnt_no" not in json.dumps(recs) and "10.0.0.1" not in json.dumps(recs)


def test_해외_접수인데_주문번호가_비면_blind_로_다시_안_보낸다(tmp_path):
    fake = FakeOvsApi()
    fake.fill, fake.reply = False, {"ord_no": "", "err_cd": "00000", "err_msg": "정상"}
    exp, halts = [0], []
    b = ovs_broker(tmp_path, fake, exp=exp, halts=halts)
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert b.blind == {"side": "buy", "pre": 0, "post": 1} and b.unknown and b.had_unknown
    assert fake.count("ovs_market_order") == 1
    # 다음 fill — 잔고가 그대로(0)면 들어갔는지 모르므로 멈추고 아무것도 안 보낸다
    assert b.fill("buy", 0.7447, "101600", "진입 · 시험") is None
    assert fake.count("ovs_market_order") == 1 and halts and "결과를 모르는 buy 주문" in halts[0]


def test_해외_주문_응답이_없으면_blind_이고_잔고가_체결_뒤를_보이면_풀린다(tmp_path):
    fake = FakeOvsApi()
    fake.order_error = TransportError("overseas_order", "응답 없음")
    exp, halts = [0], []
    b = ovs_broker(tmp_path, fake, exp=exp, halts=halts)
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert fake.count("ovs_market_order") == 1 and b.blind["post"] == 1
    assert fake.held == 1                                    # 사실은 들어갔다
    assert b.explains(1)
    exp[0] = 1                                               # 실행기가 잔고를 따라 보유 +1 로
    fake.order_error = None
    b.fill("sell", 0.7447, "101600", "청산 · 시험")
    assert b.blind is None and fake.count("ovs_market_order") == 2 and not halts


def test_해외_업무_거부는_결과를_아는_실패(tmp_path):
    fake = FakeOvsApi()
    fake.fill = False
    fake.order_error = BusinessError("overseas_order", "E0001", "증거금 부족", {})
    b = ovs_broker(tmp_path, fake)
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert b.blind is None and b.unresolved is None and not b.unknown and not b.explains(1)
    order = next(r for r in lines(tmp_path / "j.jsonl") if r["kind"] == "order")
    assert order["ok"] is False and "E0001" in order["error"]


def test_해외_주문내역이_거부면_None_이고_표시가_없다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "9"
    b = ovs_broker(tmp_path, fake)
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert b.unresolved is None and b.blind is None and fake.count("ovs_market_order") == 1
    ev = [r for r in lines(tmp_path / "j.jsonl") if r["kind"] == "event" and r.get("ord_no")]
    assert ev[-1]["text"] == "주문 거부"


def test_해외_15초_안에_체결_확인이_안_되면_unresolved_다음_주문_전에_다시_본다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "1"                                        # 접수만 — 체결 안 보임
    exp, halts = [0], []
    b = ovs_broker(tmp_path, fake, exp=exp, halts=halts)
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert b.unresolved == "0000000001" and (b.unresolved_pre, b.unresolved_post) == (0, 1)
    assert fake.count("ovs_order_history_page") == 30
    # 늦게 체결됨 — 주문내역 6, 잔고 +1(체결 뒤) → 표시 풀고 잔고 관문(기대 0 ≠ +1)이 막는다
    fake.history[0]["ord_sts"], fake.held = "6", 1
    assert b.fill("buy", 0.7447, "101600", "진입 · 시험") is None
    assert b.unresolved is None and b.landed == 1 and b.explains(1)
    assert fake.count("ovs_market_order") == 1 and not halts


def test_해외_unresolved_인데_주문내역_쪽이_남으면_아직_모름으로_세다가_멈춘다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "1"
    exp, halts = [0], []
    b = ovs_broker(tmp_path, fake, exp=exp, halts=halts)
    b.fill("buy", 0.7447, "101500", "진입 · 시험")
    assert b.unresolved == "0000000001"
    fake.hist_pages = {("" if i == 0 else f"K{i}"): ([{"ord_no": f"9{i}"}], f"K{i + 1}")
                       for i in range(markets.OVS_MAX_PAGES + 1)}
    for n in range(3):
        assert b.fill("buy", 0.7447, f"10160{n}", "진입 · 시험") is None
    assert b.unresolved_checks == 3 and halts and "3번 확인해도 모름" in halts[0]
    assert fake.count("ovs_market_order") == 1


def test_해외_주문_전_잔고가_기대와_다르면_보내지_않는다(tmp_path):
    fake = FakeOvsApi()
    fake.held = 1                                            # 남의 주문 또는 앞선 주문이 들어가 있음
    b = ovs_broker(tmp_path, fake, exp=[0])
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert fake.orders == [] and not b.sent and b.unknown and not b.explains(1)


def test_해외_예수금_기록은_USD_칸_그대로(tmp_path):
    fake = FakeOvsApi()
    fake.fee = 4.0
    b = ovs_broker(tmp_path, fake)
    snap = b.account("101500", "시작")
    assert snap["fee"] == 4.0 and set(snap) == set(markets.OVERSEAS_ACCOUNT_KEYS)
    rec = lines(tmp_path / "j.jsonl")[-1]
    assert rec["kind"] == "account" and "cust_acnt_no" not in rec


# ---------------------------------------------------------------- 최종 검토 고침 (I1·M1·M3)
def test_해외_주문내역_줄은_기록에서_허용_목록_밖의_값을_가린다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "9"
    b = ovs_broker(tmp_path, fake)
    fake.history.append({"ord_no": "0000000001", "ord_sts": "9", "cust_no": "12345678",
                         "Occurs2": [{"mbr_no": "98765432", "sym": MKU}]})
    fake.fill = False                                       # 가짜가 줄을 넣지 않게 — 위 줄만 보인다
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    text = (tmp_path / "j.jsonl").read_text(encoding="utf-8")
    assert "12345678" not in text and "98765432" not in text
    raw = [r for r in lines(tmp_path / "j.jsonl") if r.get("raw")][-1]["raw"]
    assert raw["cust_no"] == "***" and raw["ord_no"] == "0000000001" and raw["ord_sts"] == "9"
    assert raw["Occurs2"] == [{"mbr_no": "***", "sym": MKU}]


def test_국내_어댑터는_기록용_줄을_바꾸지_않는다():
    row = {"ord_no": "1", "cust_no": "12345678"}
    assert adapter(DOMESTIC, FakeApi()).log_row(row) == row
    assert adapter(OVERSEAS, FakeOvsApi()).log_row(row) == {"ord_no": "1", "cust_no": "***"}


def test_같은_주문의_줄이_여럿이면_체결_줄을_본다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "6"
    b = ovs_broker(tmp_path, fake)
    real_hist = fake.ovs_order_history_page

    def two_rows(nxt_key=""):
        got, key = real_hist(nxt_key)
        out = []
        for r in got:                                       # 접수 줄이 먼저, 체결 줄이 둘째
            out += [{**r, "ord_sts": "1", "exec_pric": "0"}, r]
        return out, key

    fake.ovs_order_history_page = two_rows
    px = b.fill("buy", 0.7447, "101500", "진입 · 시험")
    assert px == pytest.approx(0.7448) and b.unresolved is None and b.blind is None


def test_unresolved_다시_볼_때도_같은_주문의_체결_줄을_본다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "1"
    b = ovs_broker(tmp_path, fake)
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None and b.unresolved == "0000000001"
    filled = {**fake.history[0], "ord_sts": "6"}
    fake.history.append(filled)                             # 접수 줄(1) 다음에 체결 줄(6)
    fake.held = 1
    assert b.fill("buy", 0.7447, "101600", "진입 · 시험") is None
    assert b.unresolved is None and b.landed == 1           # 체결로 읽고 잔고 증거로 풀었다


def test_보내기_직전_may_send_가_거짓이면_아무것도_안_보내고_표시도_없다(tmp_path):
    fake = FakeOvsApi()
    b = ovs_broker(tmp_path, fake)
    b.may_send = lambda: False
    assert b.fill("buy", 0.7447, "101500", "진입 · 시험") is None
    assert fake.orders == [] and fake.count("ovs_market_order") == 0
    assert b.held_back and not b.sent and b.blind is None and b.unresolved is None
    assert not b.unknown and not b.had_unknown and not b.needs_check
    assert any("주문 보류" in r.get("text", "") for r in lines(tmp_path / "j.jsonl"))
    b.may_send = lambda: True                               # 다음 fill 은 보통대로, 표시도 지운다
    assert b.fill("buy", 0.7447, "101600", "진입 · 시험") is not None
    assert not b.held_back and len(fake.orders) == 1
