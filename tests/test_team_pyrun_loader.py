"""전략 폴더 불러오기 시험 — 폴더 안 파이썬 파일을 앱 모듈과 섞이지 않게 불러온다."""
import sys
from pathlib import Path

import pytest

from backend import config
from backend.team_pyrun.loader import LoadError, scan, load, strategies_dir

FOLDER = Path(__file__).parent / "fixtures/team_pyrun/strategies"


def test_전략이_있는_파일만_목록에_선다():
    got = {f.file: f for f in scan(FOLDER)}
    assert set(got) == {"broken.py", "no_target.py", "strategy.py", "strategy_bb.py"}
    assert got["strategy_bb.py"].name == "bb" and got["strategy_bb.py"].error is None
    assert got["strategy_bb.py"].params["bar_min"] == 5
    assert got["strategy.py"].name == "vwap"
    assert "SyntaxError" in got["broken.py"].error
    # target 이 없으면 오류가 아니라 알림(익절 없이 돈다)
    assert got["no_target.py"].error is None and got["no_target.py"].notes == ["target·current_vwap 이 없어 익절 없이 돕니다"]


def test_목록은_파일_이름순():
    assert [f.file for f in scan(FOLDER)] == sorted(f.file for f in scan(FOLDER))


def test_공용_모듈을_불러_쓰는_전략도_불러온다():
    bb = load(FOLDER, "strategy_bb.py")
    assert (bb.tick, bb.tick_value, bb.name) == (0.1, 1000, "bb")
    s = bb.new()
    assert s.p.bar_min == 5 and s.target is None


def test_불러온_뒤_sys_modules_에_strategy_가_남지_않는다():
    before = sys.modules.get("strategy")
    load(FOLDER, "strategy_bb.py")
    assert sys.modules.get("strategy") is before


def test_불러온_뒤_sys_path_와_폴더_모듈이_원래대로():
    path_before = list(sys.path)
    mods_before = set(sys.modules)
    load(FOLDER, "strategy_bb.py")
    scan(FOLDER)
    assert sys.path == path_before
    assert set(sys.modules) == mods_before


def test_두_번_불러도_서로_다른_모듈이다():
    a, b = load(FOLDER, "strategy_bb.py"), load(FOLDER, "strategy_bb.py")
    assert a.strategy_cls is not b.strategy_cls   # 파일이 바뀌어도 돌던 실행은 처음 것 그대로


def test_sha256_은_파일_바이트():
    import hashlib

    got = load(FOLDER, "strategy_bb.py")
    assert got.sha256 == hashlib.sha256((FOLDER / "strategy_bb.py").read_bytes()).hexdigest()


def test_없는_파일은_LoadError():
    with pytest.raises(LoadError):
        load(FOLDER, "nope.py")


def test_문법_오류와_약속_위반은_LoadError_메시지에_이유가_있다():
    with pytest.raises(LoadError, match="SyntaxError"):
        load(FOLDER, "broken.py")
    assert load(FOLDER, "no_target.py").name == "nt"      # target 이 없어도 불러온다(익절 없이)


def test_STRATEGY_도_on_minute_클래스도_없는_모듈은_LoadError():
    with pytest.raises(LoadError, match="on_minute 이 있는 전략 클래스가 없습니다"):
        load(FOLDER, "backtest_dummy.py")


def test_strategies_dir_은_없으면_만든다(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "home")
    d = strategies_dir()
    assert d == tmp_path / "home" / "strategies" and d.is_dir()


def test_해시한_바이트로_실행한다_파일이_바뀌면_해시도_코드도_따로(tmp_path):
    import shutil

    folder = tmp_path / "strategies"
    shutil.copytree(FOLDER, folder, ignore=shutil.ignore_patterns("__pycache__"))
    first = load(folder, "strategy_bb.py")
    path = folder / "strategy_bb.py"
    # 크기·수정 시각이 같아도(pyc 검사를 통과해도) 새 내용으로 실행돼야 한다
    old = path.read_bytes()
    new = old.replace(b'NAME = "bb"', b'NAME = "b2"')
    assert len(new) == len(old) and new != old
    st = path.stat()
    path.write_bytes(new)
    import os

    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    second = load(folder, "strategy_bb.py")
    assert second.sha256 != first.sha256
    assert (first.name, second.name) == ("bb", "b2")
    assert not (folder / "__pycache__").exists()   # 폴더에 pyc 를 쓰지 않는다
    import hashlib

    assert second.sha256 == hashlib.sha256(new).hexdigest()


def test_모듈_이름들을_훑는_동안_다른_스레드가_import_해도_오류가_없다():
    import threading
    import time
    import types

    stop = threading.Event()

    def churn():
        i = 0
        while not stop.is_set():
            sys.modules[f"_churn_{i % 50}"] = types.ModuleType("x")
            sys.modules.pop(f"_churn_{(i + 25) % 50}", None)
            i += 1
            time.sleep(0.0005)

    t = threading.Thread(target=churn)
    t.start()
    try:
        for _ in range(10):
            load(FOLDER, "strategy_bb.py")
    finally:
        stop.set()
        t.join()
        for k in [k for k in list(sys.modules) if k.startswith("_churn_")]:
            sys.modules.pop(k, None)


def test_future_import_없는_전략_파일은_주석이_문자열로_바뀌지_않는다(tmp_path):
    import dataclasses

    (tmp_path / "plain.py").write_text(
        '''from dataclasses import dataclass

TICK = 0.1
TICK_VALUE = 1000
TITLE = "t"
NAME = "plain"


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
        self.day = None
        self.target = None

    def on_minute(self, m): return []
    def end_of_day(self): return []
    def on_entry(self, *a): pass
    def on_exit(self, *a): pass


STRATEGY = S
''',
        encoding="utf-8",
    )
    got = load(tmp_path, "plain.py")
    assert dataclasses.fields(got.params_cls)[0].type is int   # 문자열 "int" 가 아니다


def test_NAME_에_경로_문자가_있으면_거절한다(tmp_path):
    src = (FOLDER / "strategy_bb.py").read_text(encoding="utf-8")
    for bad in ("../x", "a b", "", "한글"):
        (tmp_path / "strategy.py").write_text((FOLDER / "strategy.py").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / "strategy_bb.py").write_text(src.replace('NAME = "bb"', f'NAME = "{bad}"'), encoding="utf-8")
        with pytest.raises(LoadError, match="NAME"):
            load(tmp_path, "strategy_bb.py")
        row = next(f for f in scan(tmp_path) if f.file == "strategy_bb.py")
        assert row.error and "NAME" in row.error


# ---------------------------------------------------------------- 실행기 종류 · Params 채우기 · TICK_USD
ORB_LIKE = '''
"""시간 칸 없는 1분봉 전략 — ORB 처럼 hold_min·flatten_at 만 있다."""
from dataclasses import dataclass

TICK = 0.0001
TICK_VALUE = 2.5


@dataclass(frozen=True)
class Params:
    windows: tuple = (("서울", "090000"),)
    hold_min: int = 120
    flatten_at: str = "235000"


class Orb:
    def __init__(self, params: Params):
        self.p = params
        self.flat = params.flatten_at      # 생성자에서 Params 를 읽는 전략

    def on_minute(self, m):
        return []

    def exit_reason(self, clock, price, low, high, pos):
        return None
'''

ENGINE = '''
"""실시간 전략 — leadlag Engine 을 떼어 온 꼴."""
from dataclasses import dataclass

TICK = 0.0001
TICK_USD = 2.5


@dataclass
class LiveParams:
    flatten_at: str = "154000"


class Engine:
    def __init__(self, p: LiveParams):
        self.p = p

    def on_krx(self, price, now, hhmmss): return None
    def on_quote(self, bid, ask, now, hhmmss): return None
    def on_timer(self, now, hhmmss): return None
    def filled_entry(self, side, price, now, hhmmss, ord_no=""): pass
    def filled_exit(self, price, now, reason): return {}
'''


def _put(tmp_path, file, src):
    (tmp_path / file).write_text(src, encoding="utf-8")
    return tmp_path


def test_kind_1분봉(tmp_path):
    assert load(FOLDER, "strategy_bb.py").kind == "minute"
    assert load(_put(tmp_path, "orb.py", ORB_LIKE), "orb.py").kind == "minute"


def test_kind_실시간_LiveParams_와_TICK_USD(tmp_path):
    got = load(_put(tmp_path, "leadlag.py", ENGINE), "leadlag.py")
    assert got.kind == "realtime" and got.params_cls.__name__ == "LiveParams"
    assert (got.tick, got.tick_value, got.params_missing) == (0.0001, 2.5, ())
    assert got.new().p.flatten_at == "154000"
    row = next(f for f in scan(tmp_path) if f.file == "leadlag.py")
    assert row.error is None and row.params == {"flatten_at": "154000"} and row.notes == []


def test_kind_둘_다면_LoadError(tmp_path):
    src = ENGINE.replace("    def on_timer", "    def on_minute(self, m): return []\n    def on_timer")
    with pytest.raises(LoadError, match="on_minute.*on_krx"):
        load(_put(tmp_path, "both.py", src), "both.py")


def test_실시간_필수_이름이_빠지면_모두_적는다(tmp_path):
    src = ENGINE.replace("    def on_timer(self, now, hhmmss): return None\n", "").replace(
        '    def filled_exit(self, price, now, reason): return {}\n', "")
    with pytest.raises(LoadError, match="전략에 없는 이름: on_timer, filled_exit"):
        load(_put(tmp_path, "short.py", src), "short.py")


def test_TICK_VALUE_가_있으면_TICK_USD_보다_먼저(tmp_path):
    src = ENGINE.replace("TICK_USD = 2.5", "TICK_USD = 2.5\nTICK_VALUE = 3.0")
    assert load(_put(tmp_path, "e.py", src), "e.py").tick_value == 3.0


def test_시간_칸이_없으면_불러오되_빠진_칸을_적는다(tmp_path):
    got = load(_put(tmp_path, "orb.py", ORB_LIKE), "orb.py")
    assert got.params_missing == ("session_start", "session_end", "entry_start", "entry_end")
    s = got.new()                                   # 시장 없이 만들면 Params 그대로(칸을 지어내지 않음)
    assert not hasattr(s.p, "session_start")
    row = next(f for f in scan(tmp_path) if f.file == "orb.py")
    assert row.error is None and any("시장 시간표" in n and "session_start" in n for n in row.notes)
    assert all("익절 없이" not in n for n in row.notes)     # 청산 판단 함수가 있으면 익절 목표 알림은 없다


def test_해외_시장으로_시간_칸을_채운다(tmp_path):
    import dataclasses

    from backend.team_pyrun.markets import OVERSEAS

    got = load(_put(tmp_path, "orb.py", ORB_LIKE), "orb.py")
    s = got.new(OVERSEAS)
    p = s.p
    assert (p.session_start, p.entry_start, p.entry_end, p.flatten_at, p.session_end) == (
        "082500", "082500", "235000", "235000", "235500")
    assert isinstance(p, got.params_cls) and p.hold_min == 120 and s.flat == "235000"
    assert dataclasses.asdict(p)["session_start"] == "082500"      # 기록(asdict)에도 채운 값이 보인다
    with pytest.raises(dataclasses.FrozenInstanceError):            # frozen Params 는 채운 뒤에도 frozen
        p.hold_min = 1


def test_flatten_at_도_없으면_시장_기본값(tmp_path):
    from backend.team_pyrun.loader import fill_params
    from backend.team_pyrun.markets import DOMESTIC, OVERSEAS

    src = ORB_LIKE.replace('    flatten_at: str = "235000"\n', "").replace(
        "        self.flat = params.flatten_at      # 생성자에서 Params 를 읽는 전략\n", "")
    got = load(_put(tmp_path, "orb.py", src), "orb.py")
    assert got.params_missing[-1] == "flatten_at"
    ovs, dom = got.new(OVERSEAS).p, got.new(DOMESTIC).p
    assert (ovs.flatten_at, ovs.entry_end) == ("235000", "235000")
    assert (dom.session_start, dom.entry_end, dom.flatten_at, dom.session_end) == (
        "090000", "153000", "153000", "153100")
    assert fill_params(got.params_cls, (), OVERSEAS) is got.params_cls     # 빠진 칸이 없으면 그대로


def test_hold_min_은_시장이_채우지_않는다(tmp_path):
    src = ORB_LIKE.replace("    hold_min: int = 120\n", "")
    with pytest.raises(LoadError, match="Params 에 없는 이름: hold_min"):
        load(_put(tmp_path, "orb.py", src), "orb.py")
