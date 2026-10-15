"""반입해 둔 실시간 기록으로 봉·종이 체결을 돌려 봅니다.

지어낸 값은 우리가 아는 모양만 담습니다. **실제로 받아 둔 체결·호가**를 그대로
흘려 넣어야, 값이 글자로 오는 자리나 한 프레임에 여러 칸이 섞여 오는 자리처럼
손으로는 안 지어지는 것이 드러납니다.

기록은 `tests/fixtures/nh/{KA,KB}/…` 입니다 — KA 가 시세(체결), KB 가 호가입니다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.realtime import feeds
from backend.strategy import bars as bar_lib
from backend.strategy import engine, paper, runs

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nh"
맥락 = "domestic-day"


def _기록들(api: str) -> list[list[dict[str, Any]]]:
    """그 구독의 기록마다 자료 프레임 한 벌. 손 인사(INIT)는 빠집니다.

    **기록을 섞지 않습니다.** 기록 하나가 그때 실제로 흘러온 순서이고, 둘을
    이어 붙이면 시각이 앞뒤로 튀는 — 실시간에는 없는 — 흐름이 됩니다.
    """
    made: list[list[dict[str, Any]]] = []
    for path in sorted((FIXTURE_ROOT / api).rglob("*.json")):
        held = json.loads(path.read_text(encoding="utf-8"))
        one: list[dict[str, Any]] = []
        for event in held.get("events", []):
            payload = event.get("payload")
            if event.get("direction") != "received" or not isinstance(payload, dict):
                continue
            body = payload.get("body")
            if isinstance(body, dict):
                one.append(body)
        if one:
            made.append(one)
    return made


@pytest.fixture(scope="module")
def 체결들() -> list[dict[str, Any]]:
    """체결이 가장 많이 담긴 기록 **하나**. 흐름 하나를 그대로 씁니다."""
    쌓인것 = [
        [one for one in (feeds.trade_of(b, context=맥락) for b in 한벌) if one]
        for 한벌 in _기록들("KA")
    ]
    made = max(쌓인것, key=len, default=[])
    if not made:
        pytest.skip("체결이 담긴 시세 기록이 반입되어 있지 않습니다.")
    return made


@pytest.fixture(scope="module")
def 호가들() -> list[dict[str, Any]]:
    쌓인것 = [
        [
            one
            for one in (feeds.book_of(b, context=맥락) for b in 한벌)
            if one["asks"] and one["bids"]
        ]
        for 한벌 in _기록들("KB")
    ]
    made = max(쌓인것, key=len, default=[])
    if not made:
        pytest.skip("호가가 담긴 기록이 반입되어 있지 않습니다.")
    return made


def test_받아_둔_체결로_봉이_선다(체결들):
    """비는 분에 봉을 만들지 않으므로 봉 수는 체결 수보다 적습니다."""
    만드는것 = bar_lib.BarBuilder("1분봉")
    for one in 체결들:
        만드는것.add(one, 맥락)
    만드는것.close()

    assert 만드는것.dropped == 0, "기록의 체결은 모두 시각과 가격을 답니다."
    assert 만드는것.bars
    for 봉 in 만드는것.bars:
        assert 봉.low <= 봉.open <= 봉.high
        assert 봉.low <= 봉.close <= 봉.high
        assert 봉.volume > 0

    총량 = sum(one["quantity"] for one in 체결들)
    assert sum(봉.volume for 봉 in 만드는것.bars) == 총량, "체결 수량이 봉에 다 들어갑니다."


def test_같은_분의_체결은_한_봉에_들어간다(체결들):
    만드는것 = bar_lib.BarBuilder("1분봉")
    for one in 체결들:
        만드는것.add(one, 맥락)
    만드는것.close()

    자리들 = [봉.timestamp for 봉 in 만드는것.bars]
    assert 자리들 == sorted(set(자리들)), "봉 자리는 오름차순이고 겹치지 않습니다."
    assert len(자리들) < len(체결들), "한 분에 여러 체결이 들어 있습니다."
    assert len(자리들) == len({bar_lib.slot_of(one["timestamp"], 1) for one in 체결들})


def test_받아_둔_호가로_시장가가_채워진다(호가들):
    """표시 잔량이 실제로 몇 계약인지는 지어낼 수 없습니다."""
    첫호가 = 호가들[0]
    가까운매도 = 첫호가["asks"][-1]

    장부 = paper.PaperBook(delay=0)
    장부.place("o1", side=paper.BUY, quantity=1, order_type="시장가", at=0)
    (체결,) = 장부.on_book(첫호가, at=0)

    assert 체결["price"] == 가까운매도["price"], "가장 가까운 매도호가를 먹습니다."
    assert 체결["quantity"] == 1


def test_표시_잔량을_넘는_시장가는_다음_단계로_간다(호가들):
    첫호가 = 호가들[0]
    사다리 = list(reversed(첫호가["asks"]))
    if len(사다리) < 2:
        pytest.skip("단계가 둘 이상인 호가 기록이 없습니다.")
    원하는수량 = int(사다리[0]["quantity"]) + 1

    장부 = paper.PaperBook(delay=0)
    장부.place("o1", side=paper.BUY, quantity=원하는수량, order_type="시장가", at=0)
    채운것 = 장부.on_book(첫호가, at=0)

    assert [one["price"] for one in 채운것] == [사다리[0]["price"], 사다리[1]["price"]]
    assert [one["quantity"] for one in 채운것] == [사다리[0]["quantity"], 1]


def test_받아_둔_체결로_엔진을_돌린다(체결들, 호가들):
    """기록이 짧아 신호까지는 못 가지만, 값이 흘러가는 길은 실물로 봅니다."""
    설정 = {
        "baseBar": "1분봉",
        "evalMode": "마감",
        "rules": {"buyEntry": {"on": True, "steps": []}},
        "aux": {"orderType": "시장가", "stopTicks": "2", "takeTicks": "3", "maxHold": "5"},
    }
    실행 = runs.Run(
        id="r1",
        version_id="v1",
        code="A7569000",
        session=맥락,
        market="domestic",
        state=runs.ARMED,
        draft=설정,
        cash=10_000_000.0,
    )
    돌리는것 = engine.RunEngine(실행, tick=0.1)

    for at, one in enumerate(체결들):
        돌리는것.on_trade(one, 맥락, at=one["timestamp"] + at)
    돌리는것.on_book(호가들[0], at=체결들[-1]["timestamp"] + 1000)
    돌리는것.close_session(체결들[-1]["timestamp"] + 2000)

    한벌 = 돌리는것.snapshot()
    assert 한벌["run"]["state"] == runs.ARMED, "조건이 없는 규칙은 걸리지 않습니다."
    assert 한벌["fills"] == [], "낸 주문이 없으니 체결도 없습니다."
    assert 돌리는것.book.last_price == 체결들[-1]["price"]
    assert 한벌["curve"], "봉이 닫힐 때마다 잔고 줄이 한 칸씩 늘어납니다."
    assert 한벌["run"]["feed"] != engine.GAP, "기록 안에서는 시세가 이어집니다."


def test_받아_둔_체결_사이가_멀면_공백으로_본다(체결들):
    """기록의 시각을 그대로 쓰되, 마지막 체결에서 시계만 흘려 봅니다."""
    설정 = {"baseBar": "1분봉", "rules": {}, "aux": {}}
    실행 = runs.Run(
        id="r1",
        version_id="v1",
        code="A7569000",
        session=맥락,
        market="domestic",
        state=runs.ARMED,
        draft=설정,
    )
    돌리는것 = engine.RunEngine(실행, tick=0.1)
    첫체결 = 체결들[0]
    돌리는것.on_trade(첫체결, 맥락, at=첫체결["timestamp"])

    돌리는것.tick_clock(첫체결["timestamp"] + int(runs.GAP_SECONDS * 1000))

    assert 돌리는것.feed == engine.GAP
    (공백,) = [one for one in 돌리는것.events if one["kind"] == engine.GAP]
    assert "데이터 공백" in 공백["text"]
