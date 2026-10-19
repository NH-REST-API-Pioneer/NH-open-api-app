"""함수가 실어 보내는 요청 칸이 저장 기록의 요청 칸 안에 드는지.

재생 모드는 요청의 「고르는 인자」가 같은 기록만 골라 답합니다(`nh_api/replay.py`).
그 비교는 **양쪽에 다 있는 칸만** 봅니다 — 함수가 기록에 없는 칸을 새로 싣기
시작하면 재생이 그 칸을 조용히 지나쳐, 새 인자가 자료를 가르는데도 옛 기록으로
답합니다. 이 시험이 그 자리를 잡습니다: 함수마다 기본 인자로 부른 요청 칸이
같은 API 의 저장 기록 요청 칸 안에 들어야 합니다.

기록이 없는 API 는 견줄 것이 없어 목록으로만 들고 있습니다 — 기록이 들어오면
그 API 를 목록에서 빼고 `CALLS` 에 올리라고 시험이 알립니다.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from backend.domestic_futureoption import domestic_futureoption_functions as domestic
from backend.nh_api.catalog import HTTP_APIS
from backend.nh_api.client import ApiResult
from backend.nh_api.fixtures import load_fixtures
from backend.nh_api.replay import NON_SELECTING_FIELDS
from backend.overseas_futureoption import overseas_futureoption_functions as overseas

SYMBOL = "A7569000"
DAY = "20260909"


class 적어두는호출부:
    """부른 API 와 본문을 적어 두고 빈 응답을 돌려줍니다."""

    def __init__(self) -> None:
        self.보낸것: list[tuple[str, dict[str, Any]]] = []

    def call(self, api_id: str, payload: dict[str, Any] | None = None, *, environment=None):
        self.보낸것.append((api_id, dict(payload or {})))
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market=api_id.split("_")[0],
            http_status=200,
            body={},
            headers={},
        )


#: 기록이 있는 API 마다, 그 API 를 부르는 함수를 기본 인자로 한 번.
CALLS: dict[str, Callable[[Any], Any]] = {
    "domestic_price": lambda api: domestic.price(SYMBOL, api=api),
    "domestic_price-night": lambda api: domestic.price_night(SYMBOL, api=api),
    "domestic_price-bid": lambda api: domestic.price_bid(SYMBOL, api=api),
    "domestic_chart-daily": lambda api: domestic.chart_daily(
        SYMBOL, start_date=DAY, end_date=DAY, api=api
    ),
    "domestic_chart-minute": lambda api: domestic.chart_minute(
        SYMBOL, start_date=DAY, end_date=DAY, api=api
    ),
    "domestic_deposit": lambda api: domestic.deposit(DAY, api=api),
    "domestic_open-interest": lambda api: domestic.open_interest(api=api),
    "domestic_order-history": lambda api: domestic.order_history(api=api),
    "domestic_order": lambda api: domestic.order(
        SYMBOL, trd_div="1", ord_tp_cd="2", ord_qty="1", ord_pric="0", api=api
    ),
    "domestic_product-detail": lambda api: domestic.product_detail(api=api),
    "domestic_price-all-futures": lambda api: domestic.price_all_futures("01", api=api),
    "domestic_trend-investor": lambda api: domestic.trend_investor("751", ref_dt=DAY, api=api),
    "domestic_price-all-option": lambda api: domestic.price_all_option(
        "01", exp_mon="260910", api=api
    ),
    "domestic_price-all-option-night": lambda api: domestic.price_all_option_night(
        "01", exp_mon="260910", api=api
    ),
    "overseas_price-all-option": lambda api: overseas.price_all_option(
        "O_ESU26", exch_cd="OCME", api=api
    ),
    "overseas_price": lambda api: overseas.price([("FCME", "MESU26")], api=api),
    "overseas_bid-price": lambda api: overseas.bid_price("MESU26", exch_cd="FCME", api=api),
    "overseas_chart-minute": lambda api: overseas.chart_minute(
        "MESU26", exch_cd="FCME", inq_strt_dt=DAY, inq_ed_dt=DAY, api=api
    ),
    "overseas_chart-daily": lambda api: overseas.chart_daily(
        "MESU26", exch_cd="FCME", inq_strt_dt=DAY, inq_ed_dt=DAY, api=api
    ),
    "overseas_market-operations": lambda api: overseas.market_operations(api=api),
    "overseas_product-detail": lambda api: overseas.product_detail(api=api),
    "overseas_product-expiry": lambda api: overseas.product_expiry("MESU26", api=api),
    "overseas_open-interest-expiry": lambda api: overseas.open_interest_expiry(api=api),
}

#: 함수는 있는데 저장 기록이 없는 API. 견줄 것이 없어 여기서는 안 봅니다.
#:
#: 주문가능수량은 함수가 싣는 `rt_tp`(가능수량계산구분)가 실제 요청에는 없습니다.
#: 이 API 를 `CALLS` 로 올리면 이 시험이 그 칸을 잡습니다.
#:
#: 인자가 있을 때만 칸을 싣는 함수(해외 예수금 `biz_dt`, 잔고 `prd_cd`, 누적손익
#: `cur_cd`·`prd_cd`)는 `CALLS` 로 올릴 때 그 인자를 준 채로 불러야 그 칸이 검사에
#: 듭니다.
NO_RECORDS: frozenset[str] = frozenset(
    {
        "domestic_modify",
        "domestic_cancel",
        "domestic_order-night",
        "domestic_modify-night",
        "domestic_cancel-night",
        "domestic_order-error",
        "domestic_orderable-quantity",
        "overseas_deposit",
        "overseas_open-interest",
        "overseas_order-history",
        "overseas_orderable-quantity",
        "overseas_order",
        "overseas_order-error",
        "overseas_cumulative-pl",
    }
)


def _recorded_keys() -> dict[str, set[str]]:
    made: dict[str, set[str]] = {}
    for fixture in load_fixtures().http:
        request = fixture.request if isinstance(fixture.request, dict) else {}
        made.setdefault(fixture.api_id, set()).update(request.keys())
    return made


@pytest.mark.parametrize("api_id", sorted(CALLS))
def test_함수가_싣는_칸은_기록의_칸_안에_든다(api_id):
    recorded = _recorded_keys()
    assert api_id in recorded, f"{api_id} 기록이 없습니다 — NO_RECORDS 로 옮기세요"

    호출부 = 적어두는호출부()
    CALLS[api_id](호출부)
    (called, payload), = 호출부.보낸것
    assert called == api_id

    extra = set(payload) - recorded[api_id]
    assert not extra, f"{api_id}: 기록에 없는 칸을 싣습니다 {sorted(extra)} — 재생이 이 칸을 못 봅니다"
    # 반대 방향 — 기록에는 있는데 함수가 안 싣는 고르는 칸이 있으면, 재생은 그 칸을
    # 안 보고 기록 여럿 중 아무것이나 후보로 삼습니다.
    missing = (recorded[api_id] - set(payload)) - NON_SELECTING_FIELDS
    assert not missing, f"{api_id}: 기록의 고르는 칸을 안 싣습니다 {sorted(missing)}"


def test_기록_없는_API_목록이_사실과_같다():
    """기록이 들어오면 여기서 알립니다 — 그 API 를 `CALLS` 로 올리라는 뜻입니다."""
    recorded = set(_recorded_keys())
    now_recorded = NO_RECORDS & recorded
    assert not now_recorded, f"기록이 생겼습니다: {sorted(now_recorded)} — CALLS 에 올리세요"
    # 두 함수 모듈이 부르는 API 이름 전부가 둘 중 한 곳에 있어야 합니다 — 새 함수가
    # 생기면 여기서 알립니다. 야간 주문 셋은 이름을 만들어 부르므로 따로 더합니다.
    import inspect
    import re

    source = inspect.getsource(domestic) + inspect.getsource(overseas)
    called = set(re.findall(r'"((?:domestic|overseas)_[a-z-]+)"', source))
    called |= {"domestic_order-night", "domestic_modify-night", "domestic_cancel-night"}
    assert called <= set(HTTP_APIS), f"카탈로그에 없는 이름: {sorted(called - set(HTTP_APIS))}"
    uncovered = called - set(CALLS) - NO_RECORDS
    assert not uncovered, f"어느 목록에도 없는 API: {sorted(uncovered)}"
    assert not (set(CALLS) & NO_RECORDS), "한 API 가 두 목록에 있습니다"
