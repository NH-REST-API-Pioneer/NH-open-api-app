"""실행을 세울 때 저장과 같은 정리를 거치고, 돌 수 없는 실행은 세우지 않습니다.

- 화면이 저장 전 설정을 보내도 시장에 없는 값(해외의 체결조건)이 실행에 실리지
  않습니다 — 종이 실행과 계좌 실행이 같은 설정으로 같은 결과를 냅니다.
- 국내 실행은 종이도 계좌도 체결조건이 비면 세우지 않습니다(같은 말).
- 저장된 전략 버전으로만 세우고, 그 버전의 시장과 다른 시장으로는 세우지 않습니다.
- 계좌 갈래는 확인창(`approved`)을 거쳐야 섭니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.**
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import journal as journal_lib, paper, runs, service as service_lib, validate
from backend.strategy.strategy_routes import get_service
from tests.test_strategy_service import (
    _더하기,
    _마스터,
    _모의목록,
    _모의물음,
    _물음,
    _설정,
    _시간표,
    _해외마스터,
    _해외물음,
    주소,
)


def _해외종이목록(tmp_path, **kwargs):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_해외마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        **kwargs,
    )


def _라우트(실행목록, 몸: dict):
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        return TestClient(app).post(주소, json=몸)
    finally:
        app.dependency_overrides.pop(get_service, None)


# ── 저장과 같은 정리 ─────────────────────────────────────


@pytest.mark.parametrize("조건", ["FOK", "FAK"])
def test_해외_초안의_체결조건은_종이_실행에도_실리지_않는다(tmp_path, 조건):
    실행목록 = _해외종이목록(tmp_path)
    물음 = _해외물음()
    물음["draft"]["aux"]["fillCond"] = 조건

    실행목록.add(**물음)

    엔진 = 실행목록._engine("run1")
    assert 엔진.aux.get("fillCond") == ""
    assert 엔진.run.draft["aux"]["fillCond"] == "", "저장된 실행 설정에도 빈칸입니다."
    엔진.book.last_price = 7000.0
    엔진._send(paper.BUY, 1, 7000.0, "entry", 1_000)
    (주문,) = 엔진.book.orders
    assert 주문.fill_condition == "", "종이 장부가 FOK/FAK 를 적용하지 않습니다."
    assert 물음["draft"]["aux"]["fillCond"] == 조건, "보낸 설정은 건드리지 않습니다."


def test_국내_실행은_적은_체결조건_그대로다(tmp_path):
    실행목록 = _모의목록(tmp_path)

    # 시장가는 FAS 만 받으므로 FOK 는 지정가에 붙입니다.
    실행목록.add(**_물음(draft=_설정(fillCond="FOK", orderType="지정가")))

    assert 실행목록._engine("run1").aux.get("fillCond") == "FOK"


# ── 국내 빈 체결조건 ─────────────────────────────────────


@pytest.mark.parametrize("갈래", [runs.PAPER, runs.SIM])
def test_국내_빈_체결조건은_종이도_계좌도_같은_말로_400(tmp_path, 갈래):
    실행목록 = _모의목록(tmp_path)
    몸 = _더하기()
    몸["draft"]["aux"]["fillCond"] = ""
    if 갈래 == runs.SIM:
        몸.update({"mode": "sim", "environment": "paper", "approved": True})

    답 = _라우트(실행목록, 몸)

    assert 답.status_code == 400
    줄들 = [one for one in 답.json()["detail"]["problems"] if one["field"] == "aux.fillCond"]
    assert [one["message"] for one in 줄들] == [validate.FILL_COND_WHY]
    assert 실행목록.rows() == []


# ── 전략 버전의 시장 ─────────────────────────────────────


def test_전략_버전과_다른_시장으로는_400(tmp_path):
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        markets=lambda version_id: "overseas",
    )

    답 = _라우트(실행목록, _더하기())

    assert 답.status_code == 400
    assert [(one["field"], one["message"]) for one in 답.json()["detail"]["problems"]] == [
        ("market", service_lib.WHY_VERSION_MARKET)
    ]
    assert 실행목록.rows() == []


@pytest.mark.parametrize(
    "시장들", [lambda version_id: "domestic", None], ids=["같음", "저장소없음"]
)
def test_전략_버전의_시장이_같으면_선다(tmp_path, 시장들):
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        markets=시장들,
    )

    assert _라우트(실행목록, _더하기()).status_code == 200


def _시장목록(tmp_path, 시장들):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        markets=시장들,
    )


def _터짐(version_id):
    raise OSError("못 읽음")


@pytest.mark.parametrize("시장들", [lambda version_id: "", _터짐], ids=["없는버전", "못읽음"])
def test_저장소에_없는_버전으로는_400(tmp_path, 시장들):
    """받아 주면 그 실행이 어느 시장 전략인지 맞춰 볼 길이 없습니다."""
    실행목록 = _시장목록(tmp_path, 시장들)

    답 = _라우트(실행목록, _더하기())

    assert 답.status_code == 400
    assert [(one["field"], one["message"]) for one in 답.json()["detail"]["problems"]] == [
        ("versionId", service_lib.WHY_VERSION_UNKNOWN)
    ]
    assert 실행목록.rows() == []


def test_앱의_실행_목록은_전략_저장소로_버전을_찾는다():
    assert service_lib.service._markets is service_lib._market_from_store


def test_실행에_담기는_설정은_정리된_것이다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    설정 = _설정()
    설정["evalMode"] = "모르는 방식"

    실행목록.add(**_물음(draft=설정))

    assert 실행목록._engine("run1").run.draft["evalMode"] == "마감"
    assert 설정["evalMode"] == "모르는 방식", "보낸 설정은 건드리지 않습니다."


def test_해외_빈_체결조건_종이_실행은_그대로_선다(tmp_path):
    실행목록 = _해외종이목록(tmp_path)

    줄 = 실행목록.add(**_해외물음())

    assert 줄["market"] == "overseas"
    assert 실행목록._engine("run1").run.draft["aux"]["fillCond"] == ""


# ── 확인창 ───────────────────────────────────────────────


def test_승인된_모의_실행은_그대로_선다(tmp_path):
    실행목록 = _모의목록(tmp_path)

    줄 = 실행목록.add(**_모의물음())

    assert 줄["mode"] == runs.SIM and 줄["approvedAt"] is not None


def test_종이_실행은_승인이_없어도_선다(tmp_path):
    실행목록 = _모의목록(tmp_path)

    답 = _라우트(실행목록, {**_더하기(), "approved": False})

    assert 답.status_code == 200 and 답.json()["mode"] == runs.PAPER
