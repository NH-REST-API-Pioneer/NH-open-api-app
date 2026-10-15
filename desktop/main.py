"""데스크톱 앱 진입점.

백엔드(FastAPI)를 백그라운드 스레드로 띄운 뒤, 시스템 웹뷰 창으로 프론트엔드를 표시합니다.
백엔드를 별도 프로세스가 아닌 스레드로 실행하므로 단일 실행 파일로 패키징해도 프로세스가 하나만 뜹니다.
"""
import logging
import socket
import sys
import threading
from pathlib import Path

import uvicorn
import webview

# PyInstaller로 패키징된 경우 프로젝트 루트가 sys.path에 없으므로 직접 추가합니다.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import HOME_DIR  # noqa: E402
from backend.main import app  # noqa: E402
from desktop.notify import (  # noqa: E402
    DESKTOP_STATE_PATH,
    Api,
    Notifier,
    Zoom,
    read_desktop_state,
    update_desktop_state,
)

log = logging.getLogger(__name__)

WINDOW_TITLE = "NH FUTURES API"

#: 지난번 포트로 받아들이는 범위. 1024 아래는 널리 알려진 서비스의 자리라 받지 않습니다.
PORT_MIN = 1024
PORT_MAX = 65535

#: 포트가 비었는지 볼 때 붙여 보는 주소. Windows 는 다른 프로그램이 0.0.0.0 에서 받는
#: 포트라도 127.0.0.1 로는 붙일 수 있게 해 주므로, 127.0.0.1 만 보면 남의 포트를 함께
#: 쓰게 될 수 있습니다. 그래서 둘 다 봅니다.
PROBE_HOSTS = ("127.0.0.1", "0.0.0.0")

#: 새 포트를 고를 때 먼저 차례로 살펴보는 구간.
#:
#: 운영체제는 다른 프로그램이 밖으로 연결할 때 49152~65535 의 번호를 돌려 가며 나눠
#: 줍니다. 그 구간의 포트를 기억해 두면, 다음 실행 때 마침 다른 프로그램의 연결이 그
#: 번호를 쓰고 있어 새 포트로 뜨는 일이 생깁니다. 그 구간 밖의 이 번호들은 그렇게 쓰이는
#: 일이 드물어, 다음 실행에서도 같은 포트로 뜰 가능성이 높습니다. 구간이 전부 막혀 있으면
#: 운영체제가 주는 빈 포트를 씁니다.
PREFERRED_PORTS = range(47100, 47200)


def port_is_free(port: int) -> bool:
    """이 컴퓨터에서 아무도 `port` 를 쓰지 않으면 `True` 입니다.

    `PROBE_HOSTS` 의 주소마다 붙여 보기만 하고 바로 놓습니다(연결을 받지는 않습니다).
    """
    for host in PROBE_HOSTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                return False
    return True


def _new_port() -> int:
    """새 포트. `PREFERRED_PORTS` 의 첫 빈 포트, 전부 막혀 있으면 운영체제가 골라 주는 빈 포트."""
    for port in PREFERRED_PORTS:
        if port_is_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def pick_port(remembered: object) -> int:
    """화면을 열 포트. 지난번 포트를 먼저 쓰고, 막혀 있으면 새 포트입니다.

    화면의 브라우저 저장소(최근 본 종목, 사이드바, 칸 크기 같은 화면 설정)는 주소의
    호스트와 포트마다 따로 있습니다. 실행마다 포트가 바뀌면 지난번에 남긴 값이 보이지
    않으므로, 지난번 포트를 다시 써서 같은 저장소를 이어 씁니다.

    고정 포트를 쓰지 않는 까닭은 그대로입니다 — 그 포트를 다른 프로그램이 쓰고 있으면
    부딪치므로, 지난번 포트가 막혀 있으면 새 빈 포트(`_new_port`)로 엽니다. 그때는
    화면 설정이 처음 상태로 보입니다.

    `remembered` 가 1024~65535 의 정수가 아니면(없음·글자·참거짓·범위 밖) 새 포트입니다.
    """
    if (
        isinstance(remembered, int)
        and not isinstance(remembered, bool)
        and PORT_MIN <= remembered <= PORT_MAX
        and port_is_free(remembered)
    ):
        return remembered
    return _new_port()


def choose_port(path: Path | None = None) -> int:
    """지난번 포트를 읽어 포트를 고르고, 고른 포트를 기억해 둡니다.

    기억은 `path`(기본 `DESKTOP_STATE_PATH`)의 `port` 항목만 바꾸고 다른 항목(글씨 크기)은
    그대로 둡니다. 파일에 못 써도 앱은 고른 포트로 뜹니다.
    """
    path = path if path is not None else DESKTOP_STATE_PATH
    remembered = read_desktop_state(path).get("port")
    port = pick_port(remembered)
    if port != remembered:
        try:
            update_desktop_state(path, port=port)
        except Exception:
            log.warning("포트를 기억하지 못했습니다. 다음에 켤 때 다른 포트로 뜰 수 있습니다.", exc_info=True)
    return port


def main() -> None:
    port = choose_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # 서버가 실제로 요청을 받을 수 있게 된 뒤에 창을 열어야 빈 화면이 뜨지 않습니다.
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("백엔드 서버 기동에 실패했습니다.")
        threading.Event().wait(0.05)

    # 최소 크기입니다. 가로와 세로가 약속하는 것이 다릅니다.
    #
    # 가로 1200 은 바닥입니다 — 이 아래로는 못 줄입니다. 일반주문 화면의 기본
    # 배치가 부르는 폭은 919(왼쪽 열 415 + 호가 200 + 주문 280 + 사이 간격 24)로
    # 넉넉하지만, 카드를 끌어 가장 넓게 벌린 배치는 1099 를 부릅니다
    # (max(호가 200, 주문 280) + 주문내역 415 + 차트 380 + 사이 간격 24).
    # 여기에 왼쪽 아이콘 레일 48 과 본문 여백 24 를 더한 1171 이 1200 의 근거입니다.
    # 더 줄이면 호가와 주문 입력이 나란히 서지 못하고 화면이 가로로 밀립니다.
    # 호가를 보면서 주문 가격을 넣는 것이 이 화면의 기본 동작이라, 그 둘이
    # 갈라지면 쓸 수 없는 창입니다.
    #
    # 세로 720 도 창을 그 아래로는 못 줄이게 막지만, 가로와 달리 「화면이 다
    # 들어간다」를 약속하지는 않습니다. 기본 배치가 세로로 안 밀리려면 일반주문
    # 격자에 579 가 필요하고(차트 바닥 355 + 경계 12 + 아래 칸 212), 창으로는
    # 789 가 듭니다 — 720 에서는 69 가 모자랍니다. 789 로 올리면 1366x768
    # 노트북에서 창이 화면보다 커지는데, 그 사람에게는 세로 스크롤보다 나쁜
    # 결과입니다. 그래서 720 으로 두고 모자란 만큼은 화면이 세로로 스크롤해서
    # 받습니다. 카드가 뭉개지지는 않습니다.
    # 전략 실행 알림을 운영체제 알림으로도 냅니다. 화면이 `window.pywebview.api.notify`
    # 로 부르고, 알림 영역 아이콘은 창이 뜬 뒤 만들어 창이 닫힐 때 치웁니다.
    notifier = Notifier()
    # 화면의 글씨 크기를 창 안 웹뷰 배율로 바꿉니다. 창은 뜬 뒤에 넘깁니다.
    # 지난번에 고른 배율은 창을 넘길 때 다시 겁니다. 창이 막 뜬 때에는 웹뷰가 아직
    # 준비 전일 수 있어, 화면을 다 불러온 뒤(`loaded`)에도 한 번 더 겁니다.
    zoom = Zoom()
    window = webview.create_window(
        WINDOW_TITLE,
        f"http://127.0.0.1:{port}",
        width=1280,
        height=800,
        min_size=(1200, 720),
        js_api=Api(notifier, zoom),
    )
    window.events.shown += lambda: notifier.attach(window)
    window.events.shown += lambda: zoom.attach(window)
    window.events.loaded += lambda: zoom.apply_remembered()
    window.events.closing += lambda: notifier.dispose()
    # 웹뷰의 저장소를 사용자 홈에 둡니다.
    #
    # 기본값은 비공개 모드라 창을 닫는 순간 브라우저 저장소가 비워집니다.
    # 관심종목과 화면 배치가 지금 그 저장소에 있어서, 그대로 두면 앱을 껐다
    # 켤 때마다 담아 둔 종목과 옮겨 둔 카드가 처음 상태로 돌아갑니다.
    #
    # 자리는 설정 파일과 같은 뿌리입니다 — 앱이 사용자 홈에 남기는 것은 전부
    # `HOME_DIR` 아래이고, 뿌리를 한 곳에서만 정해야 둘이 갈라지지 않습니다.
    #
    # 백엔드가 관심종목과 배치를 파일로 옮기면 이 저장소는 그때 다시 볼 자리입니다.
    storage = HOME_DIR / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))

    server.should_exit = True


if __name__ == "__main__":
    main()
