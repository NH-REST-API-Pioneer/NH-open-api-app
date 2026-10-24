"""화면이 기억해 두는 것 — 관심종목과 화면 배치.

사용자가 고른 것을 브라우저가 아니라 사용자 홈의 파일에 남깁니다. 브라우저에
두면 저장소를 비우거나 다른 브라우저로 열었을 때 관심종목이 사라집니다.

    ~/NHFutures/state/ui.json

**저장해 둔 응답으로 도는 앱(`NH_REPLAY=1`)은 따로 씁니다** —
`~/NHFutures/state-replay/ui.json`. 확인하려고 바꾼 배치가 실서버로 띄운 창에
올라오지 않게 합니다. 그 파일이 없으면 빈 값에서 시작하고, 실서버 쪽 파일을
가져오지 않습니다. 다만 같은 브라우저 주소로 두 앱을 번갈아 띄우면, 브라우저에
남아 있던 옛 값이 먼저 뜬 쪽 파일로 옮겨질 수 있습니다(아래 「옮긴 것」).

파일에는 **쓴 앱**을 함께 적습니다. 다른 앱이 쓴 파일을 만나면 담긴 값을 쓰지
않고 빈 것으로 시작하며, 다음에 담을 때 이 앱의 것으로 새로 씁니다.

**담는 것은 「무엇을 어떻게 볼지」이지 값이 아닙니다.** 시세나 잔고는 화면을
나갔다 오면 낡은 것이라, 돌아왔을 때 옛 값이 새 값인 척하면 그게 더 나쁩니다.

**인증 정보는 여기 담지 않습니다.** APP Key 와 접속 토큰은 `config/` 아래에
있고, 그 폴더는 밖으로 내보내면 안 되는 자리입니다.

## 옮긴 것과 브라우저에 남는 것

화면이 기억하는 것이 전부 이 파일로 오는 것은 아닙니다. 가르는 기준은
**「사람을 따라가야 하는가, 이 기기에 남아야 하는가」** 입니다.

옮긴 것 — 다른 기기에서도 그대로여야 하는 것

    nh.home.watch          홈 관심종목
    nh.trade.layout        일반주문 화면 배치
    nh.trade.drawings      차트에 그린 것
    nh.trade.indicators    차트 지표 설정
    nh.trade.split         차트 분할
    nh.alerts              전략 실행 알림 설정

브라우저에 남는 것 — 그 화면, 그 창에서만 뜻이 있는 것

    nh.theme                     밝기
    nh.recent                    최근 본 종목
    nh.sidebar.open              사이드바 펼침
    nh.instruments.navWidth      종목 화면 목록 폭
    nh.instruments.openGroups    종목 화면 펼친 무리
    nh.trade.chartBottomOpen     차트 아래 칸 펼침
    nh.trade.chainBottomOpen     옵션 아래 칸 펼침

이름을 브라우저에서 쓰던 것 그대로 둡니다. 화면 코드에서 본 이름을 파일에서
그대로 찾을 수 있어야 어느 값이 어디로 갔는지 헷갈리지 않습니다.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from backend.nh_api.session import current_mode
from backend.storage import MISSING, OK, ORIGIN, from_other_app, read_json, state_dir, write_json

logger = logging.getLogger(__name__)

#: 앱이 뜰 때 한 번 정합니다. 재생인지는 도는 동안 바뀌지 않습니다.
STATE_DIR = state_dir()
UI_PATH = STATE_DIR / "ui.json"

# 파일 형식. 담는 것이 달라지면 올립니다.
VERSION = 1

#: 이 파일에 담는 항목. 여기 없는 이름은 받지 않습니다.
STORED_KEYS = (
    "nh.home.watch",
    "nh.trade.layout",
    "nh.trade.drawings",
    "nh.trade.indicators",
    "nh.trade.split",
    "nh.alerts",
)

#: 브라우저에 남기는 항목. 여기서 쓰지는 않고, 무엇을 안 옮겼는지 적어 둡니다.
DEVICE_KEYS = (
    "nh.theme",
    "nh.recent",
    "nh.sidebar.open",
    "nh.instruments.navWidth",
    "nh.instruments.openGroups",
    "nh.trade.chartBottomOpen",
    "nh.trade.chainBottomOpen",
)

# 값 하나와 파일 전체의 크기 상한. 차트에 그린 것이 계속 쌓일 수 있어 막아
# 둡니다. 넘으면 저장을 거절하고, 화면은 이번 세션 값을 그대로 씁니다.
MAX_VALUE_BYTES = 256 * 1024
MAX_DOCUMENT_BYTES = 1024 * 1024


#: 못 담은 까닭의 갈래. **화면이 이 값으로 갈래를 가릅니다.**
#:
#: 문장으로 가르면 안 됩니다 — `message` 는 사람이 읽는 말이라 다듬는 자리인데,
#: 화면이 그 글자를 보고 갈래를 정하면 문장을 다듬을 때마다 화면의 갈림이 소리
#: 없이 어긋납니다.
#:
#: `size` 담을 수 있는 크기를 넘음 · `key` 이 파일에 담지 않는 이름 · `value`
#: 담을 수 없는 값 · `write` 파일에 쓰지 못함(앞의 셋과 달리 보낸 값 탓이 아닙니다).
SIZE = "size"
KEY = "key"
VALUE = "value"
WRITE = "write"


class UiStateError(Exception):
    """받을 수 없는 값일 때 발생합니다. `code` 가 어느 갈래인지 말합니다."""

    def __init__(self, message: str, code: str = VALUE) -> None:
        super().__init__(message)
        self.code = code


class UiStore:
    """화면 상태 파일 하나."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else UI_PATH
        # 요청은 여러 스레드에서 동시에 들어옵니다. 파일을 읽고 합쳐 쓰는
        # 동안에는 하나만 들어오게 합니다.
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        """지금 담겨 있는 것.

        `stored` 는 **파일이 있었는지**입니다. 화면이 브라우저에 남은 값을 한
        번 옮겨 담을지 정하는 근거라, 「없음」과 「비어 있음」을 갈라야 합니다.
        """
        with self._lock:
            return self._current()

    def patch(self, values: dict[str, Any]) -> dict[str, Any]:
        """보내 온 항목만 바꿉니다. 나머지는 파일에 있던 값을 그대로 둡니다.

        한 화면이 한 항목만 고쳐도 다른 화면의 값을 덮어쓰지 않도록 부분
        갱신만 받습니다.

        Raises:
            UiStateError: 모르는 항목 이름이거나 값이 너무 큰 경우.
            OSError: 파일을 쓰지 못한 경우.
        """
        self._check(values)

        with self._lock:
            if not values:
                # 바꿀 것이 없으면 파일을 만들지 않습니다. 빈 요청이 파일을
                # 만들어 버리면 「아직 아무것도 담지 않았다」가 거짓이 됩니다.
                return self._current()
            return self._apply(values)

    def import_missing(self, values: dict[str, Any]) -> dict[str, Any]:
        """예전에 브라우저에 남아 있던 값을 **아직 비어 있는 항목만** 채웁니다.

        옮기는 것은 화면이 하지만, 「덮지 않는다」는 여기서 지킵니다. 이미 담긴
        항목은 어떤 경우에도 그대로 둡니다 — 옛 브라우저 값이 그 뒤에 고친 값을
        덮어쓰는 일이 화면의 판단에 달리지 않게 하려는 것입니다.

        **항목마다 따로 봅니다.** 「파일이 있으면 아무것도 안 함」으로 두면, 화면이
        옮기기 전에 무엇이든 한 번 저장하는 순간(차트 분할 하나만 바꿔도) 파일이
        생겨서 관심종목이 영영 안 옮겨집니다. 항목 단위로 보면 부르는 순서와
        상관없고, 두 번 불러도 안전합니다.

        채운 항목의 이름을 `imported` 에 담아 돌려줍니다.

        Raises:
            UiStateError: 모르는 항목 이름이거나 값이 너무 큰 경우.
            OSError: 파일을 쓰지 못한 경우.
        """
        self._check(values)

        with self._lock:
            current = self._current()
            # 파일에 아직 없는 항목만 받습니다. 있는 값은 덮지 않습니다.
            missing = {
                key: value for key, value in values.items() if key not in current["values"]
            }
            if not missing:
                return {**current, "imported": []}
            return {**self._apply(missing), "imported": sorted(missing)}

    # -- 아래 둘은 **락을 쥔 채로** 부릅니다 -------------------------------
    #
    # 읽고, 합치고, 쓰는 세 걸음이 한 덩어리여야 합니다. 중간에 다른 요청이
    # 끼어들면 둘 다 같은 내용을 읽고 각자 제 항목만 얹어 쓰기 때문에, 나중에
    # 쓴 쪽이 앞선 쪽의 항목을 지웁니다. 화면 하나가 배치와 그린 것을 동시에
    # 보내는 것만으로도 일어납니다 — 요청을 처리하는 스레드가 여럿입니다.

    def _current(self) -> dict[str, Any]:
        loaded, status = read_json(self.path)
        other = _other_app(loaded)
        values = {} if other else loaded.get("values")
        if not isinstance(values, dict):
            values = {}
        return {
            "version": VERSION,
            "stored": status == OK and not other,
            "status": status,
            "values": values,
            # 다른 앱이 쓴 파일이면 그 앱 이름. 담긴 값은 쓰지 않았습니다.
            "otherApp": other,
        }

    def _apply(self, values: dict[str, Any]) -> dict[str, Any]:
        loaded, _ = read_json(self.path)
        other = _other_app(loaded)
        if other:
            # 다른 앱의 배치는 이 앱에서 쓰지 않던 값이라 이어받지 않고 새로 씁니다.
            logger.warning(
                "화면 상태 파일을 다른 앱(%s)이 남겼습니다: %s. 담긴 것을 쓰지 않고 새로 씁니다.",
                other,
                self.path,
            )
        kept = {} if other else loaded.get("values")
        if not isinstance(kept, dict):
            kept = {}

        # 모르는 이름이 파일에 이미 있으면 지우지 않고 그대로 둡니다. 새 판이
        # 담아 둔 것을 옛 판이 열었다고 해서 지워 버리면 안 됩니다.
        merged = {**kept, **values}
        self._check_document(merged)

        # 어느 앱이 썼는지. 다른 앱은 이 파일의 값을 안 씁니다(`storage.from_other_app`).
        write_json(self.path, {"version": VERSION, ORIGIN: current_mode(), "values": merged})
        return {"version": VERSION, "stored": True, "status": OK, "values": merged, "otherApp": None}

    def _check(self, values: dict[str, Any]) -> None:
        if not isinstance(values, dict):
            raise UiStateError("담을 항목이 올바르지 않습니다.", VALUE)

        for key, value in values.items():
            if key not in STORED_KEYS:
                raise UiStateError(f"이 파일에 담지 않는 항목입니다: {key}", KEY)
            if _size(value) > MAX_VALUE_BYTES:
                raise UiStateError(f"항목이 너무 큽니다: {key}", SIZE)

    @staticmethod
    def _check_document(merged: dict[str, Any]) -> None:
        if _size(merged) > MAX_DOCUMENT_BYTES:
            raise UiStateError("담을 수 있는 크기를 넘었습니다.", SIZE)


def _other_app(loaded: Any) -> str | None:
    """다른 앱이 쓴 파일이면 그 앱 이름. 표지가 없는 옛 파일은 이 앱의 것입니다."""
    if not from_other_app(loaded, current_mode()):
        return None
    return str(loaded.get(ORIGIN) or "").strip() or None


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise UiStateError("담을 수 없는 값입니다.", VALUE) from exc


#: 앱이 쓰는 자리. 테스트는 임시 폴더를 쓰는 것으로 바꿔 끼웁니다.
store = UiStore()

__all__ = [
    "DEVICE_KEYS",
    "MAX_DOCUMENT_BYTES",
    "MAX_VALUE_BYTES",
    "MISSING",
    "STATE_DIR",
    "STORED_KEYS",
    "UI_PATH",
    "VERSION",
    "UiStateError",
    "SIZE",
    "KEY",
    "VALUE",
    "WRITE",
    "UiStore",
    "store",
]
