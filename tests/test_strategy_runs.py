"""검증 실행 — 상태 기계·가상 장부·안전 검사."""
from __future__ import annotations

import json

import pytest

from backend.nh_api import session
from backend.strategy import runs
from backend.strategy.paper import BUY, SELL


def _실행(**덮어쓰기) -> runs.Run:
    made = {
        "id": "r1",
        "version_id": "v1",
        "code": "A7569000",
        "session": "domestic-day",
        "market": "domestic",
        "state": runs.ARMED,
        "qty": 1,
    }
    made.update(덮어쓰기)
    return runs.Run(**made)


def _장부(**덮어쓰기) -> runs.Ledger:
    return runs.Ledger(**덮어쓰기)


def _체결(side: str, quantity: int, price: float, time: int = 1) -> dict:
    return {"side": side, "quantity": quantity, "price": price, "time": time}


# ── 상태 기계 ────────────────────────────────────────────


def test_상태가_여덟이다():
    assert len(runs.STATE_LABEL) == 8
    assert set(runs.STATE_LABEL) == {
        runs.ARMED,
        runs.ENTERING,
        runs.HOLDING,
        runs.EXITING,
        runs.PAUSED,
        runs.ATTENTION,
        runs.RECONCILING,
        runs.ENDED,
    }


@pytest.mark.parametrize(
    ("에서", "사건", "으로"),
    [
        (runs.ARMED, runs.ENTRY_SENT, runs.ENTERING),
        (runs.ENTERING, runs.ENTRY_FILLED, runs.HOLDING),
        (runs.ENTERING, runs.ENTRY_CANCELLED, runs.ARMED),
        (runs.HOLDING, runs.EXIT_SENT, runs.EXITING),
        (runs.EXITING, runs.EXIT_FILLED, runs.ARMED),
        (runs.EXITING, runs.EXIT_CANCELLED, runs.HOLDING),
        (runs.PAUSED, runs.RESUME, runs.ARMED),
        (runs.PAUSED, runs.END, runs.ENDED),
        (runs.RECONCILING, runs.RECONCILED, runs.PAUSED),
        (runs.RECONCILING, runs.END, runs.ENDED),
        (runs.ATTENTION, runs.ACKNOWLEDGE, runs.PAUSED),
    ],
)
def test_전이표대로_옮긴다(에서, 사건, 으로):
    assert runs.next_state(에서, 사건) == 으로


def test_재기동_뒤에는_자동으로_안_돈다():
    """대사가 끝나도 사용자가 「재개」를 눌러야 판정을 시작합니다."""
    assert runs.next_state(runs.RECONCILING, runs.RECONCILED) == runs.PAUSED


def test_표에_없는_짝은_그대로다():
    """빈 자리를 아무 데나 잇지 않습니다."""
    assert runs.next_state(runs.ARMED, runs.EXIT_FILLED) == runs.ARMED
    assert runs.next_state(runs.ENDED, runs.ENTRY_SENT) == runs.ENDED


def test_어느_상태에서든_확인_필요로_간다():
    for 에서 in (runs.ARMED, runs.HOLDING, runs.EXITING, runs.PAUSED):
        assert runs.next_state(에서, runs.FLAG) == runs.ATTENTION


def test_중지_중에_청산이_끝나면_중지로_돌아온다():
    """멈춰 둔 것을 청산 한 번으로 되살리면 안 보는 사이에 다시 진입합니다."""
    실행 = _실행(state=runs.HOLDING)

    실행.move(runs.PAUSE)
    assert 실행.state == runs.PAUSED
    실행.move(runs.EXIT_SENT)
    assert 실행.state == runs.EXITING

    assert 실행.move(runs.EXIT_FILLED) == runs.PAUSED


def test_재개하면_중지_기억이_풀린다():
    실행 = _실행(state=runs.ARMED)
    실행.move(runs.PAUSE)

    실행.move(runs.RESUME)
    실행.move(runs.ENTRY_SENT)
    실행.move(runs.EXIT_SENT)

    assert 실행.move(runs.EXIT_FILLED) == runs.ARMED


# ── 가상 장부 ────────────────────────────────────────────


def test_보유는_체결에서_센다():
    """저장한 포지션과 체결 목록이 어긋나는 날이 없게 합니다."""
    장부 = _장부()

    장부.add(_체결(BUY, 2, 400.0))
    장부.add(_체결(BUY, 2, 402.0))

    assert (장부.position.quantity, 장부.position.avg_price) == (4, 401.0)
    assert 장부.position.side == BUY


def test_거래는_0_에서_0_까지_한_덩어리다():
    """마지막 청산 한 조각만 적으면 승률과 평균 손익이 그 조각의 것이 됩니다."""
    장부 = _장부(multiplier=250_000.0, fee_per_contract=2_000.0)
    장부.add(_체결(BUY, 2, 400.0, time=1))
    장부.add(_체결(SELL, 1, 401.0, time=2))

    거래 = 장부.add(_체결(SELL, 1, 403.0, time=3))

    assert 거래 is not None
    assert (거래["quantity"], 거래["avgEntry"], 거래["avgExit"]) == (2, 400.0, 402.0)
    assert (거래["openedAt"], 거래["closedAt"]) == (1, 3)
    assert 거래["grossPl"] == 1_000_000.0
    assert 거래["fee"] == 8_000.0, "진입 2 + 청산 2 계약의 수수료입니다."
    assert 거래["netPl"] == 992_000.0
    assert 장부.position.quantity == 0


def test_반대로_넘어가면_거래가_닫히고_새로_열린다():
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0, time=1))

    닫힌것 = 장부.add(_체결(SELL, 3, 105.0, time=2))

    assert 닫힌것 is not None and 닫힌것["side"] == BUY
    assert (장부.position.quantity, 장부.position.avg_price) == (-2, 105.0)
    assert 장부.add(_체결(BUY, 2, 103.0, time=3))["side"] == SELL
    assert len(장부.trades) == 2


def test_평가손익은_마지막_체결가로_센다():
    장부 = _장부(multiplier=250_000.0)
    장부.add(_체결(SELL, 1, 400.0))

    assert 장부.unrealized(398.0) == 500_000.0, "매도 보유는 값이 내리면 이익입니다."
    assert 장부.unrealized(None) == 0.0, "값을 모르면 0 입니다."


def test_손익은_실현에서_수수료를_뺀다():
    장부 = _장부(fee_per_contract=1_000.0)
    장부.add(_체결(BUY, 1, 100.0))
    장부.add(_체결(SELL, 1, 110.0))

    assert 장부.realized == 10.0
    assert 장부.profit(None) == 10.0 - 2_000.0


def test_거래일이_바뀌면_하루치를_다시_센다():
    """보유는 넘어가고 건수와 하루 손익만 다시 엽니다."""
    실행 = _실행()
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))
    장부.add(_체결(SELL, 1, 110.0))
    실행.roll_day(1, 장부)
    실행.count_intent()

    assert runs.day_profit(실행, 장부, None) == 0.0, "어제 번 것은 오늘 것이 아닙니다."

    장부.add(_체결(BUY, 1, 100.0))
    실행.roll_day(1, 장부)

    assert 실행.intents_today == 1, "같은 날이면 그대로입니다."
    assert 장부.position.quantity == 1, "보유는 날을 넘어갑니다."


# ── 안전 검사 ────────────────────────────────────────────


def _막힘(실행, 장부, **덮어쓰기):
    물음 = {
        "side": BUY,
        "open_entry": 0,
        "max_hold": 5,
        "add_while_open": False,
        "gap": False,
        "expiring": False,
        "last_price": 100.0,
    }
    물음.update(덮어쓰기)
    return runs.entry_block(실행, 장부, **물음)


def test_막을_것이_없으면_없음이다():
    assert _막힘(_실행(), _장부()) is None


def test_판정하지_않는_상태에서는_진입하지_않는다():
    for 상태 in (runs.ENTERING, runs.EXITING, runs.PAUSED, runs.ATTENTION, runs.ENDED):
        assert _막힘(_실행(state=상태), _장부()) == runs.WHY_STATE


def test_공백과_만기가_상태_다음이다():
    """화면에 적히는 것은 첫 까닭 하나라 큰 것이 먼저 나와야 합니다."""
    assert _막힘(_실행(), _장부(), gap=True) == runs.WHY_GAP
    assert _막힘(_실행(), _장부(), expiring=True) == runs.WHY_EXPIRY


def test_하루_건수를_다_쓰면_막는다():
    실행 = _실행()
    for _ in range(runs.DAILY_INTENTS):
        실행.count_intent()

    assert _막힘(실행, _장부()) == runs.WHY_DAILY


def test_하루_손실_한도에_닿으면_막는다():
    실행 = _실행(daily_loss=1_000.0)
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))
    장부.add(_체결(SELL, 1, 90.0))

    assert 장부.realized == -10.0
    assert _막힘(실행, 장부) is None, "아직 한도에 못 미칩니다."

    실행.daily_loss = 10.0
    assert _막힘(실행, 장부) == runs.WHY_DAILY_LOSS


def test_보유와_반대_방향은_진입하지_않는다():
    장부 = _장부()
    장부.add(_체결(SELL, 1, 100.0))

    assert _막힘(_실행(), 장부, side=BUY) == runs.WHY_OPPOSITE


def test_추가_진입은_켜_두었을_때만_한다():
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))

    assert _막힘(_실행(), 장부, side=BUY) == runs.WHY_ADD
    assert _막힘(_실행(), 장부, side=BUY, add_while_open=True) is None


def test_최대_보유는_미체결_진입까지_센다():
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))

    물음 = {"side": BUY, "add_while_open": True, "max_hold": 3}
    assert _막힘(_실행(), 장부, open_entry=1, **물음) is None
    assert _막힘(_실행(), 장부, open_entry=2, **물음) == runs.WHY_MAX_HOLD


def test_증거금을_모르면_예산을_잴_수_없다고_한다():
    """0 으로 답하면 「한 계약도 못 든다」가 되고 큰 수로 답하면 예산이 없는 것과 같습니다."""
    # 국내입니다 — 품목별세부정보에 칸이 있어, 비어 있으면 아직 못 받은 것입니다.
    모름 = _실행(market="domestic", margin_budget=10_000_000.0, margin=None)
    앎 = _실행(market="domestic", margin_budget=10_000_000.0, margin=2_500_000.0)
    작음 = _실행(market="domestic", margin_budget=1_000_000.0, margin=2_500_000.0)

    assert _막힘(모름, _장부()) == runs.WHY_MARGIN_UNKNOWN
    assert _막힘(앎, _장부()) is None
    assert _막힘(작음, _장부()) == runs.WHY_BUDGET


def test_실행_수와_구독_자리가_맞는다():
    """실행마다 시세·호가 둘이라 스무 자리에서 몫이 정해집니다."""
    assert runs.MAX_RUNS * runs.FEEDS_PER_RUN == 14
    assert str(runs.MAX_RUNS) in runs.WHY_RUNS


def test_검증_줄의_이름이_화면과_같다():
    실행 = _실행()
    장부 = _장부()
    장부.add(_체결(BUY, 2, 400.0))

    줄 = runs.row_of(실행, 장부, feed="live", feed_at=7, last_price=401.0)

    assert 줄["position"] == 2 and 줄["side"] == BUY and 줄["avgPrice"] == 400.0
    assert 줄["state"] == runs.ARMED and 줄["stateLabel"] == "감시 중"
    assert "paperOnly" not in 줄
    assert 줄["environment"] is None
    assert {"id", "version", "code", "session", "qty", "cash", "margin", "pl"} <= set(줄)


def test_실행은_기본으로_종이다():
    """엔진은 사람이 단추를 누르지 않아도 주문을 냅니다. 갈래를 안 주면 종이입니다."""
    assert _실행().mode == runs.PAPER
    assert _실행().environment == ""


# ── 저장 ────────────────────────────────────────────────


def test_처음에는_담긴_실행이_없다(tmp_path):
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")

    assert 저장소.read() == []
    assert not 저장소.path.exists()


def test_담고_다시_읽으면_중지_상태다(tmp_path):
    """꺼져 있던 동안 손절 감시가 없었습니다 — 사용자가 보고 이어 갈지 정합니다."""
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")
    저장소.save([_실행(state=runs.HOLDING, qty=3, cash=5_000_000.0)])

    (읽은것,) = 저장소.read()

    assert 읽은것.state == runs.PAUSED
    assert (읽은것.id, 읽은것.qty, 읽은것.cash) == ("r1", 3, 5_000_000.0)


def test_되살린_모의_실행은_대사로_선다(tmp_path):
    """**모의는 계좌로 실제 주문이 나갑니다.**

    승인 표지는 파일에 함께 남으므로, 중지로 세우면 앱을 껐다 켠 것만으로
    「재개」 한 번에 다시 주문이 나갈 수 있습니다. 껐다 켠 뒤의 장부는 비어
    있어 이어 갈 수 있는 값도 아닙니다. 그래서 계좌와 한 번 맞춰 본 뒤
    끝냅니다(`service.reconcile`).
    """
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")
    저장소.save([_실행(state=runs.HOLDING, mode=runs.SIM, approved_at=1_700_000_000_000)])

    (읽은것,) = 저장소.read()

    assert (읽은것.state, 읽은것.restored) == (runs.RECONCILING, True)
    # 승인 표지는 그대로 둡니다 — 무엇을 승인했던 실행인지는 기록입니다.
    assert 읽은것.approved_at == 1_700_000_000_000


def test_되살린_모의_실행은_재개해도_돌지_않는다(tmp_path):
    """대사 중에는 「재개」가 없습니다 — 눌러도 상태가 안 바뀝니다."""
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")
    저장소.save([_실행(state=runs.ARMED, mode=runs.SIM, approved_at=1_700_000_000_000)])

    (읽은것,) = 저장소.read()

    assert 읽은것.move(runs.RESUME) == runs.RECONCILING


def test_되살린_표지는_파일에_안_담긴다(tmp_path):
    """앱이 뜰 때마다 새로 정해지는 값입니다 — 담아 두면 다음 판이 헷갈립니다."""
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행(state=runs.ARMED, restored=True)])

    (담긴줄,) = json.loads(길.read_text(encoding="utf-8"))["runs"]

    assert "restored" not in 담긴줄


def test_모드가_없는_옛_줄은_중지로_선다(tmp_path):
    """앞 판이 담은 줄에는 모드 칸이 없습니다 — 종이로 봅니다."""
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행(state=runs.HOLDING)])
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    담긴것["runs"][0].pop("mode")
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    (읽은것,) = runs.RunStore(길).read()

    assert 읽은것.state == runs.PAUSED


def test_망가진_줄은_건너뛰고_나머지는_읽는다(tmp_path, caplog):
    """**줄 하나 때문에 목록이 통째로 안 서면 안 됩니다.**

    JSON 은 멀쩡한데 줄 하나에 칸이 모자란 자리입니다 — 손으로 고친 파일이
    닿는 길입니다. 앞 판은 그 한 줄에 `TypeError` 로 터져 실행이 전부 사라진
    것처럼 보였습니다. 파일이 통째로 안 읽히는 길은 아래 시험이 봅니다.
    """
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행()])
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    # 필수 칸이 빠진 줄을 앞에 둡니다 — 뒤의 멀쩡한 줄까지 못 읽으면 안 됩니다.
    담긴것["runs"].insert(0, {"id": "망가진것", "market": "domestic"})
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    with caplog.at_level("WARNING", logger="backend.strategy.runs"):
        읽은것 = runs.RunStore(길).read()

    assert [one.id for one in 읽은것] == ["r1"]
    (남긴것,) = [one for one in caplog.records if one.name == "backend.strategy.runs"]
    글 = 남긴것.getMessage()
    assert "망가진것" in 글, "어느 줄인지 말해야 합니다."
    assert "목록에 서지 않고" in 글, "영향을 적어야 합니다."


def test_파일이_통째로_안_읽히면_기록에_남긴다(tmp_path, caplog):
    """**줄 하나보다 큰 길입니다.** 파일이 깨지면 실행이 전부 사라지는데,
    읽는 자리가 예외를 안 내고 옆으로 치운 뒤 빈 내용으로 답합니다 — 기록이
    없으면 사용자는 담아 둔 실행이 없어진 것만 봅니다.
    """
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행()])
    길.write_text('{"version": 1, "runs": [{"id":', encoding="utf-8")

    with caplog.at_level("WARNING", logger="backend.strategy.runs"):
        읽은것 = runs.RunStore(길).read()

    assert 읽은것 == []
    assert (tmp_path / "strategy-runs.json.broken").exists(), "옆에 남깁니다."
    (남긴것,) = [one for one in caplog.records if one.name == "backend.strategy.runs"]
    글 = 남긴것.getMessage()
    assert ".broken" in 글, "어디로 옮겼는지 말해야 합니다."
    assert "목록에 서지 않습니다" in 글, "영향을 적어야 합니다."


def test_파일이_없으면_아무_말도_안_한다(tmp_path, caplog):
    """아직 안 쓴 것과 못 읽은 것은 다릅니다 — 처음 켠 사람에게 경고가 서면 안 됩니다."""
    with caplog.at_level("WARNING", logger="backend.strategy.runs"):
        읽은것 = runs.RunStore(tmp_path / "없어요.json").read()

    assert 읽은것 == []
    assert [one for one in caplog.records if one.name == "backend.strategy.runs"] == []


def test_사전이_아닌_줄도_건너뛴다(tmp_path):
    """값이 통째로 다른 모양으로 온 자리입니다."""
    길 = tmp_path / "strategy-runs.json"
    길.write_text(
        json.dumps({"version": 1, "runs": ["줄이 아님", 3, None]}), encoding="utf-8"
    )

    assert runs.RunStore(길).read() == []


def test_장부는_안_담는다(tmp_path):
    """어느 구간의 성적인지 말할 수 없는 값을 남기지 않습니다."""
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")
    저장소.save([_실행()])

    담긴것 = 저장소.path.read_text(encoding="utf-8")

    for 아직 in ("realized", "trades", "position", "intents_today", "day_base"):
        assert 아직 not in 담긴것


def test_끝난_실행은_뒤로_밀려_먼저_버려진다(tmp_path):
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")
    실행들 = [_실행(id=f"r{at}", state=runs.ENDED) for at in range(runs.MAX_RECORDS)]
    실행들.append(_실행(id="살아있는것", state=runs.ARMED))

    저장소.save(실행들)

    읽은것 = 저장소.read()
    assert len(읽은것) == runs.MAX_RECORDS
    assert 읽은것[0].id == "살아있는것"


def test_넘어온_보유의_평가손익은_어제_몫이다():
    """아무것도 안 했는데 아침에 하루 한도가 차면 안 됩니다."""
    실행 = _실행()
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))
    실행.roll_day(1, 장부, 100.0)

    # 어제 110 까지 올라간 채로 날이 바뀝니다.
    실행.roll_day(2, 장부, 110.0)

    assert runs.day_profit(실행, 장부, 110.0) == 0.0, "오늘은 아직 번 것이 없습니다."
    assert runs.day_profit(실행, 장부, 112.0) == pytest.approx(2.0), "오늘 오른 만큼만."
    assert 장부.profit(110.0) == 10.0, "실행을 시작한 뒤의 누적은 그대로입니다."


def test_마지막_값을_모르면_기준에_평가손익을_안_넣는다():
    실행 = _실행()
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))

    실행.roll_day(1, 장부, None)

    assert 실행.day_base == 0.0


# ── 계약 하나에 드는 돈 ──────────────────────────────────


def test_선물은_계약당_개시증거금으로_센다():
    실행 = _실행(kind="futures", margin=59_816_850.0, multiplier=250_000.0)

    assert runs.per_contract(실행, BUY, 405.25) == 59_816_850.0
    assert runs.per_contract(실행, SELL, 405.25) == 59_816_850.0, "방향과 무관합니다."


def test_옵션_매수는_프리미엄_곱하기_승수다():
    """산 옵션에는 증거금이 걸리지 않고 프리미엄을 치르는 것이 전부입니다."""
    실행 = _실행(kind="option", margin=None, multiplier=250_000.0)

    assert runs.per_contract(실행, BUY, 3.5) == 875_000.0


def test_옵션_매도는_모른다():
    """거래소가 계산하는 값이라 앱이 셀 수 없습니다."""
    실행 = _실행(kind="option", margin=None, multiplier=250_000.0)

    assert runs.per_contract(실행, SELL, 3.5) is None


def test_옵션_매수도_값을_모르면_모른다():
    실행 = _실행(kind="option", margin=None, multiplier=250_000.0)

    assert runs.per_contract(실행, BUY, None) is None
    assert runs.per_contract(실행, BUY, 0.0) is None


def test_옵션_매수는_예산으로_재고_매도는_막힌다():
    """같은 전략이 방향에 따라 갈립니다."""
    장부 = _장부()
    물음 = {
        "open_entry": 0,
        "max_hold": 5,
        "add_while_open": False,
        "gap": False,
        "expiring": False,
        "last_price": 3.5,
        "signal": 3.5,
    }
    넉넉 = _실행(
        market="domestic", kind="option", margin=None, multiplier=250_000.0, margin_budget=1_000_000.0
    )
    빠듯 = _실행(
        market="domestic", kind="option", margin=None, multiplier=250_000.0, margin_budget=800_000.0
    )

    assert runs.entry_block(넉넉, 장부, side=BUY, **물음) is None
    assert runs.entry_block(빠듯, 장부, side=BUY, **물음) == runs.WHY_BUDGET
    assert runs.entry_block(넉넉, 장부, side=SELL, **물음) == runs.WHY_MARGIN_UNKNOWN


def test_담을_때_어느_앱이_썼는지_적는다(tmp_path):
    """저장본으로 도는 앱과 실제 서버에 붙는 앱이 같은 파일을 이어받지 않게 합니다."""
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행()])

    담긴것 = json.loads(길.read_text(encoding="utf-8"))

    assert 담긴것["origin"] == session.current_mode()


def test_다른_앱이_쓴_실행_파일은_안_세운다(tmp_path, caplog):
    """저장본으로 돌던 실행이 실제 서버 쪽 목록에 서면, 화면은 지금 무엇이
    도는지 잘못 말합니다."""
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행()])
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    담긴것["origin"] = "replay" if session.current_mode() == "live" else "live"
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    저장소 = runs.RunStore(길)
    with caplog.at_level("WARNING", logger="backend.strategy.runs"):
        읽은것 = 저장소.read()

    assert 읽은것 == []
    assert 저장소.state.payload["otherApp"] == 담긴것["origin"]
    (남긴것,) = [one for one in caplog.records if one.name == "backend.strategy.runs"]
    assert "다른 앱" in 남긴것.getMessage()


def test_표지가_없는_옛_파일은_그대로_읽는다(tmp_path):
    """앞 판이 담은 파일에는 이 칸이 없습니다 — 없다고 버리면 실행이 사라집니다."""
    길 = tmp_path / "strategy-runs.json"
    runs.RunStore(길).save([_실행()])
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    담긴것.pop("origin")
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    (읽은것,) = runs.RunStore(길).read()

    assert 읽은것.id == "r1"


# ── 연속 손실 한도 ───────────────────────────────────────


def _거래들(*손익: float) -> runs.Ledger:
    장부 = _장부()
    장부.trades.extend({"netPl": 값} for 값 in 손익)
    return 장부


def test_연속_손실은_끝에서부터_이어진_손실만_센다():
    실행 = _실행()

    assert runs.loss_streak(실행, _거래들()) == 0
    assert runs.loss_streak(실행, _거래들(-1.0, -2.0)) == 2
    assert runs.loss_streak(실행, _거래들(-1.0, 5.0, -2.0)) == 1, "이익이 끼면 다시 셉니다."
    assert runs.loss_streak(실행, _거래들(-1.0, -1.0, 5.0)) == 0


def test_손익이_0_인_거래는_연속을_끊는다():
    """잃지 않은 거래를 손실로 세면 본전 거래가 진입을 막는 쪽으로 셈해집니다."""
    assert runs.loss_streak(_실행(), _거래들(-1.0, 0.0)) == 0
    assert runs.loss_streak(_실행(), _거래들(-1.0, 0.0, -1.0)) == 1


def test_연속_손실_한도에_닿으면_진입만_막는다():
    장부 = _거래들(-1.0, -1.0)

    assert _막힘(_실행(), 장부, streak_limit=3) is None
    assert _막힘(_실행(), 장부, streak_limit=2) == runs.WHY_LOSS_STREAK
    assert _막힘(_실행(), 장부) is None, "한도를 안 주면 옛 동작 그대로입니다."
    assert _막힘(_실행(), 장부, streak_limit=0) is None


def test_연속_손실은_하루_손실_바로_뒤다():
    """둘 다 닿으면 하루 손실을 먼저 적고, 상태·공백은 그보다 먼저입니다."""
    장부 = _거래들(-1.0, -1.0)
    장부.realized = -500.0

    assert _막힘(_실행(daily_loss=100.0), 장부, streak_limit=1) == runs.WHY_DAILY_LOSS
    assert _막힘(_실행(state=runs.EXITING), 장부, streak_limit=1) == runs.WHY_STATE
    assert _막힘(_실행(), 장부, streak_limit=1, gap=True) == runs.WHY_GAP
    # 방향·수량 검사보다는 앞입니다.
    assert _막힘(_실행(), 장부, streak_limit=1, max_hold=0) == runs.WHY_LOSS_STREAK


def test_거래일이_바뀌면_연속_손실을_다시_센다():
    실행 = _실행()
    장부 = _거래들(-1.0, -1.0)
    실행.roll_day(1, 장부)

    assert runs.loss_streak(실행, 장부) == 0
    장부.trades.append({"netPl": -3.0})
    assert runs.loss_streak(실행, 장부) == 1, "그 날의 거래만 셉니다."


def test_실행_줄에_지금_연속_손실_수를_싣는다():
    줄 = runs.row_of(_실행(), _거래들(5.0, -1.0, -1.0), feed="live", feed_at=0)

    assert 줄["lossStreak"] == 2


def test_연속_손실_기준은_파일에_담지_않는다(tmp_path):
    """되살린 실행은 장부가 비어 섭니다. 옛 기준을 들고 오면 영영 못 셉니다."""
    assert "streak_base" not in runs._SAVED
    저장소 = runs.RunStore(tmp_path / "strategy-runs.json")
    저장소.save([_실행(streak_base=7)])

    (읽은것,) = 저장소.read()

    assert 읽은것.streak_base == 0
    assert runs.loss_streak(읽은것, _거래들(-1.0)) == 1


# ── 체결 한 건의 수수료 ─────────────────────────────────


def test_체결_수수료는_계약_수에_계약당_값을_곱한다():
    장부 = _장부(fee_per_contract=250.0)

    assert 장부.cost_of(3) == 750.0
    assert 장부.cost_of(0) == 0.0
    assert 장부.cost_of(-2) == 0.0, "음수 수량은 셈하지 않습니다."
    assert _장부().cost_of(5) == 0.0


def test_뒤집는_체결의_수수료는_전부_닫히는_거래에_든다():
    """1계약 매수 보유에 3계약 매도 체결 — 닫힌 거래 수수료 = 진입 1 + 그 체결 3.

    새로 열린 매도 2계약 거래는 수수료 0 에서 시작합니다(장부 규칙 그대로).
    그래도 실행 누계는 체결 한 건마다의 수수료 합과 같습니다.
    """
    장부 = _장부(fee_per_contract=10.0)
    체결들 = [_체결(BUY, 1, 100.0, 1), _체결(SELL, 3, 101.0, 2), _체결(BUY, 2, 100.5, 3)]
    거래들 = [장부.add(one) for one in 체결들]

    닫힌것, 새것 = 거래들[1], 거래들[2]
    assert 닫힌것["fee"] == 40.0
    assert 새것["fee"] == 20.0, "새 거래는 뒤집은 체결의 수수료를 안 가집니다."
    assert 장부.fee == sum(장부.cost_of(one["quantity"]) for one in 체결들) == 60.0


# ── 해외 — 계약당 증거금 칸이 없는 시장 ─────────────────────────


def _해외(**덮어쓰기) -> runs.Run:
    made = {"market": "overseas", "session": "overseas", "code": "ESZ26", "kind": "futures"}
    made.update(덮어쓰기)
    return _실행(**made)


def test_해외_선물은_증거금을_몰라도_예산으로_막지_않는다():
    for kind in ("futures", "spread"):
        실행 = _해외(kind=kind, margin=None, margin_budget=1.0)
        assert runs.budget_unchecked(실행)
        assert _막힘(실행, _장부()) is None


def test_해외도_다른_검사는_그대로_한다():
    장부 = _장부()
    장부.add(_체결(BUY, 1, 100.0))
    실행 = _해외(margin=None, margin_budget=1.0)
    물음 = {"side": BUY, "add_while_open": True, "max_hold": 1}

    assert _막힘(실행, 장부, **물음) == runs.WHY_MAX_HOLD
    assert _막힘(실행, _장부(), gap=True) == runs.WHY_GAP


def test_해외도_계약당_값이_생기면_예산을_잰다():
    작음 = _해외(margin=2_500_000.0, margin_budget=1_000_000.0)

    assert not runs.budget_unchecked(작음)
    assert _막힘(작음, _장부()) == runs.WHY_BUDGET


def test_해외_옵션은_매수는_재고_매도는_예산_검사_없이_연다():
    장부 = _장부()
    물음 = {
        "open_entry": 0,
        "max_hold": 5,
        "add_while_open": False,
        "gap": False,
        "expiring": False,
        "last_price": 3.5,
        "signal": 3.5,
    }
    빠듯 = _해외(kind="option", margin=None, multiplier=250_000.0, margin_budget=800_000.0)
    넉넉 = _해외(kind="option", margin=None, multiplier=250_000.0, margin_budget=1_000_000.0)

    assert not runs.budget_unchecked(빠듯)
    assert runs.entry_block(빠듯, 장부, side=BUY, **물음) == runs.WHY_BUDGET
    assert runs.entry_block(넉넉, 장부, side=SELL, **물음) is None, "해외 옵션 매도는 계약당 값을 알 길이 없어 엽니다."


def test_예산_검사를_건너뛰는지_줄에_적는다():
    def 표지(실행):
        return runs.row_of(실행, _장부(), feed="live", feed_at=0)["budgetUnchecked"]

    assert 표지(_해외(margin=None, margin_budget=1_000_000.0)) is True
    # 예산이 없으면 건너뛸 검사도 없습니다.
    assert 표지(_해외(margin=None, margin_budget=None)) is False
    assert 표지(_해외(kind="option", margin=None, margin_budget=1_000_000.0)) is False
    assert 표지(_실행(market="domestic", margin=None, margin_budget=1_000_000.0)) is False

