"""팀 API 계층 — 요청 값·응답 해석·재시도 규칙.

응답 본문은 `tests/fixtures/nh/<api_id>/` 의 기록을 그대로 돌려줍니다(원칙 6, 필드명을 짐작하지 않음).
서버는 httpx.MockTransport 라 실제 NH 서버로는 나가지 않습니다.
"""
import json
from pathlib import Path

import httpx
import pytest

from backend.nh_api.errors import BusinessError, GatewayError, TransportError
from backend.team_pyrun import api
from tests.test_trade_client import config, 서버, 세션  # noqa: F401  (config 는 fixture)
from backend.nh_api.client import TradeClient

FIXTURES = Path(__file__).parent / "fixtures" / "nh"
CHART = "/trade/v1/domestic/chart-minute"
PRICE = "/trade/v1/domestic/price"
ALL_FUTURES = "/trade/v1/domestic/price-all-futures"
DETAIL = "/trade/v1/domestic/product-detail"
DEPOSIT = "/trade/v1/domestic/deposit"
OPEN_INTEREST = "/trade/v1/domestic/open-interest"
ORDER_HISTORY = "/trade/v1/domestic/order-history"
ORDER = "/trade/v1/domestic/order"


def 기록(api_id, env, 요청=None, *, 있는칸=None):
    """기록된 응답 본문 하나. `요청` 이 같고 `있는칸` 이 본문에 있는 첫 기록."""
    for file in sorted((FIXTURES / api_id / env).glob("*/*.json")):
        record = json.loads(file.read_text(encoding="utf-8"))
        if 요청 is not None and any(record["request"].get(k) != v for k, v in 요청.items()):
            continue
        if 있는칸 is not None and 있는칸 not in record["response"]:
            continue
        return record["response"]
    raise AssertionError(f"기록이 없습니다: {api_id}/{env} {요청}")


def 만들기(config, 응답들):
    서버_ = 서버(응답들)
    return TradeClient(세션(config, 서버_)), 서버_


def 보낸본문(서버_, path):
    """서버가 그 경로로 받은 요청의 json 본문들."""
    return [json.loads(r.content) for r in 서버_.요청들 if r.url.path == path]


class 차례서버(서버):
    """같은 경로로 오는 요청마다 목록의 다음 응답을 돌려줍니다."""

    def __call__(self, request):
        path = request.url.path
        if not path.endswith("/token") and isinstance(self.응답들.get(path), list):
            self.요청들.append(request)
            결과 = self.응답들[path].pop(0)
            if isinstance(결과, Exception):
                raise 결과
            return 결과
        return super().__call__(request)


@pytest.fixture
def 쉬는시간(monkeypatch):
    """재시도 대기를 기록만 하고 실제로는 쉬지 않습니다."""
    쉰것 = []
    monkeypatch.setattr(api, "sleep", 쉰것.append)
    return 쉰것


# ── 요청 값 ─────────────────────────────────────────────────


def test_요청_값은_week02_와_같다(config):
    응답들 = {
        CHART: httpx.Response(200, json=기록("domestic_chart-minute", "real")),
        PRICE: httpx.Response(200, json=기록("domestic_price", "real")),
        ALL_FUTURES: httpx.Response(200, json=기록("domestic_price-all-futures", "real", {"prd": "75"})),
        DETAIL: httpx.Response(200, json=기록("domestic_product-detail", "real")),
        DEPOSIT: httpx.Response(200, json=기록("domestic_deposit", "paper")),
        OPEN_INTEREST: httpx.Response(200, json=기록("domestic_open-interest", "paper", 있는칸="Occurs1")),
        ORDER_HISTORY: httpx.Response(200, json=기록("domestic_order-history", "paper", 있는칸="Occurs1")),
        ORDER: httpx.Response(200, json=기록("domestic_order", "paper", {"trd_div": "1"})),
    }
    client, 서버_ = 만들기(config, 응답들)

    api.chart_minute("A756B000", req_qty=10, client=client)
    api.price("A756B000", client=client)
    api.all_futures(client=client)
    api.product_detail(client=client)
    api.deposit("20260909", client=client)
    api.open_interest(client=client)
    api.order_history(client=client)
    api.market_order("A756B000", "buy", client=client)
    api.market_order("A756B000", "sell", 2, "2", client=client)

    assert 보낸본문(서버_, CHART) == [{
        "nght_tp": "1", "sym": "A756B000", "inq_strt_dt": "00000000", "strt_tm": "000000",
        "inq_ed_dt": "99999999", "ed_tm": "235959", "req_qty": "10", "dcnt": "1",
        "cidx_yn": "0", "nxt_key": "99999999", "fut_cidx_exp_mod": "0",
    }]
    assert 보낸본문(서버_, PRICE) == [{"sym": "A756B000"}]
    assert 보낸본문(서버_, ALL_FUTURES) == [{"prd": "75"}]
    assert 보낸본문(서버_, DETAIL) == [{}]
    assert 보낸본문(서버_, DEPOSIT) == [{"biz_dt": "20260909"}]
    assert 보낸본문(서버_, OPEN_INTEREST) == [{"nxt_key": ""}]
    assert 보낸본문(서버_, ORDER_HISTORY) == [
        {"trd_div": "0", "exec_div": "0", "trd_tm_div_cd": "1", "ord_div_cd": "0", "nxt_key": ""}
    ]
    assert 보낸본문(서버_, ORDER) == [
        {"sym": "A756B000", "trd_div": "1", "ord_tp_cd": "2", "ord_qty": "1", "ord_pric": "0", "exec_cnd_cd": "1"},
        {"sym": "A756B000", "trd_div": "2", "ord_tp_cd": "2", "ord_qty": "2", "ord_pric": "0", "exec_cnd_cd": "2"},
    ]


def test_모든_호출은_모의_서버로_나간다(config):
    """`environment="paper"` — 설정의 기본 환경이 실전이어도 모의 서버 주소로만 간다."""
    client, 서버_ = 만들기(config, {PRICE: httpx.Response(200, json=기록("domestic_price", "real"))})
    api.price("A756B000", client=client)
    보낸것 = [r for r in 서버_.요청들 if r.url.path == PRICE][0]
    assert 보낸것.url.host == "apidemo.example"


def test_종목_구분_말고는_주문하지_않는다(config):
    client, 서버_ = 만들기(config, {ORDER: httpx.Response(200, json=기록("domestic_order", "paper"))})
    with pytest.raises(KeyError):
        api.market_order("A756B000", "hold", client=client)
    assert 서버_.횟수(ORDER) == 0


# ── 응답 해석 ───────────────────────────────────────────────


def test_차트_줄은_접두를_뗀다(config):
    client, _ = 만들기(config, {CHART: httpx.Response(200, json=기록("domestic_chart-minute", "real"))})
    got = api.chart_minute("A756B000", req_qty=10, client=client)
    assert {"ref_dt", "exch_tm", "close_pric", "open_pric", "high_pric", "low_pric"} <= set(got[0])
    assert not any(k.startswith("occurs1_") for k in got[0])
    assert api.num(got[0]["close_pric"]) is not None


def test_현재가는_본문_그대로(config):
    본문 = 기록("domestic_price", "real", {"sym": "A7569000"})
    client, _ = 만들기(config, {PRICE: httpx.Response(200, json=본문)})
    got = api.price("A7569000", client=client)
    assert got == 본문 and api.num(got["last_pric"]) == 1338.5


def test_잔고_줄의_모양(config):
    """공개 기록은 빈 응답이 많아 `Occurs1` 이 있는 기록을 쓴다. 줄 칸은 기록 그대로 sym·opint_qty·trd_div."""
    client, _ = 만들기(config, {OPEN_INTEREST: httpx.Response(200, json=기록("domestic_open-interest", "paper", 있는칸="Occurs1"))})
    got = api.open_interest(client=client)
    assert {"sym", "opint_qty", "trd_div"} <= set(got[0])
    assert api.net_position(got, got[0]["sym"]) == 1


def test_빈_응답은_빈_목록(config):
    client, _ = 만들기(config, {
        OPEN_INTEREST: httpx.Response(200, json=기록("domestic_open-interest", "paper", {"nxt_key": ""})),
        ORDER_HISTORY: httpx.Response(200, json=기록("domestic_order-history", "paper", {"nxt_key": ""})),
    })
    assert api.open_interest(client=client) == []
    assert api.order_history(client=client) == []


def test_주문내역_줄의_모양(config):
    client, _ = 만들기(config, {ORDER_HISTORY: httpx.Response(200, json=기록("domestic_order-history", "paper", 있는칸="Occurs1"))})
    got = api.order_history(client=client)
    assert {"ord_no", "ord_sts", "exec_pric", "exch_exec_tm"} <= set(got[0])


def test_예수금은_본문_한_줄(config):
    client, _ = 만들기(config, {DEPOSIT: httpx.Response(200, json=기록("domestic_deposit", "paper"))})
    dep = api.deposit("20260909", client=client)
    assert isinstance(dep, dict) and {"fee", "fut_cls_pl_amt", "pl_tot_pric", "ord_psb_tot_amt"} <= set(dep)
    assert api.num(dep["fee"]) is not None


def test_숫자는_0채움과_부호를_읽고_못읽으면_None():
    assert api.num("-00000000000044000.000") == -44000.0
    assert api.num("000000001335.900000000") == 1335.9
    assert api.num("") is None and api.num(None) is None and api.num("abc") is None


def test_rows_는_Occurs_가_아니면_빈_목록():
    assert api.rows({"nrec": "0000", "nxt_key": ""}) == []
    assert api.rows(None) == []
    assert api.rows({"Occurs1": [{"occurs1_a": "1", "b": "2"}, "잘못된 줄"]}) == [{"a": "1", "b": "2"}]


# ── 종목·틱·보유 ────────────────────────────────────────────


def test_최근월물과_틱():
    줄 = api.rows(기록("domestic_price-all-futures", "real", {"prd": "75"}))
    assert api.nearest_usd(줄) == "A7569000"                      # 26/09 가 가장 가깝다
    상품 = api.rows(기록("domestic_product-detail", "real"))
    assert api.usd_spec(상품) == (0.1, 1000.0)                    # 「(야간)미국달러선물(USD)」 줄은 아니다


def test_최근월물은_플렉스를_뺀다():
    줄 = [
        {"sym_exch": "A75X", "sym_nm": "미국달러 플렉스 F 260901 D", "exp_mon": "26/09"},
        {"sym_exch": "A756A000", "sym_nm": "미국달러 F 202610", "exp_mon": "26/10"},
        {"sym_exch": "A756B000", "sym_nm": "미국달러 F 202611", "exp_mon": "26/11"},
        {"sym_exch": "B0169A34", "sym_nm": "옵션", "exp_mon": "26/08"},
    ]
    assert api.nearest_usd(줄) == "A756A000"
    with pytest.raises(ValueError):
        api.nearest_usd([줄[0], 줄[3]])


def test_틱_줄이_없으면_ValueError():
    with pytest.raises(ValueError):
        api.usd_spec([{"dtl_cd_ko_nm": "코스피200선물", "cd_val_inf_1": "0.05", "tick_val": "12500"}])


def test_순보유():
    assert api.net_position([{"sym": "A", "opint_qty": "2", "trd_div": "1"}, {"sym": "A", "opint_qty": "1", "trd_div": "2"}], "A") == 1
    assert api.net_position([{"sym": "B", "opint_qty": "000000000003.000000000", "trd_div": "2"}], "A") == 0
    assert api.net_position([{"sym": " A ", "opint_qty": "000000000003.000000000", "trd_div": " 2 "}], "A") == -3


# ── 재시도 ──────────────────────────────────────────────────


def test_조회는_호출_제한이면_다시_묻는다(config, 쉬는시간):
    서버_ = 차례서버({PRICE: [
        httpx.Response(200, json={"errorCode": "EGW036", "errorMessage": "초당 호출 제한"}),
        httpx.Response(200, json=기록("domestic_price", "real")),
    ]})
    client = TradeClient(세션(config, 서버_))

    got = api.price("A7569000", client=client)

    assert api.num(got["last_pric"]) == 1338.5
    assert 서버_.횟수(PRICE) == 2 and 쉬는시간 == [1]


def test_조회는_응답이_없어도_세_번까지_쉬며_다시_묻는다(config, 쉬는시간):
    서버_ = 차례서버({CHART: [httpx.ConnectTimeout("1"), httpx.ConnectTimeout("2"), httpx.ConnectTimeout("3")]})
    client = TradeClient(세션(config, 서버_))

    with pytest.raises(TransportError):
        api.chart_minute("A7569000", req_qty=5, client=client)

    assert 서버_.횟수(CHART) == 3 and 쉬는시간 == [1, 2]       # 1초, 2초 쉬고 세 번째가 마지막


def test_조회는_다시_해도_소용없는_거절은_바로_올린다(config, 쉬는시간):
    """EGW053(모의에서 안 되는 조회)·업무 거부는 다시 물어도 같다."""
    서버_ = 차례서버({PRICE: [httpx.Response(200, json={"errorCode": "EGW053", "errorMessage": "모의 미지원"})]})
    client = TradeClient(세션(config, 서버_))
    with pytest.raises(GatewayError) as 잡힌것:
        api.price("A7569000", client=client)
    assert 잡힌것.value.code == "EGW053"
    assert 서버_.횟수(PRICE) == 1 and 쉬는시간 == []


def test_재시도_거절이_세_번_이어지면_마지막_예외를_올린다(config, 쉬는시간):
    한줄 = httpx.Response(200, json={"errorCode": "EGW036", "errorMessage": "초당 호출 제한"})
    서버_ = 차례서버({PRICE: [한줄, 한줄, 한줄]})
    client = TradeClient(세션(config, 서버_))
    with pytest.raises(GatewayError):
        api.price("A7569000", client=client)
    assert 서버_.횟수(PRICE) == 3 and 쉬는시간 == [1, 2]


# ── 주문은 한 번 ────────────────────────────────────────────


def test_주문은_응답이_없어도_다시_보내지_않는다(config, 쉬는시간):
    client, 서버_ = 만들기(config, {ORDER: httpx.ConnectTimeout("끝내 못 받음")})
    with pytest.raises(TransportError):
        api.market_order("A7569000", "buy", client=client)
    assert 서버_.횟수(ORDER) == 1 and 쉬는시간 == []


def test_주문은_호출_제한_거절도_다시_보내지_않는다(config, 쉬는시간):
    client, 서버_ = 만들기(config, {ORDER: httpx.Response(200, json={"errorCode": "EGW036", "errorMessage": "제한"})})
    with pytest.raises(GatewayError):
        api.market_order("A7569000", "sell", client=client)
    assert 서버_.횟수(ORDER) == 1 and 쉬는시간 == []


def test_주문_업무_거부는_그대로_올린다(config):
    본문 = {"ord_no": "", "msg_cd": "40010", "msg_cntn": "주문가능수량을 초과했습니다"}
    client, _ = 만들기(config, {ORDER: httpx.Response(200, json=본문)})
    with pytest.raises(BusinessError) as 잡힌것:
        api.market_order("A7569000", "buy", client=client)
    assert 잡힌것.value.code == "40010"


def test_주문_접수_응답은_본문_그대로(config):
    본문 = 기록("domestic_order", "paper", {"trd_div": "1"})
    client, _ = 만들기(config, {ORDER: httpx.Response(200, json=본문)})
    got = api.market_order("A7569000", "buy", client=client)
    assert got == 본문 and got["ord_no"]


# ── 기본 접속 ───────────────────────────────────────────────


def test_client_를_안_주면_앱의_접속을_쓴다(config, monkeypatch):
    client, 서버_ = 만들기(config, {PRICE: httpx.Response(200, json=기록("domestic_price", "real"))})
    from backend.nh_api import runtime
    monkeypatch.setattr(runtime, "client", lambda: client)
    api.price("A7569000")
    assert 서버_.횟수(PRICE) == 1
