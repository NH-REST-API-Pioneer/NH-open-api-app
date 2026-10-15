"""대신 답할 때 요청한 종목의 기록을 먼저 고르는지, 그 사실이 화면까지 가는지.

요청이 통째로 같지 않은 흔한 이유는 종목이 아니라 **날짜**입니다. 차트를 오늘
날짜로 부르면 수집한 날과 달라 「같은 요청」이 없고, 그때 아무 기록이나 집으면
화면에 다른 종목의 봉이 섭니다.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.nh_api.client import TradeClient
from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore
from backend.nh_api.replay import (
    MATCH_API,
    MATCH_CROSS_ENVIRONMENT,
    MATCH_EMPTY,
    MATCH_EXACT,
    MATCH_HEADER,
    RECORD_HEADER,
    SYMBOL_HEADER,
    SYMBOL_NONE,
    SYMBOL_SAME,
    ReplayTransport,
    replay_base_url,
    symbol_of,
)
from backend.nh_api.session import create_session
from backend.domestic_futureoption.domestic_routes import get_client, router

PATH = "/trade/v1/domestic/chart-minute"


def 기록(*, record_id, sym, day, environment="real", status=200, close="100"):
    return {
        "format": FIXTURE_FORMAT,
        "transport": "HTTP",
        "api_id": "domestic_chart-minute",
        "environment": environment,
        "market": "domestic",
        "record_id": record_id,
        "collected_at": f"2026-09-0{day}T00:00:00+00:00",
        "scenario_id": "domestic_chart-minute__base",
        "test_group": "",
        "status": "response_received",
        "method": "POST",
        "path": PATH,
        "http_status": status,
        "request": {"sym": sym, "inq_strt_dt": f"2026090{day}"},
        # 차트 응답의 종목 칸은 `sym` 입니다. `sym_exch` 는 현재가 것입니다.
        "response": {"sym": sym, "close": close},
    }


def 창고(*records) -> FixtureStore:
    from backend.nh_api.fixtures import _build
    from pathlib import Path

    return FixtureStore([_build(r, Path("메모리")) for r in records], Path("메모리"))


def 부르기(store, payload, environment="real"):
    전송 = ReplayTransport(store)
    with httpx.Client(transport=전송) as client:
        답 = client.post(f"{replay_base_url(environment)}{PATH}", json=payload)
    return 답, 전송


# ── 고르는 규칙 ──────────────────────────────────────────────


def test_요청이_같으면_그대로_그_기록이다():
    store = 창고(기록(record_id="first", sym="A7569000", day=1))
    답, _ = 부르기(store, {"sym": "A7569000", "inq_strt_dt": "20260901"})

    assert 답.headers[MATCH_HEADER] == MATCH_EXACT
    assert 답.headers[SYMBOL_HEADER] == SYMBOL_SAME


def test_날짜만_달라도_같은_종목의_기록을_고른다():
    """이 이슈의 본론입니다 — 오늘 날짜로 불러도 그 종목의 값이 와야 합니다."""
    store = 창고(
        기록(record_id="theirs", sym="B0169A34", day=1, close="11"),
        기록(record_id="mine", sym="A7569000", day=2, close="22"),
    )
    답, _ = 부르기(store, {"sym": "A7569000", "inq_strt_dt": "20261231"})

    assert 답.json()["sym"] == "A7569000"
    assert 답.headers[MATCH_HEADER] == MATCH_API
    assert 답.headers[SYMBOL_HEADER] == SYMBOL_SAME
    assert 답.headers[RECORD_HEADER] == "mine"


def test_그_종목_기록이_없으면_빈_응답이다():
    """다른 종목의 봉으로는 답하지 않습니다 — 화면에 엉뚱한 종목의 봉이 섭니다."""
    store = 창고(
        기록(record_id="first", sym="B0169A34", day=1),
        기록(record_id="second", sym="C0000000", day=2),
    )
    답, _ = 부르기(store, {"sym": "A7569000", "inq_strt_dt": "20261231"})

    assert 답.headers[MATCH_HEADER] == MATCH_EMPTY
    assert 답.headers[SYMBOL_HEADER] == SYMBOL_NONE
    assert RECORD_HEADER not in 답.headers
    assert "Occurs1" not in 답.json()


def test_같은_종목_중에서도_정상_응답을_먼저_고른다():
    store = 창고(
        기록(record_id="bad", sym="A7569000", day=1, status=400),
        기록(record_id="ok", sym="A7569000", day=2),
    )
    답, _ = 부르기(store, {"sym": "A7569000", "inq_strt_dt": "20261231"})

    assert 답.status_code == 200
    assert 답.headers[RECORD_HEADER] == "ok"
    assert 답.headers[SYMBOL_HEADER] == SYMBOL_SAME


def test_다른_환경으로_넘어갈_때도_종목이_먼저다():
    store = 창고(
        기록(record_id="theirs", sym="B0169A34", day=1, environment="real"),
        기록(record_id="mine", sym="A7569000", day=2, environment="real"),
    )
    # 모의로 물었는데 모의 기록이 없어 실전으로 넘어갑니다.
    답, _ = 부르기(store, {"sym": "A7569000", "inq_strt_dt": "20261231"}, environment="paper")

    assert 답.headers[MATCH_HEADER] == MATCH_CROSS_ENVIRONMENT
    assert 답.headers[SYMBOL_HEADER] == SYMBOL_SAME
    assert 답.headers[RECORD_HEADER] == "mine"


def test_종목을_안_받는_요청은_종목_판정이_없다():
    store = 창고(기록(record_id="first", sym="A7569000", day=1))
    답, _ = 부르기(store, {"inq_strt_dt": "20261231"})

    assert 답.headers[SYMBOL_HEADER] == SYMBOL_NONE


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"sym": "A7569000"}, "A7569000"),
        ({"sym": "  A7569000  "}, "A7569000"),
        ({"sym": ""}, ""),
        ({}, ""),
        ("문자열", ""),
    ],
)
def test_요청에서_종목을_읽는다(payload, expected):
    assert symbol_of(payload) == expected


# ── 화면까지 가는지 ──────────────────────────────────────────


def 앱(store) -> FastAPI:
    session = create_session(replay=True, fixtures=store)
    made = FastAPI()
    made.include_router(router)
    made.dependency_overrides[get_client] = lambda: TradeClient(session)
    return made


def test_재생_모드면_무엇으로_답했는지_화면까지_간다():
    """이 표시가 없으면 화면은 자기가 보는 값이 그 종목의 것인지 모릅니다."""
    store = 창고(
        기록(record_id="theirs", sym="B0169A34", day=1, environment="paper"),
        기록(record_id="mine", sym="A7569000", day=2, environment="paper"),
    )
    with TestClient(앱(store)) as client:
        답 = client.post(
            "/api/domestic/chart-minute",
            json={"sym": "A7569000", "inq_strt_dt": "20261231", "inq_ed_dt": "20261231"},
        )

    assert 답.status_code == 200
    assert 답.headers[MATCH_HEADER] == MATCH_API
    assert 답.headers[SYMBOL_HEADER] == SYMBOL_SAME
    assert 답.headers[RECORD_HEADER] == "mine"


def test_실서버_응답을_만나면_앞서_읽어_둔_표시를_지운다():
    """지우지 않으면 실서버 값에 앞 요청의 저장본 표시가 붙습니다."""
    from backend.nh_api.replay import REPLAY_HEADER, last_replay, note_replay

    note_replay({REPLAY_HEADER: "1", MATCH_HEADER: MATCH_API, SYMBOL_HEADER: SYMBOL_SAME})
    남은것 = last_replay.get()
    assert 남은것 is not None
    assert 남은것["match"] == MATCH_API

    # 실서버 응답에는 재생 헤더가 없습니다.
    note_replay({})
    assert last_replay.get() is None


def test_실서버로_돌_때는_표시가_안_붙는다():
    """붙어 있으면 실서버 값을 저장본으로 오해합니다."""

    class 실서버흉내:
        def call(self, api_id, payload=None, *, environment=None):
            from backend.nh_api.client import ApiResult

            return ApiResult(
                api_id=api_id,
                environment="real",
                market="domestic",
                http_status=200,
                body={"Occurs1": []},
                headers={},  # 재생 헤더가 없습니다.
            )

    made = FastAPI()
    made.include_router(router)
    made.dependency_overrides[get_client] = lambda: 실서버흉내()

    with TestClient(made) as client:
        답 = client.post(
            "/api/domestic/chart-minute",
            json={"sym": "A7569000", "inq_strt_dt": "20261231", "inq_ed_dt": "20261231"},
        )

    assert 답.status_code == 200
    assert MATCH_HEADER not in 답.headers
    assert SYMBOL_HEADER not in 답.headers
