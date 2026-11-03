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

해외(SGX 미니 원달러 MKU)는 `ovs_` 로 시작하는 함수들입니다. 같은 규칙(모의 서버만·주문 한 번·조회만 재시도)이고,
국내와 칸 이름이 달라 따로 둡니다 — 매수매도 칸이 `trd_div` 가 아니라 `trd_tp`, 거절이 `msg_cd` 가 아니라 `err_cd`,
현재가가 본문이 아니라 `Occurs1` 첫 줄. 해외 주문·주문내역·잔고·예수금은 저장소에 기록이 없어 칸 이름의
근거를 함수 설명에 적었습니다(운영자 `backend/overseas_futureoption/` · week03 `nh_client.py`).

함수마다 `client` 키워드로 접속을 바꿔 끼울 수 있습니다(시험용). 없으면 `runtime.client()` 입니다.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from backend import orders
from backend.nh_api import error_codes, runtime
from backend.nh_api.client import TradeClient
from backend.nh_api.errors import BusinessError, GatewayError, TransportError
from backend.sessions.hours import now_kst

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


# ── 해외 (SGX 미니 원달러 MKU) ──────────────────────────────

#: MKU 가 거래되는 거래소 코드(선물 `F` + 싱가포르 `SGX`). 근거: `etc_fut.mst` 의 `ExchName`, week03 `ws_trader` 의 `--mku` 기본 구독.
OVS_EXCHANGE = "FSGX"

#: 해외 주문내역 `ord_sts`: 전체체결. 근거: 운영자 `overseas_account.ORDER_STATUS`(1 접수·3 확인·4 부분체결·
#: 6 전체체결·8 자동취소·9 거부 — 주문내역 명세) 와 `FINISHED_STATUS`. **기록이 없습니다** — 값이 국내와
#: 같다는 것은 운영자가 명세로 읽은 것이고, 실제 모의 응답으로는 첫 주문에서야 확인됩니다.
OVS_FILLED = "6"

#: 해외 주문내역 `ord_sts`: 자동취소(8)·거부(9) — 체결 안 됨이 확인된 것. 근거는 `OVS_FILLED` 와 같습니다.
OVS_REJECTED = ("8", "9")

#: 해외 품목별 세부정보를 「통화」 그룹만 받는 값. 근거: week03 `nh_client.ovs_product_detail`(FG2 = 통화).
#: 기록으로도 확인됩니다 — 전체 조회는 100줄에서 `nxt_key` 로 쪽이 나뉘지만, FG2 는 31줄 한 쪽에 MKU·KU 가 다 있습니다.
_OVS_CURRENCY_GROUP = "FG2"


def ovs_chart_minute(sym: str, *, req_qty: int, exch_cd: str = OVS_EXCHANGE, client: TradeClient | None = None) -> list[dict]:
    """해외 1분봉. 최신 봉이 먼저 오고 `exch_tm`·`ref_dt` 는 한국시간입니다(2026-11-03 모의 조회, 설계 문서).

    요청 값: week03 `nh_client.ovs_chart_minute`(기간 `00000000`~`99999999` 로 최신부터 `req_qty` 개)와
    운영자 `overseas_futureoption_functions.chart_minute`(:333) — 해외는 연결선물이 없어 `cidx_yn` 은 `0`,
    국내의 `nght_tp`·`fut_cidx_exp_mod` 는 없습니다. 줄 칸은 `tests/fixtures/nh/overseas_chart-minute` 기록:
    `ref_dt` `exch_tm` `open_pric` `high_pric` `low_pric` `close_pric` `glb_biz_dt` `cum_trd_qty` 등.
    """
    return rows(_query("overseas_chart-minute", {
        "exch_cd": exch_cd,
        "sym": sym,
        "inq_strt_dt": "00000000",
        "strt_tm": "000000",
        "inq_ed_dt": "99999999",
        "ed_tm": "235959",
        "req_qty": str(req_qty),
        "dcnt": "1",
        "cidx_yn": "0",
        "nxt_key": "99999999",
    }, client))


def ovs_price(sym: str, *, exch_cd: str = OVS_EXCHANGE, client: TradeClient | None = None) -> dict:
    """해외 현재가 — `Occurs1` 첫 줄(접두를 뗀 dict). 마지막 체결가는 `last_pric`, 호가는 `bid_pric`·`ask_pric`, 시각 `trd_tm`.

    국내와 달리 본문이 아니라 배열 한 줄로 옵니다(`tests/fixtures/nh/overseas_price` 기록). 요청은 배열 `Iccurs1` —
    운영자 `overseas_futureoption_functions.price`(:267) 와 기록이 배열이고, week03 은 객체 하나로 보냈습니다
    (서버는 한 번에 한 종목만 받습니다). 줄이 없으면 빈 dict 입니다.
    """
    got = rows(_query("overseas_price", {"Iccurs1": [{"iccurs1_exch_cd": exch_cd, "iccurs1_sym": sym}]}, client))
    return got[0] if got else {}


def ovs_product_detail(*, client: TradeClient | None = None) -> list[dict]:
    """해외 선물 품목별 세부정보(통화 그룹) — 줄 하나가 품목: `prd_cd` `tick_unt` `tick_val` `ctr_unt` `cur_cd` 등.

    요청 값은 week03 `nh_client.ovs_product_detail("FG2")`(`fut_opt_div_cd` F). 줄 칸은 기록
    `tests/fixtures/nh/overseas_product-detail`.
    """
    return rows(_query("overseas_product-detail", {
        "sett_cd": "", "fut_opt_div_cd": "F", "cur_cd": "", "prd_grp_cd": _OVS_CURRENCY_GROUP,
        "exch_cd": "", "nxt_key": "", "prd_nm": "", "prd_cd": "",
    }, client))


def mku_spec(details: list[dict]) -> tuple[float, float]:
    """MKU 의 (호가 단위, 1틱 가치 USD). 품목코드 `MKU` 줄을 읽습니다 — 큰 계약 `KU`(0.00005, 6.25) 줄이 아닙니다.

    기록: `tick_unt` `00000000000000000000.000100000` · `tick_val` `00000000000000002.50000000`.

    Raises:
        ValueError: 그 줄이 없거나 값을 읽을 수 없을 때.
    """
    for row in details:
        if str(row.get("prd_cd", "")).strip() == "MKU":
            tick, value = num(row.get("tick_unt")), num(row.get("tick_val"))
            if tick is None or value is None:
                break
            return tick, value
    raise ValueError("해외 품목 세부정보에서 MKU 의 틱·틱가치를 읽지 못했습니다.")


def nearest_mku(master_rows: list[dict]) -> str:
    """MKU 최근월물의 종목코드(`MKUX26` 꼴). 인자는 해외 종목 마스터 `etc_fut.mst` 의 줄 dict 들입니다.

    근거: 마스터가 줄마다 근월 표지를 줍니다 — `lmon`(거래량 기준)·`lmon_my`(**만기일 기준**) (운영자
    `overseas_futureoption/master/__init__.py` 의 `OVERSEAS_FUTURES_FIELDS`). 2026-11-03 받은 파일에서
    `MKUX26`(202611)만 둘 다 `1` 입니다. 그래서 `comd`=MKU·`type`=F·`trdf`=0(거래 가능) 중
    `lmon_my`=1 인 줄을 고르고, 표지가 하나도 없으면 만기년월 `yymm`(`YYYYMM`, 문자열 순서 = 만기 순서)이
    가장 이른 줄을 씁니다. 품목 만기 조회(`overseas_product-expiry`)는 종목코드를 먼저 알아야 하고 MKU 응답
    기록이 없어(CME MES 기록만) 쓰지 않았습니다. 마스터는 날마다 새로 받으므로 월물이 넘어가면 표지도 넘어갑니다.

    줄을 가져오는 법: `master_store.load_master(...)` 의 `table.rows_as_dicts()`.

    Raises:
        ValueError: 거래 가능한 MKU 선물 줄이 하나도 없을 때.
    """
    candidates = [
        r for r in master_rows
        if str(r.get("comd", "")).strip() == "MKU"
        and str(r.get("type", "")).strip() == "F"
        and str(r.get("trdf", "")).strip() == "0"
    ]
    if not candidates:
        raise ValueError("마스터에 거래 가능한 MKU 선물 줄이 없습니다.")
    flagged = [r for r in candidates if str(r.get("lmon_my", "")).strip() == "1"]
    return str(min(flagged or candidates, key=lambda r: str(r.get("yymm", "")))["code"]).strip()


def ovs_deposit(cur_cd: str = "USD", *, biz_dt: str = "", client: TradeClient | None = None) -> dict:
    """해외 예수금 — 본문 한 덩어리. 통화별(`cvs_div` 1). 수수료 `fee`·`fut_fee`, 실현손익 `cls_pl_amt`, 주문가능금액 `ord_psb_amt`.

    근거: week03 `nh_client.ovs_deposit`(수수료·실현손익을 읽는 용도, 모의 계좌) 와 운영자
    `overseas_account.py` 의 예수금 칸 표(:60~110). **기록이 없습니다.** `biz_dt` 가 비면 서버가 ETR018 로
    거절한다고 week03 이 적어서 비우면 지금 한국 날짜를 채웁니다(해외영업일과 다를 수 있어 필요하면 넘기세요).
    """
    return _query("overseas_deposit", {
        "biz_dt": biz_dt or now_kst().strftime("%Y%m%d"),
        "cur_cd": cur_cd,
        "cvs_div": "1",
    }, client)


def ovs_open_interest(*, client: TradeClient | None = None) -> list[dict]:
    """해외 잔고(보유 포지션) — 계좌 전체. 줄 칸: `sym` `trd_tp`(1 매수·2 매도) `opint_qty` `avg_pric` `cls_psb_qty`.

    근거: week03 `nh_client.ovs_open_interest`(요청 `nxt_key`) 와 운영자 `overseas_account.py`(:333~353 읽는 칸).
    **기록이 없습니다.** 보유가 없으면 빈 목록. 종목은 호출한 쪽이 거릅니다(`ovs_net_position`).
    """
    return ovs_open_interest_page(client=client)[0]


def ovs_open_interest_page(nxt_key: str = "", *, client: TradeClient | None = None) -> tuple[list[dict], str]:
    """해외 잔고 한 쪽 — (줄, 다음 쪽 키). 키가 비면 첫 쪽. 쪽을 따라가며 합치는 일은 `markets` 의 해외 어댑터가 합니다.

    다음 쪽 키는 본문의 `nxt_key`(운영자 `overseas_account.open_interest`:357 이 화면에 넘기는 그 칸).
    """
    body = _query("overseas_open-interest", {"nxt_key": nxt_key}, client)
    return rows(body), _next_key(body)


def _next_key(body: Any) -> str:
    """응답의 다음 쪽 키(`nxt_key`, 앞뒤 빈칸 뗌). 없으면 빈 문자열 — 운영자 해외 계좌 해석과 같은 읽기."""
    return str(body.get("nxt_key") or "").strip() if isinstance(body, dict) else ""


def ovs_order_history(*, client: TradeClient | None = None) -> list[dict]:
    """해외 당일 주문·체결·미체결 전체(`inq_div` 0). 줄 칸: `ord_no` `sym` `ord_sts` `exec_qty` `exec_pric` `ord_avg_pric` `exec_tm` `err_cd` `rejt_rsn`.

    근거: week03 `nh_client.ovs_order_history`(요청 — week03 이 모의에서 주문 뒤 체결을 확인한 그 요청) 와
    운영자 `overseas_account.order_history`(:420~475 읽는 칸). **기록이 없습니다.** 국내와 달리 조회구분이 `inq_div`
    이고 매수매도가 `trd_div_cd`/`trd_tp` 입니다.
    """
    return ovs_order_history_page(client=client)[0]


def ovs_order_history_page(nxt_key: str = "", *, client: TradeClient | None = None) -> tuple[list[dict], str]:
    """해외 주문내역 한 쪽 — (줄, 다음 쪽 키). 요청 값은 `ovs_order_history` 와 같고 `nxt_key` 만 바뀝니다.

    다음 쪽 키는 본문의 `nxt_key`(운영자 `overseas_account.order_history`:478).
    """
    body = _query("overseas_order-history", {
        "trd_div_cd": "0", "inq_div": "0", "nxt_key": nxt_key, "prd_cd": "",
    }, client)
    return rows(body), _next_key(body)


def ovs_market_order(sym: str, side: str, qty: int = 1, *, client: TradeClient | None = None) -> dict:
    """해외 시장가 신규주문(`qt_div_cd` 1 · `glb_ord_tp_cd` 1 · 가격 `0`). `side` 는 `"buy"`·`"sell"`.

    근거: week03 `nh_client.ovs_market_order`(요청) 와 운영자 `overseas_futureoption_functions.order`(:211, 시장가는 주문가격 `0`·
    스탑가격 빈 값·신규는 원주문번호 `0`). **기록이 없습니다.** 응답 칸은 `ord_no` `err_cd` `err_msg` (운영자 `order_result`).

    **재시도하지 않습니다.** 응답을 못 받아도(`TransportError`) 접수됐을 수 있어 같은 주문을 다시 보내면
    이중 주문이 됩니다. 클라이언트가 올리는 예외는 바꾸지 않고 그대로 올립니다 — 접수 여부는 호출한 쪽이
    잔고·주문내역으로 확인합니다.

    **해외 거절은 `err_cd` 로 옵니다.** 공통 클라이언트는 `msg_cd` 만 보므로 여기서 거절(`err_cd` 가 비어 있지도
    전부 0 이지도 않은 것 — 접수에도 `00000` 이 실려 옵니다)을 `BusinessError` 로 올립니다. 안 올리면 거절된 주문이 접수로
    읽힙니다(운영자 `overseas_routes.py`:1276, `strategy/sim.py` `_raise_overseas_refusal`).
    """
    body = _body("overseas_order", {
        "qt_div_cd": "1",
        "sym": sym,
        "trd_div_cd": _TRD_DIV[side],
        "glb_ord_tp_cd": "1",
        "ord_qty": str(qty),
        "ord_pric": "0",
        "stop_pric": "",
        "org_ord_no": "0",
    }, client)
    code = str(body.get("err_cd") or "").strip() if isinstance(body, dict) else ""
    if orders.failed(code):
        raise BusinessError("overseas_order", code, str(body.get("err_msg") or "").strip(), body)
    return body


def ovs_net_position(positions: list[dict], sym: str) -> int:
    """해외 잔고 줄들에서 `sym` 의 순보유 계약 수. 매수(`trd_tp` 1)는 +, 매도(2)는 −.

    국내 `net_position` 과 달리 방향 칸이 `trd_tp` 입니다(운영자 `overseas_account.py`:165 `POSITION_SIDE`, :341).
    **방향 코드가 1·2 가 아니면 `ValueError`** — 부호를 짐작해 틀린 방향으로 잔고 관문을 열지 않습니다
    (수량이 0 인 줄은 방향을 안 봅니다).
    """
    total = 0
    for row in positions:
        if str(row.get("sym", "")).strip() != sym:
            continue
        qty = int(num(row.get("opint_qty")) or 0)
        if not qty:
            continue
        side = str(row.get("trd_tp", "")).strip()
        if side == "1":
            total += qty
        elif side == "2":
            total -= qty
        else:
            raise ValueError(f"해외 잔고 줄의 매수매도 구분(trd_tp)을 읽지 못했습니다: {side!r}")
    return total


def ovs_fill_price(row: dict) -> float | None:
    """해외 주문내역 한 줄의 체결가 — `exec_pric`, 0 이거나 비면 `ord_avg_pric`, 둘 다 못 읽으면 None.

    `exec_pric` 이 먼저인 것은 week03 `ws_trader` 가 모의 체결가를 이 칸으로 읽어 쓴 실사용이 있기 때문입니다
    (`float(fill["exec_pric"])`, 체결 시각은 `exec_tm`). `ord_avg_pric`(주문평균가격)은 운영자
    `order_history`(:455)가 읽는 칸으로, 기록이 없어 보조로만 씁니다. 1계약 시장가는 둘이 같습니다.
    """
    for key in ("exec_pric", "ord_avg_pric"):
        value = num(row.get(key))
        if value:
            return value
    return None
