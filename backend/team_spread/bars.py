"""스프레드 1분봉 맞추기 — 다리마다 따로 오는 차트 줄을 시각으로 합친다. 순수 함수만.

줄 칸은 `backend.team_pyrun.api.rows` 가 `occurs1_` 를 뗀 뒤의 모양이고, 국내·해외가 같다
(기록 `tests/fixtures/nh/domestic_chart-minute`·`overseas_chart-minute`): `ref_dt`(날짜) `exch_tm`(봉 **시작** 시각)
`open_pric` `high_pric` `low_pric` `close_pric` `cum_trd_qty`. 최신 봉이 먼저 오지만 여기서 시각순으로 바로잡는다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegBar:
    """한 다리의 1분봉. `filled` 면 그 분에 봉이 없어 직전 종가로 채운 것(거래량 0)."""

    open: float
    high: float
    low: float
    close: float
    volume: float
    filled: bool


@dataclass(frozen=True)
class Minute:
    """모든 다리의 1분봉 한 묶음. `time` = 그 분의 시작 `HHMMSS`(한국시간)."""

    date: str
    time: str
    legs: dict[str, LegBar]


def _bar(row: dict) -> LegBar:
    return LegBar(float(row["open_pric"]), float(row["high_pric"]), float(row["low_pric"]),
                  float(row["close_pric"]), float(row.get("cum_trd_qty") or 0), False)


def align(rows: dict[str, list[dict]]) -> list[Minute]:
    """다리 이름 → 차트 줄 목록을 시각으로 합쳐 오래된 것부터 돌려준다.

    한 다리에 봉이 없는 분은 그 다리의 직전 종가로 채운다(`filled=True`, 시가=고가=저가=종가, 거래량 0).
    모든 다리에 한 번이라도 값이 생기기 전의 분은 버린다(채울 직전 종가가 없는 다리가 있으므로)."""
    per_leg: dict[str, dict[tuple[str, str], LegBar]] = {
        name: {(str(r["ref_dt"]), str(r["exch_tm"])): _bar(r) for r in lines} for name, lines in rows.items()
    }
    keys = sorted({k for bars in per_leg.values() for k in bars})
    last_close: dict[str, float] = {}
    out: list[Minute] = []
    for key in keys:
        legs: dict[str, LegBar] = {}
        for name, bars in per_leg.items():
            bar = bars.get(key)
            if bar is not None:
                last_close[name] = bar.close
                legs[name] = bar
            elif name in last_close:
                c = last_close[name]
                legs[name] = LegBar(c, c, c, c, 0.0, True)
        if len(legs) == len(per_leg):
            out.append(Minute(key[0], key[1], legs))
    return out
