"""실행의 거래일 — 해외는 시간표의 거래 창으로 셉니다.

**서버에 닿지 않습니다.** 시간표는 손으로 지은 품목 줄(`test_strategy_vwap_day`)이고,
체결은 손으로 넣습니다.
"""
from __future__ import annotations

from datetime import date, datetime

from backend.sessions.hours import KST
from backend.strategy import backtest, bars as bar_lib, engine, paper, records, runs
from tests.test_strategy_engine import _설정
from tests.test_strategy_records import _거래, _조건
from tests.test_strategy_vwap_day import _CME, _HKEX, _거래일, _ms, _봉, _vwap_규칙

해외 = "overseas"


def _자정(day: int) -> int:
    return int(datetime(2026, 9, day, tzinfo=KST).timestamp() * 1000)


def _해외엔진(contract=_CME, draft=None, record=None) -> engine.RunEngine:
    엔진 = engine.RunEngine(
        runs.Run(id="r1", version_id="v1", code="6A", session=해외, market="overseas",
                 state=runs.ARMED, draft=draft or _설정()),
        tick=0.01,
        record=record,
    )
    엔진.trading_day = _거래일(contract)
    return 엔진


def _틱(엔진: engine.RunEngine, 때: int, price: float = 100.0) -> None:
    엔진.on_trade({"timestamp": 때, "price": price, "quantity": 1}, 해외, at=때)


# ── 열쇠 ─────────────────────────────────────────────────


def test_자정을_넘어도_같은_거래일이고_세션_시작에서_넘어간다():
    엔진 = _해외엔진()
    for 때 in (_ms(16, 23, 58), _ms(16, 23, 59), _ms(17, 0, 0)):
        _틱(엔진, 때)
    assert 엔진.run.day_key == _자정(16)
    엔진.run.intents_today = 1

    _틱(엔진, _ms(17, 0, 1))  # 00:00 봉이 닫힘
    _틱(엔진, _ms(17, 0, 2))
    assert 엔진.run.day_key == _자정(16), "KST 자정을 넘겨도 16일 거래일입니다."
    assert 엔진.run.intents_today == 1, "하루 최대 진입 수가 풀리지 않습니다."

    _틱(엔진, _ms(17, 7, 0))
    _틱(엔진, _ms(17, 7, 1))  # 07:00 봉이 닫힘
    assert 엔진.run.day_key == _자정(17)
    assert 엔진.run.intents_today == 0


def test_창_밖의_봉은_앞_봉의_거래일을_잇는다():
    엔진 = _해외엔진(_HKEX)
    for 때 in (_ms(16, 12, 59), _ms(16, 13, 30), _ms(16, 14, 0)):
        _틱(엔진, 때)

    assert 엔진._trading_slot(_ms(16, 13, 30), 해외) == _자정(16)
    assert 엔진.run.day_key == _자정(16)


def test_거래일_값은_달력_열쇠와_같은_단위다():
    엔진 = _해외엔진()
    값 = 엔진._trading_slot(_ms(17, 0, 30), 해외)

    assert 값 == bar_lib.day_slot_of(_ms(16, 12, 0), 해외), "16일 0시(KST) 밀리초입니다."
    assert datetime.fromtimestamp(값 / 1000, tz=KST).date() == date(2026, 9, 16)


def test_국내는_달력_열쇠_그대로다():
    엔진 = engine.RunEngine(
        runs.Run(id="r", version_id="", code="A", session="domestic-night", market="domestic", draft=_설정()),
        tick=0.05,
    )
    때 = _ms(16, 23, 0)
    assert 엔진._trading_slot(때, "domestic-night") == bar_lib.day_slot_of(때, "domestic-night")
    assert 엔진._day_text(때) is None


# ── 기록 ─────────────────────────────────────────────────


def test_잔고_줄은_거래일을_적고_기록은_그_날로_묶는다():
    기록: list = []
    엔진 = _해외엔진(record=lambda kind, row: 기록.append((kind, dict(row))))
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": _ms(16, 23, 0)})
    엔진.run.state = runs.HOLDING
    for 때 in (_ms(16, 23, 58), _ms(17, 0, 10)):
        _틱(엔진, 때)
    엔진.close_session(_ms(17, 6, 0))

    (잔고,) = [row for kind, row in 기록 if kind == engine.DAY_ROW]
    assert 잔고["day"] == "2026-09-16", "자정 뒤 봉까지 16일 거래일의 잔고 줄 하나입니다."
    줄 = {**_거래(_ms(17, 0, 30), market="overseas", session=해외), "tradingDay": "2026-09-16"}
    assert records.day_of_row(줄) == date(2026, 9, 16)
    묶음 = records.dataset([줄], _조건(market="overseas"))
    assert 묶음["dates"] == ["2026-09-16"]


def test_체결로_닫힌_거래_줄에_거래일이_실린다():
    기록: list = []
    엔진 = _해외엔진(record=lambda kind, row: 기록.append((kind, dict(row))))
    _틱(엔진, _ms(16, 23, 58))
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": _ms(16, 23, 0)})
    엔진.run.state = runs.HOLDING
    엔진.book.last_price = 100.0
    엔진._close(1, 100.0, engine.STOP_LOSS, _ms(17, 0, 30))
    엔진.on_book({"asks": [{"price": 100.05, "quantity": 9}], "bids": [{"price": 100.0, "quantity": 9}]},
                 at=_ms(17, 0, 31))

    (거래,) = [row for kind, row in 기록 if kind == "trade"]
    assert 거래["tradingDay"] == "2026-09-16"
    (주문,) = [row for kind, row in 기록 if kind == engine.ORDER_ROW]
    assert 주문["tradingDay"] == "2026-09-16"


def test_칸_없는_옛_줄과_국내_줄은_지금_셈_그대로다():
    옛 = _거래(_ms(17, 0, 30), market="overseas", session=해외)
    국내 = _거래(_ms(16, 23, 0), session="domestic-night")

    assert records.day_of_row(옛) == records.trading_day(_ms(17, 0, 30), 해외) == date(2026, 9, 17)
    assert records.day_of_row(국내) == records.trading_day(_ms(16, 23, 0), "domestic-night")


# ── 개장 열쇠·미룬 일봉 주문 ─────────────────────────────────


def test_해외_일봉_미룬_주문은_자정_뒤_체결에서도_나간다():
    엔진 = _해외엔진(draft={**_설정(), "baseBar": "일봉"})
    엔진.note_open(해외, _ms(16, 7, 0))
    엔진._defer("entry", paper.BUY, 100.0, _ms(16, 6, 0))

    _틱(엔진, _ms(17, 0, 30))

    assert len(엔진.book.orders) == 1, "개장 열쇠가 거래일이라 자정 뒤에도 찾습니다."


# ── 바뀌는 순간 ───────────────────────────────────────────


def test_옛_셈으로_담긴_열쇠는_넘어가지_않고_고쳐_쓴다():
    엔진 = _해외엔진()
    엔진.run.day_key = _자정(17)  # 옛 셈: 자정에 이미 17일로 넘어가 있음
    엔진.run.intents_today = 2
    엔진.run.day_base = -50.0

    _틱(엔진, _ms(17, 0, 30))
    _틱(엔진, _ms(17, 0, 31))

    assert 엔진.run.day_key == _자정(16)
    assert 엔진.run.intents_today == 2 and 엔진.run.day_base == -50.0, "다시 켠 것만으로 풀리지 않습니다."


# ── 지난 봉 셈 ────────────────────────────────────────────


def test_지난_봉_셈의_해외_거래일도_실행_엔진과_같은_답이다(monkeypatch):
    봉들 = [_봉(16, 23, minute, 100.0 + (minute % 7) * 0.05) for minute in range(30, 60)]
    봉들 += [_봉(17, 0, minute, 100.0 + (minute % 5) * 0.05) for minute in range(0, 30)]

    def 셈():
        return backtest.compute(
            draft=_vwap_규칙(), market="overseas", code="6A", session=해외, bars=봉들, tick=0.01,
            margin=1_000.0, trading_day=_거래일(_CME),
        )

    빠른 = 셈()

    class 그냥(engine.RunEngine):
        def __init__(self, run, *, every, trading_day=None, **kwargs):
            super().__init__(run, **kwargs)
            self.trading_day = trading_day

    monkeypatch.setattr(backtest, "BacktestEngine", 그냥)
    assert 셈() == 빠른
