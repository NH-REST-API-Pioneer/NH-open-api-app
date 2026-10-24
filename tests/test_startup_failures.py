"""앱을 켤 때의 실패 — 읽기를 두 번 하지 않고, 망이 끊긴 것은 한 줄로 남깁니다.

시작하면 거래시간표 두 벌과 종목 마스터를 받습니다. 망이 잠깐 끊겨 있어도 앱은
내장 표와 받아 둔 파일로 이어서 뜨는데, 그때 기록이 트레이스백 세 벌로 차면
잠깐의 끊김이 큰 사고처럼 보입니다.

**어떤 시험도 밖으로 나가지 않습니다.** 내려받기는 흉내 낸 실패로, 시간표는 받는
자리를 바꿔 끼워 봅니다.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pytest

from backend.master import master_download as 받기
from backend.master import master_service as master_module
from backend.master.master_download import DownloadResult, MasterDownloadError
from backend.master.master_files import MASTER_FILES, MASTER_FILES_BY_NAME
from backend.master.master_service import MasterService
from backend.master.master_store import save_master
from backend.net_failure import cannot_connect, unreachable
from backend.nh_api.errors import BusinessError, TransportError
from backend.sessions import service as session_module
from backend.sessions.hours import KST
from backend.sessions.service import DOMESTIC, OVERSEAS, SessionService
from tests.fixtures.master import fixture_text

_MASTERS = ("fut_opt", "stk_fut_opt", "idx_fut_opt", "cme_fut", "cme_opt",
            "etc_fut", "etc_opt", "opra_opt", "lme_fut")

#: 이름 풀이가 안 될 때 실제로 오는 글자입니다.
_이름풀이실패 = "[Errno 11001] getaddrinfo failed"


def _닿지못함(message: str = _이름풀이실패) -> httpx.ConnectError:
    return httpx.ConnectError(message, request=httpx.Request("GET", "https://example.invalid"))


def _파일을_둔다(made: MasterService) -> None:
    for name in _MASTERS:
        save_master(
            MASTER_FILES_BY_NAME[name],
            fixture_text(name).encode("utf-8"),
            stamp="20260902",
            base_dir=made.base_dir,
        )


def _읽기를_센다(made: MasterService, monkeypatch) -> list[int]:
    """`reload()` 가 몇 번 불렸는지 세는 자리. 진짜 읽기는 그대로 합니다."""
    센것: list[int] = []
    진짜 = made.reload

    def 세면서_읽는다() -> None:
        센것.append(1)
        진짜()

    monkeypatch.setattr(made, "reload", 세면서_읽는다)
    return 센것


def _받기를_바꾼다(monkeypatch, 하는일) -> None:
    monkeypatch.setattr(master_module, "download_all", 하는일)


def _끊긴_망으로_받게_한다(monkeypatch) -> list[str]:
    """받는 자리는 그대로 두고 **전송만** 끊습니다. 가 본 주소를 모아 돌려줍니다.

    `download_all` 을 흉내 내지 않습니다 — 파일별로 잡아 결과로 바꾸는 자리까지
    실물 그대로 돌아야 기록에 몇 줄이 남는지 잴 수 있습니다.
    """
    가_본_곳: list[str] = []

    def 닿지_못한다(request: httpx.Request) -> httpx.Response:
        가_본_곳.append(str(request.url))
        raise httpx.ConnectError(_이름풀이실패, request=request)

    진짜 = master_module.download_all

    def 받는다(base_dir=None, **덮어쓰기):
        with httpx.Client(transport=httpx.MockTransport(닿지_못한다)) as 전송:
            return 진짜(base_dir, client=전송, **덮어쓰기)

    monkeypatch.setattr(master_module, "download_all", 받는다)
    return 가_본_곳


def _터진다(exc: Exception):
    """무엇으로 부르든 그 예외를 일으키는 자리."""

    def 하는일(*args, **kwargs):
        raise exc

    return 하는일


# ── 닿지 못한 실패 가리기 ────────────────────────────────────


def test_닿지_못한_실패만_한_줄로_본다():
    assert unreachable(_닿지못함())
    assert unreachable(httpx.ConnectTimeout("시간 초과"))
    assert unreachable(TransportError("overseas_price", "끊김"))
    # 감싸 올린 것도 원인 사슬로 봅니다.
    감싼것 = MasterDownloadError("못 받았습니다")
    감싼것.__cause__ = _닿지못함()
    assert unreachable(감싼것)

    # 서버가 답은 했는데 거절한 것은 닿은 것입니다.
    assert not unreachable(BusinessError("overseas_price", "EGW001", "거절", {}))
    assert not unreachable(RuntimeError("어딘가 터짐"))
    assert not unreachable(None)


def test_다시_걸어_볼지는_더_좁게_가린다():
    """기록을 줄일지(`unreachable`)와 포기할지(`cannot_connect`)는 다른 물음입니다."""
    # 연결 자체가 안 선 것 — 다시 걸어도 같습니다.
    for 안_선것 in (_닿지못함(), httpx.ConnectTimeout("연결 시간 초과")):
        assert unreachable(안_선것) and cannot_connect(안_선것)

    # 받는 도중 멈추거나 끊긴 것 — 기록은 한 줄로 줄이되 다시 걸어 봅니다.
    for 도중에 in (
        httpx.ReadTimeout("받다 멈춤"),
        httpx.ReadError("받다 끊김"),
        httpx.RemoteProtocolError("서버가 끊음"),
    ):
        assert unreachable(도중에) and not cannot_connect(도중에)

    # 이 앱의 예외가 감싼 것도 원인 사슬로 봅니다.
    감싼것 = TransportError("overseas_price", "끊김")
    감싼것.__cause__ = _닿지못함()
    assert cannot_connect(감싼것)
    # 감쌀 원인이 없으면 연결이 안 선 것이라고 단정하지 않습니다.
    assert not cannot_connect(TransportError("overseas_price", "토큰을 준비하지 못했습니다"))
    assert not cannot_connect(None)


def test_접속이_끊긴_김에_드러난_다른_문제는_한_줄로_덮지_않는다():
    """`raise … from …` 으로 감싼 것만 봅니다 — 그 밖은 원인을 알아야 고칩니다."""
    try:
        try:
            raise _닿지못함()
        except httpx.ConnectError:
            raise ValueError("다른 문제")
    except ValueError as exc:
        assert exc.__context__ is not None and exc.__cause__ is None
        assert not unreachable(exc)


# ── 종목 마스터 ──────────────────────────────────────────────


def test_받아_온_파일이_없으면_다시_읽지_않는다(tmp_path, monkeypatch):
    """시작할 때 이미 한 번 읽습니다(`backend.main`). 받은 것이 없으면 그것으로 충분합니다."""
    made = MasterService(tmp_path)
    _파일을_둔다(made)
    made.reload()
    센것 = _읽기를_센다(made, monkeypatch)

    # 오늘 받아 둔 것이 이미 있어 내려받지 않은 경우입니다.
    _받기를_바꾼다(monkeypatch, lambda *a, **k: [])
    made.refresh()

    assert 센것 == []
    assert made.available and made.status()["stage"] == "ready"
    assert not made.busy


def test_받아_온_파일이_있으면_한_번_읽는다(tmp_path, monkeypatch):
    made = MasterService(tmp_path)
    _파일을_둔다(made)
    made.reload()
    센것 = _읽기를_센다(made, monkeypatch)

    받은것 = [DownloadResult(MASTER_FILES_BY_NAME["fut_opt"], tmp_path / "fut_opt.mst", None)]
    _받기를_바꾼다(monkeypatch, lambda *a, **k: 받은것)
    assert made.refresh() == 받은것

    assert 센것 == [1]


def test_한_번도_안_읽었으면_받기에_실패해도_읽는다(tmp_path, monkeypatch):
    """받아 둔 파일이 있는데 색인이 비어 있으면 화면에 내놓을 것이 없습니다."""
    made = MasterService(tmp_path)
    _파일을_둔다(made)
    센것 = _읽기를_센다(made, monkeypatch)

    _끊긴_망으로_받게_한다(monkeypatch)
    made.refresh()

    assert 센것 == [1]
    assert made.available


def test_망이_끊겨_있으면_경고_한_줄로_끝난다(tmp_path, monkeypatch, caplog):
    """**받는 자리를 바꿔 끼우지 않고 실물 경로를 그대로 탑니다** — 전송만 끊어 둡니다."""
    made = MasterService(tmp_path)
    _파일을_둔다(made)
    made.reload()
    센것 = _읽기를_센다(made, monkeypatch)

    가_본_곳 = _끊긴_망으로_받게_한다(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger=받기.__name__):
        받은것 = made.refresh()

    남긴것 = [기록 for 기록 in caplog.records if 기록.name == 받기.__name__]
    (경고,) = [기록 for 기록 in 남긴것 if 기록.levelno == logging.WARNING]
    assert not 경고.exc_info
    assert "종목 마스터를 받지 못했습니다" in 경고.message
    assert "받아 둔 파일로 화면을 세웁니다" in 경고.message
    # 다시 걸어 보지 않고, 남은 파일도 가 보지 않습니다 — 주소 하나에 한 번뿐.
    assert 가_본_곳 == [MASTER_FILES[0].url]
    assert [기록 for 기록 in 남긴것 if 기록.levelno == logging.INFO] == []
    # 파일별 사유는 남되 기록에 파묻지 않습니다.
    assert len([기록 for 기록 in 남긴것 if 기록.levelno == logging.DEBUG]) == len(MASTER_FILES)

    # 아홉 개 다 실패로 오고, 받은 것이 없으니 다시 읽지 않습니다.
    assert len(받은것) == len(MASTER_FILES) and not any(하나.ok for 하나 in 받은것)
    assert 센것 == []
    assert made.available and made.status()["stage"] == "ready" and not made.busy


def test_받는_중에_다른_문제가_생기면_트레이스백을_남긴다(tmp_path, monkeypatch, caplog):
    made = MasterService(tmp_path)
    _파일을_둔다(made)
    made.reload()

    _받기를_바꾼다(monkeypatch, _터진다(OSError("디스크가 가득 찼습니다")))
    with caplog.at_level(logging.WARNING, logger=master_module.__name__):
        made.refresh()

    (남긴것,) = [기록 for 기록 in caplog.records if 기록.name == master_module.__name__]
    assert 남긴것.exc_info


# ── 거래시간표 ───────────────────────────────────────────────


@pytest.fixture
def 시간표(monkeypatch):
    made = SessionService()
    monkeypatch.setattr(session_module, "service", made)
    return made


def test_시간표를_못_받으면_무엇으로_대신하는지_적는다(시간표, caplog):
    시간표._fetch = _터진다(TransportError("overseas_market-operations", _이름풀이실패))  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger=session_module.__name__):
        시간표.refresh_all()

    남긴것 = [기록 for 기록 in caplog.records if 기록.name == session_module.__name__]
    assert len(남긴것) == 2, "시장 두 벌이 한 줄씩입니다."
    for 기록 in 남긴것:
        assert not 기록.exc_info, "닿지 못한 것에 트레이스백을 남기지 않습니다."
        assert "받지 못했습니다" in 기록.message
    assert "내장 표로 판정합니다" in 남긴것[0].message
    assert "「모름」으로 답합니다" in 남긴것[1].message


def test_시간표도_닿은_뒤의_실패는_트레이스백을_남긴다(시간표, caplog):
    시간표._fetch = _터진다(ValueError("응답을 읽지 못했습니다"))  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger=session_module.__name__):
        시간표.refresh_all()

    남긴것 = [기록 for 기록 in caplog.records if 기록.name == session_module.__name__]
    assert 남긴것 and all(기록.exc_info for 기록 in 남긴것)


def test_받아_둔_표를_쓸_때도_한_줄이다(시간표, caplog):
    아침 = datetime(2026, 9, 16, 9, tzinfo=KST)
    시간표._fetch = lambda market, api: {"products": []}  # type: ignore[method-assign]
    처음 = 시간표.table(DOMESTIC, now=아침)

    시간표._fetch = _터진다(TransportError("domestic_product-detail", _이름풀이실패))  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger=session_module.__name__):
        다음날 = 시간표.table(DOMESTIC, now=datetime(2026, 9, 17, 9, tzinfo=KST))

    assert 다음날 is 처음
    (남긴것,) = [기록 for 기록 in caplog.records if 기록.name == session_module.__name__]
    assert not 남긴것.exc_info
    assert "받아 둔 표를 그대로 씁니다" in 남긴것.message
    assert 시간표.cached(OVERSEAS) is None
