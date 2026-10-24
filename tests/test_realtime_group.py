"""한 연결이 지는 구독 수 — 서버에서 확인되면 값 하나만 바꾸면 되는지.

명세에 「한 연결에 구독을 여럿 걸 수 있는가」가 적혀 있지 않습니다. 그래서 그
수를 값 하나로 두었고, 하나씩만 된다면 1 로 내리는 것으로 끝나야 합니다.
구조를 다시 짜야 한다면 그 값은 안전장치가 아닙니다.
"""
from __future__ import annotations

import asyncio

from backend.realtime.feeds import Feed
from backend.realtime.hub import MarketGroup
from backend.realtime.ledger import stream_key


class FakeLink:
    """구독을 세기만 하는 연결."""

    made: list["FakeLink"] = []

    def __init__(self) -> None:
        self.keys_held: dict = {}
        self.started = False
        self.stopped = False
        self.refreshed: list = []
        self.ops: list = []

    @property
    def keys(self):
        return frozenset(self.keys_held)

    def __len__(self) -> int:
        return len(self.keys_held)

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def add(self, key, feed) -> None:
        self.keys_held[key] = feed
        self.ops.append(("add", key))

    async def remove(self, key) -> None:
        self.keys_held.pop(key, None)
        self.ops.append(("remove", key))

    async def refresh(self, key) -> None:
        self.refreshed.append(key)


def 무리(capacity: int) -> tuple[MarketGroup, list[FakeLink]]:
    made: list[FakeLink] = []

    def 하나() -> FakeLink:
        link = FakeLink()
        made.append(link)
        return link

    return MarketGroup("domestic", capacity=capacity, make_link=하나), made


def 시세(sym: str) -> Feed:
    return Feed("domestic-day", "quote", sym)


def 원하는것(*syms: str) -> dict:
    return {stream_key(시세(s)): 시세(s) for s in syms}


def test_여럿을_걸_수_있으면_연결_하나로_끝난다():
    group, made = 무리(20)
    asyncio.run(group.apply(원하는것("A", "B", "C")))

    assert len(made) == 1
    assert len(made[0]) == 3


def test_하나씩만_된다면_구독마다_연결이_하나씩_열린다():
    group, made = 무리(1)
    asyncio.run(group.apply(원하는것("A", "B", "C")))

    assert len(made) == 3
    assert all(len(link) == 1 for link in made)
    assert all(link.started for link in made)


def test_자리가_차면_다음_연결을_연다():
    group, made = 무리(2)
    asyncio.run(group.apply(원하는것("A", "B", "C")))

    assert len(made) == 2
    assert sorted(len(link) for link in made) == [1, 2]


def test_그만_보는_구독은_해제한다():
    group, made = 무리(20)

    async def 실행():
        await group.apply(원하는것("A", "B"))
        await group.apply(원하는것("A"))

    asyncio.run(실행())
    assert {key[2] for key in made[0].keys} == {"A"}


def test_빈_연결은_닫는다():
    group, made = 무리(20)

    async def 실행():
        await group.apply(원하는것("A"))
        await group.apply({})

    asyncio.run(실행())
    assert made[0].stopped
    assert group.links == ()


def test_이미_걸린_구독은_다시_걸지_않는다():
    group, made = 무리(1)

    async def 실행():
        await group.apply(원하는것("A"))
        await group.apply(원하는것("A", "B"))

    asyncio.run(실행())
    # A 가 이미 있던 연결에 남고, B 만 새 연결로 갑니다.
    assert len(made) == 2
    assert {key[2] for key in made[0].keys} == {"A"}
    assert {key[2] for key in made[1].keys} == {"B"}


def test_다시_걸기는_그_구독을_든_연결에만_청한다():
    group, made = 무리(1)
    asyncio.run(group.apply(원하는것("A", "B")))
    asyncio.run(group.refresh(stream_key(시세("B"))))

    [든것] = [link for link in made if stream_key(시세("B")) in link.keys]
    assert 든것.refreshed == [stream_key(시세("B"))]
    assert all(link.refreshed == [] for link in made if link is not 든것)
    # 자리 셈은 그대로입니다.
    assert sum(len(link) for link in made) == 2


# ── 주간·야간 짝 ────────────────────────────────────────────
#
# 연결은 국내 체결·호가의 주간·야간 짝을 서버에 늘 함께 등록합니다. 짝이 든
# 연결에 걸어야 새 등록 없이 받을 수 있고, 주간에서 야간으로 바꿀 때 해제가
# 먼저 가면 짝 둘 다 서버에서 내려갑니다.


def 야간(sym: str) -> Feed:
    return Feed("domestic-night", "quote", sym)


def test_짝은_자리가_차도_짝이_든_연결에_건다():
    group, made = 무리(1)

    async def 실행():
        await group.apply(원하는것("A"))
        await group.apply({**원하는것("A"), stream_key(야간("A")): 야간("A")})

    asyncio.run(실행())
    assert len(made) == 1
    assert made[0].keys == frozenset({stream_key(시세("A")), stream_key(야간("A"))})


def test_주간에서_야간으로_바꾸면_야간을_먼저_걸고_주간을_푼다():
    group, made = 무리(20)

    async def 실행():
        await group.apply(원하는것("A"))
        made[0].ops.clear()
        await group.apply({stream_key(야간("A")): 야간("A")})

    asyncio.run(실행())
    assert made[0].ops == [("add", stream_key(야간("A"))), ("remove", stream_key(시세("A")))]
    assert made[0].keys == frozenset({stream_key(야간("A"))})


def test_짝이_없는_구독의_차례는_전과_같다():
    group, made = 무리(20)

    async def 실행():
        await group.apply(원하는것("A"))
        made[0].ops.clear()
        await group.apply(원하는것("B"))

    asyncio.run(실행())
    assert made[0].ops == [("remove", stream_key(시세("A"))), ("add", stream_key(시세("B")))]
