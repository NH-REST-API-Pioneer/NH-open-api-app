"""시세 사용 신청이 필요한 거래소(`ETR010`) — 조회의 답.

**NH선물 서버에 붙지 않습니다.** 가짜 전송로 위의 세션이 정해 둔 본문으로 답합니다.
본문은 실제 서버가 준 모양 그대로입니다 — HTTP 400 에 `errorCode` 가 실려 오고,
문장 끝에 종목과 거래소가 꼬리로 붙습니다.
"""
from __future__ import annotations

import pytest

from backend.nh_api import error_codes
from backend.nh_api.errors import ERROR_CODE_HEADER, ERROR_KIND_HEADER, BusinessError
from backend.orders import QUOTE_SUBSCRIPTION_DETAIL, quote_subscription
from tests.test_paper_unavailable import 세우기  # noqa: F401 — 픽스처를 이 파일에서도 씁니다.


def _신청필요(path: str, 꼬리: str) -> dict:
    return {
        "errorTime": "2026-09-30 23:02:11",
        "errorMessage": (
            "해당 종목은 시세사용신청 후 조회 가능합니다. (HTS:9726화면 / WTS:실시간 시세신청) " + 꼬리
        ),
        "errorStatus": 400,
        "errorCode": "ETR010",
        "errorPath": path,
    }


현재가_거절 = _신청필요("/trade/v1/overseas/price", "[iccurs1_sym::BRNZ26][미신청거래소::BRN]")
호가_거절 = _신청필요("/trade/v1/overseas/bid-price", "[sym::BRNZ26][미신청거래소::BRN]")

조회들 = [
    ("/api/overseas/price", {"syms": [{"exch_cd": "FICE", "sym": "BRNZ26"}]}, "/overseas/price", 현재가_거절),
    ("/api/overseas/bid-price", {"exch_cd": "FICE", "sym": "BRNZ26"}, "/overseas/bid-price", 호가_거절),
    ("/api/domestic/price", {"sym": "A016C000"}, "/domestic/price", 현재가_거절),
]


def test_코드는_시세_신청_갈래다():
    assert error_codes.kind_of("ETR010") == error_codes.QUOTE_SUBSCRIPTION == "quote-subscription"


@pytest.mark.parametrize("본문", [현재가_거절, 호가_거절], ids=["현재가", "호가"])
def test_원문_본문은_업무_거부로_올라오고_갈래가_시세_신청이다(세우기, 본문):
    """400 이어도 본문의 코드가 앞섭니다. 문장 꼬리가 달라도 갈래는 같습니다."""
    from backend.overseas_futureoption import overseas_futureoption_functions as api
    from backend.overseas_futureoption import overseas_routes
    from backend.main import app

    세우기(400, 본문)
    호출부 = app.dependency_overrides[overseas_routes.get_client]()

    with pytest.raises(BusinessError) as 잡힘:
        api.bid_price("BRNZ26", exch_cd="FICE", api=호출부)

    assert 잡힘.value.code == "ETR010"
    assert 잡힘.value.kind == error_codes.QUOTE_SUBSCRIPTION
    assert quote_subscription(잡힘.value)


@pytest.mark.parametrize(
    "주소, 몸, 끝, 본문", 조회들, ids=["해외_현재가", "해외_호가", "국내_현재가"]
)
def test_시세_신청이_필요한_조회는_무엇을_할지_알린다(세우기, 주소, 몸, 끝, 본문):
    앱, handler = 세우기(400, 본문)

    응답 = 앱.post(주소, json=몸)

    assert 응답.status_code == 502, "다른 거절과 같은 상태입니다."
    assert 응답.json()["detail"] == QUOTE_SUBSCRIPTION_DETAIL
    assert 응답.headers[ERROR_KIND_HEADER] == "quote-subscription"
    assert 응답.headers[ERROR_CODE_HEADER] == "ETR010"
    # 같은 요청을 다시 보내지 않습니다.
    assert len(handler.보낸것(끝)) == 1


@pytest.mark.parametrize(
    "상태, 본문",
    [
        (200, {"errorCode": "99999", "errorMessage": "ERROR - Please contact WR service center."}),
        (500, {"errorMessage": "서버 오류"}),
    ],
    ids=["다른_업무_거부", "HTTP_오류"],
)
def test_다른_거절은_지금과_같다(세우기, 상태, 본문):
    앱, _ = 세우기(상태, 본문)

    응답 = 앱.post("/api/overseas/price", json={"syms": [{"exch_cd": "FCME", "sym": "ESZ26"}]})

    assert 응답.status_code == 502
    assert 응답.json()["detail"] != QUOTE_SUBSCRIPTION_DETAIL
    assert ERROR_KIND_HEADER not in 응답.headers
    assert ERROR_CODE_HEADER not in 응답.headers
