"""저장해 둔 응답으로 띄운 앱과 실서버로 띄운 앱의 **상태 자리**.

둘이 한 폴더를 보면 재생으로 띄운 앱이 실서버에서 돌던 실행을 그대로 이어받아
세웁니다.
"""
from __future__ import annotations

from backend.config import HOME_DIR
from backend.strategy import journal as journal_lib
from backend.strategy import limits as limits_lib
from backend.strategy import runs as runs_lib
from backend.strategy import store as store_lib


def test_실서버면_원래_자리다():
    assert store_lib.run_state_dir({}) == HOME_DIR / "state"
    assert store_lib.run_state_dir({"NH_REPLAY": "0"}) == HOME_DIR / "state"


def test_재생이면_다른_자리다():
    assert store_lib.run_state_dir({"NH_REPLAY": "1"}) == HOME_DIR / "state-replay"


def test_재생_표시는_접속_자리와_같은_규칙으로_읽는다():
    """`NH_REPLAY` 를 읽는 규칙이 두 벌이 되면, 접속은 재생인데 상태는 실서버
    자리를 보는 어긋남이 생깁니다."""
    from backend.nh_api.session import replay_enabled

    for 값 in ("1", "true", "YES", "on"):
        assert replay_enabled({"NH_REPLAY": 값})
        assert store_lib.run_state_dir({"NH_REPLAY": 값}) == HOME_DIR / "state-replay"
    for 값 in ("", "0", "no", "아무거나"):
        assert not replay_enabled({"NH_REPLAY": 값})
        assert store_lib.run_state_dir({"NH_REPLAY": 값}) == HOME_DIR / "state"


def test_실행_기록_한도가_한_자리를_본다():
    """셋이 따로 정하면 하나만 옮겨지고 나머지가 남습니다."""
    자리 = store_lib.run_state_dir()

    assert runs_lib.RUNS_PATH.parent == 자리
    assert journal_lib.TRADES_PATH.parent == 자리
    assert limits_lib.LIMITS_PATH.parent == 자리


def test_전략_자체는_안_나눈다():
    """전략은 사용자가 적어 둔 설정이지 돌던 것이 아닙니다 — 재생으로 띄웠다고
    안 보이면 곤란합니다."""
    assert store_lib.STRATEGIES_PATH.parent == HOME_DIR / "state"
    assert store_lib.STRATEGIES_PATH.parent != store_lib.REPLAY_STATE_DIR


def test_기동_로그에_상태_자리를_남긴다(caplog, monkeypatch):
    """실행이 안 보일 때 「사라졌나」와 「다른 자리를 보고 있나」를 가려야 합니다.

    **기동이 바깥으로 하는 일을 전부 막아 두고 봅니다.** 이 시험이 보는 것은
    로그 한 줄뿐인데, 기동은 그 밖에도 종목 마스터를 받고(`_prepare_master`)
    장 시간표를 받습니다(`_prepare_sessions`). 둘 다 **사용자 설정 파일을 읽고
    NH선물로 나갑니다.**

    막지 않아도 지금은 안 나가지만, 그것은 지어 끼운 펌프가 한 번도 양보하지
    않아 두 태스크가 첫 걸음 전에 취소되는 **스케줄링 우연**입니다 — 누가 `await`
    하나를 더하는 순간 나갑니다. 이 컴퓨터에는 실계좌 키가 있으므로, 안 나가는
    것이 우연이 아니라 시험의 규칙이어야 합니다.
    """
    import asyncio

    from backend import main as main_lib

    class _펌프:
        def __init__(self, service):
            self.service = service

        async def start(self):
            return None

        async def stop(self):
            return None

    돈것 = []

    def _아무것도(이름):
        async def 하는것():
            돈것.append(이름)

        return 하는것

    monkeypatch.setattr(main_lib.strategy_pump, "RunPump", _펌프)
    monkeypatch.setattr(main_lib, "_prepare_master", _아무것도("master"))
    monkeypatch.setattr(main_lib, "_prepare_sessions", _아무것도("sessions"))
    # 하루 한 번 갱신도 마스터와 시간표를 받으러 나가는 길입니다.
    monkeypatch.setattr(main_lib, "_keep_fresh", _아무것도("fresh"))

    async def 띄워보기():
        async with main_lib.lifespan(main_lib.app):
            # **양보합니다.** 기동이 띄운 태스크가 첫 걸음을 떼는 데까지 갑니다 —
            # 취소되어 안 나간 것은 확인이 아닙니다.
            await asyncio.sleep(0)

    with caplog.at_level("INFO", logger="backend.main"):
        asyncio.run(띄워보기())

    assert 돈것 == ["master", "fresh", "sessions"], (
        "셋 다 돌되 **바꿔 낀 것**이 돌아야 합니다 — 안 돌았으면 이 시험은 "
        "바깥으로 안 나간 것을 확인한 것이 아니라 취소를 본 것뿐입니다."
    )

    남긴것 = [
        기록.getMessage()
        for 기록 in caplog.records
        if 기록.name == "backend.main" and "전략 상태 자리" in 기록.getMessage()
    ]

    assert len(남긴것) == 1, 남긴것
    assert str(store_lib.run_state_dir()) in 남긴것[0]
