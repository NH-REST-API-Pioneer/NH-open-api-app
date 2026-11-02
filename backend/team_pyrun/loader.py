"""전략 폴더의 파이썬 파일을 불러옵니다.

    ~/NHFutures/strategies/*.py

week02 처럼 **파일 하나가 전략 하나**이고, 파일 끝에 `STRATEGY`·`TITLE`·`NAME` 을 적어
앱에 알립니다. 전략 파일은 `from strategy import ...` 처럼 옆 파일을 이름으로 불러 쓰는데,
앱에도 `backend.strategy` 가 있어 이름이 겹칠 수 있습니다. 그래서 **불러오는 동안만**
`sys.path`·`sys.modules` 를 바꿨다가 끝나면 그대로 되돌립니다(모듈 전역 잠금 안에서).
같은 파일을 두 번 불러오면 서로 다른 모듈이 됩니다 — 파일을 고쳐도 돌던 실행은 처음 것 그대로입니다.

모듈이 지켜야 할 약속(`STRATEGY` `TITLE` `NAME` `TICK` `TICK_VALUE`, 모듈의 `Params`, 전략 인스턴스의
`on_minute` 등)은 불러올 때 한 번에 검사하고, 빠진 이름을 메시지에 모두 적습니다.
파일 하나가 잘못돼도 앱이나 다른 실행에는 번지지 않습니다(`LoadError` 로만 알림).
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import config

#: 전략 파라미터(`Params`) 필수 칸.
REQUIRED_PARAMS = ("session_start", "session_end", "entry_start", "entry_end", "flatten_at", "hold_min")
#: 전략 인스턴스 필수 이름.
REQUIRED_INSTANCE = ("on_minute", "end_of_day", "on_entry", "on_exit", "day", "p", "target")
#: 모듈 필수 이름.
REQUIRED_MODULE = ("STRATEGY", "TITLE", "NAME", "TICK", "TICK_VALUE")

#: sys.path·sys.modules 를 건드리는 동안 다른 불러오기가 끼어들지 못하게 한다.
_LOCK = threading.Lock()


class LoadError(Exception):
    """전략 파일을 불러오지 못했거나 약속을 어겼다. 메시지가 그대로 화면에 간다."""


@dataclass(frozen=True)
class StrategyFile:
    """목록 한 줄. `error` 가 있으면 쓸 수 없는 파일(이유가 담김)."""

    file: str
    name: str | None
    title: str | None
    params: dict | None
    error: str | None


@dataclass(frozen=True)
class Loaded:
    """불러온 전략. `new()` 로 실행마다 새 전략 인스턴스를 만든다."""

    file: str
    name: str
    title: str
    sha256: str
    strategy_cls: type
    params_cls: type
    tick: float
    tick_value: float

    def new(self) -> object:
        return self.strategy_cls(self.params_cls())


def strategies_dir() -> Path:
    """전략 폴더(`~/NHFutures/strategies`). 없으면 만든다."""
    path = config.HOME_DIR / "strategies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _inside(module: ModuleType, folder: Path) -> bool:
    file = getattr(module, "__file__", None)
    if not file:
        return False
    try:
        return Path(file).resolve().is_relative_to(folder)
    except (OSError, ValueError):
        return False


def _exec_module(folder: Path, file: str) -> tuple[ModuleType, str]:
    """파일을 따로 불러온다. 모듈과 파일 sha256 을 돌려준다. 실패는 `LoadError`."""
    folder = folder.resolve()
    path = folder / file
    if not path.is_file():
        raise LoadError(f"파일이 없습니다: {file}")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with _LOCK:
        saved_path = list(sys.path)
        # 폴더 안 파일 이름과 같은 이름의 모듈(앱·다른 곳에서 온 것)은 잠시 치워 둔다.
        names = {p.stem for p in folder.glob("*.py")}
        saved_mods = {n: sys.modules.pop(n) for n in names if n in sys.modules}
        modname = f"team_pyrun_{uuid.uuid4().hex}"
        try:
            sys.path.insert(0, str(folder))
            spec = importlib.util.spec_from_file_location(modname, path)
            if spec is None or spec.loader is None:
                raise LoadError(f"불러올 수 없는 파일입니다: {file}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[modname] = module   # dataclass 등이 모듈을 이름으로 찾는다
            spec.loader.exec_module(module)
            return module, sha
        except LoadError:
            raise
        except (Exception, SystemExit) as e:   # 전략 파일 하나가 앱을 멈추지 않게 한다
            raise LoadError(f"{type(e).__name__}: {e}") from e
        finally:
            sys.path[:] = saved_path
            for n in [n for n, m in sys.modules.items() if _inside(m, folder)]:
                del sys.modules[n]
            sys.modules.pop(modname, None)
            sys.modules.update(saved_mods)


def _check(module: ModuleType) -> tuple[type, type, object]:
    """약속을 검사한다. 어기면 빠진 이름을 모두 적어 `LoadError`. (전략 클래스, Params 클래스, 인스턴스)"""
    missing = [n for n in REQUIRED_MODULE if not hasattr(module, n)]
    if not hasattr(module, "Params"):
        missing.append("Params")
    if missing:
        raise LoadError("모듈에 없는 이름: " + ", ".join(missing))
    strategy_cls, params_cls = module.STRATEGY, module.Params
    try:
        params = params_cls()
        params_missing = [n for n in REQUIRED_PARAMS if not hasattr(params, n)]
        if params_missing:
            raise LoadError("Params 에 없는 이름: " + ", ".join(params_missing))
        if not dataclasses.is_dataclass(params):
            raise LoadError("Params 는 dataclass 여야 합니다")
        instance = strategy_cls(params)
    except LoadError:
        raise
    except Exception as e:
        raise LoadError(f"{type(e).__name__}: {e}") from e
    inst_missing = [n for n in REQUIRED_INSTANCE if not hasattr(instance, n)]
    if inst_missing:
        raise LoadError("전략에 없는 이름: " + ", ".join(inst_missing))
    return strategy_cls, params_cls, instance


def load(folder: Path, file: str) -> Loaded:
    """전략 파일 하나를 불러온다. 못 쓰는 파일은 `LoadError`."""
    module, sha = _exec_module(folder, file)
    if not hasattr(module, "STRATEGY"):
        raise LoadError("모듈에 없는 이름: STRATEGY")
    strategy_cls, params_cls, _ = _check(module)
    try:
        tick, tick_value = float(module.TICK), float(module.TICK_VALUE)
    except (TypeError, ValueError) as e:
        raise LoadError(f"TICK·TICK_VALUE 는 숫자여야 합니다: {e}") from e
    return Loaded(
        file=file,
        name=str(module.NAME),
        title=str(module.TITLE),
        sha256=sha,
        strategy_cls=strategy_cls,
        params_cls=params_cls,
        tick=tick,
        tick_value=tick_value,
    )


def scan(folder: Path) -> list[StrategyFile]:
    """폴더의 `*.py` 중 `STRATEGY` 가 있거나 불러오기에 실패한 것만, 파일 이름순으로.

    `STRATEGY` 없는 정상 모듈(공용 코드)은 목록에서 뺀다.
    """
    out: list[StrategyFile] = []
    for path in sorted(Path(folder).glob("*.py"), key=lambda p: p.name):
        file = path.name
        try:
            module, _ = _exec_module(folder, file)
        except LoadError as e:
            out.append(StrategyFile(file, None, None, None, str(e)))
            continue
        if not hasattr(module, "STRATEGY"):
            continue
        name = getattr(module, "NAME", None)
        title = getattr(module, "TITLE", None)
        name = None if name is None else str(name)
        title = None if title is None else str(title)
        try:
            _, _, instance = _check(module)
            params: dict[str, Any] | None = dataclasses.asdict(instance.p)
            out.append(StrategyFile(file, name, title, params, None))
        except LoadError as e:
            out.append(StrategyFile(file, name, title, None, str(e)))
    return out
