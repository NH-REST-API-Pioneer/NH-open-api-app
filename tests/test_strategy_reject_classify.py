"""계좌가 주문을 거부한 것과 답을 못 받은 것을 가릅니다.

**계좌에 닿지 않습니다.** 보내는 자리가 거래 API 의 예외를 그대로 던지게 하고,
그 사이의 우리 코드를 다 지나갑니다.

- 서버가 코드와 문구로 거부한 답은 `rejected` 이고, 사건 글에 그 코드와 문구가 실립니다.
- 응답을 못 받았거나 처리됐는지 모르는 자리는 지금처럼 `no-reply` 이고 「확인 필요」입니다.
- 진입 거부는 중지, 청산 거부는 「확인 필요」입니다.
- 「확인 필요」 동안 구독을 놓아 연결이 닫히는 것은 끊김으로 적지 않습니다.
"""
from __future__ import annotations

import pytest

from backend.nh_api.errors import BusinessError, GatewayError, HttpError, TransportError
from backend.realtime.feeds import Feed
from backend.realtime.link import STOPPED
from backend.strategy import engine as engine_lib
from backend.strategy import paper, pump as pump_lib, runs, sim
from tests.test_strategy_pump import _허브
from tests.test_strategy_service import _모의목록, _모의물음

#: 2026-10-12 모의 실행에서 받은 거부. 시장가에 FAK 를 달아 낸 진입이었습니다.
_FAK_거부 = BusinessError(
    "domestic_order", "5039", "처리불가 [시장가는 FOK, FAK 주문불가입니다 ]", {}
)
_FAK_글 = "주문 거부 5039 — 처리불가 [시장가는 FOK, FAK 주문불가입니다 ]"

시각 = 10_000


class _터지는곳:
    """주문마다 정해 둔 예외를 던지는 자리. 몇 번 불렸는지 셉니다."""

    def __init__(self, 터짐: Exception):
        self.터짐 = 터짐
        self.sent: list[dict] = []
        self.cancelled: list[str] = []

    def order(self, **물음):
        self.sent.append(물음)
        raise self.터짐

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": order.order_no}


def _장부(터짐: Exception) -> sim.SimBroker:
    run = runs.Run(
        id="r1", version_id="v1", code="A016C000", session="domestic-day", market="domestic",
        mode=runs.SIM, approved_at=1_000, environment="paper", qty=1,
    )
    return sim.SimBroker(run, sender=_터지는곳(터짐), environment=lambda: "paper")


def _거부(터짐: Exception) -> sim.SimRefused:
    with pytest.raises(sim.SimRefused) as 받음:
        _장부(터짐).place("o1", side=paper.BUY, quantity=1, order_type="시장가", fill_condition="FAK", at=1)
    return 받음.value


def _세운(tmp_path, 터짐: Exception, *, state: str):
    보낸곳 = _터지는곳(터짐)
    실행목록 = _모의목록(tmp_path, sender=보낸곳)
    실행목록.add(**_모의물음())
    펌프 = pump_lib.RunPump(실행목록, hub=_허브(), auction=lambda *_, **__: None)
    엔진 = 실행목록._engine("run1")
    엔진.run.state = state
    엔진.feed = "live"
    엔진.last_trade_at = 시각 - 1_000
    return 실행목록, 펌프, 엔진, 보낸곳


def _줄(엔진, kind: str) -> list[dict]:
    return [one for one in 엔진.events if one["kind"] == kind]


def _공백줄(엔진) -> list[str]:
    return [one["text"] for one in _줄(엔진, engine_lib.GAP)]


def _구독(펌프) -> set[Feed]:
    return {one for one in 펌프.wishes() if one.sym}


# ── 가르기 ────────────────────────────────────────────


def test_업무_거부는_rejected_이고_코드와_서버_문구를_싣는다():
    거부 = _거부(_FAK_거부)

    assert 거부.reason == sim.REJECTED == "rejected"
    assert (거부.code, 거부.detail) == ("5039", "처리불가 [시장가는 FOK, FAK 주문불가입니다 ]")
    assert str(거부) == _FAK_글
    assert 거부.flag is False, "계좌에 남은 것이 없어 확인을 청하지 않습니다."
    assert sim.WHY_NO_REPLY not in str(거부)


def test_서버_문구가_비면_예비_문구를_쓰고_그것도_없으면_코드만_남는다():
    assert str(_거부(BusinessError("domestic_order", "5039", "", {}))) == "주문 거부 5039 — 거래소 (야간)개장전입니다."
    assert str(_거부(BusinessError("domestic_order", "E1234", "", {}))) == "주문 거부 E1234"


def test_모의에서_제공하지_않는_API_라는_답은_거부다():
    거부 = _거부(GatewayError("domestic_order", "EGW053", "모의투자 미지원", {}, kind="paper-unavailable"))

    assert 거부.reason == sim.REJECTED and 거부.code == "EGW053"
    assert str(거부) == "주문 거부 EGW053 — 모의투자 미지원"


def test_HTTP_4xx_는_거부이고_서버_설명을_싣는다():
    거부 = _거부(HttpError("domestic_order", 400, {"errorMessage": "잘못된 요청"}))

    assert 거부.reason == sim.REJECTED
    assert str(거부) == "주문 거부 HTTP 400 — 잘못된 요청"


@pytest.mark.parametrize(
    "터짐",
    [
        TransportError("domestic_order", "응답 없음"),
        TimeoutError("응답 없음"),
        ConnectionError("끊김"),
        GatewayError("domestic_order", "EGW00", "게이트웨이 거절", {}),
        HttpError("domestic_order", 500, {"errorMessage": "서버 오류"}),
        RuntimeError("업무 거부 99999"),
    ],
    ids=["시간초과", "TimeoutError", "연결오류", "게이트웨이", "HTTP500", "그밖"],
)
def test_접수됐는지_모르는_자리는_지금처럼_no_reply_이고_확인을_청한다(터짐):
    거부 = _거부(터짐)

    assert 거부.reason == "no-reply"
    assert 거부.flag is True
    assert str(거부).startswith(sim.WHY_NO_REPLY)
    assert 거부.code == "" and 거부.detail == ""


# ── 엔진: 사건·결과 줄·상태 ─────────────────────────────


def test_진입이_거부되면_코드를_실은_사건이_서고_공백은_없고_중지로_간다(tmp_path):
    실행목록, 펌프, 엔진, 보낸곳 = _세운(tmp_path, _FAK_거부, state=runs.ARMED)
    남김: list = []
    엔진.record = lambda kind, row: 남김.append((kind, row))
    구독앞 = _구독(펌프)

    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    (사건,) = _줄(엔진, engine_lib.BLOCKED)
    assert 사건["text"] == _FAK_글, "「주문을 내지 않았습니다」 머리를 붙이지 않습니다 — 나갔고 거부됐습니다."
    assert 사건["reason"] == "rejected" and 사건["code"] == "5039" and 사건["why"] == _FAK_글
    assert 엔진.run.state == runs.PAUSED
    assert len(보낸곳.sent) == 1, "같은 주문을 다시 보내지 않습니다."
    assert 엔진.book.orders == []

    (결과,) = [row for kind, row in 남김 if kind == engine_lib.ORDER_ROW]
    assert 결과["outcome"] == engine_lib.REJECTED
    assert (결과["serverStatus"], 결과["serverCode"], 결과["serverMessage"]) == (
        "rejected", "5039", "처리불가 [시장가는 FOK, FAK 주문불가입니다 ]",
    )
    assert 결과["orderNo"] is None and 결과["intent"] == "entry"

    # 중지는 시세를 계속 보는 상태라 구독이 그대로이고, 연결이 닫히지 않습니다.
    assert _구독(펌프) == 구독앞 and 구독앞
    assert _공백줄(엔진) == [] and 엔진.feed == "live"


def test_중지에서는_다음_신호에_같은_진입을_다시_내지_않는다(tmp_path):
    _, _, 엔진, 보낸곳 = _세운(tmp_path, _FAK_거부, state=runs.ARMED)

    엔진._send(paper.BUY, 1, 405.0, "entry", 시각)

    assert 엔진.run.state not in runs.ENTRY_STATES, "진입 규칙을 판정하지 않는 상태입니다."
    assert len(보낸곳.sent) == 1


def test_청산이_거부되면_확인_필요다(tmp_path):
    """중지로 두면 손절·익절 감시가 같은 청산을 체결마다 다시 내 같은 거부를 되풀이합니다."""
    _, _, 엔진, 보낸곳 = _세운(tmp_path, _FAK_거부, state=runs.HOLDING)

    엔진._send(paper.SELL, 1, 405.0, "exit", 시각)

    (사건,) = _줄(엔진, engine_lib.BLOCKED)
    assert 사건["text"] == _FAK_글 and 사건["reason"] == "rejected"
    assert 엔진.run.state == runs.ATTENTION
    assert len(보낸곳.sent) == 1


@pytest.mark.parametrize("state", [runs.ARMED, runs.HOLDING])
def test_답을_못_받으면_목적과_상관없이_지금처럼_확인_필요다(tmp_path, state):
    _, _, 엔진, 보낸곳 = _세운(tmp_path, TransportError("domestic_order", "응답 없음"), state=state)

    엔진._send(paper.BUY, 1, 405.0, "entry" if state == runs.ARMED else "exit", 시각)

    (사건,) = _줄(엔진, engine_lib.BLOCKED)
    assert 사건["reason"] == "no-reply"
    assert 사건["text"].startswith(engine_lib.UNSENT_HEAD + sim.WHY_NO_REPLY)
    assert 엔진.run.state == runs.ATTENTION
    assert len(보낸곳.sent) == 1


# ── 「확인 필요」 동안의 공백 ────────────────────────────


def test_확인_필요로_구독을_놓아_연결이_닫혀도_끊김으로_적지_않는다(tmp_path):
    """확인 필요는 시세를 보지 않아 구독을 놓습니다. 그 시장에 보는 것이 없으면
    연결이 닫히고(`STOPPED`) 허브가 그 상태를 알립니다 — 끊긴 것이 아닙니다."""
    _, 펌프, 엔진, _ = _세운(tmp_path, TransportError("domestic_order", "응답 없음"), state=runs.HOLDING)
    assert _구독(펌프)

    엔진._send(paper.SELL, 1, 405.0, "exit", 시각)
    assert 엔진.run.state == runs.ATTENTION
    assert _구독(펌프) == set(), "확인 필요는 구독을 놓습니다 — 연결이 닫히는 까닭입니다."

    펌프.take({"type": "status", "market": "domestic", "state": STOPPED, "detail": ""}, at=시각 + 1)
    엔진.tick_clock(시각 + 120_000)

    assert _공백줄(엔진) == []
    assert 엔진.feed == engine_lib.GAP and 엔진.book.gap, "공백 표지는 세워 둡니다."
    assert 펌프.probes_wanted(시각 + 10_000_000) == [], "구독을 놓은 실행 때문에 시세를 묻지 않습니다."


def test_확인하면_그동안의_공백을_적고_첫_체결에서_풀린다(tmp_path):
    실행목록, 펌프, 엔진, _ = _세운(tmp_path, TransportError("domestic_order", "응답 없음"), state=runs.HOLDING)
    엔진._send(paper.SELL, 1, 405.0, "exit", 시각)
    펌프.take({"type": "status", "market": "domestic", "state": STOPPED, "detail": ""}, at=시각 + 1)

    실행목록.acknowledge("run1", 시각 + 2)

    assert 엔진.run.state == runs.PAUSED
    assert _공백줄(엔진) == [f"데이터 공백 — {engine_lib.ATTENTION_GAP}(마지막 수신 09:00:09)"]
    assert 엔진.quiet_since == 시각 + 2, "체결이 안 오면 시장이 흘렀는지 묻는 길을 탑니다."
    assert _구독(펌프), "중지는 다시 시세를 봅니다."

    엔진.on_trade({"price": 405.0, "qty": 1}, "domestic-day", at=시각 + 3)

    assert _공백줄(엔진)[-1] == "시세가 다시 들어옵니다"
    assert 엔진.feed == "live"


def test_확인_필요_동안_공백이_풀리면_사건_없이_풀린다(tmp_path):
    _, 펌프, 엔진, _ = _세운(tmp_path, TransportError("domestic_order", "응답 없음"), state=runs.HOLDING)
    엔진._send(paper.SELL, 1, 405.0, "exit", 시각)
    펌프.take({"type": "status", "market": "domestic", "state": STOPPED, "detail": ""}, at=시각 + 1)

    엔진.on_trade({"price": 405.0, "qty": 1}, "domestic-day", at=시각 + 2)

    assert _공백줄(엔진) == [], "적지 않은 공백의 「다시 들어옵니다」만 홀로 서지 않습니다."
    assert 엔진.feed == "live"


def test_보던_실행의_끊김은_지금처럼_적는다(tmp_path):
    _, 펌프, 엔진, _ = _세운(tmp_path, _FAK_거부, state=runs.HOLDING)

    펌프.take({"type": "status", "market": "domestic", "state": STOPPED, "detail": ""}, at=시각 + 1)

    assert _공백줄(엔진) == ["데이터 공백 — 연결이 끊겼습니다(마지막 수신 09:00:09)"]
