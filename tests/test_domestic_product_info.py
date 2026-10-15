"""종목 하나의 품목 값 — 증거금 넷과 호가단위 셋.

품목별세부정보는 **품목 단위**라 종목코드로는 바로 못 찾습니다. 마스터에서 그
종목의 거래대상코드와 갈래를 꺼내 품목 줄과 잇는 자리가 이 라우트입니다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.domestic_futureoption import domestic_hours, domestic_routes
from backend.main import app
from backend.master import master_service
from backend.sessions import service as session_service

주소 = "/api/domestic/product-info"


@pytest.fixture
def 재생자리(monkeypatch):
    """저장해 둔 응답으로 도는 접속 자리. **NH선물에 나가지 않습니다.**"""
    from backend.nh_api import runtime
    from backend.nh_api.session import create_session

    monkeypatch.setenv("NH_REPLAY", "1")
    runtime.use(create_session(replay=True))
    try:
        yield
    finally:
        runtime.reset()


@pytest.fixture
def 손님(재생자리, 실마스터):
    """저장해 둔 품목별세부정보를 실제로 받아 둔 손님."""
    session_service.service.refresh_all()
    return TestClient(app)


def test_종목의_증거금_넷을_낸다(손님):
    """코스피200선물입니다 — 반입 응답의 값 그대로입니다."""
    답 = 손님.post(주소, json={"sym": "A016C000"})

    assert 답.status_code == 200
    made = 답.json()
    assert made["code"] == "A016C000"
    assert (made["productCode"], made["productName"]) == ("KOSPI", "코스피200선물")
    assert made["productKind"] == "futures"
    assert made["contractInitialMargin"] == 59_816_850.0
    assert made["initialMarginRate"] == "21.75%"
    assert made["maintenanceMarginRate"] == "14.50%"
    assert made["why"] == ""
    assert made["maintenanceMarginWhy"] == domestic_hours.WHY_NO_MAINTENANCE


def test_종목의_호가단위와_틱값_거래승수를_낸다(손님):
    """가격을 한 칸 올리고 내리는 화면이 **그 종목의 호가단위**로 움직이려면
    있어야 하는 값입니다. 국내 종목 마스터에는 그 칸이 없습니다.
    """
    made = 손님.post(주소, json={"sym": "A016C000"}).json()

    assert (made["tickSize"], made["tickValue"], made["multiplier"]) == (0.05, 12_500.0, 250_000.0)
    assert made["why"] == ""


def test_품목마다_호가단위가_다르다(손님):
    """코스피200선물은 0.05, 미국달러선물은 0.1 입니다 — 한 값으로 움직이면
    달러선물에서 두 칸씩 건너뜁니다.
    """
    달러 = 손님.post(주소, json={"sym": "A7569000"}).json()
    코스피 = 손님.post(주소, json={"sym": "A016C000"}).json()

    assert (달러["tickSize"], 달러["tickValue"], 달러["multiplier"]) == (0.1, 1_000.0, 10_000.0)
    assert 달러["tickSize"] != 코스피["tickSize"]


def test_품목_줄을_못_고르면_호가단위도_빈다(손님):
    """값을 찾은 줄에서만 답니다 — 어느 줄인지 모르는 채로 찍으면 옵션이 선물의
    호가단위로 움직입니다.
    """
    made = 손님.post(주소, json={"sym": "B0169335"}).json()

    assert (made["tickSize"], made["tickValue"], made["multiplier"]) == (None, None, None)
    assert made["why"] == domestic_routes._NO_KIND, "먼저 걸린 까닭을 덮지 않습니다."


def test_표에_호가단위가_없으면_비우고_까닭을_낸다(재생자리, 실마스터, monkeypatch):
    """**반입해 둔 표에는 모든 줄에 호가단위가 있습니다.** 닿을 수 있는 모양으로
    끼워 그 자리를 봅니다 — 없는 칸을 0 으로 내면 화살표가 안 움직입니다.
    """
    줄 = {
        "name": "코스피200선물",
        "productCode": "01",
        "kind": "futures",
        "session": domestic_hours.DAY,
        "contractInitialMargin": 59_816_850.0,
    }
    monkeypatch.setattr(
        session_service.service,
        "table",
        lambda market, api=None: {"sessions": {}, "products": [줄]},
    )

    made = TestClient(app).post(주소, json={"sym": "A016C000"}).json()

    assert (made["tickSize"], made["tickValue"], made["multiplier"]) == (None, None, None)
    assert made["why"] == domestic_routes._NO_TICK


def test_계약당_유지증거금은_비고_까닭을_함께_낸다(손님):
    """응답에 그 칸이 없습니다 — 비율로 봅니다."""
    made = 손님.post(주소, json={"sym": "A016C000"}).json()

    assert made["maintenanceMargin"] is None
    assert made["maintenanceMarginWhy"] == domestic_hours.WHY_NO_MAINTENANCE


def test_마스터에_없어도_코드로_풀어_답한다(손님):
    """만기가 지나 마스터에서 빠진 종목도 품목은 풀립니다."""
    made = 손님.post(주소, json={"sym": "A7569000"}).json()

    assert made["productCode"] == "USD"
    assert made["contractInitialMargin"] == 649_924.8
    assert made["maintenanceMarginRate"] == "3.22%"
    assert made["why"] == ""


def test_갈래를_모르면_찍지_않고_까닭을_낸다(손님):
    """코스피200은 선물 줄과 옵션 줄이 함께 옵니다 — 어느 쪽인지 모르면 못 고릅니다."""
    made = 손님.post(주소, json={"sym": "B0169335"}).json()

    assert made["productCode"] == "KOSPI", "품목까지는 풀립니다."
    assert made["contractInitialMargin"] is None
    assert made["why"] == domestic_routes._NO_KIND


def test_모르는_종목은_까닭을_낸다(손님):
    made = 손님.post(주소, json={"sym": "없어요"}).json()

    assert made["productCode"] is None
    assert made["why"] == domestic_routes._NO_SYMBOL


def test_표에_품목_줄이_없으면_그렇게_답한다(재생자리, 실마스터, monkeypatch):
    """**닿을 수 있는 모양으로 끼웁니다.** `table()` 은 사전을 내거나 올립니다 —
    `None` 을 내는 자리가 없어, 그것으로 재면 못 닿는 길을 재게 됩니다.
    """
    monkeypatch.setattr(
        session_service.service,
        "table",
        lambda market, api=None: {"sessions": {}, "products": []},
    )

    made = TestClient(app).post(주소, json={"sym": "A016C000"}).json()

    assert made["why"] == domestic_routes._NO_TABLE
    assert made["maintenanceMarginWhy"] is None, "못 찾은 답에는 안 붙입니다."


def test_표를_못_받아도_안_죽고_까닭을_낸다(재생자리, 실마스터, monkeypatch):
    """증거금을 보던 사용자에게 「거래시간을 받지 못했습니다」가 서면 엉뚱한
    자리를 봅니다. 답 모양을 하나로 지키고 `why` 로 말합니다.
    """
    from backend.nh_api.errors import TransportError

    def 막힘(market, api=None):
        raise TransportError("domestic_product-detail", "끊겼습니다")

    monkeypatch.setattr(session_service.service, "table", 막힘)

    답 = TestClient(app).post(주소, json={"sym": "A016C000"})

    assert 답.status_code == 200
    made = 답.json()
    assert made["why"] == domestic_routes._TABLE_FAILED
    assert made["contractInitialMargin"] is None


def test_인증_정보가_없으면_무엇을_넣을지_말한다(재생자리, 실마스터, monkeypatch):
    """**기다려도 안 되는 자리입니다.** 해외 키만 넣은 사용자가 국내 화면을
    열면 늘 여기인데, 「잠시 뒤 다시」가 서면 영영 기다립니다.
    """
    from backend.config import ConfigError

    def 키없음(market, api=None):
        raise ConfigError("국내 인증 정보가 없습니다")

    monkeypatch.setattr(session_service.service, "table", 키없음)

    made = TestClient(app).post(주소, json={"sym": "A016C000"}).json()

    assert made["why"] == domestic_routes._NO_KEYS
    # **기다리라는 말이 들면 안 됩니다.** 이 자리는 사용자가 값을 넣어야 풀립니다.
    assert "잠시 뒤" not in domestic_routes._NO_KEYS


def test_마스터를_아직_못_받았으면_그렇게_답한다(재생자리, monkeypatch):
    """앱이 뜨고 열여덟 만 줄을 읽는 동안입니다 — 종목이 틀린 것이 아닙니다."""
    monkeypatch.setattr(master_service.service, "index", lambda: None)

    made = TestClient(app).post(주소, json={"sym": "A016C000"}).json()

    assert made["why"] == domestic_routes._NO_MASTER
    assert made["maintenanceMarginWhy"] is None


def test_살아_있는_옵션은_증거금_칸이_없다고_답한다(손님):
    """옵션 사용자가 가장 많이 볼 답입니다 — 라우트를 지나 굳혀 둡니다."""
    made = 손님.post(주소, json={"sym": "B016A745"}).json()

    assert (made["productCode"], made["productKind"]) == ("KOSPI", "option")
    assert made["contractInitialMargin"] is None
    assert made["initialMarginRate"] is None
    assert made["maintenanceMarginRate"] is None
    assert made["why"] == domestic_routes._NO_MARGIN


def test_거래일_경계를_넘기면_다시_받아_온다(손님, monkeypatch):
    """**받아 둔 것만 내면 어제 값을 새 값처럼 냅니다.** 바탕화면 앱은 며칠씩
    열어 두는 자리이고, 화면은 품목별세부정보를 띄울 때 한 번만 부릅니다.

    나가는 것은 경계 뒤 첫 한 건뿐입니다 — 그 뒤는 `stale()` 이 막습니다.
    """
    from datetime import datetime, timedelta

    from backend.sessions.hours import KST

    받은것 = []
    진짜 = session_service.service._fetch
    monkeypatch.setattr(
        session_service.service,
        "_fetch",
        lambda market, api: 받은것.append(market) or 진짜(market, api),
    )

    # 직전 경계보다 한 시간 앞에 받아 둔 것으로 되돌립니다.
    #
    # **지금 시각에서 거꾸로 셉니다.** 「어제 08:00」처럼 시각을 박아 두면 07:00
    # 전에 돌릴 때 직전 경계가 어제 07:00 이라, 어제 08:00 은 아직 안 낡은 것이
    # 되어 시험이 뜻을 잃습니다.
    session_service.service._fetched_at[session_service.DOMESTIC] = session_service._boundary(
        datetime.now(KST)
    ) - timedelta(hours=1)

    made = 손님.post(주소, json={"sym": "A016C000"}).json()

    assert 받은것 == [session_service.DOMESTIC], "경계를 넘겼으니 한 번 받습니다."
    assert made["contractInitialMargin"] == 59_816_850.0

    손님.post(주소, json={"sym": "A016C000"})

    assert 받은것 == [session_service.DOMESTIC], "그 뒤로는 안 받습니다."


def test_시세_라우트에는_안_실린다(손님):
    """현재가는 마스터를 안 보는 자리입니다 — 증거금을 얹으면 시세가 마스터
    적재 상태에 묶입니다."""
    made = 손님.post("/api/domestic/price", json={"sym": "A016C000"}).json()

    assert "contractInitialMargin" not in made
    assert "maintenanceMarginRate" not in made


def test_낡음은_07시_경계로_가른다():
    """주기를 따로 두지 않습니다 — 품목별세부정보가 곧 시간표입니다.

    **낡았는지 보는 규칙만 재는 시험입니다.** 라우트가 그 규칙을 실제로 타는
    것은 `test_거래일_경계를_넘기면_다시_받아_온다` 가 봅니다.
    """
    from datetime import datetime, timedelta

    from backend.sessions.hours import KST
    from backend.sessions.service import SessionService

    만든것 = SessionService()
    어제 = datetime(2026, 9, 16, 8, 0, tzinfo=KST)
    만든것._tables[session_service.DOMESTIC] = {"sessions": {}, "products": []}
    만든것._fetched_at[session_service.DOMESTIC] = 어제

    assert 만든것.stale(session_service.DOMESTIC, now=어제 + timedelta(hours=1)) is False
    assert 만든것.stale(session_service.DOMESTIC, now=datetime(2026, 9, 17, 7, 1, tzinfo=KST)) is True


def test_까닭마다_갈래_코드가_함께_온다(재생자리, 실마스터, monkeypatch):
    """**화면이 문장 글자로 갈래를 가르지 않게** 코드를 함께 냅니다.

    `why` 는 고객이 읽는 말이라 다듬는 자리입니다. 화면이 그 글자로 「어느
    까닭인가」를 가리면, 문장을 다듬을 때마다 화면의 갈림이 소리 없이 어긋납니다.
    """
    from backend.overseas_futureoption import overseas_routes

    for 표 in (domestic_routes._WHY_CODES, overseas_routes._WHY_CODES):
        assert len(set(표.values())) == len(표), "코드가 겹치면 화면이 못 가립니다."

    # 두 시장이 같은 문장을 쓰는 자리는 코드도 같아야 합니다.
    겹치는것 = set(domestic_routes._WHY_CODES) & set(overseas_routes._WHY_CODES)
    assert 겹치는것, "두 시장이 같은 문장을 씁니다."
    for 문장 in 겹치는것:
        assert domestic_routes._WHY_CODES[문장] == overseas_routes._WHY_CODES[문장]


def test_다_채운_답에는_갈래_코드가_없다(손님):
    """까닭이 없으면 코드도 `None` 입니다 — 화면이 「까닭 있음」으로 읽지 않습니다."""
    made = 손님.post(주소, json={"sym": "A016C000"}).json()

    assert made["why"] == ""
    assert made["whyCode"] is None


def test_못_채운_답에는_갈래_코드가_붙는다(재생자리, monkeypatch):
    """문장과 코드가 짝입니다."""
    monkeypatch.setattr(master_service.service, "index", lambda: None)

    made = TestClient(app).post(주소, json={"sym": "A016C000"}).json()

    assert made["why"] == domestic_routes._NO_MASTER
    assert made["whyCode"] == "no_master"
