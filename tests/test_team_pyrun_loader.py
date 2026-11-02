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
    assert "target" in got["no_target.py"].error


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
    with pytest.raises(LoadError, match="target"):
        load(FOLDER, "no_target.py")


def test_STRATEGY_없는_모듈은_LoadError():
    with pytest.raises(LoadError, match="STRATEGY"):
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
