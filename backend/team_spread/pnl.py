"""스프레드 손익 — 체결(`Fill`)로 다리마다 평균가 방식, 거래일·통화별.

줄이는 체결의 (체결가 − 평균가) × 수량 × `point_value`, 수수료는 따로. 날(거래일)과 실행 전체를 통화별로
`{pnl, fee, net, fills}`. 체결가를 모르는(`price_known` False) 체결이 들어간 손익은 `estimated: true`, 수수료를 모르는
체결은 `fee_unknown` 개수. 이어받은 보유는 이어받은 평균가가 시작 값(평균가가 없으면 그 손익은 추정).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

from backend.sessions.hours import to_kst
from backend.team_spread.legs import Leg

#: 거래일 경계 — 한국시간 07:00 (판정 R19). 운영자 `sessions.service.REFRESH_AT`(시간표를 새로 받는 시각)과 같다.
#: 해외 밤 장(MKU 20:50~06:15)의 자정 뒤 체결은 그 장이 연 날로, 국내 주간 장은 그날로 센다.
TRADING_DAY_STARTS = timedelta(hours=7)


def trading_date(at: datetime) -> str:
    """거래일(YYYYMMDD) — `TRADING_DAY_STARTS` 경계."""
    return (to_kst(at) - TRADING_DAY_STARTS).strftime("%Y%m%d")


def _zero() -> dict[str, Any]:
    return {"pnl": 0.0, "fee": 0.0, "fills": 0}


class Ledger:
    """체결로 센 손익(모듈 설명). 여러 스레드(실행기·정리·화면)가 부르므로 잠근다."""

    def __init__(self, inherited: dict[str, dict] | None):
        self._lock = threading.Lock()
        #: 다리 → [보유, 평균가 | None, 평균가가 추정인가]
        self.pos: dict[str, list] = {}
        for name, v in (inherited or {}).items():
            avg = v.get("avg_price")
            if int(v.get("qty") or 0):
                self.pos[name] = [int(v["qty"]), None if avg is None else float(avg), avg is None]
        self.days: dict[str, dict[str, dict]] = {}
        self.total: dict[str, dict] = {}

    def add(self, leg: Leg, qty: int, price: float | None, fee: float | None, known: bool, day: str) -> None:
        with self._lock:
            held, avg, est = self.pos.get(leg.name, [0, None, False])
            unknown = not known or price is None
            pnl, flagged, after = 0.0, False, held + qty
            if held and (held > 0) != (qty > 0):          # 줄이는(뒤집는) 체결
                closed = min(abs(held), abs(qty))
                flagged = unknown or est or avg is None
                if avg is not None and price is not None:
                    pnl = (price - avg) * closed * (1 if held > 0 else -1) * leg.point_value
                if after == 0:
                    avg, est = None, False
                elif (after > 0) != (held > 0):           # 뒤집힘 — 남은 몫은 이 체결가
                    avg, est = price, unknown
            else:                                          # 늘리는 체결
                avg = None if price is None or (held and avg is None) else \
                    ((avg or 0.0) * abs(held) + price * abs(qty)) / abs(after)
                est = est or unknown
            self.pos[leg.name] = [after, avg, est]
            fee = None if fee is not None and fee < 0 else fee     # 예수금 하루 누적이 날을 넘겨 줄면 모르는 값
            for b in (self.days.setdefault(day, {}).setdefault(leg.currency, _zero()),
                      self.total.setdefault(leg.currency, _zero())):
                b["pnl"] += pnl
                b["fills"] += 1
                if fee is None:
                    b["fee_unknown"] = b.get("fee_unknown", 0) + 1
                else:
                    b["fee"] += fee
                if flagged:
                    b["estimated"] = True

    @staticmethod
    def _out(b: dict) -> dict:
        out = {"pnl": round(b["pnl"], 2), "fee": round(b["fee"], 2), "net": round(b["pnl"] - b["fee"], 2),
               "fills": b["fills"]}
        out.update({k: b[k] for k in ("fee_unknown", "estimated") if k in b})
        return out

    def snapshot(self) -> tuple[dict, dict]:
        with self._lock:
            days = {d: {c: self._out(b) for c, b in cur.items()} for d, cur in sorted(self.days.items())}
            return days, {c: self._out(b) for c, b in self.total.items()}

    def avg(self, name: str) -> float | None:
        with self._lock:
            got = self.pos.get(name)
            return None if not got or not got[0] or got[1] is None else round(got[1], 10)
