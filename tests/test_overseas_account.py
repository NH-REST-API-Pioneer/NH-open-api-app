"""해외 계좌 응답이 화면 모양으로 바뀌는지.

**저장소에는 해외 계좌 저장본이 없습니다.** 실전 기록은 저장소에 안 올리는
자리에 있고, 그마저 예수금 둘뿐입니다(잔고·주문내역은 배열 칸 자체가 안 옵니다).
그래서 여기 시험은 **만들어 낸 응답**으로 세웁니다 — 누구 컴퓨터에서나 같게
돌아야 하고, 저장소를 갓 받은 사람도 돌릴 수 있어야 합니다.

칸 이름이 명세·실물과 맞는지는 따로 대조했습니다(이름만, 값은 안 봄).
"""
from __future__ import annotations

import json


from backend.overseas_futureoption.overseas_account import (
    CONVERSION,
    DEPOSIT_GROUPS,
    DEPOSIT_SINGLES,
    FINISHED_STATUS,
    ORDERABLE_FIELDS,
    OWN_SOURCE,
    deposit,
    order_history,
    orderable_quantity,
    positions,
)

# 지어낸 종목코드입니다. 실제 종목과 겹치지 않게 골랐습니다 — 아래 응답은 모두
# 만들어 낸 것이고, 시험이 보는 것은 값이 아니라 모양입니다.
지어낸종목 = "ZZZZ26"


def 예수금응답(**덮어쓰기):
    답 = {
        "biz_dt": "20260909",
        "ac_no": "FAKE-AC-000000",
        "cur_cd": "USD",
        "cur_fgr_cnt": "2",
        "ref_exrt": "1339.70",
        # 네 구분을 다 가진 항목 둘
        "strt_dps_tot_amt": "100",
        "strt_dps_csh_amt": "60",
        "strt_dps_sbst_amt": "30",
        "strt_dps_fcur_blc_amt": "10",
        "dps_tot_amt": "200",
        "dps_csh_amt": "120",
        "dps_sbst_amt": "50",
        "dps_fcur_amt": "30",
        # 총액 하나로만 오는 항목 몇
        "ord_mrgn": "11",
        "pstn_mrgn": "12",
        "aff_mrgn_amt": "13",
        "fx_psb_amt": "14",
        "tot_acc_aset_wth_amt": "15",
        "rsk_rt": "16.5",
    }
    답.update(덮어쓰기)
    return 답


# ── 격자가 아닌 모양 ────────────────────────────────────────


def test_네_구분을_가진_항목은_둘뿐이다():
    """국내는 일곱이 격자를 이루지만 해외는 둘뿐입니다."""
    assert len(DEPOSIT_GROUPS) == 2
    assert [row[0] for row in DEPOSIT_GROUPS] == ["start", "assets"]


def test_두_모양을_한_표로_합치지_않는다():
    made = deposit(예수금응답())

    assert [줄["key"] for 줄 in made["groups"]] == ["start", "assets"]
    assert all(len(줄["values"]) == 4 for 줄 in made["groups"])
    # 총액 하나짜리는 `value` 를 답니다 — 화면이 이걸로 두 모양을 가릅니다.
    assert all("value" in 줄 and "values" not in 줄 for 줄 in made["items"])


def test_없는_칸을_0_으로_채우지_않는다():
    """없는 것은 「값이 0」이 아니라 「그런 칸이 없다」입니다."""
    made = deposit({})

    assert all(값 is None for 줄 in made["groups"] for 값 in 줄["values"])
    assert all(줄["value"] is None for 줄 in made["items"])


# **「총액 = 세 칸 합」 시험을 두지 않습니다.**
#
# 국내 예수금에는 그 시험이 있고 매핑이 어긋나면 먼저 깨집니다. 해외는
# 다릅니다 — 실물 응답 둘에서 **예탁의 총액이 세 칸의 합보다 컸습니다**
# (개시예탁은 맞았습니다). 만들어 낸 응답에서 합이 맞게 적어 두고 그것을
# 시험하면, **반입본이 아니라 제 가정을 시험하는 것**이 됩니다. 값을 그대로
# 옮기는지는 아래 시험이 봅니다.


def test_총액을_더하지_않고_응답_값을_그대로_낸다():
    """세 칸의 합과 달라도 서버가 준 총액을 그대로 씁니다."""
    응답 = 예수금응답(dps_tot_amt="999", dps_csh_amt="1", dps_sbst_amt="0", dps_fcur_amt="0")
    예탁 = next(줄 for 줄 in deposit(응답)["groups"] if 줄["key"] == "assets")

    assert 예탁["values"][0] == 999
    assert 예탁["values"][1] == 1


def test_해외에만_있는_항목이_실려_온다():
    made = deposit(예수금응답())
    담긴열쇠 = {줄["key"] for 줄 in made["items"]}

    for 열쇠 in (
        "orderMargin",
        "positionMargin",
        "afterMargin",
        "exchangeable",
        "totalAccountValue",
        "riskRate",
    ):
        assert 열쇠 in 담긴열쇠


def test_줄마다_열쇠와_이름이_함께_나온다():
    made = deposit(예수금응답())
    assert [줄["key"] for 줄 in made["items"]] == [항목[0] for 항목 in DEPOSIT_SINGLES]
    assert all(줄["label"] for 줄 in made["items"])


# ── 통화와 환산 ─────────────────────────────────────────────


def test_어느_쪽으로_받은_것인지_함께_낸다():
    """표에 적힌 수가 합친 값인지 그 통화의 값인지 화면이 알아야 합니다."""
    합침 = deposit(예수금응답(), cur_cd="KRW", cvs_div="2")
    나눔 = deposit(예수금응답(), cur_cd="USD", cvs_div="1")

    assert 합침["conversion"] == "converted"
    assert 나눔["conversion"] == "by-currency"
    assert 합침["conversionCode"] == "2"


def test_환산구분은_응답에_안_오므로_물어본_값을_쓴다():
    assert deposit(예수금응답())["conversion"] is None
    assert deposit(예수금응답())["conversionCode"] is None
    assert set(CONVERSION) == {"1", "2"}


def test_통화는_응답이_먼저고_없으면_물어본_값():
    assert deposit(예수금응답())["currency"] == "USD"
    assert deposit(예수금응답(cur_cd=""), cur_cd="KRW")["currency"] == "KRW"


def test_자릿수와_환율은_응답이_알려_준다():
    """마스터를 안 찾아도 되고, 그 시점의 값이라 더 정확합니다."""
    made = deposit(예수금응답())

    assert made["decimals"] == 2
    assert made["rate"] == 1339.70
    assert deposit({})["decimals"] is None


def test_영업일자를_날짜_모양으로():
    assert deposit(예수금응답())["date"] == "2026-09-09"
    assert deposit(예수금응답(biz_dt=""))["date"] is None


# ── 계좌번호 ────────────────────────────────────────────────


def test_계좌번호를_지운다():
    응답 = 예수금응답()
    assert 응답["ac_no"], "지울 것이 있어야 이 시험이 뜻을 가집니다."

    담긴것 = json.dumps(deposit(응답), ensure_ascii=False)
    assert 응답["ac_no"] not in 담긴것
    assert "ac_no" not in 담긴것


# ── 보유 포지션 ─────────────────────────────────────────────
#
# 저장본에 해외 잔고는 **줄이 한 건도 없습니다**(배열 칸 자체가 안 옵니다).
# 그래서 아래는 전부 만들어 낸 응답입니다. 칸 이름이 명세와 맞는지는 따로
# 대조했습니다.


def 잔고줄(**덮어쓰기):
    한줄 = {
        "occurs1_ac_no": "FAKE-AC-000000",
        "occurs1_sym": 지어낸종목,
        "occurs1_fut_opt_tp": "1",
        "occurs1_trd_tp": "1",
        "occurs1_opint_qty": "2",
        "occurs1_cls_psb_qty": "2",
        "occurs1_avg_pric": "7600.00",
        "occurs1_last_pric": "7677.25",
        "occurs1_pl_amt": "386.25",
        "occurs1_cur_cd": "USD",
        "occurs1_usd_exrt": "1339.70",
        "occurs1_ctr_unt_amt": "5",
        "occurs1_exp_dt": "20260918",
    }
    한줄.update(덮어쓰기)
    return 한줄


def test_해외_포지션이_화면_모양으로_나온다():
    한줄 = positions({"Occurs1": [잔고줄()]})["positions"][0]

    assert 한줄["code"] == 지어낸종목
    assert 한줄["market"] == "overseas"
    assert 한줄["side"] == "long"
    assert 한줄["quantity"] == 2
    # 국내는 종가지만 해외는 현재가입니다.
    assert 한줄["lastPrice"] == 7677.25


def test_만기와_통화가_응답에서_온다():
    """국내는 만기가 없어 마스터에서 찾지만 해외는 실려 옵니다."""
    한줄 = positions({"Occurs1": [잔고줄()]})["positions"][0]

    assert 한줄["expiry"] == "2026-09-18"
    assert 한줄["currency"] == "USD"
    assert 한줄["rate"] == 1339.70


def test_종목명은_응답에_없다():
    """빈 이름을 결함으로 보지 않도록 계약에 적어 둔 자리입니다."""
    한줄 = positions({"Occurs1": [잔고줄()]})["positions"][0]
    assert "name" not in 한줄


def test_해외_잔고가_비어_올_수_있다():
    for 빈것 in ({"Occurs1": []}, {}, {"Occurs1": "줄이_아님"}):
        assert positions(빈것)["positions"] == []


def test_해외_잔고_줄의_계좌번호를_지운다():
    응답 = {"Occurs1": [잔고줄()]}
    assert 응답["Occurs1"][0]["occurs1_ac_no"], "지울 것이 있어야 뜻이 있습니다."

    담긴것 = json.dumps(positions(응답), ensure_ascii=False)
    assert "FAKE-AC-000000" not in 담긴것
    assert "ac_no" not in 담긴것


# ── 주문내역 ────────────────────────────────────────────────


def 주문줄(**덮어쓰기):
    한줄 = {
        "occurs1_ac_no": "FAKE-AC-000000",
        "occurs1_ord_no": "1234567890",
        "occurs1_sym": 지어낸종목,
        "occurs1_ord_dt": "20260909",
        "occurs1_trd_tp": "1",
        "occurs1_ord_sts": "6",
        "occurs1_qt_tp": "1",
        "occurs1_ord_tp": "2",
        "occurs1_ord_div": "0",
        "occurs1_fut_opt_tp": "1",
        "occurs1_med_div": "R",
        "occurs1_ord_qty": "1",
        "occurs1_exec_qty": "1",
        "occurs1_ord_rem_qty": "0",
        "occurs1_ord_pric": "7600.00",
        "occurs1_exec_pric": "7677.25",
        "occurs1_ord_rcv_tm": "20260909152122",
        "occurs1_exec_tm": "20260909152131",
        "occurs1_cur_cd": "USD",
    }
    한줄.update(덮어쓰기)
    return 한줄


def test_해외_주문내역이_화면_모양으로_나온다():
    한줄 = order_history({"Occurs1": [주문줄()]})["orders"][0]

    assert 한줄["id"] == "1234567890"
    assert 한줄["code"] == 지어낸종목
    assert 한줄["side"] == "buy"
    assert 한줄["status"] == "filled"
    assert 한줄["orderKind"] == "new"


def test_시각이_열네_자리로_와도_읽는다():
    """국내는 아홉 자리인데 해외는 날짜와 시각이 한 칸에 붙어 옵니다."""
    한줄 = order_history({"Occurs1": [주문줄()]})["orders"][0]

    assert 한줄["receivedDate"] == "2026-09-09"
    assert 한줄["receivedTime"] == "15:21:22"
    assert 한줄["fillTime"] == "15:21:31"
    # 화면이 쓰는 시각 하나 — 체결됐으면 체결시각.
    assert 한줄["time"] == "15:21:31"


def test_체결_안_된_주문의_체결시각은_없음이다():
    한줄 = order_history({"Occurs1": [주문줄(occurs1_exec_tm="00000000000000")]})["orders"][0]

    assert "fillTime" not in 한줄
    assert 한줄["time"] == "15:21:22"


def test_주문유형은_실시간과_같은_글자로_낸다():
    """명세는 STOP-M·STOP-L 인데 화면이 두 경로를 합치려면 글자가 같아야 합니다."""
    from backend.realtime import feeds

    바다 = feeds.PRICE_CONDITION["overseas"]
    for 코드 in ("1", "2", "3", "4"):
        한줄 = order_history({"Occurs1": [주문줄(occurs1_ord_tp=코드)]})["orders"][0]
        assert 한줄["orderType"] == 바다[코드], 코드


def test_명세에_없는_OCO_는_원문만_남긴다():
    한줄 = order_history({"Occurs1": [주문줄(occurs1_ord_tp="5")]})["orders"][0]
    assert 한줄["orderTypeCode"] == "5"
    assert "orderType" not in 한줄


def test_유효기간은_국내에_없는_값이다():
    for 코드, 뜻 in (("0", "DAY"), ("1", "GTC"), ("6", "GTD")):
        한줄 = order_history({"Occurs1": [주문줄(occurs1_ord_div=코드)]})["orders"][0]
        assert 한줄["validity"] == 뜻


def test_선물옵션구분이_국내와_값이_다르다():
    """국내 주문내역은 1선물·2콜·3풋·4스프레드, 해외는 1선물·2옵션·3스프레드."""
    from backend.domestic_futureoption import domestic_account as 국내

    한줄 = order_history({"Occurs1": [주문줄(occurs1_fut_opt_tp="3")]})["orders"][0]
    assert 한줄["productKind"] == "spread"
    # 국내에는 이 뜻의 표가 없습니다 — 있었다면 3 이 풋옵션이라 어긋납니다.
    assert not hasattr(국내, "PRODUCT_KIND")


def 고칠수있나(**덮어쓰기):
    """우리 매체로 낸, 잔량 남은, 접수 상태의 주문 한 줄."""
    기본 = {"occurs1_ord_sts": "1", "occurs1_ord_rem_qty": "2"}
    기본.update(덮어쓰기)
    return order_history({"Occurs1": [주문줄(**기본)]})["orders"][0]


def test_다른_길로_낸_주문은_화면에서_못_고친다():
    assert 고칠수있나()["editable"] is True
    남의것 = 고칠수있나(occurs1_med_div="H")
    assert 남의것["editable"] is False
    assert 남의것["source"] == "HTS"


def test_해외도_끝난_주문은_못_고친다():
    for 끝난상태 in ("6", "8", "9"):
        assert 고칠수있나(occurs1_ord_sts=끝난상태)["editable"] is False, 끝난상태
    for 남은상태 in ("1", "3", "4"):
        assert 고칠수있나(occurs1_ord_sts=남은상태)["editable"] is True, 남은상태


def test_해외도_잔량이_없거나_모르면_못_고친다():
    assert 고칠수있나(occurs1_ord_rem_qty="0")["editable"] is False
    assert 고칠수있나(occurs1_ord_rem_qty="")["editable"] is False


def test_두_시장이_같은_규칙으로_고칠_수_있는지_정한다():
    """화면은 두 시장 주문을 한 표에 섞어 놓고 `editable` 하나만 봅니다."""
    from backend.domestic_futureoption import domestic_account

    assert domestic_account.FINISHED_STATUS == FINISHED_STATUS
    assert domestic_account.OWN_SOURCE == OWN_SOURCE


def test_해외_주문내역이_비어_올_수_있다():
    for 빈것 in ({"Occurs1": []}, {}, {"Occurs1": "줄이_아님"}):
        assert order_history(빈것)["orders"] == []


def test_해외_주문내역_줄의_사람과_계좌를_지운다():
    """계좌번호만이 아닙니다 — 작업사원과 주문IP 도 줄마다 옵니다."""
    지울것 = {
        "occurs1_ac_no": "FAKE-AC-000000",
        "occurs1_user_id": "FAKE-USER",
        "occurs1_ip_addr": "203.0.113.9",
    }
    응답 = {"Occurs1": [주문줄(**지울것)]}
    # 먼저 지울 것이 정말 들어 있는지 봅니다. 안 그러면 이 시험은 늘 통과합니다.
    담긴원문 = json.dumps(응답, ensure_ascii=False)
    for 값 in 지울것.values():
        assert 값 in 담긴원문

    담긴것 = json.dumps(order_history(응답), ensure_ascii=False)
    for 칸, 값 in 지울것.items():
        assert 값 not in 담긴것, 칸
        assert 칸 not in 담긴것


# ── 국내 줄과 한 벌인지 ─────────────────────────────────────


def 국내주문줄():
    """국내 주문내역 응답 한 줄. 칸 이름이 해외와 달라 따로 지어냅니다."""
    return {
        "occurs1_ord_no": "1",
        "occurs1_sym": 지어낸종목,
        "occurs1_sym_nm": "지어낸이름",
        "occurs1_trd_div": "1",
        "occurs1_ord_sts": "4",
        "occurs1_pric_cnd_nm": "지정가",
        "occurs1_med_div": "R",
        "occurs1_ord_qty": "2",
        "occurs1_exec_qty": "1",
        "occurs1_rem_ord_qty": "1",
        "occurs1_exch_exec_tm": "152122000",
    }


def test_해외_주문내역_줄이_국내와_같은_낱말을_쓴다():
    """화면의 주문 목록은 시장을 가리지 않고 한 표에 섞어 놓습니다.

    한쪽에만 있는 칸이 생기면 그 시장 줄만 칸이 빕니다. 잔량이 그렇게 빠져
    있었습니다 — 그래서 열쇠를 세는 시험을 둡니다.
    """
    from backend.domestic_futureoption import domestic_account

    해외 = order_history({"Occurs1": [주문줄(occurs1_ord_sts="4", occurs1_ord_rem_qty="1")]})
    해외줄 = 해외["orders"][0]
    국내줄 = domestic_account.order_history({"Occurs1": [국내주문줄()]})["orders"][0]

    for 칸 in (
        "id",
        "code",
        "side",
        "status",
        "orderType",
        "time",
        "source",
        "quantity",
        "filled",
        "remaining",
    ):
        assert 칸 in 국내줄, f"국내 줄에 {칸} 이 없습니다"
        assert 칸 in 해외줄, f"해외 줄에 {칸} 이 없습니다"

    # 값 체계도 같아야 합니다 — 한쪽만 영문 낱말이면 화면이 못 합칩니다.
    assert 국내줄["side"] == 해외줄["side"] == "buy"
    assert 국내줄["status"] == 해외줄["status"] == "partial"
    assert 국내줄["orderType"] == 해외줄["orderType"] == "지정가"
    assert 국내줄["remaining"] == 해외줄["remaining"] == 1


def test_주문잔량이_없으면_화면_칸도_없다():
    """응답이 잔량을 안 주면 0 으로 지어내지 않습니다."""
    한줄 = order_history({"Occurs1": [주문줄(occurs1_ord_rem_qty="")]})["orders"][0]
    assert "remaining" not in 한줄


# ── 주문가능수량 ────────────────────────────────────────────
#
# 저장소에 이 조회의 저장본이 **한 건도 없습니다**(공개 0건). 아래는 명세의
# 아홉 칸으로 만들어 낸 응답입니다.


def 가능수량응답(**덮어쓰기):
    답 = {
        "prd_cd": "ZZZ",
        "cur_cd": "USD",
        "ord_psb_amt": "1234.5",
        "new_buy_ord_psb_qty": "3",
        "buy_cls_psb_qty": "2",
        "buy_ord_psb_qty": "5",
        "new_sel_ord_psb_qty": "7",
        "sel_cls_psb_qty": "1",
        "sel_ord_psb_qty": "8",
    }
    답.update(덮어쓰기)
    return 답


def test_해외_주문가능수량이_물어본_방향만_낸다():
    """응답에는 매수·매도가 다 오지만 화면은 한 방향만 씁니다."""
    매수 = orderable_quantity(가능수량응답(), code=지어낸종목, side="buy")
    매도 = orderable_quantity(가능수량응답(), code=지어낸종목, side="sell")

    assert (매수["quantity"], 매수["newQuantity"], 매수["closeQuantity"]) == (5, 3, 2)
    assert (매도["quantity"], 매도["newQuantity"], 매도["closeQuantity"]) == (8, 7, 1)
    # 반대쪽 값이 섞여 나오면 안 됩니다.
    assert 매수["quantity"] != 매도["quantity"]


def test_해외_주문가능수량에_통화와_품목이_실려_온다():
    """품목코드는 응답 칸이 아니라 **종목 마스터의 품목**입니다(부르는 쪽이 넘김)."""
    답 = orderable_quantity(가능수량응답(), code=지어낸종목, side="buy", product_code="ZZZ")

    assert 답["amount"] == 1234.5
    assert 답["currency"] == "USD"
    assert 답["productCode"] == "ZZZ"
    assert 답["market"] == "overseas"


def test_모르는_방향이면_수량_칸을_안_담는다():
    답 = orderable_quantity(가능수량응답(), code=지어낸종목, side="hold")

    for 없어야할것 in ("quantity", "newQuantity", "closeQuantity"):
        assert 없어야할것 not in 답
    # 방향과 상관없는 값은 그대로 옵니다.
    assert 답["amount"] == 1234.5


def test_해외_없는_칸은_지어내지_않는다():
    답 = orderable_quantity({"buy_ord_psb_qty": "5"}, code=지어낸종목, side="buy")

    assert 답["quantity"] == 5
    for 없어야할것 in ("newQuantity", "closeQuantity", "amount", "currency"):
        assert 없어야할것 not in 답
    # 품목은 응답이 아니라 종목 마스터에서 옵니다 — 마스터가 모르면 칸은 있고 값은 null.
    assert 답["productCode"] is None


def test_해외_주문가능수량_품목은_응답의_prd_cd_가_아니라_마스터에서():
    """응답 prd_cd 에 통화가 실려 와도 품목은 부르는 쪽이 넘긴 마스터 품목입니다."""
    응답 = {**가능수량응답(), "prd_cd": "USD"}

    assert orderable_quantity(응답, code=지어낸종목, side="buy", product_code="ZZZ")["productCode"] == "ZZZ"
    assert orderable_quantity(응답, code=지어낸종목, side="buy")["productCode"] is None


def test_두_시장_주문가능수량이_같은_낱말을_쓴다():
    """주문 폼은 시장을 가리지 않고 같은 자리에 같은 말로 적습니다."""
    from backend.domestic_futureoption import domestic_account

    해외 = orderable_quantity(가능수량응답(), code=지어낸종목, side="buy")
    국내 = domestic_account.orderable_quantity(
        {"ord_psb_qty": "3", "cls_psb_qty": "2", "tot_psb_qty": "5", "ord_psb_amt": "1234.5"},
        code=지어낸종목,
        side="buy",
    )

    for 칸 in ("code", "market", "side", "quantity", "newQuantity", "closeQuantity", "amount"):
        assert 칸 in 국내, f"국내에 {칸} 이 없습니다"
        assert 칸 in 해외, f"해외에 {칸} 이 없습니다"
    assert 국내["quantity"] == 해외["quantity"] == 5
    # 통화와 품목코드는 해외 응답에만 있는 칸입니다.
    assert "currency" not in 국내
    assert "currency" in 해외


def test_방향_표가_매수와_매도_둘뿐이다():
    assert set(ORDERABLE_FIELDS) == {"buy", "sell"}
    for 칸들 in ORDERABLE_FIELDS.values():
        assert len(칸들) == 3


def test_해외_원주문번호가_0_으로만_오면_없다():
    줄 = order_history(
        {"Occurs1": [주문줄(occurs1_org_ord_no="0000000000"), 주문줄(occurs1_org_ord_no="0000000118")]}
    )["orders"]

    assert 줄[0].get("originalOrderNo") is None
    assert 줄[1]["originalOrderNo"] == "0000000118"


# ── 보유포지션 만기 ─────────────────────────────────────────


def 만기줄(**덮어쓰기):
    한줄 = {
        "occurs1_sym": 지어낸종목,
        "occurs1_sym_nm": "지어낸 선물 12월물",
        "occurs1_cd_nm": "매수",
        "occurs1_pstn_qty": "2",
        "occurs1_exec_pric": "7677.25",
        "occurs1_exec_dt": "20260915",
        "occurs1_cur_cd": "USD",
        "occurs1_dlv_sett_div_nm": "현금결제",
        "occurs1_fst_ntf_dt": "20261211",
        "occurs1_exp_dt": "20261218",
        "occurs1_rem_dy": "81",
    }
    한줄.update(덮어쓰기)
    return 한줄


def test_보유포지션_만기가_화면_모양으로_나온다():
    from backend.overseas_futureoption.overseas_account import expiry_positions

    답 = expiry_positions(
        {"nrec": "0002", "nxt_key": "", "Occurs1": [만기줄(), 만기줄(occurs1_cd_nm="매도", occurs1_pstn_qty="1")]}
    )

    매수, 매도 = 답["positions"]
    assert 매수 == {
        "market": "overseas",
        "code": 지어낸종목,
        "name": "지어낸 선물 12월물",
        "sideName": "매수",
        "side": "buy",
        "quantity": 2,
        "fillPrice": 7677.25,
        "fillDate": "2026-09-15",
        "currency": "USD",
        "delivery": "현금결제",
        "firstNotice": "2026-12-11",
        "expiry": "2026-12-18",
        "daysLeft": 81,
    }
    assert (매도["side"], 매도["sideName"], 매도["quantity"]) == ("sell", "매도", 1)
    assert (답["count"], 답["nextKey"]) == (2, "")


def test_보유포지션_만기_모르는_매매구분은_방향을_비운다():
    from backend.overseas_futureoption.overseas_account import expiry_positions

    한줄 = expiry_positions({"Occurs1": [만기줄(occurs1_cd_nm="매수청산")]})["positions"][0]
    assert (한줄["side"], 한줄["sideName"]) == (None, "매수청산")


def test_보유포지션_만기_빈_날짜와_숫자는_null():
    from backend.overseas_futureoption.overseas_account import expiry_positions

    한줄 = expiry_positions(
        {"Occurs1": [만기줄(occurs1_fst_ntf_dt="", occurs1_exp_dt="00000000", occurs1_exec_pric="", occurs1_rem_dy="")]}
    )["positions"][0]
    assert (한줄["firstNotice"], 한줄["expiry"], 한줄["fillPrice"], 한줄["daysLeft"]) == (None, None, None, None)


def test_보유포지션_만기_잔존일은_받은_값_그대로():
    """만기일을 포함해 센 값입니다 — 만기일 − 오늘로 다시 세지 않습니다."""
    from backend.overseas_futureoption.overseas_account import expiry_positions

    한줄 = expiry_positions({"Occurs1": [만기줄(occurs1_exp_dt="20261218", occurs1_rem_dy="999")]})["positions"][0]
    assert 한줄["daysLeft"] == 999


def test_보유포지션_만기_0줄_답():
    """수집해 둔 실전 답 모양입니다 — 배열 칸 없이 건수와 키만 옵니다."""
    from backend.overseas_futureoption.overseas_account import expiry_positions

    assert expiry_positions({"nxt_key": "", "nrec": "0000"}) == {"positions": [], "count": 0, "nextKey": ""}


def test_보유포지션_만기에_계좌번호는_안_나간다():
    from backend.overseas_futureoption.overseas_account import expiry_positions

    한줄 = expiry_positions({"Occurs1": [만기줄(occurs1_ac_no="FAKE-AC-000000")]})["positions"][0]
    assert "FAKE-AC-000000" not in str(한줄)


def test_보유포지션_만기_잔존일은_만기일_빼기_오늘로_온다():
    """모의 계좌에서 받은 모양(2026-09-30, 만기일 2026-12-18) — 79 로 옵니다. 명세의
    「만기일 포함」대로면 80 이지만 실제는 포함하지 않습니다. 받은 값을 그대로 냅니다."""
    from backend.overseas_futureoption.overseas_account import expiry_positions

    한줄 = expiry_positions(
        {"Occurs1": [만기줄(occurs1_sym="MESZ26", occurs1_exp_dt="20261218", occurs1_fst_ntf_dt="20261218", occurs1_rem_dy="79")]}
    )["positions"][0]

    assert (한줄["expiry"], 한줄["firstNotice"], 한줄["daysLeft"]) == ("2026-12-18", "2026-12-18", 79)


def test_보유포지션_만기_체결가는_쉼표를_빼고_읽는다():
    from backend.overseas_futureoption.overseas_account import expiry_positions

    for 원문, 값 in (("7,745.25", 7745.25), ("12,345", 12345.0), ("7745.25", 7745.25)):
        assert expiry_positions({"Occurs1": [만기줄(occurs1_exec_pric=원문)]})["positions"][0]["fillPrice"] == 값


def test_보유포지션_만기_체결가가_비어_오면_null():
    from backend.overseas_futureoption.overseas_account import expiry_positions

    for 원문 in ("", None, "  "):
        assert expiry_positions({"Occurs1": [만기줄(occurs1_exec_pric=원문)]})["positions"][0]["fillPrice"] is None

