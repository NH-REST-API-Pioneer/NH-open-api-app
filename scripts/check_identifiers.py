"""프로그램 코드에 한글 이름이 섞였는지 봅니다.

이 저장소는 **주석과 설명글은 한글, 이름은 영문**입니다. 이름이란 변수·인자·
함수·클래스·속성처럼 코드가 부르는 자리를 말합니다. 설명은 읽는 사람을 위한
것이라 한글이 낫고, 이름은 도구가 다루는 것이라 영문이 안전합니다.

**눈이나 `grep` 으로는 못 가립니다.** 이 저장소는 주석과 docstring 이 거의 다
한글이라 `grep` 을 걸면 전부 걸립니다. 그래서 파이썬이 코드를 읽는 방식 그대로
(`ast`) 구문 트리를 훑어 **이름 자리만** 봅니다. 주석·설명글·문자열 안의 한글은
세지 않습니다.

시험 파일(`tests/`)은 보지 않습니다. 시험은 한글 이름을 쓰기로 되어 있습니다.

    uv run python scripts/check_identifiers.py

폴더를 직접 줄 수도 있습니다.

    uv run python scripts/check_identifiers.py backend/auth

한글 이름이 하나라도 있으면 자리를 적어 보여 주고 **1 로 끝냅니다.** 없으면
한 줄만 적고 0 으로 끝냅니다.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

#: 기본으로 보는 곳. 프로그램이 되는 코드입니다.
DEFAULT_TARGETS = ("backend", "scripts", "desktop")

#: 한글 음절 범위. 자모(ㄱ, ㅏ)까지 보지 않는 것은 이름에 쓰이지 않기 때문입니다.
FIRST = "가"
LAST = "힣"


def has_korean(text: str) -> bool:
    """글자 안에 한글이 있는지."""
    return any(FIRST <= ch <= LAST for ch in text)


def names_in(tree: ast.AST) -> list[tuple[int, str]]:
    """구문 트리에서 **이름 자리**만 골라 냅니다.

    골라 보는 자리는 여섯입니다 — 변수·함수·클래스·인자·키워드 인자·속성.
    문자열이나 주석은 트리의 이 자리에 오지 않으므로 저절로 빠집니다.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.arg):
            name = node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            name = node.arg
        elif isinstance(node, ast.Attribute):
            name = node.attr
        if name and has_korean(name):
            found.append((getattr(node, "lineno", 0), name))
    return sorted(set(found))


def check(path: Path) -> list[tuple[int, str]]:
    """파일 하나를 봅니다. 읽지 못하면 빈 목록입니다."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        # 못 읽는 파일을 여기서 막지 않습니다. 그것은 이 검사가 할 일이 아닙니다.
        return []
    return names_in(tree)


def walk(targets: list[str]) -> list[tuple[Path, int, str]]:
    """줄 곳들을 훑어 한글 이름을 모읍니다."""
    hits: list[tuple[Path, int, str]] = []
    for target in targets:
        root = Path(target)
        files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
        for path in files:
            for line, name in check(path):
                hits.append((path, line, name))
    return hits


def main(argv: list[str]) -> int:
    targets = argv[1:] or list(DEFAULT_TARGETS)
    hits = walk(targets)

    if not hits:
        print(f"한글 이름 없음 ({', '.join(targets)})")
        return 0

    print(f"한글 이름 {len(hits)}건:")
    for path, line, name in hits:
        print(f"  {path.as_posix()}:{line}  {name}")
    print("\n이름은 영문으로 바꿔 주세요. 설명이 필요하면 옆에 주석으로 답니다.")
    return 1


if __name__ == "__main__":
    # 한글을 그대로 찍습니다. 콘솔이 cp949 여도 깨지지 않게 해 둡니다.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv))
