"""전략 폴더의 파일을 화면에서 올리고 지웁니다(`POST·DELETE /api/team/pyrun/strategies`).

폴더에 직접 복사해 넣는 길은 그대로 됩니다 — 이 모듈은 같은 폴더에 같은 일을 대신 해 줄 뿐입니다.

- **이름**: `영문·숫자·_·-` + `.py` 만. 경로 문자(`/` `\\` `..`)·공백·한글 이름은 거절합니다.
- **내용**: 문자열이어야 하고 UTF-8 로 256 KB 이하. 받은 글을 **바이트 그대로**(줄바꿈 변환 없이) 씁니다.
- **올릴 때 컴파일도 실행도 하지 않습니다.** 고장 난 파일도 저장되고, 목록에서 오류로 보입니다
  (`loader.scan` 이 읽을 때 오류를 적습니다). 실행은 시작할 때 처음 불러온 코드로 돌므로(`loader.py`),
  돌고 있는 실행은 파일을 덮어쓰거나 지워도 영향이 없습니다.
- **쓰기는 한 번에**: 같은 폴더의 임시 파일에 쓴 뒤 `os.replace`. 쓰다 실패해도 옛 파일은 그대로이고 임시 파일은 지웁니다.
  임시 파일 이름은 `.py` 로 끝나지 않아 목록에 끼지 않습니다.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

#: 올릴 수 있는 파일 하나의 최대 크기(UTF-8 바이트).
MAX_STRATEGY_BYTES = 256 * 1024
#: 전략 파일 이름. 폴더 안 파일 하나만 가리킬 수 있는 글자만 받는다(경로·`..`·공백·한글 이름 거절).
FILE_PATTERN = re.compile(r"[A-Za-z0-9_-]+\.py")
#: 임시 파일 이름 앞부분. 끝이 `.py` 가 아니어서 `scan` 이 읽지 않는다.
_TEMP_PREFIX = ".upload-"


class BadFile(ValueError):
    """이름이나 내용이 맞지 않다(400). 메시지가 그대로 화면에 간다."""


class FileExists(Exception):
    """같은 이름의 파일이 이미 있다(409). 화면이 덮어쓸지 묻는 데 쓴다."""


class NoSuchFile(Exception):
    """지우려는 파일이 없다(404)."""


class StoreFailed(Exception):
    """폴더에 쓰거나 지우지 못했다(500). 메시지에 까닭이 있다."""


def check_name(file: object) -> str:
    """파일 이름을 검사해 돌려준다. 맞지 않으면 `BadFile`."""
    if not isinstance(file, str) or not FILE_PATTERN.fullmatch(file):
        raise BadFile("파일 이름은 영문·숫자·_·- 와 .py 만 쓸 수 있습니다 (예: strategy_bb.py)")
    return file


def _encode(content: object) -> bytes:
    """내용을 UTF-8 바이트로. 문자열이 아니거나 한도를 넘거나 인코딩할 수 없으면 `BadFile`."""
    if not isinstance(content, str):
        raise BadFile("파일 내용은 글(문자열)이어야 합니다")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        raise BadFile("파일 내용을 UTF-8 로 바꿀 수 없습니다") from None
    if len(data) > MAX_STRATEGY_BYTES:
        raise BadFile(f"파일이 너무 큽니다 (최대 {MAX_STRATEGY_BYTES // 1024} KB)")
    return data


def save(folder: Path, file: object, content: object, overwrite: bool) -> str:
    """전략 파일 하나를 폴더에 쓴다. 쓴 파일 이름을 돌려준다.

    같은 이름이 이미 있는데 `overwrite` 가 아니면 `FileExists`. 컴파일·실행은 하지 않는다."""
    name = check_name(file)
    data = _encode(content)
    target = Path(folder) / name
    if (target.exists() or target.is_symlink()) and not overwrite:
        raise FileExists(f"같은 이름의 파일이 있습니다: {name}")
    temp: str | None = None
    try:
        fd, temp = tempfile.mkstemp(prefix=_TEMP_PREFIX, suffix=".tmp", dir=folder)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.chmod(temp, 0o644)      # mkstemp 는 0600 으로 만든다 — 손으로 복사한 파일과 같게
        os.replace(temp, target)
        temp = None
    except OSError as e:
        raise StoreFailed(f"파일을 쓰지 못했습니다: {name} ({e})") from e
    finally:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
    return name


def delete(folder: Path, file: object) -> str:
    """전략 파일 하나를 지운다(심볼릭 링크면 링크만). 지운 이름을 돌려준다.

    이름이 맞지 않으면 `BadFile`, 파일이 없으면(폴더 포함) `NoSuchFile`."""
    name = check_name(file)
    target = Path(folder) / name
    if not (target.is_symlink() or target.is_file()):
        raise NoSuchFile(f"그 파일이 없습니다: {name}")
    try:
        target.unlink()
    except FileNotFoundError:
        raise NoSuchFile(f"그 파일이 없습니다: {name}") from None
    except OSError as e:
        raise StoreFailed(f"파일을 지우지 못했습니다: {name} ({e})") from e
    return name
