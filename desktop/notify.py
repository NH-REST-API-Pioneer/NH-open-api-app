"""운영체제 알림 — 작업 표시줄 알림 영역의 아이콘과 풍선.

화면이 `window.pywebview.api.notify({...})` 로 부릅니다. 앱 창이 앞에 있으면
화면에서 이미 보이므로 풍선을 내지 않고, 뒤에 있거나 최소화돼 있을 때만
냅니다. Windows 10·11 에서는 이 풍선이 알림 센터의 알림으로 보이고 그곳에
남습니다.

풍선을 누르면 창을 앞으로 가져오고, 화면의 `window.__nhNotifyClick(runId)`
를 불러 그 실행을 엽니다. 실행 번호가 없는 알림(여러 실행을 묶은 알림)도
빈 글자로 부르고, 화면이 기억해 둔 실행으로 엽니다. 설정의 시험 알림만은
창만 앞으로 가져옵니다.

**모든 WinForms 조작은 창의 UI 스레드에서 합니다.** 화면의 호출은 다른
스레드에서 들어오므로 창에 작업을 넘기고(`BeginInvoke`) 결과를 기다립니다.
알림 영역 아이콘은 앱이 떠 있는 동안 늘 보입니다.

Windows 가 아니거나 WinForms 를 불러올 수 없으면 아이콘을 만들지 않고,
`notify` 는 언제나 `False` 를 돌려줍니다.

화면의 글씨 크기(`set_zoom`·`get_zoom`)도 이 자리로 들어옵니다. 창 안 웹뷰의 배율
(`ZoomFactor`)을 바꿉니다 — 브라우저의 Ctrl + / − 와 같은 배율이라 화면 전체가 함께
커지고 마우스 좌표도 그대로 맞습니다. 고른 배율은 사용자 홈의 파일에 기억해 두고, 다음에
앱을 켜면 창이 뜨는 대로 다시 겁니다.
"""
from __future__ import annotations

import atexit
import json
import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from backend.storage import STATE_DIR, write_json

log = logging.getLogger(__name__)

#: 풍선 제목과 본문의 최대 길이. Windows 가 이보다 긴 글자는 받지 않습니다.
TITLE_LIMIT = 63
BODY_LIMIT = 255

#: 화면의 호출이 UI 스레드의 답을 기다리는 최대 시간(초).
WAIT_SECONDS = 1.0

#: 풍선을 보여 달라고 청하는 시간(밀리초). 실제 시간은 Windows 설정이 정합니다.
BALLOON_MS = 5000

#: 경고 아이콘으로 내는 종류 — 청산, 한도 정지, 시세 끊김.
WARNING_KINDS = frozenset({"exit", "limit", "feed"})

#: 아이콘 파일. 개발 중에는 저장소의 `build/`, 실행 파일에서는 함께 묶인 자리에서 찾습니다.
ICON_NAME = "nh-api.ico"

#: 화면이 고를 수 있는 글씨 크기(웹뷰 배율). 그 밖의 값은 받지 않습니다.
ZOOM_STEPS = (0.9, 1.0, 1.1, 1.2)

#: 「보통」 배율. 기억해 둔 값이 없거나 읽지 못하면 이 값으로 뜹니다.
DEFAULT_ZOOM = 1.0

#: 데스크톱 창이 기억하는 것(글씨 크기·지난번 포트)을 담는 파일. 예: `{"port": 51234, "zoom": 1.1}`
#:
#: 설정 파일(`~/NHFutures/config/`)과 같은 뿌리의 **다른 폴더**(`state/`)입니다. 이
#: 폴더에는 인증 정보가 아닌 것만 담습니다 — 화면 상태처럼 남에게 보여도 곤란할 것
#: 없는 것입니다.
#:
#: 항목마다 따로 갱신합니다(`update_desktop_state`). 한 항목을 쓸 때 다른 항목은 그대로
#: 남습니다.
#:
#: 글씨 크기를 화면(웹뷰)의 브라우저 저장소에 두지 않는 까닭: 앱은 지난번 포트를 먼저
#: 쓰지만 그 포트가 막혀 있으면 다른 포트로 화면을 열고, 그때는 화면 쪽 저장소가 달라져
#: 거기 둔 값이 보이지 않습니다.
DESKTOP_STATE_PATH = STATE_DIR / "desktop.json"

#: 창 안 웹뷰 컨트롤의 형 이름(pywebview 의 Edge 구현이 창에 붙이는 것).
WEBVIEW_TYPE = "WebView2"


def icon_path() -> Path | None:
    """알림 영역 아이콘 파일. 없으면 `None` — 그때는 창의 아이콘을 씁니다."""
    bundled = getattr(sys, "_MEIPASS", None)
    root = Path(bundled) if bundled else Path(__file__).resolve().parent.parent
    found = root / "build" / ICON_NAME
    return found if found.is_file() else None


def click_script(run_id: str) -> str:
    """풍선을 눌렀을 때 화면에서 돌릴 스크립트.

    실행 번호는 JSON 문자열로 넣습니다 — 따옴표나 역슬래시가 섞여도 스크립트가
    깨지거나 다른 코드가 끼어들지 않습니다.
    """
    return f"window.__nhNotifyClick?.({json.dumps(run_id)})"


class Message:
    """화면이 보낸 알림 한 건. 모양이 틀리면 `parse` 가 `None` 을 돌려줍니다."""

    __slots__ = ("title", "body", "run_id", "warning", "test")

    def __init__(self, title: str, body: str, run_id: str, warning: bool, test: bool) -> None:
        self.title = title
        self.body = body
        self.run_id = run_id
        self.warning = warning
        self.test = test

    @classmethod
    def parse(cls, payload: Any) -> Message | None:
        if not isinstance(payload, dict):
            return None
        title = payload.get("title")
        body = payload.get("body")
        run_id = payload.get("runId")
        kind = payload.get("kind")
        test = payload.get("test", False)
        if not isinstance(title, str) or not title.strip():
            return None
        # 본문이 빈 풍선은 Windows 가 띄우지 않습니다.
        if not isinstance(body, str) or not body.strip():
            return None
        if run_id is not None and not isinstance(run_id, str):
            return None
        if kind is not None and not isinstance(kind, str):
            return None
        if not isinstance(test, bool):
            return None
        return cls(
            title=title.strip()[:TITLE_LIMIT],
            body=body.strip()[:BODY_LIMIT],
            run_id=(run_id or "").strip(),
            warning=kind in WARNING_KINDS,
            test=test,
        )


class Tray(Protocol):
    """알림 영역 아이콘. `post` 와 `dispose` 를 뺀 메서드는 UI 스레드에서만 부릅니다."""

    def post(self, work: Callable[[], None]) -> None: ...
    def is_front(self) -> bool: ...
    def show(self, title: str, body: str, warning: bool) -> None: ...
    def bring_front(self) -> None: ...
    def dispose(self) -> None: ...


class _Job:
    """UI 스레드에 넘긴 알림 한 건과 그 결과."""

    def __init__(self, message: Message) -> None:
        self.message = message
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.started = False
        self.cancelled = False
        self.result = False


class Notifier:
    """알림 영역 아이콘을 들고, 화면의 알림 요청을 풍선으로 냅니다."""

    def __init__(self, wait: float = WAIT_SECONDS) -> None:
        self._wait = wait
        self._tray: Tray | None = None
        self._window: Any = None
        self._lock = threading.Lock()
        # 마지막으로 낸 풍선. UI 스레드에서만 읽고 씁니다.
        self._shown = False
        self._last_run = ""
        self._last_test = False

    # ── 수명 ──────────────────────────────────────────

    def attach(self, window: Any, make_tray: Callable[..., Tray] | None = None) -> bool:
        """창이 뜬 뒤 한 번 아이콘을 만듭니다. 못 만들면 `False` — 알림만 꺼집니다."""
        with self._lock:
            if self._tray is not None:
                return True
        try:
            make = make_tray or _winforms_tray
            tray = make(window, on_click=self._clicked, on_open=self._open_window)
        except Exception:
            log.warning("알림 영역 아이콘을 만들지 못해 운영체제 알림을 끕니다.", exc_info=True)
            return False
        with self._lock:
            self._window = window
            self._tray = tray
        atexit.register(self.dispose)
        return True

    def dispose(self) -> None:
        """아이콘을 치웁니다. 창이 닫힐 때와 프로그램이 끝날 때 부르고, 두 번 불러도 됩니다."""
        with self._lock:
            tray, self._tray = self._tray, None
        if tray is None:
            return
        try:
            tray.dispose()
        except Exception:
            log.warning("알림 영역 아이콘을 치우지 못했습니다.", exc_info=True)

    # ── 화면의 요청 ───────────────────────────────────

    def notify(self, payload: Any) -> bool:
        """풍선을 냈으면 `True`. 창이 앞에 있거나 낼 수 없으면 `False` 입니다.

        `test` 가 참이면(설정의 「보내 보기」) 창이 앞에 있어도 냅니다. 그 밖의
        검사와 처리는 똑같습니다.
        """
        try:
            message = Message.parse(payload)
            if message is None:
                log.info("모양이 맞지 않는 알림 요청이라 내지 않습니다.")
                return False
            with self._lock:
                tray = self._tray
            if tray is None:
                return False
            job = _Job(message)
            tray.post(lambda: self._run(tray, job))
            return self._result(job)
        except Exception:
            log.warning("운영체제 알림을 내지 못했습니다.", exc_info=True)
            return False

    def _result(self, job: _Job) -> bool:
        if job.done.wait(self._wait):
            return job.result
        with job.lock:
            if not job.started:
                # 늦게 돌면 화면은 「안 냄」으로 알고 있는데 풍선이 뜹니다. 돌지 않게 막아 둡니다.
                job.cancelled = True
                log.info("창이 제때 답하지 않아 알림을 내지 않습니다.")
                return False
        # 이미 도는 중이면 곧 끝납니다.
        return job.result if job.done.wait(self._wait) else False

    def _run(self, tray: Tray, job: _Job) -> None:
        """UI 스레드에서 돕니다. 앞에 있는지 보고, 아니면 풍선을 냅니다."""
        with job.lock:
            if job.cancelled:
                return
            job.started = True
        try:
            message = job.message
            if not message.test and tray.is_front():
                job.result = False
                return
            tray.show(message.title, message.body, message.warning)
            self._shown = True
            self._last_run = message.run_id
            self._last_test = message.test
            job.result = True
        except Exception:
            log.warning("운영체제 알림을 내지 못했습니다.", exc_info=True)
            job.result = False
        finally:
            job.done.set()

    # ── 누름 (UI 스레드) ──────────────────────────────

    def _clicked(self) -> None:
        """풍선을 누름. 창을 앞으로 가져오고, 시험 알림이 아니면 화면에서 그 실행을 엽니다."""
        try:
            if not self._shown:
                return
            with self._lock:
                tray = self._tray
            if tray is None:
                return
            tray.bring_front()
            if self._last_test:
                return
            # UI 스레드에서 스크립트 결과를 기다리면 창이 멈출 수 있어 다른 스레드에서 부릅니다.
            threading.Thread(target=self._open_run, args=(self._last_run,), daemon=True).start()
        except Exception:
            log.warning("알림을 눌렀을 때 창을 열지 못했습니다.", exc_info=True)

    def _open_window(self) -> None:
        """아이콘을 두 번 누름. 창만 앞으로 가져옵니다."""
        try:
            with self._lock:
                tray = self._tray
            if tray is not None:
                tray.bring_front()
        except Exception:
            log.warning("창을 앞으로 가져오지 못했습니다.", exc_info=True)

    def _open_run(self, run_id: str) -> None:
        try:
            with self._lock:
                window = self._window
            if window is not None:
                window.evaluate_js(click_script(run_id))
        except Exception:
            log.warning("알림을 눌렀을 때 그 실행을 열지 못했습니다.", exc_info=True)


class Zoom:
    """창 안 웹뷰의 배율(글씨 크기). 창이 뜬 뒤 `attach` 로 창을 받습니다.

    **배율은 창의 UI 스레드에서만 바꿉니다.** 화면의 호출은 다른 스레드에서 들어오므로
    창에 작업을 넘기고(`Invoke`) 끝날 때까지 기다립니다 — 그 스레드에서 바로 쓰면
    교차 스레드 예외가 나고 배율이 안 바뀝니다. 창이 없거나, 웹뷰를 못 찾거나, 실패하면
    `set_zoom` 은 `False` 이고 까닭은 기록에 남깁니다.

    **바꾼 배율은 파일에 기억합니다**(`DESKTOP_STATE_PATH`). 파일은 만들 때 한 번 읽고,
    창을 받으면(`attach`) 그 배율을 겁니다. 창이 막 뜬 때에는 웹뷰가 아직 준비 전일 수
    있어, 화면을 다 불러온 뒤에도 한 번 더 겁니다(`apply_remembered`, `main.py`).
    """

    def __init__(
        self,
        action: Callable[[Callable[[], None]], Any] | None = None,
        path: Path | None = None,
    ) -> None:
        self._window: Any = None
        self._action = action
        self._path = path if path is not None else DESKTOP_STATE_PATH
        self._remembered = read_remembered_zoom(self._path)

    @property
    def remembered(self) -> float:
        """기억해 둔 배율. 기억한 것이 없으면 보통(1)입니다."""
        return self._remembered

    def attach(self, window: Any) -> bool:
        """창을 받고 기억해 둔 배율을 겁니다. 결과는 `apply_remembered` 와 같습니다."""
        self._window = window
        return self.apply_remembered()

    def apply_remembered(self) -> bool:
        """기억해 둔 배율을 창에 겁니다. 여러 번 불러도 같은 배율이 걸릴 뿐입니다.

        보통이면 걸 것이 없어 창을 건드리지 않고 `True` 입니다. 창이 없거나, 웹뷰를 못
        찾거나, 실패하면 `False` 이고 까닭은 기록에 남깁니다.
        """
        step = self._remembered
        if step == DEFAULT_ZOOM:
            return True
        try:

            def work(view: Any) -> None:
                view.ZoomFactor = step

            if not self._on_webview(work):
                log.warning("창 안에서 웹뷰를 찾지 못해 기억해 둔 글씨 크기를 걸지 못했습니다.")
                return False
            return True
        except Exception:
            log.warning("기억해 둔 글씨 크기를 걸지 못했습니다.", exc_info=True)
            return False

    def set_zoom(self, factor: Any) -> bool:
        step = _zoom_step(factor)
        if step is None:
            log.warning("받지 않는 글씨 크기입니다: %r", factor)
            return False
        try:

            def work(view: Any) -> None:
                view.ZoomFactor = step

            if not self._on_webview(work):
                log.warning("창 안에서 웹뷰를 찾지 못해 글씨 크기를 바꾸지 못했습니다.")
                return False
        except Exception:
            log.warning("글씨 크기를 바꾸지 못했습니다.", exc_info=True)
            return False
        self._remember(step)
        return True

    def _remember(self, step: float) -> None:
        """바꾼 배율을 기억합니다. 파일에 못 써도 지금 창의 배율은 그대로입니다.

        파일의 다른 항목(지난번 포트)은 그대로 둡니다.
        """
        self._remembered = step
        try:
            update_desktop_state(self._path, zoom=step)
        except Exception:
            log.warning("글씨 크기를 기억하지 못했습니다. 다음에 켤 때 이전 크기로 뜹니다.", exc_info=True)

    def get_zoom(self) -> float | None:
        """지금 웹뷰의 배율. 사용자가 Ctrl + 휠로 바꿨을 수도 있어 네 단 밖일 수 있습니다."""
        try:
            held: list[float] = []

            def work(view: Any) -> None:
                held.append(float(view.ZoomFactor))

            self._on_webview(work)
            return held[0] if held else None
        except Exception:
            log.warning("글씨 크기를 읽지 못했습니다.", exc_info=True)
            return None

    def _on_webview(self, use: Callable[[Any], None]) -> bool:
        """UI 스레드에서 창 안의 웹뷰를 찾아 `use(웹뷰)` 를 돌립니다. 찾았으면 `True` 입니다.

        웹뷰를 찾는 일(창의 컨트롤 목록 훑기)도 컨트롤을 만지는 일이라 UI 스레드에서
        합니다. 창을 받기 전이면 넘기지 않고 `False` 입니다.
        """
        form = getattr(self._window, "native", None)
        if form is None:
            return False
        found: list[bool] = []

        def work() -> None:
            view = _find_webview(form)
            if view is None:
                return
            found.append(True)
            use(view)

        self._on_ui(form, work)
        return bool(found)

    def _on_ui(self, form: Any, work: Callable[[], None]) -> None:
        """UI 스레드에서 돌리고 끝날 때까지 기다립니다."""
        if form.InvokeRequired:
            form.Invoke(self._wrap(work))
        else:
            work()

    def _wrap(self, work: Callable[[], None]) -> Any:
        if self._action is not None:
            return self._action(work)
        import clr  # pywebview 가 Windows 에서 쓰는 pythonnet

        clr.AddReference("System")
        from System import Action

        return Action(work)


def _zoom_step(factor: Any) -> float | None:
    """네 단 가운데 하나면 그 값, 아니면 `None`. 수가 아닌 값(글자·참거짓)은 받지 않습니다."""
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        return None
    for step in ZOOM_STEPS:
        if abs(float(factor) - step) < 1e-9:
            return step
    return None


def read_desktop_state(path: Path) -> dict[str, Any]:
    """데스크톱 창이 기억해 둔 것 전부. 파일이 없거나 읽지 못하면 빈 dict 입니다.

    망가진 파일(JSON 이 아니거나 객체가 아닌 것)도 빈 dict 로 읽습니다 — 다음에
    `update_desktop_state` 가 쓸 때 새 내용으로 덮어씁니다.
    """
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeError):
        log.warning("데스크톱 창이 기억해 둔 것을 읽지 못해 처음 상태로 뜹니다: %s", path, exc_info=True)
        return {}
    if not isinstance(body, dict):
        log.warning("데스크톱 창이 기억해 둔 파일의 모양이 맞지 않아 처음 상태로 뜹니다: %s", path)
        return {}
    return body


def update_desktop_state(path: Path, **fields: Any) -> None:
    """파일을 읽고, 받은 항목만 바꿔 다시 씁니다. 다른 항목은 그대로 남습니다.

    Raises:
        OSError: 폴더를 만들지 못했거나 쓰지 못한 경우.
    """
    state = read_desktop_state(path)
    state.update(fields)
    write_json(path, state)


def read_remembered_zoom(path: Path) -> float:
    """파일에 기억해 둔 배율. 파일이 없거나, 읽지 못하거나, 네 단 밖의 값이면 보통(1)입니다."""
    step = _zoom_step(read_desktop_state(path).get("zoom"))
    return step if step is not None else DEFAULT_ZOOM


def _find_webview(form: Any) -> Any:
    """창의 컨트롤 가운데 웹뷰. 없으면 `None` 입니다. UI 스레드에서 부릅니다."""
    for control in form.Controls:
        if _type_name(control) == WEBVIEW_TYPE:
            return control
    return None


def _type_name(control: Any) -> str:
    """컨트롤의 형 이름. .NET 객체는 `GetType().Name` 이고, 그 밖은 파이썬 형 이름입니다."""
    get_type = getattr(control, "GetType", None)
    if callable(get_type):
        try:
            return str(get_type().Name)
        except Exception:
            pass
    return type(control).__name__


class Api:
    """화면에 내놓는 자리(`window.pywebview.api`). 공개 메서드만 화면에서 보입니다.

    창을 받는 일(`Zoom.attach`)은 여기 두지 않습니다 — 공개 메서드는 화면에서 부를 수
    있게 되기 때문입니다. 창은 `main.py` 가 `Zoom` 에 직접 넘깁니다.
    """

    def __init__(self, notifier: Notifier, zoom: Zoom | None = None) -> None:
        self._notifier = notifier
        self._zoom = zoom if zoom is not None else Zoom()

    def notify(self, payload: Any = None) -> bool:
        return self._notifier.notify(payload)

    def set_zoom(self, factor: Any = None) -> bool:
        """글씨 크기(배율)를 바꿉니다. 0.9·1·1.1·1.2 만 받습니다."""
        return self._zoom.set_zoom(factor)

    def get_zoom(self) -> float | None:
        """지금 글씨 크기(배율). 못 읽으면 `None` 입니다."""
        return self._zoom.get_zoom()


# ── Windows 구현 ─────────────────────────────────────


def _winforms_tray(window: Any, *, on_click: Callable[[], None], on_open: Callable[[], None]) -> Tray:
    if sys.platform != "win32":
        raise RuntimeError("Windows 에서만 운영체제 알림을 냅니다.")
    form = getattr(window, "native", None)
    if form is None:
        raise RuntimeError("창이 아직 없습니다.")
    title = str(getattr(window, "title", "") or "")
    return _WinFormsTray(form, title=title, on_click=on_click, on_open=on_open)


class _WinFormsTray:
    """WinForms `NotifyIcon`. 만들기와 치우기는 UI 스레드에 넘겨 돌립니다."""

    def __init__(
        self,
        form: Any,
        *,
        title: str,
        on_click: Callable[[], None],
        on_open: Callable[[], None],
    ) -> None:
        import ctypes

        import clr  # pywebview 가 Windows 에서 쓰는 pythonnet

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System import Action
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import Form, FormWindowState, NotifyIcon, ToolTipIcon

        self._form = form
        self._action = Action
        self._form_type = Form
        self._states = FormWindowState
        self._tips = ToolTipIcon
        self._user32 = ctypes.windll.user32
        self._user32.GetForegroundWindow.restype = ctypes.c_void_p
        self._icon: Any = None

        def create() -> None:
            icon = NotifyIcon()
            found = icon_path()
            if found is not None:
                icon.Icon = Icon(str(found))
            elif form.Icon is not None:
                icon.Icon = form.Icon
            else:
                icon.Icon = SystemIcons.Application
            # 알림 영역 아이콘의 설명 글자는 127자까지입니다.
            icon.Text = title[:127]
            icon.BalloonTipClicked += lambda *_: on_click()
            icon.DoubleClick += lambda *_: on_open()
            icon.Visible = True
            self._icon = icon

        self._call(create)

    def _call(self, work: Callable[[], None]) -> None:
        """UI 스레드에서 돌리고 끝날 때까지 기다립니다."""
        if self._form.InvokeRequired:
            self._form.Invoke(self._action(work))
        else:
            work()

    def post(self, work: Callable[[], None]) -> None:
        self._form.BeginInvoke(self._action(work))

    def is_front(self) -> bool:
        form = self._form
        if form.WindowState == self._states.Minimized or not form.Visible:
            return False
        handle = int(form.Handle.ToInt64())
        active = self._form_type.ActiveForm
        if active is not None and int(active.Handle.ToInt64()) == handle:
            return True
        return (self._user32.GetForegroundWindow() or 0) == handle

    def show(self, title: str, body: str, warning: bool) -> None:
        tip = self._tips.Warning if warning else self._tips.Info
        self._icon.ShowBalloonTip(BALLOON_MS, title, body, tip)

    def bring_front(self) -> None:
        form = self._form
        if form.WindowState == self._states.Minimized:
            form.WindowState = self._states.Normal
        form.Show()
        form.BringToFront()
        form.Activate()

    def dispose(self) -> None:
        icon, self._icon = self._icon, None
        if icon is None:
            return

        def drop() -> None:
            # 보이지 않게 한 뒤 치워야 알림 영역에 흔적이 남지 않습니다.
            icon.Visible = False
            icon.Dispose()

        try:
            if self._form.IsDisposed:
                drop()
            else:
                self._call(drop)
        except Exception:
            drop()
