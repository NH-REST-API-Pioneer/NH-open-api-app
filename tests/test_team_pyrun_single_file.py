"""전략 파일 하나만 올려도 돈다 — week02 원본(고치지 않은 것)을 빈 폴더에 혼자 두고 불러와 다시 돌린다.

- 폴더에 `strategy.py` 가 없으면 앱에 들어 있는 기본 공용 모듈(week02 `strategy.py` 원본)을 쓴다. 폴더의 것이 먼저다.
- `STRATEGY`·`TITLE`·`NAME` 줄이 없으면 그 파일에서 정의한 `on_minute` 클래스를 찾고 이름·제목을 정한다.
- 익절 목표는 `target`, 없으면 `current_vwap`(week02 `runner.make_strategy` 와 같음), 둘 다 없으면 익절 없음.
- `day`·`on_entry`·`on_exit`·`end_of_day` 는 없어도 된다.
"""
import hashlib
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.team_pyrun import loader
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import LiveRun, RunSpec
from backend.team_pyrun.loader import LoadError, load, scan_all
from backend.team_pyrun.replay import load_minutes, replay
from backend.team_pyrun.runner import Minute, PaperBroker, Runner, target_of
from tests.test_team_pyrun_live import FakeApi, at, bar

FIX = Path(__file__).parent / "fixtures" / "team_pyrun"
WEEK02 = FIX / "week02"
DATA = FIX / "bars_1m_A756B000_20261030.csv"

BB_GOLDEN = [("sell", 1339.6, 1337.7, "익절", "093500", "101700"),
             ("buy", 1334.9, 1336.7, "익절", "121000", "124000"),
             ("buy", 1334.1, 1335.8, "익절", "142500", "144400")]
NO_TARGET_NOTE = "target·current_vwap 이 없어 익절 없이 돕니다"

PARAMS_SRC = '''
@dataclass(frozen=True)
class Params:
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"
    hold_min: int = 30
'''


def _alone(tmp_path, name: str) -> Path:
    """week02 원본 파일 하나만 든 새 폴더."""
    folder = tmp_path / ("only_" + name.removesuffix(".py"))
    folder.mkdir()
    shutil.copy(WEEK02 / name, folder / name)
    return folder


def _write(folder: Path, file: str, src: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(src, encoding="utf-8")
    return folder


def _rows(r):
    return [(t["side"], t["entry"], t["exit"], t["reason"], t["entry_time"], t["exit_time"]) for t in r["trades"]]


# ---------------------------------------------------------------- week02 원본 그대로
def test_week02_원본은_고치지_않은_것이다():
    for name in ("strategy.py", "strategy_bb.py"):
        src = (WEEK02 / name).read_bytes()
        assert b"STRATEGY =" not in src and b"NAME =" not in src and b"TITLE =" not in src
    assert b"def target" not in (WEEK02 / "strategy.py").read_bytes()


def test_기본_공용_모듈은_week02_strategy_py_와_바이트가_같다():
    got = (loader.BUILTIN_DIR / "strategy.py").read_bytes()
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256((WEEK02 / "strategy.py").read_bytes()).hexdigest()
    assert sorted(p.name for p in loader.BUILTIN_DIR.glob("*.py")) == ["strategy.py"]


def test_볼린저_원본만_올려도_week02_와_같다(tmp_path):
    folder = _alone(tmp_path, "strategy_bb.py")
    loaded = load(folder, "strategy_bb.py")
    assert loaded.name == "strategy_bb"
    assert loaded.title == "1분봉을 넣으면 판정 봉을 쌓고, 판정 봉이 닫힐 때 Signal 을 돌려줍니다."
    assert (loaded.tick, loaded.tick_value) == (0.1, 1000)        # 기본 공용 모듈에서 import 한 TICK·TICK_VALUE
    assert loaded.strategy_cls.__name__ == "BBRSIReversion" and loaded.params_cls().bar_min == 5
    r = replay(loaded, "20261030", load_minutes(DATA), tmp_path / "out")
    assert _rows(r) == BB_GOLDEN and r["summary"]["net_pnl"] == 54000
    assert sorted(p.name for p in folder.iterdir()) == ["strategy_bb.py"]   # 폴더에 아무것도 생기지 않는다


def test_VWAP_원본만_올려도_week02_와_같다(tmp_path):
    folder = _alone(tmp_path, "strategy.py")
    loaded = load(folder, "strategy.py")
    assert loaded.name == "strategy" and loaded.strategy_cls.__name__ == "VWAPReversion"
    assert loaded.title == "1분봉을 넣으면 VWAP 을 갱신하고, 판정 봉이 닫힐 때 Signal 을 돌려줍니다."
    r = replay(loaded, "20261030", load_minutes(DATA), tmp_path / "out")
    assert [t["reason"] for t in r["trades"]] == ["익절", "익절", "익절", "손절", "손절"]
    assert r["summary"]["net_pnl"] == -21000


def test_원본만_둔_폴더의_목록에는_그_파일_하나만_선다(tmp_path):
    for name, title_start in (("strategy_bb.py", "1분봉을 넣으면 판정 봉"), ("strategy.py", "1분봉을 넣으면 VWAP")):
        strategies, modules = scan_all(_alone(tmp_path, name))
        assert modules == [] and [s.file for s in strategies] == [name]     # 기본 공용 모듈은 목록에 없다
        row = strategies[0]
        assert row.error is None and row.name == name.removesuffix(".py") and row.title.startswith(title_start)
        assert row.notes == [] and row.params["hold_min"] == 120


def test_볼린저_원본을_불러도_sys_modules_의_strategy_는_그대로다(tmp_path):
    folder = _alone(tmp_path, "strategy_bb.py")
    before = sys.modules.get("strategy")
    path_before = list(sys.path)
    load(folder, "strategy_bb.py")
    scan_all(folder)
    assert sys.modules.get("strategy") is before
    assert sys.path == path_before
    prefix = str(loader.BUILTIN_DIR.resolve())
    assert not [n for n, m in list(sys.modules.items()) if str(getattr(m, "__file__", "") or "").startswith(prefix)]


def test_다른_곳의_strategy_모듈과_backend_strategy_를_가리지도_쓰지도_않는다(tmp_path, monkeypatch):
    import backend.strategy as app_strategy

    other = SimpleNamespace(__name__="strategy", MARK="다른 곳")
    monkeypatch.setitem(sys.modules, "strategy", other)
    loaded = load(_alone(tmp_path, "strategy_bb.py"), "strategy_bb.py")
    assert sys.modules["strategy"] is other and sys.modules["backend.strategy"] is app_strategy
    s = loaded.new()
    assert type(s.day).__name__ == "DayState"           # 다른 곳의 strategy 가 아니라 기본 공용 모듈에서 왔다


# ---------------------------------------------------------------- 폴더의 strategy.py 가 먼저
def test_폴더의_strategy_py_가_기본_공용_모듈보다_먼저다(tmp_path):
    folder = _write(tmp_path / "s", "strategy.py", 'TICK = 0.1\nMARKER = "폴더"\n')
    _write(folder, "mine.py", "from dataclasses import dataclass\n\nfrom strategy import MARKER, TICK\n" + PARAMS_SRC + '''

class Mine:
    def __init__(self, p):
        self.p = p
        self.marker = MARKER

    def on_minute(self, m):
        return []
''')
    before = sys.modules.get("strategy")
    loaded = load(folder, "mine.py")
    assert loaded.new().marker == "폴더" and loaded.tick == 0.1 and loaded.tick_value == 1000
    strategies, modules = scan_all(folder)
    assert [s.file for s in strategies] == ["mine.py"] and modules == ["strategy.py"]
    assert sys.modules.get("strategy") is before


# ---------------------------------------------------------------- 전략 클래스 자동 찾기
def test_on_minute_클래스가_없으면_오류이고_목록에선_공용_모듈이다(tmp_path):
    folder = _write(tmp_path / "s", "util.py", "from dataclasses import dataclass\n" + PARAMS_SRC)
    with pytest.raises(LoadError, match=re.escape("`on_minute` 가 있는 전략 클래스가 없습니다")):
        load(folder, "util.py")
    strategies, modules = scan_all(folder)
    assert strategies == [] and modules == ["util.py"]


def test_on_minute_클래스가_여럿이면_오류이고_STRATEGY_로_고른다(tmp_path):
    body = "from dataclasses import dataclass\n" + PARAMS_SRC + '''

class A:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []


class B(A):
    pass
'''
    folder = _write(tmp_path / "s", "two.py", body)
    msg = "전략 클래스가 여러 개입니다 (A, B) — 파일 끝에 `STRATEGY = A` 처럼 하나를 고르세요"
    with pytest.raises(LoadError) as e:
        load(folder, "two.py")
    assert str(e.value) == msg
    row = scan_all(folder)[0][0]
    assert row.file == "two.py" and row.error == msg
    _write(folder, "two.py", body + "\n\nSTRATEGY = B\n")
    assert load(folder, "two.py").strategy_cls.__name__ == "B"


def test_다른_모듈에서_가져온_클래스는_세지_않는다(tmp_path):
    folder = _write(tmp_path / "s", "mine.py", "from dataclasses import dataclass\n\n"
                    "from strategy import VWAPReversion  # noqa: F401\n" + PARAMS_SRC + '''

class Mine:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []
''')
    assert load(folder, "mine.py").strategy_cls.__name__ == "Mine"


# ---------------------------------------------------------------- NAME·TITLE·Params·TICK
def test_NAME_은_파일_이름에서_TITLE_은_문서_문자열에서(tmp_path):
    src = '"""\n\n  모듈 제목 한 줄\n둘째 줄\n"""\nfrom dataclasses import dataclass\n' + PARAMS_SRC + '''

class Mine:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []
'''
    folder = _write(tmp_path / "s", "my.strat v2.py", src)
    got = load(folder, "my.strat v2.py")
    assert got.name == "my_strat_v2" and got.title == "모듈 제목 한 줄"
    assert (got.tick, got.tick_value) == (0.1, 1000)              # TICK·TICK_VALUE 가 없으면 미국달러선물 값
    _write(folder, "bare.py", "from dataclasses import dataclass\n" + PARAMS_SRC + '''

class Bare:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []
''')
    assert load(folder, "bare.py").title == "Bare"
    _write(folder, "named.py", "from dataclasses import dataclass\n" + PARAMS_SRC + '''

class Named:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []


NAME = "../x"
''')
    with pytest.raises(LoadError, match="NAME"):
        load(folder, "named.py")


def test_Params_는_init_첫_인자의_주석에서도_찾는다(tmp_path):
    folder = _write(tmp_path / "s", "cfg.py", '''from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"
    hold_min: int = 30


class Mine:
    def __init__(self, settings: Settings) -> None:
        self.p = settings

    def on_minute(self, m):
        return []
''')
    got = load(folder, "cfg.py")
    assert got.params_cls.__name__ == "Settings" and got.new().p.hold_min == 30


def test_Params_를_못_찾거나_칸이_모자라면_오류(tmp_path):
    folder = _write(tmp_path / "s", "nop.py", '''
class Mine:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []
''')
    with pytest.raises(LoadError, match=re.escape("Params(dataclass) 를 찾지 못했습니다")):
        load(folder, "nop.py")
    _write(folder, "short.py", "from dataclasses import dataclass\n" + PARAMS_SRC.replace("    hold_min: int = 30\n", "") + '''

class Mine:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m):
        return []
''')
    with pytest.raises(LoadError, match="Params 에 없는 이름: hold_min"):
        load(folder, "short.py")


def test_on_minute_과_p_는_여전히_필요하다(tmp_path):
    folder = _write(tmp_path / "s", "nop.py", "from dataclasses import dataclass\n" + PARAMS_SRC + '''

class Mine:
    def __init__(self, p):
        pass

    def on_minute(self, m):
        return []
''')
    with pytest.raises(LoadError, match="전략에 없는 이름: p"):
        load(folder, "nop.py")


# ---------------------------------------------------------------- 익절 목표
MINIMAL_SRC = "from dataclasses import dataclass\n" + PARAMS_SRC + '''

@dataclass
class Bar:
    date: str
    start: str
    end: str
    close: float


@dataclass
class Signal:
    bar: Bar
    side: object
    reason: str
    stop_ticks: object = None


class Plain:
    """09:30 봉에서 한 번 매수하는 시험 전략 — day·on_entry·on_exit·end_of_day·target 이 없다."""

    def __init__(self, p):
        self.p = p
        self.done = set()

    def on_minute(self, m):
        if not (self.p.session_start <= m.time < self.p.session_end):
            return []
        side = None
        if m.time == "093000" and m.date not in self.done:
            self.done.add(m.date)
            side = "buy"
        return [Signal(Bar(m.date, m.time, m.time, m.close), side, "시험", 200 if side else None)]
'''


def test_target_도_current_vwap_도_없으면_알림을_남기고_익절_없이_돈다(tmp_path):
    folder = _write(tmp_path / "s", "plain.py", MINIMAL_SRC)
    row = scan_all(folder)[0][0]
    assert row.error is None and row.notes == [NO_TARGET_NOTE]
    loaded = load(folder, "plain.py")
    assert target_of(loaded.new()) is None
    r = replay(loaded, "20261030", load_minutes(DATA), tmp_path / "out")
    assert [t["reason"] for t in r["trades"]] == ["시간 청산"]
    assert (r["trades"][0]["entry_time"], r["trades"][0]["exit_time"]) == ("093100", "100100")


def test_익절_목표는_target_다음_current_vwap():
    assert target_of(SimpleNamespace(target=1.5, current_vwap=2.5)) == 1.5
    assert target_of(SimpleNamespace(target=None, current_vwap=2.5)) is None     # target 이 있으면 그것(None 이어도)
    assert target_of(SimpleNamespace(current_vwap=2.5)) == 2.5
    assert target_of(SimpleNamespace()) is None


def test_target_이_있는_파일은_알림이_없다():
    rows = {s.file: s for s in scan_all(FIX / "strategies")[0]}
    assert rows["strategy_bb.py"].notes == [] and rows["strategy.py"].notes == []
    assert rows["no_target.py"].error is None and rows["no_target.py"].notes == [NO_TARGET_NOTE]


# ---------------------------------------------------------------- 고르는 메서드가 없는 전략
def _bare_strategy():
    p = SimpleNamespace(session_start="090000", session_end="153500", entry_start="090000", entry_end="150000",
                        flatten_at="153000", hold_min=120)
    sig = SimpleNamespace(bar=SimpleNamespace(date="20261030", start="090000", end="090000", close=1335.0),
                          side="buy", reason="시험", stop_ticks=10)

    class Bare:
        def __init__(self):
            self.p = p

        def on_minute(self, m):
            return [sig] if (m.date, m.time) == ("20261030", "090000") else []

    return Bare()


def test_day_on_entry_on_exit_end_of_day_가_없어도_실행기가_돈다(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    r = Runner(_bare_strategy(), j, PaperBroker(j, 0.1), 0.1, 1000)
    r.warmup([Minute("20261029", "150000", 1, 1, 1, 1, 1)])
    r.live_date = "20261030"
    r.on_minute_closed(Minute("20261030", "090000", 1335, 1335, 1335, 1335, 1))   # 날이 바뀜 → end_of_day 자리
    r.on_price("090100", 1335.0)                                                  # 진입 → on_entry 자리
    assert r.pos is not None and r.snapshot()["target"] is None
    r.on_price("090200", 1330.0)                                                  # 손절 → on_exit 자리
    assert [t["reason"] for t in r.trades] == ["손절"]
    assert r.snapshot()["stops"] == 1                                             # day 가 없으면 실행기 자신의 수


def test_day_가_없으면_앞선_손절_수를_이어받지_않고_시작한다(tmp_path):
    folder = _write(tmp_path / "s", "plain.py", MINIMAL_SRC)
    loaded = load(folder, "plain.py")
    fake = FakeApi()
    clock = {"now": at("092000")}
    out = tmp_path / "run"
    run = LiveRun("20261103_plain_paper", out, loaded, RunSpec(file="plain.py", mode="paper", sym=None),
                  api_module=fake, now=lambda: clock["now"], sleep=lambda s: None, stops_before=1)
    fake.chart = [bar("091800"), bar("091900")]
    run.prepare()
    texts = [x["text"] for x in Journal(out / "journal.jsonl").read() if x["kind"] == "event"]
    assert any("이어받지 않음" in t for t in texts)
    fake.chart = [bar("093000")]
    run.step(at("093104"))
    assert run.runner.pos is not None and run.state == "진행 중"
    fake.last = "1300.0"
    run.step(at("093105"))
    assert [t["reason"] for t in run.runner.trades] == ["손절"] and run.status()["stops"] == 1
    run.finish("중지")
    assert run.state == "끝"
