"""모의계좌 체결 — week02 `runner.py` 의 `MockAccountBroker` 를 팀 API 계층(`api.py`) 위로 옮긴 것.

모의 서버(`environment="paper"`)의 모의계좌에 **시장가 qty계약**(기본 1, `fill(..., qty=)`)을 넣고, 주문내역에서 그 주문번호가
전체체결(`ord_sts` 6)이 될 때까지 0.5초씩 최대 30번(15초) 봅니다. 체결가는 `avg_exec_pric`, 그게
0 이면 `exec_pric`(week02 10/29 수정). 둘 다 못 읽으면 체결은 확인된 것이므로 기준가로 기록합니다(재시도 없음).
수수료는 체결 전후 예수금 `fee`(하루 누적)의 차이입니다.

**주문은 한 번만 보냅니다.** 여기서도, 아래 `api.market_order` 에서도 다시 보내지 않습니다.

- 업무 거부(`BusinessError`)는 서버가 「안 받았다」고 한 것 — 결과를 아는 실패입니다.
- **번호 없이 결과를 모름**(`TransportError`·`GatewayError`·그 밖의 예외, 또는 응답에 주문번호 없음):
  `order` 줄에 `ok=False, unknown=True`, 그리고 `blind` 표시. 잔고 한 번이 주문 전 보유와 같다는 건 「안 들어갔다」는
  증거가 아니라(반영이 늦을 수 있음) 증거가 없는 것이므로, **잔고가 그 주문 체결 뒤 보유를 보일 때까지 이 실행의
  모든 주문을 막습니다.** 그 사이 주문하려 했는데 잔고가 여전히 주문 전 보유면 실행을 멈춥니다(확인 필요).
- **번호는 있는데 15초 안에 체결도 거부도 확인 안 됨**: `unresolved`(번호·방향·주문 전/체결 뒤 보유)로 들고 있다가
  다음 주문 전에 주문내역에서 다시 봅니다. 거부·취소면 풀고, 체결이면 **방향과 상관없이** 잔고가 그 주문의 체결 뒤
  보유일 때만 풀고, 주문 전 보유 그대로면 멈추고, 못 읽거나 그 밖이면 `blind` 로 바꿔 계속 막습니다.

주문을 내기 전 관문 (fill 한 번마다, 순서대로 — 하나라도 걸리면 **아무것도 보내지 않고** None)

1. `blind` 가 있으면 잔고를 봄 — 체결 뒤 보유면 표시를 풀고 다음 관문으로, 주문 전 보유 그대로면 멈춤, 그 밖이면 막음.
2. `unresolved` 가 있으면 주문내역에서 다시 봄. 번호가 안 보이거나 세 번째에도 결과가 없으면 멈춤(`halt`).
   체결(6)이면 위 규칙(잔고 = 체결 뒤 보유일 때만 통과).
3. **잔고 관문**: 잔고(`position`)가 실행기가 아는 주문 전 보유(`expected()`)와 정확히 같아야 보냄. 못 읽어도 안 냄.
   앞선 주문이 사실은 접수돼 있었다면 여기서 드러나고, 실행기는 None 을 받아 잔고를 따릅니다
   (청산 재시도인데 잔고가 0 이면 주문 없이 청산으로 기록).
4. **보내기 직전** `may_send()`(실행이 꽂음 — 해외: 지금 시각이 휴장이 아닌가)가 거짓이면 보내지 않고 `held_back`.
   위 관문들의 조회로 늦어져 판단 때는 휴장 전이던 주문이 휴장에 나가지 않게. 결과 모름 표시는 남기지 않습니다.

fill 한 번이 남기는 것 — 실행기가 None 을 받았을 때 잔고를 **이 실행의 것으로 따라도 되는지** 판단하는 데 씁니다.

- `sent`: 이 fill 에서 `market_order` 를 실제로 불렀는가(관문에 걸려 안 보냈으면 False).
- `held_back`: 이 fill 이 `may_send` 에 걸려 보내지 않았는가 — 실행기는 이때 잔고를 보지 않고 결정을 미룹니다.
- `explains(held)`: 잔고 held 가 이 실행의 결과 모름 주문으로 설명되는가 — `blind`·`unresolved` 의 체결 뒤 보유이거나,
  이 fill 에서 그 표시가 잔고 증거로 풀렸을 때(`landed`). 알려진 거절(업무 거부·8·9)이나 관문에 걸린 주문은
  아무 잔고도 설명하지 않는다 — 그때 다른 잔고는 남의 주문이다.

`expected`·`halt` 는 실행(`live.py`)이 꽂습니다. `needs_check`(None 을 돌려줌)·`unknown` 은 실행이 읽고 바로
잔고를 대조한 뒤 지웁니다. `had_unknown` 은 지우지 않습니다 — 한 번이라도 결과를 모르는 주문이 있었으면
보유가 없을 때도 잔고를 계속 대조합니다(늦은 체결 대비).

API 오류는 전부 여기서 잡습니다. 실행 쪽에서 「전략 코드 예외」와 섞이지 않게 하기 위해서입니다(R16).

**시장(국내·해외)은 어댑터가 압니다**(`markets.adapter`). 브로커는 받은 `api_module` 을 `markets.as_adapter` 로
감싸 쓰고 — 모듈이면 국내 어댑터, 이미 어댑터면 그대로 — 주문내역 줄의 체결 상태 코드·체결가·체결 시각·상태 이름·
거부 사유, 주문 답의 기록 칸, 예수금의 기록 칸만 어댑터에서 읽습니다. 위의 주문 규칙(한 번만·관문·`blind`·
`unresolved`·멈춤)은 시장과 상관없이 같습니다.
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
from backend.team_pyrun.markets import as_adapter

# 예수금 기록 칸·체결 상태 코드(전체체결 6, 거부·취소 8·9)는 시장마다라 어댑터에 있습니다
# (`markets.DomesticAdapter`·`OverseasAdapter` 의 `account_keys`·`filled`·`rejected`).
FILL_POLLS = 30         # 체결 확인 횟수
FILL_POLL_SECONDS = 0.5  # 체결 확인 간격 (초) — 30 × 0.5 = 15초
FEE_RECHECK_SECONDS = 1.0  # 예수금 fee 반영이 늦을 때 한 번 더 보기 전 쉬는 시간
UNRESOLVED_MAX_WAITS = 2  # 결과를 모르는 앞선 주문을 이만큼 더 기다려도 모르면 실행을 멈춤


def error_text(e: BaseException) -> str:
    """기록용 오류 문구 — 토큰·키 값은 가리고 300자까지."""
    return str(_redact_error(f"{type(e).__name__}: {e}"))[:300]


class MockAccountBroker:
    """모의계좌에 시장가 주문을 넣고 주문내역으로 체결가를 확인합니다.

    `api_module` 은 `backend.team_pyrun.api` 와 같은 이름의 함수를 가진 것(시험에서는 가짜) 또는 시장 어댑터
    (`markets.adapter`). 모듈이면 국내 어댑터로 감쌉니다.
    `today`(YYYYMMDD)는 예수금 조회 날짜 — 없으면 지금 한국 날짜."""

    mode = "mock-account"

    def __init__(self, api_module: ModuleType | Any, sym: str, journal: Journal, exec_cnd: str = "1",
                 sleep: Callable[[float], None] = time.sleep, *, today: str | None = None,
                 expected: Callable[[], int] | None = None, halt: Callable[[str], None] | None = None,
                 may_send: Callable[[], bool] | None = None):
        self.api, self.sym, self.j, self.exec_cnd = as_adapter(api_module), sym, journal, exec_cnd
        self.sleep = sleep
        self.today = today or now_kst().strftime("%Y%m%d")
        self.last_fee: float | None = None          # 마지막으로 본 예수금 fee (하루 누적)
        self.last_fill_fee: float | None = None     # 직전 체결의 수수료 (fee 차이) — 모르면 None
        self.unknown = False        # 직전 주문의 결과를 모름 → 실행이 바로 잔고를 대조하고 지운다
        self.had_unknown = False    # 이 실행에서 결과를 모른 주문이 한 번이라도 있었음 (지우지 않음)
        self.unresolved: str | None = None  # 접수됐지만 체결·거부가 확인 안 된 주문번호
        self.unresolved_checks = 0          # 그 주문을 다시 봤는데도 결과를 모른 횟수
        self.unresolved_side: str | None = None
        self.unresolved_qty = 1                     # 그 주문의 계약 수
        self.unresolved_pre: int | None = None      # 그 주문 전 보유
        self.unresolved_post: int | None = None     # 그 주문이 체결된 뒤 보유
        #: 번호 없이 결과를 모르는 주문 {"side","pre","post"} — 잔고가 post 를 보일 때까지 모든 주문을 막는다
        self.blind: dict | None = None
        self.needs_check = False            # fill 이 None 을 돌려줌 → 실행이 바로 잔고를 대조하고 지운다
        self.sent = False                   # 직전 fill 에서 주문을 실제로 보냈는가 (관문에 걸렸으면 False)
        #: 직전 fill 에서 결과 모름 주문이 잔고 증거로 풀렸으면 그 잔고(체결 뒤 보유). 아니면 None
        self.landed: int | None = None
        #: 실행이 꽂는 갈고리 — 실행기가 아는 보유(주문 전)와 멈춤. 없으면 잔고 관문을 건너뛴다(단독 시험용)
        self.expected: Callable[[], int] | None = expected
        self.halt: Callable[[str], None] | None = halt
        #: 보내기 **바로 직전** 한 번 더 묻는 갈고리(해외: 지금 시각이 휴장이 아닌가). 거짓이면 보내지 않는다 — 관문의
        #: 조회(잔고·주문내역·재시도)로 늦어져 20:34:58 의 판단이 20:35 를 넘겨 나가지 않게. 없으면 늘 보냄
        self.may_send: Callable[[], bool] | None = may_send
        #: 직전 fill 이 `may_send` 에 걸려 **보내지 않았음** — 깨끗한 「안 보냄」(결과 모름 표시 없음). 실행기가 읽고 미룬다
        self.held_back = False

    # ---- 계좌 조회
    def account(self, clock: str = "", why: str = "") -> dict | None:
        """예수금의 수수료·확정손익(하루 누적)을 읽어 기록합니다. 실패해도 매매는 그대로 — None 만 돌려줌."""
        try:
            with purpose("예수금"):
                dep = self.api.deposit(self.today)
            snap = {k: self.api.num(dep.get(k)) for k in self.api.account_keys}
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
    def _row_of(self, mine: list[dict]) -> dict:
        """한 주문번호의 주문내역 줄들 중 볼 줄 — 전체체결 줄이 있으면 그것, 없으면 거부·취소 줄, 없으면 첫 줄.

        같은 주문이 접수·체결 줄로 여럿 올 수 있어(쪽·순서도 모름) 첫 줄만 보면 체결을 놓칠 수 있다.
        체결과 거부 줄이 같이 있으면 체결이 먼저 — 실제로 계약이 생긴 쪽을 놓치지 않게."""
        def sts(row: dict) -> str:
            return str(row.get("ord_sts", "")).strip()
        for want in ((self.api.filled,), tuple(self.api.rejected)):
            for row in mine:
                if sts(row) in want:
                    return row
        return mine[0]

    def _mark_unknown(self) -> None:
        self.unknown = True
        self.had_unknown = True

    @staticmethod
    def _post(pre: int | None, side: str, qty: int = 1) -> int | None:
        """주문 전 보유 pre 에서 side qty계약이 체결되면 될 보유."""
        return None if pre is None else pre + (qty if side == "buy" else -qty)

    def _clean_reject(self, row: dict, qty: int) -> bool:
        """거부·취소(8·9) 줄이 「하나도 체결 안 됨」의 증거인가. 1계약이면 예전 그대로 늘 True.

        qty>1 이면 일부 체결 뒤 나머지가 취소(자동취소)될 수 있어 체결 수량 `exec_qty` 가 정확히 0 일 때만 True —
        0 보다 크거나 못 읽으면 결과를 모르는 것으로 본다."""
        if qty <= 1:
            return True
        try:
            done = self.api.num(row.get("exec_qty"))
        except Exception:
            return False
        return done is not None and done == 0

    def _partial_reject(self, side: str, pre: int | None, no: str, clock: str, row: dict) -> None:
        """qty>1 주문이 취소·거부로 끝났는데 일부 체결이 있거나 못 읽음 — 잔고가 설명해야 하는 결과 모름.
        post 를 알 수 없는 blind 표시로 모든 주문을 막고 실행을 멈춘다(잔고만 보고는 풀지 않음)."""
        self._mark_unknown()
        self.blind = {"side": side, "pre": pre, "post": None, "ord_no": no}
        self.unresolved = None
        self.j.write("event", clock=clock, ord_no=no, raw=self.api.log_row(row),
                     text=f"주문 {self.api.status_name(row)} 인데 체결 수량이 0 이 아니거나 읽지 못함 — 일부 체결 가능, 새 주문 안 냄")
        self._halt(f"{side} 주문 {no} 가 {self.api.status_name(row)} 인데 일부 체결됐을 수 있음 — 잔고 확인 필요")

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
        self.landed = held
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

        - 거부·취소(8·9) → 표시를 풀고 막지 않음
        - 전체체결(6) → **방향과 상관없이** 그 주문의 주문 전·체결 뒤 보유(pre·post)와 지금 잔고로만 판단
          - 잔고 = post → 반영 확인. 표시를 풀고 지금 주문은 잔고 관문에 맡김(실행기 보유와 다르면 관문이 막고 대조가 멈춤)
          - 잔고 = pre → 주문내역은 체결, 잔고는 그 전 그대로 — 어긋남: 멈춤, 아무것도 안 냄
          - 그 밖·못 읽음 → 막음. 표시는 지우지 않고 번호 없는 결과 모름 표시(`blind`)로 바꿔, 잔고가 post 를
            보일 때까지 모든 주문을 막는다(주문내역이 체결을 확인했으니 다시 볼 것은 잔고뿐)
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
            row = self._row_of(mine)
            sts = str(row.get("ord_sts", "")).strip()
            if sts in self.api.rejected:
                if not self._clean_reject(row, self.unresolved_qty):
                    self._partial_reject(self.unresolved_side or "", self.unresolved_pre, no, clock, row)
                    return True
                self.unresolved = None
                self.j.write("event", clock=clock, ord_no=no,
                             text=f"앞선 주문 {self.api.status_name(row)} 확인 — 체결 안 됨")
                return False
            if sts == self.api.filled:
                return self._filled_unresolved(no, clock)
        self._mark_unknown()
        self.unresolved_checks += 1
        self.j.write("event", clock=clock, ord_no=no, error=failed,
                     text=f"앞선 주문 결과를 아직 모름 ({self.unresolved_checks}번째) — 새 주문 안 냄")
        if self.unresolved_checks > UNRESOLVED_MAX_WAITS:
            self._halt(f"주문 {no} 결과를 {self.unresolved_checks}번 확인해도 모름 — 새 주문 안 냄")
        return True

    def _filled_unresolved(self, no: str, clock: str) -> bool:
        """주문내역이 앞선 결과 모름 주문(번호 no)을 전체체결로 보여 줌 — 그 주문의 pre·post 와 잔고로만 판단.

        새 주문의 방향은 보지 않는다(방향이 달라도 그 체결이 실행기 보유에 들어갔는지는 잔고만 말해 준다)."""
        prev_side, pre, post = self.unresolved_side, self.unresolved_pre, self.unresolved_post
        held = self.position()
        if held is not None and post is not None and held == post:
            self.unresolved = None
            self.landed = held
            self.j.write("event", clock=clock, ord_no=no,
                         text=f"앞선 {prev_side} 주문 체결이 잔고({held:+d})에 반영됨 — 표시 풀고 잔고 관문에 맡김")
            return False
        self._mark_unknown()
        if held is not None and pre is not None and held == pre:
            # 표시는 그대로 둔다 — 멈춘 실행은 더 주문하지 않고, 끝낼 때 요약에 남는다
            self._halt(f"주문내역은 {prev_side} 주문 {no} 체결, 잔고는 그 전 그대로({held:+d}) — 새 주문 안 냄")
            return True
        # 못 읽음·그 밖 — 표시를 버리지 않고 blind 로 바꿔 잔고가 post 를 보일 때까지 모든 주문을 막는다
        self.blind = {"side": prev_side, "pre": pre, "post": post, "ord_no": no}
        self.unresolved = None
        got = "확인 안 됨" if held is None else f"{held:+d}"
        self.j.write("event", clock=clock, ord_no=no,
                     text=f"앞선 {prev_side} 주문이 늦게 체결됨, 잔고 {got} — 체결 뒤 보유가 보일 때까지 새 주문 안 냄")
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

    def fill(self, side: str, ref_price: float, clock: str, why: str, qty: int = 1) -> float | None:
        """시장가 qty계약(기본 1)을 **한 번** 넣고 체결가를 돌려줍니다. 체결가를 못 받으면 None(재전송 없음).

        qty>1 이어도 전체체결만 체결로 봅니다 — 부분체결로 15초가 지나면 `unresolved`(보수적, 부분 수량은 읽지 않음).
        qty<1 은 아무것도 보내기 전에 ValueError. None 이면 `needs_check` 가 서서 실행이 바로 잔고를 대조합니다."""
        if qty < 1:
            raise ValueError(f"주문 수량은 1 이상이어야 합니다: {qty}")
        self.last_fill_fee = None
        self.unknown = False
        self.sent = False
        self.held_back = False
        self.landed = None
        px = self._fill(side, ref_price, clock, why, qty)
        if px is None and not self.held_back:
            self.needs_check = True     # 보류(안 보냄이 확실)는 대조할 것이 없다
        return px

    def _fill(self, side: str, ref_price: float, clock: str, why: str, qty: int = 1) -> float | None:
        if self._blocked_by_blind(clock):
            return None
        if self._blocked_by_unresolved(side, clock):
            return None
        if not self._balance_gate(clock):
            return None
        pre = self.expected() if self.expected is not None else None
        if self.may_send is not None and not self.may_send():
            # 관문 조회로 늦어져 보낼 수 없는 시각(휴장)이 됐다 — 보내지 않았음이 확실하다. 결과 모름 표시 없음
            self.held_back = True
            self.j.write("event", clock=clock, side=side, text=f"주문 보류 · {why} — 보내기 직전 휴장 시작(보내지 않음)")
            return None
        try:
            with purpose("진입" if why.startswith("진입") else "청산"):
                self.sent = True
                res = self.api.market_order(self.sym, side, qty, self.exec_cnd)
        except BusinessError as e:
            # 서버가 업무 거부로 답했다 — 접수 안 됨이 확인된 것
            self.j.write("order", clock=clock, side=side, ok=False, text=f"주문 거부 · {why}", error=error_text(e))
            return None
        except Exception as e:
            # 응답 없음(TransportError)·처리 여부 모름(GatewayError)·그 밖 — 접수됐을 수 있다. 다시 보내지 않는다.
            self._sent_blind(side, pre, qty)
            self.j.write("order", clock=clock, side=side, ok=False, unknown=True,
                         text=f"주문 결과 모름 · {why} — 잔고로 확인될 때까지 새 주문 없음", error=error_text(e))
            return None
        res = res if isinstance(res, dict) else {}
        ord_no = str(res.get("ord_no") or "").strip()
        self.j.write("order", clock=clock, side=side, ord_no=ord_no, **self.api.order_log(res),
                     ok=bool(ord_no), text=f"시장가 {qty}계약 · {why}")
        if not ord_no:
            self._sent_blind(side, pre, qty)     # 응답은 왔지만 주문번호가 없다 — 접수 여부는 잔고로
            return None
        return self._confirm(side, ord_no, clock, ref_price, pre, qty)

    def explains(self, held: int | None) -> bool:
        """잔고 held 가 이 실행의 결과 모름 주문으로 설명되는가. 실행기가 체결가 없이 잔고를 따를 때 묻는다.

        - 이 fill 에서 결과 모름 주문이 잔고 증거로 풀림(`landed`) — 청산 재시도에서 앞선 청산이 반영된 것
        - 결과 모름 표시(`blind`·`unresolved`)의 체결 뒤 보유 — 방금 보낸 주문이 응답 없이 들어간 것
        그 밖(알려진 거절·관문에 걸려 안 보냄·표시 없음)은 False — 그 잔고는 이 실행이 만든 것이 아니다."""
        if held is None:
            return False
        if self.landed is not None and held == self.landed:
            return True
        if self.blind is not None and held == self.blind["post"]:
            return True
        return self.unresolved is not None and held == self.unresolved_post

    def open_unknowns(self) -> dict | None:
        """아직 풀리지 않은 결과 모름 주문(끝낼 때 보이려고). 없으면 None."""
        if self.unresolved:
            return {"ord_no": self.unresolved, "side": self.unresolved_side,
                    "pre": self.unresolved_pre, "post": self.unresolved_post}
        if self.blind is not None:
            return dict(self.blind)
        return None

    def _sent_blind(self, side: str, pre: int | None, qty: int = 1) -> None:
        """번호 없이 결과를 모르는 주문 — 잔고가 그 주문 체결 뒤 보유를 보일 때까지 모든 주문을 막는 표시."""
        self._mark_unknown()
        self.blind = {"side": side, "pre": pre, "post": self._post(pre, side, qty)}

    def _confirm(self, side: str, ord_no: str, clock: str, ref_price: float, pre: int | None,
                 qty: int = 1) -> float | None:
        """주문내역에서 이 주문번호가 전체체결(6)이 될 때까지 0.5초씩 최대 30번 봅니다.

        전체체결인데 체결가를 못 읽으면(두 칸 다 0·빈 값) **체결된 것으로 보고 기준가로 기록**합니다 — 주문내역이
        체결을 확인해 줬으므로, None 을 돌려 실행기가 잔고(반영이 늦을 수 있음)로 판단하다 재시도하게 두지 않습니다."""
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
            last = self._row_of(mine)
            sts = str(last.get("ord_sts", "")).strip()
            if sts == self.api.filled:
                # 체결가 칸은 시장마다 다름 — 국내 avg_exec_pric(0 이면 exec_pric, week02 10/29), 해외 exec_pric(0 이면 ord_avg_pric)
                px = self.api.fill_price(last)
                price_read = px is not None
                if not price_read:
                    px = ref_price
                    self.j.write("event", clock=clock, ord_no=ord_no,
                                 text=f"전체체결 확인, 체결가를 읽지 못함 — 기준가 {ref_price} 로 기록")
                self.last_fill_fee = self._fee_after_fill(clock)
                self.j.write("fill", clock=clock, side=side, price=px, ord_no=ord_no, source="order-history",
                             price_read=price_read, exec_qty=last.get("exec_qty"), exec_tm=self.api.fill_time(last),
                             fee=self.last_fill_fee, fee_total=self.last_fee,
                             text="모의계좌 체결" if price_read else "모의계좌 체결 · 가격은 기준가")
                return px
            if sts in self.api.rejected:
                if not self._clean_reject(last, qty):
                    self._partial_reject(side, pre, ord_no, clock, last)
                    return None
                self.j.write("event", clock=clock, ord_no=ord_no, text=f"주문 {self.api.status_name(last)}",
                             reject=self.api.reject_reason(last), raw=self.api.log_row(last))
                return None
        self._mark_unknown()
        self.unresolved, self.unresolved_side, self.unresolved_checks = ord_no, side, 0
        self.unresolved_pre, self.unresolved_post = pre, self._post(pre, side, qty)
        self.unresolved_qty = qty
        self.j.write("event", clock=clock, ord_no=ord_no, text="15초 안에 전체체결 확인 안 됨 — 잔고로 확인",
                     raw=self.api.log_row(last))
        return None
