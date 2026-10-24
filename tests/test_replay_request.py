"""재생이 요청 인자를 보고 기록을 고르는지.

조회구분이 다른 기록으로 답하면 화면이 틀린 줄을 맞는 줄로 봅니다 — 미체결 조회에
체결 완료 줄이 서는 식입니다. 여기서 붙잡아 두는 성질은 넷입니다.

1. 고르는 인자가 같은 기록만 후보이고, 없으면 **빈 응답**입니다
2. 요청이 「전체」면 어떤 기록과도 맞고, 반대는 아닙니다
3. 날짜·시각·이어받기 키는 고르는 인자가 아닙니다
4. 주문은 요청이 통째로 같은 기록으로만 답하고, 없으면 답하지 않습니다
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore, _build, load_fixtures
from backend.nh_api.replay import (
    EMPTY_BODY,
    MATCH_API,
    MATCH_CROSS_ENVIRONMENT,
    MATCH_EMPTY,
    MATCH_EXACT,
    MATCH_HEADER,
    ORDER_PATHS,
    RECORD_HEADER,
    SYMBOL_HEADER,
    SYMBOL_SAME,
    ReplayMiss,
    ReplayTransport,
    replay_base_url,
    selects_same,
)

HISTORY = "/trade/v1/domestic/order-history"
DEPOSIT = "/trade/v1/domestic/deposit"
ORDER = "/trade/v1/domestic/order"


def _기록(*, record_id, api_id, path, request, response, environment="paper", collected_at="2026-09-09T00:00:00+00:00"):
    return _build(
        {
            "format": FIXTURE_FORMAT,
            "transport": "HTTP",
            "api_id": api_id,
            "environment": environment,
            "market": "domestic",
            "record_id": record_id,
            "collected_at": collected_at,
            "scenario_id": f"{api_id}__base",
            "test_group": "",
            "status": "response_received",
            "method": "POST",
            "path": path,
            "http_status": 200,
            "request": request,
            "response": response,
        },
        Path("메모리"),
    )


def _주문내역(record_id, *, exec_div="0", trd_tm_div_cd="1", rows=1, environment="paper", collected_at="2026-09-09T00:00:00+00:00"):
    return _기록(
        record_id=record_id,
        api_id="domestic_order-history",
        path=HISTORY,
        environment=environment,
        collected_at=collected_at,
        request={
            "exec_div": exec_div,
            "trd_div": "0",
            "trd_tm_div_cd": trd_tm_div_cd,
            "ord_div_cd": "0",
            "nxt_key": "",
        },
        response={"nrec": f"{rows:04d}", "nxt_key": "", **({"Occurs1": [{"occurs1_ord_no": "1"}] * rows} if rows else {})},
    )


def _창고(*records) -> FixtureStore:
    return FixtureStore(list(records), Path("메모리"))


def _부르기(store, path, payload, environment="paper"):
    전송 = ReplayTransport(store)
    with httpx.Client(transport=전송) as client:
        return client.post(f"{replay_base_url(environment)}{path}", json=payload)


def _전체조회(**덮어쓰기):
    물음 = {"exec_div": "0", "trd_div": "0", "trd_tm_div_cd": "0", "ord_div_cd": "0", "nxt_key": ""}
    물음.update(덮어쓰기)
    return 물음


# ── 1. 고르는 인자가 다르면 빈 응답 ──────────────────────────


def test_조회구분이_다르면_빈_응답이다():
    """전체 조회 기록밖에 없는데 미체결을 물으면 0건입니다 — 체결 끝난 줄을 미체결로 내지 않습니다."""
    store = _창고(_주문내역("all", exec_div="0", rows=2))

    답 = _부르기(store, HISTORY, _전체조회(exec_div="2", trd_tm_div_cd="1"))

    assert 답.status_code == 200
    assert 답.headers[MATCH_HEADER] == MATCH_EMPTY
    assert RECORD_HEADER not in 답.headers
    assert 답.json() == EMPTY_BODY


def test_조회구분이_같은_기록이_있으면_그것이다():
    store = _창고(
        _주문내역("all", exec_div="0", rows=2, collected_at="2026-09-09T00:00:01+00:00"),
        _주문내역("open", exec_div="2", rows=1, collected_at="2026-09-09T00:00:02+00:00"),
    )

    답 = _부르기(store, HISTORY, _전체조회(exec_div="2", trd_tm_div_cd="1"))

    assert 답.headers[MATCH_HEADER] == MATCH_EXACT
    assert 답.headers[RECORD_HEADER] == "open"


def test_후보_안에서는_정상_줄_담김_이른_것_차례다():
    store = _창고(
        _주문내역("empty", exec_div="2", rows=0, collected_at="2026-09-09T00:00:01+00:00"),
        _주문내역("rows", exec_div="2", rows=1, collected_at="2026-09-09T00:00:02+00:00"),
    )
    # 날짜 칸을 덧붙여 통째 일치는 안 되게 하고, 고르는 인자만 같게 둡니다.
    답 = _부르기(store, HISTORY, {**_전체조회(exec_div="2", trd_tm_div_cd="1"), "inq_dt": "20261231"})

    assert 답.headers[MATCH_HEADER] == MATCH_API
    assert 답.headers[RECORD_HEADER] == "rows"


# ── 2. 「전체」는 부분을 품는다 ───────────────────────────────


def test_요청이_전체면_특정_값의_기록도_맞는다():
    """주간(1) 기록뿐이어도 전체(0) 조회는 그것으로 답합니다."""
    store = _창고(_주문내역("day", trd_tm_div_cd="1", rows=1))

    답 = _부르기(store, HISTORY, _전체조회(trd_tm_div_cd="0"))

    assert 답.headers[MATCH_HEADER] == MATCH_API
    assert 답.headers[RECORD_HEADER] == "day"


def test_기록이_전체이고_요청이_특정이면_맞지_않는다():
    store = _창고(_주문내역("all", trd_tm_div_cd="0", rows=1))

    답 = _부르기(store, HISTORY, _전체조회(trd_tm_div_cd="2"))

    assert 답.headers[MATCH_HEADER] == MATCH_EMPTY


def test_고르는_인자_비교의_규칙():
    # 날짜·이어받기 키는 안 봅니다.
    assert selects_same({"biz_dt": "20261231", "nxt_key": "x"}, {"biz_dt": "20260909", "nxt_key": ""})
    # **해외 분봉만 다릅니다** — 그 API 는 키가 쪽을 가릅니다(날짜를 안 보는 API 라).
    분봉 = "/trade/v1/overseas/chart-minute"
    assert not selects_same({"nxt_key": "키2"}, {"nxt_key": "99999999"}, 분봉)
    assert selects_same({"nxt_key": "키2"}, {"nxt_key": "키2"}, 분봉)
    assert selects_same({"inq_strt_dt": "20261231"}, {"inq_strt_dt": "20260909"}, 분봉), "날짜는 그대로 안 봅니다."
    # 같은 칸에 다른 값이면 다른 요청입니다.
    assert not selects_same({"exec_div": "2"}, {"exec_div": "0"})
    # 요청이 전체면 맞고, 기록이 전체면 안 맞습니다.
    assert selects_same({"exec_div": "0"}, {"exec_div": "2"})
    assert not selects_same({"exec_div": "2"}, {"exec_div": "0"})
    # 한쪽에만 있는 칸은 견주지 않습니다.
    assert selects_same({"dcnt": "1", "nght_tp": "2"}, {"nght_tp": "2"})
    assert not selects_same({"dcnt": "1", "nght_tp": "2"}, {"nght_tp": "1"})
    # 종목은 여기서 안 봅니다 — 종목은 따로 같은 종목만 고릅니다.
    assert selects_same({"sym": "A", "nght_tp": "1"}, {"sym": "B", "nght_tp": "1"})


# ── 3. 날짜는 고르는 인자가 아니다 ───────────────────────────


def test_날짜만_다른_예수금은_그_기록으로_답한다():
    store = _창고(
        _기록(record_id="d", api_id="domestic_deposit", path=DEPOSIT, request={"biz_dt": "20260909"}, response={"dps_amt": "1"})
    )
    답 = _부르기(store, DEPOSIT, {"biz_dt": "20261231"})
    assert 답.headers[MATCH_HEADER] == MATCH_API
    assert 답.headers[RECORD_HEADER] == "d"


# ── 다른 환경 ───────────────────────────────────────────────


def test_그_환경에_후보가_없으면_다른_환경의_후보다():
    store = _창고(_주문내역("real-open", exec_div="2", rows=1, environment="real"))

    답 = _부르기(store, HISTORY, _전체조회(exec_div="2", trd_tm_div_cd="1"), environment="paper")

    assert 답.headers[MATCH_HEADER] == MATCH_CROSS_ENVIRONMENT
    assert 답.headers[RECORD_HEADER] == "real-open"
    # 어느 환경에도 후보가 없으면 다른 환경의 다른 인자 기록으로도 안 답합니다.
    assert _부르기(store, HISTORY, _전체조회(exec_div="3"), environment="paper").headers[MATCH_HEADER] == MATCH_EMPTY


def test_그_API_기록이_하나도_없으면_답하지_않는다():
    store = _창고(_주문내역("x"))
    with pytest.raises(ReplayMiss):
        _부르기(store, DEPOSIT, {"biz_dt": "20260909"})


# ── 4. 주문은 통째로 같아야 ────────────────────────────────


def _주문기록(record_id, *, ord_qty="1", environment="paper"):
    return _기록(
        record_id=record_id,
        api_id="domestic_order",
        path=ORDER,
        environment=environment,
        request={"sym": "A7569000", "trd_div": "1", "ord_tp_cd": "2", "ord_qty": ord_qty, "ord_pric": "0", "exec_cnd_cd": "1"},
        response={"ord_no": "5959762237", "msg_cd": "", "msg_cntn": ""},
    )


def test_주문은_통째로_같은_기록으로만_답한다():
    store = _창고(_주문기록("one", ord_qty="1"))
    같은주문 = {"sym": "A7569000", "trd_div": "1", "ord_tp_cd": "2", "ord_qty": "1", "ord_pric": "0", "exec_cnd_cd": "1"}

    답 = _부르기(store, ORDER, 같은주문)
    assert 답.headers[MATCH_HEADER] == MATCH_EXACT

    # 수량이 다르면 기록된 접수로도, 빈 응답으로도 답하지 않습니다.
    with pytest.raises(ReplayMiss):
        _부르기(store, ORDER, {**같은주문, "ord_qty": "2"})


def test_주문_경로는_카탈로그의_주문_등급_전부다():
    paths = {path for _, path in ORDER_PATHS}
    for name in ("order", "modify", "cancel", "order-night", "modify-night", "cancel-night"):
        assert f"/trade/v1/domestic/{name}" in paths
    assert "/trade/v1/overseas/order" in paths
    assert HISTORY not in paths


# ── 저장소의 진짜 기록으로 ────────────────────────────────────


def test_공개_기록으로_미체결을_물으면_빈_응답이다():
    """저장소의 국내 주문내역 기록은 전부 전체(0) 조회입니다 — 미체결(2)은 0건이어야 합니다."""
    store = load_fixtures()
    체결완료 = _부르기(store, HISTORY, _전체조회(exec_div="0"))
    미체결 = _부르기(store, HISTORY, _전체조회(exec_div="2"))

    assert 체결완료.headers[MATCH_HEADER] in (MATCH_EXACT, MATCH_API)
    assert 체결완료.json().get("Occurs1")
    assert 미체결.headers[MATCH_HEADER] == MATCH_EMPTY
    assert "Occurs1" not in 미체결.json()


def test_라우트까지_이어진다():
    from backend.main import app
    from backend.nh_api import runtime
    from backend.nh_api.session import create_session

    runtime.use(create_session(replay=True))
    try:
        client = TestClient(app)
        미체결 = client.post("/api/domestic/order-history", json={"exec_div": "2"})
        전체 = client.post("/api/domestic/order-history", json={"exec_div": "0"})
    finally:
        runtime.reset()

    assert 미체결.status_code == 200
    assert 미체결.json()["orders"] == []
    assert 미체결.headers["x-nh-replay-match"] == MATCH_EMPTY
    assert 전체.json()["orders"], "전체 조회는 주간(1) 기록으로 답합니다."


# ── 여러 종목을 한 번에 묻는 요청 ──────────────────────────────

PRICE = "/trade/v1/overseas/price"


def _해외현재가(record_id, sym, *, exch_cd="FCME", environment="real", last="1.0"):
    return _기록(
        record_id=record_id,
        api_id="overseas_price",
        path=PRICE,
        environment=environment,
        request={"Iccurs1": [{"iccurs1_exch_cd": exch_cd, "iccurs1_sym": sym}]},
        response={"nrec": "0001", "Occurs1": [{"occurs1_sym": sym, "occurs1_last_pric": last}]},
    )


def _여럿(*syms):
    return {"Iccurs1": [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": sym} for sym in syms]}


def test_여러_종목은_종목마다_기록을_모아_한_응답으로_답한다():
    store = _창고(
        _해외현재가("es", "ESZ26", last="6500.0"),
        _해외현재가("nq", "NQZ26", environment="paper", last="23000.0"),
    )

    답 = _부르기(store, PRICE, _여럿("NQZ26", "ESZ26"), environment="real")

    assert 답.status_code == 200
    몸 = 답.json()
    assert [row["occurs1_sym"] for row in 몸["Occurs1"]] == ["NQZ26", "ESZ26"], "부른 차례대로"
    assert 몸["nrec"] == "0002"
    # 하나가 다른 환경에서 왔습니다.
    assert 답.headers[MATCH_HEADER] == MATCH_CROSS_ENVIRONMENT
    assert 답.headers[RECORD_HEADER] == "nq+es"


def test_기록_없는_종목은_빠지고_있는_것만_온다():
    store = _창고(_해외현재가("es", "ESZ26"))

    답 = _부르기(store, PRICE, _여럿("ESZ26", "없는종목"), environment="real")

    assert [row["occurs1_sym"] for row in 답.json()["Occurs1"]] == ["ESZ26"]
    assert 답.headers[MATCH_HEADER] == MATCH_API
    # 한 종목만 물었고 기록과 통째로 같으면 그대로 exact 이고, 종목 판정도 모아 답할 때와 같습니다.
    하나 = _부르기(store, PRICE, _여럿("ESZ26"), environment="real")
    assert 하나.headers[MATCH_HEADER] == MATCH_EXACT
    assert 하나.headers[SYMBOL_HEADER] == SYMBOL_SAME == 답.headers[SYMBOL_HEADER]


def test_전부_기록_없는_종목이면_빈_응답이다():
    store = _창고(_해외현재가("es", "ESZ26"))
    답 = _부르기(store, PRICE, _여럿("없는종목", "또없음"), environment="real")
    assert 답.headers[MATCH_HEADER] == MATCH_EMPTY
    assert 답.json() == EMPTY_BODY


def test_공개_기록의_해외_현재가_둘을_한_번에_묻는다():
    """저장소의 해외 현재가 기록은 한 종목씩 둘입니다 — 둘을 함께 물으면 두 줄이 옵니다."""
    store = load_fixtures()
    답 = _부르기(
        store,
        PRICE,
        {
            "Iccurs1": [
                {"iccurs1_exch_cd": "OCME", "iccurs1_sym": "O_ESU26-C7600.0"},
                {"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"},
            ]
        },
        environment="real",
    )
    assert [row["occurs1_sym"] for row in 답.json()["Occurs1"]] == ["O_ESU26-C7600.0", "MESU26"]
    assert 답.headers[MATCH_HEADER] == MATCH_API
