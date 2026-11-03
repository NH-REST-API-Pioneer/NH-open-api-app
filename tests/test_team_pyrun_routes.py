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
               "today_pnl", "stops", "max_stops", "halted", "last_signal", "params", "market", "currency"]


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
    assert {"file", "name", "title", "params", "error", "notes"} == set(by_file["fake.py"])
    assert by_file["fake.py"]["notes"] == []
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


def test_이_앱에서_끝난_실행도_요약과_결과_모름_주문을_합쳐_돌려준다(client, reg):
    """끝난(끝·오류) 실행은 이 프로세스가 세운 것이어도 폴더에서 읽은 것과 같은 칸(`summary`·`unresolved_order`)이 온다."""
    run_id = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None}).json()["id"]
    assert client.post(f"{BASE}/runs/{run_id}/stop").status_code == 204
    folder = reg.root / run_id
    s = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    s["unresolved_order"] = {"side": "buy", "pre": 0, "post": 1}
    (folder / "summary.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    body = client.get(f"{BASE}/runs/{run_id}").json()
    assert body["state"] == "끝" and body["id"] == run_id
    assert body["summary"] == s["summary"] and body["summary"]["trades"] == 0
    assert body["unresolved_order"] == {"side": "buy", "pre": 0, "post": 1}
    assert body["params"]["bar_min"] == 1 and "halted" in body


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
          ("post", "/strategies/reload", None),
          ("post", "/strategies", {"file": "up.py", "content": "x = 1\n", "overwrite": True}),
          ("delete", "/strategies/fake.py", None)]


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
        r = client.request(method.upper(), f"{BASE}{path}", json=body, headers={"Origin": origin})
        assert (r.status_code, r.json()) == (403, DENIED), origin


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_Sec_Fetch_Site_cross_site_는_403(client, untouched, method, path, body):
    r = client.request(method.upper(), f"{BASE}{path}", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert (r.status_code, r.json()) == (403, DENIED)
    # Origin 이 로컬이어도 브라우저가 cross-site 라고 하면 거절
    r = client.request(method.upper(), f"{BASE}{path}", json=body,
                       headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://localhost:5173"})
    assert r.status_code == 403


def test_로컬_Origin_과_Origin_없음은_받는다(client, reg):
    run_id = client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None}).json()["id"]   # Origin 없음
    # (Origin, Host) — Host 도 로컬이어야 한다. 마지막은 개발 서버(vite, changeOrigin)가 :5173 에서 :8000 으로 넘기는 모양.
    for origin, host in (("http://localhost:5173", "localhost:8000"), ("http://127.0.0.1:8000", "127.0.0.1:8000"),
                         ("http://localhost", "localhost"), ("http://[::1]:5173", "localhost:8000"),
                         ("http://localhost:5173", "127.0.0.1:8000")):
        r = client.post(f"{BASE}/runs/{run_id}/flatten", headers={"Origin": origin, "Host": host})
        assert r.status_code == 204, (origin, host)
    r = client.post(f"{BASE}/runs/{run_id}/stop", headers={"Origin": "http://localhost:5173", "Host": "127.0.0.1:8000",
                                                           "Sec-Fetch-Site": "same-site"})
    assert r.status_code == 204
    assert client.post(f"{BASE}/runs/{run_id}/stop", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 204


# 서버 배포(도커 + Cloudflare Tunnel): 브라우저가 https://nh.example.com 으로 열면 Origin 이 그 주소이고 Host 도 그 주소다.
# 시험 환경의 NH_PUBLIC_HOSTS 는 conftest 가 "testserver,nh.example.com" 으로 정한다.
SITE = "nh.example.com"
REBIND = "rebind.attacker.tld:8000"


@pytest.fixture
def public_client(reg):
    """터널 뒤에서 보는 모양: 요청이 https://nh.example.com 으로 들어온다(Host nh.example.com, scheme https)."""
    return TestClient(app, base_url=f"https://{SITE}")


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_공개_주소_Origin_은_Host_와_같고_NH_PUBLIC_HOSTS_에_있으면_받는다(public_client, reg, method, path, body):
    # 거절되지 않았다는 것만 본다(403 이 아니면 된다 — 실행 id·파일 때문에 다른 4xx 는 날 수 있다)
    r = public_client.request(method.upper(), f"{BASE}{path}", json=body, headers={"Origin": f"https://{SITE}"})
    assert r.status_code != 403, r.text
    r = public_client.request(method.upper(), f"{BASE}{path}", json=body, headers={"Origin": f"https://{SITE}:443"})
    assert r.status_code != 403, r.text


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_DNS_리바인딩_Host_는_앱_전체가_400(client, untouched, method, path, body):
    """리바인딩된 `rebind.attacker.tld:8000` 은 Origin 도 Host 도 같지만 허용 Host 가 아니라 라우트에 닿기 전에 막힌다."""
    r = client.request(method.upper(), f"{BASE}{path}", json=body,
                       headers={"Origin": f"http://{REBIND}", "Host": REBIND})
    assert (r.status_code, r.text) == (400, "Invalid host header")


def test_모르는_Host_는_조회도_운영자_라우트도_400(client):
    for path in ("/api/health", f"{BASE}/strategies", "/"):
        r = client.get(path, headers={"Host": REBIND})
        assert (r.status_code, r.text) == (400, "Invalid host header"), path
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200      # just serve
    assert client.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 200      # vite changeOrigin
    assert client.get("/api/health", headers={"Host": SITE}).status_code == 200                  # NH_PUBLIC_HOSTS


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_localhost_Origin_이라도_Host_가_로컬이_아니면_403(client, untouched, method, path, body):
    for origin in ("http://localhost:3000", "http://127.0.0.1:8000", "http://[::1]:5173"):
        r = client.request(method.upper(), f"{BASE}{path}", json=body, headers={"Origin": origin, "Host": SITE})
        assert (r.status_code, r.json()) == (403, DENIED), origin


@pytest.mark.parametrize("method,path,body", UNSAFE)
def test_공개_주소_Origin_이_Host_와_다르면_403(public_client, untouched, method, path, body):
    cases = [
        "http://" + SITE,                  # 공개 주소는 https(443) 인데 http(80) Origin
        "https://evil.com",
        f"https://{SITE}.evil.com",
        f"https://evil.{SITE}",
        f"https://{SITE}:8443",            # 같은 호스트라도 포트가 다르면 다른 출처
        f"http://{SITE}:8000",
        "null",
        "https://",
    ]
    for origin in cases:
        r = public_client.request(method.upper(), f"{BASE}{path}", json=body, headers={"Origin": origin})
        assert (r.status_code, r.json()) == (403, DENIED), origin


def test_NH_PUBLIC_HOSTS_에_없는_공개_주소는_Host_와_같아도_403(public_client, untouched, monkeypatch):
    monkeypatch.setenv("NH_PUBLIC_HOSTS", "testserver")      # 미들웨어 목록은 앱을 만들 때 읽어 그대로 두고, 라우트는 부를 때마다 읽는다
    r = public_client.post(f"{BASE}/runs/{FINISHED}/stop", headers={"Origin": f"https://{SITE}"})
    assert (r.status_code, r.json()) == (403, DENIED)
    monkeypatch.delenv("NH_PUBLIC_HOSTS")
    r = public_client.post(f"{BASE}/runs/{FINISHED}/stop", headers={"Origin": f"https://{SITE}"})
    assert (r.status_code, r.json()) == (403, DENIED)


def test_공개_주소는_요청이_http_로_들어와도_https_Origin_만_받는다(reg):
    """터널이 전달 머리글(X-Forwarded-Proto)을 붙이는지 확인할 수 없으므로 요청 scheme 과 상관없이 판정한다."""
    c = TestClient(app, base_url=f"http://{SITE}")         # scheme http, 전달 머리글 없음
    ok = c.post(f"{BASE}/strategies/reload", headers={"Origin": f"https://{SITE}"})
    assert ok.status_code != 403, ok.text
    assert c.post(f"{BASE}/strategies/reload", headers={"Origin": f"https://{SITE}:443"}).status_code != 403
    for origin in (f"http://{SITE}", f"http://{SITE}:443", f"https://{SITE}:8443", f"https://{SITE}:80"):
        assert c.post(f"{BASE}/strategies/reload", headers={"Origin": origin}).status_code == 403, origin
    # Host 가 다른 포트를 말하면 공개 주소로 보지 않는다
    r = c.post(f"{BASE}/strategies/reload", headers={"Origin": f"https://{SITE}:8000", "Host": f"{SITE}:8000"})
    assert r.status_code == 403


def test_공개_주소_Origin_이어도_cross_site_는_403(public_client, untouched):
    r = public_client.post(f"{BASE}/runs/{FINISHED}/stop",
                           headers={"Origin": f"https://{SITE}", "Sec-Fetch-Site": "cross-site"})
    assert (r.status_code, r.json()) == (403, DENIED)


def test_프록시_머리글이_있어도_Host_로_견준다(reg):
    """uvicorn `--proxy-headers` 는 scheme·클라이언트 주소만 바꾸고 Host 는 건드리지 않는다. 같은 걸 시험에서 감싸 확인."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    proxied = TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))
    base = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9", "Host": SITE}
    ok = proxied.post(f"{BASE}/strategies/reload", headers={**base, "Origin": f"https://{SITE}"})
    assert ok.status_code != 403, ok.text
    # http Origin 은 공개 주소(https)와 다르다
    assert proxied.post(f"{BASE}/strategies/reload", headers={**base, "Origin": f"http://{SITE}"}).status_code == 403
    # 전달된 호스트 머리글(X-Forwarded-Host)로는 속일 수 없다 — 쓰지 않는다
    bad = proxied.post(f"{BASE}/strategies/reload",
                       headers={**base, "Origin": "https://evil.com", "X-Forwarded-Host": "evil.com"})
    assert (bad.status_code, bad.json()) == (403, DENIED)
    # 리바인딩 Host 는 프록시 머리글이 있어도 400
    rebind = proxied.post(f"{BASE}/strategies/reload", headers={**base, "Host": REBIND, "Origin": f"http://{REBIND}"})
    assert rebind.status_code == 400


def test_NH_PUBLIC_HOSTS_의_와일드카드는_버리고_경고한다(monkeypatch, caplog):
    from backend.team_hosts import allowed_host_patterns, public_hosts
    monkeypatch.setenv("NH_PUBLIC_HOSTS", "*,nh.example.com,*.evil.com")
    with caplog.at_level("WARNING", logger="backend.team_hosts"):
        assert public_hosts() == {"nh.example.com"}
    assert "*" not in allowed_host_patterns()
    assert "'*'" in caplog.text and "'*.evil.com'" in caplog.text


def test_NH_PUBLIC_HOSTS_읽기():
    from backend.team_hosts import allowed_host_patterns, public_hosts
    import os
    old = os.environ.get("NH_PUBLIC_HOSTS")
    try:
        os.environ["NH_PUBLIC_HOSTS"] = " NH.example.com , https://b.example.com:8443/x,,"
        assert public_hosts() == {"nh.example.com", "b.example.com"}
        assert allowed_host_patterns() == ["127.0.0.1", "b.example.com", "localhost", "nh.example.com"]
        os.environ["NH_PUBLIC_HOSTS"] = ""
        assert allowed_host_patterns() == ["127.0.0.1", "localhost"]
    finally:
        if old is None:
            os.environ.pop("NH_PUBLIC_HOSTS", None)
        else:
            os.environ["NH_PUBLIC_HOSTS"] = old


def test_조회는_Origin_을_가리지_않는다(client):
    assert client.get(f"{BASE}/runs", headers={"Origin": "https://evil.example"}).status_code == 200


def test_시작은_JSON_Content_Type_만_받는다(client, untouched):
    body = '{"file": "fake.py", "mode": "paper", "sym": null}'
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        r = client.post(f"{BASE}/runs", content=body, headers={"Content-Type": ctype})
        assert r.status_code == 415, ctype
    assert client.post(f"{BASE}/runs", content=body).status_code == 415             # 헤더 없음도 JSON 이 아니다


# ---------------------------------------------------------------- 시험은 사용자 홈의 실행 폴더를 건드리지 않는다
def _outside_home(path):
    from pathlib import Path
    return not Path(path).resolve().is_relative_to(Path.home().resolve())


def test_앱_수명을_돌려도_파이썬_전략_레지스트리는_사용자_홈_밖이다(monkeypatch):
    """`main.lifespan` 은 `pyrun_startup()` → `registry()` → `recover()` 를 부른다. 시험에서 그 레지스트리가
    `~/NHFutures/state/pyruns`·`~/NHFutures/strategies` 를 가리키면 사용자의 실행 폴더를 「끝·재시작」으로 고쳐 쓴다."""
    r = registry_mod.registry()                 # 먼저 본다 — 홈을 가리키면 수명을 돌리기 전에 멈춘다
    assert _outside_home(r.root) and _outside_home(r.strategies), (r.root, r.strategies)

    class _펌프:
        def __init__(self, service):
            pass

        async def start(self):
            return None

        async def stop(self):
            return None

    async def _아무것도():
        return None

    monkeypatch.setattr(app_main.strategy_pump, "RunPump", _펌프)
    for name in ("_prepare_master", "_prepare_sessions", "_keep_fresh"):
        monkeypatch.setattr(app_main, name, _아무것도)
    monkeypatch.setattr(nh_client, "call_observer", None)

    async def 띄워보기():
        async with app_main.lifespan(app_main.app):
            await asyncio.sleep(0)

    asyncio.run(띄워보기())
    r = registry_mod.registry()
    assert _outside_home(r.root) and _outside_home(r.strategies), (r.root, r.strategies)
    with pytest.raises(AssertionError, match="NH"):
        r._api.open_interest()                  # 시험 레지스트리의 api 는 부르면 실패한다


# ---------------------------------------------------------------- 전략 파일 올리기·지우기
GOOD_SRC = "# 올린 파일\nX = 1\n"


def _upload(client, file="up.py", content=GOOD_SRC, **extra):
    return client.post(f"{BASE}/strategies", json={"file": file, "content": content, **extra})


def test_올리면_201_과_목록_모양으로_돌려준다(client, reg):
    r = _upload(client)
    assert r.status_code == 201
    body = r.json()
    assert body["folder"] == str(reg.strategies)
    files = [s["file"] for s in body["strategies"]]
    assert files == sorted(files) and "up.py" not in files        # STRATEGY 없는 공용 코드는 strategies 가 아니라 modules 에 선다
    assert body["modules"] == ["up.py"]
    assert (reg.strategies / "up.py").read_text(encoding="utf-8") == GOOD_SRC
    # 전략 파일이면 목록에 나온다
    from tests.test_team_pyrun_live import STRATEGY_SRC
    r = _upload(client, "mine.py", STRATEGY_SRC.replace('NAME = "fake"', 'NAME = "mine"'))
    assert r.status_code == 201 and "mine.py" in [s["file"] for s in r.json()["strategies"]]


def test_올릴_때_컴파일도_실행도_하지_않는다(client, reg):
    """고장 난 코드도 그대로 저장되고(목록에 오류로 보인다), 올리는 중에는 아무것도 실행되지 않는다."""
    marker = reg.strategies.parent / "ran.txt"
    src = f"open({str(marker)!r}, 'w').write('x')\nSTRATEGY = (\n"
    r = _upload(client, "broken.py", src)
    assert r.status_code == 201
    assert (reg.strategies / "broken.py").read_text(encoding="utf-8") == src
    broken = next(s for s in r.json()["strategies"] if s["file"] == "broken.py")
    assert broken["error"] and not marker.exists()          # 목록 읽기에서도 컴파일 오류로 끝난다


@pytest.mark.parametrize("name", ["../x.py", "a/b.py", "sub\\x.py", "a b.py", "전략.py", "x.txt", "x.py.txt", ".py", "x.PY2",
                                  "", "x.py\n", "..", "/etc/passwd.py"])
def test_이상한_파일_이름은_400(client, reg, name):
    before = sorted(p.name for p in reg.strategies.iterdir())
    r = _upload(client, name)
    assert r.status_code == 400 and isinstance(r.json()["detail"], str) and r.json()["detail"]
    assert sorted(p.name for p in reg.strategies.iterdir()) == before
    assert not (reg.strategies.parent / "x.py").exists()


def test_이름이_문자열이_아니면_400(client, reg):
    r = client.post(f"{BASE}/strategies", json={"file": 3, "content": GOOD_SRC})
    assert r.status_code == 400 and "이름" in r.json()["detail"]


def test_내용은_문자열이어야_하고_크기_한도가_있다(client, reg):
    from backend.team_pyrun.strategy_files import MAX_STRATEGY_BYTES
    assert MAX_STRATEGY_BYTES == 256 * 1024
    for bad in (None, 5, ["x"], {"a": 1}):
        r = client.post(f"{BASE}/strategies", json={"file": "up.py", "content": bad})
        assert r.status_code == 400, bad
    assert not (reg.strategies / "up.py").exists()
    ok = "a" * MAX_STRATEGY_BYTES
    assert _upload(client, "edge.py", ok).status_code == 201
    r = _upload(client, "big.py", ok + "a")
    assert r.status_code == 400 and "256" in r.json()["detail"] and not (reg.strategies / "big.py").exists()
    # 글자 수가 아니라 UTF-8 로 인코딩한 바이트 수로 잰다
    r = _upload(client, "han.py", "가" * (MAX_STRATEGY_BYTES // 3 + 1))
    assert r.status_code == 400 and not (reg.strategies / "han.py").exists()
    assert _upload(client, "han.py", "가" * (MAX_STRATEGY_BYTES // 3)).status_code == 201


def test_UTF8_로_인코딩할_수_없는_내용은_400(client, reg):
    r = client.post(f"{BASE}/strategies", content='{"file": "lone.py", "content": "\\ud800"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and not (reg.strategies / "lone.py").exists()


def test_같은_이름이_있으면_409_이고_덮어쓰기를_밝혀야_바뀐다(client, reg):
    assert _upload(client, "same.py", "A = 1\n").status_code == 201
    r = _upload(client, "same.py", "A = 2\n")
    assert (r.status_code, r.json()) == (409, {"detail": "같은 이름의 파일이 있습니다: same.py"})
    assert (reg.strategies / "same.py").read_text(encoding="utf-8") == "A = 1\n"
    # true 가 아닌 값(문자열 "true" 등)은 덮어쓰기가 아니다
    for flag in (False, None, "true", 1):
        assert _upload(client, "same.py", "A = 3\n", overwrite=flag).status_code == 409, flag
    r = _upload(client, "same.py", "A = 2\n", overwrite=True)
    assert r.status_code == 201
    assert (reg.strategies / "same.py").read_text(encoding="utf-8") == "A = 2\n"
    # 있던 시험 전략도 같은 길(덮어쓰기 확인)을 지난다
    assert _upload(client, "fake.py").status_code == 409


def test_줄바꿈은_받은_그대로_바이트로_쓴다(client, reg):
    src = "A = 1\r\nB = '가'\r\n"
    assert _upload(client, "crlf.py", src).status_code == 201
    assert (reg.strategies / "crlf.py").read_bytes() == src.encode("utf-8")


def test_쓰다_실패해도_옛_파일은_그대로이고_임시_파일이_남지_않는다(client, reg, monkeypatch):
    import os
    assert _upload(client, "keep.py", "A = 1\n").status_code == 201
    before = sorted(p.name for p in reg.strategies.iterdir())

    def boom(src, dst):
        raise OSError("디스크가 가득 찼습니다")
    monkeypatch.setattr(os, "replace", boom)
    r = _upload(client, "keep.py", "A = 2\n", overwrite=True)
    assert r.status_code == 500 and "keep.py" in r.json()["detail"]
    assert (reg.strategies / "keep.py").read_text(encoding="utf-8") == "A = 1\n"
    assert sorted(p.name for p in reg.strategies.iterdir()) == before


def test_올린_파일은_본문이_JSON_일_때만_받는다(client, reg):
    body = '{"file": "up.py", "content": "X = 1\\n"}'
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        r = client.post(f"{BASE}/strategies", content=body, headers={"Content-Type": ctype})
        assert r.status_code == 415, ctype
    assert not (reg.strategies / "up.py").exists()


def test_올릴_때_본문이_모자라면_422(client):
    assert client.post(f"{BASE}/strategies", json={"file": "up.py"}).status_code == 422


def test_지우면_200_과_목록_모양으로_돌려준다(client, reg):
    assert _upload(client, "gone.py").status_code == 201
    r = client.delete(f"{BASE}/strategies/gone.py")
    assert r.status_code == 200
    assert r.json()["folder"] == str(reg.strategies)
    assert "gone.py" not in [s["file"] for s in r.json()["strategies"]]
    assert not (reg.strategies / "gone.py").exists()
    assert "fake.py" in [s["file"] for s in r.json()["strategies"]]        # 다른 파일은 그대로


def test_없는_파일_지우기는_404_이상한_이름은_400(client, reg):
    r = client.delete(f"{BASE}/strategies/nope.py")
    assert r.status_code == 404 and "nope.py" in r.json()["detail"]
    (reg.strategies / "dir.py").mkdir()                       # 폴더는 파일이 아니다
    assert client.delete(f"{BASE}/strategies/dir.py").status_code == 404 and (reg.strategies / "dir.py").is_dir()
    outside = reg.strategies.parent / "outside.py"
    outside.write_text("X = 1\n", encoding="utf-8")
    for name in ("x.txt", "a b.py", "전략.py", "..%2Foutside.py", "%2e%2e%2foutside.py", "x.py%0A"):
        r = client.delete(f"{BASE}/strategies/{name}")
        assert r.status_code in (400, 404, 405), name   # %2F·.. 는 경로로 풀려 라우트에 안 닿으면 404·405
        assert r.status_code == 400 or "%2" in name
    assert outside.exists()
    assert client.delete(f"{BASE}/strategies/..").status_code in (400, 404, 405)
    assert outside.exists()


def test_심볼릭_링크는_링크만_지우고_가리키는_파일은_남긴다(client, reg):
    target = reg.strategies.parent / "target.py"
    target.write_text("X = 1\n", encoding="utf-8")
    (reg.strategies / "link.py").symlink_to(target)
    assert client.delete(f"{BASE}/strategies/link.py").status_code == 200
    assert not (reg.strategies / "link.py").is_symlink() and target.exists()


def test_올리고_지워도_도는_실행은_처음_불러온_코드_그대로다(client, reg):
    """로더가 파일마다 따로 불러오므로, 실행 중에 파일을 덮어쓰거나 지워도 돌던 실행의 sha256 은 그대로다."""
    import hashlib
    from tests.test_team_pyrun_live import STRATEGY_SRC
    original = (reg.strategies / "fake.py").read_bytes()
    first = hashlib.sha256(original).hexdigest()
    run = reg.start(RunSpec("fake.py", "paper", None))
    live = reg.get(run["id"])
    assert live.loaded.sha256 == first and live.status()["state"] in ("대기", "진행 중")
    edited = STRATEGY_SRC.replace('TITLE = "시험 전략"', 'TITLE = "고친 전략"')
    assert edited != STRATEGY_SRC
    assert _upload(client, "fake.py", edited, overwrite=True).status_code == 201
    assert hashlib.sha256((reg.strategies / "fake.py").read_bytes()).hexdigest() != first
    assert live.loaded.sha256 == first and live.loaded.title == "시험 전략"
    on_disk = json.loads((reg.root / run["id"] / "run.json").read_text(encoding="utf-8"))
    assert on_disk["sha256"] == first
    assert client.get(f"{BASE}/runs/{run['id']}").json()["state"] in ("대기", "진행 중")
    assert client.delete(f"{BASE}/strategies/fake.py").status_code == 200
    assert live.loaded.sha256 == first and live.status()["state"] in ("대기", "진행 중")
    # 새로 세우려는 실행은 지운 파일을 못 찾는다
    assert client.post(f"{BASE}/runs", json={"file": "fake.py", "mode": "paper", "sym": None}).status_code == 409


def test_다른_사이트가_보낸_올리기·지우기는_파일을_건드리지_못한다(client, reg):
    for origin in ("https://evil.example", "null"):
        r = client.post(f"{BASE}/strategies", json={"file": "evil.py", "content": "X = 1\n"}, headers={"Origin": origin})
        assert (r.status_code, r.json()) == (403, DENIED)
        r = client.delete(f"{BASE}/strategies/fake.py", headers={"Origin": origin})
        assert (r.status_code, r.json()) == (403, DENIED)
    assert not (reg.strategies / "evil.py").exists() and (reg.strategies / "fake.py").exists()


def test_STRATEGY_없는_공용_모듈은_modules_에_서고_지울_수_있다(client, reg):
    """`helper.py`(STRATEGY 없음)는 `strategies` 에는 안 나오고 `modules` 에 이름만 선다. 지우면 사라진다.
    깨진 파일은 modules 가 아니라 strategies 의 오류 행이다."""
    before = client.get(f"{BASE}/strategies").json()
    assert before["modules"] == []
    r = _upload(client, "helper.py", "def f():\n    return 1\n")
    assert r.status_code == 201 and r.json()["modules"] == ["helper.py"]
    assert "helper.py" not in [s["file"] for s in r.json()["strategies"]]
    _upload(client, "a_util.py", "Y = 2\n")
    _upload(client, "broken.py", "raise RuntimeError('깨짐')\n")
    got = client.get(f"{BASE}/strategies").json()
    assert got["modules"] == ["a_util.py", "helper.py"]                        # 이름순, 깨진 파일은 없다
    assert any(s["file"] == "broken.py" and s["error"] for s in got["strategies"])
    assert [s["file"] for s in got["strategies"]] == sorted([s["file"] for s in before["strategies"]] + ["broken.py"])
    r = client.delete(f"{BASE}/strategies/helper.py")
    assert r.status_code == 200 and r.json()["modules"] == ["a_util.py"]
    assert not (reg.strategies / "helper.py").exists()
    assert client.get(f"{BASE}/strategies").json()["modules"] == ["a_util.py"]
    assert client.post(f"{BASE}/strategies/reload").json()["modules"] == ["a_util.py"]


def test_목록을_읽을_때_파일은_한_번만_불러온다(client, reg, monkeypatch):
    """전략·모듈을 나누느라 같은 파일을 두 번 실행하지 않는다."""
    from backend.team_pyrun import loader
    calls = []
    real = loader._exec_module
    monkeypatch.setattr(loader, "_exec_module", lambda folder, file: (calls.append(file), real(folder, file))[1])
    _upload(client, "helper.py", "Z = 1\n")
    calls.clear()
    client.get(f"{BASE}/strategies")
    assert sorted(calls) == sorted(set(calls)) and "helper.py" in calls


def test_대소문자만_다른_이름도_있는_파일로_보고_디스크의_그_파일을_덮어쓴다(client, reg):
    """대소문자를 가리지 않는 파일 시스템(맥 APFS)에서 `Case.py` 와 `case.py` 가 갈라지지 않게 —
    어느 파일 시스템에서든 대소문자를 무시하고 비교한다. 409 는 디스크에 있는 이름을 알려 준다."""
    assert _upload(client, "Case.py", "A = 1\n").status_code == 201
    r = _upload(client, "case.py", "A = 2\n")
    assert (r.status_code, r.json()) == (409, {"detail": "같은 이름의 파일이 있습니다: Case.py"})
    assert (reg.strategies / "Case.py").read_text(encoding="utf-8") == "A = 1\n"
    r = _upload(client, "CASE.py", "A = 3\n", overwrite=True)
    assert r.status_code == 201
    names = sorted(p.name for p in reg.strategies.glob("*.py") if p.name.lower() == "case.py")
    assert names == ["Case.py"]                                  # 새 이름으로 갈라지지 않는다
    assert (reg.strategies / "Case.py").read_text(encoding="utf-8") == "A = 3\n"
    assert r.json()["modules"].count("Case.py") == 1 and "CASE.py" not in r.json()["modules"]
    # 정확히 같은 이름이 있으면 그것을 쓴다(대소문자 구분 파일 시스템에서 둘이 따로 있는 경우)
    from backend.team_pyrun import strategy_files
    assert strategy_files._existing(reg.strategies, "Case.py") == "Case.py"
    assert strategy_files._existing(reg.strategies, "nothing.py") is None


HELPER_V1 = "def double(v):\n    return v * 2\n"
HELPER_V2 = "def double(v):\n    return v * 3\n"


def _uses_helper_src():
    from tests.test_team_pyrun_live import STRATEGY_SRC
    src = STRATEGY_SRC.replace('NAME = "fake"', 'NAME = "uses"').replace(
        "from dataclasses import dataclass\n", "from dataclasses import dataclass\nfrom helper import double\n", 1)
    src = src.replace("        self.seen.append((m.date, m.time))", "        self.seen.append((m.date, m.time, double(m.close)))")
    assert "from helper import double" in src and "double(m.close)" in src
    return src


def test_올리고_지워도_공용_모듈을_불러온_실행은_계속_돈다(client, reg):
    """전략이 맨 위에서 `from helper import double` 한다. 실행을 세운 뒤 helper.py 를 덮어쓰고 지워도
    그 실행은 처음 불러온 helper 로 다음 분봉을 처리하고 오류 없이 이어진다(새 실행은 바뀐 파일을 쓴다)."""
    from tests.test_team_pyrun_live import at, bar
    assert _upload(client, "helper.py", HELPER_V1).status_code == 201
    assert _upload(client, "uses.py", _uses_helper_src()).status_code == 201
    run = reg.start(RunSpec("uses.py", "paper", None))
    live = reg.get(run["id"])
    reg.fake.chart = [bar("090000", 1335.0)]
    live.step(at("090104"))
    assert live.runner.strat.seen == [("20261103", "090000", 2670.0)] and live.state == "진행 중"

    assert _upload(client, "helper.py", HELPER_V2, overwrite=True).status_code == 201
    reg.fake.chart = [bar("090000", 1335.0), bar("090100", 1336.0)]
    live.step(at("090204"))
    assert live.state == "진행 중" and live.ended_reason is None
    assert live.runner.strat.seen[-1] == ("20261103", "090100", 2672.0)          # 처음 불러온 v1 (v2 라면 4008.0)

    assert client.delete(f"{BASE}/strategies/helper.py").status_code == 200
    reg.fake.chart = [bar("090000", 1335.0), bar("090100", 1336.0), bar("090200", 1337.0)]
    live.step(at("090304"))
    assert live.state == "진행 중" and live.ended_reason is None
    assert live.runner.strat.seen[-1] == ("20261103", "090200", 2674.0)
    assert client.get(f"{BASE}/runs/{run['id']}").json()["state"] == "진행 중"
    # helper 가 없어진 뒤 새로 세우는 실행은 불러오지 못해 거부된다
    refused = client.post(f"{BASE}/runs", json={"file": "uses.py", "mode": "paper", "sym": None})
    assert refused.status_code == 409


# ---------------------------------------------------------------- 작성 규칙 문서
def test_작성_규칙_문서를_돌려준다(client):
    from pathlib import Path

    doc = Path(__file__).resolve().parents[1] / "docs" / "team" / "strategy-file-convention.md"
    r = client.get(f"{BASE}/convention")
    assert r.status_code == 200
    assert r.json() == {"markdown": doc.read_text(encoding="utf-8")}


def test_작성_규칙_문서가_없으면_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(routes_mod, "CONVENTION_DOC", tmp_path / "nope.md")
    r = client.get(f"{BASE}/convention")
    assert r.status_code == 404


def test_작성_규칙_문서_경로는_패키지_기준_저장소_안이다():
    from pathlib import Path

    root = Path(routes_mod.__file__).resolve().parents[2]
    assert routes_mod.CONVENTION_DOC == root / "docs" / "team" / "strategy-file-convention.md"


def test_익절_목표가_없는_전략은_목록에_알림이_선다(client, reg):
    src = (FIXTURES / "no_target.py").read_text(encoding="utf-8")
    (reg.strategies / "no_target.py").write_text(src, encoding="utf-8")
    row = next(s for s in client.get(f"{BASE}/strategies").json()["strategies"] if s["file"] == "no_target.py")
    assert row["error"] is None and row["notes"] == ["target·current_vwap 이 없어 익절 없이 돕니다"]
