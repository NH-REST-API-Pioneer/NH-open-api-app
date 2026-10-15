"""재생 모드의 실시간 메시지 공급."""
import asyncio
import json

import pytest

from backend.nh_api.fixtures import FIXTURE_FORMAT, FixtureStore
from backend.nh_api.replay import (
    MATCH_API,
    MATCH_CROSS_ENVIRONMENT,
    MATCH_EXACT,
    ReplayMiss,
    find_stream,
    stream_events,
)


def 기록(*, record_id, api_id="KA", action_sym="A7569000", events, environment="real", collected_at):
    request = {"header": {"action": "A"}, "body": {"action_code": api_id}}
    if action_sym is not None:
        request["body"]["action_sym"] = action_sym
    return {
        "format": FIXTURE_FORMAT,
        "transport": "WEBSOCKET",
        "api_id": api_id,
        "environment": environment,
        "market": "domestic",
        "record_id": record_id,
        "collected_at": collected_at,
        "scenario_id": f"{api_id}__base",
        "test_group": "테스트",
        "status": "stream_window_finished",
        "request": request,
        "events": events,
    }


보낸것 = {"seq": 1, "direction": "sent", "offset_ms": 45.4, "payload": {"body": {"action_code": "KA"}}}
확인 = {"seq": 2, "direction": "received", "offset_ms": 58.8, "payload": {"code": "INIT", "msg": "INIT_SUCCESS"}}
첫체결 = {"seq": 3, "direction": "received", "offset_ms": 2284.0, "payload": {"body": {"last_pric": "1335.9"}}}
둘체결 = {"seq": 4, "direction": "received", "offset_ms": 2292.7, "payload": {"body": {"last_pric": "1336.0"}}}


@pytest.fixture
def store(tmp_path):
    자료 = [
        기록(
            record_id="control-only",
            events=[보낸것, 확인],
            collected_at="2026-09-09T00:00:01+00:00",
        ),
        기록(
            record_id="usd-future",
            events=[보낸것, 확인, 첫체결, 둘체결],
            collected_at="2026-09-09T00:00:02+00:00",
        ),
        기록(
            record_id="option",
            action_sym="B0169A34",
            events=[보낸것, 확인, {**첫체결, "payload": {"body": {"last_pric": "2.55"}}}],
            collected_at="2026-09-09T00:00:03+00:00",
        ),
        기록(
            record_id="account",
            api_id="O1_K",
            action_sym=None,
            events=[보낸것, 확인, 첫체결],
            collected_at="2026-09-09T00:00:04+00:00",
        ),
    ]
    for 하나 in 자료:
        폴더 = tmp_path / 하나["api_id"] / 하나["environment"] / 하나["market"]
        폴더.mkdir(parents=True, exist_ok=True)
        (폴더 / f"{하나['record_id']}.json").write_text(
            json.dumps(하나, ensure_ascii=False), encoding="utf-8"
        )
    return FixtureStore.load(tmp_path)


def 받기(store, api_id="KA", **kwargs):
    async def 실행():
        return [메시지 async for 메시지 in stream_events(store, api_id, **kwargs)]

    return asyncio.run(실행())


def test_서버가_보낸_메시지만_순서대로_나온다(store):
    메시지들 = 받기(store, environment="real", action_sym="A7569000")
    assert 메시지들 == [확인["payload"], 첫체결["payload"], 둘체결["payload"]]


def test_구독_확인_같은_제어_메시지도_함께_나온다(store):
    # 걸러내는 것은 받는 쪽의 몫이다. 실제로 섞여 오기 때문이다.
    메시지들 = 받기(store, environment="real", action_sym="A7569000")
    assert 메시지들[0] == {"code": "INIT", "msg": "INIT_SUCCESS"}


def test_종목을_지정하면_그_종목_기록을_쓴다(store):
    골라진것 = find_stream(store, "KA", environment="real", action_sym="B0169A34")
    assert 골라진것.fixture.record_id == "option"
    assert 골라진것.match == MATCH_EXACT
    assert 골라진것.is_exact


def test_그_종목_기록이_어느_환경에도_없으면_답하지_않는다(store):
    """다른 종목의 기록을 돌려주면 화면이 남의 값을 그 종목으로 표시한다."""
    for 환경 in ("real", "paper"):
        with pytest.raises(ReplayMiss):
            find_stream(store, "KA", environment=환경, action_sym="C9999999")
        with pytest.raises(ReplayMiss):
            받기(store, environment=환경, action_sym="C9999999")


def test_다른_환경의_기록도_그_종목의_것만_쓴다(store):
    골라진것 = find_stream(store, "KA", environment="paper", action_sym="B0169A34")
    assert 골라진것.match == MATCH_CROSS_ENVIRONMENT
    assert 골라진것.fixture.record_id == "option"
    assert 골라진것.action_sym == "B0169A34"


def test_다른_환경_기록으로_내보낼_때_경고를_남긴다(store, caplog):
    with caplog.at_level("WARNING"):
        메시지들 = 받기(store, environment="paper", action_sym="A7569000")
    assert 메시지들
    남은것 = [r.getMessage() for r in caplog.records]
    assert any("real" in 문구 and "대신" in 문구 for 문구 in 남은것), 남은것


def test_막고_싶으면_다른_환경_기록도_거부할_수_있다(store):
    with pytest.raises(ReplayMiss):
        받기(store, environment="paper", action_sym="A7569000", strict=True)
    # 환경과 종목이 맞으면 막지 않는다.
    assert 받기(store, environment="real", action_sym="A7569000", strict=True)


def test_종목을_지정하지_않으면_대체로_본다(store):
    """어느 종목이 나올지 정해지지 않으므로 맞는 기록이라고 하지 않는다."""
    골라진것 = find_stream(store, "KA", environment="real")
    assert 골라진것.match == MATCH_API


def test_계좌_알림은_종목이_없어_대체가_아니다(store):
    골라진것 = find_stream(store, "O1_K", environment="real")
    assert 골라진것.match == MATCH_EXACT
    assert 골라진것.action_sym is None


def test_그_환경에_없으면_다른_환경의_기록을_쓴다(store):
    골라진것 = find_stream(store, "KA", environment="paper", action_sym="A7569000")
    assert 골라진것.match == MATCH_CROSS_ENVIRONMENT
    assert 골라진것.fixture.environment == "real"


def test_자료가_담긴_기록을_먼저_고른다(store):
    """제어 메시지만 오간 기록을 고르면 화면에 아무것도 뜨지 않는다."""
    골라진것 = find_stream(store, "KA", environment="real", action_sym="A7569000")
    assert 골라진것.fixture.record_id == "usd-future"


def test_기록을_지정할_수_있다(store):
    골라진것 = find_stream(store, "KA", environment="real", record_id="option")
    assert 골라진것.fixture.record_id == "option"
    assert 골라진것.match == MATCH_EXACT
    with pytest.raises(ReplayMiss):
        find_stream(store, "KA", environment="real", record_id="no-such-record")


def test_없는_실시간_API_는_답하지_않는다(store):
    with pytest.raises(ReplayMiss):
        받기(store, "FA", environment="real")


def test_간격을_두고_흘려보낼_수_있다(store, monkeypatch):
    잔것 = []

    async def 세기(초):
        잔것.append(초)

    monkeypatch.setattr(asyncio, "sleep", 세기)
    메시지들 = 받기(store, environment="real", action_sym="A7569000", speed=1)
    assert len(메시지들) == 3
    # 수집했을 때의 간격(초)을 그대로 둔다.
    assert 잔것 == pytest.approx([0.0588, 2.2252, 0.0087], abs=1e-3)


def test_반입해_둔_실제_기록으로도_나온다():
    실제 = FixtureStore.load()
    메시지들 = 받기(실제, "O1_K", environment="paper")
    assert 메시지들
    체결 = [m for m in 메시지들 if isinstance(m, dict) and "body" in m]
    assert 체결, "주문 체결 메시지가 있어야 한다"


def test_반입해_둔_실제_기록에서_종목이_갈린다():
    """검토에서 나온 자리. 옵션을 구독했는데 달러선물 기록이 나오면 안 된다."""
    실제 = FixtureStore.load()
    달러선물 = find_stream(실제, "KA", environment="real", action_sym="A7569000")
    옵션 = find_stream(실제, "KA", environment="real", action_sym="B0169A34")

    assert 달러선물.match == MATCH_EXACT
    assert 달러선물.action_sym == "A7569000"
    assert 옵션.match == MATCH_EXACT
    assert 옵션.action_sym == "B0169A34"
    assert 달러선물.fixture.record_id != 옵션.fixture.record_id

    # 모의 환경에는 달러선물 기록만 있다. 옵션을 구독하면 실전의 옵션 기록이
    # 다른 환경 표시로 오고, 모의의 달러선물 기록으로 대신하지 않는다.
    다른환경 = find_stream(실제, "KA", environment="paper", action_sym="B0169A34")
    assert 다른환경.match == MATCH_CROSS_ENVIRONMENT
    assert 다른환경.action_sym == "B0169A34"
    with pytest.raises(ReplayMiss):
        find_stream(실제, "KA", environment="paper", action_sym="C9999999")
