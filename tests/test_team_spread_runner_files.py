"""스프레드 실행기 파일 불러오기 시험 — LEGS·run(ctx) 약속."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend import config
from backend.team_pyrun.loader import LoadError
from backend.team_spread import runner_files as rf

OK = '''"""금리차 매매 — 두 다리"""
from helper import twice

LEGS = {"ho": "HO", "rb": "RB"}
MAX_QTY = 3


def run(ctx):
    return twice(1)
'''


def _put(tmp_path: Path, name: str, text: str) -> str:
    (tmp_path / name).write_text(text, "utf-8")
    return name


def test_정상_실행기_옆_파일_import(tmp_path):
    _put(tmp_path, "helper.py", "def twice(x):\n    return 2 * x\n")
    _put(tmp_path, "r.py", OK)
    r = rf.load_runner(tmp_path, "r.py")
    assert (r.file, r.name, r.title) == ("r.py", "r", "금리차 매매")
    assert r.legs == {"ho": "HO", "rb": "RB"} and r.max_qty == 3 and r.run(None) == 2
    assert len(r.sha256) == 64
    assert "helper" not in sys.modules


def test_TITLE_NAME_MAX_QTY_없으면_기본(tmp_path):
    _put(tmp_path, "r.py", 'LEGS = {"a": "X"}\ndef run(ctx): ...\n')
    r = rf.load_runner(tmp_path, "r.py")
    assert (r.name, r.title, r.max_qty) == ("r", "r", None)


@pytest.mark.parametrize("src,msg", [
    ("def run(ctx): ...\n", "LEGS"),
    ('LEGS = ["a"]\ndef run(ctx): ...\n', "LEGS 는 dict"),
    ("LEGS = {}\ndef run(ctx): ...\n", "LEGS 가 비었습니다"),
    ('LEGS = {"a-b": "X"}\ndef run(ctx): ...\n', "LEGS 이름"),
    ('LEGS = {"a": 3}\ndef run(ctx): ...\n', "LEGS 값"),
    ('LEGS = {"a": "X Y"}\ndef run(ctx): ...\n', "LEGS 값"),
    ('LEGS = {"a": "X/Y"}\ndef run(ctx): ...\n', "LEGS 값"),
    ('LEGS = {"a": "X"}\n', "run"),
    ('LEGS = {"a": "X"}\nrun = 3\n', "run 은 부를 수"),
    ('LEGS = {"a": "X"}\ndef run(): ...\n', "run 은 인자 하나"),
    ('LEGS = {"a": "X"}\ndef run(a, b): ...\n', "run 은 인자 하나"),
    ('LEGS = {"a": "X"}\ndef run(*args): ...\n', "run 은 인자 하나"),
    ('LEGS = {"a": "X"}\nMAX_QTY = 0\ndef run(c): ...\n', "MAX_QTY"),
    ('LEGS = {"a": "X"}\nMAX_QTY = True\ndef run(c): ...\n', "MAX_QTY"),
    ('LEGS = {"a": "X"}\nMAX_QTY = 1.5\ndef run(c): ...\n', "MAX_QTY"),
    ('LEGS = {"a": "X"}\nNAME = "a/b"\ndef run(c): ...\n', "NAME 은 영문"),
])
def test_약속_위반_문장(tmp_path, src, msg):
    _put(tmp_path, "r.py", src)
    with pytest.raises(LoadError) as e:
        rf.load_runner(tmp_path, "r.py")
    assert msg in str(e.value)


def test_앱에_없는_모듈은_골라_쓰지_않고_그대로_오류(tmp_path):
    _put(tmp_path, "r.py", 'import nh_client_nowhere\nLEGS = {"a": "X"}\ndef run(ctx): ...\n')
    with pytest.raises(LoadError) as e:
        rf.load_runner(tmp_path, "r.py")
    assert str(e.value).startswith("ModuleNotFoundError")


def test_scan_실행기와_옆_모듈을_나눈다(tmp_path):
    _put(tmp_path, "helper.py", "def twice(x):\n    return 2 * x\n")
    _put(tmp_path, "a.py", OK)
    _put(tmp_path, "bad.py", 'LEGS = {}\ndef run(ctx): ...\n')
    runners, modules = rf.scan(tmp_path)
    assert modules == ["helper.py"]
    assert [r.file for r in runners] == ["a.py", "bad.py"]
    a, bad = runners
    assert (a.name, a.title, a.legs, a.max_qty, a.error) == ("a", "금리차 매매", {"ho": "HO", "rb": "RB"}, 3, None)
    assert a.sha256 and bad.error and "비었" in bad.error and bad.legs == {}


def test_scan_불러오기_실패도_목록에(tmp_path):
    _put(tmp_path, "boom.py", "raise RuntimeError('x')\n")
    runners, modules = rf.scan(tmp_path)
    assert modules == [] and runners[0].error == "RuntimeError: x"


def test_spreads_dir_만든다(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME_DIR", tmp_path)
    d = rf.spreads_dir()
    assert d == tmp_path / "spreads" and d.is_dir()
