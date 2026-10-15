"""백엔드 기록 한 줄에 시각·수준·모듈 이름이 붙는지.

기록 설정은 프로세스 전체에 한 번 걸리고, 시험 도구도 루트 기록기에 처리기를 달아
같은 프로세스 안에서는 실제 모양을 볼 수 없습니다. 그래서 새 Python 을 띄워
데스크톱 앱과 같은 순서(백엔드를 불러온 뒤 uvicorn 설정을 만듦)로 기록을 남기고
그 출력을 읽습니다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import logging
import uvicorn
import backend.main

uvicorn.Config(backend.main.app, host="127.0.0.1", port=0, log_level="warning")
logging.getLogger("backend.sample").warning("warning-line")
logging.getLogger("backend.sample").info("info-line")
logging.getLogger("uvicorn.error").warning("uvicorn-line")
"""

STAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}"


def _run() -> list[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stderr.splitlines()


def test_경고에_시각_수준_모듈이름이_붙고_한_번만_찍힌다():
    lines = _run()

    ours = [line for line in lines if "warning-line" in line]
    assert len(ours) == 1, lines
    assert re.fullmatch(rf"{STAMP} WARNING backend\.sample warning-line", ours[0]), ours[0]

    # 수준은 그대로입니다 — 안내(INFO)는 보이지 않습니다.
    assert not any("info-line" in line for line in lines), lines

    # uvicorn 은 제 형식으로 한 번만 찍습니다. 루트로 올라와 두 번 찍히지 않습니다.
    theirs = [line for line in lines if "uvicorn-line" in line]
    assert len(theirs) == 1, lines
    assert not re.match(STAMP, theirs[0]), theirs[0]
