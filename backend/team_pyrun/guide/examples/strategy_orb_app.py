"""세션 개장 돌파(ORB) 앱용 — week03 후보 B 를 앱 1분봉 실행기로 돌리는 파일.

## 이 파일은 무엇을 어디서 옮겼나

**판정(진입 신호)은 옮기지 않았습니다.** `strategy_orb.py`(week03 원본, 한 글자도 고치지 않음)의 `SessionBreakout` 을
그대로 물려받습니다 — `on_minute`(기준 범위 쌓기·돌파 판정·진입 막기), `on_entry(window)`(개장마다 한 번),
`on_exit(pnl, stopped)`(하루 손절 수). 실행기는 신호의 `window` 칸을 `on_entry(window)` 에 넘깁니다.

옮긴 것은 week03 `backtest.py` `run()`(81~176줄)에 있던 **ORB 체결·청산 규칙**입니다. 앱 실행기의 공통 청산
(진입가 ∓ stop_ticks 손절 · `target` 익절 · hold_min 시간 청산)은 ORB 와 달라서, 실행기의 청산 판단 함수
`exit_reason` 으로 옮겼습니다.

| backtest.py | 규칙 | 여기(또는 앱) |
|---|---|---|
| 111~116 (1단계) | 보유 중 `flatten_at`(23:50) 이후 첫 봉 시가에 「마감 정리」 | **앱**의 장 마감 정리(사유 「장 마감 정리」, 같은 규칙) |
| 111~116 (1단계) | 기한(`hold_min`·`exit_by` 중 먼저) 이후 첫 봉 시가에 「시간 청산」/「다음 개장 전 청산」 — 매매 시간 밖 봉이어도 | `exit_reason` 의 기한 (진입한 분 다음 분부터) |
| 124~127 | 기한 = 진입 + hold_min, `exit_by` 가 더 이르면 그것 | `_deadline` |
| 128 | 손절 = 진입 신호의 **범위 반대편 끝**(매수 `range_low`, 매도 `range_high`) | `_levels` |
| 132~133 | 익절 = 진입가 ± `target_ticks` 틱(`common.target_price`) | `_levels` |
| 140~154 (3단계) | 매매 시간 안에서만, 손절 먼저 → 익절. 손절 `min(시가, 손절가)`(매수)·`max(시가, 손절가)`(매도), 익절 `max(시가, 목표)`·`min(시가, 목표)` | `exit_reason` 의 손절·익절 (`in_trading_hours` 로 막음) |
| 119~139 (2단계) | 신호 다음 1분봉 시가에 진입, 23:50 이후 진입 없음 | **앱** 실행기 pending 규칙(그대로) |
| 89~91 | 불리한 쪽 슬리피지 1틱 | **앱** 종이 체결(`slip_ticks`) |

「min(시가, 손절가)」 는 실행기가 한 분에 두 번 묻는 것으로 같아집니다: 먼저 시가 하나로(`low`·`high` 가 None)
묻고, 다음에 그 분의 저가·고가로 묻습니다. 시가가 이미 손절가를 지났으면 첫 물음에서 시가로, 아니면 둘째 물음에서
손절가로 청산 — 둘 중 작은 쪽이 됩니다. 익절도 같습니다. 장중 실행은 현재가 하나로만 묻습니다(그 가격에서 판단).
다른 점 하나: 시가가 이미 익절가를 넘었는데 **같은 분의 저가가 손절가까지** 내려간 봉이면 backtest 는 손절(보수적),
여기는 첫 물음(시가)에서 익절입니다 — 시가 물음에선 그 분의 저가를 모르기 때문. 한 봉이 범위 폭 + 목표 폭을
다 덮어야 생기는 일이라 week03 기간(37건)엔 없습니다(`tests/test_team_pyrun_orb.py` 골든).

`exit_levels` 는 화면 표시용(범위 끝 손절가·목표가)이고 판단에는 쓰이지 않습니다.
"""
from __future__ import annotations

from common import TICK, TICK_VALUE, hhmmss_of, in_trading_hours, minutes_of, target_price  # noqa: F401
from strategy_orb import Params, SessionBreakout  # noqa: F401 — Params 는 앱 로더가 찾는 이름

TITLE = "세션 개장 돌파 (ORB, MKU)"


class OrbApp(SessionBreakout):
    """`SessionBreakout` 판정 그대로 + week03 backtest 의 ORB 청산 규칙(`exit_reason`)."""

    # ---- 보유의 손절·익절·기한 (진입 신호에서) ----
    @staticmethod
    def _levels(pos: dict) -> tuple[float | None, float | None]:
        """(손절가, 익절가). 손절 = 범위 반대편 끝, 익절 = 진입가 ± target_ticks (backtest.py 128·132~133).

        진입 신호를 모르면(`pos["signal"]` None) 실행기의 손절가를 쓰고 익절은 없음."""
        s = pos.get("signal")
        if s is None:
            return pos.get("stop"), None
        stop = s.range_low if pos["side"] == "buy" else s.range_high
        target = target_price(pos["side"], pos["entry"], s.target_ticks) if s.target_ticks else None
        return stop, target

    def _deadline(self, pos: dict) -> tuple[str, str]:
        """(기한 HHMMSS, 사유). 진입 + hold_min, 신호의 exit_by(다음 개장 또는 23:50)가 더 이르면 그것 (124~127)."""
        hold_end = hhmmss_of(minutes_of(pos["entry_time"]) + self.p.hold_min)
        s = pos.get("signal")
        exit_by = getattr(s, "exit_by", None)
        if exit_by and exit_by < hold_end:
            return exit_by, "다음 개장 전 청산"
        return hold_end, "시간 청산"

    # ---- 앱 실행기가 부름 ----
    def exit_reason(self, clock: str, price: float, low: float | None, high: float | None, pos: dict):
        """보유 중 가격마다. None = 들고 있음, 사유 = 지금 가격으로, (사유, 기준가) = 그 가격으로 청산."""
        # 1단계(111~116): 기한 — 진입한 분이 지난 뒤, 매매 시간 밖이어도. 그 가격(리플레이는 그 분 시가)으로
        deadline, why = self._deadline(pos)
        if minutes_of(clock) > minutes_of(pos["entry_time"]) and clock >= deadline:
            return why
        # 3단계(140~154): 손절 → 익절, 매매 시간(08:25~20:35, 20:50~24:00) 안에서만
        if not in_trading_hours(clock):
            return None
        stop, target = self._levels(pos)
        buy = pos["side"] == "buy"
        lo, hi = (price, price) if low is None or high is None else (low, high)
        single = low is None or high is None
        if stop is not None and (lo <= stop if buy else hi >= stop):
            return ("손절", price if single else stop)
        if target is not None and (hi >= target if buy else lo <= target):
            return ("익절", price if single else target)
        return None

    def exit_levels(self, pos: dict) -> dict:
        """화면에 보일 손절·익절 (표시 전용 — 판단은 `exit_reason`)."""
        stop, target = self._levels(pos)
        return {"stop": stop, "target": target}


STRATEGY = OrbApp
