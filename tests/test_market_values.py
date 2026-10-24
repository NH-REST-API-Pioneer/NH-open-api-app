"""응답의 숫자 글자를 읽는 규칙 — 천 단위 쉼표."""
from __future__ import annotations

import pytest

from backend import market_values


@pytest.mark.parametrize(
    "글자, 값",
    [("7,745.25", 7745.25), ("1,234", 1234.0), ("-1,234.5", -1234.5), ("12,345,678", 12345678.0), ("7745.25", 7745.25)],
)
def test_천_단위_쉼표는_빼고_읽는다(글자, 값):
    assert market_values.number(글자) == 값
    assert market_values.plain_number(글자) == 값


@pytest.mark.parametrize("글자", ["1,2", "12,34", "1,0,0", ",123", "1,234,5"])
def test_묶음이_틀린_쉼표는_숫자가_아니다(글자):
    assert market_values.number(글자) is None


@pytest.mark.parametrize("글자, 값", [("1,2", 12.0), ("12,34", 1234.0)])
def test_사람이_적는_숫자는_쉼표를_모두_지우고_읽는다(글자, 값):
    assert market_values.plain_number(글자) == 값


def test_쉼표_묶음도_개수로_읽힌다():
    assert market_values.count("1,234") == 1234
