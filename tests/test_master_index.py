"""화면이 받아 가는 색인.

여기서 붙잡아 두는 성질은 셋입니다.

1. 국내는 같은 종목코드가 주간·야간 두 줄로 오는데, 화면에는 **한 종목**으로 나갑니다
2. 세션마다 달라지는 컬럼(`mrkt_tp` 포함)은 **안 나갑니다** — 접으면 어느 값이었는지
   사라져서, 실으면 값이 조용히 틀립니다
3. 품목은 마스터에 없어서 접어 만듭니다. 이름도 종목명에서 잘라 만들고, **원문은
   그대로 남습니다**
"""
from collections import Counter
from datetime import date

import pytest

from backend.master.master_files import MASTER_FILES_BY_NAME
from backend.master.master_index import NIGHT_SESSION, _code_field, build_index
from backend.master.master_store import load_all, save_master
from tests.fixtures.master import fixture_text

_MASTERS = (
    "fut_opt",
    "stk_fut_opt",
    "idx_fut_opt",
    "cme_fut",
    "cme_opt",
    "etc_fut",
    "etc_opt",
    "opra_opt",
    "lme_fut",
)


def _place(tmp_path, names=_MASTERS):
    """조각을 날짜 폴더에 마스터인 것처럼 놓습니다."""
    for name in names:
        save_master(
            MASTER_FILES_BY_NAME[name],
            fixture_text(name).encode("utf-8"),
            stamp="20260902",
            base_dir=tmp_path,
        )


# 잔존일을 세는 기준. 조각을 받아 둔 날이라 시험이 날짜와 함께 늙지 않습니다.
오늘 = date(2026, 9, 2)


def _build(tmp_path, today=오늘):
    """조각 아홉 개를 놓고 색인을 만듭니다."""
    _place(tmp_path)
    return build_index(load_all(tmp_path), today=today)


def _index(tmp_path, today=오늘):
    return _build(tmp_path, today).payload


def _slots(index, market="overseas"):
    """만기 슬롯을 `(품목, 만기일 또는 만기월)` 로 찾아 쓰게."""
    return {
        (하나["product_code"], 하나["expiry_date"] or 하나["expiry"]): 하나
        for 하나 in index["option_expiries"]
        if 하나["market"] == market
    }


def _contracts_by_code(index):
    return {
        c.get("series") or c["code"]: c for c in index["contracts"]
    }


def test_주간과_야간이_한_종목으로_접힌다(tmp_path):
    """`A0169000` 은 조각 안에 주간 한 줄, 야간 한 줄로 들어 있습니다."""
    index = _index(tmp_path)

    kospi_futures = [c for c in index["contracts"] if c.get("series") == "A0169000"]

    assert len(kospi_futures) == 1
    assert index["folding_conflicts"] == []


def test_세션마다_달라지는_컬럼은_안_나간다(tmp_path):
    """`mrkt_tp` 가 여기 들어 있는 것이 중요합니다.

    이름은 시장 구분처럼 생겼지만 같은 상품이 주간이면 6, 야간이면 4 로 옵니다.
    접고 나면 어느 값이었는지 알 수 없으므로 아예 안 싣습니다. 상품 분류가 필요하면
    `mrkt_code` 를 쓰세요 — 그쪽은 두 줄에서 같습니다.
    """
    index = _index(tmp_path)
    domestic_rows = [c for c in index["contracts"] if c["market"] == "domestic"]

    assert domestic_rows
    for contract in domestic_rows:
        assert "mrkt_tp" not in contract
        assert "cme_tp" not in contract
        assert "kospi_key" not in contract
        assert "upper_p_lv1" not in contract
        assert "lower_p_lv1" not in contract
        assert "dynmc_up_p" not in contract
        assert "dynmc_yn" not in contract
        # 두 줄에서 같은 컬럼은 그대로 나갑니다.
        assert contract["mrkt_code"]
        assert contract["exp_ym"]


def test_접다가_값이_어긋나면_그_종목만_빼고_알린다(tmp_path, caplog):
    """어느 줄이 맞는지 알 수 없는데 한쪽을 내보내면 값만 조용히 틀립니다.

    배포 형식이 바뀌어 지금은 같은 컬럼이 갈리기 시작해도 여기서 드러납니다.
    """
    lines = fixture_text("fut_opt").splitlines()
    day = lines[0].split(";")
    night = lines[4].split(";")
    assert day[8] == night[8] == "A0169000"
    # 야간 줄의 거래승수만 바꿉니다. 원래는 두 줄에서 같은 값입니다 —
    # 잔존일수는 세션마다 다른 것이 정상이라 여기 쓸 수 없습니다.
    night[17] = "999"
    lines[4] = ";".join(night)

    save_master(
        MASTER_FILES_BY_NAME["fut_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )
    with caplog.at_level("WARNING", logger="backend.master.master_index"):
        index = build_index(load_all(tmp_path)).payload

    assert index["folding_conflicts"] == [
        {"market": "domestic", "code": "A0169000", "fields": ["ctrt_size"]}
    ]
    assert not [c for c in index["contracts"] if c.get("series") == "A0169000"]
    # 나머지 종목은 그대로 씁니다. 한 종목 때문에 파일을 버리지 않습니다.
    assert [c for c in index["contracts"] if c.get("series") == "D01696CS"]

    # 기록은 **무슨 일이 생겼는지**부터 말해야 합니다. 칸 이름만 적어 두면 읽는
    # 사람이 그 종목이 사라진 것도, 고칠 자리가 이 앱이 아닌 것도 모릅니다.
    (남긴것,) = [
        기록 for 기록 in caplog.records if 기록.name == "backend.master.master_index"
    ]
    글 = 남긴것.getMessage()
    assert "목록·검색·주문에 나오지 않습니다" in 글, "영향을 적어야 합니다."
    assert "둘 다" in 글, "한쪽을 골라 쓴 것이 아니라는 것을 적어야 합니다."
    assert "마스터 자료의 문제" in 글, "앱에서 고칠 수 없다는 것을 적어야 합니다."
    # 물어 오는 사람이 이 줄 하나만 옮겨 적으므로 코드와 칸 이름도 남깁니다.
    assert "A0169000(ctrt_size)" in 글


def test_품목_이름을_종목명에서_잘라_내고_원문은_남긴다(tmp_path):
    """마스터에 품목 이름을 담은 컬럼이 없어서 종목명에서 만듭니다.

    자르는 규칙이 안 맞는 이름이 나와도 원문과 대조하면 바로 보이도록, 원문 종목명은
    그대로 둡니다.
    """
    index = _index(tmp_path)
    kospi = _contracts_by_code(index)["A0169000"]

    assert kospi["product_name"] == "코스피200"
    assert kospi["name_kor"] == "코스피200 F 202609"

    aud = _contracts_by_code(index)["6AU26"]
    assert aud["product_name"] == "호주달러"
    assert aud["name"] == "호주달러 (202609)"


def test_품목은_시장과_함께_센다(tmp_path):
    """같은 품목코드가 국내와 해외에 함께 나타나는 경우가 있습니다."""
    index = _index(tmp_path)

    keys = [(p["market"], p["product_code"]) for p in index["products"]]

    assert len(keys) == len(set(keys))
    assert ("domestic", "KOSPI") in keys
    assert ("overseas", "6A") in keys


def test_스프레드를_선물로_접지_않는다(tmp_path):
    """스프레드는 만기가 둘이라 월물 목록의 「만기 한 값」 칸에 넣을 값이 없습니다.

    목록에서 고른 것이 그대로 주문 대상이 되는 자리라 섞이면 안 됩니다. 다만 어디에
    세울지는 화면이 정할 일이라, 색인은 **원문 구분을 접지 않고 그대로 넘깁니다.**
    """
    index = _index(tmp_path)
    by_code = _contracts_by_code(index)

    assert by_code["D01696CS"]["kind"] == "spread"
    assert by_code["D01696CS"]["fo_tp"] == "C"
    assert by_code["S_6EH27-U26"]["kind"] == "spread"
    assert by_code["S_6EH27-U26"]["type"] == "S"
    assert by_code["A0169000"]["kind"] == "futures"


def test_스프레드는_두_다리를_함께_낸다(tmp_path):
    """스프레드는 만기가 둘이라 「만기 한 값」으로는 화면이 무엇인지 말할 수 없습니다."""
    by_code = _contracts_by_code(_index(tmp_path))

    # 국내는 종목명에서 읽고, 근월의 만기일까지 압니다(`exp_ym`).
    assert by_code["D01696CS"]["legs"] == {
        "near": "202609",
        "far": "202612",
        "nearDate": "20260910",
        "farDate": None,
    }
    # 개별주식 스프레드도 같은 규칙입니다.
    assert by_code["D0A696AS"]["legs"]["near"] == "202609"
    assert by_code["D0A696AS"]["legs"]["far"] == "202610"

    # 해외는 칸 둘(`yymm`·`yymm1`)에서 읽습니다. 날짜는 마스터에 없습니다.
    assert by_code["S_6EH27-U26"]["legs"] == {
        "near": "202609",
        "far": "202703",
        "nearDate": None,
        "farDate": None,
    }

    # 스프레드가 아닌 종목에는 이 칸이 없습니다.
    assert "legs" not in by_code["A0169000"]
    assert "legs" not in by_code["6AU26"]


def test_다리_차례는_마스터가_적은_차례가_아니라_이른_달이다():
    """`yymm`·`kofex_Code` 의 차례는 품목마다 갈립니다 — 까닭은 `_legs` 에."""
    from backend.master.master_index import _legs

    # 해외 실물에 둘 다 있습니다.
    # 첫 다리가 늦은 것 — `S_6EZ26-U26`(yymm 202612 · yymm1 202609).
    assert _legs("202612", "202609")["near"] == "202609"
    # 첫 다리가 이른 것 — `S_TNU26-H27`(yymm 202609 · yymm1 202703).
    assert _legs("202609", "202703")["near"] == "202609"
    # 연도가 바뀌어도 여섯 자리로 견주므로 어긋나지 않습니다.
    assert _legs("202912", "203003") == {
        "near": "202912",
        "far": "203003",
        "nearDate": None,
        "farDate": None,
    }


def test_다리를_못_읽으면_비워_둔다():
    """지어내지 않습니다 — 틀린 만기가 주문 자리에 서는 것보다 빈 편이 낫습니다."""
    from backend.master.master_index import _domestic_legs, _legs

    assert _legs("202609", "") is None
    assert _legs("2609", "2612") is None, "여섯 자리가 아니면 안 씁니다."
    assert _legs(None, None) is None
    # 이름에 `SP YYMM-YYMM` 이 없으면 국내는 읽을 곳이 없습니다.
    assert _domestic_legs({"name_kor": "코스피200 F 202609", "exp_ym": "20260910"}) is None
    # 근월과 다른 달의 만기일은 안 씁니다.
    엇갈림 = _domestic_legs({"name_kor": "코스피200 SP 2609-2612", "exp_ym": "20261211"})
    assert 엇갈림["near"] == "202609" and 엇갈림["nearDate"] is None


def test_모르는_구분은_선물로_뭉뚱그리지_않는다(tmp_path):
    """새 갈래가 생기면 선물 목록에 조용히 섞이는 대신 원문 값으로 드러납니다."""
    lines = fixture_text("fut_opt").splitlines()
    # 0번과 4번이 같은 종목의 주간·야간 줄입니다. 둘 다 바꿔야 접을 때 안 어긋납니다.
    for at in (0, 4):
        row = lines[at].split(";")
        row[1] = "X"
        lines[at] = ";".join(row)

    save_master(
        MASTER_FILES_BY_NAME["fut_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )
    index = build_index(load_all(tmp_path)).payload

    assert _contracts_by_code(index)["A0169000"]["kind"] == "X"
    products = {(p["market"], p["product_code"]): p for p in index["products"]}
    assert products[("domestic", "KOSPI")]["contract_counts"]["X"] == 1
    assert products[("domestic", "KOSPI")]["contract_counts"]["futures"] == 0


def test_품목을_선물이냐_옵션이냐로_나누지_않는다(tmp_path):
    """어느 축으로 나눌지는 화면이 정합니다. 여기서 굳히면 되돌릴 수 없습니다.

    대신 종류별 수를 담아, 화면이 원하는 축을 스스로 만들 수 있게 합니다.
    """
    index = _index(tmp_path)
    products = {(p["market"], p["product_code"]): p for p in index["products"]}

    kospi = products[("domestic", "KOSPI")]
    assert "kind" not in kospi
    assert kospi["contract_counts"] == {"futures": 1, "option": 1, "spread": 1}

    # 스프레드만 있는 품목이 실제로 있습니다. 화면이 스프레드를 빼면 월물 0 이 됩니다.
    euro_spread = products[("overseas", "S_6E")]
    assert euro_spread["contract_counts"] == {"futures": 0, "option": 0, "spread": 1}


def test_해외_옵션은_종목코드에서_콜풋과_행사가를_뽑는다(tmp_path):
    """해외 옵션 레이아웃에는 행사가와 콜/풋 컬럼이 아예 없습니다.

    종목코드에서 뽑되, 원문 컬럼이 아니라는 것이 이름에 드러나도록 `code_` 를 붙입니다.
    체인을 열 때 오는 목록에 실립니다.
    """
    built = _build(tmp_path)

    wti = built.chain(market="overseas", product_code="O_CL", expiry="202701")
    gold = built.chain(market="overseas", product_code="O_GC", expiry="202806")

    assert (wti[0]["code"], wti[0]["code_cp"], wti[0]["code_strike"]) == (
        "O_CLF27-C10.00",
        "C",
        "10.00",
    )
    # 종목코드 뒤가 공백으로 채워져 오는 행도 떼어 낸 뒤라 제대로 풀립니다.
    assert (gold[0]["code"], gold[0]["code_cp"], gold[0]["code_strike"]) == (
        "O_GCZ28-P5245.0",
        "P",
        "5245.0",
    )


def _해외만기(index):
    return {
        (하나["product_code"], 하나["expiry"], 하나["expiry_date"]): 하나["contract_count"]
        for 하나 in index["option_expiries"]
        if 하나["market"] == "overseas"
    }


def test_OPRA_위클리는_같은_달_안에서_날짜로_갈린다(tmp_path):
    """`lastDt` 가 OPRA 옵션에만 옵니다 — 그 덕에 주간 만기를 날로 가릅니다.

    조각의 `O_SPW`(CBOE S&P 500 위클리) 두 줄은 둘 다 202609 인데 최종거래일이
    09-02 와 09-03 로 다릅니다. 달로만 가르면 둘이 한 칸으로 뭉칩니다.
    """
    만기들 = _해외만기(_index(tmp_path))

    assert 만기들[("O_SPW", "202609", "20260902")] == 1
    assert 만기들[("O_SPW", "202609", "20260903")] == 1
    # 월물 품목도 날짜가 옵니다 — 그달 셋째 금요일 하나뿐입니다.
    assert 만기들[("O_NDX", "202609", "20260918")] == 2


def test_최종거래일이_없는_해외_옵션은_달로_남는다(tmp_path):
    """`lastDt` 는 OPRA 파일에만 있는 칸입니다. 다른 파일은 만기년월이 최대입니다."""
    만기들 = _해외만기(_index(tmp_path))

    for 품목 in ("O_CL", "O_GC", "O_HHI"):
        (열쇠,) = [하나 for 하나 in 만기들 if 하나[0] == 품목]
        assert 열쇠[2] is None, 품목

    # 해외 선물에는 애초에 그 칸이 없습니다.
    선물 = _contracts_by_code(_index(tmp_path))["6AU26"]
    assert "expiry_date" not in 선물 and "lastDt" not in 선물


def test_위클리_체인은_날로도_달로도_열린다(tmp_path):
    """체인이 서는 자리는 만기일 하나이지만, 월물을 보는 쪽은 여전히 월로 묻습니다."""
    built = _build(tmp_path)

    하루 = built.chain(market="overseas", product_code="O_SPW", expiry="20260902")
    한달 = built.chain(market="overseas", product_code="O_SPW", expiry="202609")

    assert [줄["code"] for 줄 in 하루] == ["O_SPW1WU26-C10000.0"]
    # 월로 물으면 그달의 주간 만기가 한 덩어리로 옵니다.
    assert len(한달) == 2
    assert {줄["lastDt"] for 줄 in 한달} == {"20260902", "20260903"}


def test_만기_슬롯이_체인을_부를_시리즈_코드를_낸다(tmp_path):
    """**위클리는 슬롯마다 시리즈가 다릅니다.** 화면이 종목코드에서 직접 뜯지 않게 합니다."""
    슬롯 = _slots(_index(tmp_path))

    assert 슬롯[("O_SPW", "20260902")]["series_code"] == "O_SPW1WU26"
    assert 슬롯[("O_SPW", "20260903")]["series_code"] == "O_SPW1RU26"
    # 월물 옵션도 같은 규칙입니다 — 행사가만 뗍니다.
    assert 슬롯[("O_NDX", "20260918")]["series_code"] == "O_NDXU26"
    assert 슬롯[("O_CL", "202701")]["series_code"] == "O_CLF27"


def test_국내_슬롯에는_시리즈_코드가_없다(tmp_path):
    """국내 체인은 품목코드와 만기년월로 부릅니다 — 시리즈 코드를 쓰지 않습니다."""
    슬롯 = _slots(_index(tmp_path), market="domestic")

    assert 슬롯
    assert all(하나["series_code"] is None for 하나 in 슬롯.values())


def test_해외_잔존일은_만기일에서_세고_국내는_마스터_값이다(tmp_path):
    """만기일을 아는 것은 OPRA 옵션뿐입니다. 나머지 해외는 셀 근거가 없습니다."""
    바깥 = _slots(_index(tmp_path))
    안 = _slots(_index(tmp_path), market="domestic")

    # 2026-09-02 기준. **오늘을 세어 넣으므로 그날이 만기면 1** 입니다 — NH 가
    # 국내 마스터에 적어 주는 `rem_cnt` 와 같은 기준입니다.
    assert 바깥[("O_SPW", "20260902")]["days_left"] == 1
    assert 바깥[("O_SPW", "20260903")]["days_left"] == 2
    assert 바깥[("O_NDX", "20260918")]["days_left"] == 17
    # 만기일이 없는 해외 옵션은 셀 수 없습니다. 0 으로 지어내지 않습니다.
    assert 바깥[("O_CL", "202701")]["expiry_date"] is None
    assert 바깥[("O_CL", "202701")]["days_left"] is None
    # 국내는 마스터가 준 잔존일을 그대로 씁니다.
    assert all(하나["days_left"] == 하나["rem_cnt"] for 하나 in 안.values())
    assert any(하나["days_left"] is not None for 하나 in 안.values())


def test_두_시장이_같은_만기를_같은_수로_센다():
    """같은 날 만기가 화면에서 「D-1」과 「D-0」으로 갈리면 안 됩니다."""
    from backend.master.master_index import _days_until

    받은날 = date(2026, 9, 2)
    # 국내 조각의 위클리 하나: 만기 20260903 에 마스터가 적어 준 잔존일이 2 입니다.
    assert _days_until("20260903", 받은날) == 2
    # 만기 당일은 1, 그 이튿날은 0(음수로 안 냅니다).
    assert _days_until("20260902", 받은날) == 1
    assert _days_until("20260901", 받은날) == 0


def test_지난_만기는_음수가_아니라_0_이다(tmp_path):
    """음수로 내면 화면이 「D+3」 같은 말을 만듭니다."""
    슬롯 = _slots(_index(tmp_path, today=date(2026, 9, 20)))

    assert 슬롯[("O_SPW", "20260902")]["days_left"] == 0
    assert 슬롯[("O_NDX", "20260918")]["days_left"] == 0


def test_한_슬롯에_시리즈가_둘이면_비우고_알린다(tmp_path, caplog):
    """어느 코드로 체인을 불러야 할지 알 수 없습니다. 하나를 고르면 반은 틀립니다."""
    lines = fixture_text("opra_opt").splitlines()
    # 같은 품목·같은 만기일인데 월물 글자만 다른 줄을 만듭니다.
    바꾼줄 = lines[1].split(";")
    바꾼줄[0] = 바꾼줄[1] = "O_NDXV26-C11000.0"
    lines[1] = ";".join(바꾼줄)
    save_master(
        MASTER_FILES_BY_NAME["opra_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )
    _place(tmp_path, [name for name in _MASTERS if name != "opra_opt"])

    with caplog.at_level("WARNING", logger="backend.master.master_index"):
        슬롯 = _slots(build_index(load_all(tmp_path), today=오늘).payload)

    assert 슬롯[("O_NDX", "20260918")]["series_code"] is None
    assert 슬롯[("O_NDX", "20260918")]["contract_count"] == 2, "줄은 그대로 씁니다."
    남긴것 = [기록.getMessage() for 기록 in caplog.records if "시리즈가 둘 이상" in 기록.getMessage()]
    assert 남긴것 and "O_NDXU26" in 남긴것[0] and "O_NDXV26" in 남긴것[0]


def test_날짜가_아닌_최종거래일은_안_쓴다(tmp_path):
    """있을 수 없는 날을 만기로 쓰면 그 줄만 엉뚱한 자리에 섭니다. 달로 묶습니다."""
    lines = fixture_text("opra_opt").splitlines()
    나쁜줄 = lines[2].split(";")
    assert 나쁜줄[12] == "O_SPW"
    나쁜줄[18] = "20261345"
    lines[2] = ";".join(나쁜줄)

    save_master(
        MASTER_FILES_BY_NAME["opra_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )
    _place(tmp_path, [name for name in _MASTERS if name != "opra_opt"])
    만기들 = _해외만기(build_index(load_all(tmp_path)).payload)

    assert ("O_SPW", "202609", None) in 만기들
    assert ("O_SPW", "202609", "20261345") not in 만기들


def test_국내_체인이_행사가를_한_번씩만_돌려준다(tmp_path):
    """국내 옵션은 주간·야간 두 줄로 옵니다.

    체인이 접기를 안 거치면 같은 행사가가 두 줄씩 서고, 색인에서 없앤 모호함이
    체인에만 남습니다. 접기는 색인과 체인 어느 쪽으로 나가든 똑같이 겁니다.
    """
    built = _build(tmp_path)

    chain = built.chain(market="domestic", product_code="KOSPI", expiry="202609")
    codes = [row["series"] for row in chain]

    assert codes == ["B0169335"]
    assert len(codes) == len(set(codes))


def test_체인도_세션_컬럼을_싣지_않는다(tmp_path):
    """체인도 배송본입니다. 색인에서 뺀 컬럼이 여기로 새어 나가면 안 됩니다."""
    built = _build(tmp_path)

    chain = built.chain(market="domestic", product_code="KOSPI", expiry="202609")

    assert chain
    for row in chain:
        assert "mrkt_tp" not in row
        assert "cme_tp" not in row
        assert "kospi_key" not in row
        assert "upper_p_lv1" not in row


def test_체인이_색인과_같은_종목을_돌려준다(tmp_path):
    """어느 줄을 남길지는 색인을 만들 때 한 번만 정합니다.

    체인이 같은 판단을 다시 하면, 두 곳의 규칙이 갈라지는 날 화면이 한 번은 하나로
    한 번은 둘로 보게 됩니다.
    """
    built = _build(tmp_path)
    # **열쇠는 만기일이 있으면 만기일입니다.** 만기년월로 접으면 같은 달의 주간
    # 만기가 한 칸으로 뭉쳐 이 시험이 뜻을 잃습니다.
    expiries = {
        (e["market"], e["product_code"], str(e["expiry_date"] or e["expiry"])): e["contract_count"]
        for e in built.payload["option_expiries"]
    }
    assert len(expiries) == len(built.payload["option_expiries"]), "열쇠가 겹치면 안 됩니다."

    for key, count in expiries.items():
        market, product_code, expiry = key
        assert len(built.chain(
            market=market, product_code=product_code, expiry=expiry
        )) == count

    # 만기년월로 물으면 그달에 걸린 만기를 **모두** 모아 줍니다.
    달마다 = Counter()
    for (market, product_code, expiry), count in expiries.items():
        달마다[(market, product_code, expiry[:6])] += count
    for (market, product_code, month), count in 달마다.items():
        assert len(built.chain(
            market=market, product_code=product_code, expiry=month
        )) == count, (product_code, month)


def test_접기에서_빠진_종목은_체인에도_없다(tmp_path):
    """색인에서 뺀 종목이 체인으로 새어 나가면 뺀 의미가 없습니다."""
    lines = fixture_text("fut_opt").splitlines()
    # 2번 줄이 코스피200 콜옵션입니다. 야간 짝을 만들되 거래승수만 어긋나게 둡니다.
    day = lines[2].split(";")
    night = list(day)
    night[5] = "night"
    night[17] = "999"
    lines.append(";".join(night))

    save_master(
        MASTER_FILES_BY_NAME["fut_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )
    built = build_index(load_all(tmp_path))

    assert [c["code"] for c in built.payload["folding_conflicts"]] == ["B0169335"]
    assert built.chain(market="domestic", product_code="KOSPI", expiry="202609") == []
    assert not [
        row for row in built.payload["domestic_option_index"]["rows"]
        if row[0] == "B0169335"
    ]
    # 만기월 목록의 수도 같이 줄어듭니다.
    assert not [
        e for e in built.payload["option_expiries"]
        if e["product_code"] == "KOSPI" and e["contract_count"]
    ]


def test_국내_옵션은_색인에_신원만_담긴다(tmp_path):
    """행사가·종목명·상한가는 안 담습니다.

    「이 코드가 어느 품목의 어느 달 콜/풋인가」에만 답하는 표입니다. 국내 옵션 코드는
    위클리가 주차 표기라 만기월이 코드에서 안 풀려서, 이 표가 없으면 화면이 다른
    달을 조용히 답합니다.
    """
    index = _index(tmp_path)
    table = index["domestic_option_index"]

    assert table["fields"] == ["series", "product_code", "expiry_date", "opt_tp"]

    row = {row[0]: row for row in table["rows"]}
    # 코스피위클리 — 종목코드(`B09FC945`)로는 만기가 안 풀리는 종목입니다.
    # **만기는 8자리입니다.** 위클리는 한 달에 만기가 여럿이라 월로 적으면 서로
    # 다른 종목이 같은 신원을 갖습니다.
    assert row["B09FC945"] == ["B09FC945", "WKI", "20260903", "3"]
    assert row["B0169335"] == ["B0169335", "KOSPI", "20260910", "3"]


def test_옵션_행사가_행은_색인에_안_담긴다(tmp_path):
    """옵션이 14만 행이라 전부 담으면 화면이 들고 있기 무겁습니다."""
    index = _index(tmp_path)

    assert all(c["kind"] in ("futures", "spread") for c in index["contracts"])
    # 대신 어느 품목에 어느 만기월이 있는지는 담깁니다.
    expiries = {(e["market"], e["product_code"], e["expiry"]) for e in index["option_expiries"]}
    assert ("overseas", "O_CL", "202701") in expiries
    assert ("domestic", "KOSPI", "202609") in expiries


def test_품목_안에서_갈리는_값은_품목에_안_담는다(tmp_path):
    """「품목의 성질」처럼 보여도 종목마다 다른 값이 있습니다.

    거래승수는 권리조정을 거친 종목이 섞이면 한 품목 안에서 갈립니다. 미리 고르지
    않고 매번 재서, 갈리면 그 품목에서만 뺍니다. 종목 행에는 늘 남아 있습니다.
    """
    index = _index(tmp_path)
    products = {(p["market"], p["product_code"]): p for p in index["products"]}
    by_code = _contracts_by_code(index)

    # 조각 안에 승수 10 짜리와 25 짜리가 한 품목으로 들어 있지 않으므로,
    # 값이 같은 품목에는 그대로 실립니다.
    assert products[("domestic", "S0A")]["ctrt_size"] == "10"
    assert by_code["A1M69000"]["ctrt_size"] == "25"
    assert by_code["A0A69000"]["ctrt_size"] == "10"


def test_품목_안에서_값이_갈리면_그_품목에서만_뺀다(tmp_path):
    lines = fixture_text("stk_fut_opt").splitlines()
    futures_row = lines[0].split(";")
    spread_row = lines[2].split(";")
    assert futures_row[3] == spread_row[3] == "S0A"
    # 같은 품목의 두 종목이 서로 다른 거래승수를 갖게 만듭니다.
    spread_row[17] = "25"
    lines[2] = ";".join(spread_row)

    save_master(
        MASTER_FILES_BY_NAME["stk_fut_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )
    index = build_index(load_all(tmp_path)).payload
    products = {(p["market"], p["product_code"]): p for p in index["products"]}

    assert "ctrt_size" not in products[("domestic", "S0A")]
    # 갈리지 않은 값은 그대로 남습니다.
    assert products[("domestic", "S0A")]["mrkt_code"] == "01"


def test_받기만_하는_파일은_색인에_안_들어간다(tmp_path):
    """LME 는 받아 두기만 하고 파싱하지 않습니다."""
    index = _index(tmp_path)

    assert not [c for c in index["contracts"] if c.get("code", "").startswith("L3")]


def test_위클리는_만기일까지_갈라_담긴다(tmp_path):
    """위클리는 **한 달에 만기가 여럿**이라 만기월로 접으면 한 칸으로 뭉칩니다.

    뭉치면 화면의 만기 선택에 「26년 9월물」 하나만 서서, 그 달의 주간 만기를
    고를 길이 없어집니다. 그래서 만기를 가르는 것은 날짜입니다.
    """
    index = _index(tmp_path)
    found = {
        e["product_code"]: e
        for e in index["option_expiries"]
        if e["market"] == "domestic"
    }

    # (만기일, 잔존일수) — 이 판본의 위클리 넷입니다.
    assert (found["WKI"]["expiry_date"], found["WKI"]["rem_cnt"]) == ("20260903", 2)
    assert (found["WKM"]["expiry_date"], found["WKM"]["rem_cnt"]) == ("20260907", 6)
    assert (found["WQI"]["expiry_date"], found["WQI"]["rem_cnt"]) == ("20260903", 2)
    assert (found["WQM"]["expiry_date"], found["WQM"]["rem_cnt"]) == ("20260907", 6)

    # 만기월도 함께 옵니다 — 월로 묻는 쪽이 아직 있습니다.
    assert found["WKI"]["expiry"] == "202609"


def test_월물_품목은_만기가_그대로다(tmp_path):
    """날짜로 갈라도 **한 달에 만기가 하나인 품목은 달라지지 않습니다.**

    위클리를 가르려고 넣은 규칙이 월물 품목의 만기를 쪼개면, 고치려던 것보다 넓은
    자리가 바뀝니다.
    """
    index = _index(tmp_path)
    kospi = [
        e
        for e in index["option_expiries"]
        if e["market"] == "domestic" and e["product_code"] == "KOSPI"
    ]

    assert [e["expiry"] for e in kospi] == ["202609"]
    assert kospi[0]["expiry_date"] == "20260910"
    assert kospi[0]["rem_cnt"] == 9

    units = {p["product_code"]: p["expiry_unit"] for p in index["products"]}
    assert units["KOSPI"] == "month"


def test_체인은_만기일로도_만기월로도_받는다(tmp_path):
    """체인이 서는 자리는 만기일 하나인데, 월물 품목을 보는 쪽은 여전히 월로 묻습니다.

    6자리로 물으면 그 달에 걸린 만기를 모두 모아 줍니다 — 위클리 품목을 월로
    물으면 그 달의 주간 만기가 한 덩어리로 옵니다.
    """
    built = _build(tmp_path)

    by_date = built.chain(market="domestic", product_code="WKI", expiry="20260903")
    by_month = built.chain(market="domestic", product_code="WKI", expiry="202609")

    assert by_date
    assert [c["series"] for c in by_date] == [c["series"] for c in by_month]

    # 해외는 마스터가 만기년월까지만 주므로 6자리가 곧 그 시장의 만기입니다.
    assert built.chain(market="overseas", product_code="O_CL", expiry="202701")


def test_날_단위_품목은_이_판본에서_정확히_넷이다(tmp_path):
    """**이름 판정을 지키는 시험입니다.**

    만기 단위는 마스터에 표식이 없어 품목명의 「위클리」로 가릅니다. 품목명은
    배포하는 쪽이 짓는 문자열이라 다음 판본에서 표기가 바뀔 수 있는데, 그러면
    **예외도 오류도 없이 전부 `month` 로 떨어집니다** — 화면은 멀쩡하고 라벨만
    조용히 「26년 9월물」로 돌아갑니다. 위클리를 가르려고 한 일이 통째로 사라지는데
    아무도 모릅니다.

    그래서 「몇 개가 걸리는가」를 못 박아 둡니다. 이름이 바뀌면 이 시험이 크게
    깨지고, 깨진 자리가 곧 고칠 자리입니다.
    """
    index = _index(tmp_path)

    day = {
        p["product_code"]
        for p in index["products"]
        if p["market"] == "domestic" and p["expiry_unit"] == "day"
    }
    assert day == {"WKI", "WKM", "WQI", "WQM"}

    # 해외는 날짜를 못 받아 이름에 위클리가 들어도 달 단위입니다.
    assert not [
        p for p in index["products"] if p["market"] == "overseas" and p["expiry_unit"] == "day"
    ]


# ── 잔존일수는 세션마다 다릅니다 ─────────────────────────


def _fut_opt(tmp_path, lines):
    save_master(
        MASTER_FILES_BY_NAME["fut_opt"],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20260902",
        base_dir=tmp_path,
    )


def test_잔존일수만_다른_주간_야간은_한_종목이다(tmp_path):
    """야간 줄은 **다음 거래일의 것**이라 잔존일수가 하루 적게 옵니다.

    이것을 어긋난 것으로 세면 주간·야간이 함께 오는 국내 종목이 통째로
    색인에서 빠집니다 — 코스피200 선물이 목록에 안 서는 상태가 됩니다.
    """
    lines = fixture_text("fut_opt").splitlines()
    day = lines[0].split(";")
    night = lines[4].split(";")
    assert day[8] == night[8] == "A0169000"
    day[18] = "80"
    night[18] = "79"
    lines[0] = ";".join(day)
    lines[4] = ";".join(night)
    _fut_opt(tmp_path, lines)

    index = build_index(load_all(tmp_path)).payload

    assert index["folding_conflicts"] == []
    (선것,) = [one for one in index["contracts"] if one.get("series") == "A0169000"]
    assert 선것["rem_cnt"] == "80", "주간 줄의 값입니다."


def test_야간_줄이_먼저_와도_주간_값을_쓴다(tmp_path):
    """파일 차례에 기대면 차례가 바뀌는 날 잔존일수만 조용히 틀립니다.

    **답하는 자리가 셋입니다** — 색인이 내는 줄, `locate`, 체인. 색인만 고치면
    `locate` 는 여전히 야간 줄을 내고, 그 값으로 만기 당일 판정이 하루 어긋납니다.
    """
    lines = fixture_text("fut_opt").splitlines()
    day = lines[0].split(";")
    night = lines[4].split(";")
    day[18] = "80"
    night[18] = "79"
    # 야간 줄을 앞에 둡니다.
    lines[0] = ";".join(night)
    lines[4] = ";".join(day)
    _fut_opt(tmp_path, lines)

    built = build_index(load_all(tmp_path))

    assert built.payload["folding_conflicts"] == []
    (선것,) = [
        one for one in built.payload["contracts"] if one.get("series") == "A0169000"
    ]
    assert 선것["rem_cnt"] == "80", "색인이 내는 줄"
    assert built.locate("domestic", "A0169000")["rem_cnt"] == "80", "locate"


def test_잔존일수_말고_갈리면_여전히_뺀다(tmp_path):
    """잔존일수만 예외입니다 — 갈리면 안 되는 칸은 그대로 잡습니다."""
    lines = fixture_text("fut_opt").splitlines()
    night = lines[4].split(";")
    night[17] = "999"
    night[18] = "79"
    lines[4] = ";".join(night)
    _fut_opt(tmp_path, lines)

    index = build_index(load_all(tmp_path)).payload

    assert index["folding_conflicts"] == [
        {"market": "domestic", "code": "A0169000", "fields": ["ctrt_size"]}
    ]


def test_옵션도_잔존일수만_다르면_체인에_선다(tmp_path):
    """선물만 고치면 옵션 체인은 여전히 비어 있습니다."""
    lines = fixture_text("fut_opt").splitlines()
    day = lines[2].split(";")
    night = list(day)
    night[5] = "night"
    day[18] = "80"
    night[18] = "79"
    lines[2] = ";".join(day)
    lines.append(";".join(night))
    _fut_opt(tmp_path, lines)

    built = build_index(load_all(tmp_path))

    assert built.payload["folding_conflicts"] == []
    assert built.chain(market="domestic", product_code="KOSPI", expiry="202609")
    (칸,) = [
        one
        for one in built.payload["option_expiries"]
        if one["product_code"] == "KOSPI" and one["contract_count"]
    ]
    assert 칸["rem_cnt"] == 80, "만기 칸의 잔존일수도 주간 줄의 값입니다."


def test_옵션도_야간이_먼저_오면_셋_다_주간_값이다(tmp_path):
    """체인은 **줄의 위치**를 들고 있어, 값만 바꾸면 체인은 야간 줄을 냅니다."""
    lines = fixture_text("fut_opt").splitlines()
    day = lines[2].split(";")
    night = list(day)
    night[5] = "night"
    day[18] = "80"
    night[18] = "79"
    # 야간 줄을 원래 자리에 두고 주간 줄을 뒤에 붙입니다.
    lines[2] = ";".join(night)
    lines.append(";".join(day))
    _fut_opt(tmp_path, lines)

    built = build_index(load_all(tmp_path))

    assert built.payload["folding_conflicts"] == []
    (칸,) = [
        one
        for one in built.payload["option_expiries"]
        if one["product_code"] == "KOSPI" and one["contract_count"]
    ]
    assert 칸["rem_cnt"] == 80, "만기 칸"
    (체인줄,) = built.chain(market="domestic", product_code="KOSPI", expiry="202609")
    assert 체인줄["rem_cnt"] == "80", "체인"
    assert built.locate("domestic", 체인줄["series"])["rem_cnt"] == "80", "locate"


def test_조각의_주간야간_쌍이_한_종목으로_접힌다(실마스터):
    """조각에 담은 주간·야간 쌍이 **한 종목으로 접힙니다.**

    잔존일수가 다르다는 이유로 두 줄을 어긋난 것으로 세면 그런 국내 종목이 통째로
    색인에서 빠져 코스피200 선물이 한 줄도 안 섭니다. 조각에
    품목 셋의 주간·야간 쌍을 담아, 접기가 도는지와 그 결과로 품목이 서는지를 봅니다.

    **전체 배포본에서 충돌이 몇이었는지는 여기서 세지 않습니다** — 조각은 시험이
    보는 줄만 고른 여덟 줄이라 그 수를 잴 자리가 아닙니다. 담은 쌍에서 충돌이 0
    이라는 것까지가 이 시험이 말하는 것입니다.
    """
    index = 실마스터.index()

    assert index["folding_conflicts"] == []
    선것 = [one for one in index["contracts"] if one.get("product_code") == "KOSPI"]
    assert 선것, "코스피200 월물이 색인에 섭니다."
    품목 = {
        (one["market"], one["product_code"]): one["contract_counts"]
        for one in index["products"]
    }
    assert 품목[("domestic", "KOSPI")]["futures"] > 0
    assert 품목[("domestic", "USD")]["futures"] > 0
    assert 품목[("domestic", "KOSDAQ150")]["futures"] > 0


def test_실물_마스터의_잔존일수는_주간_줄이다(실마스터):
    """같은 종목이 주간 줄과 야간 줄로 오고, **색인이 내는 것은 주간 줄의 값**
    입니다. 야간 줄은 다음 거래일 기준이라 잔존일수가 더 적습니다.

    **날수는 박지 않고 두 줄을 견줍니다.** 조각은 안 변하지만, 값을 적어 두면
    조각을 다른 판본으로 바꾸는 날 이 시험이 뜻과 상관없이 깨집니다.

    **차이가 있는 사본이라야 가립니다.** 두 줄의 잔존일수가 같으면 색인이 어느
    줄을 골랐는지 이 시험으로 알 수 없습니다 — 실물에서 그런 날이 옵니다
    (A016C000 은 2026-09-22 배포본에서 주간 80·야간 80 입니다). 조각을 차이가
    있는 배포본(09-23, 주간 80·야간 79)에서 담는 까닭입니다.
    """
    주간, 야간 = _주간야간줄(실마스터, "domestic", "A016C000")

    assert int(야간["rem_cnt"]) < int(주간["rem_cnt"]), "두 줄이 갈려야 어느 줄인지 가립니다."

    선것 = 실마스터.locate("domestic", "A016C000")

    assert 선것 is not None
    assert 선것["rem_cnt"] == 주간["rem_cnt"]


def _주간야간줄(서비스, market: str, code: str) -> tuple[dict, dict]:
    """같은 종목코드로 온 마스터 줄을 (주간, 야간)으로 갈라 냅니다.

    색인은 주간 줄만 내보내므로, 두 줄을 견주려면 읽어 둔 표에서 직접 찾습니다.
    """
    found: dict[str, dict] = {}
    for table in 서비스._index.tables.values():
        if table.market != market:
            continue
        at = table.index_of(_code_field(market))
        for raw in table.rows:
            if raw[at] == code:
                row = dict(zip(table.fields, raw))
                found[row.get("cme_tp")] = row

    assert set(found) == {"day", NIGHT_SESSION}, f"{code} 는 주간·야간 두 줄로 옵니다."
    return found["day"], found[NIGHT_SESSION]
