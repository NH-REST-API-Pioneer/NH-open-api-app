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
from backend.team_pyrun.live import LiveRun, RunSpec, StartRefused
from backend.team_pyrun.realtime import RealtimeRun
from backend.team_pyrun.registry import Registry
from tests.test_team_pyrun_live import STRATEGY_SRC, SYM, TODAY, FakeApi, at, bar
from tests.test_team_pyrun_live_overseas import MKU_SRC, FakeLive, no_master_find

FIXTURES = Path(__file__).parent / "fixtures" / "team_pyrun" / "strategies"
OTHER_SYM = "A756C000"
KRX_SYM = SYM           # 실시간 전략이 시세로만 보는 KRX 종목 (국내 최근월물)


def make_registry(tmp_path, *, now="085000", date=TODAY, env="paper", fake=None, start_thread=False, bb=False, sleep=None,
                  find=no_master_find):
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
                   start_thread=start_thread, api_module=fake, sleep=sleep or (lambda s: None), find=find)
    return reg, fake, clock


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_run(root, run_id, *, state="진행 중", mode="paper", sym=SYM, name="fake", trades=(), **extra):
    """이미 있는 실행 폴더 하나(`run.json` + 손절·거래 기록)를 만든다. `extra` 는 run.json 에 더 넣을 칸(`kind` 등)."""
    folder = root / run_id
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps(
        {"id": run_id, "file": f"{name}.py", "name": name, "title": "시험", "mode": mode, "sym": sym, "state": state,
         "started_at": "2026-11-03T09:00:00", "ended_at": None, "ended_reason": None, "sha256": "ab" * 32, **extra}),
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
    write_run(root, f"{TODAY}_fake_paper_3", state="끝", trades=[trade()])                         # 손절 1 (같은 날·NAME·종목·방식)
    write_run(root, f"{TODAY}_fake_orders_2", state="끝", mode="orders", trades=[trade()])         # 다른 방식(R28)
    write_run(root, f"{TODAY}_fake_paper_{OTHER_SYM}", state="끝", sym=OTHER_SYM, trades=[trade()])  # 다른 종목
    write_run(root, f"{TODAY}_bb_paper", state="끝", name="bb", trades=[trade()])                  # 다른 전략
    write_run(root, "20261102_fake_paper", state="끝", trades=[trade(date="20261102")])            # 어제
    (root / f"{TODAY}_fake_paper_9").mkdir()                                                         # run.json 없는 폴더
    status = reg.start(RunSpec("fake.py", "paper", None))
    run = reg.get(status["id"])
    assert status["id"] == f"{TODAY}_fake_paper_2"
    assert run.stops_before == 2 and run.runner.strat.day.stops == 2
    assert status["stops"] == 2


def test_손절_이어받기는_같은_방식의_폴더만_센다(tmp_path):
    """R28: 종이 실행의 손절이 모의 계좌 실행의 하루 손절 한도를 쓰지 않고, 반대도 마찬가지."""
    reg, fake, _ = make_registry(tmp_path)
    root = tmp_path / "pyruns"
    write_run(root, f"{TODAY}_fake_paper", state="끝", trades=[trade(), trade()])                  # 종이 손절 2
    write_run(root, f"{TODAY}_fake_orders", state="끝", mode="orders", trades=[trade()])           # 모의 계좌 손절 1
    orders = reg.get(reg.start(RunSpec("fake.py", "orders", None))["id"])
    assert orders.stops_before == 1
    paper = reg.get(reg.start(RunSpec("fake.py", "paper", None))["id"])
    assert paper.stops_before == 2


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
    # 잔고가 남은 모의 계좌 실행은 「확인 필요」를 붙여 닫는다 (종이는 계좌가 없으니 그대로)
    for folder, why in ((orders, "재시작 · 확인 필요"), (paper, "재시작")):
        run = read_json(folder / "run.json")
        assert run["state"] == "끝" and run["ended_reason"] == why
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
    assert read_json(folder / "run.json")["ended_reason"] == "재시작 · 확인 필요"      # 잔고를 못 읽음
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


def test_미국달러선물이_아닌_종목은_거부(tmp_path):
    """설계 4.1(의도한 바뀜): 미국달러선물(`A75…`)·MKU(`MKU…`) 코드가 아닌 종목은 종목 찾기(`find`)가 정한다 — 찾지 못하면
    그 글로 거부(여기서는 마스터를 읽지 않는 가짜). 국내 틱 전략에 MKU 종목을 주면 시장 가드가 거부한다(해외는
    `test_team_pyrun_live_overseas.py`)."""
    reg, fake, _ = make_registry(tmp_path)
    for sym in ("A016B000", "B756B000", "a756B000"):
        with pytest.raises(StartRefused, match=f"종목 「{sym}」 을 마스터에서 찾지 못했습니다"):
            reg.start(RunSpec("fake.py", "paper", sym))
    with pytest.raises(StartRefused, match="종목의 시장과 전략 틱이 맞지 않습니다"):
        reg.start(RunSpec("fake.py", "paper", "MKUX26"))
    assert not (tmp_path / "pyruns").exists() and fake.calls == []
    assert reg.start(RunSpec("fake.py", "paper", OTHER_SYM))["sym"] == OTHER_SYM      # A75… 는 그대로 받는다


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


# ================================================================ 실시간·해외 실행 (Task 9)
MKU = "MKUX26"          # 해외 마스터 시험 줄의 최근월물
MKU_NEXT = "MKUZ26"     # 그 다음 월물
RT_FILE = FIXTURES.parent / "realtime" / "strategy_rt_fake.py"


class 둘다(FakeLive):
    """국내(`FakeApi`)·해외(`FakeLive`) 이름을 다 가진 가짜 — 해외 이름은 이 객체, 없는 이름은 국내 가짜(`dom`)로."""

    def __init__(self):
        super().__init__()
        self.dom = FakeApi()

    def __getattr__(self, name):
        dom = self.__dict__.get("dom")
        if dom is None:
            raise AttributeError(name)
        return getattr(dom, name)


class 빈원문:
    """원문이 오지 않는 가짜 구독. `get` 은 잠깐 쉬고 None, `close` 는 닫힘만 적는다."""

    def __init__(self, run_id, wants):
        self.run_id, self.wants = run_id, list(wants)
        self.closed = False
        self.overflow = False
        self.pending = 0

    def get(self, timeout=None):
        time.sleep(min(timeout or 0.0, 0.01))
        return None

    def close(self):
        self.closed = True


def make_rt_registry(tmp_path, *, now="085000", date=TODAY, env="paper", start_thread=False):
    """국내 1분봉(`fake.py`)·해외 1분봉(`fakemku.py`)·실시간(`strategy_rt_fake.py`) 전략과, 국내·해외 이름을 다 가진
    가짜 api, 가짜 원문 구독을 쓰는 `Registry`."""
    folder = tmp_path / "strategies"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fake.py").write_text(STRATEGY_SRC, encoding="utf-8")
    (folder / "fakemku.py").write_text(MKU_SRC, encoding="utf-8")
    shutil.copy(RT_FILE, folder / "strategy_rt_fake.py")
    fake = 둘다()
    clock = {"now": at(now, date)}
    feeds: list[빈원문] = []

    def factory(run_id, wants):
        feed = 빈원문(run_id, wants)
        feeds.append(feed)
        return feed

    reg = Registry(tmp_path / "pyruns", folder, now=lambda: clock["now"], active_env=lambda: env,
                   start_thread=start_thread, api_module=fake, sleep=lambda s: None, feed_factory=factory,
                   find=no_master_find)
    return reg, fake, clock, feeds


def rt(mode="orders", sym=None, signal_sym=KRX_SYM):
    return RunSpec("strategy_rt_fake.py", mode, sym, signal_sym)


def test_실시간_전략은_RealtimeRun_으로_세우고_원문을_구독한다(tmp_path):
    reg, fake, _, feeds = make_rt_registry(tmp_path)
    status = reg.start(rt())
    run = reg.get(status["id"])
    assert isinstance(run, RealtimeRun) and status["kind"] == "realtime"
    assert status["id"] == f"{TODAY}_rtfake_orders" and status["sym"] == MKU and status["signal_sym"] == KRX_SYM
    assert (status["market"], status["currency"], status["state"]) == ("overseas", "USD", "대기")
    assert [f.run_id for f in feeds] == [status["id"]]
    assert [(w.api_id, w.sym) for w in feeds[0].wants] == [("KA", KRX_SYM), ("FB", MKU), ("FA", MKU)]
    data = read_json(tmp_path / "pyruns" / status["id"] / "run.json")
    assert (data["kind"], data["signal_sym"], data["market"]) == ("realtime", KRX_SYM, "overseas")
    # 1분봉 전략은 여전히 LiveRun
    minute = reg.get(reg.start(RunSpec("fakemku.py", "paper", None))["id"])
    assert isinstance(minute, LiveRun) and minute.status()["kind"] == "minute"
    assert fake.orders == []


def test_신호_종목_빈칸이면_국내_최근월물(tmp_path):
    reg, fake, _, feeds = make_rt_registry(tmp_path)
    for blank in (None, ""):
        status = reg.start(rt("paper", signal_sym=blank))
        assert status["signal_sym"] == SYM
    assert all(f.wants[0].sym == SYM for f in feeds)


@pytest.mark.parametrize("spec,why", [
    (RunSpec("fakemku.py", "paper", None, KRX_SYM), "실시간"),          # 1분봉 전략에 신호 종목
    (RunSpec("strategy_rt_fake.py", "paper", None, MKU), "A75"),       # 신호 종목이 MKU
    (RunSpec("strategy_rt_fake.py", "paper", None, "../A75"), "종목 코드"),
    (RunSpec("strategy_rt_fake.py", "paper", KRX_SYM, None), "시장"),   # 실시간 주문 종목이 A75
])
def test_신호_종목·주문_종목이_틀리면_폴더_없이_거부(tmp_path, spec, why):
    reg, fake, _, feeds = make_rt_registry(tmp_path)
    with pytest.raises(StartRefused, match=why):
        reg.start(spec)
    assert feeds == [] and not (tmp_path / "pyruns").exists() and fake.orders == []


@pytest.mark.parametrize("spec,why", [
    (RunSpec("strategy_rt_fake.py", "orders", "MKU", KRX_SYM), "실시간 실행은 MKU 종목 코드"),       # 주문 종목이 뿌리
    (RunSpec("strategy_rt_fake.py", "orders", MKU, "A75"), r"신호 종목\(KRX\)은 미국달러선물 종목 코드"),  # 신호 종목이 뿌리
])
def test_실시간_종목_칸의_품목_뿌리는_폴더_없이_거부(tmp_path, spec, why):
    """뿌리(`MKU`)가 그대로 주문 종목이 되면 주문이 「MKU」로 나가고 잔고 줄(`MKUX26`)과 맞지 않아 잔고 관문이 눈이 먼다 —
    실시간 실행은 품목을 찾지 않으므로 정확한 종목 코드만 받는다."""
    reg, fake, _, feeds = make_rt_registry(tmp_path)
    with pytest.raises(StartRefused, match=why) as e:
        reg.start(spec)
    assert "품목 뿌리는 받지 않습니다" in str(e.value)
    assert feeds == [] and not (tmp_path / "pyruns").exists() and fake.orders == []


def test_시험의_registry_싱글턴도_실제_마스터를_읽지_않는다():
    """conftest 가 세우는 `registry()` 자리의 종목 찾기는 거부하는 가짜 — 사용자의 `~/NHFutures/master` 를 읽지 않게."""
    from backend.team_pyrun import registry as registry_lib
    assert registry_lib.registry()._find is no_master_find


def test_같은_MKU_주문_실행은_1분봉·실시간_통틀어_하나(tmp_path):
    # ① 1분봉(ORB 자리) MKU 모의 계좌 실행이 있으면 실시간 MKU 모의 계좌 실행은 거부
    reg, fake, _, feeds = make_rt_registry(tmp_path / "a")
    minute = reg.start(RunSpec("fakemku.py", "orders", None))
    assert minute["sym"] == MKU
    for sym in (None, MKU):
        with pytest.raises(StartRefused, match=f"같은 종목 {MKU} .*이미"):
            reg.start(rt(sym=sym))
    assert feeds == [] and sorted(p.name for p in (tmp_path / "a" / "pyruns").iterdir()) == [minute["id"]]
    assert reg.start(rt("paper"))["state"] == "대기"                   # 종이는 막지 않는다
    assert reg.start(rt(sym=MKU_NEXT))["sym"] == MKU_NEXT              # 다른 월물은 된다
    # ② 거꾸로 — 실시간이 먼저면 1분봉 MKU 모의 계좌 실행이 거부
    reg, fake, _, feeds = make_rt_registry(tmp_path / "b")
    first = reg.start(rt())
    for sym in (None, MKU):
        with pytest.raises(StartRefused, match="이미"):
            reg.start(RunSpec("fakemku.py", "orders", sym))
    with pytest.raises(StartRefused, match="이미"):                   # 실시간 둘째도
        reg.start(rt(signal_sym=None))
    # 실시간이 시세로만 보는 KRX 종목은 막지 않는다 — 국내 1분봉 모의 계좌 실행은 된다
    domestic = reg.start(RunSpec("fake.py", "orders", None))
    assert domestic["sym"] == SYM == first["signal_sym"]
    # 끝나면 같은 MKU 를 다시 세울 수 있다
    reg.stop(first["id"])
    assert reg.get(first["id"]).state == "끝"
    assert reg.start(RunSpec("fakemku.py", "orders", None))["sym"] == MKU
    assert fake.orders == []


def test_해외_끝_시각_뒤엔_폴더_없이_시작_거부(tmp_path):
    # 해외 1분봉 — 끝 23:55 (국내 15:31 이 지나도 해외는 된다)
    reg, fake, _, _ = make_rt_registry(tmp_path / "late", now="235500")
    with pytest.raises(StartRefused, match="23:55"):
        reg.start(RunSpec("fakemku.py", "paper", None))
    assert fake.calls == [] and not (tmp_path / "late" / "pyruns").exists()
    reg, _, _, _ = make_rt_registry(tmp_path / "evening", now="170000")
    assert reg.start(RunSpec("fakemku.py", "paper", None))["market"] == "overseas"
    with pytest.raises(StartRefused, match="15:31"):                    # 국내는 그대로 15:31
        reg.start(RunSpec("fake.py", "paper", None))
    # 실시간 — 끝 = 전략 flatten_at 15:40 + 5분
    reg, fake, _, feeds = make_rt_registry(tmp_path / "rt", now="154500")
    with pytest.raises(StartRefused, match="15:45"):
        reg.start(rt("paper"))
    assert fake.calls == [] and feeds == [] and not (tmp_path / "rt" / "pyruns").exists()
    reg, _, _, _ = make_rt_registry(tmp_path / "rt_ok", now="154459")
    assert reg.start(rt("paper"))["state"] == "진행 중"


def test_모의_환경이_아니면_실시간_주문_실행도_폴더_없이_거부(tmp_path):
    for env in ("real", None):
        reg, fake, _, feeds = make_rt_registry(tmp_path / str(env), env=env)
        with pytest.raises(StartRefused, match="모의투자 환경에서만"):
            reg.start(rt())
        assert fake.calls == [] and feeds == [] and not (tmp_path / str(env) / "pyruns").exists()
        assert reg.start(rt("paper"))["mode"] == "paper"


def test_실시간·MKU_폴더_이름도_최근월물이_아닐_때만_종목을_붙인다(tmp_path):
    reg, _, _, _ = make_rt_registry(tmp_path)
    ids = [reg.start(spec)["id"] for spec in (
        rt("paper"), rt("paper", sym=MKU), rt("paper", sym=MKU_NEXT),
        rt("paper", signal_sym="A756C000"),                              # 신호 종목은 이름에 안 붙는다
        RunSpec("fakemku.py", "paper", None), RunSpec("fakemku.py", "paper", MKU),
        RunSpec("fakemku.py", "paper", MKU_NEXT))]
    assert ids == [f"{TODAY}_rtfake_paper", f"{TODAY}_rtfake_paper_2", f"{TODAY}_rtfake_paper_{MKU_NEXT}",
                   f"{TODAY}_rtfake_paper_3", f"{TODAY}_fakemku_paper", f"{TODAY}_fakemku_paper_2",
                   f"{TODAY}_fakemku_paper_{MKU_NEXT}"]


def test_실시간도_그날_같은_방식의_앞선_손절을_이어받는다(tmp_path):
    reg, _, _, _ = make_rt_registry(tmp_path)
    root = tmp_path / "pyruns"
    write_run(root, f"{TODAY}_rtfake_orders", state="끝", mode="orders", sym=MKU, name="rtfake",
              trades=[trade(), trade()], kind="realtime")
    write_run(root, f"{TODAY}_rtfake_paper", state="끝", sym=MKU, name="rtfake", trades=[trade()], kind="realtime")
    run = reg.get(reg.start(rt())["id"])
    assert run.stops_before == 2 and run.engine.stops == 2


def test_재시작하면_실시간_실행_폴더도_해외_잔고_한_번으로_닫는다(tmp_path):
    cases = (("zero", 0, None, "재시작"), ("held", -1, None, "재시작 · 확인 필요"),
             ("unread", 0, {}, "재시작 · 확인 필요"))
    for name, held, pages, why in cases:
        reg, fake, _, feeds = make_rt_registry(tmp_path / name)
        fake.held, fake.oi_pages = held, pages
        folder = write_run(tmp_path / name / "pyruns", f"{TODAY}_rtfake_orders", mode="orders", sym=MKU,
                           name="rtfake", kind="realtime", market="overseas", currency="USD", signal_sym=KRX_SYM)
        paper = write_run(tmp_path / name / "pyruns", f"{TODAY}_rtfake_paper", state="확인 필요", sym=MKU,
                          name="rtfake", kind="realtime", market="overseas", currency="USD", signal_sym=KRX_SYM)
        assert reg.recover() == [folder.name, paper.name]
        run = read_json(folder / "run.json")
        assert (run["state"], run["ended_reason"], run["kind"]) == ("끝", why, "realtime"), name
        summary = read_json(folder / "summary.json")
        assert (summary["kind"], summary["currency"], summary["signal_sym"]) == ("realtime", "USD", KRX_SYM)
        assert read_json(paper / "run.json")["ended_reason"] == "재시작"         # 종이는 계좌가 없다
        # 잔고는 해외 어댑터(쪽 따라가기)로 한 번 — 국내 잔고·첫 쪽만 보는 함수·주문은 부르지 않는다
        assert [c[0] for c in fake.calls] == ["ovs_open_interest_page"], name
        assert fake.dom.calls == [] and fake.orders == [] and feeds == []
        events = [r["text"] for r in Journal(folder / "journal.jsonl").read() if r["kind"] == "event"]
        assert any(("확인 실패" if pages == {} else f"{held:+d}계약") in t for t in events), name


def test_앱을_끄면_실시간_실행도_앱_종료_중지로_정리한다(tmp_path):
    # 스레드 없는 실행 — stop_all 이 바로 끝낸다
    reg, fake, _, feeds = make_rt_registry(tmp_path / "direct")
    status = reg.start(rt())
    run = reg.get(status["id"])
    assert reg.stop_all(timeout=1) == []
    assert run._shutdown and run.state == "끝" and feeds[0].closed
    assert read_json(tmp_path / "direct" / "pyruns" / status["id"] / "run.json")["state"] == "끝"
    # 스레드가 도는 실행 — 1분봉·실시간 모두 앱 종료 중지를 받고 한 마감 시각 안에 끝난다
    reg, fake, _, feeds = make_rt_registry(tmp_path / "threads", start_thread=True)
    a = reg.get(reg.start(rt())["id"])
    b = reg.get(reg.start(rt("paper"))["id"])
    c = reg.get(reg.start(RunSpec("fakemku.py", "paper", None))["id"])
    assert reg.stop_all(timeout=5) == []
    assert all(r._shutdown and r.state == "끝" for r in (a, b, c))
    assert all(f.closed for f in feeds) and fake.orders == []


# ---------------------------------------------------------------- 두 탭 함께 끄기 (스프레드 마지막 검토 F10)
def test_request_stop_all_은_새_시작을_막고_모두에게_앱_종료_중지만_알린다_기다리지_않는다(tmp_path):
    reg, fake, clock = make_registry(tmp_path)
    status = reg.start(RunSpec("fake.py", "paper", None))
    run = reg.get(status["id"])
    reg.request_stop_all()
    assert run._shutdown and run._stop_requested and run.state not in ("끝", "오류")      # 끝내지 않는다
    with pytest.raises(StartRefused):
        reg.start(RunSpec("fake.py", "paper", None))
    assert reg.stop_all(timeout=1) == [] and run.state == "끝"                          # 기다리고 끝내기는 stop_all 그대로
