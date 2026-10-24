"""국내 투자자 매매동향 — 납작한 응답을 무리 목록으로.

**NH선물 서버에 접속하지 않습니다.** 저장해 둔 응답과 지어낸 값으로 돕니다.
"""
from __future__ import annotations

import json

from backend.domestic_futureoption import domestic_futureoption_functions as api
from backend.domestic_futureoption.domestic_trend import (
    INVESTOR_GROUPS,
    KIND_CODE,
    investor_trend,
)
from backend.nh_api.fixtures import FIXTURE_ROOT

기준일 = "20260909"


def _기록(inq_tp: str) -> dict:
    폴더 = FIXTURE_ROOT / "domestic_trend-investor"
    기록들 = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(폴더.rglob("*.json"))]
    return next(하나 for 하나 in 기록들 if 하나["request"]["inq_tp"] == inq_tp)


def test_열한_무리가_온_차례대로_선다():
    """무리를 합치지 않습니다 — 「기관」을 만들려면 무엇을 더할지 명세가 말해야 합니다."""
    나온것 = investor_trend(_기록(api.QUANTITY)["response"], inq_tp=api.QUANTITY, ref_dt=기준일)

    무리들 = [줄["group"] for 줄 in 나온것["investors"]]
    assert 무리들 == [이름 for _, 이름 in INVESTOR_GROUPS]
    assert len(무리들) == 11
    assert "institution" not in 무리들, "합친 무리를 만들지 않습니다."


def test_무리_한_줄의_값이_원문과_같다():
    나온것 = investor_trend(_기록(api.QUANTITY)["response"], inq_tp=api.QUANTITY, ref_dt=기준일)

    개인 = 나온것["investors"][0]
    assert 개인 == {
        "group": "individual",
        "buy": 3165,
        "sell": 1407,
        "netBuy": 1758,
        "previousBuy": 344,
        "previousSell": 45,
        # 비율만 실수이고 나머지는 계약 수라 정수입니다.
        "buyPct": 23.47,
        "sellPct": 10.43,
    }
    외국인 = 나온것["investors"][1]
    assert (외국인["group"], 외국인["netBuy"]) == ("foreign", -2817)
    assert isinstance(개인["buy"], int) and isinstance(개인["buyPct"], float)


def test_보험만_순매수_칸_이름이_뒤집혀_있다():
    """열 무리는 `…_net_buy` 인데 보험은 `ins_buy_net` 입니다. 명세도 그렇습니다."""
    원문 = _기록(api.QUANTITY)["response"]
    assert "ins_buy_net" in 원문 and "ins_net_buy" not in 원문

    보험 = next(
        줄
        for 줄 in investor_trend(원문, inq_tp=api.QUANTITY, ref_dt=기준일)["investors"]
        if 줄["group"] == "insurance"
    )
    assert 보험["netBuy"] == int(원문["ins_buy_net"])


def test_수량과_금액은_다른_조회다():
    """같은 품목·같은 날이라도 자릿수째 다릅니다 — 어느 쪽인지 답이 말해야 합니다."""
    수량 = investor_trend(_기록(api.QUANTITY)["response"], inq_tp=api.QUANTITY, ref_dt=기준일)
    금액 = investor_trend(_기록(api.AMOUNT)["response"], inq_tp=api.AMOUNT, ref_dt=기준일)

    assert (수량["unit"], 금액["unit"]) == ("quantity", "amount")
    assert 수량["investors"][0]["buy"] == 3165
    assert 금액["investors"][0]["buy"] == 53165173000


def test_수신시각과_상품코드와_기준일을_함께_낸다():
    나온것 = investor_trend(_기록(api.QUANTITY)["response"], inq_tp=api.QUANTITY, ref_dt=기준일)

    assert 나온것["time"] == "09:01:30"
    # 거래소 상품 식별자입니다. 이 앱의 품목코드가 아닙니다.
    assert 나온것["instrument"] == "KRDRVFUUSD"
    assert 나온것["date"] == "2026-09-09"


def test_저장해_둔_응답이_없으면_무리가_비어_온다():
    """재생이 내는 빈 응답입니다 — 값을 0 으로 지어내지 않습니다."""
    나온것 = investor_trend({"nrec": "0000", "nxt_key": ""}, inq_tp=api.QUANTITY, ref_dt=기준일)

    assert 나온것["investors"] == []
    assert (나온것["time"], 나온것["instrument"]) == (None, None)
    # 무엇을 물었는지는 남깁니다.
    assert (나온것["unit"], 나온것["date"]) == ("quantity", "2026-09-09")
    # 모양이 다른 응답도 다룹니다.
    assert investor_trend("응답이 아님", inq_tp=api.QUANTITY, ref_dt="")["investors"] == []


def test_칸이_반만_온_무리도_그_칸만_담는다():
    """안 읽힌 칸은 `null` 이고, 한 칸이라도 읽히면 그 무리는 목록에 섭니다."""
    나온것 = investor_trend(
        {"ind_buy": "10", "ind_sel": "4"}, inq_tp=api.QUANTITY, ref_dt=기준일
    )

    (개인,) = 나온것["investors"]
    assert (개인["group"], 개인["buy"], 개인["sell"]) == ("individual", 10, 4)
    assert 개인["netBuy"] is None and 개인["buyPct"] is None


def _모든칸(값: str) -> dict:
    """일흔일곱 칸을 같은 값으로 채운 응답."""
    from backend.domestic_futureoption.domestic_trend import _FIELDS, _ODD_FIELDS

    made = {}
    for 접두사, _ in INVESTOR_GROUPS:
        for 이름, 접미사 in _FIELDS:
            made[_ODD_FIELDS.get((접두사, 이름), f"{접두사}{접미사}")] = 값
    return made


def test_칸은_다_왔는데_값이_비었으면_무리가_서지_않는다():
    """칸이 있는지가 아니라 값이 읽혔는지로 봅니다."""
    빈값 = _모든칸("")
    assert len(빈값) == 77, "무리 열하나에 일곱 칸씩입니다."

    assert investor_trend(빈값, inq_tp=api.QUANTITY, ref_dt=기준일)["investors"] == []


def test_영은_값이라_그대로_선다():
    """「0 계약」과 「말이 없음」은 다릅니다."""
    나온것 = investor_trend(_모든칸("0"), inq_tp=api.QUANTITY, ref_dt=기준일)

    assert len(나온것["investors"]) == 11
    assert all(줄["buy"] == 0 and 줄["netBuy"] == 0 for 줄 in 나온것["investors"])


def test_무리_이름이_명세_한글명과_맞는다():
    """`mb` 는 회원이 아니라 **종금**입니다 — 접두사만 보면 틀리기 쉬운 자리입니다."""
    이름들 = dict(INVESTOR_GROUPS)

    assert 이름들["mb"] == "merchantBank"
    assert 이름들["cntry"] == "nationalFund", "「국가」는 뜻이 좁습니다."
    assert 이름들["grs"] == "total"
    assert "member" not in 이름들.values()


def test_선물옵션구분은_명세의_한_자리다():
    """`opt_prd` 끝자리입니다 — 1 선물·2 콜·3 풋."""
    assert KIND_CODE == {"futures": "1", "call": "2", "put": "3"}
