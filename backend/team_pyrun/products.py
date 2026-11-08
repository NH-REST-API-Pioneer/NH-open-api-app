"""파이썬 전략 탭의 종목 찾기 — 스프레드 탭의 다리 찾기(`team_spread.legs.resolve`)를 그대로 쓴다.

실행 폼의 종목 칸(품목 뿌리 `HO`·`A01` 또는 종목 코드 `HOZ26`)을 `Leg`(종목·시장·거래소·통화·틱·틱 가치)로 바꾸고,
전략의 `TICK`·`TICK_VALUE` 가 그 종목과 같은지 본다. 값을 지어내지 않고, 모르면 `StartRefused`(메시지는 화면에 그대로).

import 방향: `team_spread.start` 가 `team_pyrun.live` 를 가져오므로 이 모듈은 `find_product` 안에서만 import 한다.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from backend.team_pyrun import markets
from backend.team_pyrun.markets import Market
from backend.team_spread import legs
from backend.team_spread.legs import Leg

if TYPE_CHECKING:
    from backend.team_pyrun.loader import Loaded

#: 장 시간 칸이 빠진 전략에 MKU 값을 채워 주는 품목 (설계 4.2)
_MKU = "MKU"
#: 내부 다리 이름 대신 사용자가 적은 표기를 쓰는데, 거부 메시지의 머리 「다리 <표기>: 」 는 뗀다
_INTERNAL_HEAD = "다리 "


def find_product(
    spec: str, *, api_module: Any, today: str,
    master: Callable[[], tuple[list, list]] = legs.master_rows,
) -> Leg:
    """종목 칸 표기를 `Leg` 로. 못 찾거나 틱을 확인 못 하면 `StartRefused`."""
    from backend.team_spread import start   # start 가 team_pyrun.live 를 import 하므로 함수 안에서

    spec = str(spec).strip()
    specs = {spec: spec}
    try:
        sources = start.load_sources(specs, api_module=api_module, master=master)
        return start.resolve_legs(specs, sources, today=today)[spec]
    except start.StartRefused as e:
        head = f"{_INTERNAL_HEAD}{spec}: "
        msg = str(e)
        raise start.StartRefused(msg[len(head):] if msg.startswith(head) else msg) from e


def strategy_tick_refusal(leg: Leg, loaded: Loaded) -> str | None:
    """전략 `TICK`·`TICK_VALUE` 가 종목의 틱·틱 가치와 다르면 거부 까닭, 같으면 None."""
    if math.isclose(loaded.tick, leg.tick, rel_tol=1e-9) and math.isclose(loaded.tick_value, leg.tick_value, rel_tol=1e-9):
        return None
    return (f"틱·틱가치가 전략 가정과 다릅니다 — 종목 {leg.sym} {leg.tick:g}·{leg.tick_value:g} {leg.currency}, "
            f"전략 {loaded.tick:g}·{loaded.tick_value:g}")


def domestic_roots() -> list[dict]:
    """국내 틱 확인 표의 품목 `[{"root": "A01", "name": "코스피200선물"}, …]` (표 순서) — 종목 고르기 화면용."""
    return [{"root": root, "name": name} for root, name in legs._DOMESTIC_DETAIL_NAMES.items()]


def account_market(leg: Leg) -> Market:
    """종목이 쓰는 계좌 쪽 시장 — 국내 `DOMESTIC`, 해외 `OVERSEAS`."""
    return markets.DOMESTIC if leg.market == "domestic" else markets.OVERSEAS


def is_mku(product: str | None) -> bool:
    """빠진 장 시간 칸을 MKU 값으로 채워 주는 품목인가."""
    return product == _MKU
