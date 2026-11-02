"""실행 기록(journal.jsonl)·요약 시험."""
from __future__ import annotations

import json
import threading

from backend.team_pyrun.journal import Journal, count_stops, scrub, summarize, write_summary


def test_계좌_식별정보와_토큰은_쓰기_전에_지운다(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    j.write("event", raw={"occurs1_ac_no": "1", "ac_nm": "x", "ord_no": "7", "Occurs1": [{"occurs1_user_ip_addr": "ip"}]},
            authorization="Bearer t")
    text = (tmp_path / "journal.jsonl").read_text()
    for k in ("ac_no", "ac_nm", "user_ip_addr", "authorization", "Bearer"):
        assert k not in text
    assert '"ord_no": "7"' in text


def test_scrub_은_대소문자를_가리지_않고_중첩까지_지운다():
    out = scrub({"Authorization": "x", "a": [{"Occurs1_Ord_Id": 1, "App_Secret": 2, "keep": 3}],
                 "access_token": "t", "appkey": "k", "ok": 1})
    assert out == {"a": [{"keep": 3}], "ok": 1}


def test_이어_읽기(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    [j.write("event", text=str(i)) for i in range(3)]
    assert [r["text"] for r in j.read(after=1)] == ["1", "2"] and j.count() == 3


def test_쓴_줄은_kind_at_을_갖고_시각은_시간대_꼬리가_없다(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    rec = j.write("event", x=1)
    assert rec["kind"] == "event" and rec["x"] == 1
    assert len(rec["at"]) == 19 and "+" not in rec["at"] and rec["at"][10] == "T"
    assert json.loads((tmp_path / "j.jsonl").read_text()) == rec


def test_덜_쓴_마지막_줄은_건너뛴다(tmp_path):
    p = tmp_path / "j.jsonl"
    j = Journal(p)
    j.write("event", text="0")
    with p.open("a", encoding="utf-8") as f:
        f.write('{"kind": "event", "te')
    assert [r["text"] for r in j.read()] == ["0"]


def test_여러_스레드가_써도_줄이_섞이지_않는다(tmp_path):
    j = Journal(tmp_path / "j.jsonl")

    def work(n):
        for i in range(50):
            j.write("event", n=n, i=i, pad="가" * 200)

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert j.count() == 400 and len(j.read()) == 400


def test_요약은_week02_와_같은_칸():
    s = summarize([{"pnl": 21000, "reason": "익절", "exit_date": "20261030", "fee": 1380.0},
                   {"pnl": -5000, "reason": "손절", "exit_date": "20261030", "fee": 1380.0}])
    assert s == {"trades": 2, "wins": 1, "win_rate": 0.5, "net_pnl": 16000, "profit_factor": 4.2,
                 "avg_win": 21000, "avg_loss": -5000, "max_drawdown": 5000.0,
                 "by_reason": {"익절": 1, "손절": 1}, "by_day": {"20261030": 16000},
                 "fee_total": 2760.0, "net_pnl_after_fee": 13240.0}


def test_요약_거래가_없거나_수수료를_모르면_수수료_칸이_없다():
    assert summarize([])["win_rate"] is None and "fee_total" not in summarize([])
    s = summarize([{"pnl": 1, "reason": "익절", "exit_date": "20261030"}])
    assert "fee_total" not in s and s["profit_factor"] is None


def test_그날_손절_수는_여러_폴더를_합쳐_센다(tmp_path):
    def trade(reason, date):
        return json.dumps({"kind": "trade", "reason": reason, "exit_date": date}, ensure_ascii=False)

    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    (a / "journal.jsonl").write_text(
        "\n".join([trade("손절", "20261030"), trade("익절", "20261030"), "{깨진 줄",
                   json.dumps({"kind": "event", "reason": "손절", "exit_date": "20261030"})]) + "\n", encoding="utf-8")
    (b / "journal.jsonl").write_text("\n".join([trade("손절", "20261030"), trade("손절", "20261029")]), encoding="utf-8")
    # c 에는 파일이 없음
    assert count_stops([a, b, c], "20261030") == 2
    assert count_stops([], "20261030") == 0


def test_요약_파일은_들여쓰기_1(tmp_path):
    p = write_summary(tmp_path / "run", {"한글": 1})
    assert p == tmp_path / "run" / "summary.json"
    assert p.read_text(encoding="utf-8") == '{\n "한글": 1\n}'


def test_요약_파일도_쓰는_순간_계좌_식별정보를_지운다(tmp_path):
    p = write_summary(tmp_path, {"account_start": {"occurs1_ac_no": "1", "fee": "690"}})
    text = p.read_text(encoding="utf-8")
    assert "ac_no" not in text and '"fee": "690"' in text


def test_해외_응답의_사용자_IP_계좌_칸은_접미사로도_지운다(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    j.write("event", raw={"occurs1_user_id": "u", "occurs1_ip_addr": "1.2.3.4", "action_acnt": "123",
                          "cust_acnt_no": "9", "ord_no": "7", "fee": "690"})
    text = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    for k in ("user_id", "ip_addr", "action_acnt", "acnt_no", "1.2.3.4"):
        assert k not in text
    assert '"ord_no": "7"' in text and '"fee": "690"' in text
