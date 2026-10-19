"""마스터 내려받기.

**실제 주소로 나가는 HTTP GET 한 줄은 이 시험이 보내지 않습니다** — 시험은 바깥에
나가지 않습니다. 그 한 줄을 뺀 나머지(압축 풀기 · 날짜 폴더 저장 · 실패 처리 ·
다시 받지 않기)는 배포된 실물과 같은 모양의 응답을 만들어 확인합니다.
"""
import gzip
import logging

import httpx
import pytest

from backend.master.master_download import (
    MasterDownloadError,
    download_all,
    fetch_one,
    unpack,
)
from backend.master.master_files import MASTER_FILES, MASTER_FILES_BY_NAME
from backend.master.master_store import has_all_files, load_all
from tests.fixtures.master import fixture_text


#: 기록을 몇 줄 남기는지 볼 때 거르는 이름.
_DOWNLOAD_LOGGER = "backend.master.master_download"


def _server(handler):
    """배포 주소를 흉내 내는 연결. 실제로 나가지 않습니다."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _serve_fixture(request: httpx.Request) -> httpx.Response:
    name = request.url.path.rsplit("/", 1)[-1].removesuffix(".mst.gz")
    return httpx.Response(200, content=gzip.compress(fixture_text(name).encode("utf-8")))


def test_받은_gz를_풀어_날짜_폴더에_쓰고_그대로_읽힌다(tmp_path):
    with _server(_serve_fixture) as client:
        results = download_all(tmp_path, stamp="20260902", client=client)

    assert len(results) == 9
    assert all(item.ok for item in results)
    assert has_all_files("20260902", tmp_path)

    # 저장된 것은 푼 상태입니다. 그대로 파싱까지 됩니다.
    saved = (tmp_path / "20260902" / "fut_opt.mst").read_text(encoding="utf-8")
    assert saved.startswith("4;F;1;KOSPI;")

    loaded = {item.master.name: item for item in load_all(tmp_path)}
    assert loaded["fut_opt"].table is not None
    assert len(loaded["fut_opt"].table) == 8


def test_주소는_배포된_그대로다():
    """URL 목록에 적힌 주소를 그대로 씁니다."""
    assert MASTER_FILES_BY_NAME["fut_opt"].url == (
        "https://apidev.futures.co.kr/guide/master/fut_opt.mst.gz"
    )
    assert len(MASTER_FILES) == 9


def test_오늘_것이_다_있으면_받지_않는다(tmp_path):
    """종목 목록은 하루에 한 번 바뀌므로 켤 때마다 다시 받을 이유가 없습니다."""
    with _server(_serve_fixture) as client:
        download_all(tmp_path, stamp="20260902", client=client)

    def must_not_be_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("이미 다 받아 두었는데 다시 받았습니다")

    with _server(must_not_be_called) as client:
        assert download_all(tmp_path, stamp="20260902", client=client) == []


def test_다시_받기는_다_있어도_받는다(tmp_path):
    with _server(_serve_fixture) as client:
        download_all(tmp_path, stamp="20260902", client=client)

    calls = []

    def count_and_serve(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _serve_fixture(request)

    with _server(count_and_serve) as client:
        download_all(tmp_path, stamp="20260902", force=True, client=client)

    assert len(calls) == 9


def test_하나가_실패해도_나머지는_받는다(tmp_path):
    """실패한 파일만 옛것을 쓰면 됩니다. 여기서 멈추면 받을 수 있던 것까지 못 씁니다."""

    def block_one(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("cme_opt.mst.gz"):
            return httpx.Response(500)
        return _serve_fixture(request)

    with _server(block_one) as client:
        results = download_all(tmp_path, stamp="20260902", client=client)

    failures = [item for item in results if not item.ok]
    assert [item.master.name for item in failures] == ["cme_opt"]
    assert (tmp_path / "20260902" / "fut_opt.mst").is_file()
    assert not (tmp_path / "20260902" / "cme_opt.mst").is_file()


def test_실패하면_한_번만_다시_시도한다():
    """무한히 다시 걸지 않습니다. 서버가 닫혀 있으면 옛것으로 화면을 세우는 편이 낫습니다."""
    attempts = []

    def always_fail(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        return httpx.Response(500, request=request)

    with _server(always_fail) as client:
        with pytest.raises(MasterDownloadError):
            fetch_one(client, MASTER_FILES_BY_NAME["fut_opt"])

    assert len(attempts) == 2


def test_닿지도_못하면_다시_시도하지_않는다():
    """이름 풀이가 안 되면 다시 걸어도 같습니다. 앱이 뜨는 시간만 늦어집니다."""
    attempts = []

    def unreachable_host(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)

    with _server(unreachable_host) as client:
        with pytest.raises(MasterDownloadError):
            fetch_one(client, MASTER_FILES_BY_NAME["fut_opt"])

    assert len(attempts) == 1


def test_받는_도중_멈추면_다시_걸고_나머지_파일도_받는다(tmp_path, caplog):
    """연결은 섰던 것이라 포기할 자리가 아닙니다 — 하나가 멈춰도 나머지는 그대로 갑니다."""
    attempts = []

    def stalls(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ReadTimeout("받는 중에 멈췄습니다", request=request)

    with _server(stalls) as client:
        with caplog.at_level(logging.DEBUG, logger=_DOWNLOAD_LOGGER):
            results = download_all(tmp_path, stamp="20260902", client=client)

    # 파일마다 처음 한 번에 다시 한 번. 아홉 개를 다 가 봅니다.
    assert len(attempts) == 2 * len(MASTER_FILES)
    assert len(results) == 9 and not any(item.ok for item in results)

    남긴것 = [기록 for 기록 in caplog.records if 기록.name == _DOWNLOAD_LOGGER]
    경고 = [기록 for 기록 in 남긴것 if 기록.levelno == logging.WARNING]
    # 파일별로 남고, 「받아 둔 파일로 화면을 세웁니다」 한 줄 갈래는 안 탑니다.
    assert len(경고) == len(MASTER_FILES)
    assert all("받아 둔 파일로" not in 기록.message for 기록 in 경고)
    assert len([기록 for 기록 in 남긴것 if 기록.levelno == logging.INFO]) == len(MASTER_FILES)


def test_닿지도_못하면_남은_파일은_가_보지_않는다(tmp_path):
    """아홉 개가 한 주소에서 옵니다 — 하나가 못 닿으면 나머지도 같은 결과입니다.

    기록에 무엇이 남는지는 `tests/test_startup_failures.py` 가 봅니다.
    """
    attempts = []

    def unreachable_host(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)

    with _server(unreachable_host) as client:
        results = download_all(tmp_path, stamp="20260902", client=client)

    assert len(attempts) == 1, "첫 파일에 한 번 가 보고 끝입니다."
    assert len(results) == 9 and not any(item.ok for item in results)
    assert all("getaddrinfo failed" in str(item.error) for item in results)


def test_압축이_깨졌으면_알린다():
    """받다가 끊기면 내용이 아니라 조각이 옵니다."""
    with pytest.raises(MasterDownloadError) as raised:
        unpack("gz 가 아닌 내용".encode("utf-8"), name="fut_opt.mst")

    assert "압축" in str(raised.value)


def test_받고_나면_오래된_날짜_폴더를_정리한다(tmp_path):
    for stamp in ("20260828", "20260829", "20260830", "20260831"):
        (tmp_path / stamp).mkdir(parents=True)

    with _server(_serve_fixture) as client:
        download_all(tmp_path, stamp="20260902", client=client)

    remaining = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert remaining == ["20260830", "20260831", "20260902"]
