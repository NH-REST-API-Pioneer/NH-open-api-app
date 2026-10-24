"""`/api/master` 라우트.

`TestClient(app)` 을 `with` 없이 씁니다. `with` 로 감싸면 서버 기동 절차가 돌면서
마스터를 실제로 내려받으러 나갑니다 — 테스트가 바깥으로 나가면 안 됩니다.
"""
import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from backend.main import app
from backend.master.master_files import MASTER_FILES_BY_NAME
from backend.master.master_routes import (
    _NO_MASTER,
    REPLAY_NO_REFRESH,
    get_service,
    replaying,
)
from backend.master.master_service import MasterService
from backend.master.master_store import save_master
from tests.fixtures.master import fixture_text

_MASTERS = ("fut_opt", "stk_fut_opt", "idx_fut_opt", "cme_fut", "cme_opt",
            "etc_fut", "etc_opt", "opra_opt", "lme_fut")


@pytest.fixture
def client(tmp_path):
    """임시 폴더를 쓰는 마스터로 바꿔 끼웁니다. 사용자 홈은 건드리지 않습니다."""
    service = MasterService(tmp_path)
    app.dependency_overrides[get_service] = lambda: service
    # 실서버 모드로 둡니다 — 시험을 재생 모드로 돌려도 다시 받기 규칙이 안 바뀌게.
    app.dependency_overrides[replaying] = lambda: False
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(replaying, None)


def _fill(service):
    for name in _MASTERS:
        save_master(
            MASTER_FILES_BY_NAME[name],
            fixture_text(name).encode("utf-8"),
            stamp="20260902",
            base_dir=service.base_dir,
        )
    service.reload()


def test_정적_파일이_붙어_있어도_마스터_라우트에_닿는다(tmp_path):
    """배포 모드에서는 `/` 에 프론트엔드 정적 파일이 붙습니다.

    라우터를 그보다 **뒤에** 등록하면 `/` 가 모든 경로를 가져가 이 라우트가 가려지는데,
    개발 중에는 정적 파일 폴더가 없어서 그 실수가 드러나지 않습니다. 그래서 여기서
    배포 모드와 같은 모양을 만들어 확인합니다.
    """
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app.mount("/", StaticFiles(directory=tmp_path, html=True), name="정적파일-확인용")
    try:
        response = TestClient(app).get("/api/master/status")
    finally:
        app.router.routes[:] = [
            route
            for route in app.router.routes
            if getattr(route, "name", None) != "정적파일-확인용"
        ]

    assert response.status_code == 200


def test_마스터가_없어도_상태는_정상으로_답한다(client):
    """「없다」도 화면이 알아야 하는 상태입니다. 오류로 만들면 확인할 방법이 없습니다."""
    http, _ = client

    response = http.get("/api/master/status")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert len(body["files"]) == 9
    assert set(body["failed"]) == set(_MASTERS)


def test_마스터가_없으면_색인은_503이다(client):
    """「없다」와 「찾았는데 0건」을 가르기 위해 빈 목록이 아니라 오류로 답합니다."""
    http, _ = client

    response = http.get("/api/master/index")

    assert response.status_code == 503
    # **글자가 아니라 갈래를 봅니다** — 이 문장은 화면에 그대로 서는 고객용
    # 말이라 다듬을 수 있습니다.
    assert response.json()["detail"] == _NO_MASTER


def test_색인을_돌려준다(client):
    http, service = client
    _fill(service)

    body = http.get("/api/master/index").json()

    assert body["products"]
    assert body["contracts"]
    assert body["domestic_option_index"]["fields"] == [
        "series", "product_code", "expiry_date", "opt_tp"
    ]
    assert body["folding_conflicts"] == []
    # 값 칸 폭을 잡을 후보 행이 색인에 함께 옵니다.
    assert body["width_candidates"]["groups"]
    # 시세는 마스터에 없고 이 API 에도 없습니다.
    assert all("last" not in c and "prev_close" not in c for c in body["contracts"])


def test_상태가_값_칸_폭_자체검사를_알려_준다(client):
    """어긋난 것이 있으면 화면이 그 무리의 폭을 믿지 않을 수 있어야 합니다."""
    http, service = client
    _fill(service)

    검사 = http.get("/api/master/status").json()["width_checks"]

    assert 검사["mismatched"] == []
    assert 검사["without_candidate"] == []
    assert 검사["unreadable_values"] == 0


def test_마스터가_없으면_자체검사도_비어_있다(client):
    http, _ = client
    assert http.get("/api/master/status").json()["width_checks"] == {}


def test_상태가_어느_날짜_파일을_쓰는지_알려_준다(client):
    http, service = client
    _fill(service)

    body = http.get("/api/master/status").json()

    assert body["available"] is True
    assert body["dates"] == ["20260902"]
    assert body["failed"] == []

    files = {f["name"]: f for f in body["files"]}
    assert files["fut_opt"]["rows"] == 8
    # 받기만 하는 파일은 행 수가 없습니다. 실패가 아닙니다.
    assert files["lme_fut"]["parsed"] is False
    assert files["lme_fut"]["rows"] is None
    assert files["lme_fut"]["ok"] is True


def test_체인은_품목과_만기월로_받아_간다(client):
    http, service = client
    _fill(service)

    response = http.get(
        "/api/master/products/O_CL/contracts",
        params={"market": "overseas", "expiry": "202701"},
    )

    rows = response.json()
    assert response.status_code == 200
    assert [row["code"] for row in rows] == ["O_CLF27-C10.00"]
    assert rows[0]["code_cp"] == "C"


def test_국내_체인도_행사가를_한_번씩만_돌려준다(client):
    """국내 옵션은 주간·야간 두 줄로 옵니다. 라우트까지 접힌 채로 나가야 합니다."""
    http, service = client
    _fill(service)

    response = http.get(
        "/api/master/products/KOSPI/contracts",
        params={"market": "domestic", "expiry": "202609"},
    )

    rows = response.json()
    assert response.status_code == 200
    assert [row["series"] for row in rows] == ["B0169335"]
    assert all("cme_tp" not in row and "mrkt_tp" not in row for row in rows)


def test_모르는_시장은_거절한다(client):
    http, service = client
    _fill(service)

    response = http.get(
        "/api/master/products/O_CL/contracts",
        params={"market": "lme", "expiry": "202701"},
    )

    assert response.status_code == 400


def test_받는_중이면_다시_받기를_받지_않는다(client):
    """연달아 누르면 같은 파일을 두 번 받고, 저장 중인 파일을 다른 쪽이 덮어씁니다."""
    http, service = client
    service._stage = "downloading"

    response = http.post("/api/master/refresh")

    assert response.status_code == 409
    assert response.json()["started"] is False


def test_저장해_둔_응답으로_돌_때는_다시_받지_않는다(client, monkeypatch):
    """서버에 닿지 않는 곳에서 띄우는 방식이라 받으러 나가면 안 됩니다."""
    http, service = client
    monkeypatch.setattr(service, "refresh", lambda **_: pytest.fail("받으러 나가면 안 됩니다"))
    app.dependency_overrides[replaying] = lambda: True
    response = http.post("/api/master/refresh")

    assert response.status_code == 409
    assert response.json()["detail"] == REPLAY_NO_REFRESH


def test_테스트는_사용자_홈을_건드리지_않는다(client, tmp_path):
    http, service = client

    assert service.base_dir == tmp_path
    assert http.get("/api/master/status").json()["master_dir"] == str(tmp_path)


def test_마스터_라우트는_넷이고_전부_api_아래에_있다():
    """`/` 는 프론트엔드 정적 파일이 차지하므로 라우트는 `/api` 아래에만 둡니다.

    검색은 화면이 색인 위에서 하므로 라우트를 두지 않습니다. 쓰는 곳 없는 라우트는
    만들지 않습니다.
    """
    paths = set(app.openapi()["paths"])

    assert {p for p in paths if p.startswith("/api/master")} == {
        "/api/master/status",
        "/api/master/index",
        "/api/master/products/{code}/contracts",
        "/api/master/refresh",
    }
    assert not [p for p in paths if p.startswith("/api/master") is False and "master" in p]
