"""글씨 크기 — 창 안 웹뷰의 배율(`ZoomFactor`)을 바꾸는 자리.

**창도 웹뷰도 띄우지 않습니다.** 창과 웹뷰 컨트롤은 가짜이고, UI 스레드로 넘기는
자리(`Invoke`)는 불렸는지 적고 바로 돌립니다. 배율을 기억하는 파일은 시험마다 임시
폴더로 옮겨, 사용자 홈의 파일을 건드리지 않습니다.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from desktop import notify


@pytest.fixture(autouse=True)
def _기억_파일(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "state" / "desktop.json"
    monkeypatch.setattr(notify, "DESKTOP_STATE_PATH", path)
    return path


class WebView2:
    """창 안 웹뷰 컨트롤 자리. 형 이름이 `WebView2` 여야 찾습니다."""

    def __init__(self, factor: float = 1.0) -> None:
        self.ZoomFactor = factor


class _다른컨트롤:
    ZoomFactor = 1.0


class _창틀:
    def __init__(self, controls: list, *, invoke_required: bool = True) -> None:
        self.Controls = controls
        self.InvokeRequired = invoke_required
        self.invoked = 0

    def Invoke(self, work) -> None:
        self.invoked += 1
        work()


class _창:
    def __init__(self, form) -> None:
        self.native = form


def _바로(work):
    """`System.Action` 자리. 가짜 창틀은 받은 것을 그대로 부릅니다."""
    return work


def _세운(*controls, invoke_required: bool = True):
    form = _창틀(list(controls), invoke_required=invoke_required)
    zoom = notify.Zoom(action=_바로)
    zoom.attach(_창(form))
    return zoom, form


@pytest.mark.parametrize("배율", [0.9, 1, 1.0, 1.1, 1.2])
def test_네_단은_웹뷰_배율로_건다(배율):
    웹뷰 = WebView2()
    zoom, _ = _세운(_다른컨트롤(), 웹뷰)

    assert zoom.set_zoom(배율) is True
    assert 웹뷰.ZoomFactor == pytest.approx(배율)
    assert zoom.get_zoom() == pytest.approx(배율)


@pytest.mark.parametrize("배율", [1.25, 0.5, 2, 0, -1, "1.1", None, True, float("nan")])
def test_네_단_밖은_받지_않고_배율을_그대로_둔다(배율):
    웹뷰 = WebView2(1.1)
    zoom, form = _세운(웹뷰)

    assert zoom.set_zoom(배율) is False
    assert 웹뷰.ZoomFactor == 1.1
    assert form.invoked == 0


def test_화면의_호출은_UI_스레드로_넘겨_쓴다():
    """다른 스레드에서 바로 쓰면 교차 스레드 예외로 배율이 안 바뀝니다."""
    웹뷰 = WebView2()
    zoom, form = _세운(웹뷰, invoke_required=True)

    assert zoom.set_zoom(1.2) is True
    assert form.invoked == 1, "Invoke 로 넘겼습니다."
    assert 웹뷰.ZoomFactor == 1.2
    zoom.get_zoom()
    assert form.invoked == 2, "읽을 때도 UI 스레드입니다."


class _UI스레드창틀:
    """자기 UI 스레드를 가진 창틀. 컨트롤 목록과 웹뷰 배율은 그 스레드에서만 만질 수
    있고, 다른 스레드에서 만지면 실제 창처럼 교차 스레드 예외가 납니다."""

    def __init__(self, view) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui")
        self._ui = self._pool.submit(threading.get_ident).result()
        self._controls = [_다른컨트롤(), view]
        self.touched_outside: list[str] = []

    def _check(self, what: str) -> None:
        if threading.get_ident() != self._ui:
            self.touched_outside.append(what)
            raise RuntimeError(f"교차 스레드: {what}")

    @property
    def Controls(self):
        self._check("Controls")
        return self._controls

    @property
    def InvokeRequired(self) -> bool:
        return threading.get_ident() != self._ui

    def Invoke(self, work) -> None:
        self._pool.submit(work).result()

    def close(self) -> None:
        self._pool.shutdown()


@pytest.mark.parametrize("부르기", ["set_zoom", "get_zoom", "apply_remembered"])
def test_컨트롤은_UI_스레드에서만_만진다(_기억_파일, 부르기):
    """웹뷰를 찾는 일(컨트롤 목록 훑기)까지 UI 스레드에서 합니다."""
    _기억해(_기억_파일, {"zoom": 1.1})
    form: _UI스레드창틀

    class _지키는웹뷰:
        def GetType(self):
            return type("형", (), {"Name": "WebView2"})()

        @property
        def ZoomFactor(self):
            form._check("ZoomFactor")
            return self._factor

        @ZoomFactor.setter
        def ZoomFactor(self, value):
            form._check("ZoomFactor")
            self._factor = value

    웹뷰 = _지키는웹뷰()
    웹뷰._factor = 1.0
    form = _UI스레드창틀(웹뷰)
    try:
        zoom = notify.Zoom(action=_바로)
        assert zoom.attach(_창(form)) is True, "받으면서 기억한 배율을 겁니다."
        assert 웹뷰._factor == 1.1
        웹뷰._factor = 1.0  # 웹뷰가 준비되며 배율을 되돌린 경우

        if 부르기 == "set_zoom":
            assert zoom.set_zoom(1.2) is True
            assert 웹뷰._factor == 1.2
        elif 부르기 == "get_zoom":
            assert zoom.get_zoom() == pytest.approx(1.0)
        else:
            assert zoom.apply_remembered() is True
            assert 웹뷰._factor == 1.1
        assert form.touched_outside == []
    finally:
        form.close()


def test_UI_스레드면_바로_쓴다():
    웹뷰 = WebView2()
    zoom, form = _세운(웹뷰, invoke_required=False)

    assert zoom.set_zoom(0.9) is True
    assert form.invoked == 0 and 웹뷰.ZoomFactor == 0.9


def test_웹뷰가_없으면_거짓이다():
    zoom, _ = _세운(_다른컨트롤())

    assert zoom.set_zoom(1.1) is False
    assert zoom.get_zoom() is None


def test_창을_받기_전이면_거짓이다():
    zoom = notify.Zoom(action=_바로)

    assert zoom.set_zoom(1.1) is False
    assert zoom.get_zoom() is None


def test_배율을_쓰다_터지면_거짓이고_기록에_남는다(caplog):
    class _형:
        Name = "WebView2"

    class _터지는웹뷰(WebView2):
        """.NET 컨트롤처럼 형 이름을 `GetType().Name` 으로 내고, 배율을 쓰면 터집니다."""

        def GetType(self):
            return _형()

        def __setattr__(self, name, value):
            if name == "ZoomFactor" and hasattr(self, "ZoomFactor"):
                raise RuntimeError("교차 스레드")
            super().__setattr__(name, value)

    zoom, form = _세운(_터지는웹뷰())

    assert zoom.set_zoom(1.2) is False
    assert form.invoked == 1, "웹뷰를 찾아 배율을 쓰려다 터졌습니다."
    assert "글씨 크기를 바꾸지 못했습니다" in caplog.text


def test_화면에_내놓는_자리는_배율_둘이고_창_받기는_안_내놓는다():
    """공개 메서드는 화면에서 부를 수 있습니다. 창을 받는 일은 `main.py` 몫입니다."""
    웹뷰 = WebView2()
    zoom, _ = _세운(웹뷰)
    api = notify.Api(notify.Notifier(), zoom)

    assert api.set_zoom(1.1) is True and api.get_zoom() == pytest.approx(1.1)
    공개 = {name for name in dir(api) if not name.startswith("_")}
    assert 공개 == {"notify", "set_zoom", "get_zoom"}


# ── 기억 ──────────────────────────────────────────────


def _기억해(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def test_바꾸면_파일에_기억한다(_기억_파일):
    웹뷰 = WebView2()
    zoom, _ = _세운(웹뷰)

    assert zoom.set_zoom(1.1) is True
    assert json.loads(_기억_파일.read_text(encoding="utf-8")) == {"zoom": 1.1}
    assert zoom.remembered == 1.1
    assert list(_기억_파일.parent.iterdir()) == [_기억_파일], "임시 파일이 남지 않습니다."

    assert zoom.set_zoom(0.9) is True
    assert json.loads(_기억_파일.read_text(encoding="utf-8")) == {"zoom": 0.9}


def test_바꾸지_못하면_기억하지_않는다(_기억_파일):
    _기억해(_기억_파일, {"zoom": 1.2})
    zoom, _ = _세운(_다른컨트롤())

    assert zoom.set_zoom(1.1) is False, "웹뷰가 없습니다."
    assert zoom.set_zoom(1.25) is False, "네 단 밖입니다."
    assert json.loads(_기억_파일.read_text(encoding="utf-8")) == {"zoom": 1.2}
    assert zoom.remembered == 1.2


def test_창을_받기_전에_바꾸려_하면_파일을_만들지_않는다(_기억_파일):
    zoom = notify.Zoom(action=_바로)

    assert zoom.set_zoom(1.1) is False
    assert not _기억_파일.exists()


def test_기억한_파일에_못_써도_배율은_바뀐다(_기억_파일, caplog):
    _기억_파일.parent.mkdir(parents=True)
    _기억_파일.mkdir()  # 같은 이름의 폴더가 있어 파일로 바꿔치기할 수 없습니다.
    웹뷰 = WebView2()
    zoom, _ = _세운(웹뷰)

    assert zoom.set_zoom(1.2) is True
    assert 웹뷰.ZoomFactor == 1.2 and zoom.remembered == 1.2
    assert "글씨 크기를 기억하지 못했습니다" in caplog.text


@pytest.mark.parametrize("배율", [0.9, 1.1, 1.2])
def test_만들_때_기억한_배율을_읽는다(_기억_파일, 배율):
    _기억해(_기억_파일, {"zoom": 배율})

    assert notify.Zoom(action=_바로).remembered == 배율


@pytest.mark.parametrize(
    "내용",
    [
        None,  # 파일 없음
        "{망가진",
        "",
        "[1.1]",
        {"zoom": 1.25},
        {"zoom": "1.1"},
        {"zoom": True},
        {"zoom": None},
        {"다른": 1.1},
    ],
)
def test_없거나_망가졌거나_네_단_밖이면_보통이다(_기억_파일, 내용):
    if 내용 is not None:
        _기억해(_기억_파일, 내용)

    assert notify.Zoom(action=_바로).remembered == notify.DEFAULT_ZOOM


def test_경로를_건네면_그_파일을_쓴다(tmp_path):
    path = tmp_path / "다른" / "zoom.json"
    _기억해(path, {"zoom": 0.9})
    form = _창틀([WebView2()])
    zoom = notify.Zoom(action=_바로, path=path)

    assert zoom.remembered == 0.9
    zoom.attach(_창(form))
    assert zoom.set_zoom(1.1) is True
    assert json.loads(path.read_text(encoding="utf-8")) == {"zoom": 1.1}


# ── 기억한 배율 걸기 ──────────────────────────────────


def test_창을_받으면_기억한_배율을_UI_스레드에서_건다(_기억_파일):
    _기억해(_기억_파일, {"zoom": 1.2})
    웹뷰 = WebView2()
    form = _창틀([_다른컨트롤(), 웹뷰], invoke_required=True)
    zoom = notify.Zoom(action=_바로)

    assert zoom.attach(_창(form)) is True
    assert 웹뷰.ZoomFactor == 1.2
    assert form.invoked == 1, "Invoke 로 넘겼습니다."


def test_다시_걸어도_같은_배율이다(_기억_파일):
    """창이 뜬 때와 화면을 다 불러온 때, 두 번 불립니다."""
    _기억해(_기억_파일, {"zoom": 0.9})
    웹뷰 = WebView2()
    form = _창틀([웹뷰])
    zoom = notify.Zoom(action=_바로)
    zoom.attach(_창(form))
    웹뷰.ZoomFactor = 1.0  # 웹뷰가 준비되며 배율을 되돌린 경우

    assert zoom.apply_remembered() is True
    assert 웹뷰.ZoomFactor == 0.9
    assert zoom.apply_remembered() is True
    assert 웹뷰.ZoomFactor == 0.9 and form.invoked == 3


def test_바꾼_뒤에는_바꾼_배율을_건다(_기억_파일):
    _기억해(_기억_파일, {"zoom": 0.9})
    웹뷰 = WebView2()
    zoom, _ = _세운(웹뷰)

    assert zoom.set_zoom(1.1) is True
    웹뷰.ZoomFactor = 1.0
    assert zoom.apply_remembered() is True
    assert 웹뷰.ZoomFactor == 1.1


def test_보통이면_창을_건드리지_않는다(_기억_파일):
    웹뷰 = WebView2(1.1)  # 기억한 것이 없습니다.
    form = _창틀([웹뷰])
    zoom = notify.Zoom(action=_바로)

    assert zoom.attach(_창(form)) is True
    assert zoom.apply_remembered() is True
    assert form.invoked == 0 and 웹뷰.ZoomFactor == 1.1


def test_창이_없으면_걸지_못한다(_기억_파일, caplog):
    _기억해(_기억_파일, {"zoom": 1.1})
    zoom = notify.Zoom(action=_바로)

    assert zoom.apply_remembered() is False
    assert "기억해 둔 글씨 크기를 걸지 못했습니다" in caplog.text


def test_웹뷰가_없으면_걸지_못한다(_기억_파일):
    _기억해(_기억_파일, {"zoom": 1.1})
    다른 = _다른컨트롤()
    form = _창틀([다른])
    zoom = notify.Zoom(action=_바로)

    assert zoom.attach(_창(form)) is False
    assert form.invoked == 1, "웹뷰를 찾는 일도 UI 스레드에서 합니다."
    assert 다른.ZoomFactor == 1.0, "다른 컨트롤의 배율은 건드리지 않습니다."


def test_걸다_터지면_거짓이고_기록에_남는다(_기억_파일, caplog):
    _기억해(_기억_파일, {"zoom": 1.1})

    class _터지는창틀(_창틀):
        def Invoke(self, work) -> None:
            self.invoked += 1
            raise RuntimeError("창이 닫히는 중")

    form = _터지는창틀([WebView2()])
    zoom = notify.Zoom(action=_바로)

    assert zoom.attach(_창(form)) is False
    assert form.invoked == 1
    assert "기억해 둔 글씨 크기를 걸지 못했습니다" in caplog.text
