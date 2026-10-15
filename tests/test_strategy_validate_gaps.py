"""받기만 하던 칸 셋도 저장·시작 검사가 봅니다.

- 단계 잇기(`join`)는 「모두 충족」(`all`)·「하나라도 충족」(`any`) 둘뿐입니다. 판정과
  같은 묶음(`rules.STEP_JOINS`)을 봅니다. 칸이 없거나 비면 `all` 입니다.
- 보유 중 추가 진입(`addWhileOpen`)·세션 끝 정리(`sessionEndFlat`)는 켜기·끄기(참·거짓)만
  받습니다. 칸이 없으면 끈 것입니다.

틀린 값을 받아 주면 판정은 말없이 `all` 로, 켜기 칸은 글자 「false」 도 켠 것으로 읽습니다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import rules, validate
from backend.strategy.strategy_routes import get_service
from tests.test_strategy_service import _더하기, _모의목록, _설정, 주소


def _줄들(draft: dict) -> list[tuple[str, str]]:
    return [
        (one["field"], one["message"])
        for one in validate.problems(draft, market="domestic")
        if one["severity"] == validate.ERROR
    ]


def _잇기(값) -> dict:
    설정 = _설정()
    단계 = 설정["rules"]["buyEntry"]["steps"][0]
    if 값 is _없음:
        단계.pop("join", None)
    else:
        단계["join"] = 값
    return 설정


_없음 = object()


@pytest.mark.parametrize("값", ["or", "AND", "모두", 1, True])
def test_단계_잇기가_둘_밖이면_그_단계_칸을_짚는다(값):
    assert _줄들(_잇기(값)) == [("rules.buyEntry.steps.0.join", validate._JOIN)]


@pytest.mark.parametrize(
    "값", ["all", "any", "", None, _없음], ids=["all", "any", "빈칸", "None", "칸없음"]
)
def test_단계_잇기가_둘이거나_비면_통과한다(값):
    assert _줄들(_잇기(값)) == []


def test_판정과_검사가_같은_묶음을_본다():
    assert validate.STEP_JOINS is rules.STEP_JOINS
    assert [rules.join_of({"join": one}) for one in ("any", "all", "", None, "or")] == [
        "any", "all", "all", "all", "all",
    ]


def test_검사는_그_묶음을_읽는다(monkeypatch):
    """묶음이 늘면 검사도 따라 받습니다 — 검사가 제 목록을 따로 들고 있지 않습니다."""
    monkeypatch.setattr(validate, "STEP_JOINS", (*rules.STEP_JOINS, "or"))

    assert _줄들(_잇기("or")) == []


@pytest.mark.parametrize("칸", ["addWhileOpen", "sessionEndFlat"])
@pytest.mark.parametrize("값", ["yes", "false", 1, 0])
def test_켜기_칸은_참_거짓만_받는다(칸, 값):
    설정 = _설정(**{칸: 값, "sessionEndMinutes": "10"})

    assert _줄들(설정) == [(f"aux.{칸}", validate._SWITCH)]


@pytest.mark.parametrize("값", [True, False, None])
def test_켜기_칸이_참_거짓이거나_없으면_통과한다(값):
    설정 = _설정(addWhileOpen=값, sessionEndFlat=값, sessionEndMinutes="10")

    assert _줄들(설정) == []


def test_세션_끝_정리가_참_거짓이_아니면_분_칸까지_짚지_않는다():
    설정 = _설정(sessionEndFlat=1)
    설정["aux"].pop("sessionEndMinutes", None)

    assert _줄들(설정) == [("aux.sessionEndFlat", validate._SWITCH)]


def test_세션_끝_정리를_켜고_분이_없으면_지금처럼_분_칸을_짚는다():
    설정 = _설정(sessionEndFlat=True)
    설정["aux"].pop("sessionEndMinutes", None)

    assert _줄들(설정) == [("aux.sessionEndMinutes", validate._SESSION_END_MINUTES)]


def test_세_칸이_없는_옛_저장본은_그대로_통과한다():
    설정 = _설정()
    for 칸 in ("addWhileOpen", "sessionEndFlat"):
        설정["aux"].pop(칸, None)
    for 규칙 in 설정["rules"].values():
        for 단계 in 규칙.get("steps") or []:
            단계.pop("join", None)

    assert _줄들(설정) == []


def test_틀린_단계_잇기로는_실행을_세우지_않는다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    몸 = _더하기()
    몸["draft"] = _잇기("or")
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        답 = TestClient(app).post(주소, json=몸)
    finally:
        app.dependency_overrides.pop(get_service, None)

    assert 답.status_code == 400
    assert ("rules.buyEntry.steps.0.join", validate._JOIN) in [
        (one["field"], one["message"]) for one in 답.json()["detail"]["problems"]
    ]
    assert 실행목록.rows() == []
