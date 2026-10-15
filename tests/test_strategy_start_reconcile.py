"""갓 세운 계좌 실행이 곧바로 중지로 내려앉지 않게.

계좌 실행(모의·실전)은 세울 때 봉을 받고 첫 대사를 지나 감시로 열립니다. 그 사이에
다른 길의 대사(감시 고리, 재접속 뒤 다시 받기)가 끼어들면, 갓 세운 실행이 「재접속
뒤 대사」로 읽혀 중지로 내려앉았습니다. 그 시장의 연결이 모두 닫힌 뒤 새로 선 연결이
「다시 붙음」으로 알려지던 것도 같은 결과였습니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 계좌 조회와 봉 조회는 가짜입니다.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.realtime.feeds import Feed
from backend.realtime.link import LIVE, RECONNECTING
from backend.strategy import pump as pump_lib, runs, service as service_lib
from tests.test_realtime_stream import 허브
from tests.test_strategy_pump import _허브
from tests.test_strategy_service import _모의목록, _모의물음

시작 = 1_000


def _글(실행목록, run_id: str = "run1") -> list[str]:
    return [one["text"] for one in 실행목록._engine(run_id).events]


def _끼우며_받기(실행목록, 끼울것) -> None:
    """봉을 받는 동안(세우는 중) 다른 길의 대사를 한 번 끼웁니다."""

    def 받기(run, minutes, count):
        끼울것(실행목록, run)
        return []

    실행목록._fetch = 받기


# ── 세우는 중에는 다른 길의 대사가 끼어들지 않는다 ──────────


def test_감시_고리는_세우는_중인_실행을_집지_않는다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    집은것: list[list[str]] = []

    def 감시_한_박자(목록, run):
        ids = 목록.reconcile_wanted()
        집은것.append(ids)
        for run_id in ids:
            목록.reconcile(run_id, 시작)

    _끼우며_받기(실행목록, 감시_한_박자)

    실행목록.add(**_모의물음())

    assert 집은것 == [[]], "세우는 중인 실행은 대사를 기다리는 목록에 없습니다."
    assert 실행목록._engine("run1").run.state == runs.ARMED
    assert _글(실행목록).count(service_lib.RECONCILE_DONE) == 1
    assert service_lib.WHY_NO_RESUME not in _글(실행목록)


def test_다시_받기_길의_대사도_세우는_중이면_아무것도_안_한다(tmp_path):
    """펌프의 다시 받기 길은 대사를 기다리는 목록을 거치지 않고 대사를 바로 부릅니다."""
    실행목록 = _모의목록(tmp_path)
    상태: list[str] = []

    def 다시_받기(목록, run):
        목록.reconcile(run.id, 시작)  # first=False — 재접속 뒤 대사의 길
        상태.append(목록._engine(run.id).run.state)

    _끼우며_받기(실행목록, 다시_받기)

    실행목록.add(**_모의물음())

    assert 상태 == [runs.RECONCILING], "끼어든 대사는 상태를 바꾸지 않습니다."
    assert _글(실행목록).count(service_lib.RECONCILE_START) == 1, "맞춰 보는 중 줄은 세우는 쪽 하나뿐"
    assert 실행목록._engine("run1").run.state == runs.ARMED
    assert service_lib.WHY_NO_RESUME not in _글(실행목록)


def test_세우다_터져도_세우는_중_표지가_남지_않는다(tmp_path, monkeypatch):
    실행목록 = _모의목록(tmp_path)

    def 터짐(made, at):
        raise RuntimeError("계좌 조회 실패")

    monkeypatch.setattr(실행목록, "_compare", 터짐)

    with pytest.raises(RuntimeError):
        실행목록.add(**_모의물음())

    assert 실행목록._starting == set()
    assert 실행목록.reconcile_wanted() == ["run1"], "남은 실행은 감시 고리가 다시 집습니다."


def test_되살린_실행은_감시_고리가_지금처럼_집는다(tmp_path):
    _모의목록(tmp_path).add(**_모의물음())
    다시 = _모의목록(tmp_path)

    다시.load()

    assert 다시.reconcile_wanted() == ["run1"]


def test_감시_중에_진짜로_다시_붙어_대사가_맞으면_감시를_이어_간다(tmp_path):
    """연결이 끊겼다 붙으면 계좌와 맞춰 봅니다. 맞으면 대사 전 상태(감시)로 돌아갑니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    assert 실행목록._engine("run1").run.state == runs.ARMED

    실행목록.reconcile("run1", 시작)

    assert 실행목록._engine("run1").run.state == runs.ARMED
    assert 실행목록._engine("run1").events[-1]["reason"] == service_lib.RECONCILE_RESUME_REASON
    assert service_lib.WHY_NO_RESUME not in _글(실행목록)


# ── 허브: 새 연결은 「다시 붙음」이 아니다 ────────────────────


def _상태들(engine) -> list[dict]:
    client = engine._clients["screen"]
    made = []
    while not client.queue.empty():
        one = client.queue.get_nowait()
        if one.get("type") == "status":
            made.append(one)
    return made


def _선언(code: str) -> dict[Feed, int]:
    return {Feed(context="domestic-day", kind="quote", sym=code): 1}


def test_연결이_모두_닫힌_뒤_새_연결의_첫_live_에는_다시_받기가_없다():
    engine = 허브()

    async def 실행():
        engine.attach("screen")
        await engine.declare("screen", _선언("A7569000"))  # 연결이 서며 스스로 live 를 알립니다.
        await engine.declare("screen", {})  # 그 시장의 연결이 모두 닫힙니다.
        _상태들(engine)
        await engine.declare("screen", _선언("A7569000"))  # 새 연결
        made = [one for one in _상태들(engine) if one["state"] == LIVE]
        await engine.stop()
        return made

    상태 = asyncio.run(실행())

    assert 상태, "새 연결이 live 를 알렸습니다."
    assert "refill" not in 상태[0]


def test_같은_연결이_끊겼다_붙으면_다시_받기가_있다():
    engine = 허브()

    async def 실행():
        engine.attach("screen")
        await engine.declare("screen", _선언("A7569000"))
        engine._on_state("domestic", LIVE, "")
        engine._on_state("domestic", RECONNECTING, "끊겼습니다")
        engine._on_state("domestic", LIVE, "")
        made = _상태들(engine)
        await engine.stop()
        return made

    상태 = asyncio.run(실행())

    assert 상태[-1]["refill"] is True


def test_연결_둘_중_하나만_닫히면_다시_붙음을_잊지_않는다():
    engine = 허브(per_connection=1)

    async def 실행():
        engine.attach("screen")
        await engine.declare("screen", {**_선언("A7569000"), **_선언("A7569001")})
        링크 = len(engine._groups["domestic"].links)
        engine._on_state("domestic", LIVE, "")
        await engine.declare("screen", _선언("A7569000"))  # 하나만 닫힙니다.
        남은 = len(engine._groups["domestic"].links)
        _상태들(engine)
        engine._on_state("domestic", LIVE, "")
        made = _상태들(engine)
        await engine.stop()
        return 링크, 남은, made

    링크, 남은, 상태 = asyncio.run(실행())

    assert (링크, 남은) == (2, 1)
    assert 상태[-1]["refill"] is True


# ── 실측 순서 재현 ───────────────────────────────────────


def test_구독_없는_시장에_세운_모의_실행이_곧바로_중지되지_않는다(tmp_path):
    """실측(14:05) 순서 — 세우는 사이 감시 한 박자, 이어 그 시장의 새 연결이 live.

    허브가 낸 상태를 펌프에 넣고, 펌프가 다시 받으라고 한 실행은 펌프 루프처럼
    봉을 받고 대사를 지나게 합니다(`pump._take_forever`).
    """
    실행목록 = _모의목록(tmp_path)
    펌프 = pump_lib.RunPump(실행목록, hub=_허브())
    허브_ = 허브()

    def 감시_한_박자(목록, run):
        for run_id in 목록.reconcile_wanted():
            목록.reconcile(run_id, 시작)

    async def 앞서_붙었다_닫힘():
        허브_.attach("screen")
        await 허브_.declare("screen", _선언("A7569000"))  # 그 시장에 연결이 섰다가
        await 허브_.declare("screen", {})  # 모두 닫힙니다(구독 없는 시장).
        _상태들(허브_)

    async def 새_연결():
        await 허브_.declare("screen", _선언("A7569000"))  # 실행이 건 구독으로 새 연결이 섭니다.
        made = _상태들(허브_)
        await 허브_.stop()
        return made

    asyncio.run(앞서_붙었다_닫힘())
    _끼우며_받기(실행목록, 감시_한_박자)
    실행목록.add(**_모의물음())
    실행목록._fetch = lambda run, minutes, count: []
    for 상태 in asyncio.run(새_연결()):
        for run_id in 펌프.take(상태, at=시작 + 2):
            실행목록.refill(run_id)
            실행목록.reconcile(run_id, 시작 + 2)

    assert 실행목록._engine("run1").run.state == runs.ARMED
    assert _글(실행목록).count(service_lib.RECONCILE_DONE) == 1
    assert service_lib.WHY_NO_RESUME not in _글(실행목록)
