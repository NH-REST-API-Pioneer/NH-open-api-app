"""판단 부분만 골라 쓰기 — 실행기(접속·주문·기록)와 전략(판단)이 한 파일에 같이 든 전략 파일.

week03 `ws_trader.py` 처럼 팀원이 쓴 파일에는 판단(`Engine`·`LiveParams`·`TICK`…)과 실행기(`Trader`·`main`,
`nh_client`·`fee_test`·`ws_probe` import)가 함께 있습니다. 앱에는 실행기 쪽 모듈이 없어 그대로 불러오면
`ModuleNotFoundError` 입니다. 그래서 불러오기(`loader._exec_module`)는 파일을 **실행하기 전에** 맨 위 import 를 문법으로만
훑어(`unresolved`), 앱 환경에서 못 찾는 모듈이 있으면 **그 모듈을 쓰는 문장만 빼고** 나머지를 원래 순서·원래 줄 번호
그대로 실행합니다(`pick`). 못 찾는 모듈이 없으면 지금까지처럼 파일 전체를 실행합니다 — 보통 전략 파일은 달라지지 않습니다.

**빼는 것 (그 밖에는 파일 전체를 실행할 때와 똑같음)**

    없는 모듈의 import        `import nh_client` · `from fee_test import wait_filled` (한 줄에 섞였으면 그 이름만)
    실행할 때 바로 그 이름을 쓰는 맨 위 문장   예: `CLIENT = NHClient()` · `class X(NHClient):` · `@없는것` 데코레이터
    함수·클래스 안에서 그 이름을 쓰는 정의      예: `class Trader:` (메서드가 `NHClient` 를 씀) · `def main():` (`Trader` 를 씀)
    위에서 뺀 이름을 다시 쓰는 것               끝까지 따라감(`if __name__ == "__main__": main()` 도 빠짐)

이름의 범위는 `symtable` 로 정확히 봅니다 — 메서드 안의 지역 변수 `rows` 는 `from nh_client import rows` 와 다른 이름입니다.
`from __future__ import annotations` 면 주석(annotation)은 실행되지 않으므로 빼는 까닭으로 치지 않습니다.

**막는 것 (`PickError` — 조용히 다른 값으로 돌지 않게)**

- 전략 클래스가 없는 모듈을 쓰면(판단과 주문이 섞임, 또는 옆 파일을 같이 안 올림) — 어느 이름이 어느 모듈인지 알림
- 앱이 모듈에서 읽는 이름(`STRATEGY` `Params` `LiveParams` `TICK` `TICK_VALUE` `TICK_USD` `TITLE` `NAME`)을 묶는 문장이 빠지면
  — 예: `from 없는것 import TICK` 이면 TICK 이 기본값 0.1 이 되어 시장이 바뀌므로
- 전략 클래스처럼 보이는 것(`on_minute`·`on_krx`·`on_quote` 메서드를 직접 가진 클래스, `STRATEGY`)이 파일에 하나도 없으면 —
  예전과 같은 `ModuleNotFoundError` 문장(골라 쓸 대상이 아닌 공용 모듈 등)
"""
from __future__ import annotations

import ast
import builtins
import copy
import importlib.util
import symtable
from dataclasses import dataclass

#: 골라 쓴 모듈에 붙이는 표지 이름 — 값은 `Picked`.
DECISION_ATTR = "__team_decision__"
#: 앱이 모듈에서 이름으로 읽는 것 — 이것을 묶는 문장이 빠지면 막는다.
MODULE_NAMES = ("STRATEGY", "Params", "LiveParams", "TICK", "TICK_VALUE", "TICK_USD", "TITLE", "NAME")
#: 전략 클래스임을 알아보는 메서드.
STRATEGY_METHODS = ("on_minute", "on_krx", "on_quote")
_BUILTINS = frozenset(dir(builtins))


class PickError(Exception):
    """판단 부분을 골라 낼 수 없음 — 메시지가 그대로 화면에 간다."""


@dataclass(frozen=True)
class Picked:
    """골라 쓴 결과. `module` 은 뺀 문장을 덜어 낸 새 `ast.Module`(원래 줄 번호)."""

    module: ast.Module
    dropped: tuple[str, ...]       # 뺀 맨 위 문장의 표시(이름, 이름이 없으면 「줄 N」) — 원래 순서
    missing: tuple[str, ...]       # 앱 환경에서 못 찾은 모듈

    def note(self, strategy: str) -> str:
        return (f"실행기와 판단이 한 파일 — 판단 {strategy} 만 씀 · 앱에 없는 모듈({', '.join(self.missing)})을 써서 "
                "실행하지 않는 부분: " + (", ".join(self.dropped) or "없음"))


# ---------------------------------------------------------------- 모듈 찾기
def _import_roots(node: ast.stmt) -> list[str]:
    """import 문이 부르는 맨 위 모듈 이름들. `from __future__`·상대 import 는 빈 목록."""
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module != "__future__":
        return [node.module.split(".")[0]]
    return []


def unresolved(tree: ast.Module) -> list[str]:
    """맨 위 import 중 **지금 `sys.path` 에서** 찾을 수 없는 모듈(순서대로, 중복 없이). 실행하지 않고 찾기만 한다.
    부르는 쪽이 전략 폴더·기본 공용 모듈 경로를 넣은 뒤에 불러야 옆 파일·`strategy` 를 찾는다.
    찾는 중 오류(`sys.modules` 에 있는데 `__spec__` 이 없는 모듈 등)는 「있음」으로 본다 — 예전처럼 전체를 실행하게."""
    out: list[str] = []
    for node in tree.body:
        for root in _import_roots(node):
            if root in out:
                continue
            try:
                found = importlib.util.find_spec(root) is not None
            except (ImportError, ValueError):
                found = True
            if not found:
                out.append(root)
    return out


# ---------------------------------------------------------------- 이름
def _annotation_ids(node: ast.AST) -> set[int]:
    """노드 안의 주석(annotation) 부분트리에 든 노드 id."""
    out: set[int] = set()
    for sub in ast.walk(node):
        ann = None
        if isinstance(sub, ast.arg):
            ann = sub.annotation
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ann = sub.returns
        elif isinstance(sub, ast.AnnAssign):
            ann = sub.annotation
        if ann is not None:
            out |= {id(n) for n in ast.walk(ann)}
    return out


def _loads(nodes: list[ast.AST], lazy: bool) -> set[str]:
    """노드들 안에서 읽는 이름(주석은 `lazy` 면 뺌)."""
    out: set[str] = set()
    for node in nodes:
        skip = _annotation_ids(node) if lazy else set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Load, ast.Del)) and id(sub) not in skip:
                out.add(sub.id)
    return out


def _def_header(node: ast.FunctionDef | ast.AsyncFunctionDef, lazy: bool) -> list[ast.AST]:
    """정의할 때 바로 실행되는 부분 — 데코레이터·기본값(·주석)."""
    a = node.args
    parts: list[ast.AST] = [*node.decorator_list, *a.defaults, *(d for d in a.kw_defaults if d is not None)]
    if not lazy:
        parts += [x.annotation for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg)
                  if x is not None and x.annotation is not None]
        if node.returns is not None:
            parts.append(node.returns)
    return parts


def _eager(node: ast.stmt, lazy: bool) -> set[str]:
    """맨 위 문장을 실행할 때 바로 읽는 이름. 함수 몸은 빼고(부를 때 실행), 클래스 몸은 넣는다(정의할 때 실행)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _loads(_def_header(node, lazy), lazy)
    if isinstance(node, ast.ClassDef):
        parts: list[ast.AST] = [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]
        for stmt in node.body:
            parts.extend(_def_header(stmt, lazy) if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) else [stmt])
        return _loads(parts, lazy)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return set()
    return _loads([node], lazy)          # 그 밖(대입·식·if·for·try·with…)은 통째로 — 넉넉하게


def _table_globals(table: symtable.SymbolTable) -> set[str]:
    """그 범위와 안쪽 범위가 모듈 이름으로 읽거나 쓰는 것(`global X` 포함). 지역 변수는 뺀다."""
    out: set[str] = set()
    for sym in table.get_symbols():
        if sym.is_global() and (sym.is_referenced() or sym.is_assigned()):
            out.add(sym.get_name())
    for child in table.get_children():
        out |= _table_globals(child)
    return out


def _bound(node: ast.stmt, top: set[str]) -> list[str]:
    """맨 위 문장이 묶는 모듈 이름. 복합문(if·for·try·with)은 그 안에서 묶는 모듈 이름 전부(`top` = 모듈 범위 이름)."""
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return []
        return [(a.asname or a.name.split(".")[0]) for a in node.names if a.name != "*"]
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store) and sub.id in top and sub.id not in out:
            out.append(sub.id)
        elif isinstance(sub, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name in top \
                and sub.name not in out:
            out.append(sub.name)
    return out


def _label(node: ast.stmt, names: list[str]) -> str:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
            and node.test.left.id == "__name__":
        return f'줄 {node.lineno} if __name__ == "__main__"'
    return " · ".join(names) if names else f"줄 {node.lineno}"


def _is_strategy_class(node: ast.stmt) -> bool:
    return isinstance(node, ast.ClassDef) and any(
        isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name in STRATEGY_METHODS for b in node.body)


# ---------------------------------------------------------------- 고르기
def pick(tree: ast.Module, source: str, filename: str, missing: list[str]) -> Picked:
    """없는 모듈을 쓰는 문장을 덜어 낸 모듈을 만든다. 못 하면 `PickError`(까닭은 메시지)."""
    lazy = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)
    top_table = symtable.symtable(source, filename, "exec")
    top_names = {s.get_name() for s in top_table.get_symbols()}
    tables: dict[tuple[str, int], symtable.SymbolTable] = {
        (c.get_name(), c.get_lineno()): c for c in top_table.get_children()}
    missing_set = set(missing)

    body = list(tree.body)
    tainted: dict[str, str] = {}        # 쓸 수 없는 이름 → 그 까닭 모듈
    star_missing: str | None = None      # `from 없는것 import *` — 어떤 이름이 들어올지 모름
    for i, node in enumerate(body):     # 1) 없는 모듈의 import — 섞였으면 그 이름만 뺀다
        if isinstance(node, ast.Import):
            bad = [a for a in node.names if a.name.split(".")[0] in missing_set]
            for a in bad:
                tainted[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
            if bad and len(bad) < len(node.names):
                keep = copy.copy(node)
                keep.names = [a for a in node.names if a not in bad]
                body[i] = keep
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                and node.module.split(".")[0] in missing_set:
            mod = node.module.split(".")[0]
            for a in node.names:
                if a.name == "*":
                    star_missing = mod
                else:
                    tainted[a.asname or a.name] = mod

    defined = {n for node in tree.body for n in _bound(node, top_names)}
    eager = [_eager(node, lazy) for node in body]
    later: list[set[str]] = []
    for node in body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            table = tables.get((node.name, node.lineno))
            later.append(_table_globals(table) if table is not None else _loads(node.body, lazy))
        else:
            later.append(set())
    bound = [_bound(node, top_names) for node in body]
    dropped: dict[int, str] = {}         # 문장 번호 → 까닭(이름(모듈))
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and _import_roots(node) \
                and all(r in missing_set for r in _import_roots(node)):
            dropped[i] = f"import {', '.join(_import_roots(node))}"

    def bad_names(names: set[str]) -> list[str]:
        out = [f"{n}({tainted[n]})" for n in sorted(names) if n in tainted]
        if star_missing:     # 어디에도 묶이지 않은 이름은 `from 없는것 import *` 에서 왔을 수 있다
            out += [f"{n}({star_missing})" for n in sorted(names)
                    if n not in tainted and n not in defined and n not in _BUILTINS]
        return out

    changed = True
    while changed:                       # 2) 뺀 이름을 쓰는 문장을 끝까지 뺀다
        changed = False
        for i, node in enumerate(body):
            if i in dropped:
                continue
            why = bad_names(eager[i]) or bad_names(later[i])
            if why:
                dropped[i] = ", ".join(why)
                for n in bound[i]:
                    tainted.setdefault(n, why[0].split("(")[-1].rstrip(")"))
                changed = True

    strategy_like = [i for i, n in enumerate(tree.body) if _is_strategy_class(n)
                     or "STRATEGY" in bound[i]]
    if not strategy_like:
        raise PickError(f"ModuleNotFoundError: No module named {missing[0]!r}")
    if all(i in dropped for i in strategy_like):
        parts = [f"{_label(tree.body[i], bound[i])} 이 {dropped[i]}" for i in strategy_like]
        raise PickError("전략 클래스가 앱에 없는 모듈을 씁니다: " + "; ".join(parts)
                        + ". 옆 파일이면 같이 올리고, 설치되지 않은 패키지이거나 실행기(접속·주문) 모듈이면"
                        " 판단(진입·청산을 정하는 클래스)과 나눠 주세요")
    lost = [(n, dropped[i]) for i in dropped for n in bound[i] if n in MODULE_NAMES]
    if lost:
        raise PickError("앱이 읽는 이름이 앱에 없는 모듈에 기대어 빠집니다: "
                        + ", ".join(f"{n} ← {why}" for n, why in lost)
                        + " — 그대로 두면 기본값으로 돌아 시장·틱이 바뀝니다. 이 값을 파일에 직접 적어 주세요")
    kept_body = [node for i, node in enumerate(body) if i not in dropped]
    labels = tuple(_label(tree.body[i], bound[i]) for i in sorted(dropped)
                   if not isinstance(tree.body[i], (ast.Import, ast.ImportFrom)))
    return Picked(ast.Module(body=kept_body, type_ignores=[]), labels, tuple(missing))
