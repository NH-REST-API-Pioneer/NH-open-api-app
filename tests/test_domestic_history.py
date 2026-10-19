"""분봉을 영업일 단위로 모으는 자리.

한 영업일은 **전날 18:00 야간 개장부터 그날 주간 마감까지**인데 분봉 조회는
달력 날짜로 자릅니다. 여기서 붙잡는 것은 그 어긋남을 어떻게 가르는지입니다.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend.domestic_futureoption import domestic_history as history
from backend.main import app
from backend.master import master_service
from backend.sessions.hours import KST

주소 = "/api/domestic/chart-history"

# 2026-09-16 은 수요일, 09-18 은 금요일, 09-19 는 토요일입니다.
수 = date(2026, 9, 16)
금 = date(2026, 9, 18)
월 = date(2026, 9, 21)


def _때(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=KST)


# ── 영업일 가르기 ────────────────────────────────────────


@pytest.mark.parametrize(
    ("때", "바라는것"),
    [
        (_때(2026, 9, 16, 10), 수),
        (_때(2026, 9, 16, 17, 59), 수),
        # 18:00 에 다음 영업일의 야간이 열립니다.
        (_때(2026, 9, 16, 18), date(2026, 9, 17)),
        (_때(2026, 9, 18, 19), 월),
        (_때(2026, 9, 19, 10), 월),
        (_때(2026, 9, 20, 10), 월),
    ],
)
def test_지금이_어느_영업일인지(때, 바라는것):
    assert history.latest_business_day(때) == 바라는것


def test_앞_영업일은_주말을_건너뛴다():
    assert history.previous_business_day(월) == 금
    assert history.previous_business_day(수) == date(2026, 9, 15)


def test_한_영업일은_조회_셋이다():
    """야간이 달력 날짜로 잘려 오므로 전날과 그날을 따로 부릅니다."""
    made = history.windows(수, has_night=True)

    assert [(one.date_text, one.start, one.end, one.night) for one in made] == [
        ("20260915", "180000", "235959", True),
        ("20260916", "000000", "060000", True),
        ("20260916", "000000", "235959", False),
    ]


def test_월요일_야간_뒷부분은_토요일에_있다():
    """**금요일 18:00 에 열린 야간은 토요일 06:00 에 닫힙니다.**

    이 영업일 날짜(월요일)로 부르면 일요일 밤 세션이 없어 늘 빈 답이 오고,
    토요일 새벽은 아무도 안 부르는데 담는 구간 안에 있어 통째로 빠집니다.
    """
    made = history.windows(월, has_night=True)

    assert [(one.date_text, one.start, one.end) for one in made] == [
        ("20260918", "180000", "235959"),
        ("20260919", "000000", "060000"),
        ("20260921", "000000", "235959"),
    ]


def test_담는_구간을_아무도_안_부르는_자리가_없다():
    """부르는 창들이 그 영업일 구간의 **야간 쪽을 빈틈없이** 덮어야 합니다.

    주간 창은 달력 날짜 전체로 부르므로 구간보다 넓습니다 — 넘치는 봉은
    `assemble` 이 버립니다. 모자란 자리가 없는지만 봅니다.
    """
    for 어느날 in (수, 월):
        첫칸, _ = history.span(어느날)
        앞, 뒤, 주간 = history.windows(어느날, has_night=True)

        assert history._stamp_of(앞.day, 앞.start) == 첫칸, ("야간이 18:00 에 열립니다", 어느날)
        끊긴것 = history._stamp_of(뒤.day, 뒤.start) - history._stamp_of(앞.day, 앞.end)
        assert 끊긴것 <= 1_000, ("야간 둘 사이에 빈틈", 어느날)
        assert 주간.day == 어느날, 어느날


def test_야간이_없으면_주간만_부른다():
    """빈 답이 올 조회를 내지 않습니다 — 시세 조회에는 초당 제한이 있습니다."""
    (하나,) = history.windows(수, has_night=False)

    assert (하나.date_text, 하나.night) == ("20260916", False)


def test_자정을_넘는_요청은_안_낸다():
    """`18:00~06:00` 처럼 자정을 넘는 범위는 한 요청으로 내지 않고 날짜마다 나눕니다."""
    for 창 in history.windows(수, has_night=True):
        assert 창.start < 창.end, (창.date_text, 창.start, 창.end)


# ── 모으기 ──────────────────────────────────────────────


def _봉(day: date, hour: int, minute: int = 0):
    made = datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST)
    return {"timestamp": int(made.timestamp() * 1000), "close": 1.0}


def test_영업일_밖의_봉은_버린다():
    """야간 조회에는 옆 영업일의 반쪽이 함께 옵니다."""
    전날 = history.previous_business_day(수)
    pieces = [
        {"bars": [_봉(전날, 17, 59), _봉(전날, 18, 0), _봉(전날, 23, 59)]},
        {"bars": [_봉(수, 0, 0), _봉(수, 6, 0), _봉(수, 18, 0)]},
    ]

    made = history.assemble(pieces, 수)

    # 전날 17:59 는 앞 영업일 것이고, 수요일 18:00 은 다음 영업일 것입니다.
    assert [one["timestamp"] for one in made] == [
        _봉(전날, 18, 0)["timestamp"],
        _봉(전날, 23, 59)["timestamp"],
        _봉(수, 0, 0)["timestamp"],
        _봉(수, 6, 0)["timestamp"],
    ]


def test_같은_시각의_봉은_하나만_남는다():
    """세션 경계의 한 봉이 두 조회에 함께 실려 옵니다."""
    겹침 = _봉(수, 6, 0)
    made = history.assemble([{"bars": [겹침]}, {"bars": [겹침]}], 수)

    assert len(made) == 1


def test_봉이_시각순으로_선다():
    전날 = history.previous_business_day(수)
    pieces = [{"bars": [_봉(수, 9, 0)]}, {"bars": [_봉(전날, 18, 0)]}]

    made = history.assemble(pieces, 수)

    assert [one["timestamp"] for one in made] == [
        _봉(전날, 18, 0)["timestamp"],
        _봉(수, 9, 0)["timestamp"],
    ]


# ── 앞쪽을 다 받았나 ─────────────────────────────────────


def test_첫_봉이_늦으면_보증하지_못한다():
    창 = history.windows(수, has_night=True)[0]
    전날 = history.previous_business_day(수)

    assert history.short({"bars": [_봉(전날, 20, 10)]}, 창) is True
    assert history.short({"bars": [_봉(전날, 18, 0)]}, 창) is False


def test_빈_답은_보증_못_함이_아니다():
    """봉이 하나도 없는 것은 잘린 것이 아니라 그 창에 거래가 없던 것입니다."""
    창 = history.windows(수, has_night=True)[0]

    assert history.short({"bars": []}, 창) is False


def test_첫_봉이_언제여야_하는지_모르는_창은_안_본다():
    """주간은 달력 날짜 전체로 부르고 장이 언제 여는지는 품목마다 다릅니다 —
    00:00 을 기준으로 재면 **늘** 「못 받았다」가 됩니다.
    """
    주간 = history.windows(수, has_night=True)[-1]
    assert 주간.night is False and 주간.expect == ""

    # 09:00 부터 와도 못 받았다고 하지 않습니다.
    assert history.short({"bars": [_봉(수, 9, 0)]}, 주간) is False


def test_야간_앞부분만_기준을_든다():
    """한 응답이 잘린다면 **가장 오래된 쪽**이 잘립니다."""
    앞, 뒤, 주간 = history.windows(수, has_night=True)

    assert (앞.expect, 뒤.expect, 주간.expect) == ("180000", "", "")


# ── 라우트 ──────────────────────────────────────────────


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


class _부름:
    """분봉 조회를 대신 받아 적는 자리. 몇 번, 어떤 인자로 불렸는지 봅니다."""

    def __init__(self, rows=None):
        self.calls: list[dict] = []
        self._rows = rows or {}

    def __call__(self, sym, **물음):
        self.calls.append({"sym": sym, **물음})
        키 = (물음["start_date"], 물음["night"])
        return {"Occurs1": self._rows.get(키, []), "nxt_key": "keep"}


def _원문(day: date, hour: int, minute: int = 0):
    """차트 응답 한 줄. 라우트가 읽는 칸만 담습니다."""
    return {
        "occurs1_ref_dt": day.strftime("%Y%m%d"),
        "occurs1_exch_tm": f"{hour:02d}{minute:02d}00",
        "occurs1_open_pric": "1",
        "occurs1_high_pric": "1",
        "occurs1_low_pric": "1",
        "occurs1_close_pric": "1",
        "occurs1_cum_trd_qty": "1",
    }


def test_야간이_앞_주간이_뒤로_한_줄에_선다(monkeypatch, 실마스터):
    """한 영업일은 전날 야간 개장부터 그날 주간 마감까지입니다."""
    from backend.domestic_futureoption import domestic_routes

    전날 = history.previous_business_day(수)
    부름 = _부름(
        {
            (전날.strftime("%Y%m%d"), True): [_원문(전날, 18, 0)],
            (수.strftime("%Y%m%d"), True): [_원문(수, 5, 0)],
            (수.strftime("%Y%m%d"), False): [_원문(수, 9, 0)],
        }
    )
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)

    made = TestClient(app).post(
        주소, json={"sym": "A016C000", "before": "20260917"}
    ).json()

    assert made["businessDay"] == "20260916"
    assert made["sessions"] == ["night", "day"]
    assert [one["timestamp"] for one in made["bars"]] == [
        _봉(전날, 18, 0)["timestamp"],
        _봉(수, 5, 0)["timestamp"],
        _봉(수, 9, 0)["timestamp"],
    ]
    assert len(부름.calls) == 3


def test_야간이_없는_품목은_주간만_부른다(monkeypatch, 실마스터):
    """빈 답이 올 조회를 내지 않습니다 — 시세 조회에는 초당 제한이 있습니다."""
    from backend.domestic_futureoption import domestic_routes

    부름 = _부름()
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)
    monkeypatch.setattr(master_service.service, "night_products", frozenset)

    TestClient(app).post(주소, json={"sym": "A016C000", "before": "20260917"})

    assert len(부름.calls) == 1
    assert 부름.calls[0]["night"] is False


def test_조회마다_한_달력_날짜_안에_머문다(monkeypatch, 실마스터):
    """자정을 넘는 시각 범위는 내지 않고, 조회마다 한 달력 날짜 안에 둡니다."""
    from backend.domestic_futureoption import domestic_routes

    부름 = _부름()
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)

    TestClient(app).post(주소, json={"sym": "A016C000", "before": "20260917"})

    for 한번 in 부름.calls:
        assert 한번["start_date"] == 한번["end_date"]
        assert 한번["start_time"] < 한번["end_time"]


def test_before_로_한_칸씩_과거로_간다(monkeypatch, 실마스터):
    """답의 `before` 를 그대로 다시 넣으면 앞 영업일입니다."""
    from backend.domestic_futureoption import domestic_routes

    monkeypatch.setattr(domestic_routes.api, "chart_minute", _부름())
    손님 = TestClient(app)

    첫번 = 손님.post(주소, json={"sym": "A016C000", "before": "20260922"}).json()
    두번 = 손님.post(주소, json={"sym": "A016C000", "before": 첫번["before"]}).json()

    assert (첫번["businessDay"], 두번["businessDay"]) == ("20260921", "20260918")
    assert 첫번["before"] == 첫번["businessDay"], "답의 값을 그대로 다시 넣습니다."


def test_앞쪽을_못_받으면_한_번_더_부르고_알린다(monkeypatch, 실마스터):
    """이어받기 키를 믿고 돌 수 없습니다 — 같은 키로 다시 불러도 같은 줄이 옵니다."""
    from backend.domestic_futureoption import domestic_routes

    전날 = history.previous_business_day(수)
    # 18:00 부터 달라 했는데 20:10 부터 옵니다. 다시 불러도 안 늘어납니다.
    부름 = _부름({(전날.strftime("%Y%m%d"), True): [_원문(전날, 20, 10)]})
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)

    made = TestClient(app).post(
        주소, json={"sym": "A016C000", "before": "20260917"}
    ).json()

    assert made["partial"] is True
    야간앞 = [one for one in 부름.calls if one["start_time"] == "180000"]
    assert len(야간앞) == 2, "한 번만 더 봅니다."
    assert 야간앞[1]["next_key"] == "keep", "직전 답의 키로 다시 부릅니다."


def test_다_받았으면_알리지_않는다(monkeypatch, 실마스터):
    from backend.domestic_futureoption import domestic_routes

    전날 = history.previous_business_day(수)
    부름 = _부름({(전날.strftime("%Y%m%d"), True): [_원문(전날, 18, 0)]})
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)

    made = TestClient(app).post(
        주소, json={"sym": "A016C000", "before": "20260917"}
    ).json()

    assert made["partial"] is False
    assert len(부름.calls) == 3, "다시 부르지 않습니다."


def test_이어받기_키는_늘_빈_값이다(monkeypatch, 실마스터):
    """조회 셋의 키를 하나로 낼 수 없습니다 — 더 과거는 `before` 로 갑니다."""
    from backend.domestic_futureoption import domestic_routes

    monkeypatch.setattr(domestic_routes.api, "chart_minute", _부름())

    made = TestClient(app).post(주소, json={"sym": "A016C000"}).json()

    assert made["nextKey"] == ""


def test_세_칸_뒤로_가면_창_아홉이_이렇게_나간다(monkeypatch, 실마스터):
    """**여러 영업일을 잇는 자리는 시험으로만 굳힐 수 있습니다** — 저장해 둔 기록이
    하루치뿐이라, 어떤 날짜·시각으로 나가는지를 받아 적는 자리로 봅니다.

    월요일이 끼어 있어 야간 뒷부분이 토요일로 가는 것도 여기서 잡힙니다.
    """
    from backend.domestic_futureoption import domestic_routes

    부름 = _부름()
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)
    손님 = TestClient(app)

    커서 = "20260923"
    영업일 = []
    for _ in range(3):
        made = 손님.post(주소, json={"sym": "A016C000", "before": 커서}).json()
        영업일.append(made["businessDay"])
        커서 = made["before"]

    assert 영업일 == ["20260922", "20260921", "20260918"]
    assert [(one["start_date"], one["start_time"], one["night"]) for one in 부름.calls] == [
        # 20260922 화요일 — 야간은 월요일 저녁부터 화요일 새벽까지.
        ("20260921", "180000", True),
        ("20260922", "000000", True),
        ("20260922", "000000", False),
        # 20260921 월요일 — 야간은 **금요일 저녁부터 토요일 새벽**까지.
        ("20260918", "180000", True),
        ("20260919", "000000", True),
        ("20260921", "000000", False),
        # 20260918 금요일 — 야간은 목요일 저녁부터 금요일 새벽까지.
        ("20260917", "180000", True),
        ("20260918", "000000", True),
        ("20260918", "000000", False),
    ]


def test_조회_하나가_죽어도_받은_만큼_낸다(monkeypatch, 실마스터):
    """**조회 셋 중 하나가 504 여도 그 영업일을 통째로 버리지 않습니다.**

    첫 요청이 504 로 죽고 다시 부르면 200 이 오는 경우가 있습니다.
    """
    from fastapi import HTTPException

    from backend.domestic_futureoption import domestic_routes

    전날 = history.previous_business_day(수)
    부름 = _부름({(수.strftime("%Y%m%d"), False): [_원문(수, 9, 0)]})
    진짜 = 부름.__call__
    죽는것 = {"남은횟수": 2}

    def 가끔죽음(sym, **물음):
        if 물음["start_date"] == 전날.strftime("%Y%m%d") and 죽는것["남은횟수"]:
            죽는것["남은횟수"] -= 1
            raise HTTPException(status_code=504, detail="시세를 받지 못했습니다.")
        return 진짜(sym, **물음)

    monkeypatch.setattr(domestic_routes.api, "chart_minute", 가끔죽음)

    답 = TestClient(app).post(주소, json={"sym": "A016C000", "before": "20260917"})

    assert 답.status_code == 200, "그 영업일을 통째로 버리지 않습니다."
    made = 답.json()
    assert made["partial"] is True, "못 받은 것을 알립니다."
    assert [one["timestamp"] for one in made["bars"]] == [_봉(수, 9, 0)["timestamp"]]


def test_한_번_죽고_다시_되면_알리지_않는다(monkeypatch, 실마스터):
    from fastapi import HTTPException

    from backend.domestic_futureoption import domestic_routes

    전날 = history.previous_business_day(수)
    부름 = _부름({(전날.strftime("%Y%m%d"), True): [_원문(전날, 18, 0)]})
    진짜 = 부름.__call__
    죽는것 = {"남은횟수": 1}

    def 한번죽음(sym, **물음):
        if 죽는것["남은횟수"]:
            죽는것["남은횟수"] -= 1
            raise HTTPException(status_code=504, detail="시세를 받지 못했습니다.")
        return 진짜(sym, **물음)

    monkeypatch.setattr(domestic_routes.api, "chart_minute", 한번죽음)

    made = TestClient(app).post(주소, json={"sym": "A016C000", "before": "20260917"}).json()

    assert made["partial"] is False


def test_이어받기_키가_비면_다시_안_부른다(monkeypatch, 실마스터):
    """키가 없으면 **같은 요청**을 한 번 더 내는 것이라 부를 까닭이 없습니다."""
    from backend.domestic_futureoption import domestic_routes

    전날 = history.previous_business_day(수)

    class _키없음(_부름):
        def __call__(self, sym, **물음):
            made = super().__call__(sym, **물음)
            return {**made, "nxt_key": ""}

    부름 = _키없음({(전날.strftime("%Y%m%d"), True): [_원문(전날, 20, 10)]})
    monkeypatch.setattr(domestic_routes.api, "chart_minute", 부름)

    made = TestClient(app).post(주소, json={"sym": "A016C000", "before": "20260917"}).json()

    assert made["partial"] is True, "앞쪽을 못 받은 것은 그대로 알립니다."
    assert len(부름.calls) == 3, "다시 부르지는 않습니다."


def test_저장해_둔_응답으로_그_영업일을_모은다(재생자리, 실마스터):
    """지어낸 응답이 아니라 **저장해 둔 기록**으로 한 영업일을 지나갑니다.

    기록은 2026-09-09 것이라 그 영업일을 물어야 봉이 섭니다.
    """
    made = TestClient(app).post(
        주소, json={"sym": "A7569000", "before": "20260910"}
    ).json()

    assert made["businessDay"] == "20260909"
    assert made["bars"], "저장본의 봉이 섭니다."
    처음, 끝 = made["bars"][0]["timestamp"], made["bars"][-1]["timestamp"]
    첫칸, 끝칸 = history.span(date(2026, 9, 9))
    assert 첫칸 <= 처음 <= 끝 <= 끝칸, "그 영업일 안에만 있습니다."
