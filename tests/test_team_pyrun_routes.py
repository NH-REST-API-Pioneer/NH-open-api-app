"""파이썬 전략 라우트(`/api/team/pyrun`) 시험 — 목록·시작 거부·이어 읽기·차트용 봉·내려받기·앱 연결.

`registry()` 싱글턴 자리를 `tmp_path` 의 `Registry`(스레드 없음, 가짜 api)로 바꿔 씁니다 — `~/NHFutures` 는 건드리지 않습니다.
끝난 실행 폴더는 Task 3 의 리플레이로 만듭니다(`20261030_bb_replay`).
"""
import asyncio
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main as app_main
from backend.main import app
from backend.nh_api import client as nh_client
from backend.team_pyrun import apilog
from backend.team_pyrun import registry as registry_mod
from backend.team_pyrun import routes as routes_mod
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import RunSpec
from backend.team_pyrun.loader import load
from backend.team_pyrun.replay import load_minutes, replay
from tests.test_team_pyrun_registry import FIXTURES, make_registry, write_run

DATA = FIXTURES.parent / "bars_1m_A756B000_20261030.csv"
BASE = "/api/team/pyrun"
FINISHED = "20261030_bb_replay"
STATUS_KEYS = ["id", "file", "name", "title", "mode", "sym", "state", "started_at", "ended_at", "ended_reason",
               "bar_min", "next_decision_at", "position", "entry", "stop", "stop_ticks", "target", "time_exit_at",
               "today_pnl", "stops", "max_stops", "halted", "last_signal", "params"]


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """싱글턴 자리를 시험용 `Registry` 로 바꾸고, 끝난 리플레이 실행 폴더 하나를 깔아 둔다."""
    r, fake, _ = make_registry(tmp_path, bb=True)
    monkeypatch.setattr(registry_mod, "_registry", r)
    replay(load(r.strategies, "strategy_bb.py"), "20261030", load_minutes(DATA), r.root / FINISHED)
    r.fake = fake
    return r


@pytest.fixture
def client(reg):
    return TestClient(app)


def _zip(response):
    return zipfile.ZipFile(io.BytesIO(response.content))


# ---------------------------------------------------------------- 전략 목록
def test_전략_목록(client, reg):
    r = client.get(f"{BASE}/strategies")
    assert r.status_code == 200
    body = r.json()
    assert body["folder"] == str(reg.strategies)
    by_file = {s["file"]: s for s in body["strategies"]}
    assert by_file["strategy_bb.py"]["name"] == "bb" and by_file["strategy_bb.py"]["error"] is None
    assert by_file["strategy_bb.py"]["params"]["bar_min"] == 5
    assert {"file", "name", "title", "params", "error"} == set(by_file["fake.py"])
    # 다시 읽기는 같은 것 — 그 사이 새로 놓은 파일도 보인다
    (reg.strategies / "late.py").write_text("raise RuntimeError('깨짐')\n", encoding="utf-8")
    again = client.post(f"{BASE}/strategies/reload").json()
    late = next(s for s in again["strategies"] if s["file"] == "late.py")
    assert late["error"] and late["name"] is None


# ---------------------------------------------------------------- 시작
def test_시작은_201_과_상태_칸을_돌려준다(client, reg):
    r = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None})
    assert r.status_code == 201
    status = r.json()
    assert list(status) == STATUS_KEYS and status["mode"] == "paper" and status["state"] == "대기"
    listed = client.get(f"{BASE}/runs").json()["runs"]
    assert status["id"] in [x["id"] for x in listed] and FINISHED in [x["id"] for x in listed]
    # 도는(이 앱에서 세운) 실행은 status() 그대로
    assert client.get(f"{BASE}/runs/{status['id']}").json()["state"] == "대기"
    assert list(client.get(f"{BASE}/runs/{status['id']}").json()) == STATUS_KEYS


def test_시작_거부는_409(client, reg):
    r = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "bogus"})        # sym 은 생략해도 된다
    assert r.status_code == 409 and "실행 방식" in r.json()["detail"]
    r = client.post(f"{BASE}/runs", json={"file": "nope.py", "mode": "paper", "sym": None})
    assert r.status_code == 409 and "전략" in r.json()["detail"]
    r = client.post(f"{BASE}/runs", json={"file": "../x.py", "mode": "paper", "sym": None})
    assert r.status_code == 409
    # 같은 종목 주문 실행은 하나만
    ok = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "orders", "sym": None})
    assert ok.status_code == 201
    dup = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "orders", "sym": None})
    assert dup.status_code == 409 and "이미" in dup.json()["detail"]
    assert reg.fake.orders == []


def test_본문이_모자라면_422(client):
    assert client.post(f"{BASE}/runs", json={"mode": "paper"}).status_code == 422


# ---------------------------------------------------------------- 조회
def test_끝난_실행은_run_json_과_요약을_합쳐_돌려준다(client):
    r = client.get(f"{BASE}/runs/{FINISHED}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == FINISHED and body["state"] == "끝" and body["mode"] == "replay"
    assert body["summary"]["trades"] == 3 and body["summary"]["net_pnl"] == 54000
    assert "sha256" in body


def test_끝난_실행의_멈춤과_결과_모름_주문도_올라온다(client, reg):
    folder = write_run(reg.root, "20261029_fake_orders", state="끝")
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    run["halted"] = "잔고 불일치"
    (folder / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps(
        {"summary": {"trades": 0}, "unresolved_order": "12345 (buy)"}), encoding="utf-8")
    body = client.get(f"{BASE}/runs/20261029_fake_orders").json()
    assert body["halted"] == "잔고 불일치" and body["unresolved_order"] == "12345 (buy)"
    assert body["summary"] == {"trades": 0}


def test_끝난_실행은_그때의_Params_를_돌려준다(client):
    """지난 실행 화면이 지금 파일 값이 아니라 그 실행이 쓴 Params(요약 파일의 `strategy.params`)를 보이게."""
    body = client.get(f"{BASE}/runs/{FINISHED}").json()
    assert body["params"]["bar_min"] == 5
    assert body["params"]["session_start"] == "090000"


def test_요약에_전략_정보가_없으면_params_는_null(client, reg):
    folder = write_run(reg.root, "20261028_fake_old", state="끝")
    (folder / "summary.json").write_text(json.dumps({"summary": {"trades": 0}}), encoding="utf-8")
    assert client.get(f"{BASE}/runs/20261028_fake_old").json()["params"] is None


def test_없는_실행은_404(client):
    for path in ("", "/journal", "/api-log", "/bars", "/download"):
        assert client.get(f"{BASE}/runs/20200101_none_paper{path}").status_code == 404, path
    assert client.get(f"{BASE}/runs/..%2Fetc/journal").status_code == 404
    assert client.get(f"{BASE}/runs/a-b/journal").status_code == 404           # id 글자가 아니다
    assert client.post(f"{BASE}/runs/20200101_none_paper/stop").status_code == 404
    assert client.post(f"{BASE}/runs/20200101_none_paper/flatten").status_code == 404


def test_이어_읽기(client, reg):
    j = Journal(reg.root / FINISHED / "journal.jsonl")
    total = j.count()
    first = client.get(f"{BASE}/runs/{FINISHED}/journal").json()
    assert first["next"] == total and len(first["rows"]) == total and first["rows"][0]["kind"]
    j.write("event", text="새 줄")
    rest = client.get(f"{BASE}/runs/{FINISHED}/journal", params={"after": first["next"]}).json()
    assert [x["text"] for x in rest["rows"]] == ["새 줄"] and rest["next"] == total + 1
    nothing = client.get(f"{BASE}/runs/{FINISHED}/journal", params={"after": rest["next"]}).json()
    assert nothing == {"rows": [], "next": total + 1}
    # api 호출 기록은 없으면 빈 것, 있으면 같은 꼴
    assert client.get(f"{BASE}/runs/{FINISHED}/api-log").json() == {"rows": [], "next": 0}
    log = reg.root / FINISHED / "api_log.jsonl"
    log.write_text('{"api_id": "a"}\n깨진 줄\n{"api_id": "b"}\n', encoding="utf-8")
    got = client.get(f"{BASE}/runs/{FINISHED}/api-log").json()
    assert [x["api_id"] for x in got["rows"]] == ["a", "b"] and got["next"] == 3
    assert client.get(f"{BASE}/runs/{FINISHED}/api-log", params={"after": 2}).json()["rows"] == [{"api_id": "b"}]
    assert client.get(f"{BASE}/runs/{FINISHED}/journal", params={"after": -1}).status_code == 422


def test_차트용_봉과_표시(client, reg):
    body = client.get(f"{BASE}/runs/{FINISHED}/bars").json()
    bars, marks = body["bars"], body["marks"]
    assert len(bars) == 79                                   # 5분봉 09:00 … 15:30 시작
    last = bars[-1]
    assert last["date"] == "20261030" and last["start"] == "153000" and last["end"] == "153400"
    assert {"open", "high", "low", "close", "upper", "middle", "lower", "rsi", "atr"} <= set(last)
    assert all(isinstance(b["open"], float) and b["low"] <= b["close"] <= b["high"] for b in bars)
    for k in ("kind", "at", "clock", "bar"):
        assert k not in last
    # 표시: 세 거래 = 진입·청산 체결 여섯 + 거래 세 줄
    kinds = [m["kind"] for m in marks]
    assert kinds.count("entry") == 3 and kinds.count("exit") == 3 and kinds.count("trade") == 3
    first = marks[0]
    assert first["kind"] == "entry" and first["date"] == "20261030" and first["time"] == "093500"
    assert first["side"] == "sell" and first["price"] == 1339.6
    entry_fills = [m for m in marks if m["kind"] == "entry"]
    assert [m["side"] for m in entry_fills] == ["sell", "buy", "buy"]
    trade = next(m for m in marks if m["kind"] == "trade")
    assert (trade["side"], trade["price"], trade["time"], trade["reason"]) == ("sell", 1337.7, "101700", "익절")


def test_차트용_봉_옛_기록은_시고저가_비어_있다(client, reg):
    folder = write_run(reg.root, "20261029_old_paper", state="끝")
    j = Journal(folder / "journal.jsonl")
    j.write("signal", clock="090500", date="20261029", bar="090000", close=1335.0, side=None, reason="x", rsi=50.0)
    bar = client.get(f"{BASE}/runs/20261029_old_paper/bars").json()["bars"][0]
    assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["rsi"]) == (None, None, None, 1335.0, 50.0)


# ---------------------------------------------------------------- 내려받기
def test_끝난_실행을_zip_으로_받는다(client, reg):
    (reg.root / FINISHED / "api_log.jsonl").write_text('{"api_id": "a"}\n', encoding="utf-8")
    r = client.get(f"{BASE}/runs/{FINISHED}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == f'attachment; filename="{FINISHED}.zip"'
    z = _zip(r)
    assert set(z.namelist()) == {f"{FINISHED}/journal.jsonl", f"{FINISHED}/summary.json", f"{FINISHED}/api_log.jsonl"}
    assert z.read(f"{FINISHED}/journal.jsonl") == (reg.root / FINISHED / "journal.jsonl").read_bytes()


def test_zip_에는_run_json_이나_다른_파일이_안_들어간다(client, reg):
    (reg.root / FINISHED / "memo.txt").write_text("남기지 말 것", encoding="utf-8")
    z = _zip(client.get(f"{BASE}/runs/{FINISHED}/download"))
    assert not any(n.endswith("run.json") or n.endswith("memo.txt") for n in z.namelist())
    # 요약·호출 기록이 아직 없으면 있는 것만
    folder = write_run(reg.root, "20261029_x_paper", state="끝", trades=[{"reason": "익절"}])
    assert _zip(client.get(f"{BASE}/runs/20261029_x_paper/download")).namelist() == ["20261029_x_paper/journal.jsonl"]
    assert folder.joinpath("run.json").exists()


def test_진행_중인_실행은_partial_이름으로(client, reg):
    run_id = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None}).json()["id"]
    r = client.get(f"{BASE}/runs/{run_id}/download")
    assert r.headers["content-disposition"] == f'attachment; filename="{run_id}_partial.zip"'
    names = _zip(r).namelist()
    assert f"{run_id}/journal.jsonl" in names and not any(n.endswith("run.json") for n in names)
    # 끝나면 평소 이름
    assert client.post(f"{BASE}/runs/{run_id}/stop").status_code == 204
    done = client.get(f"{BASE}/runs/{run_id}/download")
    assert done.headers["content-disposition"] == f'attachment; filename="{run_id}.zip"'
    assert f"{run_id}/summary.json" in _zip(done).namelist()


# ---------------------------------------------------------------- 중지·정리
def test_중지는_204_정리는_이_앱의_실행만(client, reg):
    run_id = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None}).json()["id"]
    assert client.post(f"{BASE}/runs/{run_id}/flatten").status_code == 204
    assert client.post(f"{BASE}/runs/{run_id}/stop").status_code == 204
    assert client.get(f"{BASE}/runs/{run_id}").json()["state"] == "끝"
    # 이전 실행(이 프로세스에서 세우지 않은 폴더)은 정리·중지할 수 없다
    assert client.post(f"{BASE}/runs/{FINISHED}/flatten").status_code == 409
    assert client.post(f"{BASE}/runs/{FINISHED}/stop").status_code == 409


# ---------------------------------------------------------------- 앱 연결
def test_앱이_뜨면_호출_관찰자를_꽂고_남은_실행을_닫는다(reg, monkeypatch):
    monkeypatch.setattr(nh_client, "call_observer", None)
    write_run(reg.root, "20261029_fake_paper", state="진행 중")
    task = asyncio.run(_startup_then_wait())
    assert nh_client.call_observer is apilog.observe
    assert json.loads((reg.root / "20261029_fake_paper" / "run.json").read_text(encoding="utf-8"))["ended_reason"] == "재시작"
    assert task is not None
    asyncio.run(routes_mod.pyrun_shutdown(None))
    assert nh_client.call_observer is None


async def _startup_then_wait():
    task = routes_mod.pyrun_startup()
    await task
    return task


def test_복구가_실패해도_앱은_뜬다(reg, monkeypatch, caplog):
    def boom():
        raise RuntimeError("복구 실패")
    monkeypatch.setattr(reg, "recover", boom)
    asyncio.run(_startup_then_wait())            # 예외가 밖으로 나오지 않는다
    assert "복구 실패" in caplog.text


def test_앱이_꺼지면_모든_실행에_중지를_요청한다(reg):
    run = reg.start(RunSpec("fake.py", "paper", None))
    asyncio.run(routes_mod.pyrun_shutdown(None))
    assert reg.get(run["id"]).state == "끝"


def test_라우터와_수명_연결이_main_에_있다():
    paths = app.openapi()["paths"]
    assert f"{BASE}/runs" in paths and f"{BASE}/runs/{{run_id}}/download" in paths
    assert app_main.pyrun_startup is routes_mod.pyrun_startup and app_main.pyrun_shutdown is routes_mod.pyrun_shutdown


# ---------------------------------------------------------------- 다른 사이트에서 온 요청 막기 (R24)
DENIED = {"detail": "다른 사이트에서 온 요청은 받지 않습니다"}
UNSAFE = [("post", "/runs/20261030_bb_replay/stop", None), ("post", "/runs/20261030_bb_replay/flatten", None),
          ("post", "/runs", {"file": "fake.py", "mode": "paper", "sym": None}),
          ("post", "/strategies/reload", None)]


@pytest.fixture
def untouched(reg, monkeypatch):
    """레지스트리의 쓰는 메서드가 불리면 시험이 실패하게 한다(거절된 요청은 닿지 않아야 한다)."""
    def boom(*a, **k):
        raise AssertionError("거절됐어야 할 요청이 레지스트리에 닿았다")
    for name in ("start", "stop", "flatten", "get"):
        monkeypatch.setattr(reg, name, boom)
    return reg


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_다른_사이트_Origin_은_403_이고_레지스트리에_닿지_않는다(client, untouched, method, path, body):
    for origin in ("https://evil.example", "http://localhost.evil.com", "null", "http://192.168.0.5:5173"):
        r = getattr(client, method)(f"{BASE}{path}", json=body, headers={"Origin": origin})
        assert (r.status_code, r.json()) == (403, DENIED), origin


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_Sec_Fetch_Site_cross_site_는_403(client, untouched, method, path, body):
    r = getattr(client, method)(f"{BASE}{path}", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert (r.status_code, r.json()) == (403, DENIED)
    # Origin 이 로컬이어도 브라우저가 cross-site 라고 하면 거절
    r = getattr(client, method)(f"{BASE}{path}", json=body,
                                headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://localhost:5173"})
    assert r.status_code == 403


def test_로컬_Origin_과_Origin_없음은_받는다(client, reg):
    run_id = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None}).json()["id"]   # Origin 없음
    for origin in ("http://localhost:5173", "http://127.0.0.1:8000", "http://localhost", "http://[::1]:5173"):
        r = client.post(f"{BASE}/runs/{run_id}/flatten", headers={"Origin": origin})
        assert r.status_code == 204, origin
    r = client.post(f"{BASE}/runs/{run_id}/stop", headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"})
    assert r.status_code == 204
    assert client.post(f"{BASE}/runs/{run_id}/stop", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 204


def test_조회는_Origin_을_가리지_않는다(client):
    assert client.get(f"{BASE}/runs", headers={"Origin": "https://evil.example"}).status_code == 200


def test_시작은_JSON_Content_Type_만_받는다(client, untouched):
    body = '{"file": "fake.py", "mode": "paper", "sym": null}'
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        r = client.post(f"{BASE}/runs", content=body, headers={"Content-Type": ctype})
        assert r.status_code == 415, ctype
    assert client.post(f"{BASE}/runs", content=body).status_code == 415             # 헤더 없음도 JSON 이 아니다
