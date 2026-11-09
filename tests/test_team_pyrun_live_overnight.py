"""1분봉 장중 실행 — 자정을 넘는 실행(거래일 시계, 설계 4.4·4.5).

가짜 해외 api·날짜까지 있는 가짜 시계·가짜 판정으로만 봅니다. NH 서버로는 아무것도 나가지 않습니다.
월 2026-11-09 22:25 에 시작하는 HO 밤 전략: 자정 뒤 시각은 24를 더해(00:01 → `"240100"`) 그 거래일(20261109)에
이어 붙고, 진입 창·`hold_min`·정리·실행 끝이 한 실행 안에서 이어집니다.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.sessions.hours import KST
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import LiveRun, RunSpec, StartRefused, _trading_clock
from backend.team_pyrun.runner import Runner, _plus_minute
from tests.test_team_pyrun_live_any import HO, FakeHO, FakeJudge, write
from tests.test_team_pyrun_live_overseas import MKU_SRC, FakeLive, journal, ovs_bar, read_json, texts

MON, TUE = "20261109", "20261110"

#: 밤 시험 전략 — 22:30 장 시작, 04:55 정리. `script` 의 분(거래일 시계)에 신호를 내고, 받은 봉을 `seen` 에 적는다
NIGHT_SRC = '''
"""밤 시험 전략."""
from dataclasses import dataclass

TICK = 0.0001
TICK_VALUE = 4.2
NAME = "night"


@dataclass
class Params:
    session_start: str = "223000"
    session_end: str = "050000"
    entry_start: str = "223000"
    entry_end: str = "040000"
    flatten_at: str = "045500"
    hold_min: int = 45


@dataclass
class Sig:
    minute: object
    side: object
    reason: str
    stop_ticks: object = None


class Strat:
    def __init__(self, p):
        self.p = p
        self.script = {"235800": "buy"}
        self.seen = []
        self.target = None

    def on_minute(self, m):
        self.seen.append((m.date, m.time))
        side = self.script.get(m.time)
        if side is None:
            return []
        return [Sig(m, side, "시험", 20)]


STRATEGY = Strat
'''

#: 자정을 넘지 않는 MKU 시험 전략(23:50 정리)에 받은 봉 적기를 더한 것
MKU_SEEN_SRC = (MKU_SRC.replace("        self.target = None\n", "        self.target = None\n        self.seen = []\n")
                .replace("    def on_minute(self, m):\n",
                         "    def on_minute(self, m):\n        self.seen.append((m.date, m.time))\n"))


def when(date: str, hhmmss: str) -> datetime:
    return datetime(int(date[:4]), int(date[4:6]), int(date[6:]), int(hhmmss[:2]), int(hhmmss[2:4]),
                    int(hhmmss[4:]), tzinfo=KST)


class NightJudge(FakeJudge):
    """실제 시각으로 답하는 판정 — [since, until) 은 쉼(`break`), 나머지는 열림."""

    def __init__(self, since: datetime, until: datetime):
        super().__init__()
        self.since, self.until = since, until

    def __call__(self, market, sym, now):
        self.calls.append((market, sym, now))
        state = "break" if self.since <= now < self.until else "open"
        return {"state": state, "source": "table", "since": self.since.isoformat(), "until": self.until.isoformat()}


def make_night(tmp_path, *, src=NIGHT_SRC, file="night.py", leg=HO, mode="paper", start=(MON, "222500"),
               judge=None, warmup=(), **kw):
    loaded = write(tmp_path, src, file)
    clock = {"now": when(*start)}
    fake = FakeHO(clock) if leg is not None else FakeLive(clock)
    if leg is not None:
        fake.sym = leg.sym
    fake.chart = list(warmup)
    out = tmp_path / "run"
    run = LiveRun(f"{start[0]}_{loaded.name}_{mode}", out, loaded, RunSpec(file=file, mode=mode, sym=None),
                  api_module=fake, now=lambda: clock["now"], sleep=lambda s: None, leg=leg, judge=judge, **kw)
    return run, fake, out, clock


def tick(run, fake, clock, moment: datetime, *, bar: bool = True) -> None:
    """시계를 `moment` 로 옮기고 step 한 번. `bar` 면 막 닫힌 1분봉(1분 전 것, 달력 날짜·시각)을 차트에 둔다."""
    if bar:
        prev = moment.replace(second=0) - timedelta(minutes=1)
        fake.chart = [ovs_bar(prev.strftime("%H%M%S"), date=prev.strftime("%Y%m%d"))]
    clock["now"] = moment
    run.step(moment)


def walk(run, fake, clock, frm: datetime, to: datetime) -> None:
    """`frm` 부터 `to` 까지 1분마다 step (막 닫힌 봉을 차트에 둠). 실행이 끝나면 멈춘다."""
    t = frm
    while t <= to and not run._finished:
        tick(run, fake, clock, t)
        t += timedelta(minutes=1)


# ---------------------------------------------------------------- 봉·Params·첫머리 기록
def test_자정_넘는_실행의_Params_와_봉은_거래일_시계(tmp_path):
    warm = [ovs_bar("010000", date=MON), ovs_bar("221000", date=MON), ovs_bar("222400", date=MON),
            ovs_bar("222500", date=MON)]
    run, fake, out, clock = make_night(tmp_path, warmup=warm)
    run.prepare()
    p = run.runner.p
    assert (run.plan.overnight, run.plan.end, run.trading_date) == (True, "290000", MON)
    assert (p.session_start, p.entry_start, p.entry_end, p.flatten_at, p.session_end) == (
        "223000", "223000", "280000", "285500", "290000")
    # 준비 봉: 지금 분(22:25) 앞 것만. 월 01:00 봉은 그 거래일(일요일 20261108)의 25시
    assert run.runner.strat.seen == [("20261108", "250000"), (MON, "221000"), (MON, "222400")]
    assert run.state == "대기"
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "000504"))
    seen = run.runner.strat.seen
    assert (MON, "235900") in seen and (MON, "240000") in seen and (MON, "240100") in seen
    assert [d for d, _ in seen[3:]] == [MON] * len(seen[3:])       # 자정 뒤 봉도 같은 거래일
    assert seen[-1] == (MON, "240400")
    assert run.state == "진행 중"
    assert run.status()["next_decision_at"] == "240600"


def test_기록_첫머리에_자정_넘는_실행과_바꾼_Params_한_줄(tmp_path):
    run, fake, out, clock = make_night(tmp_path)
    run.prepare()
    lines = texts(out)
    line = next(x for x in lines if x.startswith("자정을 넘는 실행"))
    assert line == ("자정을 넘는 실행 — 거래일 20261109, 시각은 07:00 전이면 +24 (예 01:30 → 253000). "
                    "바꾼 Params: session_end 050000→290000, entry_end 040000→280000, flatten_at 045500→285500")
    assert lines.index(line) < next(i for i, x in enumerate(lines) if x.startswith("전략 "))
    assert any("실행 끝 05:00 (+1)" in x for x in lines)


def test_끝만_24시를_넘는_실행은_바꾼_Params_없음(tmp_path):
    src = (NIGHT_SRC.replace('session_end: str = "050000"', 'session_end: str = "235900"')
           .replace('entry_end: str = "040000"', 'entry_end: str = "235000"')
           .replace('flatten_at: str = "045500"', 'flatten_at: str = "235800"'))
    run, fake, out, clock = make_night(tmp_path, src=src)
    run.prepare()
    assert (run.plan.overnight, run.plan.end) == (True, "240300")
    assert any(x.startswith("자정을 넘는 실행 — 거래일 20261109") and x.endswith("바꾼 Params: 없음") for x in texts(out))


# ---------------------------------------------------------------- 자정을 넘는 보유
def test_자정_넘는_보유는_hold_min_분_셈으로_시간_청산_기록은_거래일(tmp_path):
    run, fake, out, clock = make_night(tmp_path)
    run.prepare()
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "000004"))
    pos = run.runner.pos
    assert pos is not None and pos["entry_time"] == "235904"       # 23:58 봉 신호 → 23:59 첫 가격
    assert run.status()["time_exit_at"] == "244400"
    walk(run, fake, clock, when(TUE, "000104"), when(TUE, "004304"))
    assert run.runner.pos is not None                               # 44분 — 아직
    walk(run, fake, clock, when(TUE, "004404"), when(TUE, "005004"))
    t = run.runner.trades[0]
    assert t["reason"] == "시간 청산"
    assert (t["entry_time"], t["exit_time"]) == ("235904", "244404")
    assert t["entry_date"] == t["exit_date"] == MON
    row = next(r for r in journal(out) if r["kind"] == "trade")
    assert (row["clock"], row["exit_date"], row["exit_time"]) == ("244404", MON, "244404")
    assert run.state == "진행 중"


def test_0455_에_보유가_있으면_장_마감_정리_0500_에_끝_run_json_은_거래일(tmp_path):
    src = NIGHT_SRC.replace("hold_min: int = 45", "hold_min: int = 600")
    run, fake, out, clock = make_night(tmp_path, src=src)
    run.prepare()
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "045404"))
    assert run.runner.pos is not None and run.state == "진행 중"
    walk(run, fake, clock, when(TUE, "045504"), when(TUE, "045904"))
    t = run.runner.trades[0]
    assert (t["reason"], t["exit_time"], t["exit_date"]) == ("장 마감 정리", "285504", MON)
    assert run.runner.pos is None and run.state == "진행 중"
    tick(run, fake, clock, when(TUE, "045959"), bar=False)
    assert run.state == "진행 중"
    tick(run, fake, clock, when(TUE, "050000"), bar=False)
    assert run.state == "끝" and run.ended_reason == "장 끝"
    assert run.ended_at == "2026-11-10T05:00:00"
    j = read_json(out / "run.json")
    assert (j["state"], j["trading_date"], j["overnight"], j["end"]) == ("끝", MON, True, "290000")
    s = read_json(out / "summary.json")
    assert (s["trading_date"], s["overnight"], s["trades"][0]["exit_time"]) == (MON, True, "285504")


def test_다리_없는_MKU_045500_전략_23시_진입_0455_정리_0500_끝(tmp_path):
    """Task 4 검토의 재현 — 자정 뒤 실제 시각 000100 이 바꾼 session_start 보다 작아 「대기」로 빠지고
    보유를 돌보지 않던 것. 이제 23:01 진입 → 04:55 「장 마감 정리」 → 05:00 「끝」."""
    src = MKU_SRC.replace('flatten_at: str = "235000"', 'flatten_at: str = "045500"')
    run, fake, out, clock = make_night(tmp_path, src=src, file="fakemku.py", leg=None, start=(MON, "082000"))
    run.prepare()
    assert (run.plan.overnight, run.plan.end, run.runner.p.flatten_at) == (True, "290000", "285500")
    run.runner.strat.script = {"230000": ("서울", "buy")}
    walk(run, fake, clock, when(MON, "225904"), when(MON, "230104"))
    assert run.runner.pos is not None and run.runner.pos["entry_time"] == "230104"
    walk(run, fake, clock, when(MON, "230204"), when(TUE, "045404"))
    assert run.state == "진행 중" and run.runner.pos is not None
    assert run.runner.strat.date == MON         # 자정 뒤 봉도 같은 거래일 — 전략이 하루를 새로 만들지 않음
    tick(run, fake, clock, when(TUE, "045504"))
    t = run.runner.trades[-1]
    assert (t["reason"], t["exit_time"], t["exit_date"]) == ("장 마감 정리", "285504", MON)
    tick(run, fake, clock, when(TUE, "050000"), bar=False)
    assert run.state == "끝" and run.ended_reason == "장 끝"


# ---------------------------------------------------------------- 실행 끝·거래일 넘김
def test_실행_끝이_다음_날_07시면_0700_에_끝난다(tmp_path):
    src = (NIGHT_SRC.replace('session_end: str = "050000"', 'session_end: str = "065900"')
           .replace('flatten_at: str = "045500"', 'flatten_at: str = "065500"')
           .replace("hold_min: int = 45", "hold_min: int = 600"))
    run, fake, out, clock = make_night(tmp_path, src=src)
    run.prepare()
    assert run.plan.end == "310000"
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "000004"))
    assert run.runner.pos is not None
    tick(run, fake, clock, when(TUE, "065504"))
    assert run.runner.trades[-1]["exit_time"] == "305504"
    tick(run, fake, clock, when(TUE, "065959"), bar=False)
    assert run.state == "진행 중"
    tick(run, fake, clock, when(TUE, "070000"), bar=False)
    assert run.state == "끝" and run.ended_reason == "장 끝"


def test_거래일이_지나서_온_step_은_대기로_빠지지_않고_끝낸다(tmp_path):
    """잠들었다 다음 날 08:00 에 깨어도 「대기」로 다음 장을 기다리지 않는다 — 시각은 거래일에서 이어 세고(32시) 끝내기가 정리."""
    src = NIGHT_SRC.replace("hold_min: int = 45", "hold_min: int = 600")
    run, fake, out, clock = make_night(tmp_path, src=src)
    run.prepare()
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "000004"))
    assert run.runner.pos is not None
    tick(run, fake, clock, when(TUE, "080000"), bar=False)
    assert run.state == "끝" and run.ended_reason == "장 끝"
    t = run.runner.trades[-1]
    assert (t["reason"], t["exit_time"], t["exit_date"]) == ("실행 종료 정리", "320000", MON)


# ---------------------------------------------------------------- 모의 계좌·판정
def test_자정_뒤에_시작하면_거래일은_전날_예수금_날짜는_달력_그대로(tmp_path):
    run, fake, out, clock = make_night(tmp_path, mode="orders", start=(TUE, "003000"))
    run.prepare()
    assert run.trading_date == MON and run.state == "진행 중"
    assert run.broker.today == TUE
    assert ("ovs_deposit", "USD", TUE) in fake.calls


def test_모의_계좌_자정_넘는_보유_주문은_실제_시각_기록은_거래일_시계(tmp_path):
    run, fake, out, clock = make_night(tmp_path, mode="orders")
    run.prepare()
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "005004"))
    assert [o[1] for o in fake.orders] == ["buy", "sell"]
    assert fake.order_clocks == ["235904", "004404"]
    t = run.runner.trades[0]
    assert (t["reason"], t["entry_time"], t["exit_time"], t["exit_date"]) == ("시간 청산", "235904", "244404", MON)
    assert run.runner.halted is None and run.state == "진행 중"


def test_자정_뒤_판정이_쉼이면_주문_없고_열리면_진입_판정엔_실제_시각(tmp_path):
    judge = NightJudge(when(TUE, "010000"), when(TUE, "011000"))
    run, fake, out, clock = make_night(tmp_path, mode="orders", judge=judge)
    run.prepare()
    run.runner.strat.script = {"245900": "buy"}       # 00:59 봉 (거래일 시계)
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "010904"))
    assert fake.orders == [] and run.runner.pending is not None
    judge.calls.clear()
    tick(run, fake, clock, when(TUE, "011004"))
    assert [o[1] for o in fake.orders] == ["buy"] and fake.order_clocks == ["011004"]
    assert run.runner.pos["entry_time"] == "251004"
    # 판정에는 거래일 시계를 실제 한국시간으로 되돌려 넘긴다(하루 늦게 묻지 않음)
    assert judge.calls and all(abs(c[2] - clock["now"]) <= timedelta(seconds=1) for c in judge.calls)


class ClosedFrom(FakeJudge):
    """`since` 부터 닫힘(`closed`), 그 전은 열림 — 실제 시각으로 답한다."""

    def __init__(self, since: datetime):
        super().__init__()
        self.since = since

    def __call__(self, market, sym, now):
        self.calls.append((market, sym, now))
        return {"state": "closed" if now >= self.since else "open", "source": "table"}


class UnknownBetween(FakeJudge):
    """[since, until) 동안 종목을 모르는 판정(`source` unknown), 나머지는 열림."""

    def __init__(self, since: datetime, until: datetime):
        super().__init__()
        self.since, self.until = since, until

    def __call__(self, market, sym, now):
        self.calls.append((market, sym, now))
        if self.since <= now < self.until:
            return {"state": "closed", "source": "unknown"}
        return {"state": "open", "source": "table"}


def test_거래일이_지나_깬_보유_모의_계좌_실행은_판정이_닫혔으면_정리하지_않고_확인_필요(tmp_path):
    """R8 — 자정 넘는 모의 계좌 실행이 보유한 채 잠들었다 다음 날 08:00(거래일이 지남)에 깸. 그때 판정이 닫힘이면
    정리 주문을 내지 않고 「확인 필요」로 끝낸다(다음 날 자동 시작도 막힘)."""
    from backend.team_pyrun.autostart import blocked_reason, summary_reason
    src = NIGHT_SRC.replace("hold_min: int = 45", "hold_min: int = 600")
    run, fake, out, clock = make_night(tmp_path, src=src, mode="orders", judge=ClosedFrom(when(TUE, "050000")))
    run.prepare()
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "000004"))
    assert run.runner.pos is not None and [o[1] for o in fake.orders] == ["buy"]
    tick(run, fake, clock, when(TUE, "080000"), bar=False)
    assert run.state == "끝" and [o[1] for o in fake.orders] == ["buy"]          # 정리 주문 없음
    assert run.ended_reason.startswith("장 끝 · 정리 안 함 — 확인 필요: 장 닫힘(장 마감) 끝 — 정리 주문을 내지 않음")
    assert run.runner.pos is not None and run.runner.trades == []
    s = read_json(out / "summary.json")
    assert "정리 주문을 내지 않음 · 보유 +1" in s["halted"]
    assert blocked_reason(run.state, run.ended_reason) and summary_reason(s)


def test_자정_뒤_판정이_종목을_모르게_되면_그동안_주문_없고_기록은_한_번(tmp_path):
    judge = UnknownBetween(when(TUE, "000000"), when(TUE, "003000"))
    run, fake, out, clock = make_night(tmp_path, mode="orders", judge=judge)
    run.prepare()
    run.runner.strat.script = {"240500": "buy"}       # 00:05 봉 (거래일 시계) — 판정이 종목을 모르는 동안
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "002904"))
    assert fake.orders == [] and run.runner.pending is not None
    lines = texts(out)
    assert lines.count("장 시간표 모름 — 주문 멈춤") == 1
    tick(run, fake, clock, when(TUE, "003004"))
    assert [o[1] for o in fake.orders] == ["buy"] and fake.order_clocks == ["003004"]
    lines = texts(out)
    assert lines.count("장 시간표 모름 — 주문 멈춤") == 1 and lines.count("장 시간표 다시 확인 — 주문 받음") == 1


def test_registry_가_정한_거래일과_준비_때_거래일이_다르면_거부(tmp_path):
    """07:00 에 걸친 시작 — 실행 관리는 월요일 거래일로 폴더·손절 수를 정했는데 준비는 화요일 07:00:01 이면 거부(조회·주문 없음)."""
    src = (NIGHT_SRC.replace('session_end: str = "050000"', 'session_end: str = "065900"')
           .replace('flatten_at: str = "045500"', 'flatten_at: str = "065500"'))
    run, fake, out, clock = make_night(tmp_path, src=src, mode="orders", start=(TUE, "070001"), trading_date=MON)
    with pytest.raises(StartRefused, match="^거래일이 바뀌는 07:00 에 걸쳐 시작했습니다 — 다시 시작하세요$"):
        run.prepare()
    assert fake.calls == [] and fake.orders == []
    j = read_json(out / "run.json")
    assert j["state"] == "끝" and j["ended_reason"] == "시작 거부: 거래일이 바뀌는 07:00 에 걸쳐 시작했습니다 — 다시 시작하세요"
    # 같은 거래일이면 그대로 선다 · 주지 않으면(None) 지금처럼 스스로 셈
    for given in (TUE, None):
        ok, _, _, _ = make_night(tmp_path / str(given), src=src, start=(TUE, "070001"), trading_date=given)
        ok.prepare()
        assert ok.trading_date == TUE and ok.state == "대기"


# ---------------------------------------------------------------- 자정을 넘지 않는 실행은 그대로
def test_자정_넘지_않는_MKU_전략의_준비_봉은_지금처럼_달력_날짜(tmp_path):
    warm = [ovs_bar("235800", date=MON), ovs_bar("001000", date=TUE), ovs_bar("081900", date=TUE)]
    run, fake, out, clock = make_night(tmp_path, src=MKU_SEEN_SRC, file="fakemku.py", leg=None,
                                       start=(TUE, "082000"), warmup=warm)
    run.prepare()
    assert run.plan.overnight is False and run.trading_date == TUE
    assert run.runner.strat.seen == [(MON, "235800"), (TUE, "001000"), (TUE, "081900")]
    assert not any("자정을 넘는 실행" in x for x in texts(out))


def test_자정_넘지_않는_실행도_날이_지나_온_step_은_대기_없이_끝낸다(tmp_path):
    """실행 하나 = 하루. 23:55 에 끝나는 MKU 실행이 잠들었다 다음 날 00:10 에 깨어도 「대기」로 다음 장을 기다리지 않는다."""
    run, fake, out, clock = make_night(tmp_path, src=MKU_SRC, file="fakemku.py", leg=None, mode="orders",
                                       start=(MON, "082000"))
    run.prepare()
    assert (run.plan.overnight, run.plan.end, run.trading_date) == (False, "235500", MON)
    tick(run, fake, clock, when(MON, "230004"))
    assert run.state == "진행 중"
    states: list[str] = []
    set_state = run._set_state
    run._set_state = lambda s: (states.append(s), set_state(s))
    tick(run, fake, clock, when(TUE, "001004"))
    assert run.state == "끝" and run.ended_reason == "장 끝" and "대기" not in states
    tick(run, fake, clock, when(TUE, "083004"))      # 다음 장이 열려도 끝난 실행은 그대로
    assert run.state == "끝" and fake.orders == [] and "대기" not in states
    assert read_json(out / "run.json")["state"] == "끝"


def _record_states(run) -> list[str]:
    states: list[str] = []
    set_state = run._set_state
    run._set_state = lambda s: (states.append(s), set_state(s))
    return states


def test_거래일에서_이어_센_시각은_6자리를_넘지_않는다():
    assert _trading_clock(MON, when("20261113", "035959")) == "995959"      # 99시간 59분 59초
    assert _trading_clock(MON, when("20261113", "040000")) == "995959"      # 100시간 — 묶음
    assert _trading_clock(MON, when("20261120", "120000")) == "995959"
    assert _trading_clock(MON, when("20261108", "230000")) == "000000"      # 날짜보다 이르면 0
    assert _trading_clock(MON, when(TUE, "070000")) == "310000"


def test_100시간_넘게_지나_온_step_도_자정_넘는_보유_실행을_끝낸다(tmp_path):
    """금요일 08:00(월요일 0시부터 104시간)에 깨어도 「대기」로 빠지지 않고 「장 끝」 — 시각 문자열이 넘쳐 비교가 틀리지 않게."""
    src = NIGHT_SRC.replace("hold_min: int = 45", "hold_min: int = 600")
    run, fake, out, clock = make_night(tmp_path, src=src)
    run.prepare()
    walk(run, fake, clock, when(MON, "223004"), when(TUE, "000004"))
    assert run.runner.pos is not None
    states = _record_states(run)
    tick(run, fake, clock, when("20261113", "080000"), bar=False)
    assert run.state == "끝" and run.ended_reason == "장 끝" and "대기" not in states
    t = run.runner.trades[-1]
    assert (t["reason"], t["exit_time"], t["exit_date"]) == ("실행 종료 정리", "995959", MON)
    assert run.runner.pos is None and fake.orders == []
    assert all(len(r["clock"]) == 6 for r in journal(out) if "clock" in r)


def test_100시간_넘게_지나_온_step_도_자정_넘지_않는_모의_계좌_실행을_끝낸다(tmp_path):
    run, fake, out, clock = make_night(tmp_path, src=MKU_SRC, file="fakemku.py", leg=None, mode="orders",
                                       start=(MON, "082000"))
    run.prepare()
    tick(run, fake, clock, when(MON, "230004"))
    assert run.state == "진행 중"
    states = _record_states(run)
    calls = len(fake.calls)
    tick(run, fake, clock, when("20261113", "083004"))
    assert run.state == "끝" and run.ended_reason == "장 끝" and "대기" not in states
    assert fake.orders == []
    # 끝내기 확인(끝 잔고·예수금)만 — 1분봉·현재가로 전략을 돌리지 않음
    assert {c[0] for c in fake.calls[calls:]} <= {"ovs_open_interest_page", "ovs_deposit"}
    tick(run, fake, clock, when("20261113", "083104"))
    assert run.state == "끝" and fake.orders == []


# ---------------------------------------------------------------- Runner: 24시를 넘는 시각 셈
def _night_runner(tmp_path, broker):
    p = SimpleNamespace(entry_start="223000", entry_end="280000", flatten_at="285500", hold_min=45)
    strat = SimpleNamespace(p=p, target=None)
    r = Runner(strat, Journal(tmp_path / "journal.jsonl"), broker, 0.0001, 4.2)
    r.live_date = MON
    r.pos = {"side": "buy", "entry": 0.75, "entry_time": "235904", "signal_time": "235900",
             "stop_ticks": 20, "stop": 0.748, "entry_fee": None}
    return r


class _Broker:
    mode = "fake"
    last_fill_fee = None

    def __init__(self, fill_px=None, held=None):
        self.fill_px, self.held = fill_px, held
        self.fills: list[tuple] = []

    def fill(self, side, ref_price, clock, why):
        self.fills.append((side, clock, why))
        return self.fill_px

    def position(self):
        return self.held

    def account(self, clock="", why=""):
        return None


def test_Runner_시간_청산_재시도_1분_뒤는_24시를_넘어_센다(tmp_path):
    assert _plus_minute("235900") == "240000" and _plus_minute("285900") == "290000"
    b = _Broker(fill_px=None, held=1)          # 청산 체결 확인 안 됨, 잔고는 그대로 → 10초 뒤 재시도
    r = _night_runner(tmp_path, b)
    assert r.snapshot()["time_exit_at"] == "244400"
    r.on_price("244355", 0.75)                  # 진입 분(23:59)부터 44분 — 아직
    assert b.fills == []
    r.on_price("245955", 0.75)
    assert b.fills == [("sell", "245955", "청산 · 시간 청산")] and r.retry_after == "250005"
    r.on_price("250000", 0.75)                  # 아직 10초 안 됨
    assert len(b.fills) == 1
    b.fill_px = 0.7499
    r.on_price("250005", 0.75)
    assert len(b.fills) == 2
    assert (r.trades[0]["reason"], r.trades[0]["exit_time"], r.trades[0]["exit_date"]) == ("시간 청산", "250005", MON)
