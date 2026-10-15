"""운영체제 알림 — 판정·자르기·누름·수명.

**창도 서버도 띄우지 않습니다.** 알림 영역 아이콘은 가짜이고, UI 스레드로
넘기는 자리는 바로 돌리거나 들고 있다가 나중에 돌립니다. 실제 WinForms 를
쓰는 시험은 Windows 와 pythonnet 이 있을 때만 돌고, 그때도 아이콘을 띄우지
않습니다.
"""
from __future__ import annotations

import json
import sys
import threading

import pytest

from desktop import notify


class _가짜아이콘:
    def __init__(self, *, front: bool = False, later: bool = False) -> None:
        self.front = front
        self.later = later
        self.held: list = []
        self.shown: list[tuple[str, str, bool]] = []
        self.posted = 0
        self.fronted = 0
        self.disposed = 0
        self.show_error: Exception | None = None
        self.post_error: Exception | None = None

    def post(self, work) -> None:
        if self.post_error is not None:
            raise self.post_error
        self.posted += 1
        if self.later:
            self.held.append(work)
        else:
            work()

    def is_front(self) -> bool:
        return self.front

    def show(self, title: str, body: str, warning: bool) -> None:
        if self.show_error is not None:
            raise self.show_error
        self.shown.append((title, body, warning))

    def bring_front(self) -> None:
        self.fronted += 1

    def dispose(self) -> None:
        self.disposed += 1


class _가짜창:
    def __init__(self) -> None:
        self.scripts: list[tuple[str, int]] = []
        self.ran = threading.Event()

    def evaluate_js(self, script: str):
        self.scripts.append((script, threading.get_ident()))
        self.ran.set()


def _붙임(아이콘: _가짜아이콘, wait: float = 1.0):
    알림 = notify.Notifier(wait=wait)
    창 = _가짜창()
    누름: dict = {}

    def 만듦(window, *, on_click, on_open):
        누름["click"] = on_click
        누름["open"] = on_open
        return 아이콘

    assert 알림.attach(창, make_tray=만듦)
    return 알림, 창, 누름


def _물음(**덮어쓰기):
    made = {"title": "MESZ26 체결", "body": "매수 1계약 7765.75", "runId": "run1", "kind": "fill"}
    made.update(덮어쓰기)
    return made


# ── 낼지 말지 ──────────────────────────────────────────


def test_창이_뒤에_있으면_풍선을_내고_참이다():
    아이콘 = _가짜아이콘(front=False)
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음()) is True
    assert 아이콘.shown == [("MESZ26 체결", "매수 1계약 7765.75", False)]


def test_창이_앞에_있으면_내지_않고_거짓이다():
    아이콘 = _가짜아이콘(front=True)
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음()) is False
    assert 아이콘.shown == []


@pytest.mark.parametrize("kind", ["exit", "limit", "feed"])
def test_청산_한도_시세끊김은_경고_아이콘이다(kind):
    아이콘 = _가짜아이콘()
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음(kind=kind)) is True
    assert 아이콘.shown[0][2] is True


@pytest.mark.parametrize("kind", ["signal", "fill", "unsent", None, "모르는종류"])
def test_그_밖의_종류는_정보_아이콘이다(kind):
    아이콘 = _가짜아이콘()
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음(kind=kind)) is True
    assert 아이콘.shown[0][2] is False


def test_시험_알림은_창이_앞에_있어도_낸다():
    아이콘 = _가짜아이콘(front=True)
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음(title="시험 알림 · NH FUTURES API", runId="", test=True)) is True
    assert len(아이콘.shown) == 1


def test_시험_알림도_모양_검사와_거짓_처리는_같다():
    """앞에 있음 판정만 건너뜁니다. 틀린 인자·예외는 그대로 거짓이고, UI 스레드로 넘깁니다."""
    아이콘 = _가짜아이콘(front=True)
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음(body="", test=True)) is False
    assert 알림.notify(_물음(test="yes")) is False
    assert 아이콘.posted == 0, "모양이 틀리면 UI 스레드에 넘기지도 않습니다."

    아이콘.show_error = RuntimeError("풍선 실패")
    assert 알림.notify(_물음(test=True)) is False
    assert 아이콘.posted == 1, "시험 알림도 UI 스레드에서 냅니다."


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "글자",
        {"body": "본문"},
        _물음(title=""),
        _물음(title="   "),
        _물음(title=3),
        _물음(body=""),
        _물음(body=None),
        _물음(runId=7),
        _물음(kind=1),
        _물음(test=1),
    ],
)
def test_모양이_틀린_인자는_예외없이_거짓이다(payload):
    아이콘 = _가짜아이콘()
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(payload) is False
    assert 아이콘.posted == 0 and 아이콘.shown == []


def test_runId_가_없거나_null_이어도_낸다():
    아이콘 = _가짜아이콘()
    알림, _, _ = _붙임(아이콘)
    물음 = _물음()
    del 물음["runId"]

    assert 알림.notify(물음) is True
    assert 알림.notify(_물음(runId=None)) is True


def test_제목과_본문은_윈도우_한도로_자른다():
    아이콘 = _가짜아이콘()
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음(title="가" * 100, body="나" * 400)) is True
    ((제목, 본문, _),) = 아이콘.shown
    assert len(제목) == notify.TITLE_LIMIT == 63
    assert len(본문) == notify.BODY_LIMIT == 255


# ── 낼 수 없을 때 ──────────────────────────────────────


def test_아이콘이_없으면_거짓이다():
    assert notify.Notifier().notify(_물음()) is False


def test_아이콘을_못_만들면_붙이기도_알림도_거짓이다():
    알림 = notify.Notifier()

    def 실패(window, *, on_click, on_open):
        raise RuntimeError("WinForms 없음")

    assert 알림.attach(_가짜창(), make_tray=실패) is False
    assert 알림.notify(_물음()) is False


def test_창이_없는_창으로는_아이콘을_만들지_않는다():
    """`native` 가 없으면(창이 아직 안 섬·Windows 아님) 붙이지 않고 알림만 꺼집니다."""
    알림 = notify.Notifier()

    assert 알림.attach(_가짜창()) is False
    assert 알림.notify(_물음()) is False


def test_풍선을_내다_예외가_나면_거짓이다():
    아이콘 = _가짜아이콘()
    아이콘.show_error = RuntimeError("풍선 실패")
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음()) is False


def test_UI_스레드에_못_넘기면_거짓이다():
    아이콘 = _가짜아이콘()
    아이콘.post_error = RuntimeError("창이 닫힘")
    알림, _, _ = _붙임(아이콘)

    assert 알림.notify(_물음()) is False


def test_시간_안에_답이_없으면_거짓이고_늦게_돌아도_풍선을_내지_않는다():
    """화면은 「안 냄」으로 알았는데 뒤늦게 뜨면, 같은 사건을 다시 낼 때 두 번 보입니다."""
    아이콘 = _가짜아이콘(later=True)
    알림, _, _ = _붙임(아이콘, wait=0.01)

    assert 알림.notify(_물음()) is False
    (늦은작업,) = 아이콘.held
    늦은작업()

    assert 아이콘.shown == []


# ── 누름 ──────────────────────────────────────────────


def test_풍선을_누르면_창을_앞으로_하고_다른_스레드에서_그_실행을_연다():
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)
    번호 = 'r"1\\x</script>'
    assert 알림.notify(_물음(runId=번호)) is True

    누름["click"]()

    assert 아이콘.fronted == 1
    assert 창.ran.wait(2)
    ((스크립트, 스레드),) = 창.scripts
    assert 스레드 != threading.get_ident(), "UI 스레드에서 스크립트 결과를 기다리면 창이 멈춥니다."
    assert 스크립트 == f"window.__nhNotifyClick?.({json.dumps(번호)})"


def test_누름_스크립트는_따옴표와_역슬래시를_이스케이프한다():
    스크립트 = notify.click_script('a"b\\c d')

    assert 스크립트 == 'window.__nhNotifyClick?.("a\\"b\\\\c\\u2028d")'


def test_실행_번호가_빈_풍선도_빈_글자로_화면을_부른다():
    """여러 실행을 묶은 알림입니다. 어느 실행을 열지는 화면이 기억해 둔 것으로 고릅니다."""
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)
    assert 알림.notify(_물음(runId="")) is True

    누름["click"]()

    assert 아이콘.fronted == 1
    assert 창.ran.wait(2)
    assert 창.scripts[0][0] == "window.__nhNotifyClick?.(\"\")"


@pytest.mark.parametrize("run_id", ["", None, "run1"])
def test_시험_풍선을_누르면_창만_앞으로_온다(run_id):
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)
    assert 알림.notify(_물음(runId=run_id, test=True)) is True

    누름["click"]()

    assert 아이콘.fronted == 1
    assert not 창.ran.wait(0.1) and 창.scripts == []


def test_시험_풍선_뒤의_실제_풍선은_다시_화면을_부른다():
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)
    알림.notify(_물음(runId="", test=True))
    알림.notify(_물음(runId="run2"))

    누름["click"]()

    assert 창.ran.wait(2)
    assert 창.scripts[0][0] == notify.click_script("run2")


def test_마지막_풍선의_실행을_연다():
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)
    알림.notify(_물음(runId="run1"))
    알림.notify(_물음(runId="run2"))

    누름["click"]()

    assert 창.ran.wait(2)
    assert 창.scripts[0][0] == notify.click_script("run2")


def test_낸_풍선이_없으면_눌러도_아무_일도_없다():
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)

    누름["click"]()

    assert 아이콘.fronted == 0 and 창.scripts == []


def test_앞에_있어_안_낸_알림은_누름_대상이_아니다():
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)
    알림.notify(_물음(runId="run1"))
    아이콘.front = True
    assert 알림.notify(_물음(runId="run2")) is False

    누름["click"]()

    assert 창.ran.wait(2)
    assert 창.scripts[0][0] == notify.click_script("run1")


def test_아이콘을_두_번_누르면_창만_앞으로_온다():
    아이콘 = _가짜아이콘()
    알림, 창, 누름 = _붙임(아이콘)

    누름["open"]()

    assert 아이콘.fronted == 1 and 창.scripts == []


# ── 수명 ──────────────────────────────────────────────


def test_치우기는_한_번만_치우고_두_번_불러도_된다():
    아이콘 = _가짜아이콘()
    알림, _, _ = _붙임(아이콘)

    알림.dispose()
    알림.dispose()

    assert 아이콘.disposed == 1
    assert 알림.notify(_물음()) is False, "치운 뒤에는 내지 않습니다."


def test_치우다_예외가_나도_밖으로_내지_않는다():
    아이콘 = _가짜아이콘()

    def 실패():
        raise RuntimeError("이미 치움")

    아이콘.dispose = 실패
    알림, _, _ = _붙임(아이콘)

    알림.dispose()


def test_두_번_붙여도_아이콘은_하나다():
    아이콘 = _가짜아이콘()
    알림, 창, _ = _붙임(아이콘)
    만든횟수 = []

    def 또만듦(window, *, on_click, on_open):
        만든횟수.append(1)
        return _가짜아이콘()

    assert 알림.attach(창, make_tray=또만듦) is True
    assert 만든횟수 == []


def test_화면에는_알림과_글씨_크기만_보인다():
    api = notify.Api(notify.Notifier())

    assert [name for name in dir(api) if not name.startswith("_")] == ["get_zoom", "notify", "set_zoom"]
    assert api.notify() is False, "인자 없이 불러도 예외가 아닙니다."
    assert api.set_zoom() is False and api.get_zoom() is None, "창이 없으면 거짓·없음입니다."


def test_아이콘_파일은_저장소의_build_에서_찾는다():
    found = notify.icon_path()

    assert found is not None and found.name == "nh-api.ico" and found.parent.name == "build"


def test_묶인_실행_파일에서는_함께_묶인_자리에서_찾는다(tmp_path, monkeypatch):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "nh-api.ico").write_bytes(b"")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert notify.icon_path() == tmp_path / "build" / "nh-api.ico"


# ── 실제 WinForms ─────────────────────────────────────


def test_WinForms_의_알림_영역_형식을_불러온다():
    """아이콘은 띄우지 않고, 쓰는 형식과 값이 있는지만 봅니다."""
    if sys.platform != "win32":
        pytest.skip("Windows 에서만 운영체제 알림을 냅니다.")
    clr = pytest.importorskip("clr")
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Drawing import SystemIcons
    from System.Windows.Forms import Form, FormWindowState, NotifyIcon, ToolTipIcon

    assert NotifyIcon is not None and Form is not None and SystemIcons.Application is not None
    assert {ToolTipIcon.Info, ToolTipIcon.Warning} and FormWindowState.Minimized is not None
