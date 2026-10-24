"""값 칸 폭을 잡기 위한 후보 행."""
import pytest

from backend.master.master_files import MASTER_FILES_BY_NAME
from backend.master.master_index import build_index
from backend.master.master_store import load_all, save_master
from backend.master.master_widths import (
    DECIMAL,
    FRACTION,
    WidthCandidates,
    decimals_of,
    integer_digits,
    is_fraction,
    price_decimals,
    tick_decimals,
)

from tests.fixtures.master import fixture_text

DOMESTIC = "domestic"
OVERSEAS = "overseas"

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


def 국내(p_dec="2", upper="", lower="", strike="", series="A7569000"):
    return {
        "p_dec": p_dec,
        "upper_p_lv1": upper,
        "lower_p_lv1": lower,
        "strike_p": strike,
        "series": series,
    }


def 해외(pind="3", tsiz="0.010000000", prev="", code="MESU26"):
    return {"pind": pind, "tsiz": tsiz, "prev": prev, "code": code}


def test_가격표시방법이_말하는_자릿수():
    """명세의 코드표 그대로다 — 1 이 소수점 없음, 9 가 여덟 자리."""
    assert price_decimals("1") == 0
    assert price_decimals("3") == 2
    assert price_decimals("9") == 8
    # 글자는 분수라 자리 수를 말하지 않는다.
    assert price_decimals("F") is None
    assert price_decimals("") is None
    assert price_decimals(None) is None
    assert price_decimals("0") is None


def test_호가단위에서_센_자릿수():
    assert tick_decimals("0.010000000") == 2
    assert tick_decimals("0.000050000") == 5
    assert tick_decimals("1") == 0
    assert tick_decimals("") is None
    assert tick_decimals(None) is None


def test_분수로_적는_상품():
    assert is_fraction("F") is True
    assert is_fraction("3") is False
    assert is_fraction("") is False


def test_국내_자릿수는_마스터가_준_값을_그대로_쓴다():
    """국내 파일은 개별주식선물도 값을 소수 두 자리로 싣지만 `p_dec` 은 0 이다."""
    assert decimals_of(DOMESTIC, 국내(p_dec="0", upper="18290.00")) == 0
    assert decimals_of(DOMESTIC, 국내(p_dec="2")) == 2
    assert decimals_of(DOMESTIC, 국내(p_dec="")) is None


def test_해외_자릿수는_표시와_호가단위_중_큰_쪽이다():
    """호가단위가 더 잘게 오는 품목이 있다. 표시 쪽만 쓰면 한 틱 움직여도 숫자가 안 바뀐다."""
    # 표시 2자리 · 호가단위 1자리 → 2자리로 적는다.
    assert decimals_of(OVERSEAS, 해외(pind="3", tsiz="0.500000000")) == 2
    # 표시 2자리 · 호가단위 5자리 → 5자리.
    assert decimals_of(OVERSEAS, 해외(pind="3", tsiz="0.000050000")) == 5
    # 분수 상품은 표시가 자리 수를 말하지 않으므로 호가단위에서 센다.
    assert decimals_of(OVERSEAS, 해외(pind="F", tsiz="0.015625000")) == 6
    assert decimals_of(OVERSEAS, 해외(pind="", tsiz="")) is None


def test_정수부_자릿수():
    assert integer_digits("1651000.00") == 7
    assert integer_digits("-146000.00") == 6
    # 0.65 는 화면에 0 이 한 자 서므로 한 자리로 본다.
    assert integer_digits("0.65432") == 1
    assert integer_digits("53240") == 5
    assert integer_digits("") is None
    assert integer_digits("없는값") is None
    assert integer_digits("1,234") is None


def test_자릿수가_같아도_표기가_다르면_다른_무리():
    """분수 상품의 긴 값이 소수 상품의 칸까지 넓히면 안 된다."""
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(pind="7", tsiz="0.000001000", prev="0.6264"))
    모은것.add(OVERSEAS, 해외(pind="F", tsiz="0.015625000", prev="109.421875000"))

    무리들 = {(g["decimals"], g["notation"]): g for g in 모은것.payload()["groups"]}
    assert set(무리들) == {(6, DECIMAL), (6, FRACTION)}
    assert 무리들[(6, DECIMAL)]["candidates"][0]["value"] == "0.6264"
    assert 무리들[(6, FRACTION)]["candidates"][0]["value"] == "109.421875000"


def test_꼬리_0_에_속지_않고_정수부로_고른다():
    """원문에는 꼬리 0 이 붙어 있어 글자 수를 세면 짧은 값이 이긴다."""
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(prev="9.9999999"))  # 아홉 자, 정수부 한 자리
    모은것.add(OVERSEAS, 해외(prev="12345.6"))  # 일곱 자, 정수부 다섯 자리

    후보 = 모은것.payload()["groups"][0]["candidates"]
    assert [c["value"] for c in 후보] == ["12345.6"]


def test_양수와_음수를_따로_고른다():
    """음수는 부호 한 자리를 더 쓴다."""
    모은것 = WidthCandidates()
    모은것.add(DOMESTIC, 국내(p_dec="0", upper="1651000.00", lower="-146000.00"))

    후보 = 모은것.payload()["groups"][0]["candidates"]
    assert [(c["sign"], c["value"]) for c in 후보] == [
        ("positive", "1651000.00"),
        ("negative", "-146000.00"),
    ]


def test_음수가_없으면_음수_후보도_없다():
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(prev="29513.00"))

    후보 = 모은것.payload()["groups"][0]["candidates"]
    assert [c["sign"] for c in 후보] == ["positive"]


def test_국내는_상하한가와_행사가를_본다():
    """국내 마스터에는 가격 필드가 없다."""
    모은것 = WidthCandidates()
    모은것.add(DOMESTIC, 국내(p_dec="2", upper="826.55", strike="9945.00"))

    후보 = 모은것.payload()["groups"][0]["candidates"][0]
    assert 후보["value"] == "9945.00"
    assert 후보["field"] == "strike_p"


def test_어느_종목에서_나왔는지_남긴다():
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(prev="29513.00", code="ESU26"))
    assert 모은것.payload()["groups"][0]["candidates"][0]["code"] == "ESU26"


def test_값이_없는_무리는_내지_않는다():
    """행은 있는데 잴 값이 하나도 없으면 후보를 만들 수 없다."""
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(prev=""))

    나온것 = 모은것.payload()
    assert 나온것["groups"] == []
    # 그래도 「후보 없는 무리」로 세어 둔다.
    assert 나온것["checks"]["without_candidate"] == ["overseas/2/decimal"]


def test_자릿수를_모르는_행은_세어_둔다():
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(pind="", tsiz="", prev="1.5"))
    assert 모은것.payload()["checks"]["rows_without_decimals"] == 1


def test_숫자로_읽지_못한_값은_세어_둔다():
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(prev="가격없음"))
    assert 모은것.payload()["checks"]["unreadable_values"] == 1


def test_호가단위가_더_잘게_온_행을_세어_둔다():
    """화면이 큰 쪽을 쓰기로 한 근거가 몇 건인지 볼 수 있어야 한다."""
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(pind="3", tsiz="0.000050000", prev="0.71630"))
    모은것.add(OVERSEAS, 해외(pind="3", tsiz="0.500000000", prev="29513.00"))

    assert 모은것.payload()["checks"]["tick_finer_than_display"] == 1


def test_고른_후보가_그_무리의_최댓값과_같은지_스스로_잰다():
    모은것 = WidthCandidates()
    for 값 in ("1.5", "222.5", "33.5"):
        모은것.add(OVERSEAS, 해외(pind="2", tsiz="0.100000000", prev=값))

    검사 = 모은것.payload()["checks"]
    assert 검사["mismatched"] == []
    assert 모은것.payload()["groups"][0]["candidates"][0]["value"] == "222.5"


def test_행_수를_센다():
    모은것 = WidthCandidates()
    for _ in range(3):
        모은것.add(OVERSEAS, 해외(prev="1.00"))
    assert 모은것.payload()["groups"][0]["rows"] == 3


def test_무리는_시장_자릿수_표기_순으로_나온다():
    모은것 = WidthCandidates()
    모은것.add(OVERSEAS, 해외(pind="F", tsiz="0.015625000", prev="109.421875000"))
    모은것.add(OVERSEAS, 해외(pind="1", tsiz="1", prev="53240"))
    모은것.add(DOMESTIC, 국내(p_dec="0", upper="1651000.00"))

    나온것 = [(g["market"], g["decimals"], g["notation"]) for g in 모은것.payload()["groups"]]
    assert 나온것 == [
        ("domestic", 0, DECIMAL),
        ("overseas", 0, DECIMAL),
        ("overseas", 6, FRACTION),
    ]


def test_색인이_후보를_함께_낸다(tmp_path):
    """마스터 조각으로 색인을 만들어 실제로 실리는지 본다."""
    for name in _MASTERS:
        save_master(
            MASTER_FILES_BY_NAME[name],
            fixture_text(name).encode("utf-8"),
            stamp="20260902",
            base_dir=tmp_path,
        )
    나온것 = build_index(load_all(tmp_path)).payload["width_candidates"]

    assert 나온것["groups"], "무리가 하나도 안 나오면 화면이 폭을 못 정한다"
    for 무리 in 나온것["groups"]:
        assert 무리["market"] in (DOMESTIC, OVERSEAS)
        assert 무리["notation"] in (DECIMAL, FRACTION)
        assert 무리["rows"] > 0
        assert 무리["candidates"], 무리
        for 후보 in 무리["candidates"]:
            assert 후보["value"].strip() == 후보["value"]
            assert integer_digits(후보["value"]) is not None

    검사 = 나온것["checks"]
    assert 검사["mismatched"] == []
    assert 검사["without_candidate"] == []


def test_옵션_행도_센다(tmp_path):
    """국내는 행사가가 가장 긴 값을 낼 수 있고, 옵션은 색인에 안 담긴다."""
    for name in ("fut_opt", "stk_fut_opt", "idx_fut_opt"):
        save_master(
            MASTER_FILES_BY_NAME[name],
            fixture_text(name).encode("utf-8"),
            stamp="20260902",
            base_dir=tmp_path,
        )
    나온것 = build_index(load_all(tmp_path)).payload["width_candidates"]

    쓰인_열 = {
        후보["field"] for 무리 in 나온것["groups"] for 후보 in 무리["candidates"]
    }
    assert 쓰인_열 <= {"upper_p_lv1", "lower_p_lv1", "strike_p"}


@pytest.mark.parametrize("market", [DOMESTIC, OVERSEAS])
def test_같은_자료를_두_번_넣어도_후보가_같다(market):
    def 모으기(횟수):
        모은것 = WidthCandidates()
        for _ in range(횟수):
            if market == DOMESTIC:
                모은것.add(DOMESTIC, 국내(p_dec="2", upper="15452.20"))
            else:
                모은것.add(OVERSEAS, 해외(prev="29513.00"))
        return [g["candidates"] for g in 모은것.payload()["groups"]]

    assert 모으기(1) == 모으기(5)
