"""평가 방식 「틱」 — 체결 시세마다 **진행 중인 봉까지** 넣어 판정합니다.

시험은 모두 **펌프를 거칩니다**(`pump.take`). 판정이 체결 묶음마다 한 번인지는
펌프가 엔진을 어떻게 부르는지에 달려, 엔진만 직접 부르면 그 자리를 못 잽니다.
시각은 가짜입니다(`at`).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.realtime.link import LIVE
from backend.sessions.hours import KST
from backend.strategy import backtest, engine as engine_lib, journal as journal_lib
from backend.strategy import pump as pump_lib, runs, service as service_lib
from tests.test_strategy_pump import _마스터, _시간표, _허브

주간 = "domestic-day"
종목 = "A7569000"


def _시각(minute: int, second: int = 0) -> int:
    return int(datetime(2026, 9, 17, 10, minute, second, tzinfo=KST).timestamp() * 1000)


def _조건(op: str, value: str) -> dict:
    return {"id": "c1", "left": "close", "op": op, "rightKind": "number", "right": value}


def _규칙(*conds: dict) -> dict:
    return {"on": True, "steps": [{"id": "s1", "join": "all", "withinBars": 0, "conds": list(conds)}]}


def _설정(평가: str, *, 청산: dict | None = None, **aux) -> dict:
    묶음 = {
        "orderType": "시장가",
        "priceBasis": "신호가",
        "stopBasis": "",
        "fillCond": "FAS",
        # 손절·익절은 멀리 둡니다 — 이 파일은 규칙 판정만 봅니다.
        "stopTicks": "50",
        "takeTicks": "50",
        "perOrder": "1",
        "maxHold": "5",
        "session": "국내 주간",
        "addWhileOpen": False,
        "dailyLoss": "300000000",
        "marginBudget": "10000000",
    }
    묶음.update(aux)
    return {
        "memo": "",
        "baseBar": "1분봉",
        "evalMode": 평가,
        "rules": {
            "buyEntry": _규칙(_조건("gt", "100")),
            "sellEntry": {"on": False, "steps": []},
            "buyExit": 청산 if 청산 is not None else {"on": False, "steps": []},
            "sellExit": {"on": False, "steps": []},
        },
        "aux": 묶음,
    }


def _실행목록(tmp_path) -> service_lib.RunService:
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )


@pytest.fixture
def 실행목록(tmp_path):
    return _실행목록(tmp_path)


@pytest.fixture
def 펌프(실행목록):
    # 단일가 구간이 없는 펌프입니다. 시험 마스터의 종목은 판정이 몰라 늘 단일가로
    # 보이므로, 그대로 두면 종이 장부가 호가로 채우지 않습니다.
    return pump_lib.RunPump(실행목록, hub=_허브(), auction=lambda *_, **__: None)


def _세우기(실행목록, 평가: str = "틱", run_id: str = "run1", **덮어쓰기) -> engine_lib.RunEngine:
    실행목록.add(
        run_id=run_id,
        version_id="v1",
        draft=_설정(평가, **덮어쓰기),
        market="domestic",
        code=종목,
        session=주간,
        qty=1,
        cash=10_000_000.0,
        fee_per_contract=0.0,
    )
    엔진 = 실행목록._engine(run_id)
    # 계약당 증거금. 모르면 예산 검사가 진입을 막습니다.
    엔진.run.margin = 1_000.0
    return 엔진


def _체결(펌프, at: int, *prices: float) -> None:
    """체결 묶음 하나. 값이 여럿이면 한 묶음에 함께 실려 옵니다."""
    펌프.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": 종목,
            "trades": [{"timestamp": at, "price": p, "quantity": 1} for p in prices],
        },
        at=at,
    )


def _호가(펌프, at: int, ask: float, bid: float) -> None:
    펌프.take(
        {
            "type": "book",
            "context": 주간,
            "sym": 종목,
            "asks": [{"price": ask, "quantity": 9}],
            "bids": [{"price": bid, "quantity": 9}],
        },
        at=at,
    )


def _준비(펌프) -> None:
    """닫힌 봉 둘(종가 99)을 만들어 판정할 수 있게 합니다. 10:02 봉이 열려 있습니다."""
    _체결(펌프, _시각(0), 99.0)
    _체결(펌프, _시각(1), 99.0)
    _체결(펌프, _시각(2), 99.0)


def _신호(엔진) -> list[dict]:
    return [one for one in 엔진.events if one["kind"] == engine_lib.SIGNAL]


def _진입_주문(엔진) -> list:
    return [one for one in 엔진.book.orders if 엔진._purpose.get(one.id) == "entry"]


# ── 틱 판정 ─────────────────────────────────────────────


def test_진행_중인_봉에서_조건이_참이_되면_그_체결에서_낸다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)

    (신호,) = _신호(엔진)
    assert 신호["time"] == _시각(2, 10)
    assert 신호["partialBar"] is True and 신호["evalMode"] == "틱"
    assert len(_진입_주문(엔진)) == 1, "봉이 닫히기 전에 주문이 나갑니다."


def test_같은_봉에서는_다시_안_낸다(펌프, 실행목록):
    """값이 문턱을 오르내려도 한 봉에 한 번입니다."""
    엔진 = _세우기(실행목록)
    _준비(펌프)
    _체결(펌프, _시각(2, 10), 100.5)

    _체결(펌프, _시각(2, 20), 99.5)
    _체결(펌프, _시각(2, 30), 100.6)

    assert len(_신호(엔진)) == 1
    assert len(_진입_주문(엔진)) == 1


def test_주문이_막혀도_같은_봉에서는_신호를_한_번만_센다(펌프, 실행목록):
    """주문이 안 나가면 그 봉의 판정이 계속 돕니다. 그래도 규칙은 한 번만 겁니다."""
    엔진 = _세우기(실행목록)
    엔진.run.margin = None  # 예산을 확인할 수 없어 진입이 막힙니다.
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)
    _체결(펌프, _시각(2, 20), 99.5)
    _체결(펌프, _시각(2, 30), 100.6)

    assert len(_신호(엔진)) == 1
    assert 엔진.unsent_today(_시각(2, 30)) == 1, "안 낸 신호도 한 번입니다."


def test_봉이_바뀌면_다시_걸_수_있다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)
    _체결(펌프, _시각(2, 10), 100.5)
    _체결(펌프, _시각(2, 50), 99.0)  # 10:02 봉은 99 로 닫힙니다.

    _체결(펌프, _시각(3, 10), 100.5)

    assert [one["time"] for one in _신호(엔진)] == [_시각(2, 10), _시각(3, 10)]


def test_봉이_닫힐_때_다시_판정하지_않는다(펌프, 실행목록):
    """틱에서 걸린 봉이 100 위로 닫혀도 마감에서 또 걸지 않습니다."""
    엔진 = _세우기(실행목록)
    _준비(펌프)
    _체결(펌프, _시각(2, 10), 100.5)

    _체결(펌프, _시각(3), 100.7)  # 10:02 봉이 100.5 로 닫힙니다.

    assert len(_신호(엔진)) == 1


def test_묶음_하나에는_한_번_마지막_체결가로_판정한다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 99.5, 100.5, 99.0)

    assert _신호(엔진) == [], "묶음 가운데의 100.5 로는 판정하지 않습니다."


def test_청산이_나간_봉에서는_진입을_안_본다(펌프, 실행목록):
    엔진 = _세우기(실행목록, 청산=_규칙(_조건("lt", "99")))
    _준비(펌프)
    _체결(펌프, _시각(2, 10), 100.5)  # 진입
    _호가(펌프, _시각(2, 11), 100.5, 100.0)
    assert 엔진.ledger.position.quantity == 1
    _체결(펌프, _시각(2, 50), 99.5)  # 10:02 봉은 99.5 로 닫힙니다(진입·청산 모두 거짓).

    _체결(펌프, _시각(3, 10), 98.5)  # 청산 규칙이 걸립니다.
    _체결(펌프, _시각(3, 20), 100.5)  # 진입 조건도 참이 되지만 같은 봉입니다.

    글 = [one["text"] for one in _신호(엔진)]
    assert 글 == ["매수 진입 규칙이 걸렸습니다", "매수 청산 규칙이 걸렸습니다"]
    assert [one.side for one in 엔진.book.orders] == ["buy", "sell"], "진입 하나, 청산 하나뿐입니다."


def test_여러_단계_규칙은_틱에서_걸린_봉을_걸린_것으로_확정한다(펌프, 실행목록):
    """2단계가 틱에서 걸린 봉이 그 값 아래로 닫혀도, 다음 봉에서 같은 신호를 또 걸지 않습니다."""
    엔진 = _세우기(실행목록)
    엔진.rules["buyEntry"] = {
        "on": True,
        "steps": [
            {"id": "s1", "join": "all", "withinBars": 3, "conds": [_조건("gt", "100")]},
            {"id": "s2", "join": "all", "withinBars": 0, "conds": [_조건("gt", "101")]},
        ],
    }
    엔진.run.margin = None  # 주문은 막고 신호만 셉니다(예산 확인 불가).
    _준비(펌프)
    _체결(펌프, _시각(2, 50), 100.5)  # 1단계는 10:02 봉 마감 값으로 채워집니다.
    _체결(펌프, _시각(3, 10), 101.5)  # 10:03 봉 안에서 2단계 — 걸림
    _체결(펌프, _시각(3, 50), 100.5)  # 10:03 봉은 101 아래로 닫힙니다.

    _체결(펌프, _시각(4, 10), 101.5)

    assert [one["time"] for one in _신호(엔진)] == [_시각(3, 10)]


# ── 마감 방식은 그대로 ───────────────────────────────────


def test_마감_방식은_봉이_닫힐_때만_낸다(펌프, 실행목록):
    엔진 = _세우기(실행목록, "마감")
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)
    assert _신호(엔진) == [] and _진입_주문(엔진) == [], "진행 중인 봉으로는 판정하지 않습니다."

    _체결(펌프, _시각(3), 100.7)  # 10:02 봉이 100.5 로 닫힙니다.

    (신호,) = _신호(엔진)
    assert 신호["time"] == _시각(3) and "partialBar" not in 신호


# ── 판정하지 않는 때 ─────────────────────────────────────


def test_공백_중에는_판정하지_않는다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)
    펌프.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=_시각(2, 5))
    assert 엔진.feed == engine_lib.GAP

    # 체결 없이 값만 바뀐 시세 — 공백이 안 풀리고 판정도 없습니다.
    펌프.take(
        {"type": "quote", "context": 주간, "sym": 종목, "patch": {"last": 100.5}},
        at=_시각(2, 10),
    )

    assert _신호(엔진) == []


def test_공백에서_풀린_뒤_다음_봉이_닫히기_전에는_판정하지_않는다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)
    펌프.take({"type": "status", "market": "domestic", "state": "reconnecting"}, at=_시각(2, 5))
    펌프.take({"type": "status", "market": "domestic", "state": LIVE}, at=_시각(2, 6))
    assert 엔진.feed == LIVE

    _체결(펌프, _시각(2, 10), 100.5)
    assert _신호(엔진) == [], "풀린 봉 안에서는 쉽니다."
    _체결(펌프, _시각(2, 50), 99.0)

    _체결(펌프, _시각(3, 10), 100.5)  # 10:02 봉이 닫힌 뒤입니다.

    assert [one["time"] for one in _신호(엔진)] == [_시각(3, 10)]


def test_되살린_실행은_틱_판정을_쉬며_선다(실행목록, tmp_path):
    _세우기(실행목록)
    다시 = _실행목록(tmp_path)

    다시.load()
    되살린 = 다시._engine("run1")

    assert 되살린.eval_tick, "평가 방식은 실행에 담긴 설정에서 읽습니다."
    assert 되살린._tick_rest_from is not None


def test_쉬는_동안은_안_걸고_봉이_닫히면_다시_건다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)
    엔진.rest_ticks()

    _체결(펌프, _시각(2, 10), 100.5)
    _체결(펌프, _시각(2, 50), 99.0)
    _체결(펌프, _시각(3, 10), 100.5)

    assert [one["time"] for one in _신호(엔진)] == [_시각(3, 10)]


# ── 진입 시간·표지 ───────────────────────────────────────


def test_신규_진입_시간은_체결_시각으로_본다(펌프, 실행목록):
    """10:03 까지인 창에서 10:02 봉의 10초 체결은 안입니다. 마감이면 봉 마감 10:03 이라 밖입니다."""
    틱 = _세우기(실행목록, entryEnd="10:03")
    마감 = _세우기(실행목록, "마감", run_id="run2", entryEnd="10:03")
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)
    _체결(펌프, _시각(3), 100.7)

    assert len(_진입_주문(틱)) == 1
    assert _진입_주문(마감) == []
    assert any(runs.WHY_ENTRY_WINDOW in one["text"] for one in 마감.events)


def test_틱에서_낸_주문에는_그_순간의_표지를_묶는다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)

    (주문,) = _진입_주문(엔진)
    묶음 = 엔진._snap[주문.id]
    assert 묶음["barTime"] == _시각(2), "진행 중인 봉의 시각입니다."
    assert 묶음["evalMode"] == "틱" and 묶음["partialBar"] is True
    assert 묶음["judgedAt"] == _시각(2, 10)
    assert 묶음["values"]["close"] == 100.5


def test_체결이_없으면_펌프가_판정을_부르지_않는다(펌프, 실행목록, monkeypatch):
    엔진 = _세우기(실행목록)
    부름: list[int] = []
    monkeypatch.setattr(엔진, "judge_tick", lambda at: 부름.append(at))

    펌프.take({"type": "quote", "context": 주간, "sym": 종목, "patch": {"volume": 3}}, at=_시각(0))
    _체결(펌프, _시각(0, 1), 99.0, 99.5)

    assert 부름 == [_시각(0, 1)], "묶음마다 한 번, 체결이 있을 때만입니다."


# ── 백테스트 ─────────────────────────────────────────────


def test_백테스트는_틱_전략도_봉_마감으로_세고_표지를_단다():
    from tests.test_strategy_backtest import _물결, _셈

    봉들 = _물결(120)
    틱 = _셈(봉들, _설정("틱"))
    마감 = _셈(봉들, _설정("마감"))

    assert 틱["assumptions"]["evalBasis"] == 마감["assumptions"]["evalBasis"] == "bar-close"
    assert {k: v for k, v in 틱.items() if k != "assumptions"} == {
        k: v for k, v in 마감.items() if k != "assumptions"
    }


def test_백테스트_엔진은_실행_설정이_틱이어도_마감으로_판정한다():
    run = runs.Run(
        id="b",
        version_id="v",
        code=종목,
        session=주간,
        market="domestic",
        state=runs.ARMED,
        qty=1,
        cash=1e7,
        multiplier=1.0,
        draft=_설정("틱"),
    )

    assert backtest.BacktestEngine(run, every=[], tick=0.05).eval_tick is False
    assert engine_lib.RunEngine(run, tick=0.05).eval_tick is True


# ── 봉 마감 일은 봉 마감에서만 ───────────────────────────


def test_틱_판정은_봉_마감_일을_하지_않는다(펌프, 실행목록, monkeypatch):
    """기록·거래일·곡선·청산 뒤 대기 셈은 봉이 닫힐 때만입니다 — 체결마다 돌면 하루 경계가 깨집니다."""
    엔진 = _세우기(실행목록)
    _준비(펌프)
    셈: list[str] = []
    for 이름 in ("_mark", "_catch_day", "_write_day"):
        원래 = getattr(엔진, 이름)
        monkeypatch.setattr(엔진, 이름, lambda *a, _n=이름, _f=원래, **k: (셈.append(_n), _f(*a, **k))[1])
    원래_넘김 = 엔진.run.roll_day
    monkeypatch.setattr(엔진.run, "roll_day", lambda *a, **k: (셈.append("roll_day"), 원래_넘김(*a, **k))[1])
    곡선 = len(엔진.curve)
    엔진._wait_left = 3

    for 초 in (10, 20, 30, 40):
        _체결(펌프, _시각(2, 초), 100.5 if 초 == 10 else 100.0 + 초 / 100)

    assert len(_신호(엔진)) == 1, "틱 판정은 돌았습니다."
    assert 셈 == [] and len(엔진.curve) == 곡선 and 엔진._wait_left == 3


def test_마감_전략은_진행_중인_봉을_세지_않는다(펌프, 실행목록, monkeypatch):
    마감 = _세우기(실행목록, "마감")
    틱 = _세우기(실행목록, run_id="run2")
    _준비(펌프)
    셈 = {"마감": 0, "틱": 0}
    for 이름, 엔진 in (("마감", 마감), ("틱", 틱)):
        원래 = 엔진._live_series
        monkeypatch.setattr(
            엔진, "_live_series", lambda *a, _n=이름, _f=원래, **k: (셈.__setitem__(_n, 셈[_n] + 1), _f(*a, **k))[1]
        )

    for 초 in (10, 20, 30):
        _체결(펌프, _시각(2, 초), 99.5)

    assert 셈 == {"마감": 0, "틱": 3}


# ── 단계·대기 ────────────────────────────────────────────


def test_한_봉에서_단계를_둘_건너뛰지_않는다(펌프, 실행목록):
    """1단계를 채운 체결 뒤에 2단계 값이 와도 같은 봉에서는 걸리지 않습니다 — 마감과 같은 폭입니다."""
    엔진 = _세우기(실행목록)
    엔진.rules["buyEntry"] = {
        "on": True,
        "steps": [
            {"id": "s1", "join": "all", "withinBars": 3, "conds": [_조건("gt", "100")]},
            {"id": "s2", "join": "all", "withinBars": 0, "conds": [_조건("gt", "101")]},
        ],
    }
    엔진.run.margin = None  # 주문은 막고 신호만 셉니다.
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)  # 1단계
    _체결(펌프, _시각(2, 20), 101.5)  # 2단계 값이지만 같은 봉
    assert _신호(엔진) == []
    _체결(펌프, _시각(2, 50), 100.5)  # 10:02 봉은 100.5 — 1단계가 닫힌 값으로 확정됩니다.

    _체결(펌프, _시각(3, 10), 101.5)

    assert [one["time"] for one in _신호(엔진)] == [_시각(3, 10)]


def test_청산_뒤_대기_봉_동안은_틱으로도_진입하지_않는다(펌프, 실행목록):
    엔진 = _세우기(실행목록, 청산=_규칙(_조건("lt", "99")), reentryWaitBars="2")
    _준비(펌프)
    _체결(펌프, _시각(2, 10), 100.5)  # 진입
    _호가(펌프, _시각(2, 11), 100.5, 100.0)
    _체결(펌프, _시각(2, 50), 99.5)
    _체결(펌프, _시각(3, 10), 98.5)  # 청산
    _호가(펌프, _시각(3, 11), 99.0, 98.5)
    assert 엔진.ledger.position.quantity == 0
    _체결(펌프, _시각(3, 50), 99.5)  # 대기 봉 하나가 지납니다.

    _체결(펌프, _시각(4, 10), 100.5)  # 아직 대기 중
    assert [one.side for one in 엔진.book.orders] == ["buy", "sell"]
    assert any(runs.WHY_REENTRY_WAIT in one["text"] for one in 엔진.events)
    _체결(펌프, _시각(4, 50), 99.5)

    _체결(펌프, _시각(5, 10), 100.5)

    assert [one.side for one in 엔진.book.orders] == ["buy", "sell", "buy"]


# ── 되살린 직후·체결 ─────────────────────────────────────


def test_다시_켠_직후에는_같은_봉에서_다시_걸지_않는다(실행목록, tmp_path):
    """앞서 돌던 엔진이 그 봉에서 이미 걸었는지 모릅니다. 다시 켠 엔진은 다음 봉부터 겁니다."""
    _세우기(실행목록)
    다시 = _실행목록(tmp_path)
    다시.load()
    되살린 = 다시._engine("run1")
    되살린.run.state = runs.ARMED
    되살린.run.margin = 1_000.0
    펌프 = pump_lib.RunPump(다시, hub=_허브(), auction=lambda *_, **__: None)
    # 지난 봉은 조회로 받고, 실시간은 진행 중인 10:02 봉부터 옵니다.
    되살린.seed(
        [{"timestamp": _시각(m), "close": 99.0} for m in (0, 1)], 주간
    )
    _체결(펌프, _시각(2), 99.0)

    _체결(펌프, _시각(2, 10), 100.5)
    assert _신호(되살린) == []
    _체결(펌프, _시각(2, 50), 99.0)

    _체결(펌프, _시각(3, 10), 100.5)

    assert [one["time"] for one in _신호(되살린)] == [_시각(3, 10)]


def test_틱_신호의_시장가는_접수_지연_뒤_호가로_채운다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)
    _체결(펌프, _시각(2, 10), 100.5)

    _호가(펌프, _시각(2, 10) + 100, 100.6, 100.4)
    assert 엔진.fills == [], "접수 지연 전입니다."
    _호가(펌프, _시각(2, 11), 100.7, 100.5)

    (체결,) = 엔진.fills
    assert 체결["price"] == 100.7 and 체결["model"] == "paper-v2"
    assert 체결["snapshot"]["evalMode"] == "틱" and 체결["snapshot"]["judgedAt"] == _시각(2, 10)


# ── 부하 ─────────────────────────────────────────────────


def test_실행_일곱_이천봉의_틱_판정이_넉넉한_상한_안에_끝난다(tmp_path):
    """실행 일곱(종목마다 하나) × 2000봉 × 규칙 넷. 봉 경계 묶음과 봉 안 묶음을 다섯 번씩 잽니다.

    단정은 넉넉하게 둡니다(경계 합 300ms, 봉 안 합 60ms, 다섯 번의 중앙값) — 그때
    기계가 얼마나 바쁜지에 달린 값이라 빠듯하면 바쁜 기계에서만 틀립니다.
    """
    import statistics
    import time

    from tests.test_strategy_backtest import _네_규칙, _물결

    목록 = _실행목록(tmp_path)
    종목들 = [f"A75690{n:02d}" for n in range(7)]
    봉들 = _물결(2000)
    for 하나 in 종목들:
        설정 = _네_규칙()
        설정["evalMode"] = "틱"
        목록.add(
            run_id=하나,
            version_id="v1",
            draft=설정,
            market="domestic",
            code=하나,
            session=주간,
            qty=1,
            cash=10_000_000.0,
            fee_per_contract=0.0,
        )
        엔진 = 목록._engine(하나)
        엔진.bars.bars = list(봉들)
        엔진.bars.sessions = [주간] * len(봉들)
    펌프 = pump_lib.RunPump(목록, hub=_허브(), auction=lambda *_, **__: None)

    def 묶음(code: str, at: int, price: float = 100.0) -> None:
        펌프.take(
            {
                "type": "quote",
                "context": 주간,
                "sym": code,
                "trades": [{"timestamp": at, "price": price, "quantity": 1}],
            },
            at=at,
        )

    처음 = 봉들[-1].timestamp + 60_000
    for 하나 in 종목들:
        묶음(하나, 처음)
        묶음(하나, 처음 + 1_000)
    경계: list[float] = []
    안: list[float] = []
    for 번 in range(1, 6):
        칸 = 처음 + 번 * 60_000
        시작 = time.perf_counter()
        for 하나 in 종목들:
            묶음(하나, 칸)
        경계.append((time.perf_counter() - 시작) * 1000)
        for 몇 in range(1, 6):
            시작 = time.perf_counter()
            for 하나 in 종목들:
                묶음(하나, 칸 + 몇 * 100, 100.0 + 몇 / 100)
            안.append((time.perf_counter() - 시작) * 1000)

    assert len(목록._engine(종목들[0]).bars.bars) == 2000, "봉 수 상한에서 앞이 잘리는 길입니다."
    assert statistics.median(경계) < 300
    assert statistics.median(안) < 60


# ── 이어 세기·이어 굴리기 = 처음부터 세기 ────────────────


def _모든_지표() -> list[tuple[str, dict]]:
    """저장이 받는 가장 긴 기간으로 지표 전부. 앞 값을 기억하는 지표(EMA·RSI·ATR·MACD)가 듭니다."""
    from backend.strategy import rules

    made: list[tuple[str, dict]] = [("vwap", {})]
    for name, spec in rules.PARAM_SPECS.items():
        params: dict = {}
        for key, default in spec:
            if key in ("period", "slow", "signal"):
                params[key] = 200
            elif key == "fast":
                params[key] = 199
            elif key in ("k", "d"):
                params[key] = 50
            else:
                params[key] = default
        made.append((name, params))
    return made


def test_이어_센_판정_값은_처음부터_센_값과_같다():
    """봉 수 상한에서 앞이 한 봉씩 잘리는 길입니다. 모든 칸이 처음부터 센 값과 같아야 합니다."""
    from backend.strategy import rules
    from tests.test_strategy_backtest import _물결

    창 = 600  # 기간 200 지표가 값을 내기에 넉넉한 봉 수 상한
    봉들 = _물결(창 + 40)
    세션 = [주간] * len(봉들)
    원하는것 = _모든_지표()
    적은값 = {
        one.timestamp: {"bid1": one.close - 0.05, "positionQty": float(i % 3), "barOrder": float(i)}
        for i, one in enumerate(봉들)
    }

    앞 = rules.series_of(봉들[:창], sessions=세션[:창], marks=적은값, session=주간, wanted=원하는것)
    assert 앞.at("ema(200)", 창 - 1) is not None, "기간 200 지표가 값을 냅니다."
    for 끝 in range(창 + 1, len(봉들) + 1):
        잘림 = 끝 - 창
        목록 = 봉들[잘림:끝]
        이어 = rules.extend_series(
            앞,
            목록,
            drop=1,
            sessions=세션[잘림:끝],
            mark=적은값[목록[-1].timestamp],
            session=주간,
            wanted=원하는것,
        )
        전체 = rules.series_of(
            목록, sessions=세션[잘림:끝], marks=적은값, session=주간, wanted=원하는것
        )
        assert 이어.values.keys() == 전체.values.keys()
        for 이름 in 전체.values:
            assert 이어.values[이름] == 전체.values[이름], 이름
        앞 = 이어


def test_이어_센_판정_값은_잘리지_않을_때도_같다():
    from backend.strategy import rules
    from tests.test_strategy_backtest import _물결

    봉들 = _물결(300)
    원하는것 = _모든_지표()
    앞 = rules.series_of(봉들[:299], sessions=[주간] * 299, session=주간, wanted=원하는것)

    이어 = rules.extend_series(앞, 봉들, sessions=[주간] * 300, session=주간, wanted=원하는것)
    전체 = rules.series_of(봉들, sessions=[주간] * 300, session=주간, wanted=원하는것)

    assert 이어.values == 전체.values


def _다단계() -> dict:
    return {
        "on": True,
        "resetBars": 4,
        "steps": [
            {"id": "s1", "join": "all", "withinBars": 3, "conds": [_조건("gt", "100")]},
            {"id": "s2", "join": "all", "withinBars": 2, "conds": [_조건("gt", "100.4")]},
            {"id": "s3", "join": "all", "withinBars": 0, "conds": [_조건("lt", "100.2")]},
        ],
    }


def _물결_체결(펌프, 분: int) -> None:
    """분마다 오르내리는 체결 셋. 다단계 규칙이 여러 번 걸리고 시한이 지나게 합니다."""
    import math

    for 초, 몫 in ((10, 0.0), (30, 0.5), (50, 1.0)):
        값 = 100.0 + 0.6 * math.sin((분 + 몫) / 2.0)
        _체결(펌프, _시각(0) + 분 * 60_000 + 초 * 1_000, round(값, 2))


def test_이어_굴린_규칙_상태는_처음부터_굴린_상태와_같다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    엔진.rules["buyEntry"] = _다단계()
    엔진.run.margin = None  # 주문은 막고 판정만 봅니다.
    _준비(펌프)

    견줌 = 0
    나아감 = 0
    for 분 in range(2, 90):
        _물결_체결(펌프, 분)
        닫힌 = len(엔진.bars.bars)
        if 엔진._tick_base is None or 엔진._tick_base[0] != 닫힌:
            continue
        series = 엔진._series()
        처음부터 = 엔진._rolled("buyEntry", 엔진.rules["buyEntry"], series, 닫힌 - 1)[0]
        assert 엔진._tick_base[2]["buyEntry"] == 처음부터, 분
        견줌 += 1
        나아감 += 처음부터.step > 0

    assert 견줌 >= 80
    assert 나아감 >= 5, "단계가 나아간 상태를 여러 번 견줍니다."
    assert _신호(엔진), "규칙이 걸린 봉(틱에서 걸림 확정)을 지난 길입니다."


def test_앞이_잘려도_규칙_상태의_자리가_같은_봉을_가리킨다(실행목록):
    """봉 수 상한이 작은 실행과 넉넉한 실행에 같은 체결을 넣어, 상태가 가리키는 봉 시각을 견줍니다."""
    넉넉 = _세우기(실행목록)
    작은 = _세우기(실행목록, run_id="run2")
    for 엔진 in (넉넉, 작은):
        엔진.rules["buyEntry"] = _다단계()
        엔진.run.margin = None
    작은.bars.limit = 8
    펌프 = pump_lib.RunPump(실행목록, hub=_허브(), auction=lambda *_, **__: None)
    _준비(펌프)

    def 가리킴(엔진, stage):
        봉 = 엔진.bars.bars
        시각 = 봉[stage.deadline].timestamp if 0 <= stage.deadline < len(봉) else None
        return stage.step, 시각

    본것 = 0
    for 분 in range(2, 30):
        _물결_체결(펌프, 분)
        if 작은._tick_base is None or 넉넉._tick_base is None:
            continue
        a = 넉넉._tick_base[2]["buyEntry"]
        b = 작은._tick_base[2]["buyEntry"]
        if a.step and a.deadline < len(넉넉.bars.bars):
            assert 가리킴(넉넉, a) == 가리킴(작은, b), 분
            본것 += 1

    assert len(작은.bars.bars) == 8
    assert 본것 >= 1, "단계가 나아간 상태를 견준 적이 있습니다."
    assert [one["time"] for one in _신호(작은)] == [one["time"] for one in _신호(넉넉)]


def test_진행_중인_봉의_판정_값은_처음부터_센_값과_같다(펌프, 실행목록):
    """엔진이 체결마다 쓰는 값(이어 세기) == 닫힌 봉 + 진행 중인 봉을 처음부터 센 값."""
    엔진 = _세우기(실행목록)
    엔진.rules["buyEntry"] = _다단계()
    엔진.run.margin = None
    _준비(펌프)
    for 분 in range(2, 12):
        _물결_체결(펌프, 분)
    _체결(펌프, _시각(12, 10), 100.3)
    봉 = 엔진.bars.open_bar
    맥락 = 엔진.bars.open_session

    이어 = 엔진._live_series(봉, 맥락)
    보유 = 엔진.ledger.position
    전체 = 엔진._series_of(
        [*엔진.bars.bars, 봉],
        [*엔진.bars.sessions, 맥락],
        live=엔진._mark_values(봉.close, 보유.quantity, 보유.avg_price),
    )

    assert 이어.values == 전체.values


def test_기억한_봉이_어긋나면_처음부터_센다(펌프, 실행목록):
    """봉 시각이 기억과 맞지 않으면(가운데 끼우기 등) 이어 붙이지 않고 처음부터 셉니다."""
    엔진 = _세우기(실행목록)
    _준비(펌프)
    for 분 in range(2, 6):
        _물결_체결(펌프, 분)
    from backend.strategy import rules

    값, 시각들 = 엔진._tick_closed
    # 다른 봉들로 센 기억입니다 — 시각도 값도 지금 봉과 다릅니다. 이어 붙이면 틀린 값이 남습니다.
    틀린값 = rules.Series(
        values={이름: [v + 1 if isinstance(v, float) else v for v in 열] for 이름, 열 in 값.values.items()},
        length=값.length,
        session=값.session,
    )
    엔진._tick_closed = (틀린값, [one + 1 for one in 시각들])

    _체결(펌프, _시각(6), 100.0)  # 10:05 봉이 닫힙니다.

    값, 시각들 = 엔진._tick_closed
    assert 시각들 == [one.timestamp for one in 엔진.bars.bars]
    assert 값.values == 엔진._series().values


# ── 일봉 ─────────────────────────────────────────────────


def test_일봉_틱은_장중에_바로_내고_같은_날은_다시_안_내며_날이_바뀌면_새로_센다(펌프, 실행목록):
    from datetime import date

    from backend.strategy import bars as bar_lib

    엔진 = _세우기(실행목록, addWhileOpen=True, maxEntriesPerDay="1")
    엔진.bars = bar_lib.BarBuilder("일봉")

    def 날(d: int, h: int = 0, m: int = 0) -> int:
        return int(datetime(2026, 9, d, h, m, tzinfo=KST).timestamp() * 1000)

    엔진.seed([{"timestamp": 날(15), "close": 99.0}, {"timestamp": 날(16), "close": 99.0}], 주간)
    엔진.note_open(주간, 날(17, 8, 45))
    _체결(펌프, 날(17, 9), 99.0)

    _체결(펌프, 날(17, 10), 100.5)  # 장중 — 바로 냅니다
    _호가(펌프, 날(17, 10) + 1_000, 100.5, 100.0)
    _체결(펌프, 날(17, 11), 99.5)
    _체결(펌프, 날(17, 12), 100.6)  # 같은 날(같은 봉) — 다시 안 냅니다
    _체결(펌프, 날(17, 15), 99.5)
    assert len(_신호(엔진)) == 1 and 엔진.run.intents_today == 1
    assert len(엔진.book.orders) == 1
    assert date.fromtimestamp(엔진.run.day_key / 1000) == date(2026, 9, 17)

    엔진.note_open(주간, 날(18, 8, 45))
    _체결(펌프, 날(18, 9), 99.0)  # 첫 체결에서 날이 넘어갑니다.
    assert 엔진.run.intents_today == 0
    _체결(펌프, 날(18, 10), 100.5)

    assert [one["time"] for one in _신호(엔진)] == [날(17, 10), 날(18, 10)]
    assert 엔진.run.intents_today == 1, "하루 최대 진입은 새 날 몫으로 셉니다."
    assert [one.side for one in 엔진.book.orders] == ["buy", "buy"]


# ── 화면이 읽는 줄에 싣는 틱 표지 ───────────────────────


def test_틱_신호에는_진행_중인_봉의_시각을_싣는다(펌프, 실행목록):
    엔진 = _세우기(실행목록)
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)

    (신호,) = _신호(엔진)
    (주문,) = _진입_주문(엔진)
    assert 신호["barTime"] == _시각(2), "진행 중인 봉의 시작 시각입니다."
    assert 신호["barTime"] == 엔진._snap[주문.id]["barTime"] == 엔진._conditions["barTime"]
    (줄,) = [one for one in 엔진.open_orders if one["orderId"] == 주문.id]
    assert 줄["barTime"] == 엔진._conditions["barTime"], "조건 표와 같은 봉입니다."


#: 열린 주문 줄의 칸들. 틱 표지가 없는 주문은 이 모양 그대로입니다.
_주문_줄_칸 = {
    "orderId", "runId", "time", "side", "intent", "reason", "quantity", "remaining",
    "price", "stopPrice", "orderType", "status", "virtual", "orderNo",
}


def test_열린_주문_줄에는_틱_표지를_싣고_마감_주문_줄은_모양이_그대로다(펌프, 실행목록):
    틱 = _세우기(실행목록)
    마감 = _세우기(실행목록, "마감", run_id="run2")
    _준비(펌프)

    _체결(펌프, _시각(2, 10), 100.5)
    _체결(펌프, _시각(3), 100.7)  # 마감 실행은 10:02 봉이 닫히며 냅니다.

    (틱줄,) = [one for one in 틱.open_orders if one["intent"] == "entry"]
    assert {name: 틱줄[name] for name in engine_lib.TICK_MARK_FIELDS} == {
        "evalMode": "틱",
        "partialBar": True,
        "judgedAt": _시각(2, 10),
        "barTime": _시각(2),
    }
    (마감줄,) = [one for one in 마감.open_orders if one["intent"] == "entry"]
    assert set(마감줄) == _주문_줄_칸, "봉 마감 주문은 줄 모양이 그대로입니다."

    틱._snap.pop(틱줄["orderId"])  # 묶음이 없는 주문(우리가 묶지 않은 주문)
    (묶음없는줄,) = [one for one in 틱.open_orders if one["orderId"] == 틱줄["orderId"]]
    assert set(묶음없는줄) == _주문_줄_칸


def test_실행_줄에_평가_방식을_싣고_없으면_마감이다(실행목록):
    _세우기(실행목록)
    _세우기(실행목록, "마감", run_id="run2")
    없음 = _세우기(실행목록, run_id="run3")
    없음.run.draft.pop("evalMode")
    _세우기(실행목록, run_id="run4").run.draft["evalMode"] = ""
    _세우기(실행목록, run_id="run5").run.draft["evalMode"] = "모르는 값"

    줄들 = {one["id"]: one["evalMode"] for one in 실행목록.rows()}

    assert 줄들 == {"run1": "틱", "run2": "마감", "run3": "마감", "run4": "마감", "run5": "마감"}
