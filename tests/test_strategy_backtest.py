"""지난 봉으로 돌려 보기 — 봉 체결 모형 `bar-v1`.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 봉은 손으로 지은 작은 목록이고, 봉을
받는 자리와 종목 정보는 가짜로 끼웁니다. 값은 손으로 셈한 것과 견줍니다.
"""
from __future__ import annotations

import itertools
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import backtest, engine, journal as journal_lib, paper, runs, sim
from backend.strategy import service as service_lib
from backend.strategy.indicators import Bar
from backend.strategy.strategy_routes import get_master, get_service
from tests.test_strategy_engine import _규칙, _때, _설정, _조건

주간 = "domestic-day"
틱 = 0.05


def _봉(hour: int, minute: int, o: float, h: float, l: float, c: float, *, day: int = 17) -> Bar:
    return Bar(_때(hour, minute, day=day), o, h, l, c, 10)


def _평평(count: int, *, day: int = 17, price: float = 99.0, hour: int = 9) -> list[Bar]:
    """판정 준비용 봉. 값이 99 로 평평해 규칙이 걸리지 않습니다."""
    return [_봉(hour, minute, price, price, price, price, day=day) for minute in range(count)]


def _셈(bars: list[Bar], draft: dict | None = None, **덮어쓰기) -> dict:
    물음 = {
        "draft": draft if draft is not None else _설정(),
        "market": "domestic",
        "code": "A7569000",
        "session": 주간,
        "bars": bars,
        "tick": 틱,
        # 계약당 증거금. 모르면 실행과 같이 예산 검사가 진입을 막습니다.
        "margin": 1_000.0,
    }
    물음.update(덮어쓰기)
    return backtest.compute(**물음)


def _신호_봉(draft: dict, bars: list[Bar]) -> list[int]:
    """실행 엔진(종이 장부)에 같은 봉을 실시간처럼 넣었을 때 규칙이 걸린 봉."""
    엔진 = engine.RunEngine(
        runs.Run(
            id="r1", version_id="v1", code="A7569000", session=주간, market="domestic",
            state=runs.ARMED, qty=1, cash=10_000_000.0, draft=draft,
        ),
        tick=틱,
        history=10_000,
    )
    for one in bars:
        for step, price in enumerate((one.open, one.high, one.low, one.close)):
            때 = one.timestamp + step * 1_000
            엔진.on_trade({"timestamp": 때, "price": price, "quantity": 1}, 주간, at=때)
    엔진.close_session(bars[-1].timestamp + 60_000)
    return _닫힌_봉(bars, [one["time"] for one in 엔진.events if one["kind"] == engine.SIGNAL])


def _닫힌_봉(bars: list[Bar], times: list[int]) -> list[int]:
    """신호 시각마다 그때 막 닫힌 봉의 시각."""
    return [max(one.timestamp for one in bars if one.timestamp + 60_000 <= when) for when in times]


# ── 판정은 실행과 같다 ─────────────────────────────────────


def test_규칙이_걸리는_봉은_실행_엔진과_같다():
    설정 = _설정(stopTicks="", takeTicks="", maxHold="9")
    값들 = [99.0, 101.0, 100.5, 99.0, 102.0, 98.0, 101.0, 101.5, 99.5, 100.2]
    봉들 = _평평(2) + [_봉(9, 2 + i, v, v + 0.2, v - 0.2, v) for i, v in enumerate(값들)]
    잡은: list[int] = []
    원래 = backtest._answer

    def 엿보기(answer, made, fed, minutes):
        잡은.extend(one["time"] for one in made.events if one["kind"] == engine.SIGNAL)
        return 원래(answer, made, fed, minutes)

    backtest._answer = 엿보기
    try:
        답 = _셈(봉들, 설정)
    finally:
        backtest._answer = 원래

    엔진_봉 = _신호_봉(설정, 봉들)
    assert 엔진_봉, "시험 봉에서 규칙이 걸려야 비교가 됩니다."
    assert _닫힌_봉(봉들, 잡은) == 엔진_봉
    assert 답["signals"] == len(엔진_봉)
    assert 답["model"] == backtest.MODEL == "bar-v1"
    assert 답["assumptions"]["slippageTicks"] == 1 and 답["assumptions"]["sameBarStopFirst"] is True


# ── 시장가·손절·익절 ──────────────────────────────────────


def _진입봉(*more: Bar) -> list[Bar]:
    """09:02 봉이 101 로 닫혀 매수 진입이 걸립니다. 주문은 09:03 봉의 시가에 나갑니다."""
    return _평평(2) + [_봉(9, 2, 99.0, 101.0, 99.0, 101.0), *more]


def test_시장가_진입은_다음_봉_시가에_슬리피지를_더한다_같은_봉_손절이_익절보다_먼저다():
    # 진입 101 + 1틱 = 101.05. 손절 2틱 = 100.95, 익절 3틱 = 101.20.
    # 09:03 봉은 저가 100.8·고가 101.5 로 둘 다 닿습니다 — 매수 보유라 저가가 먼저입니다.
    답 = _셈(_진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2)))

    (거래,) = 답["trades"]
    assert 거래["entryPrice"] == pytest.approx(101.05)
    assert 거래["exitPrice"] == pytest.approx(100.90), "손절 100.95 에서 발동, 1틱 불리하게."
    assert 거래["reason"] == engine.STOP_LOSS
    assert 거래["pl"] == pytest.approx(-0.15)
    assert 답["pl"] == pytest.approx(-0.15) and 답["losses"] == 1 and 답["winRate"] == 0.0
    assert 답["fills"] == 2 and 답["signals"] == 1


def test_슬리피지_0_이면_시가_그대로다():
    답 = _셈(_진입봉(_봉(9, 3, 101.0, 101.25, 101.0, 101.25)), slippage_ticks=0)

    (거래,) = 답["trades"]
    assert 거래["entryPrice"] == pytest.approx(101.0)
    assert 거래["exitPrice"] == pytest.approx(101.15), "익절 101.15 (진입 101 + 3틱)."
    assert 거래["reason"] == engine.TAKE_PROFIT
    assert 답["assumptions"]["slippageTicks"] == 0


def test_갭으로_손절을_넘어_열리면_시가에서_닫는다():
    답 = _셈(
        _진입봉(
            _봉(9, 3, 101.0, 101.1, 101.0, 101.05),  # 손절 100.95·익절 101.20 어느 쪽도 안 닿음
            _봉(9, 4, 100.5, 100.6, 100.4, 100.5),  # 시가가 이미 손절 아래
        )
    )

    (거래,) = 답["trades"]
    assert 거래["exitPrice"] == pytest.approx(100.45), "시가 100.5 에서 1틱 불리하게."
    assert 거래["closedAt"] == _때(9, 4)


def test_매도_보유는_고가가_먼저라_손절이다():
    설정 = _설정()
    설정["rules"]["buyEntry"] = {"on": False, "steps": []}
    설정["rules"]["sellEntry"] = _규칙(_조건(op="lt", right="99"))
    봉들 = _평평(2) + [
        _봉(9, 2, 99.0, 99.0, 98.0, 98.0),  # 98 로 닫혀 매도 진입
        _봉(9, 3, 98.0, 98.5, 97.5, 98.0),  # 진입 97.95. 손절 98.05·익절 97.80 둘 다 닿음
    ]

    (거래,) = _셈(봉들, 설정)["trades"]
    assert 거래["side"] == paper.SELL
    assert 거래["entryPrice"] == pytest.approx(97.95)
    assert 거래["exitPrice"] == pytest.approx(98.10), "손절 98.05 에서 1틱 불리하게."
    assert 거래["reason"] == engine.STOP_LOSS


def test_보유가_없으면_양봉은_저가_먼저_음봉은_고가_먼저다(monkeypatch):
    길: list[float] = []
    엔진 = engine.RunEngine(
        runs.Run(id="r", version_id="", code="A", session=주간, market="domestic", state=runs.ARMED, draft=_설정()),
        tick=틱,
        book=backtest.BarBook(tick=틱, slippage_ticks=1),
    )
    monkeypatch.setattr(엔진, "on_trade", lambda trade, context, at: 길.append(trade["price"]))
    monkeypatch.setattr(엔진, "on_book", lambda book, at: None)

    backtest._walk(엔진, 엔진.book, _봉(9, 0, 100.0, 102.0, 99.0, 101.0), 주간, None, 0)
    assert 길 == [100.0, 99.0, 102.0, 101.0]
    길.clear()
    backtest._walk(엔진, 엔진.book, _봉(9, 1, 101.0, 102.0, 99.0, 100.0), 주간, None, 0)
    assert 길 == [101.0, 102.0, 99.0, 100.0]


# ── 지정가 ───────────────────────────────────────────────


def _지정가(**aux) -> dict:
    return _설정(orderType="지정가", priceBasis="신호가", stopTicks="", takeTicks="", **aux)


def test_지정가는_닿기만_하면_안_채우고_넘어가면_지정가에_채운다():
    봉들 = _진입봉(
        _봉(9, 3, 101.2, 101.3, 101.0, 101.1),  # 저가가 지정가 101 에 닿기만 함
        _봉(9, 4, 101.1, 101.2, 100.95, 101.0),  # 100.95 로 넘어감
    )

    답 = _셈(봉들, _지정가())
    assert 답["fills"] == 1
    assert 답["openPosition"]["avgPrice"] == pytest.approx(101.0), "지정가 그대로, 슬리피지 없음."
    assert 답["openPosition"]["quantity"] == 1


def test_낸_순간_이미_유리한_지정가는_그_값에_채운다():
    봉들 = _진입봉(_봉(9, 3, 100.5, 100.6, 100.4, 100.5))  # 시가 100.5 + 1틱 < 지정가 101

    답 = _셈(봉들, _지정가())
    assert 답["openPosition"]["avgPrice"] == pytest.approx(100.55)


@pytest.mark.parametrize("fill", ["FOK", "FAK"])
def test_FOK_FAK_는_낸_순간_안_채워지면_취소한다(fill):
    봉들 = _진입봉(
        _봉(9, 3, 101.2, 101.3, 101.2, 101.3),
        _봉(9, 4, 101.1, 101.2, 100.5, 100.6),  # 지정가 아래로 넘어가도 이미 취소됨
    )

    답 = _셈(봉들, _지정가(fillCond=fill))
    assert 답["fills"] == 0 and 답["openPosition"] is None


# ── 세션 ─────────────────────────────────────────────────


def test_세션이_바뀌면_기다리던_지정가를_거둔다():
    봉들 = _진입봉(_봉(9, 3, 101.2, 101.3, 101.2, 101.3)) + [
        _봉(9, 0, 100.0, 100.1, 99.0, 99.5, day=18),  # 다음 거래일 — 지정가 101 아래지만 이미 거둠
    ]

    답 = _셈(봉들, _지정가())
    assert 답["fills"] == 0
    assert 답["bars"]["sessions"] == 2


def test_세션_끝_정리는_뒤에_세션이_이어질_때만_한다():
    설정 = _설정(stopTicks="", takeTicks="", sessionEndFlat=True, sessionEndMinutes="2")
    첫날 = _진입봉(*[_봉(9, minute, 101.0, 101.1, 101.0, 101.0) for minute in range(3, 7)])
    # 진입은 09:03 봉 시가. 첫날 끝은 09:07(09:06 봉 마감)이고 끝 2분 전(09:05~)부터 정리합니다.
    둘째날 = [_봉(9, 0, 99.0, 99.0, 99.0, 99.0, day=18), _봉(9, 1, 99.0, 101.0, 99.0, 101.0, day=18)]
    셋째 = [_봉(9, 2, 101.0, 101.0, 101.0, 101.0, day=18), _봉(9, 3, 101.0, 101.1, 101.0, 101.05, day=18)]

    답 = _셈(첫날 + 둘째날 + 셋째, 설정)

    (거래,) = 답["trades"]
    assert 거래["reason"] == engine.SESSION_END
    assert 거래["closedAt"] == _때(9, 5), "정리 창에 든 첫 점(09:05 봉 시가)에서 닫습니다."
    assert 거래["exitPrice"] == pytest.approx(100.95), "시장가라 1틱 불리하게."
    assert 답["openPosition"] is not None, "마지막 세션은 정리하지 않습니다."
    assert 답["openPosition"]["lastPrice"] == 101.05


def test_범위는_마지막_세션만_거래로_본다():
    첫날 = _진입봉(_봉(9, 3, 101.0, 101.25, 101.0, 101.25))
    둘째날 = _평평(3, day=18)

    답 = _셈(첫날 + 둘째날, sessions=1)
    assert 답["trades"] == [] and 답["signals"] == 0
    assert 답["bars"]["from"] == _때(9, 0, day=18) and 답["bars"]["count"] == 3
    assert 답["bars"]["have"] == len(첫날) + 3


def test_봉이_모자라면_필요한_수와_받은_수로_답한다():
    답 = _셈(_평평(1))

    assert 답["enough"] is False
    assert (답["bars"]["have"], 답["bars"]["need"]) == (1, 2)
    assert 답["trades"] == [] and 답["bars"]["count"] == 0


# ── 같은 답·시간 상한 ─────────────────────────────────────


def test_시계와_상관없이_같은_답이다():
    봉들 = _진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2), _봉(9, 4, 101.2, 101.3, 101.1, 101.2))
    이른 = itertools.count(0.0, 0.001)
    늦은 = itertools.count(1e9, 0.001)

    assert _셈(봉들, clock=lambda: next(이른)) == _셈(봉들, clock=lambda: next(늦은))


def test_시간_상한을_넘으면_504_로_멈춘다():
    흐름 = itertools.count(0.0, 100.0)

    with pytest.raises(backtest.BacktestError) as 막힘:
        _셈(_진입봉(_봉(9, 3, 101.0, 101.1, 101.0, 101.0)), clock=lambda: next(흐름), time_limit=1.0)
    assert 막힘.value.status == 504


def _네_규칙() -> dict:
    설정 = _설정(maxHold="1")
    def 교차(op: str) -> dict:
        return {
            "id": "c1", "left": "ema", "leftParams": {"period": 5}, "op": op,
            "rightKind": "operand", "right": "ema", "rightParams": {"period": 20},
        }

    def 강도(op: str, value: str) -> dict:
        return {"id": "c1", "left": "rsi", "leftParams": {"period": 14}, "op": op, "rightKind": "number", "right": value}

    설정["rules"] = {
        "buyEntry": _규칙(교차("crossUp")),
        "sellEntry": _규칙(교차("crossDown")),
        "buyExit": _규칙(강도("gt", "70")),
        "sellExit": _규칙(강도("lt", "30")),
    }
    return 설정


def _물결(count: int) -> list[Bar]:
    import math

    made = []
    for i in range(count):
        mid = 100.0 + 3.0 * math.sin(i / 15.0) + 0.5 * math.sin(i / 3.0)
        mid = round(mid / 틱) * 틱
        made.append(Bar(_때(9, 0) + i * 60_000, mid, mid + 0.2, mid - 0.2, mid + 0.05, 10))
    return made


def test_다시_세지_않는_엔진도_실행_엔진과_같은_답이다(monkeypatch):
    """지표를 한 번 세고 규칙을 한 봉씩 굴리는 자리가 답을 바꾸지 않습니다."""
    설정 = _네_규칙()
    설정["rules"]["buyEntry"]["steps"].append(
        {"id": "s2", "join": "all", "withinBars": 3, "conds": [_조건(op="gt", right="101")]}
    )
    봉들 = _물결(300)
    빠른 = _셈(봉들, 설정)

    class 그냥(engine.RunEngine):
        def __init__(self, run, *, every, trading_day=None, **kwargs):
            super().__init__(run, **kwargs)
            self.trading_day = trading_day

    monkeypatch.setattr(backtest, "BacktestEngine", 그냥)
    # 비교용 느린 엔진은 상한을 보는 자리가 아니라 넉넉히 둡니다(상한은 실제 엔진에만).
    assert _셈(봉들, 설정, time_limit=60.0) == 빠른
    assert 빠른["signals"] > 0 and 빠른["trades"]


def test_천칠백봉_규칙_넷이_시간_상한_안에_끝난다():
    봉들 = _물결(1_701)

    처음 = time.perf_counter()
    답 = _셈(봉들, _네_규칙())
    걸림 = time.perf_counter() - 처음

    assert 답["bars"]["count"] > 1_600 and 답["signals"] > 0
    assert 걸림 < backtest.TIME_LIMIT_SECONDS


# ── 봉 받기 ──────────────────────────────────────────────


class _가짜목록:
    """실행 목록 자리. 봉 조회와 종목 정보만 답합니다."""

    def __init__(self, rows=None, engines=()):
        self.rows = rows or []
        self._engines = list(engines)
        self.asked: list[tuple] = []

    def engines(self):
        return self._engines

    def _fetch(self, run, minutes, count):
        self.asked.append((run.code, run.session, minutes, count))
        return self.rows

    def instrument(self, market, code, session=""):
        return {"tick": 틱, "multiplier": 1.0, "margin": 1_000.0, "exchange": "", "kind": ""}


def _줄(bar: Bar) -> dict:
    return backtest._row_of(bar)


def test_돌고_있는_실행이_없으면_한_번_받고_열린_봉은_뺀다():
    봉들 = _평평(4)
    목록 = _가짜목록(rows=[_줄(one) for one in reversed(봉들)])

    받은 = backtest.gather(
        목록, market="domestic", code="A7569000", session=주간, base_bar="1분봉", exchange="",
        now=_때(9, 3, 30),
    )

    assert [one.timestamp for one in 받은] == [one.timestamp for one in 봉들[:3]], "09:03 봉은 아직 열려 있습니다."
    assert 목록.asked == [("A7569000", 주간, 1, backtest.MAX_BARS)]


def test_같은_종목_기준봉으로_도는_실행이_있으면_그_봉을_쓴다():
    엔진 = engine.RunEngine(
        runs.Run(id="r1", version_id="v1", code="A7569000", session=주간, market="domestic", draft=_설정()),
        tick=틱,
    )
    엔진.seed([_줄(one) for one in _평평(3)], 주간)
    목록 = _가짜목록(engines=[엔진])

    받은 = backtest.gather(
        목록, market="domestic", code="A7569000", session=주간, base_bar="1분봉", exchange="",
        now=_때(10, 0),
    )
    assert len(받은) == 3 and 목록.asked == []


# ── 라우트 ───────────────────────────────────────────────


def _버전() -> dict:
    return {
        "id": "v1", "groupId": "g1", "name": "시험", "version": "v1", "market": "domestic",
        "productCode": "USD", "productKind": "futures", "role": "usdFutures",
    }


class _마스터:
    def index(self):
        return {"products": [{"market": "domestic", "product_code": "USD"}]}

    def product_of(self, market, code):
        return {"market": market, "product_code": "USD"} if code == "A7569000" else None


@pytest.fixture
def 손님():
    목록 = _가짜목록(rows=[_줄(one) for one in _진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2))])
    app.dependency_overrides[get_service] = lambda: 목록
    app.dependency_overrides[get_master] = _마스터
    try:
        yield TestClient(app), 목록
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_master, None)


def _몸(**덮어쓰기) -> dict:
    몸 = {"version": _버전(), "draft": _설정(), "code": "A7569000", "session": 주간, "range": "all"}
    몸.update(덮어쓰기)
    return 몸


def test_라우트는_셈한_답을_낸다(손님):
    앱, _ = 손님

    답 = 앱.post("/api/strategy/backtest", json=_몸())

    assert 답.status_code == 200, 답.text
    몸 = 답.json()
    assert 몸["model"] == "bar-v1" and 몸["assumptions"]
    assert 몸["currency"] == "KRW"
    assert len(몸["trades"]) == 1


def test_저장과_같은_검사에서_막히면_400_과_problems_다(손님):
    앱, _ = 손님

    답 = 앱.post("/api/strategy/backtest", json=_몸(draft=_설정(stopTicks="abc")))

    assert 답.status_code == 400
    몸 = 답.json()["detail"]
    assert 몸["message"] and any(one["field"] == "aux.stopTicks" for one in 몸["problems"])


@pytest.mark.parametrize(
    ("덮어쓰기", "칸"),
    [({"range": "7d"}, "range"), ({"slippageTicks": 11}, "slippageTicks"), ({"slippageTicks": -1}, "slippageTicks")],
)
def test_범위와_슬리피지가_밖이면_400_이다(손님, 덮어쓰기, 칸):
    앱, _ = 손님

    답 = 앱.post("/api/strategy/backtest", json=_몸(**덮어쓰기))

    assert 답.status_code == 400
    assert [one["field"] for one in 답.json()["detail"]["problems"]] == [칸]


def test_다른_셈이_돌고_있으면_409_다(손님):
    앱, _ = 손님

    assert backtest._busy.acquire(blocking=False)
    try:
        답 = 앱.post("/api/strategy/backtest", json=_몸())
    finally:
        backtest._busy.release()

    assert 답.status_code == 409
    assert 답.json()["detail"] == {"message": backtest.BUSY, "problems": []}


def test_셈은_아무것도_남기지_않고_계좌에_닿지_않는다(tmp_path, monkeypatch):
    """실행 목록·기록·한도 파일이 그대로이고, 계좌 장부와 주문 길은 불리지 않습니다."""

    def 닿으면_안됨(*args, **kwargs):
        raise AssertionError("셈이 계좌·기록 길에 닿았습니다.")

    monkeypatch.setattr(sim.SimBroker, "__init__", 닿으면_안됨)
    monkeypatch.setattr(journal_lib.Journal, "write", 닿으면_안됨)
    목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [_줄(one) for one in _진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2))],
    )
    monkeypatch.setattr(
        목록, "instrument", lambda *a, **k: {"tick": 틱, "multiplier": 1.0, "margin": 1_000.0, "exchange": ""}
    )
    app.dependency_overrides[get_service] = lambda: 목록
    app.dependency_overrides[get_master] = _마스터
    try:
        답 = TestClient(app).post("/api/strategy/backtest", json=_몸())
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_master, None)

    assert 답.status_code == 200, 답.text
    assert 목록.rows() == []
    assert sorted(path.name for path in tmp_path.iterdir()) == []


# ── 지난 봉으로 판정하지 못하는 조건 ────────────────────────
#
# 호가는 실행이 그 순간 적는 값이라 지난 봉에는 없습니다. 그 조건은 거짓으로 읽히고
# (단계·규칙을 건너뛰지 않음), 답의 `assumptions.unjudged` 가 그 조건을 알립니다.


def _호가_조건() -> dict:
    return {"id": "c2", "left": "bid1", "op": "gt", "rightKind": "number", "right": "0"}


def _단계(join: str, *conds: dict, within: int = 0) -> dict:
    return {"id": "s", "join": join, "withinBars": within, "conds": list(conds)}


def _설정_단계(*steps: dict) -> dict:
    설정 = _설정()
    설정["rules"]["buyEntry"] = {"on": True, "steps": list(steps)}
    return 설정


def test_모두_단계의_호가_조건은_그_단계를_막는다():
    답 = _셈(_진입봉(), _설정_단계(_단계("all", _조건(), _호가_조건())))

    assert 답["assumptions"]["unjudged"] == [
        {"rule": "buyEntry", "step": 1, "cond": 2, "operand": "bid1", "effect": backtest.STEP_BLOCKED}
    ]
    assert 답["signals"] == 0


def test_하나라도_1단계의_호가_조건은_다른_조건이_참이어도_규칙을_막는다():
    """1단계는 직전 봉에서 바뀐 것만 보는데, 직전 봉에 호가가 없으면 바뀐 것으로 치지 않습니다."""
    답 = _셈(_진입봉(), _설정_단계(_단계("any", _조건(), _호가_조건())))

    (줄,) = 답["assumptions"]["unjudged"]
    assert 줄["effect"] == backtest.RULE_NEVER_FIRES and 줄["step"] == 1
    assert 답["signals"] == 0, "close > 100 이 참이 되는 봉이 있어도 걸리지 않습니다."


def test_하나라도_나중_단계의_호가_조건은_그_조건만_거짓이다():
    설정 = _설정_단계(
        _단계("all", _조건(), within=3),
        _단계("any", _호가_조건(), _조건(right="100.5")),
    )

    답 = _셈(_진입봉(_봉(9, 3, 101.0, 101.5, 100.8, 101.2), *_평평(3, hour=10)), 설정)

    (줄,) = 답["assumptions"]["unjudged"]
    assert (줄["step"], 줄["cond"], 줄["effect"]) == (2, 1, backtest.COND_FALSE)
    assert 답["signals"] == 1, "2단계는 다른 조건(close > 100.5)으로 채워집니다."


def test_호가를_안_쓰면_판정_못_한_조건이_없다():
    답 = _셈(_진입봉())

    assert 답["assumptions"]["unjudged"] == []
    assert 답["signals"] == 1


def test_봉이_모자라_값이_없는_지표는_판정_못_한_조건에_안_든다():
    """기간이 받은 봉보다 긴 지표는 호가 때문이 아닙니다. 그런 조건은 목록에 들지 않습니다."""
    긴 = {"id": "c3", "left": "ema", "leftParams": {"period": 200}, "op": "gt", "rightKind": "number", "right": "0"}

    엔진 = engine.RunEngine(
        runs.Run(
            id="b", version_id="v", code="A7569000", session=주간, market="domestic",
            state=runs.ARMED, qty=1, cash=1e7, multiplier=1.0,
            draft=_설정_단계(_단계("all", _조건(), 긴, _호가_조건())),
        ),
        tick=틱,
    )
    엔진.bars.bars = _평평(10)
    엔진.bars.sessions = [주간] * 10

    줄들 = backtest.unjudged(엔진)

    assert 엔진._series().at("ema(200)", 9) is None, "끝까지 값이 없는 지표입니다."
    assert [줄["operand"] for 줄 in 줄들] == ["bid1"], "호가 조건만 듭니다."


def test_판정_못_한_조건을_알려도_판정은_그대로다(monkeypatch):
    """목록을 셈하지 않아도 같은 답입니다(목록 칸만 다름)."""
    설정 = _설정_단계(_단계("all", _조건(), _호가_조건()))
    있음 = _셈(_진입봉(), 설정)
    monkeypatch.setattr(backtest, "unjudged", lambda made: [])

    없음 = _셈(_진입봉(), 설정)

    없음["assumptions"]["unjudged"] = 있음["assumptions"]["unjudged"]
    assert 있음 == 없음


def test_쓰지_않는_주문유형으로_셈하면_그_칸은_한_줄이다(손님):
    앱, _ = 손님

    답 = 앱.post("/api/strategy/backtest", json=_몸(draft=_설정(orderType="최유리지정가")))

    assert 답.status_code == 400
    줄들 = [one for one in 답.json()["detail"]["problems"] if one["field"] == "aux.orderType"]
    assert [one["message"] for one in 줄들] == [
        "최유리지정가는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요"
    ]
