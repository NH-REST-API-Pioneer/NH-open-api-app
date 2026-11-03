"""시장 묶음 — 국내 미국달러선물·해외 SGX 미니 원달러(MKU)의 API·시간표·통화를 한 자리에.

브로커(`MockAccountBroker`)와 실행(`live.py`)이 「어느 시장인지」 몰라도 되게, 시장마다 다른 것을 여기 모읍니다.

    Market      시장 값 — 통화·실행 끝 시각·장 시작·휴장·종이 수수료·종이 슬리피지 (바꿀 수 없음)
    market_of   종목코드로 시장 고르기 (`A75…` 국내, `MKU…` 해외, 그 밖은 ValueError)
    in_break    거래소 휴장 중인가 (해외 20:35~20:50, 국내는 없음)
    adapter     그 시장의 `api.py` 함수들을 브로커·1분봉 실행이 부르는 **같은 이름**으로 잇는 객체

어댑터 이름 (브로커가 부름 — 국내 `api` 이름 그대로)

    market_order(sym, side, qty, exec_cnd)   주문 **한 번**. 재시도 없음 (해외는 체결조건 칸이 없어 exec_cnd 를 안 씀)
    order_history()  open_interest()  net_position(rows, sym)  deposit(biz_dt)  num(v)  rows(body)
    filled  rejected  account_keys            체결 상태 코드·예수금에서 기록하는 칸
    fill_price(row)  fill_time(row)  status_name(row)  reject_reason(row)  order_log(res)   주문내역 줄·주문 답 읽기

어댑터 이름 (1분봉 실행이 부름)

    chart_minute(sym, req_qty=)  price(sym)  spec() → (틱, 1틱 가치)

**어댑터는 종목을 다시 고르지 않습니다.** 실행 하나의 종목은 시작 때 한 번 정해져 끝까지 같습니다
(월물이 넘어가도 실행 중에 바꾸지 않음). 국내 어댑터에만 시작 때 쓰는 `all_futures`·`nearest_usd` 가 있습니다.

**해외 잔고·주문내역은 쪽을 따라갑니다**(컨트롤러 결정 R5). 다음 쪽 키(`nxt_key`)를 `OVS_MAX_PAGES` 쪽까지 따라
합칩니다. 끝 규칙은 운영자 `overseas_account.collect_pl` 과 같습니다 — 다음 키가 비었거나 이미 쓴 키면 끝,
이어 온 쪽이 비었거나 바로 앞 쪽과 줄이 같으면 그 쪽은 버림(끝 표지로 한 번 더 부르면 같은 쪽이 올 수 있어,
잔고를 두 번 세지 않게). **상한까지 갔는데 새 키가 남으면 `PagesLeft` 를 올립니다** — 잔고 일부로 순보유를
셈하면 틀린 보유로 잔고 관문이 열리기 때문입니다. 브로커는 이 예외를 다른 조회 실패와 똑같이 받으므로
잔고는 「모름」(None), 주문은 「아직 못 찾음」이 됩니다. 브로커의 판단 규칙은 그대로입니다.

국내 어댑터는 지금 `api` 를 그대로 부릅니다(쪽 넘기기 없음 — week02 와 같은 첫 쪽만).
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Literal

from backend.team_pyrun import api as default_api

#: 해외 잔고·주문내역을 따라가는 쪽 수 상한. 쪽마다 조회 한 번(재시도는 `api._query` 규칙)이라 길지 않게 둡니다.
#: MKU 1계약 전략의 하루 주문은 수십 줄이라 한두 쪽이면 끝납니다.
OVS_MAX_PAGES = 10

#: 국내 예수금에서 기록하는 칸(week02 와 같음 — `broker.ACCOUNT_KEYS`). 수수료·확정손익은 하루 누적값입니다.
DOMESTIC_ACCOUNT_KEYS = ("fee", "fut_cls_pl_amt", "pl_tot_pric", "ord_psb_tot_amt")

#: 해외 예수금에서 기록하는 칸 — 위탁수수료·선물수수료·실현손익·주문가능금액(USD). 첫 칸 `fee` 의 차이가 체결
#: 수수료입니다(국내와 같은 읽기). 근거: 운영자 `overseas_account.DEPOSIT_SINGLES`(:60~110), week03 `nh_client.ovs_deposit`.
OVERSEAS_ACCOUNT_KEYS = ("fee", "fut_fee", "cls_pl_amt", "ord_psb_amt")

#: 해외 주문내역 `ord_sts` 의 한글 이름 — 해외 줄에는 국내 `ord_sts_nm` 같은 이름 칸이 없습니다.
#: 근거: 운영자 `overseas_account.ORDER_STATUS`(주문내역 명세: 1 접수·3 확인·4 부분체결·6 전체체결·8 자동취소·9 거부).
OVS_STATUS_NAMES = {"1": "접수", "3": "확인", "4": "부분체결", "6": "전체체결", "8": "자동취소", "9": "거부"}


@dataclass(frozen=True)
class Market:
    """시장 하나의 값. 시각은 전부 한국시간 `HHMMSS`."""

    id: Literal["domestic", "overseas"]
    currency: Literal["KRW", "USD"]
    end_time: str                           # 1분봉 실행을 끝내는 시각
    session_start: str                      # 장 시작(전략 Params 에 없을 때 채우는 값)
    breaks: tuple[tuple[str, str], ...]     # 휴장 [시작, 끝) — 이 사이엔 주문하지 않음
    paper_fee: float                        # 종이 체결 수수료 (체결마다, 그 시장 통화)
    paper_slip_ticks: int                   # 종이 체결 슬리피지 (틱)


#: 국내 미국달러선물 — 기존 값 그대로(실행 끝 `live.END_TIME`, 종이 `runner.PAPER_FEE`·`PAPER_SLIP_TICKS`,
#: 장 시작은 week02 전략 `session_start` — 모의계좌 주문은 09:00 부터).
DOMESTIC = Market(id="domestic", currency="KRW", end_time="153100", session_start="090000",
                  breaks=(), paper_fee=690.0, paper_slip_ticks=1)

#: 해외 SGX 미니 원달러 MKU — 장 08:25~20:35 · 휴장 20:35~20:50 · 20:50~, 실행 끝 23:55,
#: 종이 수수료 편도 US$2(체결마다)·슬리피지 1틱(전역 약속).
OVERSEAS = Market(id="overseas", currency="USD", end_time="235500", session_start="082500",
                  breaks=(("203500", "205000"),), paper_fee=2.0, paper_slip_ticks=1)


def market_of(sym: str) -> Market:
    """종목코드의 시장. `A75…`(미국달러선물) → 국내, `MKU…`(SGX 미니 원달러) → 해외.

    큰 계약 `KU…` 나 그 밖의 종목은 이 앱이 다루지 않아 `ValueError` 입니다(틀린 시장 함수로 주문하지 않게).
    """
    code = str(sym or "").strip()
    if code.startswith("A75"):
        return DOMESTIC
    if code.startswith("MKU"):
        return OVERSEAS
    raise ValueError(f"시장을 알 수 없는 종목코드입니다: {sym!r} (A75… 국내 미국달러선물, MKU… 해외만)")


def in_break(market: Market, hhmmss: str) -> bool:
    """`hhmmss`(한국시간)가 그 시장의 휴장 [시작, 끝) 안인가."""
    return any(start <= hhmmss < end for start, end in market.breaks)


class PagesLeft(Exception):
    """쪽 상한까지 따라갔는데 다음 쪽이 남았다 — 받은 줄이 전부가 아니어서 쓰면 안 된다(잔고 모름·주문 못 찾음)."""


# ── 어댑터 ──────────────────────────────────────────────────


class MarketAdapter:
    """시장 어댑터의 공통 자리. `api` 는 `backend.team_pyrun.api` 와 같은 이름을 가진 것(시험에서는 가짜)."""

    market: Market
    filled: str
    rejected: tuple[str, ...]
    account_keys: tuple[str, ...]

    def __init__(self, api_module: ModuleType | Any = default_api):
        self.api = api_module

    def num(self, v: Any) -> float | None:
        return self.api.num(v)

    def rows(self, body: Any) -> list[dict]:
        return self.api.rows(body)


class DomesticAdapter(MarketAdapter):
    """국내 미국달러선물 — 지금 `api` 함수 그대로. 브로커가 읽던 칸도 week02 그대로."""

    market = DOMESTIC
    filled = "6"            # 주문내역 `ord_sts`: 전체체결
    rejected = ("8", "9")   # 거부·취소 — 체결 안 됨이 확인된 것
    account_keys = DOMESTIC_ACCOUNT_KEYS

    # ---- 브로커가 부름
    def market_order(self, sym: str, side: str, qty: int = 1, exec_cnd: str = "1") -> dict:
        """주문 **한 번** — 그대로 넘기고 예외도 그대로 올린다."""
        return self.api.market_order(sym, side, qty, exec_cnd)

    def order_history(self) -> list[dict]:
        return self.api.order_history()

    def open_interest(self) -> list[dict]:
        return self.api.open_interest()

    def net_position(self, positions: list[dict], sym: str) -> int:
        return self.api.net_position(positions, sym)

    def deposit(self, biz_dt: str) -> dict:
        return self.api.deposit(biz_dt)

    def fill_price(self, row: dict) -> float | None:
        """`avg_exec_pric`, 그게 0("0000…0.000")·빈 값이면 `exec_pric`(week02 10/29 수정). 둘 다 못 읽으면 None."""
        return (self.num(row.get("avg_exec_pric")) or self.num(row.get("exec_pric"))) or None

    @staticmethod
    def fill_time(row: dict) -> Any:
        return row.get("exch_exec_tm")

    @staticmethod
    def status_name(row: dict) -> Any:
        return row.get("ord_sts_nm")

    @staticmethod
    def reject_reason(row: dict) -> Any:
        return row.get("ord_rejt_rsn")

    @staticmethod
    def order_log(res: dict) -> dict:
        """주문 답에서 기록하는 칸 — 국내는 `msg_cd`·`msg_cntn`."""
        return {"msg_cd": res.get("msg_cd"), "msg_cntn": res.get("msg_cntn")}

    # ---- 1분봉 실행이 부름
    def chart_minute(self, sym: str, *, req_qty: int) -> list[dict]:
        return self.api.chart_minute(sym, req_qty=req_qty)

    def price(self, sym: str) -> dict:
        return self.api.price(sym)

    def spec(self) -> tuple[float, float]:
        """(호가 단위, 1틱 가치 원) — 품목 세부정보의 `미국달러선물(USD)` 줄."""
        return self.api.usd_spec(self.api.product_detail())

    # ---- 시작 때만 (종목 고르기 — 실행 중에는 부르지 않음)
    def all_futures(self, prd: str = "75") -> list[dict]:
        return self.api.all_futures(prd)

    def nearest_usd(self, futures: list[dict]) -> str:
        return self.api.nearest_usd(futures)

    def product_detail(self) -> list[dict]:
        return self.api.product_detail()

    def usd_spec(self, details: list[dict]) -> tuple[float, float]:
        return self.api.usd_spec(details)


class OverseasAdapter(MarketAdapter):
    """해외 MKU — `api.py` 의 `ovs_*` 함수로. 국내 함수(`market_order` 등)는 절대 부르지 않습니다."""

    market = OVERSEAS
    account_keys = OVERSEAS_ACCOUNT_KEYS

    @property
    def filled(self) -> str:        # type: ignore[override]
        return self.api.OVS_FILLED

    @property
    def rejected(self) -> tuple[str, ...]:      # type: ignore[override]
        return tuple(self.api.OVS_REJECTED)

    # ---- 브로커가 부름
    def market_order(self, sym: str, side: str, qty: int = 1, exec_cnd: str = "1") -> dict:
        """주문 **한 번**. 해외 시장가에는 체결조건 칸이 없어 `exec_cnd` 는 받기만 하고 안 씁니다.

        `err_cd` 거절은 `api.ovs_market_order` 가 `BusinessError` 로 올립니다(결과를 아는 실패). 응답 없음 등
        다른 예외는 그대로 올라가 브로커가 `blind` 로 다룹니다. 주문번호가 빈 접수 답도 브로커가 `blind` 로 다룹니다."""
        return self.api.ovs_market_order(sym, side, qty)

    def order_history(self) -> list[dict]:
        """당일 주문내역 전부(쪽을 따라감). 상한을 넘겨 남으면 `PagesLeft` — 브로커에선 「아직 못 찾음」."""
        return _all_pages(self.api.ovs_order_history_page)

    def open_interest(self) -> list[dict]:
        """잔고 전부(쪽을 따라감). 상한을 넘겨 남으면 `PagesLeft` — 브로커에선 잔고 「모름」(None)."""
        return _all_pages(self.api.ovs_open_interest_page)

    def net_position(self, positions: list[dict], sym: str) -> int:
        return self.api.ovs_net_position(positions, sym)

    def deposit(self, biz_dt: str) -> dict:
        """USD 예수금. 날짜는 브로커가 실행 시작 때 정한 한국 날짜(해외 실행은 23:55 에 끝나 자정을 넘지 않음)."""
        return self.api.ovs_deposit("USD", biz_dt=biz_dt)

    def fill_price(self, row: dict) -> float | None:
        """`exec_pric`, 0·빈 값이면 `ord_avg_pric`, 둘 다 못 읽으면 None (`api.ovs_fill_price`)."""
        return self.api.ovs_fill_price(row)

    @staticmethod
    def fill_time(row: dict) -> Any:
        return row.get("exec_tm")       # 열네 자리(날짜+시각) — 운영자 overseas_account.order_history

    @staticmethod
    def status_name(row: dict) -> Any:
        sts = str(row.get("ord_sts", "")).strip()
        return OVS_STATUS_NAMES.get(sts, sts)

    @staticmethod
    def reject_reason(row: dict) -> Any:
        """해외는 오류코드(`err_cd`)와 거부사유(`rejt_rsn`)가 따로 옵니다(운영자 order_history). 둘을 이어 적음."""
        text = " ".join(str(row.get(k) or "").strip() for k in ("err_cd", "rejt_rsn")).strip()
        return text or None

    @staticmethod
    def order_log(res: dict) -> dict:
        """주문 답에서 기록하는 칸 — 해외는 `err_cd`·`err_msg`(`msg_cd` 가 아님, 운영자 order_result)."""
        return {"err_cd": res.get("err_cd"), "err_msg": res.get("err_msg")}

    # ---- 1분봉 실행이 부름
    def chart_minute(self, sym: str, *, req_qty: int) -> list[dict]:
        return self.api.ovs_chart_minute(sym, req_qty=req_qty)

    def price(self, sym: str) -> dict:
        return self.api.ovs_price(sym)

    def spec(self) -> tuple[float, float]:
        """(호가 단위, 1틱 가치 USD) — 해외 품목 세부정보의 `MKU` 줄(큰 계약 KU 아님)."""
        return self.api.mku_spec(self.api.ovs_product_detail())


def _all_pages(page) -> list[dict]:
    """`page(nxt_key) -> (줄, 다음 키)` 를 끝까지 따라 줄을 합칩니다. 끝 규칙은 모듈 설명(운영자 collect_pl 과 같음)."""
    got: list[list[dict]] = []
    used: set[str] = set()
    key = ""
    for _ in range(OVS_MAX_PAGES):
        part, following = page(key)
        part = list(part)
        if got and (not part or part == got[-1]):
            return [r for p in got for r in p]      # 끝 표지로 부른 쪽 — 버림
        got.append(part)
        if not following or following in used:
            return [r for p in got for r in p]
        used.add(following)
        key = following
    raise PagesLeft(f"{OVS_MAX_PAGES}쪽을 넘게 이어집니다 — 받은 줄이 전부가 아니라 쓰지 않습니다")


def adapter(market: Market, api_module: ModuleType | Any = default_api) -> MarketAdapter:
    """그 시장의 어댑터. `api_module` 은 시험에서 가짜를 꽂는 자리."""
    if market.id == "domestic":
        return DomesticAdapter(api_module)
    if market.id == "overseas":
        return OverseasAdapter(api_module)
    raise ValueError(f"모르는 시장입니다: {market.id!r}")


def as_adapter(api_module: ModuleType | Any) -> MarketAdapter:
    """이미 어댑터면 그대로, 아니면(`api` 모듈·국내 이름을 가진 가짜) 국내 어댑터로 감쌉니다.

    지금까지 브로커는 `api` 모듈을 바로 받았습니다 — 그 호출들은 전부 국내였으므로 감싸도 동작이 같습니다."""
    if isinstance(api_module, MarketAdapter):
        return api_module
    return DomesticAdapter(api_module)
