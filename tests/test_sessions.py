"""거래시간과 세션 판정 — 시간표는 저장 기록으로, 판정은 시각을 넣어서.

**어떤 시험도 NH선물 서버에 붙지 않습니다.** 시간표는 재생 세션(저장 기록)으로
받고, 판정은 시각을 직접 넣어 봅니다. 마스터는 조각(`tests/fixtures/master`)입니다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.domestic_futureoption import domestic_hours
from backend.main import app
from backend.master import master_service
from backend.master.master_files import MASTER_FILES_BY_NAME
from backend.master.master_service import MasterService
from backend.master.master_store import save_master
from backend.nh_api import runtime
from backend.nh_api.client import TradeClient
from backend.nh_api.session import create_session
from backend.overseas_futureoption import overseas_hours
from backend.realtime import hub as hub_module
from backend.sessions import judge
from backend.sessions import service as session_service
from backend.sessions.hours import KST, TimeRange, from_dict, now_kst, time_range
from backend.sessions.service import SessionService
from tests.fixtures.master import fixture_text

FIXTURES = Path(__file__).parent / "fixtures" / "nh"
_MASTERS = (
    "fut_opt", "stk_fut_opt", "idx_fut_opt", "cme_fut", "cme_opt",
    "etc_fut", "etc_opt", "opra_opt", "lme_fut",
)


def _at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=KST)


# 2026-09-16 은 수요일입니다.
WED = (2026, 9, 16)


def _raw(api_id: str) -> list[dict]:
    """저장 기록의 응답 본문들(기록된 차례)."""
    made = []
    for path in sorted((FIXTURES / api_id).rglob("*.json")):
        made.append(json.loads(path.read_text(encoding="utf-8")))
    return made


# ── 시간 구간 ─────────────────────────────────────────────


def test_지금_한국시간은_컴퓨터_시간대와_무관하다():
    """라우트의 「오늘」 기본값이 이 값을 쓰므로, 세계시에서 셈한 한국 날짜와 같아야 합니다."""
    from datetime import timezone

    지금 = now_kst()
    assert 지금.tzinfo is KST
    세계시로_센_것 = datetime.now(timezone.utc).astimezone(KST)
    assert abs((세계시로_센_것 - 지금).total_seconds()) < 5
    assert 지금.utcoffset() == timedelta(hours=9)


def test_시간_구간을_읽는다():
    assert time_range("08:45~15:45") == TimeRange(time(8, 45), time(15, 45))
    night = time_range("18:00~익일06:00")
    assert night == TimeRange(time(18, 0), time(6, 0)) and night.next_day
    overseas = time_range("07:00 ~ 06:00")
    assert overseas is not None and overseas.next_day
    # 해외 시간표의 「없음」.
    assert time_range("00:00 ~ 00:00") is None
    # 정산가 산정 시각은 한 점입니다.
    point = time_range("17:35:00 ~ 17:35:00")
    assert point is not None and point.is_point and not point.next_day
    assert time_range("") is None and time_range("아무거나") is None
    # 화면 모양과 되읽기.
    shape = night.as_dict()
    assert shape == {"open": "18:00", "close": "06:00", "nextDay": True}
    assert from_dict(shape) == night


def test_자정을_넘는_구간의_시작과_끝():
    night = time_range("18:00~익일06:00")
    start, end = night.starting(_at(*WED, 0).date())
    assert (start, end) == (_at(*WED, 18), _at(2026, 9, 17, 6))
    assert night.contains(_at(2026, 9, 17, 3), _at(*WED, 0).date())
    assert not night.contains(_at(2026, 9, 17, 6), _at(*WED, 0).date())


# ── 국내 시간표 ─────────────────────────────────────────────


@pytest.fixture
def 국내표():
    (record,) = _raw("domestic_product-detail")
    return domestic_hours.product_detail(record["response"])


def test_국내_시간표는_세션별로_같다(국내표):
    products = 국내표["products"]
    assert len(products) == 31
    assert sum(p["session"] == "day" for p in products) == 20
    assert sum(p["session"] == "night" for p in products) == 11
    day, night = 국내표["sessions"]["day"], 국내표["sessions"]["night"]
    assert day["uniform"] and night["uniform"]
    assert day["trading"] == {"open": "08:45", "close": "15:45", "nextDay": False}
    assert day["openingAuction"] == {"open": "08:30", "close": "08:45", "nextDay": False}
    assert day["closingAuction"] == {"open": "15:35", "close": "15:45", "nextDay": False}
    assert night["trading"] == {"open": "18:00", "close": "06:00", "nextDay": True}
    assert night["openingAuction"] == {"open": "17:50", "close": "18:00", "nextDay": False}
    assert night["closingAuction"] == {"open": "05:50", "close": "06:00", "nextDay": False}


def test_국내_줄에는_이름과_만기와_증거금이_실린다(국내표):
    kospi = next(p for p in 국내표["products"] if p["name"] == "코스피200선물")
    assert kospi["lastDayTrading"] == {"open": "08:45", "close": "15:20", "nextDay": False}
    assert kospi["nearestExpiry"] == "2026-09-10"
    assert (kospi["tick"], kospi["tickValue"], kospi["multiplier"]) == (0.05, 12500, 250000)
    assert kospi["initialMarginRate"] == "21.75%"
    assert kospi["contractInitialMargin"] == 59816850
    night = next(p for p in 국내표["products"] if p["name"] == "(야간)코스피200선물")
    assert night["lastDayTrading"] is None and night["nearestExpiry"] is None


def test_국내_줄에_품목코드가_붙는다(국내표):
    """응답에는 이름만 옵니다 — 화면이 마스터와 이어 붙이려면 코드가 있어야 합니다."""
    코드들 = {p["name"]: p["productCode"] for p in 국내표["products"]}

    assert 코드들["코스피200선물"] == "01"
    assert 코드들["코스피200옵션"] == "01", "선물과 옵션이 같은 품목코드입니다."
    assert 코드들["미국달러선물(USD)"] == "75"
    assert 코드들["3년국채선물(KTB)"] == "65"
    # 위클리는 마스터가 따로 갈라 줍니다(09 코스피위클리·AJ 코스닥위클리).
    assert (코드들["코스피200위클리옵션"], 코드들["코스닥150위클리옵션"]) == ("09", "AJ")
    # 야간 줄도 같은 품목이라 같은 코드입니다.
    assert 코드들["(야간)코스피200선물"] == "01"
    # 저장해 둔 서른한 줄이 하나도 빠짐없이 맞습니다.
    assert [이름 for 이름, 코드 in 코드들.items() if 코드 is None] == []


def test_국내_줄에_선물인지_옵션인지가_붙는다(국내표):
    """응답에 갈래 칸이 없습니다 — 화면이 이름을 뜯어보지 않게 여기서 가릅니다."""
    갈래 = {p["name"]: p["kind"] for p in 국내표["products"]}

    assert 갈래["코스피200선물"] == "futures"
    assert 갈래["코스피200옵션"] == "option"
    assert 갈래["코스피200위클리옵션"] == "option"
    assert 갈래["(야간)코스피200옵션"] == "option"
    # 「선물」도 「옵션」도 없는 이름은 선물로 봅니다.
    assert 갈래["코스닥 글로벌 지수"] == "futures"
    # 서른한 줄이 모두 둘 중 하나이고, 이름에 「옵션」이 있는 것만 옵션입니다.
    assert len(갈래) == 31
    assert set(갈래.values()) == {"futures", "option"}
    assert all((값 == "option") == ("옵션" in 이름) for 이름, 값 in 갈래.items())


def test_모르는_품목_이름은_코드를_비우고_알린다(caplog):
    """이름이 바뀌거나 품목이 늘어난 날 조용히 틀리지 않게 합니다."""
    with caplog.at_level("WARNING"):
        made = domestic_hours.product_detail(
            {"Occurs1": [{"occurs1_dtl_cd_ko_nm": "처음 보는 품목선물"}]}
        )

    (줄,) = made["products"]
    assert 줄["productCode"] is None
    assert 줄["name"] == "처음 보는 품목선물", "줄 자체는 그대로 냅니다."
    assert any("품목코드" in 남긴것.getMessage() for 남긴것 in caplog.records)


def test_최종거래일_시각_표는_시간표와_맞는다(국내표):
    """지수 계열은 15:20, 통화·국채는 11:30 — 내장 표가 받은 값과 같아야 합니다."""
    closes = {p["name"]: p["lastDayTrading"]["close"] for p in 국내표["products"] if p["lastDayTrading"]}
    assert set(closes.values()) == {"15:20", "11:30"}
    for name, close in closes.items():
        currency_or_bond = "국채" in name or any(code in name for code in ("USD", "EUR", "JPY", "CNH"))
        expected = judge.LAST_DAY_CLOSE["05" if currency_or_bond else "03"]
        assert close == expected.strftime("%H:%M"), name


def test_내장_표는_받은_시간표와_같다(국내표):
    for session in ("day", "night"):
        for field, text in judge.DOMESTIC_FALLBACK[session].items():
            assert time_range(text).as_dict() == 국내표["sessions"][session][field], (session, field)


# ── 해외 시간표 ─────────────────────────────────────────────


@pytest.fixture
def 해외표():
    groups = [r["response"] for r in _raw("overseas_market-operations") if r["request"].get("prd_grp_cd")]
    assert len(groups) == 7
    return overseas_hours.market_operations(groups)


def test_해외_시간표는_그룹_일곱으로_전부_모인다(해외표):
    products = 해외표["products"]
    assert len(products) == 187
    keys = {(p["exchange"], p["productCode"]) for p in products}
    assert len(keys) == 187
    assert {p["exchange"] for p in products} == {"CME", "EUREX", "SGX", "HKEX", "ICE", "CBOE", "JPX"}


def test_해외_줄의_구간_셋과_없음(해외표):
    by_key = {(p["exchange"], p["productCode"]): p for p in 해외표["products"]}
    aud = by_key[("CME", "6A")]
    assert aud["trading"] == {"open": "07:00", "close": "06:00", "nextDay": True}
    assert aud["second"] is None and aud["nextDayTrading"] is None
    assert aud["kind"] == "futures" and aud["currency"] == "USD" and aud["koreanName"] == "호주달러"
    hsi = by_key[("HKEX", "HCEI")]
    assert hsi["trading"] == {"open": "10:15", "close": "13:00", "nextDay": False}
    assert hsi["second"] == {"open": "14:00", "close": "17:30", "nextDay": False}
    assert hsi["nextDayTrading"] == {"open": "18:00", "close": "04:00", "nextDay": True}
    option = by_key[("CME", "O_ES")]
    assert option["kind"] == "option"


def test_마스터_거래소_코드가_시간표_낱말로_이어진다():
    assert overseas_hours.exchange_of("01") == "CME"
    assert overseas_hours.exchange_of("06") == "HKEX"
    assert overseas_hours.exchange_of("99") == "99"


# ── 마스터에서 야간 품목과 종목 줄 ───────────────────────────


@pytest.fixture
def 조각마스터(tmp_path) -> MasterService:
    for name in _MASTERS:
        save_master(MASTER_FILES_BY_NAME[name], fixture_text(name).encode("utf-8"), stamp="20260902", base_dir=tmp_path)
    made = MasterService(base_dir=tmp_path)
    made.reload()
    return made


def test_마스터에_없는_종목도_코드로_품목을_푼다(조각마스터):
    """만기가 지난 옵션은 마스터에서 빠집니다 — 코드의 거래대상코드로 품목을 압니다."""
    # 조각 마스터에 없는 코스피200 옵션(콜·풋)과 선물 코드.
    콜 = 조각마스터.product_of("domestic", "B0169C42")
    풋 = 조각마스터.product_of("domestic", "C016A745")
    선물 = 조각마스터.product_of("domestic", "A0179000")
    assert 조각마스터.locate("domestic", "B0169C42") is None
    assert (콜["product_code"], 콜["trd_code"], 콜["mrkt_code"]) == ("KOSPI", "01", "03")
    assert 풋["product_code"] == "KOSPI" and 선물["product_code"] == "KOSPI"
    assert "expiry_date" not in 콜, "코드로 푼 줄에는 만기가 없습니다"
    # 위클리는 거래대상코드가 글자이고, 스프레드(D)도 같은 자리입니다.
    assert 조각마스터.product_of("domestic", "CAFBW999")["product_code"] == "WKM"
    assert 조각마스터.product_of("domestic", "D01697CS")["product_code"] == "KOSPI"
    # 마스터에 있는 종목이면 그 줄 그대로(만기 포함).
    있는것 = 조각마스터.product_of("domestic", "A0169000")
    assert 있는것["expiry_date"] == "20260910"
    # 모르는 거래대상코드·모양이면 없음.
    assert 조각마스터.product_of("domestic", "B9969000") is None
    assert 조각마스터.product_of("domestic", "없는코드") is None


def test_해외_시리즈_코드도_품목을_푼다(조각마스터):
    """행사가 없는 시리즈 코드(`O_CLF27`)나 마스터에 없는 월물도 품목으로 답합니다."""
    시리즈 = 조각마스터.product_of("overseas", "O_CLF27")
    assert (시리즈["comd"], 시리즈["exch"], 시리즈["ExchName"]) == ("O_CL", "01", "OCME")
    assert 조각마스터.product_of("overseas", "O_CLF27-C60.0")["comd"] == "O_CL"
    assert 조각마스터.product_of("overseas", "6AZ99")["comd"] == "6A"
    # 스프레드는 두 번째 월물이 꼬리에 붙습니다.
    assert 조각마스터.product_of("overseas", "S_6EH27-U26")["comd"] == "S_6E"
    # 위클리 옵션(`O_SPW3FU26-…`)은 코드 모양이 달라 못 풉니다 — 마스터에 있는 동안은
    # `locate` 가 받습니다. 모양이 아닌 코드도 없음입니다.
    assert 조각마스터.product_of("overseas", "O_SPW3FU26-C10000.0") is None
    assert 조각마스터.product_of("overseas", "ZZZZ") is None
    # 표의 열쇠는 행의 품목코드 그대로라 코드 규칙이 못 푸는 모양이 섞이지 않습니다.
    assert all("-" not in 열쇠 for 열쇠 in 조각마스터._index._product_keys("overseas"))


def test_마스터에서_야간_품목과_종목_줄을_찾는다(조각마스터):
    assert "KOSPI" in 조각마스터.night_products()
    assert "NKTB" in 조각마스터.night_products()
    kospi = 조각마스터.locate("domestic", "A0169000")
    assert kospi is not None
    assert (kospi["product_code"], kospi["mrkt_code"], kospi["expiry_date"]) == ("KOSPI", "03", "20260910")
    assert "cme_tp" not in kospi, "세션마다 갈리는 컬럼은 접혀 있습니다."
    aud = 조각마스터.locate("overseas", "6AU26")
    assert aud is not None and (aud["exch"], aud["comd"]) == ("01", "6A")
    assert 조각마스터.locate("overseas", "O_CLF27-C10.00")["comd"] == "O_CL"
    assert 조각마스터.locate("domestic", "없는코드") is None


# ── 판정: 국내 ─────────────────────────────────────────────

KOSPI = {"product_code": "KOSPI", "mrkt_code": "03", "expiry_date": "20261210"}


def _domestic(now, *, contract=KOSPI, has_night=True, table=None):
    return judge.judge_domestic(contract, has_night=has_night, table=table, now=now)


def test_국내_하루의_상태들():
    cases = [
        (_at(*WED, 7, 30), "closed", None, _at(*WED, 8, 30), _at(*WED, 8, 45)),
        (_at(*WED, 8, 35), "pre-open", "day", _at(*WED, 8, 45), _at(*WED, 8, 45)),
        (_at(*WED, 9, 0), "day", "day", _at(*WED, 15, 35), _at(*WED, 18, 0)),
        (_at(*WED, 15, 40), "closing-auction", "day", _at(*WED, 15, 45), _at(*WED, 18, 0)),
        (_at(*WED, 16, 0), "closed", None, _at(*WED, 17, 50), _at(*WED, 18, 0)),
        (_at(*WED, 17, 55), "pre-night", "night", _at(*WED, 18, 0), _at(*WED, 18, 0)),
        (_at(*WED, 20, 0), "night", "night", _at(2026, 9, 17, 5, 50), _at(2026, 9, 17, 8, 45)),
        (_at(2026, 9, 17, 3, 0), "night", "night", _at(2026, 9, 17, 5, 50), _at(2026, 9, 17, 8, 45)),
        (_at(2026, 9, 17, 5, 55), "closing-auction", "night", _at(2026, 9, 17, 6, 0), _at(2026, 9, 17, 8, 45)),
    ]
    for now, state, session, until, next_open in cases:
        made = _domestic(now)
        assert (made["state"], made["session"]) == (state, session), now
        assert made["until"] == until.isoformat(timespec="seconds"), now
        assert made["nextOpen"] == next_open.isoformat(timespec="seconds"), now
        assert made["source"] == "table" and made["hasNight"] is True
        assert made["lastTradingDay"] is None


def test_야간이_없는_품목은_낮이_끝나면_다음_날_아침이다():
    made = _domestic(_at(*WED, 16, 0), has_night=False)
    assert made["state"] == "closed" and made["hasNight"] is False
    assert made["nextOpen"] == _at(2026, 9, 17, 8, 45).isoformat(timespec="seconds")
    assert _domestic(_at(*WED, 20, 0), has_night=False)["state"] == "closed"


def test_주말은_마감이고_다음_개장은_월요일이다():
    saturday = _at(2026, 9, 19, 12, 0)
    made = _domestic(saturday)
    assert made["state"] == "closed"
    assert made["nextOpen"] == _at(2026, 9, 21, 8, 45).isoformat(timespec="seconds")
    # 금요일 밤 세션은 토요일 아침까지 이어집니다.
    assert _domestic(_at(2026, 9, 19, 3, 0))["state"] == "night"
    assert _domestic(_at(2026, 9, 20, 20, 0))["state"] == "closed", "일요일 밤에는 야간이 없습니다."


def test_최종거래일은_일찍_끝난다():
    today = {"product_code": "KOSPI", "mrkt_code": "03", "expiry_date": "20260916"}
    made = _domestic(_at(*WED, 15, 0), contract=today)
    assert made["state"] == "day"
    assert made["until"] == _at(*WED, 15, 20).isoformat(timespec="seconds")
    assert made["lastTradingDay"] == {"closeAt": _at(*WED, 15, 20).isoformat(timespec="seconds")}
    # 마감 뒤에는 이 종목의 세션이 더 없습니다 — 그날 야간도, 다음 날도.
    after = _domestic(_at(*WED, 15, 30), contract=today)
    assert (after["state"], after["until"], after["nextOpen"]) == ("closed", None, None)
    assert after["lastTradingDay"] == made["lastTradingDay"]
    assert _domestic(_at(*WED, 20, 0), contract=today)["state"] == "closed"
    # 마감 전에도 「다음 개장」은 없습니다 — 이 세션이 마지막입니다.
    assert made["nextOpen"] is None
    bond = {"product_code": "NKTB", "mrkt_code": "05", "expiry_date": "20260916"}
    assert _domestic(_at(*WED, 11, 0), contract=bond)["until"] == _at(*WED, 11, 30).isoformat(timespec="seconds")
    assert _domestic(_at(*WED, 12, 0), contract=bond)["state"] == "closed"
    # 어제가 만기였으면 오늘은 보통 날입니다.
    past = {"product_code": "KOSPI", "mrkt_code": "03", "expiry_date": "20260915"}
    assert _domestic(_at(*WED, 15, 30), contract=past)["state"] == "day"


def test_받은_시간표가_있으면_그것을_쓴다(국내표):
    made = _domestic(_at(*WED, 9, 0), table=국내표)
    assert made["source"] == "api" and made["state"] == "day"
    # 표가 비어 있으면 내장 표로 갑니다.
    assert _domestic(_at(*WED, 9, 0), table={"sessions": {}})["source"] == "table"


# ── 판정: 해외 ─────────────────────────────────────────────


def _overseas(now, contract, table):
    return judge.judge_overseas(contract, table=table, now=now)


def test_해외_한_구간_품목(해외표):
    aud = {"exch": "01", "comd": "6A"}
    made = _overseas(_at(*WED, 10, 0), aud, 해외표)
    assert made["state"] == "open" and made["session"] is None
    assert made["since"] == _at(*WED, 7, 0).isoformat(timespec="seconds")
    assert made["until"] == _at(2026, 9, 17, 6, 0).isoformat(timespec="seconds")
    assert made["nextOpen"] == _at(2026, 9, 17, 7, 0).isoformat(timespec="seconds")
    assert made["source"] == "api" and made["hasNight"] is False
    # 06:00~07:00 정비 시간.
    gap = _overseas(_at(2026, 9, 17, 6, 30), aud, 해외표)
    assert gap["state"] == "closed" and gap["nextOpen"] == _at(2026, 9, 17, 7, 0).isoformat(timespec="seconds")


def test_해외_세_구간_품목의_휴식과_익일(해외표):
    hsi = {"exch": "06", "comd": "HCEI"}
    assert _overseas(_at(*WED, 11, 0), hsi, 해외표)["state"] == "open"
    lunch = _overseas(_at(*WED, 13, 30), hsi, 해외표)
    assert lunch["state"] == "break" and lunch["until"] == _at(*WED, 14, 0).isoformat(timespec="seconds")
    assert _overseas(_at(*WED, 15, 0), hsi, 해외표)["state"] == "open-2"
    evening = _overseas(_at(*WED, 17, 45), hsi, 해외표)
    assert evening["state"] == "break" and evening["nextOpen"] == _at(*WED, 18, 0).isoformat(timespec="seconds")
    assert _overseas(_at(2026, 9, 17, 2, 0), hsi, 해외표)["state"] == "next-day"
    assert _overseas(_at(2026, 9, 19, 12, 0), hsi, 해외표)["state"] == "closed"


def test_해외_시간표에_없는_품목은_모름이다(해외표):
    made = _overseas(_at(*WED, 10, 0), {"exch": "01", "comd": "SAAPL"}, 해외표)
    assert made["state"] == "closed" and made["source"] == "unknown"
    assert made["since"] is None and made["until"] is None
    assert _overseas(_at(*WED, 10, 0), {"exch": "01", "comd": "6A"}, None)["source"] == "unknown"


# ── 판정: 해외 「익일」 구간과 주말 ─────────────────────────────
#
# 합성 시간표입니다. 2026-10-02 가 금요일, 10-03 토요일, 10-05 월요일입니다.


def _익일창(시작, 끝, 익일=False):
    return {"open": 시작, "close": 끝, "nextDay": 익일}


def _익일표(*줄):
    return {"products": list(줄)}


def _익일줄(거래소, 품목, 첫, 둘=None, 익일=None):
    return {"exchange": 거래소, "productCode": 품목, "trading": 첫, "second": 둘, "nextDayTrading": 익일}


변동성 = _익일줄("CBOE", "VX", _익일창("07:00", "22:30"), _익일창("22:30", "05:15", True), _익일창("05:30", "06:00"))
항셍 = _익일줄("HKEX", "HSI", _익일창("10:15", "13:00"), _익일창("14:00", "17:30"), _익일창("18:15", "04:00", True))
미니SP = _익일줄("CME", "ES", _익일창("07:00", "06:00", True))
유로스톡스 = _익일줄("EUREX", "FESX", _익일창("08:10", "05:00", True))
싱가폴 = _익일줄("SGX", "SSG", _익일창("09:30", "18:25"), _익일창("18:50", "06:15", True))


def _익일판정(시각, 거래소코드, 품목, 줄):
    return _overseas(시각, {"exch": 거래소코드, "comd": 품목}, _익일표(줄))


@pytest.mark.parametrize(
    "시각, 상태",
    [
        (_at(2026, 10, 2, 23, 0), "open-2"),
        (_at(2026, 10, 3, 5, 20), "break"),
        (_at(2026, 10, 3, 5, 45), "next-day"),
        (_at(2026, 10, 3, 6, 10), "closed"),
        (_at(2026, 10, 5, 5, 45), "closed"),
        (_at(2026, 10, 5, 7, 10), "open"),
    ],
)
def test_다음날_새벽의_익일_구간은_그_전_거래일의_연장이다(시각, 상태):
    """금요일 장의 익일 구간은 토요일 새벽에 서고, 월요일 새벽에는 서지 않습니다."""
    made = _익일판정(시각, "15", "VX", 변동성)
    assert made["state"] == 상태


def test_익일_구간_앞의_틈은_같은_거래일의_쉼이다():
    made = _익일판정(_at(2026, 10, 3, 5, 20), "15", "VX", 변동성)
    assert made["until"] == _at(2026, 10, 3, 5, 30).isoformat(timespec="seconds")
    닫힘 = _익일판정(_at(2026, 10, 3, 6, 10), "15", "VX", 변동성)
    assert 닫힘["nextOpen"] == _at(2026, 10, 5, 7, 0).isoformat(timespec="seconds")


@pytest.mark.parametrize(
    "시각, 상태",
    [
        (_at(2026, 9, 30, 12, 0), "open"),
        (_at(2026, 9, 30, 13, 30), "break"),
        (_at(2026, 10, 6, 2, 0), "next-day"),
        (_at(2026, 10, 5, 3, 0), "closed"),
        (_at(2026, 10, 3, 3, 0), "next-day"),
    ],
)
def test_저녁에_여는_익일_구간은_그_날_시작이다(시각, 상태):
    """홍콩 익일 구간은 그 날 저녁에 열어 자정을 넘깁니다 — 옮기지 않습니다."""
    assert _익일판정(시각, "06", "HSI", 항셍)["state"] == 상태


@pytest.mark.parametrize(
    "시각, 상태",
    [
        (_at(2026, 10, 2, 5, 30), "open"),
        (_at(2026, 10, 2, 6, 30), "closed"),
        (_at(2026, 10, 3, 5, 30), "open"),
        (_at(2026, 10, 3, 6, 30), "closed"),
        (_at(2026, 10, 5, 6, 30), "closed"),
        (_at(2026, 10, 5, 7, 10), "open"),
    ],
)
def test_자정을_넘는_1차_구간은_그대로다(시각, 상태):
    """06:00~07:00 은 날마다의 정비 시간이고, 금요일 거래일은 토요일 06:00 에 닫힙니다."""
    assert _익일판정(시각, "01", "ES", 미니SP)["state"] == 상태


def test_유럽과_싱가폴도_그대로다():
    assert _익일판정(_at(2026, 10, 3, 4, 0), "04", "FESX", 유로스톡스)["state"] == "open"
    assert _익일판정(_at(2026, 10, 5, 8, 0), "04", "FESX", 유로스톡스)["state"] == "closed"
    assert _익일판정(_at(2026, 10, 3, 6, 0), "05", "SSG", 싱가폴)["state"] == "open-2"
    assert _익일판정(_at(2026, 10, 2, 18, 30), "05", "SSG", 싱가폴)["state"] == "break"


# ── 판정: 거래소를 다르게 적는 품목 ───────────────────────────


def test_마스터가_ICE_로_적은_MEM_은_LIFFE_줄로_판정한다():
    줄 = _익일줄("LIFFE", "MEM", _익일창("09:00", "07:00", True))
    made = _익일판정(_at(2026, 9, 30, 10, 0), "11", "MEM", 줄)
    assert (made["source"], made["state"]) == ("api", "open")
    assert _익일판정(_at(2026, 9, 30, 8, 0), "11", "MEM", 줄)["state"] == "closed"


def test_다른_ICE_품목은_LIFFE_줄이_있어도_안_잡힌다():
    줄 = _익일줄("LIFFE", "XYZ", _익일창("09:00", "07:00", True))
    assert _익일판정(_at(2026, 9, 30, 10, 0), "11", "XYZ", 줄)["source"] == "unknown"


def test_ICE_줄이_있으면_그쪽이_먼저다():
    표 = _익일표(
        _익일줄("LIFFE", "MEM", _익일창("09:00", "07:00", True)),
        _익일줄("ICE", "MEM", _익일창("11:00", "12:00")),
    )
    made = _overseas(_at(2026, 9, 30, 11, 30), {"exch": "11", "comd": "MEM"}, 표)
    assert made["until"] == _at(2026, 9, 30, 12, 0).isoformat(timespec="seconds")


# ── 시간표 자리 ────────────────────────────────────────────


@pytest.fixture
def 재생호출부():
    session = create_session(replay=True)
    try:
        yield TradeClient(session)
    finally:
        session.close()


def test_시간표를_받아_두고_하루_한_번만_새로_받는다(재생호출부):
    made = SessionService()
    morning = _at(*WED, 9, 0)
    table = made.table(session_service.DOMESTIC, api=재생호출부, now=morning)
    assert table["asOf"] == morning.isoformat(timespec="seconds")
    assert len(table["products"]) == 31
    # 같은 날 안에서는 그대로, 다음 날 07:00 이 지나면 낡은 것입니다.
    assert not made.stale(session_service.DOMESTIC, _at(*WED, 23, 0))
    assert not made.stale(session_service.DOMESTIC, _at(2026, 9, 17, 6, 59))
    assert made.stale(session_service.DOMESTIC, _at(2026, 9, 17, 7, 0))
    assert made.cached(session_service.OVERSEAS) is None


def test_해외_시간표는_그룹마다_기록과_똑같은_요청으로_받는다(재생호출부):
    """저장 기록은 일곱 칸을 다 실은 요청으로만 exact 로 맞습니다."""
    made = SessionService()
    table = made.table(session_service.OVERSEAS, api=재생호출부, now=_at(*WED, 9, 0))
    assert len(table["products"]) == 187


def test_새로_받지_못하면_받아_둔_것을_쓴다(재생호출부, monkeypatch):
    made = SessionService()
    first = made.table(session_service.DOMESTIC, api=재생호출부, now=_at(*WED, 9, 0))

    def 터진다(*args, **kwargs):
        raise RuntimeError("못 받음")

    monkeypatch.setattr(made, "_fetch", 터진다)
    again = made.table(session_service.DOMESTIC, api=재생호출부, now=_at(2026, 9, 17, 9, 0))
    assert again is first
    # 받아 둔 것도 없으면 실패가 그대로 올라옵니다.
    with pytest.raises(RuntimeError):
        made.table(session_service.OVERSEAS, api=재생호출부, now=_at(*WED, 9, 0))
    # 실패한 뒤 잠시는 다시 가지 않습니다 — 요청마다 NH선물을 두드리지 않습니다.
    monkeypatch.setattr(made, "_fetch", lambda *a, **k: pytest.fail("다시 가면 안 됩니다"))
    assert made.table(session_service.DOMESTIC, api=재생호출부, now=_at(2026, 9, 17, 9, 5)) is first
    with pytest.raises(RuntimeError):
        made.table(session_service.OVERSEAS, api=재생호출부, now=_at(*WED, 9, 5))
    assert made.stale(session_service.OVERSEAS, _at(*WED, 9, 11)), "십 분 뒤에는 다시 가 봅니다."


# ── 라우트 ───────────────────────────────────────────────


@pytest.fixture
def 앱(조각마스터, monkeypatch):
    session = create_session(replay=True)
    runtime.use(session)
    fresh = SessionService()
    monkeypatch.setattr(session_service, "service", fresh)
    monkeypatch.setattr(master_service, "service", 조각마스터)
    fresh.refresh_all(api=TradeClient(session))
    try:
        yield TestClient(app)
    finally:
        runtime.reset()
        asyncio.run(hub_module.reset())


def test_시간표_라우트_둘(앱):
    domestic = 앱.post("/api/domestic/product-detail", json={})
    assert domestic.status_code == 200
    assert domestic.json()["sessions"]["night"]["trading"]["nextDay"] is True
    assert domestic.headers["x-nh-environment"] == "paper"
    overseas = 앱.post("/api/overseas/market-operations", json={})
    assert overseas.status_code == 200
    assert len(overseas.json()["products"]) == 187


def test_판정_라우트(앱, monkeypatch):
    monkeypatch.setattr("backend.sessions.sessions_routes.now_kst", lambda: _at(*WED, 20, 0))
    kospi = 앱.get("/api/session", params={"market": "domestic", "sym": "A0169000"}).json()
    # 재생 설정은 두 환경 모두 인증 정보가 차 있어 시간표를 실전에서 받습니다.
    assert (kospi["state"], kospi["session"], kospi["hasNight"], kospi["source"]) == ("night", "night", True, "api:real")
    assert kospi["now"] == _at(*WED, 20, 0).isoformat(timespec="seconds")
    assert kospi["holidayAware"] is False
    aud = 앱.get("/api/session", params={"market": "overseas", "sym": "6AU26"}).json()
    assert (aud["state"], aud["source"]) == ("open", "api:real")
    unknown = 앱.get("/api/session", params={"market": "domestic", "sym": "없는코드"}).json()
    assert (unknown["state"], unknown["source"]) == ("closed", "unknown")
    # 마스터에 없는(만기 지난) 코스피200 옵션도 품목 창으로 답합니다 — 만기는 모릅니다.
    option = 앱.get("/api/session", params={"market": "domestic", "sym": "B0169C42"}).json()
    assert (option["state"], option["session"], option["hasNight"]) == ("night", "night", True)
    assert option["source"] == "api:real"
    assert option["lastTradingDay"] is None
    # 해외는 행사가 없는 시리즈 코드로도 그 품목의 창입니다.
    series = 앱.get("/api/session", params={"market": "overseas", "sym": "6AZ99"}).json()
    assert (series["state"], series["source"]) == ("open", "api:real")
    assert 앱.get("/api/session", params={"market": "lme", "sym": "X"}).status_code == 422
    assert 앱.get("/api/session", params={"market": "domestic"}).status_code == 422


def test_분봉_주간_야간_한_벌(앱):
    body = {"sym": "A7569000", "inq_strt_dt": "20260909", "inq_ed_dt": "20260909", "session": "both"}
    made = 앱.post("/api/domestic/chart-minute", json=body)
    assert made.status_code == 200
    got = made.json()
    assert got["sessions"] == ["day", "night"] and got["nextKey"] == ""
    stamps = [bar["timestamp"] for bar in got["bars"]]
    assert stamps == sorted(stamps) and len(stamps) == len(set(stamps))
    day_only = 앱.post("/api/domestic/chart-minute", json={**body, "session": "day"}).json()
    night_only = 앱.post("/api/domestic/chart-minute", json={**body, "session": "night"}).json()
    assert day_only["sessions"] == ["day"] and night_only["sessions"] == ["night"]
    assert len(got["bars"]) == len(day_only["bars"]) + len(night_only["bars"])
    assert min(stamps) == night_only["bars"][0]["timestamp"], "야간 00:00~06:00 이 주간보다 앞에 섭니다."


# ── 허브의 세션 시계 ─────────────────────────────────────────


def test_세션_알림과_다음_경계까지_기다릴_시간():
    notice, wait = hub_module.session_notice(_at(*WED, 9, 0))
    assert notice["type"] == "session" and notice["market"] == "domestic"
    assert (notice["state"], notice["session"]) == ("day", "day")
    assert notice["until"] == _at(*WED, 15, 35).isoformat(timespec="seconds")
    # 15:35 까지 6시간 35분이지만 한 시간마다 다시 셉니다.
    assert wait == hub_module.SESSION_CLOCK_MAX_WAIT
    _, short = hub_module.session_notice(_at(*WED, 15, 34) + timedelta(seconds=30))
    assert short == 30.0


def test_시계는_경계를_지났을_때만_방송한다(monkeypatch):
    states = iter(["day", "day", "closing-auction"])
    calls = []

    def 가짜알림(now):
        state = next(states)
        calls.append(state)
        return {"type": "session", "market": "domestic", "state": state}, 0.01

    monkeypatch.setattr(hub_module, "session_notice", 가짜알림)

    async def 실행():
        engine = hub_module.Hub(session=create_session(replay=True), environment="paper")
        client = engine.attach("screen")
        await asyncio.sleep(0.2)
        await engine.stop()
        got = []
        while not client.queue.empty():
            got.append(client.queue.get_nowait())
        return got

    got = asyncio.run(실행())
    session = [m for m in got if m["type"] == "session"]
    assert [m["state"] for m in session] == ["closing-auction"], "같은 상태는 다시 알리지 않습니다."


def test_시계는_품목마다_다른_경계에서도_방송한다(monkeypatch):
    """**상태만 보면 모자랍니다.** 공통 표의 상태는 소수 쪽 품목의 경계를 모르므로,
    09:00 에 여는 품목이 열리는 순간에는 안 바뀝니다. 그 품목을 보던 화면은 다음
    경계까지 옛 세션으로 남습니다.
    """
    # 경계 셋을 차례로 낸 뒤 마지막 것을 그대로 되풉니다 — 다 쓰고 나서도 시계는
    # 계속 도므로, 같은 값을 내야 「안 바뀌면 안 울린다」까지 함께 굳힙니다.
    edges = iter(["08:45", "09:00", "15:35"])
    held = {"edge": "15:35"}

    def 가짜알림(now):
        held["edge"] = next(edges, held["edge"])
        return (
            {"type": "session", "market": "domestic", "state": "day",
             "nextEdge": held["edge"]},
            0.01,
        )

    monkeypatch.setattr(hub_module, "session_notice", 가짜알림)

    async def 실행():
        engine = hub_module.Hub(session=create_session(replay=True), environment="paper")
        client = engine.attach("screen")
        await asyncio.sleep(0.2)
        await engine.stop()
        got = []
        while not client.queue.empty():
            got.append(client.queue.get_nowait())
        return got

    got = asyncio.run(실행())
    session = [m for m in got if m["type"] == "session"]
    assert [m["nextEdge"] for m in session] == ["09:00", "15:35"], "상태가 같아도 울립니다."


def test_세션_알림의_경계는_품목_줄들에서_온다(monkeypatch):
    """**알림의 두 시각은 뜻이 다릅니다.** `until` 은 이 시계의 세션이 끝나는
    때(공통 표 기준)이고, `nextEdge` 는 어느 품목이든 다음으로 뭔가 바뀌는
    때입니다. 09:00 에 여는 품목이 있으면 08:50 의 다음 경계는 09:00 입니다.
    """
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("08:45", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
        ]
    )
    monkeypatch.setattr(session_service.service, "cached", lambda market: 표)

    notice, wait = hub_module.session_notice(_at(*WED, 8, 50))

    assert notice["nextEdge"] == _at(*WED, 9, 0).isoformat(timespec="seconds")
    assert notice["until"] == _at(*WED, 15, 35).isoformat(timespec="seconds")
    assert wait == 600.0, "09:00 까지 10분입니다."


def test_다음_경계는_품목마다_다른_것을_모은다():
    """개장이 08:45 인 품목과 09:00 인 품목이 함께 오면 **둘 다 경계**입니다."""
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("08:45", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
        ]
    )

    이른때 = judge.domestic_edges(표, _at(*WED, 8, 40))
    늦은때 = judge.domestic_edges(표, _at(*WED, 8, 50))

    assert 이른때 == _at(*WED, 8, 45).isoformat(timespec="seconds")
    assert 늦은때 == _at(*WED, 9, 0).isoformat(timespec="seconds")


def test_같은_경계는_한_값이다():
    """품목이 여럿이어도 경계가 같으면 **한 값**입니다 — 시계는 한 번 울립니다."""
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("09:00", "15:45"),
                   openingAuction=_구간("08:45", "09:00")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45"),
                   openingAuction=_구간("08:45", "09:00")),
        ]
    )

    # 08:40 → 동시호가가 열리는 08:45, 08:50 → 둘이 함께 여는 09:00.
    assert judge.domestic_edges(표, _at(*WED, 8, 40)) == _at(*WED, 8, 45).isoformat(
        timespec="seconds"
    )
    assert judge.domestic_edges(표, _at(*WED, 8, 50)) == _at(*WED, 9, 0).isoformat(
        timespec="seconds"
    )


def test_시간표가_없으면_내장_표_경계다():
    """표를 못 받아도 시계는 멈추지 않습니다 — 품목과 무관한 판정 그대로입니다."""
    때 = _at(*WED, 8, 40)

    assert judge.domestic_edges(None, 때) == judge.judge_domestic(
        None, has_night=True, table=None, now=때
    )["until"]


def test_공통_표는_동수면_이른_값이다():
    """아홉 대 아홉이면 최다값이 없습니다 — 줄 순서로 정해지면 같은 표를 다시
    받았을 뿐인데 공통 구간이 바뀝니다.
    """
    이른것 = _품목줄("01", "day", trading=_구간("08:45", "15:45"))
    늦은것 = _품목줄("02", "day", trading=_구간("09:00", "15:45"))

    앞뒤 = domestic_hours._common([이른것, 늦은것], "day")
    뒤앞 = domestic_hours._common([늦은것, 이른것], "day")

    assert 앞뒤["trading"]["open"] == "08:45"
    assert 뒤앞["trading"]["open"] == "08:45", "줄 순서가 바뀌어도 같은 값입니다."
    assert 앞뒤["uniform"] is False


def test_동수의_이른_값은_여는_시각으로_가른다():
    """**여는 시각이 먼저입니다.** 이른 쪽이 늦게 닫아도 이른 쪽을 씁니다 —
    닫는 시각을 먼저 보면 늦게 여는 품목의 구간이 공통 표에 올라옵니다.
    """
    일찍여는것 = _품목줄("01", "day", trading=_구간("08:45", "16:00"))
    일찍닫는것 = _품목줄("02", "day", trading=_구간("09:00", "15:45"))

    made = domestic_hours._common([일찍닫는것, 일찍여는것], "day")

    assert made["trading"] == _구간("08:45", "16:00")


def test_동수면_구간이_있는_쪽을_쓴다():
    """구간이 아예 없는 줄과 동수면 **시각이 적힌 쪽**입니다 — 견줄 시각이 없는
    것을 골라 두면 그 줄이 없는 종목의 판정이 단일가 구간을 통째로 잃습니다.
    """
    없는것 = _품목줄("01", "day", openingAuction=None)
    있는것 = _품목줄("02", "day", openingAuction=_구간("08:30", "08:45"))

    made = domestic_hours._common([없는것, 있는것], "day")

    assert made["openingAuction"] == _구간("08:30", "08:45")


# ── 품목마다 다른 시간 ───────────────────────────────────


def _구간(open_, close, next_day=False):
    return {"open": open_, "close": close, "nextDay": next_day}


def _품목줄(code, session, kind="futures", **덮어쓰기):
    """품목별세부정보 한 줄. 판정이 보는 칸만 담습니다."""
    made = {
        "name": f"{code}-{session}",
        "productCode": code,
        "kind": kind,
        "session": session,
        "trading": _구간("08:45", "15:45"),
        "openingAuction": _구간("08:30", "08:45"),
        "closingAuction": _구간("15:35", "15:45"),
    }
    made.update(덮어쓰기)
    return made


def _표(products):
    """`_common` 을 실제로 돌려 공통 표까지 만든 시간표."""
    return {
        "products": products,
        "sessions": {
            "day": domestic_hours._common(products, "day"),
            "night": domestic_hours._common(products, "night"),
        },
    }


def _종목(code, kind="futures"):
    """마스터 종목 줄에서 판정이 보는 칸만. 열쇠는 `trd_code` 입니다."""
    return {"market": "domestic", "trd_code": code, "kind": kind, "product_code": "X"}


def test_같은_시각에_품목마다_다르게_판정한다():
    """공통 표 하나로 답하면 둘 중 한쪽은 늘 틀립니다.

    주간 개장이 08:45 인 품목과 09:00 인 품목이 반반씩 섞일 수 있습니다 —
    최다값을 고르는 것으로는 절반이 틀립니다.
    """
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("08:45", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
        ]
    )
    때 = _at(*WED, 8, 50)

    이른것 = judge.judge_domestic(_종목("01"), has_night=False, table=표, now=때)
    늦은것 = judge.judge_domestic(_종목("02"), has_night=False, table=표, now=때)

    assert 이른것["state"] == "day", "08:45 에 연 품목은 벌써 거래 중입니다."
    assert 늦은것["state"] != "day", "09:00 에 여는 품목은 아직입니다."


def test_야간_마감도_품목마다_다르다():
    """05:00 에 끝나는 품목과 06:00 에 끝나는 품목이 함께 옵니다(넷 대 여섯)."""
    밤 = {
        "trading": _구간("18:00", "06:00", True),
        "openingAuction": _구간("17:50", "18:00"),
        "closingAuction": _구간("05:50", "06:00"),
    }
    이른밤 = dict(밤)
    이른밤["trading"] = _구간("18:00", "05:00", True)
    이른밤["closingAuction"] = _구간("04:50", "05:00")
    표 = _표(
        [
            _품목줄("01", "night", **밤),
            _품목줄("02", "night", **이른밤),
            _품목줄("03", "night", **이른밤),
        ]
    )
    때 = _at(2026, 9, 17, 5, 30)

    늦은것 = judge.judge_domestic(_종목("01"), has_night=True, table=표, now=때)
    이른것 = judge.judge_domestic(_종목("02"), has_night=True, table=표, now=때)

    assert 늦은것["session"] == "night", "06:00 까지 도는 품목은 아직 야간입니다."
    assert 이른것["session"] != "night", "05:00 에 끝난 품목은 이미 닫혔습니다."


def test_품목_줄이_없으면_공통_표로_간다():
    """시간표에 없는 품목입니다 — 답을 못 한다고 하기보다 시장 표로 답합니다."""
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("09:00", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
            _품목줄("01", "night", trading=_구간("18:00", "06:00", True)),
        ]
    )
    때 = _at(*WED, 8, 50)

    made = judge.judge_domestic(_종목("99"), has_night=False, table=표, now=때)

    assert made["source"] == "api", "내장 표까지 가지 않습니다."
    assert made["state"] != "day", "공통 표의 09:00 개장을 씁니다."


def test_종목을_모르면_공통_표로_간다():
    """허브의 세션 시계가 이렇게 부릅니다 — 품목과 무관한 경계를 냅니다."""
    표 = _표([_품목줄("01", "day", trading=_구간("09:00", "15:45"))])
    때 = _at(*WED, 8, 50)

    made = judge.judge_domestic(None, has_night=False, table=표, now=때)

    assert made["state"] != "day"


def test_갈래가_다른_줄을_안_물어온다():
    """한 품목에 선물 줄과 옵션 줄이 함께 옵니다 — 실제 응답이 그렇습니다."""
    표 = _표(
        [
            _품목줄("01", "day", kind="futures", trading=_구간("08:45", "15:45")),
            _품목줄("01", "day", kind="option", trading=_구간("09:00", "15:45")),
        ]
    )
    때 = _at(*WED, 8, 50)

    선물 = judge.judge_domestic(_종목("01", "futures"), has_night=False, table=표, now=때)
    옵션 = judge.judge_domestic(_종목("01", "option"), has_night=False, table=표, now=때)

    assert 선물["state"] == "day"
    assert 옵션["state"] != "day"


def test_야간_줄이_없으면_주간_줄로_답하지_않는다():
    """주간 구간을 야간에 물리면 18시에 열릴 것이 08시 45분에 열립니다."""
    표 = _표([_품목줄("01", "day", trading=_구간("08:45", "15:45"))])
    때 = _at(*WED, 20, 0)

    made = judge.judge_domestic(_종목("01"), has_night=True, table=표, now=때)

    assert made["session"] == "night", "내장 표의 18:00~06:00 으로 갑니다."


def test_공통_표가_갈려도_알림으로_안_남긴다(caplog):
    """품목마다 다른 것이 이 표의 성질입니다 — 판정은 품목 줄을 먼저 씁니다."""
    products = [
        _품목줄("01", "day", trading=_구간("08:45", "15:45")),
        _품목줄("02", "day", trading=_구간("09:00", "15:45")),
    ]

    with caplog.at_level("INFO", logger="backend.domestic_futureoption.domestic_hours"):
        made = domestic_hours._common(products, "day")

    assert made["uniform"] is False
    남긴것 = [
        기록
        for 기록 in caplog.records
        if 기록.name == "backend.domestic_futureoption.domestic_hours"
    ]
    assert [기록.levelname for 기록 in 남긴것] == ["INFO"], 남긴것


def test_품목_줄_고르는_규칙은_한_곳이다():
    """증거금을 찾는 자리와 시간을 찾는 자리가 같은 줄을 골라야 합니다."""
    from backend.strategy import service as service_lib

    products = [
        _품목줄("01", "day", kind="futures", tick=0.05),
        _품목줄("01", "day", kind="option", tick=0.01),
    ]
    실행목록 = service_lib.RunService(
        hours=type("시간표", (), {"cached": lambda self, market: {"products": products}})(),
    )

    골라낸것 = 실행목록._product_row(_종목("01", "option"), "domestic-day")

    assert 골라낸것 is domestic_hours.product_row(products, _종목("01", "option"), "day")
    assert 골라낸것["kind"] == "option"


def test_갈래를_모르는_줄에는_찍어서_답하지_않는다():
    """마스터에 없는 종목(만기 지난 옵션)은 갈래 없는 최소 줄로 옵니다.

    그 품목에 선물 줄과 옵션 줄이 함께 있으면 **어느 쪽인지 알 수 없습니다.**
    먼저 온 줄을 내면 맞는지 틀리는지가 그날 두 값이 같았는지에 달립니다.
    """
    products = [
        _품목줄("01", "day", kind="futures", trading=_구간("08:45", "15:45")),
        _품목줄("01", "day", kind="option", trading=_구간("09:00", "15:45")),
    ]
    갈래없음 = {"market": "domestic", "trd_code": "01", "product_code": "X"}

    assert domestic_hours.product_row(products, 갈래없음, "day") is None
    assert domestic_hours.product_row(products, 갈래없음, "day", any_window=True) is None


def test_갈래가_하나뿐이면_몰라도_답한다():
    """가릴 것이 없으면 못 가린 것이 아닙니다."""
    products = [_품목줄("06", "day", kind="futures", trading=_구간("09:00", "15:45"))]
    갈래없음 = {"market": "domestic", "trd_code": "06", "product_code": "X"}

    골라낸것 = domestic_hours.product_row(products, 갈래없음, "day")

    assert 골라낸것 is products[0]


def test_갈래를_모르면_공통_표로_답한다():
    """판정은 멈추지 않습니다 — 그 종목의 줄을 못 고를 뿐입니다."""
    표 = _표(
        [
            _품목줄("01", "day", kind="futures", trading=_구간("08:45", "15:45")),
            _품목줄("01", "day", kind="option", trading=_구간("09:00", "15:45")),
            _품목줄("02", "day", kind="futures", trading=_구간("09:00", "15:45")),
            _품목줄("01", "night", trading=_구간("18:00", "06:00", True)),
        ]
    )
    때 = _at(*WED, 8, 50)
    갈래없음 = {"market": "domestic", "trd_code": "01", "product_code": "X"}

    made = judge.judge_domestic(갈래없음, has_night=False, table=표, now=때)

    assert made["source"] == "api", "내장 표까지 가지 않습니다."
    assert made["state"] != "day", "공통 표의 최다값(09:00)을 씁니다."


def test_품목_줄에_거래시간이_없으면_공통_표를_한_번_더_본다():
    """건너뛰면 오늘 받은 값을 두고 작년에 적어 둔 내장 표로 갑니다."""
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("09:00", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
            _품목줄("01", "night", trading=_구간("18:00", "06:00", True)),
        ]
    )
    # 그 품목 줄만 거래시간이 빕니다 — 응답에 그 칸이 안 온 자리입니다.
    표["products"][0]["trading"] = None
    때 = _at(*WED, 8, 50)

    made = judge.judge_domestic(_종목("01"), has_night=False, table=표, now=때)

    assert made["source"] == "api", "공통 표로 한 칸만 내려옵니다."
    assert made["state"] != "day", "공통 표의 09:00 개장을 씁니다."


# ── 야간이 없는 품목의 `source` ─────────────────────────


def _주간만_있는_표():
    """**야간 줄이 하나도 없는 시간표를 지어 넣습니다.** 받아 둔 응답(2026-09-09)은
    서른한 줄 가운데 열한 줄이 야간이라, 공통 야간 표가 늘 차 있습니다. 지어 넣는
    것은 판정의 **입력**이지 서버가 그렇게 답한다는 주장이 아닙니다.
    """
    return _표([_품목줄("01", "day", trading=_구간("08:45", "15:45"))])


def test_야간이_없는_품목은_야간_표가_없어도_받은_표를_쓴다():
    """주간을 오늘 받은 품목 줄에서 읽었으면 `source` 는 `api` 입니다 — 애초에 없는
    야간 구간을 못 찾았다고 「시간표를 못 받았다」로 답하면 어긋납니다.
    """
    made = judge.judge_domestic(
        _종목("01"), has_night=False, table=_주간만_있는_표(), now=_at(*WED, 9, 30)
    )

    assert made["source"] == judge.FROM_API
    assert made["hasNight"] is False
    assert made["state"] == "day", "주간은 품목 줄의 08:45 개장입니다."


def test_야간이_있는_품목은_야간_표가_없으면_전과_같이_내장_표다():
    """야간 창을 실제로 내장 표로 세우므로 `table` 이 맞습니다."""
    made = judge.judge_domestic(
        _종목("01"), has_night=True, table=_주간만_있는_표(), now=_at(*WED, 9, 30)
    )

    assert made["source"] == judge.FROM_TABLE
    assert made["hasNight"] is True


def test_야간이_없는_품목도_주간을_못_읽으면_내장_표다():
    """`source` 는 **주간 구간의 출처를 따릅니다** — 야간이 없다고 늘 `api` 인 것이
    아닙니다. 주간까지 내장 표로 셈하면 그대로 `table` 입니다.
    """
    for 표 in (None, {"sessions": {}}):
        made = judge.judge_domestic(_종목("01"), has_night=False, table=표, now=_at(*WED, 9, 30))

        assert made["source"] == judge.FROM_TABLE, 표


# ── 시간 구간을 어느 층에서 읽었나 ─────────────────────


def test_품목_줄이_있으면_층은_품목_줄이다():
    """**`source` 로는 못 가립니다** — 품목 줄과 공통 표가 둘 다 `api` 입니다.
    화면이 「지금 보이는 시각이 이 품목 것인가」를 물을 수 있어야 합니다.
    """
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("08:45", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
            _품목줄("01", "night", trading=_구간("18:00", "06:00", True)),
        ]
    )

    made = judge.judge_domestic(_종목("01"), has_night=True, table=표, now=_at(*WED, 9, 30))

    assert made["hoursLayer"]["day"] == judge.LAYER_PRODUCT
    assert made["source"] == judge.FROM_API, "`source` 의 뜻은 그대로입니다."


def test_품목_줄에_거래시간이_없으면_층은_공통_표다():
    """**품목 줄이 있는지로 짐작하면 틀립니다.** 줄은 찾았는데 그 세션의 거래시간을
    못 읽어 한 칸 내려온 자리입니다 — 시각은 공통 표의 것입니다.

    **시간표를 지어 넣습니다.** 받아 둔 응답(2026-09-09)은 서른한 줄이 모두 거래시간이
    차 있어 이 갈래를 실물로 만들 수 없습니다. 지어 넣는 것은 판정의 **입력**이지
    서버가 그렇게 답한다는 주장이 아닙니다.
    """
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("08:45", "15:45")),
            _품목줄("02", "day", trading=_구간("09:00", "15:45")),
            _품목줄("01", "night", trading=_구간("18:00", "06:00", True)),
        ]
    )
    # 그 품목 줄만 거래시간이 빕니다 — 응답에 그 칸이 안 온 자리입니다.
    표["products"][0]["trading"] = None

    made = judge.judge_domestic(_종목("01"), has_night=True, table=표, now=_at(*WED, 9, 30))

    assert made["hoursLayer"]["day"] == judge.LAYER_COMMON
    assert made["source"] == judge.FROM_API, "오늘 받은 표라 `source` 는 그대로입니다."


def test_품목_줄이_없으면_층은_공통_표다():
    표 = _표([_품목줄("01", "day", trading=_구간("08:45", "15:45"))])

    made = judge.judge_domestic(_종목("99"), has_night=False, table=표, now=_at(*WED, 9, 30))

    assert made["hoursLayer"]["day"] == judge.LAYER_COMMON


def test_시간표가_없으면_층은_내장_표다():
    made = judge.judge_domestic(_종목("01"), has_night=False, table=None, now=_at(*WED, 9, 30))

    assert made["hoursLayer"]["day"] == judge.LAYER_BUILTIN
    assert made["source"] == judge.FROM_TABLE


def test_주간과_야간의_층이_따로_나온다():
    """**한 값으로는 못 말합니다.** 주간은 품목 줄, 야간은 공통 표인 종목이 올 수 있습니다 —
    야간 줄이 없는 품목이 그렇습니다.
    """
    표 = _표(
        [
            _품목줄("01", "day", trading=_구간("08:45", "15:45")),
            _품목줄("02", "night", trading=_구간("18:00", "06:00", True)),
        ]
    )

    made = judge.judge_domestic(_종목("01"), has_night=True, table=표, now=_at(*WED, 9, 30))

    assert made["hoursLayer"] == {
        "day": judge.LAYER_PRODUCT,
        "night": judge.LAYER_COMMON,
    }


def test_야간이_없는_품목은_야간_층이_빈다():
    """야간 창을 안 세웠는데 층만 남으면 **「이 종목에 야간이 있다」로 읽힙니다.**"""
    표 = _표([_품목줄("01", "day", trading=_구간("08:45", "15:45"))])

    made = judge.judge_domestic(_종목("01"), has_night=False, table=표, now=_at(*WED, 9, 30))

    assert made["hoursLayer"]["night"] is None
    assert made["hasNight"] is False


def test_세션_알림에는_품목_줄_층이_안_나온다():
    """시계는 **종목 없이** 재므로 품목 줄을 찾을 데가 없습니다 — 공통 표 아니면
    내장 표입니다.
    """
    표 = _표([_품목줄("01", "day", trading=_구간("08:45", "15:45"))])
    바꾸기 = pytest.MonkeyPatch()
    바꾸기.setattr(session_service.service, "cached", lambda market: 표)
    try:
        notice, _ = hub_module.session_notice(_at(*WED, 9, 30))
    finally:
        바꾸기.undo()

    assert notice["hoursLayer"]["day"] != judge.LAYER_PRODUCT
    assert notice["hoursLayer"]["day"] == judge.LAYER_COMMON


def test_국내_계약당_증거금은_쉼표가_붙어_와도_읽는다():
    from backend.domestic_futureoption import domestic_hours

    made = domestic_hours.product_detail(
        {"Occurs1": [{"occurs1_dtl_cd_ko_nm": "코스피200선물", "occurs1_ctr_init_mrgn": "59,816,850"}]}
    )
    assert made["products"][0]["contractInitialMargin"] == 59816850.0


# ── 시간표를 받는 환경 ──────────────────────────────────────


def _설정(*, real=(), paper=(), default="paper"):
    """환경마다 인증 정보가 찬 시장만 값을 넣은 설정. 나머지 시장은 비어 있습니다."""
    from backend.config import Config, EnvironmentConfig, MarketConfig

    def 환경(name, markets):
        def 시장(market):
            key = "k" if market in markets else ""
            return MarketConfig(name, market, key, key)

        return EnvironmentConfig(
            name=name, base_url="http://없음", domestic=시장("domestic"), overseas=시장("overseas")
        )

    return Config(
        default_environment=default,
        environments={"paper": 환경("paper", paper), "real": 환경("real", real)},
    )


class _가짜호출부:
    """NH선물에 붙지 않는 호출부. 어느 환경으로 불렀는지만 적어 둡니다."""

    def __init__(self, config):
        from types import SimpleNamespace

        self.session = SimpleNamespace(config=config)
        self.calls: list[tuple[str, str | None]] = []

    def call(self, api_id, payload=None, *, environment=None):
        from types import SimpleNamespace

        from backend.nh_api.client import last_environment

        # 진짜 호출부처럼 부른 환경을 적습니다 — 응답 헤더가 이 값을 씁니다.
        last_environment.set(environment)
        self.calls.append((api_id, environment))
        if api_id == "domestic_product-detail":
            return SimpleNamespace(body=_raw("domestic_product-detail")[0]["response"])
        return SimpleNamespace(body={"Occurs1": [], "nxt_key": ""})


def test_실전_인증_정보가_있으면_실전에서_받는다():
    호출부 = _가짜호출부(_설정(real=("domestic", "overseas"), paper=("domestic", "overseas")))
    made = SessionService()
    국내 = made.table(session_service.DOMESTIC, api=호출부, now=_at(*WED, 9, 0))
    해외 = made.table(session_service.OVERSEAS, api=호출부, now=_at(*WED, 9, 0))
    assert (국내["environment"], 해외["environment"]) == ("real", "real")
    assert {env for _, env in 호출부.calls} == {"real"}
    # 해외는 품목그룹마다 한 번씩입니다.
    assert len(호출부.calls) == 1 + len(overseas_hours.PRODUCT_GROUPS)


def test_실전_인증_정보가_없는_시장만_모의에서_받는다():
    호출부 = _가짜호출부(_설정(real=("domestic",), paper=("domestic", "overseas"), default="real"))
    made = SessionService()
    made.refresh_all(api=호출부)
    assert made.cached(session_service.DOMESTIC)["environment"] == "real"
    assert made.cached(session_service.OVERSEAS)["environment"] == "paper"
    assert ("domestic_product-detail", "real") in 호출부.calls
    assert {env for api_id, env in 호출부.calls if api_id.startswith("overseas")} == {"paper"}


def test_어느_환경에도_인증_정보가_없으면_받지_않고_실패한다():
    from backend.config import ConfigError

    호출부 = _가짜호출부(_설정(real=("domestic",)))
    made = SessionService()
    with pytest.raises(ConfigError):
        made.table(session_service.OVERSEAS, api=호출부, now=_at(*WED, 9, 0))
    assert 호출부.calls == []
    # 앱이 뜰 때의 길 — 기록만 남기고 넘어가며, 해외는 받아 둔 것이 없습니다.
    fresh = SessionService()
    fresh.refresh_all(api=호출부)
    assert fresh.cached(session_service.OVERSEAS) is None
    assert fresh.cached(session_service.DOMESTIC)["environment"] == "real"


def test_시간표는_고른_환경과_무관하게_한_벌이다():
    """활성 환경이 모의든 실전이든 실전에서 받고, 바꿨다고 다시 받지 않습니다."""
    모의 = _가짜호출부(_설정(real=("domestic",), paper=("domestic",), default="paper"))
    made = SessionService()
    first = made.table(session_service.DOMESTIC, api=모의, now=_at(*WED, 9, 0))
    실전 = _가짜호출부(_설정(real=("domestic",), paper=("domestic",), default="real"))
    assert made.table(session_service.DOMESTIC, api=실전, now=_at(*WED, 10, 0)) is first
    assert 모의.calls == [("domestic_product-detail", "real")] and 실전.calls == []


def test_시간표를_받은_응답의_환경_헤더는_활성_환경이다(조각마스터, monkeypatch):
    """실전에서 받아도 화면이 고른 환경(모의)의 답으로 나갑니다 — 화면이 버리지 않게."""
    session = create_session(replay=True)
    runtime.use(session)
    monkeypatch.setattr(session_service, "service", SessionService())
    monkeypatch.setattr(master_service, "service", 조각마스터)
    try:
        got = TestClient(app).post("/api/domestic/product-detail", json={})
        assert got.status_code == 200
        assert got.json()["environment"] == "real"
        assert got.headers["x-nh-environment"] == "paper"
    finally:
        runtime.reset()
        asyncio.run(hub_module.reset())


@pytest.mark.parametrize(
    ("real", "paper", "expected"),
    [
        (("domestic", "overseas"), (), "api:real"),
        ((), ("domestic", "overseas"), "api:paper"),
    ],
)
def test_판정_라우트의_source_는_받은_환경을_말한다(조각마스터, monkeypatch, real, paper, expected):
    호출부 = _가짜호출부(_설정(real=real, paper=paper))
    fresh = SessionService()
    fresh.table(session_service.DOMESTIC, api=호출부, now=now_kst())
    monkeypatch.setattr(session_service, "service", fresh)
    monkeypatch.setattr(master_service, "service", 조각마스터)
    monkeypatch.setattr("backend.sessions.sessions_routes.now_kst", lambda: _at(*WED, 20, 0))
    try:
        made = TestClient(app).get("/api/session", params={"market": "domestic", "sym": "A0169000"})
        assert made.json()["source"] == expected
        # 받아 둔 것이 없는 해외는 그대로 `unknown` 입니다.
        해외 = TestClient(app).get("/api/session", params={"market": "overseas", "sym": "6AU26"})
        assert 해외.json()["source"] == "unknown"
    finally:
        asyncio.run(hub_module.reset())


def test_시험에서는_호출부_없이_시간표를_실서버로_받지_못한다():
    """실서버 세션이 잡혀 있어도 호출부 없이 부른 시간표 받기는 나가기 전에 멈춥니다."""
    session = create_session(replay=False, config=_설정(real=("domestic", "overseas")))
    runtime.use(session)
    try:
        with pytest.raises(AssertionError, match="실서버"):
            SessionService().table(session_service.DOMESTIC, now=_at(*WED, 9, 0))
    finally:
        runtime.reset()


def test_내장_표와_환경이_안_적힌_표는_source_가_그대로다(조각마스터, monkeypatch):
    fresh = SessionService()
    monkeypatch.setattr(session_service, "service", fresh)
    monkeypatch.setattr(master_service, "service", 조각마스터)
    monkeypatch.setattr("backend.sessions.sessions_routes.now_kst", lambda: _at(*WED, 20, 0))
    try:
        client = TestClient(app)
        params = {"market": "domestic", "sym": "A0169000"}
        assert client.get("/api/session", params=params).json()["source"] == "table"
        fresh._tables[session_service.DOMESTIC] = domestic_hours.product_detail(
            _raw("domestic_product-detail")[0]["response"]
        )
        assert client.get("/api/session", params=params).json()["source"] == "api"
    finally:
        asyncio.run(hub_module.reset())

