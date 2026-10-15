"""재생 모드의 화면 배치는 실서버와 다른 파일에 담깁니다.

**사용자 홈을 건드리지 않습니다** — 두 모드의 파일을 임시 폴더에 두고 봅니다.
"""
from __future__ import annotations

import json

import pytest

from backend import deposit_history, storage
from backend.config import HOME_DIR
from backend.storage import ORIGIN
from backend.strategy import store as strategy_store
from backend.ui import ui_store
from backend.ui.ui_store import UiStore

재생 = {"NH_REPLAY": "1"}
실서버 = {"NH_REPLAY": "0"}


def test_상태_폴더는_재생이면_따로다():
    assert storage.state_dir(실서버) == HOME_DIR / "state"
    assert storage.state_dir({}) == HOME_DIR / "state"
    assert storage.state_dir(재생) == HOME_DIR / "state-replay"


@pytest.mark.parametrize("env", [실서버, 재생])
def test_세_자리가_같은_폴더_규칙을_따른다(env):
    assert strategy_store.run_state_dir(env) == deposit_history.state_dir(env) == storage.state_dir(env)


def test_전략_목록은_두_모드가_함께_쓴다():
    assert strategy_store.STRATEGIES_PATH == HOME_DIR / "state" / "strategies.json"


def test_화면_배치_자리는_뜰_때의_모드를_따른다():
    """실서버 모드는 전과 같은 파일(`state/ui.json`), 재생은 `state-replay/ui.json`."""
    from backend.nh_api.session import replay_enabled

    폴더 = "state-replay" if replay_enabled() else "state"
    assert ui_store.UI_PATH == HOME_DIR / 폴더 / "ui.json"


def _두_자리(tmp_path, monkeypatch):
    """임시 홈 아래 두 모드의 화면 배치 파일."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(storage, "REPLAY_STATE_DIR", tmp_path / "state-replay")
    return storage.state_dir(실서버) / "ui.json", storage.state_dir(재생) / "ui.json"


def test_재생에서_바꾼_배치는_실서버_파일에_안_간다(tmp_path, monkeypatch):
    실서버파일, 재생파일 = _두_자리(tmp_path, monkeypatch)
    monkeypatch.delenv("NH_REPLAY", raising=False)
    UiStore(실서버파일).patch({"nh.trade.split": {"count": 1}})
    앞 = 실서버파일.read_bytes()

    monkeypatch.setenv("NH_REPLAY", "1")
    UiStore(재생파일).patch({"nh.trade.split": {"count": 2}})

    assert 실서버파일.read_bytes() == 앞
    assert json.loads(재생파일.read_text(encoding="utf-8"))["values"] == {"nh.trade.split": {"count": 2}}


def test_재생_폴더가_비었으면_실서버_값을_가져오지_않는다(tmp_path, monkeypatch):
    실서버파일, 재생파일 = _두_자리(tmp_path, monkeypatch)
    monkeypatch.delenv("NH_REPLAY", raising=False)
    UiStore(실서버파일).patch({"nh.home.watch": ["A7569000"]})

    monkeypatch.setenv("NH_REPLAY", "1")
    읽음 = UiStore(재생파일).read()

    assert (읽음["values"], 읽음["stored"], 읽음["status"]) == ({}, False, "missing")
    assert not 재생파일.exists()


def test_쓴_파일에_쓴_앱이_적힌다(tmp_path, monkeypatch):
    monkeypatch.setenv("NH_REPLAY", "1")
    자리 = tmp_path / "ui.json"
    UiStore(자리).patch({"nh.trade.split": {"count": 2}})

    assert json.loads(자리.read_text(encoding="utf-8"))[ORIGIN] == "replay"


def _남의_파일(자리, 앱="replay"):
    자리.write_text(
        json.dumps({"version": 1, ORIGIN: 앱, "values": {"nh.home.watch": ["A0169000"]}}),
        encoding="utf-8",
    )


def test_다른_앱이_쓴_파일은_읽을_때_안_쓴다(tmp_path, monkeypatch):
    monkeypatch.delenv("NH_REPLAY", raising=False)
    자리 = tmp_path / "ui.json"
    _남의_파일(자리)

    읽음 = UiStore(자리).read()

    assert (읽음["values"], 읽음["stored"], 읽음["otherApp"]) == ({}, False, "replay")


def test_다른_앱이_쓴_파일에_담으면_이_앱의_것으로_새로_쓴다(tmp_path, monkeypatch, caplog):
    """한도 파일과 같은 규칙 — 다른 앱의 배치는 이어받지 않습니다."""
    monkeypatch.delenv("NH_REPLAY", raising=False)
    자리 = tmp_path / "ui.json"
    _남의_파일(자리)

    with caplog.at_level("WARNING"):
        답 = UiStore(자리).patch({"nh.trade.split": {"count": 2}})

    담긴것 = json.loads(자리.read_text(encoding="utf-8"))
    assert 담긴것[ORIGIN] == "live"
    assert 담긴것["values"] == {"nh.trade.split": {"count": 2}}, "다른 앱의 관심종목은 안 이어받습니다."
    assert 답["otherApp"] is None
    assert "다른 앱" in caplog.text


def test_표지_없는_옛_파일은_이_앱의_것이다(tmp_path, monkeypatch):
    monkeypatch.setenv("NH_REPLAY", "1")
    자리 = tmp_path / "ui.json"
    자리.write_text(json.dumps({"version": 1, "values": {"nh.home.watch": ["A0169000"]}}), encoding="utf-8")

    읽음 = UiStore(자리).read()

    assert (읽음["values"], 읽음["otherApp"]) == ({"nh.home.watch": ["A0169000"]}, None)
