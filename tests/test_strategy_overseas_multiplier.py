"""해외 종목의 승수 — 마스터의 틱값 ÷ 호가단위.

**서버에 닿지 않습니다.** 마스터 줄은 손으로 지은 것입니다(실물 MESZ26 과 같은 값).
"""
from __future__ import annotations

import pytest

from backend.strategy import journal as journal_lib, paper, runs
from backend.strategy import service as service_lib
from tests.test_strategy_engine import _설정

#: 실물 마스터의 MESZ26 줄에서 쓰는 칸(계약크기 칸은 해외 줄에 없습니다).
_MES = {"tsiz": "0.25", "tval": "1.25", "ExchName": "CME", "kind": "futures"}


class _마스터:
    def __init__(self, row):
        self.row = row

    def locate(self, market, code):
        return dict(self.row) if market == "overseas" and code == "MESZ26" else None


def _목록(tmp_path, row) -> service_lib.RunService:
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(row),
        hours=type("H", (), {"cached": lambda self, m: {"products": []}})(),
        fetch=lambda run, minutes, count: [],
        judged=lambda *a: {"source": "unknown"},
    )


@pytest.mark.parametrize(
    ("row", "승수"),
    [
        (_MES, 5.0),  # 1.25 ÷ 0.25
        ({**_MES, "ctrt_size": "50"}, 50.0),  # 계약크기가 있으면 그것이 먼저
        ({"tsiz": "0.0001", "tval": "12.5"}, 125_000.0),  # 6E 형
        ({"tsiz": "0.015625", "tval": "15.625"}, 1_000.0),  # 분수 틱(1/64)
        ({"tsiz": "0.1", "tval": "0.3"}, 3.0),  # 부동소수로 나누면 2.9999999999999996
    ],
)
def test_해외_승수는_틱값을_호가단위로_나눈_값이다(row, 승수):
    assert service_lib.overseas_multiplier(row) == 승수, "찌꺼기 없는 값입니다."


@pytest.mark.parametrize("row", [{"tsiz": "0.25"}, {"tval": "1.25"}, {"tsiz": "0", "tval": "1.25"}, {}])
def test_셀_수_없으면_모름이다(row, tmp_path):
    assert service_lib.overseas_multiplier(row) is None
    사실 = _목록(tmp_path, {**row, "ExchName": "CME"}).instrument("overseas", "MESZ26")
    assert 사실["multiplier"] is None and 사실["why"] == service_lib.WHY_NO_MULTIPLIER


def test_그_승수로_선_실행의_손익은_포인트당_5달러다(tmp_path):
    목록 = _목록(tmp_path, _MES)
    줄 = 목록.add(
        run_id="r1", version_id="v1", draft=_설정(session="해외 CME", fillCond=""), market="overseas",
        code="MESZ26", session="overseas", qty=1, cash=1.0,
    )
    엔진 = 목록._engine("r1")

    assert 줄["multiplier"] == 5.0 and 엔진.run.multiplier == 5.0
    엔진._take([{"orderId": "a", "side": paper.BUY, "quantity": 1, "price": 7764.5, "time": 1}], 1)
    엔진._take([{"orderId": "b", "side": paper.SELL, "quantity": 1, "price": 7766.5, "time": 2}], 2)
    assert 엔진.fills[-1]["realized"] == pytest.approx(10.0), "2포인트 × 5달러"


def test_국내_승수는_그대로다(tmp_path):
    from tests.test_strategy_service import _마스터 as 국내마스터, _시간표

    목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=국내마스터(),
        hours=_시간표([]),
        fetch=lambda run, minutes, count: [],
    )

    assert 목록.instrument("domestic", "A7569000")["multiplier"] == 250_000.0


# ── 승수를 모를 때 — 1 로 세우지 않습니다 ─────────────────────────


_모름 = {"tsiz": "0.25", "ExchName": "CME", "kind": "futures"}  # tval 없음


def _세우기(목록, **덮어쓰기):
    물음 = {
        "run_id": "r1", "version_id": "v1", "draft": _설정(session="해외 CME", fillCond=""),
        "market": "overseas", "code": "MESZ26", "session": "overseas", "qty": 1, "cash": 1.0,
    }
    물음.update(덮어쓰기)
    return 목록.add(**물음)


def test_승수를_모르면_계좌_실행은_세우지_않는다(tmp_path):
    목록 = _목록(tmp_path, _모름)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        _세우기(목록, mode=runs.SIM, approved_at=1, environment="paper")
    assert runs.WHY_MULTIPLIER_UNKNOWN in [one["message"] for one in 터짐.value.problems]


def test_승수를_모르는_종이_실행은_손익을_모름으로_낸다(tmp_path):
    목록 = _목록(tmp_path, _모름)
    줄 = _세우기(목록)
    엔진 = 목록._engine("r1")

    assert 엔진.run.multiplier is None and 줄["multiplier"] is None
    assert 줄["multiplierWhy"] == runs.WHY_MULTIPLIER_UNKNOWN
    엔진._take([{"orderId": "a", "side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1}], 1)
    엔진._take([{"orderId": "b", "side": paper.SELL, "quantity": 1, "price": 102.0, "time": 2}], 2)
    줄 = 목록.rows()[0]
    assert (줄["pl"], 줄["dayPl"], 줄["realizedPl"], 줄["openPl"]) == (None, None, None, None)
    assert 엔진.fills[-1]["realized"] is None, "1 로 센 값을 돈인 척 내지 않습니다."
    (거래,) = 목록.journal.read(run_id="r1", kind="trade")
    assert 거래["grossPl"] is None and 거래["netPl"] is None


def test_승수를_모르는_실행은_하루_손실_한도와_계좌_한도에서_빠진다(tmp_path):
    목록 = _목록(tmp_path, _모름)
    _세우기(목록, draft=_설정(session="해외 CME", fillCond="", dailyLoss="1"))
    엔진 = 목록._engine("r1")
    엔진.ledger.realized = -1_000.0

    assert runs.entry_block(
        엔진.run, 엔진.ledger, side=paper.BUY, open_entry=0, max_hold=5, add_while_open=True,
        gap=False, expiring=False, last_price=100.0,
    ) is None
    assert 목록.account_loss({"USD": 1.0}, 10) == []


def test_분석은_손익을_모르는_거래를_합계에서_뺀다():
    from backend.strategy import records
    from tests.test_strategy_records import _거래, _때, _조건

    아는것 = _거래(_때(10, 10), run="a", net=100.0)
    모름 = {**_거래(_때(11, 10), run="b"), "grossPl": None, "netPl": None}

    묶음 = records.dataset([아는것, 모름], _조건())

    assert [one["net"] for one in 묶음["trades"]] == [100.0, None]
    assert sum(one["curve"][-1] for one in 묶음["strategies"]) == 100.0


def test_지난_봉_셈은_승수를_모르면_400_이다(tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.strategy.strategy_routes import get_master, get_service

    목록 = _목록(tmp_path, _모름)
    app.dependency_overrides[get_service] = lambda: 목록
    app.dependency_overrides[get_master] = lambda: type(
        "M", (), {"index": lambda self: None, "product_of": lambda self, m, c: None}
    )()
    try:
        답 = TestClient(app).post("/api/strategy/backtest", json={
            "version": {"id": "v1", "market": "overseas", "productCode": "MES", "productKind": "futures"},
            "draft": _설정(session="해외 CME", fillCond=""), "code": "MESZ26", "session": "overseas",
        })
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_master, None)

    assert 답.status_code == 400, 답.text
    assert runs.WHY_MULTIPLIER_UNKNOWN in [one["message"] for one in 답.json()["detail"]["problems"]]


def test_담겨_있던_해외_실행은_담긴_승수_그대로_선다(tmp_path):
    """되살린 실행은 다시 셈하지 않습니다 — 이 판 전에 선 실행은 승수 1 로 남습니다."""
    runs.RunStore(tmp_path / "runs.json").save([
        runs.Run(id="r1", version_id="v1", code="MESZ26", session="overseas", market="overseas",
                 state=runs.PAUSED, draft=_설정(session="해외 CME"), multiplier=1.0)
    ])

    목록 = _목록(tmp_path, _MES)

    assert 목록._engine("r1").run.multiplier == 1.0


def test_지난_봉_셈의_승수_모름_막음은_해외만이다(monkeypatch):
    """국내는 승수가 비면 1 로 셉니다."""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.strategy import backtest
    from backend.strategy.strategy_routes import get_master, get_service
    from tests.test_strategy_backtest import _가짜목록, _몸, _마스터 as 백테스트마스터

    class 승수없음(_가짜목록):
        def instrument(self, market, code, session=""):
            return {**super().instrument(market, code, session), "multiplier": None}

    받음: dict = {}
    원래 = backtest.compute
    monkeypatch.setattr(backtest, "compute", lambda **물음: 받음.update(물음) or 원래(**물음))
    app.dependency_overrides[get_service] = lambda: 승수없음()
    app.dependency_overrides[get_master] = 백테스트마스터
    try:
        답 = TestClient(app).post("/api/strategy/backtest", json=_몸())
    finally:
        app.dependency_overrides.pop(get_service, None)
        app.dependency_overrides.pop(get_master, None)

    assert 답.status_code == 200, 답.text
    assert 받음["multiplier"] == 1.0
