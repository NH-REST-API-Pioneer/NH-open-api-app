"""KRX→MKU 연계 실시간 전략 (leadlag) — week03 `ws_trader.py` 에서 판단 부분(`Engine`)만 떼어 낸 앱용 파일.

## 이 파일은 무엇을 어디서 옮겼나

week03 `leadlag/ws_trader.py` 에서 아래 다섯 이름만 **한 글자도 고치지 않고** 옮겼습니다
(`tests/test_team_pyrun_leadlag.py` 가 ws_trader 원문과 소스를 글자 그대로 비교합니다).

| 남긴 것 | 무엇 |
|---|---|
| `TICK` · `TICK_USD` · `FEE_TICKS` | MKU 틱 0.0001 = US$2.5, 수수료 편도 US$2 를 틱으로 |
| `LiveParams` | 전략 값(충격 구간·기준·반영률·호가 차이·손절·보유 시간·진입 시간·마감 시각) |
| `Engine` | 판단만 — `on_krx`·`on_quote`·`on_timer` 가 진입·청산 행동(dict)을 돌려주고, `filled_entry`·`filled_exit` 로 체결을 받음 |

## 뺀 것과 까닭

| 뺀 것 | 까닭 |
|---|---|
| `Recorder` | 기록은 앱이 함(`journal.jsonl`·`summary.json`, 민감 칸은 쓰는 순간 지움). 원문(`raw.jsonl`)은 남기지 않음 |
| `Trader` | 웹소켓 접속·다시 붙기·주문·체결 확인은 앱 실시간 실행기(`backend/team_pyrun/realtime.py`)가 함 — 올린 코드는 주문을 내지 못함 |
| `main` · `argparse` | 명령줄 실행 대신 앱 「실행 세우기」(종목·모의 계좌/종이 고르기) |
| `open_raw` · `HERE` | 녹화 읽기는 앱 리플레이(`backend/team_pyrun/replay.py` `read_raw`)가 함 |
| `SILENCE_S` | 끊김 판단은 앱 허브가 함(끊겼다 붙으면 공백 표지) |
| `websockets` · `nh_client` · `fee_test` · `ws_probe` import | 위를 빼면 쓰이지 않음. 이 파일은 **표준 라이브러리만** 씀(앱에 없는 모듈을 부르지 않게) |
| `asyncio` · `csv` · `gzip` · `json` · `time` · `datetime` · `Path` · `asdict` import | 위와 같음 |

앱이 이 파일을 「실시간」 전략으로 알아보는 것은 `Engine` 에 `on_krx`·`on_quote` 가 있어서입니다(`loader._kind`).
Params 는 `LiveParams`, 틱 가치는 `TICK_USD` 로 읽습니다. 앱에서 바뀌는 점(모의 계좌 체결을 못 받으면 「확인 필요」로
멈춤, 휴장 중 주문 없음, 실행 끝 = `flatten_at` + 5분)은 실행기 문서에 있습니다 — 판단은 ws_trader 와 같습니다.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

TICK = 0.0001
TICK_USD = 2.5
FEE_TICKS = 2.0 / TICK_USD        # 수수료 편도 $2 (근거 문서 5절)


@dataclass
class LiveParams:
    lookback_s: float = 45        # KRX 충격 구간 (초)
    move_won: float = 0.8         # KRX 충격 기준 (원) — 11/03 기록 재현으로 0.5 → 0.8 (근거 문서 5절)
    rho_max: float = 0.5          # MKU 반영률 상한
    max_spread_ticks: int = 2     # 이보다 호가가 벌어져 있으면 진입 안 함
    stale_s: float = 20           # 시세가 이만큼 끊겼다 오면 그 전 값은 버림 (끊기기 전 값과 비교한 가짜 충격 방지)
    tp_ticks: float | None = None
    sl_ticks: float = 5
    hold_s: float = 300           # 시간 청산 (초) — 화요일 기록 분석 뒤 확정
    cooldown_s: float = 60
    max_stops_per_day: int = 3
    entry_start: str = "090000"
    entry_end: str = "152000"
    flatten_at: str = "154000"


class Engine:
    """판단만 하는 부분. 시세를 넣으면 할 일(진입·청산)을 돌려준다 — 접속·주문 없이 시험할 수 있게."""

    def __init__(self, p: LiveParams):
        self.p = p
        self.krx: deque[tuple[float, float]] = deque()     # (단조시각, 가격)
        self.mid: deque[tuple[float, float]] = deque()     # (단조시각, MKU 중간값)
        self.bid = self.ask = None
        self.pos: dict | None = None
        self.pending = False      # 주문이 나가 있는 동안 새 판단을 막음
        self.stops = 0
        self.resume_at = 0.0

    # ---- 시세 ----
    def on_krx(self, price: float, now: float, hhmmss: str) -> dict | None:
        self._drop_if_stale(self.krx, now)
        self.krx.append((now, price))
        self._trim(self.krx, now)
        return self._entry(now, hhmmss)

    def on_quote(self, bid: float, ask: float, now: float, hhmmss: str) -> dict | None:
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        self.bid, self.ask = bid, ask
        self._drop_if_stale(self.mid, now)
        self.mid.append((now, (bid + ask) / 2))
        self._trim(self.mid, now)
        return self._exit(now, hhmmss)

    def on_timer(self, now: float, hhmmss: str) -> dict | None:
        return self._exit(now, hhmmss)

    def _drop_if_stale(self, dq: deque, now: float) -> None:
        # 비운 뒤에는 lookback 만큼 다시 쌓여야 구간 시작값이 생기므로 그동안 진입하지 않는다
        if dq and now - dq[-1][0] > self.p.stale_s:
            dq.clear()

    def _trim(self, dq: deque, now: float) -> None:
        # 구간 시작값이 필요하므로 lookback 보다 조금 더 남김
        while len(dq) > 2 and dq[1][0] < now - self.p.lookback_s - 5:
            dq.popleft()

    @staticmethod
    def _at(dq: deque, t: float) -> float | None:
        """시각 t 에 유효했던 값 (t 이전 마지막 값)."""
        val = None
        for ts, v in dq:
            if ts > t:
                break
            val = v
        return val

    # ---- 진입 ----
    def _entry(self, now: float, hhmmss: str) -> dict | None:
        p = self.p
        if self.pos or self.pending or now < self.resume_at or self.stops >= p.max_stops_per_day:
            return None
        if not (p.entry_start <= hhmmss <= p.entry_end) or self.bid is None:
            return None
        t0 = now - p.lookback_s
        k0, m0 = self._at(self.krx, t0), self._at(self.mid, t0)
        if k0 is None or m0 is None:
            return None
        dk = round(self.krx[-1][1] - k0, 2)      # 1340.8-1340.0 = 0.7999… 방지
        if abs(dk) < p.move_won:
            return None
        spread = round((self.ask - self.bid) / TICK)
        if spread > p.max_spread_ticks:
            return None
        k_dir = 1 if dk > 0 else -1
        m1 = self.mid[-1][1]
        expected = abs(dk) / (1000 * TICK / m1 ** 2)
        followed = -k_dir * (m1 - m0) / TICK
        rho = followed / expected
        if rho >= p.rho_max:
            return None
        side = -k_dir
        self.pending = True
        return {"act": "enter", "side": side, "ref": self.ask if side > 0 else self.bid,
                "dk": round(dk, 2), "expected": round(expected, 2), "followed": round(followed, 2),
                "rho": round(rho, 2), "spread": spread, "time": hhmmss}

    def filled_entry(self, side: int, price: float, now: float, hhmmss: str, ord_no: str = "") -> None:
        self.pos = {"side": side, "price": price, "t": now, "time": hhmmss, "ord_no": ord_no}
        self.pending = False

    # ---- 청산 ----
    def _exit(self, now: float, hhmmss: str) -> dict | None:
        if not self.pos or self.pending or self.bid is None:
            return None
        p, pos = self.p, self.pos
        mark = self.bid if pos["side"] > 0 else self.ask     # 지금 청산하면 받을 호가
        pnl = round(pos["side"] * (mark - pos["price"]) / TICK, 6)   # 0.0003/0.0001 = 2.9999… 방지
        reason = ""
        if p.tp_ticks is not None and pnl >= p.tp_ticks:
            reason = "익절"
        elif pnl <= -p.sl_ticks:
            reason = "손절"
        elif now - pos["t"] >= p.hold_s:
            reason = "시간"
        elif hhmmss >= p.flatten_at:
            reason = "마감"
        if not reason:
            return None
        self.pending = True
        return {"act": "exit", "side": -pos["side"], "ref": mark, "reason": reason, "time": hhmmss}

    def filled_exit(self, price: float, now: float, reason: str) -> dict:
        pos = self.pos
        gross = pos["side"] * (price - pos["price"]) / TICK
        net = gross - 2 * FEE_TICKS
        self.stops += reason == "손절"
        self.pos, self.pending = None, False
        self.resume_at = now + self.p.cooldown_s
        return {"gross_ticks": round(gross, 2), "net_ticks": round(net, 2), "net_usd": round(net * TICK_USD, 2),
                "held_s": round(now - pos["t"], 1)}
