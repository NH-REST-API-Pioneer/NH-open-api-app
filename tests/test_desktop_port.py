"""화면을 여는 포트 — 지난번 포트를 먼저 쓰고, 막혀 있으면 새 포트.

**창도 서버도 띄우지 않습니다.** 포트가 비었는지는 소켓을 붙여 보기만 하고, 「사용 중」은
시험 안에서 소켓을 잡아 두어 만듭니다. 기억 파일은 시험마다 임시 폴더에 둡니다.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from desktop import main as desktop_main
from desktop import notify


#: 비어 있는 포트로 시험할 때 몇 번까지 다시 해 보는지.
TRIES = 5


def _빈_포트() -> int:
    """지금 비어 있는 포트.

    Windows 는 운영체제가 골라 준 포트가 놓은 직후 다시 붙여 보면 막혀 있는 때가 있습니다
    (같은 번호를 다른 프로그램의 연결이 막 가져간 경우). 그런 포트는 건너뜁니다. 같은
    까닭으로 비었다고 본 포트가 바로 다음 순간 막힐 수도 있어, 「비어 있으면 그대로」를
    보는 시험은 몇 번 다시 해 봅니다(`TRIES`).
    """
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if desktop_main.port_is_free(port):
            return port
    raise AssertionError("빈 포트를 찾지 못했습니다.")


def _잡아(host: str) -> socket.socket:
    """`host` 의 빈 포트를 잡고 받는 중으로 둡니다. 시험이 끝나면 닫습니다."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen()
    return sock


def _기억해(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def _읽어(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def 기억_파일(tmp_path) -> Path:
    return tmp_path / "state" / "desktop.json"


# ── 고르기 ────────────────────────────────────────────


def test_지난번_포트가_비어_있으면_그대로_쓴다():
    for _ in range(TRIES):
        port = _빈_포트()
        chosen = desktop_main.pick_port(port)
        if chosen == port:
            break

    assert chosen == port


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_지난번_포트가_사용_중이면_새_포트다(host):
    """0.0.0.0 에서 받는 프로그램도 사용 중으로 봅니다(Windows 는 127.0.0.1 로는 붙여 줍니다)."""
    with _잡아(host) as held:
        busy = held.getsockname()[1]

        port = desktop_main.pick_port(busy)

        assert port != busy
        assert desktop_main.PORT_MIN <= port <= desktop_main.PORT_MAX


@pytest.mark.parametrize(
    "기억값",
    [None, "51234", 51234.0, True, [51234], 0, -1, 1023, 65536, 10**9],
)
def test_정수가_아니거나_범위_밖이면_새_포트다(monkeypatch, 기억값):
    """비었는지 보기 전에 거릅니다 — 비었다고 답하게 해 두어도 받지 않습니다."""
    monkeypatch.setattr(desktop_main, "port_is_free", lambda _port: True)

    port = desktop_main.pick_port(기억값)

    assert isinstance(port, int) and not isinstance(port, bool)
    assert port != 기억값
    assert desktop_main.PORT_MIN <= port <= desktop_main.PORT_MAX


@pytest.mark.parametrize("port", [desktop_main.PORT_MIN, desktop_main.PORT_MAX])
def test_범위_끝도_받는다(monkeypatch, port):
    monkeypatch.setattr(desktop_main, "port_is_free", lambda _port: True)

    assert desktop_main.pick_port(port) == port


# ── 새 포트 ───────────────────────────────────────────


def test_새_포트는_구간의_첫_포트가_비면_그것이다(monkeypatch):
    monkeypatch.setattr(desktop_main, "port_is_free", lambda _port: True)

    assert desktop_main.pick_port(None) == desktop_main.PREFERRED_PORTS[0] == 47100


def test_구간_앞쪽이_막혀_있으면_다음_빈_포트다(monkeypatch):
    seen: list[int] = []

    def free(port: int) -> bool:
        seen.append(port)
        return port >= 47103

    monkeypatch.setattr(desktop_main, "port_is_free", free)

    assert desktop_main.pick_port(None) == 47103
    assert seen == [47100, 47101, 47102, 47103], "차례로 보고 첫 빈 포트에서 멈춥니다."


def test_구간이_전부_막혀_있으면_운영체제가_주는_포트다(monkeypatch):
    preferred = desktop_main.PREFERRED_PORTS
    monkeypatch.setattr(desktop_main, "port_is_free", lambda port: port not in preferred)

    port = desktop_main.pick_port(None)

    assert port not in preferred
    assert desktop_main.PORT_MIN <= port <= desktop_main.PORT_MAX


def test_구간은_운영체제의_임시_대역_밖이다():
    preferred = desktop_main.PREFERRED_PORTS
    assert desktop_main.PORT_MIN <= preferred[0] and preferred[-1] < 49152


# ── 기억 ──────────────────────────────────────────────


def test_고른_포트를_기억하고_글씨_크기는_남긴다(기억_파일):
    _기억해(기억_파일, {"zoom": 1.1})

    port = desktop_main.choose_port(기억_파일)

    assert _읽어(기억_파일) == {"port": port, "zoom": 1.1}
    assert list(기억_파일.parent.iterdir()) == [기억_파일], "임시 파일이 남지 않습니다."


def test_지난번_포트가_비어_있으면_그_포트로_뜨고_파일은_그대로다(기억_파일):
    for _ in range(TRIES):
        port = _빈_포트()
        _기억해(기억_파일, {"port": port, "zoom": 0.9})
        chosen = desktop_main.choose_port(기억_파일)
        if chosen == port:
            break

    assert chosen == port
    assert _읽어(기억_파일) == {"port": port, "zoom": 0.9}


def test_지난번_포트가_막혀_있으면_새_포트를_기억한다(기억_파일):
    with _잡아("127.0.0.1") as held:
        busy = held.getsockname()[1]
        _기억해(기억_파일, {"port": busy, "zoom": 1.2})

        port = desktop_main.choose_port(기억_파일)

    assert port != busy
    assert _읽어(기억_파일) == {"port": port, "zoom": 1.2}


@pytest.mark.parametrize("내용", [None, "{망가진", "", "[51234]"])
def test_없거나_망가진_파일이면_새_포트로_덮어쓴다(기억_파일, 내용):
    if 내용 is not None:
        _기억해(기억_파일, 내용)

    port = desktop_main.choose_port(기억_파일)

    assert _읽어(기억_파일) == {"port": port}


def test_파일에_못_써도_고른_포트로_뜬다(기억_파일, caplog):
    기억_파일.mkdir(parents=True)  # 같은 이름의 폴더가 있어 파일로 바꿔치기할 수 없습니다.

    port = desktop_main.choose_port(기억_파일)

    assert desktop_main.PORT_MIN <= port <= desktop_main.PORT_MAX
    assert "포트를 기억하지 못했습니다" in caplog.text


# ── 글씨 크기 저장과 함께 ─────────────────────────────


class WebView2:
    """창 안 웹뷰 컨트롤 자리. 형 이름이 `WebView2` 여야 찾습니다."""

    ZoomFactor = 1.0


class _창틀:
    InvokeRequired = False

    def __init__(self, controls: list) -> None:
        self.Controls = controls


class _창:
    def __init__(self, form) -> None:
        self.native = form


def test_글씨_크기를_바꿔도_포트_항목은_남는다(기억_파일):
    _기억해(기억_파일, {"port": 51234})
    zoom = notify.Zoom(action=lambda work: work, path=기억_파일)
    zoom.attach(_창(_창틀([WebView2()])))

    assert zoom.set_zoom(1.1) is True
    assert _읽어(기억_파일) == {"port": 51234, "zoom": 1.1}
