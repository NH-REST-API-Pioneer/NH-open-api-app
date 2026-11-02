"""모의계좌 체결 — week02 `runner.py` 의 `MockAccountBroker` 를 팀 API 계층(`api.py`) 위로 옮긴 것.

모의 서버(`environment="paper"`)의 모의계좌에 **시장가 1계약**을 넣고, 주문내역에서 그 주문번호가
전체체결(`ord_sts` 6)이 될 때까지 0.5초씩 최대 30번(15초) 봅니다. 체결가는 `avg_exec_pric`, 그게
0 이면 `exec_pric`(week02 10/29 수정). 수수료는 체결 전후 예수금 `fee`(하루 누적)의 차이입니다.

**주문은 한 번만 보냅니다.** 여기서도, 아래 `api.market_order` 에서도 다시 보내지 않습니다.

- 응답을 못 받았거나(`TransportError`) 처리 여부를 모르는 거절(`GatewayError` 등)이면 `order` 줄에
  `ok=False, unknown=True` 를 남기고 `None` — 접수됐는지는 실행기가 바로 잔고(`position`)로 확인합니다.
- 업무 거부(`BusinessError`)는 서버가 「안 받았다」고 한 것이라 `unknown` 이 아닙니다.
- 주문은 받았는데 15초 안에 체결도 거부도 확인되지 않으면 역시 `unknown` 입니다(늦게 체결될 수 있음).
  그 주문번호를 `unresolved` 로 들고 있다가, **다음 주문을 내기 전에 주문내역에서 그 주문을 다시 봅니다.**
  거부·취소가 확인되면 새 주문을 내고, 늦게 체결됐거나 아직 모르면 새 주문을 내지 않고 `None`
  (실행기가 잔고로 실제 상태를 따릅니다). 살아 있을지 모르는 주문 위에 주문을 겹쳐 내지 않기 위해서입니다.

`unknown` 은 실행(`live.py`)이 읽고 바로 잔고를 대조한 뒤 지웁니다. `had_unknown` 은 지우지 않습니다 —
한 번이라도 결과를 모르는 주문이 있었으면 보유가 없을 때도 잔고를 계속 대조합니다(늦은 체결 대비).

API 오류는 전부 여기서 잡습니다. 실행 쪽에서 「전략 코드 예외」와 섞이지 않게 하기 위해서입니다(R16).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from types import ModuleType
from typing import Any

from backend.nh_api.errors import BusinessError
from backend.sessions.hours import now_kst
from backend.team_pyrun.apilog import _redact_error, purpose
from backend.team_pyrun.journal import Journal

#: 예수금에서 기록하는 칸(week02 와 같음). 수수료·확정손익은 하루 누적값입니다.
ACCOUNT_KEYS = ("fee", "fut_cls_pl_amt", "pl_tot_pric", "ord_psb_tot_amt")
FILL_POLLS = 30         # 체결 확인 횟수
FILL_POLL_SECONDS = 0.5  # 체결 확인 간격 (초) — 30 × 0.5 = 15초
FEE_RECHECK_SECONDS = 1.0  # 예수금 fee 반영이 늦을 때 한 번 더 보기 전 쉬는 시간
FILLED = "6"            # 주문내역 `ord_sts`: 전체체결
REJECTED = ("8", "9")   # 주문내역 `ord_sts`: 거부·취소 — 체결 안 됨이 확인된 것


def error_text(e: BaseException) -> str:
    """기록용 오류 문구 — 토큰·키 값은 가리고 300자까지."""
    return str(_redact_error(f"{type(e).__name__}: {e}"))[:300]


class MockAccountBroker:
    """모의계좌에 시장가 주문을 넣고 주문내역으로 체결가를 확인합니다.

    `api_module` 은 `backend.team_pyrun.api` 와 같은 이름의 함수를 가진 것(시험에서는 가짜).
    `today`(YYYYMMDD)는 예수금 조회 날짜 — 없으면 지금 한국 날짜."""

    mode = "mock-account"

    def __init__(self, api_module: ModuleType | Any, sym: str, journal: Journal, exec_cnd: str = "1",
                 sleep: Callable[[float], None] = time.sleep, *, today: str | None = None):
        self.api, self.sym, self.j, self.exec_cnd = api_module, sym, journal, exec_cnd
        self.sleep = sleep
        self.today = today or now_kst().strftime("%Y%m%d")
        self.last_fee: float | None = None          # 마지막으로 본 예수금 fee (하루 누적)
        self.last_fill_fee: float | None = None     # 직전 체결의 수수료 (fee 차이) — 모르면 None
        self.unknown = False        # 직전 주문의 결과를 모름 → 실행이 바로 잔고를 대조하고 지운다
        self.had_unknown = False    # 이 실행에서 결과를 모른 주문이 한 번이라도 있었음 (지우지 않음)
        self.unresolved: str | None = None  # 접수됐지만 체결·거부가 확인 안 된 주문번호

    # ---- 계좌 조회
    def account(self, clock: str = "", why: str = "") -> dict | None:
        """예수금의 수수료·확정손익(하루 누적)을 읽어 기록합니다. 실패해도 매매는 그대로 — None 만 돌려줌."""
        try:
            with purpose("예수금"):
                dep = self.api.deposit(self.today)
            snap = {k: self.api.num(dep.get(k)) for k in ACCOUNT_KEYS}
        except Exception as e:      # 기록용 조회라 어떤 오류도 매매를 멈추지 않게
            self.j.write("event", clock=clock, text=f"예수금 조회 실패 ({why})", error=error_text(e))
            return None
        if why:
            self.j.write("account", clock=clock, text=f"계좌 · {why}", **snap)
        return snap

    def _fee_after_fill(self, clock: str) -> float | None:
        """체결 직후 fee 차이 = 이 체결의 수수료. 반영이 늦으면 1초 뒤 한 번 더 봅니다."""
        before = self.last_fee
        snap = self.account(clock)
        if snap and before is not None and snap["fee"] == before:
            self.sleep(FEE_RECHECK_SECONDS)
            snap = self.account(clock) or snap
        if not snap or snap["fee"] is None:
            return None
        self.last_fee = snap["fee"]
        return None if before is None else round(snap["fee"] - before, 2)

    def position(self) -> int | None:
        """이 종목 순보유 계약 수 (매수 +, 매도 −). 조회 실패면 None."""
        try:
            with purpose("잔고확인"):
                return int(self.api.net_position(self.api.open_interest(), self.sym))
        except Exception as e:
            self.j.write("event", text="잔고 조회 실패", error=error_text(e))
            return None

    # ---- 주문
    def _mark_unknown(self) -> None:
        self.unknown = True
        self.had_unknown = True

    def _blocked_by_unresolved(self, clock: str) -> bool:
        """결과를 모르던 앞선 주문을 주문내역에서 다시 봅니다. 새 주문을 내면 안 되면 True."""
        if not self.unresolved:
            return False
        no, key = self.unresolved, self.unresolved.lstrip("0")
        try:
            with purpose("체결확인"):
                hist = self.api.order_history()
        except Exception as e:
            self._mark_unknown()
            self.j.write("event", clock=clock, ord_no=no, text="앞선 주문 결과 확인 실패 — 새 주문 안 냄",
                         error=error_text(e))
            return True
        mine = [r for r in hist if str(r.get("ord_no", "")).strip().lstrip("0") == key]
        sts = str(mine[0].get("ord_sts", "")).strip() if mine else ""
        if sts in REJECTED:
            self.unresolved = None
            self.j.write("event", clock=clock, ord_no=no, text=f"앞선 주문 {mine[0].get('ord_sts_nm')} 확인 — 체결 안 됨")
            return False
        self._mark_unknown()
        if sts == FILLED:
            self.unresolved = None
            self.j.write("event", clock=clock, ord_no=no, text="앞선 주문이 늦게 체결됨 — 새 주문 안 냄, 잔고로 확인")
        else:
            self.j.write("event", clock=clock, ord_no=no, text="앞선 주문 결과를 아직 모름 — 새 주문 안 냄")
        return True

    def fill(self, side: str, ref_price: float, clock: str, why: str) -> float | None:
        """시장가 1계약을 **한 번** 넣고 체결가를 돌려줍니다. 체결가를 못 받으면 None(재전송 없음)."""
        self.last_fill_fee = None
        self.unknown = False
        if self._blocked_by_unresolved(clock):
            return None
        try:
            with purpose("진입" if why.startswith("진입") else "청산"):
                res = self.api.market_order(self.sym, side, 1, self.exec_cnd)
        except BusinessError as e:
            # 서버가 업무 거부로 답했다 — 접수 안 됨이 확인된 것
            self.j.write("order", clock=clock, side=side, ok=False, text=f"주문 거부 · {why}", error=error_text(e))
            return None
        except Exception as e:
            # 응답 없음(TransportError)·처리 여부 모름(GatewayError)·그 밖 — 접수됐을 수 있다. 다시 보내지 않는다.
            self._mark_unknown()
            self.j.write("order", clock=clock, side=side, ok=False, unknown=True,
                         text=f"주문 결과 모름 · {why} — 잔고로 확인", error=error_text(e))
            return None
        res = res if isinstance(res, dict) else {}
        ord_no = str(res.get("ord_no") or "").strip()
        self.j.write("order", clock=clock, side=side, ord_no=ord_no, msg_cd=res.get("msg_cd"),
                     msg_cntn=res.get("msg_cntn"), ok=bool(ord_no), text=f"시장가 1계약 · {why}")
        if not ord_no:
            self._mark_unknown()     # 응답은 왔지만 주문번호가 없다 — 접수 여부는 잔고로
            return None
        return self._confirm(side, ord_no, clock)

    def _confirm(self, side: str, ord_no: str, clock: str) -> float | None:
        """주문내역에서 이 주문번호가 전체체결(6)이 될 때까지 0.5초씩 최대 30번 봅니다."""
        key = ord_no.lstrip("0")
        last = None
        for _ in range(FILL_POLLS):
            self.sleep(FILL_POLL_SECONDS)
            try:
                with purpose("체결확인"):
                    hist = self.api.order_history()
            except Exception as e:
                self.j.write("event", clock=clock, text="주문내역 조회 실패", error=error_text(e))
                continue
            mine = [r for r in hist if str(r.get("ord_no", "")).strip().lstrip("0") == key]
            if not mine:
                continue
            last = mine[0]
            sts = str(last.get("ord_sts", "")).strip()
            if sts == FILLED:
                # avg_exec_pric 가 "0000…0.000" 으로 올 때가 있어 0 이면 exec_pric 를 씀 (week02 10/29 수정)
                px = (self.api.num(last.get("avg_exec_pric")) or self.api.num(last.get("exec_pric"))) or None
                self.last_fill_fee = self._fee_after_fill(clock)
                self.j.write("fill", clock=clock, side=side, price=px, ord_no=ord_no, source="order-history",
                             exec_qty=last.get("exec_qty"), exec_tm=last.get("exch_exec_tm"),
                             fee=self.last_fill_fee, fee_total=self.last_fee, text="모의계좌 체결")
                if px is None:
                    self._mark_unknown()     # 체결은 됐는데 가격을 못 읽음 — 실행기가 잔고로 확인
                return px
            if sts in REJECTED:
                self.j.write("event", clock=clock, ord_no=ord_no, text=f"주문 {last.get('ord_sts_nm')}",
                             reject=last.get("ord_rejt_rsn"), raw=last)
                return None
        self._mark_unknown()
        self.unresolved = ord_no
        self.j.write("event", clock=clock, ord_no=ord_no, text="15초 안에 전체체결 확인 안 됨 — 잔고로 확인",
                     raw=last)
        return None
