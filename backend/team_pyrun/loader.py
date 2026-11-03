"""전략 폴더의 파이썬 파일을 불러옵니다.

    ~/NHFutures/strategies/*.py

week02 처럼 **파일 하나가 전략 하나**입니다. **week02 파일을 고치지 않고 하나만 올려도 됩니다**:

- 파일 끝의 `STRATEGY`·`TITLE`·`NAME` 은 있으면 그대로 쓰고, 없으면 찾습니다 — 전략 클래스는 그 파일에서
  정의한 클래스 중 `on_minute` 이 있는 것 하나, `NAME` 은 파일 이름, `TITLE` 은 모듈 문서 첫 줄의 「 — 」 앞
  (없으면 클래스 문서 첫 줄, 그것도 없으면 클래스 이름).
- `Params` 는 이 파일에서 정의한 dataclass `Params` → 전략 `__init__` 첫 인자의 주석(dataclass) → 가져온
  `Params`(예: `from strategy import Params`) 순서로 찾습니다. `TICK`·`TICK_VALUE` 가
  없으면 미국달러선물 값(0.1·1000) — 장중 실행은 시작할 때 서버 값과 다시 맞춰 봅니다(`live.prepare`).
- 익절 목표(`target`·`current_vwap`)가 없으면 오류가 아니라 알림(`notes`)만 남깁니다(익절 없이 돕니다).
- 전략 파일은 `from strategy import ...` 처럼 옆 파일을 이름으로 불러 씁니다. 폴더에 `strategy.py` 가 없으면
  앱에 든 **기본 공용 모듈**(`builtin/strategy.py` = week02 `strategy.py` 원본 그대로)을 씁니다. 폴더의 것이 먼저입니다.

앱에도 `backend.strategy` 가 있어 이름이 겹칠 수 있습니다. 그래서 **불러오는 동안만**
`sys.path`·`sys.modules` 를 바꿨다가 끝나면 그대로 되돌립니다(모듈 전역 잠금 안에서). 기본 공용 모듈도 같습니다 —
불러온 뒤 `sys.modules` 에 `strategy` 로 남지 않습니다.
같은 파일을 두 번 불러오면 서로 다른 모듈이 됩니다 — 파일을 고쳐도 돌던 실행은 처음 것 그대로입니다.
대상 파일은 **해시한 바이트 그대로** 컴파일해 실행합니다(이 파일의 `from __future__` 를 물려주지 않습니다. pyc 캐시를 쓰지 않아 해시와 코드가 어긋나지 않고, 폴더에 `__pycache__` 도 안 생깁니다. 옆 모듈의 pyc 도 쓰지 않습니다).

**전략 파일은 옆 모듈을 맨 위에서 import 해야 합니다.** 메서드 안에서 하는 import 는 불러온 뒤 폴더의 모듈이
`sys.modules` 에서 빠지므로 실패합니다.

지켜야 할 약속(전략 클래스 하나, dataclass `Params` 와 필수 칸, 전략 인스턴스의 `on_minute`·`p`)은 불러올 때
한 번에 검사하고, 빠진 이름을 메시지에 모두 적습니다. 작성 규칙은 `docs/team/strategy-file-convention.md`.

**실행기 종류(`Loaded.kind`)** — 전략 클래스에 `on_minute` 이 있으면 `"minute"`(1분봉 실행기), `on_krx`·`on_quote`
가 있으면 `"realtime"`(실시간 실행기), 둘 다면 `LoadError`. 실시간 전략의 필수 이름은 `on_krx` `on_quote`
`on_timer` `filled_entry` `filled_exit` `p` 이고, Params 는 `Params` 또는 `LiveParams`(dataclass — 찾는 순서는
`_params_class` 와 같음)입니다. 실시간 전략엔 필수 Params 칸이 없습니다. 틱 가치는 `TICK_VALUE`, 없으면 `TICK_USD`.

**Params 시간 칸 채우기** — 1분봉 실행기가 읽는 6칸(`REQUIRED_PARAMS`) 중 장 시간 5칸(`SCHEDULE_PARAMS`)은
없어도 불러옵니다. 빠진 칸은 `Loaded.params_missing` 에 적고, 실행을 시작할 때 시장(`markets.Market`)으로
`Loaded.new(market)` 가 채웁니다(`fill_params`). 채우는 값:

    session_start = entry_start = 시장 장 시작 (국내 090000, 해외 082500)
    flatten_at    = Params 의 flatten_at, 없으면 시장 기본 (국내 153000, 해외 235000)
    entry_end     = 위 flatten_at (청산 시각까지 진입 가능 — 진입 판단은 전략이 함)
    session_end   = 시장 실행 끝 (국내 153100, 해외 235500)

`hold_min` 은 시장이 채우지 않습니다(없으면 `LoadError`). 채우기 전(시장 없이 `new()`)에는 Params 그대로입니다 —
칸을 지어내지 않습니다. 국내 1분봉 실행은 빠진 칸이 있으면 시작을 거부합니다(`live.prepare`).
파일 하나가 잘못돼도 앱이나 다른 실행에는 번지지 않습니다(`LoadError` 로만 알림).
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import inspect
import os
import re
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from backend import config
from backend.team_pyrun.markets import Market
from backend.team_pyrun.runner import EXIT_HOOK, TARGET_NAMES

#: 1분봉 전략 파라미터(`Params`) 칸 — 1분봉 실행기가 읽는 것. 이 중 `SCHEDULE_PARAMS` 는 없으면 시장이 채운다.
REQUIRED_PARAMS = ("session_start", "session_end", "entry_start", "entry_end", "flatten_at", "hold_min")
#: 없어도 되는 장 시간 칸 — 실행을 시작할 때 시장 시간표로 채운다(모듈 문서).
SCHEDULE_PARAMS = ("session_start", "session_end", "entry_start", "entry_end", "flatten_at")
#: Params 에 `flatten_at` 도 없을 때 시장마다 쓰는 청산 시각(국내는 week02 전략 값, 해외는 ORB 23:50).
DEFAULT_FLATTEN = {"domestic": "153000", "overseas": "235000"}
#: 1분봉 전략 인스턴스 필수 이름. `end_of_day`·`on_entry`·`on_exit`·`exit_reason`·`day`·`target` 은 없어도 된다.
REQUIRED_INSTANCE = ("on_minute", "p")
#: 실시간 전략 인스턴스 필수 이름(leadlag `Engine` 꼴). `pending`·`pos`·`stops` 는 있으면 화면에 쓴다.
REQUIRED_REALTIME = ("on_krx", "on_quote", "on_timer", "filled_entry", "filled_exit", "p")
#: 실시간 전략임을 알아보는 메서드 — 하나라도 있으면 실시간.
REALTIME_METHODS = ("on_krx", "on_quote")
#: 실행기 종류마다 찾는 Params 클래스 이름, 이 순서로.
PARAMS_NAMES = {"minute": ("Params",), "realtime": ("Params", "LiveParams")}
#: `TICK`·`TICK_VALUE` 가 없을 때 쓰는 값 — 미국달러선물(틱 0.1원 = 1,000원).
DEFAULT_TICK, DEFAULT_TICK_VALUE = 0.1, 1000
#: 익절 목표가 없을 때 목록에 남기는 알림(오류가 아님). 청산 판단 함수(`exit_reason`)가 있으면 남기지 않는다.
NO_TARGET_NOTE = "target·current_vwap 이 없어 익절 없이 돕니다"
#: 장 시간 칸이 빠졌을 때 목록에 남기는 알림(오류가 아님).
SCHEDULE_NOTE = "Params 에 없는 시간 칸({names})은 해외 실행을 시작할 때 시장 시간표로 채웁니다 (국내 실행은 이 칸이 있어야 합니다)"
#: 기본 공용 모듈 폴더. 폴더에 같은 이름 파일이 없을 때만 쓰인다(`sys.path` 에서 전략 폴더 다음).
BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"

#: `NAME` 은 실행 기록 폴더 이름에 들어간다 — 경로 문자가 섞이지 못하게 한다.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

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
    notes: list[str] = field(default_factory=list)   # 알림(오류 아님) — 예: 익절 목표가 없음


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
    kind: str = "minute"                        # "minute"(1분봉) | "realtime"(실시간)
    params_missing: tuple[str, ...] = ()        # Params 에 없는 장 시간 칸 — `new(market)` 가 채운다

    def new(self, market: Market | None = None) -> object:
        """새 전략 인스턴스. `market` 을 주면 빠진 장 시간 칸을 그 시장 값으로 채운 Params 로 만든다."""
        cls = self.params_cls if market is None else fill_params(self.params_cls, self.params_missing, market)
        return self.strategy_cls(cls())


def schedule_values(params: object, missing: tuple[str, ...], market: Market) -> dict[str, str]:
    """빠진 장 시간 칸에 넣을 값(모듈 문서의 표). `params` 는 그 Params 의 기본 인스턴스."""
    flatten = DEFAULT_FLATTEN[market.id] if "flatten_at" in missing else str(params.flatten_at)
    values = {"session_start": market.session_start, "entry_start": market.session_start,
              "entry_end": flatten, "flatten_at": flatten, "session_end": market.end_time}
    return {n: values[n] for n in missing}


def fill_params(params_cls: type, missing: tuple[str, ...], market: Market) -> type:
    """빠진 칸을 기본값으로 더한 Params 하위 클래스(같은 이름·같은 frozen). 빠진 칸이 없으면 그대로.

    하위 클래스라서 `isinstance` 와 전략의 다른 칸은 그대로이고, `asdict` 로 남기는 기록에도 채운 값이 보인다."""
    if not missing:
        return params_cls
    values = schedule_values(params_cls(), missing, market)
    frozen = params_cls.__dataclass_params__.frozen    # 부모와 frozen 이 다르면 dataclass 가 상속을 거부한다
    return dataclasses.make_dataclass(
        params_cls.__name__, [(n, str, field(default=v)) for n, v in values.items()],
        bases=(params_cls,), frozen=frozen, module=params_cls.__module__)


def strategies_dir() -> Path:
    """전략 폴더(`~/NHFutures/strategies`). 없으면 만든다."""
    path = config.HOME_DIR / "strategies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _inside(module: ModuleType, prefix: str | tuple[str, ...]) -> bool:
    """모듈 파일이 폴더(들) 안인가. 문자열 앞부분만 본다(`sys.path` 에 넣은 풀어 쓴 경로에서 왔으므로)."""
    file = getattr(module, "__file__", None)
    return isinstance(file, str) and file.startswith(prefix)


def _exec_module(folder: Path, file: str) -> tuple[ModuleType, str]:
    """파일을 따로 불러온다. 모듈과 파일 sha256 을 돌려준다. 실패는 `LoadError`."""
    folder = folder.resolve()
    builtin = BUILTIN_DIR.resolve()
    path = folder / file
    if not path.is_file():
        raise LoadError(f"파일이 없습니다: {file}")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with _LOCK:
        saved_path = list(sys.path)
        saved_dwb = sys.dont_write_bytecode
        saved_mods: dict[str, ModuleType] = {}
        modname = f"team_pyrun_{uuid.uuid4().hex}"
        try:   # 아래 준비 중 어디서 실패해도 finally 가 전부 되돌린다
            sys.dont_write_bytecode = True   # 옆 모듈을 불러올 때도 폴더에 pyc 를 쓰지 않는다
            # 폴더·기본 공용 모듈 파일 이름과 같은 이름의 모듈(앱·다른 곳에서 온 것)은 잠시 치워 둔다.
            for n in {p.stem for p in folder.glob("*.py")} | {p.stem for p in builtin.glob("*.py")}:
                if n in sys.modules:
                    saved_mods[n] = sys.modules.pop(n)
            sys.path.insert(0, str(folder))
            sys.path.insert(1, str(builtin))   # 폴더 다음 — 폴더에 strategy.py 가 있으면 그것이 먼저
            spec = importlib.util.spec_from_file_location(modname, path)
            if spec is None or spec.loader is None:
                raise LoadError(f"불러올 수 없는 파일입니다: {file}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[modname] = module   # dataclass 등이 모듈을 이름으로 찾는다
            exec(compile(data, str(path), "exec", dont_inherit=True), module.__dict__)   # 해시한 바이트 그대로
            return module, sha
        except LoadError:
            raise
        except (Exception, SystemExit) as e:   # 전략 파일 하나가 앱을 멈추지 않게 한다
            raise LoadError(f"{type(e).__name__}: {e}") from e
        finally:
            sys.path[:] = saved_path
            sys.dont_write_bytecode = saved_dwb
            prefix = (str(folder) + os.sep, str(builtin) + os.sep)   # 폴더와 기본 공용 모듈에서 온 것 모두
            for n, m in list(sys.modules.items()):   # 다른 스레드의 import 와 겹쳐도 안전하게 복사본을 훑는다
                if _inside(m, prefix):
                    sys.modules.pop(n, None)
            sys.modules.pop(modname, None)
            sys.modules.update(saved_mods)


def _has_any(cls: type, names: tuple[str, ...]) -> bool:
    return any(callable(getattr(cls, n, None)) for n in names)


def _candidates(module: ModuleType) -> list[type]:
    """그 파일에서 정의한(`__module__` 이 그 모듈인) 클래스 중 `on_minute`(1분봉) 또는 `on_krx`·`on_quote`(실시간)를
    부를 수 있는 것, 정의 순서대로. `from strategy import …` 로 가져온 클래스는 세지 않는다."""
    out: list[type] = []
    for value in vars(module).values():
        if (isinstance(value, type) and value.__module__ == module.__name__
                and _has_any(value, ("on_minute", *REALTIME_METHODS)) and value not in out):
            out.append(value)
    return out


def _kind(strategy_cls: type) -> str:
    """실행기 종류. `on_minute` 이면 1분봉, `on_krx`·`on_quote` 면 실시간, 둘 다면 `LoadError`.
    둘 다 없으면(`STRATEGY` 로 고른 클래스) 1분봉으로 보고 필수 이름 검사가 빠진 것을 알린다."""
    minute = callable(getattr(strategy_cls, "on_minute", None))
    realtime = _has_any(strategy_cls, REALTIME_METHODS)
    if minute and realtime:
        raise LoadError("on_minute(1분봉)과 on_krx·on_quote(실시간)를 한 전략 클래스에 함께 둘 수 없습니다 — 하나만 고르세요")
    return "realtime" if realtime else "minute"


def _is_strategy(module: ModuleType) -> bool:
    """전략 파일인가 — `STRATEGY` 가 있거나 `on_minute`(또는 실시간 `on_krx`·`on_quote`) 클래스를 정의했다. 아니면 공용 모듈."""
    return hasattr(module, "STRATEGY") or bool(_candidates(module))


def _strategy_class(module: ModuleType) -> type:
    """`STRATEGY` 가 있으면 그것, 없으면 그 파일의 전략 클래스(`_candidates`) 하나. 없거나 여럿이면 `LoadError`."""
    if hasattr(module, "STRATEGY"):
        return module.STRATEGY
    found = _candidates(module)
    if not found:
        raise LoadError("on_minute 이 있는 전략 클래스가 없습니다 (실시간 전략은 on_krx·on_quote)")
    if len(found) > 1:
        names = ", ".join(c.__name__ for c in found)
        raise LoadError(f"전략 클래스가 여러 개입니다 ({names}) — 파일 끝에 「STRATEGY = {found[0].__name__}」 처럼 하나를 고르세요")
    return found[0]


def _first_arg_type(strategy_cls: type) -> object:
    """전략 `__init__` 의 첫 인자(self 다음) 주석. 문자열 주석(`from __future__ import annotations`)도 풀어 본다. 없으면 None."""
    try:
        params = list(inspect.signature(strategy_cls.__init__, eval_str=True).parameters.values())
    except Exception:
        return None
    if len(params) < 2 or params[1].annotation is inspect.Parameter.empty:
        return None
    return params[1].annotation


def _params_class(module: ModuleType, strategy_cls: type, names: tuple[str, ...] = ("Params",)) -> type:
    """Params 클래스를 이 순서로 찾는다(모두 dataclass 여야 한다). 못 찾으면 `LoadError`.

    0. (실시간 전략만) 전략 `__init__` 첫 인자 주석이 이 파일에서 정의한 dataclass 면 그것
    1. 이 파일에서 정의한 `Params` (실시간 전략은 그다음 `LiveParams` — `names` 순서)
    2. 전략 `__init__` 첫 인자의 주석
    3. 가져온 `Params`(예: `from strategy import Params`) — 파일이 자기 Params 를 주석으로 밝혔는데
       가져온 것이 먼저 잡혀 엉뚱한 값으로 도는 일이 없게 마지막에 본다."""
    def ok(candidate: object) -> bool:
        return isinstance(candidate, type) and dataclasses.is_dataclass(candidate)

    found = [getattr(module, n, None) for n in names]
    annotated = _first_arg_type(strategy_cls)
    # 실시간 전략: 같은 파일에 Params 와 LiveParams 가 함께 있으면 `__init__` 이 밝힌 것(그 파일 정의)을 먼저 —
    # leadlag `Engine(p: LiveParams)` 이 옆의 다른 Params 로 돌지 않게
    if len(names) > 1 and ok(annotated) and annotated.__module__ == module.__name__:
        return annotated
    for own in found:
        if ok(own) and own.__module__ == module.__name__:
            return own
    if ok(annotated):
        return annotated
    for own in found:
        if ok(own):
            return own
    what = "·".join(names)
    raise LoadError(f"{what}(dataclass) 를 찾지 못했습니다")


def _first_line(doc: object) -> str | None:
    """문서 문자열의 비지 않은 첫 줄."""
    if isinstance(doc, str):
        for line in doc.splitlines():
            if line.strip():
                return line.strip()
    return None


def _module_title(doc: object) -> str | None:
    """모듈 문서 첫 줄에서 제목만 — 첫 「 — 」 앞까지, 끝의 「.」 은 뺀다.
    (`볼린저 밴드 + RSI 평균회귀 전략 — 판정 규칙 한 벌 (2주차 후보 2).` → `볼린저 밴드 + RSI 평균회귀 전략`)"""
    line = _first_line(doc)
    if line is None:
        return None
    title = line.split(" — ", 1)[0].strip().removesuffix(".").strip()
    return title or None


@dataclass(frozen=True)
class _Checked:
    """약속 검사를 통과한 전략 파일의 내용."""

    strategy_cls: type
    params_cls: type
    instance: object
    name: str
    title: str
    tick: float
    tick_value: float
    notes: list[str]
    kind: str
    params_missing: tuple[str, ...]


def _check(module: ModuleType, file: str) -> _Checked:
    """약속을 검사한다. 어기면 까닭(빠진 이름은 모두)을 적어 `LoadError`."""
    strategy_cls = _strategy_class(module)
    if hasattr(module, "NAME"):
        name = str(module.NAME)
        if not NAME_PATTERN.fullmatch(name):
            raise LoadError(f"NAME 은 영문·숫자·_·- 만 쓸 수 있습니다: {module.NAME!r}")
    else:
        name = re.sub(r"[^A-Za-z0-9_-]", "_", Path(file).stem)   # 실행 기록 폴더 이름에 들어가도 되게
    if hasattr(module, "TITLE"):
        title = str(module.TITLE)
    else:
        # 클래스 문서는 대개 메서드 설명(「1분봉을 넣으면 …」)이라 모듈 문서의 제목이 먼저다
        title = (_module_title(module.__doc__) or _first_line(getattr(strategy_cls, "__doc__", None))
                 or getattr(strategy_cls, "__name__", name))
    try:
        tick = float(getattr(module, "TICK", DEFAULT_TICK))
        # 틱 가치: TICK_VALUE, 없으면 TICK_USD(leadlag), 둘 다 없으면 미국달러선물 값
        tick_value = float(getattr(module, "TICK_VALUE", getattr(module, "TICK_USD", DEFAULT_TICK_VALUE)))
    except (TypeError, ValueError) as e:
        raise LoadError(f"TICK·TICK_VALUE(또는 TICK_USD) 는 숫자여야 합니다: {e}") from e
    kind = _kind(strategy_cls)
    params_cls = _params_class(module, strategy_cls, PARAMS_NAMES[kind])
    notes: list[str] = []
    try:
        params = params_cls()
        absent: tuple[str, ...] = ()
        if kind == "minute":
            absent = tuple(n for n in REQUIRED_PARAMS if not hasattr(params, n))
            hard = [n for n in absent if n not in SCHEDULE_PARAMS]     # 시장이 채우지 못하는 칸
            if hard:
                raise LoadError("Params 에 없는 이름: " + ", ".join(hard))
        instance = strategy_cls(params)
        required = REQUIRED_INSTANCE if kind == "minute" else REQUIRED_REALTIME
        inst_missing = [n for n in required if not hasattr(instance, n)]
        if inst_missing:
            raise LoadError("전략에 없는 이름: " + ", ".join(inst_missing))
        if kind == "minute":
            if not callable(instance.on_minute):
                raise LoadError("on_minute 은 부를 수 있는 메서드여야 합니다")
            if hasattr(instance, EXIT_HOOK) and not callable(getattr(instance, EXIT_HOOK)):
                raise LoadError(f"{EXIT_HOOK} 은 부를 수 있는 메서드여야 합니다")
            # 청산을 전략이 판단하면 앱의 익절 규칙을 쓰지 않으므로 익절 목표 알림이 필요 없다
            if not any(hasattr(instance, n) for n in (*TARGET_NAMES, EXIT_HOOK)):
                notes.append(NO_TARGET_NOTE)
            if absent:
                notes.append(SCHEDULE_NOTE.format(names=", ".join(absent)))
    except LoadError:
        raise
    except Exception as e:
        raise LoadError(f"{type(e).__name__}: {e}") from e
    return _Checked(strategy_cls, params_cls, instance, name, title, tick, tick_value, notes, kind, absent)


def load(folder: Path, file: str) -> Loaded:
    """전략 파일 하나를 불러온다. 못 쓰는 파일은 `LoadError`."""
    module, sha = _exec_module(folder, file)
    c = _check(module, file)
    return Loaded(
        file=file,
        name=c.name,
        title=c.title,
        sha256=sha,
        strategy_cls=c.strategy_cls,
        params_cls=c.params_cls,
        tick=c.tick,
        tick_value=c.tick_value,
        kind=c.kind,
        params_missing=c.params_missing,
    )


def scan_all(folder: Path) -> tuple[list[StrategyFile], list[str]]:
    """폴더의 `*.py` 를 한 번 훑어 (전략 목록, 공용 모듈 이름들)을 돌려준다. 파일마다 한 번만 불러온다.

    전략 목록은 전략 파일(`STRATEGY` 가 있거나 `on_minute`·`on_krx`·`on_quote` 클래스를 정의한 파일)이거나 불러오기에 실패한 파일
    (파일 이름순). 공용 모듈은 오류 없이 불러와지지만 전략 파일이 아닌 것(이름순) — 전략 파일이
    `from strategy import …` 처럼 불러 쓰는 공용 코드다. 기본 공용 모듈(`builtin/`)은 어느 쪽에도 없다.
    """
    out: list[StrategyFile] = []
    modules: list[str] = []
    for path in sorted(Path(folder).glob("*.py"), key=lambda p: p.name):
        file = path.name
        try:
            module, _ = _exec_module(folder, file)
        except LoadError as e:
            out.append(StrategyFile(file, None, None, None, str(e)))
            continue
        if not _is_strategy(module):
            modules.append(file)
            continue
        name = getattr(module, "NAME", None)
        title = getattr(module, "TITLE", None)
        name = None if name is None else str(name)
        title = None if title is None else str(title)
        try:
            c = _check(module, file)
            params: dict[str, Any] | None = dataclasses.asdict(c.instance.p)
            out.append(StrategyFile(file, c.name, c.title, params, None, c.notes))
        except LoadError as e:
            out.append(StrategyFile(file, name, title, None, str(e)))
    return out, modules


def scan(folder: Path) -> list[StrategyFile]:
    """폴더의 `*.py` 중 전략 파일이거나 불러오기에 실패한 것만, 파일 이름순으로.

    전략 파일이 아닌 정상 모듈(공용 코드)은 목록에서 뺀다 — 이름은 `scan_all` 의 두 번째 값.
    """
    return scan_all(folder)[0]
