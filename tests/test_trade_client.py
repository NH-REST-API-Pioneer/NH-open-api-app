"""거래 API 공통 호출부."""
import json

import httpx
import pytest

from backend.auth.auth_functions import TokenManager
from backend.config import load_config
from backend.nh_api.catalog import Limit
from backend.nh_api.client import TradeClient, business_failure
from backend.nh_api import error_codes
from backend.nh_api.errors import (
    BusinessError,
    GatewayError,
    HttpError,
    TransportError,
)
from backend.nh_api.rate_limit import RateLimiter
from backend.nh_api.session import LIVE, Session

CONFIG = """
default_environment: paper
paper:
  base_url: "https://apidemo.example"
  domestic:
    app_key: "PAPERDOM"
    app_secret: "PAPERDOMSECRET"
  overseas:
    app_key: "PAPEROVS"
    app_secret: "PAPEROVSSECRET"
real:
  base_url: "https://api.example"
  domestic:
    app_key: "REALDOM"
    app_secret: "REALDOMSECRET"
"""

현재가 = {"sym_exch": "A7569000", "last_pric": "1338.50", "trd_qty": "6850"}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return load_config(path)


class 서버:
    """요청을 받아 두고 정해 둔 응답을 돌려준다."""

    def __init__(self, 응답들):
        self.응답들 = 응답들
        self.요청들 = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.요청들.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={"access_token": "TOKENVALUE", "token_type": "Bearer", "expires_in": "3600"},
            )
        결과 = self.응답들[request.url.path]
        if isinstance(결과, Exception):
            raise 결과
        return 결과

    def 횟수(self, path):
        return sum(1 for r in self.요청들 if r.url.path == path)


def 세션(config, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Session(
        mode=LIVE,
        config=config,
        client=client,
        tokens=TokenManager(config, client=client),
    )


def 만들기(config, 응답들, limiter=None):
    서버_ = 서버(응답들)
    return TradeClient(세션(config, 서버_), limiter=limiter), 서버_


def test_접속_토큰을_붙여_부른다(config):
    client, 서버_ = 만들기(config, {"/trade/v1/domestic/price": httpx.Response(200, json=현재가)})

    결과 = client.call("domestic_price", {"sym": "A7569000"})

    보낸것 = [r for r in 서버_.요청들 if r.url.path == "/trade/v1/domestic/price"][0]
    assert 보낸것.headers["Authorization"] == "Bearer TOKENVALUE"
    assert 보낸것.url.host == "apidemo.example"
    assert 결과.http_status == 200
    assert 결과.market == "domestic"
    assert 결과.environment == "paper"


def test_응답을_손대지_않고_돌려준다(config):
    client, _ = 만들기(config, {"/trade/v1/domestic/price": httpx.Response(200, json=현재가)})
    결과 = client.call("domestic_price", {"sym": "A7569000"})
    assert 결과.body == 현재가


def test_환경을_지정할_수_있다(config):
    client, 서버_ = 만들기(config, {"/trade/v1/domestic/price": httpx.Response(200, json=현재가)})
    client.call("domestic_price", {"sym": "A7569000"}, environment="real")
    보낸것 = [r for r in 서버_.요청들 if r.url.path == "/trade/v1/domestic/price"][0]
    assert 보낸것.url.host == "api.example"


def test_주문_응답의_처리코드가_비어_있으면_성공이다(config):
    응답 = {"ord_no": "5959762237", "msg_cd": "", "msg_cntn": ""}
    client, _ = 만들기(config, {"/trade/v1/domestic/order": httpx.Response(200, json=응답)})

    결과 = client.call("domestic_order", {"sym": "A7569000", "ord_qty": "1"})
    assert 결과.body["ord_no"] == "5959762237"


def test_HTTP_200_이어도_처리코드가_있으면_실패다(config):
    응답 = {"ord_no": "", "msg_cd": "40010", "msg_cntn": "주문가능수량을 초과했습니다"}
    client, _ = 만들기(config, {"/trade/v1/domestic/order": httpx.Response(200, json=응답)})

    with pytest.raises(BusinessError) as 잡힌것:
        client.call("domestic_order", {"sym": "A7569000", "ord_qty": "999"})

    assert 잡힌것.value.code == "40010"
    assert "주문가능수량" in 잡힌것.value.detail
    assert 잡힌것.value.body == 응답


def test_조회_결과가_0건인_것은_실패가_아니다(config):
    응답 = {"nxt_key": "", "nrec": "0000"}
    client, _ = 만들기(config, {"/trade/v1/domestic/open-interest": httpx.Response(200, json=응답)})

    결과 = client.call("domestic_open-interest", {"nxt_key": ""})
    assert 결과.body["nrec"] == "0000"


def test_HTTP_오류는_서버가_보낸_설명을_남긴다(config):
    응답 = {
        "errorTime": "2026-09-09 09:02:28",
        "errorMessage": "'09' 마켓 검색 실패 [SDIF7224Q02@dom]",
        "errorStatus": 400,
        "errorPath": "/trade/v1/domestic/price-all-option-night",
    }
    client, _ = 만들기(
        config, {"/trade/v1/domestic/price-all-option-night": httpx.Response(400, json=응답)}
    )

    with pytest.raises(HttpError) as 잡힌것:
        client.call("domestic_price-all-option-night", {"prd": "09"})

    assert 잡힌것.value.status == 400
    assert "마켓 검색 실패" in 잡힌것.value.message
    assert 잡힌것.value.body == 응답


def test_시간이_초과되면_확인하라고_알린다(config):
    client, _ = 만들기(
        config, {"/trade/v1/domestic/order": httpx.TimeoutException("timed out")}
    )

    with pytest.raises(TransportError) as 잡힌것:
        client.call("domestic_order", {"sym": "A7569000"})

    assert "주문내역" in 잡힌것.value.message


def test_실패해도_다시_보내지_않는다(config):
    client, 서버_ = 만들기(
        config, {"/trade/v1/domestic/order": httpx.TimeoutException("timed out")}
    )

    with pytest.raises(TransportError):
        client.call("domestic_order", {"sym": "A7569000"})

    assert 서버_.횟수("/trade/v1/domestic/order") == 1


def test_인증_API_는_이_자리에서_부르지_않는다(config):
    client, _ = 만들기(config, {})
    with pytest.raises(ValueError):
        client.call("token", {})


def test_모르는_API_는_거부한다(config):
    client, _ = 만들기(config, {})
    with pytest.raises(ValueError):
        client.call("없는_api", {})


def test_인증_정보가_없는_시장은_부르기_전에_걸린다(config):
    client, 서버_ = 만들기(config, {})
    with pytest.raises(Exception):
        client.call("overseas_price", {"sym": "MESU26"}, environment="real")
    assert 서버_.요청들 == []


def test_호출_간격을_지킨다(config):
    잔것 = []
    limiter = RateLimiter(monotonic=lambda: 0.0, sleep=잔것.append)
    client, _ = 만들기(
        config, {"/trade/v1/domestic/price": httpx.Response(200, json=현재가)}, limiter=limiter
    )

    for _ in range(3):
        client.call("domestic_price", {"sym": "A7569000"})

    # 시세는 초당 10건이므로 0.1초씩 벌어진다.
    assert 잔것 == pytest.approx([0.1, 0.2])


def test_처리코드_판정():
    assert business_failure({"msg_cd": "", "msg_cntn": ""}) is None
    assert business_failure({"nrec": "0000"}) is None
    assert business_failure("문자열") is None
    assert business_failure({"msg_cd": "40010", "msg_cntn": "설명"}) == ("40010", "설명")


def test_등급별_간격():
    assert RateLimiter.interval(Limit.QUOTE) == pytest.approx(0.1)
    assert RateLimiter.interval(Limit.ACCOUNT) == pytest.approx(0.1)
    assert RateLimiter.interval(Limit.ORDER) == pytest.approx(0.2)
    assert RateLimiter.interval(Limit.AUTH) == pytest.approx(1 / 3)


def test_등급과_환경마다_따로_센다():
    잔것 = []
    limiter = RateLimiter(monotonic=lambda: 0.0, sleep=잔것.append)

    limiter.wait("paper", "domestic", Limit.QUOTE)
    limiter.wait("paper", "domestic", Limit.ORDER)
    limiter.wait("real", "domestic", Limit.QUOTE)
    assert 잔것 == []

    limiter.wait("paper", "domestic", Limit.QUOTE)
    assert 잔것 == pytest.approx([0.1])


def test_시장이_다르면_따로_센다():
    """국내와 해외는 APP Key 가 따로 발급되는 서로 다른 계좌다."""
    잔것 = []
    limiter = RateLimiter(monotonic=lambda: 0.0, sleep=잔것.append)

    limiter.wait("real", "domestic", Limit.QUOTE)
    limiter.wait("real", "overseas", Limit.QUOTE)
    assert 잔것 == []


def test_같은_계좌는_간격을_지킨다():
    잔것 = []
    limiter = RateLimiter(monotonic=lambda: 0.0, sleep=잔것.append)

    limiter.wait("real", "domestic", Limit.QUOTE)
    limiter.wait("real", "domestic", Limit.QUOTE)
    assert 잔것 == pytest.approx([0.1])


def test_공통_호출부가_시장을_넘긴다(config):
    """국내를 부른 뒤 해외를 불러도 기다리지 않아야 한다."""
    잔것 = []
    limiter = RateLimiter(monotonic=lambda: 0.0, sleep=잔것.append)
    client, _ = 만들기(
        config,
        {
            "/trade/v1/domestic/price": httpx.Response(200, json=현재가),
            "/trade/v1/overseas/price": httpx.Response(200, json=현재가),
        },
        limiter=limiter,
    )

    client.call("domestic_price", {"sym": "A7569000"})
    client.call("overseas_price", {"sym": "MESU26"})
    assert 잔것 == []

    client.call("domestic_price", {"sym": "A7569000"})
    assert 잔것 == pytest.approx([0.1])


# ── 실전 환경 ──────────────────────────────────────────────
#
# **막지 않습니다.** 설정에 적힌 환경으로 그대로 나갑니다 — 조회도 주문도
# 같습니다. 어느 환경으로 갈지 고르는 자리는 설정 화면입니다.


def test_실전으로_주문이_나간다(config):
    """되돌릴 수 없는 요청이 실제 서버로 나가는 자리입니다."""
    응답 = {"ord_no": "5959762237", "msg_cd": "", "msg_cntn": ""}
    client, 서버_ = 만들기(config, {"/trade/v1/domestic/order": httpx.Response(200, json=응답)})

    결과 = client.call(
        "domestic_order", {"sym": "A7569000", "ord_qty": "1"}, environment="real"
    )

    보낸것 = [r for r in 서버_.요청들 if r.url.path == "/trade/v1/domestic/order"][0]
    assert 보낸것.url.host == "api.example", "실전 주소로 나갑니다."
    assert json.loads(보낸것.content) == {"sym": "A7569000", "ord_qty": "1"}, "본문 그대로"
    assert 결과.environment == "real"
    assert 결과.body["ord_no"] == "5959762237"


def test_주문_등급도_다른_조회와_같은_길로_간다(config):
    """등급으로 가르는 것은 호출 제한뿐입니다."""
    from backend.nh_api.catalog import HTTP_APIS

    주문들 = [spec.api_id for spec in HTTP_APIS.values() if spec.limit is Limit.ORDER]
    assert len(주문들) == 7, 주문들

    응답 = {"ord_no": "1", "msg_cd": "", "msg_cntn": ""}
    client, 서버_ = 만들기(
        config,
        {spec.path: httpx.Response(200, json=응답) for spec in HTTP_APIS.values()},
    )

    # 시험 설정에 실전 인증 정보가 있는 것은 국내뿐이라 국내 여섯만 부릅니다.
    국내주문 = [api_id for api_id in 주문들 if HTTP_APIS[api_id].market == "domestic"]
    assert len(국내주문) == 6, 국내주문

    for api_id in 국내주문:
        결과 = client.call(api_id, {"sym": "A7569000"}, environment="real")
        assert 결과.environment == "real"

    나간것 = {r.url.path for r in 서버_.요청들 if not r.url.path.endswith("/token")}
    assert 나간것 == {HTTP_APIS[api_id].path for api_id in 국내주문}


# ── 토큰을 안 받아 줄 때 ────────────────────────────────────


class 한번은거절하는서버:
    """첫 요청만 401 로 돌려보내고 그다음은 받아 줍니다."""

    def __init__(self, 응답):
        self.응답 = 응답
        self.토큰요청 = 0
        self.본요청 = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            self.토큰요청 += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"TOKEN{self.토큰요청}",
                    "token_type": "Bearer",
                    "expires_in": "3600",
                },
            )
        self.본요청 += 1
        if self.본요청 == 1:
            return httpx.Response(401, json={"errorMessage": "토큰이 유효하지 않습니다"})
        return self.응답


def test_토큰을_안_받아_주면_한_번_다시_받는다(config):
    """만료 전이라 여겼는데 서버가 거절하는 경우입니다."""
    서버_ = 한번은거절하는서버(httpx.Response(200, json=현재가))
    client = TradeClient(세션(config, 서버_))

    결과 = client.call("domestic_price", {"sym": "A7569000"})

    assert 결과.http_status == 200
    assert 서버_.본요청 == 2, "같은 요청을 한 번만 다시 보냅니다."
    assert 서버_.토큰요청 == 2, "토큰을 새로 받아 붙입니다."


class 늘거절하는서버(한번은거절하는서버):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            self.토큰요청 += 1
            return httpx.Response(
                200,
                json={"access_token": "T", "token_type": "Bearer", "expires_in": "3600"},
            )
        self.본요청 += 1
        return httpx.Response(401, json={"errorMessage": "토큰이 유효하지 않습니다"})


def test_다시_받아도_거절되면_그대로_올린다(config):
    """반복하면 인증 호출 제한에 걸리고, 그래도 안 될 일은 안 됩니다."""
    서버_ = 늘거절하는서버(httpx.Response(200, json=현재가))
    client = TradeClient(세션(config, 서버_))

    with pytest.raises(HttpError) as 잡힌것:
        client.call("domestic_price", {"sym": "A7569000"})

    assert 잡힌것.value.status == 401
    assert 서버_.본요청 == 2, "두 번까지입니다."


# ── 본문에 실린 오류 코드 ───────────────────────────────────
#
# **상태 코드만 보면 놓칩니다.** 200 으로 오면서 본문에만 실패가 적혀 오는
# 자리가 있습니다.


def test_200_이어도_본문에_오류코드가_있으면_실패다(config):
    응답 = {"errorCode": "EGW034", "errorMessage": "게이트웨이 내부 오류"}
    client, _ = 만들기(config, {"/trade/v1/domestic/price": httpx.Response(200, json=응답)})

    with pytest.raises(GatewayError) as 잡힌것:
        client.call("domestic_price", {"sym": "A7569000"})

    assert 잡힌것.value.code == "EGW034"
    assert 잡힌것.value.kind == error_codes.RETRY


def test_게이트웨이_거절과_업무_거부를_가린다(config):
    """주문 화면이 둘을 같은 말로 적으면 이미 나간 주문을 안 나갔다고 말합니다."""
    응답 = {"errorCode": "50013", "errorMessage": "주문가격을 확인하십시요."}
    client, _ = 만들기(config, {"/trade/v1/domestic/order": httpx.Response(200, json=응답)})

    with pytest.raises(BusinessError) as 잡힌것:
        client.call("domestic_order", {"sym": "A7569000", "ord_qty": "1"})

    assert 잡힌것.value.code == "50013"
    # 숫자 코드는 업무 쪽입니다. 게이트웨이 코드가 아닙니다.
    assert not isinstance(잡힌것.value, GatewayError)


def test_정상_코드는_실패로_안_본다(config):
    """토큰 발급 성공에도 코드가 실려 옵니다."""
    응답 = {"errorCode": "EGW013", "nrec": "0"}
    client, _ = 만들기(config, {"/trade/v1/domestic/price": httpx.Response(200, json=응답)})

    결과 = client.call("domestic_price", {"sym": "A7569000"})

    assert 결과.body["errorCode"] == "EGW013"


class 토큰을거절하는서버:
    """첫 요청만 본문으로 「토큰 다시 받아라」를 돌려보냅니다."""

    def __init__(self, 응답):
        self.응답 = 응답
        self.토큰요청 = 0
        self.본요청 = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            self.토큰요청 += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"TOKEN{self.토큰요청}",
                    "token_type": "Bearer",
                    "expires_in": "3600",
                },
            )
        self.본요청 += 1
        if self.본요청 == 1:
            # 상태는 200 인데 본문이 재발급을 말합니다.
            return httpx.Response(200, json={"errorCode": "EGW052"})
        return self.응답


def test_본문이_재발급을_말해도_한_번_다시_받는다(config):
    """401 과 같은 길입니다 — 상태만 보면 이 자리를 놓칩니다."""
    서버_ = 토큰을거절하는서버(httpx.Response(200, json=현재가))
    client = TradeClient(세션(config, 서버_))

    결과 = client.call("domestic_price", {"sym": "A7569000"})

    assert 결과.http_status == 200
    assert 서버_.본요청 == 2, "같은 요청을 한 번만 다시 보냅니다."
    assert 서버_.토큰요청 == 2, "토큰을 새로 받아 붙입니다."
