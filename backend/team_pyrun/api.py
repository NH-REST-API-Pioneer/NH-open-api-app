"""팀 API 계층 — 요청 값 만들기·응답 읽기·오류 다루기.

week02 `nh_client.py` 의 요청 값과 해석을 운영자 접속 자리(`runtime.client().call`) 위로 옮긴 것입니다.
전송·토큰·호출 제한은 운영자 쪽에 맡기고, **무엇을 보낼지(payload)·응답을 어떻게 읽을지·실패에
어떻게 대응할지**는 여기서 정합니다(원칙 2, 「API 활용」).

규칙

    - 모든 호출은 `environment="paper"`(모의 서버). 실전으로 나가는 길은 없습니다.
    - **주문은 한 번만 보냅니다.** 재시도도, 예외 바꿔 던지기도 없습니다. 응답을 못 받은 주문
      (`TransportError`)·처리 여부를 모르는 거절(`GatewayError`)은 그대로 올라가고, 접수됐는지는
      호출한 쪽이 잔고·주문내역으로 확인합니다.
    - 조회만 다시 묻습니다. `TransportError` 이거나 오류 코드의 갈래가 `RETRY` 일 때 1초, 2초 쉬며
      처음 포함 최대 3번. 그 밖의 거절(모의 미지원 `EGW053`, 업무 거부 등)은 다시 물어도 같아서 바로 올립니다.
    - payload 값은 전부 문자열입니다(명세가 그렇습니다). 필드명은 `tests/fixtures/nh/` 기록으로 확인했습니다.

함수마다 `client` 키워드로 접속을 바꿔 끼울 수 있습니다(시험용). 없으면 `runtime.client()` 입니다.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from backend.nh_api import error_codes, runtime
from backend.nh_api.client import TradeClient
from backend.nh_api.errors import BusinessError, GatewayError, TransportError

#: 모든 호출이 가는 서버. 실전은 이 계층에 없습니다.
ENVIRONMENT = "paper"

#: 조회를 다시 묻기 전에 쉬는 시간(초). 길이가 곧 다시 묻는 횟수(처음 + 2번 = 최대 3번)입니다.
RETRY_WAITS = (1, 2)

#: 매수·매도 → `trd_div`.
_TRD_DIV = {"buy": "1", "sell": "2"}

#: 재시도 대기. 시험이 실제로 쉬지 않도록 바꿔 끼울 수 있게 모듈 값으로 둡니다.
sleep: Callable[[float], None] = time.sleep


# ── 응답 읽기 ───────────────────────────────────────────────


def rows(body: Any) -> list[dict]:
    """응답의 `Occurs1` 배열을 꺼내고 칸 이름 앞의 `occurs1_` 를 뗍니다.

    배열이 없는 응답(`{"nrec": "0000", "nxt_key": ""}` 처럼 비어 있는 경우)은 빈 목록입니다.
    """
    if not isinstance(body, dict):
        return []
    for key, value in body.items():
        if key.lower().startswith("occurs") and isinstance(value, list):
            return [
                {k.split("_", 1)[1] if k.lower().startswith("occurs") else k: v for k, v in row.items()}
                for row in value
                if isinstance(row, dict)
            ]
    return []


def num(v: Any) -> float | None:
    """응답 숫자 문자열(`"-00000000000044000.000"` 처럼 0 채움·부호 포함)을 float 로. 못 읽으면 None."""
    try:
        text = str(v).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


# ── 호출 ────────────────────────────────────────────────────


def _body(api_id: str, payload: dict[str, str], client: TradeClient | None) -> Any:
    """모의 서버로 한 번 부르고 응답 본문을 돌려줍니다. 예외는 그대로 올립니다."""
    return (client or runtime.client()).call(api_id, payload, environment=ENVIRONMENT).body


def _worth_retrying(exc: BaseException) -> bool:
    """다시 물어볼 만한 실패인지 — 응답을 못 받았거나, 코드 갈래가 「잠시 뒤 다시」인 거절."""
    if isinstance(exc, TransportError):
        return True
    if isinstance(exc, (BusinessError, GatewayError)):
        return error_codes.kind_of(exc.code) == error_codes.RETRY
    return False


def _query(api_id: str, payload: dict[str, str], client: TradeClient | None) -> Any:
    """조회 호출. 다시 물어볼 만한 실패면 `RETRY_WAITS` 만큼 쉬며 다시 묻고, 끝내 안 되면 마지막 예외를 올립니다."""
    for wait in RETRY_WAITS:
        try:
            return _body(api_id, payload, client)
        except (TransportError, BusinessError, GatewayError) as exc:
            if not _worth_retrying(exc):
                raise
        sleep(wait)
    return _body(api_id, payload, client)


# ── 시세 ────────────────────────────────────────────────────


def chart_minute(sym: str, *, req_qty: int, client: TradeClient | None = None) -> list[dict]:
    """1분봉(주간). 최신 봉이 먼저 오고 `exch_tm` 은 봉 시작 시각입니다."""
    return rows(_query("domestic_chart-minute", {
        "nght_tp": "1",
        "sym": sym,
        "inq_strt_dt": "00000000",
        "strt_tm": "000000",
        "inq_ed_dt": "99999999",
        "ed_tm": "235959",
        "req_qty": str(req_qty),
        "dcnt": "1",
        "cidx_yn": "0",
        "nxt_key": "99999999",
        "fut_cidx_exp_mod": "0",
    }, client))


def price(sym: str, *, client: TradeClient | None = None) -> dict:
    """현재가. 줄이 아니라 본문 그대로입니다(`last_pric` 등)."""
    return _query("domestic_price", {"sym": sym}, client)


def all_futures(prd: str = "75", *, client: TradeClient | None = None) -> list[dict]:
    """품목 전체 선물 시세(`prd` 75 = 미국달러). 월물별 종목코드(`sym_exch`)를 찾을 때 씁니다."""
    return rows(_query("domestic_price-all-futures", {"prd": prd}, client))


def product_detail(*, client: TradeClient | None = None) -> list[dict]:
    """품목별 세부정보 — 틱(`cd_val_inf_1`)·틱가치(`tick_val`)·거래시간 등."""
    return rows(_query("domestic_product-detail", {}, client))


# ── 계좌 ────────────────────────────────────────────────────


def deposit(biz_dt: str, *, client: TradeClient | None = None) -> dict:
    """예수금·수수료·확정손익. `biz_dt` 는 `YYYYMMDD`. 줄 목록이 아니라 본문 한 덩어리를 돌려줍니다."""
    return _query("domestic_deposit", {"biz_dt": biz_dt}, client)


def open_interest(*, client: TradeClient | None = None) -> list[dict]:
    """잔고(보유 포지션) — 계좌 전체. 종목은 호출한 쪽이 거릅니다(`net_position`). 보유가 없으면 빈 목록."""
    return rows(_query("domestic_open-interest", {"nxt_key": ""}, client))


def order_history(*, client: TradeClient | None = None) -> list[dict]:
    """당일 주문·체결·미체결 전체. 줄의 `ord_no`·`ord_sts`(6 = 전체체결)로 내 주문을 찾습니다."""
    return rows(_query("domestic_order-history", {
        "trd_div": "0", "exec_div": "0", "trd_tm_div_cd": "1", "ord_div_cd": "0", "nxt_key": "",
    }, client))


# ── 주문 ────────────────────────────────────────────────────


def market_order(
    sym: str, side: str, qty: int = 1, exec_cnd: str = "1", *, client: TradeClient | None = None
) -> dict:
    """시장가 신규주문. `side` 는 `"buy"`·`"sell"`, `exec_cnd` 는 1 FAS · 2 FOK · 3 FAK.

    **재시도하지 않습니다.** 응답을 못 받아도(`TransportError`) 접수됐을 수 있어 같은 주문을 다시
    보내면 이중 주문이 됩니다. 클라이언트가 올리는 예외(`TransportError`·`BusinessError`·`GatewayError`)는
    바꾸지 않고 그대로 올립니다 — 접수 여부는 호출한 쪽이 잔고·주문내역으로 확인합니다.
    """
    return _body("domestic_order", {
        "sym": sym,
        "trd_div": _TRD_DIV[side],
        "ord_tp_cd": "2",
        "ord_qty": str(qty),
        "ord_pric": "0",
        "exec_cnd_cd": exec_cnd,
    }, client)


# ── 종목·틱·보유 읽기 ───────────────────────────────────────


def nearest_usd(futures: list[dict]) -> str:
    """미국달러선물 중 만기가 가장 가까운 월물의 종목코드(`sym_exch`).

    `A75` 로 시작하고 이름에 「플렉스」가 없는 줄만 봅니다. `exp_mon` 은 `"26/09"` 꼴이라 문자열
    순서가 곧 만기 순서입니다.

    Raises:
        ValueError: 맞는 줄이 하나도 없을 때.
    """
    candidates = [
        f for f in futures
        if str(f.get("sym_exch", "")).startswith("A75") and "플렉스" not in str(f.get("sym_nm", ""))
    ]
    if not candidates:
        raise ValueError("미국달러선물(A75…, 플렉스 제외) 줄이 응답에 없습니다.")
    return min(candidates, key=lambda f: f["exp_mon"])["sym_exch"]


def usd_spec(details: list[dict]) -> tuple[float, float]:
    """미국달러선물의 (호가 단위, 1틱 가치). 「(야간)」 줄이 아니라 `미국달러선물(USD)` 줄을 읽습니다.

    Raises:
        ValueError: 그 줄이 없거나 값을 읽을 수 없을 때.
    """
    for row in details:
        if row.get("dtl_cd_ko_nm") == "미국달러선물(USD)":
            tick, value = num(row.get("cd_val_inf_1")), num(row.get("tick_val"))
            if tick is None or value is None:
                break
            return tick, value
    raise ValueError("품목 세부정보에서 미국달러선물(USD) 의 틱·틱가치를 읽지 못했습니다.")


def net_position(positions: list[dict], sym: str) -> int:
    """잔고 줄들에서 `sym` 의 순보유 계약 수. 매수(`trd_div` 1)는 +, 매도는 −."""
    total = 0
    for row in positions:
        if str(row.get("sym", "")).strip() == sym:
            qty = int(num(row.get("opint_qty")) or 0)
            total += qty if str(row.get("trd_div")).strip() == "1" else -qty
    return total
