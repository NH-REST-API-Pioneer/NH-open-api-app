"""그 시장의 첫 연결이 붙는 것은 끊김이 아닙니다.

실행을 세워 그 시장에 처음 연결이 서면 허브는 「연결 준비 중 → 받는 중」을 알립니다.
그것을 끊김으로 받으면 갓 세운 실행에 「연결이 끊겼습니다」·「시세가 다시
들어옵니다」가 찍히고 틱 판정이 첫 봉 마감까지 쉽니다. 허브는 그 시장이 아직
한 번도 받은 적이 없을 때의 상태에 `fresh` 를 달고, 펌프는 그것을 실행에
넘기지 않습니다. 한 번 받은 뒤의 끊김은 공백·다시 채우기입니다.

**NH선물 서버에 나가지 않습니다.** 연결은 가짜 소켓이거나 저장본입니다.
"""
from __future__ import annotations

import asyncio

from backend.realtime.feeds import Feed
from backend.realtime.link import CONNECTING, LIVE, RECONNECTING, STOPPED
from backend.strategy import engine as engine_lib, pump as pump_lib, runs
from backend.strategy import service as service_lib
from backend.strategy.service import IDLE
from tests.test_realtime_link import INIT_OK, FakeConnect, FakeSocket, 기다린다, 연결
from tests.test_realtime_stream import 허브
from tests.test_strategy_pump import _허브
from tests.test_strategy_service import _모의목록, _모의물음

시각 = 10_000


def _상태들(engine, 할일) -> list[dict]:
    """허브에 붙어 할 일을 한 뒤 받은 상태 알림들."""
    받은: list[dict] = []

    async def 실행():
        client = engine.attach("strategy")
        await 할일(engine)
        while not client.queue.empty():
            받은.append(client.queue.get_nowait())
        await engine.stop()

    asyncio.run(실행())
    return [one for one in 받은 if one["type"] == "status"]


def _세운(tmp_path, *ids: str):
    실행목록 = _모의목록(tmp_path)
    for run_id in ids or ("run1",):
        실행목록.add(**_모의물음(run_id=run_id))
    펌프 = pump_lib.RunPump(실행목록, hub=_허브(), auction=lambda *_, **__: None)
    return 실행목록, 펌프


def _공백줄(엔진) -> list[str]:
    return [one["text"] for one in 엔진.events if one["kind"] == engine_lib.GAP]


# ── 허브: 첫 연결에만 표지 ─────────────────────────────


def test_첫_연결의_준비와_첫_받음에만_새_연결_표지를_단다():
    async def 할일(engine):
        engine._on_state("domestic", CONNECTING, "")
        engine._on_state("domestic", RECONNECTING, "")  # 한 번도 못 붙고 다시 시도
        engine._on_state("domestic", LIVE, "")
        engine._on_state("domestic", RECONNECTING, "")
        engine._on_state("domestic", LIVE, "")

    상태 = _상태들(허브(), 할일)

    assert [(one["state"], one.get("fresh"), one.get("refill")) for one in 상태] == [
        (CONNECTING, True, None),
        (RECONNECTING, True, None),
        (LIVE, True, None),
        (RECONNECTING, None, None),
        (LIVE, None, True),
    ]


def test_시장마다_따로_본다():
    async def 할일(engine):
        engine._on_state("domestic", LIVE, "")
        engine._on_state("overseas", CONNECTING, "")

    상태 = _상태들(허브(), 할일)

    assert [(one["market"], one.get("fresh")) for one in 상태] == [
        ("domestic", True),
        ("overseas", True),
    ]


def test_진짜_연결이_처음_붙을_때_새_연결_표지가_실린다():
    engine = 허브()

    async def 할일(engine):
        made, _, _ = 연결(FakeConnect(FakeSocket([INIT_OK])))
        made._on_state = engine._on_state
        made.start()
        await 기다린다(lambda: engine._was_live.get("domestic"))
        await made.stop()

    상태 = _상태들(engine, 할일)

    assert [(one["state"], one.get("fresh")) for one in 상태] == [
        (CONNECTING, True),
        (LIVE, True),
        (STOPPED, None),
    ]


def test_같은_연결이_끊겼다_다시_붙으면_새_연결이_아니다():
    """연결은 끊기면 같은 객체가 안에서 다시 붙습니다. 첫 받음 뒤의 상태에는 표지가 없습니다."""
    engine = 허브()

    async def 할일(engine):
        첫소켓 = FakeSocket([INIT_OK])
        둘째소켓 = FakeSocket([INIT_OK])
        made, _, _ = 연결(FakeConnect(첫소켓, 둘째소켓))
        made._on_state = engine._on_state
        made.start()
        await 기다린다(lambda: engine._was_live.get("domestic"))
        첫소켓.push(None)  # 서버가 닫습니다.
        await 기다린다(lambda: 둘째소켓.sent)
        await 기다린다(lambda: made.state == LIVE)
        await made.stop()

    상태 = _상태들(engine, 할일)

    assert [(one["state"], one.get("fresh"), one.get("refill")) for one in 상태] == [
        (CONNECTING, True, None),
        (LIVE, True, None),
        (RECONNECTING, None, None),
        (CONNECTING, None, None),
        (LIVE, None, True),
        (STOPPED, None, None),
    ]


def _국내(sym: str = "A7569000") -> Feed:
    return Feed(context="domestic-day", kind="quote", sym=sym)


def test_토큰을_다시_받아_그_시장을_다시_열면_새_연결이_아니다():
    """새 연결 객체로 다시 붙지만 받던 시세가 끊긴 것입니다 — 공백과 다시 채우기가 맞습니다."""

    async def 할일(engine):
        await engine.declare("strategy", {_국내(): 1})
        assert engine._was_live.get("domestic")
        assert await engine.reconnect_market("domestic") == "reconnected"

    상태 = _상태들(허브(), 할일)

    assert [(one["state"], one.get("fresh"), one.get("refill")) for one in 상태] == [
        (LIVE, True, None),
        (STOPPED, None, None),
        (LIVE, None, True),
    ]


def test_환경을_바꿔_연결을_다시_열어도_새_연결이_아니다():
    async def 할일(engine):
        await engine.declare("strategy", {_국내(): 1})
        await engine.reconnect()

    상태 = _상태들(허브(), 할일)

    assert [(one["state"], one.get("fresh"), one.get("refill")) for one in 상태] == [
        (LIVE, True, None),
        (STOPPED, None, None),
        (LIVE, None, True),
    ]


def test_연결이_둘이면_받던_연결이_끊길_때_새_연결이_아니다(tmp_path):
    """한 연결이 지는 구독 수를 줄여 연결이 둘인 경우입니다. 시장 단위로 알립니다 —
    끊긴 연결에 묶이지 않은 실행도 함께 공백으로 봅니다."""

    async def 할일(engine):
        await engine.declare("strategy", {_국내("A7569000"): 1, _국내("A7569001"): 1})
        첫째, 둘째 = engine._groups["domestic"].links
        첫째._set_state(RECONNECTING, "")

    상태 = _상태들(허브(per_connection=1), 할일)

    assert 상태[-1]["state"] == RECONNECTING and "fresh" not in 상태[-1]
    실행목록, 펌프 = _세운(tmp_path)
    엔진 = 실행목록._engine("run1")
    엔진.feed = "live"
    펌프.take(상태[-1], at=시각)
    assert 엔진.feed == engine_lib.GAP


# ── 펌프: 새 연결 표지는 실행에 넘기지 않는다 ───────────


def test_첫_연결이_붙는_동안_실행에_공백도_다시_채우기도_없다(tmp_path):
    실행목록, 펌프 = _세운(tmp_path)
    엔진 = 실행목록._engine("run1")
    앞 = len(엔진.events)

    채울것 = []
    for state in (CONNECTING, LIVE):
        채울것 += 펌프.take(
            {"type": "status", "market": "domestic", "state": state, "fresh": True}, at=시각
        )

    assert 채울것 == []
    assert _공백줄(엔진)[앞:] == [] and 엔진.events[앞:] == []
    assert 엔진.feed == IDLE, "첫 시세가 올 때까지 받는 중이 아닙니다."
    assert 엔진._tick_rest_from is None and not 엔진._after_gap


def test_첫_연결이_끝내_못_붙으면_실행은_받는_중이_아닌_채로_남는다(tmp_path):
    실행목록, 펌프 = _세운(tmp_path)
    엔진 = 실행목록._engine("run1")

    for state in (CONNECTING, RECONNECTING, CONNECTING, RECONNECTING):
        펌프.take({"type": "status", "market": "domestic", "state": state, "fresh": True}, at=시각)

    assert 엔진.feed == IDLE and 엔진.feed != engine_lib.GAP
    assert _공백줄(엔진) == []


def test_받던_연결이_끊기면_지금처럼_공백이고_다시_붙으면_채운다(tmp_path):
    실행목록, 펌프 = _세운(tmp_path)
    엔진 = 실행목록._engine("run1")
    엔진.feed = "live"

    펌프.take({"type": "status", "market": "domestic", "state": RECONNECTING}, at=시각)
    채울것 = 펌프.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=시각 + 1
    )

    assert _공백줄(엔진)[-2:] == ["데이터 공백 — 연결이 끊겼습니다(마지막 수신 09:00:10)", "시세가 다시 들어옵니다"]
    assert 채울것 == ["run1"]


def test_끝난_실행은_공백도_조회도_없고_확인_필요는_상태와_조회를_받는다(tmp_path):
    실행목록, 펌프 = _세운(tmp_path, "run1", "run2", "run3")
    끝 = 실행목록._engine("run2")
    확인 = 실행목록._engine("run3")
    for 엔진 in (실행목록._engine("run1"), 끝, 확인):
        엔진.feed = "live"
    끝.run.state = runs.ENDED
    확인.run.state = runs.ATTENTION
    끝앞 = len(끝.events)

    펌프.take({"type": "status", "market": "domestic", "state": RECONNECTING}, at=시각)
    끊긴동안 = 확인.feed
    채울것 = 펌프.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=시각 + 1
    )

    assert 채울것 == ["run1", "run3"], "끝난 실행만 빠집니다. 확인 필요도 봉은 다시 받습니다."
    assert 끝.events[끝앞:] == [] and 끝.feed == "live"
    assert 끊긴동안 == engine_lib.GAP and 확인.feed == "live", "확인 필요도 공백 상태는 따라갑니다."
    assert _공백줄(확인) == [], "확인 필요는 시세를 보지 않는 상태라 공백을 사건으로 적지 않습니다."


def _세어_둔(실행목록) -> dict[str, list[str]]:
    """다시 받기·맞춰 보기를 부른 것을 셉니다. 실제 일은 그대로 합니다."""
    부른것: dict[str, list[str]] = {"refill": [], "reconcile": []}
    다시받기, 맞춰보기 = 실행목록.refill, 실행목록.reconcile

    def refill(run_id, *args, **kwargs):
        부른것["refill"].append(run_id)
        return 다시받기(run_id, *args, **kwargs)

    def reconcile(run_id, *args, **kwargs):
        부른것["reconcile"].append(run_id)
        return 맞춰보기(run_id, *args, **kwargs)

    실행목록.refill, 실행목록.reconcile = refill, reconcile
    return 부른것


def test_확인_필요_실행은_다시_붙으면_봉만_다시_받고_맞춰_보지_않는다(tmp_path):
    """그 상태는 사용자가 확인해야 풀립니다. 봉은 받아 두어야 확인 뒤 구멍 없이 판정합니다.

    맞춰 보기가 불리면 상태는 그대로여도 「맞춰 보는 중」·「재개를 눌러 주세요」 줄이
    남습니다. 그래서 줄까지 봅니다. 같은 시장의 감시 중 실행은 맞춰 봅니다.
    """
    실행목록, 펌프 = _세운(tmp_path, "run1", "run2")
    확인 = 실행목록._engine("run1")
    감시 = 실행목록._engine("run2")
    확인.run.state = runs.ATTENTION
    확인앞, 감시앞 = len(확인.events), len(감시.events)
    부른것 = _세어_둔(실행목록)

    for run_id in 펌프.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=시각
    ):
        펌프.catch_up(run_id)

    assert 부른것 == {"refill": ["run1", "run2"], "reconcile": ["run2"]}
    assert 확인.run.state == runs.ATTENTION
    확인글 = [one["text"] for one in 확인.events[확인앞:]]
    assert service_lib.RECONCILE_START not in 확인글
    assert service_lib.WHY_NO_RESUME not in 확인글
    assert 감시.run.state == runs.ARMED
    감시글 = [one["text"] for one in 감시.events[감시앞:] if one["kind"] != engine_lib.READY]
    assert 감시글 == [service_lib.RECONCILE_START, service_lib.RECONCILE_RESUME]
    assert [one for one in 확인.events[확인앞:] if one["kind"] == engine_lib.READY], (
        "확인 필요 실행도 봉을 다시 받았습니다."
    )
