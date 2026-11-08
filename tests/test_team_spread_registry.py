"""스프레드 실행 관리(`SpreadRegistry`) — 시작 거부, 두 탭 통틀어 종목 하나, 이어받기, 복구, 중지·종료, 월물 교체 예약.

가짜 시세·가짜 해외 api·가짜 실행기 파일(임시 폴더)로 돈다(`test_team_spread_run.py` 의 것을 가져다 씀). `start_thread=False` 가 기본이라
실행은 준비까지만 하고 시험이 직접 굴린다.
"""
import json
import threading
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.team_pyrun.live import RunSpec, StartRefused
from backend.team_pyrun.registry import Registry as PyRegistry
from backend.team_spread.legs import resolve
from backend.team_spread.registry import SpreadRegistry
from backend.team_spread.run import SHUTDOWN_HOLDING, SpreadSpec
from tests.test_team_pyrun_live import STRATEGY_SRC, SYM, at
from tests.test_team_pyrun_live import FakeApi as PyFakeApi
from tests.test_team_spread_run import FAST, NOW, ROWS, Api, Clock, FakeFeed, until

PAIR = 'LEGS = {"ho": "HO", "rb": "RB"}\ndef run(ctx):\n    while ctx.running():\n        ctx.sleep(1)\n'
HOLD = ('LEGS = {"ho": "HO", "rb": "RB"}\ndef run(ctx):\n    ctx.target({"ho": 1, "rb": -1})\n'
        '    while ctx.running():\n        ctx.sleep(1)\n')
USD = 'LEGS = {"usd": "A75", "ho": "HO"}\ndef run(ctx):\n    pass\n'


def runner_folder(tmp_path, **files):
    folder = tmp_path / "spreads_src"
    folder.mkdir(parents=True, exist_ok=True)
    for name, src in ({"s.py": PAIR, **files}).items():
        (folder / name).write_text(src, encoding="utf-8")
    return folder


def make(tmp_path, *, env="paper", api=None, start_thread=False, other_busy=None, cross=None, now=NOW, master=None,
         **files):
    api = api if api is not None else Api()
    reg = SpreadRegistry(tmp_path / "spreads", runner_folder(tmp_path, **files), now=Clock(now), active_env=lambda: env,
                         start_thread=start_thread, api_module=api, sleep=lambda s: None,
                         feed_factory=lambda **kw: FakeFeed(**kw), master=master or (lambda: (ROWS["overseas_rows"], ROWS["domestic_rows"])),
                         timing=FAST, other_busy=other_busy, cross_lock=cross)
    return reg, api


def spec(file="s.py", mode="orders", **kw):
    return SpreadSpec(file, mode, kw.get("syms"), None, None, kw.get("inherit_from"))


def folders(reg):
    return sorted(p.name for p in reg.root.iterdir()) if reg.root.is_dir() else []


def read(path):
    return json.loads(Path(path).read_text("utf-8"))


def leg_dicts(*pairs):
    return [asdict(resolve(n, s, overseas_rows=ROWS["overseas_rows"], domestic_rows=ROWS["domestic_rows"],
                           overseas_details=ROWS["overseas_details"], domestic_details=ROWS["domestic_details"],
                           today="20261109")) for n, s in pairs]


def write_prev(reg, run_id="20261109_S_orders", *, state="끝", mode="orders", inheritable=True, file="s.py",
               reason="앱 종료 · 보유 남음 — 이어받기로 다시", legs=None, **extra):
    folder = reg.root / run_id
    folder.mkdir(parents=True)
    legs = legs if legs is not None else leg_dicts(("ho", "HOZ26"), ("rb", "RBZ26"))
    (folder / "run.json").write_text(json.dumps({
        "id": run_id, "file": file, "name": "S", "title": "t", "mode": mode, "state": state, "sha256": "ab" * 32,
        "started_at": "2026-11-09T09:00:00", "ended_at": None, "ended_reason": reason, "legs": legs,
        "holding_left": {"ho": 1, "rb": -1}, "inheritable": inheritable, **extra}), encoding="utf-8")
    return folder


# ---------------------------------------------------------------- 시작·거부
def test_시작하면_정확한_종목으로_폴더가_생긴다(tmp_path):
    reg, api = make(tmp_path)
    st = reg.start(spec(mode="paper"))
    assert st["id"] == "20261109_s_paper" and st["state"] == "진행 중"
    run = reg.get(st["id"])
    assert run.order_syms() == {"HOZ26", "RBZ26"} and run.spec.syms == {"ho": "HOZ26", "rb": "RBZ26"}
    assert reg.start(spec(mode="paper"))["id"] == "20261109_s_paper_2"
    assert [r["id"] for r in reg.list()] == ["20261109_s_paper_2", "20261109_s_paper"] or len(reg.list()) == 2
    assert reg.folder(st["id"]).is_dir() and api.orders == []
    with pytest.raises(KeyError):
        reg.folder("../x")


@pytest.mark.parametrize("kw,match", [
    (dict(mode="replay"), "방식"), (dict(file="../s.py"), "파일 이름"), (dict(file="nope.py"), "불러오지 못"),
    (dict(syms={"zz": "HO"}), "없는 다리"), (dict(syms={"ho": "XX"}), "다리 ho"), (dict(syms={"ho": "H/O"}), "표기"),
    (dict(inherit_from="x"), "이어받을"),
])
def test_거부는_폴더를_남기지_않는다(tmp_path, kw, match):
    reg, api = make(tmp_path)
    with pytest.raises(StartRefused, match=match):
        reg.start(spec(**{"mode": "orders", **kw}))
    assert folders(reg) == [] and api.orders == []


def test_주말_모의환경아님_앱끄는중_거부(tmp_path):
    reg, _ = make(tmp_path, now=NOW.replace(day=7))
    with pytest.raises(StartRefused, match="주말"):
        reg.start(spec(mode="paper"))
    reg, _ = make(tmp_path / "r", env="real")
    with pytest.raises(StartRefused, match="모의투자 환경"):
        reg.start(spec())
    assert reg.start(spec(mode="paper"))["state"] == "진행 중"       # 종이는 된다
    reg.close_starts()
    with pytest.raises(StartRefused, match="끄는 중"):
        reg.start(spec(mode="paper"))


def test_두_다리가_같은_종목이면_거부(tmp_path):
    reg, _ = make(tmp_path)
    with pytest.raises(StartRefused, match="같은 종목"):
        reg.start(spec(syms={"ho": "RBZ26", "rb": "RBZ26"}))
    assert folders(reg) == []


def test_같은_종목_모의_실행은_하나_종이는_상관없음(tmp_path):
    reg, _ = make(tmp_path)
    first = reg.start(spec())
    with pytest.raises(StartRefused, match="이미"):
        reg.start(spec())
    assert folders(reg) == [first["id"]]
    assert reg.start(spec(mode="paper"))["mode"] == "paper"
    reg.stop(first["id"])
    assert reg.get(first["id"]).state == "끝"
    assert reg.start(spec())["id"] == "20261109_s_orders_2"


# ---------------------------------------------------------------- 두 탭 통틀어
def test_파이썬_전략이_주문_중인_종목은_스프레드가_거부(tmp_path):
    pyapi = PyFakeApi()
    pfolder = tmp_path / "strategies"
    pfolder.mkdir()
    (pfolder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    cross = threading.RLock()
    py = PyRegistry(tmp_path / "pyruns", pfolder, now=lambda: at("085000"),
                    active_env=lambda: "paper", start_thread=False, api_module=pyapi, sleep=lambda s: None, cross_lock=cross)
    reg, api = make(tmp_path, other_busy=lambda s: "파이썬 점유" if py.busy_sym(s) else None, cross=cross,
                    **{"u.py": USD})
    assert py.start(RunSpec("fake.py", "orders", None))["sym"] == SYM
    with pytest.raises(StartRefused, match="파이썬 점유"):
        reg.start(spec("u.py"))
    assert folders(reg) == [] and api.orders == []
    assert reg.start(spec("u.py", mode="paper"))["state"] == "진행 중"      # 종이는 상관없음


def test_스프레드가_주문_중인_종목은_파이썬_전략이_거부(tmp_path):
    pyapi = PyFakeApi()
    pfolder = tmp_path / "strategies"
    pfolder.mkdir()
    (pfolder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    reg, _ = make(tmp_path)

    class Stub:           # A75 를 주문 중인 스프레드 실행
        spec = SpreadSpec("s.py", "orders")
        state, run_id = "진행 중", "stub"

        @staticmethod
        def order_syms():
            return {SYM}
    reg._runs["stub"] = Stub()
    py = PyRegistry(tmp_path / "pyruns", pfolder, now=lambda: at("085000"), active_env=lambda: "paper",
                    start_thread=False, api_module=pyapi, sleep=lambda s: None,
                    other_busy=lambda s: "스프레드 점유" if reg.busy_sym(s) else None, cross_lock=reg._cross)
    with pytest.raises(StartRefused, match="스프레드 점유"):
        py.start(RunSpec("fake.py", "orders", None))
    assert not (tmp_path / "pyruns").exists() or list((tmp_path / "pyruns").iterdir()) == []
    Stub.state = "끝"
    assert py.start(RunSpec("fake.py", "orders", None))["state"] == "대기"


def test_pyrun_갈고리가_없으면_동작_그대로(tmp_path):
    pfolder = tmp_path / "strategies"
    pfolder.mkdir()
    (pfolder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    py = PyRegistry(tmp_path / "pyruns", pfolder, now=lambda: at("085000"), active_env=lambda: "paper",
                    start_thread=False, api_module=PyFakeApi(), sleep=lambda s: None)
    assert py.start(RunSpec("fake.py", "orders", None))["state"] == "대기"
    assert py.busy_sym(SYM) and py.busy_sym("ZZZ") is None


# ---------------------------------------------------------------- 이어받기
def test_이어받기_미리보기와_성공(tmp_path):
    reg, api = make(tmp_path)
    prev = write_prev(reg).name
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    pv = reg.inherit_preview(prev)
    assert pv["legs"]["ho"] == {"sym": "HOZ26", "qty": 1, "avg_price": None} and pv["legs"]["rb"]["qty"] == -1
    assert pv["ended_reason"].startswith("앱 종료") and pv["warning"] is None
    st = reg.start(spec(inherit_from=prev), expect={"ho": 1, "rb": -1})
    run = reg.get(st["id"])
    assert run.inherited == {"from": prev, "ended_reason": pv["ended_reason"],
                             "legs": {"ho": {"qty": 1, "avg_price": None}, "rb": {"qty": -1, "avg_price": None}}}
    assert read(reg.root / prev / "run.json")["handed_to"] == st["id"] and read(reg.root / st["id"] / "run.json")["inherited_from"] == prev
    assert api.orders == []
    with pytest.raises(StartRefused, match="이미"):                      # 같은 실행을 두 번 이어받지 못함
        reg.start(spec(inherit_from=prev), expect={"ho": 1, "rb": -1})


def test_이어받기_평균가는_앞선_요약에서(tmp_path):
    reg, api = make(tmp_path)
    prev = write_prev(reg)
    (prev / "summary.json").write_text(json.dumps({"legs": [{"name": "ho", "avg_price": 4.4}, {"name": "rb", "avg_price": None}]}))
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    assert reg.inherit_preview(prev.name)["legs"]["ho"]["avg_price"] == 4.4


def test_확인과_시작_사이에_잔고가_바뀌면_시작하지_않는다(tmp_path):
    reg, api = make(tmp_path)
    prev = write_prev(reg).name
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    seen = {k: v["qty"] for k, v in reg.inherit_preview(prev)["legs"].items()}
    api.pos = {"HOZ26": 1, "RBZ26": 0}                                   # 그 사이 바뀜
    with pytest.raises(StartRefused, match="바뀌었습니다"):
        reg.start(spec(inherit_from=prev), expect=seen)
    assert folders(reg) == [prev] and "handed_to" not in read(reg.root / prev / "run.json")
    api.pos = {"HOZ26": 1, "RBZ26": -1}                                  # 거부는 표를 남기지 않는다 — 다시 된다
    assert reg.start(spec(inherit_from=prev), expect=seen)["state"] == "진행 중"


def test_이어받기_거부들(tmp_path):
    reg, api = make(tmp_path, **{"t.py": PAIR})
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    ok = {"ho": 1, "rb": -1}
    cases = {
        "20261109_A_orders": (dict(inheritable=False), "보유가 없"),
        "20261109_B_orders": (dict(state="진행 중"), "끝나지 않은"),
        "20261109_C_orders": (dict(mode="paper"), "모의 계좌 실행만"),
        "20261109_D_orders": (dict(file="t.py"), "다른 실행기 파일"),
        "20261109_E_orders": (dict(handed_to="x"), "이미"),
        "20261109_F_orders": (dict(legs=leg_dicts(("ho", "HOF27"), ("rb", "RBZ26"))), "다리 종목"),
    }
    for rid, (kw, _) in cases.items():
        write_prev(reg, rid, **kw)
    for rid, (_, match) in cases.items():
        with pytest.raises(StartRefused, match=match):
            reg.start(spec(inherit_from=rid), expect=ok)
        if rid != "20261109_D_orders":              # 미리보기는 자기 파일·종목으로 보므로 파일·종목 다름은 시작에서만 걸린다
            if rid != "20261109_F_orders":
                with pytest.raises(StartRefused, match=match):
                    reg.inherit_preview(rid)
    assert set(folders(reg)) == set(cases)            # 거부된 시작은 새 폴더를 남기지 않는다
    write_prev(reg, "20261109_G_orders")
    with pytest.raises(StartRefused, match="expect"):
        reg.start(spec(inherit_from="20261109_G_orders"))
    with pytest.raises(StartRefused, match="다리 종목"):                  # 다른 종목을 고르면
        reg.start(spec(inherit_from="20261109_G_orders", syms={"ho": "HOF27"}), expect=ok)
    with pytest.raises(StartRefused, match="찾지 못"):
        reg.start(spec(inherit_from="20261109_NOPE_orders"), expect=ok)
    with pytest.raises(StartRefused, match="모의 계좌 실행만"):
        reg.start(spec(mode="paper", inherit_from="20261109_G_orders"), expect=ok)


def test_멈춘_실행의_미리보기에는_주문내역_경고(tmp_path):
    reg, api = make(tmp_path)
    api.pos = {"HOZ26": 1, "RBZ26": 0}
    prev = write_prev(reg, reason="실행기가 끝냄 · 정리 안 함 — 확인 필요: 결과 모름", halted="결과 모름").name
    assert "주문내역을 먼저 확인하세요" in reg.inherit_preview(prev)["warning"]


# ---------------------------------------------------------------- 복구
def test_복구_보유가_있으면_확인_필요_이어받을_수_있다(tmp_path):
    reg, api = make(tmp_path)
    for i, state in enumerate(("진행 중", "정리 대기")):
        write_prev(reg, f"20261109_{i}_orders", state=state, reason=None, inheritable=False, holding_left={})
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    assert len(reg.recover()) == 2
    for rid in folders(reg):
        d = read(reg.root / rid / "run.json")
        assert d["state"] == "끝" and d["ended_reason"] == "재시작 · 확인 필요"
        assert d["holding_left"] == {"ho": 1, "rb": -1} and d["inheritable"] is True
        assert (reg.root / rid / "summary.json").is_file()
    assert api.orders == []
    rid = folders(reg)[0]
    pv = reg.inherit_preview(rid)                                          # 이어받기로만 다시 세운다
    assert reg.start(spec(inherit_from=rid), expect={k: v["qty"] for k, v in pv["legs"].items()})["state"] == "진행 중"


def test_복구_평탄이면_재시작_이어받기_아님(tmp_path):
    reg, api = make(tmp_path)
    rid = write_prev(reg, state="준비", reason=None, inheritable=False).name
    assert reg.recover() == [rid]
    d = read(reg.root / rid / "run.json")
    assert d["ended_reason"] == "재시작" and d["inheritable"] is False and d["holding_left"] == {} and d["state"] == "끝"
    with pytest.raises(StartRefused):
        reg.inherit_preview(rid)


def test_복구_잔고를_못_읽으면_확인_필요(tmp_path):
    reg, api = make(tmp_path)
    rid = write_prev(reg, state="진행 중", reason=None, inheritable=False).name
    api.ovs_open_interest_page = lambda nxt_key="": (_ for _ in ()).throw(RuntimeError("끊김"))
    assert reg.recover() == [rid]
    d = read(reg.root / rid / "run.json")
    assert d["ended_reason"] == "재시작 · 확인 필요" and d["inheritable"] is True and d["balance_unread"] is True


def test_복구_종이와_끝난것_도는것은_건드리지_않는다(tmp_path):
    reg, api = make(tmp_path)
    paper = write_prev(reg, "20261109_P_paper", state="진행 중", mode="paper", inheritable=False, reason=None).name
    done = write_prev(reg, "20261109_D_orders", state="끝", reason="끝").name
    live = reg.start(spec("s.py", mode="paper"))["id"]
    calls = len(api.calls)
    api.pos = {"HOZ26": 3}
    assert reg.recover() == [paper]
    assert read(reg.root / paper / "run.json")["ended_reason"] == "재시작" and len(api.calls) == calls
    assert read(reg.root / done / "run.json")["ended_reason"] == "끝"
    assert reg.get(live).state == "진행 중" and read(reg.root / live / "run.json")["state"] == "진행 중"
    assert reg.recover() == []


# ---------------------------------------------------------------- 중지·종료
def test_stop은_스레드_없는_실행을_바로_끝낸다(tmp_path):
    reg, _ = make(tmp_path)
    rid = reg.start(spec(mode="paper"))["id"]
    reg.stop(rid)
    assert reg.get(rid).state == "끝" and read(reg.root / rid / "run.json")["state"] == "끝"
    with pytest.raises(KeyError):
        reg.stop("nope")


def test_stop_all은_보유를_두고_끝내며_finish를_부르지_않는다(tmp_path):
    reg, api = make(tmp_path, start_thread=True, **{"h.py": HOLD})
    rid = reg.start(spec("h.py"))["id"]
    until(lambda: api.pos.get("HOZ26") == 1 and api.pos.get("RBZ26") == -1)
    assert reg.stop_all(timeout=5) == []
    run = reg.get(rid)
    until(lambda: run.state == "끝")
    d = read(reg.root / rid / "run.json")
    assert d["ended_reason"] == SHUTDOWN_HOLDING and d["inheritable"] is True and d["holding_left"] == {"ho": 1, "rb": -1}
    assert api.pos == {"HOZ26": 1, "RBZ26": -1} and len(api.orders) == 2          # 정리 주문 없음
    with pytest.raises(StartRefused, match="끄는 중"):
        reg.start(spec(mode="paper"))
    # 다시 켠 뒤 이어받기로만 다시 세운다
    reg2, _ = make(tmp_path, api=api, **{"h.py": HOLD})
    pv = reg2.inherit_preview(rid)
    assert reg2.start(spec("h.py", inherit_from=rid), expect={k: v["qty"] for k, v in pv["legs"].items()})["state"] == "진행 중"


def test_stop_all_스레드_없는_미끝_실행은_pending(tmp_path):
    reg, _ = make(tmp_path)
    rid = reg.start(spec(mode="paper"))["id"]
    assert reg.stop_all(timeout=0.1) == [rid] and reg.get(rid).state == "진행 중"      # finish 안 부름


# ---------------------------------------------------------------- 월물 교체
def test_roll_guard_다른_실행이_잡은_종목은_거부_통과하면_예약(tmp_path):
    reg, _ = make(tmp_path, **{"t.py": 'LEGS = {"x": "HOF27"}\ndef run(ctx):\n    pass\n',
                               "u.py": 'LEGS = {"y": "RBF27"}\ndef run(ctx):\n    pass\n'})
    a = reg.get(reg.start(spec())["id"])
    b = reg.get(reg.start(spec("t.py"))["id"])
    with pytest.raises(StartRefused, match="이미"):
        a._roll_guard("HOF27")                                          # b 가 주문 중
    a._roll_guard("RBF27")                                              # 통과 — 예약
    with pytest.raises(StartRefused, match="이미"):
        reg.start(spec("u.py"))                                         # a.order_syms() 가 아직 옛 종목이어도 막힘
    assert b.order_syms() == {"HOF27"}
    reg.stop(a.run_id)                                                  # 끝난 실행의 예약은 풀린다
    assert reg.start(spec("u.py"))["state"] == "진행 중"


def test_roll_guard_두_실행이_같은_새_종목을_다투면_하나만(tmp_path):
    reg, _ = make(tmp_path, **{"t.py": 'LEGS = {"x": "HOG27"}\ndef run(ctx):\n    pass\n'})
    a, b = (reg.get(reg.start(spec(f))["id"]) for f in ("s.py", "t.py"))
    results, gate = [], threading.Barrier(2)

    def go(run):
        gate.wait()
        try:
            run._roll_guard("RBG27")
            results.append("ok")
        except StartRefused:
            results.append("refused")
    ts = [threading.Thread(target=go, args=(r,)) for r in (a, b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == ["ok", "refused"]


def test_roll_guard_다른_탭이_잡은_종목도_거부(tmp_path):
    reg, _ = make(tmp_path, other_busy=lambda s: "파이썬 점유" if s == "HOF27" else None)
    a = reg.get(reg.start(spec())["id"])
    with pytest.raises(StartRefused, match="파이썬 점유"):
        a._roll_guard("HOF27")
    a._roll_guard("HOG27")


# ---------------------------------------------------------------- 고침 1회
def with_avg(api, avgs):
    """가짜 api 의 잔고 줄에 계좌 평균가(`avg_pric`) 칸을 붙인다."""
    orig = api.ovs_open_interest_page

    def page(nxt_key=""):
        rows, nxt = orig(nxt_key)
        return [{**r, "avg_pric": avgs[r["sym"]]} if r["sym"] in avgs else r for r in rows], nxt
    api.ovs_open_interest_page = page


def test_이어받기_평균가는_계좌_평균가가_먼저_앞선_기록은_없을_때만(tmp_path):
    reg, api = make(tmp_path)
    prev = write_prev(reg)
    (prev / "summary.json").write_text(json.dumps({"legs": [{"name": "ho", "avg_price": 4.4}, {"name": "rb", "avg_price": 2.5}]}))
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    with_avg(api, {"HOZ26": "4.4100"})
    pv = reg.inherit_preview(prev.name)
    assert pv["legs"]["ho"]["avg_price"] == 4.41 and pv["legs"]["rb"]["avg_price"] == 2.5     # 계좌 먼저, 없으면 앞선 기록
    run = reg.get(reg.start(spec(inherit_from=prev.name), expect={"ho": 1, "rb": -1})["id"])
    assert {n: v["avg_price"] for n, v in run.inherited["legs"].items()} == {"ho": 4.41, "rb": 2.5}   # 미리보기와 같은 값


def test_복구한_실행을_이어받아도_계좌_평균가가_산다(tmp_path):
    reg, api = make(tmp_path)
    rid = write_prev(reg, state="진행 중", reason=None, inheritable=False).name
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    with_avg(api, {"HOZ26": "4.4100", "RBZ26": "2.3000"})
    reg.recover()
    assert {n: v["avg_price"] for n, v in reg.inherit_preview(rid)["legs"].items()} == {"ho": 4.41, "rb": 2.3}


def test_종이_실행은_월물_교체_가드가_없다(tmp_path):
    reg, _ = make(tmp_path, **{"t.py": 'LEGS = {"x": "HOF27"}\ndef run(ctx):\n    pass\n'})
    reg.start(spec("t.py"))                                              # 주문 실행이 HOF27 을 잡고 있다
    paper = reg.get(reg.start(spec(mode="paper"))["id"])
    assert paper._roll_guard is None
    assert paper._roll("ho").sym == "HOF27"


def test_다리_조회가_실패하면_StartRefused(tmp_path):
    def boom():
        raise OSError("마스터 없음")
    reg, _ = make(tmp_path, master=boom)
    with pytest.raises(StartRefused, match="다리를 찾지 못했습니다"):
        reg.start(spec(mode="paper"))
    reg, api = make(tmp_path / "b")
    api.ovs_product_detail_page = lambda g, k="": (_ for _ in ()).throw(RuntimeError("끊김"))
    with pytest.raises(StartRefused, match="다리를 찾지 못했습니다"):
        reg.start(spec(mode="paper"))
    assert folders(reg) == []


def test_handed_to를_쓰기_전에_죽어도_두_번_이어받지_못한다(tmp_path):
    reg, api = make(tmp_path)
    prev = write_prev(reg).name
    other = write_prev(reg, "20261109_X_orders", state="끝", inheritable=False)         # 이어받은 새 실행의 기록
    d = read(other / "run.json")
    d["inherited_from"] = prev
    (other / "run.json").write_text(json.dumps(d))
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    with pytest.raises(StartRefused, match="이미"):
        reg.start(spec(inherit_from=prev), expect={"ho": 1, "rb": -1})
    with pytest.raises(StartRefused, match="이미"):
        reg.inherit_preview(prev)


def test_경고는_기계용_칸으로_말이_다르다(tmp_path):
    reg, api = make(tmp_path)
    api.pos = {"HOZ26": 1, "RBZ26": 0}
    halted = write_prev(reg, "20261109_H_orders", reason="x", halted="결과 모름").name
    unread = write_prev(reg, "20261109_U_orders", reason="x", balance_unread=True).name
    plain = write_prev(reg, "20261109_P_orders", reason="재시작 · 확인 필요").name
    wh, wu = reg.inherit_preview(halted)["warning"], reg.inherit_preview(unread)["warning"]
    assert "주문내역을 먼저 확인하세요" in wh and "멈췄" in wh
    assert "잔고를 읽지 못" in wu and wu != wh
    assert reg.inherit_preview(plain)["warning"] is None                  # 글자만 보고 경고하지 않는다


@pytest.mark.parametrize("bad", ["1", True, 1.0, None])
def test_expect_값이_정수가_아니면_거부(tmp_path, bad):
    reg, api = make(tmp_path)
    prev = write_prev(reg).name
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    with pytest.raises(StartRefused, match="expect"):
        reg.start(spec(inherit_from=prev), expect={"ho": bad, "rb": -1})
    assert folders(reg) == [prev]


def test_시작을_거부당한_이어받기_기록은_이어받기로_세지_않는다(tmp_path):
    reg, api = make(tmp_path)
    prev = write_prev(reg).name
    ref = write_prev(reg, "20261109_R_orders", inheritable=False, reason="시작 거부: 잔고가 바뀜")
    d = read(ref / "run.json")
    d["inherited_from"] = prev
    (ref / "run.json").write_text(json.dumps(d))
    api.pos = {"HOZ26": 1, "RBZ26": -1}
    assert reg.start(spec(inherit_from=prev), expect={"ho": 1, "rb": -1})["state"] == "진행 중"
