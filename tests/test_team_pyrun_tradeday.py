"""거래일 시계·Params 바꾸기·PAPER_FEE 시험."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

import pytest

from backend.sessions.hours import KST
from backend.team_pyrun.loader import LoadError, load
from backend.team_pyrun.runner import Minute
from backend.team_pyrun.tradeday import (
    RunClock,
    clock_text,
    is_overnight,
    plus_minutes,
    shift,
    shifted_params,
)


@dataclass(frozen=True)
class P:
    hold_min: int = 1
    session_start: str = "223000"
    session_end: str = "060000"
    entry_start: str = "223000"
    entry_end: str = "030000"
    flatten_at: str = "045500"


@dataclass(frozen=True)
class DayP:
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "090000"
    entry_end: str = "150000"
    flatten_at: str = "153000"


def test_shift():
    assert shift("065959") == "305959"
    assert shift("070000") == "070000"
    assert shift("253000") == "253000"
    assert shift("013000") == "253000"


def test_plus_minutes():
    assert plus_minutes("235800", 5) == "240300"
    assert plus_minutes("153000", 1) == "153100"


def test_is_overnight():
    assert is_overnight(P(), "060100")
    assert not is_overnight(DayP(), "153100")
    assert is_overnight(DayP(), "240300")


def test_run_clock_label():
    at = datetime(2026, 11, 10, 1, 30, tzinfo=KST)
    assert RunClock(False).label(at) == ("20261110", "013000")
    assert RunClock(True).label(at) == ("20261109", "253000")
    assert RunClock(True).label(datetime(2026, 11, 10, 7, 0, tzinfo=KST)) == ("20261110", "070000")
    assert RunClock(True).label(datetime(2026, 11, 10, 1, 30)) == ("20261109", "253000")   # 시간대 없는 값은 한국시간


def test_run_clock_bar():
    m = Minute("20261110", "013000", 1, 2, 0.5, 1.5, 3)
    got = RunClock(True).bar(m)
    assert (got.date, got.time) == ("20261109", "253000")
    assert got.open == 1 and got.volume == 3
    assert RunClock(False).bar(m) is m
    day = Minute("20261110", "093000", 1, 2, 0.5, 1.5, 3)
    assert RunClock(True).bar(day) == day


def test_run_clock_moment():
    assert RunClock(True).moment("20261109", "253000") == datetime(2026, 11, 10, 1, 30, tzinfo=KST)
    assert RunClock(True).moment("20261109", "223000") == datetime(2026, 11, 9, 22, 30, tzinfo=KST)


def test_shifted_params():
    cls = shifted_params(P)
    p = cls()
    assert p.flatten_at == "285500" and p.session_end == "300000" and p.entry_end == "270000"
    assert p.session_start == "223000"
    assert cls.__name__ == "P" and isinstance(p, P)
    assert dataclasses.asdict(p)["flatten_at"] == "285500"
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.hold_min = 3
    assert shifted_params(DayP) is DayP


def test_clock_text():
    assert clock_text("253000") == "01:30 (+1)"
    assert clock_text("090000") == "09:00"
    assert clock_text("153000") == "15:30"


_SRC = '''from dataclasses import dataclass
{extra}
TITLE = "t"
NAME = "fee"


@dataclass(frozen=True)
class Params:
    hold_min: int = 1
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"


class S:
    def __init__(self, p):
        self.p = p

    def on_minute(self, m): return []


STRATEGY = S
'''


def _load(tmp_path, extra):
    (tmp_path / "fee.py").write_text(_SRC.format(extra=extra), encoding="utf-8")
    return load(tmp_path, "fee.py")


def test_paper_fee(tmp_path):
    assert _load(tmp_path, "PAPER_FEE = 15.0").paper_fee == 15.0
    assert _load(tmp_path, "").paper_fee is None
    assert _load(tmp_path, "PAPER_FEE = 0").paper_fee == 0.0
    for bad in ("PAPER_FEE = -1", "PAPER_FEE = 'x'", "PAPER_FEE = float('nan')", "PAPER_FEE = float('inf')"):
        with pytest.raises(LoadError):
            _load(tmp_path, bad)


def test_params_for_and_new(tmp_path):
    loaded = _load(tmp_path, "")
    assert loaded.params_for(None) is loaded.params_cls
    assert loaded.new().p.flatten_at == "153000"
    assert loaded.new(overnight=False).p.flatten_at == "153000"
    # 낮 시각뿐이면 overnight 여도 그대로
    assert loaded.params_for(None, overnight=True) is loaded.params_cls
