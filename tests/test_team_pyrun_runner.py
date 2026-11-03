"""파이썬 전략 실행기·리플레이 시험 — week02 와 같은 거래가 나오는지, 멈춘 실행이 주문을 안 내는지."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.team_pyrun import replay as replay_mod
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.loader import load
from backend.team_pyrun.replay import load_minutes, replay
from backend.team_pyrun.runner import (Minute, PaperBroker, Runner, minute_of, pnl_ticks,
                                       stop_price, take_profit_price)

FOLDER = Path(__file__).parent / "fixtures/team_pyrun/strategies"
DATA = Path(__file__).parent / "fixtures/team_pyrun/bars_1m_A756B000_20261030.csv"


def _trades(file, tmp_path):
    r = replay(load(FOLDER, file), "20261030", load_minutes(DATA), tmp_path)
    return [(t["side"], t["entry"], t["exit"], t["reason"], t["entry_time"], t["exit_time"])
            for t in r["trades"]], r


def test_볼린저_리플레이는_week02_와_같다(tmp_path):
    got, r = _trades("strategy_bb.py", tmp_path)
    assert got == [("sell", 1339.6, 1337.7, "익절", "093500", "101700"),
                   ("buy", 1334.9, 1336.7, "익절", "121000", "124000"),
                   ("buy", 1334.1, 1335.8, "익절", "142500", "144400")]
    assert r["summary"]["net_pnl"] == 54000
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["summary"]["net_pnl"] == 54000
    # 실시간 실행과 같은 꼴로 전략 정보가 남는다(지난 실행 화면의 Params)
    strategy = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["strategy"]
    assert strategy["file"] == "strategy_bb.py" and strategy["params"]["bar_min"] == 5


def test_VWAP_리플레이는_week02_와_같다(tmp_path):
    got, r = _trades("strategy.py", tmp_path)
    assert [g[3] for g in got] == ["익절", "익절", "익절", "손절", "손절"] and r["summary"]["net_pnl"] == -21000


def test_판정_봉마다_signal_줄이_선다(tmp_path):
    _trades("strategy_bb.py", tmp_path)
    sig = [x for x in Journal(tmp_path / "journal.jsonl").read() if x["kind"] == "signal" and x["date"] == "20261030"]
    assert len(sig) == 79                       # 5분봉 09:00, 09:05 … 15:30 시작
    assert {"upper", "middle", "lower", "rsi", "atr"} <= set(sig[-1])


def test_trade_줄에_reason_과_exit_date_가_있다(tmp_path):
    _trades("strategy.py", tmp_path)
    rows = [x for x in Journal(tmp_path / "journal.jsonl").read() if x["kind"] == "trade"]
    assert [x["reason"] for x in rows] == ["익절", "익절", "익절", "손절", "손절"]
    assert {x["exit_date"] for x in rows} == {"20261030"}


def test_리플레이는_run_json_을_남긴다(tmp_path):
    loaded = load(FOLDER, "strategy_bb.py")
    folder = tmp_path / "20261030_bb_replay"
    replay(loaded, "20261030", load_minutes(DATA), folder)
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert run["id"] == "20261030_bb_replay"
    assert (run["file"], run["name"], run["title"], run["sha256"]) == (
        loaded.file, loaded.name, loaded.title, loaded.sha256)
    assert (run["mode"], run["sym"], run["state"], run["ended_reason"]) == ("replay", "A756B000", "끝", "리플레이")
    assert run["started_at"] and run["ended_at"]


def test_명령줄은_저장소_밖_상태_폴더에_쓴다(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(replay_mod.storage, "state_dir", lambda env=None: state)
    monkeypatch.setattr(replay_mod, "strategies_dir", lambda: FOLDER)
    out = state / "pyruns" / "20261030_bb_replay"
    out.mkdir(parents=True)
    (out / "old.txt").write_text("지난 것", encoding="utf-8")        # 같은 이름 폴더는 비우고 다시 씀
    replay_mod.main(["strategy_bb.py", "20261030", str(DATA)])
    assert not (out / "old.txt").exists()
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["summary"]["net_pnl"] == 54000
    assert json.loads((out / "run.json").read_text(encoding="utf-8"))["sym"] == "A756B000"


# ---------------------------------------------------------------- 가짜 broker 로 보는 안전장치
class FakeBroker:
    mode = "fake"
    last_fill_fee = None

    def __init__(self, fill_px=None, held=None):
        self.fill_px, self.held = fill_px, held
        self.fills: list[tuple] = []

    def fill(self, side, ref_price, clock, why):
        self.fills.append((side, ref_price, clock, why))
        return self.fill_px

    def position(self):
        return self.held

    def account(self, clock="", why=""):
        return None


def _runner(tmp_path, broker, side="buy"):
    p = SimpleNamespace(entry_start="093000", entry_end="150000", flatten_at="153000", hold_min=120)
    day = SimpleNamespace(stops=0, realized_pnl=0)

    def on_exit(pnl, stopped):      # 실제 전략처럼 하루 손절 수를 센다
        day.stops += int(stopped)

    strat = SimpleNamespace(p=p, target=None, day=day, on_entry=lambda: None, on_exit=on_exit)
    r = Runner(strat, Journal(tmp_path / "journal.jsonl"), broker, 0.1, 1000)
    r.live_date = "20261030"
    r.pos = {"side": side, "entry": 1335.0, "entry_time": "100000", "signal_time": "095900",
             "stop_ticks": 10, "stop": 1334.0 if side == "buy" else 1336.0, "entry_fee": None}
    return r


def test_멈춘_실행은_청산도_진입도_안_한다(tmp_path):
    b = FakeBroker(fill_px=1333.0)
    r = _runner(tmp_path, b)
    r.pending = {"side": "sell", "stop_ticks": 5, "signal": "100000"}
    r.halt("시험")
    assert r.halted == "시험"
    r.on_price("100100", 1333.0, ref_low=1333.0, ref_high=1333.0)   # 손절가를 지남
    r.on_price("153100", 1333.0)                                    # 장 마감 정리 시각도
    assert b.fills == [] and r.pos is not None and r.trades == []
    r.force_flat("153000")
    assert b.fills == []


def test_청산_뒤_잔고가_기대와_다르면_다시_청산하지_않고_멈춘다(tmp_path):
    b = FakeBroker(fill_px=None, held=2)         # 기대 +1, 계좌 +2 (남의 주문이 섞임)
    r = _runner(tmp_path, b)
    r.on_price("100100", 1333.0, ref_low=1333.0, ref_high=1333.0)
    assert len(b.fills) == 1
    assert r.halted and "잔고 불일치" in r.halted and "+1" in r.halted and "+2" in r.halted
    r.on_price("100200", 1333.0, ref_low=1333.0, ref_high=1333.0)   # 10초가 지나도 재시도 없음
    r.on_price("100300", 1333.0)
    assert len(b.fills) == 1 and r.pos is not None


def test_청산_뒤_잔고를_못_읽으면_멈춘다(tmp_path):
    b = FakeBroker(fill_px=None, held=None)
    r = _runner(tmp_path, b)
    r.on_price("100100", 1333.0, ref_low=1333.0, ref_high=1333.0)
    assert r.halted and "잔고 불일치" in r.halted
    assert len(b.fills) == 1


def test_청산_뒤_잔고가_기대와_같으면_10초_뒤_다시_시도한다(tmp_path):
    b = FakeBroker(fill_px=None, held=1)
    r = _runner(tmp_path, b)
    r.on_price("100100", 1333.0)
    assert r.halted is None and len(b.fills) == 1 and r.retry_after == "100110"
    r.on_price("100105", 1333.0)                    # 아직 10초 안 됨
    assert len(b.fills) == 1
    r.on_price("100110", 1333.0)
    assert len(b.fills) == 2


def test_청산_뒤_잔고가_0이면_week02_처럼_기록한다(tmp_path):
    b = FakeBroker(fill_px=None, held=0)
    r = _runner(tmp_path, b)
    r.on_price("100100", 1333.0)
    assert r.pos is None and r.halted is None
    assert r.trades[0]["exit"] == 1333.0       # 단일 가격이면 그 가격으로 기록
    assert r.trades[0]["reason"] == "손절"


def test_진입_뒤_잔고를_못_읽으면_멈춘다(tmp_path):
    b = FakeBroker(fill_px=None, held=None)
    r = _runner(tmp_path, b)
    r.pos = None
    r.pending = {"side": "buy", "stop_ticks": 5, "signal": "100000"}
    r.on_price("100100", 1335.0)
    assert r.halted and r.pos is None and len(b.fills) == 1


def test_snapshot_칸(tmp_path):
    r = _runner(tmp_path, FakeBroker())
    s = r.snapshot()
    assert {"position", "entry", "stop", "stop_ticks", "target", "time_exit_at", "today_pnl", "stops",
            "max_stops", "halted", "last_signal"} <= set(s)
    assert (s["position"], s["entry"], s["stop"], s["time_exit_at"]) == (1, 1335.0, 1334.0, "120000")
    assert (s["today_pnl"], s["stops"], s["halted"], s["last_signal"]) == (0, 0, None, None)
    assert r.expected_position() == 1


def test_snapshot_보유_없음과_오늘_손익(tmp_path):
    r = _runner(tmp_path, FakeBroker(fill_px=1333.0))
    r.on_price("100100", 1333.0)                    # 손절로 청산: 1335.0 -> 1333.0 = -20틱 -> -20000원
    s = r.snapshot()
    assert (s["position"], s["entry"], s["stop"], s["stop_ticks"], s["time_exit_at"]) == (0, None, None, None, None)
    assert s["today_pnl"] == -20000 and s["stops"] == 1


def test_snapshot_손절_수는_전략의_하루_값을_따른다(tmp_path):
    r = _runner(tmp_path, FakeBroker())
    r.strat.day.stops = 1                           # 앞선 실행이 낸 손절을 이어받은 값
    assert r.snapshot()["stops"] == 1 and r.snapshot()["today_pnl"] == 0


def test_신호_줄의_지표_칸은_예약_칸과_비정상_수를_뺀다(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Bar:
        date: str = "20261030"
        start: str = "100000"
        end: str = "100500"
        close: float = 1335.0
        reason: float = 7.0         # 신호 줄의 reason 과 같은 이름
        kind: float = 1.0
        rsi: float = 55.55555
        bad: float = float("nan")
        big: float = float("inf")

    sig = SimpleNamespace(bar=Bar(), side=None, reason="신호 없음", stop_ticks=None)
    r = _runner(tmp_path, FakeBroker())
    r.strat.on_minute = lambda m: [sig]
    r.on_minute_closed(Minute("20261030", "100400", 1, 1, 1, 1, 0))
    row = Journal(tmp_path / "journal.jsonl").read()[-1]
    assert row["kind"] == "signal" and row["reason"] == "신호 없음" and row["rsi"] == 55.556
    assert "bad" not in row and "big" not in row
    assert r.last_signal == row


# ---------------------------------------------------------------- 작은 함수
def test_틱_함수는_틱_인자를_따른다():
    assert stop_price("buy", 1335.0, 10, 0.1) == 1334.0
    assert stop_price("sell", 1335.0, 10, 0.1) == 1336.0
    assert take_profit_price("buy", 1336.04, 0.1) == 1336.1       # 매수 보유는 올림
    assert take_profit_price("sell", 1336.04, 0.1) == 1336.0      # 매도 보유는 내림
    assert pnl_ticks("buy", 1335.0, 1336.7, 0.1) == 17
    assert pnl_ticks("sell", 1335.0, 1336.7, 0.1) == -17
    assert stop_price("buy", 0.7500, 3, 0.0001) == 0.7497         # 틱이 다른 종목


def test_종이_체결은_불리한_쪽_한_틱(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    b = PaperBroker(j, 0.1)
    assert b.fill("buy", 1335.0, "100000", "진입") == 1335.1
    assert b.fill("sell", 1335.0, "100100", "청산") == 1334.9
    rows = j.read()
    assert rows[0]["source"] == "paper" and rows[0]["text"].startswith("종이 체결 · ") and rows[0]["fee"] == 690.0
    assert b.mode == "paper" and b.position() is None and b.last_fill_fee == 690.0


def test_차트_줄에서_분봉을_만든다():
    m = minute_of({"ref_dt": "20261030", "exch_tm": "090000", "open_pric": "1331.60", "high_pric": "1331.70",
                   "low_pric": "1331.00", "close_pric": "1331.20", "cum_trd_qty": "4594"})
    assert m == Minute("20261030", "090000", 1331.6, 1331.7, 1331.0, 1331.2, 4594.0)
    assert minute_of({"ref_dt": "20261030", "exch_tm": "090000", "open_pric": "1", "high_pric": "1",
                      "low_pric": "1", "close_pric": "1", "cum_trd_qty": ""}).volume == 0.0


# ---------------------------------------------------------------- 전략이 청산을 판단하는 약속 (exit_reason)
class _Ask:
    """`exit_reason` 이 받은 인자를 적고, `answer` 를 돌려준다."""

    def __init__(self, answer=None):
        self.answer, self.calls = answer, []

    def __call__(self, clock, price, low, high, pos):
        self.calls.append((clock, price, low, high, pos))
        return self.answer(clock, price, low, high, pos) if callable(self.answer) else self.answer


def _judge(tmp_path, broker, answer=None, side="buy"):
    """보유 중인 실행기 + 청산 판단 함수를 가진 전략. 공통 규칙이 쓰였다면 걸릴 값(손절·익절·시간)을 깔아 둔다."""
    r = _runner(tmp_path, broker, side=side)
    exits = []
    r.strat.target = 1336.0                         # 공통 규칙이면 익절에 걸림
    r.strat.exit_reason = _Ask(answer)
    r.strat.on_exit = lambda pnl, stopped: exits.append((pnl, stopped))
    r.exits = exits
    return r


def test_청산_판단_함수가_있으면_공통_규칙을_쓰지_않는다(tmp_path):
    b = FakeBroker(fill_px=1333.0)
    r = _judge(tmp_path, b, answer=None)
    r.on_price("100100", 1333.0, ref_low=1333.0, ref_high=1337.0)  # 공통이면 손절(1334.0)·익절 둘 다 걸림
    r.on_price("120100", 1335.0)                                    # 공통이면 시간 청산(hold_min 120)
    assert b.fills == [] and r.pos is not None and r.trades == []
    assert len(r.strat.exit_reason.calls) == 2
    assert r.snapshot()["time_exit_at"] is None                    # 시간 청산도 전략이 판단 — 앱은 시각을 짐작하지 않음


def test_청산_판단이_손절이면_청산하고_on_exit_에_stopped(tmp_path):
    b = FakeBroker(fill_px=1333.0)
    r = _judge(tmp_path, b, answer="손절")
    r.on_price("100100", 1333.5)
    assert b.fills == [("sell", 1333.5, "100100", "청산 · 손절")]     # 기준가 = 지금 가격
    assert r.pos is None and r.trades[0]["reason"] == "손절"
    assert r.exits == [(-20000, True)]
    r.strat.day = None                              # 하루 상태가 없으면 실행기가 센 손절 수
    assert r.snapshot()["stops"] == 1


def test_청산_판단은_기준가를_함께_돌려줄_수_있다(tmp_path):
    b = FakeBroker(fill_px=1334.0)
    r = _judge(tmp_path, b, answer=("손절", 1334.0))
    r.on_price("100100", 1333.0, ref_low=1332.0, ref_high=1335.5)
    assert b.fills == [("sell", 1334.0, "100100", "청산 · 손절")]
    assert r.trades[0]["reason"] == "손절" and r.exits[0][1] is True


def test_청산_판단에_넘기는_인자(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Sig:
        side: str = "buy"
        window: str = "서울"
        range_low: float = 1334.2

    b = FakeBroker(fill_px=1335.0)
    r = _judge(tmp_path, b)
    r.pos = None
    sig = Sig()
    r.pending = {"side": "buy", "stop_ticks": 5, "signal": "100000", "obj": sig}
    r.on_price("100100", 1335.0)                                    # 진입 → 그 가격으로 바로 한 번 물어봄
    r.on_price("100100", 1335.2, ref_low=1334.8, ref_high=1335.6)
    (c1, p1, lo1, hi1, pos1), (c2, p2, lo2, hi2, pos2) = r.strat.exit_reason.calls
    assert (c1, p1, lo1, hi1) == ("100100", 1335.0, None, None)    # 가격 하나면 low·high 는 None
    assert (c2, p2, lo2, hi2) == ("100100", 1335.2, 1334.8, 1335.6)
    assert pos2["signal"] is sig and pos2["window"] == "서울"
    assert (pos2["side"], pos2["entry"], pos2["entry_time"], pos2["entry_date"]) == ("buy", 1335.0, "100100", "20261030")
    assert pos2["stop"] == 1334.5 and pos2["signal_time"] == "100000"
    pos2["side"] = "sell"                                           # 넘긴 것은 사본 — 실행기 보유는 그대로
    assert r.pos["side"] == "buy" and "signal" not in r.pos


@pytest.mark.parametrize("clock", ["153000", "153100"])
def test_장_마감은_전략이_None_이어도_청산한다(tmp_path, clock):
    b = FakeBroker(fill_px=1335.0)
    r = _judge(tmp_path, b, answer=None)
    r.on_price(clock, 1335.0)
    assert r.trades[0]["reason"] == "장 마감 정리"
    assert r.strat.exit_reason.calls == []                          # 마감은 앱이 먼저 — 전략에 묻지 않음


def test_멈춘_실행은_청산_판단을_묻지도_않는다(tmp_path):
    b = FakeBroker(fill_px=1333.0)
    r = _judge(tmp_path, b, answer="손절")
    r.halt("시험")
    r.on_price("100100", 1333.0)
    assert b.fills == [] and r.strat.exit_reason.calls == []


def test_실행_끝_정리는_청산_판단과_상관없다(tmp_path):
    b = FakeBroker(fill_px=1335.0)
    r = _judge(tmp_path, b, answer=None)
    r.on_price("100100", 1335.0)
    r.force_flat("153000")
    assert r.trades[0]["reason"] == "실행 종료 정리"


def test_청산이_확인_안_되면_전략에_다시_묻지_않고_같은_사유로_다시_시도한다(tmp_path):
    b = FakeBroker(fill_px=None, held=1)            # 청산 주문이 안 들어감(잔고 그대로)
    answers = iter(["손절"])
    r = _judge(tmp_path, b, answer=lambda *a: next(answers, None))
    r.on_price("100100", 1333.0)
    assert r.retry_after == "100110" and len(b.fills) == 1
    r.on_price("100105", 1335.0)                    # 기다리는 동안은 묻지도 주문하지도 않음
    assert len(b.fills) == 1 and len(r.strat.exit_reason.calls) == 1
    b.fill_px = 1335.0
    r.on_price("100110", 1335.0)                    # 전략은 이제 None 이지만 앞선 청산 결정을 다시 시도
    assert b.fills[-1] == ("sell", 1335.0, "100110", "청산 · 손절")
    assert len(r.strat.exit_reason.calls) == 1 and r.trades[0]["reason"] == "손절"


@pytest.mark.parametrize("bad", ["", 3, ("손절",), ("손절", float("nan")), ("손절", "1334")])
def test_청산_판단이_엉뚱한_값을_돌려주면_오류(tmp_path, bad):
    r = _judge(tmp_path, FakeBroker(fill_px=1333.0), answer=bad)
    with pytest.raises(TypeError, match="exit_reason"):
        r.on_price("100100", 1333.0)
    assert r.pos is not None and r.trades == []


# ---------------------------------------------------------------- on_entry 인자 · minute 꼴 신호
def test_on_entry_인자는_같은_이름의_신호_칸_값(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Sig:
        window: str = "런던"
        target_ticks: int = 7

    got = []
    r = _runner(tmp_path, FakeBroker(fill_px=1335.1))
    r.pos = None
    r.strat.on_entry = lambda window, target_ticks, extra="기본": got.append((window, target_ticks, extra))
    r.pending = {"side": "buy", "stop_ticks": 5, "signal": "100000", "obj": Sig()}
    r.on_price("100100", 1335.0)
    assert got == [("런던", 7, "기본")]
    assert r.pos["window"] == "런던"


def test_on_entry_인자가_신호에_없으면_오류(tmp_path):
    r = _runner(tmp_path, FakeBroker(fill_px=1335.1))
    r.pos = None
    r.strat.on_entry = lambda window: None
    r.pending = {"side": "buy", "stop_ticks": 5, "signal": "100000", "obj": SimpleNamespace(side="buy")}
    with pytest.raises(TypeError, match="on_entry 의 인자 window 와 같은 이름의 칸이 진입 신호에 없습니다"):
        r.on_price("100100", 1335.0)


def test_minute_꼴_신호를_기록하고_trade_에_window(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Sig:
        minute: Minute
        window: str
        side: object
        reason: str
        range_high: float | None = None
        range_low: float | None = None
        stop_ticks: int | None = None
        target_ticks: int | None = None
        exit_by: str | None = None
        flag: bool = True                          # 참거짓은 기록하지 않음
        bad: float = float("nan")

    m = Minute("20261030", "100400", 0.75, 0.7512, 0.7498, 0.7511, 30)
    s = Sig(m, "서울", "buy", "서울 개장 범위 위로 돌파", 0.7505, 0.7489, 22, 16, "170000")
    j = Journal(tmp_path / "journal.jsonl")
    p = SimpleNamespace(entry_start="082500", entry_end="235000", flatten_at="235000", hold_min=120)
    strat = SimpleNamespace(p=p, on_minute=lambda m: [s], exit_reason=lambda *a: "손절")
    r = Runner(strat, j, PaperBroker(j, 0.0001, fee=2.0), 0.0001, 2.5)
    r.live_date = "20261030"
    r.on_minute_closed(m)
    row = j.read()[-1]
    assert row["kind"] == "signal"
    assert (row["date"], row["bar"], row["clock"], row["close"]) == ("20261030", "100400", "100500", 0.7511)
    assert (row["open"], row["high"], row["low"]) == (0.75, 0.7512, 0.7498)
    assert (row["window"], row["range_high"], row["range_low"]) == ("서울", 0.7505, 0.7489)
    assert (row["target_ticks"], row["exit_by"], row["stop_ticks"], row["side"]) == (16, "170000", 22, "buy")
    assert "flag" not in row and "bad" not in row and "minute" not in row
    assert r.pending["obj"] is s and r.pending["signal"] == "100500"
    r.on_price("100500", 0.7511)
    r.on_price("100600", 0.7490)
    trade = [x for x in j.read() if x["kind"] == "trade"][0]
    assert trade["window"] == "서울" and trade["reason"] == "손절"
    assert r.trades[0]["window"] == "서울"


def test_week02_꼴_trade_줄에는_window_가_없다(tmp_path):
    _trades("strategy.py", tmp_path)
    rows = [x for x in Journal(tmp_path / "journal.jsonl").read() if x["kind"] == "trade"]
    assert rows and all("window" not in x for x in rows)


def _orb_exit(clock, price, low, high, pos):
    """week03 backtest.py ORB 청산 규칙을 옮긴 꼴(보고서의 스케치와 같음) — 기한은 그 분 시가에서, 손절은 범위 반대편 끝."""
    sig, buy = pos["signal"], pos["side"] == "buy"
    stop = sig.range_low if buy else sig.range_high
    if low is None and clock >= sig.exit_by:
        return "다음 개장 전 청산"
    lo, hi = (price, price) if low is None else (low, high)
    if (lo <= stop) if buy else (hi >= stop):
        # 가격 하나(시가)면 그 가격, 범위면 손절가 = backtest 의 min(open, stop)/max(open, stop)
        return ("손절", price if low is None else stop)
    return None


@pytest.mark.parametrize("bar, want", [
    ((1334.5, 1334.6, 1333.8, 1334.0), ("100100", 1334.0)),     # 그 분 안에서 손절가를 지남 → 손절가
    ((1333.5, 1333.6, 1333.0, 1333.2), ("100100", 1333.5)),     # 시가가 이미 손절가 밖 → 시가
])
def test_ORB_꼴_청산을_리플레이_순서로_재현한다(tmp_path, bar, want):
    o, h, lo, c = bar
    b = FakeBroker(fill_px=1333.0)
    r = _runner(tmp_path, b)
    r.strat.exit_reason = _orb_exit
    r.entry_signal = SimpleNamespace(range_low=1334.0, range_high=1336.0, exit_by="170000")
    r.on_price("100100", o)                         # replay: 그 분 시가
    r.on_price("100100", c, ref_low=lo, ref_high=h)  # replay: 종가와 저가·고가
    assert [(f[2], f[1]) for f in b.fills] == [want] and r.trades[0]["reason"] == "손절"


def test_ORB_꼴_기한은_그_분_시가에서(tmp_path):
    b = FakeBroker(fill_px=1335.0)
    r = _runner(tmp_path, b)
    r.strat.exit_reason = _orb_exit
    r.entry_signal = SimpleNamespace(range_low=1330.0, range_high=1340.0, exit_by="113000")   # 시험 실행기의 마감은 15:30
    r.on_price("112900", 1335.0, ref_low=1334.0, ref_high=1336.0)
    assert b.fills == []
    r.on_price("113000", 1335.2)
    assert b.fills == [("sell", 1335.2, "113000", "청산 · 다음 개장 전 청산")]


# ---------------------------------------------------------------- 고침 1차: 기준가 묶기·on_entry 먼저·예약 사유·자릿수
def test_전략_기준가는_가격_하나면_그_가격_범위면_범위_안으로(tmp_path):
    b = FakeBroker(fill_px=1335.0)
    r = _judge(tmp_path, b, answer=("익절", 9999.0))
    r.on_price("100100", 1335.0)                                    # 가격 하나 → 지금 가격
    assert b.fills[-1][1] == 1335.0
    r2 = _judge(tmp_path / "b", b2 := FakeBroker(fill_px=1336.0), answer=("익절", 9999.0))
    r2.on_price("100100", 1335.2, ref_low=1334.8, ref_high=1336.0)  # 범위 → 고가로 묶음
    assert b2.fills[-1][1] == 1336.0
    r3 = _judge(tmp_path / "c", b3 := FakeBroker(fill_px=1334.8), answer=("손절", 1.0))
    r3.on_price("100100", 1335.2, ref_low=1334.8, ref_high=1336.0)  # 범위 → 저가로 묶음
    assert b3.fills[-1][1] == 1334.8
    for out in (tmp_path, tmp_path / "b"):
        texts = [x.get("text", "") for x in Journal(out / "journal.jsonl").read() if x["kind"] == "event"]
        assert any("기준가" in t and "9999" in t for t in texts)


def test_전략_기준가가_범위_안이면_그대로_알림도_없다(tmp_path):
    b = FakeBroker(fill_px=1334.0)
    r = _judge(tmp_path, b, answer=("손절", 1334.0))
    r.on_price("100100", 1333.0, ref_low=1332.0, ref_high=1335.5)
    assert b.fills[-1][1] == 1334.0
    assert not any("기준가" in x.get("text", "") for x in Journal(tmp_path / "journal.jsonl").read())


def test_on_entry_인자가_틀리면_주문_전에_멈춘다(tmp_path):
    b = FakeBroker(fill_px=1335.1)
    r = _runner(tmp_path, b)
    r.pos = None
    r.strat.on_entry = lambda window: None
    r.pending = {"side": "buy", "stop_ticks": 5, "signal": "100000", "obj": SimpleNamespace(side="buy")}
    with pytest.raises(TypeError, match="on_entry 의 인자 window"):
        r.on_price("100100", 1335.0)
    assert b.fills == [] and r.pos is None and r.pending is None


@pytest.mark.parametrize("bad", ["장 마감 정리", "실행 종료 정리", " 장 마감 정리 ", "가" * 41, ("실행 종료 정리", 1334.0)])
def test_앱_예약_사유와_긴_사유는_받지_않는다(tmp_path, bad):
    r = _judge(tmp_path, FakeBroker(fill_px=1333.0), answer=bad)
    with pytest.raises(TypeError, match="exit_reason"):
        r.on_price("100100", 1333.0)
    assert r.pos is not None and r.trades == []


def test_사유는_40자까지(tmp_path):
    r = _judge(tmp_path, FakeBroker(fill_px=1333.0), answer="가" * 40)
    r.on_price("100100", 1333.0)
    assert r.trades[0]["reason"] == "가" * 40


def test_지표_자릿수는_틱을_따른다_국내는_3자리_그대로(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Bar:
        date: str = "20261030"
        start: str = "100000"
        end: str = "100500"
        open: float = 0.7433
        high: float = 0.7435
        low: float = 0.7431
        close: float = 0.7434
        ema: float = 0.7433456789

    sig = SimpleNamespace(bar=Bar(), side=None, reason="", stop_ticks=None)
    j = Journal(tmp_path / "journal.jsonl")
    strat = SimpleNamespace(p=SimpleNamespace(), on_minute=lambda m: [sig])
    r = Runner(strat, j, PaperBroker(j, 0.0001, fee=2.0), 0.0001, 2.5)
    r.on_minute_closed(Minute("20261030", "100400", 1, 1, 1, 1, 0))
    row = j.read()[-1]
    assert row["ema"] == 0.743346 and (row["open"], row["high"], row["low"]) == (0.7433, 0.7435, 0.7431)
    r2 = _runner(tmp_path / "d", FakeBroker())                     # 국내(틱 0.1)는 기존 3자리
    r2.strat.on_minute = lambda m: [SimpleNamespace(bar=Bar(ema=55.55555), side=None, reason="", stop_ticks=None)]
    r2.on_minute_closed(Minute("20261030", "100400", 1, 1, 1, 1, 0))
    assert Journal(tmp_path / "d" / "journal.jsonl").read()[-1]["ema"] == 55.556
