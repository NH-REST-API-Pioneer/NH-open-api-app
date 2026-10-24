"""종목 마스터·거래시간표의 하루 한 번 갱신.

가짜 시계와 가짜 받기로만 봅니다 — 이 시험은 바깥으로 나가지 않습니다.
2026-10-12 는 월요일입니다.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.master import master_daily, master_service
from backend.master.master_daily import DailyRefresh
from backend.master.master_download import DownloadResult
from backend.master.master_files import MASTER_FILES, MASTER_FILES_BY_NAME
from backend.master.master_parser import MasterTable
from backend.master.master_routes import get_daily, get_service, replaying
from backend.master.master_service import MasterService, published_on
from backend.master.master_store import LoadedMaster, save_master
from backend.sessions.hours import KST
from tests.fixtures.master import fixture_text

_MASTERS = ("fut_opt", "stk_fut_opt", "idx_fut_opt", "cme_fut", "cme_opt",
            "etc_fut", "etc_opt", "opra_opt", "lme_fut")

어제것 = date(2026, 10, 8)
오늘 = date(2026, 10, 12)


def 시각(일: int, 시: int, 분: int = 0) -> datetime:
    return datetime(2026, 10, 일, 시, 분, tzinfo=KST)


class 가짜마스터:
    """`MasterService` 가운데 갱신이 쓰는 두 가지(`published`, `refresh`)만 흉내 냅니다."""

    def __init__(self, published: date | None = 어제것) -> None:
        self.published = published
        self.불린 = []
        #: 받으면 이 배포일이 됩니다. `None` 이면 배포일이 그대로입니다(전날 파일).
        self.받으면: date | None = None
        #: "ok", "fail", "raise", "busy"
        self.결과 = "ok"
        self.오늘날짜 = 오늘

    def refresh(self, *, force: bool = False):
        self.불린.append(force)
        if self.결과 == "raise":
            raise RuntimeError("받다가 터짐")
        if self.결과 == "busy":
            return []
        if self.결과 == "fail":
            return [DownloadResult(MASTER_FILES[0], None, "끊겼습니다")]
        if self.받으면 is not None:
            self.published = self.받으면
        return [DownloadResult(MASTER_FILES[0], Path("x"), None)]


def 갱신(마스터, *, 재생=False, 시간표=None):
    시간표 = 시간표 if 시간표 is not None else []
    return DailyRefresh(
        마스터,
        refresh_sessions=lambda: 시간표.append("sessions"),
        replaying=lambda: 재생,
        clock=lambda: 시각(12, 7, 20),
    )


# ── (ㄱ) 예정 시각이 지나면 한 번 받고 같은 날 다시 안 함 ──────────────


def test_예정_시각_전에는_받지_않는다():
    마스터 = 가짜마스터()
    작업 = 갱신(마스터)

    assert 작업.tick(시각(12, 7, 19)) is False
    assert 마스터.불린 == []
    assert 작업.next_at(시각(12, 7, 19)) == 시각(12, 7, 20)


def test_예정_시각이_지나면_한_번_받고_같은_날은_다시_안_받는다():
    마스터 = 가짜마스터()
    마스터.받으면 = 오늘
    시간표 = []
    작업 = 갱신(마스터, 시간표=시간표)

    assert 작업.tick(시각(12, 7, 20)) is True
    assert 마스터.불린 == [True], "오늘 폴더가 차 있어도 다시 받아야 합니다(force)."
    assert 시간표 == ["sessions"]

    for 그때 in (시각(12, 7, 21), 시각(12, 9, 0), 시각(12, 11, 59), 시각(12, 23, 0)):
        assert 작업.tick(그때) is False
    assert 마스터.불린 == [True]
    assert 시간표 == ["sessions"]
    assert 작업.next_at(시각(12, 9, 0)) == 시각(13, 7, 20)


def test_다음_날_예정_시각에_다시_받는다():
    마스터 = 가짜마스터()
    마스터.받으면 = 오늘
    작업 = 갱신(마스터)
    작업.tick(시각(12, 7, 20))

    마스터.받으면 = date(2026, 10, 13)
    assert 작업.tick(시각(13, 7, 19)) is False
    assert 작업.tick(시각(13, 7, 20)) is True
    assert 마스터.불린 == [True, True]


def test_이미_오늘_목록이면_받지_않는다():
    """오늘 켠 서버는 뜰 때 오늘 것을 받았습니다 — 그날은 다시 받지 않습니다."""
    마스터 = 가짜마스터(published=오늘)
    작업 = 갱신(마스터)

    assert 작업.tick(시각(12, 7, 20)) is False
    assert 작업.tick(시각(12, 10, 0)) is False
    assert 마스터.불린 == []
    assert 작업.next_at(시각(12, 7, 20)) == 시각(13, 7, 20)


def test_예정_시각_뒤에_켠_서버는_곧바로_받는다():
    마스터 = 가짜마스터()
    마스터.받으면 = 오늘
    작업 = 갱신(마스터)

    assert 작업.next_at(시각(12, 9, 30)) == 시각(12, 7, 20)
    assert 작업.tick(시각(12, 9, 30)) is True
    assert 마스터.불린 == [True]


def test_주말에는_받지_않는다():
    마스터 = 가짜마스터()
    마스터.받으면 = date(2026, 10, 17)
    작업 = 갱신(마스터)

    assert 작업.tick(시각(17, 7, 20)) is False  # 토요일
    assert 작업.tick(시각(18, 9, 0)) is False  # 일요일
    assert 마스터.불린 == []
    assert 작업.next_at(시각(17, 7, 20)) == 시각(19, 7, 20)


def test_저장해_둔_응답으로_도는_중에는_마스터를_받지_않는다():
    마스터 = 가짜마스터()
    시간표 = []
    작업 = 갱신(마스터, 재생=True, 시간표=시간표)

    assert 작업.tick(시각(12, 7, 20)) is True
    assert 마스터.불린 == []
    assert 시간표 == ["sessions"], "시간표는 뜰 때와 같이 받습니다."
    assert 작업.tick(시각(12, 7, 50)) is False


# ── (ㄴ) 실패해도 멈추지 않고 다시, 안 되면 다음 날 ──────────────────


@pytest.mark.parametrize("결과", ["fail", "raise", "busy"])
def test_실패하면_30분_뒤에_다시_가_본다(결과):
    마스터 = 가짜마스터()
    마스터.결과 = 결과
    작업 = 갱신(마스터)

    assert 작업.tick(시각(12, 7, 20)) is True, "실패를 밖으로 올리지 않습니다."
    assert 작업.next_at(시각(12, 7, 21)) == 시각(12, 7, 50)
    assert 작업.tick(시각(12, 7, 49)) is False

    마스터.결과 = "ok"
    마스터.받으면 = 오늘
    assert 작업.tick(시각(12, 7, 50)) is True
    assert len(마스터.불린) == 2
    assert 작업.next_at(시각(12, 8, 0)) == 시각(13, 7, 20)


def test_받았는데_전날_파일이면_다시_가_본다():
    """NH선물이 아직 오늘 파일을 올리지 않았으면 전날 것이 옵니다."""
    마스터 = 가짜마스터()
    작업 = 갱신(마스터)

    작업.tick(시각(12, 7, 20))

    assert 마스터.published == 어제것
    assert 작업.next_at(시각(12, 7, 30)) == 시각(12, 7, 50)


def test_정오까지_못_받으면_그날은_그만두고_다음_평일에_다시(caplog):
    마스터 = 가짜마스터()
    마스터.결과 = "fail"
    작업 = 갱신(마스터)

    지금 = 시각(12, 7, 20)
    with caplog.at_level(logging.WARNING, logger="backend.master.master_daily"):
        while 지금.date() == 오늘 and 작업.next_at(지금).date() == 오늘:
            지금 = max(지금, 작업.next_at(지금))
            assert 작업.tick(지금) is True

    # 07:20 부터 30분마다 11:50 까지 — 열 번.
    assert len(마스터.불린) == 10
    assert 작업.next_at(시각(12, 11, 55)) == 시각(13, 7, 20)
    assert 작업.tick(시각(12, 15, 0)) is False
    경고 = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(경고) == 1, "그만둘 때 한 줄만 남깁니다."

    마스터.결과 = "ok"
    마스터.받으면 = date(2026, 10, 13)
    assert 작업.tick(시각(13, 7, 20)) is True
    assert 마스터.published == date(2026, 10, 13)


def test_시간표_받기가_터져도_마스터는_받는다():
    마스터 = 가짜마스터()
    마스터.받으면 = 오늘

    def 터지는시간표():
        raise RuntimeError("시간표 실패")

    작업 = DailyRefresh(마스터, refresh_sessions=터지는시간표, replaying=lambda: False)

    assert 작업.tick(시각(12, 7, 20)) is True
    assert 마스터.불린 == [True]
    assert 마스터.published == 오늘


def test_배포일을_모르는_마스터는_받은_것으로_끝낸다():
    """국내 마스터가 없으면 배포일을 셀 수 없습니다. 받은 것을 그대로 쓰고 끝냅니다."""
    마스터 = 가짜마스터(published=None)
    작업 = 갱신(마스터)

    assert 작업.tick(시각(12, 7, 20)) is True
    assert 작업.tick(시각(12, 7, 50)) is False
    assert 작업.next_at(시각(12, 8, 0)) == 시각(13, 7, 20)


def test_반복은_예정_시각까지_짧게_끊어_자고_받는다(monkeypatch):
    마스터 = 가짜마스터()
    마스터.받으면 = 오늘
    작업 = 갱신(마스터)
    잔시간 = []

    async def 가짜잠(초):
        잔시간.append(초)
        raise asyncio.CancelledError

    monkeypatch.setattr(master_daily.asyncio, "sleep", 가짜잠)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(작업.run())

    assert 마스터.불린 == [True]
    assert 잔시간 == [master_daily.POLL_SECONDS]


# ── (ㄷ) 바꿔 끼우는 동안 종목 조회가 끊기지 않음 ─────────────────────


def _채우기(자리: Path, stamp: str = "20260902") -> None:
    for 이름 in _MASTERS:
        save_master(
            MASTER_FILES_BY_NAME[이름],
            fixture_text(이름).encode("utf-8"),
            stamp=stamp,
            base_dir=자리,
        )


def _국내종목(서비스: MasterService) -> str:
    표 = 서비스._index.tables["fut_opt"]
    return 표.rows[0][표.index_of("series")]


def test_새_색인을_만드는_동안에도_앞의_목록으로_답한다(tmp_path, monkeypatch):
    서비스 = MasterService(tmp_path)
    _채우기(tmp_path)
    서비스.reload()
    코드 = _국내종목(서비스)
    앞색인 = 서비스.index()
    본것 = []

    원래 = master_service.build_index

    def 지켜보며_만들기(loaded, **kwargs):
        # 새 색인을 만드는 한가운데에서 묻습니다.
        본것.append((서비스.locate("domestic", 코드), 서비스.index(), 서비스.available))
        return 원래(loaded, **kwargs)

    def 가짜받기(base_dir=None, *, force=False, **_):
        _채우기(base_dir, stamp="20260903")
        return [DownloadResult(MASTER_FILES[0], Path("x"), None)]

    monkeypatch.setattr(master_service, "build_index", 지켜보며_만들기)
    monkeypatch.setattr(master_service, "download_all", 가짜받기)

    서비스.refresh(force=True)

    assert len(본것) == 1
    줄, 색인, 있음 = 본것[0]
    assert 줄 is not None and 색인 is 앞색인 and 있음 is True
    assert 서비스.locate("domestic", 코드) is not None
    assert 서비스.index() is not 앞색인, "다 만든 뒤에는 새 색인으로 바뀝니다."
    assert 서비스.status()["dates"] == ["20260903"]


def test_색인을_만들다_실패하면_앞의_목록을_그대로_쓴다(tmp_path, monkeypatch):
    서비스 = MasterService(tmp_path)
    _채우기(tmp_path)
    서비스.reload()
    코드 = _국내종목(서비스)
    앞색인 = 서비스.index()

    def 터지는색인(loaded, **kwargs):
        raise RuntimeError("색인 실패")

    monkeypatch.setattr(master_service, "build_index", 터지는색인)

    with pytest.raises(RuntimeError):
        서비스.reload()

    assert 서비스.index() is 앞색인
    assert 서비스.locate("domestic", 코드) is not None
    assert 서비스.status()["stage"] == master_service.READY


def test_다른_스레드가_묻는_동안_여러_번_바꿔_끼워도_비지_않는다(tmp_path):
    서비스 = MasterService(tmp_path)
    _채우기(tmp_path)
    서비스.reload()
    코드 = _국내종목(서비스)
    끝 = threading.Event()
    빈답 = []
    물은수 = [0]

    def 계속묻기():
        while not 끝.is_set():
            물은수[0] += 1
            if 서비스.locate("domestic", 코드) is None or 서비스.index() is None:
                빈답.append(물은수[0])

    묻는쪽 = threading.Thread(target=계속묻기)
    묻는쪽.start()
    try:
        for _ in range(3):
            서비스.reload()
    finally:
        끝.set()
        묻는쪽.join()

    assert 물은수[0] > 0
    assert 빈답 == []


# ── 배포일과 상태 칸 ──────────────────────────────────────────────────


def _국내표(*줄: tuple[str, str]) -> LoadedMaster:
    표 = MasterTable("fut_opt", "domestic", ("series", "exp_ym", "rem_cnt"),
                    tuple(("A", 만기, 남은) for 만기, 남은 in 줄))
    return LoadedMaster(MASTER_FILES_BY_NAME["fut_opt"], "20261012", 표, None)


def test_배포일은_만기일에서_잔존일수를_거슬러_센다():
    # 만기 당일이 1 입니다. 다른 기준의 줄 하나가 섞여도 가장 많은 날을 답합니다.
    loaded = [_국내표(("20261012", "1"), ("20261015", "4"), ("20261112", "32"),
                     ("20261015", "3"), ("2026", "1"), ("20261015", ""))]

    assert published_on(loaded) == 오늘


def test_국내_마스터가_없으면_배포일은_모름():
    해외 = MasterTable("cme_fut", "overseas", ("code",), (("X",),))
    loaded = [LoadedMaster(MASTER_FILES_BY_NAME["cme_fut"], "20261012", 해외, None)]

    assert published_on(loaded) is None
    assert published_on([]) is None


def test_상태에_마지막_갱신과_다음_예정_시각이_있다(tmp_path):
    서비스 = MasterService(tmp_path)
    작업 = DailyRefresh(서비스, refresh_sessions=lambda: None, replaying=lambda: False,
                      clock=lambda: 시각(12, 8, 0))
    app.dependency_overrides[get_service] = lambda: 서비스
    app.dependency_overrides[get_daily] = lambda: 작업
    app.dependency_overrides[replaying] = lambda: False
    try:
        http = TestClient(app)
        비었을때 = http.get("/api/master/status").json()
        _채우기(tmp_path)
        서비스.reload()
        채운뒤 = http.get("/api/master/status").json()
    finally:
        for 열쇠 in (get_service, get_daily, replaying):
            app.dependency_overrides.pop(열쇠, None)

    assert 비었을때["refreshed_at"] is None
    assert 비었을때["published"] is None
    # 배포일을 모르면 아직 오늘 할 일이 남은 것으로 봅니다 — 이미 지난 07:20 이 예정입니다.
    assert 비었을때["next_refresh_at"] == "2026-10-12T07:20:00+09:00"

    assert 채운뒤["refreshed_at"] is not None
    assert 채운뒤["published"] == 서비스.published.isoformat()
    assert 채운뒤["published"] < "2026-10-12"
