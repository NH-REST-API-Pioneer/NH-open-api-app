"""한글 이름 검사기.

검사기가 **주석·설명글의 한글에는 안 걸리고 이름에만 걸리는지**를 봅니다.
그 구분이 이 도구의 전부입니다 — `grep` 으로 못 하는 일이 그것뿐입니다.
"""
from __future__ import annotations

import ast

from scripts.check_identifiers import check, has_korean, main, names_in

한글이름 = '''
def 더하기(값, 다른값):
    """두 값을 더합니다."""
    합계 = 값 + 다른값
    return 합계
'''

영문이름 = '''
def add(first, second):
    """두 값을 더합니다 — 설명은 한글입니다.

    표·칸·코드 같은 낱말이 설명에 잔뜩 있어도 이름이 아니면 안 걸립니다.
    """
    # 여기 주석도 한글입니다.
    total = first + second
    label = "값이 담긴 글자"
    return total, label
'''


def test_한글_이름을_찾는다():
    찾은것 = names_in(ast.parse(한글이름))

    이름들 = {name for _, name in 찾은것}
    assert "더하기" in 이름들
    assert "합계" in 이름들
    assert "값" in 이름들


def test_주석과_설명글의_한글은_안_걸린다():
    """이 저장소는 설명이 전부 한글이라, 여기서 걸리면 도구가 쓸모없습니다."""
    assert names_in(ast.parse(영문이름)) == []


def test_문자열_안의_한글도_안_걸린다():
    코드 = 'message = "주문을 내지 못했습니다"\n'

    assert names_in(ast.parse(코드)) == []


def test_읽지_못하는_파일은_건너뛴다(tmp_path):
    """검사가 할 일이 아닙니다. 구문 오류는 다른 도구가 잡습니다."""
    깨진것 = tmp_path / "broken.py"
    깨진것.write_text("def (:", encoding="utf-8")

    assert check(깨진것) == []


def test_한글_음절만_본다():
    assert has_korean("합계") is True
    assert has_korean("total") is False
    # 자모는 이름에 안 쓰입니다.
    assert has_korean("total_1") is False


def test_있으면_1_로_끝난다(tmp_path, capsys):
    자리 = tmp_path / "bad.py"
    자리.write_text(한글이름, encoding="utf-8")

    끝값 = main(["check_identifiers.py", str(자리)])

    assert 끝값 == 1
    적힌것 = capsys.readouterr().out
    assert "더하기" in 적힌것
    assert "bad.py" in 적힌것


def test_없으면_0_으로_끝난다(tmp_path, capsys):
    자리 = tmp_path / "good.py"
    자리.write_text(영문이름, encoding="utf-8")

    끝값 = main(["check_identifiers.py", str(자리)])

    assert 끝값 == 0
    assert "없음" in capsys.readouterr().out


def test_지금_저장소가_깨끗하다():
    """이 시험이 규칙을 지킵니다 — 한글 이름이 새로 들어오면 여기서 걸립니다."""
    from scripts.check_identifiers import DEFAULT_TARGETS, walk

    hits = walk(list(DEFAULT_TARGETS))

    assert hits == [], f"한글 이름이 있습니다: {hits}"
