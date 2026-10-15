"""`/api/ui` 라우트 — 화면이 기억해 두는 것을 읽고 씁니다.

**주소에 시장 칸이 없습니다.** `/api/{시장}/{API 이름}` 은 NH선물 서버에 그대로
물어보는 거래 API 의 규칙입니다. 여기 담기는 것은 NH선물에 없는 우리 파일이라
국내·해외로 나뉘지 않습니다. `/api/health`, `/api/config`, `/api/master/…` 도
같은 자리입니다. 규칙에 맞춘다며 `/api/domestic/ui` 같은 주소로 옮기지 마세요.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.ui import ui_store as ui_store_codes
from backend.ui.ui_store import UiStateError, UiStore, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui", tags=["ui"])

#: 화면 상태를 못 담았을 때 사용자가 읽는 한 문장. **갈래마다 다른 말을 하지
#: 않습니다** — 어느 갈래든 사용자가 할 일이 같고(없고), 달라지는 것은 다음에 열
#: 때 자리가 그대로인지뿐입니다. 어느 갈래였는지는 답의 `code` 가 말합니다.
NOT_STORED = "화면 상태를 담지 못했습니다. 다음에 열 때 자리가 지금과 다를 수 있습니다."


def get_store() -> UiStore:
    """앱이 쓰는 자리. 테스트는 이 의존성을 바꿔 임시 폴더를 쓰게 합니다."""
    return store


class UiPatch(BaseModel):
    """바꿀 항목만 담습니다. 빠진 항목은 파일에 있던 값이 그대로 남습니다."""

    values: dict[str, Any]


@router.get("")
def read_ui(ui: UiStore = Depends(get_store)) -> dict[str, Any]:
    """담겨 있는 것과, 파일이 있었는지.

    파일을 읽지 못했을 때도 정상으로 답합니다. 「못 읽었다」는 것도 화면이
    알아야 하는 상태이고, 여기서 오류로 만들면 화면이 아예 안 뜹니다.
    """
    return ui.read()


@router.patch("")
def write_ui(patch: UiPatch, ui: UiStore = Depends(get_store)) -> dict[str, Any]:
    """보내 온 항목만 파일에 씁니다.

    Raises:
        HTTPException: 모르는 항목이거나 너무 큰 경우 400, 쓰지 못한 경우 500.
    """
    return _write(lambda: ui.patch(patch.values))


@router.post("/import")
def import_ui(patch: UiPatch, ui: UiStore = Depends(get_store)) -> dict[str, Any]:
    """예전에 브라우저에 남아 있던 값을 옮겨 받습니다.

    **이미 담긴 항목은 그대로 둡니다.** 비어 있는 항목만 채우고, 실제로 채운
    항목의 이름을 `imported` 에 담아 답합니다.

    항목마다 따로 보므로 **언제 불러도 됩니다.** 다른 저장보다 먼저 부르든
    나중에 부르든 결과가 같고, 두 번 불러도 안전합니다.

    Raises:
        HTTPException: 모르는 항목이거나 너무 큰 경우 400, 쓰지 못한 경우 500.
    """
    return _write(lambda: ui.import_missing(patch.values))


def _write(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """저장을 해 보고, 못 하면 **까닭과 갈래를 함께** 냅니다.

    답의 `detail` 은 `{message, code}` 입니다. 화면은 `code` 로 갈래를 가르고
    `message` 는 사람에게 보여 줄 때만 씁니다 — 까닭은 `ui_store` 의 갈래 값에
    적어 두었습니다.
    """
    try:
        return action()
    except UiStateError as exc:
        # **항목 이름은 기록에만 남깁니다** — 화면이 보낸 이름이라 사용자가 고칠
        # 것이 아니고, 고칠 자리를 찾는 사람에게는 기록이 더 쓸모 있습니다.
        logger.warning("화면 상태를 담지 못했습니다: %s", exc)
        raise HTTPException(
            status_code=400, detail={"message": NOT_STORED, "code": exc.code}
        ) from exc
    except OSError as exc:
        # 원본 문구를 그대로 내보내지 않습니다. 경로에 사용자 이름이 들어 있습니다.
        logger.warning("화면 상태 파일을 쓰지 못했습니다: %s", exc)
        raise HTTPException(
            status_code=500,
            # **보낸 값 탓이 아닙니다** — 앞의 갈래 셋과 달리 파일을 못 쓴 것이라
            # 따로 말합니다. 같은 값을 다시 보내도 같은 답이 옵니다.
            detail={"message": NOT_STORED, "code": ui_store_codes.WRITE},
        ) from exc
