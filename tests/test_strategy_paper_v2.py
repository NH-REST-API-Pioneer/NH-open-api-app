"""종이 체결 모형 `paper-v2` — 낙관적이던 곳의 보정과 모형 이름.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 호가·체결·세션 판정은 손으로 넣고,
실행 파일·기록 파일은 임시 폴더에 씁니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine, journal as journal_lib, paper, pump as pump_lib, records, runs
from backend.strategy import service as service_lib
from tests.test_strategy_engine import _때, _매수_보유, _설정, _틱
from tests.test_strategy_records import _거래, _조건

기준 = 1_000_000
지연 = int(paper.DELAY_SECONDS * 1000)


def _호가(asks, bids) -> dict:
    return {
        "asks": [{"price": price, "quantity": qty} for price, qty in asks],
        "bids": [{"price": price, "quantity": qty} for price, qty in bids],
    }


def _시장가(장부: paper.PaperBook, quantity: int, side: str = paper.BUY, name: str = "o1") -> paper.PaperOrder:
    return 장부.place(name, side=side, quantity=quantity, order_type=paper.MARKET_ORDER, at=기준)


# ── 모형 이름 ─────────────────────────────────────────────


def test_모형_이름은_paper_v2_다():
    assert paper.MODEL == "paper-v2" and paper.LEGACY_MODEL == "paper-v1"


def _목록(tmp_path) -> service_lib.RunService:
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=type("M", (), {"locate": lambda self, m, c: {"rem_cnt": "9", "ctrt_size": "1", "product_code": "01"}})(),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
    )


def test_새_종이_실행은_v2_로_서고_실행_줄도_v2_다(tmp_path):
    목록 = _목록(tmp_path)
    목록.add(run_id="r1", version_id="v1", draft=_설정(), market="domestic", code="A7569000",
            session="domestic-day", qty=1, cash=1.0)

    (줄,) = 목록.rows()
    assert 목록._engine("r1").run.model == "paper-v2" and 줄["model"] == "paper-v2"


def _옛_실행(tmp_path, state: str = runs.PAUSED) -> None:
    """모형 칸이 없던 때의 파일 — 옛 종이 실행 하나."""
    runs.RunStore(tmp_path / "runs.json").save(
        [runs.Run(id="r1", version_id="v1", code="A7569000", session="domestic-day",
                  market="domestic", state=state, draft=_설정())]
    )


def _바뀜(목록: service_lib.RunService) -> list[str]:
    return [one["text"] for one in 목록._engine("r1").events if "체결 모델이" in one["text"]]


def test_되살린_옛_종이_실행은_v2_로_바뀌고_이벤트는_한_번이다(tmp_path):
    _옛_실행(tmp_path)

    처음 = _목록(tmp_path)
    (줄,) = 처음.rows()
    assert 줄["model"] == "paper-v2"
    assert _바뀜(처음) == ["체결 모델이 paper-v2 로 바뀜"]

    다시 = _목록(tmp_path)
    (줄,) = 다시.rows()
    assert 줄["model"] == "paper-v2"
    assert _바뀜(다시) == [], "고친 이름을 담아 두어 다시 켜도 또 남기지 않습니다."


def test_끝난_옛_실행은_담긴_이름_그대로다(tmp_path):
    _옛_실행(tmp_path, state=runs.ENDED)

    목록 = _목록(tmp_path)
    (줄,) = 목록.rows()
    assert 줄["model"] == "paper-v1" and _바뀜(목록) == []


def test_체결_줄과_거래_줄에_모형을_싣는다():
    기록: list = []
    엔진, 때 = _매수_보유()
    엔진.record = lambda kind, row: 기록.append((kind, dict(row)))
    (진입,) = 엔진.fills
    assert 진입["model"] == "paper-v2"

    _틱(엔진, 때 + 10, 101.0)  # 2틱 손절
    엔진.on_book({"asks": [{"price": 101.05, "quantity": 9}], "bids": [{"price": 101.0, "quantity": 9}]},
                 at=때 + 10 + 지연)
    (거래,) = [row for kind, row in 기록 if kind == "trade"]
    assert 거래["model"] == "paper-v2"


def test_옛_기록은_v1_로_읽고_섞인_기간에는_표지를_단다():
    옛 = _거래(_때(10, 10))  # 모형 칸 없음
    새 = {**_거래(_때(11, 10), run="r2"), "model": "paper-v2"}

    assert records.model_of(옛) == "paper-v1"
    assert records.model_of({**옛, "record": "sim"}) == "sim-v1"
    섞임 = records.dataset([옛, 새], _조건())
    assert 섞임["models"] == ["paper-v1", "paper-v2"] and 섞임["mixedModels"] is True
    assert [one["model"] for one in 섞임["trades"]] == ["paper-v1", "paper-v2"]
    한가지 = records.dataset([새], _조건())
    assert 한가지["mixedModels"] is False


# ── 1 시장가 잔량 다시 먹기 ──────────────────────────────────


def test_같은_호가가_다시_와도_먹은_잔량은_다시_못_먹는다():
    장부 = paper.PaperBook()
    _시장가(장부, 3, name="o1")
    채움 = 장부.on_book(_호가([(100.0, 3)], [(99.0, 9)]), at=기준 + 지연)
    assert [(one["price"], one["quantity"]) for one in 채움] == [(100.0, 3)]

    _시장가(장부, 3, name="o2")
    다시 = 장부.on_book(_호가([(100.0, 3)], [(99.0, 9)]), at=기준 + 지연 + 10)
    assert 다시 == [], "같은 잔량 3 은 이미 먹었습니다."


def test_잔량이_늘면_는_만큼만_줄면_기억을_지운다():
    장부 = paper.PaperBook()
    _시장가(장부, 3, name="o1")
    장부.on_book(_호가([(100.0, 3)], [(99.0, 9)]), at=기준 + 지연)

    둘째 = _시장가(장부, 5, name="o2")
    늘어남 = 장부.on_book(_호가([(100.0, 5)], [(99.0, 9)]), at=기준 + 지연 + 10)
    assert [(one["price"], one["quantity"]) for one in 늘어남] == [(100.0, 2)], "3 → 5, 는 2 만."

    줄어듦 = 장부.on_book(_호가([(100.0, 1)], [(99.0, 9)]), at=기준 + 지연 + 20)
    assert [(one["price"], one["quantity"]) for one in 줄어듦] == [(100.0, 1)], "줄었으니 새 잔량입니다."
    assert 둘째.remaining == 2


# ── 2 단일가·가격제한 ────────────────────────────────────────


def test_단일가_구간에서는_채우지_않고_끝난_뒤_첫_값부터_채운다():
    장부 = paper.PaperBook()
    끝 = 기준 + 지연 + 100
    장부.auction = (0, 끝)
    주문 = _시장가(장부, 1)
    assert 장부.on_book(_호가([(100.0, 9)], [(99.0, 9)]), at=기준 + 지연) == []
    assert 장부.on_trade({"price": 100.0, "quantity": 5}, at=기준 + 지연) == []

    assert len(장부.on_book(_호가([(100.5, 9)], [(99.0, 9)]), at=끝)) == 1
    assert 주문.fills[0]["price"] == 100.5, "단일가로 한 값에 맞추지 않고 끝난 뒤 첫 호가입니다."


def test_단일가는_박자가_아니라_체결_시각으로_가른다():
    """거래 창에서 받은 「다음 경계」를 체결 시각과 견줍니다 — 경계 직전은 채우고 직후는 미룹니다."""
    장부 = paper.PaperBook()
    경계 = 기준 + 10_000
    장부.auction = (경계, 경계 + 600_000)
    앞 = 장부.place("a", side=paper.BUY, quantity=1, order_type=paper.LIMIT_ORDER, price=100.0, at=기준)
    장부.on_book(_호가([(101.0, 9)], [(99.0, 9)]), at=기준 + 지연)

    assert len(장부.on_trade({"price": 99.5, "quantity": 1}, at=경계 - 1)) == 1, "경계 직전 체결은 채웁니다."
    뒤 = 장부.place("b", side=paper.BUY, quantity=1, order_type=paper.LIMIT_ORDER, price=100.0, at=기준)
    뒤.arrived, 뒤.queue_ahead, 뒤.queue_done = True, 0, 0
    assert 장부.on_trade({"price": 99.5, "quantity": 1}, at=경계) == [], "경계 직후 체결은 미룹니다."
    assert 앞.filled == 1 and 뒤.filled == 0


def test_한도_가격에_줄_선_지정가는_그_가격의_체결로_채운다():
    """상한가에서 시장가 매수는 미루지만, 상한가에 줄 서 있던 매수 지정가는 줄 규칙대로 채웁니다."""
    장부 = paper.PaperBook()
    장부.upper, 장부.lower = 101.0, 90.0
    장부.on_trade({"price": 101.0, "quantity": 1}, at=기준)
    지정 = 장부.place("l", side=paper.BUY, quantity=2, order_type=paper.LIMIT_ORDER, price=101.0, at=기준)
    시장 = _시장가(장부, 1, paper.BUY, "m")

    assert 장부.on_book(_호가([(101.0, 9)], [(100.95, 9)]), at=기준 + 지연) == [], "먹지 않고 줄만 섭니다."
    assert 지정.arrived and 지정.queue_ahead == 0

    채움 = 장부.on_trade({"price": 101.0, "quantity": 1}, at=기준 + 지연 + 10)
    assert [(one["orderId"], one["quantity"]) for one in 채움] == [("l", 1)]
    assert 시장.filled == 0


def test_상한가에_앞_순위가_있으면_체결에서_앞_순위를_먼저_깎는다():
    장부 = paper.PaperBook()
    장부.upper, 장부.lower = 101.0, 90.0
    장부.on_trade({"price": 101.0, "quantity": 1}, at=기준)
    지정 = 장부.place("l", side=paper.BUY, quantity=4, order_type=paper.LIMIT_ORDER, price=101.0, at=기준)
    장부.on_book(_호가([(101.05, 9)], [(101.0, 3)]), at=기준 + 지연)
    assert 지정.queue_ahead == 3

    채움 = 장부.on_trade({"price": 101.0, "quantity": 5}, at=기준 + 지연 + 10)
    assert [(one["price"], one["quantity"]) for one in 채움] == [(101.0, 2)], "체결 5 − 앞 순위 3 = 2."


def test_한도_값을_아직_모르면_제한하지_않는다():
    장부 = paper.PaperBook()
    장부.on_trade({"price": 500.0, "quantity": 1}, at=기준)
    _시장가(장부, 1)

    assert len(장부.on_book(_호가([(500.0, 9)], [(499.0, 9)]), at=기준 + 지연)) == 1


def test_상한가에_닿으면_매수는_미루고_매도는_채운다():
    장부 = paper.PaperBook()
    장부.upper, 장부.lower = 101.0, 90.0
    장부.on_trade({"price": 101.0, "quantity": 1}, at=기준)
    사기 = _시장가(장부, 1, paper.BUY, "b")
    팔기 = _시장가(장부, 1, paper.SELL, "s")

    채움 = 장부.on_book(_호가([(101.0, 9)], [(100.95, 9)]), at=기준 + 지연)
    assert [one["orderId"] for one in 채움] == ["s"]
    assert 사기.filled == 0 and 팔기.filled == 1


def test_하한가에_닿으면_매도를_미룬다():
    장부 = paper.PaperBook()
    장부.upper, 장부.lower = 110.0, 90.0
    장부.on_trade({"price": 90.0, "quantity": 1}, at=기준)
    _시장가(장부, 1, paper.SELL, "s")

    assert 장부.on_book(_호가([(90.05, 9)], [(90.0, 9)]), at=기준 + 지연) == []


def test_실행_목록이_단일가_표지와_실시간_상하한을_엔진에_넣는다(tmp_path):
    목록 = _목록(tmp_path)
    목록.add(run_id="r1", version_id="v1", draft=_설정(), market="domestic", code="A7569000",
            session="domestic-day", qty=1, cash=1.0)
    엔진 = 목록._engine("r1")
    구간 = (_때(8, 30), _때(8, 45))
    돌리는것 = pump_lib.RunPump(목록, hub=None, judge=lambda *a: True, auction=lambda *a: 구간,
                            replaying=lambda: False)

    돌리는것._sessions(_때(8, 50))
    assert 엔진.book.auction == 구간
    돌리는것.take({"type": "quote", "context": "domestic-day", "sym": "A7569000",
                "patch": {"upperLimit": 120.0, "lowerLimit": 80.0}, "trades": []}, at=_때(8, 50))
    assert (엔진.book.upper, 엔진.book.lower) == (120.0, 80.0)

    돌리는것.auction = lambda *a: None
    돌리는것._sessions(_때(9, 0))
    assert 엔진.book.auction is None


def test_세션_판정에서_단일가_구간을_읽는다(monkeypatch):
    from datetime import datetime

    from backend.sessions import judge, sessions_routes
    from backend.sessions.hours import KST

    def iso(hour, minute, day=17):
        return datetime(2026, 9, day, hour, minute, tzinfo=KST).isoformat()

    답 = {"source": "api", "state": judge.PRE_OPEN, "session": "day", "since": iso(8, 30), "until": iso(8, 45),
         "nextOpen": iso(8, 45)}
    monkeypatch.setattr(sessions_routes, "judged", lambda market, code, now: dict(답))

    assert pump_lib._auction_now("domestic", "A7569000", "domestic-day") == (_때(8, 30), _때(8, 45))
    assert pump_lib._auction_now("domestic", "A7569000", "domestic-night") is None
    답.update(state="day", since=iso(8, 45), until=iso(15, 35), nextOpen=iso(8, 45, day=18))
    assert pump_lib._auction_now("domestic", "A7569000", "domestic-day") == (_때(15, 35), _때(8, 45, day=18)), (
        "거래 창이면 다음 경계(종가 단일가 시작)부터입니다."
    )
    답.update(state=judge.CLOSING_AUCTION, since=iso(15, 35), until=iso(15, 45))
    assert pump_lib._auction_now("domestic", "A7569000", "domestic-day") == (_때(15, 35), _때(15, 45))
    답.update(source=judge.UNKNOWN)
    assert pump_lib._auction_now("domestic", "A7569000", "domestic-day") == (0, pump_lib._FOREVER), (
        "품목을 모르면 늘 미룹니다."
    )
    assert pump_lib._auction_now("overseas", "ESZ26", "overseas") is None, (
        "해외는 시간표를 몰라도(UNKNOWN) 단일가가 아닙니다 — 출처가 없어 늘 아님입니다."
    )


def test_해외_기록은_달러_그대로이고_원화_칸이_없다():
    해외 = records.dataset([_거래(_때(10, 10), market="overseas")], _조건(market="overseas"))

    assert 해외["currency"] == "USD"
    assert not [key for key in 해외 if "krw" in key.lower() or "fx" in key.lower() or "rate" == key.lower()]


# ── 4 끊긴 뒤 손절 ─────────────────────────────────────────


def test_끊긴_사이_손절선을_지나면_다시_붙은_첫_값에_닫는다():
    엔진, 때 = _매수_보유(stopTicks="2", takeTicks="100")  # 101.5 에 1계약, 손절 101.4
    엔진.on_status(False, at=때 + 10)
    assert 엔진.feed == engine.GAP

    _틱(엔진, 때 + 20, 100.0)

    청산 = 엔진.fills[-1]
    assert 청산["price"] == 100.0 and 청산["time"] == 때 + 20 and 청산["reason"] == engine.STOP_LOSS
    assert 엔진.ledger.position.quantity == 0
    (거래,) = 엔진.ledger.trades
    assert -거래["grossPl"] > 2 * 0.05, "손실이 손절 폭보다 큽니다."


# ── 5 수수료 두 칸 ─────────────────────────────────────────


def test_체결_줄의_수수료는_거래소_몫과_청산_몫이고_합이_fee_다():
    from tests.test_strategy_engine import _엔진, _넣기

    엔진 = _엔진(_설정(), fee_per_contract=250.0)
    _넣기(엔진, 0, 99.0)
    _넣기(엔진, 1, 101.0)
    _넣기(엔진, 2, 101.0)
    엔진.on_book({"asks": [{"price": 101.5, "quantity": 9}], "bids": [{"price": 101.0, "quantity": 9}]},
                 at=_때(10, 2) + 지연)
    (진입,) = 엔진.fills

    assert 진입["fee"] == 250.0
    assert 진입["feeExchange"] == 250.0 and 진입["feeClearing"] is None, "청산 몫은 출처가 없습니다."
    assert 엔진.ledger.fee == 250.0, "장부의 누계는 그대로 합입니다."
