"""해외 주문오류내역과 누적손익이 화면 모양으로 바뀌는지.

**저장본에 줄이 없습니다.** 공개 기록은 0건이고, 로컬 전용 기록 셋도 모두
`Occurs1` 칸 자체가 안 옵니다(`nrec: "0000"`). 그래서 여기 시험은 명세의 칸
이름으로 **만들어 낸 응답**으로 세웁니다 — 값도 종목도 지어낸 것입니다.
"""
from __future__ import annotations

import json

from backend.overseas_futureoption.overseas_account import (
    ERROR_NAMES,
    cumulative_pl,
    order_errors,
)

# 지어낸 종목코드입니다. 실제 종목과 겹치지 않게 골랐습니다.
지어낸종목 = "ZZZZ26"


def 오류줄(**덮어쓰기):
    한줄 = {
        "occurs1_inq_dt": "20260910",
        "occurs1_seq_no": "12",
        "occurs1_inp_tm": "152122",
        "occurs1_ord_no": "7",
        "occurs1_org_ord_no": "",
        "occurs1_sym": 지어낸종목,
        "occurs1_glb_ord_div_cd_nm": "일반",
        "occurs1_qt_div_cd_nm": "신규",
        "occurs1_trd_div_nm": "매수",
        "occurs1_glb_ord_tp_cd_nm": "지정가",
        "occurs1_ord_pric": "7677.25",
        "occurs1_ord_qty": "2",
        "occurs1_stop_pric": "0",
        "occurs1_msg_cd": "40015",
        "occurs1_err_msg": "주문가능수량을 초과했습니다.",
        "occurs1_ip_addr": "203.0.113.9",
        "occurs1_fst_ord_id": "",
        "occurs1_mltple_grp_no": "",
        "occurs1_pric_ind": "3",
        "occurs1_cme_yn": "Y",
        "occurs1_dom_dt": "20260911",
        "occurs1_dom_tm": "052122",
        "occurs1_ord_med_div_cd_nm": "REST API",
    }
    한줄.update(덮어쓰기)
    return 한줄


def test_주문오류가_화면_모양으로_나온다():
    한줄 = order_errors({"Occurs1": [오류줄()], "nrec": "0001"})["errors"][0]

    assert 한줄["id"] == "12"
    assert 한줄["code"] == 지어낸종목
    assert 한줄["market"] == "overseas"
    assert 한줄["message"] == "주문가능수량을 초과했습니다."
    assert 한줄["messageCode"] == "40015"
    assert 한줄["quantity"] == 2
    assert 한줄["price"] == 7677.25


def test_국내와_같은_이름으로_오류_사전_자리를_맞춘다():
    """오류 코드 사전이 붙는 날 두 시장이 한 자리에서 받아야 합니다."""
    from backend.domestic_futureoption import domestic_account

    해외 = order_errors({"Occurs1": [오류줄()]})["errors"][0]
    국내 = domestic_account.order_errors(
        {"Occurs1": [{"occurs1_msg_cd": "40015", "occurs1_msg": "초과"}]}
    )["errors"][0]

    for 칸 in ("message", "messageCode"):
        assert 칸 in 국내
        assert 칸 in 해외


def test_코드는_안_오고_이름만_온다():
    """이름을 코드로 되짚어 만들지 않습니다 — 서버 문구가 바뀌면 조용히 틀립니다."""
    한줄 = order_errors({"Occurs1": [오류줄()]})["errors"][0]

    assert 한줄["side"] == "매수"
    assert 한줄["orderKind"] == "신규"
    assert 한줄["orderType"] == "지정가"
    assert 한줄["source"] == "REST API"
    for 이름칸, _ in ERROR_NAMES:
        assert f"{이름칸}Code" not in 한줄


def test_사람을_가리키는_칸을_안_내보낸다():
    """IP·최초주문ID·복수그룹번호. 반입 스크립트가 가리는 칸과 같은 자리입니다.

    **빈 값으로 두고 보면 저절로 참이 됩니다.** 그런 시험은 골라 담는 구조가
    바뀌는 날 아무것도 못 잡습니다. 그래서 가짜 값을 넣고 봅니다.
    """
    지울것 = {
        "occurs1_ip_addr": "203.0.113.9",
        "occurs1_fst_ord_id": "FAKE-OP",
        "occurs1_mltple_grp_no": "FAKE-GRP",
    }
    응답 = {"Occurs1": [오류줄(**지울것)]}

    # 먼저 지울 것이 정말 들어 있는지 봅니다.
    담긴원문 = json.dumps(응답, ensure_ascii=False)
    for 값 in 지울것.values():
        assert 값 in 담긴원문

    담긴것 = json.dumps(order_errors(응답), ensure_ascii=False)
    for 칸, 값 in 지울것.items():
        assert 값 not in 담긴것, 칸
        assert 칸.replace("occurs1_", "") not in 담긴것


def test_화면_시각은_국내_쪽이다():
    """사용자가 보는 시계가 그것입니다. 주문 쪽도 함께 냅니다."""
    한줄 = order_errors({"Occurs1": [오류줄()]})["errors"][0]

    assert (한줄["date"], 한줄["time"]) == ("2026-09-11", "05:21:22")
    assert (한줄["orderDate"], 한줄["orderTime"]) == ("2026-09-10", "15:21:22")


def test_주문시간이_여덟_자리면_못_읽고_기록에_남는다(caplog):
    """명세 안에서 길이 칸(8)과 설명(HHMMSS)이 어긋나 있습니다."""
    한줄 = order_errors({"Occurs1": [오류줄(occurs1_inp_tm="15212200")]})["errors"][0]

    assert "orderTime" not in 한줄
    assert any("주문시간을 읽지 못했습니다" in 남은것.message for 남은것 in caplog.records)


def test_진법_코드를_그대로_낸다():
    """분수 호가 표가 여기 있습니다. 뜻 표는 마스터가 쥡니다."""
    한줄 = order_errors({"Occurs1": [오류줄(occurs1_pric_ind="E")]})["errors"][0]

    assert 한줄["priceNotationCode"] == "E"


def test_주문오류가_비어_올_수_있다():
    """반입해 둔 기록이 그렇습니다 — `Occurs1` 칸 자체가 안 옵니다."""
    for 빈것 in ({"nrec": "0000", "nxt_key": ""}, {"Occurs1": []}, {}):
        답 = order_errors(빈것)
        assert 답["errors"] == []


# ── 누적손익 ────────────────────────────────────────────────


def 손익줄(**덮어쓰기):
    한줄 = {
        "occurs1_prd_cd": "ZZZ",
        "occurs1_prd_nm": "지어낸 품목",
        "occurs1_cur_cd": "USD",
        "occurs1_cls_pl_amt": "100.5",
        "occurs1_pl_amt": "-20",
        "occurs1_fee": "3.2",
        "occurs1_net_pl_amt": "77.3",
    }
    한줄.update(덮어쓰기)
    return 한줄


def 총합줄(**덮어쓰기):
    return 손익줄(occurs1_prd_cd="--------", occurs1_prd_nm="환산합계", **덮어쓰기)


def test_누적손익이_화면_모양으로_나온다():
    한줄 = cumulative_pl({"Occurs1": [손익줄()]})["rows"][0]

    assert 한줄["productCode"] == "ZZZ"
    assert 한줄["currency"] == "USD"
    assert 한줄["realisedPl"] == 100.5
    assert 한줄["unrealisedPl"] == -20
    assert 한줄["fee"] == 3.2
    assert 한줄["netPl"] == 77.3
    assert 한줄["market"] == "overseas"


def test_총합_줄은_목록에서_빼서_따로_낸다():
    """두면 화면이 합을 다시 더해 두 배로 적습니다."""
    답 = cumulative_pl({"Occurs1": [손익줄(), 총합줄(occurs1_net_pl_amt="77.3")]})

    assert len(답["rows"]) == 1
    assert 답["rows"][0]["productCode"] == "ZZZ"
    assert 답["total"]["netPl"] == 77.3
    assert 답["total"]["productName"] == "환산합계"


def test_총합_표시가_다르면_그냥_줄로_둔다():
    """실물로 확인 못 한 자리입니다. 지어내서 빼 버리면 값이 사라집니다."""
    답 = cumulative_pl({"Occurs1": [손익줄(occurs1_prd_cd="합계")]})

    assert 답["total"] is None
    assert len(답["rows"]) == 1


def test_누적손익이_비어_올_수_있다():
    for 빈것 in ({"nrec": "0000", "nxt_key": ""}, {"Occurs1": []}, {}):
        답 = cumulative_pl(빈것)
        assert 답["rows"] == []
        assert 답["total"] is None


def test_주문오류의_가격은_쉼표가_붙어_와도_읽는다():
    """명세에서 긴 글자 칸인 가격 자리 — 보유포지션만기조회처럼 쉼표가 붙어 와도 숫자입니다."""
    from backend.overseas_futureoption.overseas_account import order_errors

    한줄 = order_errors({"Occurs1": [오류줄(occurs1_ord_pric="7,677.25", occurs1_stop_pric="7,600.00")]})["errors"][0]
    assert (한줄["price"], 한줄["stopPrice"]) == (7677.25, 7600.0)

