"""판단 부분만 골라 쓰기(`decision.py` + `loader._exec_module`) 시험.

실행기와 판단이 한 파일에 든 전략(week03 `ws_trader.py`)을 그대로 올리면, 앱에 없는 모듈(`nh_client`·`fee_test`·`ws_probe`)을
쓰는 문장만 빼고 나머지를 전체 실행과 똑같이 실행한다. 녹화 리플레이 결과는 떼어 낸 예제(`strategy_leadlag.py`)와 같아야 하고,
빼는 바람에 조용히 다른 값(틱·Params·전략 클래스)으로 도는 일이 없어야 한다.
"""
from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from backend.team_pyrun import replay
from backend.team_pyrun.loader import LoadError, load, scan_all
from tests.test_team_pyrun_leadlag import DOC_TABLE, EXAMPLES, RAW_1103, WS_TRADER

MISSING = "team_pyrun_no_such_module_xyz"

ENGINE = '''
class Engine:
    def __init__(self, p): self.p, self.pending, self.pos, self.stops = p, False, None, 0
    def on_krx(self, price, now, hhmmss): return None
    def on_quote(self, bid, ask, now, hhmmss): return None
    def on_timer(self, now, hhmmss): return None
    def filled_entry(self, side, price, now, hhmmss, ord_no=""): pass
    def filled_exit(self, price, now, reason): return {}
'''
HEAD = f"from dataclasses import dataclass\nimport {MISSING}\n"
LIVE = "\n\n@dataclass(frozen=True)\nclass LiveParams:\n    move: float = 0.8\n"
MKU = "TICK = 0.0001\nTICK_USD = 2.5\n"


def engine_krx(body: str) -> str:
    """`on_krx` 가 `body` 를 돌려주는 Engine."""
    return ENGINE.replace("def on_krx(self, price, now, hhmmss): return None",
                          f"def on_krx(self, price, now, hhmmss): return {body}")


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


# ---------------------------------------------------------------- ws_trader.py 그대로
def test_ws_trader_를_그대로_올리면_판단_부분만_불러_실시간_전략이_된다(ws_folder):
    got = load(ws_folder, "ws_trader.py")
    assert got.kind == "realtime" and got.strategy_cls.__name__ == "Engine"
    assert got.params_cls.__name__ == "LiveParams"
    assert got.tick == 0.0001 and got.tick_value == 2.5
    (row,) = scan_all(ws_folder)[0]
    assert row.error is None and row.kind == "realtime" and row.market == "overseas"
    note = next(n for n in row.notes if n.startswith("실행기와 판단이 한 파일"))
    assert "판단 Engine 만 씀" in note
    skipped = note.split("실행하지 않는 부분:")[1]
    for unused in ("Trader", "main", "__main__"):
        assert unused in skipped
    for kept in ("Recorder", "Backoff", "LiveParams", "Engine"):     # 없는 모듈을 안 쓰는 것은 그대로 정의만 됨
        assert kept not in skipped
    for mod in ("fee_test", "nh_client", "ws_probe"):
        assert mod in note


@pytest.mark.parametrize("move", sorted(DOC_TABLE))
def test_ws_trader_그대로와_떼어_낸_예제의_리플레이가_같다(tmp_path, ws_folder, msgs, move):
    whole = load(ws_folder, "ws_trader.py")
    example = load(EXAMPLES, "strategy_leadlag.py")
    a = replay.replay_realtime(whole, msgs, tmp_path / "a", params={"move_won": move})["trades"]
    b = replay.replay_realtime(example, msgs, tmp_path / "b", params={"move_won": move})["trades"]
    keys = ("side", "entry", "exit", "entry_time", "exit_time", "reason", "gross_ticks", "net_usd")
    assert [{k: t.get(k) for k in keys} for t in a] == [{k: t.get(k) for k in keys} for t in b]
    assert len(a) == DOC_TABLE[move][0]


def test_줄_번호는_원본_그대로(ws_folder):
    got = load(ws_folder, "ws_trader.py")
    text = (ws_folder / "ws_trader.py").read_text(encoding="utf-8").splitlines()
    line = got.strategy_cls.on_krx.__code__.co_firstlineno
    assert text[line - 1].strip().startswith("def on_krx")


# ---------------------------------------------------------------- 무엇을 빼고 무엇을 두나
def test_없는_모듈을_쓰는_문장만_빼고_실행한다(tmp_path):
    marker = tmp_path / "ran.txt"
    kept = tmp_path / "kept.txt"
    write(tmp_path / "s", "mixed.py", f'''"""섞인 파일 — 판단과 실행기."""
from __future__ import annotations
from dataclasses import dataclass
import {MISSING}

TICK = 0.0001
TICK_USD = 2.5
open({str(kept)!r}, "w").write("top")
{MISSING}.log(open({str(marker)!r}, "w"))
CLIENT = {MISSING}.Client()


@dataclass(frozen=True)
class LiveParams:
    move: float = 0.8
{ENGINE}

class Trader:
    def __init__(self):
        {MISSING}.connect()


def main():
    Trader().run(CLIENT)


if __name__ == "__main__":
    main()
''')
    got = load(tmp_path / "s", "mixed.py")
    assert got.strategy_cls.__name__ == "Engine" and got.kind == "realtime"
    assert kept.exists() and not marker.exists()            # 없는 모듈을 쓰는 맨 위 문장은 실행 안 함
    (row,) = scan_all(tmp_path / "s")[0]
    skipped = row.notes[-1].split("실행하지 않는 부분:")[1]
    for name in ("CLIENT", "Trader", "main", "줄 "):
        assert name in skipped


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
    with pytest.raises(LoadError, match=rf"Engine 이 send_order\({MISSING}\).*옆 파일이면 같이 올리고.*나눠 주세요"):
        load(tmp_path / "s", "bad.py")


def test_전략_클래스가_없고_모듈도_없으면_보통의_import_오류(tmp_path):
    write(tmp_path / "s", "lib.py", f"import {MISSING}\nX = 1\n")
    with pytest.raises(LoadError, match=rf"ModuleNotFoundError: No module named '{MISSING}'"):
        load(tmp_path / "s", "lib.py")


def test_전략_클래스가_둘이면_없는_모듈을_안_쓰는_쪽만_남긴다(tmp_path):
    write(tmp_path / "s", "two.py", HEAD + MKU + LIVE + ENGINE + f'''

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
        return [_ticks(gap(m.close, m.open)) > LIMIT]


def run_live():
    {MISSING}.go()
''')
    got = load(folder, "minute.py")
    assert got.kind == "minute" and got.strategy_cls.__name__ == "Breakout" and got.title == "돌파"

    class M:
        date, time, open, high, low, close, volume = "20261104", "093000", 1.0, 1.0, 1.0, 1.5, 1.0
    assert got.new().on_minute(M()) == [True]


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
    assert row.error is None and not any(n.startswith("실행기와 판단") for n in row.notes)


# ---------------------------------------------------------------- 조용히 다른 값으로 돌지 않게 (검토에서 찾은 경우)
@pytest.mark.parametrize("tick_src", [
    "TICK, TICK_USD = 0.0001, 2.5\n",
    "MKU = True\nif MKU:\n    TICK = 0.0001\n    TICK_USD = 2.5\nelse:\n    TICK = 0.1\n    TICK_USD = 1000\n",
    "try:\n    from math import inf\nexcept ImportError:\n    inf = None\nTICK = 0.0001\nTICK_USD = 2.5\n",
])
def test_튜플_if_try_로_정한_TICK_도_그대로(tmp_path, tick_src):
    write(tmp_path / "s", "t.py", HEAD + tick_src + LIVE + ENGINE)
    got = load(tmp_path / "s", "t.py")
    assert got.tick == 0.0001 and got.tick_value == 2.5


def test_나중에_값을_바꾸는_문장도_그대로(tmp_path):
    write(tmp_path / "s", "t.py", HEAD + MKU + "FEE = {'x': 2.0}\nFEE['x'] = 9.0\n" + LIVE + engine_krx("FEE['x']"))
    assert load(tmp_path / "s", "t.py").new().on_krx(1, 0, "090000") == 9.0


def test_TICK_이_없는_모듈에서_오면_막는다(tmp_path):
    write(tmp_path / "s", "t.py", f"from dataclasses import dataclass\nfrom {MISSING} import TICK\nTICK_USD = 2.5\n"
          + LIVE + ENGINE)
    with pytest.raises(LoadError, match=rf"TICK ← import {MISSING}"):
        load(tmp_path / "s", "t.py")


def test_옆_파일의_별표_import_는_그대로_쓴다(tmp_path):
    folder = tmp_path / "s"
    write(folder, "common.py", "def ticks(x):\n    return x * 2\n")
    write(folder, "t.py", HEAD + "from common import *\n" + MKU + LIVE + engine_krx("ticks(price)"))
    assert load(folder, "t.py").new().on_krx(3, 0, "090000") == 6


def test_상속한_전략_클래스가_둘이면_전체_실행처럼_고르라고_한다(tmp_path):
    src = HEAD + '''TICK = 0.1


@dataclass(frozen=True)
class Params:
    hold_min: int = 30
    session_start: str = "090000"
    session_end: str = "153500"
    entry_start: str = "093000"
    entry_end: str = "150000"
    flatten_at: str = "153000"


class Base:
    LIMIT = 1
    def __init__(self, p): self.p = p
    def on_minute(self, m): return []


class Tuned(Base):
    LIMIT = 5
'''
    write(tmp_path / "s", "t.py", src)
    with pytest.raises(LoadError, match="여러 개"):
        load(tmp_path / "s", "t.py")
    write(tmp_path / "s", "t.py", src + "\nSTRATEGY = Tuned\n")
    assert load(tmp_path / "s", "t.py").new().LIMIT == 5


def test_주석의_import_는_있는_모듈이면_그대로(tmp_path):
    write(tmp_path / "s", "t.py", f'''from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from typing import ClassVar
import {MISSING}

TICK = 0.0001
TICK_USD = 2.5


@dataclass(frozen=True)
class Params:
    hold_min: int = 30


@dataclass(frozen=True)
class LiveParams:
    move: float = 0.8
    VERSION: ClassVar[int] = 3
''' + ENGINE.replace("def __init__(self, p):", "def __init__(self, p: LiveParams, book: OrderedDict | None = None):"))
    got = load(tmp_path / "s", "t.py")
    assert got.params_cls.__name__ == "LiveParams"
    assert [f.name for f in dataclasses.fields(got.params_cls)] == ["move"]


def test_주석이_실행되면_주석의_없는_모듈도_막는다(tmp_path):
    src = (f"from dataclasses import dataclass\nfrom {MISSING} import Client\n" + MKU + LIVE
           + ENGINE.replace("def __init__(self, p):", "def __init__(self, p: LiveParams, client: Client = None):"))
    write(tmp_path / "a", "eager.py", src)
    with pytest.raises(LoadError, match="Client"):
        load(tmp_path / "a", "eager.py")
    write(tmp_path / "b", "lazy.py", "from __future__ import annotations\n" + src)
    assert load(tmp_path / "b", "lazy.py").strategy_cls.__name__ == "Engine"


def test_파일에서_정의한_내장_이름이_먼저(tmp_path):
    write(tmp_path / "s", "t.py", HEAD + MKU + "def round(x):\n    return 'custom'\n" + LIVE + engine_krx("round(1.26)"))
    assert load(tmp_path / "s", "t.py").new().on_krx(1, 0, "090000") == "custom"


def test_내장_이름을_없는_모듈에서_가져와_쓰면_막는다(tmp_path):
    write(tmp_path / "s", "t.py", f"from dataclasses import dataclass\nfrom {MISSING} import max\n" + MKU + LIVE
          + engine_krx("max(1, 2)"))
    with pytest.raises(LoadError, match=rf"max\({MISSING}\)"):
        load(tmp_path / "s", "t.py")


def test_옆_파일을_빠뜨리면_같이_올리라고_안내한다(tmp_path):
    write(tmp_path / "s", "app.py", "from base_strategy_missing_zz import Base\n\n\nclass App(Base):\n"
          "    def on_minute(self, m): return []\n\n\nSTRATEGY = App\n")
    with pytest.raises(LoadError, match="옆 파일이면 같이 올리고"):
        load(tmp_path / "s", "app.py")


def test_지역_변수가_없는_모듈의_이름과_같아도_막지_않는다(tmp_path):
    write(tmp_path / "s", "t.py", f"from dataclasses import dataclass\nfrom {MISSING} import rows\n" + MKU + LIVE
          + engine_krx("[rows for rows in range(price)]"))
    assert load(tmp_path / "s", "t.py").new().on_krx(2, 0, "090000") == [0, 1]


def test_한_줄에_섞인_import_는_있는_모듈만_남긴다(tmp_path):
    write(tmp_path / "s", "t.py", f"from dataclasses import dataclass\nimport json, {MISSING}\n" + MKU + LIVE
          + engine_krx("json.dumps([price])"))
    assert load(tmp_path / "s", "t.py").new().on_krx(1, 0, "090000") == "[1]"
