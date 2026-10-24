"""주문 계약 — 두 시장이 함께 쓰는 규칙.

여기 시험은 **아무 주문도 내지 않습니다.** 값 다루는 규칙만 봅니다.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend import orders


def 가짜호출부(environment="paper", replay=False):
    """환경만 알려 주는 호출부 흉내."""
    session = SimpleNamespace(
        config=SimpleNamespace(default_environment=environment), is_replay=replay
    )
    return SimpleNamespace(session=session)


def test_원주문번호를_열_자리로_채운다():
    """명세가 `1` 을 `0000000001` 로 받습니다."""
    assert orders.order_no("1") == "0000000001"
    assert orders.order_no(1) == "0000000001"
    assert orders.order_no(" 7745231861 ") == "7745231861"


def test_열_자리보다_긴_번호는_자르지_않는다():
    """앞뒤를 자르면 엉뚱한 주문을 건드립니다. 판단은 서버에 맡깁니다."""
    assert orders.order_no("123456789012") == "123456789012"


def test_실전인지_모의인지는_주소를_고를_뿐이다():
    """**환경으로 주문을 막지 않습니다.** 설정에 적힌 대로 나갑니다."""
    assert orders.environment_of(가짜호출부("real")) == "real"
    assert orders.environment_of(가짜호출부("paper")) == "paper"
    assert orders.unknown_environment(가짜호출부("real")) is False


def test_환경을_못_읽으면_보내지_않는다():
    """모르는 채 되돌릴 수 없는 요청을 내는 것보다 안 보내고 알립니다."""
    assert orders.environment_of(SimpleNamespace()) is None
    assert orders.unknown_environment(SimpleNamespace()) is True
    # 설정이 반쯤 채워진 경우도 같습니다.
    for 빈값 in (None, "", "   "):
        assert orders.unknown_environment(가짜호출부(빈값)) is True, 빈값


def test_재생인지_알려_준다():
    assert orders.is_replay(가짜호출부(replay=True)) is True
    assert orders.is_replay(가짜호출부(replay=False)) is False
    assert orders.is_replay(SimpleNamespace()) is False


def test_접수된_주문은_주문내역과_같은_낱말을_쓴다():
    답 = orders.accepted(
        order_id=" 5959762237 ",
        market="domestic",
        environment="paper",
        code="A7569000",
        side="buy",
        quantity=1,
    )

    assert 답 == {
        "accepted": True,
        "id": "5959762237",
        "market": "domestic",
        "environment": "paper",
        "code": "A7569000",
        "side": "buy",
        "quantity": 1,
    }


def test_어느_환경으로_나간_주문인지_함께_낸다():
    """실전과 모의가 같은 화면에서 같은 모양으로 접수됩니다."""
    실전 = orders.accepted(
        order_id="1", market="domestic", environment="real", code="A", side="buy", quantity=1
    )
    거절 = orders.rejected(code="40015", message="안 됩니다", environment="real")

    assert 실전["environment"] == "real"
    assert 거절["environment"] == "real"


def test_해외에만_있는_칸은_더해서_낸다():
    답 = orders.accepted(
        order_id="7",
        market="overseas",
        environment="paper",
        code="ZZZZ26",
        side="sell",
        quantity=2,
        businessDate="2026-09-09",
        parentOrderNo=None,
        price=7677.25,
    )

    assert 답["businessDate"] == "2026-09-09"
    assert 답["price"] == 7677.25
    # 값이 없는 칸은 안 담습니다.
    assert "parentOrderNo" not in 답


def test_거절은_서버_문구를_그대로_낸다():
    """무엇을 고쳐야 다시 낼 수 있는지가 그 문구에 있습니다."""
    답 = orders.rejected(
        code="40015", message="주문가능수량을 초과했습니다.", environment="paper"
    )

    assert 답 == {
        "accepted": False,
        "code": "40015",
        "message": "주문가능수량을 초과했습니다.",
        "kind": "other",
        "environment": "paper",
    }


def test_서버가_문구를_안_보내면_사전에서_꺼낸다():
    """차례는 원문 → 사전 → 코드만입니다. 사전이 원문을 덮지 않습니다."""
    사전만 = orders.rejected(code="7022", message="", environment="paper")
    원문 = orders.rejected(code="7022", message="서버가 보낸 말", environment="paper")

    assert 사전만["message"] == "거래대상 종목이 아닙니다."
    assert 원문["message"] == "서버가 보낸 말", "사전이 원문을 덮으면 안 됩니다."


def test_모르는_코드는_문구_없이_코드만_남는다():
    답 = orders.rejected(code="99999999", message="", environment="paper")

    assert 답["code"] == "99999999"
    assert 답["message"] == ""
    assert 답["kind"] == "other"


def test_상세를_봐야_하는_코드에는_표지가_붙는다():
    """`5039` 는 같은 코드에 서로 다른 사유가 붙어 옵니다."""
    표지있음 = orders.rejected(code="5039", message="처리불가", environment="paper")
    표지없음 = orders.rejected(code="7022", message="거래대상 아님", environment="paper")

    assert 표지있음["needsDetail"] is True
    assert "needsDetail" not in 표지없음


def test_거절에도_갈래가_붙는다():
    """사용자가 무엇을 해야 하는지입니다."""
    답 = orders.rejected(code="EGW052", message="", environment="paper")

    assert 답["kind"] == "reissue"
    assert 답["message"] == "토큰 재발급이 필요합니다."


def test_원주문번호가_비었거나_0_뿐이면_없다():
    for 값 in (None, "", "   ", "0000000000", "0"):
        assert orders.original_no(값, "1234567890") is None, repr(값)


def test_원주문번호가_자기_주문번호와_같으면_없다():
    """신규 줄에 자기 번호를 원주문 칸에 실어 보내는 답이 있습니다 — 원주문이 아닙니다."""
    assert orders.original_no("5959762237", "5959762237") is None
    assert orders.original_no(" 5959762237 ", "5959762237") is None


def test_다른_번호면_원주문번호_그대로():
    assert orders.original_no("0000000118", "0000000119") == "0000000118"
    # 자기 번호를 모르면 비교하지 않습니다.
    assert orders.original_no("5959762237") == "5959762237"
