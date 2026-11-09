"""리플레이 — 아무 품목 · 자정을 넘는 거래일 (설계 4.8). 서버·주문 없음, 합성 HO 1분봉으로만 본다."""
import json
from datetime import datetime, timedelta

from backend.team_pyrun import replay as replay_mod
from tests.test_team_pyrun_live_overnight import NIGHT_SRC


def write_csv(path, start: datetime, end: datetime, price: float = 0.5):
    rows = ["ref_dt,exch_tm,open_pric,high_pric,low_pric,close_pric,cum_trd_qty,cum_trd_amt,opint,diff_rt,rt"]
    t = start
    while t <= end:
        rows.append(f"{t:%Y%m%d},{t:%H%M%S},{price:.4f},{price + 0.0002:.4f},{price - 0.0002:.4f},{price:.4f},10,0,0,0,")
        t += timedelta(minutes=1)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def setup(tmp_path, monkeypatch, csv_name):
    folder = tmp_path / "strategies"
    folder.mkdir()
    (folder / "night.py").write_text(NIGHT_SRC, encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setattr(replay_mod.storage, "state_dir", lambda env=None: state)
    monkeypatch.setattr(replay_mod, "strategies_dir", lambda: folder)
    csv = tmp_path / csv_name
    write_csv(csv, datetime(2026, 11, 9, 22, 0), datetime(2026, 11, 10, 6, 0))
    return state, csv


def test_품목_지정_리플레이는_자정을_넘어_한_거래일로_이어진다(tmp_path, monkeypatch):
    state, csv = setup(tmp_path, monkeypatch, "bars_1m_HOZ26_20261109.csv")
    code = replay_mod.main(["night.py", "20261109", str(csv), "--market", "overseas", "--currency", "USD"])
    assert code == 0
    out = state / "pyruns" / "20261109_night_replay"
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["currency"] == "USD" and summary["market"] == "overseas"
    assert summary["summary"]["trades"] == 1
    lines = [json.loads(x) for x in (out / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    trade = next(x for x in lines if x.get("kind") == "trade")
    assert (trade["entry_time"], trade["exit_time"], trade["exit_date"]) == ("235900", "244400", "20261109")
    assert trade["reason"] == "시간 청산" and "USD" in trade["text"]       # 45분 보유 — 자정을 넘어 이어짐


def test_시장_지정_없이_품목_csv_면_시장이_맞지_않다(tmp_path, monkeypatch, capsys):
    state, csv = setup(tmp_path, monkeypatch, "bars_1m_HOZ26_20261109.csv")
    assert replay_mod.main(["night.py", "20261109", str(csv)]) == 2
    assert "시장이 맞지 않습니다" in capsys.readouterr().err


def test_시장_지정이면_품목_코드_가드_없이_봉_한_개_날도_쓴다(tmp_path):
    csv = tmp_path / "bars_1m_HOZ26.csv"
    write_csv(csv, datetime(2026, 11, 9, 22, 0), datetime(2026, 11, 9, 22, 4))
    assert replay_mod.load_minutes(csv, market=replay_mod.DOMESTIC) == []          # 국내 기본 250봉
    assert len(replay_mod.load_minutes(csv, market=replay_mod.DOMESTIC, min_bars=1)) == 5
    assert len(replay_mod.load_minutes(csv, market=replay_mod.OVERSEAS)) == 5


def test_기록_글의_통화는_지정한_통화로(tmp_path, monkeypatch):
    state, csv = setup(tmp_path, monkeypatch, "bars_1m_HOZ26_20261109.csv")
    assert replay_mod.main(["night.py", "20261109", str(csv), "--market", "overseas", "--currency", "JPY"]) == 0
    out = state / "pyruns" / "20261109_night_replay"
    lines = [json.loads(x) for x in (out / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    text = next(x for x in lines if x.get("kind") == "trade")["text"]
    assert "JPY" in text and "USD" not in text and "수수료" in text
