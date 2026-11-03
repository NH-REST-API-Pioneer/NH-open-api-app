"""ORB 앱용 파일과 MKU 리플레이 골든 시험.

week03 `backtest.py` 로 낸 `results/backtest_orb/start_all.json`(20261012~20261102, 37건, US$87.5, 수수료 0, 슬리피지 1틱)과
같은 1분봉을 앱 리플레이에 넣으면 **거래 목록이 같아야** 합니다(진입·청산 날짜·시각·가격·사유·손익).
비교에서만 맞추는 두 가지:
- 사유 이름 — 앱의 23:50 정리는 「장 마감 정리」, 백테스트는 「마감 정리」(같은 규칙).
- `signal_time` — 앱은 판정한 1분봉이 **끝난** 시각, 백테스트는 그 분의 **시작** 시각(`s.minute.time`) → 1분 차이.
week03 파일은 내려받은 것이라 실행하지 않고, 같은 바이트를 시험 자료로 두고 앱 로더로만 불러옵니다.
"""
import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.team_pyrun.journal import Journal
from backend.team_pyrun.loader import Loaded, load
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS
from backend.team_pyrun.replay import load_minutes, replay
from backend.team_pyrun.runner import Minute, PaperBroker, Runner

HERE = Path(__file__).parent
WEEK03 = HERE / "fixtures/team_pyrun/week03"
APP_FILE = HERE.parent / "docs/team/examples/strategy_orb_app.py"
CSV = WEEK03 / "bars_1m_MKUX26.csv"
GOLDEN = WEEK03 / "start_all.json"
DATA_FROM, DATA_TO = "20261012", "20261102"     # week03 backtest.py DATA_FROM·DATA_TO

#: week03 원본(내려받은 그대로)의 sha256 — 복사본이 한 바이트도 바뀌지 않았음을 지킨다
WEEK03_SHA256 = {
    "strategy_orb.py": "486ba7dc3d19705578808e1c62e246990942a0fa7c283b14ce59f719fdbc597e",
    "common.py": "acc75dd9d33a47e1f5232ce41dc6fd7b207cbeee1ab505668b6d0388f697f1a7",
}

#: 앱 사유 → 백테스트 사유 (비교에서만)
REASON_MAP = {"장 마감 정리": "마감 정리"}


@pytest.fixture
def folder(tmp_path):
    """tmp 전략 폴더 — 앱 파일과 그것이 부르는 week03 원본 두 개."""
    d = tmp_path / "strategies"
    d.mkdir()
    for src in (APP_FILE, WEEK03 / "strategy_orb.py", WEEK03 / "common.py"):
        shutil.copy(src, d / src.name)
    return d


def _minutes():
    return [m for m in load_minutes(CSV) if DATA_FROM <= m.date <= DATA_TO]


def _plus_minute(hhmmss: str) -> str:
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4]) + 1
    return f"{t // 60:02d}{t % 60:02d}00"


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _row(t: dict) -> tuple:
    return (t["entry_date"], t["entry_time"], t["side"], t["entry"], t["exit_date"], t["exit_time"], t["exit"],
            REASON_MAP.get(t["reason"], t["reason"]), t["ticks"])


def _replay(folder, out):
    loaded = load(folder, "strategy_orb_app.py")
    return replay(loaded, None, _minutes(), out, market=OVERSEAS, fee=0.0, slip_ticks=1, sym="MKUX26")


# ---------------------------------------------------------------- 불러오기
def test_앱_ORB_파일은_week03_원본과_같이_불러온다(folder):
    loaded = load(folder, "strategy_orb_app.py")
    assert loaded.kind == "minute" and loaded.name == "strategy_orb_app"
    assert (loaded.tick, loaded.tick_value) == (0.0001, 2.5)
    # ORB Params 에는 장 시간 칸이 없다 — 해외 실행이 시장 시간표로 채운다
    assert set(loaded.params_missing) == {"session_start", "session_end", "entry_start", "entry_end"}
    s = loaded.new(OVERSEAS)
    assert (s.p.session_start, s.p.entry_start, s.p.entry_end, s.p.flatten_at, s.p.session_end) == (
        "082500", "082500", "235000", "235000", "235500")
    assert hasattr(s, "exit_reason") and hasattr(s, "exit_levels")


def test_앱_ORB_파일은_strategy_orb_py_를_고치지_않는다():
    # 판정 코드는 week03 원본 그대로 가져다 쓴다(복사본이 원본과 같고, 앱 파일은 그것을 import 할 뿐)
    text = APP_FILE.read_text(encoding="utf-8")
    assert "from strategy_orb import Params, SessionBreakout" in text
    assert "def on_minute" not in text and "def on_entry" not in text and "def _decide" not in text
    # 시험 자료의 week03 원본 두 개가 내려받은 바이트 그대로인가 (scratchpad week03 원본의 sha256)
    assert {name: hashlib.sha256((WEEK03 / name).read_bytes()).hexdigest() for name in WEEK03_SHA256} == WEEK03_SHA256


# ---------------------------------------------------------------- 골든
def test_MKU_리플레이는_week03_백테스트와_거래가_같다(folder, tmp_path):
    golden = _golden()
    assert golden["summary"]["trades"] == 37 and golden["summary"]["net_pnl"] == 87.5
    got = _replay(folder, tmp_path / "out")
    assert [_row(t) for t in got["trades"]] == [_row(t) for t in golden["trades"]]
    assert got["summary"]["trades"] == 37
    assert got["summary"]["net_pnl"] == pytest.approx(87.5)
    assert got["summary"]["fee_total"] == 0
    assert [t["pnl"] for t in got["trades"]] == pytest.approx([t["pnl"] for t in golden["trades"]])


def test_MKU_리플레이의_개장_이름과_신호_시각도_같다(folder, tmp_path):
    golden = _golden()["trades"]
    got = _replay(folder, tmp_path / "out")["trades"]
    assert [t["window"] for t in got] == [t["window"] for t in golden]
    # 앱의 signal_time 은 판정 봉이 끝난 시각 = 백테스트 signal_time(그 분 시작) + 1분
    assert [t["signal_time"] for t in got] == [_plus_minute(t["signal_time"]) for t in golden]


def test_MKU_리플레이의_기록과_run_json(folder, tmp_path):
    out = tmp_path / "out"
    _replay(folder, out)
    rows = [x for x in Journal(out / "journal.jsonl").read() if x["kind"] == "trade"]
    assert len(rows) == 37 and {r["exit_date"] for r in rows} >= {"20261012", "20261102"}
    fills = [x for x in Journal(out / "journal.jsonl").read() if x["kind"] == "fill"]
    assert {f["source"] for f in fills} == {"paper"} and {f["fee"] for f in fills} == {0.0}
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (run["mode"], run["sym"], run["state"]) == ("replay", "MKUX26", "끝")
    params = json.loads((out / "summary.json").read_text(encoding="utf-8"))["strategy"]["params"]
    assert params["session_start"] == "082500" and params["range_min"] == 15


# ---------------------------------------------------------------- exit_reason 직접 시험 (골든이 안 지나는 규칙)
@pytest.fixture
def orb(folder):
    """해외 시간표로 채운 앱 ORB 전략 (hold_min 120 · flatten 23:50)."""
    return load(folder, "strategy_orb_app.py").new(OVERSEAS)


def _pos(side, entry, entry_time="093000", *, low=0.7480, high=0.7520, target_ticks=10, exit_by="170000"):
    """실행기가 넘기는 보유 사본 꼴. 신호는 ORB Signal 에서 exit_reason 이 읽는 칸만."""
    sig = SimpleNamespace(range_low=low, range_high=high, target_ticks=target_ticks, exit_by=exit_by)
    return {"side": side, "entry": entry, "entry_time": entry_time, "entry_date": "20261030",
            "signal_time": entry_time, "stop": None, "stop_ticks": 20, "signal": sig}


def test_매수_시가가_손절가_아래면_시가로_손절_아니면_손절가로(orb):
    pos = _pos("buy", 0.7500)            # 손절 = 범위 아래 끝 0.7480, 익절 = 0.7500 + 10틱 = 0.7510
    # 시가 물음(가격 하나): 시가 0.7470 이 이미 손절가 아래 → 시가 = min(시가, 손절가)
    assert orb.exit_reason("100000", 0.7470, None, None, pos) == ("손절", 0.7470)
    # 시가 0.7490 은 손절가 위 → 시가 물음은 들고 있음, 범위 물음(저가 0.7475)에서 손절가 = min(시가, 손절가)
    assert orb.exit_reason("100000", 0.7490, None, None, pos) is None
    assert orb.exit_reason("100000", 0.7485, 0.7475, 0.7492, pos) == ("손절", 0.7480)
    # 같은 분에 둘 다 닿으면 손절 먼저 (backtest 147~154 순서)
    assert orb.exit_reason("100000", 0.7500, 0.7475, 0.7515, pos) == ("손절", 0.7480)


def test_매수_익절_갭은_시가로_닿으면_목표가로(orb):
    pos = _pos("buy", 0.7500)
    assert orb.exit_reason("100000", 0.7515, None, None, pos) == ("익절", 0.7515)       # max(시가, 목표)
    assert orb.exit_reason("100000", 0.7505, 0.7501, 0.7512, pos) == ("익절", 0.7510)


def test_매도는_거울_시가가_손절가_위면_시가로_익절_갭도_시가로(orb):
    pos = _pos("sell", 0.7500)           # 손절 = 범위 위 끝 0.7520, 익절 = 0.7500 − 10틱 = 0.7490
    assert orb.exit_reason("100000", 0.7530, None, None, pos) == ("손절", 0.7530)       # max(시가, 손절가)
    assert orb.exit_reason("100000", 0.7510, None, None, pos) is None
    assert orb.exit_reason("100000", 0.7512, 0.7505, 0.7525, pos) == ("손절", 0.7520)
    assert orb.exit_reason("100000", 0.7485, None, None, pos) == ("익절", 0.7485)       # min(시가, 목표)
    assert orb.exit_reason("100000", 0.7495, 0.7488, 0.7499, pos) == ("익절", 0.7490)


def test_exit_by_가_hold_min_보다_이르면_다음_개장_전_청산(orb):
    # 17:10 진입 · hold_min 120 → 19:10, 신호의 exit_by 19:00 이 더 이름
    pos = _pos("buy", 0.7500, "171000", exit_by="190000")
    assert orb.exit_reason("185900", 0.7500, None, None, pos) is None
    assert orb.exit_reason("190000", 0.7502, None, None, pos) == "다음 개장 전 청산"   # 그 분 시가에서
    # exit_by 가 더 늦으면 hold_min 의 「시간 청산」
    late = _pos("buy", 0.7500, "171000", exit_by="223000")
    assert orb.exit_reason("190900", 0.7500, None, None, late) is None
    assert orb.exit_reason("191000", 0.7500, None, None, late) == "시간 청산"


def test_기한은_진입한_분이_지나야(orb):
    # 성긴 봉으로 exit_by(17:00) 뒤인 17:05 에 진입 — backtest 1단계는 그 분 전부터 든 보유만 보므로 그 분엔 기한 없음
    pos = _pos("buy", 0.7500, "170500", exit_by="170000")
    assert orb.exit_reason("170500", 0.7500, None, None, pos) is None
    assert orb.exit_reason("170500", 0.7500, 0.7499, 0.7501, pos) is None
    assert orb.exit_reason("170600", 0.7500, None, None, pos) == "다음 개장 전 청산"


def test_휴장_중엔_손절_익절_없이_기한만(orb):
    pos = _pos("buy", 0.7500, "184000", exit_by="223000")   # 기한 = 18:40 + 120분 = 20:40 (휴장 20:35~20:50)
    early = _pos("buy", 0.7500, "190000", exit_by="223000")
    # 20:40 은 매매 시간 밖 — 손절가·목표가를 지나도 None (backtest 141 `tradable`)
    assert orb.exit_reason("203400", 0.7470, None, None, early) == ("손절", 0.7470)      # 20:34 는 매매 시간
    assert orb.exit_reason("204000", 0.7470, None, None, early) is None
    assert orb.exit_reason("204000", 0.7500, 0.7470, 0.7530, early) is None
    assert orb.exit_reason("204000", 0.7515, None, None, early) is None
    # 기한은 매매 시간 밖이어도 그 분 시가에서 (backtest 111~116 은 tradable 을 보지 않음)
    assert orb.exit_reason("204000", 0.7470, None, None, pos) == "시간 청산"
    # 휴장 끝(20:50)부터 다시 손절
    assert orb.exit_reason("205000", 0.7470, None, None, early) == ("손절", 0.7470)


def _buy_runner(strat, tmp_path, hh="09"):
    """`hh`:00 개장 범위(0.7480~0.7500, 20틱)를 쌓고 `hh`:15 봉 종가 0.7502 로 위 돌파 → `hh`:16 시가 0.7503 에 매수.

    진입가 = 시가 0.7503 + 슬리피지 1틱 = 0.7504 · 손절 = 범위 아래 끝 0.7480 · 익절 = 0.7504 + 20틱 = 0.7524."""
    j = Journal(tmp_path / "journal.jsonl")
    r = Runner(strat, j, PaperBroker(j, 0.0001, fee=0.0, slip_ticks=1), 0.0001, 2.5)
    r.live_date = "20261030"
    for i in range(15):
        r.on_minute_closed(Minute("20261030", f"{hh}{i:02d}00", 0.7490, 0.7500, 0.7480, 0.7490, 1))
    r.on_minute_closed(Minute("20261030", f"{hh}1500", 0.7500, 0.7502, 0.7499, 0.7502, 1))
    assert r.pending is not None
    r.on_price(f"{hh}1600", 0.7503)          # 그 분 시가 하나로 진입 (대기 신호 → 다음 분 시가)
    assert r.pos is not None and (r.pos["entry"], r.pos["entry_time"]) == (0.7504, f"{hh}1600")
    return r


def test_실행기에서_시가_갭_손절은_시가_슬리피지로_체결(orb, tmp_path):
    r = _buy_runner(orb, tmp_path)
    r.on_price("091700", 0.7470)             # 시가가 범위 아래 끝 0.7480 을 이미 지남 → 시가 − 1틱
    assert [(t["reason"], t["exit"], t["exit_time"]) for t in r.trades] == [("손절", 0.7469, "091700")]
    assert orb.day.stops == 1


def test_실행기에서_다음_개장_전_청산은_그_분_시가_슬리피지로(orb, tmp_path):
    # hold_min 600 → 기한 19:16, 서울 신호의 exit_by(런던 개장 17:00)가 더 이름
    strat = type(orb)(replace(orb.p, hold_min=600))
    r = _buy_runner(strat, tmp_path)
    r.on_price("165900", 0.7505)
    assert r.trades == []
    r.on_price("170000", 0.7510)             # 그 분 시가 → 시가 − 1틱
    assert [(t["reason"], t["exit"], t["exit_time"]) for t in r.trades] == [("다음 개장 전 청산", 0.7509, "170000")]


def test_실행기에서_휴장_중_기한은_손절가를_지나도_시간_청산(orb, tmp_path):
    # 런던 17:16 진입 · hold_min 204 → 기한 20:40 (휴장 20:35~20:50), exit_by 22:30 은 더 늦음
    strat = type(orb)(replace(orb.p, hold_min=204))
    r = _buy_runner(strat, tmp_path, hh="17")
    r.on_price("203600", 0.7470)             # 휴장 중 손절가 아래 — 손절 없음
    assert r.trades == []
    r.on_price("204000", 0.7470)             # 기한은 휴장이어도 그 분 시가에서 → 시가 − 1틱, 사유는 시간 청산
    assert [(t["reason"], t["exit"], t["exit_time"]) for t in r.trades] == [("시간 청산", 0.7469, "204000")]
    assert strat.day.stops == 0


# ---------------------------------------------------------------- 화면의 손절·익절 (exit_levels)
def test_화면의_손절_익절은_exit_levels_를_따른다(folder, tmp_path):
    loaded = load(folder, "strategy_orb_app.py")
    j = Journal(tmp_path / "journal.jsonl")
    r = Runner(loaded.new(OVERSEAS), j, PaperBroker(j, loaded.tick, fee=0.0, slip_ticks=1), loaded.tick,
               loaded.tick_value)
    r.live_date = DATA_FROM
    for m in (m for m in _minutes() if m.date == DATA_FROM):
        if not (r.p.session_start <= m.time < r.p.session_end):
            r.feed(m)
            continue
        r.on_price(m.time, m.open)
        if r.pos is not None:
            break
        r.on_price(m.time, m.close, ref_low=m.low, ref_high=m.high)
        r.on_minute_closed(m)
    snap = r.snapshot()
    # 골든 첫 거래: 서울 매수 0.7481 · 손절 = 범위 아래 끝 0.7465 · 익절 = 0.7481 + 13틱 = 0.7494
    assert (snap["position"], snap["entry"]) == (1, 0.7481)
    assert (snap["stop"], snap["target"]) == (0.7465, 0.7494)
    assert snap["time_exit_at"] is None


@dataclass(frozen=True)
class _P:
    session_start: str = "090000"
    session_end: str = "153100"
    entry_start: str = "090000"
    entry_end: str = "150000"
    flatten_at: str = "153000"
    hold_min: int = 60


@dataclass
class _Sig:
    minute: Minute
    side: str | None
    reason: str = "시험"
    stop_ticks: int = 5


class _Levels:
    """09:00 봉에 매수 신호. `exit_levels` 는 엉뚱한 값을 보이지만 판단(공통 손절)은 그대로여야 한다."""

    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return [_Sig(m, "buy")] if m.time == "090000" else []

    def exit_levels(self, pos):
        return {"stop": 1.0, "target": 9999.0}


def test_exit_levels_는_화면에만_쓰고_판단에는_쓰지_않는다(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    r = Runner(_Levels(_P()), j, PaperBroker(j, 0.1, fee=0.0, slip_ticks=0), 0.1, 1000)
    r.live_date = "20261030"
    bar = Minute("20261030", "090000", 1340.0, 1340.0, 1340.0, 1340.0, 1)
    r.on_minute_closed(bar)
    r.on_price("090100", 1340.0)
    assert r.snapshot()["stop"] == 1.0 and r.snapshot()["target"] == 9999.0
    assert r.pos["stop"] == 1339.5          # 실행기의 손절은 진입가 − 5틱 그대로
    r.on_price("090200", 1339.5, ref_low=1339.5, ref_high=1340.0)
    assert [t["reason"] for t in r.trades] == ["손절"] and r.trades[0]["exit"] == 1339.5


def test_exit_levels_가_틀린_값이나_예외면_원래_값을_보인다(tmp_path):
    class Bad(_Levels):
        def exit_levels(self, pos):
            raise RuntimeError("화면용 계산 실패")

    class Odd(_Levels):
        def exit_levels(self, pos):
            return {"stop": "높음", "target": float("nan")}

    class Huge(_Levels):
        def exit_levels(self, pos):
            return {"stop": 10**400, "target": -(10**400)}     # float 로 못 바꾸는 큰 정수 — OverflowError 가 새지 않게

    for cls in (Bad, Odd, Huge):
        j = Journal(tmp_path / f"{cls.__name__}.jsonl")
        r = Runner(cls(_P()), j, PaperBroker(j, 0.1, fee=0.0, slip_ticks=0), 0.1, 1000)
        r.live_date = "20261030"
        r.on_minute_closed(Minute("20261030", "090000", 1340.0, 1340.0, 1340.0, 1340.0, 1))
        r.on_price("090100", 1340.0)
        snap = r.snapshot()
        assert snap["stop"] == 1339.5 and snap["target"] is None


# ---------------------------------------------------------------- 리플레이 인자 (시장·수수료·슬리피지·여러 날)
def _fake_loaded(cls, params=_P):
    return Loaded(file="fake.py", name="fake", title="가짜", sha256="0" * 64, strategy_cls=cls, params_cls=params,
                  tick=0.1, tick_value=1000)


class _LastMinute:
    """그날 마지막 판정 봉(15:00)에 매수 신호 — 다음 날로 넘어가면 안 된다."""

    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return [_Sig(m, "buy")] if m.time == "145900" else []


def test_여러_날_리플레이는_날이_바뀌면_대기_신호를_버린다(tmp_path):
    # 10/29 은 14:59 봉이 마지막 — 그 신호는 다음 가격이 없어 대기로 남는다. 백테스트처럼 날이 바뀌면 버린다
    ms = [Minute("20261029", t, 1340.0, 1340.0, 1340.0, 1340.0, 1) for t in ("145800", "145900")]
    ms += [Minute("20261030", t, 1340.0, 1340.0, 1340.0, 1340.0, 1) for t in ("090000", "090100")]
    got = replay(_fake_loaded(_LastMinute), None, ms, tmp_path / "out", fee=0.0, slip_ticks=0)
    assert got["trades"] == []      # 10/30 09:00 에 전날 신호로 들어가지 않음
    events = [x["text"] for x in Journal(tmp_path / "out/journal.jsonl").read() if x["kind"] == "event"]
    assert "날이 바뀌어 대기 신호를 버림" in events


class _Hold:
    """09:00 봉에 매수 신호, 청산 규칙에 안 걸리게 손절 폭을 크게."""

    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return [_Sig(m, "buy", stop_ticks=1000)] if m.time == "090000" else []


@dataclass(frozen=True)
class _LongP(_P):
    hold_min: int = 10_000


def test_여러_날은_날마다_따로_정리하고_날짜를_남긴다(tmp_path):
    ms = [Minute(d, t, 1340.0, 1341.0, 1339.0, 1340.0, 1)
          for d in ("20261029", "20261030") for t in ("090000", "090100", "090200")]
    got = replay(_fake_loaded(_Hold, _LongP), None, ms, tmp_path / "out", fee=10.0, slip_ticks=2)
    t = got["trades"]
    assert [(x["entry_date"], x["exit_date"], x["exit_time"], x["reason"]) for x in t] == [
        ("20261029", "20261029", "153000", "실행 종료 정리"), ("20261030", "20261030", "153000", "실행 종료 정리")]
    # 슬리피지 2틱(0.2) — 매수 진입 1340.0 + 0.2, 매도 청산 1340.0 − 0.2 · 수수료는 체결마다 10
    assert (t[0]["entry"], t[0]["exit"], t[0]["fee"]) == (1340.2, 1339.8, 20.0)


def test_해외_리플레이의_끝_정리는_해외_청산_시각(tmp_path):
    @dataclass(frozen=True)
    class NoSchedule:
        hold_min: int = 10_000

    class Hold(_Hold):
        def on_minute(self, m):
            return [_Sig(m, "buy", stop_ticks=1000)] if m.time == "090000" else []

    loaded = Loaded(file="fake.py", name="fake", title="가짜", sha256="0" * 64, strategy_cls=Hold,
                    params_cls=NoSchedule, tick=0.0001, tick_value=2.5,
                    params_missing=("session_start", "session_end", "entry_start", "entry_end", "flatten_at"))
    # 23:50 뒤 봉이 없으면 끝 정리 — 시각은 국내 153000 이 아니라 해외 청산 시각 235000
    ms = [Minute("20261030", t, 0.75, 0.7501, 0.7499, 0.75, 1) for t in ("090000", "090100", "234900")]
    got = replay(loaded, None, ms, tmp_path / "out", market=OVERSEAS, fee=2.0, slip_ticks=1)
    assert [(x["exit_time"], x["reason"]) for x in got["trades"]] == [("235000", "실행 종료 정리")]
    assert got["trades"][0]["fee"] == 4.0
    # 23:50 이후 봉(세션 끝 23:55 전)이 있으면 그 봉에서 장 마감 정리
    ms.append(Minute("20261030", "235400", 0.75, 0.7501, 0.7499, 0.75, 1))
    got = replay(loaded, None, ms, tmp_path / "out2", market=OVERSEAS, fee=2.0, slip_ticks=1)
    assert [(x["exit_time"], x["reason"]) for x in got["trades"]] == [("235400", "장 마감 정리")]


def test_리플레이_기본값은_국내_그대로(tmp_path):
    import inspect

    sig = inspect.signature(replay)
    assert sig.parameters["market"].default is DOMESTIC
    assert sig.parameters["fee"].default == 690.0 and sig.parameters["slip_ticks"].default == 1
