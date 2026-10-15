"""시험이 사용자 홈의 상태 파일을 안 보는지.

앱이 쓰는 저장소는 싱글턴 하나이고 시험도 그것을 그대로 씁니다. 돌려 두지
않으면 시험 결과가 그때 `~/NHFutures/state/` 에 무엇이 담겨 있는지에 따라
갈리고, 시험이 사용자의 실행 목록을 덮어쓸 수도 있습니다.

**여기서는 사용자 홈을 읽지도 쓰지도 않습니다** — 자리가 어디를 가리키는지만
봅니다. 확인하려고 그 폴더에 무언가를 만드는 순간 이 시험이 스스로 하지 말라는
일을 하게 됩니다.
"""
from __future__ import annotations

import json

from backend.config import HOME_DIR
from backend.strategy import journal as journal_lib
from backend.strategy import limits as limits_lib
from backend.strategy import runs as runs_lib
from backend.strategy import service as service_lib
from backend.strategy import store as store_lib
from backend.ui import ui_store


def _자리들():
    return {
        "실행": runs_lib.store.path,
        "거래 기록": journal_lib.journal.path,
        "손실 한도": limits_lib.store.path,
        "전략 목록": store_lib.store.path,
        # 전략 것은 아니지만 같은 폴더이고, 라우트가 이 싱글턴을 그대로 씁니다.
        "화면 상태": ui_store.store.path,
    }


def test_앱이_쓰는_자리가_전부_사용자_홈_밖이다():
    집 = HOME_DIR.resolve()

    안에것 = {
        이름: 자리
        for 이름, 자리 in _자리들().items()
        if 집 == 자리.resolve().parent or 집 in 자리.resolve().parents
    }

    assert 안에것 == {}, 안에것


def test_다섯이_한_폴더에_모인다():
    """하나만 돌려 두면 나머지가 홈에 남습니다."""
    부모들 = {자리.parent for 자리 in _자리들().values()}

    assert len(부모들) == 1, _자리들()


def test_앱이_쓰는_실행_목록은_돌려_둔_파일을_읽는다():
    """자리만 바꾼 것이 아니라 **그 자리를 실제로 읽는지**까지 봅니다."""
    runs_lib.store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "runs": [
                    {
                        "id": "돌려둔것",
                        "version_id": "v1",
                        "code": "A7569000",
                        "session": "domestic-day",
                        "market": "domestic",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        읽은것 = service_lib.RunService().store.read()
    finally:
        runs_lib.store.path.unlink(missing_ok=True)

    assert [one.id for one in 읽은것] == ["돌려둔것"]
