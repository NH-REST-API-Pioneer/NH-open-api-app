"""`/api/ui` 라우트.

`TestClient(app)` 을 `with` 없이 씁니다. `with` 로 감싸면 서버 기동 절차가 돌면서
마스터를 실제로 내려받으러 나갑니다 — 테스트가 바깥으로 나가면 안 됩니다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.ui.ui_routes import get_store
from backend.ui.ui_routes import NOT_STORED
from backend.ui.ui_store import KEY, SIZE, UiStore, WRITE


@pytest.fixture
def client(tmp_path):
    """임시 폴더를 쓰는 자리로 바꿔 끼웁니다. 사용자 홈은 건드리지 않습니다."""
    store = UiStore(tmp_path / "state" / "ui.json")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app), store
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_처음에는_비어_있다고_답한다(client):
    api, _ = client
    응답 = api.get("/api/ui")
    assert 응답.status_code == 200
    # `otherApp` 은 다른 앱(실서버·재생)이 쓴 파일을 만났을 때만 이름이 섭니다.
    assert 응답.json() == {"version": 1, "stored": False, "status": "missing", "values": {}, "otherApp": None}


def test_보낸_항목만_담는다(client):
    api, _ = client
    api.patch("/api/ui", json={"values": {"nh.home.watch": ["A7569000"]}})
    응답 = api.patch("/api/ui", json={"values": {"nh.trade.split": {"count": 2}}})

    assert 응답.status_code == 200
    assert 응답.json()["values"] == {
        "nh.home.watch": ["A7569000"],
        "nh.trade.split": {"count": 2},
    }
    assert api.get("/api/ui").json()["stored"] is True


def test_담지_않는_항목은_400(client):
    api, store = client
    응답 = api.patch("/api/ui", json={"values": {"nh.theme": "dark"}})
    assert 응답.status_code == 400
    assert not store.path.is_file()


def test_못_담은_까닭에_갈래가_함께_온다(client):
    """**화면은 갈래로 가릅니다.** 문장 글자로 가르면 문장을 다듬는 순간 화면의
    갈림이 소리 없이 어긋나, 크기를 넘은 것이 그냥 「못 남겼다」로 떨어집니다.
    """
    api, _ = client

    담지않는것 = api.patch("/api/ui", json={"values": {"nh.theme": "dark"}}).json()
    큰것 = api.patch(
        "/api/ui", json={"values": {"nh.home.watch": ["x" * 300_000]}}
    ).json()

    assert 담지않는것["detail"]["code"] == KEY
    assert 큰것["detail"]["code"] == SIZE
    # **문장은 갈래마다 다르지 않습니다** — 어느 갈래든 사용자가 할 일이 같습니다.
    # 항목 이름 같은 속사정은 기록에만 남습니다.
    for 하나 in (담지않는것, 큰것):
        assert 하나["detail"]["message"] == NOT_STORED
    assert "nh.theme" not in 담지않는것["detail"]["message"]


def test_형식이_틀리면_422(client):
    api, _ = client
    assert api.patch("/api/ui", json={"values": "목록이 아님"}).status_code == 422
    assert api.patch("/api/ui", json={}).status_code == 422


def test_쓰지_못하면_500_이고_경로를_알리지_않는다(client, monkeypatch):
    api, store = client

    def 실패(*args, **kwargs):
        raise OSError(f"{store.path} 에 쓸 수 없습니다")

    monkeypatch.setattr("backend.ui.ui_store.write_json", 실패)
    응답 = api.patch("/api/ui", json={"values": {"nh.home.watch": []}})

    assert 응답.status_code == 500
    # 경로에 사용자 이름이 들어 있으므로 원본 문구를 그대로 내보내지 않는다.
    assert str(store.path) not in 응답.text
    # **보낸 값 탓이 아닌 갈래입니다** — 값이 잘못됐다고 말하면 사용자가 방금
    # 바꾼 화면 자리를 되돌리러 갑니다.
    assert 응답.json()["detail"]["code"] == WRITE


def test_못_읽어도_정상으로_답한다(client):
    """파일이 깨졌다고 화면이 안 뜨면 되돌릴 방법이 없다."""
    api, store = client
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{망가짐", encoding="utf-8")

    응답 = api.get("/api/ui")
    assert 응답.status_code == 200
    assert 응답.json()["status"] == "broken"
    assert 응답.json()["stored"] is False


def test_이관은_비어_있는_항목만_채운다(client):
    api, _ = client
    처음 = api.post("/api/ui/import", json={"values": {"nh.home.watch": ["A7569000"]}})
    assert 처음.status_code == 200
    assert 처음.json()["imported"] == ["nh.home.watch"]

    api.patch("/api/ui", json={"values": {"nh.home.watch": ["그 뒤에 고친 값"]}})
    다시 = api.post("/api/ui/import", json={"values": {"nh.home.watch": ["A7569000"]}})

    assert 다시.status_code == 200
    assert 다시.json()["imported"] == []
    assert api.get("/api/ui").json()["values"]["nh.home.watch"] == ["그 뒤에 고친 값"]


def test_이관은_부르는_순서를_타지_않는다(client):
    """화면이 무엇을 먼저 저장했든 관심종목은 옮겨져야 한다."""
    api, _ = client
    api.patch("/api/ui", json={"values": {"nh.trade.split": {"count": 2}}})

    응답 = api.post("/api/ui/import", json={"values": {"nh.home.watch": ["A7569000"]}})

    assert 응답.json()["imported"] == ["nh.home.watch"]
    assert api.get("/api/ui").json()["values"]["nh.home.watch"] == ["A7569000"]


def test_화면_상태_주소에는_시장_칸이_없다():
    """`/api/{시장}/…` 은 NH선물에 그대로 묻는 거래 API 의 규칙이다.

    화면 상태는 NH선물에 없는 앱의 파일이라 국내·해외로 나뉘지 않는다.
    규칙에 맞춘다며 `/api/domestic/ui` 같은 자리로 옮기면 안 된다.
    """
    경로들 = set(app.openapi()["paths"])

    assert "/api/ui" in 경로들
    assert not any(path.endswith("/ui") and path != "/api/ui" for path in 경로들)


# ── 재생과 실서버가 가르는 파일 ─────────────────────────────


def test_GET_PATCH_import_가_같은_파일을_본다(client):
    api, store = client
    api.patch("/api/ui", json={"values": {"nh.trade.split": {"count": 2}}})
    api.post("/api/ui/import", json={"values": {"nh.home.watch": ["A7569000"]}})

    읽음 = api.get("/api/ui").json()

    assert 읽음["values"] == {"nh.trade.split": {"count": 2}, "nh.home.watch": ["A7569000"]}
    assert store.path.is_file()

