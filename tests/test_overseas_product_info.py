"""해외 종목 하나의 품목 값.

**계좌에 한 건도 안 보냅니다.** 마스터 색인과 품목 표를 지어 끼우고, 그 사이의
앱 코드를 다 지나갑니다.

품목별세부정보는 **품목 단위**라 종목코드로는 바로 못 찾습니다 — 마스터가 그
종목의 품목을 풀어 주고, 라우트가 그 품목 줄을 표에서 찾습니다. 이 시험이 보는
것은 그 잇는 자리와 **못 찾았을 때 무엇이라 말하는가**입니다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.master import master_service
from backend.nh_api.errors import TransportError
from backend.overseas_futureoption import overseas_product_service, overseas_routes
from backend.overseas_futureoption.overseas_routes import get_client

주소 = "/api/overseas/product-info"
종목 = "MESZ26"


def _표(**덮어쓰기):
    """품목 표 한 벌. 칸 이름은 `overseas_products._detail` 과 같습니다."""
    made = {
        "products": [
            {
                "productCode": "MES",
                "name": "마이크로 이미니S&P 500",
                "kind": "futures",
                "group": "지수",
                "exchangeCode": "CME",
                "currency": "USD",
                "contractUnit": 5.0,
                "tickSize": 0.25,
                "tickValue": 1.25,
                "delivery": "현금결제",
                "appliedDate": "2026-09-01",
            }
        ],
        "count": 1,
        "source": "cache",
    }
    made.update(덮어쓰기)
    return made


class _색인:
    """마스터 색인 흉내. **「아직 못 받음」과 「그 종목이 없음」을 가릅니다.**"""

    def __init__(self, product=None, *, ready=True):
        self.product = product
        self.ready = ready

    def index(self):
        return {} if self.ready else None

    def product_of(self, market, code):
        return self.product


@pytest.fixture
def 손님(monkeypatch):
    def 세우기(*, product={"product_code": "MES", "kind": "futures"}, ready=True, 표=None, 터질것=None):
        monkeypatch.setattr(master_service, "service", _색인(product, ready=ready))
        monkeypatch.setattr(
            overseas_product_service.service,
            "products",
            lambda **물음: (_ for _ in ()).throw(터질것) if 터질것 else (표 if 표 is not None else _표()),
        )
        app.dependency_overrides[get_client] = lambda: SimpleNamespace(
            session=SimpleNamespace(config=SimpleNamespace(default_environment="paper"))
        )
        return TestClient(app)

    try:
        yield 세우기
    finally:
        app.dependency_overrides.pop(get_client, None)


def test_그_종목의_품목_값을_낸다(손님):
    답 = 손님().post(주소, json={"sym": 종목}).json()

    assert 답["code"] == 종목
    assert (답["productCode"], 답["productKind"]) == ("MES", "futures")
    assert 답["productName"] == "마이크로 이미니S&P 500"
    assert 답["contractUnit"] == 5.0
    assert (답["currency"], 답["delivery"]) == ("USD", "현금결제")
    assert 답["appliedDate"] == "2026-09-01"
    assert 답["source"] == "cache"
    assert 답["why"] == ""


def test_틱은_안_낸다(손님):
    """마스터가 호가단위(`tsiz`)와 틱값(`tval`)을 줍니다. 같은 값을 두 곳에서
    내면 어긋나는 날 어느 쪽이 맞는지 못 가립니다.
    """
    답 = 손님().post(주소, json={"sym": 종목}).json()

    assert "tickSize" not in 답 and "tickValue" not in 답


def test_마스터를_못_받았으면_그렇다고_말한다(손님):
    """「없다」와 「아직 못 받았다」는 다릅니다 — 사용자가 할 일이 다릅니다."""
    답 = 손님(ready=False).post(주소, json={"sym": 종목}).json()

    assert 답["why"] == overseas_routes._NO_MASTER
    # **화면은 이 코드로 갈래를 가릅니다** — 문장 글자로 가르면 문장을 다듬을
    # 때마다 화면의 갈림이 소리 없이 어긋납니다.
    assert 답["whyCode"] == "no_master"
    assert 답["productCode"] is None and 답["contractUnit"] is None


def test_마스터에_없는_종목이면_그렇다고_말한다(손님):
    """색인은 있는데 그 종목이 없는 자리입니다."""
    답 = 손님(product=None).post(주소, json={"sym": "ZZZZ26"}).json()

    assert 답["why"] == overseas_routes._NO_SYMBOL
    assert 답["whyCode"] == "no_symbol"
    assert 답["productCode"] is None


def test_표에_그_품목이_없으면_그렇다고_말한다(손님):
    답 = 손님(표=_표(products=[])).post(주소, json={"sym": 종목}).json()

    assert 답["why"] == overseas_routes._NO_PRODUCT
    assert 답["whyCode"] == "no_product"
    assert 답["productCode"] == "MES", "품목은 풀었고 표에만 없습니다."
    assert 답["contractUnit"] is None


def test_표를_못_받아도_답_모양은_같다(손님):
    """계약단위를 보던 사용자에게 다른 조회의 문구가 서면 엉뚱한 자리를 봅니다."""
    답 = 손님(터질것=TransportError("overseas_product-detail", "끊김")).post(
        주소, json={"sym": 종목}
    )

    assert 답.status_code == 200
    몸 = 답.json()
    assert 몸["why"] == overseas_routes._TABLE_FAILED
    assert 몸["whyCode"] == "table_failed"
    assert 몸["productCode"] == "MES" and 몸["contractUnit"] is None


def test_모르는_칸은_안_받는다(손님):
    """조용히 버리면 「인자가 안 먹는다」로 보입니다 — 품목 표를 종목으로 묻는
    경우가 그렇습니다.
    """
    앱 = 손님()

    assert 앱.post(주소, json={"sym": 종목, "exch_cd": "FCME"}).status_code == 422
    assert 앱.post(주소, json={}).status_code == 422
