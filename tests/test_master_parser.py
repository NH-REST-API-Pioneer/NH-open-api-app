"""종목 마스터 파서.

픽스처는 NH선물이 배포하는 실물 파일에서 몇 줄만 잘라 온 것입니다. 27MB 를 저장소에
넣지 않으면서도 실제 값으로 확인하기 위한 것이라, **직접 만든 값이 아닙니다.**
어느 파일 몇 번째 줄에서 왔는지는 `tests/fixtures/master/__init__.py` 에 있습니다.
"""
import gzip

import pytest

from backend.domestic_futureoption.master import DOMESTIC_FIELDS
from backend.master.master_parser import (
    MasterParseError,
    parse_master_file,
    parse_master_text,
)
from backend.overseas_futureoption.master import OVERSEAS_OPTION_FIELDS
from tests.fixtures.master import fixture_path, fixture_text


def test_국내_마스터를_컬럼_스물여섯_개로_읽는다():
    table = parse_master_file(fixture_path("fut_opt"), DOMESTIC_FIELDS, name="fut_opt")

    assert table.fields == DOMESTIC_FIELDS
    assert len(table) == 8

    first = next(table.rows_as_dicts())
    assert first["series"] == "A0169000"
    assert first["name_kor"] == "코스피200 F 202609"
    assert first["fo_tp"] == "F"
    assert first["cme_tp"] == "day"
    # 종목명 가운데의 정렬용 공백은 원문 그대로 남습니다.
    spread = list(table.rows_as_dicts())[1]
    assert spread["name_kor"] == "코스피200 SP 2609-2612"


def test_종목코드_뒤에_붙은_공백을_떼어_낸다():
    """실물에 종목코드 뒤가 공백으로 채워진 행이 있습니다.

    떼어 내지 않으면 화면이 같은 종목을 코드로 찾지 못합니다. 종목코드와
    시세벤더코드가 **둘 다** 채워져 오므로 두 값을 비교하는 것으로는 안 잡힙니다.
    """
    table = parse_master_file(
        fixture_path("cme_opt"), OVERSEAS_OPTION_FIELDS, name="cme_opt"
    )

    codes = table.column("code")
    assert "O_GCZ28-P5245.0" in codes
    assert all(code == code.strip() for code in codes)
    assert all(code == code.strip() for code in table.column("VenderCode"))


def test_항목_수가_다른_줄이_있으면_파일을_통째로_거부한다():
    """한 줄만 어긋나도 컬럼이 통째로 밀렸을 수 있어 그 파일은 쓰지 않습니다."""
    good = fixture_text("cme_opt").splitlines()[0]

    with pytest.raises(MasterParseError) as raised:
        parse_master_text(f"{good}\n{good};덤\n", OVERSEAS_OPTION_FIELDS, name="cme_opt")

    assert "2번째 줄" in str(raised.value)
    assert "17개" in str(raised.value)


def test_빈_줄과_파일_끝의_개행은_종목으로_세지_않는다():
    good = fixture_text("cme_opt").splitlines()[0]

    table = parse_master_text(f"{good}\n\n{good}\n", OVERSEAS_OPTION_FIELDS)

    assert len(table) == 2


def test_UTF8이_아니면_읽지_못한다(tmp_path):
    """다른 인코딩을 자동으로 넣어 보지 않습니다.

    넣어 보면 대개 예외 없이 엉뚱한 글자로 읽혀서, 종목명이 깨진 채 화면까지 가고
    아무도 모릅니다. 못 읽으면 그 파일을 실패로 두는 편이 낫습니다.
    """
    path = tmp_path / "fut_opt.mst"
    path.write_bytes(fixture_text("fut_opt").encode("cp949"))

    with pytest.raises(MasterParseError) as raised:
        parse_master_file(path, DOMESTIC_FIELDS, name="fut_opt")

    assert "utf-8" in str(raised.value)


def test_없는_컬럼을_찾으면_알려_준다():
    table = parse_master_file(fixture_path("fut_opt"), DOMESTIC_FIELDS, name="fut_opt")

    with pytest.raises(KeyError):
        table.column("없는컬럼")


def test_압축을_푼_내용과_원본이_같다(tmp_path):
    """배포는 `.gz` 로 오고 저장은 푼 상태로 합니다."""
    from backend.master.master_download import unpack

    original = fixture_text("fut_opt").encode("utf-8")

    assert unpack(gzip.compress(original), name="fut_opt.mst") == original
