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
def test_최대_보유_정수는_모든_다리에_펼쳐진다(client, reg):
    r = start(client, max_qty=3, orders_per_min=7)
    assert r.status_code == 201, r.text
    legs = [x["name"] for x in r.json()["legs"]]
    assert legs and reg.get(r.json()["id"]).max_qty == {n: 3 for n in legs}


def test_최대_보유_dict_는_다리별로(client, reg):
    name = next(iter(client.get(f"{BASE}/runners").json()["runners"][0]["legs"]))
    r = start(client, max_qty={name: 2})
    assert r.status_code == 201, r.text
    assert reg.get(r.json()["id"]).max_qty[name] == 2


def test_최대_보유_모르는_다리와_나쁜_값은_409(client):
    assert "실행기에 없는 다리" in start(client, max_qty={"nope": 2}).json()["detail"]
    name = next(iter(client.get(f"{BASE}/runners").json()["runners"][0]["legs"]))
    assert start(client, max_qty={name: 0}).status_code == 409
    assert start(client, max_qty=-1).status_code == 409
    assert start(client, max_qty={name: True}).status_code == 422
    assert start(client, max_qty=True).status_code == 422


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


def test_차트용_점은_분봉_줄에서_체결과_log_는_따로(client, reg):
    folder = write_prev(reg, "20261108_S_orders")
    j = Journal(folder / "journal.jsonl")
    j.write("minute", date="20261109", time="101500", legs={"ho": {"close": 1.5, "filled": False}, "rb": {"close": 3, "filled": True}})
    j.write("minute", date="20261109", time="101600", legs={"ho": {"close": 1.6, "filled": False}})
    j.write("fill", clock="10:00:01", leg="ho", sym="HOZ26", qty=1, price=2.5, fee=0.1)
    j.write("log", name="gap", value=1.5)
    j.write("log", name="skip", value="x")
    body = client.get(f"{BASE}/runs/20261108_S_orders/bars").json()
    assert set(body) == {"legs", "logs", "fills"}
    assert [p["close"] for p in body["legs"]["ho"]] == [1.5, 1.6] and [p["close"] for p in body["legs"]["rb"]] == [3]
    assert body["legs"]["ho"][0]["at"] == "2026-11-09T10:15:00"
    assert [p["value"] for p in body["logs"]["gap"]] == [1.5] and "skip" not in body["logs"]
    assert len(body["fills"]) == 1 and body["fills"][0]["price"] == 2.5


def test_끝난_실행은_요약을_합친다(client, reg):
    folder = write_prev(reg, "20261108_S_orders")
    assert client.get(f"{BASE}/runs/20261108_S_orders").json()["summary"] is None
    (folder / "summary.json").write_text(json.dumps({"total": {"USD": {"fills": 4}}, "halted": "멈춤"}), encoding="utf-8")
    got = client.get(f"{BASE}/runs/20261108_S_orders").json()
    assert got["summary"]["total"] == {"USD": {"fills": 4}} and got["halted"] == "멈춤"
    run_id = start(client).json()["id"]
    client.post(f"{BASE}/runs/{run_id}/stop")
    assert "summary" in client.get(f"{BASE}/runs/{run_id}").json()


def test_기본_시험_레지스트리는_홈과_실제_시세를_못_쓴다():
    from backend.team_spread import registry as m
    fresh = m.registry()
    assert fresh._active_env() == "paper"
    assert fresh._master() == ([], [])
    assert fresh._feed_factory.__name__ != "_live_feed"


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
    monkeypatch.setattr(reg, "request_stop_all", lambda: calls.append("request_stop_all"), raising=False)
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
    assert calls == ["recover", "request_stop_all", "close_starts", "stop_all"]


def test_복구_중지가_실패해도_앱은_뜨고_꺼진다(reg, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("터짐")

    monkeypatch.setattr(reg, "recover", boom)
    monkeypatch.setattr(reg, "stop_all", boom)
    asyncio.run(routes_mod.spread_startup())
    asyncio.run(routes_mod.spread_shutdown())
    assert "스프레드 실행 복구에 실패" in caplog.text and "스프레드 실행 중지에 실패" in caplog.text


# ---------------------------------------------------------------- 마지막 검토 고침 (final-findings)
def _lifespan(monkeypatch):
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
            await asyncio.sleep(0.02)

    asyncio.run(돌리기())


def test_F10_앱_종료는_두_탭_모두에게_먼저_중지를_알린_뒤에_기다린다(reg, monkeypatch):
    from backend.team_pyrun import registry as py_mod
    py = py_mod.registry()
    calls = []
    for tag, r in (("spread", reg), ("pyrun", py)):
        monkeypatch.setattr(r, "request_stop_all", lambda tag=tag: calls.append(f"{tag}.request_stop_all"), raising=False)
        monkeypatch.setattr(r, "stop_all", lambda timeout=20.0, tag=tag: calls.append(f"{tag}.stop_all") or [])
    _lifespan(monkeypatch)
    asks = [i for i, c in enumerate(calls) if c.endswith("request_stop_all")]
    joins = [i for i, c in enumerate(calls) if c.endswith(".stop_all")]
    assert len(asks) == 2 and len(joins) == 2, calls
    assert max(asks) < min(joins), calls          # 어느 쪽도 기다리기 전에 두 탭 모두 중지를 받는다


def test_F10_두_탭의_기다림은_한_마감_시각을_나눠_쓴다(reg, monkeypatch):
    from backend.team_pyrun import registry as py_mod
    py = py_mod.registry()
    got = {}
    for tag, r in (("spread", reg), ("pyrun", py)):
        monkeypatch.setattr(r, "stop_all", lambda timeout=20.0, tag=tag: got.update({tag: timeout}) or [])
    monkeypatch.setattr(routes_mod, "SHUTDOWN_SECONDS", 5.0, raising=False)
    _lifespan(monkeypatch)
    assert set(got) == {"spread", "pyrun"} and all(0 < t <= 5.0 for t in got.values()), got   # 둘 다 같은 마감(기본 20초 따로가 아님)


def _orders_run_with_holding(reg):
    """도는 모의 계좌 실행에 ho +1 을 들게 한 뒤 앱 종료로 끝낸다(메모리에 남은 끝난 실행)."""
    run = reg.get(reg.start(reg_mod.SpreadSpec("s.py", "orders"))["id"])
    run.ctx.order("ho", 1)
    run.request_stop(shutdown=True)
    run.finish("앱 종료")
    return run


def test_F2_메모리에_남은_끝난_실행도_이어받기와_남은_보유를_보인다(client, reg):
    run = _orders_run_with_holding(reg)
    got = client.get(f"{BASE}/runs/{run.run_id}").json()
    assert got["state"] == "끝" and got["inheritable"] is True and got["holding_left"] == {"ho": 1}
    row = next(r for r in client.get(f"{BASE}/runs").json()["runs"] if r["id"] == run.run_id)
    assert row["inheritable"] is True and row["holding_left"] == {"ho": 1} and row["handed_to"] is None


def test_F6_예전_일지의_NaN_무한대는_null_로_응답이_깨지지_않는다(client, reg):
    folder = write_prev(reg, "20261108_S_orders")
    j = Journal(folder / "journal.jsonl")
    j.write("log", name="z", value=float("nan"), beta=float("inf"))
    j.write("log", name="z", value=1.5)
    j.write("fill", leg="ho", qty=1, price=float("nan"))
    r = client.get(f"{BASE}/runs/20261108_S_orders/journal")
    assert r.status_code == 200 and r.json()["rows"][0]["value"] is None and r.json()["rows"][0]["beta"] is None
    b = client.get(f"{BASE}/runs/20261108_S_orders/bars")
    assert b.status_code == 200 and [p["value"] for p in b.json()["logs"]["z"]] == [1.5]
    assert b.json()["fills"][0]["price"] is None
    run_id = start(client).json()["id"]
    reg.get(run_id).j.write("log", name="z", value=float("nan"))       # ctx 를 거치지 않은 줄(예전 파일과 같은 꼴)
    assert client.get(f"{BASE}/runs").status_code == 200
    got = client.get(f"{BASE}/runs/{run_id}")
    assert got.status_code == 200 and got.json()["logs_tail"][-1]["value"] is None
    # 프레임워크의 직렬화(지금 FastAPI 는 NaN 을 null 로 바꿔 줌)에 기대지 않는다 — 라우트가 돌려주는 값 자체가 엄격한 JSON
    for body in (routes_mod.run_journal("20261108_S_orders", 0), routes_mod.run_bars("20261108_S_orders"),
                 routes_mod.get_run(run_id), routes_mod.list_runs()):
        json.dumps(body, allow_nan=False)


def test_F11_F13_차트_체결엔_price_known_log_점은_봉_시각_t(client, reg):
    folder = write_prev(reg, "20261108_S_orders")
    j = Journal(folder / "journal.jsonl")
    j.write("fill", clock="101500", leg="ho", sym="HOZ26", qty=-1, price=2.5, fee=0.1, price_known=False)
    j.write("log", name="z", value=1.5, t="2026-11-09T10:15:00")
    j.write("log", name="old", value=2.0)                              # t 가 없는 예전 줄은 기록 시각 그대로
    body = client.get(f"{BASE}/runs/20261108_S_orders/bars").json()
    assert body["fills"][0]["price_known"] is False and body["fills"][0]["qty"] == -1
    assert body["logs"]["z"][0]["at"] == "2026-11-09T10:15:00"
    assert body["logs"]["old"][0]["at"]
