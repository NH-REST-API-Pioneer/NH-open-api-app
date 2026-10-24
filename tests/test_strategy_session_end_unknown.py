"""세션 끝 정리를 켰는데 장 시간표를 모를 때.

「지금 거래 창이 아님」과 「시간표를 모름」은 다릅니다. 앞의 것은 창이 열리면 끝
시각을 알지만, 뒤의 것은 정리할 시각이 없습니다. 그래서 시작 때 갈래에 따라 막거나
알리고, 실행 중에는 정리하지 못한다고 거래일마다 한 번 남깁니다.

실행 중 알림은 **펌프 박자를 거칩니다**(`pump.beat`). 시각은 가짜입니다(`at`).
"""
from __future__ import annotations

import pytest

from backend.sessions import judge as judge_lib
from backend.strategy import engine as engine_lib, pump as pump_lib, runs, service as service_lib
from tests.test_strategy_engine import _때, _설정
from tests.test_strategy_service import _모의목록, _모의물음, _물음

주간 = "domestic-day"
종목 = "A7569000"


def _모름(market, code, now):
    return {"source": judge_lib.UNKNOWN}


def _앎(market, code, now):
    return {"source": "api", "state": "day", "session": "day"}


def _켬(**aux) -> dict:
    return _설정(sessionEndFlat=True, sessionEndMinutes="10", **aux)


def _세션_줄(엔진) -> list[str]:
    return [one["text"] for one in 엔진.events if one["kind"] == engine_lib.SESSION]


# ── 시작할 때 ────────────────────────────────────────────


def test_계좌_실행은_시간표를_모르면_시작을_막는다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록._judged = _모름

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_모의물음(draft=_켬()))

    (하나,) = [one for one in 터짐.value.problems if one["field"] == "aux.sessionEndFlat"]
    assert 하나["message"] == service_lib.WHY_SESSION_END_UNKNOWN
    assert "잠시 뒤" in 하나["message"], "까닭과 함께 언제 다시 하면 되는지 말합니다."


def test_계좌_실행도_시간표를_알면_막지_않는다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록._judged = _앎

    problems = 실행목록.start_problems(
        draft=_켬(), market="domestic", code=종목, session=주간, qty=1, cash=1.0,
        fee_per_contract=0.0, mode=runs.SIM, environment="paper",
    )

    assert "aux.sessionEndFlat" not in [one["field"] for one in problems]


def test_종이_실행은_세우되_한_줄_남긴다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록._judged = _모름

    실행목록.add(**_물음(draft=_켬()))

    assert service_lib.WHY_SESSION_END_UNKNOWN in _세션_줄(실행목록._engine("run1"))


@pytest.mark.parametrize("모드", [runs.PAPER, runs.SIM])
def test_세션_끝_정리를_끄면_시간표를_몰라도_아무_일도_없다(tmp_path, 모드):
    실행목록 = _모의목록(tmp_path)
    실행목록._judged = _모름
    물음 = _물음(draft=_설정()) if 모드 == runs.PAPER else _모의물음(draft=_설정(fillCond="FAS"))

    실행목록.add(**물음)

    assert _세션_줄(실행목록._engine("run1")) == []
    펌프 = _펌프(실행목록, 모름=True)
    _체결(펌프, _때(10, 0))
    펌프.beat(at=_때(10, 0, 1))
    assert _세션_줄(실행목록._engine("run1")) == []


# ── 실행 중 ─────────────────────────────────────────────


def _펌프(실행목록, *, 모름: bool, 끝: int | None = None) -> pump_lib.RunPump:
    상태 = {"모름": 모름}
    made = pump_lib.RunPump(
        실행목록,
        hub=None,
        judge=lambda *a: True,
        closing=lambda *a: 끝,
        replaying=lambda: False,
        unknown=lambda market, code: 상태["모름"],
    )
    made.상태 = 상태
    return made


def _체결(펌프, at: int, price: float = 99.0) -> None:
    펌프.take(
        {
            "type": "quote",
            "context": 주간,
            "sym": 종목,
            "trades": [{"timestamp": at, "price": price, "quantity": 1}],
        },
        at=at,
    )


def _세운(tmp_path, **aux):
    실행목록 = _모의목록(tmp_path)
    실행목록._judged = _앎
    실행목록.add(**_물음(draft=_켬(**aux)))
    return 실행목록, 실행목록._engine("run1")


def test_시간표를_모르면_거래일마다_한_번_남긴다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    펌프 = _펌프(실행목록, 모름=True)

    for 분 in range(3):
        _체결(펌프, _때(10, 분))
        펌프.beat(at=_때(10, 분, 1))
        펌프.beat(at=_때(10, 분, 2))
    assert _세션_줄(엔진).count(service_lib.SESSION_END_UNKNOWN_NOTE) == 1, "여러 박자·체결 뒤에도 한 번"

    _체결(펌프, _때(10, 0, day=18))
    펌프.beat(at=_때(10, 0, 1, day=18))

    assert _세션_줄(엔진).count(service_lib.SESSION_END_UNKNOWN_NOTE) == 2, "다음 거래일엔 다시 한 번"


def test_체결이_안_오면_장이_흐르는지_몰라_남기지_않는다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    펌프 = _펌프(실행목록, 모름=True)

    펌프.beat(at=_때(22, 0))

    assert service_lib.SESSION_END_UNKNOWN_NOTE not in _세션_줄(엔진)


def test_시간표를_나중에_받으면_알림이_그치고_정리가_돈다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    끝 = _때(15, 35)
    펌프 = _펌프(실행목록, 모름=True, 끝=끝)
    부름: list[int] = []
    엔진.session_end = lambda at, until: 부름.append(at) or True
    _체결(펌프, _때(15, 0))
    펌프.beat(at=_때(15, 0, 1))
    assert _세션_줄(엔진).count(service_lib.SESSION_END_UNKNOWN_NOTE) == 1

    펌프.상태["모름"] = False
    _체결(펌프, _때(15, 26))
    펌프.beat(at=_때(15, 26, 1))

    assert _세션_줄(엔진).count(service_lib.SESSION_END_UNKNOWN_NOTE) == 1, "알게 된 뒤로는 안 남깁니다."
    assert 부름 == [_때(15, 26, 1)], "끝 10분 전 창에서 정리가 돕니다."


def test_시간표를_알면_정리는_그대로다(tmp_path):
    실행목록, 엔진 = _세운(tmp_path)
    펌프 = _펌프(실행목록, 모름=False, 끝=_때(15, 35))
    부름: list[int] = []
    엔진.session_end = lambda at, until: 부름.append(at) or True

    펌프._session_ends(_때(15, 24))
    펌프._session_ends(_때(15, 25))

    assert 부름 == [_때(15, 25)]
    assert _세션_줄(엔진) == []


def test_시작_검사와_펌프는_같은_판정을_쓴다(monkeypatch):
    """판정 원천이 「모름」이면 참입니다. 「창 밖」(시간표는 앎)은 거짓입니다."""
    from backend.sessions import sessions_routes

    monkeypatch.setattr(sessions_routes, "judged", _모름)
    assert service_lib.timetable_unknown("domestic", 종목) is True
    monkeypatch.setattr(sessions_routes, "judged", lambda m, c, n: {"source": "api", "state": "closed"})
    assert service_lib.timetable_unknown("domestic", 종목) is False
    assert pump_lib.RunPump(None, hub=None).unknown is service_lib.timetable_unknown
