"""매일 자동 시작 — 종목 칸(품목 뿌리·종목 코드) · `session_start` 기준 시작 시각 · 거래일(`autostart.py`, 설계 4.6).

가짜 실행 관리(`resolve_product` 는 표기 → `Leg` 사전 — 마스터·서버 없음)와 가짜 시계로 본다.
시작 거부 규칙과 주문은 `Registry.start` 의 일이라 여기선 가짜가 부른 횟수와 넘긴 spec 만 본다.
"""
import json
import shutil
from pathlib import Path

import pytest

from backend.team_pyrun.autostart import ScheduleError, Schedules
from backend.team_pyrun.live import RunSpec, StartRefused
from backend.team_spread.legs import Leg
from tests.test_team_pyrun_autostart import FakeRegistry, FakeRun, move
from tests.test_team_pyrun_live import STRATEGY_SRC, at
from tests.test_team_pyrun_live_any import HO, HO_SRC, KOSPI, KOSPI_SRC, MKU_LEG
from tests.test_team_pyrun_live_overseas import MKU_SRC

FRI, SAT, MON, TUE, WED = "20261106", "20261107", "20261109", "20261110", "20261111"
A75 = Leg("main", "A756B000", "A75", "domestic", "KRX", "KRW", 0.1, 1000.0, "20261116")
RT_FILE = Path(__file__).parent / "fixtures" / "team_pyrun" / "realtime" / "strategy_rt_fake.py"

#: 새벽 01:00 에 여는 HO 전략 — 자정을 넘는 실행(거래일 시계 `"250000"`), 04:55 정리 → 실행 끝 05:00(`"290000"`)
DAWN_SRC = (HO_SRC.replace('NAME = "fakeho"', 'NAME = "fakedawn"')
            .replace('session_start: str = "090000"', 'session_start: str = "010000"')
            .replace('session_end: str = "233500"', 'session_end: str = "050000"')
            .replace('entry_start: str = "090000"', 'entry_start: str = "010000"')
            .replace('entry_end: str = "230000"', 'entry_end: str = "040000"')
            .replace('flatten_at: str = "233000"', 'flatten_at: str = "045500"'))
#: 09:30 에 여는 국내 미국달러선물 전략
LATE_SRC = STRATEGY_SRC.replace('session_start: str = "090000"', 'session_start: str = "093000"')
#: 국내 틱인데 04:55 에 정리하는 전략 — 자정을 넘는 계획
DNIGHT_SRC = STRATEGY_SRC.replace('flatten_at: str = "153000"', 'flatten_at: str = "045500"')
#: 장 시간 칸이 빠진(MKU 시험 전략) 채 틱가치만 HO 값인 전략
HOBARE_SRC = MKU_SRC.replace("TICK_VALUE = 2.5", "TICK_VALUE = 4.2")
assert '"010000"' in DAWN_SRC and '"045500"' in DAWN_SRC and '"093000"' in LATE_SRC
assert '"045500"' in DNIGHT_SRC and "4.2" in HOBARE_SRC

FILES = {"fake.py": STRATEGY_SRC, "late.py": LATE_SRC, "mku.py": MKU_SRC, "mku2.py": MKU_SRC,
         "ho.py": HO_SRC, "dawn.py": DAWN_SRC, "kospi.py": KOSPI_SRC, "dnight.py": DNIGHT_SRC,
         "hobare.py": HOBARE_SRC}


class FakeAnyRegistry(FakeRegistry):
    """`resolve_product` 를 가진 가짜 실행 관리 — 표기 → `Leg`, 모르는 표기는 `StartRefused`. 부른 표기를 적는다."""

    def __init__(self, root: Path, strategies: Path):
        super().__init__(root, strategies)
        self.legs = {"HO": HO, "HOZ26": HO, "MKU": MKU_LEG, "A75": A75, "A01": KOSPI}
        self.resolved: list[str] = []

    def resolve_product(self, spec):
        self.resolved.append(spec)
        if spec not in self.legs:
            raise StartRefused(f"마스터에 없는 종목입니다: {spec}")
        return self.legs[spec]


def setup(tmp_path, now="080000", date=TUE):
    folder = tmp_path / "strategies"
    folder.mkdir()
    for name, src in FILES.items():
        (folder / name).write_text(src, encoding="utf-8")
    shutil.copy(RT_FILE, folder / "rt.py")
    reg = FakeAnyRegistry(tmp_path / "pyruns", folder)
    clock = {"now": at(now, date)}
    sch = Schedules(tmp_path / "pyrun_schedules.json", reg, now=lambda: clock["now"])
    return sch, reg, clock


# ---------------------------------------------------------------- 거래일 (자정을 넘는 실행)
def test_새벽_예약은_금요일_거래일엔_토요일_00시55분에_서고_일요일_거래일엔_안_선다(tmp_path):
    sch, reg, clock = setup(tmp_path, "120000", FRI)
    item = sch.create("dawn.py", "paper", sym="HO")
    assert (item["sym"], item["product"], item["market"]) == ("HO", "HO", "overseas")
    assert (item["at"], item["overnight"], item["end"]) == ("245500", True, "290000")
    assert item["next_start"] == "2026-11-07T00:55:00"                 # 금요일 거래일 = 토요일 새벽
    move(clock, "005400", SAT)
    assert sch.tick() == []
    move(clock, "005500", SAT)
    assert sch.tick() == ["run1"]
    spec = reg.calls[0]
    assert (spec.file, spec.mode, spec.sym, spec.signal_sym) == ("dawn.py", "paper", "HO", None)  # 뿌리 그대로 — 날마다 최근월물
    for hhmmss in ("010000", "020000"):                                 # 같은 거래일(금요일) — 다시 안 부름
        move(clock, hhmmss, SAT)
        assert sch.tick() == []
    again = Schedules(sch.path, reg, now=lambda: clock["now"])          # 앱을 다시 켜도
    assert again.tick() == [] and len(reg.calls) == 1
    s = sch.list()[0]
    assert s["last_day"] == FRI
    assert s["next_start"] == "2026-11-10T00:55:00"                    # 토·일 거래일 없음 → 월요일 거래일 = 화요일 새벽
    reg.runs["run1"].state, reg.runs["run1"].ended_reason = "끝", "실행 끝 시각"
    move(clock, "005500", MON)                                          # 월요일 새벽 = 일요일 거래일
    assert sch.tick() == [] and len(reg.calls) == 1
    move(clock, "120000", MON)
    assert sch.tick() == []
    move(clock, "005500", TUE)                                          # 월요일 거래일
    assert sch.tick() == ["run2"]
    assert sch.list()[0]["last_day"] == MON


def test_만든_순간_시작_시각이_지났으면_그_거래일은_건너뛴다(tmp_path):
    sch, reg, clock = setup(tmp_path, "013000", SAT)                   # 금요일 거래일 01:30 (+1)
    item = sch.create("dawn.py", "paper", sym="HO")
    assert item["skip_day"] == FRI and item["next_start"] == "2026-11-10T00:55:00"
    assert sch.tick() == [] and reg.calls == []


def test_다시_켜기도_거래일로(tmp_path):
    sch, reg, clock = setup(tmp_path, "120000", FRI)
    sch.create("dawn.py", "orders", sym="HO")
    move(clock, "005500", SAT)
    sch.tick()
    reg.runs["run1"].state, reg.runs["run1"].ended_reason = "끝", "재시작 · 확인 필요"
    move(clock, "005500", TUE)                                          # 월요일 거래일 첫 시도 — 앞선 실행을 보고 막음
    assert sch.tick() == [] and sch.list()[0]["blocked"]
    move(clock, "013000", TUE)                                          # 월요일 거래일 시작 시각 뒤에 다시 켬
    resumed = sch.resume(sch.list()[0]["id"])
    assert resumed["skip_day"] == MON and resumed["next_start"] == "2026-11-11T00:55:00"
    assert sch.tick() == [] and len(reg.calls) == 1
    move(clock, "005500", WED)
    assert sch.tick() == ["run2"]


def test_지금_세운_실행과_이으면_그_실행의_종목_칸과_거래일(tmp_path):
    sch, reg, clock = setup(tmp_path, "023000", SAT)                   # 토요일 새벽(금요일 거래일)에 손으로 세운 실행
    reg.runs["manual"] = FakeRun("진행 중", spec=RunSpec("dawn.py", "paper", "HO"))
    with pytest.raises(ScheduleError, match="다른 종목"):
        sch.create("dawn.py", "paper", run_id="manual", sym="HOZ26")
    item = sch.create("dawn.py", "paper", run_id="manual")
    assert item["sym"] == "HO" and item["last_day"] == FRI and item["last_run_id"] == "manual"
    assert sch.tick() == [] and reg.calls == []
    assert item["next_start"] == "2026-11-10T00:55:00"


# ---------------------------------------------------------------- 시작 시각 = session_start 5분 전
def test_국내_전략은_session_start_5분_전(tmp_path):
    sch, reg, clock = setup(tmp_path, "080000", TUE)
    item = sch.create("late.py", "paper")
    assert (item["at"], item["overnight"], item["end"]) == ("092500", False, "153100")
    assert (item["sym"], item["product"], item["market"]) == (None, "A75", "domestic")
    assert item["next_start"] == "2026-11-10T09:25:00"
    move(clock, "092400", TUE)
    assert sch.tick() == []
    move(clock, "092500", TUE)
    assert sch.tick() == ["run1"]
    assert reg.calls[0].sym is None and reg.resolved == []
    assert sch.create("fake.py", "orders")["at"] == "085500"           # week02(09:00) 는 지금과 같음


def test_MKU_전략은_채운_08시25분의_5분_전(tmp_path):
    sch, reg, clock = setup(tmp_path, "080000", TUE)
    item = sch.create("mku.py", "paper")
    assert (item["at"], item["overnight"], item["end"]) == ("082000", False, "235500")
    assert (item["market"], item["product"]) == ("overseas", "MKU")
    code = sch.create("mku.py", "orders", sym="MKUX26")                # 정확한 MKU 코드 — 지금 길(종목 찾기 없음)
    assert (code["at"], code["product"], code["sym"]) == ("082000", "MKU", "MKUX26") and reg.resolved == []
    root = sch.create("mku2.py", "paper", sym="MKU")                   # 뿌리 — 종목 찾기로
    assert (root["at"], root["product"], root["sym"]) == ("082000", "MKU", "MKU") and reg.resolved == ["MKU"]


def test_실시간_전략은_시각이_지금대로이고_종목_칸은_MKU_코드만(tmp_path):
    sch, reg, clock = setup(tmp_path, "080000", TUE)
    item = sch.create("rt.py", "paper")
    assert (item["at"], item["overnight"], item["end"], item["product"]) == ("082000", False, "235500", "MKU")
    with pytest.raises(ScheduleError, match="실시간"):
        sch.create("rt.py", "orders", sym="MKU")                        # 실시간 실행은 품목 뿌리를 받지 않는다
    assert sch.create("rt.py", "orders", sym="MKUX26")["sym"] == "MKUX26"
    assert reg.resolved == []


# ---------------------------------------------------------------- 옛 예약 파일
def _old(sid, file, mode, market, at_):
    return {"id": sid, "file": file, "mode": mode, "market": market, "at": at_,
            "created_at": "2026-11-02T10:00:00", "blocked": None, "last_day": None, "attempts": 0,
            "last_run_id": None, "skip_day": None, "last_result": None, "next_try": None}


OLD = {"schedules": [_old("fake_paper", "fake.py", "paper", "domestic", "085500"),
                     _old("mku_orders", "mku.py", "orders", "overseas", "082000")]}
NEW_KEYS = {"sym", "product", "overnight", "end"}


def test_옛_예약_파일은_칸이_없어도_지금_시각과_끝으로(tmp_path):
    sch, reg, clock = setup(tmp_path, "080000", TUE)
    sch.path.write_text(json.dumps(OLD, ensure_ascii=False), encoding="utf-8")
    before = sch.path.read_text(encoding="utf-8")
    got = {s["id"]: s for s in sch.list()}
    assert got["fake_paper"]["at"] == "085500" and got["fake_paper"]["next_start"] == "2026-11-10T08:55:00"
    assert got["mku_orders"]["at"] == "082000" and got["mku_orders"]["next_start"] == "2026-11-10T08:20:00"
    move(clock, "153100", TUE)                                          # 국내 끝 15:31 뒤 — 내일. 해외는 23:55 까지 오늘
    got = {s["id"]: s for s in sch.list()}
    assert got["fake_paper"]["next_start"] == "2026-11-11T08:55:00"
    assert got["mku_orders"]["next_start"] == "2026-11-10T08:20:00"
    move(clock, "235500", TUE)
    assert sch.list()[1]["next_start"] == "2026-11-11T08:20:00"
    assert sch.path.read_text(encoding="utf-8") == before               # 읽기만으로 고쳐 쓰지 않음


def test_옛_예약은_달력_날짜로_시작하고_칸을_더하지_않는다(tmp_path):
    sch, reg, clock = setup(tmp_path, "080000", SAT)
    sch.path.write_text(json.dumps(OLD, ensure_ascii=False), encoding="utf-8")
    move(clock, "090000", SAT)
    assert sch.tick() == []                                             # 토요일(달력)
    move(clock, "082000", TUE)
    assert sch.tick() == ["run1"]
    move(clock, "085500", TUE)
    assert sch.tick() == ["run2"]
    assert [(c.file, c.mode, c.sym) for c in reg.calls] == [("mku.py", "orders", None), ("fake.py", "paper", None)]
    raw = json.loads(sch.path.read_text(encoding="utf-8"))["schedules"]
    assert [s["last_day"] for s in raw] == [TUE, TUE]
    assert all(not (NEW_KEYS & set(s)) for s in raw) and reg.resolved == []


# ---------------------------------------------------------------- 만들기 거부 · 겹침
def test_같은_품목의_모의_계좌_예약은_하나(tmp_path):
    sch, reg, clock = setup(tmp_path)
    sch.create("dawn.py", "orders", sym="HO")
    with pytest.raises(ScheduleError, match="같은 품목"):
        sch.create("ho.py", "orders", sym="HOZ26")                     # 같은 품목 HO 의 종목 코드
    sch.create("ho.py", "paper", sym="HO")                              # 종이는 겹쳐도 됨
    sch.create("mku.py", "orders")                                      # 빈칸 해외 = MKU 최근월물 — HO 와는 따로
    with pytest.raises(ScheduleError, match="같은 품목"):
        sch.create("mku2.py", "orders", sym="MKU")                      # 빈칸 해외 예약과 같은 최근월물
    with pytest.raises(ScheduleError, match="같은 시장"):
        sch.create("mku2.py", "orders")                                 # 빈칸끼리는 지금 규칙·글 그대로
    sch.create("kospi.py", "orders", sym="A01")                         # 국내 다른 품목
    sch.create("late.py", "orders", sym="A75")                          # 국내 미국달러선물 뿌리
    with pytest.raises(ScheduleError, match="같은 품목"):
        sch.create("fake.py", "orders")                                 # 빈칸 국내 = A75 최근월물
    assert sorted(s["id"] for s in sch.list()) == ["dawn_orders", "ho_paper", "kospi_orders", "late_orders",
                                                   "mku_orders"]


def test_종목을_못_찾거나_틱이_다르면_만들지_않는다(tmp_path):
    sch, reg, clock = setup(tmp_path)
    with pytest.raises(ScheduleError, match="마스터에 없는 종목"):
        sch.create("ho.py", "paper", sym="ZZ")
    with pytest.raises(ScheduleError, match="틱·틱가치") as e:
        sch.create("mku.py", "paper", sym="HO")                         # MKU 틱가치(2.5) 전략을 HO(4.2)에
    assert "4.2" in str(e.value) and "2.5" in str(e.value)
    with pytest.raises(ScheduleError, match="시장"):
        sch.create("fake.py", "paper", sym="MKUX26")                    # 국내 틱 전략에 MKU 코드 — 지금 시장 가드
    assert sch.list() == []


def test_국내_종목에_자정을_넘는_전략은_만들_때_거부(tmp_path):
    sch, reg, clock = setup(tmp_path)
    with pytest.raises(ScheduleError, match="국내는 주간"):
        sch.create("dnight.py", "paper")                                # 실행 준비와 같은 글 (`live.plan_refusal`)
    assert sch.list() == []


def test_MKU_아닌_품목에_장_시간_칸이_빠진_전략은_만들_때_거부(tmp_path):
    sch, reg, clock = setup(tmp_path)
    with pytest.raises(ScheduleError, match="Params 에 장 시간 칸이 없습니다") as e:
        sch.create("hobare.py", "paper", sym="HO")                     # 빠진 칸을 채우는 것은 MKU 만
    assert "session_start" in str(e.value) and sch.list() == []


def test_해외_실행_끝이_다음_날_07시를_넘는_전략은_만들_때_거부(tmp_path):
    sch, reg, clock = setup(tmp_path)
    late = DAWN_SRC.replace('session_end: str = "050000"', 'session_end: str = "065900"')
    (reg.strategies / "past7.py").write_text(late.replace('flatten_at: str = "045500"', 'flatten_at: str = "065800"'),
                                             encoding="utf-8")
    with pytest.raises(ScheduleError, match=r"실행 끝\(07:03 \(\+1\)\)이 다음 날 07:00 을 넘습니다 — flatten_at 을 당기세요"):
        sch.create("past7.py", "paper", sym="HO")                        # 실행 준비와 같은 글 (`live.plan_refusal`)
    assert sch.list() == []
    (reg.strategies / "edge7.py").write_text(late.replace('flatten_at: str = "045500"', 'flatten_at: str = "065500"'),
                                             encoding="utf-8")
    assert sch.create("edge7.py", "paper", sym="HO")["end"] == "310000"  # 07:00 정각은 넘지 않음


# ---------------------------------------------------------------- 라우트
@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.team_pyrun import autostart as autostart_lib
    sch, reg, clock = setup(tmp_path, "120000", FRI)
    monkeypatch.setattr(autostart_lib, "_schedules", sch)
    return TestClient(app), sch, reg, clock


def test_라우트_종목_칸(api):
    c, sch, reg, clock = api
    r = c.post("/api/team/pyrun/schedules", json={"file": "dawn.py", "mode": "paper", "sym": "HO"})
    assert r.status_code == 201
    assert (r.json()["sym"], r.json()["at"], r.json()["next_start"]) == ("HO", "245500", "2026-11-07T00:55:00")
    r = c.post("/api/team/pyrun/schedules", json={"file": "ho.py", "mode": "paper", "sym": "ZZ"})
    assert r.status_code == 409 and "마스터에 없는 종목" in r.json()["detail"]
    r = c.post("/api/team/pyrun/schedules", json={"file": "ho.py", "mode": "paper", "foo": "x"})
    assert r.status_code == 422                                         # 모르는 칸은 여전히 422
