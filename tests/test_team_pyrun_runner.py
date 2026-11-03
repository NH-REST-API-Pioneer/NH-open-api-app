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
