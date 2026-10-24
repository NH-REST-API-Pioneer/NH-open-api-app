"""계좌 실행의 청산 주문이 싣는 체결조건.

국내 신규주문은 체결조건(`exec_cnd_cd`)이 꼭 있어야 합니다 — 비어 있으면 서버가
「필수 필드 값이 비어져있습니다」(ETR023)로 거부합니다. 시장가 전량 청산(손절·익절·
추적·세션 끝·사용자 청산)은 국내면 늘 FAS 로 냅니다. 설정의 체결조건은 진입과
청산 규칙에만 씁니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 주문 함수를 가짜로 바꿔 끼우고 보낸
몸만 견줍니다. 가짜는 서버처럼 빈 체결조건을 거부합니다.
"""
from __future__ import annotations

import pytest

from backend.domestic_futureoption import domestic_account
from backend.domestic_futureoption import domestic_futureoption_functions as domestic_api
from backend.nh_api.errors import BusinessError
from backend.overseas_futureoption import overseas_futureoption_functions as overseas_api
from backend.strategy import engine, paper, runs, sim
from tests.test_strategy_engine import _설정

주간 = "domestic-day"
시장가 = next(code for code, name in domestic_account.ORDER_TYPE.items() if name == "시장가")


@pytest.fixture
def 국내몸(monkeypatch):
    """국내 주문 함수가 받은 몸(거부된 것 포함). 체결조건이 비면 서버처럼 거부합니다."""
    몸들: list[dict] = []

    def 국내주문(sym, **몸):
        # 거부되는 부름도 적습니다 — 「아예 안 불렀는가」를 잴 수 있게.
        몸들.append({"sym": sym, **몸})
        if not str(몸.get("exec_cnd_cd") or "").strip():
            raise BusinessError(
                "domestic_order", "ETR023", "필수 필드 값이 비어져있습니다.: exec_cnd_cd", body={}
            )
        return {"ord_no": "0000000777"}

    monkeypatch.setattr(domestic_api, "order", 국내주문)
    return 몸들


def _국내실행(**aux) -> runs.Run:
    return runs.Run(
        id="r1", version_id="v1", code="A016C000", session=주간, market="domestic",
        state=runs.ARMED, qty=1, cash=1e8, multiplier=250000.0, draft=_설정(**aux),
        mode=runs.SIM, approved_at=1_000, environment="paper",
    )


def _엔진(run: runs.Run) -> engine.RunEngine:
    made = engine.RunEngine(
        run, tick=0.05, book=sim.SimBroker(run, sender=sim.NhSender(), environment=lambda: "paper")
    )
    made.book.last_price = 100.0
    return made


def _보유(엔진: engine.RunEngine) -> None:
    """매수 1계약을 들고 있는 장부."""
    엔진._take([{"orderId": "in", "side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1}], 1)
    엔진.run.state = runs.HOLDING


@pytest.mark.parametrize(
    "까닭",
    [engine.STOP_LOSS, engine.TAKE_PROFIT, engine.TRAIL_STOP, engine.SESSION_END, engine.FLATTEN],
)
def test_국내_시장가_전량_청산은_FAS_로_낸다(국내몸, 까닭):
    엔진 = _엔진(_국내실행(fillCond="FOK"))  # 설정이 FOK 여도 전량 청산은 FAS 입니다.
    _보유(엔진)

    엔진._close(1, 99.0, 까닭, 10)

    (몸,) = 국내몸
    assert 몸["exec_cnd_cd"] == "1", "FAS"
    assert 몸["ord_tp_cd"] == 시장가 and 몸["ord_qty"] == "1"
    assert 엔진.book.orders[-1].fill_condition == engine.EXIT_FILL_CONDITION == "FAS"
    assert 엔진.run.state == runs.EXITING


def test_청산_규칙과_진입은_설정의_체결조건을_싣는다(국내몸):
    엔진 = _엔진(_국내실행(fillCond="FOK", orderType="시장가"))

    엔진._send(paper.BUY, 1, 100.0, "entry", 10)
    엔진._take([{"orderId": 엔진.book.orders[-1].id, "side": paper.BUY, "quantity": 1, "price": 100.0, "time": 11}], 11)
    엔진.run.state = runs.HOLDING
    엔진._close(1, 99.0, engine.RULE_EXIT, 12)

    assert [몸["exec_cnd_cd"] for 몸 in 국내몸] == ["2", "2"], "FOK"


def test_해외_청산에는_체결조건이_없다(monkeypatch):
    몸들: list[dict] = []
    monkeypatch.setattr(overseas_api, "order", lambda sym, **몸: 몸들.append(몸) or {"ord_no": "0000012345"})
    run = runs.Run(
        id="r1", version_id="v1", code="6AZ26", session="overseas", market="overseas",
        state=runs.ARMED, qty=1, cash=1.0, multiplier=100000.0, draft=_설정(),
        mode=runs.SIM, approved_at=1_000, environment="paper", currency="USD",
    )
    엔진 = engine.RunEngine(run, tick=0.0001, book=sim.SimBroker(run, sender=sim.NhSender(), environment=lambda: "paper"))
    엔진.book.last_price = 0.65
    _보유(엔진)

    엔진._close(1, 0.64, engine.STOP_LOSS, 10)

    (몸,) = 몸들
    assert not any("cnd" in 이름 for 이름 in 몸), "해외 주문에는 체결조건 칸이 없습니다."
    assert 엔진.book.orders[-1].fill_condition == ""


def test_선택_전략_청산이_빈_체결조건으로_거부되지_않는다(국내몸, tmp_path):
    """실측에서 「선택 전략 청산」이 ETR023 으로 거부되던 순서입니다. 국내 모의 실행·보유 1 → 청산."""
    from tests.test_strategy_service import _모의목록, _모의물음

    실행목록 = _모의목록(tmp_path, sender=sim.NhSender())
    실행목록.add(**_모의물음())
    엔진 = 실행목록._engine("run1")
    assert 엔진.run.state == runs.ARMED
    엔진.book.last_price = 400.0
    _보유(엔진)

    실행목록.flatten("run1", 20)

    (몸,) = 국내몸
    assert 몸["exec_cnd_cd"] == "1"
    assert 엔진.run.state == runs.EXITING, "확인 필요로 내려앉지 않습니다."


# ── 시작 검사: 국내 실행의 빈 체결조건 ─────────────────────
#
# 국내 주문은 체결조건이 꼭 있어야 합니다. 저장은 빈 칸을 받아 줍니다. 계좌 실행도
# 종이 실행도 같은 설정으로 같은 결과를 내야 하므로, 국내 실행은 시작할 때 막습니다.


def _물음_빈_체결조건(**덮어쓰기):
    from tests.test_strategy_service import _설정 as _서비스설정, _모의물음

    설정 = _서비스설정()
    설정["aux"]["fillCond"] = ""
    return _모의물음(draft=설정, **덮어쓰기)


def test_국내_계좌_실행은_체결조건이_비면_시작하지_않는다(tmp_path):
    from backend.strategy import service as service_lib, validate
    from tests.test_strategy_service import _모의목록

    실행목록 = _모의목록(tmp_path)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음_빈_체결조건())

    줄들 = [one for one in 터짐.value.problems if one["field"] == "aux.fillCond"]
    assert [one["message"] for one in 줄들] == [validate.FILL_COND_WHY]


def test_국내_종이_실행도_체결조건이_비면_계좌와_같은_말로_시작하지_않는다(tmp_path):
    from backend.strategy import service as service_lib, validate
    from tests.test_strategy_service import _모의목록

    실행목록 = _모의목록(tmp_path)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음_빈_체결조건(mode=runs.PAPER, approved_at=0, environment=""))

    줄들 = [one for one in 터짐.value.problems if one["field"] == "aux.fillCond"]
    assert [one["message"] for one in 줄들] == [validate.FILL_COND_WHY]
    assert 실행목록.rows() == []


def test_해외_계좌_실행은_체결조건_칸을_보지_않는다(tmp_path):
    from tests.test_strategy_service import _모의목록

    실행목록 = _모의목록(tmp_path)
    설정 = _설정()
    설정["aux"]["fillCond"] = ""

    found = 실행목록.start_problems(
        draft=설정, market="overseas", code="6AZ26", session="overseas", qty=1, cash=1.0,
        fee_per_contract=0.0, mode=runs.SIM, environment="paper",
    )

    assert "aux.fillCond" not in [one["field"] for one in found]
