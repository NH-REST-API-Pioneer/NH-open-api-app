"""국내 계좌 응답이 화면 모양으로 바뀌는지 — 반입해 둔 모의 응답으로 확인합니다."""
from __future__ import annotations

import json

import pytest

from backend.domestic_futureoption.domestic_account import (
    DEPOSIT_ITEMS,
    ORDER_SIDE,
    ORDER_SOURCE,
    ORDER_STATUS,
    SIDE_CODE,
    DEPOSIT_SINGLES,
    deposit,
    order_errors,
    order_history,
    orderable_quantity,
    positions,
)
from backend.nh_api.fixtures import FIXTURE_ROOT


def 반입본() -> list[dict]:
    """반입해 둔 예수금 응답 전부."""
    return [
        json.loads(경로.read_text(encoding="utf-8"))["response"]
        for 경로 in sorted((FIXTURE_ROOT / "domestic_deposit").rglob("*.json"))
    ]


@pytest.fixture(scope="module")
def 응답들():
    made = 반입본()
    assert made, "반입해 둔 예수금 응답이 있어야 합니다."
    return made


# ── 표 모양 ─────────────────────────────────────────────────


def test_항목_일곱에_칸이_넷씩_나온다(응답들):
    made = deposit(응답들[0])
    assert len(made["items"]) == 7
    assert all(len(row["values"]) == 4 for row in made["items"])


def test_줄마다_열쇠와_이름이_함께_나온다(응답들):
    made = deposit(응답들[0])
    assert [row["key"] for row in made["items"]] == [item[0] for item in DEPOSIT_ITEMS]
    assert all(row["label"] for row in made["items"])


def test_총액_칸이_나머지_세_칸의_합과_같다(응답들):
    """서버가 세는 방식이 우리 생각과 같은지 — 어긋나면 매핑이 틀린 것입니다."""
    for raw in 응답들:
        for row in deposit(raw)["items"]:
            총액, 현금, 대용, 외화 = row["values"]
            assert 총액 == pytest.approx((현금 or 0) + (대용 or 0) + (외화 or 0)), row["key"]


def test_예탁자산_총액은_입금액이_아니다(응답들):
    """`dps_amt` 은 이름이 그럴듯하지만 명세 한글명이 「입금액」입니다."""
    raw = 응답들[0]
    자산 = next(row for row in deposit(raw)["items"] if row["key"] == "assets")

    assert 자산["values"][0] == float(raw["dps_aset_tot_amt"])
    # 반입본에서 둘의 값이 다릅니다. `dps_amt` 으로 잡으면 예수금이 0 이 됩니다.
    assert float(raw["dps_amt"]) != 자산["values"][0]


@pytest.mark.parametrize(
    ("key", "field"),
    [
        ("start", "strt_dps_fcur_blc_amt"),
        ("maintenanceMargin", "mtn_mrgn_tam_amt"),
        ("assets", "dps_aset_tot_amt"),
    ],
)
def test_이름이_규칙에서_벗어난_세_칸을_제자리에_넣는다(응답들, key, field):
    raw = 응답들[0]
    줄 = next(row for row in deposit(raw)["items"] if row["key"] == key)
    자리 = 3 if field.endswith("fcur_blc_amt") else 0
    assert 줄["values"][자리] == float(raw[field])


# ── 값 규칙 ─────────────────────────────────────────────────


def test_안_온_칸은_없음이다():
    made = deposit({})
    assert all(값 is None for row in made["items"] for 값 in row["values"])
    assert made["date"] is None


def test_0_과_없음을_가른다():
    """원래 안 오는 칸과 「0원」이 화면에서 갈려야 합니다."""
    made = deposit({"ord_psb_tot_amt": "0", "ord_psb_csh_amt": ""})
    주문가능 = next(row for row in made["items"] if row["key"] == "orderable")
    assert 주문가능["values"][0] == 0
    assert 주문가능["values"][1] is None


def test_영업일자는_물어본_쪽에서_온다(응답들):
    """응답에 날짜가 없습니다 — 명세에서 `biz_dt` 는 요청 항목뿐입니다."""
    assert all("biz_dt" not in raw for raw in 응답들)

    assert deposit(응답들[0], asked_date="20260909")["date"] == "2026-09-09"
    assert deposit(응답들[0])["date"] is None
    assert deposit({}, asked_date="안녕")["date"] is None
    # 자리 수만 세지 않고 있는 날인지 봅니다.
    assert deposit({}, asked_date="20261345")["date"] is None


def test_낱개_값도_함께_나온다(응답들):
    made = deposit(응답들[0])
    for name, _ in DEPOSIT_SINGLES:
        assert name in made


def test_숫자가_아닌_낱개_값은_글자_그대로():
    made = deposit({"adt_mrgn_ocu_div_nm": "추가증거금"})
    assert made["marginCallReason"] == "추가증거금"
    assert deposit({})["marginCallReason"] is None


def test_추가증거금이_안_생겨도_구분명은_채워져_온다(응답들):
    """이 값이 있다고 발생한 것이 아닙니다 — 발생 여부는 금액으로 봅니다."""
    for raw in 응답들:
        assert str(raw["adt_mrgn_ocu_div_nm"]).strip() == "발생 없음"
        assert float(raw["adt_mrgn_tot_amt"]) == 0

    made = deposit(응답들[0])
    assert made["marginCallReason"] == "발생 없음"
    추가 = next(row for row in made["items"] if row["key"] == "additionalMargin")
    assert 추가["values"][0] == 0


def test_낱개_값_이름은_명세_한글명을_따른다(응답들):
    """약자를 짐작해 옮기면 값은 맞고 뜻만 뒤집힙니다."""
    raw = 응답들[0]
    made = deposit(raw)

    # `rez` 는 미실현이 아니라 확정입니다.
    assert made["futuresRealisedPl"] == float(raw["fut_rez_pl_amt"])
    assert made["optionRealisedPl"] == float(raw["opt_rez_pl_amt"])
    # `opt_pl_amt` 는 평가손익이라 확정손익과 갈라 적습니다.
    assert made["optionUnrealisedPl"] == float(raw["opt_pl_amt"])
    # `cls` 는 청산이 아니라 장중 순손실 상당액입니다.
    assert made["futuresIntradayLoss"] == float(raw["fut_cls_pl_amt"])
    for 옛이름 in ("futuresUnrealisedPl", "futuresClosedPl", "optionPl"):
        assert 옛이름 not in made


def test_야간정산차금이_선물정산차금_뒤에_실린다(응답들):
    """반입본 값은 0 이고, 낱개 값의 차례는 선물정산차금 뒤에 하나만 낍니다."""
    made = deposit(응답들[0])
    assert made["nightSettlement"] == 0.0

    이름들 = [name for name, _ in DEPOSIT_SINGLES]
    자리 = 이름들.index("futuresSettlement")
    assert 이름들[자리 + 1] == "nightSettlement"
    assert [name for name in 이름들 if name != "nightSettlement"] == [
        "fee", "nightFee", "futuresSettlement", "futuresIntradayLoss", "futuresRealisedPl",
        "optionUnrealisedPl", "optionRealisedPl", "totalPl", "nextDaySettlement", "unpaid",
        "marginCallReason",
    ]


@pytest.mark.parametrize("원문, 값", [("-000000000000012500.000", -12500.0), ("000000000000212500.000", 212500.0)])
def test_정산차금_두_칸은_부호를_그대로_낸다(원문, 값):
    """손익 값이라 양수는 이익, 음수는 손실 — 부호를 바꾸지 않습니다."""
    made = deposit({"fut_sett_amt": 원문, "nght_sett_amt": 원문, "fut_cls_pl_amt": 원문})

    assert made["futuresSettlement"] == 값
    assert made["nightSettlement"] == 값
    assert made["futuresIntradayLoss"] == 값


# ── 계좌번호 ────────────────────────────────────────────────


def test_예수금_응답에는_계좌번호가_아예_없다(응답들):
    """지울 것이 없다는 사실 자체를 적어 둡니다.

    계좌번호는 잔고·주문내역처럼 **줄이 있는 응답**에 `occurs1_ac_no` 로 옵니다.
    예수금에는 없어서, 여기서 「지웠다」고 하면 헛도는 시험이 됩니다. 지우는
    것을 지키는 시험은 그 두 응답을 붙일 때 함께 넣습니다.
    """
    for raw in 응답들:
        assert not [key for key in raw if "ac_no" in key or "ac_nm" in key]

    담긴것 = json.dumps(deposit(응답들[0]), ensure_ascii=False)
    assert "ac_no" not in 담긴것
    assert "ac_nm" not in 담긴것


# ── 보유 포지션 ─────────────────────────────────────────────


def 잔고들() -> list[dict]:
    return [
        json.loads(경로.read_text(encoding="utf-8"))["response"]
        for 경로 in sorted((FIXTURE_ROOT / "domestic_open-interest").rglob("*.json"))
    ]


@pytest.fixture(scope="module")
def 줄있는잔고():
    """줄이 실제로 담긴 응답. 빈 응답으로는 아무것도 확인되지 않습니다."""
    for raw in 잔고들():
        if raw.get("Occurs1"):
            return raw
    pytest.skip("줄이 담긴 잔고 응답이 반입되어 있지 않습니다.")


def test_보유_포지션이_화면_모양으로_나온다(줄있는잔고):
    줄 = positions(줄있는잔고)["positions"]
    assert 줄

    원본 = 줄있는잔고["Occurs1"][0]
    첫줄 = 줄[0]
    assert 첫줄["code"] == 원본["occurs1_sym"]
    assert 첫줄["name"] == 원본["occurs1_ko_sym_nm"]
    assert 첫줄["quantity"] == int(float(원본["occurs1_opint_qty"]))
    assert 첫줄["avgPrice"] == float(원본["occurs1_avg_pric"])
    # 국내는 현재가가 아니라 종가로 옵니다.
    assert 첫줄["lastPrice"] == float(원본["occurs1_close_pric"])


def test_매매구분을_길고_짧음으로_읽는다():
    긴것 = positions({"Occurs1": [{"occurs1_trd_div": "1"}]})["positions"][0]
    짧은것 = positions({"Occurs1": [{"occurs1_trd_div": "2"}]})["positions"][0]

    assert 긴것["side"] == "long"
    assert 짧은것["side"] == "short"


def test_모르는_매매구분은_원문만_남긴다():
    한줄 = positions({"Occurs1": [{"occurs1_trd_div": "9"}]})["positions"][0]
    assert 한줄["sideCode"] == "9"
    assert "side" not in 한줄


def test_줄마다_주간인지_야간인지_알려_준다():
    """한 응답에 주간 줄과 야간 줄이 섞여 옵니다."""
    나온것 = positions(
        {
            "Occurs1": [
                {"occurs1_exch_cd": "KRX"},
                {"occurs1_exch_cd": "KRX_NDV"},
            ]
        }
    )["positions"]

    assert [줄["market"] for 줄 in 나온것] == ["domestic-day", "domestic-night"]


def test_모르는_거래소코드는_원문만_남긴다():
    한줄 = positions({"Occurs1": [{"occurs1_exch_cd": "KRX_X"}]})["positions"][0]
    assert 한줄["exchangeCode"] == "KRX_X"
    assert "market" not in 한줄


def test_잔고가_비어_올_수_있다():
    for 빈것 in ({"Occurs1": []}, {}, {"Occurs1": "줄이_아님"}):
        assert positions(빈것)["positions"] == []


def test_이어_받을_키를_함께_낸다():
    assert positions({"nxt_key": "다음"})["nextKey"] == "다음"
    assert positions({})["nextKey"] == ""


def test_잔고_줄의_계좌번호와_계좌명을_지운다(줄있는잔고):
    """이번에는 지울 것이 실제로 있습니다 — 예수금과 다른 자리입니다."""
    원본줄 = 줄있는잔고["Occurs1"]
    계좌값 = {
        str(줄.get(항목) or "").strip()
        for 줄 in 원본줄
        for 항목 in ("occurs1_ac_no", "occurs1_ac_nm")
    }
    계좌값.discard("")
    # 지울 것이 없으면 아래 확인이 헛돕니다.
    assert 계좌값, "반입본 잔고 줄에 계좌번호나 계좌명이 있어야 이 시험이 뜻을 가집니다."

    담긴것 = json.dumps(positions(줄있는잔고), ensure_ascii=False)
    for 값 in 계좌값:
        assert 값 not in 담긴것
    assert "ac_no" not in 담긴것
    assert "ac_nm" not in 담긴것


def test_쓰는_곳이_없는_값은_안_낸다(줄있는잔고):
    """화면 타입에 없는 값을 미리 내보내면 계약에 남습니다."""
    담긴것 = json.dumps(positions(줄있는잔고), ensure_ascii=False)
    for 아직 in ("cls_psb_qty", "opint_amt"):
        assert 아직 not in 담긴것


def test_잔고_줄이_무슨_상품인지_알려_준다(줄있는잔고):
    첫줄 = positions(줄있는잔고)["positions"][0]
    원본 = 줄있는잔고["Occurs1"][0]

    assert 첫줄["productKindCode"] == 원본["occurs1_fut_opt_div_cd"]
    assert 첫줄["productKind"] == "futures"


def test_잔고의_그외는_낱말_없이_코드만_낸다():
    """명세가 「3:그외」라고만 적어, 스프레드라고 짚어 말하지 않습니다."""
    옵션 = positions({"Occurs1": [{"occurs1_fut_opt_div_cd": "2"}]})["positions"][0]
    그외 = positions({"Occurs1": [{"occurs1_fut_opt_div_cd": "3"}]})["positions"][0]

    assert 옵션["productKind"] == "option"
    assert 그외["productKindCode"] == "3"
    assert "productKind" not in 그외


# ── 주문내역과 미체결 ────────────────────────────────────────


@pytest.fixture(scope="module")
def 줄있는주문내역():
    for 경로 in sorted((FIXTURE_ROOT / "domestic_order-history").rglob("*.json")):
        raw = json.loads(경로.read_text(encoding="utf-8"))["response"]
        if raw.get("Occurs1"):
            return raw
    pytest.skip("줄이 담긴 주문내역이 반입되어 있지 않습니다.")


def test_주문내역이_화면_모양으로_나온다(줄있는주문내역):
    줄 = order_history(줄있는주문내역)["orders"]
    assert 줄

    원본 = 줄있는주문내역["Occurs1"][0]
    첫줄 = 줄[0]
    assert 첫줄["id"] == 원본["occurs1_ord_no"]
    assert 첫줄["code"] == 원본["occurs1_sym"]
    assert 첫줄["name"] == 원본["occurs1_sym_nm"]
    assert 첫줄["quantity"] == int(float(원본["occurs1_ord_qty"]))


def test_한_줄에_주문과_체결이_함께_들어_있다(줄있는주문내역):
    """화면의 두 표가 같은 목록을 다르게 읽습니다."""
    체결된것 = [줄 for 줄 in order_history(줄있는주문내역)["orders"] if 줄.get("fillPrice")]
    assert 체결된것, "체결된 줄이 있어야 이 시험이 뜻을 가집니다."

    한줄 = 체결된것[0]
    # 미체결 표가 읽는 것
    assert "quantity" in 한줄 and "remaining" in 한줄
    # 체결 표가 읽는 것
    assert "fillPrice" in 한줄 and "fillTime" in 한줄


def test_주문_종류는_코드가_아니라_이름에서_온다(줄있는주문내역):
    """명세가 가격조건코드의 뜻을 「(미사용)」으로 두어 안 밝힙니다.

    값은 채워져 옵니다 — 그래서 「비어 있으니 이름을 쓴다」가 아니라
    **뜻을 모르는 코드를 짐작해 옮기지 않는다**가 이유입니다.
    """
    원본줄 = 줄있는주문내역["Occurs1"]
    assert all(str(줄.get("occurs1_pric_cnd_cd") or "").strip() for 줄 in 원본줄), (
        "코드 칸이 채워져 온다는 전제가 깨졌으면 이 판단을 다시 보세요."
    )

    첫줄 = order_history(줄있는주문내역)["orders"][0]
    assert 첫줄["orderType"] == 원본줄[0]["occurs1_pric_cnd_nm"]
    # 뜻을 모르는 코드 칸은 내보내지 않습니다.
    assert "pric_cnd_cd" not in json.dumps(첫줄, ensure_ascii=False)


@pytest.mark.parametrize(
    ("칸", "원문", "코드", "뜻"),
    [
        ("side", "occurs1_trd_div", "1", "buy"),
        ("side", "occurs1_trd_div", "2", "sell"),
        ("status", "occurs1_ord_sts", "1", "accepted"),
        ("status", "occurs1_ord_sts", "4", "partial"),
        ("status", "occurs1_ord_sts", "6", "filled"),
        ("status", "occurs1_ord_sts", "9", "rejected"),
        ("orderKind", "occurs1_ord_div_cd", "2", "modify"),
        ("fillCondition", "occurs1_exec_cnd_cd", "2", "FOK"),
    ],
)
def test_명세에_뜻이_있는_코드를_읽는다(칸, 원문, 코드, 뜻):
    한줄 = order_history({"Occurs1": [{원문: 코드}]})["orders"][0]
    assert 한줄[칸] == 뜻
    assert 한줄[f"{칸}Code"] == 코드


def test_모르는_코드는_원문만_남긴다():
    한줄 = order_history({"Occurs1": [{"occurs1_ord_sts": "7"}]})["orders"][0]
    assert 한줄["statusCode"] == "7"
    assert "status" not in 한줄


@pytest.mark.parametrize(
    ("코드", "뜻"),
    [("1", "futures"), ("2", "option"), ("3", "option"), ("4", "spread")],
)
def test_주문내역의_상품구분은_잔고와_표가_다르다(코드, 뜻):
    """이쪽은 콜과 풋을 갈라 세 번째 자리까지 옵션입니다."""
    한줄 = order_history({"Occurs1": [{"occurs1_fut_opt_div_cd": 코드}]})["orders"][0]

    assert 한줄["productKind"] == 뜻
    assert 한줄["productKindCode"] == 코드


def test_스프레드처리구분이_말하면_스프레드다():
    """상품구분이 스프레드라고 말하지 않아도 이 칸이 말하면 스프레드입니다."""
    줄 = {"occurs1_fut_opt_div_cd": "1", "occurs1_spd_proc_div_cd": "S"}
    나머지 = {"occurs1_fut_opt_div_cd": "1", "occurs1_spd_proc_div_cd": "G"}

    assert order_history({"Occurs1": [줄]})["orders"][0]["productKind"] == "spread"
    assert order_history({"Occurs1": [나머지]})["orders"][0]["productKind"] == "futures"


def test_저장해_둔_주문내역_줄의_상품구분(줄있는주문내역):
    첫줄 = order_history(줄있는주문내역)["orders"][0]
    원본 = 줄있는주문내역["Occurs1"][0]

    assert 첫줄["productKindCode"] == 원본["occurs1_fut_opt_div_cd"]
    assert 첫줄["productKind"] == "futures"
    assert 원본["occurs1_spd_proc_div_cd"] == "G", "반입된 줄에 스프레드가 없습니다."


def test_상품구분_낱말이_해외와_같다():
    """두 시장의 같은 칸을 화면이 한 벌로 읽습니다."""
    from backend.domestic_futureoption.domestic_account import (
        ORDER_PRODUCT_KIND,
        POSITION_PRODUCT_KIND,
    )
    from backend.overseas_futureoption.overseas_account import PRODUCT_KIND

    국내 = set(ORDER_PRODUCT_KIND.values()) | set(POSITION_PRODUCT_KIND.values())
    assert 국내 == set(PRODUCT_KIND.values()) == {"futures", "option", "spread"}


def test_시장가_주문의_주문가격은_없음이다():
    한줄 = order_history({"Occurs1": [{"occurs1_ord_pric": "0"}]})["orders"][0]
    assert "price" not in 한줄


def 고칠수있나(**덮어쓰기):
    """우리 매체로 낸, 잔량 남은, 접수 상태의 주문 한 줄."""
    한줄 = {
        "occurs1_med_div": "R",
        "occurs1_ord_sts": "1",
        "occurs1_ord_qty": "3",
        "occurs1_rem_ord_qty": "3",
    }
    한줄.update(덮어쓰기)
    return order_history({"Occurs1": [한줄]})["orders"][0]


def test_다른_길로_낸_주문은_화면에서_못_고친다():
    assert 고칠수있나()["editable"] is True
    assert 고칠수있나(occurs1_med_div="H")["editable"] is False


def test_끝난_주문은_못_고친다():
    """**매체만 보면 체결 끝난 우리 주문에도 참이 됩니다.**

    화면은 이 값 하나로 단추를 세우므로, 그러면 이미 끝난 주문에 정정 단추가
    섭니다. 체결완료·자동취소·거부 셋을 상태 **코드**로 가립니다.
    """
    for 끝난상태 in ("6", "8", "9"):
        assert 고칠수있나(occurs1_ord_sts=끝난상태)["editable"] is False, 끝난상태
    # 접수·확인·부분체결은 아직 고칠 수 있습니다.
    for 남은상태 in ("1", "3", "4"):
        assert 고칠수있나(occurs1_ord_sts=남은상태)["editable"] is True, 남은상태


def test_잔량이_없거나_모르면_못_고친다():
    """0 과 「칸이 안 왔다」는 다른 일이지만 답은 같습니다."""
    assert 고칠수있나(occurs1_rem_ord_qty="0")["editable"] is False
    assert 고칠수있나(occurs1_rem_ord_qty="")["editable"] is False
    # 칸 자체가 없는 경우.
    없는것 = order_history(
        {"Occurs1": [{"occurs1_med_div": "R", "occurs1_ord_sts": "1"}]}
    )["orders"][0]
    assert "remaining" not in 없는것
    assert 없는것["editable"] is False


def test_저장해_둔_주문내역은_다_못_고친다(줄있는주문내역):
    """반입해 둔 줄은 넷 다 체결 완료이고 잔량이 0 입니다."""
    나온것 = order_history(줄있는주문내역)["orders"]

    assert 나온것, "줄이 있어야 이 시험이 뜻을 가집니다."
    우리것 = [줄 for 줄 in 나온것 if 줄.get("sourceCode") == "R"]
    assert 우리것, "우리 매체로 낸 줄이 있어야 합니다."
    assert all(줄["editable"] is False for 줄 in 우리것)


def test_주간과_야간을_줄마다_알려_준다():
    나온것 = order_history(
        {"Occurs1": [{"occurs1_exch_cd": "KRX"}, {"occurs1_exch_cd": "KRX_NDV"}]}
    )["orders"]
    assert [줄["market"] for 줄 in 나온것] == ["domestic-day", "domestic-night"]


def test_주문내역이_비어_올_수_있다():
    for 빈것 in ({"Occurs1": []}, {}, {"Occurs1": "줄이_아님"}):
        assert order_history(빈것)["orders"] == []


def test_주문내역_줄의_사람_항목을_지운다(줄있는주문내역):
    """계좌번호·계좌명·사용자IP·주문ID 는 화면으로 안 나갑니다."""
    원본줄 = 줄있는주문내역["Occurs1"]
    지울것 = {
        str(줄.get(항목) or "").strip()
        for 줄 in 원본줄
        for 항목 in ("occurs1_ac_no", "occurs1_ac_nm", "occurs1_user_ip_addr", "occurs1_ord_id")
    }
    지울것.discard("")
    assert 지울것, "반입본에 지울 값이 있어야 이 시험이 뜻을 가집니다."

    담긴것 = json.dumps(order_history(줄있는주문내역), ensure_ascii=False)
    for 값 in 지울것:
        assert 값 not in 담긴것
    for 이름 in ("ac_no", "ac_nm", "user_ip_addr", "ord_id"):
        assert 이름 not in 담긴것


def test_거래소_시각이_아홉_자리로_옵니다(줄있는주문내역):
    """명세는 여섯 자리라고 적었지만 실제로는 밀리초가 붙어 옵니다."""
    원본줄 = 줄있는주문내역["Occurs1"]
    자릿수 = {len(str(줄.get("occurs1_exch_rcv_tm") or "").strip()) for 줄 in 원본줄}
    assert 자릿수 == {9}, "여섯 자리로 바뀌었으면 이 시험을 다시 보세요."

    첫줄 = order_history(줄있는주문내역)["orders"][0]
    앞여섯 = str(원본줄[0]["occurs1_exch_rcv_tm"])[:6]
    assert 첫줄["receivedTime"] == f"{앞여섯[0:2]}:{앞여섯[2:4]}:{앞여섯[4:6]}"


# ── 실시간 알림과 한 벌인지 ─────────────────────────────────


def test_주문내역과_실시간_알림이_같은_낱말을_쓴다(줄있는주문내역):
    """화면이 목록 위에 알림을 이어 붙이므로 칸 이름이 한 벌이어야 합니다."""
    from backend.realtime import feeds

    조회 = order_history(줄있는주문내역)["orders"][0]
    알림 = feeds.order_event(
        {
            "ord_no": "1",
            "sym": "A7569000",
            "trd_div": "1",
            "ord_sts": "6",
            "pric_cnd": "2",
            "exec_tm": "152122",
            "med_div": "R",
        },
        context="domestic-day",
    )

    for 칸 in ("id", "code", "side", "status", "orderType", "time", "source"):
        assert 칸 in 조회, f"주문내역에 {칸} 이 없습니다"
        assert 칸 in 알림, f"실시간 알림에 {칸} 이 없습니다"

    # 값 체계도 같아야 합니다 — 한쪽만 영문 낱말이면 화면이 못 합칩니다.
    assert 알림["side"] in ("buy", "sell")
    assert 조회["side"] in ("buy", "sell")
    assert 알림["orderType"] == "시장가"


def test_주문_상태와_매매구분_표가_실시간과_같다():
    """명세가 두 곳에 같은 값을 적고 있습니다. 한쪽만 고쳐지면 여기서 깨집니다."""
    from backend.realtime import feeds

    assert ORDER_STATUS == feeds.ORDER_STATUS
    assert ORDER_SIDE == feeds.ORDER_SIDE
    assert ORDER_SOURCE == feeds.ORDER_SOURCE


def test_주문유형_표가_실시간_가격조건과_같다():
    """주문을 낼 때 싣는 코드와 알림이 내는 가격조건이 같은 네 값입니다.

    접수 답이 이 표로 주문 종류를 적으므로, 한쪽만 고쳐지면 같은 주문이 조회와
    접수 답에서 다른 이름으로 섭니다.
    """
    from backend.domestic_futureoption.domestic_account import ORDER_TYPE
    from backend.realtime import feeds

    assert ORDER_TYPE == feeds.PRICE_CONDITION["domestic"]


# ── 접수 답이 미체결 표 한 줄인지 ────────────────────────────


def _접수답(**덮어쓰기):
    from datetime import datetime

    from backend.domestic_futureoption.domestic_account import order_reply
    from backend.sessions.hours import KST

    물음 = {
        "order_id": "5959762237",
        "kind": "new",
        "environment": "paper",
        "code": "A7569000",
        "side": "buy",
        "quantity": 2,
        "context": "domestic-day",
        "now": datetime(2026, 9, 17, 10, 4, 56, tzinfo=KST),
        "order_type_code": "1",
        "fill_condition_code": "1",
        "price": "405.25",
    }
    물음.update(덮어쓰기)
    return order_reply(**물음)


def test_접수_답의_칸_이름이_주문내역_줄과_한_벌이다(줄있는주문내역):
    """화면이 접수 답을 목록 위에 그대로 얹습니다 — 이름이 갈리면 못 얹습니다."""
    조회 = order_history(줄있는주문내역)["orders"][0]
    접수 = _접수답()

    for 칸 in ("id", "code", "side", "status", "orderType", "quantity", "remaining", "date"):
        assert 칸 in 조회, f"주문내역에 {칸} 이 없습니다"
        assert 칸 in 접수, f"접수 답에 {칸} 이 없습니다"

    # 값 체계도 같아야 합니다 — 한쪽만 영문 낱말이면 화면이 못 합칩니다.
    assert 접수["side"] in ("buy", "sell")
    assert 접수["status"] in ORDER_STATUS.values()
    assert 접수["orderType"] == "지정가"
    assert 접수["fillCondition"] == "FAS"

    # 화면이 이미 아는 이름 말고 새로 늘어나는 것은 넷뿐입니다. 이 자리가 늘면
    # 화면은 접수 답 전용 갈래를 따로 두어야 합니다.
    from backend.realtime import feeds

    알림 = feeds.order_event(
        {
            "ord_no": "1",
            "org_ord_no": "2",
            "sym": "A7569000",
            "ord_sts": "1",
            "trd_div": "1",
            "pric_cnd": "1",
            "med_div": "R",
            "ord_qty": "2",
            "exec_qty": "0",
            "rem_ord_qty": "2",
            "cxl_qty": "0",
            "ord_pric": "405.25",
            "rcv_tm": "100456",
            "ord_dt": "20260917",
        },
        context="domestic-day",
    )
    assert set(접수) - set(조회) - set(알림) == {
        "accepted",
        "acceptedAt",
        "environment",
        "context",
    }


def test_접수_답의_시각은_우리_시계다():
    """응답에 접수 시각 칸이 없어 한국시간으로 우리가 적습니다."""
    접수 = _접수답()

    assert 접수["acceptedAt"] == "2026-09-17T10:04:56+09:00"
    # 화면이 줄에 그리는 시각은 `time` 하나입니다 — 조회 줄·알림과 같은 이름.
    assert (접수["date"], 접수["time"]) == ("2026-09-17", "10:04:56")
    assert "receivedTime" not in 접수, "화면이 안 읽는 이름을 늘리지 않습니다."


def test_취소_접수는_상태코드_없이_낱말만_낸다():
    """`ORDER_STATUS` 에 짝이 되는 코드가 없습니다 — 까닭은 `CANCELLED_STATUS` 에."""
    from backend.domestic_futureoption.domestic_account import CANCELLED_STATUS

    취소 = _접수답(kind="cancel", order_type_code="", fill_condition_code="", price="")

    assert 취소["status"] == CANCELLED_STATUS
    assert CANCELLED_STATUS not in ORDER_STATUS.values()
    assert "statusCode" not in 취소
    assert (취소["remaining"], 취소["editable"]) == (0, False)


def test_체결_안_된_시각은_없음이다():
    """0 으로 채워진 시각을 그대로 두면 화면에 「00:00:00 에 체결」이 섭니다."""
    한줄 = order_history(
        {"Occurs1": [{"occurs1_exch_exec_tm": "000000000", "occurs1_exch_rcv_tm": "152122966"}]}
    )["orders"][0]

    assert "fillTime" not in 한줄
    assert 한줄["receivedTime"] == "15:21:22"
    # 화면이 쓰는 시각은 체결 전이면 접수시각입니다 — 실시간과 같은 규칙.
    assert 한줄["time"] == "15:21:22"


def test_화면이_쓰는_시각은_체결됐으면_체결시각(줄있는주문내역):
    """실시간 알림과 같은 규칙 — 두 경로가 갈리면 화면이 시각을 다르게 적습니다."""
    첫줄 = order_history(줄있는주문내역)["orders"][0]
    assert 첫줄["time"] == 첫줄["fillTime"]
    # 자세한 시각 둘도 그대로 남습니다.
    assert "receivedTime" in 첫줄


def test_매체구분을_이름으로도_낸다():
    우리것 = order_history({"Occurs1": [{"occurs1_med_div": "R"}]})["orders"][0]
    남의것 = order_history({"Occurs1": [{"occurs1_med_div": "H"}]})["orders"][0]

    assert 우리것["source"] == "REST API"
    assert 남의것["source"] == "HTS"
    assert 남의것["sourceCode"] == "H"


def test_모르는_매체구분은_원문만_남긴다():
    한줄 = order_history({"Occurs1": [{"occurs1_med_div": "Q"}]})["orders"][0]
    assert 한줄["sourceCode"] == "Q"
    assert "source" not in 한줄


# ── 주문 오류 ───────────────────────────────────────────────
#
# **공개 저장본이 없습니다.** 실전 기록 셋은 저장소에 안 올리는 자리에 있고
# 그마저 줄이 0 입니다. 그래서 여기 시험은 전부 만들어 낸 응답입니다 —
# 반입본으로 확인한 다른 단계와 다르므로, 실물이 오면 다시 봐야 합니다.


def 오류줄(**덮어쓰기):
    한줄 = {
        "occurs1_rcv_tm": "152122966",
        "occurs1_ac_no": "FAKE-AC-000000",
        "occurs1_ac_nm": "FAKE-AC-NAME",
        "occurs1_sym": "A7569000",
        "occurs1_sym_nm": "미국달러 F 202609",
        "occurs1_msg_cd": "40015",
        "occurs1_msg": "주문가능수량을 초과했습니다.",
        "occurs1_org_ord_no": "",
        "occurs1_ord_form_cd": "1",
        "occurs1_ord_form_nm": "일반주문",
        "occurs1_ord_qty": "00000000000005.000000000",
        "occurs1_ord_pric": "0",
        "occurs1_trd_div_cd": "1",
        "occurs1_ord_tp_cd": "2",
        "occurs1_ord_tp_nm": "시장가",
        "occurs1_ord_div_cd": "1",
        "occurs1_exec_cnd_cd": "1",
        "occurs1_med_div": "R",
        "occurs1_med_div_nm": "RESTApi",
    }
    한줄.update(덮어쓰기)
    return 한줄


def 오류응답(*줄, **덮어쓰기):
    답 = {
        "data_tot_cnt": "00000000003",
        "nxt_data_yn": "N",
        "nxt_key": "",
        "nrec": f"{len(줄):04d}",
        "Occurs1": list(줄),
    }
    답.update(덮어쓰기)
    return 답


def test_주문_오류가_화면_모양으로_나온다():
    한줄 = order_errors(오류응답(오류줄()))["errors"][0]

    assert 한줄["code"] == "A7569000"
    assert 한줄["name"] == "미국달러 F 202609"
    assert 한줄["message"] == "주문가능수량을 초과했습니다."
    assert 한줄["messageCode"] == "40015"
    assert 한줄["time"] == "15:21:22"
    assert 한줄["quantity"] == 5


def test_응답에_없는_열쇠와_시장은_만들지_않는다():
    """지어낸 값은 나중에 진짜와 구분되지 않습니다."""
    한줄 = order_errors(오류응답(오류줄()))["errors"][0]

    assert "id" not in 한줄
    assert "market" not in 한줄


def test_신규_주문_거부는_원주문번호가_비어_온다():
    한줄 = order_errors(오류응답(오류줄()))["errors"][0]
    assert "originalOrderNo" not in 한줄

    정정 = order_errors(오류응답(오류줄(occurs1_org_ord_no="5959762237")))["errors"][0]
    assert 정정["originalOrderNo"] == "5959762237"


def test_주문유형은_주문내역과_다른_체계다():
    """주문내역은 가격조건 1~4, 여기는 1·2·7 입니다."""
    from backend.domestic_futureoption.domestic_account import ERROR_ORDER_TYPE

    from backend.realtime import feeds

    assert ERROR_ORDER_TYPE["7"] == "STOP주문"
    # 주문 종류를 코드로 말하는 다른 자리(실시간 알림의 가격조건)에는 7 이
    # 없고, 같은 `2` 도 뜻이 겹칠 뿐 같은 표가 아닙니다.
    assert "7" not in feeds.PRICE_CONDITION["domestic"]
    assert ERROR_ORDER_TYPE != feeds.PRICE_CONDITION["domestic"]


def test_이름_칸이_있으면_그것을_쓰고_없으면_표에서_찾는다():
    있음 = order_errors(오류응답(오류줄(occurs1_ord_tp_nm="시장가")))["errors"][0]
    없음 = order_errors(오류응답(오류줄(occurs1_ord_tp_nm="")))["errors"][0]

    assert 있음["orderType"] == "시장가"
    assert 없음["orderType"] == "시장가"
    assert 없음["orderTypeCode"] == "2"


def test_STOP_은_두_칸에_나뉘어_오고_합치지_않는다():
    한줄 = order_errors(
        오류응답(오류줄(occurs1_ord_form_cd="2", occurs1_ord_form_nm="STOP주문", occurs1_ord_tp_cd="7", occurs1_ord_tp_nm="STOP주문"))
    )["errors"][0]

    assert 한줄["orderForm"] == "STOP주문"
    assert 한줄["orderType"] == "STOP주문"
    assert 한줄["orderFormCode"] == "2"
    assert 한줄["orderTypeCode"] == "7"


def test_오류_줄의_시장가_주문가격도_없음이다():
    한줄 = order_errors(오류응답(오류줄()))["errors"][0]
    assert "price" not in 한줄


def test_이어_받기_항목이_다른_조회와_다르다():
    """전체 건수와 다음 여부가 더 옵니다."""
    답 = order_errors(오류응답(오류줄(), data_tot_cnt="00000000012", nxt_data_yn="Y", nxt_key="이어서"))

    assert 답["total"] == 12
    assert 답["hasMore"] is True
    assert 답["nextKey"] == "이어서"

    없음 = order_errors(오류응답(오류줄()))
    assert 없음["hasMore"] is False


def test_주문_오류가_비어_올_수_있다():
    for 빈것 in ({"Occurs1": []}, {}, {"Occurs1": "줄이_아님"}):
        assert order_errors(빈것)["errors"] == []


def test_주문_오류_줄의_계좌번호와_계좌명을_지운다():
    응답 = 오류응답(오류줄())
    계좌값 = {응답["Occurs1"][0]["occurs1_ac_no"], 응답["Occurs1"][0]["occurs1_ac_nm"]}
    assert all(계좌값), "지울 것이 있어야 이 시험이 뜻을 가집니다."

    담긴것 = json.dumps(order_errors(응답), ensure_ascii=False)
    for 값 in 계좌값:
        assert 값 not in 담긴것
    assert "ac_no" not in 담긴것
    assert "ac_nm" not in 담긴것


# ── 주문가능수량 ────────────────────────────────────────────
#
# 저장소에 이 조회의 저장본이 **한 건도 없습니다**(공개 0건). 아래는 명세의
# 네 칸으로 만들어 낸 응답이고, 시험이 보는 것은 값이 아니라 모양입니다.


def 가능수량응답(**덮어쓰기):
    답 = {
        "ord_psb_qty": "3",
        "cls_psb_qty": "2",
        "tot_psb_qty": "5",
        "ord_psb_amt": "1234.5",
    }
    답.update(덮어쓰기)
    return 답


def test_주문가능수량이_화면_모양으로_나온다():
    답 = orderable_quantity(가능수량응답(), code="A7569000", side="buy")

    assert 답["code"] == "A7569000"
    assert 답["market"] == "domestic"
    assert 답["side"] == "buy"
    assert 답["quantity"] == 5
    assert 답["newQuantity"] == 3
    assert 답["closeQuantity"] == 2
    assert 답["amount"] == 1234.5


def test_화면_한_줄에_쓰는_값은_총가능수량이다():
    """이름만 보면 「주문가능수량」이 그 값 같지만 그것은 신규분입니다."""
    답 = orderable_quantity(가능수량응답(), code="A7569000", side="sell")

    assert 답["quantity"] == 5
    assert 답["quantity"] != 답["newQuantity"]


def test_없는_칸은_지어내지_않는다():
    답 = orderable_quantity({"ord_psb_qty": "3"}, code="A7569000", side="buy")

    assert 답["newQuantity"] == 3
    for 없어야할것 in ("quantity", "closeQuantity", "amount"):
        assert 없어야할것 not in 답


def test_매매구분_표는_주문내역_표를_뒤집은_것이다():
    """한쪽만 고쳐지면 조회와 주문이 서로 다른 방향을 가리킵니다."""
    assert SIDE_CODE == {"buy": "1", "sell": "2"}
    for 코드, 낱말 in ORDER_SIDE.items():
        assert SIDE_CODE[낱말] == 코드


def test_신규_줄이_원주문_칸에_자기_번호를_실어도_원주문번호는_없다():
    같은번호 = {"occurs1_ord_no": "5959762237", "occurs1_org_ord_no": "5959762237"}
    정정 = {"occurs1_ord_no": "5959762238", "occurs1_org_ord_no": "5959762237"}

    줄 = order_history({"Occurs1": [같은번호, 정정]})["orders"]

    assert 줄[0].get("originalOrderNo") is None
    assert 줄[1]["originalOrderNo"] == "5959762237"


def test_주문_오류_줄도_자기_번호와_같은_원주문은_없다():
    한줄 = order_errors(
        오류응답(오류줄(occurs1_ord_no="5959762237", occurs1_org_ord_no="5959762237"))
    )["errors"][0]
    assert 한줄.get("originalOrderNo") is None
