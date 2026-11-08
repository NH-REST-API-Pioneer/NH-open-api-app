"""스프레드 실행 세우기 — 실행기 `LEGS`(또는 시작 화면 표기)를 `Leg` 로: 마스터 + 필요한 품목 세부정보 + 틱 확인.

`SpreadRun.prepare` 와 registry(폴더를 만들기 전 거부·같은 종목 검사)가 같은 함수를 쓴다. 거부는 모두 `StartRefused`
(판정 R2: `team_pyrun.live.StartRefused`). 해외 품목 세부정보는 그룹마다 따로 묻는다(판정 R4).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.overseas_futureoption.overseas_hours import PRODUCT_GROUPS
from backend.team_pyrun import api as default_api
from backend.team_pyrun.apilog import purpose
from backend.team_pyrun.live import StartRefused
from backend.team_spread.legs import Leg, LegError, resolve
from backend.team_spread.runner_files import LoadedRunner

#: 팀이 쓰는 통화(FG2 — MKU)·에너지(FG6 — HO·RB) 그룹을 먼저 묻고, 필요한 품목을 다 찾으면 멈춘다
FIRST_GROUPS = ("FG2", "FG6")
DETAIL_MAX_PAGES = 10


def _s(row: dict | None, key: str) -> str:
    return str((row or {}).get(key, "")).strip()


@dataclass(frozen=True)
class Sources:
    """다리 찾기에 쓴 마스터 줄과 품목 세부정보 — 월물 교체 때 다시 쓴다."""

    overseas_rows: list[dict]
    domestic_rows: list[dict]
    overseas_details: list[dict]
    domestic_details: list[dict]

    def kw(self) -> dict[str, list[dict]]:
        return {"overseas_rows": self.overseas_rows, "domestic_rows": self.domestic_rows,
                "overseas_details": self.overseas_details, "domestic_details": self.domestic_details}


def leg_specs(loaded: LoadedRunner, syms: dict[str, str] | None) -> dict[str, str]:
    """다리 → 표기. `syms` 가 실행기에 없는 다리를 말하면 `StartRefused`."""
    extra = sorted(set(syms or {}) - set(loaded.legs))
    if extra:
        raise StartRefused(f"실행기에 없는 다리입니다: {', '.join(extra)}")
    return {name: (syms or {}).get(name) or spec for name, spec in loaded.legs.items()}


def overseas_details(products: set[str], api_module: Any) -> list[dict]:
    """해외 품목 세부정보 — 필요한 품목이 다 나올 때까지 그룹을 차례로, 그룹마다 `nxt_key` 쪽을 따라."""
    got: list[dict] = []
    left = set(products)
    for group in sorted(PRODUCT_GROUPS, key=lambda g: g not in FIRST_GROUPS):
        key, used = "", set()
        for _ in range(DETAIL_MAX_PAGES):
            rows, key = api_module.ovs_product_detail_page(group, key)
            got += rows
            left -= {_s(r, "prd_cd") for r in rows}
            if not key or key in used:
                break
            used.add(key)
        if not left:
            break
    return got


def load_sources(specs: dict[str, str], *, api_module: Any, master: Callable[[], tuple[list, list]]) -> Sources:
    """마스터(파일)와 필요한 품목 세부정보(조회). 해외 표기가 없으면 해외 세부정보를, 국내가 없으면 국내를 묻지 않는다."""
    ovs, dom = master()
    wanted = set(specs.values())
    products = {_s(r, "comd") for r in ovs if _s(r, "code") in wanted or _s(r, "comd") in wanted}
    known = {_s(r, "code") for r in ovs} | {_s(r, "comd") for r in ovs}
    with purpose("품목 세부정보"):
        ovs_details = overseas_details(products, api_module) if products else []
        dom_details = api_module.product_detail() if wanted - known else []
    return Sources(ovs, dom, ovs_details, dom_details)


def check_ticks(legs: dict[str, Leg], details: list[dict]) -> None:
    """해외 다리의 틱·틱 가치(마스터)를 품목 세부정보(`tick_unt`·`tick_val`)와 맞춰 본다 — 다르면 `StartRefused`.
    국내는 `resolve` 가 세부정보 틱으로 이미 맞춰 본다."""
    for leg in legs.values():
        if leg.market != "overseas":
            continue
        row = next((d for d in details if _s(d, "prd_cd") == leg.product), None)
        tick, value = default_api.num(_s(row, "tick_unt")), default_api.num(_s(row, "tick_val"))
        if not tick or not value:
            raise StartRefused(f"{leg.name}({leg.sym}) 의 틱을 품목 세부정보에서 읽지 못했습니다")
        if not (math.isclose(tick, leg.tick, rel_tol=1e-9) and math.isclose(value, leg.tick_value, rel_tol=1e-9)):
            raise StartRefused(f"{leg.name}({leg.sym}) 틱·틱가치가 마스터({leg.tick:g}·{leg.tick_value:g})와 "
                               f"품목 세부정보({tick:g}·{value:g})가 다릅니다")


def resolve_legs(specs: dict[str, str], sources: Sources, *, today: str) -> dict[str, Leg]:
    """표기 → `Leg`, 틱 확인, 두 다리가 같은 종목이면 거부(잔고 관문이 한 계좌 보유를 나눠 볼 수 없음)."""
    legs: dict[str, Leg] = {}
    for name, spec in specs.items():
        try:
            legs[name] = resolve(name, spec, **sources.kw(), today=today)
        except LegError as e:
            raise StartRefused(f"다리 {name}: {e}") from e
    check_ticks(legs, sources.overseas_details)
    syms = [leg.sym for leg in legs.values()]
    if len(set(syms)) != len(syms):
        raise StartRefused(f"두 다리가 같은 종목입니다: {', '.join(syms)}")
    return legs
