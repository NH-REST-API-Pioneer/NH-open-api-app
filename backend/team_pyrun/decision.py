"""판단 부분만 골라 쓰기 — 실행기(접속·주문·기록)와 전략(판단)이 한 파일에 같이 든 전략 파일.

week03 `ws_trader.py` 처럼 팀원이 쓴 파일에는 판단(`Engine`·`LiveParams`·`TICK`…)과 실행기(`Trader`·`Recorder`·
`main`, `websockets`·`nh_client`·`fee_test` import)가 함께 있습니다. 앱에는 실행기 쪽 모듈이 없어 그대로 불러오면
`ModuleNotFoundError` 입니다. 그래서 불러오기(`loader._exec_module`)는 파일을 **실행하기 전에** 맨 위 import 를 문법으로만
훑어(`unresolved`), 앱 환경에서 못 찾는 모듈이 있으면 **전략 클래스가 실제로 쓰는 이름만 따라가** 그 부분만 실행합니다
(`pick`). 못 찾는 모듈이 없으면 지금까지처럼 파일 전체를 실행합니다 — 보통 전략 파일은 달라지지 않습니다.

    뿌리    = 그 파일에서 정의한 전략 클래스(`on_minute` 또는 `on_krx`·`on_quote` 메서드를 가진 클래스, `STRATEGY` 가 있으면 그것)
              + 앱이 모듈에서 읽는 이름(`Params` `LiveParams` `TICK` `TICK_VALUE` `TICK_USD` `TITLE` `NAME` `STRATEGY`)
    따라가기 = 뿌리가 쓰는 맨 위 이름(클래스·함수·값·import)을 끝까지. 주석(annotation)은 `from __future__ import annotations`
              면 실행되지 않으므로 그 안의 이름은 파일에서 정의한 것만 따라감(import 는 안 따라감)
    남김    = 모듈 문서·`from __future__`·따라간 맨 위 문장 — **원래 순서·원래 줄 번호 그대로**(오류 줄 번호가 원본과 같게)
    버림    = 나머지 전부: 실행기 클래스·`main`·`if __name__ == "__main__":`·못 찾는 import·그 밖의 맨 위 문장

전략 클래스가 못 찾는 모듈을 직접 쓰면(판단과 주문이 섞인 파일) 골라 쓸 수 없습니다 — 어느 이름이 어느 모듈을 쓰는지
`LoadError` 메시지로 알립니다. 전략 클래스가 여럿이면, 못 찾는 모듈을 쓰지 않는 것만 남깁니다(그래도 여럿이면 `STRATEGY` 를 고르라는
보통 오류). 골라 쓴 모듈에는 `DECISION_ATTR` 에 남긴 이름·버린 이름·못 찾은 모듈을 적어 두고, 목록에 알림으로 보입니다.
"""
from __future__ import annotations

import ast
import builtins
import importlib.util
from dataclasses import dataclass

#: 골라 쓴 모듈에 붙이는 표지 이름 — 값은 `Picked`.
DECISION_ATTR = "__team_decision__"
#: 앱이 모듈에서 이름으로 읽는 것 — 있으면 뿌리로 남긴다.
MODULE_NAMES = ("STRATEGY", "Params", "LiveParams", "TICK", "TICK_VALUE", "TICK_USD", "TITLE", "NAME")
#: 전략 클래스임을 알아보는 메서드.
STRATEGY_METHODS = ("on_minute", "on_krx", "on_quote")
_BUILTINS = frozenset(dir(builtins))


class PickError(Exception):
    """판단 부분을 골라 낼 수 없음 — 메시지가 그대로 화면에 간다."""


@dataclass(frozen=True)
class Picked:
    """골라 쓴 결과. `module` 은 남긴 문장만 든 새 `ast.Module`."""

    module: ast.Module
    kept: tuple[str, ...]          # 남긴 맨 위 이름(원래 순서, import 빼고)
    dropped: tuple[str, ...]       # 버린 맨 위 이름(원래 순서, import 빼고 — 못 찾은 모듈은 `missing`)
    missing: tuple[str, ...]       # 앱 환경에서 못 찾은 모듈

    def note(self) -> str:
        return ("판단 부분만 불러옴 — 쓴 것: " + ", ".join(self.kept)
                + " · 안 쓴 것(앱이 맡음): " + (", ".join(self.dropped) or "없음")
                + " · 앱에 없는 모듈: " + ", ".join(self.missing))


def _import_roots(node: ast.stmt) -> list[str]:
    """import 문이 부르는 맨 위 모듈 이름들. `from __future__`·상대 import 는 빈 목록."""
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module != "__future__":
        return [node.module.split(".")[0]]
    return []


def unresolved(tree: ast.Module) -> list[str]:
    """맨 위 import 중 **지금 `sys.path` 에서** 찾을 수 없는 모듈(순서대로, 중복 없이). 실행하지 않고 찾기만 한다.
    부르는 쪽이 전략 폴더·기본 공용 모듈 경로를 넣은 뒤에 불러야 옆 파일·`strategy` 를 찾는다."""
    out: list[str] = []
    for node in tree.body:
        for root in _import_roots(node):
            if root in out:
                continue
            try:
                found = importlib.util.find_spec(root) is not None
            except (ImportError, ValueError):
                found = False
            if not found:
                out.append(root)
    return out


def _bound(node: ast.stmt) -> list[str]:
    """맨 위 문장이 묶는 이름."""
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return []
        return [(a.asname or a.name.split(".")[0]) for a in node.names]
    return []


def _annotations(node: ast.AST) -> list[ast.AST]:
    """노드 안의 주석(annotation) 부분트리 — `from __future__ import annotations` 면 실행되지 않는다."""
    out: list[ast.AST] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.arg) and sub.annotation is not None:
            out.append(sub.annotation)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.returns is not None:
            out.append(sub.returns)
        elif isinstance(sub, ast.AnnAssign):
            out.append(sub.annotation)
    return out


def _names(node: ast.AST, lazy_annotations: bool) -> tuple[set[str], set[str]]:
    """(실행될 때 읽는 이름, 주석 안에서만 읽는 이름)."""
    soft_nodes = {id(n) for a in _annotations(node) for n in ast.walk(a)} if lazy_annotations else set()
    hard: set[str] = set()
    soft: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            (soft if id(sub) in soft_nodes else hard).add(sub.id)
    return hard - _BUILTINS, soft - _BUILTINS


def _is_strategy_class(node: ast.stmt) -> bool:
    return isinstance(node, ast.ClassDef) and any(
        isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name in STRATEGY_METHODS for b in node.body)


def pick(tree: ast.Module, missing: list[str]) -> Picked:
    """판단 부분만 남긴 모듈을 만든다. 못 하면 `PickError`(까닭은 메시지)."""
    lazy = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)
    defs: dict[str, int] = {}                       # 이름 → 그것을 (마지막으로) 묶는 맨 위 문장 번호
    for i, node in enumerate(tree.body):
        for name in _bound(node):
            defs[name] = i
    missing_set = set(missing)
    import_of: dict[int, str] = {}                  # 못 찾는 모듈을 부르는 import 문 번호 → 모듈
    for i, node in enumerate(tree.body):
        bad = [r for r in _import_roots(node) if r in missing_set]
        if bad:
            import_of[i] = bad[0]

    def closure(start: list[int]) -> tuple[set[int], dict[str, str]]:
        """문장 번호들에서 따라간 문장 번호와, 그 가운데 못 찾는 모듈을 쓰는 이름 → 모듈."""
        seen: set[int] = set()
        bad: dict[str, str] = {}
        todo = list(start)
        while todo:
            i = todo.pop()
            if i in seen:
                continue
            seen.add(i)
            node = tree.body[i]
            hard, soft = _names(node, lazy)
            for name in hard:
                j = defs.get(name)
                if j is None:
                    continue
                if j in import_of:
                    bad[name] = import_of[j]
                todo.append(j)
            for name in soft:                       # 주석 속 이름 — 파일에서 정의한 것만(import 는 실행되지 않음)
                j = defs.get(name)
                if j is not None and not isinstance(tree.body[j], (ast.Import, ast.ImportFrom)):
                    todo.append(j)
        return seen, bad

    strategy_idx = defs.get("STRATEGY")
    if strategy_idx is not None:
        classes = [strategy_idx]
    else:
        classes = [i for i, n in enumerate(tree.body) if _is_strategy_class(n)]
    if not classes:
        raise PickError("ModuleNotFoundError: No module named " + repr(missing[0])
                        + " — 전략 클래스(on_minute 또는 on_krx·on_quote)도 찾지 못했습니다")
    usable, blocked = [], []
    for i in classes:
        _, bad = closure([i])
        (blocked if bad else usable).append((i, bad))
    if not usable:
        parts = [f"{tree.body[i].name if hasattr(tree.body[i], 'name') else 'STRATEGY'} 이 "
                 + ", ".join(f"{name}({mod})" for name, mod in sorted(bad.items()))
                 for i, bad in blocked]
        raise PickError("판단 부분을 골라 쓸 수 없습니다 — 전략 클래스가 앱에 없는 모듈을 직접 씁니다: " + "; ".join(parts)
                        + ". 판단(진입·청산을 정하는 클래스)과 실행기(접속·주문)를 나눠 주세요")
    roots = [i for i, _ in usable]
    for name in MODULE_NAMES:                        # 앱이 모듈에서 읽는 이름
        j = defs.get(name)
        if j is not None and j not in import_of:
            roots.append(j)
    keep, bad = closure(roots)
    if bad:     # 뿌리 쪽 이름(예: TICK = 실행기 모듈의 값)이 못 찾는 모듈을 쓴다
        raise PickError("판단 부분을 골라 쓸 수 없습니다 — 앱에 없는 모듈을 쓰는 이름: "
                        + ", ".join(f"{name}({mod})" for name, mod in sorted(bad.items())))
    body: list[ast.stmt] = []
    kept: list[str] = []
    dropped: list[str] = []
    for i, node in enumerate(tree.body):
        doc = i == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
            and isinstance(node.value.value, str)
        future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        is_import = isinstance(node, (ast.Import, ast.ImportFrom))
        if doc or future or i in keep:
            body.append(node)
            if not is_import:
                kept.extend(_bound(node))
        elif not is_import:                          # 버린 import 는 이름 대신 못 찾은 모듈로 알린다
            dropped.extend(_bound(node) or [_label(node)])
    module = ast.Module(body=body, type_ignores=[])
    return Picked(module, tuple(kept), tuple(n for n in dropped if n), tuple(missing))


def _label(node: ast.stmt) -> str:
    """이름 없는 맨 위 문장의 표시 — `if __name__ == "__main__":` 만 이름을 붙이고 나머지는 빈 글자(목록에 안 적음)."""
    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
            and node.test.left.id == "__name__":
        return "__main__"
    return ""
