"""끝난 실행은 시세를 받지 않고 판정하지 않습니다.

끝난 실행은 자기 구독이 없지만, 같은 종목을 다른 실행이 보고 있으면 펌프로 그
시세가 옵니다. 그것을 넘기면 끝난 실행의 봉·조건 표·곡선이 움직이고 안 낸 신호가
기록에 쌓여, 살아 있는 실행처럼 보입니다. 같은 종목의 살아 있는 실행은 그대로
판정합니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 시세는 가짜이고 펌프를 거칩니다.
"""
from __future__ import annotations

from backend.strategy import engine as engine_lib, pump as pump_lib, runs
from tests.test_strategy_tick_eval import _세우기, _시각, _신호, _준비, _체결, _허브
from tests.test_strategy_tick_eval import 실행목록, 펌프  # noqa: F401 — 시험 고정값


def _모습(엔진) -> tuple:
    """끝난 뒤 움직이면 안 되는 것들."""
    return (
        len(엔진.bars.bars),
        엔진.bars.open_bar,
        len(엔진.curve),
        엔진._conditions,
        len(엔진.events),
        엔진.last_trade_at,
        엔진.feed,
        엔진.last_volume,
        엔진.book.last_price,
        엔진._quote,
    )


def _기록줄(tmp_path, run_id: str) -> list[str]:
    path = tmp_path / "trades.jsonl"
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if f'"{run_id}"' in line]


def _끝낸(실행목록, run_id: str, at: int):
    실행목록.end(run_id, at)
    엔진 = 실행목록._engine(run_id)
    assert 엔진.run.state == runs.ENDED
    return 엔진


def test_끝난_실행은_같은_종목_시세가_와도_움직이지_않고_산_실행은_판정한다(펌프, 실행목록, tmp_path):
    산 = _세우기(실행목록)
    끝 = _세우기(실행목록, run_id="run2")
    _준비(펌프)
    _끝낸(실행목록, "run2", _시각(2, 5))
    앞모습, 앞기록 = _모습(끝), _기록줄(tmp_path, "run2")

    _체결(펌프, _시각(2, 10), 100.5)  # 산 실행은 진행 중인 봉에서 겁니다.
    _체결(펌프, _시각(3), 100.7)  # 봉이 닫힙니다.
    _체결(펌프, _시각(4), 100.9)
    펌프.take(  # 체결 없이 누적 거래량·호가만 바뀐 시세도 넘기지 않습니다.
        {"type": "quote", "context": "domestic-day", "sym": 산.run.code, "patch": {"volume": 999}},
        at=_시각(4, 5),
    )
    펌프.take(
        {
            "type": "book",
            "context": "domestic-day",
            "sym": 산.run.code,
            "asks": [{"price": 101.0, "quantity": 9}],
            "bids": [{"price": 100.0, "quantity": 9}],
        },
        at=_시각(4, 6),
    )

    assert _모습(끝) == 앞모습, "끝난 실행의 봉·곡선·조건 표·사건이 그대로입니다."
    assert _기록줄(tmp_path, "run2") == 앞기록, "기록 파일에 끝난 실행 줄이 늘지 않습니다."
    assert [one["time"] for one in _신호(산)] == [_시각(2, 10)], "산 실행은 그대로 판정합니다."
    assert len(산.bars.bars) > 앞모습[0]


def test_끝난_실행에는_시계가_돌아도_공백_줄이_없다(펌프, 실행목록):
    산 = _세우기(실행목록)
    끝 = _세우기(실행목록, run_id="run2")
    _준비(펌프)
    _끝낸(실행목록, "run2", _시각(2, 5))
    끝앞, 산앞 = len(끝.events), len(산.events)

    펌프.beat(at=_시각(9))  # 마지막 체결 뒤 한참 지났습니다.

    assert 끝.events[끝앞:] == [] and 끝.feed != engine_lib.GAP
    assert 산.feed == engine_lib.GAP, "산 실행은 지금처럼 공백입니다."
    assert [one["kind"] for one in 산.events[산앞:]] == [engine_lib.GAP], "공백 줄 하나입니다."
    줄 = [one for one in 펌프.beat(at=_시각(9, 1))["runs"] if one["id"] == "run2"]
    assert len(줄) == 1, "목록 방송에는 끝난 실행 줄이 그대로 섭니다."


def test_끝난_실행_때문에_시장이_흘렀는지_묻지_않는다(펌프, 실행목록):
    산 = _세우기(실행목록)
    끝 = _세우기(실행목록, run_id="run2")
    _준비(펌프)
    _끝낸(실행목록, "run2", _시각(2, 5))
    for 엔진 in (산, 끝):
        엔진.feed = engine_lib.GAP
        엔진.quiet_since = _시각(2)
        엔진.probe_asked = False

    묻는것 = 펌프.probes_wanted(_시각(9))

    assert [[one.run.id for one in group] for _, group in 묻는것] == [["run1"]]


def test_펌프_밖에서_불러도_끝난_실행은_체결을_받지_않는다(펌프, 실행목록):
    엔진 = _세우기(실행목록, run_id="run2")
    _준비(펌프)
    _끝낸(실행목록, "run2", _시각(2, 5))
    앞모습 = _모습(엔진)

    체결 = {"timestamp": _시각(3, 30), "price": 101.0, "quantity": 1}
    엔진.on_trade(체결, "domestic-day", at=_시각(3, 30))
    엔진.judge_tick(_시각(3, 30))

    assert _모습(엔진) == 앞모습


def test_중지한_보유_실행은_같은_시세로_손절을_낸다(펌프, 실행목록):
    """중지(PAUSED)는 끝남이 아닙니다. 들고 있는 것의 손절 감시는 시세를 받아 돕니다."""
    from backend.strategy import paper

    중지 = _세우기(실행목록, stopTicks="2")
    끝 = _세우기(실행목록, run_id="run2")
    _준비(펌프)
    _끝낸(실행목록, "run2", _시각(2, 5))
    중지._take([{"orderId": "in", "side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1}], 1)
    중지.run.state = runs.HOLDING
    중지.run.move(runs.PAUSE)
    assert 중지.run.state == runs.PAUSED and 중지.ledger.position.quantity == 1
    끝앞 = _모습(끝)

    손절선 = 중지._exit_lines(None)[0]
    _체결(펌프, _시각(2, 20), 손절선 - 중지.tick)  # 손절선 아래 체결입니다.

    청산 = [one for one in 중지.book.orders if 중지._purpose.get(one.id) == "exit"]
    assert len(청산) == 1, "손절 청산 주문이 나갑니다."
    assert 중지.run.state == runs.EXITING
    assert _모습(끝) == 끝앞
