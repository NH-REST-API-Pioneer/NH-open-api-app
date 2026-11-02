"""실행 관리(`registry.py`) 시험 — 시작 거부 규칙·폴더 이름·종료 정리·재시작 정리.

`start_thread=False` 로 스레드 없이 `LiveRun` 을 직접 굴리고, 가짜 `api_module`·가짜 `now` 를 씁니다.
가짜 api·전략은 `test_team_pyrun_live.py` 의 것을 그대로 가져다 씁니다.
"""
import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import RunSpec, StartRefused
from backend.team_pyrun.registry import Registry
from tests.test_team_pyrun_live import STRATEGY_SRC, SYM, TODAY, FakeApi, at, bar

FIXTURES = Path(__file__).parent / "fixtures" / "team_pyrun" / "strategies"
OTHER_SYM = "A756C000"


def make_registry(tmp_path, *, now="085000", date=TODAY, env="paper", fake=None, start_thread=False, bb=False, sleep=None):
    """전략 폴더(시험 전략 `fake.py`, 원하면 `strategy_bb.py` 도)와 `Registry`. 시각은 `clock["now"]` 로 옮긴다."""
    folder = tmp_path / "strategies"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    if bb:
        for name in ("strategy.py", "strategy_bb.py"):
            shutil.copy(FIXTURES / name, folder / name)
    fake = fake or FakeApi()
    clock = {"now": at(now, date)}
    reg = Registry(tmp_path / "pyruns", folder, now=lambda: clock["now"], active_env=lambda: env,
                   start_thread=start_thread, api_module=fake, sleep=sleep or (lambda s: None))
    return reg, fake, clock


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_run(root, run_id, *, state="진행 중", mode="paper", sym=SYM, name="fake", trades=()):
    """이미 있는 실행 폴더 하나(`run.json` + 손절·거래 기록)를 만든다."""
    folder = root / run_id
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps(
        {"id": run_id, "file": f"{name}.py", "name": name, "title": "시험", "mode": mode, "sym": sym, "state": state,
         "started_at": "2026-11-03T09:00:00", "ended_at": None, "ended_reason": None, "sha256": "ab" * 32}),
        encoding="utf-8")
    j = Journal(folder / "journal.jsonl")
    for t in trades:
        j.write("trade", **t)
    return folder


def trade(reason="손절", pnl=-10000, date=TODAY):
    return {"side": "buy", "entry": 1335.0, "exit": 1334.0, "entry_time": "090100", "exit_time": "090500",
            "ticks": -10, "pnl": pnl, "fee": 1380, "pnl_after_fee": pnl - 1380, "reason": reason, "exit_date": date}


# ---------------------------------------------------------------- 시작 거부
def test_같은_종목_주문_실행은_하나만(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    first = reg.start(RunSpec("fake.py", "orders", None))
    assert first["id"] == f"{TODAY}_fake_orders" and first["state"] == "대기" and first["sym"] == SYM
    # 종목을 주지 않아도(최근월물으로 풀림), 직접 줘도 같은 종목
    for sym in (None, SYM):
        with pytest.raises(StartRefused, match="이미"):
            reg.start(RunSpec("fake.py", "orders", sym))
    assert fake.orders == [] and len(list((tmp_path / "pyruns").iterdir())) == 1
    # 다른 종목은 된다 (폴더 이름에 종목이 붙음)
    other = reg.start(RunSpec("fake.py", "orders", OTHER_SYM))
    assert other["id"] == f"{TODAY}_fake_orders_{OTHER_SYM}"
    # 끝난 뒤에는 같은 종목을 다시 세울 수 있다 (폴더는 _2)
    reg.stop(first["id"])                          # 스레드가 없는 실행은 바로 끝난다
    assert reg.get(first["id"]).state == "끝"
    again = reg.start(RunSpec("fake.py", "orders", None))
    assert again["id"] == f"{TODAY}_fake_orders_2"


def test_종이_실행은_여러_개_세울_수_있고_폴더가_따로다(tmp_path):
    reg, fake, _ = make_registry(tmp_path, bb=True)
    a = reg.start(RunSpec("strategy_bb.py", "paper", None))
    b = reg.start(RunSpec("strategy_bb.py", "paper", SYM))                  # 최근월물을 직접 줘도 이름에 안 붙는다
    c = reg.start(RunSpec("strategy_bb.py", "paper", OTHER_SYM))
    assert [a["id"], b["id"], c["id"]] == [f"{TODAY}_bb_paper", f"{TODAY}_bb_paper_2", f"{TODAY}_bb_paper_{OTHER_SYM}"]
    assert all((tmp_path / "pyruns" / x["id"] / "run.json").is_file() for x in (a, b, c))
    assert reg.get(a["id"]) is not reg.get(b["id"])
    assert fake.orders == [] and fake.count("domestic_order") == 0
    # 종이 실행은 주문 실행과도 겹치지 않는다
    assert reg.start(RunSpec("fake.py", "orders", None))["state"] == "대기"


def test_주말이나_장_끝난_뒤엔_시작_거부(tmp_path):
    for date, text in (("20261107", "토"), ("20261108", "일")):
        reg, fake, _ = make_registry(tmp_path / text, now="100000", date=date)
        with pytest.raises(StartRefused, match="주말"):
            reg.start(RunSpec("fake.py", "paper", None))
        assert fake.calls == []
    for clock in ("153100", "170000"):
        reg, fake, _ = make_registry(tmp_path / clock, now=clock)
        with pytest.raises(StartRefused, match="장이 끝"):
            reg.start(RunSpec("fake.py", "paper", None))
        assert fake.calls == []
    reg, _, _ = make_registry(tmp_path / "ok", now="153059")        # 끝 시각 직전은 시작할 수 있다
    assert reg.start(RunSpec("fake.py", "paper", None))["state"] == "진행 중"


def test_모의_환경이_아니면_주문_실행_거부(tmp_path):
    for env in ("real", None):
        reg, fake, _ = make_registry(tmp_path / str(env), env=env)
        with pytest.raises(StartRefused, match="모의투자 환경에서만 모의 계좌 실행을 세울 수 있습니다"):
            reg.start(RunSpec("fake.py", "orders", None))
        assert fake.calls == []
        assert reg.start(RunSpec("fake.py", "paper", None))["mode"] == "paper"   # 종이 실행은 주문이 없으니 된다


def test_시작_준비가_거부되면_폴더와_run_json_이_남고_StartRefused(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    fake.held = 1                                                    # 시작 잔고가 남아 있으면 거부
    with pytest.raises(StartRefused, match="잔고 \\+1계약"):
        reg.start(RunSpec("fake.py", "orders", None))
    run = read_json(tmp_path / "pyruns" / f"{TODAY}_fake_orders" / "run.json")
    assert run["state"] == "끝" and "시작 거부" in run["ended_reason"]
    assert fake.orders == [] and reg.get(f"{TODAY}_fake_orders") is None
    fake.held = 0                                                    # 거부된 실행은 같은 종목을 막지 않는다
    assert reg.start(RunSpec("fake.py", "orders", None))["id"] == f"{TODAY}_fake_orders_2"


def test_그날_앞선_실행의_손절을_이어받는다(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    root = tmp_path / "pyruns"
    write_run(root, f"{TODAY}_fake_paper", state="끝", trades=[trade(), trade("익절", 5000)])    # 손절 1
    write_run(root, f"{TODAY}_fake_orders_2", state="끝", mode="orders", trades=[trade()])         # 손절 1 (같은 날·NAME·종목)
    write_run(root, f"{TODAY}_fake_paper_{OTHER_SYM}", state="끝", sym=OTHER_SYM, trades=[trade()])  # 다른 종목
    write_run(root, f"{TODAY}_bb_paper", state="끝", name="bb", trades=[trade()])                  # 다른 전략
    write_run(root, "20261102_fake_paper", state="끝", trades=[trade(date="20261102")])            # 어제
    (root / f"{TODAY}_fake_paper_9").mkdir()                                                         # run.json 없는 폴더
    status = reg.start(RunSpec("fake.py", "paper", None))
    run = reg.get(status["id"])
    assert status["id"] == f"{TODAY}_fake_paper_2"
    assert run.stops_before == 2 and run.runner.strat.day.stops == 2
    assert status["stops"] == 2


# ---------------------------------------------------------------- 종료·재시작
def test_종료하면_돌던_실행을_정리한다(tmp_path):
    reg, fake, clock = make_registry(tmp_path)
    status = reg.start(RunSpec("fake.py", "orders", None))
    run = reg.get(status["id"])
    run.runner.strat.script = {"090000": "buy"}
    fake.chart = [bar("090000")]
    clock["now"] = at("090104")
    run.step(clock["now"])
    assert run.runner.pos is not None and len(fake.orders) == 1 and fake.held == 1
    reg.stop_all(timeout=1)                       # 스레드가 없으니 바로 finish("중지")
    assert [o[1] for o in fake.orders] == ["buy", "sell"] and fake.held == 0
    assert run.state == "끝" and read_json(tmp_path / "pyruns" / status["id"] / "run.json")["state"] == "끝"
    assert (tmp_path / "pyruns" / status["id"] / "summary.json").is_file()
    reg.stop_all(timeout=1)                       # 두 번 불러도 주문은 더 없다
    assert len(fake.orders) == 2


def test_스레드가_돌면_stop_은_바로_돌아오고_stop_all_은_끝날_때까지_기다린다(tmp_path):
    reg, fake, clock = make_registry(tmp_path, start_thread=True, sleep=lambda s: time.sleep(0.01))
    status = reg.start(RunSpec("fake.py", "paper", None))
    run = reg.get(status["id"])
    (thread,) = [t for t in threading.enumerate() if t.name == f"pyrun-{status['id']}"]
    assert thread.is_alive() and thread.daemon
    reg.stop(status["id"])                        # 요청만 한다 — 스레드가 살아 있으니 직접 끝내지 않는다
    assert reg.stop_all(timeout=5) == [] and not thread.is_alive()
    assert run.state == "끝" and run.ended_reason == "중지"


def test_재시작하면_끝나지_않은_실행을_닫는다(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    root = tmp_path / "pyruns"
    fake.held = 1
    orders = write_run(root, f"{TODAY}_fake_orders", mode="orders", trades=[trade(), trade("익절", 5000)])
    paper = write_run(root, f"{TODAY}_fake_paper", state="대기", trades=[trade()])
    done = write_run(root, f"{TODAY}_fake_paper_2", state="끝")
    errored = write_run(root, f"{TODAY}_fake_paper_3", state="오류")
    broken = root / f"{TODAY}_fake_paper_4"
    broken.mkdir()
    (broken / "run.json").write_text("{깨짐", encoding="utf-8")
    (root / "빈폴더").mkdir()
    reg.recover()
    for folder in (orders, paper):
        run = read_json(folder / "run.json")
        assert run["state"] == "끝" and run["ended_reason"] == "재시작"
        summary = read_json(folder / "summary.json")
        assert summary["summary"]["trades"] == len(summary["trades"])
    assert read_json(orders / "summary.json")["summary"]["net_pnl"] == -5000
    events = [r["text"] for r in Journal(orders / "journal.jsonl").read() if r["kind"] == "event"]
    assert any("재시작" in t and "+1" in t for t in events)           # 잔고를 한 번 적는다
    assert fake.count("domestic_open-interest") == 1 and fake.orders == []   # orders 만 한 번 조회, 주문은 없다
    assert [json.loads(x)["purpose"] for x in (orders / "api_log.jsonl").read_text(encoding="utf-8").splitlines()] \
        == ["잔고확인"]
    assert not (paper / "api_log.jsonl").exists()
    assert not [r for r in Journal(paper / "journal.jsonl").read() if r["kind"] == "event"]
    for folder in (done, errored):                                   # 이미 닫힌 건 그대로
        assert not (folder / "summary.json").exists() and read_json(folder / "run.json")["ended_reason"] is None
    assert (broken / "run.json").read_text(encoding="utf-8") == "{깨짐"     # 깨진 건 건드리지 않는다
    reg.recover()                                                      # 두 번째는 할 일이 없다
    assert fake.count("domestic_open-interest") == 1


def test_재시작_정리에서_잔고를_못_읽으면_확인_실패로_적고_summary_는_그대로_둔다(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    fake.oi_error = RuntimeError("연결 실패")
    folder = write_run(tmp_path / "pyruns", f"{TODAY}_fake_orders", mode="orders")
    (folder / "summary.json").write_text('{"keep": 1}', encoding="utf-8")
    reg.recover()
    assert read_json(folder / "run.json")["ended_reason"] == "재시작"
    assert read_json(folder / "summary.json") == {"keep": 1}
    events = [r["text"] for r in Journal(folder / "journal.jsonl").read() if r["kind"] == "event"]
    assert any("확인 실패" in t for t in events) and fake.orders == []


# ---------------------------------------------------------------- 목록·폴더
def test_목록은_도는_것과_폴더를_중복_없이_최근순으로(tmp_path):
    reg, fake, clock = make_registry(tmp_path)
    root = tmp_path / "pyruns"
    old = write_run(root, "20261102_fake_paper", state="끝")
    run_json = read_json(old / "run.json")
    run_json["started_at"] = "2026-11-02T09:00:00"
    (old / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    (root / "깨짐").mkdir()
    (root / "깨짐" / "run.json").write_text("x", encoding="utf-8")
    (root / "없음").mkdir()
    clock["now"] = at("090000")
    live = reg.start(RunSpec("fake.py", "paper", None))
    rows = reg.list()
    assert [r["id"] for r in rows] == [live["id"], "20261102_fake_paper"]
    assert rows[0]["state"] == "진행 중" and "params" in rows[0]         # 도는 실행은 status() 그대로


def test_실행_id_로_폴더_밖을_가리킬_수_없다(tmp_path):
    reg, _, _ = make_registry(tmp_path)
    (tmp_path / "x").mkdir()
    status = reg.start(RunSpec("fake.py", "paper", None))
    assert reg.folder(status["id"]) == tmp_path / "pyruns" / status["id"]
    for bad in ("../x", "..", "", "a/b", "a\\b", f"{status['id']}\n", "없는_실행", f"{TODAY}_fake_paper_99"):
        with pytest.raises(KeyError):
            reg.folder(bad)
    assert reg.get("../x") is None


def test_모르는_실행에_stop_flatten_은_KeyError(tmp_path):
    reg, _, _ = make_registry(tmp_path)
    for call in (reg.stop, reg.flatten):
        with pytest.raises(KeyError):
            call("없는_실행")


def test_파일_이름과_종목_코드에_경로_문자가_있으면_거부(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    for spec in (RunSpec("../fake.py", "paper", None), RunSpec("sub/fake.py", "paper", None),
                 RunSpec("fake.txt", "paper", None), RunSpec("fake.py", "paper", "../x"),
                 RunSpec("fake.py", "paper", "A75 6"), RunSpec("fake.py", "../../x", None),
                 RunSpec("fake.py", "live", None), RunSpec("fake.py", "", None)):
        with pytest.raises(StartRefused):
            reg.start(spec)
    assert not (tmp_path / "pyruns").exists() and fake.calls == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["strategies"]        # 폴더 밖에도 아무것도 안 생겼다


def test_동시에_시작해도_같은_종목_주문_실행은_하나만(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    results: list = []
    barrier = threading.Barrier(6)

    def go():
        barrier.wait()
        try:
            results.append(reg.start(RunSpec("fake.py", "orders", None))["id"])
        except StartRefused as e:
            results.append(e)

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r for r in results if isinstance(r, str)] == [f"{TODAY}_fake_orders"]
    assert len([r for r in results if isinstance(r, StartRefused)]) == 5


def test_최근월물을_모르면_종목을_안_준_시작은_거부하고_경고를_남긴다(tmp_path, caplog):
    reg, fake, _ = make_registry(tmp_path)

    def boom(prd="75"):
        raise RuntimeError("조회 실패")
    fake.all_futures = boom
    for mode in ("orders", "paper"):
        with caplog.at_level("WARNING", logger="backend.team_pyrun.registry"):
            with pytest.raises(StartRefused, match="최근월물을 알 수 없습니다 — 잠시 뒤 다시 시작하세요"):
                reg.start(RunSpec("fake.py", mode, None))
    assert "조회 실패" in caplog.text
    assert not (tmp_path / "pyruns").exists() and fake.orders == []
    # 종목을 직접 줬으면 최근월물을 몰라도 시작할 수 있다(폴더 이름에 종목이 붙는다)
    assert reg.start(RunSpec("fake.py", "paper", SYM))["id"] == f"{TODAY}_fake_paper_{SYM}"


class BlockingApi(FakeApi):
    """`product_detail`(준비 중의 네트워크 호출) 에서 `release` 가 열릴 때까지 멈춘다."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def product_detail(self):
        self.entered.set()
        assert self.release.wait(10)
        return super().product_detail()


def test_준비_중인_실행은_stop_과_stop_all_이_기다리지_않고_준비가_끝나면_주문_없이_끝난다(tmp_path):
    fake = BlockingApi()
    reg, _, _ = make_registry(tmp_path, fake=fake)
    started: dict = {}
    starter = threading.Thread(target=lambda: started.update(status=reg.start(RunSpec("fake.py", "orders", None))))
    starter.start()
    assert fake.entered.wait(5)                                       # prepare() 가 LiveRun 잠금을 쥔 채 멈춰 있다
    run_id = f"{TODAY}_fake_orders"
    run = reg.get(run_id)
    assert run is not None and run.state == "대기"

    def promptly(call, *args):
        t = threading.Thread(target=call, args=args)
        t0 = time.monotonic()
        t.start()
        t.join(2)
        assert not t.is_alive(), "준비 중인 실행의 중지 요청이 잠금에서 기다린다"
        return time.monotonic() - t0
    assert promptly(reg.stop, run_id) < 1
    results: list = []
    assert promptly(lambda: results.append(reg.stop_all(timeout=0.2))) < 1
    assert results == [[run_id]]                                      # 아직 끝나지 않은 실행으로 알린다
    assert run.state == "대기"                                         # 직접 끝내지 않았다
    fake.release.set()
    starter.join(5)
    assert not starter.is_alive()
    assert started["status"]["state"] == "끝" and run.ended_reason == "중지"
    assert read_json(tmp_path / "pyruns" / run_id / "run.json")["state"] == "끝"
    assert fake.orders == [] and fake.count("domestic_order") == 0
    assert not [t for t in threading.enumerate() if t.name == f"pyrun-{run_id}"]      # 스레드 없이 끝났다
    # 끝났으니 같은 종목을 다시 세울 수 있다
    assert reg.start(RunSpec("fake.py", "orders", None))["id"] == f"{run_id}_2"


def test_준비_중_중지_요청이_없으면_스레드가_돈다(tmp_path):
    reg, fake, _ = make_registry(tmp_path, start_thread=True, sleep=lambda s: time.sleep(0.01))
    status = reg.start(RunSpec("fake.py", "paper", None))
    assert status["state"] == "대기"
    assert [t for t in threading.enumerate() if t.name == f"pyrun-{status['id']}"]
    assert reg.stop_all(timeout=5) == []


def test_전략_생성자가_고장나면_빈_폴더_없이_StartRefused(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    src = STRATEGY_SRC.replace("    def __init__(self, p):\n        self.p = p\n",
                               "    def __init__(self, p):\n        COUNT[0] += 1\n"
                               "        if COUNT[0] > 1:\n            raise ValueError('두 번째부터 고장')\n        self.p = p\n")
    src = src.replace('NAME = "fake"', 'NAME = "flaky"\nCOUNT = [0]')
    assert "COUNT[0] += 1" in src
    (tmp_path / "strategies" / "flaky.py").write_text(src, encoding="utf-8")
    with pytest.raises(StartRefused, match="전략을 만들지 못했습니다 — ValueError: 두 번째부터 고장"):
        reg.start(RunSpec("flaky.py", "paper", None))
    assert list((tmp_path / "pyruns").iterdir()) == [] and reg.get(f"{TODAY}_flaky_paper") is None
    assert reg.list() == []


def test_전략_파일을_못_불러오면_LoadError_가_아니라_StartRefused(tmp_path):
    reg, fake, _ = make_registry(tmp_path)
    (tmp_path / "strategies" / "bad.py").write_text("def (:\n", encoding="utf-8")
    for file, text in (("bad.py", "SyntaxError"), ("없는.py", "파일이 없습니다")):
        with pytest.raises(StartRefused, match=f"전략 파일을 불러오지 못했습니다 — .*{text}"):
            reg.start(RunSpec(file, "paper", None))
    assert fake.calls == [] and not (tmp_path / "pyruns").exists()


def test_켜질_때_정리는_방금_세운_실행의_run_json_을_건드리지_않는다(tmp_path):
    """앱이 뜬 직후 시작한 실행(상태 「대기」)을 복구가 「끝·재시작」으로 닫으면 안 된다(R25)."""
    reg, _, _ = make_registry(tmp_path)
    run = reg.start(RunSpec("fake.py", "paper", None))
    path = tmp_path / "pyruns" / run["id"] / "run.json"
    before = path.read_text(encoding="utf-8")
    stale = write_run(tmp_path / "pyruns", "20261029_fake_paper", state="진행 중")
    assert reg.recover() == ["20261029_fake_paper"]
    assert path.read_text(encoding="utf-8") == before and reg.get(run["id"]).state == "대기"
    assert read_json(stale / "run.json")["ended_reason"] == "재시작"
