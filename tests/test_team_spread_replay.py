"""스프레드 재생 — 다리별 1분봉 csv 로 같은 실행기를 서버 없이 돌린다 (`backend.team_spread.replay`).

작은 두 다리 csv: A(국내 원화 선물 꼴)·B(해외 달러 선물 꼴). 실행기는 직전 6분 스프레드 대비 z>2 면 짝(A 팔고 B 산다)을 낸다.
"""
import csv
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend import storage
from backend.nh_api import runtime
from backend.team_spread import replay as rp
from backend.team_spread.legs import Leg
from backend.team_spread.runner_files import load_runner

RUNNER = '''\
"""z 시험 실행기"""
LEGS = {"A": "A75", "B": "MKU"}


def run(ctx):
    hist = []
    held = False
    while ctx.running():
        m = ctx.next_minute(["A", "B"])
        if m is None:
            break
        s = m.legs["A"].close - m.legs["B"].close
        if len(hist) >= 6 and not held:
            w = hist[-6:]
            mean = sum(w) / 6
            sd = (sum((x - mean) ** 2 for x in w) / 6) ** 0.5
            if sd > 0 and (s - mean) / sd > 2:
                try:
                    ctx.target({"A": -1, "B": 1})
                    held = True
                except Exception as e:
                    ctx.log("rejected", 1, why=str(e))
        hist.append(s)
'''

A = Leg("A", "A75", "A75", "domestic", "KRX", "KRW", 0.1, 1000.0, "")
B = Leg("B", "MKU", "MKU", "overseas", "", "USD", 0.0001, 2.5, "")
LEGS = {"A": A, "B": B}
T0 = datetime(2026, 11, 9, 9, 0, 0)


def _write(path: Path, rows: list[tuple[int, float, float]]) -> Path:
    """rows = (분 번호, 시가, 종가)"""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ref_dt", "exch_tm", "open_pric", "high_pric", "low_pric", "close_pric", "cum_trd_qty"])
        for i, o, c in rows:
            t = T0 + timedelta(minutes=i)
            w.writerow([t.strftime("%Y%m%d"), t.strftime("%H%M%S"), o, max(o, c), min(o, c), c, 10])
    return path


def make_csvs(tmp: Path, *, skip_a=(), skip_b=(), n=12) -> dict[str, Path]:
    a, b = [], []
    for i in range(n):
        close_a = 100.0 + (0.1 if i % 2 else 0.0) if i < 8 else 101.0
        if i not in skip_a:
            a.append((i, round(close_a + 0.2, 4), close_a))
        if i not in skip_b:
            b.append((i, 50.3, 50.0))
    return {"A": _write(tmp / "a.csv", a), "B": _write(tmp / "b.csv", b)}


@pytest.fixture
def loaded(tmp_path):
    (tmp_path / "r.py").write_text(RUNNER, encoding="utf-8")
    return load_runner(tmp_path, "r.py")


def lines(out: Path, name="journal.jsonl") -> list[dict]:
    return [json.loads(x) for x in (out / name).read_text("utf-8").splitlines()]


def fills(out: Path) -> list[dict]:
    return [r for r in lines(out) if r["kind"] == "fill"]


def test_pairs_when_z_crosses_and_fills_at_next_open_plus_minus_a_tick(tmp_path, loaded):
    out = tmp_path / "out"
    summary = rp.replay(loaded, make_csvs(tmp_path), LEGS, out)
    f = fills(out)
    # 8 번째 분(09:08)에 짝: A 팔고 B 산다 — 체결은 다음 분(09:09) 시가 ∓/± 1틱
    assert [(x["leg"], x["qty"]) for x in f[:2]] == [("A", -1), ("B", 1)]
    assert f[0]["price"] == pytest.approx(101.2 - 0.1) and f[1]["price"] == pytest.approx(50.3 + 0.0001)
    assert f[0]["clock"] == "090800"
    assert f[0]["fee"] == 690.0 and f[1]["fee"] == 2.0          # 시장별 종이 수수료
    # CSV 가 끝나면 실행기가 돌려주고 보유를 정리한다 (마지막 분 종가 ± 1틱)
    assert [(x["leg"], x["qty"]) for x in f[2:]] == [("A", 1), ("B", -1)]
    assert f[2]["price"] == pytest.approx(101.0 + 0.1)
    assert summary["mode"] == "replay" and "보유 정리" in summary["ended_reason"]
    assert summary["legs"][0]["position"] == 0 and summary["holding_left"] == {}


def test_folder_shape_like_a_live_run(tmp_path, loaded):
    out = tmp_path / "out"
    rp.replay(loaded, make_csvs(tmp_path), LEGS, out)
    assert {p.name for p in out.iterdir()} >= {"run.json", "journal.jsonl", "summary.json"}      # api_log 는 호출이 있어야 생긴다
    run_json = json.loads((out / "run.json").read_text("utf-8"))
    assert run_json["kind"] == "spread" and run_json["mode"] == "replay" and run_json["state"] == "끝"
    kinds = {r["kind"] for r in lines(out)}
    assert {"minute", "fill", "leg", "event"} <= kinds


def test_same_input_twice_gives_identical_result(tmp_path, loaded):
    csvs = make_csvs(tmp_path)
    s1 = rp.replay(loaded, csvs, LEGS, tmp_path / "o1")
    s2 = rp.replay(loaded, csvs, LEGS, tmp_path / "o2")
    assert s1 == s2
    strip = lambda out: [{k: v for k, v in r.items() if k != "at"} for r in lines(out)]      # noqa: E731
    assert strip(tmp_path / "o1") == strip(tmp_path / "o2")


def test_target_refused_while_one_leg_has_no_bar(tmp_path, loaded):
    out = tmp_path / "out"
    rp.replay(loaded, make_csvs(tmp_path, skip_b=(8,)), LEGS, out)
    rejected = [r for r in lines(out) if r["kind"] == "log" and r["name"] == "rejected"]
    assert rejected and "장 쉼: B" in rejected[0]["why"]
    f = fills(out)
    assert f[0]["clock"] == "090900"        # B 봉이 돌아온 첫 분에야 짝이 나감
    assert not [r for r in lines(out) if r["kind"] == "revert"]       # 한쪽만 체결되지 않았다


def test_minutes_without_any_bar_are_a_closed_gap(tmp_path, loaded):
    out = tmp_path / "out"
    rp.replay(loaded, make_csvs(tmp_path, skip_a=(4, 5), skip_b=(4, 5)), LEGS, out)
    gaps = [r for r in lines(out) if r["kind"] == "gap"]
    assert len(gaps) == 1 and gaps[0]["cause"] == "장 쉼"
    assert gaps[0]["first"] == "20261109 090400" and gaps[0]["last"] == "20261109 090500"
    texts = [r["text"] for r in lines(out) if r["kind"] == "event"]
    assert any("장 쉼" in t for t in texts) and any("장 열림" in t for t in texts)


def test_never_touches_the_network(tmp_path, loaded, monkeypatch):
    class NoApi:
        def __getattr__(self, name):
            raise AssertionError(f"재생이 서버 api 를 불렀다: {name}")

    def boom(*a, **k):
        raise AssertionError("재생이 전송을 불렀다")

    monkeypatch.setattr(runtime, "client", boom)
    summary = rp.replay(loaded, make_csvs(tmp_path), LEGS, tmp_path / "out", api_module=NoApi())
    assert summary["api"]["calls"] == {}
    assert not (tmp_path / "out" / "api_log.jsonl").exists()


def test_csv_must_cover_every_leg_and_have_bars(tmp_path, loaded):
    csvs = make_csvs(tmp_path)
    with pytest.raises(rp.ReplayError, match="다리 B"):
        rp.replay(loaded, {"A": csvs["A"]}, LEGS, tmp_path / "o")
    empty = _write(tmp_path / "e.csv", [])
    with pytest.raises(rp.ReplayError, match="봉이 없"):
        rp.replay(loaded, {"A": csvs["A"], "B": empty}, LEGS, tmp_path / "o")


# ---------------------------------------------------------------- 명령줄
@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "state_dir", lambda env=None: tmp_path / "state")
    return tmp_path / "state"


def test_parse_explicit_leg_form(tmp_path):
    csvs = make_csvs(tmp_path)
    leg_args = [f"A={csvs['A']}:0.1:1000:KRW", f"B={csvs['B']}:0.0001:2.5:USD"]
    paths, legs = rp.parse_legs(leg_args, {"A": "A75", "B": "MKU"})
    assert paths == csvs
    assert legs["A"] == Leg("A", "A75", "A75", "domestic", "KRX", "KRW", 0.1, 1000.0, "")
    assert legs["B"] == Leg("B", "MKU", "MKU", "overseas", "", "USD", 0.0001, 2.5, "")


@pytest.mark.parametrize("bad", ["A", "A=x.csv", "A=x.csv:0.1:1000", "A=x.csv:0:1000:KRW", "A=x.csv:0.1:abc:KRW",
                                 "Z=x.csv:0.1:1000:KRW"])
def test_parse_rejects_malformed(bad):
    with pytest.raises(rp.ReplayError):
        rp.parse_legs([bad], {"A": "A75"})


def test_cli_writes_replay_folder_and_numbers_repeats(tmp_path, state, capsys):
    (tmp_path / "r.py").write_text(RUNNER, encoding="utf-8")
    csvs = make_csvs(tmp_path)
    argv = [str(tmp_path / "r.py"), f"A={csvs['A']}:0.1:1000:KRW", f"B={csvs['B']}:0.0001:2.5:USD"]
    assert rp.main(argv) == 0
    assert rp.main(argv) == 0
    assert (state / "spreads" / "20261109_r_replay" / "summary.json").exists()
    assert (state / "spreads" / "20261109_r_replay_2" / "summary.json").exists()
    assert "20261109_r_replay" in capsys.readouterr().out


def test_cli_usage_and_errors(tmp_path, state, capsys):
    assert rp.main([]) == 2
    (tmp_path / "r.py").write_text(RUNNER, encoding="utf-8")
    capsys.readouterr()
    assert rp.main([str(tmp_path / "r.py"), "A=x.csv:0.1:1000:KRW"]) == 2      # B 의 csv 가 없음
    assert "다리 B" in capsys.readouterr().err


def test_legs_from_master_needs_currency_and_only_overseas():
    rows = json.loads((Path(__file__).parent / "fixtures" / "team_spread" / "legs.json").read_text("utf-8"))
    master = lambda: (rows["overseas_rows"], rows["domestic_rows"])      # noqa: E731
    paths, legs = rp.parse_legs(["h=h.csv:USD"], {"h": "HO"}, from_master=True, master=master)
    assert paths == {"h": Path("h.csv")} and legs["h"].product == "HO" and legs["h"].currency == "USD"
    assert legs["h"].tick > 0 and legs["h"].tick_value > 0
    with pytest.raises(rp.ReplayError, match="통화"):
        rp.parse_legs(["h=h.csv"], {"h": "HO"}, from_master=True, master=master)
    with pytest.raises(rp.ReplayError, match="직접"):
        rp.parse_legs(["d=d.csv:KRW"], {"d": "A75"}, from_master=True, master=master)


# ---------------------------------------------------------------- 수정 1차: 세션 경계 체결가
def _two_day(tmp: Path) -> dict[str, Path]:
    """첫날 09:00~09:09 / 다음날 09:00~ — 첫날 마지막 분 종가 100.0, 다음날 시가 110.0."""
    def rows(base):
        out = []
        for day in (0, 1):
            for i in range(10):
                t = T0 + timedelta(days=day, minutes=i)
                c = 100.0 if day == 0 else 110.0
                out.append((t, c, c))
        return out
    paths = {}
    for name, base in (("A", 100.0), ("B", 50.0)):
        p = tmp / f"{name.lower()}2.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ref_dt", "exch_tm", "open_pric", "high_pric", "low_pric", "close_pric", "cum_trd_qty"])
            for t, o, c in rows(base):
                k = 1 if name == "A" else 0.5
                w.writerow([t.strftime("%Y%m%d"), t.strftime("%H%M%S"), o * k, o * k, o * k, c * k, 1])
        paths[name] = p
    return paths


ONCE = '''\
LEGS = {"A": "A75", "B": "MKU"}


def run(ctx):
    n = 0
    while ctx.running():
        m = ctx.next_minute(["A", "B"])
        if m is None:
            break
        n += 1
        if m.time == "090900" and m.date == "20261109":       # 첫날 마지막 분에 짝
            ctx.target({"A": 1, "B": -1})
'''


def test_fill_on_last_bar_of_a_day_does_not_take_next_morning_open(tmp_path):
    (tmp_path / "o.py").write_text(ONCE, encoding="utf-8")
    ld = load_runner(tmp_path, "o.py")
    out = tmp_path / "out"
    rp.replay(ld, _two_day(tmp_path), LEGS, out)
    f = fills(out)
    # 다음 분(= 다음날 09:00) 시가 110 이 아니라 그 분 종가 100 ± 1틱
    assert f[0]["leg"] == "A" and f[0]["price"] == pytest.approx(100.0 + 0.1)
    assert f[1]["leg"] == "B" and f[1]["price"] == pytest.approx(50.0 - 0.0001)


def test_fill_does_not_use_carried_price_of_a_closed_leg(tmp_path):
    from backend.team_spread.bars import LegBar, Minute
    real = LegBar(10.0, 10.0, 10.0, 10.0, 1, False)
    carried = LegBar(99.0, 99.0, 99.0, 99.0, 0, True)
    ms = [Minute("20261109", "090000", {"A": real, "B": real}), Minute("20261109", "090100", {"A": real, "B": carried})]
    feed = rp.ReplayFeed(ms)
    feed.next_minute([A, B], threading.Event())
    assert feed.fill_price(B, 1) == pytest.approx(10.0 + 0.0001)      # 99 가 아니라 지금 종가
    assert feed.fill_price(A, 1) == pytest.approx(10.0 + 0.1)


# ---------------------------------------------------------------- 수정 1차: 나쁜 csv
@pytest.mark.parametrize("content,match", [
    ("ref_dt,exch_tm,open_pric,high_pric,low_pric,close_pric\n20261109,090000,1,1,1,abc\n", r"b\.csv.*2.*close_pric"),
    ("ref_dt,exch_tm,open_pric,high_pric,low_pric,close_pric\n20261109,,1,1,1,1\n", r"b\.csv.*2.*exch_tm"),
    ("ref_dt,exch_tm,open_pric,high_pric,low_pric,close_pric\n20261109,090000,1,1,1,nan\n", r"b\.csv.*2"),
])
def test_bad_csv_rows_become_replay_error(tmp_path, loaded, content, match):
    csvs = make_csvs(tmp_path)
    csvs["B"] = tmp_path / "b.csv"
    csvs["B"].write_text(content, encoding="utf-8")
    with pytest.raises(rp.ReplayError, match=match):
        rp.replay(loaded, csvs, LEGS, tmp_path / "o")


def test_non_utf8_csv_and_cli_give_message_not_traceback(tmp_path, state, capsys):
    (tmp_path / "r.py").write_text(RUNNER, encoding="utf-8")
    csvs = make_csvs(tmp_path)
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"ref_dt,exch_tm\n\xff\xfe\x00\n")
    argv = [str(tmp_path / "r.py"), f"A={csvs['A']}:0.1:1000:KRW", f"B={bad}:0.0001:2.5:USD"]
    assert rp.main(argv) == 2
    assert "bad.csv" in capsys.readouterr().err
