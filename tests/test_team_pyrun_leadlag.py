"""leadlag 실시간 예제 파일(`docs/team/examples/strategy_leadlag.py`)과 녹화 리플레이(`replay.replay_realtime`) 시험.

- 예제 파일: 로더가 실시간 전략으로 읽고, 표준 라이브러리만 쓰고, `Engine`·`LiveParams`·상수의 소스가 week03
  `ws_trader.py` 와 **글자 그대로** 같다(복사 확인). ws_trader 는 `websockets`·`nh_client` 를 import 해서 불러올 수
  없으므로 글(`ast`)로만 읽는다 — 실행하지 않는다.
- 골든: week03 이 기록한 20261103 원문(`raw.jsonl.gz`)을 앱 실시간 실행기(`RealtimeRun.handle`·`fire_timer`)에 흘린 결과가
  ① week03 문서 7-4절의 `replay_live.py` 표(충격 기준 0.5·0.6·0.7·0.8·1.0원)와 같고 ② 0.5원 거래는 그날 ws_trader
  종이 기록(`events.csv`)의 앞 4건과 진입·청산 시각·방향·가격·사유가 같고 ③ `replay_live.py` 를 옮겨 적은 기준
  구현(`replay_live_ref`)과 거래 하나하나 같다.
"""
from __future__ import annotations

import ast
import csv
import gzip
import json
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from backend.team_pyrun import replay
from backend.team_pyrun.loader import load
from backend.team_pyrun import realtime
from backend.team_pyrun.realtime import RealtimeRun

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/team/examples"
EXAMPLE = EXAMPLES / "strategy_leadlag.py"
WEEK03 = Path(__file__).parent / "fixtures/team_pyrun/week03/leadlag"
WS_TRADER = WEEK03 / "ws_trader.py"         # week03 원본 사본(깃허브 11/04 판) — 여기선 글로만 읽는다. 그대로 불러오기는 test_team_pyrun_decision
RAW_1103 = WEEK03 / "20261103/raw.jsonl.gz"
RAW_1102 = WEEK03 / "20261102/raw.jsonl.gz"

#: 떼어 내며 남긴 이름 — 이 소스가 ws_trader 와 같아야 한다
KEPT = ("TICK", "TICK_USD", "FEE_TICKS", "LiveParams", "Engine")
#: 판단 메서드 — 하나씩도 비교한다
JUDGE = ("__init__", "on_krx", "on_quote", "on_timer", "_drop_if_stale", "_trim", "_at", "_entry",
         "filled_entry", "_exit", "filled_exit")

#: week03 문서(`week03-전략-근거-연계.md`) 7-4절 replay_live 표 — (거래, 승, 틱 합(비용 전), 순손익 USD)
DOC_TABLE = {0.5: (4, 1, -2, -21.0), 0.6: (3, 1, -1, -14.5), 0.7: (2, 1, 4, 2.0), 0.8: (1, 1, 9, 18.5),
             1.0: (0, 0, 0, 0.0)}


# ---------------------------------------------------------------- 도움
def _with_decorators(text: str, node: ast.AST) -> tuple[list[str], str]:
    """(데코레이터들, 소스 조각) — `get_source_segment` 는 데코레이터 줄을 빼므로 따로 붙인다(`@dataclass`·`@staticmethod`)."""
    return [ast.unparse(d) for d in node.decorator_list], ast.get_source_segment(text, node, padded=True)


def top_level(text: str) -> dict[str, object]:
    """모듈 맨 위의 클래스·함수·대입 이름 → 소스 조각(클래스·함수는 데코레이터까지)."""
    tree = ast.parse(text)
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = _with_decorators(text, node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = ast.get_source_segment(text, node)
    return out


def methods(text: str, cls: str) -> dict[str, str]:
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return {f.name: _with_decorators(text, f)
            for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}


@pytest.fixture(scope="module")
def loaded():
    return load(EXAMPLES, "strategy_leadlag.py")


@pytest.fixture(scope="module")
def msgs_1103():
    return replay.read_raw(RAW_1103)


def replay_live_ref(loaded, msgs, p) -> list[dict]:
    """week03 `replay_live.py` 의 `replay()`(31~59줄)를 그대로 옮겨 적은 기준 구현 — 앱 실행기를 거치지 않는다.

    다른 점은 원문을 `replay.read_raw` 로 읽는다는 것뿐(시각 = recv_ts, KA·FB 만 — replay_live `stream` 과 같음)."""
    e = loaded.strategy_cls(p)
    trades, nxt = [], None

    def act(a, now, hhmmss):
        if not a:
            return
        if a["act"] == "enter":
            e.filled_entry(a["side"], a["ref"], now, a["time"], "")
            trades.append({"in": hhmmss, "side": a["side"], "dk": a.get("dk"), "rho": a.get("rho"), "entry": a["ref"]})
        else:
            r = e.filled_exit(a["ref"], now, a["reason"])
            trades[-1].update(out=hhmmss, exit=a["ref"], reason=a["reason"], **r)

    for m in msgs:
        now, b = m.recv_monotonic, m.body
        hhmmss = replay.wall_of(now).strftime("%H%M%S")
        nxt = nxt or now
        while nxt <= now:
            act(e.on_timer(nxt, replay.wall_of(nxt).strftime("%H%M%S")), nxt, hhmmss)
            nxt += 1
        if m.api_id == "KA":
            if b.get("tick_div") == "1" and float(b.get("exec_qty") or 0):
                act(e.on_krx(float(b["last_pric"]), now, b.get("exch_tm", "")[:6]), now, hhmmss)
        else:
            try:
                bid, ask = float(b["bid_pric_1"]), float(b["ask_pric_1"])
            except (KeyError, ValueError):
                continue
            act(e.on_quote(bid, ask, now, b.get("ko_exec_tm", "")[:6]), now, hhmmss)
    return [t for t in trades if "out" in t]


def app_view(trades: list[dict]) -> list[tuple]:
    """앱 trade 줄 → 비교용 (진입 시각, 방향, 진입가, 청산 시각, 청산가, 사유, 틱(비용 전), 순손익 USD, 보유 초)."""
    return [(t["entry_time"], 1 if t["side"] == "buy" else -1, t["entry"], t["exit_time"], t["exit"], t["reason"],
             t["gross_ticks"], t["net_usd"], t["held_s"]) for t in trades]


def ref_view(trades: list[dict]) -> list[tuple]:
    return [(t["in"], t["side"], t["entry"], t["out"], t["exit"], t["reason"], t["gross_ticks"], t["net_usd"],
             t["held_s"]) for t in trades]


# ---------------------------------------------------------------- 예제 파일
def test_예제_파일은_실시간_전략으로_불러짐(loaded):
    assert loaded.kind == "realtime"
    assert loaded.strategy_cls.__name__ == "Engine" and loaded.params_cls.__name__ == "LiveParams"
    assert (loaded.tick, loaded.tick_value) == (0.0001, 2.5)
    assert loaded.name == "strategy_leadlag"
    eng = loaded.new()
    assert eng.p.flatten_at == "154000" and eng.pending is False and eng.stops == 0


def test_예제_파일은_표준_라이브러리만_import():
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names, "import 가 하나도 없음 — 파일을 잘못 읽음"
    assert all(n == "__future__" or n in sys.stdlib_module_names for n in names), names
    for gone in ("websockets", "nh_client", "fee_test", "ws_probe", "asyncio", "argparse"):
        assert gone not in names


def test_예제_파일에서_뺀_것():
    got = top_level(EXAMPLE.read_text(encoding="utf-8"))
    for gone in ("Recorder", "Trader", "main", "open_raw", "HERE", "SILENCE_S"):
        assert gone not in got
    head = EXAMPLE.read_text(encoding="utf-8").split('"""', 2)
    assert head[0] == "" and "ws_trader.py" in head[1]          # 머리말(모듈 문서)이 맨 위
    for word in ("Recorder", "Trader", "main", "open_raw", "websockets", "nh_client", "fee_test", "ws_probe"):
        assert word in head[1], f"머리말에 뺀 것 {word} 설명이 없음"


def test_Engine_LiveParams_상수_소스가_ws_trader_와_같음():
    ours = top_level(EXAMPLE.read_text(encoding="utf-8"))
    theirs = top_level(WS_TRADER.read_text(encoding="utf-8"))
    for name in KEPT:
        assert ours[name] == theirs[name], f"{name} 이 ws_trader 와 다름"
    assert ours["LiveParams"][0] == ["dataclass"]       # 데코레이터도 비교하고 있음


def test_판단_메서드가_하나씩_같음():
    ours = methods(EXAMPLE.read_text(encoding="utf-8"), "Engine")
    theirs = methods(WS_TRADER.read_text(encoding="utf-8"), "Engine")
    assert set(ours) == set(theirs) == set(JUDGE)
    for name in JUDGE:
        assert ours[name] == theirs[name], f"Engine.{name} 이 ws_trader 와 다름"
    assert ours["_at"][0] == ["staticmethod"]


def test_데코레이터가_다르면_복사_확인이_잡음():
    text = WS_TRADER.read_text(encoding="utf-8")
    bad = text.replace("    @staticmethod\n    def _at(", "    def _at(", 1)
    assert bad != text
    assert methods(bad, "Engine")["_at"] != methods(text, "Engine")["_at"]


# ---------------------------------------------------------------- 녹화 읽기
def test_녹화_읽기는_KA_FB_만_recv_ts_로(msgs_1103):
    assert {m.api_id for m in msgs_1103} == {"KA", "FB"}
    assert sum(m.api_id == "KA" for m in msgs_1103) == 33152 and sum(m.api_id == "FB" for m in msgs_1103) == 18626
    first = msgs_1103[0]
    assert (first.market, first.sym) == ("domestic", "A756B000")
    assert replay.wall_of(first.recv_monotonic).isoformat(timespec="milliseconds") == "2026-11-03T09:24:49.693+09:00"
    monos = [m.recv_monotonic for m in msgs_1103]
    assert monos == sorted(monos)
    assert {m.sym for m in msgs_1103 if m.api_id == "FB"} == {"MKUX26"}


def test_녹화_날짜로_거르기(tmp_path):
    raw = tmp_path / "raw.jsonl"
    line = {"recv_ts": "", "conn": "국내", "msg": {"header": {"action_code": "KA", "action_sym": "A756B000"},
                                                     "body": {"tick_div": "1", "exec_qty": "1", "last_pric": "1340.0"}}}
    rows = []
    for ts in ("2026-11-03T09:00:00.100", "2026-11-04T09:00:00.100"):
        rows.append(json.dumps({**line, "recv_ts": ts}, ensure_ascii=False))
    rows.append(json.dumps({"recv_ts": "2026-11-03T09:00:01.000", "conn": "국내", "msg": {"code": "pingpong"}}))
    raw.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert len(replay.read_raw(raw)) == 2
    got = replay.read_raw(raw, date="20261104")
    assert len(got) == 1 and replay.wall_of(got[0].recv_monotonic).strftime("%Y%m%d") == "20261104"


# ---------------------------------------------------------------- 골든 (20261103)
@pytest.mark.parametrize("move", sorted(DOC_TABLE))
def test_골든_week03_문서_replay_live_표(tmp_path, loaded, msgs_1103, move):
    got = replay.replay_realtime(loaded, msgs_1103, tmp_path / "out", params={"move_won": move})
    tr = got["trades"]
    n, win, ticks, net = DOC_TABLE[move]
    assert len(tr) == n
    assert sum(t["net_usd"] > 0 for t in tr) == win
    assert round(sum(t["gross_ticks"] for t in tr)) == ticks
    assert round(sum(t["net_usd"] for t in tr), 2) == net
    # replay_live 를 옮겨 적은 기준 구현과 거래 하나하나 같다
    ref = replay_live_ref(loaded, msgs_1103, replace(loaded.params_cls(), move_won=move))
    assert app_view(tr) == ref_view(ref)


def test_골든_0_5원은_그날_ws_trader_종이_기록의_앞_4건(tmp_path, loaded, msgs_1103):
    got = replay.replay_realtime(loaded, msgs_1103, tmp_path / "out", params={"move_won": 0.5})
    with (WEEK03 / "20261103/events.csv").open(encoding="utf-8") as f:
        ev = [r for r in csv.DictReader(f) if r["kind"] in ("진입", "청산")]
    live = []
    for e_in, e_out in zip(ev[0::2], ev[1::2], strict=True):
        live.append((e_in["ts"][11:19].replace(":", ""), int(e_in["side"]), float(e_in["price"]),
                     e_out["ts"][11:19].replace(":", ""), float(e_out["price"]), e_out["reason"],
                     float(e_out["gross_ticks"]), float(e_out["net_usd"]), float(e_out["held_s"])))
    # ws_trader 는 그날 5건 — 14:47 건은 끊긴 뒤 가짜 충격(문서 7-5절), 지금 Engine 은 stale_s 로 거른다
    assert len(live) == 5 and live[4][0] == "144719"
    app = app_view(got["trades"])
    assert [a[:8] for a in app] == [w[:8] for w in live[:4]]
    # 보유 초는 ws_trader 가 단조 시계, 리플레이가 recv_ts 라 조금 다를 수 있다
    assert all(abs(a[8] - w[8]) <= 0.5 for a, w in zip(app, live[:4], strict=True))


def test_리플레이는_실행기_넣기_길로_첫_타이머는_첫_원문_시각(tmp_path, loaded, msgs_1103, monkeypatch):
    handled, fired = [], []
    real_handle, real_fire = RealtimeRun.handle, RealtimeRun.fire_timer
    monkeypatch.setattr(RealtimeRun, "handle", lambda self, item: (handled.append(item), real_handle(self, item))[1])
    monkeypatch.setattr(RealtimeRun, "fire_timer",
                        lambda self, mono, hh=None: (fired.append(mono), real_fire(self, mono, hh))[1])
    few = msgs_1103[:400]
    replay.replay_realtime(loaded, few, tmp_path / "out")
    assert handled == few
    assert fired[0] == few[0].recv_monotonic                    # replay_live: nxt = 첫 원문 시각
    assert all(b - a == 1.0 for a, b in zip(fired, fired[1:], strict=False))
    assert fired[-1] <= few[-1].recv_monotonic < fired[-1] + 1


def test_리플레이_기록은_실시간_종이_리플레이(tmp_path, loaded, msgs_1103):
    out = tmp_path / "out"
    got = replay.replay_realtime(loaded, msgs_1103, out, params={"move_won": 0.8})
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (run["mode"], run["kind"], run["state"], run["sym"], run["signal_sym"]) == (
        "replay", "realtime", "끝", "MKUX26", "A756B000")
    assert run["ended_reason"] == "장 끝"          # 녹화가 15:45(flatten_at + 5분) 넘어서까지 있음 — 장중 실행처럼 끝냄
    first = json.loads((out / "journal.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["kind"] == "event" and first["text"].startswith("리플레이") and "서버 접속 없음" in first["text"]
    assert "서버 paper" not in (out / "journal.jsonl").read_text(encoding="utf-8")
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["kind"] == "realtime" and s["engine_net_usd"] == 18.5 and len(s["trades"]) == 1
    assert s["strategy"]["params"]["move_won"] == 0.8
    assert s["api"]["calls"] == {}                              # NH 로 아무것도 안 감
    lines = [json.loads(x) for x in (out / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    fills = [r for r in lines if r["kind"] == "fill"]
    assert len(fills) == 2 and all(r["source"] == "paper" for r in fills)
    sig = [r for r in lines if r["kind"] == "signal"]
    assert [(r["act"], r["side"], r.get("reason")) for r in sig] == [("enter", "sell", None), ("exit", "buy", "시간")]
    assert any(r["kind"] == "minute" for r in lines)
    assert got["summary"]["trades"] == 1


# ---------------------------------------------------------------- 20261102 (작은 녹화)
def test_20261102_녹화는_거래_없음(tmp_path, loaded):
    msgs = replay.read_raw(RAW_1102)
    assert len(msgs) == 43 and replay.wall_of(msgs[0].recv_monotonic).strftime("%H%M%S") >= "171200"
    assert replay_live_ref(loaded, msgs, loaded.params_cls()) == []
    # 17:12 녹화 — 앱 실행기는 끝 시각(15:45) 뒤라 시작을 거부한다(주문·판단 없음)
    got = replay.replay_realtime(loaded, msgs, tmp_path / "out")
    assert got["trades"] == [] and "끝 시각" in got["refused"]


# ---------------------------------------------------------------- 명령줄
def test_명령줄은_원문_녹화면_실시간_리플레이(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "strategies"
    folder.mkdir()
    shutil.copy(EXAMPLE, folder / "strategy_leadlag.py")
    monkeypatch.setattr(replay.storage, "state_dir", lambda env=None: tmp_path / "state")
    raw = tmp_path / "raw.jsonl.gz"
    with gzip.open(RAW_1103, "rt", encoding="utf-8") as src, gzip.open(raw, "wt", encoding="utf-8") as dst:
        for i, line in enumerate(src):
            if i > 3000:
                break
            dst.write(line)
    assert replay.main([str(folder / "strategy_leadlag.py"), "20261103", str(raw)]) == 0
    out = tmp_path / "state" / "pyruns" / "20261103_strategy_leadlag_replay"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (run["kind"], run["mode"]) == ("realtime", "replay")
    assert replay.main(["x.py"]) == 2
    assert "<raw.jsonl[.gz]>" in capsys.readouterr().err
    # 1분봉 전략에 원문 녹화 / 실시간 전략에 1분봉 csv — 거부
    assert replay.main([str(folder / "strategy_leadlag.py"), "20261103", str(tmp_path / "bars_1m_MKUX26.csv")]) == 2


def test_StartRefused_는_리플레이에서_돌려줌(tmp_path, loaded, msgs_1103):
    # 시작 거부는 예외로 새지 않고 결과의 refused 로 (명령줄이 그대로 알림)
    late = [m._replace(recv_monotonic=m.recv_monotonic + 7 * 3600) for m in msgs_1103[:10]]
    got = replay.replay_realtime(loaded, late, tmp_path / "out")
    assert "끝 시각" in got["refused"] and got["trades"] == []


def test_wall_of_는_한국시간():
    w = replay.wall_of(datetime.fromisoformat("2026-11-03T09:00:00.250+09:00").timestamp())
    assert w.strftime("%Y%m%d %H%M%S") == "20261103 090000" and w.utcoffset().total_seconds() == 9 * 3600


# ---------------------------------------------------------------- 보유 중 긴 공백 (손으로 만든 녹화)
def _ka(ts: str, price: float, exch: str):
    return replay.RawMessage("domestic", "KA", "A756B000",
                             {"tick_div": "1", "exec_qty": "1", "last_pric": f"{price:.2f}", "exch_tm": exch + "00"},
                             replay._mono_of(ts))


def _fb(ts: str, bid: float, ask: float, ko: str):
    return replay.RawMessage("overseas", "FB", "MKUX26",
                             {"bid_pric_1": f"{bid:.4f}", "ask_pric_1": f"{ask:.4f}", "ko_exec_tm": ko},
                             replay._mono_of(ts))


def test_보유_중_10분_넘는_공백도_replay_live_처럼_타이머를_다_돌림(tmp_path, loaded):
    # 09:30:00 시세 → 09:30:46 KRX +0.8원(MKU 그대로) 매도 진입 → 12분 동안 원문 없음 → 09:42:46 호가 하나
    msgs = [_fb("2026-11-03T09:30:00.100", 0.7450, 0.7451, "093000"),
            _ka("2026-11-03T09:30:00.200", 1340.0, "093000"),
            _ka("2026-11-03T09:30:15.200", 1340.0, "093015"),      # stale_s(20초) 안에 이어지게
            _ka("2026-11-03T09:30:30.200", 1340.0, "093030"),
            _ka("2026-11-03T09:30:46.300", 1340.8, "093046"),
            _fb("2026-11-03T09:42:46.400", 0.7450, 0.7451, "094246")]
    ref = replay_live_ref(loaded, msgs, loaded.params_cls())
    assert len(ref) == 1 and ref[0]["reason"] == "시간" and abs(ref[0]["held_s"] - 300) < 1   # 공백 안의 타이머에서
    out = tmp_path / "out"
    got = replay.replay_realtime(loaded, msgs, out)
    assert app_view(got["trades"]) == ref_view(ref)
    t = got["trades"][0]
    assert (t["exit_time"], t["reason"], t["held_s"]) == (ref[0]["out"], ref[0]["reason"], ref[0]["held_s"])
    assert "건너뜀" not in (out / "journal.jsonl").read_text(encoding="utf-8")


def test_장중_실행은_긴_공백의_타이머를_그대로_건너뜀(tmp_path, loaded):
    # 장중 기본값(600)은 그대로 — 같은 녹화를 상한 있는 실행기로 돌리면 공백 끝에서 시간 청산
    msgs = [_fb("2026-11-03T09:30:00.100", 0.7450, 0.7451, "093000"),
            _ka("2026-11-03T09:30:00.200", 1340.0, "093000"),
            _ka("2026-11-03T09:30:15.200", 1340.0, "093015"),      # stale_s(20초) 안에 이어지게
            _ka("2026-11-03T09:30:30.200", 1340.0, "093030"),
            _ka("2026-11-03T09:30:46.300", 1340.8, "093046"),
            _fb("2026-11-03T09:42:46.400", 0.7450, 0.7451, "094246")]
    assert RealtimeRun.__init__.__kwdefaults__["max_timer_catchup"] == realtime.MAX_TIMER_CATCHUP == 600
    got = replay.replay_realtime(loaded, msgs, tmp_path / "out", max_timer_catchup=realtime.MAX_TIMER_CATCHUP)
    assert got["trades"][0]["held_s"] > 700
    assert "건너뜀" in (tmp_path / "out" / "journal.jsonl").read_text(encoding="utf-8")


def test_RunSpec_mode_에_replay_가_있음():
    import typing

    from backend.team_pyrun import registry
    from backend.team_pyrun.live import RunSpec
    assert typing.get_args(typing.get_type_hints(RunSpec)["mode"]) == ("orders", "paper", "replay")
    assert registry.MODES == ("orders", "paper")        # 실행 세우기는 여전히 둘만
