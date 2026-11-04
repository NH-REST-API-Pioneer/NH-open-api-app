"""판단 부분만 골라 쓰기(`decision.py` + `loader._exec_module`) 시험.

실행기와 판단이 한 파일에 든 전략(week03 `ws_trader.py`)을 그대로 올려도, 앱에 없는 모듈(`nh_client`·`fee_test`·`ws_probe`)을
실행하지 않고 판단 부분(`Engine`·`LiveParams`·`TICK`…)만 불러 돌린다. 녹화 리플레이 결과는 떼어 낸 예제
(`strategy_leadlag.py`)와 같아야 한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.team_pyrun import replay
from backend.team_pyrun.loader import LoadError, load, scan_all
from tests.test_team_pyrun_leadlag import DOC_TABLE, EXAMPLES, RAW_1103, WS_TRADER

MISSING = "team_pyrun_no_such_module_xyz"


@pytest.fixture(scope="module")
def msgs():
    return replay.read_raw(RAW_1103)


@pytest.fixture
def ws_folder(tmp_path):
    folder = tmp_path / "strategies"
    folder.mkdir()
    shutil.copy(WS_TRADER, folder / "ws_trader.py")
    return folder


def write(folder: Path, name: str, src: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(src, encoding="utf-8")


def test_ws_trader_를_그대로_올리면_판단_부분만_불러_실시간_전략이_된다(ws_folder):
    got = load(ws_folder, "ws_trader.py")
    assert got.kind == "realtime" and got.strategy_cls.__name__ == "Engine"
    assert got.params_cls.__name__ == "LiveParams"
    assert got.tick == 0.0001 and got.tick_value == 2.5
    (row,) = scan_all(ws_folder)[0]
    assert row.error is None and row.kind == "realtime" and row.market == "overseas"
    note = next(n for n in row.notes if n.startswith("판단 부분만 불러옴"))
    for used in ("TICK", "TICK_USD", "FEE_TICKS", "LiveParams", "Engine"):
        assert used in note.split("안 쓴 것")[0]
    for unused in ("Trader", "Recorder", "main", "Backoff"):
        assert unused in note.split("안 쓴 것")[1]
    for mod in ("fee_test", "nh_client", "ws_probe"):
        assert mod in note.split("앱에 없는 모듈")[1]


@pytest.mark.parametrize("move", sorted(DOC_TABLE))
def test_ws_trader_그대로와_떼어_낸_예제의_리플레이가_같다(tmp_path, ws_folder, msgs, move):
    whole = load(ws_folder, "ws_trader.py")
    example = load(EXAMPLES, "strategy_leadlag.py")
    a = replay.replay_realtime(whole, msgs, tmp_path / "a", params={"move_won": move})["trades"]
    b = replay.replay_realtime(example, msgs, tmp_path / "b", params={"move_won": move})["trades"]
    keys = ("side", "entry", "exit", "entry_time", "exit_time", "reason", "gross_ticks", "net_usd")
    assert [{k: t.get(k) for k in keys} for t in a] == [{k: t.get(k) for k in keys} for t in b]
    assert len(a) == DOC_TABLE[move][0]


def test_버린_부분은_실행하지_않는다(tmp_path):
    marker = tmp_path / "ran.txt"
    write(tmp_path / "s", "mixed.py", f'''"""섞인 파일 — 판단과 실행기."""
from __future__ import annotations
from dataclasses import dataclass
import {MISSING}

TICK = 0.0001
TICK_USD = 2.5
open({str(marker)!r}, "w").write("top")


@dataclass(frozen=True)
class LiveParams:
    move: float = 0.8


class Engine:
    def __init__(self, p: LiveParams):
        self.p, self.pending, self.pos, self.stops = p, False, None, 0
    def on_krx(self, price, now, hhmmss): return None
    def on_quote(self, bid, ask, now, hhmmss): return None
    def on_timer(self, now, hhmmss): return None
    def filled_entry(self, side, price, now, hhmmss, ord_no=""): pass
    def filled_exit(self, price, now, reason): return {{}}


class Trader:
    def __init__(self):
        {MISSING}.connect()
    def on_dom(self): {MISSING}.order()


def main():
    Trader()


raise SystemExit("실행기까지 돌았다")
if __name__ == "__main__":
    main()
''')
    got = load(tmp_path / "s", "mixed.py")
    assert got.strategy_cls.__name__ == "Engine" and got.kind == "realtime"
    assert not marker.exists()                                  # 맨 위 open(...)·raise 는 버렸다


def test_전략_클래스가_없는_모듈을_직접_쓰면_어디를_나눌지_알린다(tmp_path):
    write(tmp_path / "s", "bad.py", f'''from dataclasses import dataclass
from {MISSING} import send_order

TICK = 0.0001


@dataclass(frozen=True)
class LiveParams:
    move: float = 0.8


class Engine:
    def __init__(self, p): self.p = p
    def on_krx(self, price, now, hhmmss):
        send_order()
    def on_quote(self, bid, ask, now, hhmmss): return None
''')
    with pytest.raises(LoadError, match=rf"Engine 이 send_order\({MISSING}\).*나눠 주세요"):
        load(tmp_path / "s", "bad.py")


def test_전략_클래스가_없고_모듈도_없으면_보통의_import_오류(tmp_path):
    write(tmp_path / "s", "lib.py", f"import {MISSING}\nX = 1\n")
    with pytest.raises(LoadError, match=rf"ModuleNotFoundError: No module named '{MISSING}'"):
        load(tmp_path / "s", "lib.py")


def test_전략_클래스가_둘이면_없는_모듈을_안_쓰는_쪽만_남긴다(tmp_path):
    write(tmp_path / "s", "two.py", f'''from dataclasses import dataclass
import {MISSING}

TICK = 0.0001


@dataclass(frozen=True)
class LiveParams:
    move: float = 0.8


class Engine:
    def __init__(self, p): self.p, self.pending, self.pos, self.stops = p, False, None, 0
    def on_krx(self, price, now, hhmmss): return None
    def on_quote(self, bid, ask, now, hhmmss): return None
    def on_timer(self, now, hhmmss): return None
    def filled_entry(self, side, price, now, hhmmss, ord_no=""): pass
    def filled_exit(self, price, now, reason): return {{}}


class LiveTrader:
    def on_quote(self, bid, ask, now, hhmmss):
        {MISSING}.order()
''')
    assert load(tmp_path / "s", "two.py").strategy_cls.__name__ == "Engine"


def test_따라가는_이름은_함수_상수_옆_모듈까지(tmp_path):
    folder = tmp_path / "s"
    write(folder, "helper.py", "def gap(a, b):\n    return a - b\n")
    write(folder, "minute.py", f'''"""돌파 — 1분봉 섞인 파일."""
from dataclasses import dataclass
from helper import gap
import {MISSING}

LIMIT = 3


def _ticks(x):
    return round(x / 0.1)


@dataclass(frozen=True)
class Params:
    hold_min: int = 30
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"


class Breakout:
    def __init__(self, p): self.p = p
    def on_minute(self, m):
        _ticks(gap(m.close, m.open)) > LIMIT
        return []


def run_live():
    {MISSING}.go()
''')
    got = load(folder, "minute.py")
    assert got.kind == "minute" and got.strategy_cls.__name__ == "Breakout" and got.title == "돌파"
    inst = got.new()

    class M:
        date, time, open, high, low, close, volume = "20261104", "093000", 1.0, 1.0, 1.0, 1.5, 1.0
    assert inst.on_minute(M()) == []


def test_줄_번호는_원본_그대로(ws_folder):
    got = load(ws_folder, "ws_trader.py")
    text = (ws_folder / "ws_trader.py").read_text(encoding="utf-8").splitlines()
    line = got.strategy_cls.on_krx.__code__.co_firstlineno
    assert text[line - 1].strip().startswith("def on_krx")


def test_주석이_실행되면_주석의_모듈도_따라가_막는다(tmp_path):
    # `from __future__ import annotations` 가 없으면 주석이 실행된다 — 없는 모듈의 이름을 주석에 쓰면 골라 쓸 수 없다
    src = f'''from dataclasses import dataclass
from {MISSING} import Client

TICK = 0.0001


@dataclass(frozen=True)
class LiveParams:
    move: float = 0.8


class Engine:
    def __init__(self, p: LiveParams, client: Client = None): self.p = p
    def on_krx(self, price, now, hhmmss): return None
    def on_quote(self, bid, ask, now, hhmmss): return None
'''
    write(tmp_path / "a", "eager.py", src)
    with pytest.raises(LoadError, match="Client"):
        load(tmp_path / "a", "eager.py")
    write(tmp_path / "b", "lazy.py", "from __future__ import annotations\n" + src.replace(
        "    def on_quote", "    def on_timer(self, now, hhmmss): return None\n"
        "    def filled_entry(self, side, price, now, hhmmss, ord_no=''): pass\n"
        "    def filled_exit(self, price, now, reason): return {}\n    def on_quote"))
    assert load(tmp_path / "b", "lazy.py").strategy_cls.__name__ == "Engine"


def test_모듈이_다_있으면_지금까지처럼_파일_전체를_실행한다(tmp_path):
    write(tmp_path / "s", "plain.py", '''from dataclasses import dataclass
import json

SIDE_EFFECT = json.dumps([1])


@dataclass(frozen=True)
class Params:
    hold_min: int = 30
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"


class S:
    def __init__(self, p): self.p = p
    def on_minute(self, m): return []
''')
    (row,) = scan_all(tmp_path / "s")[0]
    assert row.error is None and not any(n.startswith("판단 부분만") for n in row.notes)
