"""재생 모드의 HTTP 응답."""
import json

import httpx
import pytest

from backend.nh_api.client import TradeClient
from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore
from backend.nh_api.replay import (
    EMPTY_BODY,
    MATCH_CROSS_ENVIRONMENT,
    MATCH_EMPTY,
    MATCH_EXACT,
    RECORD_HEADER,
    MATCH_HEADER,
    SYMBOL_NONE,
    ReplayMiss,
    ReplayTransport,
    replay_base_url,
    replay_client,
)
from backend.nh_api.session import create_session


def 기록(
    *,
    record_id,
    environment="real",
    market="domestic",
    api_id="domestic_price",
    path="/trade/v1/domestic/price",
    request,
    response,
    http_status=200,
    collected_at="2026-09-09T00:00:19+00:00",
):
    return {
        "format": FIXTURE_FORMAT,
        "transport": "HTTP",
        "api_id": api_id,
        "environment": environment,
        "market": market,
        "record_id": record_id,
        "collected_at": collected_at,
        "scenario_id": f"{api_id}__base",
        "test_group": "테스트",
        "status": "response_received",
        "method": "POST",
        "path": path,
        "http_status": http_status,
        "request": request,
        "response": response,
    }


@pytest.fixture
def store(tmp_path):
    자료 = [
        기록(
            record_id="first",
            request={"sym": "A7569000"},
            response={"last_pric": "1338.50"},
            collected_at="2026-09-09T00:00:01+00:00",
        ),
        기록(
            record_id="second",
            request={"sym": "B0169A34"},
            response={"last_pric": "2.55"},
            collected_at="2026-09-09T00:00:02+00:00",
        ),
        기록(
            record_id="error",
            api_id="domestic_price-all-option-night",
            path="/trade/v1/domestic/price-all-option-night",
            request={"prd": "09"},
            response={
                "errorTime": "2026-09-09 09:02:28",
                "errorMessage": "'09' 마켓 검색 실패",
                "errorStatus": 400,
                "errorPath": "/trade/v1/domestic/price-all-option-night",
            },
            http_status=400,
        ),
        기록(
            record_id="paper-one",
            environment="paper",
            api_id="domestic_deposit",
            path="/trade/v1/domestic/deposit",
            request={"biz_dt": "20260909"},
            response={"ord_psb_tot_amt": "100000000"},
        ),
    ]
    for 하나 in 자료:
        폴더 = tmp_path / 하나["api_id"] / 하나["environment"] / 하나["market"]
        폴더.mkdir(parents=True, exist_ok=True)
        (폴더 / f"{하나['record_id']}.json").write_text(
            json.dumps(하나, ensure_ascii=False), encoding="utf-8"
        )
    return FixtureStore.load(tmp_path)


def 부르기(store, path, payload, environment="real"):
    with replay_client(store) as client:
        return client.post(f"{replay_base_url(environment)}{path}", json=payload)


def test_같은_요청이면_그_응답이_온다(store):
    응답 = 부르기(store, "/trade/v1/domestic/price", {"sym": "B0169A34"})
    assert 응답.status_code == 200
    assert 응답.json() == {"last_pric": "2.55"}
    assert 응답.headers["x-nh-replay-match"] == MATCH_EXACT
    assert 응답.headers["x-nh-replay-record"] == "second"


def test_기록에_없는_종목은_빈_응답이다(store):
    """다른 종목의 기록으로 답하면 화면에 엉뚱한 종목의 값이 섭니다."""
    응답 = 부르기(store, "/trade/v1/domestic/price", {"sym": "없는종목"})
    assert 응답.status_code == 200
    assert 응답.headers["x-nh-replay-match"] == MATCH_EMPTY
    assert 응답.headers["x-nh-replay-symbol"] == SYMBOL_NONE
    assert "x-nh-replay-record" not in 응답.headers
    # 실제 0건 응답과 같은 모양 — 배열 칸이 없고 건수와 이어받기 키뿐입니다.
    assert 응답.json() == EMPTY_BODY


def test_그_환경에_기록이_없으면_다른_환경의_기록으로_답한다(store):
    응답 = 부르기(store, "/trade/v1/domestic/price", {"sym": "A7569000"}, environment="paper")
    assert 응답.status_code == 200
    assert 응답.headers["x-nh-replay-match"] == MATCH_CROSS_ENVIRONMENT
    assert 응답.headers["x-nh-replay-record"] == "first"


def test_다른_환경에서도_요청이_같은_기록을_먼저_찾는다(store):
    """이것이 없으면 종목을 바꿔도 늘 같은 응답이 온다.

    국내 시세처럼 한쪽 환경에서만 수집된 API 는, 그 환경으로 켜지 않으면
    요청과 상관없이 가장 이른 기록으로 떨어진다. 화면에서는 「값이 안 바뀐다」로
    보여서 화면 잘못으로 오인하기 쉽다.
    """
    응답 = 부르기(store, "/trade/v1/domestic/price", {"sym": "B0169A34"}, environment="paper")

    assert 응답.headers["x-nh-replay-match"] == MATCH_CROSS_ENVIRONMENT
    # 요청이 같은 기록을 골랐으므로 그 종목의 값이 온다.
    assert 응답.headers["x-nh-replay-record"] == "second"
    assert 응답.json() == {"last_pric": "2.55"}


def test_환경이_맞으면_그_환경의_기록을_쓴다(store):
    응답 = 부르기(store, "/trade/v1/domestic/deposit", {"biz_dt": "20260909"}, environment="paper")
    assert 응답.headers["x-nh-replay-match"] == MATCH_EXACT
    assert 응답.headers["x-nh-replay-record"] == "paper-one"


def test_오류_응답도_그대로_돌려준다(store):
    응답 = 부르기(store, "/trade/v1/domestic/price-all-option-night", {"prd": "09"})
    assert 응답.status_code == 400
    assert 응답.json()["errorMessage"] == "'09' 마켓 검색 실패"


def test_기록이_없는_경로는_답하지_않는다(store):
    with pytest.raises(ReplayMiss):
        부르기(store, "/trade/v1/domestic/order", {"sym": "A7569000"})


def test_실서버_주소로는_부를_수_없다(store):
    with replay_client(store) as client:
        with pytest.raises(ReplayMiss):
            client.post("https://api.futures.co.kr/trade/v1/domestic/price", json={"sym": "A7569000"})


def test_무엇으로_답했는지_남긴다(store):
    전송 = ReplayTransport(store)
    with httpx.Client(transport=전송) as client:
        client.post(f"{replay_base_url('real')}/trade/v1/domestic/price", json={"sym": "없는종목"})
    assert 전송.log == [
        {
            "method": "POST",
            "path": "/trade/v1/domestic/price",
            "match": MATCH_EMPTY,
            # 답한 기록이 없으니 종목 판정도 없습니다.
            "symbol": SYMBOL_NONE,
            "record_id": "",
        }
    ]


def test_빈_응답으로_답할_때_경고를_남긴다(store, caplog):
    with caplog.at_level("WARNING"):
        부르기(store, "/trade/v1/domestic/price", {"sym": "없는종목"})
    assert any("빈 응답" in record.getMessage() for record in caplog.records)


def test_반입해_둔_실제_기록으로도_답한다():
    """저장소에 저장해 둔 자료로 한 번 확인한다."""
    실제 = FixtureStore.load()
    응답 = 부르기(실제, "/trade/v1/domestic/price", {"sym": "A7569000"})
    assert 응답.status_code == 200
    assert 응답.headers["x-nh-replay-match"] == MATCH_EXACT
    assert 응답.json()["sym_exch"] == "A7569000"


def test_재생_모드에서_공통_호출부까지_이어진다():
    """토큰 발급부터 응답 판정까지 한 번에 돌려 본다. 밖으로 나가는 통신이 없다."""
    with create_session(replay=True) as session:
        client = TradeClient(session)
        결과 = client.call("domestic_price", {"sym": "A7569000"}, environment="real")

    assert 결과.body["sym_exch"] == "A7569000"
    assert 결과.headers["x-nh-replay-match"] == MATCH_EXACT
    assert 결과.environment == "real"


# ── 같은 요청이 여럿이면 줄이 담긴 기록을 먼저 ──────────────


def _잔고기록(record_id, 줄수, *, collected_at, status=200, environment="paper"):
    """요청이 같고 줄 수만 다른 기록. 잔고는 요청이 이어받기 키뿐입니다.

    기록 번호는 **ASCII 로 둡니다** — 응답 헤더가 ASCII 만 담을 수 있어
    한글로 두면 물음표로 바뀌어 무엇이 뽑혔는지 못 봅니다.
    """
    return {
        "format": FIXTURE_FORMAT,
        "transport": "HTTP",
        "api_id": "domestic_open-interest",
        "environment": environment,
        "market": "domestic",
        "record_id": record_id,
        "collected_at": collected_at,
        "scenario_id": "domestic_open-interest__base",
        "test_group": "",
        "status": "response_received",
        "method": "POST",
        "path": "/trade/v1/domestic/open-interest",
        "http_status": status,
        "request": {"nxt_key": ""},
        "response": {
            "nrec": f"{줄수:04d}",
            "Occurs1": [{"occurs1_sym": "A7569000"} for _ in range(줄수)],
        },
    }


def _창고(*records):
    from pathlib import Path

    from backend.nh_api.fixtures import FixtureStore, _build

    return FixtureStore([_build(r, Path("메모리")) for r in records], Path("메모리"))


def _부르기(store, environment="paper"):
    전송 = ReplayTransport(store)
    with httpx.Client(transport=전송) as client:
        답 = client.post(
            f"{replay_base_url(environment)}/trade/v1/domestic/open-interest",
            json={"nxt_key": ""},
        )
    return 답


def test_요청이_같으면_줄이_담긴_기록을_먼저_고른다():
    """빈 기록이 먼저 수집됐다는 이유로 화면이 빈 표를 보면 안 됩니다."""
    store = _창고(
        _잔고기록("empty", 0, collected_at="2026-09-09T01:00:00+00:00"),
        _잔고기록("withrows", 1, collected_at="2026-09-09T02:00:00+00:00"),
    )
    답 = _부르기(store)

    assert 답.headers[RECORD_HEADER] == "withrows"
    assert 답.headers[MATCH_HEADER] == MATCH_EXACT
    assert len(답.json()["Occurs1"]) == 1


def test_줄이_담긴_것이_없으면_가장_이른_기록():
    store = _창고(
        _잔고기록("first", 0, collected_at="2026-09-09T01:00:00+00:00"),
        _잔고기록("second", 0, collected_at="2026-09-09T02:00:00+00:00"),
    )
    assert _부르기(store).headers[RECORD_HEADER] == "first"


def test_다른_환경으로_넘어갈_때도_줄이_먼저다():
    store = _창고(
        _잔고기록("empty", 0, collected_at="2026-09-09T01:00:00+00:00", environment="real"),
        _잔고기록("withrows", 2, collected_at="2026-09-09T02:00:00+00:00", environment="real"),
    )
    답 = _부르기(store, environment="paper")

    assert 답.headers[MATCH_HEADER] == MATCH_CROSS_ENVIRONMENT
    assert 답.headers[RECORD_HEADER] == "withrows"


def test_오류_응답보다_정상_응답이_먼저다():
    """줄이 담겼어도 오류면 안 됩니다 — 정상 먼저, 그다음 줄."""
    store = _창고(
        _잔고기록("badrows", 3, collected_at="2026-09-09T01:00:00+00:00", status=400),
        _잔고기록("okempty", 0, collected_at="2026-09-09T02:00:00+00:00"),
    )
    # 요청이 같지 않게 만들어 대체 갈래로 보냅니다.
    전송 = ReplayTransport(store)
    with httpx.Client(transport=전송) as client:
        답 = client.post(
            f"{replay_base_url('paper')}/trade/v1/domestic/open-interest",
            json={"nxt_key": "다른값"},
        )

    assert 답.status_code == 200
    assert 답.headers[RECORD_HEADER] == "okempty"


def test_줄이_없는_API_는_순서가_그대로다():
    """예수금처럼 배열이 없는 응답은 이 잣대가 차이를 못 냅니다."""
    from backend.nh_api.replay import has_rows

    store = _창고(_잔고기록("one", 0, collected_at="2026-09-09T01:00:00+00:00"))
    (기록,) = store.http
    assert has_rows(기록) is False


def test_요청이_같아도_오류보다_정상이_먼저다():
    """고르는 차례는 세 경로가 같습니다 — 정상 > 줄 담김 > 이른 것."""
    store = _창고(
        _잔고기록("badrows2", 3, collected_at="2026-09-09T01:00:00+00:00", status=400),
        _잔고기록("okrows", 1, collected_at="2026-09-09T02:00:00+00:00"),
    )
    답 = _부르기(store)

    assert 답.status_code == 200
    assert 답.headers[MATCH_HEADER] == MATCH_EXACT
    assert 답.headers[RECORD_HEADER] == "okrows"
