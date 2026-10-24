"""API 목록이 명세와 맞는지."""
import os
import re
from pathlib import Path

import pytest

from backend.nh_api import catalog
from backend.nh_api.catalog import (
    COMMON,
    DOMESTIC,
    LIMIT_PER_SECOND,
    OVERSEAS,
    Limit,
    http_spec,
    is_known,
    stream_spec,
)

# 명세 문서는 저장소에 포함되지 않습니다. 가지고 있는 자리에서만 대조하고,
# 다른 곳에 두었다면 NH_API_DOCS 로 알려 줍니다.
DOCS = Path(os.environ.get("NH_API_DOCS") or Path(__file__).resolve().parents[1] / "rest_api_docs")

LIMIT_BY_LABEL = {
    "시세 LIMIT (10/초)": Limit.QUOTE,
    "계좌 LIMIT (10/초)": Limit.ACCOUNT,
    "주문 LIMIT (5/초)": Limit.ORDER,
    "API 디폴트 (3/초)": Limit.AUTH,
}


def test_시장별_개수():
    markets = [spec.market for spec in catalog.HTTP_APIS.values()]
    assert markets.count(DOMESTIC) == 22
    assert markets.count(OVERSEAS) == 16
    assert markets.count(COMMON) == 3
    assert len(catalog.STREAM_APIS) == 8


def test_경로는_거래나_인증_아래에_있다():
    for spec in catalog.HTTP_APIS.values():
        if spec.market == COMMON:
            assert spec.path.startswith(("/auth-service/", "/permission/"))
        else:
            assert spec.path.startswith(f"/trade/v1/{spec.market}/")
        assert spec.method in ("GET", "POST")


def test_경로가_겹치지_않는다():
    routes = [(spec.method, spec.path) for spec in catalog.HTTP_APIS.values()]
    assert len(routes) == len(set(routes))


def test_등급마다_초당_건수가_있다():
    for spec in catalog.HTTP_APIS.values():
        assert LIMIT_PER_SECOND[spec.limit] > 0


def test_국내_주문체결은_보내는_값이_이름과_다르다():
    # 이름은 O1_K 이지만 구독 메시지에는 O1 을 넣습니다.
    assert stream_spec("O1_K").action_code == "O1"
    assert stream_spec("KA").action_code == "KA"


def test_모르는_이름은_거부한다():
    with pytest.raises(ValueError):
        http_spec("없는_api")
    with pytest.raises(ValueError):
        stream_spec("없는_api")
    assert is_known("domestic_price")
    assert is_known("KA")
    assert not is_known("lme_order")


def _doc_rows():
    for path in sorted(DOCS.rglob("*.md")):
        if path.parent.name == "lme" or path.stem.endswith("_LME") or path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")

        def cell(label):
            found = re.search(rf"^\|\s*{label}\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
            return found.group(1).strip().strip("`") if found else ""

        yield path.stem, cell("API 통신 방식"), cell("HTTP Method"), cell("URL"), cell("API 요청 제한")


@pytest.mark.skipif(not DOCS.is_dir(), reason="명세 문서가 이 자리에 없습니다.")
def test_명세와_대조():
    documented = {}
    for api_id, transport, method, url, limit in _doc_rows():
        if transport != "HTTP":
            continue
        documented[api_id] = (method, url, LIMIT_BY_LABEL[limit])

    assert set(documented) == set(catalog.HTTP_APIS)
    for api_id, (method, url, limit) in documented.items():
        spec = catalog.HTTP_APIS[api_id]
        assert (spec.method, spec.path, spec.limit) == (method, url, limit), api_id


@pytest.mark.skipif(not DOCS.is_dir(), reason="명세 문서가 이 자리에 없습니다.")
def test_실시간_명세와_대조():
    documented = {
        api_id for api_id, transport, *_ in _doc_rows() if transport == "WEBSOCKET"
    }
    assert documented == set(catalog.STREAM_APIS)
