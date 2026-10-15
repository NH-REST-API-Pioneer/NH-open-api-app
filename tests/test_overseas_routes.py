"""`/api/overseas/…` 라우트.

**저장소에 해외 계좌 저장본이 없습니다.** 그래서 재생 클라이언트가 아니라
만들어 낸 저장소로 세웁니다 — 국내 라우트 시험과 방식이 다른 까닭입니다.
값도 종목코드도 지어낸 것이라 **모양만 봅니다.**
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.nh_api.client import ApiResult, TradeClient
from backend.nh_api.errors import BusinessError, TransportError
from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore, _build
from backend.nh_api.replay import MATCH_HEADER, RECORD_HEADER, REPLAY_HEADER, SYMBOL_HEADER
from backend.nh_api.session import create_session
from backend.overseas_futureoption import overseas_routes
from backend.overseas_futureoption.overseas_routes import get_client

# 지어낸 종목코드입니다. 실제 종목과 겹치지 않게 골랐습니다.
지어낸종목 = "ZZZZ26"


def _기록(api_id: str, path: str, request: dict[str, Any], response: dict[str, Any]):
    """저장본 한 줄. 반입한 기록과 칸 구성이 같아야 재생이 읽습니다."""
    return _build(
        {
            "format": FIXTURE_FORMAT,
            "transport": "HTTP",
            "api_id": api_id,
            "environment": "paper",
            "market": "overseas",
            "record_id": f"made-up-{api_id}",
            "collected_at": "2026-09-09T00:00:00+00:00",
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


def _예수금():
    return _기록(
        "overseas_deposit",
        "/trade/v1/overseas/deposit",
        {"cur_cd": "KRW", "cvs_div": "2"},
        {
            "biz_dt": "20260909",
            "ac_no": "FAKE-AC-000000",
            "cur_cd": "KRW",
            "cur_fgr_cnt": "0",
            "ref_exrt": "1.00",
            "strt_dps_tot_amt": "100",
            "strt_dps_csh_amt": "100",
            "strt_dps_sbst_amt": "0",
            "strt_dps_fcur_blc_amt": "0",
            "dps_tot_amt": "100",
            "dps_csh_amt": "100",
            "dps_sbst_amt": "0",
            "dps_fcur_amt": "0",
            "ord_mrgn": "0",
            "rsk_rt": "0",
        },
    )


def _잔고():
    return _기록(
        "overseas_open-interest",
        "/trade/v1/overseas/open-interest",
        {"nxt_key": ""},
        {
            "ac_no": "FAKE-AC-000000",
            "nxt_key": "",
            "Occurs1": [
                {
                    "occurs1_sym": 지어낸종목,
                    "occurs1_trd_tp": "2",
                    "occurs1_fut_opt_tp": "1",
                    "occurs1_opint_qty": "3",
                    "occurs1_cls_psb_qty": "3",
                    "occurs1_avg_pric": "10.5",
                    "occurs1_last_pric": "11",
                    "occurs1_pl_amt": "-25",
                    "occurs1_exp_dt": "20260918",
                    "occurs1_cur_cd": "USD",
                    "occurs1_usd_exrt": "1300",
                    "occurs1_ctr_unt_amt": "5",
                }
            ],
        },
    )


def _주문내역():
    return _기록(
        "overseas_order-history",
        "/trade/v1/overseas/order-history",
        {"inq_div": "0", "trd_div_cd": "0", "nxt_key": ""},
        {
            "ac_no": "FAKE-AC-000000",
            "nxt_key": "",
            "Occurs1": [
                {
                    "occurs1_ord_no": "7",
                    "occurs1_sym": 지어낸종목,
                    "occurs1_ord_dt": "20260909",
                    "occurs1_trd_tp": "1",
                    "occurs1_ord_sts": "6",
                    "occurs1_qt_tp": "1",
                    "occurs1_ord_tp": "2",
                    "occurs1_ord_div": "1",
                    "occurs1_fut_opt_tp": "1",
                    "occurs1_med_div": "R",
                    "occurs1_ord_qty": "2",
                    "occurs1_exec_qty": "2",
                    "occurs1_ord_pric": "10.5",
                    "occurs1_exec_pric": "10.5",
                    "occurs1_stop_pric": "0",
                    "occurs1_cur_cd": "USD",
                    "occurs1_ord_rcv_tm": "20260909152122",
                    "occurs1_exec_tm": "20260909152130",
                }
            ],
        },
    )


def _저장소():
    return FixtureStore([_예수금(), _잔고(), _주문내역()], Path("메모리"))


@pytest.fixture
def client():
    session = create_session(replay=True, fixtures=_저장소())
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()


# ── 시세 ────────────────────────────────────────────────────
#
# **여기는 저장소의 진짜 기록으로 돕니다.** 해외 시세는 반입해 둔 응답이
# 있습니다(현재가·호가·분봉). 계좌 쪽이 만든 저장소를 쓰는 것과 다릅니다.


@pytest.fixture
def 시세client():
    session = create_session(replay=True)
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()


def _분봉기록(키: str, 다음키: str, clock: str):
    """해외 분봉 저장본 한 건. 쪽마다 이어받기 키가 다릅니다."""
    return _기록(
        "overseas_chart-minute",
        "/trade/v1/overseas/chart-minute",
        {
            "exch_cd": "FCME",
            "sym": 지어낸종목,
            "inq_strt_dt": "20260909",
            "inq_ed_dt": "20260909",
            "strt_tm": "000000",
            "ed_tm": "235959",
            "req_qty": "300",
            "dcnt": "1",
            "cidx_yn": "0",
            "nxt_key": 키,
        },
        {
            "sym": 지어낸종목,
            "exch_cd": "FCME",
            "nrec": "0001",
            "nxt_key": 다음키,
            "Occurs1": [
                {
                    "occurs1_glb_biz_dt": "20260909",
                    "occurs1_ref_dt": "20260909",
                    "occurs1_exch_tm": clock,
                    "occurs1_open_pric": "1",
                    "occurs1_high_pric": "1",
                    "occurs1_low_pric": "1",
                    "occurs1_close_pric": "1",
                    "occurs1_cum_trd_qty": "1",
                }
            ],
        },
    )


def test_해외_분봉은_이어받기_키로_쪽을_가른다():
    """**해외 분봉만 키를 봅니다.** 날짜 인자를 안 보는 API 라, 키까지 안 보면
    어느 쪽을 물어도 같은 쪽이 와서 재생에서는 한 쪽만 돌고 맙니다.
    """
    저장소 = FixtureStore([_분봉기록("99999999", "키2", "120000"), _분봉기록("키2", "", "030000")], Path("메모리"))
    session = create_session(replay=True, fixtures=저장소)
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        앱 = TestClient(app)
        # **수집한 날과 다른 날짜로 묻습니다.** 화면은 늘 오늘로 부르므로 기록과
        # 통째로 같은 요청이 될 일이 없습니다 — 그 길(정확일치)을 막아야 이
        # 시험이 「고르는 인자」를 봅니다.
        물음 = {"exch_cd": "FCME", "sym": 지어낸종목, "inq_strt_dt": "20261231", "inq_ed_dt": "20261231"}
        첫쪽 = 앱.post("/api/overseas/chart-minute", json=물음).json()
        둘째쪽 = 앱.post("/api/overseas/chart-minute", json={**물음, "nxt_key": "키2"}).json()
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()

    assert 첫쪽["nextKey"] == "키2", "키를 안 보내면 지금처럼 첫 쪽입니다."
    assert 둘째쪽["nextKey"] == "", "그 키의 기록이 답합니다 — 같은 쪽이 또 오지 않습니다."
    assert 첫쪽["bars"][0]["timestamp"] != 둘째쪽["bars"][0]["timestamp"]


def test_해외_현재가가_여러_종목으로_온다(시세client):
    응답 = 시세client.post(
        "/api/overseas/price",
        json={"syms": [{"exch_cd": "FCME", "sym": "MESU26"}]},
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert len(몸["quotes"]) >= 1
    한줄 = 몸["quotes"][0]
    assert 한줄["code"]
    assert 한줄["market"] == "overseas"
    assert 한줄["last"] is not None
    담긴것 = 응답.text
    assert "occurs1_" not in 담긴것


class 종목별호출부:
    """종목마다 정해 둔 답(또는 실패)을 내는 현재가 호출부."""

    def __init__(self, 답들: dict[str, Any]):
        self.답들 = 답들
        self.보낸것: list[tuple[str, dict]] = []
        self.session = SimpleNamespace(
            config=SimpleNamespace(default_environment="paper"), is_replay=False
        )

    def call(self, api_id, payload, environment=None):
        self.보낸것.append((api_id, dict(payload)))
        답 = self.답들[payload["Iccurs1"][0]["iccurs1_sym"]]
        if isinstance(답, Exception):
            raise 답
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market="overseas",
            http_status=200,
            body=답,
            headers={},
        )


def _현재가줄(sym: str, last: str) -> dict[str, Any]:
    return {"nrec": "1", "Occurs1": [{"occurs1_sym": sym, "occurs1_last_pric": last}]}


def _현재가를_묻는다(호출부, *syms: str):
    app.dependency_overrides[get_client] = lambda: 호출부
    try:
        return TestClient(app).post(
            "/api/overseas/price",
            json={"syms": [{"exch_cd": "FCME", "sym": sym} for sym in syms]},
        )
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_해외_현재가는_종목마다_한_번씩_부른다():
    """서버는 한 번에 한 종목만 받습니다 — 둘을 한 요청에 넣으면 거절됩니다."""
    호출부 = 종목별호출부(
        {"MESZ26": _현재가줄("MESZ26", "6500.25"), "MESU26": _현재가줄("MESU26", "6480")}
    )
    응답 = _현재가를_묻는다(호출부, "MESZ26", "MESU26")

    assert 응답.status_code == 200
    assert [(api_id, 보낸것["Iccurs1"]) for api_id, 보낸것 in 호출부.보낸것] == [
        ("overseas_price", [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESZ26"}]),
        ("overseas_price", [{"iccurs1_exch_cd": "FCME", "iccurs1_sym": "MESU26"}]),
    ]
    몸 = 응답.json()
    assert [(줄["code"], 줄["last"]) for 줄 in 몸["quotes"]] == [
        ("MESZ26", 6500.25),
        ("MESU26", 6480),
    ]
    assert 몸["failed"] == []


def test_해외_현재가_종목_하나면_한_번_부른다():
    호출부 = 종목별호출부({"MESZ26": _현재가줄("MESZ26", "6500.25")})
    응답 = _현재가를_묻는다(호출부, "MESZ26")

    assert 응답.status_code == 200
    assert len(호출부.보낸것) == 1
    assert [줄["code"] for 줄 in 응답.json()["quotes"]] == ["MESZ26"]
    assert 응답.json()["failed"] == []


def test_해외_현재가_한_종목이_실패해도_나머지는_답한다():
    from backend.overseas_futureoption import overseas_routes as 해외

    호출부 = 종목별호출부(
        {
            "MESZ26": _현재가줄("MESZ26", "6500.25"),
            "MESU26": BusinessError("overseas_price", "EGW999", "거절", {}),
            "ESZ26": TransportError("overseas_price", "끊김"),
        }
    )
    응답 = _현재가를_묻는다(호출부, "MESZ26", "MESU26", "ESZ26")

    assert 응답.status_code == 200
    assert len(호출부.보낸것) == 3, "하나가 실패해도 뒤 종목을 계속 묻습니다."
    몸 = 응답.json()
    assert [줄["code"] for 줄 in 몸["quotes"]] == ["MESZ26"]
    assert 몸["failed"] == [
        {"code": "MESU26", "message": 해외._QUOTE_REJECTED},
        {"code": "ESZ26", "message": 해외._QUOTE_NOT_RECEIVED},
    ]


def test_해외_현재가_전부_실패하면_요청이_실패한다():
    from backend.overseas_futureoption import overseas_routes as 해외

    호출부 = 종목별호출부(
        {
            "MESZ26": TransportError("overseas_price", "끊김"),
            "MESU26": BusinessError("overseas_price", "EGW999", "거절", {}),
        }
    )
    응답 = _현재가를_묻는다(호출부, "MESZ26", "MESU26")

    # 마지막 실패의 종류로 답합니다 — 거절이면 502.
    assert 응답.status_code == 502
    assert 응답.json()["detail"] == 해외._QUOTE_REJECTED


def test_해외_현재가_재생_헤더는_종목_전체를_한_번에_알린다(시세client):
    """종목마다 따로 부르지만 헤더는 하나 — 마지막 종목의 것만 남으면 앞 줄과 어긋납니다."""
    있는둘 = [{"exch_cd": "FCME", "sym": "MESU26"}, {"exch_cd": "OCME", "sym": "O_ESU26-C7600.0"}]
    응답 = 시세client.post("/api/overseas/price", json={"syms": 있는둘})
    assert [줄["code"] for 줄 in 응답.json()["quotes"]] == ["MESU26", "O_ESU26-C7600.0"]
    assert 응답.headers[MATCH_HEADER] != "empty"
    assert 응답.headers[SYMBOL_HEADER] == "same"
    # 쓴 기록 둘을 부른 차례로 잇습니다.
    기록들 = 응답.headers[RECORD_HEADER].split("+")
    assert len(기록들) == 2 and 기록들[0] < 기록들[1]

    하나와없는것 = [{"exch_cd": "FCME", "sym": "MESU26"}, {"exch_cd": "FCME", "sym": "ZZZZ9999"}]
    응답 = 시세client.post("/api/overseas/price", json={"syms": 하나와없는것})
    assert [줄["code"] for 줄 in 응답.json()["quotes"]] == ["MESU26"]
    assert 응답.headers[MATCH_HEADER] != "empty", "줄이 있는데 빈 응답이라 하면 안 됩니다."
    assert 응답.headers[RECORD_HEADER] == 기록들[0]

    없는것만 = [{"exch_cd": "FCME", "sym": "ZZZZ9999"}]
    응답 = 시세client.post("/api/overseas/price", json={"syms": 없는것만})
    assert 응답.json()["quotes"] == []
    assert 응답.headers[MATCH_HEADER] == "empty"
    assert RECORD_HEADER not in 응답.headers


def test_해외_현재가는_종목을_하나_이상_받는다(시세client):
    assert 시세client.post("/api/overseas/price", json={"syms": []}).status_code == 422
    assert 시세client.post("/api/overseas/price", json={}).status_code == 422


def test_거래소코드가_없으면_안_부른다(시세client):
    나쁜값들 = (
        {"syms": [{"sym": "MESU26"}]},
        {"syms": [{"exch_cd": "fcme", "sym": "MESU26"}]},
        {"syms": [{"exch_cd": "FCME", "sym": ""}]},
    )
    for 나쁜값 in 나쁜값들:
        assert 시세client.post("/api/overseas/price", json=나쁜값).status_code == 422, 나쁜값


def test_해외_옵션_체인이_한_번에_온다(시세client):
    응답 = 시세client.post("/api/overseas/option-chain", json={"exch_cd": "OCME", "sym": "O_ESU26"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["series"] == "O_ESU26" and 몸["count"] == 338
    줄 = 몸["rows"][0]
    assert 줄["call"]["code"] == "O_ESU26-C12000.0" and 줄["put"]["code"] == "O_ESU26-P12000.0"
    assert 몸["asOf"].endswith("+09:00")
    assert "occurs1_" not in 응답.text


def test_해외_옵션_체인은_시리즈와_거래소가_필요하다(시세client):
    for 나쁜값 in ({}, {"sym": "O_ESU26"}, {"exch_cd": "ocme", "sym": "O_ESU26"}):
        assert 시세client.post("/api/overseas/option-chain", json=나쁜값).status_code == 422, 나쁜값


def test_없는_시리즈의_해외_옵션_체인은_빈_응답이다(시세client):
    응답 = 시세client.post("/api/overseas/option-chain", json={"exch_cd": "OCME", "sym": "O_ZZZZ99"})
    assert 응답.status_code == 200
    assert 응답.json()["rows"] == []
    assert 응답.headers[MATCH_HEADER] == "empty"


def test_해외_호가가_화면_순서로_온다(시세client):
    응답 = 시세client.post(
        "/api/overseas/bid-price", json={"exch_cd": "FCME", "sym": "MESU26"}
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    asks = [단계["price"] for 단계 in 몸["asks"]]
    bids = [단계["price"] for 단계 in 몸["bids"]]
    assert asks == sorted(asks, reverse=True)
    assert bids == sorted(bids, reverse=True)
    assert 몸["code"]


def test_해외_분봉이_오래된_것부터_온다(시세client):
    응답 = 시세client.post(
        "/api/overseas/chart-minute",
        json={
            "exch_cd": "FCME",
            "sym": "MESU26",
            "inq_strt_dt": "20260909",
            "inq_ed_dt": "20260909",
        },
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    시각들 = [하나["timestamp"] for 하나 in 몸["bars"]]
    assert 시각들 == sorted(시각들)
    assert 시각들, "저장해 둔 기록에 봉이 있어야 합니다."
    # 응답의 종목 칸이 비어 오므로 물어본 코드로 채워집니다.
    assert 몸["code"] == "MESU26"


def test_해외_일봉이_그날_0시로_온다(시세client):
    """일봉에는 시각이 없어 그날 0시(한국시간)로 앉습니다 — 국내 일봉과 같은 규칙."""
    from datetime import datetime

    from backend.sessions.hours import KST

    응답 = 시세client.post(
        "/api/overseas/chart-daily",
        json={"exch_cd": "FCME", "sym": "MESU26", "inq_strt_dt": "20260909", "inq_ed_dt": "20260909"},
    )

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["code"] == "MESU26"
    assert len(몸["bars"]) == 1, "저장해 둔 기록에 일봉이 한 줄 있습니다."
    봉 = 몸["bars"][0]
    assert 봉["timestamp"] == int(datetime(2026, 9, 9, tzinfo=KST).timestamp() * 1000)
    assert (봉["open"], 봉["high"], 봉["low"], 봉["close"], 봉["volume"]) == (
        7680.25, 7682.75, 7672.75, 7681.25, 17767
    )
    assert 몸["skipped"] == 0


def test_해외_일봉은_날짜_둘이_필수다(시세client):
    assert 시세client.post(
        "/api/overseas/chart-daily", json={"exch_cd": "FCME", "sym": "MESU26"}
    ).status_code == 422
    나쁜값 = {"exch_cd": "FCME", "sym": "MESU26", "inq_strt_dt": "2026", "inq_ed_dt": "20260909"}
    assert 시세client.post("/api/overseas/chart-daily", json=나쁜값).status_code == 422


def test_기록_없는_종목의_해외_일봉은_빈_응답이다(시세client):
    응답 = 시세client.post(
        "/api/overseas/chart-daily",
        json={"exch_cd": "FCME", "sym": "ZZZZ26", "inq_strt_dt": "20260909", "inq_ed_dt": "20260909"},
    )
    assert 응답.status_code == 200
    assert 응답.json()["bars"] == []
    assert 응답.headers[MATCH_HEADER] == "empty"


def test_해외_분봉은_날짜를_여덟_자리로_받는다(시세client):
    나쁜값 = {"exch_cd": "FCME", "sym": "MESU26", "inq_strt_dt": "2026", "inq_ed_dt": "20260909"}
    assert 시세client.post("/api/overseas/chart-minute", json=나쁜값).status_code == 422


# ── 만기 정보 ─────────────────────────────────────────────
#
# 저장 기록(real)으로 돕니다. 잔존일 기준(`rem_dy`)은 재생이 안 보는 칸이라
# 같은 종목 기록 중 줄이 담긴 것이 옵니다.


def test_해외_만기_정보가_기록으로_온다(시세client):
    응답 = 시세client.post("/api/overseas/product-expiry", json={"sym": "MESU26"})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["code"] == "MESU26"
    assert 몸["remainingDaysLimit"] == 999
    assert len(몸["rows"]) == 1
    줄 = 몸["rows"][0]
    assert (줄["code"], 줄["productCode"], 줄["exchange"]) == ("MESU26", "MES", "CME")
    assert (줄["expiry"], 줄["firstNotice"], 줄["lastSettlement"]) == (
        "2026-09-18",
        "2026-09-18",
        "2026-09-18",
    )
    assert 줄["remainingDays"] == 9
    assert 응답.headers[MATCH_HEADER] != "empty"
    assert "occurs1_" not in 응답.text


def test_해외_만기_정보는_종목코드가_필요하다(시세client):
    나쁜값들 = (
        {},
        {"sym": ""},
        {"sym": "MESU26", "fut_opt_div_cd": "X"},
        {"sym": "MESU26", "rem_dy": "많이"},
    )
    for 나쁜값 in 나쁜값들:
        assert 시세client.post("/api/overseas/product-expiry", json=나쁜값).status_code == 422, 나쁜값


def test_없는_종목의_만기_정보는_빈_응답이다(시세client):
    응답 = 시세client.post("/api/overseas/product-expiry", json={"sym": "ZZZZ26"})
    assert 응답.status_code == 200
    assert 응답.json()["rows"] == []
    assert 응답.headers[MATCH_HEADER] == "empty"


def test_해외_만기_정보는_잔존일_기준을_실어_보낸다():
    호출부 = 적어두는호출부({"nrec": "0000", "nxt_key": ""})
    app.dependency_overrides[get_client] = lambda: 호출부
    try:
        기본 = TestClient(app).post("/api/overseas/product-expiry", json={"sym": "MESU26"})
        준것 = TestClient(app).post(
            "/api/overseas/product-expiry",
            json={"sym": "MESU26", "fut_opt_div_cd": "F", "rem_dy": "30"},
        )
    finally:
        app.dependency_overrides.pop(get_client, None)

    (id1, 보낸것1), (id2, 보낸것2) = 호출부.보낸것
    assert id1 == id2 == "overseas_product-expiry"
    # 비우면 먼 월물까지 오도록 크게, 주면 준 대로 — 응답이 그 값을 돌려줍니다.
    assert 보낸것1 == {"fut_opt_div_cd": "", "nxt_key": "", "rem_dy": "999", "sym": "MESU26"}
    assert 기본.json()["remainingDaysLimit"] == 999
    assert 보낸것2 == {"fut_opt_div_cd": "F", "nxt_key": "", "rem_dy": "30", "sym": "MESU26"}
    assert 준것.json()["remainingDaysLimit"] == 30


def test_해외_품목_실패는_품목_문구로_온다():
    from backend.overseas_futureoption import overseas_routes as 해외

    못받음 = 적어두는호출부({}, 터질것=TransportError("overseas_product-expiry", "끊김"))
    app.dependency_overrides[get_client] = lambda: 못받음
    try:
        응답 = TestClient(app).post("/api/overseas/product-expiry", json={"sym": "MESU26"})
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 해외._PRODUCT_NOT_RECEIVED
    assert "계좌" not in 응답.json()["detail"] and "시세" not in 응답.json()["detail"]

    거절 = 적어두는호출부({}, 터질것=BusinessError("overseas_product-expiry", "EGW999", "거절", {}))
    app.dependency_overrides[get_client] = lambda: 거절
    try:
        응답 = TestClient(app).post("/api/overseas/product-expiry", json={"sym": "MESU26"})
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 응답.status_code == 502
    assert 응답.json()["detail"] == 해외._PRODUCT_REJECTED


# ── 실패 문구는 시세와 계좌를 가른다 ────────────────────────────

_시세요청 = (
    ("/api/overseas/price", {"syms": [{"exch_cd": "FCME", "sym": "MESU26"}]}),
    ("/api/overseas/bid-price", {"exch_cd": "FCME", "sym": "MESU26"}),
    (
        "/api/overseas/chart-minute",
        {"exch_cd": "FCME", "sym": "MESU26", "inq_strt_dt": "20260909", "inq_ed_dt": "20260909"},
    ),
    (
        "/api/overseas/chart-daily",
        {"exch_cd": "FCME", "sym": "MESU26", "inq_strt_dt": "20260909", "inq_ed_dt": "20260909"},
    ),
)


@pytest.mark.parametrize("주소, 본문", _시세요청)
def test_해외_시세_실패는_시세_문구로_온다(주소, 본문):
    """시세를 못 받았는데 「계좌 정보」라 적히면 사용자가 설정 화면을 봅니다 — 국내와 같은 문구."""
    from backend.domestic_futureoption import domestic_routes as 국내

    못받음 = 적어두는호출부({}, 터질것=TransportError("overseas_price", "끊김"))
    app.dependency_overrides[get_client] = lambda: 못받음
    try:
        응답 = TestClient(app).post(주소, json=본문)
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 국내._NOT_RECEIVED
    assert "계좌" not in 응답.json()["detail"]

    거절 = 적어두는호출부({}, 터질것=BusinessError("overseas_price", "EGW999", "거절", {}))
    app.dependency_overrides[get_client] = lambda: 거절
    try:
        응답 = TestClient(app).post(주소, json=본문)
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 응답.status_code == 502
    assert 응답.json()["detail"] == 국내._REJECTED


def test_해외_계좌_실패_문구는_그대로다():
    from backend.overseas_futureoption import overseas_routes as 해외

    못받음 = 적어두는호출부({}, 터질것=TransportError("overseas_deposit", "끊김"))
    app.dependency_overrides[get_client] = lambda: 못받음
    try:
        응답 = TestClient(app).post("/api/overseas/deposit", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 해외._NOT_RECEIVED
    assert "계좌 정보" in 응답.json()["detail"]


def test_해외_시세_주소가_붙어_있다():
    주소 = set()
    for route in app.routes:
        붙은것 = getattr(route, "original_router", None)
        for 하나 in getattr(붙은것, "routes", []) if 붙은것 else [route]:
            주소.add(getattr(하나, "path", ""))
    for 자리 in (
        "/api/overseas/price",
        "/api/overseas/bid-price",
        "/api/overseas/chart-minute",
        "/api/overseas/chart-daily",
    ):
        assert 자리 in 주소


def test_해외_예수금이_화면_모양으로_온다(client):
    응답 = client.post("/api/overseas/deposit", json={})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert len(몸["groups"]) == 2
    assert 몸["items"], "총액 하나짜리 항목이 있어야 합니다."
    assert 몸["currency"] == "KRW"
    assert 몸["conversion"] == "converted"
    담긴것 = 응답.text
    assert "dps_tot_amt" not in 담긴것
    assert "ac_no" not in 담긴것
    assert "FAKE-AC-000000" not in 담긴것


def test_환산구분은_1_이나_2_만_받는다(client):
    assert client.post("/api/overseas/deposit", json={"cvs_div": "3"}).status_code == 422
    assert client.post("/api/overseas/deposit", json={"cvs_div": "1", "cur_cd": "USD"}).status_code == 200


def test_영업일자는_비우거나_여덟_자리(client):
    assert client.post("/api/overseas/deposit", json={"biz_dt": ""}).status_code == 200
    assert client.post("/api/overseas/deposit", json={"biz_dt": "2026"}).status_code == 422


def test_해외_라우트가_앱에_붙어_있다():
    주소 = set()
    for route in app.routes:
        붙은것 = getattr(route, "original_router", None)
        for 하나 in getattr(붙은것, "routes", []) if 붙은것 else [route]:
            주소.add(getattr(하나, "path", ""))
    assert "/api/overseas/deposit" in 주소
    assert "/api/overseas/open-interest" in 주소
    assert "/api/overseas/order-history" in 주소


def test_통화코드는_세_글자_대문자만_받는다(client):
    assert client.post("/api/overseas/deposit", json={"cur_cd": "USD"}).status_code == 200
    assert client.post("/api/overseas/deposit", json={"cur_cd": "usd"}).status_code == 422
    assert client.post("/api/overseas/deposit", json={"cur_cd": "US"}).status_code == 422
    assert client.post("/api/overseas/deposit", json={"cur_cd": "DOLLAR"}).status_code == 422


def test_해외_잔고가_화면_모양으로_온다(client):
    응답 = client.post("/api/overseas/open-interest", json={})

    assert 응답.status_code == 200
    몸 = 응답.json()
    한줄 = 몸["positions"][0]
    assert 한줄["code"] == 지어낸종목
    assert 한줄["market"] == "overseas"
    assert 한줄["side"] == "short"
    assert 한줄["quantity"] == 3
    assert 한줄["expiry"] == "2026-09-18"
    assert 한줄["currency"] == "USD"
    assert 몸["nextKey"] == ""
    담긴것 = 응답.text
    assert "occurs1_sym" not in 담긴것
    assert "ac_no" not in 담긴것
    assert "FAKE-AC-000000" not in 담긴것


def test_해외_주문내역이_화면_모양으로_온다(client):
    응답 = client.post("/api/overseas/order-history", json={})

    assert 응답.status_code == 200
    몸 = 응답.json()
    한줄 = 몸["orders"][0]
    assert 한줄["id"] == "7"
    assert 한줄["code"] == 지어낸종목
    assert 한줄["side"] == "buy"
    assert 한줄["status"] == "filled"
    assert 한줄["orderType"] == "지정가"
    assert 한줄["validity"] == "GTC"
    # 열네 자리 한 칸이 날짜와 시각으로 갈립니다.
    assert (한줄["receivedDate"], 한줄["receivedTime"]) == ("2026-09-09", "15:21:22")
    assert 한줄["time"] == "15:21:30"
    담긴것 = 응답.text
    assert "occurs1_ord_no" not in 담긴것
    assert "FAKE-AC-000000" not in 담긴것


def test_해외_주문내역_조회구분은_0에서_4까지(client):
    """국내는 0~3 이고 해외는 미체결이 둘로 갈려 4 까지입니다."""
    for 값 in ("0", "1", "2", "3", "4"):
        assert client.post("/api/overseas/order-history", json={"inq_div": 값}).status_code == 200
    assert client.post("/api/overseas/order-history", json={"inq_div": "5"}).status_code == 422


def test_매매구분은_0에서_2까지(client):
    for 값 in ("0", "1", "2"):
        주문 = client.post("/api/overseas/order-history", json={"trd_div_cd": 값})
        assert 주문.status_code == 200, 값
    assert client.post("/api/overseas/order-history", json={"trd_div_cd": "3"}).status_code == 422


def test_저장본으로_답하면_헤더로_알린다(client):
    """어느 기록으로 답했는지가 헤더에 실립니다 — 국내 라우트와 같은 규칙입니다."""
    for 주소 in ("/api/overseas/open-interest", "/api/overseas/order-history"):
        응답 = client.post(주소, json={})
        assert 응답.headers[MATCH_HEADER], 주소
        assert REPLAY_HEADER not in 응답.headers, "재생 표시는 라우트가 다시 내지 않습니다."


def test_품목코드는_열_글자까지_받는다(client):
    """명세상 선택입니다. 빈 값이면 요청에 안 실립니다."""
    assert client.post("/api/overseas/order-history", json={"prd_cd": ""}).status_code == 200
    열글자 = client.post("/api/overseas/order-history", json={"prd_cd": "ABCDEF7890"})
    assert 열글자.status_code == 200
    # 명세 길이는 10 입니다.
    assert client.post(
        "/api/overseas/order-history", json={"prd_cd": "ABCDEF78901"}
    ).status_code == 422


# ── 주문가능수량 ────────────────────────────────────────────
#
# 저장본이 없고 **무엇을 보내는지까지** 봐야 해서 받은 요청을 적어 두는
# 호출부로 세웁니다.


class 적어두는호출부:
    """부른 값을 적어 두고 정해 둔 응답을 내는 호출부.

    주문 라우트가 어느 환경인지 보므로 그 자리도 흉내 냅니다.
    """

    def __init__(
        self, 응답, *, environment="paper", replay=False, 터질것=None, 보내기전에터짐=False
    ):
        self.응답 = 응답
        self.보낸것: list[tuple[str, dict]] = []
        self.터질것 = 터질것
        # 실전 차단은 **보내기 전에** 납니다. 그 자리를 흉내 낼 때는 적어 두지도
        # 않아야 「보낸 것 없음」이 뜻을 가집니다.
        self.보내기전에터짐 = 보내기전에터짐
        # 시장 참고 자료는 인증 정보가 있는 환경을 골라 부르므로 그 자리도 흉내 냅니다.
        # 활성 환경 하나에만 두 시장의 인증 정보가 있습니다.
        self.session = SimpleNamespace(
            config=SimpleNamespace(
                default_environment=environment,
                environments={
                    environment: SimpleNamespace(configured_markets=("domestic", "overseas"))
                },
            ),
            is_replay=replay,
        )

    def call(self, api_id, payload, environment=None):
        if self.터질것 is not None and self.보내기전에터짐:
            raise self.터질것
        self.보낸것.append((api_id, dict(payload)))
        if self.터질것 is not None:
            raise self.터질것
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market="overseas",
            http_status=200,
            body=self.응답,
            headers={},
        )


@pytest.fixture
def 적어두는():
    호출부 = 적어두는호출부(
        {
            "prd_cd": "ZZZ",
            "cur_cd": "USD",
            "ord_psb_amt": "1234.5",
            "new_buy_ord_psb_qty": "3",
            "buy_cls_psb_qty": "2",
            "buy_ord_psb_qty": "5",
            "new_sel_ord_psb_qty": "7",
            "sel_cls_psb_qty": "1",
            "sel_ord_psb_qty": "8",
        }
    )
    app.dependency_overrides[get_client] = lambda: 호출부
    try:
        yield TestClient(app), 호출부
    finally:
        app.dependency_overrides.pop(get_client, None)


def _물음(**덮어쓰기):
    물음 = {"sym": 지어낸종목, "side": "buy", "glb_ord_tp_cd": "2", "ord_pric": "7677.25"}
    물음.update(덮어쓰기)
    return 물음


def test_해외_주문가능수량이_화면_모양으로_온다(적어두는):
    앱, _ = 적어두는
    응답 = 앱.post("/api/overseas/orderable-quantity", json=_물음())

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert (몸["quantity"], 몸["newQuantity"], 몸["closeQuantity"]) == (5, 3, 2)
    assert 몸["currency"] == "USD"
    assert 몸["market"] == "overseas"
    담긴것 = 응답.text
    assert "buy_ord_psb_qty" not in 담긴것
    assert "sel_ord_psb_qty" not in 담긴것


def test_매도를_물으면_매도_쪽_값이_온다(적어두는):
    앱, 호출부 = 적어두는
    몸 = 앱.post("/api/overseas/orderable-quantity", json=_물음(side="sell")).json()

    assert (몸["quantity"], 몸["newQuantity"], 몸["closeQuantity"]) == (8, 7, 1)
    # 방향은 화면 쪽 값입니다 — NH선물 요청에는 방향 칸이 없습니다.
    assert "trd_div" not in 호출부.보낸것[-1][1]
    assert "side" not in 호출부.보낸것[-1][1]


def test_STOP_주문유형은_스탑가격이_있어야_한다(적어두는):
    앱, 호출부 = 적어두는
    for 유형 in ("3", "4"):
        막힘 = 앱.post("/api/overseas/orderable-quantity", json=_물음(glb_ord_tp_cd=유형))
        assert 막힘.status_code == 422, 유형
        됨 = 앱.post(
            "/api/overseas/orderable-quantity",
            json=_물음(glb_ord_tp_cd=유형, stop_pric="7600"),
        )
        assert 됨.status_code == 200, 유형
    assert 호출부.보낸것[-1][1]["stop_pric"] == "7600"


def test_STOP_이_아니면_스탑가격은_빈_값으로_나간다(적어두는):
    """칸을 빼지 않습니다 — 반입해 둔 기록이 빈 값으로 부르고 있습니다."""
    앱, 호출부 = 적어두는
    앱.post("/api/overseas/orderable-quantity", json=_물음(glb_ord_tp_cd="1"))

    보낸것 = 호출부.보낸것[-1][1]
    assert 보낸것["stop_pric"] == ""
    assert 보낸것["glb_ord_tp_cd"] == "1"
    assert 보낸것["ord_pric"] == "7677.25", "시장가에도 가격을 실어 보냅니다."


def test_해외_가격과_방향과_유형을_검사한다(적어두는):
    앱, 호출부 = 적어두는
    나쁜값들 = (
        _물음(ord_pric=""),
        _물음(ord_pric="시장가"),
        _물음(side="long"),
        _물음(glb_ord_tp_cd="5"),
        _물음(sym=""),
    )
    for 나쁜값 in 나쁜값들:
        막힘 = 앱.post("/api/overseas/orderable-quantity", json=나쁜값)
        assert 막힘.status_code == 422, 나쁜값
    assert 호출부.보낸것 == [], "값이 틀리면 NH선물을 부르지 않습니다."


# ── 주문·정정·취소 ──────────────────────────────────────────
#
# **해외는 셋이 API 하나입니다.** 저장본이 없어 받은 요청을 적어 두는 호출부로
# 세웁니다. 아무 주문도 나가지 않습니다.

주문응답 = {
    "biz_dt": "20260909",
    "mo_ord_no": "12",
    "org_ord_no": "",
    "ord_no": "7",
    "sym": 지어낸종목,
    "ord_pric": "7677.25",
    "ord_qty": "2",
    "qt_div_cd": "1",
    "trd_div_cd": "1",
    # **정상 답에도 코드가 실려 옵니다.** 모의 계좌로 신규·정정·취소를 내 보니
    # 셋 다 이 값이었습니다(2026-09-23). 「코드가 있으면 거절」로 읽으면 들어간
    # 주문을 거절이라고 답하게 됩니다.
    "err_cd": "00000",
    "err_msg": "주문이 정상처리 되었습니다.",
}


def _주문(**덮어쓰기):
    물음 = {
        # 화면이 믿는 환경. 흉내 낸 호출부의 기본값(모의)과 같게 둡니다.
        "environment": "paper",
        "sym": 지어낸종목,
        "side": "buy",
        "qt_div_cd": "1",
        "glb_ord_tp_cd": "1",
        "ord_qty": 2,
    }
    물음.update(덮어쓰기)
    return 물음


def _세운다(응답=None, **설정):
    호출부 = 적어두는호출부(응답 or 주문응답, **설정)
    app.dependency_overrides[get_client] = lambda: 호출부
    return TestClient(app), 호출부


@pytest.fixture
def 주문():
    앱, 호출부 = _세운다()
    try:
        yield 앱, 호출부
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_해외_신규주문이_화면_모양으로_온다(주문):
    앱, 호출부 = 주문
    응답 = 앱.post("/api/overseas/order", json=_주문())

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is True
    assert (몸["id"], 몸["market"], 몸["code"], 몸["side"], 몸["quantity"]) == (
        "7",
        "overseas",
        지어낸종목,
        "buy",
        2,
    )
    # 해외에만 있는 칸입니다.
    assert 몸["businessDate"] == "2026-09-09"
    assert 몸["parentOrderNo"] == "12"
    assert 몸["price"] == 7677.25
    # 값이 빈 칸은 안 담습니다.
    assert "originalOrderNo" not in 몸


def test_해외_접수_답이_미체결_표_한_줄이다(주문):
    """화면이 목록 위에 그대로 얹는 줄입니다 — **국내 접수 답과 같은 칸**이라야
    한 표에 두 시장의 줄이 섭니다.
    """
    앱, _ = 주문

    몸 = 앱.post("/api/overseas/order", json=_주문()).json()

    assert (몸["status"], 몸["statusCode"]) == ("accepted", "1")
    assert (몸["remaining"], 몸["filled"]) == (2, 0)
    assert 몸["orderKind"] == "new"
    assert (몸["orderTypeCode"], 몸["orderType"]) == ("1", "시장가")
    assert 몸["date"] and 몸["time"] and 몸["acceptedAt"], "우리 시계로 적는 값입니다."
    assert (몸["sourceCode"], 몸["source"]) == ("R", "REST API")
    assert 몸["editable"] is True, "우리가 낸 주문이라 화면에서 고칠 수 있습니다."


def test_해외_취소_접수는_잔량이_없다(주문):
    """취소가 **접수된** 것이지 원주문이 사라진 것을 본 것은 아닙니다."""
    앱, _ = 주문

    몸 = 앱.post("/api/overseas/order", json=_주문(qt_div_cd="3", org_ord_no="7")).json()

    assert 몸["orderKind"] == "cancel"
    assert (몸["status"], 몸["remaining"]) == ("cancelled", 0)
    assert "statusCode" not in 몸, "취소에는 짝이 되는 상태코드가 없습니다."
    assert 몸["originalOrderNo"] == "0000000007", "보낸 모양 그대로입니다."
    assert 몸["editable"] is False, "잔량이 없으면 고칠 것도 없습니다."


def test_해외_정정_접수는_원주문을_가리킨다(주문):
    앱, _ = 주문

    몸 = 앱.post("/api/overseas/order", json=_주문(qt_div_cd="2", org_ord_no="7")).json()

    assert 몸["orderKind"] == "modify"
    assert 몸["originalOrderNo"] == "0000000007"
    assert 몸["status"] == "accepted" and 몸["remaining"] == 2


def test_해외_접수_답에_주문번호가_없으면_안_받는다():
    """번호 없는 줄은 뒤이어 오는 알림·조회가 덮을 수가 없어 화면에 영영 남습니다."""
    앱, 호출부 = _세운다({**주문응답, "ord_no": ""})
    try:
        답 = 앱.post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 답.status_code == 504
    from backend import orders

    assert 답.json()["detail"] == orders.NO_ORDER_NUMBER
    assert len(호출부.보낸것) == 1, "다시 보내지 않습니다."


def test_해외_신규는_원주문번호_자리에_0_을_보낸다(주문):
    앱, 호출부 = 주문
    앱.post("/api/overseas/order", json=_주문())

    api_id, 보낸것 = 호출부.보낸것[-1]
    assert api_id == "overseas_order"
    assert 보낸것["org_ord_no"] == "0"
    assert 보낸것["qt_div_cd"] == "1"
    assert 보낸것["trd_div_cd"] == "1"
    assert 보낸것["ord_pric"] == "0", "시장가는 명세대로 0 을 싣습니다."
    assert 보낸것["stop_pric"] == ""


def test_해외_정정과_취소는_원주문번호가_필요하다(주문):
    앱, 호출부 = 주문
    for 구분 in ("2", "3"):
        막힘 = 앱.post("/api/overseas/order", json=_주문(qt_div_cd=구분))
        assert 막힘.status_code == 422, 구분
    assert 호출부.보낸것 == []

    앱.post("/api/overseas/order", json=_주문(qt_div_cd="3", org_ord_no="7"))
    assert 호출부.보낸것[-1][1]["org_ord_no"] == "0000000007"


def test_해외_지정가는_가격이_STOP_은_스탑가격이_필요하다(주문):
    앱, 호출부 = 주문
    assert 앱.post("/api/overseas/order", json=_주문(glb_ord_tp_cd="2")).status_code == 422
    assert (
        앱.post(
            "/api/overseas/order", json=_주문(glb_ord_tp_cd="4", ord_pric="7677.25")
        ).status_code
        == 422
    )
    assert 호출부.보낸것 == []

    됨 = 앱.post(
        "/api/overseas/order",
        json=_주문(glb_ord_tp_cd="4", ord_pric="7677.25", stop_pric="7600"),
    )
    assert 됨.status_code == 200
    보낸것 = 호출부.보낸것[-1][1]
    assert (보낸것["ord_pric"], 보낸것["stop_pric"]) == ("7677.25", "7600")


def test_해외_정상_코드는_접수다(주문):
    """**실물이 이렇습니다** — 접수 답이 `00000` 과 「정상처리」 문구를 함께 냅니다.

    모의 계좌에서 신규·정정·취소 셋 다 이 모양이었는데, 그때 우리는 「코드가
    있으면 거절」로 읽어 **들어간 주문을 거절이라고 답했습니다.**
    """
    앱, _ = 주문

    몸 = 앱.post("/api/overseas/order", json=_주문()).json()

    assert 몸["accepted"] is True
    assert 몸["id"] == "7" and 몸["status"] == "accepted"


def test_해외_0_뿐인_코드는_자리_수를_안_센다():
    """같은 뜻을 다른 길이로 보내는 날 같은 사고가 되풀이되지 않게."""
    앱, _ = _세운다({**주문응답, "err_cd": "0", "err_msg": "정상"})
    try:
        몸 = 앱.post("/api/overseas/order", json=_주문()).json()
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 몸["accepted"] is True


def test_해외_0_이_아닌_코드는_거절이다():
    앱, _ = _세운다({**주문응답, "err_cd": "40", "err_msg": "주문가능금액이 부족합니다."})
    try:
        몸 = 앱.post("/api/overseas/order", json=_주문()).json()
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 몸["accepted"] is False
    assert 몸["code"] == "40"
    assert "부족" in 몸["message"]


def test_해외_거절은_에러코드로_온다():
    """국내는 `msg_cd` 인데 해외는 `err_cd` 라 공통 판정이 못 잡습니다."""
    앱, 호출부 = _세운다({**주문응답, "err_cd": "40015", "err_msg": "주문가능수량 초과"})
    try:
        응답 = 앱.post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is False
    assert 몸["code"] == "40015"
    assert 몸["message"] == "주문가능수량 초과"


def test_해외도_실전이면_실전으로_나간다():
    앱, 호출부 = _세운다(environment="real")
    try:
        응답 = 앱.post("/api/overseas/order", json=_주문(environment="real"))
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is True
    assert 몸["environment"] == "real"
    assert len(호출부.보낸것) == 1


def test_해외도_환경을_못_읽으면_안_낸다():
    앱, 호출부 = _세운다(environment=None)
    try:
        막힘 = 앱.post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 막힘.status_code == 500
    assert 호출부.보낸것 == []


def test_해외도_재생에_기록이_없으면_거부다():
    앱, _ = _세운다(replay=True, 터질것=TransportError("overseas_order", "기록 없음"))
    try:
        응답 = 앱.post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 409


def test_두_시장_주문_결과가_같은_낱말을_쓴다():
    """화면은 두 시장의 주문 결과를 같은 자리에 같은 말로 적습니다."""
    from backend import orders

    앱, _ = _세운다()
    try:
        해외 = 앱.post("/api/overseas/order", json=_주문()).json()
    finally:
        app.dependency_overrides.pop(get_client, None)
    국내 = orders.accepted(
        order_id="5959762237",
        market="domestic",
        environment="paper",
        code="A7569000",
        side="buy",
        quantity=1,
    )

    for 칸 in ("accepted", "id", "market", "environment", "code", "side", "quantity"):
        assert 칸 in 국내, f"국내에 {칸} 이 없습니다"
        assert 칸 in 해외, f"해외에 {칸} 이 없습니다"


def test_해외_거절은_어느_칸으로_와도_같은_모양이다():
    """`err_cd` 로 오는 것을 봤지만 `msg_cd` 로 오는 날도 화면은 같아야 합니다."""
    앱, _ = _세운다(
        터질것=BusinessError("overseas_order", "40015", "주문가능수량을 초과했습니다.", {})
    )
    try:
        응답 = 앱.post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["accepted"] is False
    assert (몸["code"], 몸["message"]) == ("40015", "주문가능수량을 초과했습니다.")


# ── 주문오류·누적손익 ───────────────────────────────────────
#
# **저장본에 줄이 없습니다**(공개 0건, 로컬 전용도 0줄). 무엇을 보내는지까지
# 봐야 해서 받은 요청을 적어 두는 호출부로 세웁니다.


def test_해외_주문오류_라우트가_오늘로_부른다(monkeypatch):
    # 한국시간 16일 새벽 — 세계시로는 아직 15일입니다. 조회일자는 한국 날짜여야 합니다.
    _한국시간_고정(monkeypatch, "20260916 00:30")
    오늘 = "20260916"
    앱, 호출부 = _세운다({"nrec": "0000", "nxt_key": ""})
    try:
        응답 = 앱.post("/api/overseas/order-error", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    assert 응답.json()["errors"] == []
    api_id, 보낸것 = 호출부.보낸것[-1]
    assert api_id == "overseas_order-error"
    assert 보낸것["inq_dt"] == 오늘


def test_해외_주문오류는_조회일자를_여덟_자리로_받는다():
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        assert 앱.post("/api/overseas/order-error", json={"inq_dt": "2026"}).status_code == 422
        assert 앱.post("/api/overseas/order-error", json={"inq_dt": "20260910"}).status_code == 200
    finally:
        app.dependency_overrides.pop(get_client, None)


def _한국시간_고정(monkeypatch, 언제: str):
    """라우트가 보는 「지금(한국시간)」을 고정합니다."""
    from datetime import datetime

    from backend.sessions.hours import KST

    고정 = datetime.strptime(언제, "%Y%m%d %H:%M").replace(tzinfo=KST)
    monkeypatch.setattr(overseas_routes, "now_kst", lambda: 고정)


def test_누적손익이_기간과_통화를_실어_보낸다(monkeypatch):
    # 한국시간 16일 새벽 — 세계시로는 아직 15일입니다. 끝날은 한국 날짜여야 합니다.
    _한국시간_고정(monkeypatch, "20260916 00:30")
    앱, 호출부 = _세운다({"nrec": "0000", "nxt_key": ""})
    try:
        응답 = 앱.post("/api/overseas/cumulative-pl", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert 몸["rows"] == []
    assert 몸["total"] is None
    보낸것 = 호출부.보낸것[-1][1]
    # 기간을 비우면 끝날은 오늘(한국시간), 시작일은 30일 전입니다 — 서버가 기간
    # 없는 요청을 거절합니다.
    assert 보낸것["inq_ed_dt"] == "20260916"
    assert 보낸것["inq_strt_dt"] == "20260817"
    assert 보낸것["cvs_cur_cd"] == "KRW"
    # 비운 값은 안 보냅니다.
    assert "cur_cd" not in 보낸것
    assert "prd_cd" not in 보낸것
    # 실제로 쓴 기간을 화면에 돌려줍니다.
    assert 몸["period"] == {"from": "2026-08-17", "to": "2026-09-16"}


def test_끝날만_주면_시작일은_그_30일_전이다(monkeypatch):
    _한국시간_고정(monkeypatch, "20260916 09:00")
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        응답 = 앱.post("/api/overseas/cumulative-pl", json={"inq_ed_dt": "20260301"})
    finally:
        app.dependency_overrides.pop(get_client, None)

    보낸것 = 호출부.보낸것[-1][1]
    assert (보낸것["inq_strt_dt"], 보낸것["inq_ed_dt"]) == ("20260130", "20260301")
    assert 응답.json()["period"] == {"from": "2026-01-30", "to": "2026-03-01"}


def test_누적손익_기간은_있는_날짜여야_한다():
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        for 칸 in ("inq_strt_dt", "inq_ed_dt"):
            assert 앱.post(
                "/api/overseas/cumulative-pl", json={칸: "20261345"}
            ).status_code == 422, 칸
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 호출부.보낸것 == []


def test_시작일이_끝날보다_뒤면_보내지_않는다(monkeypatch):
    _한국시간_고정(monkeypatch, "20260916 09:00")
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        거꾸로 = 앱.post(
            "/api/overseas/cumulative-pl",
            json={"inq_strt_dt": "20260910", "inq_ed_dt": "20260901"},
        )
        # 시작일만 줘도 끝날(오늘)과 견줍니다.
        미래 = 앱.post("/api/overseas/cumulative-pl", json={"inq_strt_dt": "20260917"})
        같은날 = 앱.post(
            "/api/overseas/cumulative-pl",
            json={"inq_strt_dt": "20260901", "inq_ed_dt": "20260901"},
        )
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert (거꾸로.status_code, 미래.status_code, 같은날.status_code) == (422, 422, 200)
    assert "시작일이 끝날보다 뒤" in 거꾸로.text
    assert len(호출부.보낸것) == 1


def test_환산통화는_원화나_달러만_받는다():
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        assert 앱.post(
            "/api/overseas/cumulative-pl", json={"cvs_cur_cd": "USD"}
        ).status_code == 200
        assert 앱.post(
            "/api/overseas/cumulative-pl", json={"cvs_cur_cd": "JPY"}
        ).status_code == 422
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_거르는_통화와_품목은_준_대로_보낸다():
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        응답 = 앱.post(
            "/api/overseas/cumulative-pl",
            json={
                "cur_cd": "USD",
                "prd_cd": "ZZZ",
                "inq_strt_dt": "20260901",
                "inq_ed_dt": "20260910",
            },
        )
    finally:
        app.dependency_overrides.pop(get_client, None)

    보낸것 = 호출부.보낸것[-1][1]
    assert (보낸것["cur_cd"], 보낸것["prd_cd"]) == ("USD", "ZZZ")
    # 준 기간은 그대로 보내고 그대로 돌려줍니다.
    assert (보낸것["inq_strt_dt"], 보낸것["inq_ed_dt"]) == ("20260901", "20260910")
    assert 응답.json()["period"] == {"from": "2026-09-01", "to": "2026-09-10"}


def test_주문오류와_누적손익_주소가_붙어_있다():
    주소 = set()
    for route in app.routes:
        붙은것 = getattr(route, "original_router", None)
        for 하나 in getattr(붙은것, "routes", []) if 붙은것 else [route]:
            주소.add(getattr(하나, "path", ""))
    assert "/api/overseas/order-error" in 주소
    assert "/api/overseas/cumulative-pl" in 주소


def test_해외도_게이트웨이_거절이면_확인을_청한다():
    from backend.nh_api.errors import GatewayError
    from backend import orders as 주문계약

    앱, 호출부 = _세운다(
        터질것=GatewayError("overseas_order", "EGW033", "백엔드 연결 실패", {}, "retry")
    )
    try:
        응답 = 앱.post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 주문계약.NOT_RECEIVED
    assert len(호출부.보낸것) == 1


def test_해외도_본문에_담긴_게이트웨이_오류면_확인을_청한다():
    """200 으로 오는 자리입니다. 그 요청은 이미 나간 뒤입니다."""
    from backend import orders as 주문계약

    # 주문은 요청이 통째로 같은 기록으로만 재생됩니다 — 라우트가 실어 보내는 그 모양.
    기록 = _기록(
        "overseas_order",
        "/trade/v1/overseas/order",
        {
            "qt_div_cd": "1",
            "sym": 지어낸종목,
            "trd_div_cd": "1",
            "glb_ord_tp_cd": "1",
            "ord_qty": "2",
            "ord_pric": "0",
            "stop_pric": "",
            "org_ord_no": "0",
        },
        {"errorCode": "EGW000", "errorMessage": "오류가 발생하였습니다."},
    )
    session = create_session(replay=True, fixtures=FixtureStore([기록], Path("메모리")))
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        응답 = TestClient(app).post("/api/overseas/order", json=_주문())
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()

    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 주문계약.NOT_RECEIVED


# -- 잔존일·품목코드 ---------------------------------------------------------


@pytest.fixture
def 빈_만기(monkeypatch):
    """받아 둔 만기일은 앱이 켜진 동안 남는 값이라, 시험마다 비우고 시작합니다."""
    from backend.overseas_futureoption import overseas_products

    monkeypatch.setattr(overseas_products, "_EXPIRIES", {})


def test_해외_현재가의_잔존일은_받아_둔_만기일로_채운다(시세client, 빈_만기, monkeypatch):
    _한국시간_고정(monkeypatch, "20260909 10:00")
    물음 = {"syms": [{"exch_cd": "FCME", "sym": "MESU26"}]}

    전 = 시세client.post("/api/overseas/price", json=물음).json()["quotes"][0]
    assert 전["daysLeft"] is None, "만기 조회 전에는 모릅니다 — NH선물을 더 부르지 않습니다."

    만기 = 시세client.post("/api/overseas/product-expiry", json={"sym": "MESU26"}).json()
    후 = 시세client.post("/api/overseas/price", json=물음).json()["quotes"][0]

    assert 후["daysLeft"] == 만기["rows"][0]["remainingDays"] == 9


def test_해외_주문가능수량의_품목은_마스터에서(적어두는, monkeypatch):
    from backend.master import master_service

    앱, _ = 적어두는
    monkeypatch.setattr(
        master_service.service, "product_of", lambda market, code: {"product_code": "MES"}
    )
    assert 앱.post("/api/overseas/orderable-quantity", json=_물음()).json()["productCode"] == "MES"

    monkeypatch.setattr(master_service.service, "product_of", lambda market, code: None)
    assert 앱.post("/api/overseas/orderable-quantity", json=_물음()).json()["productCode"] is None


# -- 예수금 통화 조합 ----------------------------------------------------------


def test_통화별로_보면서_통화를_안_주면_보내지_않는다():
    """기본값(원화)으로 조용히 불리면 고르지 않은 통화의 값이 옵니다."""
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        빠짐 = 앱.post("/api/overseas/deposit", json={"cvs_div": "1"})
        원화 = 앱.post("/api/overseas/deposit", json={"cvs_div": "1", "cur_cd": "KRW"})
        빈글자 = 앱.post("/api/overseas/deposit", json={"cvs_div": "1", "cur_cd": ""})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert 빠짐.status_code == 422
    assert "통화별로 보려면 통화 코드(cur_cd)를 함께 보내 주세요" in 빠짐.text
    assert 원화.status_code == 200, "원화를 적어 보내면 원화 예수금만 보는 뜻입니다."
    # 빈 글자는 통화 코드 모양 검사에서 먼저 걸립니다.
    assert 빈글자.status_code == 422
    assert 빈글자.json()["detail"][0]["loc"] == ["body", "cur_cd"]
    assert len(호출부.보낸것) == 1


@pytest.mark.parametrize(
    "물음, 기대",
    [
        ({}, ("KRW", "2", "converted")),
        ({"cur_cd": "USD", "cvs_div": "1"}, ("USD", "1", "byCurrency")),
    ],
)
def test_예수금_답에_부른_통화와_환산이_실린다(물음, 기대):
    from backend.overseas_futureoption.overseas_account import CONVERSION

    앱, 호출부 = _세운다({"dps_aset_amt": "7"})
    try:
        몸 = 앱.post("/api/overseas/deposit", json=물음).json()
    finally:
        app.dependency_overrides.pop(get_client, None)

    통화, 코드, _ = 기대
    assert (몸["currency"], 몸["conversionCode"], 몸["conversion"]) == (통화, 코드, CONVERSION[코드])
    보낸것 = 호출부.보낸것[-1][1]
    assert (보낸것["cur_cd"], 보낸것["cvs_div"]) == (통화, 코드)


# -- 누적손익: 환산통화·쪽 모으기 ------------------------------------------------


class 쪽을주는호출부(적어두는호출부):
    """다음 키마다 정해 둔 쪽을 냅니다. `터질쪽` 번째(1부터) 부름에서 터집니다."""

    def __init__(self, 쪽들, *, 터질쪽=None, 터질것=None):
        super().__init__({})
        self.쪽들 = 쪽들
        self.터질쪽 = 터질쪽
        self.터질것_쪽 = 터질것

    def call(self, api_id, payload, environment=None):
        self.보낸것.append((api_id, dict(payload)))
        if self.터질쪽 is not None and len(self.보낸것) == self.터질쪽:
            raise self.터질것_쪽
        몸 = self.쪽들[str(payload.get("nxt_key") or "")]
        return ApiResult(
            api_id=api_id, environment="paper", market="overseas", http_status=200, body=몸, headers={}
        )


def _손익줄(품목, 순손익="1"):
    return {"occurs1_prd_cd": 품목, "occurs1_cur_cd": "USD", "occurs1_net_pl_amt": 순손익}


def _총합줄(순손익):
    return {"occurs1_prd_cd": "--------", "occurs1_prd_nm": "환산합계", "occurs1_net_pl_amt": 순손익}


def _누적손익(호출부, 물음=None):
    app.dependency_overrides[get_client] = lambda: 호출부
    try:
        return TestClient(app).post("/api/overseas/cumulative-pl", json=물음 or {"inq_strt_dt": "20260901", "inq_ed_dt": "20260910"})
    finally:
        app.dependency_overrides.pop(get_client, None)


@pytest.mark.parametrize("물음, 기대", [({}, "KRW"), ({"cvs_cur_cd": "USD"}, "USD")])
def test_누적손익_답에_보낸_환산통화가_실린다(물음, 기대):
    호출부 = 쪽을주는호출부({"": {"Occurs1": [_손익줄("AAA"), _총합줄("5")], "nxt_key": ""}})
    몸 = _누적손익(호출부, {"inq_strt_dt": "20260901", "inq_ed_dt": "20260910", **물음}).json()

    assert 몸["conversionCurrency"] == 기대
    assert 호출부.보낸것[-1][1]["cvs_cur_cd"] == 기대
    assert "conversionCurrency" not in 몸["total"], "환산통화는 응답 머리 한 곳에만 둡니다."


def test_누적손익_한_쪽이면_그대로():
    호출부 = 쪽을주는호출부({"": {"nrec": "0009", "Occurs1": [_손익줄("AAA"), _총합줄("5")], "nxt_key": ""}})
    몸 = _누적손익(호출부).json()

    assert [줄["productCode"] for 줄 in 몸["rows"]] == ["AAA"]
    assert 몸["total"]["netPl"] == 5
    # 건수는 원문 건수(9)가 아니라 우리가 낸 줄 수입니다.
    assert (몸["count"], 몸["pages"], 몸["nextKey"], 몸["truncated"]) == (1, 1, "", False)


def test_누적손익_세_쪽을_모으고_총합은_마지막_쪽에서():
    호출부 = 쪽을주는호출부(
        {
            "": {"Occurs1": [_손익줄("AAA"), _손익줄("BBB")], "nxt_key": "K1"},
            # 가운데 쪽의 총합 줄은 목록에도 총합에도 두지 않습니다.
            "K1": {"Occurs1": [_손익줄("CCC"), _총합줄("999")], "nxt_key": "K2"},
            "K2": {"Occurs1": [_손익줄("DDD"), _총합줄("4")], "nxt_key": ""},
        }
    )
    몸 = _누적손익(호출부).json()

    assert [줄["productCode"] for 줄 in 몸["rows"]] == ["AAA", "BBB", "CCC", "DDD"]
    assert 몸["total"]["netPl"] == 4
    assert (몸["count"], 몸["pages"], 몸["truncated"]) == (4, 3, False)
    보낸들 = [보낸 for _, 보낸 in 호출부.보낸것]
    assert [보낸.get("nxt_key", "") for 보낸 in 보낸들] == ["", "K1", "K2"]
    # 쪽마다 같은 기간·환산통화가 실립니다.
    assert {(보낸["inq_strt_dt"], 보낸["inq_ed_dt"], 보낸["cvs_cur_cd"]) for 보낸 in 보낸들} == {
        ("20260901", "20260910", "KRW")
    }


def test_누적손익_같은_다음_키가_되풀이되면_끝으로_보고_총합을_둔다():
    """마지막 쪽에도 빈 값이 아닌 키가 올 수 있어, 되돌아온 키는 끝으로 봅니다."""
    호출부 = 쪽을주는호출부(
        {
            "": {"Occurs1": [_손익줄("AAA")], "nxt_key": "K1"},
            "K1": {"Occurs1": [_손익줄("BBB"), _총합줄("3")], "nxt_key": "K1"},
        }
    )
    몸 = _누적손익(호출부).json()

    assert len(호출부.보낸것) == 2
    assert (몸["pages"], 몸["truncated"], 몸["total"]["netPl"]) == (2, False, 3)
    assert [줄["productCode"] for 줄 in 몸["rows"]] == ["AAA", "BBB"]


_첫쪽_끝표지 = {"Occurs1": [_손익줄("AAA"), _손익줄("BBB"), _총합줄("3")], "nxt_key": "S"}


@pytest.mark.parametrize(
    "되돌아온쪽",
    [_첫쪽_끝표지, {"Occurs1": [], "nxt_key": "S"}],
    ids=["같은_쪽", "빈_쪽"],
)
def test_누적손익_끝_표지로_다시_부른_답이_겹치거나_비면_버린다(되돌아온쪽):
    """끝 표지 「S」로 한 번 더 부르면 같은 쪽이나 빈 쪽이 올 수 있습니다 — 줄은 한 벌, 총합은 앞 쪽."""
    호출부 = 쪽을주는호출부({"": _첫쪽_끝표지, "S": 되돌아온쪽})
    몸 = _누적손익(호출부).json()

    assert len(호출부.보낸것) == 2
    assert [줄["productCode"] for 줄 in 몸["rows"]] == ["AAA", "BBB"]
    assert (몸["pages"], 몸["truncated"], 몸["total"]["netPl"]) == (1, False, 3)


def test_누적손익_쪽_상한을_넘으면_잘렸다고_하고_총합은_없다():
    from backend.overseas_futureoption.overseas_account import MAX_PL_PAGES

    쪽들 = {
        ("" if 번 == 0 else f"K{번}"): {
            "Occurs1": [_손익줄(f"P{번}"), _총합줄("1")],
            "nxt_key": f"K{번 + 1}",
        }
        for 번 in range(MAX_PL_PAGES + 5)
    }
    호출부 = 쪽을주는호출부(쪽들)
    몸 = _누적손익(호출부).json()

    assert len(호출부.보낸것) == MAX_PL_PAGES == 20
    assert (몸["pages"], 몸["truncated"], 몸["total"], 몸["count"]) == (20, True, None, 20)


@pytest.mark.parametrize(
    "터질것, 상태",
    [(TransportError("overseas_cumulative-pl", "끊김"), 504), (BusinessError("overseas_cumulative-pl", "9", "거절", {}), 502)],
)
def test_누적손익_둘째_쪽이_실패하면_전체가_실패다(터질것, 상태):
    """앞 쪽만 내면 총합 없는 일부가 전부처럼 보입니다."""
    호출부 = 쪽을주는호출부(
        {"": {"Occurs1": [_손익줄("AAA")], "nxt_key": "K1"}, "K1": {"Occurs1": [], "nxt_key": ""}},
        터질쪽=2,
        터질것=터질것,
    )
    응답 = _누적손익(호출부)

    assert 응답.status_code == 상태
    assert "rows" not in 응답.text


# -- 보유포지션 만기 ------------------------------------------------------------


def test_보유포지션_만기_첫_쪽은_000_이고_빈_인자는_안_보낸다():
    앱, 호출부 = _세운다({"nxt_key": "", "nrec": "0000"})
    try:
        첫 = 앱.post("/api/overseas/open-interest-expiry", json={})
        거름 = 앱.post("/api/overseas/open-interest-expiry", json={"und_sym": "6A", "inq_dy_cnt": "30"})
        다음 = 앱.post("/api/overseas/open-interest-expiry", json={"nxt_key": "K2"})
    finally:
        app.dependency_overrides.pop(get_client, None)

    assert (첫.status_code, 거름.status_code, 다음.status_code) == (200, 200, 200)
    assert 첫.json() == {"positions": [], "count": 0, "nextKey": ""}
    보낸것 = [(이름, 몸) for 이름, 몸 in 호출부.보낸것]
    assert 보낸것 == [
        ("overseas_open-interest-expiry", {"nxt_key": "000"}),
        ("overseas_open-interest-expiry", {"nxt_key": "000", "und_sym": "6A", "inq_dy_cnt": "30"}),
        ("overseas_open-interest-expiry", {"nxt_key": "K2"}),
    ]


def test_보유포지션_만기_인자는_모양대로만_받는다():
    앱, 호출부 = _세운다({"nrec": "0000"})
    try:
        for 나쁜값 in ({"und_sym": "6A!"}, {"und_sym": "ABCDEFGHIJK"}, {"inq_dy_cnt": "1234567"}, {"inq_dy_cnt": "3일"}):
            assert 앱.post("/api/overseas/open-interest-expiry", json=나쁜값).status_code == 422, 나쁜값
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 호출부.보낸것 == []


def test_보유포지션_만기_실패는_계좌_문장이다():
    from backend.overseas_futureoption import overseas_routes as 해외

    못받음 = 적어두는호출부({}, 터질것=TransportError("overseas_open-interest-expiry", "끊김"))
    app.dependency_overrides[get_client] = lambda: 못받음
    try:
        응답 = TestClient(app).post("/api/overseas/open-interest-expiry", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)
    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 해외._NOT_RECEIVED


def test_보유포지션_만기는_재생에서_반입한_기록으로_답한다(시세client):
    """모의 계좌에서 보유 1계약일 때 받은 기록입니다."""
    응답 = 시세client.post("/api/overseas/open-interest-expiry", json={})

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert (몸["count"], 몸["nextKey"]) == (1, "")
    (줄,) = 몸["positions"]
    assert (줄["code"], 줄["side"], 줄["sideName"], 줄["quantity"]) == ("MESZ26", "buy", "매수", 1)
    # 체결가는 쉼표가 붙어 옵니다(`7,745.25`).
    assert 줄["fillPrice"] == 7745.25
    assert (줄["fillDate"], 줄["currency"], 줄["delivery"]) == ("2026-09-30", "USD", "현금")
    # 현금결제 품목도 최초통보일이 만기일과 같은 날로 채워 옵니다.
    assert (줄["firstNotice"], 줄["expiry"]) == ("2026-12-18", "2026-12-18")
    # 만기일 − 조회일(2026-09-30) — 명세의 「만기일 포함」과 달리 79 입니다.
    assert 줄["daysLeft"] == 79
    assert 응답.headers[MATCH_HEADER] != "empty"