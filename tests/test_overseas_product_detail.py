"""해외 품목별세부정보 — 가공·이어받기·하루 캐시·라우트.

**어떤 시험도 NH선물 서버에 붙지 않습니다.** 저장해 둔 응답(재생 세션)이나
지어낸 답을 내는 호출부로 돕니다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.nh_api.client import ApiResult, TradeClient
from backend.nh_api.errors import TransportError
from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore, _build
from backend.nh_api.replay import MATCH_HEADER
from backend.nh_api.session import create_session
from backend.overseas_futureoption import overseas_product_service
from backend.overseas_futureoption import overseas_products
from backend.overseas_futureoption.overseas_product_service import MAX_PAGES, ProductService
from backend.overseas_futureoption.overseas_routes import get_client
from backend.sessions.hours import KST

API = "overseas_product-detail"


def _at(year, month, day, hour=9):
    return datetime(year, month, day, hour, tzinfo=KST)


def _줄(code: str, **덮어쓰기: Any) -> dict[str, Any]:
    """품목 한 줄의 원문. 실제 기록과 칸 이름이 같습니다."""
    줄 = {
        "occurs1_prd_cd": code,
        "occurs1_ko_prd_nm": "호주달러",
        "occurs1_fut_opt_div_cd": "F",
        "occurs1_prd_grp_nm": "통화",
        "occurs1_exch_cd": "CME",
        "occurs1_cur_cd": "USD",
        "occurs1_ctr_unt": "00000000000100000.00000000",
        "occurs1_tick_unt": "00000000000000000000.000050000",
        "occurs1_tick_val": "00000000000000005.00000000",
        "occurs1_dlv_div": "2",
        "occurs1_apl_dt": "20260713",
    }
    줄.update(덮어쓰기)
    return 줄


def _쪽(*줄들: dict[str, Any], nxt_key: str = "") -> dict[str, Any]:
    return {"nrec": f"{len(줄들):05d}", "nxt_key": nxt_key, "Occurs1": list(줄들)}


# ── 가공 ────────────────────────────────────────────────────


def test_품목_한_줄이_화면_모양으로_바뀐다():
    made = overseas_products.details([_쪽(_줄("6A"))])

    assert made["count"] == 1
    (품목,) = made["products"]
    assert 품목 == {
        "productCode": "6A",
        "name": "호주달러",
        "kind": "futures",
        "group": "통화",
        "exchangeCode": "CME",
        "currency": "USD",
        # 자리를 0 으로 채운 문자열이 숫자로 옵니다.
        "contractUnit": 100000.0,
        "tickSize": 0.00005,
        "tickValue": 5.0,
        "delivery": "physical",
        "appliedDate": "2026-07-13",
    }


def test_상품구분과_인수도구분이_낱말로_온다():
    쪽 = _쪽(
        _줄("O_4TF", occurs1_fut_opt_div_cd="O", occurs1_dlv_div="1"),
        _줄("S_6E", occurs1_fut_opt_div_cd="S"),
        _줄("ZZ", occurs1_fut_opt_div_cd="Z"),
        _줄("??", occurs1_prd_cd="QQ", occurs1_fut_opt_div_cd="", occurs1_dlv_div=""),
    )
    갈래 = {p["productCode"]: (p["kind"], p["delivery"]) for p in overseas_products.details([쪽])["products"]}

    assert 갈래["O_4TF"] == ("option", "cash")
    assert 갈래["S_6E"] == ("spread", "physical")
    # 명세의 `Z`(기타)와 모르는 값은 같게 답합니다. 모르는 인수도구분은 `null`.
    assert 갈래["ZZ"] == ("other", "physical")
    assert 갈래["QQ"] == ("other", None)


def test_읽히지_않는_값은_비워_둔다():
    (품목,) = overseas_products.details(
        [
            _쪽(
                _줄(
                    "6A",
                    occurs1_ko_prd_nm="   ",
                    occurs1_ctr_unt="",
                    occurs1_tick_unt="아무거나",
                    occurs1_apl_dt="20261345",
                )
            )
        ]
    )["products"]

    assert 품목["name"] is None
    assert 품목["contractUnit"] is None and 품목["tickSize"] is None
    # 있을 수 없는 날은 날짜가 아닙니다.
    assert 품목["appliedDate"] is None


def test_품목코드가_열쇠라_겹치면_뒤엣것이_남고_빈_것은_빠진다():
    made = overseas_products.details(
        [
            _쪽(_줄("6A", occurs1_tick_val="00000000000000005.00000000"), _줄("")),
            _쪽(_줄("6A", occurs1_tick_val="00000000000000009.00000000"), _줄("   ")),
        ]
    )

    assert made["count"] == 1
    assert made["products"][0]["tickValue"] == 9.0


def test_줄이_없거나_모양이_다른_응답도_다룬다():
    assert overseas_products.details([]) == {"products": [], "count": 0}
    # 재생에 기록이 없을 때 오는 빈 응답입니다.
    assert overseas_products.details([{"nrec": "0000", "nxt_key": ""}])["count"] == 0
    assert overseas_products.details([{"Occurs1": "줄이 아님"}, "응답이 아님"])["count"] == 0


# ── 이어받기·하루 캐시 ───────────────────────────────────────


class 쪽마다호출부:
    """미리 정해 둔 쪽을 차례로 내는 호출부. 다 내면 마지막 것을 되풉니다."""

    def __init__(self, 쪽들: list[dict[str, Any]], 터질것: Exception | None = None) -> None:
        self.쪽들 = 쪽들
        self.터질것 = 터질것
        self.보낸것: list[dict[str, Any]] = []
        # 품목 표는 해외 인증 정보가 있는 환경을 골라 부르므로 그 자리도 흉내 냅니다.
        self.session = SimpleNamespace(
            config=SimpleNamespace(
                default_environment="paper",
                environments={"paper": SimpleNamespace(configured_markets=("overseas",))},
            ),
            is_replay=False,
        )

    def call(self, api_id: str, payload: dict[str, Any] | None = None, *, environment=None):
        self.보낸것.append(dict(payload or {}))
        if self.터질것 is not None:
            raise self.터질것
        쪽 = self.쪽들[min(len(self.보낸것) - 1, len(self.쪽들) - 1)]
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market="overseas",
            http_status=200,
            body=쪽,
            headers={},
        )


def test_이어받기_키가_빌_때까지_받아_한_벌로_낸다():
    호출부 = 쪽마다호출부([_쪽(_줄("6A"), nxt_key="SMJI"), _쪽(_줄("6B"), _줄("6C"))])

    made = ProductService().products(api=호출부, now=_at(2026, 9, 16))

    assert [p["productCode"] for p in made["products"]] == ["6A", "6B", "6C"]
    assert made["count"] == 3 and made["source"] == "api"
    assert made["asOf"] == _at(2026, 9, 16).isoformat(timespec="seconds")
    # 첫 요청은 빈 키로, 다음 요청은 받은 키로. 여덟 칸을 늘 다 싣습니다.
    assert [보낸것["nxt_key"] for 보낸것 in 호출부.보낸것] == ["", "SMJI"]
    assert set(호출부.보낸것[0]) == {
        "cur_cd", "exch_cd", "fut_opt_div_cd", "nxt_key",
        "prd_cd", "prd_grp_cd", "prd_nm", "sett_cd",
    }


def test_같은_이어받기_키가_다시_오면_멈추고_알린다(caplog):
    """앞으로 나아가지 못한 것이라 같은 쪽을 상한까지 다시 받으면 안 됩니다.

    멈추면 그 뒤 품목이 표에서 빠진 채 그날 내내 쓰이므로 경고를 남깁니다.
    """
    호출부 = 쪽마다호출부([_쪽(_줄("6A"), nxt_key="SMJI")])

    with caplog.at_level(logging.WARNING, logger=overseas_product_service.__name__):
        made = ProductService().products(api=호출부, now=_at(2026, 9, 16))

    assert made["count"] == 1
    assert len(호출부.보낸것) == 2
    (남긴것,) = [기록 for 기록 in caplog.records if 기록.name == overseas_product_service.__name__]
    assert "SMJI" in 남긴것.message
    assert "그 뒤 품목은 이 표에 없습니다" in 남긴것.message


def test_이어받기에는_상한이_있다(caplog):
    class 끝없는호출부(쪽마다호출부):
        def call(self, api_id, payload=None, *, environment=None):
            self.보낸것.append(dict(payload or {}))
            차례 = len(self.보낸것)
            return ApiResult(
                api_id=api_id,
                environment="paper",
                market="overseas",
                http_status=200,
                body=_쪽(_줄(f"P{차례}"), nxt_key=f"KEY{차례}"),
                headers={},
            )

    호출부 = 끝없는호출부([])
    with caplog.at_level("WARNING"):
        made = ProductService().products(api=호출부, now=_at(2026, 9, 16))

    assert len(호출부.보낸것) == MAX_PAGES and made["count"] == MAX_PAGES
    assert any("품목 정보" in 남긴것.message for 남긴것 in caplog.records)


def test_같은_날_두_번째부터는_받아_둔_것을_낸다():
    호출부 = 쪽마다호출부([_쪽(_줄("6A"))])
    made = ProductService()

    처음 = made.products(api=호출부, now=_at(2026, 9, 16, 9))
    다시 = made.products(api=호출부, now=_at(2026, 9, 16, 23))

    assert 처음["source"] == "api" and 다시["source"] == "cache"
    assert 다시["products"] == 처음["products"]
    # 같은 날 안에서는 한 번만 부릅니다.
    assert len(호출부.보낸것) == 1
    # 받아 둔 표가 언제 것인지는 그대로 둡니다 — 다시 부른 시각이 아닙니다.
    assert 다시["asOf"] == 처음["asOf"]


def test_날이_바뀌면_다시_받는다():
    호출부 = 쪽마다호출부([_쪽(_줄("6A"))])
    made = ProductService()

    made.products(api=호출부, now=_at(2026, 9, 16, 23))
    이튿날 = made.products(api=호출부, now=_at(2026, 9, 17, 0))

    assert 이튿날["source"] == "api"
    assert len(호출부.보낸것) == 2


def test_force_면_같은_날에도_다시_받는다():
    호출부 = 쪽마다호출부([_쪽(_줄("6A"))])
    made = ProductService()

    made.products(api=호출부, now=_at(2026, 9, 16))
    다시 = made.products(api=호출부, force=True, now=_at(2026, 9, 16))

    assert 다시["source"] == "api"
    assert len(호출부.보낸것) == 2


def test_받지_못하면_실패가_그대로_올라온다():
    made = ProductService()
    with pytest.raises(TransportError):
        made.products(api=쪽마다호출부([], 터질것=TransportError(API, "끊김")), now=_at(2026, 9, 16))
    assert made.cached() is None


# ── 라우트 ───────────────────────────────────────────────────


@pytest.fixture
def 품목client(monkeypatch):
    """저장해 둔 진짜 기록으로 도는 라우트. 서비스는 시험마다 새것입니다."""
    monkeypatch.setattr(overseas_product_service, "service", ProductService())
    session = create_session(replay=True)
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()


def test_해외_품목_정보가_기록으로_온다(품목client):
    응답 = 품목client.post("/api/overseas/product-detail", json={})

    assert 응답.status_code == 200
    몸 = 응답.json()
    # 기록은 한 쪽(100줄)뿐이고 이어받기 키가 같은 값으로 되돌아옵니다.
    assert 몸["count"] == 100 and len(몸["products"]) == 100
    assert 몸["source"] == "api"
    품목 = {p["productCode"]: p for p in 몸["products"]}["6A"]
    assert (품목["name"], 품목["kind"], 품목["group"]) == ("호주달러", "futures", "통화")
    assert (품목["exchangeCode"], 품목["currency"]) == ("CME", "USD")
    assert (품목["contractUnit"], 품목["tickSize"], 품목["tickValue"]) == (100000.0, 0.00005, 5.0)
    assert (품목["delivery"], 품목["appliedDate"]) == ("physical", "2026-07-13")
    assert 응답.headers[MATCH_HEADER] != "empty"
    assert "occurs1_" not in 응답.text


def test_라우트도_하루_한_번만_받고_force_로_다시_받는다(품목client):
    처음 = 품목client.post("/api/overseas/product-detail", json={}).json()
    두번째 = 품목client.post("/api/overseas/product-detail", json={}).json()
    다시받기 = 품목client.post("/api/overseas/product-detail", json={"force": True}).json()

    assert (처음["source"], 두번째["source"], 다시받기["source"]) == ("api", "cache", "api")
    assert 두번째["count"] == 처음["count"] == 다시받기["count"]


def _저장소(*기록들: dict[str, Any]) -> FixtureStore:
    """지어낸 저장소. **빈 저장소는 저장소의 기록으로 되돌아가므로** 한 건은 둡니다."""
    만든것 = [
        _build(
            {
                "format": FIXTURE_FORMAT,
                "transport": "HTTP",
                "api_id": "overseas_deposit",
                "environment": "paper",
                "market": "overseas",
                "record_id": "made-up-overseas_deposit",
                "collected_at": "2026-09-09T00:00:00+00:00",
                "scenario_id": "overseas_deposit__base",
                "test_group": "",
                "status": "response_received",
                "method": "POST",
                "path": "/trade/v1/overseas/deposit",
                "http_status": 200,
                "request": {"cur_cd": "KRW", "cvs_div": "2"},
                "response": {"biz_dt": "20260909"},
            },
            Path("메모리"),
        )
    ]
    만든것.extend(_build(하나, Path("메모리")) for 하나 in 기록들)
    return FixtureStore(만든것, Path("메모리"))


def _품목기록(응답: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": FIXTURE_FORMAT,
        "transport": "HTTP",
        "api_id": API,
        "environment": "paper",
        "market": "overseas",
        "record_id": f"made-up-{API}",
        "collected_at": "2026-09-09T00:00:00+00:00",
        "scenario_id": f"{API}__base",
        "test_group": "",
        "status": "response_received",
        "method": "POST",
        "path": "/trade/v1/overseas/product-detail",
        "http_status": 200,
        "request": {
            "cur_cd": "", "exch_cd": "", "fut_opt_div_cd": "", "nxt_key": "",
            "prd_cd": "", "prd_grp_cd": "", "prd_nm": "", "sett_cd": "",
        },
        "response": 응답,
    }


def _저장소로_부른다(monkeypatch, store: FixtureStore):
    monkeypatch.setattr(overseas_product_service, "service", ProductService())
    session = create_session(replay=True, fixtures=store)
    app.dependency_overrides[get_client] = lambda: TradeClient(session)
    try:
        return TestClient(app).post("/api/overseas/product-detail", json={})
    finally:
        app.dependency_overrides.pop(get_client, None)
        session.close()


def test_저장한_응답이_0줄이면_빈_표로_온다(monkeypatch):
    """재생이 내는 빈 응답(`replay-empty`)도 같은 모양입니다 — 배열 칸이 아예 없습니다."""
    응답 = _저장소로_부른다(monkeypatch, _저장소(_품목기록({"nrec": "0000", "nxt_key": ""})))

    assert 응답.status_code == 200
    몸 = 응답.json()
    assert (몸["products"], 몸["count"], 몸["source"]) == ([], 0, "api")
    # 재생 설정은 실전 인증 정보가 있어 실전으로 묻고, 모의 기록만 있으니 그것으로 답합니다.
    assert 몸["environment"] == "real"
    assert 응답.headers[MATCH_HEADER] == "cross-environment"


def test_품목_기록이_아예_없으면_받지_못했다고_답한다(monkeypatch):
    """다른 재생 라우트와 같습니다 — 그 API 의 기록이 한 건도 없으면 실패입니다."""
    from backend.overseas_futureoption import overseas_routes as 해외

    응답 = _저장소로_부른다(monkeypatch, _저장소())

    assert 응답.status_code == 504
    assert 응답.json()["detail"] == 해외._PRODUCT_NOT_RECEIVED


def test_force_는_참거짓만_받는다(품목client):
    assert 품목client.post("/api/overseas/product-detail", json={"force": "아니오"}).status_code == 422
