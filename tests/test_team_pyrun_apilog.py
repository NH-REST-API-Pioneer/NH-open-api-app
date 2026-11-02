"""API 로그 갈고리 — `TradeClient.call_observer` 와 실행별 `api_log.jsonl`."""
import json
import threading

import httpx
import pytest

from backend.nh_api import client as client_module
from backend.nh_api.rate_limit import RateLimiter
from backend.team_pyrun import apilog
from backend.team_pyrun.apilog import ApiLog
from tests.test_trade_client import config, 만들기, 세션, 한번은거절하는서버  # noqa: F401  (config 는 fixture)
from backend.nh_api.client import TradeClient

PRICE = "/trade/v1/domestic/price"
CHART = "/trade/v1/domestic/chart-minute"
ORDER = "/trade/v1/domestic/order"


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def 갈고리(monkeypatch):
    monkeypatch.setattr(client_module, "call_observer", apilog.observe)


def test_실행이_부른_호출만_남는다(config, tmp_path, 갈고리):
    api, _ = 만들기(config, {PRICE: httpx.Response(200, json={"last_pric": "1338.50", "trd_qty": "6850"})})
    log = ApiLog(tmp_path / "api_log.jsonl", "r1")
    api.call("domestic_price", {"sym": "A756B000"})                 # 바인딩 없음 -> 안 남음
    with apilog.bind(log), apilog.purpose("현재가"):
        api.call("domestic_price", {"sym": "A756B000"})
    api.call("domestic_price", {"sym": "A756B000"})                 # 빠져나온 뒤 -> 안 남음
    rows = _rows(tmp_path / "api_log.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["purpose"] == "현재가" and row["run"] == "r1" and row["api_id"] == "domestic_price"
    assert row["summary"] == {"last_pric": "1338.50"}
    assert "body" not in row and row["ok"] is True and row["error"] is None
    assert row["env"] == "paper" and row["http"] == 200 and row["request"] == {"sym": "A756B000"}
    assert row["waited_ms"] >= 0 and row["reissued"] is False and row["code"] is None
    assert isinstance(row["ms"], (int, float)) and row["at"][:2] == "20"


def test_차트는_봉_수와_처음_끝_시각만(config, tmp_path, 갈고리):
    body = {"Occurs1": [
        {"occurs1_ref_dt": "20260909", "occurs1_exch_tm": "090200", "occurs1_close_pric": "1"},
        {"occurs1_ref_dt": "20260909", "occurs1_exch_tm": "090100", "occurs1_close_pric": "2"},
        {"occurs1_ref_dt": "20260909", "occurs1_exch_tm": "090000", "occurs1_close_pric": "3"},
    ]}
    api, _ = 만들기(config, {CHART: httpx.Response(200, json=body)})
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log), apilog.purpose("준비 봉"):
        api.call("domestic_chart-minute", {"sym": "A756B000"})
    row = _rows(tmp_path / "a.jsonl")[0]
    assert row["summary"] == {"rows": 3, "first": "20260909 090200", "last": "20260909 090000"}
    assert "body" not in row


def test_주문_계열은_본문_전체가_남고_계좌_식별정보는_지운다(config, tmp_path, 갈고리):
    body = {"ord_no": "5959", "msg_cd": "", "msg_cntn": "", "ac_no": "1234567890", "Occurs1": [{"occurs1_ac_nm": "홍길동"}]}
    api, _ = 만들기(config, {ORDER: httpx.Response(200, json=body)})
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log), apilog.purpose("진입 주문"):
        api.call("domestic_order", {"sym": "A756B000", "ord_qty": "1", "ac_no": "1234567890", "user_ip_addr": "1.2.3.4"})
    text = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    row = json.loads(text)
    assert row["body"]["ord_no"] == "5959" and "summary" not in row
    for secret in ("1234567890", "홍길동", "1.2.3.4"):
        assert secret not in text
    assert "ac_no" not in row["request"]


def test_업무_거부는_ok_False_코드_본문_전체(config, tmp_path, 갈고리):
    body = {"ord_no": "", "msg_cd": "40010", "msg_cntn": "주문가능수량을 초과했습니다"}
    api, _ = 만들기(config, {ORDER: httpx.Response(200, json=body)})
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log), apilog.purpose("진입 주문"):
        with pytest.raises(client_module.BusinessError):
            api.call("domestic_order", {"sym": "A756B000", "ord_qty": "999"})
    row = _rows(tmp_path / "a.jsonl")[0]
    assert row["ok"] is False and row["code"] == "40010" and row["message"] == "주문가능수량을 초과했습니다"
    assert row["body"] == body and row["error"].startswith("BusinessError: ")
    assert row["http"] == 200


def test_게이트웨이_거절과_HTTP_오류도_남는다(config, tmp_path, 갈고리):
    api, _ = 만들기(config, {
        PRICE: httpx.Response(200, json={"errorCode": "EGW034", "errorMessage": "게이트웨이 내부 오류"}),
        CHART: httpx.Response(500, json={"errorMessage": "서버 오류"}),
    })
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log):
        with pytest.raises(client_module.GatewayError):
            api.call("domestic_price", {})
        with pytest.raises(client_module.HttpError):
            api.call("domestic_chart-minute", {})
    a, b = _rows(tmp_path / "a.jsonl")
    assert a["code"] == "EGW034" and a["error"].startswith("GatewayError: ") and a["ok"] is False
    assert b["http"] == 500 and b["ok"] is False and b["error"].startswith("HttpError: ")
    assert b["body"] == {"errorMessage": "서버 오류"} and a["purpose"] is None


def test_토큰_재발급은_마지막_응답만_남기고_표시한다(config, tmp_path, 갈고리):
    서버_ = 한번은거절하는서버(httpx.Response(200, json={"last_pric": "1.0"}))
    api = TradeClient(세션(config, 서버_))
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log):
        api.call("domestic_price", {"sym": "x"})
    rows = _rows(tmp_path / "a.jsonl")
    assert len(rows) == 1 and rows[0]["reissued"] is True and rows[0]["http"] == 200 and rows[0]["ok"] is True


def test_호출_간격_대기가_남는다(config, tmp_path, 갈고리):
    limiter = RateLimiter(monotonic=lambda: 0.0, sleep=lambda s: None)
    api, _ = 만들기(config, {PRICE: httpx.Response(200, json={"last_pric": "1"})}, limiter=limiter)
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log):
        api.call("domestic_price", {})
        api.call("domestic_price", {})
    rows = _rows(tmp_path / "a.jsonl")
    assert rows[0]["waited_ms"] == 0 and rows[1]["waited_ms"] == 100


def test_응답을_못_받은_호출도_남는다(config, tmp_path, 갈고리):
    api, _ = 만들기(config, {ORDER: httpx.ConnectTimeout("끝내 못 받음")})
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log), apilog.purpose("진입 주문"):
        with pytest.raises(client_module.TransportError):
            api.call("domestic_order", {"sym": "A756B000"})
    row = _rows(tmp_path / "a.jsonl")[0]
    assert row["http"] is None and row["ok"] is False and row["error"].startswith("TransportError: ")
    assert "body" not in row


def test_보내기_전에_막힌_호출도_남고_예외는_그대로다(config, tmp_path, 갈고리):
    api, _ = 만들기(config, {})
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log):
        with pytest.raises(ValueError):
            api.call("auth_token", {})
    row = _rows(tmp_path / "a.jsonl")[0]
    assert row["api_id"] == "auth_token" and row["http"] is None and row["error"].startswith("ValueError: ")


def test_관찰자가_터져도_호출은_그대로다(config, monkeypatch, caplog):
    def 터진다(call):
        raise RuntimeError("관찰자 고장")

    monkeypatch.setattr(client_module, "call_observer", 터진다)
    api, _ = 만들기(config, {PRICE: httpx.Response(200, json={"last_pric": "1"})})
    assert api.call("domestic_price", {}).body == {"last_pric": "1"}
    assert "관찰자 고장" in caplog.text

    api, _ = 만들기(config, {PRICE: httpx.Response(200, json={"errorCode": "EGW034"})})
    with pytest.raises(client_module.GatewayError):     # 예외 종류도 그대로
        api.call("domestic_price", {})


def test_관찰자가_없으면_예전과_같다(config):
    assert client_module.call_observer is None
    api, _ = 만들기(config, {PRICE: httpx.Response(200, json={"last_pric": "1"})})
    assert api.call("domestic_price", {}).http_status == 200


def test_스레드마다_바인딩이_따로다(config, tmp_path, 갈고리):
    api, _ = 만들기(config, {PRICE: httpx.Response(200, json={"last_pric": "1"})})
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    with apilog.bind(log):
        t = threading.Thread(target=lambda: api.call("domestic_price", {}))
        t.start()
        t.join()
    assert not (tmp_path / "a.jsonl").exists() or _rows(tmp_path / "a.jsonl") == []


def test_통계(tmp_path):
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    base = {"env": "paper", "request": {}, "http": 200, "body": {}, "reissued": False, "error": None,
            "code": None, "message": None, "waited_ms": 0}
    log.record({**base, "api_id": "domestic_price", "ms": 10})
    log.record({**base, "api_id": "domestic_price", "ms": 30, "waited_ms": 100, "reissued": True})
    log.record({**base, "api_id": "domestic_order", "ms": 50, "error": "BusinessError: x", "code": "40010", "message": "m"})
    assert log.stats() == {
        "calls": {"domestic_price": 2, "domestic_order": 1},
        "failures": {"domestic_order": 1},
        "codes": {"40010": 1},
        "ms_avg": {"domestic_price": 20.0, "domestic_order": 50.0},
        "ms_max": {"domestic_price": 30, "domestic_order": 50},
        "waited_ms_total": 100,
        "reissued": 1,
    }
    assert len(_rows(tmp_path / "a.jsonl")) == 3


def test_여러_스레드가_써도_줄이_섞이지_않는다(tmp_path):
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    base = {"api_id": "domestic_price", "env": "paper", "request": {}, "http": 200,
            "body": {"last_pric": "1"}, "ms": 1, "waited_ms": 0, "reissued": False, "error": None,
            "code": None, "message": None}
    ts = [threading.Thread(target=lambda: [log.record(base) for _ in range(50)]) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(_rows(tmp_path / "a.jsonl")) == 400


def test_해외_주문_계열도_본문_전체가_남는다(tmp_path):
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    base = {"env": "paper", "request": {}, "http": 200, "ms": 1, "waited_ms": 0, "reissued": False,
            "error": None, "code": None, "message": None}
    for api_id in ("overseas_order", "overseas_order-history", "overseas_open-interest",
                   "overseas_deposit", "overseas_product-detail"):
        log.record({**base, "api_id": api_id, "body": {"ord_no": "7", "x": "y"}})
    for row in _rows(tmp_path / "a.jsonl"):
        assert row["body"] == {"ord_no": "7", "x": "y"} and "summary" not in row
    assert {"overseas_order", "overseas_deposit"} <= apilog.FULL_BODY_APIS


def test_오류_문구의_토큰과_키는_가려서_쓴다(tmp_path):
    log = ApiLog(tmp_path / "a.jsonl", "r1")
    base = {"api_id": "domestic_price", "env": "paper", "request": {}, "http": None, "body": None,
            "ms": 1, "waited_ms": 0, "reissued": False, "code": None, "message": None}
    error = ("TransportError: 접속 토큰을 준비하지 못했습니다: 응답 {'access_token': 'abc123', "
             '"app_secret": "SEC456", "appkey": "KEY789"} 헤더 Bearer xyz appsecret=ZZZ9 ' + "끝" * 600)
    log.record({**base, "error": error})
    text = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    for secret in ("abc123", "SEC456", "KEY789", "xyz", "ZZZ9"):
        assert secret not in text
    row = json.loads(text)
    assert "Bearer ***" in row["error"] and "'access_token': '***'" in row["error"]
    assert len(row["error"]) <= 500 and row["ok"] is False and row["error"].startswith("TransportError: ")
