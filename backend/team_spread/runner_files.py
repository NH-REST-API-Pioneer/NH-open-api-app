"""스프레드 실행기 파일 — `~/NHFutures/spreads/*.py` 를 불러와 약속(`LEGS` 와 `run(ctx)`)을 검사한다.

파일 하나가 실행기 하나다. 맨 위에 `LEGS = {"이름": "다리 표기"}` 와 `def run(ctx)` 가 있어야 한다.
`TITLE`·`NAME`(파이썬 전략과 같은 규칙)·`MAX_QTY`(양의 정수, 선택)는 있으면 쓴다.
`run` 또는 `LEGS` 를 정의하지 않은 파일은 옆 모듈(실행기가 `import` 하는 공용 코드)로 따로 센다.
다리 표기 자체의 뜻은 여기서 보지 않고 `legs.resolve` 가 본다.

격리 실행은 파이썬 전략 탭과 같다(`team_pyrun.loader.exec_isolated`). 다만 판단 부분만 골라 쓰기는 하지 않아
(`pick=False`) 앱에 없는 모듈을 import 하면 그대로 `ModuleNotFoundError` 로 알린다.
올리기·지우기는 `team_pyrun.strategy_files` 를 폴더만 바꿔 쓴다.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable

from backend import config
from backend.team_pyrun.loader import NAME_PATTERN, LoadError, _module_title, exec_isolated

#: 다리 이름 — 기록·화면에 그대로 쓰인다.
LEG_NAME = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class RunnerFile:
    """목록 한 줄. `error` 가 있으면 쓸 수 없는 파일(이유가 담김)."""

    file: str
    name: str | None
    title: str | None
    legs: dict[str, str]
    max_qty: int | None
    error: str | None
    sha256: str | None


@dataclass(frozen=True)
class LoadedRunner:
    """불러온 실행기."""

    file: str
    name: str
    title: str
    sha256: str
    legs: dict[str, str]
    max_qty: int | None
    run: Callable


def spreads_dir() -> Path:
    """실행기 폴더(`~/NHFutures/spreads`). 없으면 만든다."""
    path = config.HOME_DIR / "spreads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_runner(module: ModuleType) -> bool:
    return hasattr(module, "run") or hasattr(module, "LEGS")


def _legs(module: ModuleType) -> dict[str, str]:
    if not hasattr(module, "LEGS"):
        raise LoadError("LEGS 가 없습니다 — 「LEGS = {'이름': '다리'}」 꼴로 적어 주세요")
    legs = module.LEGS
    if not isinstance(legs, dict):
        raise LoadError(f"LEGS 는 dict 여야 합니다: {type(legs).__name__}")
    if not legs:
        raise LoadError("LEGS 가 비었습니다 — 다리를 하나 이상 적어 주세요")
    for key, value in legs.items():
        if not isinstance(key, str) or not LEG_NAME.fullmatch(key):
            raise LoadError(f"LEGS 이름은 영문·숫자·_ 만 쓸 수 있습니다: {key!r}")
        if not isinstance(value, str) or not value or re.search(r"\s|/", value):
            raise LoadError(f"LEGS 값은 공백·/ 없는 글자여야 합니다: {key!r}: {value!r}")
    return dict(legs)


def _run(module: ModuleType) -> Callable:
    if not hasattr(module, "run"):
        raise LoadError("run 이 없습니다 — 「def run(ctx):」 를 정의해 주세요")
    fn = module.run
    if not callable(fn):
        raise LoadError("run 은 부를 수 있는 함수여야 합니다")
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError) as e:
        raise LoadError(f"run 의 인자를 알 수 없습니다: {e}") from e
    ok = (len(params) == 1
          and params[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
    if not ok:
        raise LoadError("run 은 인자 하나(ctx)만 받아야 합니다")
    return fn


def _max_qty(module: ModuleType) -> int | None:
    if not hasattr(module, "MAX_QTY"):
        return None
    q = module.MAX_QTY
    if isinstance(q, bool) or not isinstance(q, int) or q <= 0:
        raise LoadError(f"MAX_QTY 는 양의 정수여야 합니다: {q!r}")
    return q


def _name_title(module: ModuleType, file: str) -> tuple[str, str]:
    if hasattr(module, "NAME"):
        name = str(module.NAME)
        if not NAME_PATTERN.fullmatch(name):
            raise LoadError(f"NAME 은 영문·숫자·_·- 만 쓸 수 있습니다: {module.NAME!r}")
    else:
        name = re.sub(r"[^A-Za-z0-9_-]", "_", Path(file).stem)
    title = str(module.TITLE) if hasattr(module, "TITLE") else (_module_title(module.__doc__) or name)
    return name, title


def _check(module: ModuleType, file: str, sha: str) -> LoadedRunner:
    legs = _legs(module)
    run = _run(module)
    max_qty = _max_qty(module)
    name, title = _name_title(module, file)
    return LoadedRunner(file, name, title, sha, legs, max_qty, run)


def load_runner(folder: Path, file: str) -> LoadedRunner:
    """실행기 파일 하나를 불러온다. 못 쓰는 파일은 `LoadError`."""
    module, sha = exec_isolated(folder, file, pick=False)
    return _check(module, file, sha)


def scan(folder: Path) -> tuple[list[RunnerFile], list[str]]:
    """폴더의 `*.py` 를 한 번 훑어 (실행기 목록, 옆 모듈 이름들)을 돌려준다. 둘 다 파일 이름순.

    실행기 목록은 `run`·`LEGS` 를 정의한 파일이거나 불러오기에 실패한 파일(`error` 에 까닭)."""
    runners: list[RunnerFile] = []
    modules: list[str] = []
    for path in sorted(Path(folder).glob("*.py"), key=lambda p: p.name):
        file = path.name
        try:
            module, sha = exec_isolated(folder, file, pick=False)
        except LoadError as e:
            runners.append(RunnerFile(file, None, None, {}, None, str(e), None))
            continue
        if not _is_runner(module):
            modules.append(file)
            continue
        try:
            r = _check(module, file, sha)
            runners.append(RunnerFile(file, r.name, r.title, r.legs, r.max_qty, None, sha))
        except LoadError as e:
            runners.append(RunnerFile(file, None, None, {}, None, str(e), sha))
    return runners, modules
