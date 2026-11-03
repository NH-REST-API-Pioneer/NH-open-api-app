"""팀 API 계층 — 해외(SGX 미니 원달러 MKU) 쪽 요청 값·응답 해석·재시도 규칙.

응답 본문은 `tests/fixtures/nh/overseas_*` 기록을 그대로 돌려줍니다. 해외 주문·주문내역·잔고·예수금은
기록이 없어(저장소에 공개된 해외 기록은 시세·품목 조회뿐) 운영자 `backend/overseas_futureoption/` 의
해석 코드와 week03 `nh_client.py` 에서 확인한 칸 이름으로 응답을 직접 만들어 씁니다 — 아래 `# 근거` 주석.
서버는 httpx.MockTransport 라 실제 NH 서버로는 나가지 않습니다.
"""
import httpx
import pytest

from backend.nh_api.client import TradeClient
from backend.nh_api.errors import BusinessError, GatewayError, TransportError
from backend.team_pyrun import api
from tests.test_team_pyrun_api import (  # noqa: F401  (쉬는시간 은 fixture)
    기록,
    만들기,
    보낸본문,
    쉬는시간,
    차례서버,
)
from tests.test_trade_client import config, 세션  # noqa: F401  (config 는 fixture)

BASE = "/trade/v1/overseas"
CHART = f"{BASE}/chart-minute"
PRICE = f"{BASE}/price"
DETAIL = f"{BASE}/product-detail"
DEPOSIT = f"{BASE}/deposit"
OPEN_INTEREST = f"{BASE}/open-interest"
ORDER_HISTORY = f"{BASE}/order-history"
ORDER = f"{BASE}/order"

# 근거: 주문 접수 답. 운영자 overseas_account.order_result(:557~) — `ord_no`, 접수에도 `err_cd`="00000".
접수 = {"ord_no": "0000012345", "err_cd": "00000", "err_msg": "주문이 정상처리 되었습니다.", "sym": "MKUX26"}

# MKU 마스터(etc_fut.mst) 줄 — 칸 이름은 OVERSEAS_FUTURES_FIELDS. 2026-11-03 받은 파일의 값 그대로(이름 칸만 뺌).
마스터 = [
    {"code": "MKUZ26", "comd": "MKU", "type": "F", "trdf": "0", "yymm": "202612", "lmon": "0", "lmon_my": "0"},
    {"code": "MKUX26", "comd": "MKU", "type": "F", "trdf": "0", "yymm": "202611", "lmon": "1", "lmon_my": "1"},
    {"code": "MKUF27", "comd": "MKU", "type": "F", "trdf": "0", "yymm": "202701", "lmon": "0", "lmon_my": "0"},
    {"code": "KUX26", "comd": "KU", "type": "F", "trdf": "0", "yymm": "202611", "lmon": "1", "lmon_my": "1"},
]


# ── 요청 값 ─────────────────────────────────────────────────


def test_요청_값은_week03_와_운영자_해외_래퍼와_같다(config):
    응답들 = {
        CHART: httpx.Response(200, json=기록("overseas_chart-minute", "real", {"exch_cd": "FCME", "dcnt": "1"})),
        PRICE: httpx.Response(200, json=기록("overseas_price", "real", {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]})),
        DETAIL: httpx.Response(200, json=기록("overseas_product-detail", "real", {"prd_grp_cd": "FG2"})),
        DEPOSIT: httpx.Response(200, json={"biz_dt": "20261103", "cur_cd": "USD", "fee": "4.00"}),
        OPEN_INTEREST: httpx.Response(200, json={"nrec": "0000", "nxt_key": ""}),
        ORDER_HISTORY: httpx.Response(200, json={"nrec": "0000", "nxt_key": ""}),
        ORDER: httpx.Response(200, json=접수),
    }
    client, 서버_ = 만들기(config, 응답들)

    api.ovs_chart_minute("MKUX26", req_qty=10, client=client)
    api.ovs_price("MKUX26", client=client)
    api.ovs_product_detail(client=client)
    api.ovs_deposit(biz_dt="20261103", client=client)
    api.ovs_open_interest(client=client)
    api.ovs_order_history(client=client)
    api.ovs_market_order("MKUX26", "buy", client=client)
    api.ovs_market_order("MKUX26", "sell", 2, client=client)

    assert 보낸본문(서버_, CHART) == [{
        "exch_cd": "FSGX", "sym": "MKUX26", "inq_strt_dt": "00000000", "strt_tm": "000000",
        "inq_ed_dt": "99999999", "ed_tm": "235959", "req_qty": "10", "dcnt": "1",
        "cidx_yn": "0", "nxt_key": "99999999",
    }]
    assert 보낸본문(서버_, PRICE) == [{"Iccurs1": [{"iccurs1_exch_cd": "FSGX", "iccurs1_sym": "MKUX26"}]}]
    assert 보낸본문(서버_, DETAIL) == [{
        "sett_cd": "", "fut_opt_div_cd": "F", "cur_cd": "", "prd_grp_cd": "FG2",
        "exch_cd": "", "nxt_key": "", "prd_nm": "", "prd_cd": "",
    }]
    assert 보낸본문(서버_, DEPOSIT) == [{"biz_dt": "20261103", "cur_cd": "USD", "cvs_div": "1"}]
    assert 보낸본문(서버_, OPEN_INTEREST) == [{"nxt_key": ""}]
    assert 보낸본문(서버_, ORDER_HISTORY) == [{"trd_div_cd": "0", "inq_div": "0", "nxt_key": "", "prd_cd": ""}]
    assert 보낸본문(서버_, ORDER) == [
        {"qt_div_cd": "1", "sym": "MKUX26", "trd_div_cd": "1", "glb_ord_tp_cd": "1",
         "ord_qty": "1", "ord_pric": "0", "stop_pric": "", "org_ord_no": "0"},
        {"qt_div_cd": "1", "sym": "MKUX26", "trd_div_cd": "2", "glb_ord_tp_cd": "1",
         "ord_qty": "2", "ord_pric": "0", "stop_pric": "", "org_ord_no": "0"},
    ]


def test_거래소와_예수금_통화는_바꿔_끼울_수_있다(config):
    client, 서버_ = 만들기(config, {
        CHART: httpx.Response(200, json=기록("overseas_chart-minute", "real", {"exch_cd": "FCME", "dcnt": "1"})),
        PRICE: httpx.Response(200, json=기록("overseas_price", "real", {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]})),
        DEPOSIT: httpx.Response(200, json={"cur_cd": "KRW"}),
    })
    api.ovs_chart_minute("KUX26", req_qty=5, exch_cd="FSGX", client=client)
    api.ovs_price("KUX26", exch_cd="FSGX", client=client)
    api.ovs_deposit("KRW", biz_dt="20261103", client=client)
    assert 보낸본문(서버_, DEPOSIT)[0]["cur_cd"] == "KRW"


def test_예수금_날짜를_안_주면_지금_한국_날짜(config, monkeypatch):
    """week03 근거: biz_dt 가 비면 ETR018 — 오늘 날짜를 채운다."""
    from datetime import datetime

    from backend.sessions.hours import KST
    monkeypatch.setattr(api, "now_kst", lambda: datetime(2026, 11, 3, 21, 0, tzinfo=KST))
    client, 서버_ = 만들기(config, {DEPOSIT: httpx.Response(200, json={"fee": "0"})})
    api.ovs_deposit(client=client)
    assert 보낸본문(서버_, DEPOSIT) == [{"biz_dt": "20261103", "cur_cd": "USD", "cvs_div": "1"}]


def test_해외_호출도_모두_모의_서버로_나간다(config):
    client, 서버_ = 만들기(config, {PRICE: httpx.Response(200, json=기록("overseas_price", "real", {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]}))})
    api.ovs_price("MKUX26", client=client)
    보낸것 = [r for r in 서버_.요청들 if r.url.path == PRICE][0]
    assert 보낸것.url.host == "apidemo.example"


def test_종목_구분_말고는_주문하지_않는다(config):
    client, 서버_ = 만들기(config, {ORDER: httpx.Response(200, json=접수)})
    with pytest.raises(KeyError):
        api.ovs_market_order("MKUX26", "hold", client=client)
    assert 서버_.횟수(ORDER) == 0


# ── 응답 해석 ───────────────────────────────────────────────


def test_차트_줄은_접두를_뗀다(config):
    본문 = 기록("overseas_chart-minute", "real", {"exch_cd": "FCME", "dcnt": "1"})
    client, _ = 만들기(config, {CHART: httpx.Response(200, json=본문)})
    got = api.ovs_chart_minute("MKUX26", req_qty=10, client=client)
    assert len(got) == len(본문["Occurs1"])
    assert {"ref_dt", "exch_tm", "open_pric", "high_pric", "low_pric", "close_pric", "glb_biz_dt"} <= set(got[0])
    assert not any(k.startswith("occurs1_") for k in got[0])
    assert api.num(got[0]["close_pric"]) is not None


def test_현재가는_Occurs1_첫_줄(config):
    """해외 현재가는 국내와 달리 본문이 아니라 `Occurs1[0]` 에 `last_pric` 이 있다(기록)."""
    본문 = 기록("overseas_price", "real", {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]})
    client, _ = 만들기(config, {PRICE: httpx.Response(200, json=본문)})
    got = api.ovs_price("MKUX26", client=client)
    assert got["sym"] == "MESU26" and api.num(got["last_pric"]) == 7680.5
    assert {"bid_pric", "ask_pric", "trd_tm"} <= set(got)


def test_현재가_줄이_없으면_빈_dict(config):
    client, _ = 만들기(config, {PRICE: httpx.Response(200, json={"nrec": "0"})})
    assert api.ovs_price("MKUX26", client=client) == {}


def test_품목_세부정보에서_MKU_틱과_틱가치(config):
    본문 = 기록("overseas_product-detail", "real", {"prd_grp_cd": "FG2"})
    client, _ = 만들기(config, {DETAIL: httpx.Response(200, json=본문)})
    줄 = api.ovs_product_detail(client=client)
    assert {"prd_cd", "tick_unt", "tick_val", "cur_cd", "ctr_unt"} <= set(줄[0])
    assert api.mku_spec(줄) == (0.0001, 2.5)          # 큰 계약 KU(0.00005, 6.25) 줄이 아니다
    assert api.num(next(r for r in 줄 if r["prd_cd"] == "MKU")["ctr_unt"]) == 25000.0


def test_MKU_줄이_없으면_ValueError():
    with pytest.raises(ValueError):
        api.mku_spec([{"prd_cd": "KU", "tick_unt": "0.00005", "tick_val": "6.25"}])
    with pytest.raises(ValueError):
        api.mku_spec([{"prd_cd": "MKU", "tick_unt": "", "tick_val": "2.5"}])


def test_최근월물은_마스터에서_만기일_기준_근월(config):
    assert api.nearest_mku(마스터) == "MKUX26"


def test_최근월물_표지가_없으면_만기년월이_가장_이른_것():
    표지없음 = [{**줄, "lmon": "0", "lmon_my": "0"} for 줄 in 마스터]
    assert api.nearest_mku(표지없음) == "MKUX26"


def test_최근월물은_MKU_선물_거래_가능만_본다():
    줄 = [
        {"code": "MKUX26", "comd": "MKU", "type": "F", "trdf": "1", "yymm": "202611", "lmon_my": "1"},   # 거래 불가
        {"code": "MKUX26-Z26", "comd": "MKU", "type": "S", "trdf": "0", "yymm": "202611", "lmon_my": "1"},  # 스프레드
        {"code": "KUX26", "comd": "KU", "type": "F", "trdf": "0", "yymm": "202611", "lmon_my": "1"},
        {"code": "MKUZ26", "comd": "MKU", "type": "F", "trdf": "0", "yymm": "202612", "lmon_my": "0"},
    ]
    assert api.nearest_mku(줄) == "MKUZ26"
    with pytest.raises(ValueError):
        api.nearest_mku(줄[:3])


def test_순보유는_trd_tp_로_부호를_정한다():
    """근거: 해외 잔고 매수매도 칸은 `trd_tp`(운영자 overseas_account.py:165·341), 수량은 `opint_qty`."""
    줄 = [
        {"sym": "MKUX26", "opint_qty": "000000000002.000000000", "trd_tp": "1"},
        {"sym": "MKUX26", "opint_qty": "1", "trd_tp": "2"},
        {"sym": "KUX26", "opint_qty": "5", "trd_tp": "1"},
    ]
    assert api.ovs_net_position(줄, "MKUX26") == 1
    assert api.ovs_net_position([{"sym": " MKUX26 ", "opint_qty": "3", "trd_tp": " 2 "}], "MKUX26") == -3
    assert api.ovs_net_position([], "MKUX26") == 0
    assert api.ovs_net_position([{"sym": "MKUX26", "opint_qty": "0", "trd_tp": ""}], "MKUX26") == 0


def test_순보유_방향을_모르면_ValueError():
    """부호를 짐작하지 않는다 — 잔고 관문이 틀린 방향으로 열리지 않게."""
    with pytest.raises(ValueError):
        api.ovs_net_position([{"sym": "MKUX26", "opint_qty": "1", "trd_tp": "9"}], "MKUX26")
    with pytest.raises(ValueError):
        api.ovs_net_position([{"sym": "MKUX26", "opint_qty": "1"}], "MKUX26")


def test_잔고와_주문내역_줄은_접두를_뗀다(config):
    잔고 = {"Occurs1": [{"occurs1_sym": "MKUX26", "occurs1_trd_tp": "1", "occurs1_opint_qty": "000000000001.000000000"}], "nrec": "0001", "nxt_key": ""}
    내역 = {"Occurs1": [{
        "occurs1_ord_no": "0000012345", "occurs1_sym": "MKUX26", "occurs1_ord_sts": "6", "occurs1_trd_tp": "1",
        "occurs1_ord_qty": "1", "occurs1_exec_qty": "1", "occurs1_exec_pric": "0.7447", "occurs1_ord_avg_pric": "0.7447",
        "occurs1_exec_tm": "20261103101500", "occurs1_err_cd": "", "occurs1_rejt_rsn": "",
    }], "nrec": "0001", "nxt_key": ""}
    client, _ = 만들기(config, {OPEN_INTEREST: httpx.Response(200, json=잔고), ORDER_HISTORY: httpx.Response(200, json=내역)})
    pos, hist = api.ovs_open_interest(client=client), api.ovs_order_history(client=client)
    assert api.ovs_net_position(pos, "MKUX26") == 1
    assert hist[0]["ord_no"] == "0000012345" and hist[0]["ord_sts"] == api.OVS_FILLED


def test_빈_응답은_빈_목록(config):
    client, _ = 만들기(config, {
        OPEN_INTEREST: httpx.Response(200, json={"nrec": "0000", "nxt_key": ""}),
        ORDER_HISTORY: httpx.Response(200, json={"nrec": "0000", "nxt_key": ""}),
    })
    assert api.ovs_open_interest(client=client) == []
    assert api.ovs_order_history(client=client) == []


def test_예수금은_본문_한_덩어리(config):
    본문 = {"biz_dt": "20261103", "cur_cd": "USD", "fee": "000000000000004.00", "fut_fee": "4.00", "cls_pl_amt": "-5.00"}
    client, _ = 만들기(config, {DEPOSIT: httpx.Response(200, json=본문)})
    got = api.ovs_deposit(biz_dt="20261103", client=client)
    assert got == 본문 and api.num(got["fee"]) == 4.0


# ── 체결 확인 칸 ────────────────────────────────────────────


def test_상태_상수는_운영자_해외_주문상태와_같다():
    """근거: 운영자 overseas_account.ORDER_STATUS — 6 전체체결 · 8 자동취소 · 9 거부."""
    assert api.OVS_FILLED == "6"
    assert api.OVS_REJECTED == ("8", "9")


def test_체결가는_exec_pric_없으면_ord_avg_pric_못읽으면_None():
    assert api.ovs_fill_price({"exec_pric": "0000000000000.744700000", "ord_avg_pric": "0.7448"}) == 0.7447
    assert api.ovs_fill_price({"exec_pric": "0.000000000", "ord_avg_pric": "0.7448"}) == 0.7448
    assert api.ovs_fill_price({"exec_pric": "", "ord_avg_pric": "0"}) is None
    assert api.ovs_fill_price({}) is None


# ── 재시도 ──────────────────────────────────────────────────


def test_해외_조회는_호출_제한이면_다시_묻는다(config, 쉬는시간):
    서버_ = 차례서버({PRICE: [
        httpx.Response(200, json={"errorCode": "EGW036", "errorMessage": "초당 호출 제한"}),
        httpx.Response(200, json=기록("overseas_price", "real", {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]})),
    ]})
    client = TradeClient(세션(config, 서버_))
    got = api.ovs_price("MKUX26", client=client)
    assert api.num(got["last_pric"]) == 7680.5
    assert 서버_.횟수(PRICE) == 2 and 쉬는시간 == [1]


def test_해외_조회는_응답이_없어도_세_번까지(config, 쉬는시간):
    서버_ = 차례서버({ORDER_HISTORY: [httpx.ConnectTimeout("1"), httpx.ConnectTimeout("2"), httpx.ConnectTimeout("3")]})
    client = TradeClient(세션(config, 서버_))
    with pytest.raises(TransportError):
        api.ovs_order_history(client=client)
    assert 서버_.횟수(ORDER_HISTORY) == 3 and 쉬는시간 == [1, 2]


def test_해외_조회는_모의_미지원_거절을_바로_올린다(config, 쉬는시간):
    서버_ = 차례서버({PRICE: [httpx.Response(200, json={"errorCode": "EGW053", "errorMessage": "모의 미지원"})]})
    client = TradeClient(세션(config, 서버_))
    with pytest.raises(GatewayError) as 잡힌것:
        api.ovs_price("MKUX26", client=client)
    assert 잡힌것.value.code == "EGW053" and 서버_.횟수(PRICE) == 1 and 쉬는시간 == []


# ── 주문은 한 번 ────────────────────────────────────────────


def test_해외_주문은_응답이_없어도_다시_보내지_않는다(config, 쉬는시간):
    client, 서버_ = 만들기(config, {ORDER: httpx.ConnectTimeout("끝내 못 받음")})
    with pytest.raises(TransportError):
        api.ovs_market_order("MKUX26", "buy", client=client)
    assert 서버_.횟수(ORDER) == 1 and 쉬는시간 == []


def test_해외_주문은_호출_제한_거절도_다시_보내지_않는다(config, 쉬는시간):
    client, 서버_ = 만들기(config, {ORDER: httpx.Response(200, json={"errorCode": "EGW036", "errorMessage": "제한"})})
    with pytest.raises(GatewayError):
        api.ovs_market_order("MKUX26", "sell", client=client)
    assert 서버_.횟수(ORDER) == 1 and 쉬는시간 == []


def test_해외_주문_접수는_err_cd_00000_이어도_본문_그대로(config):
    client, _ = 만들기(config, {ORDER: httpx.Response(200, json=접수)})
    got = api.ovs_market_order("MKUX26", "buy", client=client)
    assert got == 접수 and got["ord_no"]


def test_해외_주문_거절은_err_cd_로_와도_업무_거부로_올린다(config, 쉬는시간):
    """근거: 해외는 거절을 `msg_cd` 가 아닌 `err_cd`·`err_msg` 로 싣는다(운영자 overseas_routes.py:1276,
    sim.py `_raise_overseas_refusal`). 공통 클라이언트가 못 잡으므로 여기서 올리지 않으면 접수로 읽힌다."""
    본문 = {"ord_no": "", "err_cd": "40010", "err_msg": "주문가능수량을 초과했습니다"}
    client, 서버_ = 만들기(config, {ORDER: httpx.Response(200, json=본문)})
    with pytest.raises(BusinessError) as 잡힌것:
        api.ovs_market_order("MKUX26", "buy", client=client)
    assert 잡힌것.value.code == "40010" and 서버_.횟수(ORDER) == 1 and 쉬는시간 == []


def test_client_를_안_주면_앱의_접속을_쓴다(config, monkeypatch):
    client, 서버_ = 만들기(config, {PRICE: httpx.Response(200, json=기록("overseas_price", "real", {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]}))})
    from backend.nh_api import runtime
    monkeypatch.setattr(runtime, "client", lambda: client)
    api.ovs_price("MKUX26")
    assert 서버_.횟수(PRICE) == 1
