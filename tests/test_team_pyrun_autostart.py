"""매일 자동 시작(`autostart.py`) 시험 — 가짜 실행 관리로 날짜·시각을 옮겨 가며 본다.

시작 거부 규칙과 주문은 `Registry.start` 의 일이라 여기선 가짜가 부른 횟수와 넘긴 spec 만 본다.
마지막 시험 하나는 진짜 `Registry` 로 자동 시작이 같은 거부 규칙을 지나는지 본다.
"""
import json
from pathlib import Path

import pytest

from backend.team_pyrun.autostart import MAX_ATTEMPTS, ScheduleError, Schedules, blocked_reason, fire_time
from backend.team_pyrun.live import StartRefused
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS
from tests.test_team_pyrun_live import STRATEGY_SRC, at
from tests.test_team_pyrun_live_overseas import MKU_SRC

TUE, WED, SAT = "20261103", "20261104", "20261107"


class FakeRun:
    def __init__(self, state="대기", ended_reason=None, spec=None):
        self.state, self.ended_reason, self.spec = state, ended_reason, spec


class FakeRegistry:
    def __init__(self, root: Path, strategies: Path):
        self.root, self.strategies = root, strategies
        self.calls, self.runs, self.refuse = [], {}, None
        self.n = 0

    def start(self, spec):
        self.calls.append(spec)
        if self.refuse:
            raise StartRefused(self.refuse)
        self.n += 1
        run_id = f"run{self.n}"
        self.runs[run_id] = FakeRun(spec=spec)
        return {"id": run_id, "state": "대기"}

    def get(self, run_id):
        return self.runs.get(run_id)


def setup(tmp_path, now="080000", date=TUE):
    folder = tmp_path / "strategies"
    folder.mkdir()
    (folder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    (folder / "mku.py").write_text(MKU_SRC, encoding="utf-8")
    reg = FakeRegistry(tmp_path / "pyruns", folder)
    clock = {"now": at(now, date)}
    sch = Schedules(tmp_path / "pyrun_schedules.json", reg, now=lambda: clock["now"])
    return sch, reg, clock


def move(clock, hhmmss, date):
    clock["now"] = at(hhmmss, date)


def test_시작_시각은_장_시작_5분_전():
    assert fire_time(OVERSEAS) == "082000"
    assert fire_time(DOMESTIC) == "085500"


def test_정한_시각이_되어야_시작하고_그날_한_번만(tmp_path):
    sch, reg, clock = setup(tmp_path, "080000")
    item = sch.create("mku.py", "orders")
    assert item["market"] == "overseas" and item["at"] == "082000"
    assert item["next_start"] == "2026-11-03T08:20:00"
    assert sch.tick() == []                                     # 08:00 — 아직
    move(clock, "082000", TUE)
    assert sch.tick() == ["run1"]
    spec = reg.calls[0]
    assert (spec.file, spec.mode, spec.sym, spec.signal_sym) == ("mku.py", "orders", None, None)  # 날마다 최근월물
    move(clock, "120000", TUE)
    assert sch.tick() == [] and len(reg.calls) == 1             # 그날은 한 번
    assert sch.list()[0]["next_start"] == "2026-11-04T08:20:00"


def test_다음_날_앞선_실행이_깨끗이_끝났으면_다시_시작(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "paper")
    move(clock, "082000", TUE)
    sch.tick()
    reg.runs["run1"].state, reg.runs["run1"].ended_reason = "끝", "실행 끝 시각"
    move(clock, "082000", WED)
    assert sch.tick() == ["run2"]


@pytest.mark.parametrize("state,reason", [
    ("끝", "실행 끝 시각 · 정리 안 함 — 확인 필요: 잔고 불일치"),
    ("끝", "재시작 · 확인 필요"),
    ("확인 필요", None),
    ("오류", "오류: 무언가"),
])
def test_앞선_실행이_확인_필요나_오류면_다음_날_시작하지_않고_막는다(tmp_path, state, reason):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "orders")
    move(clock, "082000", TUE)
    sch.tick()
    reg.runs["run1"].state, reg.runs["run1"].ended_reason = state, reason
    move(clock, "082000", WED)
    assert sch.tick() == [] and len(reg.calls) == 1
    s = sch.list()[0]
    assert s["blocked"] and s["next_start"] is None
    move(clock, "090000", WED)
    assert sch.tick() == []                                     # 막힌 채로
    resumed = sch.resume(s["id"])                               # 사람이 확인하고 다시 켬 — 시작 시각이 지났으니 오늘은 안 세움
    assert resumed["next_start"] == "2026-11-05T08:20:00"
    assert sch.tick() == [] and len(reg.calls) == 1
    move(clock, "082000", "20261105")
    assert sch.tick() == ["run2"]


def test_앞선_실행은_폴더의_run_json_으로도_본다(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "orders")
    move(clock, "082000", TUE)
    sch.tick()
    del reg.runs["run1"]                                        # 앱을 다시 켠 뒤 — 실행 객체는 없고 폴더만
    (reg.root / "run1").mkdir(parents=True)
    (reg.root / "run1" / "run.json").write_text(
        json.dumps({"state": "끝", "ended_reason": "재시작 · 확인 필요"}), encoding="utf-8")
    move(clock, "082000", WED)
    assert sch.tick() == [] and sch.list()[0]["blocked"]


def test_앞선_실행이_아직_돌면_그날은_기다린다(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "paper")
    move(clock, "082000", TUE)
    sch.tick()
    reg.runs["run1"].state = "진행 중"
    move(clock, "082000", WED)
    assert sch.tick() == []
    reg.runs["run1"].state = "끝"
    move(clock, "082100", WED)
    assert sch.tick() == ["run2"]


def test_거부되면_5분_뒤_다시_하루_3번까지(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "orders")
    move(clock, "082000", TUE)
    reg.refuse = "시작 잔고가 0 이 아닙니다"
    assert sch.tick() == []
    assert "시작 거부 1/3" in sch.list()[0]["last_result"]
    move(clock, "082200", TUE)
    sch.tick()
    assert len(reg.calls) == 1                                  # 5분 안 — 안 함
    for hhmm in ("082500", "083000", "083500", "090000"):
        move(clock, hhmm + "00", TUE)
        sch.tick()
    assert len(reg.calls) == MAX_ATTEMPTS
    assert sch.list()[0]["next_start"] == "2026-11-04T08:20:00"
    reg.refuse = None
    move(clock, "082000", WED)                                  # 다음 날은 새로
    assert sch.tick() == ["run1"]


def test_주말과_끝_시각_뒤에는_시작하지_않는다(tmp_path):
    sch, reg, clock = setup(tmp_path, "070000", SAT)
    sch.create("fake.py", "paper")
    move(clock, "090000", SAT)
    assert sch.tick() == []
    assert sch.list()[0]["next_start"] == "2026-11-09T08:55:00"   # 월요일
    move(clock, "153100", "20261109")                            # 국내 끝 시각
    assert sch.tick() == [] and reg.calls == []


def test_시작_시각이_지난_뒤_만들면_첫_시작은_다음_장_날(tmp_path):
    sch, reg, clock = setup(tmp_path, "120000")
    item = sch.create("mku.py", "paper")
    assert item["next_start"] == "2026-11-04T08:20:00"
    assert sch.tick() == [] and reg.calls == []


def test_지금_세운_실행과_이으면_그날은_다시_세우지_않고_다음_날_그_끝을_본다(tmp_path):
    sch, reg, clock = setup(tmp_path, "120000")
    from backend.team_pyrun.live import RunSpec
    reg.runs["manual"] = FakeRun("진행 중", spec=RunSpec("mku.py", "orders", None, None))
    reg.runs["other"] = FakeRun("진행 중", spec=RunSpec("fake.py", "orders", None, None))
    with pytest.raises(ScheduleError, match="다른 전략"):
        sch.create("mku.py", "orders", run_id="other")
    sch.create("mku.py", "orders", run_id="manual")
    assert sch.tick() == []
    reg.runs["manual"].state, reg.runs["manual"].ended_reason = "끝", "정리 안 함 — 확인 필요: x"
    move(clock, "082000", WED)
    assert sch.tick() == [] and sch.list()[0]["blocked"]


def test_만들기_거부(tmp_path):
    sch, reg, clock = setup(tmp_path)
    with pytest.raises(ScheduleError):
        sch.create("없음.py", "paper")
    with pytest.raises(ScheduleError):
        sch.create("../mku.py", "paper")
    with pytest.raises(ScheduleError):
        sch.create("mku.py", "live")
    with pytest.raises(ScheduleError):
        sch.create("mku.py", "paper", run_id="모름")
    sch.create("mku.py", "paper")
    with pytest.raises(ScheduleError, match="이미 있습니다"):
        sch.create("mku.py", "paper")
    sch.create("mku.py", "orders")
    (reg.strategies / "mku2.py").write_text(MKU_SRC, encoding="utf-8")
    with pytest.raises(ScheduleError, match="같은 시장"):
        sch.create("mku2.py", "orders")                         # 해외 모의 계좌 예약은 하나
    sch.create("fake.py", "orders")                             # 국내는 따로 하나 됨


def test_지우기와_저장(tmp_path):
    sch, reg, clock = setup(tmp_path)
    item = sch.create("mku.py", "paper")
    again = Schedules(sch.path, reg, now=lambda: clock["now"])  # 앱을 다시 켜도 남음
    assert [s["id"] for s in again.list()] == [item["id"]]
    again.delete(item["id"])
    assert sch.list() == []
    with pytest.raises(KeyError):
        sch.delete(item["id"])
    with pytest.raises(KeyError):
        sch.resume(item["id"])


def test_시작_도중_앱이_꺼졌으면_다시_켤_때_막고_같은_날_다시_세우지_않는다(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "orders")
    move(clock, "082000", TUE)
    crashed = {}

    def die(spec):
        crashed["spec"] = spec
        raise SystemExit("앱 꺼짐")                          # BaseException — _record 까지 가지 않는다

    reg.start = die
    with pytest.raises(SystemExit):
        sch.tick()
    reg2 = FakeRegistry(reg.root, reg.strategies)
    again = Schedules(sch.path, reg2, now=lambda: clock["now"])
    assert again.block_interrupted() == [sch.list()[0]["id"]]
    move(clock, "083000", TUE)
    assert again.tick() == [] and reg2.calls == []
    assert again.list()[0]["blocked"]


def test_막는_까닭():
    assert blocked_reason("끝", "실행 끝 시각") is None
    assert blocked_reason("끝", "중지") is None
    assert blocked_reason("끝", "시작 거부: 시작 잔고") is None
    assert blocked_reason("끝", "재시작") is None
    assert blocked_reason("끝", "재시작 · 확인 필요")
    assert blocked_reason("오류", "오류: x")


def test_진짜_실행_관리로도_같은_거부_규칙을_지난다(tmp_path):
    from tests.test_team_pyrun_registry import make_registry
    reg, fake, clock = make_registry(tmp_path, now="085000")
    sch = Schedules(tmp_path / "pyrun_schedules.json", reg, now=lambda: clock["now"])
    sch.create("fake.py", "paper")
    clock["now"] = at("085500")
    started = sch.tick()
    assert len(started) == 1 and reg.get(started[0]).spec.mode == "paper"
    assert reg.get(started[0]).spec.sym is None                 # 최근월물로 — 실행이 prepare 에서 찾음


# ---------------------------------------------------------------- 라우트
@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.team_pyrun import autostart as autostart_lib
    sch, reg, clock = setup(tmp_path, "080000")
    monkeypatch.setattr(autostart_lib, "_schedules", sch)
    return TestClient(app), sch, reg, clock


def test_라우트_만들기_목록_다시_켜기_지우기(api):
    c, sch, reg, clock = api
    r = c.post("/api/team/pyrun/schedules", json={"file": "mku.py", "mode": "orders"})
    assert r.status_code == 201 and r.json()["next_start"] == "2026-11-03T08:20:00"
    sid = r.json()["id"]
    assert [s["id"] for s in c.get("/api/team/pyrun/schedules").json()["schedules"]] == [sid]
    assert c.post("/api/team/pyrun/schedules", json={"file": "mku.py", "mode": "orders"}).status_code == 409
    assert c.post("/api/team/pyrun/schedules", json={"file": "mku.py", "mode": "orders", "sym": "X"}).status_code == 422
    assert c.post(f"/api/team/pyrun/schedules/{sid}/resume").status_code == 200
    assert c.post("/api/team/pyrun/schedules/없음/resume").status_code == 404
    assert c.delete(f"/api/team/pyrun/schedules/{sid}").status_code == 204
    assert c.delete(f"/api/team/pyrun/schedules/{sid}").status_code == 404


def test_라우트는_다른_사이트_요청을_받지_않는다(api):
    c, *_ = api
    r = c.post("/api/team/pyrun/schedules", json={"file": "mku.py", "mode": "paper"},
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403



def test_다시_켜기는_시작_시각_전이면_오늘_세운다(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "paper")
    move(clock, "082000", TUE)
    sch.tick()
    reg.runs["run1"].state, reg.runs["run1"].ended_reason = "끝", "재시작 · 확인 필요"
    move(clock, "082000", WED)
    assert sch.tick() == [] and sch.list()[0]["blocked"]
    move(clock, "080000", "20261105")                           # 다음 날 장 전에 확인하고 다시 켬
    assert sch.resume(sch.list()[0]["id"])["next_start"] == "2026-11-05T08:20:00"
    move(clock, "082000", "20261105")
    assert sch.tick() == ["run2"]


def test_시작_도중_꺼진_뒤_다시_켜도_같은_날_다시_세우지_않는다(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "orders")
    move(clock, "082000", TUE)

    def die(spec):
        raise SystemExit("앱 꺼짐")

    reg.start = die
    with pytest.raises(SystemExit):
        sch.tick()
    reg2 = FakeRegistry(reg.root, reg.strategies)
    again = Schedules(sch.path, reg2, now=lambda: clock["now"])
    sid = again.block_interrupted()[0]
    move(clock, "120000", TUE)
    again.resume(sid)
    assert again.tick() == [] and reg2.calls == []


def _prev_folder(reg, run_id, run_json=None, summary=None):
    folder = reg.root / run_id
    folder.mkdir(parents=True, exist_ok=True)
    if run_json is not None:
        (folder / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    if summary is not None:
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


@pytest.mark.parametrize("run_json,summary,live", [
    ({"state": "끝", "ended_reason": "실행 끝 시각"}, {"unresolved_order": {"ord_no": "7"}}, False),
    ({"state": "끝", "ended_reason": "실행 끝 시각"}, {"halted": "잔고 불일치"}, False),
    ({"state": "끝", "ended_reason": "중지 · 끝내기 처리 실패 (X)"}, None, False),
    (None, None, False),                                        # 앞선 실행 폴더가 없음 — 모르면 막는다
    ({"state": "진행 중"}, None, False),                          # 객체는 없는데 폴더는 돈다고 — 정리가 못 닫은 것
    ({"state": "끝"}, {"unresolved_order": {"ord_no": "7"}}, True),  # 도는 객체가 있어도 폴더 요약을 본다
])
def test_앞선_실행을_모르거나_결과_모름_주문이_남았으면_막는다(tmp_path, run_json, summary, live):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.create("mku.py", "orders")
    move(clock, "082000", TUE)
    sch.tick()
    if live:
        reg.runs["run1"].state, reg.runs["run1"].ended_reason = "끝", "실행 끝 시각"
    else:
        del reg.runs["run1"]
    if run_json is not None or summary is not None:
        _prev_folder(reg, "run1", run_json, summary)
    move(clock, "082000", WED)
    assert sch.tick() == [] and sch.list()[0]["blocked"]


def test_앱을_끄는_중엔_실행_관리가_새_실행을_받지_않는다(tmp_path):
    from tests.test_team_pyrun_registry import make_registry
    reg, fake, clock = make_registry(tmp_path, now="085500")
    reg.close_starts()
    from backend.team_pyrun.live import RunSpec
    with pytest.raises(StartRefused, match="끄는 중"):
        reg.start(RunSpec("fake.py", "paper", None, None))


def test_예약_루프를_멈춘_뒤엔_다시_띄우지_않는다(tmp_path):
    sch, reg, clock = setup(tmp_path, "081500")
    sch.stop_loop()
    sch.start_loop()
    assert sch._thread is None
