"""`/api/domestic` 라우트 — 국내 시세.

저장해 둔 응답으로 돌립니다. **NH선물 서버에 접속하지 않습니다.**

`TestClient(app)` 을 `with` 없이 씁니다. `with` 로 감싸면 서버 기동 절차가
돌면서 마스터를 실제로 내려받으러 나갑니다.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import orders
from backend.domestic_futureoption import domestic_routes
from backend.domestic_futureoption.domestic_routes import get_client
from backend.main import app
from backend.nh_api.client import ApiResult, TradeClient
from backend.nh_api.errors import BusinessError, HttpError, TransportError
from backend.nh_api.replay import MATCH_HEADER
from backend.nh_api.session import create_session

SYMBOL = "A7569000"
DATE = "20260909"


@pytest.fixture
def client():
    """저장해 둔 응답으로 답하는 호출부로 바꿔 끼웁니다.

    기본 환경은 모의입니다. 국내 시세 기록은 전부 실전에서 수집됐지만, 재생이
    다른 환경에서도 **요청이 같은 기록**을 찾으므로 종목마다 제 값이 옵니다.
    """
    session = create_session(replay=True)
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()


class 터지는호출부:
    """정해 둔 예외를 내는 호출부."""

    def __init__(self, 예외):
        self.예외 = 예외

    def call(self, *args, **kwargs):
        raise self.예외


@pytest.fixture
def 터지는(request):
    app.dependency_overrides[get_client] = lambda: 터지는호출부(request.param)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_현재가가_화면_모양으로_온다(client):
    응답 = client.post("/api/domestic/price", json={"sym": SYMBOL})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["code"] == SYMBOL
    assert isinstance(몸["last"], float)
    assert isinstance(몸["volume"], int)
    # 원문 필드 이름은 백엔드 밖으로 나가지 않는다.
    assert "last_pric" not in 몸
    assert "chg_sign" not in 몸


def test_선물전체시세가_월물_목록으로_온다(client):
    """만기 목록이 쓰는 자리 — 품목 하나의 월물이 한 번에 옵니다."""
    응답 = client.post("/api/domestic/price-all", json={"prd": "01"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert (몸["product"], 몸["count"]) == ("01", 7)
    assert len(몸["rows"]) == 7
    첫줄 = 몸["rows"][0]
    assert (첫줄["code"], 첫줄["last"], 첫줄["change"]) == ("A0169000", 1105.3, 6.9)
    assert (첫줄["volume"], 첫줄["openInterest"]) == (2498, 99203)
    # 야간 전체시세 API 가 없어 밤에도 주간 값입니다. 화면이 알아보라는 표지.
    assert 몸["session"] == "day"
    assert 몸["asOf"].endswith("+09:00")
    assert 응답.headers[MATCH_HEADER] != "empty"
    assert "occurs1_" not in 응답.text


def test_선물전체시세는_품목코드_두_자리만_받는다(client):
    """명세에 필수이고 「전체」에 해당하는 값이 없습니다."""
    나쁜값들 = ({}, {"prd": ""}, {"prd": "1"}, {"prd": "012"}, {"prd": "ab"})
    for 나쁜값 in 나쁜값들:
        assert client.post("/api/domestic/price-all", json=나쁜값).status_code == 422, 나쁜값


def test_모르는_품목의_선물전체시세는_빈_응답이다(client):
    응답 = client.post("/api/domestic/price-all", json={"prd": "ZZ"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    # 값을 지어내지 않습니다. 무엇을 물었는지는 남깁니다.
    assert (몸["rows"], 몸["count"], 몸["product"]) == ([], 0, "ZZ")
    assert 응답.headers[MATCH_HEADER] == "empty"


def test_투자자_매매동향이_무리_목록으로_온다(client):
    응답 = client.post("/api/domestic/trend-investor", json={"prd": "75"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert len(몸["investors"]) == 11
    개인 = 몸["investors"][0]
    assert (개인["group"], 개인["buy"], 개인["netBuy"]) == ("individual", 3165, 1758)
    assert (몸["unit"], 몸["time"], 몸["instrument"]) == ("quantity", "09:01:30", "KRDRVFUUSD")
    assert 응답.headers[MATCH_HEADER] != "empty"
    assert "ind_buy" not in 응답.text, "원문 칸 이름은 밖으로 나가지 않습니다."


def test_투자자_매매동향_요청을_백엔드가_조립한다():
    """NH 는 품목과 선물·콜·풋을 붙인 네 자리로 받습니다."""
    호출부 = 적어두는호출부({})
    app.dependency_overrides[get_client] = lambda: 호출부
    try:
        앱 = TestClient(app)
        앱.post("/api/domestic/trend-investor", json={"prd": "75"})
        앱.post("/api/domestic/trend-investor", json={"prd": "01", "kind": "call"})
        앱.post(
            "/api/domestic/trend-investor",
            json={"prd": "06", "kind": "put", "ref_dt": "20260909", "inq_tp": "2"},
        )
    finally:
        app.dependency_overrides.pop(get_client, None)

    보낸것 = [본문 for _, 본문 in 호출부.보낸것]
    assert [하나["opt_prd"] for 하나 in 보낸것] == ["751", "012", "063"]
    assert [하나["inq_tp"] for 하나 in 보낸것] == ["1", "1", "2"]
    # 기준일을 비우면 한국시간의 오늘로 채웁니다. 준 날은 그대로 나갑니다.
    오늘 = domestic_routes.now_kst().strftime("%Y%m%d")
    assert [하나["ref_dt"] for 하나 in 보낸것] == [오늘, 오늘, "20260909"]
    assert all(이름 == "domestic_trend-investor" for 이름, _ in 호출부.보낸것)


def test_투자자_매매동향은_품목과_종류를_모양대로_받는다(client):
    나쁜값들 = (
        {},
        {"prd": "7"},
        {"prd": "755"},
        {"prd": "75", "kind": "stock"},
        {"prd": "75", "ref_dt": "2026"},
        {"prd": "75", "inq_tp": "3"},
    )
    for 나쁜값 in 나쁜값들:
        assert client.post("/api/domestic/trend-investor", json=나쁜값).status_code == 422, 나쁜값


def test_기록_없는_품목의_투자자_매매동향은_빈_목록이다(client):
    응답 = client.post("/api/domestic/trend-investor", json={"prd": "01"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    # 값을 0 으로 지어내지 않습니다. 무엇을 물었는지는 남깁니다.
    assert 몸["investors"] == [] and 몸["unit"] == "quantity"
    assert 응답.headers[MATCH_HEADER] == "empty"


def test_옵션_체인이_한_덩이로_온다(client):
    """저장본은 다음 쪽을 물어도 같은 기록을 주므로 첫 쪽 261줄이 한 번만 담긴다."""
    응답 = client.post("/api/domestic/option-chain", json={"prd": "01", "exp_mon": "260910"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["session"] == "day" and 몸["count"] == 261
    assert 몸["future"]["code"] == "A0169000"
    줄 = 몸["rows"][0]
    assert 줄["call"]["code"] == "B0169C42" and 줄["put"]["code"] == "C0169C42"
    assert 몸["asOf"].endswith("+09:00")
    assert 응답.headers[MATCH_HEADER] != "empty"
    assert "occurs1_" not in 응답.text


def test_야간_옵션_체인은_야간_API_로_부른다(client):
    몸 = client.post(
        "/api/domestic/option-chain", json={"prd": "01", "exp_mon": "260910", "session": "night"}
    ).json()
    assert 몸["session"] == "night" and 몸["count"] == 400
    assert 몸["future"] is None
    assert 몸["rows"][0]["call"]["last"] is None


def test_옵션_체인은_품목과_만기를_모양대로_받는다(client):
    나쁜값들 = (
        {},
        {"prd": "1", "exp_mon": "260910"},
        {"prd": "01", "exp_mon": "2609"},
        {"prd": "01", "exp_mon": "260910", "session": "dawn"},
    )
    for 나쁜값 in 나쁜값들:
        assert client.post("/api/domestic/option-chain", json=나쁜값).status_code == 422, 나쁜값


def test_없는_만기의_옵션_체인은_빈_응답이다(client):
    응답 = client.post("/api/domestic/option-chain", json={"prd": "01", "exp_mon": "991231"})
    assert 응답.status_code == 200
    assert 응답.json()["rows"] == []
    assert 응답.headers[MATCH_HEADER] == "empty"


def test_호가가_화면_순서로_온다(client):
    몸 = client.post("/api/domestic/price-bid", json={"sym": SYMBOL}).json()

    assert 몸["asks"] and 몸["bids"]
    # 매도는 먼 값부터, 매수는 가까운 값부터.
    assert 몸["asks"][-1]["price"] > 몸["bids"][0]["price"]
    assert [단계["price"] for 단계 in 몸["asks"]] == sorted(
        (단계["price"] for 단계 in 몸["asks"]), reverse=True
    )
    # 값이 안 채워진 단계는 빠진다.
    assert all(단계["price"] > 0 for 단계 in 몸["asks"] + 몸["bids"])
    # 호가 시각은 실시간 호가와 같은 자리·같은 모양(HH:MM:SS)이다.
    assert 몸["time"] and len(몸["time"]) == 8 and 몸["time"][2] == ":"
    # 예상체결가 칸은 늘 있고, 접속매매 중 기록이라 값은 없다.
    assert "expectedPrice" in 몸 and 몸["expectedPrice"] is None


def test_분봉이_오래된_것부터_온다(client):
    몸 = client.post(
        "/api/domestic/chart-minute",
        json={"sym": SYMBOL, "inq_strt_dt": DATE, "inq_ed_dt": DATE},
    ).json()

    assert 몸["bars"]
    시각 = [봉["timestamp"] for 봉 in 몸["bars"]]
    assert 시각 == sorted(시각)
    assert set(몸["bars"][0]) == {"timestamp", "open", "high", "low", "close", "volume"}


def test_일봉은_저장해_둔_자료로는_0개로_나온다(client):
    """봉이 실제로 있는데 **날짜 칸이 가려진 채로** 저장되어 있다.

    수집기가 연속조회 키를 가명으로 바꿀 때, 그 키와 글자가 같았던 봉의 날짜까지
    함께 덮였다. NH선물이 이상한 값을 보낸 것이 아니고 실서버로 부르면 날짜가
    그대로 온다. 봉이 사라진 것은 `skipped` 로 드러난다.
    """
    응답 = client.post(
        "/api/domestic/chart-daily",
        json={"sym": SYMBOL, "inq_strt_dt": DATE, "inq_ed_dt": DATE, "night": True},
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["bars"] == []
    assert 몸["skipped"] == 1


def test_야간_현재가는_현물가_자리가_비어_온다(client):
    몸 = client.post("/api/domestic/price-night", json={"sym": SYMBOL}).json()

    assert 몸["last"] is not None
    assert 몸["spot"] is None
    assert 몸["spotChange"] is None


def test_종목코드가_없으면_422(client):
    assert client.post("/api/domestic/price", json={}).status_code == 422
    assert client.post("/api/domestic/price", json={"sym": ""}).status_code == 422


def test_주소에_시장_칸이_있다():
    """거래 API 는 `/api/{시장}/{API 이름}` 규칙을 따른다."""
    경로들 = set(app.openapi()["paths"])
    assert {
        "/api/domestic/price",
        "/api/domestic/price-night",
        "/api/domestic/price-bid",
        "/api/domestic/chart-daily",
        "/api/domestic/chart-minute",
    } <= 경로들


@pytest.mark.parametrize(
    "터지는,기대",
    [
        (TransportError("domestic_price", "시간이 초과되었습니다"), 504),
        (HttpError("domestic_price", 400, {"errorMessage": "'A7569000' 종목 없음"}), 502),
    ],
    indirect=["터지는"],
)
def test_실패는_화면용_문구로_온다(터지는, 기대):
    """코드 없는 실패는 화면용 문구만 냅니다. 서버 문구에 실린 요청 값이 되비치지 않습니다."""
    응답 = 터지는.post("/api/domestic/price", json={"sym": SYMBOL})

    assert 응답.status_code == 기대
    detail = 응답.json()["detail"]
    assert "A7569000" not in detail
    assert detail
    assert "x-nh-error-code" not in 응답.headers


@pytest.mark.parametrize(
    "터지는",
    [BusinessError("domestic_price", "40010", "거부되었습니다", {})],
    indirect=True,
)
def test_코드가_있는_시세_거절은_코드와_원문을_싣는다(터지는):
    응답 = 터지는.post("/api/domestic/price", json={"sym": SYMBOL})

    assert 응답.status_code == 502
    assert 응답.json()["detail"] == "시세 조회가 거절되었습니다 — 40010 거부되었습니다"
    assert 응답.headers["x-nh-error-code"] == "40010"
    assert 응답.headers["x-nh-error-kind"] == "other"


@pytest.mark.parametrize(
    "터지는",
    [BusinessError("domestic_orderable-quantity", "5033", "[주문불가계좌] 계좌입니다. 계좌번호를 확인하세요.", {})],
    indirect=True,
)
def test_코드가_있는_계좌_조회_거절은_계좌_문장에_코드와_원문을_싣는다(터지는):
    응답 = 터지는.post(
        "/api/domestic/orderable-quantity",
        json={"sym": SYMBOL, "side": "buy", "ord_pric": "405.25"},
    )

    assert 응답.status_code == 502
    assert 응답.json()["detail"] == "계좌 조회가 거절되었습니다 — 5033 [주문불가계좌] 계좌입니다. 계좌번호를 확인하세요."
    assert (응답.headers["x-nh-error-code"], 응답.headers["x-nh-error-kind"]) == ("5033", "other")


@pytest.mark.parametrize(
    "터지는",
    [HttpError("domestic_orderable-quantity", 400, {"errorMessage": "잘못된 요청"})],
    indirect=True,
)
def test_코드가_없는_계좌_조회_거절은_기존_문구_그대로다(터지는):
    응답 = 터지는.post(
        "/api/domestic/orderable-quantity",
        json={"sym": SYMBOL, "side": "buy", "ord_pric": "405.25"},
    )

    assert 응답.status_code == 502
    assert 응답.json()["detail"] == domestic_routes._ACCOUNT_REJECTED
    assert "x-nh-error-code" not in 응답.headers


def test_실서버로_나가지_않는다(client):
    """재생 모드로 돌리는 동안 밖으로 나가는 요청이 없어야 한다."""
    보낸것 = []

    실제 = httpx.Client.send

    def 지켜보기(self, request, *args, **kwargs):
        보낸것.append(str(request.url))
        return 실제(self, request, *args, **kwargs)

    httpx.Client.send = 지켜보기
    try:
        client.post("/api/domestic/price", json={"sym": SYMBOL})
    finally:
        httpx.Client.send = 실제

    assert 보낸것, "요청이 한 번은 나가야 한다"
    assert all("futures.co.kr" not in 주소 for 주소 in 보낸것), 보낸것


# ── 계좌 ────────────────────────────────────────────────────


def test_예수금이_화면_모양으로_온다(client):
    응답 = client.post("/api/domestic/deposit", json={"biz_dt": "20260909"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["date"] == "2026-09-09"
    assert len(몸["items"]) == 7
    assert all(len(줄["values"]) == 4 for 줄 in 몸["items"])
    # 원문 항목 이름은 백엔드 밖으로 나가지 않는다.
    assert "dps_aset_tot_amt" not in 몸
    assert "mtn_mrgn_tam_amt" not in 몸


def test_예수금은_영업일자를_여덟_자리로_받는다(client):
    assert client.post("/api/domestic/deposit", json={"biz_dt": "2026"}).status_code == 422
    assert client.post("/api/domestic/deposit", json={"biz_dt": "2026abcd"}).status_code == 422


def _한국시간_고정(monkeypatch, 언제: str):
    """라우트가 보는 「지금(한국시간)」을 고정합니다 — 컴퓨터 시간대와 무관하게."""
    from datetime import datetime

    from backend.sessions.hours import KST

    고정 = datetime.strptime(언제, "%Y%m%d %H:%M").replace(tzinfo=KST)
    monkeypatch.setattr(domestic_routes, "now_kst", lambda: 고정)


def test_영업일자를_비우면_오늘로_부른다(monkeypatch):
    """화면이 날짜를 지어내지 않게 백엔드가 채웁니다 — 한국시간의 오늘로."""
    # 한국시간 16일 00:30 — 세계시로는 아직 15일 15:30 입니다.
    _한국시간_고정(monkeypatch, "20260916 00:30")
    앱, 호출부 = _세운다({"biz_dt": "20260916", "ord_psb_tot_amt": "0", "dps_amt": "0"})
    try:
        응답 = 앱.post("/api/domestic/deposit", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    assert 호출부.보낸것[-1][1]["biz_dt"] == "20260916"
    # 화면에 적는 날짜도 같은 값이어야 합니다.
    assert 응답.json()["date"] == "2026-09-16"


def test_영업일자를_주면_그_날로_부른다():
    앱, 호출부 = _세운다({"biz_dt": "20260101"})
    try:
        앱.post("/api/domestic/deposit", json={"biz_dt": "20260101"})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 호출부.보낸것[-1][1]["biz_dt"] == "20260101"


def test_잔고내역이_화면_모양으로_온다(client):
    응답 = client.post("/api/domestic/open-interest", json={})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert isinstance(몸["positions"], list)
    assert "nextKey" in 몸
    # 원문 항목 이름과 계좌번호는 백엔드 밖으로 나가지 않는다.
    담긴것 = 응답.text
    assert "occurs1_" not in 담긴것
    assert "ac_no" not in 담긴것


def test_주문내역이_화면_모양으로_온다(client):
    응답 = client.post("/api/domestic/order-history", json={"exec_div": "0"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert isinstance(몸["orders"], list)
    assert "nextKey" in 몸
    담긴것 = 응답.text
    assert "occurs1_" not in 담긴것
    for 이름 in ("ac_no", "ac_nm", "user_ip_addr", "ord_id"):
        assert 이름 not in 담긴것


def test_주문내역_조건은_정해진_값만_받는다(client):
    assert client.post("/api/domestic/order-history", json={"exec_div": "9"}).status_code == 422
    assert client.post("/api/domestic/order-history", json={"trd_div": "x"}).status_code == 422
    # 안 주면 전체로 봅니다.
    assert client.post("/api/domestic/order-history", json={}).status_code == 200


def test_재생에서_잔고_줄이_실제로_옵니다(client):
    """빈 기록이 먼저 뽑히면 이 단언이 헛돕니다 — 화면이 늘 빈 표를 봅니다."""
    응답 = client.post("/api/domestic/open-interest", json={})

    assert 응답.status_code == 200
    assert 응답.json()["positions"], "저장해 둔 잔고에 줄이 있어야 합니다."
    # 줄이 있는 위에서 확인해야 뜻이 있습니다.
    assert "ac_no" not in 응답.text


# ── 주문 오류 ───────────────────────────────────────────────
#
# **저장소에 이 응답의 저장본이 없습니다.** 실전 기록 셋은 저장소에 안 올리는
# 자리에 있고 그마저 줄이 0 입니다. 그래서 재생 클라이언트가 아니라 **만들어
# 낸 저장소**로 세웁니다 — 다른 라우트 시험과 방식이 다른 까닭입니다.


def _오류저장소():
    from pathlib import Path

    from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore, _build

    기록 = {
        "format": FIXTURE_FORMAT,
        "transport": "HTTP",
        "api_id": "domestic_order-error",
        "environment": "paper",
        "market": "domestic",
        "record_id": "made-up",
        "collected_at": "2026-09-09T00:00:00+00:00",
        "scenario_id": "domestic_order-error__base",
        "test_group": "",
        "status": "response_received",
        "method": "POST",
        "path": "/trade/v1/domestic/order-error",
        "http_status": 200,
        "request": {"inq_dt": "20260909", "trd_div_cd": "0", "nxt_key": ""},
        "response": {
            "data_tot_cnt": "00000000001",
            "nxt_data_yn": "N",
            "nxt_key": "",
            "nrec": "0001",
            "Occurs1": [
                {
                    "occurs1_rcv_tm": "152122966",
                    "occurs1_ac_no": "FAKE-AC-000000",
                    "occurs1_ac_nm": "FAKE-AC-NAME",
                    "occurs1_sym": "A7569000",
                    "occurs1_sym_nm": "미국달러 F 202609",
                    "occurs1_msg_cd": "40015",
                    "occurs1_msg": "주문가능수량을 초과했습니다.",
                    "occurs1_trd_div_cd": "1",
                    "occurs1_ord_tp_cd": "2",
                    "occurs1_ord_tp_nm": "시장가",
                    "occurs1_med_div": "R",
                }
            ],
        },
    }
    return FixtureStore([_build(기록, Path("메모리"))], Path("메모리"))


@pytest.fixture
def 오류client():
    session = create_session(replay=True, fixtures=_오류저장소())
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()


def test_주문_오류가_화면_모양으로_온다(오류client):
    응답 = 오류client.post(
        "/api/domestic/order-error", json={"inq_dt": "20260909", "trd_div_cd": "0"}
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert len(몸["errors"]) == 1
    assert 몸["total"] == 1
    assert 몸["hasMore"] is False
    담긴것 = 응답.text
    assert "occurs1_" not in 담긴것
    assert "ac_no" not in 담긴것
    assert "FAKE-AC-000000" not in 담긴것


def test_주문_오류는_조회일자를_여덟_자리로_받는다(오류client):
    for 나쁜값 in ({"inq_dt": "2026"}, {"inq_dt": "2026abcd"}):
        assert 오류client.post("/api/domestic/order-error", json=나쁜값).status_code == 422


def test_주문_오류도_조회일자를_비우면_오늘로_부른다(monkeypatch):
    """예수금·해외 주문오류와 같은 규칙입니다 — 화면이 날짜를 지어내지 않게."""
    _한국시간_고정(monkeypatch, "20260916 23:30")
    오늘 = "20260916"
    앱, 호출부 = _세운다({"data_tot_cnt": "0", "nxt_data_yn": "N", "nxt_key": ""})
    try:
        응답 = 앱.post("/api/domestic/order-error", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    assert 응답.json()["errors"] == []
    api_id, 보낸것 = 호출부.보낸것[-1]
    assert api_id == "domestic_order-error"
    assert 보낸것["inq_dt"] == 오늘


def test_주문_오류에_조회일자를_주면_그_날로_부른다():
    앱, 호출부 = _세운다({"data_tot_cnt": "0", "nxt_data_yn": "N"})
    try:
        앱.post("/api/domestic/order-error", json={"inq_dt": "20260101"})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 호출부.보낸것[-1][1]["inq_dt"] == "20260101"


# ── 주문가능수량 ────────────────────────────────────────────
#
# 이 조회도 저장본이 **한 건도 없습니다**. 무엇을 보내는지까지 봐야 해서
# 저장소가 아니라 **받은 요청을 적어 두는 호출부**로 세웁니다.


class 적어두는호출부:
    """부른 값을 적어 두고 정해 둔 응답을 내는 호출부.

    주문 라우트가 어느 환경인지 보므로 그 자리도 흉내 냅니다.
    """

    def __init__(
        self, 응답, *, environment="paper", replay=False, 터질것=None, 보내기전에터짐=False
    ):
        self.응답 = 응답
        self.보낸것 = []
        self.터질것 = 터질것
        # 실전 차단은 **보내기 전에** 납니다. 그 자리를 흉내 낼 때는 적어 두지도
        # 않아야 「보낸 것 없음」이 뜻을 가집니다.
        self.보내기전에터짐 = 보내기전에터짐
        # 시장 참고 자료는 인증 정보가 있는 환경을 골라 부르므로 그 자리도 흉내 냅니다.
        # 활성 환경 하나에만 두 시장의 인증 정보가 있습니다.
        self.session = SimpleNamespace(
            config=SimpleNamespace(
                default_environment=environment,
                environments={
                    environment: SimpleNamespace(configured_markets=("domestic", "overseas"))
                },
            ),
            is_replay=replay,
        )

    def call(self, api_id, payload, environment=None):
        if self.터질것 is not None and self.보내기전에터짐:
            raise self.터질것
        self.보낸것.append((api_id, dict(payload)))
        if self.터질것 is not None:
            raise self.터질것
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market="domestic",
            http_status=200,
            body=self.응답,
            headers={},
        )


@pytest.fixture
def 적어두는():
    호출부 = 적어두는호출부(
        {"ord_psb_qty": "3", "cls_psb_qty": "2", "tot_psb_qty": "5", "ord_psb_amt": "1234.5"}
    )
    app.dependency_overrides[get_client] = lambda: 호출부
    try:
        yield TestClient(app), 호출부
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_주문가능수량이_화면_모양으로_온다(적어두는):
    앱, _ = 적어두는
    응답 = 앱.post(
        "/api/domestic/orderable-quantity",
        json={"sym": SYMBOL, "side": "buy", "ord_pric": "405.25"},
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert (몸["quantity"], 몸["newQuantity"], 몸["closeQuantity"]) == (5, 3, 2)
    assert 몸["market"] == "domestic"
    assert 몸["side"] == "buy"
    담긴것 = 응답.text
    assert "tot_psb_qty" not in 담긴것
    assert "ord_psb_amt" not in 담긴것


def test_매수와_매도를_다른_값으로_부른다(적어두는):
    앱, 호출부 = 적어두는
    for 낱말, 코드 in (("buy", "1"), ("sell", "2")):
        앱.post(
            "/api/domestic/orderable-quantity",
            json={"sym": SYMBOL, "side": 낱말, "ord_pric": "405.25"},
        )
        assert 호출부.보낸것[-1][1]["trd_div"] == 코드


def test_야간이면_처리구분이_바뀐다(적어두는):
    """주간 1, 야간 3. 법인(2·4)은 안 씁니다."""
    앱, 호출부 = 적어두는
    앱.post(
        "/api/domestic/orderable-quantity",
        json={"sym": SYMBOL, "side": "buy", "ord_pric": "405.25"},
    )
    assert 호출부.보낸것[-1][1]["ord_sts"] == "1"

    앱.post(
        "/api/domestic/orderable-quantity",
        json={
            "sym": SYMBOL,
            "side": "buy",
            "ord_pric": "405.25",
            "context": "domestic-night",
        },
    )
    보낸것 = 호출부.보낸것[-1][1]
    assert 보낸것["ord_sts"] == "3"
    assert 보낸것["rt_tp"] == "2", "수량까지 달라고 해야 합니다."


def test_가격이_없거나_글자면_안_부른다(적어두는):
    앱, 호출부 = 적어두는
    나쁜값들 = (
        {"sym": SYMBOL, "side": "buy"},
        {"sym": SYMBOL, "side": "buy", "ord_pric": ""},
        {"sym": SYMBOL, "side": "buy", "ord_pric": "시장가"},
        {"sym": SYMBOL, "side": "long", "ord_pric": "405.25"},
        {"side": "buy", "ord_pric": "405.25"},
    )
    for 나쁜값 in 나쁜값들:
        assert 앱.post("/api/domestic/orderable-quantity", json=나쁜값).status_code == 422, 나쁜값
    assert 호출부.보낸것 == [], "값이 틀리면 NH선물을 부르지 않습니다."


# ── 주문·정정·취소 ──────────────────────────────────────────
#
# **아무 주문도 나가지 않습니다.** 저장본으로 답하거나, 받은 요청을 적어 두는
# 호출부로 세웁니다. 실전 환경 차단과 재생 거부도 여기서 봅니다.

주문응답 = {"ord_no": "5959762237", "msg_cd": "", "msg_cntn": ""}


def _주문(**덮어쓰기):
    # 화면이 믿는 환경. 흉내 낸 호출부의 기본값(모의)과 같게 둡니다.
    물음 = {"environment": "paper", "sym": SYMBOL, "side": "buy", "ord_qty": 1, "ord_tp_cd": "2"}
    물음.update(덮어쓰기)
    return 물음


def _세운다(응답=None, **설정):
    호출부 = 적어두는호출부(주문응답 if 응답 is None else 응답, **설정)
    app.dependency_overrides[get_client] = lambda: 호출부
    return TestClient(app), 호출부


@pytest.fixture
def 주문():
    앱, 호출부 = _세운다()
    try:
        yield 앱, 호출부
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_신규주문이_접수되면_화면_모양으로_온다(주문):
    앱, 호출부 = 주문
    응답 = 앱.post("/api/domestic/order", json=_주문())

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is True
    assert 몸["id"] == "5959762237"
    # 국내 응답에는 종목도 수량도 없어 보낸 값을 되비칩니다.
    assert (몸["market"], 몸["code"], 몸["side"], 몸["quantity"]) == (
        "domestic",
        SYMBOL,
        "buy",
        1,
    )
    api_id, 보낸것 = 호출부.보낸것[-1]
    assert api_id == "domestic_order"
    assert 보낸것["trd_div"] == "1"
    assert 보낸것["ord_pric"] == "0", "시장가는 명세대로 0 을 싣습니다."
    assert 보낸것["exec_cnd_cd"] == "1"


def test_신규_접수_답이_미체결_표_한_줄이다(주문, monkeypatch):
    """화면이 목록 위에 그대로 얹습니다 — 칸 이름이 주문내역 줄과 같아야 합니다."""
    monkeypatch.setattr(domestic_routes, "now_kst", _접수시각)
    앱, _ = 주문
    몸 = 앱.post("/api/domestic/order", json=_주문(ord_tp_cd="1", ord_pric="405.25")).json()

    assert (몸["status"], 몸["statusCode"]) == ("accepted", "1")
    # 방금 낸 주문이라 체결된 것이 없고 잔량은 주문수량 그대로입니다.
    assert (몸["filled"], 몸["remaining"], 몸["quantity"]) == (0, 1, 1)
    assert (몸["orderTypeCode"], 몸["orderType"]) == ("1", "지정가")
    assert (몸["fillConditionCode"], 몸["fillCondition"]) == ("1", "FAS")
    assert 몸["price"] == 405.25
    assert (몸["orderKind"], 몸["context"]) == ("new", "domestic-day")
    # 이 앱이 낸 주문이라 화면에서 고칠 수 있습니다.
    assert (몸["sourceCode"], 몸["source"], 몸["editable"]) == ("R", "REST API", True)
    # 접수 시각은 서버의 한국시간입니다 — 응답에 그 칸이 없습니다.
    assert 몸["acceptedAt"] == "2026-09-17T10:04:56+09:00"
    assert (몸["date"], 몸["time"]) == ("2026-09-17", "10:04:56")
    assert "originalOrderNo" not in 몸, "신규에는 원주문이 없습니다."


def test_시장가_접수_답에는_가격이_없다(주문):
    """시장가는 `0` 을 실어 보냅니다. 0 을 그대로 내면 화면에 「0」이 섭니다."""
    앱, _ = 주문
    몸 = 앱.post("/api/domestic/order", json=_주문()).json()

    assert "price" not in 몸
    assert (몸["orderTypeCode"], 몸["orderType"]) == ("2", "시장가")


def test_정정_접수_답은_바뀐_값과_원주문번호를_담는다(주문):
    앱, _ = 주문
    몸 = 앱.post(
        "/api/domestic/modify",
        json=_주문(ord_tp_cd="1", ord_pric="405.50", ord_qty=3, org_ord_no="1"),
    ).json()

    assert 몸["orderKind"] == "modify"
    assert (몸["quantity"], 몸["remaining"], 몸["price"]) == (3, 3, 405.50)
    assert (몸["status"], 몸["statusCode"]) == ("accepted", "1")
    # 보낸 모양 그대로 — 뒤에 오는 알림과 조회가 이 글자로 말합니다.
    assert 몸["originalOrderNo"] == "0000000001"
    assert 몸["editable"] is True


def test_취소_접수_답은_잔량이_0_이고_고칠_수_없다(주문):
    앱, _ = 주문
    몸 = 앱.post(
        "/api/domestic/cancel",
        json={
            "environment": "paper",
            "sym": SYMBOL,
            "side": "sell",
            "ord_qty": 2,
            "org_ord_no": "9",
            "context": "domestic-night",
        },
    ).json()

    assert (몸["orderKind"], 몸["status"], 몸["remaining"]) == ("cancel", "cancelled", 0)
    # 취소에는 짝이 되는 상태코드가 없습니다 — 까닭은 `CANCELLED_STATUS` 에.
    assert "statusCode" not in 몸
    assert 몸["editable"] is False
    assert (몸["originalOrderNo"], 몸["context"]) == ("0000000009", "domestic-night")
    # 고칠 값을 안 보내는 요청이라 주문유형·체결조건·가격도 답에 없습니다.
    assert not ({"orderType", "orderTypeCode", "fillCondition", "price"} & set(몸))


def test_주문번호가_비어_오면_접수라고_답하지_않는다():
    """거절이 아닙니다 — 주문은 나갔을 수 있어 화면이 주문내역으로 확인해야 합니다."""
    앱, 호출부 = _세운다({"ord_no": "", "msg_cd": "", "msg_cntn": ""})
    try:
        응답 = 앱.post("/api/domestic/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 504
    assert 응답.json()["detail"] == orders.NO_ORDER_NUMBER
    assert 응답.json()["detail"] != orders.NOT_RECEIVED, "무엇이 없는지 가려집니다."
    # 화면이 배지를 바로잡을 수 있게 활성 환경은 알려 줍니다.
    assert 응답.headers["x-nh-environment"] == "paper"
    assert len(호출부.보낸것) == 1, "다시 보내지 않습니다."


def _접수시각():
    from datetime import datetime

    from backend.sessions.hours import KST

    return datetime(2026, 9, 17, 10, 4, 56, tzinfo=KST)


def test_지정가인데_가격이_없으면_안_부른다(주문):
    앱, 호출부 = 주문
    막힘 = 앱.post("/api/domestic/order", json=_주문(ord_tp_cd="1"))

    assert 막힘.status_code == 422
    assert 호출부.보낸것 == []


def test_지정가는_보낸_가격을_그대로_싣는다(주문):
    앱, 호출부 = 주문
    앱.post("/api/domestic/order", json=_주문(ord_tp_cd="1", ord_pric="405.25"))

    assert 호출부.보낸것[-1][1]["ord_pric"] == "405.25"


def test_야간이면_야간_API_로_나간다(주문):
    """주간·야간이 API 자체가 다릅니다."""
    앱, 호출부 = 주문
    앱.post("/api/domestic/order", json=_주문(context="domestic-night"))
    assert 호출부.보낸것[-1][0] == "domestic_order-night"

    앱.post(
        "/api/domestic/cancel",
        json={
            "environment": "paper",
            "sym": SYMBOL,
            "side": "buy",
            "ord_qty": 1,
            "org_ord_no": "1",
            "context": "domestic-night",
        },
    )
    assert 호출부.보낸것[-1][0] == "domestic_cancel-night"


def test_정정은_원주문번호를_열_자리로_채워_보낸다(주문):
    앱, 호출부 = 주문
    응답 = 앱.post(
        "/api/domestic/modify",
        json=_주문(ord_tp_cd="1", ord_pric="405.25", org_ord_no="1"),
    )

    assert 응답.status_code == 200
    api_id, 보낸것 = 호출부.보낸것[-1]
    assert api_id == "domestic_modify"
    assert 보낸것["org_ord_no"] == "0000000001"


def test_정정에_원주문번호가_없으면_안_부른다(주문):
    앱, 호출부 = 주문
    막힘 = 앱.post("/api/domestic/modify", json=_주문(ord_tp_cd="1", ord_pric="405.25"))

    assert 막힘.status_code == 422
    assert 호출부.보낸것 == []


def test_취소는_고칠_값을_안_보낸다(주문):
    """취소 요청은 화면 환경·종목·매매구분·취소수량·원주문번호 다섯뿐입니다."""
    앱, 호출부 = 주문
    응답 = 앱.post(
        "/api/domestic/cancel",
        json={"environment": "paper", "sym": SYMBOL, "side": "sell", "ord_qty": 2, "org_ord_no": "9"},
    )

    assert 응답.status_code == 200
    api_id, 보낸것 = 호출부.보낸것[-1]
    assert api_id == "domestic_cancel"
    assert set(보낸것) == {"sym", "trd_div", "ord_qty", "org_ord_no"}
    assert 보낸것["ord_qty"] == "2"


def test_수량은_한_계약_이상이어야_한다(주문):
    앱, 호출부 = 주문
    for 나쁜값 in (0, -1):
        assert 앱.post("/api/domestic/order", json=_주문(ord_qty=나쁜값)).status_code == 422
    assert 호출부.보낸것 == []


def test_거절은_실패가_아니라_답이다():
    """업무 거부는 200 으로 오고 문구는 서버가 보낸 그대로입니다."""
    앱, 호출부 = _세운다(
        터질것=BusinessError("domestic_order", "40015", "주문가능수량을 초과했습니다.", {})
    )
    try:
        응답 = 앱.post("/api/domestic/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is False
    assert 몸["code"] == "40015"
    assert 몸["message"] == "주문가능수량을 초과했습니다."


def test_실전_환경이면_실전으로_나간다():
    """**막지 않습니다.** 설정이 실전이면 실전으로 주문이 나갑니다."""
    앱, 호출부 = _세운다(environment="real")
    try:
        응답 = 앱.post("/api/domestic/order", json=_주문(environment="real"))
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is True
    # 화면이 「실전 접수」와 「모의 접수」를 결과만 보고 가릴 수 있어야 합니다.
    assert 몸["environment"] == "real"
    assert len(호출부.보낸것) == 1, "NH선물을 부릅니다."


def test_환경을_못_읽으면_주문을_안_낸다():
    """어느 서버로 갈지 모르는 채 되돌릴 수 없는 요청을 내지 않습니다."""
    앱, 호출부 = _세운다(environment=None)
    try:
        막힘 = 앱.post("/api/domestic/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 막힘.status_code == 500
    assert "설정 화면" in 막힘.json()["detail"]
    assert 호출부.보낸것 == [], "NH선물을 부르지 않습니다."


def test_응답을_못_받으면_확인을_청한다():
    """접수됐는지 알 수 없는 자리입니다. 다시 보내지 않습니다."""
    앱, 호출부 = _세운다(터질것=TransportError("domestic_order", "시간 초과"))
    try:
        응답 = 앱.post("/api/domestic/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 504
    # 어디서 확인해야 하는지가 문구에 들어 있어야 합니다 — 화면의 그 자리 이름입니다.
    assert "주문체결상세" in 응답.json()["detail"]
    assert len(호출부.보낸것) == 1, "다시 보내지 않습니다."


def test_재생에_기록이_없으면_연결_실패가_아니라_거부다():
    앱, _ = _세운다(replay=True, 터질것=TransportError("domestic_cancel", "기록 없음"))
    try:
        응답 = 앱.post(
            "/api/domestic/cancel",
            json={"environment": "paper", "sym": SYMBOL, "side": "buy", "ord_qty": 1, "org_ord_no": "1"},
        )
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 409
    assert "재생" in 응답.json()["detail"]


def test_저장해_둔_모의_주문으로_왕복한다(client):
    """공개 저장본에 모의 주간 신규 시장가 둘이 있습니다."""
    응답 = client.post("/api/domestic/order", json=_주문())

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is True
    assert 몸["id"].isdigit() and len(몸["id"]) == 10
    assert 응답.headers["x-nh-replay-match"]


def test_재생에_없는_주문은_거부로_온다(client):
    """정정·취소·야간·해외는 저장본이 없습니다."""
    응답 = client.post(
        "/api/domestic/cancel",
        json={"environment": "paper", "sym": SYMBOL, "side": "buy", "ord_qty": 1, "org_ord_no": "1"},
    )

    assert 응답.status_code == 409


def test_계좌_조회_실패는_계좌_문구로_온다():
    """예수금을 못 받았는데 「시세를 받지 못했습니다」가 서면 안 됩니다."""
    앱, _ = _세운다(터질것=TransportError("domestic_deposit", "시간 초과"))
    try:
        못받음 = 앱.post("/api/domestic/deposit", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 못받음.status_code == 504
    문구 = 못받음.json()["detail"]
    assert "계좌" in 문구
    assert "시세" not in 문구


def test_계좌_거절도_계좌_문구로_온다():
    앱, _ = _세운다(
        터질것=BusinessError("domestic_open-interest", "40010", "조회할 수 없습니다", {})
    )
    try:
        거절 = 앱.post("/api/domestic/open-interest", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 거절.status_code == 502
    문구 = 거절.json()["detail"]
    assert "계좌" in 문구
    assert "시세" not in 문구


def test_시세_실패는_시세_문구_그대로다():
    """가른 것은 계좌 쪽이고 시세 문구는 그대로여야 합니다."""
    앱, _ = _세운다(터질것=TransportError("domestic_price", "시간 초과"))
    try:
        못받음 = 앱.post("/api/domestic/price", json={"sym": SYMBOL})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 못받음.status_code == 504
    assert "시세" in 못받음.json()["detail"]
    assert "계좌" not in 못받음.json()["detail"]


def test_게이트웨이가_거절하면_확인을_청한다():
    """**처리됐는지 모르는 자리입니다.** 「잠시 뒤 다시」로 적으면 이미 나갔을
    수 있는 주문을 한 번 더 내라는 말이 됩니다."""
    from backend.nh_api.errors import GatewayError
    from backend import orders as 주문계약

    앱, 호출부 = _세운다(
        터질것=GatewayError("domestic_order", "EGW034", "게이트웨이 내부 오류", {}, "retry")
    )
    try:
        응답 = 앱.post("/api/domestic/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 주문계약.NOT_RECEIVED
    assert "주문체결상세" in 응답.json()["detail"]
    assert len(호출부.보낸것) == 1, "다시 보내지 않습니다."


def _본문오류저장소(api_id: str, path: str):
    """본문에 오류 코드를 담은 채 **200 으로** 오는 응답 하나."""
    from pathlib import Path as _Path

    from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore, _build

    기록 = {
        "format": FIXTURE_FORMAT,
        "transport": "HTTP",
        "api_id": api_id,
        "environment": "paper",
        "market": "domestic",
        "record_id": "made-up",
        "collected_at": "2026-09-11T00:00:00+00:00",
        "scenario_id": f"{api_id}__gateway",
        "test_group": "",
        "status": "response_received",
        "method": "POST",
        "path": path,
        "http_status": 200,
        # 주문은 요청이 통째로 같은 기록으로만 재생됩니다 — 라우트가 실어 보내는 그 모양.
        "request": {
            "sym": SYMBOL,
            "trd_div": "1",
            "ord_tp_cd": "2",
            "ord_qty": "1",
            "ord_pric": "0",
            "exec_cnd_cd": "1",
        },
        "response": {"errorCode": "EGW000", "errorMessage": "오류가 발생하였습니다."},
    }
    return FixtureStore([_build(기록, _Path("메모리"))], _Path("메모리"))


def test_본문에_담긴_게이트웨이_오류도_확인을_청한다():
    """**200 으로 오는 자리입니다.** 상태만 보면 성공으로 읽습니다.

    그 요청은 이미 서버로 나간 뒤입니다 — 「잠시 뒤 다시」로 적으면 중복
    주문을 부릅니다.
    """
    from backend import orders as 주문계약

    session = create_session(
        replay=True, fixtures=_본문오류저장소("domestic_order", "/trade/v1/domestic/order")
    )
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        응답 = TestClient(app).post("/api/domestic/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()

    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 주문계약.NOT_RECEIVED


# -- 스프레드 빈 칸·야간 자리표 봉·옵션 체인 만기 ---------------------------------


def _마스터가_이렇게_답한다(monkeypatch, 줄):
    from backend.master import master_service

    monkeypatch.setattr(master_service.service, "locate", lambda market, code: 줄)


def _스프레드_현재가(monkeypatch):
    """스프레드처럼 뜻없는 칸이 0 으로 오는 현재가 답."""
    원문 = {"sym_exch": "B0169A34", "last_pric": "14.95", "trd_qty": "705", "up_act_pric": "0.00",
            "lo_act_pric": "0.00", "theo_pric": "0.00", "dev_rt": "0.00", "ivol": "0.00",
            "spt_pric": "1101.20", "theo_bas": "0.00", "fact_bas": "0.00"}
    monkeypatch.setattr(domestic_routes.api, "price", lambda sym, *, api: dict(원문))
    monkeypatch.setattr(domestic_routes.api, "price_night", lambda sym, *, api: dict(원문))


@pytest.mark.parametrize("경로", ["/api/domestic/price", "/api/domestic/price-night"])
def test_마스터가_스프레드라_하면_뜻없는_칸이_null(client, monkeypatch, 경로):
    _스프레드_현재가(monkeypatch)
    _마스터가_이렇게_답한다(monkeypatch, {"kind": "spread"})

    몸 = client.post(경로, json={"sym": "B0169A34"}).json()

    for 칸 in ("upperLimit", "lowerLimit", "theory", "disparity", "iv", "basisTheory", "basisActual"):
        assert 몸[칸] is None, 칸
    assert 몸["last"] == 14.95


@pytest.mark.parametrize("줄", [None, {"kind": "futures"}])
def test_마스터가_모르거나_선물이면_원문_값_그대로(client, monkeypatch, 줄):
    """코드 모양으로 짐작하지 않습니다 — 짐작이 틀리면 선물의 값이 지워집니다."""
    _스프레드_현재가(monkeypatch)
    _마스터가_이렇게_답한다(monkeypatch, 줄)

    몸 = client.post("/api/domestic/price", json={"sym": "B0169A34"}).json()

    assert (몸["disparity"], 몸["theory"], 몸["upperLimit"]) == (0.0, 0.0, 0.0)


def _일봉_원문():
    return {
        "Occurs1": [
            # 체결 없던 날의 자리표 — 네 가격이 같고 거래량 0.
            {"occurs1_ref_dt": "20260924", "occurs1_open_pric": "1338.50", "occurs1_high_pric": "1338.50",
             "occurs1_low_pric": "1338.50", "occurs1_close_pric": "1338.50", "occurs1_cum_trd_qty": "0"},
            {"occurs1_ref_dt": "20260925", "occurs1_open_pric": "1338.00", "occurs1_high_pric": "1340.00",
             "occurs1_low_pric": "1337.00", "occurs1_close_pric": "1339.00", "occurs1_cum_trd_qty": "120"},
        ]
    }


def test_야간_일봉은_자리표_봉을_빼고_주간_일봉은_그대로(client, monkeypatch):
    monkeypatch.setattr(domestic_routes.api, "chart_daily", lambda *a, **k: _일봉_원문())
    물음 = {"sym": SYMBOL, "inq_strt_dt": "20260924", "inq_ed_dt": "20260925"}

    야간 = client.post("/api/domestic/chart-daily", json={**물음, "night": True}).json()
    주간 = client.post("/api/domestic/chart-daily", json={**물음, "night": False}).json()

    assert [봉["volume"] for 봉 in 야간["bars"]] == [120]
    assert 야간["skipped"] == 1
    assert [봉["volume"] for 봉 in 주간["bars"]] == [0, 120]
    assert 주간["skipped"] == 0


def test_옵션_체인_만기_칸은_만기일_여섯_자리라고_적혀_있다():
    """년월(YYYYMM)로 부르면 NH선물이 거절합니다 — 문서가 모양을 말해야 합니다."""
    설명 = app.openapi()["components"]["schemas"]["OptionChainRequest"]["properties"]["exp_mon"]["description"]

    assert "YYMMDD" in 설명
    assert "261008" in 설명
