"""허브와 실행 사이의 펌프.

**허브를 지어 씁니다.** 붙는 쪽이 쓰는 것은 `attach`·`declare`·`detach`·`publish`
넷뿐이라, 그 넷만 있는 가짜로 실제 연결 없이 확인할 수 있습니다. 흘려 넣는
자료는 저장해 둔 실시간 기록입니다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from backend.realtime import feeds
from backend.realtime.link import LIVE
from backend.sessions.hours import KST
from backend.strategy import engine as engine_lib
from backend.strategy import journal as journal_lib
from backend.strategy import pump as pump_lib
from backend.strategy import runs, service as service_lib

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nh"
주간 = "domestic-day"
야간 = "domestic-night"


class _허브:
    """붙는 쪽이 쓰는 넷만 있는 허브."""

    def __init__(self) -> None:
        self.declared: list[dict[feeds.Feed, int]] = []
        self.sent: list[dict[str, Any]] = []
        self.detached: list[str] = []

    def attach(self, name):
        # 큐는 진짜입니다 — 펌프가 그것에서 꺼내 돌기 때문입니다.
        return type("손님", (), {"queue": asyncio.Queue()})()

    async def declare(self, name, wishes):
        self.declared.append(wishes)

    async def detach(self, name):
        self.detached.append(name)

    def publish(self, payload):
        self.sent.append(payload)


class _마스터:
    def locate(self, market, code):
        return {"rem_cnt": "9", "ctrt_size": "250000", "product_code": "01"}


class _시간표:
    def cached(self, market):
        return {"products": [{"productCode": "01", "tick": "0.05"}]}


def _설정(**aux) -> dict:
    묶음 = {
        "orderType": "시장가",
        "priceBasis": "신호가",
        "stopBasis": "",
        "fillCond": "FAS",
        "stopTicks": "2",
        "takeTicks": "3",
        "perOrder": "1",
        "maxHold": "5",
        "session": "국내 주간",
        "addWhileOpen": False,
        "dailyLoss": "300000",
        "marginBudget": "10000000",
    }
    묶음.update(aux)
    return {
        "memo": "",
        "baseBar": "1분봉",
        "evalMode": "마감",
        "rules": {
            "buyEntry": {
                "on": True,
                "steps": [
                    {
                        "id": "s1",
                        "join": "all",
                        "withinBars": 0,
                        "conds": [
                            {
                                "id": "c1",
                                "left": "close",
                                "op": "gt",
                                "rightKind": "number",
                                "right": "100",
                            }
                        ],
                    }
                ],
            },
            "sellEntry": {"on": False, "steps": []},
            "buyExit": {"on": False, "steps": []},
            "sellExit": {"on": False, "steps": []},
        },
        "aux": 묶음,
    }


@pytest.fixture
def 실행목록(tmp_path):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )


def _세우기(실행목록, run_id="run1", code="A7569000", session=주간) -> dict:
    return 실행목록.add(
        run_id=run_id,
        version_id="v1",
        draft=_설정(),
        market="domestic",
        code=code,
        session=session,
        qty=1,
        cash=10_000_000.0,
        fee_per_contract=0.0,
    )


async def 기다린다(재는것, 몇: int, 한도: float = 3.0) -> None:
    """그 수에 닿을 때까지 기다립니다. **시계로 재지 않습니다.**

    박자 몇 번이 0.05초 안에 도는지는 그때 기계가 얼마나 바쁜지에 달렸습니다.
    시계로 재면 다른 시험이 많이 돌 때만 틀리는 시험이 됩니다.
    """
    import time

    끝 = time.monotonic() + 한도
    while 재는것() < 몇 and time.monotonic() < 끝:
        await asyncio.sleep(0.005)


@pytest.fixture
def 펌프(실행목록):
    허브 = _허브()
    return pump_lib.RunPump(실행목록, hub=허브), 실행목록, 허브


# ── 구독 ────────────────────────────────────────────────


def test_실행마다_시세와_호가_둘을_건다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    바라는것 = 돌리는것.wishes()

    assert set(바라는것) == {
        feeds.Feed(context=주간, kind="quote", sym="A7569000"),
        feeds.Feed(context=주간, kind="book", sym="A7569000"),
    }


def test_같은_종목을_보는_실행이_둘이어도_구독은_하나다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "run1")
    _세우기(실행목록, "run2")

    assert len(돌리는것.wishes()) == 2, "종목 하나에 시세·호가 둘입니다."


def test_창이_다르면_다른_구독이다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "낮", session=주간)
    _세우기(실행목록, "밤", session=야간)

    assert len(돌리는것.wishes()) == 4


def test_끝난_실행의_구독은_놓는다(펌프):
    """자리가 스물뿐이라 안 보는 것을 붙들고 있으면 안 됩니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    실행목록.end("run1", 10)

    assert 돌리는것.wishes() == {}


def test_중지한_실행도_시세는_본다(펌프):
    """들고 있는 것의 손절·익절 감시는 중지해도 돌아야 합니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    실행목록.pause("run1", 10)

    assert len(돌리는것.wishes()) == 2


# ── 받기 ────────────────────────────────────────────────


def test_그_종목을_보는_실행에만_넣는다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "맞는것", code="A7569000")
    _세우기(실행목록, "다른것", code="A7569001")

    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "trades": [{"timestamp": 1, "price": 100.0, "quantity": 1}],
        },
        at=1,
    )

    assert 실행목록._engine("맞는것").book.last_price == 100.0
    assert 실행목록._engine("다른것").book.last_price is None


def test_체결이_오면_살아_있는_것으로_본다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    assert 실행목록._engine("run1").feed == service_lib.IDLE

    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "trades": [{"timestamp": 1, "price": 100.0, "quantity": 1}],
        },
        at=1,
    )

    assert 실행목록._engine("run1").feed == LIVE


def test_연결이_끊기면_공백이다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    돌리는것.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=1)

    assert 실행목록._engine("run1").feed == engine_lib.GAP


def test_다시_붙으면_앞을_다시_채울_실행을_알린다(펌프):
    """끊긴 동안의 봉은 실시간이 메워 주지 않습니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    채울것 = 돌리는것.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=1
    )

    assert 채울것 == ["run1"]


def test_채우는_일은_루프_밖으로_넘긴다(펌프):
    """조회는 통신이라 제한기에서 기다릴 수 있습니다 — 그동안 시세가 멈춥니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    부른곳 = []
    실행목록._fetch = lambda run, minutes, count: 부른곳.append(run.id) or []

    # `take` 자체는 조회를 부르지 않습니다.
    채울것 = 돌리는것.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=1
    )
    assert 부른곳 == [], "여기서는 통신하지 않습니다."

    for one in 채울것:
        실행목록.refill(one)
    assert 부른곳 == ["run1"]


def test_붙기만_하고_refill_이_없으면_안_채운다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    assert 돌리는것.take({"type": "status", "market": "domestic", "state": LIVE}, at=1) == []


def test_구독이_밀리면_시세를_못_받는_것으로_본다(펌프):
    """화면에는 살아 있는 것처럼 보이는데 봉이 안 서는 상태가 됩니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "밀린것", code="A7569000")
    _세우기(실행목록, "받는것", code="A7569001")
    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "trades": [{"timestamp": 1, "price": 100.0, "quantity": 1}],
        },
        at=1,
    )
    assert 실행목록._engine("밀린것").feed == LIVE

    돌리는것.take(
        {
            "type": "subscriptions",
            "granted": [{"context": 주간, "kind": "quote", "sym": "A7569001"}],
            "rejected": [{"context": 주간, "kind": "quote", "sym": "A7569000"}],
        },
        at=2,
    )

    assert 실행목록._engine("밀린것").feed == service_lib.IDLE
    assert any(
        pump_lib.NO_ROOM in one["text"] for one in 실행목록._engine("밀린것").events
    )
    받는것 = 실행목록._engine("받는것")
    assert not [one for one in 받는것.events if pump_lib.NO_ROOM in one["text"]]


def test_서버가_등록을_거절한_구독은_자리_없음이_아니라_서버의_글로_남긴다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "거절된것", code="A7569000")
    _세우기(실행목록, "밀린것", code="A7569001")
    거절글 = "해당 종목은 시세사용신청 후 조회 가능합니다. [action_sym::A7569000]"

    돌리는것.take(
        {
            "type": "subscriptions",
            "granted": [],
            "rejected": [
                {"context": 주간, "kind": "quote", "sym": "A7569000"},
                {"context": 주간, "kind": "quote", "sym": "A7569001"},
            ],
            "failed": [
                {
                    "context": 주간,
                    "kind": "quote",
                    "sym": "A7569000",
                    "code": "RT_FAIL",
                    "message": 거절글,
                }
            ],
        },
        at=2,
    )

    거절된것 = 실행목록._engine("거절된것")
    assert 거절된것.feed == service_lib.IDLE
    글 = [one["text"] for one in 거절된것.events]
    assert f"실시간 등록을 서버가 거절했습니다 — RT_FAIL {거절글}" in 글
    assert not [one for one in 글 if pump_lib.NO_ROOM in one]

    밀린것 = 실행목록._engine("밀린것")
    assert 밀린것.feed == service_lib.IDLE
    assert any(pump_lib.NO_ROOM in one["text"] for one in 밀린것.events)
    assert not [one for one in 밀린것.events if pump_lib.REFUSED in one["text"]]


def test_거절_글이_비면_코드만_남긴다():
    assert pump_lib.refused_text("RT_FAIL", "") == "실시간 등록을 서버가 거절했습니다 — RT_FAIL"
    assert pump_lib.refused_text("RT_FAIL", None) == "실시간 등록을 서버가 거절했습니다 — RT_FAIL"
    assert pump_lib.refused_text("RT_FAIL", " 까닭 ") == "실시간 등록을 서버가 거절했습니다 — RT_FAIL 까닭"


def test_다_받아들여지면_아무것도_안_한다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    돌리는것.take(
        {
            "type": "subscriptions",
            "granted": [{"context": 주간, "kind": "quote", "sym": "A7569000"}],
            "rejected": [],
        },
        at=2,
    )

    assert not [
        one for one in 실행목록._engine("run1").events if pump_lib.NO_ROOM in one["text"]
    ]


def test_다른_시장의_상태는_안_본다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    돌리는것.take({"type": "status", "market": "overseas", "state": "reconnecting"}, at=1)

    assert 실행목록._engine("run1").feed != engine_lib.GAP


def test_허브의_세션_방송으로는_안_닫는다(펌프):
    """닫는 길은 **하나**입니다 — 둘이 함께 돌면 같은 실행이 두 번 닫힙니다.

    방송은 시장 하나의 시계라 품목마다 다른 경계를 말하지 못합니다. 실행은
    종목마다 판정해 닫습니다(`_sessions`).
    """
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "낮", session=주간)
    _세우기(실행목록, "밤", session=야간)

    돌리는것.take({"type": "session", "market": "domestic", "session": "night"}, at=1)

    for one in ("낮", "밤"):
        assert engine_lib.SESSION not in [
            줄["kind"] for 줄 in 실행목록._engine(one).events
        ], one


# ── 내기 ────────────────────────────────────────────────


def test_한_박자에_한_묶음을_보낸다(펌프):
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)

    보낸것 = 돌리는것.beat(at=1)

    assert 보낸것 is not None
    assert 보낸것["type"] == pump_lib.CHANNEL
    assert [one["id"] for one in 보낸것["runs"]] == ["run1"]
    assert set(보낸것) == {"type", "runs", "fills", "events", "openOrders"}
    assert 허브.sent == [보낸것]


def test_실행이_없으면_안_보낸다(펌프):
    돌리는것, _, 허브 = 펌프

    assert 돌리는것.beat(at=1) is None
    assert 허브.sent == []


def test_박자마다_시계를_돌린다(펌프):
    """체결이 안 오는 것도 하나의 사건입니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "trades": [{"timestamp": 1, "price": 100.0, "quantity": 1}],
        },
        at=1_000,
    )

    돌리는것.beat(at=1_000 + int(runs.GAP_SECONDS * 1000))

    assert 실행목록._engine("run1").feed == engine_lib.GAP


# ── 저장해 둔 기록으로 ────────────────────────────────────


def _기록(api: str) -> list[dict[str, Any]]:
    """체결이 가장 많이 담긴 기록 하나의 자료 프레임."""
    made: list[list[dict[str, Any]]] = []
    for path in sorted((FIXTURE_ROOT / api).rglob("*.json")):
        held = json.loads(path.read_text(encoding="utf-8"))
        one = [
            event["payload"]["body"]
            for event in held.get("events", [])
            if event.get("direction") == "received"
            and isinstance(event.get("payload"), dict)
            and isinstance(event["payload"].get("body"), dict)
        ]
        if one:
            made.append(one)
    return max(made, key=len, default=[])


def test_반입해_둔_시세_묶음을_흘려_넣는다(펌프):
    """허브가 내는 모양 그대로 — `trades` 가 여러 건씩 묶여 옵니다."""
    돌리는것, 실행목록, 허브 = 펌프
    체결들 = [
        one
        for one in (feeds.trade_of(b, context=주간) for b in _기록("KA"))
        if one
    ]
    if not 체결들:
        pytest.skip("체결이 담긴 시세 기록이 반입되어 있지 않습니다.")
    _세우기(실행목록)

    # 허브는 100밀리초씩 모아 보냅니다 — 다섯씩 묶어 넣습니다.
    for start in range(0, len(체결들), 5):
        묶음 = 체결들[start : start + 5]
        돌리는것.take(
            {"type": "quote", "context": 주간, "sym": "A7569000", "trades": 묶음},
            at=묶음[-1]["timestamp"],
        )

    돌린것 = 실행목록._engine("run1")
    assert 돌린것.feed == LIVE
    assert 돌린것.book.last_price == 체결들[-1]["price"]
    assert 돌린것.bars.dropped == 0
    assert 돌리는것.beat(at=체결들[-1]["timestamp"])["runs"][0]["feed"] == LIVE


def test_반입해_둔_호가로_대기_주문이_채워진다(펌프):
    돌리는것, 실행목록, _ = 펌프
    호가들 = [feeds.book_of(b, context=주간) for b in _기록("KB")]
    호가들 = [one for one in 호가들 if one["asks"] and one["bids"]]
    if not 호가들:
        pytest.skip("호가가 담긴 기록이 반입되어 있지 않습니다.")
    _세우기(실행목록)
    돌린것 = 실행목록._engine("run1")
    돌린것.book.place("o1", side="buy", quantity=1, order_type="시장가", at=0)

    돌리는것.take({"type": "book", "context": 주간, "sym": "A7569000", **호가들[0]}, at=1_000)

    가까운매도 = 호가들[0]["asks"][-1]["price"]
    assert [one["price"] for one in 돌린것.fills] == [가까운매도]


def test_구독이_달라졌을_때만_다시_선언한다(펌프):
    """박자마다 맞춰 보되, 같으면 허브를 건드리지 않습니다."""
    돌리는것, 실행목록, 허브 = 펌프
    돌리는것._client = 허브.attach(돌리는것.name)
    asyncio.run(돌리는것.declare())
    assert len(허브.declared) == 1

    assert asyncio.run(돌리는것.sync()) is False, "달라진 것이 없습니다."

    _세우기(실행목록)
    assert asyncio.run(돌리는것.sync()) is True
    assert len(허브.declared) == 2
    assert len(허브.declared[-1]) == 2


# ── 초마다 보는 것 ───────────────────────────────────────


@pytest.fixture
def 해외펌프(tmp_path):
    """해외 실행 하나와, 장중 여부를 손으로 답하는 펌프."""
    from backend.strategy import limits as limit_lib

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(
        run_id="밖것",
        version_id="v1",
        draft=_설정(session="해외 CME"),
        market="overseas",
        code="ESU26",
        session="overseas",
        qty=1,
        cash=10_000.0,
        fee_per_contract=0.0,
    )
    장중 = {"열림": True}
    돌리는것 = pump_lib.RunPump(
        실행목록,
        hub=_허브(),
        limits=limit_lib.LimitStore(tmp_path / "limits.json"),
        judge=lambda market, code, session: 장중["열림"],
    )
    return 돌리는것, 실행목록, 장중


def test_해외_실행은_창_밖으로_나갈_때_세션을_닫는다(해외펌프):
    """허브의 세션 신호는 국내만 옵니다 — 해외는 판정을 함께 봅니다."""
    돌리는것, 실행목록, 장중 = 해외펌프

    돌리는것.check(1_000)
    assert engine_lib.SESSION not in [one["kind"] for one in 실행목록._engine("밖것").events]

    장중["열림"] = False
    돌리는것.check(2_000)

    assert engine_lib.SESSION in [one["kind"] for one in 실행목록._engine("밖것").events]


def test_계속_닫혀_있으면_한_번만_닫는다(해외펌프):
    돌리는것, 실행목록, 장중 = 해외펌프
    돌리는것.check(1_000)
    장중["열림"] = False
    돌리는것.check(2_000)

    돌리는것.check(3_000)

    닫은것 = [one for one in 실행목록._engine("밖것").events if one["kind"] == engine_lib.SESSION]
    assert len(닫은것) == 1


def test_초에_한_번만_본다(해외펌프):
    """마스터·시간표를 뒤지는 일이라 박자마다 하기에는 무겁습니다."""
    돌리는것, _, _ = 해외펌프

    assert 돌리는것.check(1_000) is True
    assert 돌리는것.check(1_100) is False, "같은 초입니다."
    assert 돌리는것.check(2_000) is True


def test_한도를_걸면_박자에_본다(펌프, tmp_path):
    from backend.strategy import limits as limit_lib

    돌리는것, 실행목록, _ = 펌프
    한도 = limit_lib.LimitStore(tmp_path / "limits.json")
    한도.save({"domestic": {"dailyLoss": 1.0}})
    돌리는것.limits = 한도
    _세우기(실행목록)
    하나 = 실행목록._engine("run1")
    하나.ledger.add({"side": "buy", "quantity": 1, "price": 100.0, "time": 1})
    하나.ledger.add({"side": "sell", "quantity": 1, "price": 90.0, "time": 2})

    돌리는것.beat(at=1_000)

    assert 실행목록.rows()[0]["state"] == runs.PAUSED


# ── 허브가 실제로 받는 모양인가 ───────────────────────────


def test_구독이_허브가_아는_맥락으로_선다(펌프):
    """가짜 허브는 `Feed` 를 안 만들어 봐서 이 자리를 못 잡습니다.

    실행의 `session` 에 화면 문구(「국내 주간」)가 담기면 여기서 터집니다 —
    `Feed` 가 모르는 맥락을 받지 않기 때문입니다.
    """
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "낮", session=주간)
    _세우기(실행목록, "밤", session=야간)

    바라는것 = 돌리는것.wishes()

    # 만든 것이 진짜 `Feed` 이고, 맥락이 허브의 목록 안입니다.
    assert all(isinstance(one, feeds.Feed) for one in 바라는것)
    assert {one.context for one in 바라는것} <= set(feeds.CONTEXTS)
    assert {one.kind for one in 바라는것} == {"quote", "book"}


def test_실제_허브에_선언까지_해_본다(실행목록):
    """붙는 쪽이 쓰는 넷만 가짜로 둔 탓에 못 보던 자리입니다.

    진짜 `Hub` 는 붙는 순간 제 일을 시작하므로 **이벤트 루프 안에서** 붙였다
    떼야 합니다 — 그것까지 해 봐야 앱이 하는 것과 같습니다.
    """
    from backend.realtime.hub import Hub

    _세우기(실행목록)

    async def 돌려보기():
        허브 = Hub()
        돌리는것 = pump_lib.RunPump(실행목록, hub=허브)
        try:
            돌리는것._client = 허브.attach(돌리는것.name)
            await 돌리는것.declare()
            return tuple(허브._clients[돌리는것.name].feeds)
        finally:
            await 허브.stop()

    선언된것 = asyncio.run(돌려보기())

    assert len(선언된것) == 2
    assert {one.context for one in 선언된것} == {주간}
    assert {one.kind for one in 선언된것} == {"quote", "book"}


def test_창_이름을_문구로_보내도_키로_담는다(실행목록):
    """화면은 설정에 문구를 담고 실행을 세울 때는 키를 보냅니다."""
    줄 = 실행목록.add(
        run_id="문구",
        version_id="v1",
        draft=_설정(),
        market="domestic",
        code="A7569000",
        session="국내 주간",
        qty=1,
        cash=10_000_000.0,
        fee_per_contract=0.0,
    )

    assert 줄["session"] == 주간, "담기는 허브 맥락 키로 담습니다."
    assert 줄["sessionLabel"] == "국내 주간", "화면이 읽을 말은 따로 냅니다."
    assert 실행목록._engine("문구").run.session == 주간


def test_같은_예외가_이어지면_한_번만_남긴다(펌프, caplog):
    """박자는 초에 열 번입니다 — 같은 줄이 초당 열 번씩 쌓이면 다른 일이 묻힙니다."""
    import logging

    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    터짐 = ValueError("모르는 화면 맥락입니다")

    with caplog.at_level(logging.ERROR, logger="backend.strategy.pump"):
        돌리는것._fault(터짐, 1_000)
        돌리는것._fault(터짐, 1_100)
        돌리는것._fault(터짐, 1_200)

    assert len(caplog.records) == 1
    막힘 = [one for one in 실행목록._engine("run1").events if pump_lib.FAULT in one["text"]]
    assert len(막힘) == 1
    assert "모르는 화면 맥락입니다" in 막힘[0]["text"], "화면이 무엇이 막혔는지 봅니다."


def test_다른_예외는_다시_남긴다(펌프, caplog):
    import logging

    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    with caplog.at_level(logging.ERROR, logger="backend.strategy.pump"):
        돌리는것._fault(ValueError("하나"), 1_000)
        돌리는것._fault(ValueError("둘"), 1_100)

    assert len(caplog.records) == 2


def test_다시_붙을_때도_같은_길로_채운다(펌프):
    """`status refill` 이 오면 붙어 있는 실행마다 한 번씩 채웁니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록, "하나")
    _세우기(실행목록, "둘", code="A7569001")
    받은것 = []
    실행목록._fetch = lambda run, minutes, count: 받은것.append(run.id) or []

    for one in 돌리는것.take(
        {"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=1
    ):
        실행목록.refill(one, 1)

    assert 받은것 == ["하나", "둘"]


# ── 실제 이벤트 루프에서 ─────────────────────────────────


def test_박자가_실제_루프에서_돈다(펌프):
    """`beat` 를 손으로 부르는 것과 **루프가 부르는 것**은 다릅니다.

    허브는 지어 쓰되 루프는 진짜입니다 — 박자 태스크가 서고, 잠들었다 깨어
    제 일을 하고, 멈추라면 멈추는지까지 봅니다.
    """
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    돌리는것.interval = 0.01
    박자들: list[int] = []
    원래박자 = 돌리는것.beat

    def 세는박자(*, at):
        박자들.append(at)
        return 원래박자(at=at)

    돌리는것.beat = 세는박자

    async def 돌려보기():
        await 돌리는것.start()
        try:
            await 기다린다(lambda: len(박자들), 2)
            return len(박자들)
        finally:
            await 돌리는것.stop()

    돈수 = asyncio.run(돌려보기())

    assert 돈수 >= 2, f"박자가 거듭 돌아야 합니다(돈 수 {돈수})"
    assert len(허브.sent) >= 1, "첫 박자의 묶음은 나갑니다."
    assert 허브.sent[-1]["type"] == pump_lib.CHANNEL
    assert [one["id"] for one in 허브.sent[-1]["runs"]] == ["run1"]
    assert 돌리는것._tasks == [], "멈추면 태스크를 거둡니다."
    assert 실행목록._engine("run1").feed == service_lib.IDLE


def test_루프가_시계도_돌린다(펌프):
    """체결이 안 오는 것도 사건입니다 — 박자가 그것을 봅니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    돌리는것.interval = 0.01
    돌린것 = 실행목록._engine("run1")
    # 마지막 체결을 아주 옛날로 두면 다음 박자가 공백으로 봅니다.
    돌린것.last_trade_at = 1

    async def 돌려보기():
        await 돌리는것.start()
        try:
            await 기다린다(
                lambda: len([one for one in 돌린것.events if one["kind"] == engine_lib.GAP]), 1
            )
        finally:
            await 돌리는것.stop()

    asyncio.run(돌려보기())

    assert engine_lib.GAP in [one["kind"] for one in 돌린것.events]


def test_루프가_터져도_다음_박자가_돈다(펌프):
    """한 박자 때문에 펌프가 멈추면 안 됩니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    돌리는것.interval = 0.01
    센것 = {"수": 0}
    원래 = 돌리는것.beat

    def 가끔터짐(*, at):
        센것["수"] += 1
        if 센것["수"] == 1:
            raise RuntimeError("첫 박자만 터집니다")
        return 원래(at=at)

    돌리는것.beat = 가끔터짐

    async def 돌려보기():
        await 돌리는것.start()
        try:
            await 기다린다(lambda: 센것["수"], 2)
        finally:
            await 돌리는것.stop()

    asyncio.run(돌려보기())

    assert 센것["수"] >= 2, "터진 뒤에도 박자가 이어집니다."
    assert 허브.sent, "그 다음 박자는 방송까지 갑니다."
    막힘 = [one for one in 실행목록._engine("run1").events if pump_lib.FAULT in one["text"]]
    assert len(막힘) == 1, "터진 것은 실행에 한 번 남습니다."


def test_자료_한_건이_터져도_실행에_남는다(펌프, caplog):
    """기록에만 남기면 화면은 값이 안 오는 까닭을 모른 채 봉만 안 서는 것을 봅니다."""
    import logging

    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    async def 돌려보기():
        await 돌리는것.start()
        try:
            # 허브가 보낸 것처럼 큐에 넣되, 실행이 읽다 터지는 모양으로.
            돌리는것._client.queue.put_nowait({"type": "quote", "context": 주간, "sym": None})
            await 기다린다(
                lambda: len(
                    [
                        one
                        for one in 실행목록._engine("run1").events
                        if pump_lib.FAULT in one["text"]
                    ]
                ),
                1,
            )
        finally:
            await 돌리는것.stop()

    with caplog.at_level(logging.ERROR, logger="backend.strategy.pump"):
        돌리는것.interval = 0.01
        원래 = 돌리는것._quote
        돌리는것._quote = lambda payload, at: (_ for _ in ()).throw(ValueError("못 읽는 줄"))
        try:
            asyncio.run(돌려보기())
        finally:
            돌리는것._quote = 원래

    막힘 = [one for one in 실행목록._engine("run1").events if pump_lib.FAULT in one["text"]]
    assert 막힘, "실행에 까닭이 답니다."
    assert "못 읽는 줄" in 막힘[0]["text"]


# ── 모의 계좌 알림 ───────────────────────────────────────


def _모의세우기(실행목록, run_id="sim1", code="A7569000"):
    return 실행목록.add(
        run_id=run_id,
        version_id="v1",
        # 국내 계좌 실행은 체결조건이 있어야 섭니다.
        draft=_설정(fillCond="FAS"),
        market="domestic",
        code=code,
        session=주간,
        qty=1,
        cash=10_000_000.0,
        fee_per_contract=0.0,
        mode=runs.SIM,
        approved_at=1_000,
        environment="paper",
    )


@pytest.fixture
def 모의펌프(tmp_path):
    from backend.strategy import limits as limit_lib

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        # 대사가 읽는 계좌. **빈 계좌라 장부와 맞습니다** — 안 끼우면 시험이
        # 실제 계좌 조회로 나갑니다.
        account=lambda run: {"orders": [], "positions": []},
        sender=type("보냄", (), {"order": lambda self, **물음: {"id": "0000012345"}})(),
        environment=lambda: "paper",
    )
    허브 = _허브()
    돌리는것 = pump_lib.RunPump(
        실행목록, hub=허브, limits=limit_lib.LimitStore(tmp_path / "limits.json")
    )
    return 돌리는것, 실행목록, 허브


def test_모의_실행이_있으면_주문_알림도_구독한다(모의펌프):
    """계좌 단위라 실행이 몇이든 하나면 됩니다."""
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록, "sim1")
    _모의세우기(실행목록, "sim2", code="A7569001")

    바라는것 = 돌리는것.wishes()

    주문것 = [one for one in 바라는것 if one.kind == "orders"]
    assert len(주문것) == 1, "계좌 단위 구독이라 하나뿐입니다."
    assert 주문것[0].sym == "", "주문 알림에는 종목이 없습니다."


def test_종이만_있으면_주문_알림을_안_건다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    assert [one for one in 돌리는것.wishes() if one.kind == "orders"] == []


def test_주문_알림을_모든_모의_실행에_넣고_제_것만_받는다(모의펌프):
    """같은 계좌를 보는 실행 모두에 들어가고, 주문번호로 갈립니다."""
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록, "내것")
    _모의세우기(실행목록, "남의것", code="A7569001")
    내장부 = 실행목록._engine("내것").book
    내장부.place("o1", side="buy", quantity=1, order_type="시장가", at=1_000)

    돌리는것.take(
        {
            "type": "orders",
            "market": "domestic",
            "events": [{"id": "0000012345", "status": "filled", "filled": 1, "remaining": 0}],
        },
        at=2_000,
    )

    assert [one["quantity"] for one in 실행목록._engine("내것").fills] == [1]
    assert 실행목록._engine("남의것").fills == [], "제 주문번호가 아닙니다."


def test_다른_시장의_주문_알림은_안_본다(모의펌프):
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록)
    실행목록._engine("sim1").book.place(
        "o1", side="buy", quantity=1, order_type="시장가", at=1_000
    )

    돌리는것.take(
        {
            "type": "orders",
            "market": "overseas",
            "events": [{"id": "0000012345", "filled": 1, "remaining": 0}],
        },
        at=2_000,
    )

    assert 실행목록._engine("sim1").fills == []


def test_저장해_둔_알림_스트림이_펌프를_지나_장부까지_간다(tmp_path):
    """허브가 내는 묶음 모양 그대로 흘려 넣습니다.

    가짜 알림으로는 「어느 칸이 누적인가」·「계좌 단위라 종목이 없다」 같은
    것이 드러나지 않습니다. 저장해 둔 O1_K 기록을 그대로 씁니다.
    """
    import json
    from pathlib import Path

    from backend.realtime import feeds
    from backend.strategy import limits as limit_lib

    root = Path(__file__).parent / "fixtures" / "nh" / "O1_K"
    프레임 = [
        event["payload"]["body"]
        for path in sorted(root.rglob("*.json"))
        for event in json.loads(path.read_text(encoding="utf-8")).get("events", [])
        if event.get("direction") == "received"
        and isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("body"), dict)
    ]
    알림들 = [feeds.order_event(one, context=주간) for one in 프레임]
    번호 = next((one.get("id") for one in 알림들 if one.get("id")), None)
    if 번호 is None:
        pytest.skip("주문 알림 기록이 반입되어 있지 않습니다.")

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        sender=type("보냄", (), {"order": lambda self, **물음: {"id": 번호}})(),
        environment=lambda: "paper",
    )
    돌리는것 = pump_lib.RunPump(
        실행목록, hub=_허브(), limits=limit_lib.LimitStore(tmp_path / "limits.json")
    )
    _모의세우기(실행목록, "sim1")
    돌린것 = 실행목록._engine("sim1")
    돌린것.book.place("o1", side="buy", quantity=1, order_type="시장가", at=1_000)
    돌린것.run.state = runs.ENTERING
    돌린것._purpose["o1"] = "entry"

    # 허브는 한 묶음에 여러 건을 실어 보냅니다.
    돌리는것.take({"type": "orders", "market": "domestic", "events": 알림들}, at=2_000)

    (체결,) = 돌린것.fills
    assert 체결["quantity"] == 1 and 체결["price"] == 1335.9
    assert 체결["orderNo"] == 번호
    assert 돌린것.ledger.position.quantity == 1, "가상 장부까지 들어갑니다."
    assert 돌린것.run.state == runs.HOLDING, "전량 체결이라 보유로 갑니다."


# ── 대사 박자 ──────────────────────────────


def test_대사를_기다리는_실행을_루프가_집어_간다(모의펌프):
    """앱을 켜면 담아 둔 모의 실행이 대사를 기다리며 서 있습니다.

    **조회는 방송 박자와 따로 돕니다** — 계좌 조회 한 건이 1초 가까이 걸릴 수
    있어, 방송 박자 안에서 기다리면 그동안 화면이 아무 값도 못 받습니다.
    """
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록)
    돌린것 = 실행목록._engine("sim1")
    돌린것.run.state = runs.RECONCILING
    돌리는것.interval = 0.01

    async def 돌려보기():
        await 돌리는것.start()
        try:
            await 기다린다(lambda: int(돌린것.run.state == runs.PAUSED), 1)
        finally:
            await 돌리는것.stop()

    asyncio.run(돌려보기())

    assert 돌린것.run.state == runs.PAUSED, "맞으면 중지입니다 — 자동 재개는 없습니다."


def test_거래일이_바뀐_실행도_루프가_맞춰_본다(모의펌프):
    """맞으면 **상태를 안 내려놓습니다** — 날이 바뀌었다고 돌던 전략이 멈추면 안 됩니다."""
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록)
    돌린것 = 실행목록._engine("sim1")
    돌린것.audit_wanted = True
    돌리는것.interval = 0.01

    async def 돌려보기():
        await 돌리는것.start()
        try:
            await 기다린다(lambda: int(not 돌린것.audit_wanted), 1)
        finally:
            await 돌리는것.stop()

    asyncio.run(돌려보기())

    assert 돌린것.audit_wanted is False
    assert 돌린것.run.state == runs.ARMED


def test_종이_실행은_대사_박자가_안_집는다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)

    assert 실행목록.reconcile_wanted() == []
    assert 실행목록.audit_wanted() == []


def test_다시_붙으면_모의_실행이_대사를_지난다(모의펌프):
    """끊겨 있던 동안 계좌에서 무슨 일이 있었는지 앱은 모릅니다.

    봉만 다시 받고 이어 가면, 그 사이 채워진 주문이나 사라진 보유를 모른 채
    다음 봉에서 주문을 냅니다. 종이 실행은 맞춰 볼 계좌가 없어 봉만 받습니다.
    """
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록)
    _세우기(실행목록, "paper1")
    돌린것 = 실행목록._engine("sim1")
    종이 = 실행목록._engine("paper1")
    채운것 = []
    실행목록._fetch = lambda run, minutes, count: 채운것.append(run.id) or []
    돌리는것.interval = 0.01

    async def 돌려보기():
        await 돌리는것.start()
        try:
            await 돌리는것._client.queue.put(
                {"type": "status", "market": "domestic", "state": LIVE, "refill": True}
            )
            # 둘 다 채우기를 기다립니다 — 모의의 대사는 그 사이에 끝납니다.
            await 기다린다(lambda: len(채운것), 2)
        finally:
            await 돌리는것.stop()

    asyncio.run(돌려보기())

    assert set(채운것) == {"sim1", "paper1"}, "봉은 둘 다 다시 받습니다."
    assert 돌린것.run.state == runs.ARMED, "모의는 대사를 지나, 맞으면 감시로 돌아갑니다."
    assert 종이.run.state == runs.ARMED, "종이는 이어 갑니다."


# ── 세션은 종목마다 ─────────────────────────────────────


@pytest.fixture
def 국내둘(tmp_path):
    """국내 실행 둘과, 종목마다 장중 여부를 손으로 답하는 펌프.

    개장이 08:45 인 품목과 09:00 인 품목이 함께 옵니다 — 시장 하나의 경계로
    닫으면 그중 한쪽은 늘 어긋납니다.
    """
    from backend.strategy import limits as limit_lib

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )
    _세우기(실행목록, "이른것", code="A7569000")
    _세우기(실행목록, "늦은것", code="A7569001")
    # **열쇠가 (종목, 창) 입니다.** 국내는 한 종목이 주간과 야간에 두 번
    # 열려, 종목만으로 흉내 내면 주간 실행이 야간에도 장중으로 잡힙니다.
    장중 = {
        ("A7569000", 주간): True,
        ("A7569001", 주간): True,
        ("A7569000", 야간): False,
        ("A7569001", 야간): False,
    }
    돌리는것 = pump_lib.RunPump(
        실행목록,
        hub=_허브(),
        limits=limit_lib.LimitStore(tmp_path / "limits.json"),
        judge=lambda market, code, session: 장중[(code, session)],
    )
    return 돌리는것, 실행목록, 장중


def _닫힌것(실행목록, run_id):
    return [one for one in 실행목록._engine(run_id).events if one["kind"] == engine_lib.SESSION]


def test_같은_초에_한_종목만_닫는다(국내둘):
    """주간 마감이 품목마다 다릅니다 — 먼저 끝난 쪽만 닫혀야 합니다."""
    돌리는것, 실행목록, 장중 = 국내둘
    돌리는것.check(1_000)

    장중[("A7569000", 주간)] = False
    돌리는것.check(2_000)

    assert len(_닫힌것(실행목록, "이른것")) == 1
    assert _닫힌것(실행목록, "늦은것") == [], "아직 도는 품목입니다."


def test_야간_마감_둘도_따로_닫는다(국내둘):
    """05:00 에 끝나는 품목과 06:00 에 끝나는 품목이 함께 옵니다(넷 대 여섯)."""
    돌리는것, 실행목록, 장중 = 국내둘
    돌리는것.check(1_000)

    # 05:00 — 이른 품목만 창 밖입니다.
    장중[("A7569000", 주간)] = False
    돌리는것.check(2_000)
    assert len(_닫힌것(실행목록, "이른것")) == 1
    assert _닫힌것(실행목록, "늦은것") == []

    # 06:00 — 나머지도 끝납니다.
    장중[("A7569001", 주간)] = False
    돌리는것.check(3_000)

    assert len(_닫힌것(실행목록, "이른것")) == 1, "두 번 닫지 않습니다."
    assert len(_닫힌것(실행목록, "늦은것")) == 1


def test_국내도_계속_닫혀_있으면_한_번만_닫는다(국내둘):
    돌리는것, 실행목록, 장중 = 국내둘
    돌리는것.check(1_000)
    장중[("A7569000", 주간)] = False
    돌리는것.check(2_000)

    돌리는것.check(3_000)

    assert len(_닫힌것(실행목록, "이른것")) == 1


def test_창_판정은_화면이_쓰는_자리를_부른다(monkeypatch):
    """엔진이 따로 셈하면 화면은 열려 있다는데 실행은 닫힌 상태가 됩니다."""
    from backend.sessions import sessions_routes

    물은것 = []

    def _답(market, sym, now):
        물은것.append((market, sym))
        return {"state": "closed"}

    monkeypatch.setattr(sessions_routes, "judged", _답)

    assert pump_lib._open_now("domestic", "A7569000") is False
    assert 물은것 == [("domestic", "A7569000")]


def test_모르는_종목은_닫힘으로_안_본다(monkeypatch):
    """**「모른다」와 「닫혔다」는 다릅니다.** 그 종목을 마스터에서 못 찾거나
    거래시간 표에 그 품목 줄이 없으면 판정이 창을 하나도 못 세워 마감으로
    답합니다. 그것을 닫힘으로 읽으면, 장이 열려 있는데 표가 낡았다는 것만으로
    실행이 세션을 닫고 판정을 내려놓습니다.
    """
    from backend.sessions import judge, sessions_routes

    답 = {"state": judge.CLOSED, "source": judge.UNKNOWN}
    monkeypatch.setattr(sessions_routes, "judged", lambda market, sym, now: 답)

    assert pump_lib._open_now("domestic", "없는코드", 주간) is True
    assert pump_lib._open_now("overseas", "없는코드") is True

    답["source"] = "api"
    assert pump_lib._open_now("overseas", "없는코드") is False, "아는 채로 닫힌 것은 닫힘입니다."


def test_거래시간_표에_없는_품목도_닫힘이_아니다():
    """판정을 지어내지 않고 **실제로 불러** 봅니다 — 마스터에 없는 종목은
    `judged` 가 해외 판정으로 내려가 `unknown` 으로 답합니다.
    """
    assert pump_lib._open_now("overseas", "없는종목AAA") is True
    assert pump_lib._open_now("domestic", "없는종목AAA", 주간) is True


def test_마스터를_아직_못_받았으면_아는_종목도_닫힘이_아니다(monkeypatch):
    """**한 종목이 아니라 판 전체가 걸리는 자리입니다.**

    앱이 뜨고 종목 마스터를 읽는 동안에는 판정이 그 종목 줄을 못 찾아, 시장과
    무관하게 해외 판정으로 내려가 `unknown` 으로 답합니다(`sessions_routes.judged`).
    재 보면 코스피200선물처럼 아는 종목도 그렇습니다 — 그것을 닫힘으로 읽으면
    마스터를 읽는 동안 **모든 실행**이 세션을 닫습니다.
    """
    from backend.master import master_service

    monkeypatch.setattr(master_service.service, "product_of", lambda market, sym: None)

    assert pump_lib._open_now("domestic", "A016C000", 주간) is True
    assert pump_lib._open_now("overseas", "MESZ26") is True


def test_주간_실행은_야간_창에서_안_열린다(국내둘):
    """한 종목이 주간과 야간에 두 번 열립니다.

    「지금 이 종목이 열려 있나」만 보면 주간 실행이 야간에도 장중으로 잡혀,
    15:45 에 한 번 닫히고 다음 날 06:00 에 **또** 닫힙니다 — 거래 한 번 없는
    주간 실행이 야간 끝에 「세션 종료」를 받습니다.
    """
    돌리는것, 실행목록, 장중 = 국내둘
    돌리는것.check(1_000)

    # 15:45 — 주간이 끝납니다.
    장중[("A7569000", 주간)] = False
    장중[("A7569001", 주간)] = False
    돌리는것.check(2_000)
    assert len(_닫힌것(실행목록, "이른것")) == 1

    # 18:00 — 같은 종목의 야간이 열립니다. 주간 실행과는 상관없는 창입니다.
    장중[("A7569000", 야간)] = True
    장중[("A7569001", 야간)] = True
    돌리는것.check(3_000)

    # 06:00 — 야간이 끝납니다.
    장중[("A7569000", 야간)] = False
    장중[("A7569001", 야간)] = False
    돌리는것.check(4_000)

    assert len(_닫힌것(실행목록, "이른것")) == 1, "주간 실행은 하루 한 번만 닫힙니다."
    assert len(_닫힌것(실행목록, "늦은것")) == 1


def test_창_판정은_국내에서_창까지_맞춘다(monkeypatch):
    """국내는 창을 맞추고 해외는 닫혔는지만 봅니다 — 해외는 창이 하나입니다."""
    from backend.sessions import sessions_routes

    답 = {"state": "night", "session": "night"}
    monkeypatch.setattr(sessions_routes, "judged", lambda market, sym, now: 답)

    assert pump_lib._open_now("domestic", "A7569000", 야간) is True
    assert pump_lib._open_now("domestic", "A7569000", 주간) is False, "주간 실행의 창이 아닙니다."
    assert pump_lib._open_now("overseas", "ESU26", "overseas") is True, "해외는 창을 안 봅니다."

    답.update({"state": "closed", "session": None})
    assert pump_lib._open_now("domestic", "A7569000", 야간) is False
    assert pump_lib._open_now("overseas", "ESU26", "overseas") is False


def test_한_실행이_값을_못_내도_묶음은_나간다(펌프):
    """묶음이 통째로 멈추면 **멀쩡한 실행들의 화면까지** 같은 자리에 멎습니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    _세우기(실행목록, run_id="run2", code="A016C000")
    말썽 = 실행목록._engine("run1")
    앞것 = 돌리는것.beat(at=1)
    말썽.book = _못_읽는_장부()

    보낸것 = 돌리는것.beat(at=2)

    assert 보낸것 is not None, "나가야 합니다."
    assert [one["id"] for one in 보낸것["runs"]] == ["run1", "run2"], "줄은 안 빠집니다."
    묵은것 = 보낸것["runs"][0]
    assert 묵은것["stale"] is True, "묵은 값이라고 적어 보냅니다."
    assert {key: 값 for key, 값 in 묵은것.items() if key != "stale"} == 앞것["runs"][0]
    assert "stale" not in 보낸것["runs"][1], "멀쩡한 실행은 그대로입니다."
    남긴것 = [one for one in 말썽.events if "말썽" in one["text"]]
    assert len(남긴것) == 1, "그 실행에 까닭을 답니다."


def test_첫_박자부터_못_내도_줄은_선다(펌프):
    """세울 앞 값이 없어도 **줄은 세웁니다** — 목록에서 사라지면 사용자가 그
    실행을 멈출 방법까지 잃습니다(중지·종료 단추가 그 줄에 섭니다).
    """
    돌리는것, 실행목록, 허브 = 펌프
    세운것 = _세우기(실행목록)
    실행목록._engine("run1").book = _못_읽는_장부()

    (줄,) = 돌리는것.beat(at=1)["runs"]

    assert 줄["stale"] is True
    assert 줄["id"] == "run1" and 줄["state"] == 세운것["state"], "단추가 설 칸은 있습니다."
    assert 줄["pl"] is None and 줄["position"] is None, "모르는 값은 0 이 아니라 빈 칸입니다."
    assert set(줄) == set(세운것) | {"stale"}, "칸은 성한 줄과 같습니다."


def test_값이_다시_나오면_표지가_사라진다(펌프):
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    말썽 = 실행목록._engine("run1")
    성한장부 = 말썽.book
    말썽.book = _못_읽는_장부()
    assert 돌리는것.beat(at=1)["runs"][0]["stale"] is True

    말썽.book = 성한장부

    assert "stale" not in 돌리는것.beat(at=2)["runs"][0]


def test_사고는_기록에_안_남긴다(펌프, tmp_path):
    """거래에서 일어난 일이 아닙니다. 거래 기록 사이에 끼면 그 실행이 무엇을
    했는지 읽을 때 방해가 됩니다 — 화면은 이벤트로 봅니다.
    """
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    말썽 = 실행목록._engine("run1")
    말썽.book = _못_읽는_장부()
    기록 = 실행목록.journal.path
    앞줄수 = sum(1 for _ in 기록.open(encoding="utf-8")) if 기록.exists() else 0

    for 회차 in range(5):
        돌리는것.beat(at=회차)

    뒷줄수 = sum(1 for _ in 기록.open(encoding="utf-8")) if 기록.exists() else 0
    assert 뒷줄수 == 앞줄수, "기록에는 한 줄도 안 늘어납니다."
    assert [one for one in 말썽.events if "말썽" in one["text"]], "화면에는 남습니다."


def test_시계가_터져도_묶음은_나간다(펌프):
    """값을 꺼내 보기도 전에 멈추면 화면은 아무것도 못 받습니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    _세우기(실행목록, run_id="run2", code="A016C000")
    말썽 = 실행목록._engine("run1")

    def 터진다(at):
        raise RuntimeError("말썽")

    말썽.tick_clock = 터진다

    보낸것 = 돌리는것.beat(at=1)

    assert 보낸것 is not None
    assert [one["id"] for one in 보낸것["runs"]] == ["run1", "run2"]
    assert 보낸것["runs"][0]["stale"] is True, "시계를 못 돈 실행도 묵은 줄입니다."


def test_같은_까닭은_실행마다_한_번만_남긴다(펌프):
    """박자는 초에 열 번입니다. 같은 줄이 쌓이면 기록에서 다른 일이 묻힙니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    말썽 = 실행목록._engine("run1")
    말썽.book = _못_읽는_장부()

    for 회차 in range(5):
        돌리는것.beat(at=회차)

    assert len([one for one in 말썽.events if "말썽" in one["text"]]) == 1
    assert len(허브.sent) == 1, "묶음은 첫 박자에 나가고, 같은 묶음은 다시 안 나갑니다."


def test_다시_온전해지면_알림을_놓는다(펌프):
    """고쳐졌다가 또 터지면 그때는 새로 알려야 합니다. **한 칸만 되는 사이에는
    안 풉니다** — 그러면 같은 고장이 박자마다 다시 적힙니다.
    """
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    말썽 = 실행목록._engine("run1")
    성한장부 = 말썽.book

    말썽.book = _못_읽는_장부()
    돌리는것.beat(at=1)
    말썽.book = 성한장부
    돌리는것.beat(at=2)
    말썽.book = _못_읽는_장부()
    돌리는것.beat(at=3)

    assert len([one for one in 말썽.events if "말썽" in one["text"]]) == 2


def test_열린_주문만_못_꺼내도_그_줄에_적는다(펌프):
    """줄은 성한데 미체결만 못 받는 자리입니다. 안 적으면 화면이 빈 표를
    **「없습니다」**로 그립니다 — 못 받은 것과 없는 것은 다릅니다.
    """
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    말썽 = 실행목록._engine("run1")
    말썽.book = _줄로_못_내는_장부()

    보낸것 = 돌리는것.beat(at=1)

    (줄,) = 보낸것["runs"]
    assert 줄["stale"] is True
    assert 줄["id"] == "run1" and 줄["state"], "줄 자체는 성합니다."
    assert 보낸것["openOrders"] == []


class _반쪽_주문:
    """수는 세지는데 줄로는 못 내는 주문.

    **실제로 오는 모양입니다** — 모의 주문에 스탑 가격 칸이 없으면 줄을 만들다
    터질 수 있습니다. 그때도 열린 주문 **수**는 멀쩡히 세어집니다.
    """

    id = "o1"
    open = True
    remaining = 1
    quantity = 1
    side = "buy"


class _줄로_못_내는_장부:
    """열린 주문을 세는 것은 되고 줄로 내는 것만 터지는 장부."""

    gap = False
    last_price = None
    orders = [_반쪽_주문()]

    @property
    def open_orders(self):
        return list(self.orders)

    def cancel_open(self, reason: str) -> list:
        return []


class _못_읽는_장부:
    """열린 주문을 물으면 터지는 장부. 줄을 못 내는 실행을 흉내 냅니다."""

    gap = False
    last_price = None
    orders: list = []

    @property
    def open_orders(self):
        raise RuntimeError("말썽")

    def cancel_open(self, reason: str) -> list:
        return []


# ── 봉 순서의 기준 — 개장 시각 ─────────────────────────


def test_장중이면_개장_시각을_거래일마다_한_번_엔진에_넘긴다(해외펌프, tmp_path):
    from backend.strategy import limits as limit_lib

    _, 실행목록, 장중 = 해외펌프
    물음 = []
    개장 = 1_758_000_000_000

    def 여는때(market, code, session):
        물음.append((market, code, session))
        return 개장

    돌리는것 = pump_lib.RunPump(
        실행목록,
        hub=None,
        limits=limit_lib.LimitStore(tmp_path / "limits2.json"),
        judge=lambda market, code, session: 장중["열림"],
        opening=여는때,
    )
    돌리는것.check(개장 + 1_000)
    돌리는것.check(개장 + 2_000)

    엔진 = 실행목록._engine("밖것")
    assert 엔진.open_known(개장 + 3_000, "overseas")
    assert 물음 == [("overseas", "ESU26", "overseas")], "받은 날에는 다시 묻지 않습니다."


def test_장이_닫혀_있으면_개장_시각을_묻지_않는다(해외펌프, tmp_path):
    from backend.strategy import limits as limit_lib

    _, 실행목록, 장중 = 해외펌프
    장중["열림"] = False
    물음 = []
    돌리는것 = pump_lib.RunPump(
        실행목록,
        hub=None,
        limits=limit_lib.LimitStore(tmp_path / "limits2.json"),
        judge=lambda market, code, session: 장중["열림"],
        opening=lambda *args: 물음.append(args) or 1,
    )

    돌리는것.check(1_000)

    assert 물음 == []


def test_장중_판정만_바꿔_끼우면_개장_시각은_모른다고_답한다(해외펌프):
    돌리는것, _, _ = 해외펌프

    assert 돌리는것.opening("overseas", "ESU26", "overseas") is None


@pytest.mark.parametrize(
    ("market", "session", "판정", "기대"),
    [
        ("domestic", "domestic-day", {"state": "day", "session": "day", "since": "2026-09-17T08:45:00+09:00"}, "2026-09-17T08:45:00+09:00"),
        ("domestic", "domestic-night", {"state": "night", "session": "night", "since": "2026-09-17T18:00:00+09:00"}, "2026-09-17T18:00:00+09:00"),
        # 거래 창이 아니면 그 창의 시작은 개장 시각이 아닙니다.
        ("domestic", "domestic-day", {"state": "closing-auction", "session": "day", "since": "2026-09-17T15:35:00+09:00"}, None),
        ("domestic", "domestic-day", {"state": "pre-open", "session": "day", "since": "2026-09-17T08:30:00+09:00"}, None),
        # 주간 실행에 야간 창의 시작을 주지 않습니다.
        ("domestic", "domestic-day", {"state": "night", "session": "night", "since": "2026-09-17T18:00:00+09:00"}, None),
        ("overseas", "overseas", {"state": "open", "session": None, "since": "2026-09-17T07:00:00+09:00"}, "2026-09-17T07:00:00+09:00"),
        ("overseas", "overseas", {"state": "open-2", "session": None, "since": "2026-09-17T12:00:00+09:00"}, None),
        ("domestic", "domestic-day", {"state": "closed", "session": None, "since": None, "source": "unknown"}, None),
    ],
)
def test_개장_시각은_거래_창_안에서만_판정의_since_로_읽는다(monkeypatch, market, session, 판정, 기대):
    from datetime import datetime

    from backend.sessions import sessions_routes

    monkeypatch.setattr(sessions_routes, "judged", lambda m, code, now: {"source": "api", **판정})

    답 = pump_lib._opening_now(market, "CODE", session)

    assert 답 == (None if 기대 is None else int(datetime.fromisoformat(기대).timestamp() * 1000))


# ── 시세 연결이 끊긴 것 같을 때 ────────────────────────────────
#
# 체결이 한동안 안 오면 「데이터 공백」입니다. 그 공백이 `PROBE_AFTER` 를 넘기면
# (맥락, 종목)마다 한 번 현재가를 조회해, 시장이 흘렀는데 이 실행만 못 받았으면
# 끊김으로 갈라 적습니다.

시작 = 1_000
공백 = 시작 + int(runs.GAP_SECONDS * 1000)


class _조회:
    """현재가 조회 자리. 부른 실행을 적고 정해 둔 누적 거래량을 답합니다."""

    def __init__(self, volume=150, fail: bool = False) -> None:
        self.volume = volume
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, run):
        self.calls.append(run.id)
        if self.fail:
            raise RuntimeError("조회 실패")
        return self.volume


def _조용한_펌프(실행목록, 조회: _조회, *, replaying: bool = False, ids=("run1",)):
    돌리는것 = pump_lib.RunPump(실행목록, hub=_허브(), probe=조회, replaying=lambda: replaying)
    for run_id in ids:
        _세우기(실행목록, run_id=run_id)
    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "patch": {"last": 100.0, "volume": 100},
            "trades": [{"timestamp": 시작, "price": 100.0, "quantity": 1}],
        },
        at=시작,
    )
    돌리는것.beat(at=공백)
    return 돌리는것


def _글들(실행목록, run_id="run1") -> list[str]:
    return [one["text"] for one in 실행목록._engine(run_id).events]


def test_실시간의_누적_거래량을_실행에_적어_둔다(실행목록):
    _조용한_펌프(실행목록, _조회())

    engine = 실행목록._engine("run1")
    assert engine.last_volume == 100
    assert engine.feed == engine_lib.GAP
    assert engine.quiet_since == 공백


def test_공백이_오래되기_전에는_조회하지_않는다(실행목록):
    조회 = _조회()
    돌리는것 = _조용한_펌프(실행목록, 조회)

    assert asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_AFTER - 1)) == 0
    assert 조회.calls == []


def test_오래된_공백은_종목마다_한_번_조회한다(실행목록):
    조회 = _조회()
    돌리는것 = _조용한_펌프(실행목록, 조회, ids=("run1", "run2"))

    assert asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_AFTER)) == 1
    assert len(조회.calls) == 1
    # 같은 공백 안에서는 다시 묻지 않습니다 — 간격이 지나도.
    나중 = 공백 + pump_lib.PROBE_AFTER + pump_lib.PROBE_EVERY + 1
    assert asyncio.run(돌리는것.probe_quiet(나중)) == 0
    assert len(조회.calls) == 1


def test_시장이_흘렀으면_끊김으로_적는다(실행목록):
    돌리는것 = _조용한_펌프(실행목록, _조회(volume=150), ids=("run1", "run2"))
    asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_AFTER))

    for run_id in ("run1", "run2"):
        assert _글들(실행목록, run_id)[-1] == engine_lib.FEED_LOST


def test_시장도_조용하면_공백_문장_그대로다(실행목록):
    돌리는것 = _조용한_펌프(실행목록, _조회(volume=100))
    asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_AFTER))

    글들 = _글들(실행목록)
    assert engine_lib.FEED_LOST not in 글들
    assert engine_lib.NO_TRADE in 글들[-1]


@pytest.mark.parametrize("조회", [_조회(fail=True), _조회(volume=None)])
def test_조회가_실패하거나_값이_없으면_판단하지_않는다(실행목록, 조회):
    돌리는것 = _조용한_펌프(실행목록, 조회)
    asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_AFTER))

    assert engine_lib.FEED_LOST not in _글들(실행목록)


def test_재생_중에는_조회하지_않는다(실행목록):
    조회 = _조회()
    돌리는것 = _조용한_펌프(실행목록, 조회, replaying=True)

    assert asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_AFTER)) == 0
    assert 조회.calls == []
    assert engine_lib.FEED_LOST not in _글들(실행목록)


def test_연결이_끊긴_공백은_조회하지_않는다(실행목록):
    조회 = _조회()
    돌리는것 = pump_lib.RunPump(실행목록, hub=_허브(), probe=조회, replaying=lambda: False)
    _세우기(실행목록)
    돌리는것.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=시작)

    assert asyncio.run(돌리는것.probe_quiet(시작 + pump_lib.PROBE_AFTER * 2)) == 0
    assert 조회.calls == []


def test_같은_종목은_간격_안에_다시_묻지_않는다(실행목록, monkeypatch):
    monkeypatch.setattr(pump_lib, "PROBE_AFTER", 0)
    조회 = _조회(volume=100)
    돌리는것 = _조용한_펌프(실행목록, 조회)
    assert asyncio.run(돌리는것.probe_quiet(공백)) == 1

    # 체결이 다시 와 공백이 풀렸다가, 곧 다시 공백이 납니다.
    다시 = 공백 + 1_000
    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "trades": [{"timestamp": 다시, "price": 100.0, "quantity": 1}],
        },
        at=다시,
    )
    또공백 = 다시 + int(runs.GAP_SECONDS * 1000)
    돌리는것.beat(at=또공백)

    assert 실행목록._engine("run1").quiet_since == 또공백
    assert asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_EVERY - 1)) == 0
    assert asyncio.run(돌리는것.probe_quiet(공백 + pump_lib.PROBE_EVERY)) == 1
    assert len(조회.calls) == 2


class _다시거는허브(_허브):
    def __init__(self) -> None:
        super().__init__()
        self.refreshed: list[list[feeds.Feed]] = []

    async def refresh(self, wanted):
        self.refreshed.append(list(wanted))


def test_재개하면_그_실행의_구독을_다시_걸어_달라고_청한다(실행목록):
    허브 = _다시거는허브()
    돌리는것 = pump_lib.RunPump(실행목록, hub=허브)
    돌리는것._client = 허브.attach(pump_lib.NAME)
    _세우기(실행목록)
    _세우기(실행목록, run_id="run2", code="A016C000")
    실행목록.pause("run1", 시작)
    실행목록.resume("run1", 시작 + 1)

    assert asyncio.run(돌리는것.refresh()) == 2
    assert 허브.refreshed == [
        [feeds.Feed(주간, "quote", "A7569000"), feeds.Feed(주간, "book", "A7569000")]
    ]
    # 한 번 청하면 표지를 내립니다.
    assert asyncio.run(돌리는것.refresh()) == 0


def test_허브에_다시_걸기가_없으면_아무것도_안_한다(펌프):
    돌리는것, 실행목록, 허브 = 펌프
    돌리는것._client = 허브.attach(pump_lib.NAME)
    _세우기(실행목록)
    실행목록.pause("run1", 시작)
    실행목록.resume("run1", 시작 + 1)

    assert asyncio.run(돌리는것.refresh()) == 0


# ── 체결이 안 오던 공백에서 돌아오기 ───────────────────────
#
# 30초 동안 체결이 없으면 실행은 공백에 듭니다(`engine.RunEngine.tick_clock`).
# 그 뒤 첫 체결이 **펌프를 지나** 들어올 때 공백이 풀려야 합니다 — 엔진만 직접
# 부르는 시험은 펌프가 엔진보다 먼저 「살아 있다」고 적는 일을 못 잡습니다.


다시 = "시세가 다시 들어옵니다"
공백길이 = int(runs.GAP_SECONDS * 1000)


def _시각(minute: int, second: int = 0) -> int:
    return int(datetime(2026, 9, 17, 10, minute, second, tzinfo=KST).timestamp() * 1000)


def _체결_시세(돌리는것, at: int, price: float = 100.0) -> None:
    돌리는것.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": "A7569000",
            "trades": [{"timestamp": at, "price": price, "quantity": 1}],
        },
        at=at,
    )


def _돌아옴(실행목록, run_id: str) -> int:
    return sum(1 for one in 실행목록._engine(run_id).events if one["text"] == 다시)


def _공백에_넣기(돌리는것, 실행목록, run_id: str, 마지막: int, price: float = 100.0) -> int:
    """마지막 체결 뒤 30초를 시계로 흘려 공백을 만듭니다. 공백에 든 시각을 냅니다."""
    _체결_시세(돌리는것, 마지막, price)
    든때 = 마지막 + 공백길이
    돌리는것.beat(at=든때)
    엔진 = 실행목록._engine(run_id)
    assert 엔진.feed == engine_lib.GAP and 엔진.book.gap
    return 든때


def test_체결이_없던_공백은_다음_체결에서_풀린다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))

    _체결_시세(돌리는것, 든때 + 1_000)

    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == LIVE
    assert 엔진.book.gap is False, "장부가 다시 채울 수 있어야 합니다."
    assert 엔진.quiet_since == 0
    assert _돌아옴(실행목록, "run1") == 1


def test_체결_없는_시세로는_공백이_안_풀린다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))

    돌리는것.take(
        {"type": "quote", "context": 주간, "sym": "A7569000", "patch": {"volume": 7}},
        at=든때 + 1_000,
    )

    assert 실행목록._engine("run1").feed == engine_lib.GAP
    assert _돌아옴(실행목록, "run1") == 0


def test_처음_받은_시세는_공백에서_돌아온_것이_아니다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    assert 실행목록._engine("run1").feed == service_lib.IDLE

    _체결_시세(돌리는것, _시각(0))

    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == LIVE
    assert _돌아옴(실행목록, "run1") == 0
    assert 엔진._after_gap is False


@pytest.fixture
def 단일가없는펌프(실행목록):
    """단일가 구간이 없는 펌프. 종이 장부가 호가로 채우지 않는 까닭이 **공백 하나뿐**이게 합니다.

    여느 펌프는 박자마다 그 종목의 단일가 구간을 묻는데, 시험 마스터의 종목은 판정이
    몰라 늘 단일가로 봅니다. 그러면 공백이 없어도 호가로 안 채워져, 공백을 보는 시험이
    아무것도 재지 못합니다.
    """
    return pump_lib.RunPump(실행목록, hub=_허브(), auction=lambda *_, **__: None), 실행목록, None


def test_단일가가_없으면_종이_장부는_호가로_채운다(단일가없는펌프):
    """아래 두 시험의 짝. 같은 순서에서 공백만 없으면 채워집니다."""
    돌리는것, 실행목록, _ = 단일가없는펌프
    _세우기(실행목록)
    _체결_시세(돌리는것, _시각(0))
    돌리는것.beat(at=_시각(0, 1))
    엔진 = 실행목록._engine("run1")
    엔진.book.place("o1", side="buy", quantity=1, order_type="시장가", at=_시각(0, 1))

    돌리는것.take(
        {
            "type": "book",
            "context": 주간,
            "sym": "A7569000",
            "asks": [{"price": 100.5, "quantity": 9}],
            "bids": [{"price": 100.0, "quantity": 9}],
        },
        at=_시각(0, 11),
    )

    assert [one["price"] for one in 엔진.fills] == [100.5]


def test_종이_장부는_공백_중_호가로_안_채운다(단일가없는펌프):
    돌리는것, 실행목록, _ = 단일가없는펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    엔진 = 실행목록._engine("run1")
    엔진.book.place("o1", side="buy", quantity=1, order_type="시장가", at=든때)

    돌리는것.take(
        {
            "type": "book",
            "context": 주간,
            "sym": "A7569000",
            "asks": [{"price": 100.5, "quantity": 9}],
            "bids": [{"price": 100.0, "quantity": 9}],
        },
        at=든때 + 10_000,
    )

    assert 엔진.fills == [], "끊긴 동안의 호가로는 지어내지 않습니다."


def test_공백_뒤_첫_체결에서_손절을_본다(펌프):
    """끊긴 사이 가격이 손절선을 넘었으면 돌아온 첫 체결에서 바로 닫습니다."""
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    엔진 = 실행목록._engine("run1")
    # 계약당 증거금. 모르면 예산 검사가 진입을 막습니다.
    엔진.run.margin = 1_000.0
    # 1분봉 마감이 100 을 넘어 시장가 매수가 나가고, 다음 호가에 101.5 로 채워집니다.
    _체결_시세(돌리는것, _시각(0), 99.0)
    _체결_시세(돌리는것, _시각(1), 101.0)
    _체결_시세(돌리는것, _시각(2), 101.0)
    호가때 = _시각(2) + int(engine_lib.paper.DELAY_SECONDS * 1000)
    돌리는것.take(
        {
            "type": "book",
            "context": 주간,
            "sym": "A7569000",
            "asks": [{"price": 101.5, "quantity": 9}],
            "bids": [{"price": 101.0, "quantity": 9}],
        },
        at=호가때,
    )
    assert 엔진.ledger.position.quantity == 1 and 엔진.run.state == runs.HOLDING
    # 공백 전 마지막 체결은 손절선 위입니다 — 여기서 손절이 걸리면 이 시험이 아닙니다.
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", 호가때, 101.5)
    assert 엔진.run.state == runs.HOLDING

    # 손절은 평균가 101.5 에서 2틱입니다. 돌아온 첫 체결은 그보다 한 틱 더 아래입니다.
    넘은값 = 101.5 - 3 * 엔진.tick
    _체결_시세(돌리는것, 든때 + 1_000, 넘은값)

    assert 엔진.ledger.position.quantity == 0
    청산 = 엔진.fills[-1]
    assert 청산["price"] == 넘은값 and 청산["time"] == 든때 + 1_000
    assert 청산["reason"] == engine_lib.STOP_LOSS


def _모의_주문(실행목록, run_id: str = "sim1"):
    엔진 = 실행목록._engine(run_id)
    엔진.book.place("o1", side="buy", quantity=1, order_type="시장가", at=_시각(0))
    return 엔진


def _체결_알림(돌리는것, at: int) -> None:
    돌리는것.take(
        {
            "type": "orders",
            "market": "domestic",
            "events": [{"id": "0000012345", "status": "filled", "filled": 1, "remaining": 0}],
        },
        at=at,
    )


def test_공백이_풀린_뒤_계좌_체결을_받는다(모의펌프):
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록)
    엔진 = _모의_주문(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "sim1", _시각(0))
    _체결_시세(돌리는것, 든때 + 1_000)
    assert 엔진.feed == LIVE and _돌아옴(실행목록, "sim1") == 1

    _체결_알림(돌리는것, 든때 + 2_000)

    assert [one["quantity"] for one in 엔진.fills] == [1]


def test_공백_중에도_계좌_체결을_적는다(모의펌프):
    """계좌의 체결은 시세 공백과 상관없이 실제로 난 일입니다."""
    돌리는것, 실행목록, _ = 모의펌프
    _모의세우기(실행목록)
    엔진 = _모의_주문(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "sim1", _시각(0))

    _체결_알림(돌리는것, 든때 + 1_000)

    assert [one["quantity"] for one in 엔진.fills] == [1]
    assert 엔진.feed == engine_lib.GAP, "체결 알림은 시세가 아니라 공백을 안 풉니다."


# ── 체결이 안 오던 공백 중에 연결이 다시 붙을 때 ───────────
#
# 연결이 다시 붙었다는 알림은 체결이 아닙니다. 체결이 안 와서 든 공백은 첫
# 체결에서만 풉니다 — 그 전에 풀면 체결 하나 없이 「시세가 다시 들어옵니다」가
# 적히고 다음 박자에 같은 공백이 다시 걸립니다.


def _다시_붙음(돌리는것, at: int) -> None:
    돌리는것.take({"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=at)


def _공백_줄(실행목록, run_id: str = "run1") -> int:
    return sum(
        1 for one in 실행목록._engine(run_id).events if one["text"].startswith("데이터 공백")
    )


def test_체결이_없던_공백은_연결이_다시_붙어도_그대로다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    돌리는것.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=든때 + 1_000)

    _다시_붙음(돌리는것, 든때 + 2_000)
    돌리는것.beat(at=든때 + 3_000)

    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == engine_lib.GAP and 엔진.book.gap
    assert _돌아옴(실행목록, "run1") == 0, "체결이 온 것이 아닙니다."
    assert _공백_줄(실행목록) == 1, "같은 공백을 다시 적지 않습니다."


def test_연결이_다시_붙은_뒤_첫_체결에서_풀린다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    _다시_붙음(돌리는것, 든때 + 1_000)

    _체결_시세(돌리는것, 든때 + 2_000)

    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == LIVE and 엔진.book.gap is False
    assert _돌아옴(실행목록, "run1") == 1


def test_연결이_끊겨_든_공백은_다시_붙으면_풀린다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    _체결_시세(돌리는것, _시각(0))
    돌리는것.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=_시각(0, 5))
    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == engine_lib.GAP
    # 끊긴 동안 30초가 넘게 흘러도 「체결이 안 온 공백」으로 바뀌지 않습니다.
    돌리는것.beat(at=_시각(0, 50))
    assert 엔진.quiet_since == 0

    _다시_붙음(돌리는것, _시각(0, 55))

    assert 엔진.feed == LIVE and 엔진.book.gap is False
    assert _돌아옴(실행목록, "run1") == 1


def test_다시_붙은_뒤_첫_체결_전_호가로는_종이를_안_채운다(단일가없는펌프):
    돌리는것, 실행목록, _ = 단일가없는펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    _다시_붙음(돌리는것, 든때 + 1_000)
    엔진 = 실행목록._engine("run1")
    주문 = 엔진.book.place("o1", side="buy", quantity=1, order_type="시장가", at=든때 + 1_000)

    돌리는것.take(
        {
            "type": "book",
            "context": 주간,
            "sym": "A7569000",
            "asks": [{"price": 100.5, "quantity": 9}],
            "bids": [{"price": 100.0, "quantity": 9}],
        },
        at=든때 + 10_000,
    )

    assert 엔진.fills == [] and 주문.open, "체결이 오기 전까지는 공백입니다."


def test_다시_붙어도_같은_공백을_두_번_조회하지_않는다(실행목록):
    조회 = _조회(volume=100)
    돌리는것 = _조용한_펌프(실행목록, 조회)
    물은때 = 공백 + pump_lib.PROBE_AFTER
    assert asyncio.run(돌리는것.probe_quiet(물은때)) == 1

    돌리는것.take({"type": "status", "market": "domestic", "state": LIVE, "refill": True}, at=물은때 + 1)
    for 몇 in range(1, 4):
        돌리는것.beat(at=물은때 + 몇 * 1_000)
    나중 = 물은때 + pump_lib.PROBE_AFTER + pump_lib.PROBE_EVERY + 4_000

    assert asyncio.run(돌리는것.probe_quiet(나중)) == 0
    assert len(조회.calls) == 1


# ── 공백 표지를 든 채 시세를 못 받다가(idle) 다시 받을 때 ──────
#
# 공백 중에 구독이 밀리거나 펌프가 멈추면 실행은 `idle` 이 됩니다. 장부는 공백
# 표지를 든 채입니다. 다시 시세가 오면 첫 체결에서 공백을 풀어야 합니다 —
# 그러지 않으면 종이는 계속 안 채우고, 공백 뒤 손절 감시도 안 켜집니다.


def _밀림(돌리는것, at: int) -> None:
    돌리는것.take(
        {
            "type": "subscriptions",
            "granted": [],
            "rejected": [{"context": 주간, "kind": "quote", "sym": "A7569000"}],
        },
        at=at,
    )


def _호가_한_벌(돌리는것, at: int) -> None:
    돌리는것.take(
        {
            "type": "book",
            "context": 주간,
            "sym": "A7569000",
            "asks": [{"price": 100.5, "quantity": 9}],
            "bids": [{"price": 100.0, "quantity": 9}],
        },
        at=at,
    )


def _줄_수(실행목록, 글: str, run_id: str = "run1") -> int:
    return sum(1 for one in 실행목록._engine(run_id).events if 글 in one["text"])


def test_펌프가_멈췄다_다시_받으면_첫_체결에서_공백이_풀린다(단일가없는펌프):
    돌리는것, 실행목록, _ = 단일가없는펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    asyncio.run(돌리는것.stop())
    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == service_lib.IDLE and 엔진.book.gap

    _체결_시세(돌리는것, 든때 + 1_000)

    assert 엔진.feed == LIVE and 엔진.book.gap is False
    assert _돌아옴(실행목록, "run1") == 1
    엔진.book.place("o1", side="buy", quantity=1, order_type="시장가", at=든때 + 1_000)
    _호가_한_벌(돌리는것, 든때 + 10_000)
    assert [one["price"] for one in 엔진.fills] == [100.5], "공백이 풀렸으니 호가로 채웁니다."


def test_구독이_밀렸다_다시_받으면_첫_체결에서_공백이_풀린다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    _밀림(돌리는것, 든때 + 1_000)
    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == service_lib.IDLE and 엔진.book.gap

    _체결_시세(돌리는것, 든때 + 2_000)

    assert 엔진.feed == LIVE and 엔진.book.gap is False
    assert 엔진.quiet_since == 0
    assert _돌아옴(실행목록, "run1") == 1
    assert _줄_수(실행목록, "데이터 공백") == 1 and _줄_수(실행목록, pump_lib.NO_ROOM) == 1


def test_다시_받은_첫_시세가_값만이면_공백_그대로다(단일가없는펌프):
    돌리는것, 실행목록, _ = 단일가없는펌프
    _세우기(실행목록)
    든때 = _공백에_넣기(돌리는것, 실행목록, "run1", _시각(0))
    _밀림(돌리는것, 든때 + 1_000)
    엔진 = 실행목록._engine("run1")

    돌리는것.take(
        {"type": "quote", "context": 주간, "sym": "A7569000", "patch": {"volume": 7}},
        at=든때 + 2_000,
    )

    assert 엔진.feed == engine_lib.GAP and 엔진.book.gap
    assert _돌아옴(실행목록, "run1") == 0
    엔진.book.place("o1", side="buy", quantity=1, order_type="시장가", at=든때 + 2_000)
    _호가_한_벌(돌리는것, 든때 + 10_000)
    assert 엔진.fills == [], "체결이 오기 전까지는 공백입니다."


def test_연결_공백도_펌프가_멈췄다_다시_받으면_풀린다(펌프):
    돌리는것, 실행목록, _ = 펌프
    _세우기(실행목록)
    _체결_시세(돌리는것, _시각(0))
    돌리는것.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=_시각(0, 5))
    엔진 = 실행목록._engine("run1")
    assert 엔진.feed == engine_lib.GAP and 엔진.quiet_since == 0
    asyncio.run(돌리는것.stop())

    _체결_시세(돌리는것, _시각(0, 10))

    assert 엔진.feed == LIVE and 엔진.book.gap is False
    assert _돌아옴(실행목록, "run1") == 1


def test_밀렸다_돌아온_공백을_다시_조회하지_않는다(실행목록):
    조회 = _조회(volume=100)
    돌리는것 = _조용한_펌프(실행목록, 조회)
    물은때 = 공백 + pump_lib.PROBE_AFTER
    assert asyncio.run(돌리는것.probe_quiet(물은때)) == 1
    _밀림(돌리는것, 물은때 + 1)
    돌리는것.take(
        {"type": "quote", "context": 주간, "sym": "A7569000", "patch": {"volume": 100}},
        at=물은때 + 2,
    )
    assert 실행목록._engine("run1").feed == engine_lib.GAP

    나중 = 물은때 + pump_lib.PROBE_AFTER + pump_lib.PROBE_EVERY + 3
    assert asyncio.run(돌리는것.probe_quiet(나중)) == 0
    assert len(조회.calls) == 1


# ── 바뀐 것만 방송 ───────────────────────────────────────


def test_끝난_실행만_남으면_방송을_멈춘다(펌프):
    """끝난 실행은 다시 바뀌지 않습니다. 박자마다 보내면 전략 탭을 쓰지 않는
    화면까지 시세와 같은 큐에서 자리를 내줍니다. 첫 묶음과, 버려졌을 때를
    메우는 한 번만 나갑니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    실행목록.end("run1", 10)

    for 회차 in range(300):  # 100밀리초 박자로 30초.
        돌리는것.beat(at=1_000 + 회차 * 100)

    assert len(허브.sent) == 2, "첫 묶음 하나와 다시 보내기 한 번입니다."
    assert 허브.sent[1]["runs"] == 허브.sent[0]["runs"]
    assert 허브.sent[0]["runs"][0]["state"] == runs.ENDED, "끝난 실행 줄은 그대로 실립니다."


def test_끝난_실행만이어도_박자는_묶음을_돌려준다(펌프):
    """보내지 않는 박자에도 지금 모습은 냅니다 — 부르는 쪽이 그것을 봅니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    실행목록.end("run1", 10)

    돌리는것.beat(at=1)
    보지않은것 = 돌리는것.beat(at=2)

    assert len(허브.sent) == 1
    assert 보지않은것 is not None and 보지않은것["runs"] == 허브.sent[0]["runs"]


def test_도는_실행은_바뀐_박자에만_보낸다(펌프):
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)

    돌리는것.beat(at=1)
    돌리는것.beat(at=101)
    assert len(허브.sent) == 1, "바뀐 것이 없으면 안 보냅니다."

    _체결_시세(돌리는것, at=150, price=101.0)
    돌리는것.beat(at=201)
    assert len(허브.sent) == 2, "체결로 줄이 바뀌면 그 박자에 나갑니다."
    assert 허브.sent[-1]["runs"][0]["lastPrice"] == 101.0

    돌리는것.beat(at=301)
    assert len(허브.sent) == 2


def test_도는_실행의_상태가_바뀌면_보낸다(펌프):
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    돌리는것.beat(at=1)

    실행목록.end("run1", 50)
    돌리는것.beat(at=101)

    assert len(허브.sent) == 2
    assert 허브.sent[-1]["runs"][0]["state"] == runs.ENDED


def test_도는_실행이_있으면_같은_묶음도_간격마다_다시_보낸다(펌프):
    """화면 쪽 큐가 차서 방송 하나가 버려져도, 도는 실행의 모습은 늦어도 이
    간격 안에 다시 닿습니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)

    for 회차 in range(151):  # 100밀리초 박자로 15초. 체결이 없어 공백도 없습니다.
        돌리는것.beat(at=1 + 회차 * 100)

    assert len(허브.sent) == 1 + 15_000 // pump_lib.RESEND_MS


def test_새_화면이_붙으면_같은_묶음도_한_번_보낸다(펌프):
    """새 화면은 앞 방송을 받지 않았습니다. 끝난 실행만 있어도 첫 모습은 받습니다."""
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    실행목록.end("run1", 10)
    허브.attached = 1
    for 회차 in range(100):
        돌리는것.beat(at=1_000 + 회차 * 100)
    앞수 = len(허브.sent)

    허브.attached = 2
    돌리는것.beat(at=20_000)
    돌리는것.beat(at=20_100)

    assert len(허브.sent) == 앞수 + 1, "붙은 뒤 한 번, 그 뒤는 다시 조용합니다."
    assert 허브.sent[-1]["runs"][0]["id"] == "run1"


def test_실행이_모두_없어졌다_다시_서면_보낸다(펌프):
    돌리는것, 실행목록, 허브 = 펌프
    _세우기(실행목록)
    실행목록.end("run1", 10)
    돌리는것.beat(at=1)
    엔진 = 실행목록._engines.pop("run1")

    assert 돌리는것.beat(at=2) is None

    실행목록._engines["run1"] = 엔진
    돌리는것.beat(at=3)
    assert len(허브.sent) == 2, "없어졌다 다시 서면 앞 방송과 같아도 보냅니다."


def test_허브는_화면이_붙은_횟수를_센다():
    from backend.realtime import hub as hub_lib

    허브 = hub_lib.Hub(session_clock=False)
    assert 허브.attached == 0

    async def 붙기():
        허브.attach("가")
        허브.attach("나")
        허브.attach("가")  # 다시 붙은 것도 셉니다.
        await 허브.stop()

    asyncio.run(붙기())
    assert 허브.attached == 3
