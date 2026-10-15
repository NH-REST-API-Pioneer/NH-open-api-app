"""해외 분봉을 영업일 단위로 모으는 자리.

**계좌에 한 건도 안 보냅니다.** 부르는 자리를 지어 끼우고, 이어받기 키마다
무엇을 돌려줄지 시험이 정합니다.

줄 모양과 쪽 나뉨은 실측을 따릅니다 — 해외 분봉은 **날짜 인자를 안 보고** 늘
가장 최근 쪽을 내며, 과거로 가는 길은 `nxt_key` 하나입니다(`overseas_history.py`
첫머리). 그래서 시험도 날짜가 아니라 **키**로 쪽을 가릅니다.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.nh_api.client import ApiResult
from backend.nh_api.errors import BusinessError, TransportError
from backend.overseas_futureoption import overseas_futureoption_functions as api
from backend.overseas_futureoption import overseas_history as history
from backend.overseas_futureoption.overseas_routes import get_client

주소 = "/api/overseas/chart-history"
종목 = {"exch_cd": "FCME", "sym": "MESU26"}
첫키 = api.FIRST_PAGE


def _줄(biz: str, clock: str, ref: str = "", price: str = "7681.50") -> dict:
    """봉 한 줄. 칸 이름은 반입 기록 그대로입니다."""
    return {
        "occurs1_glb_biz_dt": biz,
        "occurs1_ref_dt": ref or biz,
        "occurs1_exch_tm": clock,
        "occurs1_open_pric": price,
        "occurs1_high_pric": price,
        "occurs1_low_pric": price,
        "occurs1_close_pric": price,
        "occurs1_cum_trd_qty": "1",
    }


def _쪽(*rows: dict, 다음키: str = "") -> dict:
    return {
        "sym": "MESU26",
        "exch_cd": "FCME",
        "nrec": f"{len(rows):04d}",
        "nxt_key": 다음키,
        "Occurs1": list(rows),
    }


class _키마다:
    """보낸 키마다 정해 둔 쪽을 내는 호출부. 안 정해 둔 키는 빈 쪽입니다."""

    def __init__(self, 쪽들: dict[str, dict], 터질키: set[str] | None = None):
        self.쪽들 = 쪽들
        self.터질키 = 터질키 or set()
        self.보낸키: list[str] = []
        self.보낸것: list[tuple[str, dict]] = []
        self.session = SimpleNamespace(
            config=SimpleNamespace(default_environment="paper"), is_replay=False
        )

    def call(self, api_id, payload, environment=None):
        키 = str(payload.get("nxt_key") or "")
        self.보낸키.append(키)
        self.보낸것.append((api_id, dict(payload)))
        if 키 in self.터질키:
            raise TransportError(api_id, "끊김")
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market="overseas",
            http_status=200,
            body=self.쪽들.get(키, _쪽()),
            headers={},
        )


@pytest.fixture
def 손님():
    def 세우기(쪽들, 터질키=None, 호출부=None):
        부르는것 = 호출부 if 호출부 is not None else _키마다(쪽들, 터질키)
        app.dependency_overrides[get_client] = lambda: 부르는것
        return TestClient(app), 부르는것

    try:
        yield 세우기
    finally:
        app.dependency_overrides.pop(get_client, None)


# ── 순수 함수 ───────────────────────────────────────────


def test_영업일을_줄에서_읽는다():
    쪽 = _쪽(_줄("20260923", "120000"), _줄("20260922", "230000"), _줄("20260922", "200000"))

    assert history.days_in(쪽) == [date(2026, 9, 22), date(2026, 9, 23)]
    assert history.latest_in(쪽) == date(2026, 9, 23)
    assert history.before_in([쪽], date(2026, 9, 23)) == date(2026, 9, 22)


def test_그_앞_영업일이_보이면_다_찬_것이다():
    쪽 = _쪽(_줄("20260923", "120000"), _줄("20260922", "230000"))

    assert history.has_older(쪽, date(2026, 9, 23)) is True
    assert history.has_older(쪽, date(2026, 9, 22)) is False, "더 걸어야 합니다."


def test_그_영업일_줄만_남긴다():
    """봉이 되기 전에 걸러야 합니다 — 봉의 시각은 달력 기준이라 뒤에는 못 가립니다."""
    쪽 = _쪽(_줄("20260923", "120000"), _줄("20260922", "230000"))

    남은것 = history.pick(쪽, date(2026, 9, 23))

    assert [one["occurs1_exch_tm"] for one in 남은것["Occurs1"]] == ["120000"]
    assert 남은것["sym"] == "MESU26", "나머지 칸은 원문 그대로입니다."


def test_커서와_낸_영업일을_한_칸에_담는다():
    값 = history.as_before("20260923030200999999", date(2026, 9, 23))

    assert 값 == "20260923030200999999@20260923"
    assert history.as_cursor(값) == ("20260923030200999999", date(2026, 9, 23))
    assert history.as_cursor("") == ("", None), "비면 가장 최근부터입니다."
    assert history.as_cursor("이상한값") == ("", None)


def test_키는_답이_준_것을_그대로_읽는다():
    assert history.next_key_of(_쪽(다음키="20260922184700999999")) == "20260922184700999999"
    assert history.next_key_of(_쪽()) == "" and history.next_key_of(None) == ""


# ── 걷기 ────────────────────────────────────────────────


def test_그_앞_영업일이_보일_때까지_걷는다(손님):
    """한 영업일이 세 쪽쯤이라, 한 쪽만 보고 끝내면 그 영업일의 앞부분이 빕니다."""
    앱, 호출부 = 손님(
        {
            첫키: _쪽(_줄("20260923", "120000"), 다음키="1001"),
            "1001": _쪽(_줄("20260923", "080000"), 다음키="1002"),
            "1002": _쪽(_줄("20260923", "070000"), _줄("20260922", "235900"), 다음키="1003"),
        }
    )

    답 = 앱.post(주소, json=종목).json()

    assert 호출부.보낸키 == [첫키, "1001", "1002"], "앞 영업일이 보이면 멈춥니다."
    assert len(답["bars"]) == 3, "세 쪽에서 그 영업일 줄만 모읍니다."
    assert 답["businessDay"] == "20260923"
    assert 답["partial"] is False
    assert 답["sessions"] == ["day"] and 답["nextKey"] == ""
    assert 답["before"] == "1002@20260923", "경계가 걸린 쪽부터 다시 걷습니다."


def test_다음_장은_경계_쪽부터_다시_걷는다(손님):
    """경계 쪽에는 두 영업일이 함께 있습니다. 그 쪽을 건너뛰면 **줄을 잃습니다.**"""
    앱, 호출부 = 손님(
        {
            "1002": _쪽(_줄("20260923", "070000"), _줄("20260922", "235900"), 다음키="1003"),
            "1003": _쪽(_줄("20260922", "200000"), _줄("20260921", "235900"), 다음키="1004"),
        }
    )

    답 = 앱.post(주소, json={**종목, "before": "1002@20260923"}).json()

    assert 호출부.보낸키 == ["1002", "1003"]
    assert 답["businessDay"] == "20260922"
    assert len(답["bars"]) == 2, "경계 쪽에 있던 줄(235900)이 빠지지 않습니다."
    assert 답["before"] == "1003@20260922"


def test_키를_지어내지_않는다(손님):
    """답이 준 값을 그대로 되돌려 보냅니다. 키의 속뜻은 확인하지 못했습니다."""
    앱, 호출부 = 손님(
        {
            첫키: _쪽(_줄("20260923", "120000"), 다음키="20260923030200999999"),
            "20260923030200999999": _쪽(
                _줄("20260923", "030000"), _줄("20260922", "235900"), 다음키="1009"
            ),
        }
    )

    답 = 앱.post(주소, json=종목).json()

    assert 호출부.보낸키 == [첫키, "20260923030200999999"]
    assert 답["before"] == "20260923030200999999@20260923"


# ── 못 받을 때 ──────────────────────────────────────────


def test_키가_더_안_나가면_알린다(손님):
    """다 찼는지 알 수 없습니다 — 「받은 만큼」이라고 적습니다."""
    앱, _ = 손님({첫키: _쪽(_줄("20260923", "120000"), 다음키="")})

    답 = 앱.post(주소, json=종목).json()

    assert 답["partial"] is True
    assert len(답["bars"]) == 1, "받은 것은 그대로 냅니다."
    assert 답["businessDay"] == "20260923"


def test_같은_키가_돌아와도_멈춘다(손님):
    """같은 자리를 되풀이해 부르지 않습니다. **다 찼는지는 알 수 없습니다.**"""
    앱, 호출부 = 손님(
        {
            첫키: _쪽(_줄("20260923", "120000"), 다음키="1002"),
            "1002": _쪽(_줄("20260923", "110000"), 다음키="1002"),
        }
    )

    답 = 앱.post(주소, json=종목).json()

    assert 호출부.보낸키 == [첫키, "1002"], "같은 자리를 다시 부르지 않습니다."
    assert 답["partial"] is True


def test_창의_아래끝이면_탈이_아니다(손님):
    """**키가 전부 9 면 더 과거가 없다는 뜻**입니다(실측). 못 받은 것이 아니라
    없는 것이라, 화면이 멈추도록 다음 장을 안 가리킵니다.
    """
    앱, 호출부 = 손님({첫키: _쪽(_줄("20260923", "120000"), 다음키="9" * 32)})

    답 = 앱.post(주소, json=종목).json()

    assert 호출부.보낸키 == [첫키], "창 끝을 보고 멈춥니다."
    assert 답["partial"] is False
    assert 답["before"] == "", "다음 장이 없습니다."
    assert len(답["bars"]) == 1, "받은 것은 그대로 냅니다."


def test_창의_아래끝을_넉넉히_잡는다(손님):
    """시작 날짜는 **창의 아래끝**입니다. 오늘로 두면 오늘 00:00 에서 걷기가
    끝나 앞 영업일로 못 갑니다.
    """
    from backend.overseas_futureoption import overseas_routes

    앱, 호출부 = 손님({첫키: _쪽(_줄("20260923", "120000"), 다음키="9" * 32)})

    앱.post(주소, json=종목)

    (_, 보낸것) = 호출부.보낸것[-1]
    오늘 = overseas_routes.now_kst().date()
    아래끝 = 오늘 - timedelta(days=history.WINDOW_DAYS)
    assert 보낸것["inq_strt_dt"] == history.as_text(아래끝)
    assert 보낸것["inq_ed_dt"] == history.as_text(오늘)


def _긴날(쪽수: int = 10) -> dict:
    """한 영업일이 쪽 상한을 넘는 종목. 경계가 한참 뒤에 있습니다."""
    return {
        (첫키 if 회차 == 0 else f"{1000 + 회차}"): _쪽(
            _줄("20260923", f"{12 - 회차:02d}0000"), 다음키=f"{1000 + 회차 + 1}"
        )
        for 회차 in range(쪽수)
    }


def test_쪽_상한은_탈이_아니다(손님):
    """한 번 누른 화면이 조회를 수십 건 내지 않게 끊습니다. **받은 만큼 내고
    다음 장이 같은 영업일을 이어 받습니다** — 못 받은 것이 아닙니다.
    """
    앱, 호출부 = 손님(_긴날())

    답 = 앱.post(주소, json=종목).json()

    assert len(호출부.보낸키) == 6, "쪽 상한에서 멈춥니다."
    assert 답["partial"] is False
    assert len(답["bars"]) == 6 and 답["businessDay"] == "20260923"
    assert 답["before"] == "1006@", "영업일 자리가 비면 「같은 영업일을 이어서」입니다."


def test_같은_영업일을_이어_받는다(손님):
    """다음 장이 같은 `businessDay` 로 옵니다. 화면은 이어 붙입니다."""
    앱, 호출부 = 손님(_긴날())

    답 = 앱.post(주소, json={**종목, "before": "1006@"}).json()

    assert 호출부.보낸키[0] == "1006", "끊긴 자리에서 이어 받습니다."
    assert 답["businessDay"] == "20260923", "같은 영업일입니다."
    assert 답["bars"], "앞 장에 못 담은 줄이 옵니다."


def test_걷다_못_받으면_받은_만큼_낸다(손님):
    앱, 호출부 = 손님(
        {첫키: _쪽(_줄("20260923", "120000"), 다음키="1001")},
        터질키={"1001"},
    )

    답 = 앱.post(주소, json=종목).json()

    assert 호출부.보낸키 == [첫키, "1001", "1001"], "한 번 더 봅니다."
    assert 답["partial"] is True and len(답["bars"]) == 1


def test_첫_조회_거절은_그대로_올린다(손님):
    """빈 답으로 감추면 화면이 「빈 영업일」로 읽고 더 뒤로 갑니다 — 못 받는
    거래소를 그렇게 지나치면 사용자는 까닭을 영영 못 봅니다.
    """
    앱, 호출부 = 손님({}, 터질키={첫키})

    답 = 앱.post(주소, json=종목)

    assert 답.status_code == 504
    assert 호출부.보낸키 == [첫키, 첫키], "한 번 더 보고 올립니다."
    assert "시세" in 답.json()["detail"]


def test_첫_조회_거부도_그대로_올린다(손님):
    class _거부하는곳(_키마다):
        def call(self, api_id, payload, environment=None):
            self.보낸키.append(str(payload.get("nxt_key") or ""))
            raise BusinessError(api_id, "EGW999", "거절", {})

    앱, _ = 손님({}, 호출부=_거부하는곳({}))

    답 = 앱.post(주소, json=종목)

    assert 답.status_code == 502


def test_한_줄도_없으면_빈_장이다(손님):
    """죽은 종목입니다. 영업일도 커서도 낼 것이 없습니다."""
    앱, _ = 손님({첫키: _쪽()})

    답 = 앱.post(주소, json=종목).json()

    assert 답["bars"] == [] and 답["businessDay"] == "" and 답["before"] == ""
    assert 답["partial"] is False, "빈 것은 못 받은 것이 아닙니다."


def test_나쁜_값은_받지_않는다(손님):
    앱, _ = 손님({})

    assert 앱.post(주소, json={**종목, "before": "20260923"}).status_code == 422
    assert 앱.post(주소, json={**종목, "before": "키@20260923"}).status_code == 422
    assert 앱.post(주소, json={**종목, "dcnt": "열"}).status_code == 422
