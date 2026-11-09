"""실행 관리(`registry.py`) — 아무 선물 종목(품목 뿌리·종목 코드), 거래일, 다시 켤 때, 판정 꽂기 (설계 4.1·4.3·4.4·4.7).

종목 찾기는 가짜 `find`(마스터·품목 세부정보 조회 없음)로, 시세·계좌는 가짜 api 로만 봅니다(`start_thread=False`).
NH 서버로는 아무것도 나가지 않습니다.
"""
import threading

import pytest

from backend.team_pyrun import live, opening, products
from backend.team_pyrun import registry as registry_lib
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import LiveRun, RunSpec, StartRefused
from backend.team_pyrun.registry import Registry
from backend.team_spread.legs import Leg, LegError
from tests.test_team_pyrun_live import STRATEGY_SRC, SYM, FakeApi, at
from tests.test_team_pyrun_live_any import HO, HO_SRC, KOSPI, KOSPI_SRC, FakeHO, FakeJudge, FakeKospi
from tests.test_team_pyrun_live_overseas import MKU, MKU_SRC, FakeLive
from tests.test_team_pyrun_registry import read_json, trade, write_run

TODAY = "20261103"      # 화요일
HO_NEXT = Leg("main", "HOF27", "HO", "overseas", "FCME", "USD", 0.0001, 4.2, "202701")

#: 자정을 넘는 HO 전략 — 22:30 시작, 04:55 정리 → 실행 끝 05:00(거래일 시계 `"290000"`)
HO_NIGHT_SRC = (HO_SRC.replace('NAME = "fakeho"', 'NAME = "fakehon"')
                .replace('session_start: str = "090000"', 'session_start: str = "223000"')
                .replace('session_end: str = "233500"', 'session_end: str = "050000"')
                .replace('entry_start: str = "090000"', 'entry_start: str = "223000"')
                .replace('entry_end: str = "230000"', 'entry_end: str = "040000"')
                .replace('flatten_at: str = "233000"', 'flatten_at: str = "045500"'))
KOSPI_FILE_SRC = KOSPI_SRC.replace('NAME = "fake"', 'NAME = "fakekospi"')
#: 07:00 에 끝나는 자정 넘는 HO 전략 — 06:55 정리 → 실행 끝 07:00(거래일 시계 `"310000"`, 넘지 않음)
HO_DAWN_SRC = (HO_NIGHT_SRC.replace('NAME = "fakehon"', 'NAME = "fakehod"')
               .replace('session_end: str = "050000"', 'session_end: str = "065900"')
               .replace('flatten_at: str = "045500"', 'flatten_at: str = "065500"'))
#: 07:03 에 끝나는 자정 넘는 HO 전략 — 06:58 정리 → 실행 끝 `"310300"`(다음 날 07:00 을 넘음)
HO_LATE_SRC = (HO_NIGHT_SRC.replace('NAME = "fakehon"', 'NAME = "fakehol"')
               .replace('session_end: str = "050000"', 'session_end: str = "065900"')
               .replace('flatten_at: str = "045500"', 'flatten_at: str = "065800"'))
#: 장 시간 칸이 빠진(MKU 시험 전략) 채 틱가치만 HO 값인 전략 — 빠진 칸을 채우는 것은 MKU 만
HOBARE_SRC = MKU_SRC.replace("TICK_VALUE = 2.5", "TICK_VALUE = 4.2").replace('NAME = "fakemku"', 'NAME = "hobare"')
assert '"045500"' in HO_NIGHT_SRC and '"fakehon"' in HO_NIGHT_SRC and '"fakekospi"' in KOSPI_FILE_SRC
assert '"065500"' in HO_DAWN_SRC and '"065800"' in HO_LATE_SRC and '"hobare"' in HOBARE_SRC


class FakeFind:
    """종목 찾기(`products.find_product`) 가짜 — 표기 → `Leg`. 받은 인자를 적고, 모르는 표기는 `StartRefused`."""

    def __init__(self, legs: dict | None = None):
        self.legs = dict(legs if legs is not None else
                         {"HO": HO, "HOZ26": HO, "HOF27": HO_NEXT, "A01": KOSPI, KOSPI.sym: KOSPI})
        self.calls: list[tuple] = []

    def __call__(self, spec, *, api_module, today):
        self.calls.append((spec, api_module, today))
        if spec not in self.legs:
            raise StartRefused(f"마스터에 없는 종목입니다: {spec}")
        return self.legs[spec]


def make_reg(tmp_path, *, now="100000", date=TODAY, fake=None, find=None, env="paper", **kw):
    """전략 폴더(HO·자정 넘는 HO·MKU·국내·코스피200 시험 전략)와 가짜 `find` 를 꽂은 `Registry`."""
    folder = tmp_path / "strategies"
    folder.mkdir(parents=True, exist_ok=True)
    for file, src in (("fakeho.py", HO_SRC), ("fakehon.py", HO_NIGHT_SRC), ("fakemku.py", MKU_SRC),
                      ("fake.py", STRATEGY_SRC), ("fakekospi.py", KOSPI_FILE_SRC)):
        (folder / file).write_text(src, encoding="utf-8")
    clock = {"now": at(now, date)}
    fake = fake if fake is not None else FakeHO(clock)
    fake.clock = clock
    find = find if find is not None else FakeFind()
    reg = Registry(tmp_path / "pyruns", folder, now=lambda: clock["now"], active_env=lambda: env,
                   start_thread=False, api_module=fake, sleep=lambda s: None, find=find, **kw)
    return reg, fake, find, clock


def events(folder):
    return [r.get("text", "") for r in Journal(folder / "journal.jsonl").read() if r["kind"] == "event"]


# ---------------------------------------------------------------- 종목 칸: 품목 뿌리·종목 코드
def test_뿌리_HO_는_find_로_찾고_실행이_그_leg_를_받는다(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path)
    status = reg.start(RunSpec("fakeho.py", "paper", "HO"))
    assert find.calls == [("HO", fake, TODAY)]                  # api 그대로, 최근월물은 지금 달력 날짜로
    run = reg.get(status["id"])
    assert isinstance(run, LiveRun) and run.leg is HO
    assert run.sym == status["sym"] == "HOZ26"
    assert status["id"] == f"{TODAY}_fakeho_paper"              # 뿌리 = 최근월물 — 폴더 이름에 종목을 안 붙인다
    data = read_json(tmp_path / "pyruns" / status["id"] / "run.json")
    assert (data["sym"], data["product"], data["exchange"], data["market"], data["currency"], data["tick_value"]) == (
        "HOZ26", "HO", "FCME", "overseas", "USD", 4.2)
    assert ("ovs_chart_minute", "HOZ26", live.WARMUP_BARS, "FCME") in fake.calls


def test_찾은_종목_코드는_폴더_이름에_붙고_조회는_한_번(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path)
    code = reg.start(RunSpec("fakeho.py", "paper", "HOZ26"))
    other = reg.start(RunSpec("fakeho.py", "paper", "HOF27"))
    root = reg.start(RunSpec("fakeho.py", "paper", "HO"))
    # 코드면 최근월물인지 모른다(최근월물을 찾으려고 더 조회하지 않음) → 지금 규칙(최근월물을 모르면 붙임)대로 붙인다
    assert [code["id"], other["id"], root["id"]] == [
        f"{TODAY}_fakeho_paper_HOZ26", f"{TODAY}_fakeho_paper_HOF27", f"{TODAY}_fakeho_paper"]
    assert (code["sym"], other["sym"], root["sym"]) == ("HOZ26", "HOF27", "HOZ26")
    assert [c[0] for c in find.calls] == ["HOZ26", "HOF27", "HO"]     # 시작마다 한 번
    assert fake.calls and not [c for c in fake.calls if "detail" in c[0] or "master" in c[0]]


def test_정확한_A75·MKU_코드는_find_를_안_부르고_지금_길(tmp_path):
    """지금 종목 고르기가 보내는 두 코드는 마스터·품목 세부정보를 새로 읽지 않는다(설계 5장 — 지금과 같아야 함)."""
    reg, fake, find, _ = make_reg(tmp_path, fake=FakeApi())
    status = reg.start(RunSpec("fake.py", "paper", "A756C000"))
    assert find.calls == [] and status["sym"] == "A756C000" and reg.get(status["id"]).leg is None
    assert status["id"] == f"{TODAY}_fake_paper_A756C000"                     # 최근월물(A756B000)과 다르면 붙음
    assert "domestic_product-detail" in fake.calls                            # 틱은 지금처럼 시작 때 서버로 확인
    reg, fake, find, _ = make_reg(tmp_path / "mku", fake=FakeLive())
    status = reg.start(RunSpec("fakemku.py", "paper", MKU))
    assert find.calls == [] and status["sym"] == MKU and reg.get(status["id"]).leg is None
    assert status["id"] == f"{TODAY}_fakemku_paper"                           # 최근월물이면 안 붙음 (지금 그대로)
    with pytest.raises(StartRefused, match="종목의 시장과 전략 틱이 맞지 않습니다"):   # 시장 가드도 그대로
        reg.start(RunSpec("fake.py", "paper", MKU))
    assert find.calls == []


def test_뿌리_A75·MKU_는_find_로_그날의_최근월물(tmp_path):
    usd = Leg("main", SYM, "A75", "domestic", "KRX", "KRW", 0.1, 1000.0, "20261116")
    mku = Leg("main", MKU, "MKU", "overseas", "FSGX", "USD", 0.0001, 2.5, "202611")
    reg, fake, find, _ = make_reg(tmp_path, fake=FakeApi(), find=FakeFind({"A75": usd}))
    status = reg.start(RunSpec("fake.py", "paper", "A75"))
    assert [c[0] for c in find.calls] == ["A75"] and reg.get(status["id"]).leg is usd
    assert (status["sym"], status["id"]) == (SYM, f"{TODAY}_fake_paper")
    reg, fake, find, _ = make_reg(tmp_path / "mku", find=FakeFind({"MKU": mku}))
    status = reg.start(RunSpec("fakemku.py", "paper", "MKU"))
    assert [c[0] for c in find.calls] == ["MKU"] and reg.get(status["id"]).leg is mku
    assert (status["sym"], status["id"]) == (MKU, f"{TODAY}_fakemku_paper")


def test_국내_코스피200_뿌리도_find_로_국내_계좌(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path, fake=FakeKospi())
    status = reg.start(RunSpec("fakekospi.py", "paper", "A01"))
    assert (status["sym"], status["market"], status["currency"], status["product"]) == (
        KOSPI.sym, "domestic", "KRW", "A01")
    assert reg.get(status["id"]).leg is KOSPI and "domestic_chart-minute" in fake.calls
    assert "domestic_product-detail" not in fake.calls          # 틱은 종목 찾기가 이미 확인했다


def test_MKU_틱_전략에_HO_면_조회_없이_폴더_없이_거부(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path)
    for mode in ("orders", "paper"):
        with pytest.raises(StartRefused, match="틱·틱가치가 전략 가정과 다릅니다") as e:
            reg.start(RunSpec("fakemku.py", mode, "HO"))
        assert "4.2" in str(e.value) and "2.5" in str(e.value)  # 종목·전략 두 값
    assert not (tmp_path / "pyruns").exists() and fake.calls == [] and fake.orders == []


def test_빈_종목은_find_를_부르지_않는다_지금_길(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path, fake=FakeApi())
    status = reg.start(RunSpec("fake.py", "paper", None))
    assert find.calls == [] and status["sym"] == SYM and reg.get(status["id"]).leg is None
    assert status["id"] == f"{TODAY}_fake_paper"
    reg, fake, find, _ = make_reg(tmp_path / "mku", fake=FakeLive())           # MKU 틱이면 MKU 최근월물
    status = reg.start(RunSpec("fakemku.py", "paper", None))
    assert find.calls == [] and status["sym"] == MKU and reg.get(status["id"]).leg is None


def test_find_가_거부하면_그_글_그대로_폴더_없이(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path)
    with pytest.raises(StartRefused, match="마스터에 없는 종목입니다: ZZZ9"):
        reg.start(RunSpec("fakeho.py", "orders", "ZZZ9"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []


def test_find_가_다른_예외를_내도_StartRefused_로_폴더_없이(tmp_path):
    def broken(spec, *, api_module, today):
        raise LegError("종목 마스터 cme_fut 를 읽지 못했습니다 — 받아 둔 파일이 없습니다.")
    reg, fake, _, _ = make_reg(tmp_path, find=broken)
    with pytest.raises(StartRefused, match="종목을 찾지 못했습니다 — LegError: 종목 마스터 cme_fut"):
        reg.start(RunSpec("fakeho.py", "paper", "HO"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []


def test_resolve_product_는_달력_날짜로_찾는다(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path, now="010000", date="20261114")     # 토요일 새벽 (거래일은 금요일)
    assert reg.resolve_product("HO") is HO
    assert find.calls == [("HO", fake, "20261114")]


# ---------------------------------------------------------------- 실행 끝·거래일
def test_HO_는_정리_5분_뒤가_끝_시각(tmp_path):
    reg, fake, _, _ = make_reg(tmp_path, now="233500")
    with pytest.raises(StartRefused, match=r"실행 끝 시각\(23:35\) 뒤에는 실행을 시작할 수 없습니다"):
        reg.start(RunSpec("fakeho.py", "paper", "HO"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []
    reg, _, _, _ = make_reg(tmp_path / "ok", now="233459")
    assert reg.start(RunSpec("fakeho.py", "paper", "HO"))["state"] == "진행 중"


def test_자정_넘는_전략은_토요일_새벽에도_선다_거래일은_금요일(tmp_path):
    reg, fake, find, _ = make_reg(tmp_path, now="010000", date="20261114")
    root = tmp_path / "pyruns"
    write_run(root, "20261113_fakehon_paper", state="끝", name="fakehon", sym="HOZ26",
              trades=[trade(date="20261113")])                  # 같은 거래일의 앞선 손절 1
    write_run(root, "20261114_fakehon_paper", state="끝", name="fakehon", sym="HOZ26",
              trades=[trade(date="20261114")])                  # 달력 날짜 폴더는 다른 거래일
    status = reg.start(RunSpec("fakehon.py", "paper", "HO"))
    assert status["id"] == "20261113_fakehon_paper_2"            # 폴더 이름 = 거래일
    run = reg.get(status["id"])
    assert run.plan.overnight and run.trading_date == "20261113"
    assert run.stops_before == 1 and run.runner.strat.day.stops == 1
    assert find.calls[0][2] == "20261114"                       # 최근월물은 달력 날짜로 고른다


def test_자정_넘는_전략도_일요일_거래일이면_주말_거부(tmp_path):
    reg, fake, _, _ = make_reg(tmp_path, now="010000", date="20261116")        # 월요일 01:00 = 일요일 거래일
    with pytest.raises(StartRefused, match="주말"):
        reg.start(RunSpec("fakehon.py", "paper", "HO"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []
    # 자정을 넘지 않는 전략은 지금처럼 달력 날짜 — 토요일 01:00 은 주말
    reg, fake, _, _ = make_reg(tmp_path / "day", now="010000", date="20261114")
    with pytest.raises(StartRefused, match="주말"):
        reg.start(RunSpec("fakeho.py", "paper", "HO"))
    assert not (tmp_path / "day" / "pyruns").exists() and fake.calls == []


def test_자정_넘는_전략을_화요일_0659_에_시작하면_끝_시각_뒤(tmp_path):
    reg, fake, _, _ = make_reg(tmp_path, now="065900", date="20261117")        # 거래일 월요일의 305900
    with pytest.raises(StartRefused, match=r"실행 끝 시각\(05:00 \(\+1\)\) 뒤에는 실행을 시작할 수 없습니다"):
        reg.start(RunSpec("fakehon.py", "paper", "HO"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []
    reg, _, _, _ = make_reg(tmp_path / "ok", now="045959", date="20261117")    # 끝 직전은 선다 (거래일 월요일)
    assert reg.start(RunSpec("fakehon.py", "paper", "HO"))["id"] == "20261116_fakehon_paper"


class CrossingFind(FakeFind):
    """찾는 동안 시계가 07:00 을 넘는 종목 찾기 — 실행 관리가 정한 거래일과 실행 준비의 거래일이 갈리는 때."""

    clock: dict | None = None

    def __call__(self, spec, *, api_module, today):
        leg = super().__call__(spec, api_module=api_module, today=today)
        self.clock["now"] = at("070001", "20261104")
        return leg


def test_07시에_걸쳐_시작하면_준비가_거부한다(tmp_path):
    """실행 관리는 06:59:58(수요일 = 화요일 거래일)로 폴더 이름·앞선 손절을 정했는데 실행 준비는 07:00:01(수요일 거래일) —
    다른 거래일로 정한 폴더·손절 수로 돌지 않게 준비가 거부한다(조회·주문 없음, run.json 은 「시작 거부」)."""
    find = CrossingFind()
    reg, fake, _, clock = make_reg(tmp_path, now="065958", date="20261104", find=find)
    find.clock = clock
    (reg.strategies / "fakehod.py").write_text(HO_DAWN_SRC, encoding="utf-8")
    with pytest.raises(StartRefused, match="거래일이 바뀌는 07:00 에 걸쳐 시작했습니다 — 다시 시작하세요"):
        reg.start(RunSpec("fakehod.py", "orders", "HO"))
    data = read_json(reg.root / f"{TODAY}_fakehod_orders" / "run.json")      # 폴더는 실행 관리가 정한 거래일(화요일)
    assert data["state"] == "끝" and data["ended_reason"].startswith("시작 거부: 거래일이 바뀌는 07:00")
    assert fake.calls == [] and fake.orders == [] and reg.list()[0]["state"] == "끝"
    # 걸치지 않으면(07:00:01 에 바로) 수요일 거래일로 선다
    reg, _, _, _ = make_reg(tmp_path / "ok", now="070001", date="20261104")
    (reg.strategies / "fakehod.py").write_text(HO_DAWN_SRC, encoding="utf-8")
    run = reg.get(reg.start(RunSpec("fakehod.py", "paper", "HO"))["id"])
    assert run.trading_date == "20261104" and run.state == "대기"


# ---------------------------------------------------------------- 계획만으로 보이는 거부 (`live.plan_refusal`) — 폴더 전에
def test_MKU_아닌_품목에_장_시간_칸이_빠지면_끝_시각_글이_아니라_그_까닭으로_폴더_없이(tmp_path):
    for now in ("235800", "100000"):        # 채운 칸의 끝(23:55) 뒤여도 진짜 까닭 · 앞이어도 폴더 없이
        reg, fake, _, _ = make_reg(tmp_path / now, now=now)
        (reg.strategies / "hobare.py").write_text(HOBARE_SRC, encoding="utf-8")
        with pytest.raises(StartRefused, match=r"Params 에 장 시간 칸이 없습니다 \(.*\) — 이 품목은 Params 에 적어야 합니다"):
            reg.start(RunSpec("hobare.py", "paper", "HO"))
        assert not (tmp_path / now / "pyruns").exists() and fake.calls == []


def test_해외_실행_끝이_다음_날_07시를_넘으면_폴더_없이_거부(tmp_path):
    reg, fake, _, _ = make_reg(tmp_path, now="100000")
    (reg.strategies / "holate.py").write_text(HO_LATE_SRC, encoding="utf-8")
    with pytest.raises(StartRefused, match=r"실행 끝\(07:03 \(\+1\)\)이 다음 날 07:00 을 넘습니다 — flatten_at 을 당기세요"):
        reg.start(RunSpec("holate.py", "paper", "HO"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []


# ---------------------------------------------------------------- 같은 종목 하나 — 뿌리·코드·스프레드 탭 통틀어
def test_같은_HOZ26_모의_계좌_실행은_뿌리·코드_통틀어_하나(tmp_path):
    reg, fake, _, _ = make_reg(tmp_path)
    first = reg.start(RunSpec("fakeho.py", "orders", "HO"))
    assert first["sym"] == "HOZ26" and reg.busy_sym("HOZ26") == first["id"] and reg.busy_sym("HO") is None
    with pytest.raises(StartRefused, match="같은 종목 HOZ26 .*이미"):
        reg.start(RunSpec("fakeho.py", "orders", "HOZ26"))
    assert reg.start(RunSpec("fakeho.py", "orders", "HOF27"))["sym"] == "HOF27"    # 다른 월물은 된다
    assert reg.start(RunSpec("fakeho.py", "paper", "HO"))["mode"] == "paper"       # 종이는 막지 않는다
    assert fake.orders == []


def test_HO_모의_계좌_실행이_있으면_같은_HOZ26_스프레드_다리는_거부(tmp_path):
    from tests.test_team_spread_registry import folders
    from tests.test_team_spread_registry import make as make_spread
    from tests.test_team_spread_registry import spec as spread_spec

    cross = threading.RLock()
    reg, fake, _, _ = make_reg(tmp_path, now="101500", date="20261109", cross_lock=cross)
    spread, api = make_spread(tmp_path, other_busy=lambda s: "파이썬 점유" if reg.busy_sym(s) else None, cross=cross)
    assert reg.start(RunSpec("fakeho.py", "orders", "HO"))["sym"] == "HOZ26"
    with pytest.raises(StartRefused, match="파이썬 점유"):
        spread.start(spread_spec())                             # 다리 ho = HO → HOZ26
    assert folders(spread) == [] and api.orders == [] and fake.orders == []
    assert spread.start(spread_spec(mode="paper"))["state"] == "진행 중"         # 종이는 상관없음


def test_스프레드가_HOZ26_을_주문_중이면_HO_뿌리_시작은_거부(tmp_path):
    asked: list[str] = []

    def busy(sym):
        asked.append(sym)
        return "스프레드 점유" if sym == "HOZ26" else None
    reg, fake, _, _ = make_reg(tmp_path, other_busy=busy)
    with pytest.raises(StartRefused, match="스프레드 점유"):
        reg.start(RunSpec("fakeho.py", "orders", "HO"))
    assert asked == ["HOZ26"]                                   # 뿌리가 아니라 고른 종목으로 묻는다
    assert not (tmp_path / "pyruns").exists() and fake.calls == []
    assert reg.start(RunSpec("fakeho.py", "paper", "HO"))["sym"] == "HOZ26"


# ---------------------------------------------------------------- 다시 켤 때 (recover)
def test_재시작_정리는_run_json_의_시장·거래소로_해외_어댑터를_만든다(tmp_path, monkeypatch):
    reg, fake, find, _ = make_reg(tmp_path)
    fake.held = 1
    seen: list[tuple] = []
    real = registry_lib.adapter_for

    def spy(market, api_module, **kw):
        seen.append((market.id, kw))
        return real(market, api_module, **kw)
    monkeypatch.setattr(registry_lib, "adapter_for", spy)
    folder = write_run(tmp_path / "pyruns", f"{TODAY}_fakeho_orders", mode="orders", sym="HOZ26", name="fakeho",
                       market="overseas", exchange="FCME", currency="USD", product="HO")
    assert reg.recover() == [folder.name]
    assert seen == [("overseas", {"exch_cd": "FCME", "cur_cd": "USD"})]
    assert ("ovs_open_interest_page", "") in fake.calls and fake.orders == [] and find.calls == []
    data = read_json(folder / "run.json")
    assert (data["state"], data["ended_reason"]) == ("끝", "재시작 · 확인 필요")
    assert any("잔고 HOZ26 +1계약" in t for t in events(folder))


def test_재시작_정리는_국내_다른_품목도_run_json_의_시장으로(tmp_path):
    fake = FakeKospi()
    fake.held = -1
    reg, _, _, _ = make_reg(tmp_path, fake=fake)
    folder = write_run(tmp_path / "pyruns", f"{TODAY}_fakekospi_orders", mode="orders", sym=KOSPI.sym,
                       name="fakekospi", market="domestic", exchange="KRX", currency="KRW", product="A01")
    assert reg.recover() == [folder.name]
    assert fake.count("domestic_open-interest") == 1 and fake.orders == []
    assert any(f"잔고 {KOSPI.sym} -1계약" in t for t in events(folder))
    assert read_json(folder / "run.json")["ended_reason"] == "재시작 · 확인 필요"


# ---------------------------------------------------------------- 판정 꽂기
def test_Registry_의_판정을_LiveRun_에_그대로_넘긴다(tmp_path):
    judge = FakeJudge()

    def ends(market, sym, now):
        return None
    reg, fake, _, _ = make_reg(tmp_path, judge=judge, day_end=ends)
    run = reg.get(reg.start(RunSpec("fakeho.py", "paper", "HO"))["id"])
    assert run.judge is judge and run.day_end is ends
    assert judge.calls and judge.calls[0][:2] == ("overseas", "HOZ26")
    # 빈 종목(지금 길)에도 꽂는다
    blank = reg.get(reg.start(RunSpec("fakemku.py", "paper", None))["id"])
    assert blank.leg is None and blank.judge is judge and blank.day_end is ends
    # 판정이 종목을 모르면 시작 거부
    judge.source = "unknown"
    with pytest.raises(StartRefused, match="장 시간표에 이 종목이 없습니다"):
        reg.start(RunSpec("fakeho.py", "paper", "HO"))


def test_Registry_의_마스터_확인을_LiveRun_에_그대로_넘긴다(tmp_path):
    judge = FakeJudge(source="unknown")

    def unread(market, sym):
        return False
    reg, fake, _, _ = make_reg(tmp_path, judge=judge, master_knows=unread)
    with pytest.raises(StartRefused, match="종목 마스터를 아직 읽지 못했습니다 — 잠시 뒤 다시 시작하세요"):
        reg.start(RunSpec("fakeho.py", "paper", "HO"))
    judge.source = "table"
    run = reg.get(reg.start(RunSpec("fakeho.py", "paper", "HO"))["id"])
    assert run.master_knows is unread
    plain, _, _, _ = make_reg(tmp_path / "plain")
    assert plain.get(plain.start(RunSpec("fakeho.py", "paper", "HO"))["id"]).master_knows is None


def test_앱의_registry_공장은_운영자_마스터_확인도_꽂는다(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_lib, "_registry", None)
    monkeypatch.setattr(registry_lib.storage, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(registry_lib, "strategies_dir", lambda: tmp_path / "strategies")
    assert registry_lib.registry()._master_knows is opening.default_master_knows


def test_판정을_안_주면_지금_규칙(tmp_path):
    reg, _, _, _ = make_reg(tmp_path)
    run = reg.get(reg.start(RunSpec("fakeho.py", "paper", "HO"))["id"])
    assert run.judge is None and run.day_end is None


def test_앱의_registry_공장은_운영자_판정과_종목_찾기를_꽂는다(tmp_path, monkeypatch):
    """판정 R2: 시험이 만드는 Registry 는 판정 없음(지금 규칙), 앱이 쓰는 `registry()` 만 운영자 판정 — 운영의 유일한 스위치."""
    monkeypatch.setattr(registry_lib, "_registry", None)
    monkeypatch.setattr(registry_lib.storage, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(registry_lib, "strategies_dir", lambda: tmp_path / "strategies")
    reg = registry_lib.registry()
    assert reg._judge is opening.default_judge and reg._day_end is opening.default_day_end
    assert reg._find is products.find_product
    assert reg._other_busy is registry_lib._spread_busy and reg._cross is registry_lib.CROSS_LOCK
    assert reg.root == tmp_path / "state" / "pyruns" and registry_lib.registry() is reg
