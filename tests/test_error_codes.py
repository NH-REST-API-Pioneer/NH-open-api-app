"""오류 코드 사전.

**갈래를 코드로만 정하는지**가 여기서 지킬 것입니다. 문구를 글자로 맞춰 보면
서버가 문구를 한 글자만 바꿔도 조용히 어긋납니다.
"""
from __future__ import annotations

import pytest

from backend.nh_api import error_codes


def test_정의서의_코드를_다_담았다():
    """시스템 59·주문 102 — 중복 코드 둘은 먼저 나온 문구로 한 번씩입니다.

    시스템 쪽에는 정의서에 없는 `EGW053`(모의투자에서 부를 수 없는 API) 하나가
    더 있습니다 — 실제 응답으로 받은 코드입니다.
    """
    assert len(error_codes.SYSTEM_MESSAGES) == 59 + 1
    assert "EGW053" in error_codes.SYSTEM_MESSAGES
    assert len(error_codes.ORDER_MESSAGES) == 102


def test_문구는_정의서_그대로다():
    assert error_codes.message_of("EGW052") == "토큰 재발급이 필요합니다."
    assert error_codes.message_of("EST06") == "현재 appkey로 20개 이상의 메시지를 등록할 수 없습니다."
    assert error_codes.message_of("50013") == "주문가격을 확인하십시요."


def test_빈_문구인_코드도_그대로_담았다():
    """`50803` 은 정의서에 문구가 비어 있습니다."""
    assert "50803" in error_codes.ORDER_MESSAGES
    assert error_codes.message_of("50803") == ""


@pytest.mark.parametrize(
    "code,kind",
    [
        ("EGW052", error_codes.REISSUE),
        ("EGW024", error_codes.REISSUE),
        ("EST02", error_codes.REISSUE),
        ("EGW020", error_codes.RETRY),
        ("EGW033", error_codes.RETRY),
        ("EGW001", error_codes.SETTINGS),
        ("EGW009", error_codes.SETTINGS),
        ("EGW014", error_codes.PERMISSION),
        ("EST03", error_codes.PERMISSION),
        ("EGW002", error_codes.OK),
        ("0", error_codes.OK),
        ("50013", error_codes.OTHER),
    ],
)
def test_갈래를_코드로_가린다(code, kind):
    assert error_codes.kind_of(code) == kind


def test_모르는_코드는_아는_척하지_않는다():
    assert error_codes.kind_of("EGW999") == error_codes.OTHER
    assert error_codes.kind_of("123456") == error_codes.OTHER
    assert error_codes.kind_of("") == error_codes.OTHER
    assert error_codes.message_of("EGW999") == ""


def test_문구가_아니라_코드로_가린다():
    """같은 문구를 가진 코드를 지어내도 갈래는 코드가 정합니다."""
    사전문구 = error_codes.message_of("EGW052")

    assert error_codes.kind_of("EGW052") == error_codes.REISSUE
    # 문구가 같아도 코드가 다르면 갈래가 다릅니다.
    assert error_codes.describe("99999", 사전문구)["kind"] == error_codes.OTHER


def test_원문이_사전을_이긴다():
    답 = error_codes.describe("EGW052", "서버가 보낸 다른 말")

    assert 답["message"] == "서버가 보낸 다른 말"


def test_원문이_없으면_사전에서_꺼낸다():
    답 = error_codes.describe("EGW052", "")

    assert 답["message"] == "토큰 재발급이 필요합니다."
    assert 답["kind"] == error_codes.REISSUE


def test_본문에_오류코드가_있으면_상태와_무관하게_실패다():
    """200 으로 오면서 본문에만 실패가 적혀 오는 자리가 있습니다."""
    답 = error_codes.failure_of({"errorCode": "EGW018", "errorMessage": "만료"})

    assert 답 == {
        "code": "EGW018",
        "message": "만료",
        "kind": error_codes.REISSUE,
    }


def test_정상_코드는_실패가_아니다():
    """토큰 발급 성공에도 코드가 실려 옵니다."""
    assert error_codes.failure_of({"errorCode": "EGW002"}) is None
    assert error_codes.failure_of({"errorCode": "EGW013"}) is None


def test_오류코드가_없으면_실패가_아니다():
    assert error_codes.failure_of({"ord_no": "1"}) is None
    assert error_codes.failure_of({"errorCode": ""}) is None
    assert error_codes.failure_of("본문이 아님") is None
    assert error_codes.failure_of(None) is None


def test_문구_칸_이름을_차례로_본다():
    """어느 이름으로 오는지 실물로 확인하지 못한 자리입니다."""
    for 칸 in error_codes.ERROR_MESSAGE_FIELDS:
        답 = error_codes.failure_of({"errorCode": "EGW034", "": "", 칸: "그 자리 문구"})
        assert 답["message"] == "그 자리 문구", 칸


def test_상세를_봐야_하는_코드():
    assert error_codes.needs_detail("5039") is True
    assert error_codes.needs_detail("50013") is False


def test_구독_상한_코드가_표에_있다():
    """실시간 허브가 이 코드로 상한을 압니다 — 앱키 하나에 스무 건입니다."""
    assert error_codes.SUBSCRIPTION_LIMIT == "EST06"
    assert "20개" in error_codes.message_of(error_codes.SUBSCRIPTION_LIMIT)


def test_모의투자에서_부를_수_없는_API_는_따로_가른다():
    """다시 해도, 토큰을 다시 받아도 같은 답이라 그 두 갈래가 아닙니다."""
    said = error_codes.describe("EGW053")

    assert said == {
        "code": "EGW053",
        "message": "해당 API는 모의투자에서 호출할 수 없습니다.",
        "kind": error_codes.PAPER_UNAVAILABLE,
    }
    assert said["kind"] not in (error_codes.REISSUE, error_codes.RETRY)
    # 서버가 보낸 문구가 먼저입니다.
    assert error_codes.describe("EGW053", "해당 API는 모의투자 에서 호출 할수 없습니다.")["message"] == (
        "해당 API는 모의투자 에서 호출 할수 없습니다."
    )

