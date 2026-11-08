"""스프레드 실행 하나(`SpreadRun`) — 시작 거부, 끝·오류·중지·앱 종료의 정리, 정리 대기, 정리 거부, 주기 대조, 요약 손익.

가짜 시세(`FakeFeed`)·가짜 해외 api(`Api`, 종목마다 잔고)·가짜 실행기 함수로 돈다. 장부는 진짜(`AccountBook`·`PaperBook`).
기다림은 `Timing` 을 줄여 실제로 오래 쉬지 않는다. 마스터·품목 세부정보 줄은 `tests/fixtures/team_spread/legs.json`(실제 기록).
"""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.nh_api.errors import BusinessError
from backend.team_pyrun.live import StartRefused
from backend.team_spread.ctx import Halted, OrderRejected
from backend.team_spread.feed import WAIT_CLOSED, WAIT_RUNNING, Quote
from backend.team_spread.pnl import TRADING_DAY_STARTS, trading_date
from backend.team_spread.run import MAX_FLATTEN_REJECTS, SHUTDOWN_HOLDING, SpreadRun, SpreadSpec, Timing
from backend.team_spread.start import Sources, leg_specs, load_sources, resolve_legs
from backend.team_spread.runner_files import LoadedRunner
from tests.test_team_pyrun_markets import FakeOvsApi

ROWS = json.loads((Path(__file__).parent / "fixtures" / "team_spread" / "legs.json").read_text("utf-8"))
DETAIL = {r["prd_cd"]: r for r in ROWS["overseas_details"]}
NOW = datetime(2026, 11, 9, 10, 15, 0)
FAST = Timing(stop_wait=2.0, reconcile=3600.0, retry=0.0, poll=0.005)


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class FakeFeed:
    """닫힌 다리(`closed`)·현재가(`quotes`)를 시험이 바꾼다. 봉은 주지 않는다."""

    def __init__(self, *, now, on_wait, on_gap, on_error):
        self._now, self.on_wait, self.on_gap, self.on_error = now, on_wait, on_gap, on_error
        self.closed: set[str] = set()
        self.quotes: dict[str, Quote] = {}

    def history(self, legs, count):
        return []

    def next_minute(self, legs, stop):
        stop.wait(0.01)
        return None

    def quote(self, leg):
        return self.quotes.get(leg.name, Quote(4.40, 4.3999, 4.4001, self._now()))

    def is_open(self, leg, now):
        return leg.name not in self.closed

    def now(self):
        return self._now()

    def sleep(self, seconds, stop):
        stop.wait(min(seconds, 0.005))


class Api(FakeOvsApi):
    """여러 종목의 가짜 해외 api — 종목마다 잔고(`pos`), 종목마다 남은 거부 수(`reject`), 체결가 칸 비우기(`blank_price`),
    날마다 쌓이는 예수금 수수료(`day` = 체결이 쌓이는 날, 예수금은 물은 `biz_dt` 의 누적), 잔고 조회 때 한 번 부르는 `hook`."""

    def __init__(self):
        super().__init__()
        self.last = "4.4000"
        self.pos: dict[str, int] = {}
        self.reject: dict[str, int] = {}
        self.blank_price = False
        self.order_times: list[float] = []
        self.groups = {"FG2": [DETAIL["MKU"]], "FG6": [DETAIL["HO"], DETAIL["RB"]]}
        self.day = "20261109"
        self.fee_by_day: dict[str, float] = {}
        self.hook = None

    def ovs_deposit(self, cur_cd="USD", *, biz_dt=""):
        self.calls.append(("ovs_deposit", cur_cd, biz_dt))
        return {"fee": f"{self.fee_by_day.get(biz_dt, 0.0):018.2f}", "cls_pl_amt": "0", "ord_psb_amt": "50000"}

    def ovs_open_interest_page(self, nxt_key=""):
        self.calls.append(("ovs_open_interest_page", nxt_key))
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()
        return [{"sym": s, "trd_tp": "1" if q > 0 else "2", "opint_qty": str(abs(q))}
                for s, q in self.pos.items() if q], ""

    def ovs_market_order(self, sym, side, qty=1):
        self.orders.append((sym, side, qty))
        self.order_times.append(time.monotonic())
        if self.reject.get(sym):
            self.reject[sym] -= 1
            raise BusinessError("overseas_order", "E1", "거부", {})
        no = f"{len(self.orders):010d}"
        self.pos[sym] = self.pos.get(sym, 0) + (qty if side == "buy" else -qty)
        self.fee += 2.0
        self.fee_by_day[self.day] = self.fee_by_day.get(self.day, 0.0) + 2.0
        px = "0" if self.blank_price else f"{float(self.last) + (0.0001 if side == 'buy' else -0.0001):.4f}"
        self.history.insert(0, {"ord_no": no, "sym": sym, "ord_sts": "6", "trd_tp": "1" if side == "buy" else "2",
                                "exec_qty": str(qty), "exec_pric": px, "ord_avg_pric": px,
                                "exec_tm": "20261109101500", "err_cd": "", "rejt_rsn": ""})
        return {"ord_no": no, "err_cd": "00000", "err_msg": "주문이 정상처리 되었습니다.", "sym": sym}

    def ovs_product_detail_page(self, prd_grp_cd, nxt_key=""):
        self.calls.append(("ovs_product_detail_page", prd_grp_cd, nxt_key))
        return [dict(r) for r in self.groups.get(prd_grp_cd, [])], ""

    def product_detail(self):
        self.calls.append(("product_detail",))
        return [dict(r) for r in ROWS["domestic_details"]]


def build(tmp_path, run_fn, *, mode="orders", legs=None, api=None, timing=FAST, clock=None, box=None, roll_guard=None,
          **spec_kw):
    api = api if api is not None else Api()
    clock = clock or Clock(NOW)
    box = box if box is not None else {}

    def factory(**kw):
        box["feed"] = FakeFeed(**kw)
        return box["feed"]

    inherited = spec_kw.pop("inherited", None)
    loaded = LoadedRunner("s.py", "S", "스프레드", "ab" * 32, legs or {"ho": "HO", "rb": "RB"}, None, run_fn)
    spec = SpreadSpec("s.py", mode, spec_kw.get("syms"), spec_kw.get("max_qty"), spec_kw.get("orders_per_min"),
                      spec_kw.get("inherit_from"))
    run = SpreadRun(f"20261109_S_{mode}", tmp_path / "run", loaded, spec, api_module=api, now=clock,
                    sleep=lambda s: None, feed_factory=factory,
                    master=lambda: (ROWS["overseas_rows"], ROWS["domestic_rows"]),
                    active_env=lambda: "paper", inherited=inherited, roll_guard=roll_guard, timing=timing)
    return run, box["feed"], api


def start(run) -> threading.Thread:
    run.prepare()
    t = threading.Thread(target=run.run_forever, daemon=True)
    t.start()
    return t


def until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.003)
    raise AssertionError("기다린 조건이 오지 않음")


def saved(run, name="run.json"):
    return json.loads((run.folder / name).read_text("utf-8"))


def journal(run):
    return [json.loads(x) for x in (run.folder / "journal.jsonl").read_text("utf-8").splitlines()]


def pair_and_wait(entered):
    """짝(ho +1, rb −1)을 잡고 중지까지 기다리는 실행기."""
    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        while ctx.running():
            ctx.sleep(1)
    return run_fn


FLAT = {"HOZ26": 0, "RBZ26": 0}
PAIR_ORDERS = [("HOZ26", "buy", 1), ("RBZ26", "sell", 1)]
FLATTEN_ORDERS = [("HOZ26", "sell", 1), ("RBZ26", "buy", 1)]


# ---------------------------------------------------------------- 약속 값
def test_기다림과_다시_시도는_약속_값():
    assert Timing() == Timing(stop_wait=30.0, reconcile=30.0, retry=10.0, poll=1.0)
    assert MAX_FLATTEN_REJECTS == 3
    assert SHUTDOWN_HOLDING == "앱 종료 · 보유 남음 — 이어받기로 다시"


def test_거래일은_한국시간_07시_경계():
    assert TRADING_DAY_STARTS == timedelta(hours=7)
    assert trading_date(datetime(2026, 11, 10, 2, 0)) == "20261109"     # 밤 장 자정 뒤
    assert trading_date(datetime(2026, 11, 10, 7, 0)) == "20261110"
    assert trading_date(datetime(2026, 11, 9, 23, 59)) == "20261109"


# ---------------------------------------------------------------- 끝 규칙
def test_실행기가_돌려주면_끝_보유는_앱이_정리(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: ctx.target({"ho": 1, "rb": -1}))
    start(run).join(5)
    assert run.state == "끝" and run.ended_reason == "실행기가 끝냄 · 보유 정리"
    assert api.orders == PAIR_ORDERS + FLATTEN_ORDERS and api.pos == FLAT
    head = saved(run)
    assert head["state"] == "끝" and head["kind"] == "spread"
    assert head["holding_left"] == {} and head["inheritable"] is False
    assert [(x["name"], x["sym"]) for x in head["legs"]] == [("ho", "HOZ26"), ("rb", "RBZ26")]
    summary = saved(run, "summary.json")
    assert summary["ended_reason"] == run.ended_reason and summary["total"]["USD"]["fills"] == 4


def test_보유_없이_돌려주면_주문_없이_끝(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: None)
    start(run).join(5)
    assert run.state == "끝" and run.ended_reason == "실행기가 끝냄" and api.orders == []


def test_실행기_예외는_오류_정리도_한다(tmp_path):
    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        raise ValueError("계산 실수")
    run, feed, api = build(tmp_path, run_fn)
    start(run).join(5)
    assert run.state == "오류" and run.ended_reason.startswith("오류: ValueError: 계산 실수")
    assert run.ended_reason.endswith("· 보유 정리")
    assert api.orders == PAIR_ORDERS + FLATTEN_ORDERS and api.pos == FLAT
    row = next(r for r in journal(run) if "실행기 예외" in r.get("text", ""))
    assert row["where"] and "run_fn" in row["where"][-1]      # 줄 번호·함수 이름만(값은 남기지 않음)


def test_중지는_실행기가_돌려주길_기다린_뒤_정리(tmp_path):
    entered, back = threading.Event(), {}

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        while ctx.running():
            ctx.sleep(1)
        time.sleep(0.15)        # 중지 뒤 마무리하는 실행기
        back["at"] = time.monotonic()
    run, feed, api = build(tmp_path, run_fn)
    t = start(run)
    assert entered.wait(5)
    run.request_stop()
    t.join(5)
    assert run.state == "끝" and run.ended_reason == "중지 · 보유 정리"
    assert api.orders == PAIR_ORDERS + FLATTEN_ORDERS
    assert min(api.order_times[2:]) >= back["at"]       # 정리는 실행기가 돌려준 뒤


def test_중지_뒤_ctx_거부를_내던진_실행기는_오류가_아니라_중지(tmp_path):
    entered = threading.Event()

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        while True:                 # running() 을 보지 않아 중지 뒤 target 이 거부(OrderRejected)를 낸다
            ctx.target({"ho": 1, "rb": -1})
            time.sleep(0.002)
    run, feed, api = build(tmp_path, run_fn)
    t = start(run)
    assert entered.wait(5)
    run.request_stop()
    t.join(5)
    assert run.state == "끝" and run.ended_reason == "중지 · 보유 정리" and api.pos == FLAT


def test_RF2_중지를_무시하는_실행기는_주문을_못_내고_앱이_기다린_뒤_정리(tmp_path):
    entered, release, seen = threading.Event(), threading.Event(), []

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        while ctx.running():
            time.sleep(0.002)
        while not release.is_set():          # 중지를 무시하고 계속 주문하려 한다
            try:
                ctx.order("ho", 1)
            except Exception as e:      # noqa: BLE001 — 받은 것을 그대로 본다
                seen.append(e)
            time.sleep(0.003)
    run, feed, api = build(tmp_path, run_fn, timing=Timing(stop_wait=0.3, reconcile=3600, retry=0, poll=0.005))
    t = start(run)
    assert entered.wait(5)
    stopped = time.monotonic()
    run.request_stop()
    t.join(5)
    try:
        assert run.state == "끝" and run.ended_reason == "중지 · 보유 정리"
        assert api.orders == PAIR_ORDERS + FLATTEN_ORDERS and api.pos == FLAT
        assert min(api.order_times[2:]) - stopped >= 0.3       # 30초(여기선 0.3초) 기다린 뒤 앱이 정리
        assert seen and all(isinstance(e, OrderRejected) and not isinstance(e, Halted) for e in seen)
        time.sleep(0.03)
        assert len(api.orders) == 4         # 실행기는 아직 돌지만 주문은 하나도 안 나감
    finally:
        release.set()


# ---------------------------------------------------------------- 정리 대기 (RF3)
def test_RF3_한_다리가_쉬면_정리_대기_짝을_들고_모두_열리면_한꺼번에(tmp_path):
    entered = threading.Event()
    run, feed, api = build(tmp_path, pair_and_wait(entered))
    t = start(run)
    assert entered.wait(5)
    feed.closed = {"rb"}
    run.request_stop()
    until(lambda: run.state == "정리 대기")
    st = run.status()
    assert st["waiting_for"] == ["rb"] and saved(run)["state"] == "정리 대기"
    time.sleep(0.05)
    assert api.orders == PAIR_ORDERS        # 열린 ho 도 혼자 정리하지 않는다
    feed.closed = set()
    t.join(5)
    assert run.state == "끝" and run.ended_reason == "중지 · 보유 정리"
    assert api.orders == PAIR_ORDERS + FLATTEN_ORDERS and api.pos == FLAT
    assert run.status()["waiting_for"] == []


def test_종이는_장이_쉬어도_기다리지_않고_지금_시세로_장부만_0(tmp_path):
    entered = threading.Event()
    run, feed, api = build(tmp_path, pair_and_wait(entered), mode="paper")
    t = start(run)
    assert entered.wait(5)
    feed.closed = {"rb"}
    run.request_stop()
    t.join(5)
    assert run.state == "끝" and run.ended_reason == "중지 · 보유 정리"
    assert api.orders == [] and all(x["position"] == 0 for x in run.status()["legs"])
    assert [c for c in api.calls if c[0] in ("ovs_open_interest_page", "ovs_deposit")] == []    # 계좌를 안 본다


# ---------------------------------------------------------------- 앱 종료 (RF5)
def test_RF5_앱_종료는_정리하지_않고_실행기도_기다리지_않는다(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        release.wait(10)                # 중지를 무시 — 그래도 앱 종료를 막지 않는다
    run, feed, api = build(tmp_path, run_fn, timing=Timing(poll=0.005))     # 실행기 기다림은 약속 값 30초
    t = start(run)
    assert entered.wait(5)
    began = time.monotonic()
    run.request_stop(shutdown=True)
    t.join(5)
    try:
        assert time.monotonic() - began < 3
        assert run.state == "끝" and run.ended_reason == SHUTDOWN_HOLDING
        assert api.orders == PAIR_ORDERS and api.pos == {"HOZ26": 1, "RBZ26": -1}
        assert saved(run, "summary.json")["ended_reason"] == SHUTDOWN_HOLDING
        head = saved(run)
        assert head["holding_left"] == {"ho": 1, "rb": -1} and head["inheritable"] is True
    finally:
        release.set()


def test_RF5_중지_뒤_기다리는_중에_앱_종료가_오면_더_기다리지_않고_정리도_안_함(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        release.wait(10)
    run, feed, api = build(tmp_path, run_fn, timing=Timing(poll=0.005))     # 실행기 기다림 30초
    t = start(run)
    assert entered.wait(5)
    run.request_stop()
    until(lambda: any("돌려주길" in r.get("text", "") for r in journal(run)))
    began = time.monotonic()
    run.request_stop(shutdown=True)
    t.join(5)
    try:
        assert time.monotonic() - began < 3
        assert run.ended_reason == SHUTDOWN_HOLDING and api.orders == PAIR_ORDERS
    finally:
        release.set()


def test_RF5_정리_대기_중_앱_종료도_정리하지_않는다(tmp_path):
    entered = threading.Event()
    run, feed, api = build(tmp_path, pair_and_wait(entered))
    t = start(run)
    assert entered.wait(5)
    feed.closed = {"rb"}
    run.request_stop()
    until(lambda: run.state == "정리 대기")
    run.request_stop(shutdown=True)
    t.join(5)
    assert run.state == "끝" and run.ended_reason == SHUTDOWN_HOLDING
    assert api.orders == PAIR_ORDERS and api.pos == {"HOZ26": 1, "RBZ26": -1}


# ---------------------------------------------------------------- 정리 거부·주기 대조
@pytest.mark.parametrize("rejects", [2, 3])
def test_정리_거부는_10초_뒤_다시_세_번_안_되면_멈춤(tmp_path, rejects):
    api = Api()

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        api.reject["RBZ26"] = rejects
    run, feed, api = build(tmp_path, run_fn, api=api, timing=Timing(stop_wait=2, reconcile=3600, retry=0.05, poll=0.005))
    start(run).join(5)
    rb = [i for i, o in enumerate(api.orders) if o[0] == "RBZ26"]
    assert len(rb) == 1 + 3                             # 짝 1번 + 정리 3번(처음 + 다시 2번)
    gaps = [api.order_times[b] - api.order_times[a] for a, b in zip(rb[1:], rb[2:])]
    assert all(g >= 0.05 for g in gaps)                 # 거부 뒤 다시까지 기다림
    assert api.pos["HOZ26"] == 0                        # 열린 다리는 마저 정리
    if rejects == 2:
        assert api.pos["RBZ26"] == 0 and run.book.halted is None
        assert run.ended_reason == "실행기가 끝냄 · 보유 정리"
    else:
        assert api.pos["RBZ26"] == -1
        assert "정리 주문이 3번 거절됨" in run.book.halted and "rb(RBZ26)" in run.book.halted
        assert run.ended_reason.startswith("실행기가 끝냄 · 정리 안 함 — 확인 필요: ")
        assert saved(run)["halted"] == run.book.halted


def test_보유_중_주기_대조가_다르면_멈춤_그리고_정리하지_않음(tmp_path):
    entered = threading.Event()
    api = Api()
    run, feed, api = build(tmp_path, pair_and_wait(entered), api=api,
                           timing=Timing(stop_wait=2, reconcile=0.02, retry=0, poll=0.005))
    t = start(run)
    assert entered.wait(5)
    api.pos["RBZ26"] = 0                    # 누가 계좌에서 rb 를 정리했다
    until(lambda: run.book.halted is not None)
    t.join(5)                               # 멈추면 ctx.running() 이 False — 실행기가 돌려준다
    assert "잔고 불일치" in run.book.halted and "rb(RBZ26)" in run.book.halted
    assert api.orders == PAIR_ORDERS
    assert "정리 안 함 — 확인 필요" in run.ended_reason and saved(run)["halted"] == run.book.halted
    assert saved(run)["holding_left"] == {"ho": 1, "rb": -1} and saved(run)["inheritable"] is True


def test_멈추면_상태는_확인_필요(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        entered.set()
        release.wait(5)
    run, feed, api = build(tmp_path, run_fn)
    t = start(run)
    assert entered.wait(5)
    run.book.halt("시험 멈춤")
    until(lambda: run.state == "확인 필요")
    assert saved(run)["state"] == "확인 필요" and run.status()["halted"] == "시험 멈춤"
    release.set()
    t.join(5)
    assert run.state == "끝" and api.orders == PAIR_ORDERS


def test_장_쉼_알림은_상태와_기다리는_다리(tmp_path):
    entered = threading.Event()
    run, feed, api = build(tmp_path, pair_and_wait(entered), mode="paper")
    t = start(run)
    assert entered.wait(5)
    feed.on_wait(WAIT_CLOSED, ["rb"])
    assert run.state == "장 쉼" and run.status()["waiting_for"] == ["rb"]
    feed.on_wait(WAIT_RUNNING, [])
    assert run.state == "진행 중" and run.status()["waiting_for"] == []
    run.request_stop()
    t.join(5)


# ---------------------------------------------------------------- 요약 손익
def test_요약은_거래일_통화별_손익_수수료_체결수(tmp_path):
    clock, box = Clock(datetime(2026, 11, 9, 10, 0)), {}

    def run_fn(ctx):
        q = box["feed"].quotes
        q.update(m=Quote(0.7447, 0.7446, 0.7448, NOW), u=Quote(1400.0, 1399.9, 1400.1, NOW))
        ctx.target({"m": 2, "u": -1})                   # m 매수 0.7448×2 · u 매도 1399.9
        clock.t = datetime(2026, 11, 10, 2, 0)           # 자정 뒤 밤 장 — 거래일은 11/09
        q["m"] = Quote(0.7457, 0.7456, 0.7458, NOW)
        ctx.order("m", -1)                              # (0.7456 − 0.7448) × 25000 = 20
        clock.t = datetime(2026, 11, 10, 10, 0)
        q.update(m=Quote(0.7437, 0.7436, 0.7438, NOW), u=Quote(1399.0, 1398.9, 1399.1, NOW))
        ctx.target({"m": 0, "u": 0})                    # m (0.7436 − 0.7448)×25000 = −30 · u (1399.9 − 1399.1)×10000 = 8000
    run, feed, api = build(tmp_path, run_fn, mode="paper", legs={"m": "MKU", "u": "A75"}, clock=clock, box=box)
    start(run).join(5)
    s = saved(run, "summary.json")
    d9, d10 = s["days"]["20261109"], s["days"]["20261110"]
    assert d9["USD"] == pytest.approx({"pnl": 20.0, "fee": 6.0, "net": 14.0, "fills": 2})
    assert d9["KRW"] == pytest.approx({"pnl": 0.0, "fee": 690.0, "net": -690.0, "fills": 1})
    assert d10["USD"] == pytest.approx({"pnl": -30.0, "fee": 2.0, "net": -32.0, "fills": 1})
    assert d10["KRW"] == pytest.approx({"pnl": 8000.0, "fee": 690.0, "net": 7310.0, "fills": 1})
    assert s["total"]["USD"] == pytest.approx({"pnl": -10.0, "fee": 8.0, "net": -18.0, "fills": 3})
    assert s["total"]["KRW"] == pytest.approx({"pnl": 8000.0, "fee": 1380.0, "net": 6620.0, "fills": 2})
    st = run.status()
    assert st["pnl_today"]["USD"]["pnl"] == pytest.approx(-30.0) and st["pnl_total"]["KRW"]["pnl"] == pytest.approx(8000)
    assert {x["sym"]: x["currency"] for x in s["legs"]} == {"MKUX26": "USD", "A756B000": "KRW"}


def test_체결가를_모르는_체결이_든_손익은_추정으로_표시(tmp_path):
    api = Api()
    api.blank_price = True
    known = {}

    def run_fn(ctx):
        fills = ctx.target({"ho": 1, "rb": -1})
        known["open"] = [f.price_known for f in fills]
        api.blank_price = False                         # 정리 체결은 체결가를 읽는다
    run, feed, api = build(tmp_path, run_fn, api=api)
    start(run).join(5)
    assert known["open"] == [False, False]
    s = saved(run, "summary.json")
    assert s["total"]["USD"]["estimated"] is True and s["days"]["20261109"]["USD"]["estimated"] is True
    assert run.status()["pnl_total"]["USD"]["estimated"] is True


def test_체결가를_다_알면_추정_표시_없음(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: ctx.target({"ho": 1, "rb": -1}))
    start(run).join(5)
    total = saved(run, "summary.json")["total"]["USD"]
    assert "estimated" not in total
    assert total["pnl"] == pytest.approx(-16.8) and total["fee"] == pytest.approx(8.0)   # 4.4001/4.3999 왕복 두 다리


# ---------------------------------------------------------------- 시작 거부
def test_다리를_못_찾으면_시작_거부_run_json_남김(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: None, legs={"x": "ZZ", "rb": "RB"})
    with pytest.raises(StartRefused, match="ZZ"):
        run.prepare()
    head = saved(run)
    assert head["state"] == "끝" and head["ended_reason"].startswith("시작 거부: ") and api.orders == []
    assert head["holding_left"] == {} and head["inheritable"] is False


def test_틱이_품목_세부정보와_다르면_시작_거부(tmp_path):
    api = Api()
    api.groups["FG6"] = [{**DETAIL["HO"], "tick_val": "00000000000000005.00000000"}, DETAIL["RB"]]
    run, feed, api = build(tmp_path, lambda ctx: None, api=api)
    with pytest.raises(StartRefused, match=r"ho\(HOZ26\) 틱·틱가치"):
        run.prepare()
    assert saved(run)["ended_reason"].startswith("시작 거부: ") and api.orders == []


def test_모의_계좌_시작_잔고가_0_이_아니면_거부(tmp_path):
    api = Api()
    api.pos["RBZ26"] = -2
    run, feed, api = build(tmp_path, lambda ctx: None, api=api)
    with pytest.raises(StartRefused, match=r"rb\(RBZ26\) 잔고 -2계약"):
        run.prepare()
    assert saved(run)["state"] == "끝" and api.orders == []
    assert not (run.folder / "summary.json").exists()


def test_모의_계좌는_모의투자_환경에서만(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: None)
    run._active_env = lambda: "real"
    with pytest.raises(StartRefused, match="모의투자"):
        run.prepare()


def test_해외_품목_세부정보는_필요한_그룹만_묻는다(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: None)
    run.prepare()
    asked = [c[1] for c in api.calls if c[0] == "ovs_product_detail_page"]
    assert asked[:2] == ["FG2", "FG6"] and "product_detail" not in [c[0] for c in api.calls]


# ---------------------------------------------------------------- 이어받기 (R20 꼴)
INHERITED = {"from": "20261106_S_orders", "ended_reason": SHUTDOWN_HOLDING,
             "legs": {"ho": {"qty": 1, "avg_price": 4.3}, "rb": {"qty": -1, "avg_price": 4.5}}}


def test_이어받기는_그_잔고로_시작하고_이어받은_평균가로_손익(tmp_path):
    api = Api()
    api.pos.update({"HOZ26": 1, "RBZ26": -1})
    given = {**INHERITED, "extra": 1, "legs": {"ho": {**INHERITED["legs"]["ho"], "note": "x"}, "rb": INHERITED["legs"]["rb"]}}
    box = {}

    def run_fn(ctx):
        box["inh"], box["pos"] = ctx.inherited, (ctx.position("ho"), ctx.position("rb"))
    run, feed, api = build(tmp_path, run_fn, api=api, inherited=given, inherit_from="20261106_S_orders")
    start(run).join(5)
    assert box == {"inh": INHERITED, "pos": (1, -1)}          # 다른 칸은 버리고 한 꼴로
    assert api.orders == FLATTEN_ORDERS and api.pos == FLAT
    s = saved(run, "summary.json")
    assert s["inherited_from"] == "20261106_S_orders" and s["inherited"] == INHERITED
    assert s["total"]["USD"]["pnl"] == pytest.approx((4.3999 - 4.3) * 42000 + (4.5 - 4.4001) * 42000)
    assert saved(run)["inherited"] == INHERITED and saved(run)["inherited_from"] == "20261106_S_orders"
    assert run.status()["inherited_from"] == "20261106_S_orders"


def test_이어받기의_from_은_spec_에서_채우고_다르면_거부(tmp_path):
    api = Api()
    api.pos.update({"HOZ26": 1, "RBZ26": -1})
    given = {k: v for k, v in INHERITED.items() if k != "from"}
    run, feed, api = build(tmp_path, lambda ctx: None, api=api, inherited=given, inherit_from="20261106_S_orders")
    run.prepare()
    assert run.ctx.inherited["from"] == "20261106_S_orders"
    run2, _, _ = build(tmp_path / "b", lambda ctx: None, api=api, inherited=INHERITED, inherit_from="다른_실행")
    with pytest.raises(StartRefused, match="이어받을 실행"):
        run2.prepare()


def test_이어받을_잔고가_바뀌었으면_시작_거부(tmp_path):
    api = Api()
    api.pos.update({"HOZ26": 1})
    run, feed, api = build(tmp_path, lambda ctx: None, api=api, inherited=INHERITED, inherit_from="20261106_S_orders")
    with pytest.raises(StartRefused, match="이어받을 잔고가 바뀌었습니다"):
        run.prepare()
    assert api.orders == []


def test_이어받을_평균가가_수가_아니면_시작_거부(tmp_path):
    api = Api()
    api.pos.update({"HOZ26": 1})
    bad = {**INHERITED, "legs": {"ho": {"qty": 1, "avg_price": "4.3"}}}
    run, feed, api = build(tmp_path, lambda ctx: None, api=api, inherited=bad, inherit_from="20261106_S_orders")
    with pytest.raises(StartRefused, match="이어받을 보유가 맞지 않습니다"):
        run.prepare()


def test_넘겨줌은_run_json_에(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: None)
    start(run).join(5)
    run.mark_handed_to("20261110_S_orders")
    assert saved(run)["handed_to"] == "20261110_S_orders" and run.status()["handed_to"] == "20261110_S_orders"


# ---------------------------------------------------------------- 월물 교체
def test_월물_교체는_새_종목으로_장부_run_json_기록_order_syms(tmp_path):
    box = {}

    def run_fn(ctx):
        box["new"] = ctx.roll("ho")
        box["syms"] = run.order_syms()
        ctx.target({"ho": 1, "rb": -1})
    run, feed, api = build(tmp_path, run_fn)
    start(run).join(5)
    assert box["new"].sym == "HOF27" and box["syms"] == {"HOF27", "RBZ26"}
    assert api.orders[0] == ("HOF27", "buy", 1) and api.pos == {"HOF27": 0, "RBZ26": 0}
    assert [x["sym"] for x in saved(run)["legs"]] == ["HOF27", "RBZ26"]
    row = next(r for r in journal(run) if r["kind"] == "leg" and r.get("why") == "월물 교체")
    assert (row["leg"], row["old"], row["sym"]) == ("ho", "HOZ26", "HOF27")


def test_새_월물에_잔고가_있으면_교체_거부(tmp_path):
    api, box = Api(), {}
    api.pos["HOF27"] = 1

    def run_fn(ctx):
        try:
            ctx.roll("ho")
        except OrderRejected as e:
            box["err"] = str(e)
    run, feed, api = build(tmp_path, run_fn, api=api)
    start(run).join(5)
    assert "HOF27" in box["err"] and run.order_syms() == {"HOZ26", "RBZ26"} and api.orders == []
    assert run.book.halted is None and run.state == "끝"


# ---------------------------------------------------------------- 상태
def test_상태_칸(tmp_path):
    entered = threading.Event()
    run, feed, api = build(tmp_path, pair_and_wait(entered), mode="paper")
    t = start(run)
    assert entered.wait(5)
    st = run.status()
    assert list(st) == ["id", "file", "name", "title", "mode", "state", "started_at", "ended_at", "ended_reason",
                        "halted", "legs", "pnl_today", "pnl_total", "waiting_for", "inherited_from", "handed_to",
                        "logs_tail"]
    assert st["legs"][0] == {"name": "ho", "sym": "HOZ26", "market": "overseas", "currency": "USD",
                             "position": 1, "avg_price": pytest.approx(4.4001), "last": pytest.approx(4.40)}
    assert st["state"] == "진행 중" and run.order_syms() == {"HOZ26", "RBZ26"}
    run.request_stop()
    t.join(5)


def test_log_값은_logs_tail_에(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: ctx.log("z", 2.5), mode="paper")
    start(run).join(5)
    tail = run.status()["logs_tail"]
    assert [(r["name"], r["value"]) for r in tail] == [("z", 2.5)]


# ---------------------------------------------------------------- 고침 1회차
def test_시세_오류와_공백_까닭은_토큰을_가려_기록(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: None, mode="paper")
    feed.on_error("PermissionError: Bearer TOKEN123 access_token=SECRET9")
    feed.on_gap("20261109 101500", "20261109 101600", "봉이 오지 않음 — 마지막 조회 오류 {'app_secret': 'SECRET9'} Bearer TOKEN123")
    text = (run.folder / "journal.jsonl").read_text("utf-8")
    assert "TOKEN123" not in text and "SECRET9" not in text and "Bearer ***" in text


def test_R15_종이는_앱_종료에도_장부를_0_으로(tmp_path):
    entered = threading.Event()
    run, feed, api = build(tmp_path, pair_and_wait(entered), mode="paper")
    t = start(run)
    assert entered.wait(5)
    run.request_stop(shutdown=True)
    t.join(5)
    assert run.state == "끝" and run.ended_reason == "앱 종료 · 보유 정리" and api.orders == []
    assert all(x["position"] == 0 for x in run.status()["legs"])
    head = saved(run)
    assert head["holding_left"] == {} and head["inheritable"] is False


def test_R18_날을_넘긴_체결의_수수료는_그날_예수금으로(tmp_path):
    api, clock = Api(), Clock(NOW)

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        clock.t, api.day = datetime(2026, 11, 10, 10, 0), "20261110"     # 다음 날 — 정리 체결은 이날 예수금에 쌓인다
    run, feed, api = build(tmp_path, run_fn, api=api, clock=clock)
    start(run).join(5)
    days = saved(run, "summary.json")["days"]
    assert days["20261109"]["USD"]["fee"] == pytest.approx(4.0) and days["20261110"]["USD"]["fee"] == pytest.approx(4.0)
    assert "fee_unknown" not in days["20261110"]["USD"]
    assert ("ovs_deposit", "USD", "20261110") in api.calls


def test_R22a_정리_전_대조_중_앱_종료가_오면_첫_정리_주문도_안_냄(tmp_path):
    api, box = Api(), {}

    def run_fn(ctx):
        ctx.target({"ho": 1, "rb": -1})
        api.hook = lambda: box["run"].request_stop(shutdown=True)       # 다음 잔고 조회 = 정리 전 대조
    run, feed, api = build(tmp_path, run_fn, api=api)
    box["run"] = run
    start(run).join(5)
    assert api.orders == PAIR_ORDERS and run.ended_reason == SHUTDOWN_HOLDING
    assert saved(run)["inheritable"] is True


def test_R22c_roll_guard_의_거부는_실행기에_OrderRejected(tmp_path):
    box = {}

    def guard(sym):
        raise StartRefused(f"같은 종목 {sym} 의 모의 계좌 실행이 이미 있습니다")

    def run_fn(ctx):
        try:
            ctx.roll("ho")
        except OrderRejected as e:
            box["err"] = str(e)
    run, feed, api = build(tmp_path, run_fn, roll_guard=guard)
    start(run).join(5)
    assert "HOF27" in box["err"] and run.state == "끝" and run.order_syms() == {"HOZ26", "RBZ26"}


def test_R22d_끝내기가_실패해도_멈춤_표시_요약_남은_보유를_남긴다(tmp_path):
    run, feed, api = build(tmp_path, lambda ctx: ctx.target({"ho": 1, "rb": -1}))

    def boom():
        raise RuntimeError("뜻밖")
    run._flatten_orders = boom
    start(run).join(5)
    assert run.state == "끝" and "끝내기 처리 실패" in run.ended_reason and "확인 필요" in run.ended_reason
    assert "끝내기 처리 실패" in run.book.halted
    head, s = saved(run), saved(run, "summary.json")
    assert head["holding_left"] == {"ho": 1, "rb": -1} and head["inheritable"] is True and head["halted"]
    assert s["halted"] == run.book.halted and s["holding_left"] == {"ho": 1, "rb": -1}


def test_다리_찾기_함수는_실행_밖에서도_쓴다(tmp_path):
    loaded = LoadedRunner("s.py", "S", "스프레드", "ab" * 32, {"ho": "HO", "rb": "RB"}, None, lambda ctx: None)
    specs = leg_specs(loaded, {"ho": "HOF27"})
    src = load_sources(specs, api_module=Api(), master=lambda: (ROWS["overseas_rows"], ROWS["domestic_rows"]))
    legs = resolve_legs(specs, src, today="20261109")
    assert isinstance(src, Sources) and {n: x.sym for n, x in legs.items()} == {"ho": "HOF27", "rb": "RBZ26"}
    with pytest.raises(StartRefused, match="실행기에 없는 다리"):
        leg_specs(loaded, {"zz": "HO"})
