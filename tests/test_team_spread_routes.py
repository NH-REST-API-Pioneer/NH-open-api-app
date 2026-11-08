"""스프레드 라우트(`/api/team/spread`) 시험 — 가짜 시세·api 의 임시 `SpreadRegistry` 로 돈다(`~/NHFutures` 는 건드리지 않는다)."""
import asyncio
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main as app_main
from backend.main import app
from backend.team_pyrun.journal import Journal
from backend.team_spread import registry as reg_mod
from backend.team_spread import routes as routes_mod
from tests.test_team_spread_registry import PAIR, make, write_prev

BASE = "/api/team/spread"


@pytest.fixture
def reg(tmp_path, monkeypatch):
    r, api = make(tmp_path)
    monkeypatch.setattr(reg_mod, "_registry", r)
    r.fake = api
    return r


@pytest.fixture
def client(reg):
    return TestClient(app)


def start(client, **kw):
    return client.post(f"{BASE}/runs", json={"file": "s.py", "mode": "paper", **kw})


# ---------------------------------------------------------------- 실행기 파일
def test_목록과_다시_읽기(client, reg):
    r = client.get(f"{BASE}/runners")
    assert r.status_code == 200 and r.json()["folder"] == str(reg.folder_of_runners)
    assert [x["file"] for x in r.json()["runners"]] == ["s.py"]
    assert client.post(f"{BASE}/runners/reload").json() == r.json()


def test_올리기와_지우기(client, reg):
    r = client.post(f"{BASE}/runners", json={"file": "t.py", "content": PAIR})
    assert r.status_code == 201 and {x["file"] for x in r.json()["runners"]} == {"s.py", "t.py"}
    assert client.post(f"{BASE}/runners", json={"file": "t.py", "content": PAIR}).status_code == 409
    assert client.post(f"{BASE}/runners", json={"file": "t.py", "content": PAIR, "overwrite": True}).status_code == 201
    assert client.post(f"{BASE}/runners", json={"file": "../x.py", "content": PAIR}).status_code == 400
    assert client.delete(f"{BASE}/runners/t.py").status_code == 200
    assert client.delete(f"{BASE}/runners/t.py").status_code == 404
    assert client.post(f"{BASE}/runners", content=b"{}", headers={"content-type": "text/plain"}).status_code == 415


def test_작성_규칙은_문서가_없으면_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(routes_mod, "CONVENTION_DOC", tmp_path / "nope.md")
    assert client.get(f"{BASE}/convention").status_code == 404
    doc = tmp_path / "c.md"
    doc.write_text("# 규칙", encoding="utf-8")
    monkeypatch.setattr(routes_mod, "CONVENTION_DOC", doc)
    assert client.get(f"{BASE}/convention").json() == {"markdown": "# 규칙"}


# ---------------------------------------------------------------- 실행
def test_시작_목록_조회(client, reg):
    r = start(client)
    assert r.status_code == 201
    run_id = r.json()["id"]
    assert [x["id"] for x in client.get(f"{BASE}/runs").json()["runs"]] == [run_id]
    got = client.get(f"{BASE}/runs/{run_id}")
    assert got.status_code == 200 and got.json()["id"] == run_id and got.json()["mode"] == "paper"


def test_시작_거부는_409_와_문장(client):
    r = start(client, mode="replay")
    assert r.status_code == 409 and "방식" in r.json()["detail"]
    assert start(client, file="nope.py").status_code == 409


def test_모르는_칸은_422(client):
    assert start(client, symbol="HO").status_code == 422
    assert client.post(f"{BASE}/runs/x/inherit", json={"file": "s.py", "expect": {}, "zz": 1}).status_code == 422


def test_json_이_아니면_415(client):
    assert client.post(f"{BASE}/runs", content=b"{}", headers={"content-type": "text/plain"}).status_code == 415


def test_다른_사이트_쓰기는_403(client):
    body = {"file": "s.py", "mode": "paper"}
    assert client.post(f"{BASE}/runs", json=body, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post(f"{BASE}/runs", json=body, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post(f"{BASE}/runs/x/stop", headers={"origin": "null"}).status_code == 403
    assert client.get(f"{BASE}/runs", headers={"sec-fetch-site": "cross-site"}).status_code == 200


@pytest.mark.parametrize("path", ["", "/journal", "/api-log", "/bars", "/download", "/inherit"])
def test_모르는_실행은_404(client, path):
    assert client.get(f"{BASE}/runs/nope{path}").status_code == 404
    assert client.get(f"{BASE}/runs/..%2Fx{path}").status_code == 404


def test_모르는_실행_중지_404_이전_실행은_409(client, reg):
    assert client.post(f"{BASE}/runs/nope/stop").status_code == 404
    write_prev(reg, "20261108_S_orders")
    assert client.post(f"{BASE}/runs/20261108_S_orders/stop").status_code == 409


def test_중지는_204(client, reg):
    run_id = start(client).json()["id"]
    assert client.post(f"{BASE}/runs/{run_id}/stop").status_code == 204
    assert reg.get(run_id).state == "끝"


def test_끝난_이전_실행은_run_json_으로_조회(client, reg):
    write_prev(reg, "20261108_S_orders")
    got = client.get(f"{BASE}/runs/20261108_S_orders")
    assert got.status_code == 200 and got.json()["id"] == "20261108_S_orders"


def test_일지_이어_읽기(client, reg):
    run_id = start(client).json()["id"]
    first = client.get(f"{BASE}/runs/{run_id}/journal").json()
    assert first["rows"] and first["next"] == len(first["rows"])
    Journal(reg.folder(run_id) / "journal.jsonl").write("event", text="추가")
    more = client.get(f"{BASE}/runs/{run_id}/journal", params={"after": first["next"]}).json()
    assert [r["text"] for r in more["rows"]] == ["추가"]
    assert client.get(f"{BASE}/runs/{run_id}/journal", params={"after": -1}).status_code == 422
    assert client.get(f"{BASE}/runs/{run_id}/api-log").json() == {"rows": [], "next": 0}


def test_차트용_점은_체결과_log_에서(client, reg):
    folder = write_prev(reg, "20261108_S_orders")
    j = Journal(folder / "journal.jsonl")
    j.write("fill", clock="10:00:01", leg="ho", sym="HOZ26", qty=1, price=2.5, fee=0.1)
    j.write("fill", clock="10:00:02", leg="rb", sym="RBZ26", qty=-1, price=None, fee=0.1)
    j.write("log", name="gap", value=1.5)
    j.write("log", name="skip", value="x")
    body = client.get(f"{BASE}/runs/20261108_S_orders/bars").json()
    assert set(body) == {"legs", "logs", "fills"}
    assert [p["close"] for p in body["legs"]["ho"]] == [2.5] and "rb" not in body["legs"]
    assert [p["value"] for p in body["logs"]["gap"]] == [1.5] and "skip" not in body["logs"]
    assert len(body["fills"]) == 2 and body["fills"][0]["leg"] == "ho"


def test_내려받기는_세_파일만(client, reg):
    run_id = start(client).json()["id"]
    r = client.get(f"{BASE}/runs/{run_id}/download")
    assert r.status_code == 200 and f"{run_id}_partial.zip" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == [f"{run_id}/journal.jsonl"] and not any("run.json" in n for n in names)
    client.post(f"{BASE}/runs/{run_id}/stop")
    r = client.get(f"{BASE}/runs/{run_id}/download")
    assert f'filename="{run_id}.zip"' in r.headers["content-disposition"]
    assert "run.json" not in " ".join(zipfile.ZipFile(io.BytesIO(r.content)).namelist())


# ---------------------------------------------------------------- 이어받기
def test_이어받기_미리_보기와_시작(client, reg):
    write_prev(reg, "20261108_S_orders", inheritable=False)
    r = client.get(f"{BASE}/runs/20261108_S_orders/inherit")
    assert r.status_code == 409 and r.json()["detail"]
    r = client.post(f"{BASE}/runs/20261108_S_orders/inherit", json={"file": "s.py", "expect": {"ho": 1, "rb": -1}})
    assert r.status_code == 409 and r.json()["detail"]
    assert client.post(f"{BASE}/runs/20261108_S_orders/inherit", json={"file": "s.py"}).status_code == 422


def test_이어받기_성공(client, reg, monkeypatch):
    write_prev(reg, "20261108_S_orders")
    seen = {}

    def fake_start(spec, expect=None):
        seen.update(spec=spec, expect=expect)
        return {"id": "new"}

    monkeypatch.setattr(reg, "start", fake_start)
    monkeypatch.setattr(reg, "inherit_preview", lambda rid: {"id": rid})
    assert client.get(f"{BASE}/runs/20261108_S_orders/inherit").json() == {"id": "20261108_S_orders"}
    r = client.post(f"{BASE}/runs/20261108_S_orders/inherit", json={"file": "s.py", "expect": {"ho": 1}})
    assert r.status_code == 201 and r.json() == {"id": "new"}
    assert seen["spec"].inherit_from == "20261108_S_orders" and seen["spec"].mode == "orders" and seen["expect"] == {"ho": 1}


# ---------------------------------------------------------------- 동기 / 앱 연결
def test_시작_라우트는_동기_def(client):
    import inspect
    assert not inspect.iscoroutinefunction(routes_mod.start_run) and not inspect.iscoroutinefunction(routes_mod.inherit_run)


def test_라우터와_수명_연결이_main_에_있다():
    assert f"{BASE}/runs" in app.openapi()["paths"]
    assert app_main.spread_startup is routes_mod.spread_startup and app_main.spread_shutdown is routes_mod.spread_shutdown


def test_앱_수명에서_복구와_전체_중지가_불린다(reg, monkeypatch):
    calls = []
    monkeypatch.setattr(reg, "recover", lambda: calls.append("recover") or [])
    monkeypatch.setattr(reg, "close_starts", lambda: calls.append("close_starts"))
    monkeypatch.setattr(reg, "stop_all", lambda timeout=20.0: calls.append("stop_all") or [])

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

    async def 돌리기():
        async with app_main.lifespan(app_main.app):
            for _ in range(20):
                await asyncio.sleep(0.01)
                if "recover" in calls:
                    break

    asyncio.run(돌리기())
    assert calls == ["recover", "close_starts", "stop_all"]


def test_복구_중지가_실패해도_앱은_뜨고_꺼진다(reg, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("터짐")

    monkeypatch.setattr(reg, "recover", boom)
    monkeypatch.setattr(reg, "stop_all", boom)
    asyncio.run(routes_mod.spread_startup())
    asyncio.run(routes_mod.spread_shutdown())
    assert "스프레드 실행 복구에 실패" in caplog.text and "스프레드 실행 중지에 실패" in caplog.text
