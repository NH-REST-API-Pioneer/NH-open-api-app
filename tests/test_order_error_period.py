"""주문오류내역 기간 조회 — 날마다 차례로 불러 합칩니다(국내·해외).

**NH선물 서버에 붙지 않습니다.** 날짜와 다음 쪽 키마다 정해 둔 원문을 내는 호출부로
봅니다. 원문은 시험 안에서 지어낸 합성 값입니다.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import order_error_days
from backend.domestic_futureoption import domestic_routes
from backend.main import app
from backend.nh_api.client import ApiResult
from backend.nh_api.errors import BusinessError, TransportError
from backend.nh_api.replay import MATCH_HEADER, last_replay
from backend.overseas_futureoption import overseas_routes
from backend.sessions.hours import KST

오늘 = "20260929"


class 날별호출부:
    """(조회일자, 다음 쪽 키)마다 정해 둔 원문을 냅니다. 날마다 터뜨리거나 재생 표시를 답니다."""

    def __init__(self, 쪽들=None, *, 실패=None, 재생=None):
        self.쪽들 = 쪽들 or {}
        self.실패 = 실패 or {}
        self.재생 = 재생
        self.보낸것: list[tuple[str, dict]] = []
        self.session = SimpleNamespace(
            config=SimpleNamespace(default_environment="paper"), is_replay=bool(재생)
        )

    def call(self, api_id, payload, environment=None):
        self.보낸것.append((api_id, dict(payload)))
        날 = payload["inq_dt"]
        if self.재생 is not None:
            last_replay.set({"match": self.재생.get(날, "exact"), "symbol": "none", "record": f"rec-{날}"})
        if 날 in self.실패:
            raise self.실패[날]
        몸 = self.쪽들.get((날, payload.get("nxt_key", "")), {"nrec": "0000", "nxt_key": ""})
        return ApiResult(
            api_id=api_id, environment="paper", market="x", http_status=200, body=몸, headers={}
        )

    def 부른날(self) -> list[str]:
        return [몸["inq_dt"] for _, 몸 in self.보낸것]


@pytest.fixture
def 세우기(monkeypatch):
    고정 = datetime(2026, 9, 29, 23, 0, tzinfo=KST)
    monkeypatch.setattr(domestic_routes, "now_kst", lambda: 고정)
    monkeypatch.setattr(overseas_routes, "now_kst", lambda: 고정)

    def 만들기(호출부):
        app.dependency_overrides[domestic_routes.get_client] = lambda: 호출부
        app.dependency_overrides[overseas_routes.get_client] = lambda: 호출부
        return TestClient(app)

    try:
        yield 만들기
    finally:
        app.dependency_overrides.pop(domestic_routes.get_client, None)
        app.dependency_overrides.pop(overseas_routes.get_client, None)


# ── 합성 원문 ──────────────────────────────────────────────


def 국내줄(시각="152122966", 종목="A016C000"):
    return {"occurs1_rcv_tm": 시각, "occurs1_sym": 종목, "occurs1_msg_cd": "40015", "occurs1_msg": "초과"}


def 국내쪽(*줄, 다음="", 더="N"):
    return {"data_tot_cnt": f"{len(줄):011d}", "nxt_data_yn": 더, "nxt_key": 다음, "nrec": f"{len(줄):04d}", "Occurs1": list(줄)}


def 해외줄(번호="1", 주문일="20260929", 국내일="20260929", 시각="101010"):
    return {
        "occurs1_seq_no": 번호, "occurs1_inq_dt": 주문일, "occurs1_dom_dt": 국내일, "occurs1_dom_tm": 시각,
        "occurs1_sym": "MESZ26", "occurs1_msg_cd": "40015", "occurs1_err_msg": "초과",
    }


def 해외쪽(*줄, 다음=""):
    return {"nrec": f"{len(줄):04d}", "nxt_key": 다음, "Occurs1": list(줄)}


국내주소 = "/api/domestic/order-error"
해외주소 = "/api/overseas/order-error"


# ── 하루 조회는 그대로 ─────────────────────────────────────────


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
def test_기간을_안_주면_지금과_같은_하루_조회다(세우기, 주소):
    호출부 = 날별호출부()
    답 = 세우기(호출부).post(주소, json={}).json()

    assert 호출부.부른날() == [오늘]
    assert "period" not in 답 and "failedDays" not in 답
    assert 답["errors"] == []


# ── 날마다 차례로 ──────────────────────────────────────────


def test_국내_사흘을_최신부터_부르고_줄에_물은_날을_붙인다(세우기):
    호출부 = 날별호출부(
        {
            ("20260927", ""): 국내쪽(국내줄("090000000")),
            ("20260928", ""): 국내쪽(국내줄("100000000"), 국내줄("110000000")),
            ("20260929", ""): 국내쪽(국내줄("080000000")),
        }
    )
    답 = 세우기(호출부).post(국내주소, json={"inq_strt_dt": "20260927", "inq_ed_dt": "20260929"}).json()

    assert 호출부.부른날() == ["20260929", "20260928", "20260927"]
    assert [(줄["date"], 줄["time"]) for 줄 in 답["errors"]] == [
        ("2026-09-29", "08:00:00"),
        ("2026-09-28", "11:00:00"),
        ("2026-09-28", "10:00:00"),
        ("2026-09-27", "09:00:00"),
    ]
    assert 답["period"] == {"from": "2026-09-27", "to": "2026-09-29"}
    assert (답["days"], 답["failedDays"], 답["truncated"], 답["nextKey"]) == (3, [], False, "")
    assert (답["total"], 답["hasMore"]) == (4, False)


def test_해외_사흘_줄의_날은_국내_일자가_먼저다(세우기):
    호출부 = 날별호출부(
        {
            ("20260929", ""): 해외쪽(해외줄("1", 국내일="20260930", 시각="050000")),
            ("20260928", ""): 해외쪽(해외줄("2", 주문일="20260928", 국내일="")),
        }
    )
    답 = 세우기(호출부).post(해외주소, json={"inq_strt_dt": "20260927", "inq_ed_dt": "20260929"}).json()

    assert [(줄["id"], 줄["date"]) for 줄 in 답["errors"]] == [("1", "2026-09-30"), ("2", "2026-09-28")]
    assert 답["count"] == 2


@pytest.mark.parametrize("시장", ["국내", "해외"])
def test_한_날의_다음_쪽을_끝까지_받는다(세우기, 시장):
    if 시장 == "국내":
        쪽들 = {
            ("20260929", ""): 국내쪽(국내줄("100000000"), 다음="K2", 더="Y"),
            ("20260929", "K2"): 국내쪽(국내줄("090000000")),
        }
        주소 = 국내주소
    else:
        쪽들 = {
            ("20260929", ""): 해외쪽(해외줄("1"), 다음="K2"),
            ("20260929", "K2"): 해외쪽(해외줄("2", 시각="090000")),
        }
        주소 = 해외주소
    호출부 = 날별호출부(쪽들)
    답 = 세우기(호출부).post(주소, json={"inq_strt_dt": "20260929", "inq_ed_dt": "20260929"}).json()

    assert [몸.get("nxt_key") for _, 몸 in 호출부.보낸것] == ["", "K2"]
    assert len(답["errors"]) == 2


def test_국내는_다음_여부가_N_이면_키가_있어도_멈춘다(세우기):
    호출부 = 날별호출부({("20260929", ""): 국내쪽(국내줄(), 다음="K2", 더="N")})
    세우기(호출부).post(국내주소, json={"inq_strt_dt": "20260929", "inq_ed_dt": "20260929"})

    assert len(호출부.보낸것) == 1


# ── 실패 ─────────────────────────────────────────────────


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
def test_둘째_날이_실패하면_그_날만_빠진다(세우기, 주소):
    줄 = 국내쪽(국내줄()) if 주소 == 국내주소 else 해외쪽(해외줄())
    호출부 = 날별호출부(
        {("20260929", ""): 줄, ("20260927", ""): 줄},
        실패={"20260928": TransportError("x_order-error", "끊김")},
    )
    답 = 세우기(호출부).post(주소, json={"inq_strt_dt": "20260927", "inq_ed_dt": "20260929"}).json()

    assert 호출부.부른날() == ["20260929", "20260928", "20260927"]
    assert [실패["date"] for 실패 in 답["failedDays"]] == ["2026-09-28"]
    assert "NH" not in 답["failedDays"][0]["reason"] and 답["failedDays"][0]["reason"]
    assert 답["days"] == 3


class 둘째쪽에서터지는호출부(날별호출부):
    """그 날의 다음 쪽(키가 있는 부름)에서만 터집니다."""

    def call(self, api_id, payload, environment=None):
        if payload.get("inq_dt") == "20260928" and payload.get("nxt_key"):
            self.보낸것.append((api_id, dict(payload)))
            raise TransportError("x_order-error", "끊김")
        return super().call(api_id, payload, environment)


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
def test_한_날의_둘째_쪽이_실패하면_그_날_줄을_다_버린다(세우기, 주소):
    """앞 쪽만 실으면 그 날이 다 받은 것처럼 보입니다."""
    if 주소 == 국내주소:
        첫쪽 = 국내쪽(국내줄("100000000"), 다음="K2", 더="Y")
        다른날 = 국내쪽(국내줄("090000000"))
    else:
        첫쪽 = 해외쪽(해외줄("5", 주문일="20260928", 국내일="20260928"), 다음="K2")
        다른날 = 해외쪽(해외줄("6"))
    호출부 = 둘째쪽에서터지는호출부({("20260928", ""): 첫쪽, ("20260929", ""): 다른날})
    답 = 세우기(호출부).post(주소, json={"inq_strt_dt": "20260928", "inq_ed_dt": "20260929"}).json()

    assert [줄["date"] for 줄 in 답["errors"]] == ["2026-09-29"]
    assert [실패["date"] for 실패 in 답["failedDays"]] == ["2026-09-28"]


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
@pytest.mark.parametrize(
    "터질것, 상태",
    [(TransportError("x_order-error", "끊김"), 504), (BusinessError("x_order-error", "9", "거절", {}), 502)],
)
def test_모든_날이_실패하면_하루_조회와_같은_실패다(세우기, 주소, 터질것, 상태):
    호출부 = 날별호출부(실패={날: 터질것 for 날 in ("20260927", "20260928", "20260929")})
    응답 = 세우기(호출부).post(주소, json={"inq_strt_dt": "20260927", "inq_ed_dt": "20260929"})

    assert 응답.status_code == 상태


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
def test_모의에서_막힌_조회면_첫_날에서_끝낸다(세우기, 주소):
    """모의투자에서 부를 수 없다는 답은 다른 날도 같습니다 — 더 부르지 않습니다."""
    from backend.nh_api.errors import ERROR_CODE_HEADER, ERROR_KIND_HEADER, GatewayError

    막힘 = GatewayError("x_order-error", "EGW053", "해당 API는 모의투자 에서 호출 할수 없습니다.", {}, "paper-unavailable")
    호출부 = 날별호출부(실패={날: 막힘 for 날 in ("20260927", "20260928", "20260929")})
    응답 = 세우기(호출부).post(주소, json={"inq_strt_dt": "20260927", "inq_ed_dt": "20260929"})

    assert 응답.status_code == 502
    assert (응답.headers[ERROR_KIND_HEADER], 응답.headers[ERROR_CODE_HEADER]) == ("paper-unavailable", "EGW053")
    assert 호출부.부른날() == ["20260929"]


# ── 기간 모양 ──────────────────────────────────────────────


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
@pytest.mark.parametrize(
    "몸, 까닭",
    [
        ({"inq_strt_dt": "20260829", "inq_ed_dt": "20260929"}, order_error_days.TOO_LONG),
        ({"inq_strt_dt": "20260929", "inq_ed_dt": "20260920"}, order_error_days.REVERSED),
        ({"inq_strt_dt": "20260920"}, order_error_days.HALF_PERIOD),
        ({"inq_ed_dt": "20260920"}, order_error_days.HALF_PERIOD),
        ({"inq_strt_dt": "20260920", "inq_ed_dt": "20260921", "inq_dt": "20260920"}, order_error_days.WITH_SINGLE_DAY),
        ({"inq_strt_dt": "20261001", "inq_ed_dt": "20261002"}, order_error_days.FUTURE),
        ({"inq_strt_dt": "20261345", "inq_ed_dt": "20261346"}, "있는 날짜여야 합니다"),
    ],
)
def test_모양이_틀린_기간은_보내지_않는다(세우기, 주소, 몸, 까닭):
    호출부 = 날별호출부()
    응답 = 세우기(호출부).post(주소, json=몸)

    assert 응답.status_code == 422
    assert 까닭 in 응답.text
    assert 호출부.보낸것 == []


def test_31일은_받고_끝날이_오늘보다_뒤면_오늘로_자른다(세우기):
    호출부 = 날별호출부()
    답 = 세우기(호출부).post(국내주소, json={"inq_strt_dt": "20260830", "inq_ed_dt": "20261005"}).json()

    assert 답["period"] == {"from": "2026-08-30", "to": "2026-09-29"}
    assert 답["days"] == 31 and len(호출부.보낸것) == 31
    assert 호출부.부른날()[0] == 오늘 and 호출부.부른날()[-1] == "20260830"


def test_쪽_상한을_넘으면_잘렸다고_한다(세우기, monkeypatch):
    monkeypatch.setattr(order_error_days, "MAX_PAGES", 3)
    쪽들 = {(날, ""): 국내쪽(국내줄()) for 날 in ("20260929", "20260928", "20260927", "20260926")}
    호출부 = 날별호출부(쪽들)
    답 = 세우기(호출부).post(국내주소, json={"inq_strt_dt": "20260926", "inq_ed_dt": "20260929"}).json()

    assert len(호출부.보낸것) == 3
    assert (답["truncated"], 답["days"]) == (True, 3)


# ── 겹침 ─────────────────────────────────────────────────


def test_해외는_두_날에_걸린_같은_줄을_한_번만_남긴다(세우기):
    같은줄 = 해외줄("7", 주문일="20260928", 국내일="20260929")
    호출부 = 날별호출부({("20260929", ""): 해외쪽(같은줄), ("20260928", ""): 해외쪽(같은줄)})
    답 = 세우기(호출부).post(해외주소, json={"inq_strt_dt": "20260928", "inq_ed_dt": "20260929"}).json()

    assert [줄["id"] for 줄 in 답["errors"]] == ["7"]


def test_국내는_열쇠가_없어_날마다의_줄을_거르지_않는다(세우기):
    같은줄 = 국내줄("100000000")
    호출부 = 날별호출부({("20260929", ""): 국내쪽(같은줄), ("20260928", ""): 국내쪽(같은줄)})
    답 = 세우기(호출부).post(국내주소, json={"inq_strt_dt": "20260928", "inq_ed_dt": "20260929"}).json()

    assert [줄["date"] for 줄 in 답["errors"]] == ["2026-09-29", "2026-09-28"]


# ── 재생 ─────────────────────────────────────────────────


@pytest.mark.parametrize("주소", [국내주소, 해외주소])
def test_재생에서_요청과_다른_기록으로_답한_날은_줄을_버린다(세우기, 주소):
    """날짜만 다른 요청에 같은 기록이 답하면, 합친 줄이 날마다 되풀이됩니다."""
    줄 = 국내쪽(국내줄()) if 주소 == 국내주소 else 해외쪽(해외줄())
    호출부 = 날별호출부(
        {(날, ""): 줄 for 날 in ("20260927", "20260928", "20260929")},
        재생={"20260929": "exact", "20260928": "api", "20260927": "api"},
    )
    응답 = 세우기(호출부).post(주소, json={"inq_strt_dt": "20260927", "inq_ed_dt": "20260929"})
    답 = 응답.json()

    assert len(답["errors"]) == 1
    assert 답["replayDroppedDays"] == 2
    assert 응답.headers[MATCH_HEADER] == "api"
