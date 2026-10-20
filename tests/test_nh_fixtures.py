"""저장해 둔 응답이 온전한지.

`scripts/import_nh_fixtures.py` 의 결과를 검사합니다. 개수는 같이 반입되는
`index.json` 과 맞는지로 보고, 처음 반입한 만큼은 있는지도 함께 봅니다.
"""
import json
from pathlib import Path

import pytest

from backend.nh_api import catalog
from backend.nh_api.fixtures import (
    FIXTURE_ROOT,
    INDEX_NAME,
    FixtureStore,
    HttpFixture,
    StreamFixture,
)
from scripts.import_nh_fixtures import LIVE_ENVIRONMENT, MASKED, PERSON_FIELDS

# 처음 반입한 개수. 자료가 늘면 이 값보다 많아집니다.
FIRST_IMPORT_HTTP = 137
FIRST_IMPORT_STREAM = 14

# 수집 기록에는 있지만 반입하지 않는 항목입니다. 열람용 응답과 계좌 별칭이
# 여기 들어갑니다.
NOT_IMPORTED = (
    "fixture_seed",
    "response_headers",
    "account_alias",
    "identity_namespace",
    "collection_session",
    "expected_frontend",
    "source_workbook_sha256",
    "redaction",
    "request_edited",
)


@pytest.fixture(scope="module")
def store():
    return FixtureStore.load()


@pytest.fixture(scope="module")
def index():
    return json.loads((FIXTURE_ROOT / INDEX_NAME).read_text(encoding="utf-8"))


def _files():
    return [p for p in sorted(FIXTURE_ROOT.rglob("*.json")) if p.name != INDEX_NAME]


def test_개수가_출처_목록과_같다(store, index):
    assert len(store) == index["record_count"]
    assert len(_files()) == index["record_count"]
    assert len(store.http) >= FIRST_IMPORT_HTTP
    assert len(store.streams) >= FIRST_IMPORT_STREAM


def test_출처_목록의_파일이_모두_있다(index):
    for record in index["records"]:
        path = FIXTURE_ROOT / record["file"]
        assert path.is_file(), record["file"]
        assert record["collected_at"]
        assert record["record_id"]


def test_파일이름과_폴더가_내용과_같다():
    for path in _files():
        raw = json.loads(path.read_text(encoding="utf-8"))
        api_id, environment, market = path.parts[-4:-1]
        assert raw["api_id"] == api_id
        assert raw["environment"] == environment
        assert raw["market"] == market
        assert raw["record_id"] == path.stem


def test_반입하지_않는_항목이_없다():
    for path in _files():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for field in NOT_IMPORTED:
            assert field not in raw, f"{path.name} 에 {field} 가 들어 있다"


def test_사람을_가리키는_항목에_원래_값이_없다():
    """작업사원, 주문ID, 계좌명은 가린 문구이거나 비어 있어야 한다."""
    seen = 0

    def walk(value):
        nonlocal seen
        if isinstance(value, dict):
            for key, item in value.items():
                if key in PERSON_FIELDS and isinstance(item, str):
                    assert item in ("", MASKED), f"{key}={item!r}"
                    seen += 1
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for path in _files():
        walk(json.loads(path.read_text(encoding="utf-8")))

    # 검사가 실제로 걸리는 자리가 있는지 확인한다. 0 이면 통과해도 의미가 없다.
    assert seen > 0


def test_실전_계좌_응답은_반입하지_않는다(store):
    """실전 환경에서 받은 예수금·잔고·손익·주문 내역은 저장소에 두지 않는다.

    식별자는 바뀌어 있지만 금액은 실제 값 그대로다.
    """
    남은것 = [
        f
        for f in store.all
        if f.environment == LIVE_ENVIRONMENT and catalog.is_account_api(f.api_id)
    ]
    assert 남은것 == [], [f"{f.api_id}/{f.record_id}" for f in 남은것]


def test_모의_계좌_응답과_실전_시세는_남아_있다(store):
    """빼는 규칙이 필요한 자료까지 지우지는 않았는지 본다."""
    모의계좌 = [f for f in store.all if f.environment == "paper" and catalog.is_account_api(f.api_id)]
    실전시세 = [
        f
        for f in store.all
        if f.environment == LIVE_ENVIRONMENT and not catalog.is_account_api(f.api_id)
    ]
    assert 모의계좌, "모의 환경의 계좌 응답이 있어야 한다"
    assert 실전시세, "실전 환경의 시장 정보가 있어야 한다"


def test_HTTP_기록은_명세의_경로를_쓴다(store):
    for fixture in store.http:
        spec = catalog.http_spec(fixture.api_id)
        assert (fixture.method, fixture.path) == (spec.method, spec.path)
        assert spec.market in (fixture.market, catalog.COMMON)
        assert 100 <= fixture.http_status < 600


def test_실시간_기록은_순서대로다(store):
    for fixture in store.streams:
        assert fixture.api_id in catalog.STREAM_APIS
        sequences = [e.seq for e in fixture.events]
        assert sequences == sorted(sequences)
        offsets = [e.offset_ms for e in fixture.received]
        assert offsets == sorted(offsets)
        assert {e.direction for e in fixture.events} <= {"sent", "received"}


def test_찾기(store):
    현재가 = store.find_http(
        method="POST", path="/trade/v1/domestic/price", environment="real"
    )
    assert 현재가
    assert all(isinstance(f, HttpFixture) for f in 현재가)
    # 수집한 순서대로 나온다.
    assert [f.collected_at for f in 현재가] == sorted(f.collected_at for f in 현재가)

    체결 = store.find_stream("KA", environment="real")
    assert 체결
    assert all(isinstance(f, StreamFixture) for f in 체결)


# ── 저장소에 안 올리는 자리 ──────────────────────────────────


def _사본(tmp_path, api_id="domestic_deposit"):
    """임시 폴더에 기록 하나를 놓습니다. 누구 컴퓨터에서나 같게 돕니다."""
    import json

    from backend.nh_api.fixtures import FIXTURE_FORMAT

    자리 = tmp_path / api_id / "real" / "domestic"
    자리.mkdir(parents=True)
    (자리 / "onlyhere.json").write_text(
        json.dumps(
            {
                "format": FIXTURE_FORMAT,
                "transport": "HTTP",
                "api_id": api_id,
                "environment": "real",
                "market": "domestic",
                "record_id": "onlyhere",
                "collected_at": "2026-09-09T00:00:00+00:00",
                "scenario_id": f"{api_id}__base",
                "test_group": "",
                "status": "response_received",
                "method": "POST",
                "path": f"/trade/v1/domestic/{api_id.split('_', 1)[1]}",
                "http_status": 200,
                "request": {"biz_dt": "20260909"},
                "response": {"dps_csh_amt": "1"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_그_폴더가_있으면_함께_읽는다(tmp_path):
    from backend.nh_api.fixtures import FIXTURE_ROOT, FixtureStore

    안읽음 = FixtureStore.load(FIXTURE_ROOT)
    읽음 = FixtureStore.load(FIXTURE_ROOT, _사본(tmp_path))

    assert len(읽음) == len(안읽음) + 1
    assert any(f.record_id == "onlyhere" for f in 읽음.all)


def test_그_폴더가_없으면_조용히_넘어간다(tmp_path):
    from backend.nh_api.fixtures import FIXTURE_ROOT, FixtureStore

    없는자리 = tmp_path / "아무것도없음"
    assert len(FixtureStore.load(FIXTURE_ROOT, 없는자리)) == len(
        FixtureStore.load(FIXTURE_ROOT)
    )


def test_읽을지_말지는_환경변수가_정한다():
    from backend.nh_api.fixtures import PRIVATE_DIR_FLAG, PRIVATE_ROOT, private_root

    # 안 정하면 기본 자리를 봅니다.
    assert private_root({}) == PRIVATE_ROOT
    # 비워 두면 아예 안 읽습니다. 시험이 이 상태로 돕니다.
    assert private_root({PRIVATE_DIR_FLAG: ""}) is None
    assert private_root({PRIVATE_DIR_FLAG: "  "}) is None
    # 자리를 주면 그곳을 봅니다.
    assert private_root({PRIVATE_DIR_FLAG: "D:/어딘가"}) == Path("D:/어딘가")


def test_시험은_그_폴더를_안_읽는_상태로_돈다():
    """`conftest.py` 가 꺼 둡니다 — 사람마다 결과가 달라지면 안 됩니다."""
    import os

    from backend.nh_api.fixtures import PRIVATE_DIR_FLAG, private_root

    assert os.environ.get(PRIVATE_DIR_FLAG) == ""
    assert private_root() is None
