"""모의계좌 체결 — week02 `runner.py` 의 `MockAccountBroker` 를 팀 API 계층(`api.py`) 위로 옮긴 것.

모의 서버(`environment="paper"`)의 모의계좌에 **시장가 1계약**을 넣고, 주문내역에서 그 주문번호가
전체체결(`ord_sts` 6)이 될 때까지 0.5초씩 최대 30번(15초) 봅니다. 체결가는 `avg_exec_pric`, 그게
0 이면 `exec_pric`(week02 10/29 수정). 수수료는 체결 전후 예수금 `fee`(하루 누적)의 차이입니다.

**주문은 한 번만 보냅니다.** 여기서도, 아래 `api.market_order` 에서도 다시 보내지 않습니다.

- 업무 거부(`BusinessError`)는 서버가 「안 받았다」고 한 것 — 결과를 아는 실패입니다.
- **번호 없이 결과를 모름**(`TransportError`·`GatewayError`·그 밖의 예외, 또는 응답에 주문번호 없음):
  `order` 줄에 `ok=False, unknown=True`, 그리고 `blind` 표시. 잔고 한 번이 주문 전 보유와 같다는 건 「안 들어갔다」는
  증거가 아니라(반영이 늦을 수 있음) 증거가 없는 것이므로, **잔고가 그 주문 체결 뒤 보유를 보일 때까지 이 실행의
  모든 주문을 막습니다.** 그 사이 주문하려 했는데 잔고가 여전히 주문 전 보유면 실행을 멈춥니다(확인 필요).
- **번호는 있는데 15초 안에 체결도 거부도 확인 안 됨**: `unresolved`(번호·방향)로 들고 있다가 다음 주문 전에
  주문내역에서 다시 봅니다. 거부·취소면 풀고, 같은 방향 주문이 체결됐으면 보내지 않습니다(잔고가 그대로면 멈춤).

주문을 내기 전 관문 (fill 한 번마다, 순서대로 — 하나라도 걸리면 **아무것도 보내지 않고** None)

1. `blind` 가 있으면 잔고를 봄 — 체결 뒤 보유면 표시를 풀고 다음 관문으로, 주문 전 보유 그대로면 멈춤, 그 밖이면 막음.
2. `unresolved` 가 있으면 주문내역에서 다시 봄. 번호가 안 보이거나 세 번째에도 결과가 없으면 멈춤(`halt`).
3. **잔고 관문**: 잔고(`position`)가 실행기가 아는 주문 전 보유(`expected()`)와 정확히 같아야 보냄. 못 읽어도 안 냄.
   앞선 주문이 사실은 접수돼 있었다면 여기서 드러나고, 실행기는 None 을 받아 잔고를 따릅니다
   (청산 재시도인데 잔고가 0 이면 주문 없이 청산으로 기록).

`expected`·`halt` 는 실행(`live.py`)이 꽂습니다. `needs_check`(None 을 돌려줌)·`unknown` 은 실행이 읽고 바로
잔고를 대조한 뒤 지웁니다. `had_unknown` 은 지우지 않습니다 — 한 번이라도 결과를 모르는 주문이 있었으면
보유가 없을 때도 잔고를 계속 대조합니다(늦은 체결 대비).

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
UNRESOLVED_MAX_WAITS = 2  # 결과를 모르는 앞선 주문을 이만큼 더 기다려도 모르면 실행을 멈춤


def error_text(e: BaseException) -> str:
    """기록용 오류 문구 — 토큰·키 값은 가리고 300자까지."""
    return str(_redact_error(f"{type(e).__name__}: {e}"))[:300]


class MockAccountBroker:
    """모의계좌에 시장가 주문을 넣고 주문내역으로 체결가를 확인합니다.

    `api_module` 은 `backend.team_pyrun.api` 와 같은 이름의 함수를 가진 것(시험에서는 가짜).
    `today`(YYYYMMDD)는 예수금 조회 날짜 — 없으면 지금 한국 날짜."""

    mode = "mock-account"

    def __init__(self, api_module: ModuleType | Any, sym: str, journal: Journal, exec_cnd: str = "1",
                 sleep: Callable[[float], None] = time.sleep, *, today: str | None = None,
                 expected: Callable[[], int] | None = None, halt: Callable[[str], None] | None = None):
        self.api, self.sym, self.j, self.exec_cnd = api_module, sym, journal, exec_cnd
        self.sleep = sleep
        self.today = today or now_kst().strftime("%Y%m%d")
        self.last_fee: float | None = None          # 마지막으로 본 예수금 fee (하루 누적)
        self.last_fill_fee: float | None = None     # 직전 체결의 수수료 (fee 차이) — 모르면 None
        self.unknown = False        # 직전 주문의 결과를 모름 → 실행이 바로 잔고를 대조하고 지운다
        self.had_unknown = False    # 이 실행에서 결과를 모른 주문이 한 번이라도 있었음 (지우지 않음)
        self.unresolved: str | None = None  # 접수됐지만 체결·거부가 확인 안 된 주문번호
        self.unresolved_checks = 0          # 그 주문을 다시 봤는데도 결과를 모른 횟수
        self.unresolved_side: str | None = None
        #: 번호 없이 결과를 모르는 주문 {"side","pre","post"} — 잔고가 post 를 보일 때까지 모든 주문을 막는다
        self.blind: dict | None = None
        self.needs_check = False            # fill 이 None 을 돌려줌 → 실행이 바로 잔고를 대조하고 지운다
        #: 실행이 꽂는 갈고리 — 실행기가 아는 보유(주문 전)와 멈춤. 없으면 잔고 관문을 건너뛴다(단독 시험용)
        self.expected: Callable[[], int] | None = expected
        self.halt: Callable[[str], None] | None = halt

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

    @staticmethod
    def _post(pre: int | None, side: str) -> int | None:
        """주문 전 보유 pre 에서 side 1계약이 체결되면 될 보유."""
        return None if pre is None else pre + (1 if side == "buy" else -1)

    def _halt(self, reason: str) -> None:
        """실행을 멈추게 한다(실행이 `halt` 를 꽂아 둔 경우). 없으면 기록만."""
        if self.halt is not None:
            self.halt(reason)
        else:
            self.j.write("event", text=f"멈춰야 함 · {reason}")

    def blind_landed(self, held: int | None) -> bool:
        """잔고 held 가 번호 없는 결과 모름 주문(`blind`)이 체결된 뒤의 보유와 같은가 — 그 주문이 들어갔다는 증거."""
        return self.blind is not None and held is not None and held == self.blind["post"]

    def lift_blind(self, clock: str, held: int) -> None:
        """번호 없는 결과 모름 주문이 잔고에 반영된 것을 확인 — 표시를 지운다."""
        b, self.blind = self.blind, None
        self.j.write("event", clock=clock, text=f"결과를 모르던 {b['side']} 주문이 잔고({held:+d})에 반영됨 — 주문 막음 해제")

    def _blocked_by_blind(self, clock: str) -> bool:
        """번호 없는 결과 모름 주문이 있으면, 잔고가 그 주문 체결 뒤 보유를 보일 때까지 어떤 주문도 내지 않는다.

        - 잔고 = 그 주문 체결 뒤 보유 → 들어간 것이 확인됨: 표시를 지우고, 지금 주문은 잔고 관문에 맡긴다
          (청산 재시도인데 잔고 0 이면 관문이 막고 실행기가 청산으로 기록)
        - 잔고 = 그 주문 전 보유(실행기가 아는 보유) → 안 들어간 건지 반영이 늦는 건지 모른다: 멈춤(확인 필요)
        - 그 밖·못 읽음 → 보내지 않음(실행기가 잔고를 따른다)"""
        if self.blind is None:
            return False
        held = self.position()
        if self.blind_landed(held):
            self.lift_blind(clock, held)
            return False
        self._mark_unknown()
        exp = self.expected() if self.expected is not None else None
        got = "확인 안 됨" if held is None else f"{held:+d}"
        if held is not None and held == exp:
            self._halt(f"결과를 모르는 {self.blind['side']} 주문 뒤 잔고가 그대로({got}) — 들어갔는지 알 수 없어 새 주문 안 냄")
        else:
            self.j.write("event", clock=clock, text=f"결과를 모르는 주문이 있어 새 주문 안 냄 · 잔고 {got}")
        return True

    def _blocked_by_unresolved(self, side: str, clock: str) -> bool:
        """결과를 모르던 앞선 주문(번호 있음)을 주문내역에서 다시 봅니다. 새 주문을 내면 안 되면 True.

        - 거부·취소(8·9) → 막지 않음
        - 전체체결(6), **방향이 다름**(예: 늦게 체결돼 받아들인 진입 뒤의 청산) → 막지 않음. 잔고 관문이 판단
        - 전체체결(6), **같은 방향** → 보내지 않음. 잔고가 아직 주문 전 보유면 주문내역과 잔고가 어긋난 것이라 멈춤
        - 주문내역에 그 번호가 없음 → 멈춤(첫 쪽에 안 보이면 영영 못 찾을 수 있어 손절이 조용히 막히지 않게)
        - 아직 결과 없음·조회 실패 → 막음. 세 번째에도 그러면 멈춤"""
        if not self.unresolved:
            return False
        no, key = self.unresolved, self.unresolved.lstrip("0")
        try:
            with purpose("체결확인"):
                hist = self.api.order_history()
        except Exception as e:
            hist, failed = None, error_text(e)
        else:
            failed = None
        if hist is not None:
            mine = [r for r in hist if str(r.get("ord_no", "")).strip().lstrip("0") == key]
            if not mine:
                self._mark_unknown()
                self._halt(f"결과를 모르는 주문 {no} 을 주문내역에서 찾지 못함 — 새 주문 안 냄")
                return True
            sts = str(mine[0].get("ord_sts", "")).strip()
            if sts in REJECTED:
                self.unresolved = None
                self.j.write("event", clock=clock, ord_no=no, text=f"앞선 주문 {mine[0].get('ord_sts_nm')} 확인 — 체결 안 됨")
                return False
            if sts == FILLED:
                prev_side, self.unresolved = self.unresolved_side, None
                if prev_side != side:
                    self.j.write("event", clock=clock, ord_no=no,
                                 text=f"앞선 {prev_side} 주문이 늦게 체결됨 — 방향이 다른 새 주문은 잔고 관문에 맡김")
                    return False
                self._mark_unknown()
                held = self.position()
                exp = self.expected() if self.expected is not None else None
                if held is not None and held == exp:
                    self._halt(f"주문내역은 {side} 주문 {no} 체결, 잔고는 그대로({held:+d}) — 새 주문 안 냄")
                else:
                    self.j.write("event", clock=clock, ord_no=no,
                                 text="같은 방향 앞선 주문이 늦게 체결됨 — 새 주문 안 냄, 잔고로 확인")
                return True
        self._mark_unknown()
        self.unresolved_checks += 1
        self.j.write("event", clock=clock, ord_no=no, error=failed,
                     text=f"앞선 주문 결과를 아직 모름 ({self.unresolved_checks}번째) — 새 주문 안 냄")
        if self.unresolved_checks > UNRESOLVED_MAX_WAITS:
            self._halt(f"주문 {no} 결과를 {self.unresolved_checks}번 확인해도 모름 — 새 주문 안 냄")
        return True

    def _balance_gate(self, clock: str) -> bool:
        """주문 직전 잔고가 실행기가 아는 보유(주문 전)와 정확히 같을 때만 True. 못 읽어도 False.

        앞선 주문이 사실은 접수돼 잔고가 바뀌었다면 여기서 걸린다 — 그때 실행기는 None 을 받고 잔고를 따른다
        (청산 재시도인데 잔고가 0 이면 청산된 것으로 기록)."""
        if self.expected is None:
            return True     # 실행에 묶이지 않은 브로커(단독 시험) — 실행(live.py)은 언제나 꽂아 둔다
        exp = self.expected()
        held = self.position()
        if held is not None and held == exp:
            return True
        self._mark_unknown()
        got = "확인 안 됨" if held is None else f"{held:+d}"
        self.j.write("event", clock=clock, text=f"주문 전 잔고 {got} ≠ 기대 {exp:+d} — 주문 안 냄, 잔고로 확인")
        return False

    def fill(self, side: str, ref_price: float, clock: str, why: str) -> float | None:
        """시장가 1계약을 **한 번** 넣고 체결가를 돌려줍니다. 체결가를 못 받으면 None(재전송 없음).

        None 이면 `needs_check` 가 서서 실행이 바로 잔고를 대조합니다."""
        self.last_fill_fee = None
        self.unknown = False
        px = self._fill(side, clock, why)
        if px is None:
            self.needs_check = True
        return px

    def _fill(self, side: str, clock: str, why: str) -> float | None:
        if self._blocked_by_blind(clock):
            return None
        if self._blocked_by_unresolved(side, clock):
            return None
        if not self._balance_gate(clock):
            return None
        pre = self.expected() if self.expected is not None else None
        try:
            with purpose("진입" if why.startswith("진입") else "청산"):
                res = self.api.market_order(self.sym, side, 1, self.exec_cnd)
        except BusinessError as e:
            # 서버가 업무 거부로 답했다 — 접수 안 됨이 확인된 것
            self.j.write("order", clock=clock, side=side, ok=False, text=f"주문 거부 · {why}", error=error_text(e))
            return None
        except Exception as e:
            # 응답 없음(TransportError)·처리 여부 모름(GatewayError)·그 밖 — 접수됐을 수 있다. 다시 보내지 않는다.
            self._sent_blind(side, pre)
            self.j.write("order", clock=clock, side=side, ok=False, unknown=True,
                         text=f"주문 결과 모름 · {why} — 잔고로 확인될 때까지 새 주문 없음", error=error_text(e))
            return None
        res = res if isinstance(res, dict) else {}
        ord_no = str(res.get("ord_no") or "").strip()
        self.j.write("order", clock=clock, side=side, ord_no=ord_no, msg_cd=res.get("msg_cd"),
                     msg_cntn=res.get("msg_cntn"), ok=bool(ord_no), text=f"시장가 1계약 · {why}")
        if not ord_no:
            self._sent_blind(side, pre)     # 응답은 왔지만 주문번호가 없다 — 접수 여부는 잔고로
            return None
        return self._confirm(side, ord_no, clock)

    def _sent_blind(self, side: str, pre: int | None) -> None:
        """번호 없이 결과를 모르는 주문 — 잔고가 그 주문 체결 뒤 보유를 보일 때까지 모든 주문을 막는 표시."""
        self._mark_unknown()
        self.blind = {"side": side, "pre": pre, "post": self._post(pre, side)}

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
        self.unresolved, self.unresolved_side, self.unresolved_checks = ord_no, side, 0
        self.j.write("event", clock=clock, ord_no=ord_no, text="15초 안에 전체체결 확인 안 됨 — 잔고로 확인",
                     raw=last)
        return None
