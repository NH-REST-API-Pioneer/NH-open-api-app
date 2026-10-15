"""전략 실행의 계좌 갈래 — 모의 계좌(`sim`)와 실전 계좌(`real`).

**계좌에 한 건도 안 보냅니다.** 보내는 자리·계좌 조회·활성 환경을 가짜로 끼우고
그 사이의 우리 코드를 다 지나갑니다. 실제 계좌로 부르는 길은 시험 내내 막혀
있습니다(`conftest._전략은_시험에서_계좌로_못_나간다`).
"""
from __future__ import annotations

import pytest

from backend.nh_api import runtime
from backend.strategy import engine as engine_lib
from backend.strategy import journal as journal_lib
from backend.strategy import paper, records, runs, sim
from backend.strategy import service as service_lib
from tests.test_strategy_service import _계좌, _마스터, _물음, _시간표

주간 = "domestic-day"


class _보내는곳:
    """주문을 받아 적기만 하는 자리. 계좌에 닿지 않습니다."""

    def __init__(self, order_no: str = "0000012345", fails: Exception | None = None, reply=None):
        self.order_no = order_no
        self.fails = fails
        self.reply = reply
        self.sent: list[dict] = []
        self.cancelled: list[str] = []

    def order(self, **물음):
        if self.fails is not None:
            raise self.fails
        self.sent.append(물음)
        return self.reply if self.reply is not None else {"id": self.order_no}

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": order.order_no}


def _실행(**덮어쓰기) -> runs.Run:
    made = {
        "id": "r1",
        "version_id": "v1",
        "code": "A016C000",
        "session": 주간,
        "market": "domestic",
        "mode": runs.REAL,
        "environment": "real",
        "approved_at": 1_000,
        "qty": 1,
    }
    made.update(덮어쓰기)
    return runs.Run(**made)


def _장부(run, sender, active):
    return sim.SimBroker(run, sender=sender, environment=lambda: active)


def _내기(장부):
    return 장부.place("o1", side=paper.BUY, quantity=1, order_type="지정가", price=405.25, at=5_000)


# ── 보내기 전 검사 넷 × 두 환경 ─────────────────────────────


@pytest.mark.parametrize(("mode", "environment"), [(runs.SIM, "paper"), (runs.REAL, "real")])
def test_환경이_맞고_승인이_있으면_한_건을_보낸다(mode, environment):
    보낸곳 = _보내는곳()
    실행 = _실행(mode=mode, environment=environment)

    _내기(_장부(실행, 보낸곳, environment))

    assert len(보낸곳.sent) == 1
    assert 보낸곳.sent[0]["run"].environment == environment


@pytest.mark.parametrize(("mode", "environment", "other"), [(runs.SIM, "paper", "real"), (runs.REAL, "real", "paper")])
def test_실행의_환경과_활성_환경이_다르면_한_건도_안_낸다(mode, environment, other):
    보낸곳 = _보내는곳()

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(_장부(_실행(mode=mode, environment=environment), 보낸곳, other))

    assert str(터짐.value) == runs.why_environment(environment, other)
    assert 터짐.value.flag is True, "「확인 필요」로 갑니다."
    assert 보낸곳.sent == []


@pytest.mark.parametrize(("mode", "environment"), [(runs.SIM, "paper"), (runs.REAL, "real")])
def test_환경을_바꾸는_중이면_한_건도_안_낸다(monkeypatch, mode, environment):
    from backend import orders

    보낸곳 = _보내는곳()
    monkeypatch.setattr(runtime, "switching", lambda: True)

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(_장부(_실행(mode=mode, environment=environment), 보낸곳, environment))

    assert str(터짐.value) == orders.SWITCHING
    assert 보낸곳.sent == []


@pytest.mark.parametrize(("mode", "environment"), [(runs.SIM, "paper"), (runs.REAL, "real")])
@pytest.mark.parametrize("모름", ["", None])
def test_활성_환경을_못_읽으면_한_건도_안_낸다(mode, environment, 모름):
    from backend import orders

    보낸곳 = _보내는곳()

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(_장부(_실행(mode=mode, environment=environment), 보낸곳, 모름))

    assert str(터짐.value) == orders.UNKNOWN_ENVIRONMENT
    assert 보낸곳.sent == []


@pytest.mark.parametrize(("mode", "environment"), [(runs.SIM, "paper"), (runs.REAL, "real")])
def test_승인이_없으면_한_건도_안_낸다(mode, environment):
    보낸곳 = _보내는곳()

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(_장부(_실행(mode=mode, environment=environment, approved_at=0), 보낸곳, environment))

    assert str(터짐.value) == runs.WHY_NOT_APPROVED
    assert 보낸곳.sent == []


def test_선_환경이_빈_계좌_실행은_안_낸다():
    """환경 칸이 비었다는 것은 어디서 섰는지 모른다는 뜻입니다."""
    보낸곳 = _보내는곳()

    with pytest.raises(sim.SimRefused):
        _내기(_장부(_실행(environment=""), 보낸곳, "real"))

    assert 보낸곳.sent == []


# ── 보낸 뒤 실패 ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("보낸곳", "까닭"),
    [
        (_보내는곳(fails=RuntimeError("업무 거부 99999")), sim.WHY_NO_REPLY),
        (_보내는곳(fails=TimeoutError("답 없음")), sim.WHY_NO_REPLY),
        (_보내는곳(fails=ConnectionError("끊김")), sim.WHY_NO_REPLY),
        (_보내는곳(reply={"id": ""}), sim.WHY_NO_ORDER_NO),
    ],
    ids=["오류_코드", "답_없음", "끊김", "주문번호_없음"],
)
def test_실전_실행도_보낸_뒤_실패는_다시_안_보내고_확인을_청한다(보낸곳, 까닭):
    장부 = _장부(_실행(), 보낸곳, "real")

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(장부)

    assert str(터짐.value).startswith(까닭)
    assert 터짐.value.flag is True
    assert 장부.orders == [], "나갔는지 모르는 주문은 장부에 올리지 않고, 다시 보내지도 않습니다."


# ── 부를 때는 실행의 환경을 적습니다 ────────────────────────


class _거래함수:
    """국내 거래 함수 자리. 받은 인자를 적고 정해 둔 답을 줍니다."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def order(self, sym, **물음):
        self.calls.append(("order", 물음))
        return {"ord_no": "0000000077"}

    def cancel(self, sym, **물음):
        self.calls.append(("cancel", 물음))
        return {"ord_no": "0000000078"}

    def order_history(self, **물음):
        self.calls.append(("order_history", 물음))
        return {"Occurs1": []}

    def open_interest(self, **물음):
        self.calls.append(("open_interest", 물음))
        return {"Occurs1": []}


@pytest.fixture
def 거래함수(monkeypatch):
    from backend.domestic_futureoption import domestic_futureoption_functions as api

    가짜 = _거래함수()
    for 이름 in ("order", "cancel", "order_history", "open_interest"):
        monkeypatch.setattr(api, 이름, getattr(가짜, 이름))
    return 가짜


@pytest.mark.parametrize("environment", ["paper", "real"])
def test_주문과_취소는_실행의_환경으로_부른다(거래함수, environment):
    실행 = _실행(mode=runs.SIM if environment == "paper" else runs.REAL, environment=environment)
    보내는것 = sim.NhSender()

    답 = 보내는것.order(
        run=실행, side=paper.BUY, quantity=1, order_type="지정가", price=405.25,
        stop_price=None, fill_condition="", tick=0.05,
    )
    보내는것.cancel(run=실행, order=sim.SimOrder(id="o1", side=paper.BUY, quantity=1, order_type="지정가", order_no="77"))

    assert [(이름, 물음["environment"]) for 이름, 물음 in 거래함수.calls] == [
        ("order", environment),
        ("cancel", environment),
    ]
    assert 답["environment"] == environment


def test_검사_뒤에_활성_환경이_바뀌어도_실행의_환경으로_나간다(거래함수):
    """검사와 전송 사이에 환경이 바뀌는 순간에도 다른 계좌로 새지 않습니다."""
    활성 = {"값": "real"}

    class _바꾸는보내는곳(sim.NhSender):
        def order(self, **물음):
            활성["값"] = "paper"  # 검사를 지난 바로 뒤에 바뀝니다.
            return super().order(**물음)

    장부 = sim.SimBroker(_실행(), sender=_바꾸는보내는곳(), environment=lambda: 활성["값"], tick=0.05)

    _내기(장부)

    assert [물음["environment"] for 이름, 물음 in 거래함수.calls if 이름 == "order"] == ["real"]


def test_계좌_대사도_실행의_환경으로_묻는다(거래함수):
    service_lib._fetch_account(_실행())

    assert sorted((이름, 물음["environment"]) for 이름, 물음 in 거래함수.calls) == [
        ("open_interest", "real"),
        ("order_history", "real"),
    ]


def test_선_환경을_모르면_계좌로_부르지_않는다(거래함수):
    with pytest.raises(ValueError):
        sim.NhSender().order(
            run=_실행(environment=""), side=paper.BUY, quantity=1, order_type="지정가",
            price=405.25, stop_price=None, fill_condition="", tick=0.05,
        )
    assert 거래함수.calls == []


# ── 세울 때 셋이 같아야 합니다 ───────────────────────────────


def _목록(tmp_path, *, active, sender=None):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표([{"productCode": "01", "tick": "0.05", "contractInitialMargin": "2500000"}]),
        fetch=lambda run, minutes, count: [],
        account=_계좌(),
        sender=sender if sender is not None else _보내는곳(),
        environment=lambda: active,
    )


def _실전물음(**덮어쓰기):
    made = dict(_물음())
    made.update({"mode": runs.REAL, "approved_at": 1_000, "environment": "real"})
    made.update(덮어쓰기)
    return made


def test_실전에서_실전_실행이_선다(tmp_path):
    실행목록 = _목록(tmp_path, active="real")

    줄 = 실행목록.add(**_실전물음())

    assert 줄["mode"] == runs.REAL and 줄["environment"] == "real"
    assert 줄["approvedAt"] == 1_000
    assert 줄["model"] == sim.MODEL, "실전 실행은 종이 장부로 돌지 않습니다."
    엔진 = 실행목록._engine("run1")
    assert isinstance(엔진.book, sim.SimBroker)
    assert 엔진.virtual is False


@pytest.mark.parametrize(
    ("mode", "active", "claimed", "field"),
    [
        (runs.REAL, "paper", "paper", "mode"),  # 활성이 모의
        (runs.REAL, "real", "paper", "environment"),  # 화면이 옛 환경을 들고 있음
        (runs.SIM, "paper", "real", "environment"),
        (runs.SIM, "real", "real", "mode"),
        (runs.REAL, "", "real", "environment"),  # 활성 환경을 못 읽음
    ],
)
def test_세_값이_하나라도_다르면_실행이_안_선다(tmp_path, mode, active, claimed, field):
    실행목록 = _목록(tmp_path, active=active)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_실전물음(mode=mode, environment=claimed))

    assert field in [one["field"] for one in 터짐.value.problems]
    assert 실행목록.engines() == []


def test_환경을_바꾸는_중이면_실행이_안_선다(tmp_path, monkeypatch):
    from backend import orders

    monkeypatch.setattr(runtime, "switching", lambda: True)
    실행목록 = _목록(tmp_path, active="real")

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_실전물음())

    assert orders.SWITCHING in [one["message"] for one in 터짐.value.problems]
    assert 실행목록.engines() == []


def test_종이_실행은_환경을_안_본다(tmp_path):
    실행목록 = _목록(tmp_path, active="")

    줄 = 실행목록.add(**_물음())

    assert 줄["mode"] == runs.PAPER and 줄["environment"] is None


@pytest.mark.parametrize(
    ("active", "switching", "modes"),
    [("paper", False, ["sim"]), ("real", False, ["real"]), ("", False, []), ("real", True, [])],
)
def test_세울_수_있는_계좌_갈래를_답한다(tmp_path, monkeypatch, active, switching, modes):
    monkeypatch.setattr(runtime, "switching", lambda: switching)

    답 = _목록(tmp_path, active=active).account_state()

    assert 답 == {"accountModes": modes, "activeEnvironment": active or None}


# ── 다시 켤 때 ──────────────────────────────────────────────


def test_되살린_실전_실행은_대사로_서고_대사_뒤_끝나_재개로_주문이_안_나간다(tmp_path):
    """승인 표지만 남은 채 중지로 서면 「재개」 한 번에 다시 실전 주문이 나갑니다."""
    담는것 = runs.RunStore(tmp_path / "runs.json")
    담는것.save([_실행(id="도는것", state=runs.ARMED, draft={})])
    보낸곳 = _보내는곳()
    실행목록 = service_lib.RunService(
        store=담는것,
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        account=_계좌(),
        sender=보낸곳,
        environment=lambda: "real",
    )

    실행목록.load()
    assert 실행목록.reconcile_wanted() == ["도는것"]
    assert 실행목록._engine("도는것").run.environment == "real"

    실행목록.reconcile("도는것", 2_000)

    assert 실행목록._engine("도는것").run.state == runs.ENDED
    실행목록.resume("도는것", 3_000)
    assert 실행목록._engine("도는것").run.state == runs.ENDED, "끝난 실행은 재개로 안 돌아옵니다."
    assert 보낸곳.sent == []


def test_환경_칸이_없는_옛_모의_실행은_모의로_읽는다(tmp_path):
    import json

    길 = tmp_path / "runs.json"
    runs.RunStore(길).save([_실행(mode=runs.SIM, environment="paper", state=runs.ENDED)])
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    for one in 담긴것["runs"]:
        one.pop("environment")
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    (읽은것,) = runs.RunStore(길).read()

    assert (읽은것.mode, 읽은것.environment) == (runs.SIM, "paper")


# ── 같은 계좌만 맞춰 봅니다 ─────────────────────────────────


def test_대사는_같은_환경의_실행만_센다(tmp_path):
    """모의와 실전은 다른 계좌입니다 — 섞어 세면 멀쩡한 실행이 「어긋남」이 됩니다."""
    실행목록 = _목록(tmp_path, active="real")
    실행목록.add(**_실전물음())
    엔진 = 실행목록._engine("run1")
    모의 = engine_lib.RunEngine(_실행(id="모의", mode=runs.SIM, environment="paper", code="A7569000"), tick=0.05)
    모의.ledger.add({"side": paper.BUY, "quantity": 2, "price": 400.0, "time": 1})
    실행목록._engines["모의"] = 모의

    assert 실행목록._compare(엔진, 5_000) == []


# ── 기록 ────────────────────────────────────────────────────


def test_실전_기록은_모의와_섞이지_않는다(tmp_path):
    기록 = journal_lib.Journal(tmp_path / "trades.jsonl")
    for mode, environment in ((runs.SIM, "paper"), (runs.REAL, "real")):
        기록.write(
            "trade",
            _실행(id=mode, mode=mode, environment=environment),
            {"closedAt": 1_790_000_000_000, "netPl": 10.0, "grossPl": 12.0, "fee": 2.0},
        )
    줄들 = 기록.read(kind="trade")
    assert sorted(one["record"] for one in 줄들) == ["real", "sim"]

    def 고른것(record):
        ask = records.query_of(record=record, market="domestic", start="2026-09-01", end="2026-09-30")
        return [one["runId"] for one in records.picked(줄들, ask)]

    assert 고른것("real") == ["real"]
    assert 고른것("sim") == ["sim"]
    assert records.KIND_LABELS["real"] == "실전 계좌 거래"


# ── 구조로 막기 ──────────────────────────────────────────────


def test_시험에서는_호출부_없이_실서버로_못_부른다():
    """가짜를 끼우는 것을 잊은 시험 하나가 실제 계좌로 주문을 내지 않게 합니다."""
    from backend.nh_api.session import create_session, replay_config

    runtime.use(create_session(replay=False, config=replay_config()))
    try:
        with pytest.raises(AssertionError, match="실서버"):
            sim.NhSender().order(
                run=_실행(environment="paper", mode=runs.SIM), side=paper.BUY, quantity=1,
                order_type="지정가", price=405.25, stop_price=None, fill_condition="", tick=0.05,
            )
    finally:
        runtime.reset()
    assert sim.environment_now() == "", "시험의 활성 환경은 모름입니다."


# ── 계좌 손실 한도 ───────────────────────────────────────────


def test_실전_손실은_실전_한도로만_멈춘다(tmp_path):
    from backend.strategy import limits

    실행목록 = _목록(tmp_path, active="real")
    실행목록.add(**_실전물음())
    엔진 = 실행목록._engine("run1")
    엔진.run.state = runs.ARMED
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    엔진.ledger.add({"side": paper.SELL, "quantity": 1, "price": 90.0, "time": 2})

    assert 실행목록.account_loss({"domestic": 1.0}, 10) == [], "모의 쪽 한도는 실전 실행을 안 셉니다."
    assert 실행목록.account_loss({"domestic": 1.0}, 10, environment=limits.REAL) == ["run1"]


# ── 라우트 ──────────────────────────────────────────────────


@pytest.mark.parametrize(("claimed", "status"), [("real", 200), ("paper", 400)])
def test_라우트가_화면이_믿는_환경을_받아_견준다(tmp_path, claimed, status):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.strategy.strategy_routes import get_service
    from tests.test_strategy_service import _더하기

    실행목록 = _목록(tmp_path, active="real")
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        앱 = TestClient(app)
        답 = 앱.post(
            "/api/strategy/runs",
            json={**_더하기(), "mode": "real", "approved": True, "environment": claimed},
        )
        목록 = 앱.get("/api/strategy/runs").json()
    finally:
        app.dependency_overrides.pop(get_service, None)

    assert 답.status_code == status
    assert (목록["accountModes"], 목록["activeEnvironment"]) == (["real"], "real")
    assert "paperOnly" not in 목록, "갈래는 accountModes 로 읽습니다."
    if status == 200:
        assert 답.json()["environment"] == "real" and 답.json()["mode"] == "real"
    else:
        assert 목록["runs"] == []
