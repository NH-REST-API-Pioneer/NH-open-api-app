"""검증 실행 — 기록 파일·실행 목록·라우트.

**사용자 홈을 건드리지 않습니다** — 임시 폴더를 쓰는 저장소와 기록을 따로 만들어
씁니다. 마스터와 시간표도 지어낸 것을 끼웁니다(실호출 없음).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.domestic_futureoption import domestic_hours
from backend.strategy import engine as engine_lib
from backend.strategy import journal as journal_lib
from backend.strategy import paper, runs, service as service_lib, validate as validate_lib
from backend.strategy.strategy_routes import get_service

주소 = "/api/strategy/runs"


class _마스터:
    """종목 한 줄만 아는 마스터. 실호출도 파일도 없습니다."""

    def __init__(self, row=None):
        self.row = row if row is not None else {
            "rem_cnt": "5",
            "ctrt_size": "250000",
            # **열쇠는 `trd_code` 입니다** — `product_code` 는 `KOSPI` 처럼 생긴
            # 다른 코드라 품목별세부정보의 두 자리 품목코드와 안 맞습니다.
            "trd_code": "01",
            "product_code": "KOSPI",
            "kind": "futures",
        }

    def locate(self, market, code):
        return dict(self.row) if code == "A7569000" else None


class _시간표:
    def __init__(self, products=None):
        self.products = products or []

    def cached(self, market):
        return {"products": self.products}


def _설정(**aux) -> dict:
    묶음 = {
        "orderType": "시장가",
        "priceBasis": "신호가",
        "stopBasis": "",
        "fillCond": "FAS",
        "stopTicks": "2",
        "takeTicks": "3",
        "perOrder": "1",
        "maxHold": "5",
        "session": "국내 주간",
        "addWhileOpen": False,
        "dailyLoss": "300000",
        "marginBudget": "10000000",
    }
    묶음.update(aux)
    return {
        "memo": "",
        "baseBar": "5분봉",
        "evalMode": "마감",
        "rules": {
            "buyEntry": {
                "on": True,
                "steps": [
                    {
                        "id": "s1",
                        "join": "all",
                        "withinBars": 0,
                        "conds": [
                            {
                                "id": "c1",
                                "left": "close",
                                "op": "gt",
                                "rightKind": "number",
                                "right": "100",
                            }
                        ],
                    }
                ],
            },
            "sellEntry": {"on": False, "steps": []},
            "buyExit": {"on": False, "steps": []},
            "sellExit": {"on": False, "steps": []},
        },
        "aux": 묶음,
    }


def _더하기(**덮어쓰기) -> dict:
    made = {
        "id": "run1",
        "versionId": "v1",
        "draft": _설정(),
        "market": "domestic",
        "code": "A7569000",
        "session": "domestic-day",
        "qty": 1,
        "cash": 10_000_000.0,
        "feePerContract": 2_000.0,
    }
    made.update(덮어쓰기)
    return made


def _물음(**덮어쓰기) -> dict:
    """`RunService.add` 가 받는 이름. 라우트가 본문 이름을 이렇게 옮깁니다."""
    본문 = _더하기(**덮어쓰기)
    return {
        "run_id": 본문.pop("id"),
        "version_id": 본문.pop("versionId"),
        "fee_per_contract": 본문.pop("feePerContract"),
        **본문,
    }


@pytest.fixture
def 실행목록(tmp_path):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "strategy-runs.json"),
        journal=journal_lib.Journal(tmp_path / "strategy-trades.jsonl"),
        master=_마스터(),
        hours=_시간표(
            [
                {
                    "productCode": "01",
                    "kind": "futures",
                    "session": "day",
                    "tick": "0.05",
                    "contractInitialMargin": "2500000",
                }
            ]
        ),
    )


@pytest.fixture
def 손님(실행목록):
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        yield TestClient(app), 실행목록
    finally:
        app.dependency_overrides.pop(get_service, None)


# ── 기록 파일 ────────────────────────────────────────────


def test_기록은_덧붙이기만_한다(tmp_path):
    """통째로 다시 쓰지 않으므로 쓰다 멈춰도 앞의 기록이 다치지 않습니다."""
    기록 = journal_lib.Journal(tmp_path / "strategy-trades.jsonl")
    실행 = runs.Run(id="r1", version_id="v1", code="A7569000", session="domestic-day",
                   market="domestic")

    기록.write(journal_lib.FILL, 실행, {"price": 400.0, "quantity": 1})
    기록.write(journal_lib.TRADE, 실행, {"netPl": 1000.0})

    줄들 = 기록.path.read_text(encoding="utf-8").splitlines()
    assert len(줄들) == 2
    첫줄 = json.loads(줄들[0])
    assert 첫줄["kind"] == journal_lib.FILL
    assert (첫줄["runId"], 첫줄["versionId"], 첫줄["code"]) == ("r1", "v1", "A7569000")
    assert 첫줄["record"] == journal_lib.PAPER, "종이거래로 지어낸 값이라는 표지입니다."


def test_반쪽_줄_하나가_앞의_기록을_못_읽게_하지_않는다(tmp_path):
    기록 = journal_lib.Journal(tmp_path / "strategy-trades.jsonl")
    실행 = runs.Run(id="r1", version_id="v1", code="A", session="s", market="domestic")
    기록.write(journal_lib.FILL, 실행, {"price": 1.0})
    with 기록.path.open("a", encoding="utf-8") as file:
        file.write('{"kind": "fill", "pri')

    읽은것 = 기록.read()

    assert [one["price"] for one in 읽은것] == [1.0]


def test_갈래와_실행으로_골라_읽는다(tmp_path):
    기록 = journal_lib.Journal(tmp_path / "strategy-trades.jsonl")
    하나 = runs.Run(id="r1", version_id="v1", code="A", session="s", market="domestic")
    둘 = runs.Run(id="r2", version_id="v1", code="A", session="s", market="domestic")
    기록.write(journal_lib.FILL, 하나, {"price": 1.0})
    기록.write(journal_lib.TRADE, 하나, {"netPl": 2.0})
    기록.write(journal_lib.FILL, 둘, {"price": 3.0})

    assert len(기록.read(run_id="r1")) == 2
    assert len(기록.read(kind=journal_lib.FILL)) == 2
    assert len(기록.read(run_id="r1", kind=journal_lib.TRADE)) == 1


def test_파일이_커지면_한_대만_남긴다(tmp_path):
    """지워 주는 사람이 없어 디스크가 차지 않는 편이 먼저입니다."""
    기록 = journal_lib.Journal(tmp_path / "strategy-trades.jsonl", max_bytes=1)
    실행 = runs.Run(id="r1", version_id="v1", code="A", session="s", market="domestic")

    기록.write(journal_lib.FILL, 실행, {"price": 1.0})
    기록.write(journal_lib.FILL, 실행, {"price": 2.0})

    assert [one["price"] for one in 기록.read()] == [2.0]
    assert 기록.path.with_suffix(".jsonl.old").exists()


# ── 실행 목록 ────────────────────────────────────────────


def test_실행을_세우면_종목_값을_물고_온다(실행목록):
    줄 = 실행목록.add(**_물음())

    assert 줄["state"] == runs.ARMED
    assert 줄["feed"] == service_lib.IDLE, "아직 시세를 안 물렸습니다."
    assert 줄["tickSize"] == 0.05 and 줄["margin"] == 2_500_000.0
    assert 줄["daysLeft"] == 5 and 줄["expiring"] is False
    assert 줄["model"] == paper.MODEL and "paperOnly" not in 줄


def test_모형이_못_다루는_주문유형으로는_시작하지_않는다(실행목록):
    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(draft=_설정(orderType="조건부지정가")))

    assert str(터짐.value) == "조건부지정가는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요"


def test_켜진_진입_규칙이_없으면_시작하지_않는다(실행목록):
    """저장은 담아 주지만 시작은 돌 수 있는 설정만 받습니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["on"] = False

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(draft=설정))

    assert str(터짐.value) == validate_lib.NO_ENTRY_START


def test_적을_수_없는_값으로는_시작하지_않는다(실행목록):
    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(draft=_설정(stopTicks="0")))

    assert "손절" in str(터짐.value)


def test_여덟째_실행은_막는다(실행목록):
    """자리가 모자라면 이미 돌던 실행의 시세가 끊깁니다."""
    for at in range(runs.MAX_RUNS):
        실행목록.add(**_물음(id=f"run{at}"))

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(id="하나 더"))

    assert str(터짐.value) == runs.WHY_RUNS


def test_만기_당일이면_표지를_단다(tmp_path):
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터({"rem_cnt": "1", "ctrt_size": "250000", "trd_code": "01", "kind": "futures"}),
        hours=_시간표(),
    )

    줄 = 실행목록.add(**_물음())

    assert 줄["daysLeft"] == 1 and 줄["expiring"] is True


def test_보유가_있으면_끝내지_못한다(실행목록):
    실행목록.add(**_물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.ledger.add({"side": paper.BUY, "quantity": 1, "price": 400.0, "time": 1})

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.end("run1", 10)

    assert str(터짐.value) == service_lib.WHY_HOLDING


def test_청산하면_시장가_전량_의도가_나간다(실행목록):
    실행목록.add(**_물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.ledger.add({"side": paper.BUY, "quantity": 2, "price": 400.0, "time": 1})
    돌리는것.run.state = runs.HOLDING

    실행목록.flatten("run1", 10)

    (주문,) = 돌리는것.book.open_orders
    assert (주문.side, 주문.quantity, 주문.order_type) == (paper.SELL, 2, paper.MARKET_ORDER)
    assert 돌리는것.run.state == runs.EXITING


def test_닫을_보유가_없으면_청산하지_않는다(실행목록):
    실행목록.add(**_물음())

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.flatten("run1", 10)

    assert str(터짐.value) == service_lib.WHY_NOTHING


def test_중지는_진입_주문만_거둔다(실행목록):
    """나가 있는 청산까지 거두면 중지를 누른 순간 보유가 무방비가 됩니다."""
    실행목록.add(**_물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.book.place("들어가는것", side=paper.BUY, quantity=1, order_type="지정가",
                     price=1.0, at=0)
    돌리는것.book.place("나오는것", side=paper.SELL, quantity=1, order_type="지정가",
                     price=9_999.0, at=0)
    돌리는것._purpose["들어가는것"] = "entry"
    돌리는것._purpose["나오는것"] = "exit"

    줄 = 실행목록.pause("run1", 10)

    assert 줄["state"] == runs.PAUSED
    assert [one.id for one in 돌리는것.book.open_orders] == ["나오는것"]


def test_청산_중_중지는_상태를_안_바꾸고_기억해_둔다(실행목록):
    """청산이 끝난 뒤에 듭니다 — 그 사이 진입으로 돌아가면 안 됩니다."""
    실행목록.add(**_물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.ledger.add({"side": paper.BUY, "quantity": 1, "price": 400.0, "time": 1})
    돌리는것.run.state = runs.HOLDING
    실행목록.flatten("run1", 10)
    assert 돌리는것.run.state == runs.EXITING

    줄 = 실행목록.pause("run1", 20)

    assert 줄["state"] == runs.EXITING, "나가 있는 청산을 거두지 않습니다."
    assert 돌리는것.run.pause_requested is True
    assert 돌리는것.book.open_orders, "청산 주문은 살아 있습니다."

    assert 돌리는것.run.move(runs.EXIT_FILLED) == runs.PAUSED


def test_청산은_버전_주문유형을_따르지_않는다(실행목록):
    """지정가로 걸면 값이 지나가 버려 들고 있는 채로 남습니다."""
    실행목록.add(**_물음(draft=_설정(orderType="지정가", priceBasis="신호가")))
    돌리는것 = 실행목록._engine("run1")
    돌리는것.ledger.add({"side": paper.BUY, "quantity": 2, "price": 400.0, "time": 1})
    돌리는것.run.state = runs.HOLDING

    실행목록.flatten("run1", 10)

    (주문,) = 돌리는것.book.open_orders
    assert 주문.order_type == paper.MARKET_ORDER and 주문.price is None
    assert 주문.quantity == 2, "전량입니다."


def test_끝난_실행만_지운다(실행목록):
    실행목록.add(**_물음())

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.delete("run1")
    assert str(터짐.value) == service_lib.WHY_NOT_ENDED

    실행목록.end("run1", 10)
    실행목록.delete("run1")
    assert 실행목록.rows() == []


def test_담아_둔_실행은_중지로_돌아온다(tmp_path):
    """꺼져 있던 동안 손절 감시가 없었습니다."""
    물음 = {
        "store": runs.RunStore(tmp_path / "runs.json"),
        "journal": journal_lib.Journal(tmp_path / "trades.jsonl"),
        "master": _마스터(),
        "hours": _시간표(),
    }
    service_lib.RunService(**물음).add(**_물음())

    다시 = service_lib.RunService(**물음)

    (줄,) = 다시.rows()
    assert 줄["state"] == runs.PAUSED


def test_전체_중지는_대상만_센다(실행목록):
    실행목록.add(**_물음(id="run1"))
    실행목록.add(**_물음(id="run2"))
    실행목록.pause("run2", 10)

    답 = 실행목록.stop_all(20)

    assert 답["paused"] == 1, "이미 중지한 것은 빼고 셉니다."
    assert [one["state"] for one in 답["runs"]] == [runs.PAUSED, runs.PAUSED]


def test_모르는_종목이면_값을_모른다고_한다(실행목록):
    """0 으로 답하면 「한 계약도 못 든다」가 됩니다."""
    아는것 = 실행목록.instrument("domestic", "A7569000")
    모르는것 = 실행목록.instrument("domestic", "없는종목")

    assert 아는것["margin"] == 2_500_000.0
    assert 모르는것["margin"] is None and 모르는것["tick"] is None
    assert 모르는것["why"] == service_lib.WHY_CODE, "왜 모르는지도 함께 냅니다."


# ── 라우트 ──────────────────────────────────────────────


def test_처음에는_돌고_있는_실행이_없다(손님):
    앱, _ = 손님

    답 = 앱.get(주소)

    assert 답.status_code == 200
    assert 답.json() == {
        "runs": [],
        "max": runs.MAX_RUNS,
        "accountModes": [],
        "activeEnvironment": None,
        "store": {"status": "missing", "stored": False, "movedTo": None, "otherApp": None},
    }


def test_세우고_보고_끝내고_지운다(손님):
    앱, _ = 손님

    세우기 = 앱.post(주소, json=_더하기())
    assert 세우기.status_code == 200 and 세우기.json()["id"] == "run1"

    한벌 = 앱.get(f"{주소}/run1").json()
    assert set(한벌) == {"run", "fills", "events", "curve", "trades", "openOrders", "conditions"}

    assert 앱.post(f"{주소}/run1/stop").json()["state"] == runs.PAUSED
    assert 앱.post(f"{주소}/run1/resume").json()["state"] == runs.ARMED
    assert 앱.post(f"{주소}/run1/end").json()["state"] == runs.ENDED
    assert 앱.delete(f"{주소}/run1").json()["runs"] == []


def test_없는_실행은_404_다(손님):
    앱, _ = 손님

    assert 앱.get(f"{주소}/없는것").status_code == 404
    assert 앱.post(f"{주소}/없는것/stop").status_code == 404


def test_시작할_수_없는_설정은_400_이다(손님):
    앱, _ = 손님

    답 = 앱.post(주소, json=_더하기(draft=_설정(orderType="최유리지정가")))

    assert 답.status_code == 400
    속 = 답.json()["detail"]
    assert 속["message"] == service_lib.NOT_STARTED
    assert [one["field"] for one in 속["problems"]] == ["aux.orderType"]
    assert 속["problems"][0]["message"] == "최유리지정가는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요"


def test_전체_중지_라우트(손님):
    앱, _ = 손님
    앱.post(주소, json=_더하기())

    답 = 앱.post("/api/strategy/stop-all")

    assert 답.json()["paused"] == 1
    assert 답.json()["runs"][0]["state"] == runs.PAUSED


def test_전체_중지는_고른_갈래만_멈춘다(tmp_path):
    """검증 탭 단추는 종이 실행만 멈춥니다 — 계좌 실행은 그대로 돕니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_물음(id="paper1"))
    실행목록.add(**_모의물음(run_id="sim1"))

    답 = 실행목록.stop_all(20, ["paper"])

    assert 답["paused"] == 1 and 답["pausedIds"] == ["paper1"]
    assert 답["modes"] == ["paper"], "적용한 갈래를 되돌립니다."
    assert 실행목록._engine("sim1").run.state == runs.ARMED


def test_전체_중지는_갈래를_안_주면_전부다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_물음(id="paper1"))
    실행목록.add(**_모의물음(run_id="sim1"))

    답 = 실행목록.stop_all(20)

    assert sorted(답["pausedIds"]) == ["paper1", "sim1"] and 답["paused"] == 2
    assert 답["modes"] == ["paper", "sim", "real"], "안 주면 전 갈래입니다."


def test_전체_중지_라우트는_모르는_갈래를_400_으로_막는다(손님):
    앱, 실행목록 = 손님
    앱.post(주소, json=_더하기())

    for 몸 in ({"modes": ["종이"]}, {"modes": []}):
        답 = 앱.post("/api/strategy/stop-all", json=몸)
        assert 답.status_code == 400
        assert [one["field"] for one in 답.json()["detail"]["problems"]] == ["modes"]
    assert 실행목록._engine("run1").run.state == runs.ARMED, "막힌 요청은 아무것도 안 멈춥니다."
    골라 = 앱.post("/api/strategy/stop-all", json={"modes": ["paper"]}).json()
    assert 골라["pausedIds"] == ["run1"] and 골라["modes"] == ["paper"]
    assert 앱.post("/api/strategy/stop-all").json()["modes"] == ["paper", "sim", "real"], "몸이 없어도 됩니다."


def test_실행을_세우면_기록에_한_줄_남는다(손님):
    앱, 실행목록 = 손님

    앱.post(주소, json=_더하기())

    남은것 = 실행목록.journal.read(run_id="run1")
    assert {one["kind"] for one in 남은것} == {journal_lib.EVENT}
    assert all(one["record"] == journal_lib.PAPER for one in 남은것)
    말들 = " ".join(one.get("text", "") for one in 남은것)
    assert "검증 실행을 세웠습니다" in 말들
    assert "준비 봉" in 말들, "몇 개를 받았는지도 기록에 남습니다."


def test_만기일에는_신규_진입을_막는다(tmp_path):
    """자동 롤오버가 없어, 만기 당일에 들어가면 나올 자리가 없습니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터({"rem_cnt": "1", "ctrt_size": "250000", "trd_code": "01", "kind": "futures"}),
        hours=_시간표(),
    )
    실행목록.add(**_물음())

    돌리는것 = 실행목록._engine("run1")

    assert 돌리는것.expiring is True
    막힘 = runs.entry_block(
        돌리는것.run,
        돌리는것.ledger,
        side=paper.BUY,
        open_entry=0,
        max_hold=5,
        add_while_open=False,
        gap=False,
        expiring=돌리는것.expiring,
        last_price=100.0,
    )
    assert 막힘 == runs.WHY_EXPIRY


def test_계좌_손실_한도는_그_시장을_통째로_멈춘다(실행목록):
    """한 전략이 낸 손실이 아니라 계좌가 진 손실입니다."""
    실행목록.add(**_물음(id="run1"))
    실행목록.add(**_물음(id="run2"))
    하나 = 실행목록._engine("run1")
    하나.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    하나.ledger.add({"side": paper.SELL, "quantity": 1, "price": 90.0, "time": 2})

    assert 하나.ledger.realized < 0, "그 실행이 손실을 냈습니다."
    멈춘것 = 실행목록.account_loss({"domestic": 1.0}, 10)

    assert 멈춘것 == ["run1", "run2"], "손실을 안 낸 실행까지 멈춥니다."
    assert [one["state"] for one in 실행목록.rows()] == [runs.PAUSED, runs.PAUSED]
    assert any(
        service_lib.WHY_ACCOUNT_LOSS in one["text"] for one in 실행목록._engine("run2").events
    )


def test_계좌_손실_한도_줄은_코드를_싣는다(실행목록, tmp_path):
    """화면은 글이 아니라 코드(`reason`)로 이 줄을 가립니다. 이미 중지한 실행에는 안 답니다."""
    실행목록.add(**_물음(id="run1"))
    실행목록.add(**_물음(id="run2"))
    실행목록.add(**_물음(id="run3"))
    실행목록.pause("run3", 5)
    하나 = 실행목록._engine("run1")
    하나.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    하나.ledger.add({"side": paper.SELL, "quantity": 1, "price": 90.0, "time": 2})

    assert 실행목록.account_loss({"domestic": 1.0}, 10) == ["run1", "run2"]

    for run_id in ("run1", "run2"):
        사건 = 실행목록._engine(run_id).events
        줄들 = [one for one in 사건 if one["text"] == service_lib.WHY_ACCOUNT_LOSS]
        assert [(one["kind"], one["reason"]) for one in 줄들] == [
            (engine_lib.STATE, service_lib.ACCOUNT_LOSS_REASON)
        ]
        assert "why" not in 줄들[0]
    셋째 = 실행목록._engine("run3").events
    assert not [one for one in 셋째 if one.get("reason") == service_lib.ACCOUNT_LOSS_REASON], (
        "이미 중지한 실행에는 줄이 없습니다."
    )
    막힘코드 = set(engine_lib.BLOCK_REASONS.values()) | {engine_lib.OTHER_REASON}
    assert service_lib.ACCOUNT_LOSS_REASON not in 막힘코드

    기록 = [
        json.loads(line)
        for line in (tmp_path / "strategy-trades.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    남은줄 = [one for one in 기록 if one.get("text") == service_lib.WHY_ACCOUNT_LOSS]
    assert [(one["runId"], one["reason"]) for one in 남은줄] == [
        ("run1", service_lib.ACCOUNT_LOSS_REASON),
        ("run2", service_lib.ACCOUNT_LOSS_REASON),
    ], "기록 파일의 줄에도 코드가 실립니다."


def test_코드를_실은_사건의_글은_그대로다():
    """화면에 보이는 글은 바뀌지 않습니다. 코드는 글 옆 칸에 따로 실립니다."""
    assert service_lib.WHY_ACCOUNT_LOSS == "계좌 손실 한도에 닿아 이 시장의 전략을 모두 중지했습니다"
    assert service_lib.RECONCILE_RESUME == "재접속 뒤 대사 일치 — 감시를 이어 갑니다"
    assert service_lib.RECONCILE_KEPT_PAUSED == "재접속 뒤 대사 일치 — 중지 상태 그대로입니다"
    assert (
        service_lib.ACCOUNT_LOSS_REASON,
        service_lib.RECONCILE_RESUME_REASON,
        service_lib.RECONCILE_KEPT_PAUSED_REASON,
    ) == ("account-loss", "reconcile-resume", "reconcile-kept-paused")


def test_한도에_못_미치면_안_멈춘다(실행목록):
    실행목록.add(**_물음())

    assert 실행목록.account_loss({"domestic": 1_000_000.0}, 10) == []
    assert 실행목록.rows()[0]["state"] == runs.ARMED


def test_시장마다_한도를_따로_본다(실행목록):
    """국내는 원, 해외는 달러라 두 시장의 손익을 더하면 뜻이 없는 수가 나옵니다."""
    실행목록.add(**_물음())
    하나 = 실행목록._engine("run1")
    하나.ledger.add({"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1})
    하나.ledger.add({"side": paper.SELL, "quantity": 1, "price": 90.0, "time": 2})

    assert 실행목록.account_loss({"overseas": 1.0}, 10) == [], "다른 시장 한도입니다."
    assert 실행목록.account_loss({"domestic": 0}, 10) == [], "한도 0 은 안 건 것입니다."


def test_실행을_세우면_바로_앞을_채운다(실행목록):
    """준비 봉이 없으면 첫 신호까지 몇 시간을 기다리게 됩니다."""
    받은것 = []
    실행목록._fetch = lambda run, minutes, count: 받은것.append((run.id, minutes, count)) or []

    실행목록.add(**_물음())

    assert [one[0] for one in 받은것] == ["run1"]
    assert 받은것[0][1] == 5, "5분봉 실행입니다."
    assert 받은것[0][2] >= 2, "지표가 설 만큼 청합니다."


def test_받아_온_준비_봉이_바로_들어간다(실행목록):
    실행목록._fetch = lambda run, minutes, count: [
        {"timestamp": 1_000 + at * 60_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        for at in range(3)
    ]

    실행목록.add(**_물음())

    assert len(실행목록._engine("run1").bars.bars) == 3


def test_받아_오지_못해도_실행은_선다(실행목록):
    """봉이 모자란 것은 엔진이 「준비 중」으로 다룹니다."""
    def 터짐(run, minutes, count):
        raise RuntimeError("통신 실패")

    실행목록._fetch = 터짐

    줄 = 실행목록.add(**_물음())

    assert 줄["state"] == runs.ARMED
    assert 실행목록._engine("run1").bars.bars == []


def test_루프와_라우트가_같은_엔진에_함께_들어와도_어긋나지_않는다(실행목록):
    """시세는 이벤트 루프가, 중지·청산은 라우트 스레드가 부릅니다."""
    import threading

    실행목록.add(**_물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.ledger.add({"side": paper.BUY, "quantity": 1, "price": 400.0, "time": 1})
    돌리는것.run.state = runs.HOLDING

    def 시세():
        for step in range(200):
            때 = 1_000 + step * 60_000
            돌리는것.on_trade(
                {"timestamp": 때, "price": 400.0, "quantity": 1}, "domestic-day", at=때
            )

    흐르는것 = threading.Thread(target=시세)
    흐르는것.start()
    try:
        for _ in range(10):
            실행목록.pause("run1", 10)
            실행목록.resume("run1", 10)
    finally:
        흐르는것.join(timeout=10)

    assert 돌리는것.run.state in (runs.ARMED, runs.HOLDING, runs.EXITING, runs.PAUSED)
    assert len(돌리는것.bars.sessions) == len(돌리는것.bars.bars), "봉과 맥락이 한 벌입니다."


# ── 시작할 때 보는 값 ────────────────────────────────────


@pytest.mark.parametrize(
    ("칸", "덮어쓰기", "문구"),
    [
        ("qty", {"qty": 99}, service_lib.WHY_QTY),
        ("qty", {"qty": 0}, service_lib.WHY_QTY),
        ("cash", {"cash": 0}, service_lib.WHY_CASH),
        ("feePerContract", {"feePerContract": -5}, service_lib.WHY_FEE),
        ("code", {"code": "없는종목"}, service_lib.WHY_CODE),
        ("session", {"session": "해외 CME"}, service_lib.WHY_SESSION),
        ("session", {"session": "overseas"}, service_lib.WHY_SESSION),
    ],
)
def test_시작할_수_없는_값은_칸을_짚어_막는다(실행목록, 칸, 덮어쓰기, 문구):
    """저장과 같은 모양으로 냅니다 — 화면이 두 자리를 한 갈래로 읽습니다."""
    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(**덮어쓰기))

    (하나,) = [one for one in 터짐.value.problems if one["field"] == 칸]
    assert 하나["message"] == 문구
    assert 하나["severity"] == "error"
    assert 실행목록.rows() == [], "아무것도 안 세웁니다."


def test_최대_보유까지는_받는다(실행목록):
    """`_설정()` 의 최대 보유가 5 입니다."""
    줄 = 실행목록.add(**_물음(qty=5))

    assert 줄["qty"] == 5


def test_국내_실행에_해외_창을_못_붙인다(실행목록):
    """시장이 정하는 창이 아니면 구독을 걸 자리가 없습니다."""
    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(session="overseas"))

    assert [one["field"] for one in 터짐.value.problems] == ["session"]


def test_막을_것이_여럿이면_다_냅니다(실행목록):
    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(qty=0, cash=0, feePerContract=-1))

    assert {one["field"] for one in 터짐.value.problems} == {"qty", "cash", "feePerContract"}


def test_시작_검사는_저장_검사보다_좁다(실행목록):
    """저장은 「담되 안 돈다」를 받아 주지만 시작은 돌 수 있는 것만 받습니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["on"] = False

    찾은것 = 실행목록.start_problems(
        draft=설정,
        market="domestic",
        code="A7569000",
        session="domestic-day",
        qty=1,
        cash=1.0,
        fee_per_contract=0.0,
    )

    assert [one["field"] for one in 찾은것] == ["rules"]
    assert 찾은것[0]["message"] == validate_lib.NO_ENTRY_START


def test_한_벌의_줄이_목록_줄과_같은_칸이다(손님):
    """화면이 두 답을 같은 줄로 씁니다."""
    앱, _ = 손님
    앱.post(주소, json=_더하기())

    목록 = 앱.get(주소).json()["runs"][0]
    한벌 = 앱.get(f"{주소}/run1").json()["run"]

    assert set(한벌) == set(목록)
    for 칸 in ("tickSize", "multiplier", "daysLeft", "expiring", "warmup", "sessionLabel"):
        assert 칸 in 한벌, f"{칸} 이 상세에서 빠집니다"


# ── 준비 봉을 실제로 받아 오는 길 ─────────────────────────


def test_준비_봉을_받아_오는_길이_실제로_돈다(monkeypatch, tmp_path):
    """시험이 늘 가짜를 끼워 넣어 이 자리가 한 번도 안 돌았습니다.

    바꿔 끼우지 않고 **`_fetch_bars` 를 그대로** 부르되, NH선물에 나가는 자리만
    막습니다 — 그 사이의 우리 코드는 다 지나갑니다.
    """
    from backend.domestic_futureoption import domestic_futureoption_functions as 국내
    from backend.strategy import service as 그자리

    부른것 = {}

    def _가짜조회(sym, **물음):
        부른것.update({"sym": sym, **물음})
        return {
            "Occurs1": [
                {
                    "occurs1_ref_dt": "20260917",
                    "occurs1_exch_tm": "100000",
                    "occurs1_open_pric": "400.0",
                    "occurs1_high_pric": "401.0",
                    "occurs1_low_pric": "399.0",
                    "occurs1_close_pric": "400.5",
                    "occurs1_cum_trd_qty": "12",
                }
            ]
        }

    monkeypatch.setattr(국내, "chart_minute", _가짜조회)
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
    )
    assert 실행목록._fetch is 그자리._fetch_bars, "가짜를 안 끼웠습니다."

    줄 = 실행목록.add(**_물음())

    assert 부른것["sym"] == "A7569000"
    assert 부른것["minutes"] == "5", "5분봉 실행입니다."
    assert 부른것["night"] is False, "주간 창입니다."
    assert 줄["bars"] == 1


def test_야간_실행은_야간_봉을_청한다(monkeypatch, tmp_path):
    from backend.domestic_futureoption import domestic_futureoption_functions as 국내

    부른것 = {}
    monkeypatch.setattr(
        국내, "chart_minute", lambda sym, **물음: 부른것.update(물음) or {"Occurs1": []}
    )
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
    )

    실행목록.add(**_물음(session="국내 야간"))

    assert 부른것["night"] is True


def test_받은_것이_없으면_그것도_적어_둔다(tmp_path):
    """봉이 0 개일 때 「빈 답」과 「부르다 막힌 것」을 가릴 수 있어야 합니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음())

    말들 = [one["text"] for one in 실행목록._engine("run1").events]

    assert "준비 봉 조회 0줄 — 새 봉 0개(지금 0개)" in 말들


# ── 준비 봉 줄: 받은 줄·새 봉·갱신·지금 든 봉 ─────────────────

_분 = 5 * 60_000


def _봉줄(*자리: int) -> list[dict]:
    return [{"timestamp": 하나 * _분, "close": 100.0 + 하나} for 하나 in 자리]


def _준비목록(tmp_path, 답들: list[list[dict]]):
    """부를 때마다 다음 답을 주는 조회. 계좌에도 NH선물에도 닿지 않습니다."""
    남은것 = list(답들)
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: 남은것.pop(0),
    )
    실행목록.add(**_물음())
    return 실행목록, 실행목록._engine("run1")


def _준비줄(엔진) -> list[str]:
    """준비 봉 조회의 줄만. 같은 갈래(`ready`)에 증거금 안내 같은 다른 줄도 섭니다."""
    return [
        one["text"]
        for one in 엔진.events
        if one["kind"] == engine_lib.READY and one["text"].startswith("준비 봉 조회")
    ]


def test_처음_받으면_갱신_없이_새_봉과_못_읽은_줄을_적는다(tmp_path):
    _, 엔진 = _준비목록(tmp_path, [_봉줄(1, 2, 3) + [{"timestamp": None, "close": 1.0}]])

    assert _준비줄(엔진) == ["준비 봉 조회 4줄 — 새 봉 3개(지금 3개), 못 읽은 줄 1"]


def test_다시_받아_전부_겹치면_새_봉_0개_갱신으로_적는다(tmp_path):
    실행목록, 엔진 = _준비목록(tmp_path, [_봉줄(1, 2, 3), _봉줄(1, 2, 3)])

    assert 실행목록.refill("run1", 9_000) == 0

    assert _준비줄(엔진)[-1] == "준비 봉 조회 3줄 — 새 봉 0개, 갱신 3개(지금 3개)"


def test_다시_받아_일부만_새로우면_나눠_적는다(tmp_path):
    실행목록, 엔진 = _준비목록(tmp_path, [_봉줄(1, 2, 3), _봉줄(2, 3, 4, 5)])

    assert 실행목록.refill("run1", 9_000) == 2

    assert _준비줄(엔진)[-1] == "준비 봉 조회 4줄 — 새 봉 2개, 갱신 2개(지금 5개)"


def test_상한에서_앞이_잘려도_새_봉을_센다(tmp_path):
    """든 봉 수는 그대로라 수의 차이는 0 이지만, 새 시각의 봉이 들어왔습니다."""
    실행목록, 엔진 = _준비목록(tmp_path, [_봉줄(1, 2, 3), _봉줄(2, 3, 4)])
    엔진.bars.limit = 3

    assert 실행목록.refill("run1", 9_000) == 0, "돌려주는 값(늘어난 수)은 그대로입니다."

    assert _준비줄(엔진)[-1] == "준비 봉 조회 3줄 — 새 봉 1개, 갱신 2개(지금 3개)"
    assert [one.timestamp for one in 엔진.bars.bars] == [2 * _분, 3 * _분, 4 * _분]


def test_부르다_막히면_까닭을_적어_둔다(tmp_path):
    def 터짐(run, minutes, count):
        raise RuntimeError("통신 실패")

    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=터짐,
    )
    실행목록.add(**_물음())

    말들 = [one["text"] for one in 실행목록._engine("run1").events]

    assert any(service_lib.WHY_NO_BARS in one and "RuntimeError" in one for one in 말들)


# ── 두 시장의 조회를 저장본으로 진짜 불러 보기 ─────────────


@pytest.fixture
def 재생자리(monkeypatch):
    """저장해 둔 응답으로 도는 접속 자리. **NH선물에 나가지 않습니다.**

    가짜 `fetch` 를 끼우면 시장마다 인자 이름이 다른 자리를 못 봅니다 —
    해외 조회는 `exch_cd` 를 **반드시** 받는데 국내 이름으로 부르면 그대로
    터집니다. 여기서는 우리 코드를 다 지나 저장본까지 갑니다.
    """
    from backend.nh_api import runtime
    from backend.nh_api.session import create_session

    monkeypatch.setenv("NH_REPLAY", "1")
    runtime.use(create_session(replay=True))
    try:
        yield
    finally:
        runtime.reset()


def _실물목록(tmp_path, master):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=master,
        hours=_시간표(),
    )


def test_국내_준비_봉을_저장본에서_받아_온다(재생자리, tmp_path):
    """1분봉 기록이 16줄 담겨 있습니다."""
    실행목록 = _실물목록(tmp_path, _마스터())
    설정 = _설정()
    설정["baseBar"] = "1분봉"

    줄 = 실행목록.add(**_물음(draft=설정))

    assert 줄["bars"] == 16
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert "준비 봉 조회 16줄 — 새 봉 16개(지금 16개)" in 말들


class _해외마스터:
    """해외 종목 한 줄. 거래소 이름이 조회에 그대로 실립니다."""

    def locate(self, market, code):
        if market != "overseas" or code != "MESU26":
            return None
        return {"ExchName": "FCME", "tsiz": "0.25", "ctrt_size": "5", "expiry_date": "20260918"}


def _해외물음(**덮어쓰기):
    설정 = _설정(session="해외 CME", fillCond="")
    설정["baseBar"] = "1분봉"
    made = {
        "run_id": "run1",
        "version_id": "v1",
        "draft": 설정,
        "market": "overseas",
        "code": "MESU26",
        "session": "overseas",
        "qty": 1,
        "cash": 10_000.0,
        "fee_per_contract": 0.0,
    }
    made.update(덮어쓰기)
    return made


def test_해외_준비_봉도_그_API_가_받는_인자로_부른다(재생자리, tmp_path):
    """해외는 `exch_cd` 를 반드시 받습니다 — 국내 이름으로 부르면 터집니다."""
    실행목록 = _실물목록(tmp_path, _해외마스터())

    줄 = 실행목록.add(**_해외물음())

    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert not [one for one in 말들 if service_lib.WHY_NO_BARS in one], 말들
    assert 줄["bars"] == 485, "저장본의 MESU26 1분봉이 485줄입니다."
    assert 실행목록._engine("run1").run.exchange == "FCME", "거래소가 조회까지 실려 갑니다."


def test_거래소를_모르면_부르지_않고_까닭을_적는다(재생자리, tmp_path):
    """그냥 부르면 `TypeError` 가 나고 그것은 왜 봉이 없는지를 안 알려 줍니다."""

    class _거래소없음:
        def locate(self, market, code):
            return {"tsiz": "0.25", "ctrt_size": "5"}

    실행목록 = _실물목록(tmp_path, _거래소없음())

    실행목록.add(**_해외물음())

    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    막힘 = [one for one in 말들 if service_lib.WHY_NO_BARS in one]
    assert 막힘 and "거래소를 몰라" in 막힘[0]
    assert "ValueError" in 막힘[0], "예외 종류도 함께 남습니다."


# ── 일봉 준비 봉 ─────────────────────────────────────────


def _일봉물음(**덮어쓰기):
    설정 = _설정()
    설정["baseBar"] = "일봉"
    made = dict(_물음(draft=설정))
    made.update(덮어쓰기)
    return made


def test_일봉_실행도_준비_봉을_받는다(monkeypatch, tmp_path):
    """이월이던 자리입니다 — 전에는 아무것도 안 하고 0 을 냈습니다."""
    from backend.domestic_futureoption import domestic_futureoption_functions as 국내

    부른것 = {}

    def _가짜조회(sym, **물음):
        부른것.update({"sym": sym, **물음})
        return {
            "Occurs1": [
                {
                    "occurs1_ref_dt": f"2026091{at}",
                    "occurs1_open_pric": "400.0",
                    "occurs1_high_pric": "401.0",
                    "occurs1_low_pric": "399.0",
                    "occurs1_close_pric": "400.5",
                    "occurs1_cum_trd_qty": "12",
                }
                for at in range(1, 4)
            ]
        }

    monkeypatch.setattr(국내, "chart_daily", _가짜조회)
    실행목록 = _실물목록(tmp_path, _마스터())

    줄 = 실행목록.add(**_일봉물음())

    assert 부른것["sym"] == "A7569000"
    assert set(부른것) == {"sym", "start_date", "end_date"}, "일봉에는 봉 길이 인자가 없습니다."
    assert 줄["bars"] == 3


def test_일봉_줄을_분봉으로_읽지_않는다(monkeypatch, tmp_path):
    """일봉 줄에는 시각 칸이 없어, 분봉으로 읽으면 **모든 줄이 버려집니다.**"""
    from backend.domestic_futureoption import domestic_futureoption_functions as 국내
    from backend.strategy import service as 그자리

    monkeypatch.setattr(
        국내,
        "chart_daily",
        lambda sym, **물음: {
            "Occurs1": [
                {
                    "occurs1_ref_dt": "20260917",
                    "occurs1_open_pric": "1",
                    "occurs1_high_pric": "1",
                    "occurs1_low_pric": "1",
                    "occurs1_close_pric": "1",
                    "occurs1_cum_trd_qty": "1",
                }
            ]
        },
    )
    실행 = runs.Run(
        id="r1",
        version_id="v1",
        code="A7569000",
        session="domestic-day",
        market="domestic",
    )

    받은것 = 그자리._fetch_daily(실행, 2)

    assert len(받은것) == 1, "시각 칸이 없어도 일봉은 읽힙니다."


def test_해외_일봉도_그_API_가_받는_인자로_부른다(재생자리, tmp_path):
    """저장본의 `MESU26` 일봉이 한 줄 담겨 있습니다."""
    실행목록 = _실물목록(tmp_path, _해외마스터())
    물음 = _해외물음()
    물음["draft"]["baseBar"] = "일봉"

    줄 = 실행목록.add(**물음)

    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert not [one for one in 말들 if service_lib.WHY_NO_BARS in one], 말들
    assert 줄["bars"] == 1


def test_거래소를_모르면_일봉도_안_부른다(재생자리, tmp_path):
    class _거래소없음:
        def locate(self, market, code):
            return {"tsiz": "0.25", "ctrt_size": "5"}

    실행목록 = _실물목록(tmp_path, _거래소없음())
    물음 = _해외물음()
    물음["draft"]["baseBar"] = "일봉"

    실행목록.add(**물음)

    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    막힘 = [one for one in 말들 if service_lib.WHY_NO_BARS in one]
    assert 막힘 and "해외 일봉" in 막힘[0] and "ValueError" in 막힘[0]


# ── 모의 계좌 실행 ───────────────────────────────────────


class _보내는곳:
    """주문을 받아 적기만 하는 자리. 계좌에 닿지 않습니다."""

    def __init__(self, order_no: str = "0000012345"):
        self.order_no = order_no
        self.sent: list[dict] = []
        self.cancelled: list[str] = []

    def order(self, **물음):
        self.sent.append(물음)
        return {"id": self.order_no}

    def cancel(self, *, run, order):
        self.cancelled.append(order.order_no)
        return {"id": order.order_no}


def _계좌(orders=None, positions=None):
    """대사가 읽는 계좌 두 벌. 안 주면 빈 계좌입니다."""
    return lambda run: {"orders": list(orders or []), "positions": list(positions or [])}


def _모의목록(tmp_path, *, environment="paper", sender=None, account=None):
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표([{"productCode": "01", "tick": "0.05", "contractInitialMargin": "2500000"}]),
        fetch=lambda run, minutes, count: [],
        account=account if account is not None else _계좌(),
        sender=sender if sender is not None else _보내는곳(),
        environment=lambda: environment,
    )


def _모의물음(**덮어쓰기):
    made = dict(_물음())
    made.update({"mode": runs.SIM, "approved_at": 1_000, "environment": "paper"})
    made.update(덮어쓰기)
    return made


def test_모의_실행은_모의_장부를_문다(tmp_path):
    """갈리는 자리를 한 곳에 모아 두어야 「어디서 계좌로 가나」를 한 줄로 답합니다."""
    from backend.strategy import sim

    실행목록 = _모의목록(tmp_path)

    줄 = 실행목록.add(**_모의물음())

    assert 줄["mode"] == runs.SIM and 줄["approvedAt"] == 1_000
    assert 줄["model"] == sim.MODEL
    assert isinstance(실행목록._engine("run1").book, sim.SimBroker)


def test_종이_실행은_계좌에_닿지_않는다(tmp_path):
    from backend.strategy import paper as paper_lib

    실행목록 = _모의목록(tmp_path)

    줄 = 실행목록.add(**_물음())

    assert 줄["mode"] == runs.PAPER and 줄["approvedAt"] is None
    assert isinstance(실행목록._engine("run1").book, paper_lib.PaperBook)


def test_모의_환경이_아니면_실행을_못_세운다(tmp_path):
    """돌기 시작한 뒤에 알게 되는 것보다 낫습니다."""
    실행목록 = _모의목록(tmp_path, environment="real")

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_모의물음(environment="real"))

    assert [one["field"] for one in 터짐.value.problems] == ["mode"]
    assert 터짐.value.problems[0]["message"] == service_lib.WHY_ACCOUNT_ENVIRONMENT.format(
        environment="모의", mode="모의 계좌"
    )
    assert 실행목록.engines() == []


def test_해외_계좌_실행은_품목_통화를_모르면_못_세운다(tmp_path):
    실행목록 = _모의목록(tmp_path)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_모의물음(market="overseas", code="없는종목", session="overseas"))

    assert service_lib.WHY_CURRENCY in [one["message"] for one in 터짐.value.problems]


def test_모르는_갈래는_안_받는다(tmp_path):
    실행목록 = _모의목록(tmp_path)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_모의물음(mode="live"))

    assert [one["field"] for one in 터짐.value.problems] == ["mode"]
    assert 터짐.value.problems[0]["message"] == service_lib.WHY_MODE


def test_취소_확인을_기다리면_못_끝낸다(tmp_path):
    """계좌는 취소를 받고 나중에 답합니다."""
    보낸곳 = _보내는곳()
    실행목록 = _모의목록(tmp_path, sender=보낸곳)
    실행목록.add(**_모의물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.book.place(
        "o1", side=paper.BUY, quantity=1, order_type="지정가", price=1.0, at=1_000
    )
    # 중지는 **진입 목적** 주문만 거둡니다 — 엔진이 내면 이 표가 함께 섭니다.
    돌리는것._purpose["o1"] = "entry"
    실행목록.pause("run1", 2_000)
    assert 돌리는것.book.pending == 1

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.end("run1", 3_000)
    assert str(터짐.value) == service_lib.WHY_PENDING

    돌리는것.book.on_order(
        {"id": 보낸곳.order_no, "status": "cancelled", "filled": 0, "remaining": 1}, at=4_000
    )

    assert 실행목록.end("run1", 5_000)["state"] == runs.ENDED


def test_확인_대기_수가_줄에_보인다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.book.place(
        "o1", side=paper.BUY, quantity=1, order_type="지정가", price=1.0, at=1_000
    )
    돌리는것._purpose["o1"] = "entry"

    assert 실행목록.rows()[0]["pending"] == 0
    실행목록.pause("run1", 2_000)
    assert 실행목록.rows()[0]["pending"] == 1


def test_라우트가_갈래와_승인을_받는다(tmp_path):
    """승인은 **서버 시계**로 적습니다 — 화면이 보낸 시각을 그대로 담지 않습니다."""
    실행목록 = _모의목록(tmp_path)
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        앱 = TestClient(app)

        답 = 앱.post(주소, json={**_더하기(), "mode": "sim", "approved": True, "environment": "paper"})

        assert 답.status_code == 200
        줄 = 답.json()
        assert 줄["mode"] == "sim"
        assert 줄["approvedAt"] and 줄["approvedAt"] > 1_700_000_000_000
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_승인_없이_보낸_계좌_실행은_세우지_않는다(tmp_path):
    """세워 두고 주문만 막으면 아무것도 안 하는 실행이 목록에 남습니다."""
    실행목록 = _모의목록(tmp_path)
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        답 = TestClient(app).post(주소, json={**_더하기(), "mode": "sim", "environment": "paper"})

        assert 답.status_code == 400
        속 = 답.json()["detail"]
        assert [(one["field"], one["message"]) for one in 속["problems"]] == [
            ("approved", service_lib.WHY_UNAPPROVED)
        ]
        assert 실행목록.rows() == []
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_모르는_갈래는_라우트에서_400_이다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        답 = TestClient(app).post(주소, json={**_더하기(), "mode": "live"})

        assert 답.status_code == 400
        속 = 답.json()["detail"]
        assert [one["field"] for one in 속["problems"]] == ["mode"]
    finally:
        app.dependency_overrides.pop(get_service, None)


# ── 계약당 증거금 ────────────────────────────────────────


@pytest.fixture
def 시간표받아둠(재생자리):
    """저장본으로 국내 품목별세부정보를 실제로 받아 둡니다.

    **가짜 시간표로는 이 자리를 못 봅니다** — 마스터 줄과 품목 줄을 잇는
    열쇠가 무엇인지가 문제라, 두 쪽 다 실물이어야 드러납니다.
    """
    from backend.sessions import service as 시간표

    시간표.service.reset()
    시간표.service.table(시간표.DOMESTIC)
    try:
        yield 시간표.service
    finally:
        시간표.service.reset()


def test_계약당_증거금을_품목별세부정보에서_받는다(시간표받아둠, 실마스터, tmp_path):
    """라이브에서 늘 비어 있던 값입니다 — 이으려면 `trd_code` 여야 합니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=실마스터,
        hours=시간표받아둠,
        fetch=lambda run, minutes, count: [],
    )

    아는것 = 실행목록.instrument("domestic", "A016C000", "domestic-day")

    assert 아는것["margin"] == 59_816_850.0, "코스피200선물의 계약당 개시증거금입니다."
    assert 아는것["tick"] == 0.05
    assert 아는것["multiplier"] == 250_000.0
    assert 아는것["why"] == ""


def test_마스터의_product_code_로는_못_잇는다(실마스터):
    """`KOSPI` 처럼 생긴 다른 코드라 두 자리 품목코드와 안 맞습니다."""
    줄 = 실마스터.locate("domestic", "A016C000")

    assert 줄["trd_code"] == "01", "품목별세부정보가 쓰는 두 자리 코드입니다."
    assert 줄["product_code"] == "KOSPI", "이것으로 이으면 영영 안 맞습니다."


def test_옵션은_선물_줄의_증거금을_물고_가지_않는다(tmp_path):
    """코드만 보면 옵션 종목이 선물 줄의 틱과 증거금을 가져갑니다.

    실물 국내 옵션은 색인이 안 담아 코드를 고를 수 없어, 같은 품목코드에
    갈래만 다른 두 줄로 봅니다.
    """
    두줄 = _시간표(
        [
            {
                "productCode": "01",
                "kind": "futures",
                "session": "day",
                "tick": "0.05",
                "contractInitialMargin": "59816850",
            },
            {
                "productCode": "01",
                "kind": "option",
                "session": "day",
                "tick": "0.01",
                "contractInitialMargin": None,
            },
        ]
    )
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터({"rem_cnt": "5", "ctrt_size": "250000", "trd_code": "01", "kind": "option"}),
        hours=두줄,
        fetch=lambda run, minutes, count: [],
    )

    아는것 = 실행목록.instrument("domestic", "A7569000", "domestic-day")

    assert 아는것["tick"] == 0.01, "옵션 줄의 틱입니다."
    assert 아는것["margin"] is None, "옵션에는 계약당 증거금 칸이 없습니다."
    assert 아는것["why"] == runs.WHY_SOLD_OPTION


def test_야간_실행은_야간_품목_줄을_본다(tmp_path):
    두줄 = _시간표(
        [
            {
                "productCode": "01",
                "kind": "futures",
                "session": "day",
                "tick": "0.05",
                "contractInitialMargin": "1",
            },
            {
                "productCode": "01",
                "kind": "futures",
                "session": "night",
                "tick": "0.05",
                "contractInitialMargin": "2",
            },
        ]
    )
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=두줄,
        fetch=lambda run, minutes, count: [],
    )

    assert 실행목록.instrument("domestic", "A7569000", "domestic-day")["margin"] == 1.0
    assert 실행목록.instrument("domestic", "A7569000", "domestic-night")["margin"] == 2.0


def test_증거금을_못_받으면_까닭을_한_번_남긴다(tmp_path):
    """「주문을 내지 않았습니다 — 증거금을 몰라…」만 되풀이되면 왜 모르는지는 알 수가 없습니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    실행목록.add(**_물음())
    실행목록.rows()
    실행목록.rows()

    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    막힘 = [one for one in 말들 if service_lib.WHY_NO_MARGIN in one]
    assert len(막힘) == 1, 말들
    assert service_lib.WHY_NO_TABLE in 막힘[0]


def test_뒤에_받으면_그때_담는다(tmp_path):
    """품목별세부정보는 앱이 뜬 뒤에 옵니다 — 그 전에 세운 실행도 채워집니다."""
    시간표 = _시간표()
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=시간표,
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음())
    assert 실행목록._engine("run1").run.margin is None

    시간표.products = [
        {
            "productCode": "01",
            "kind": "futures",
            "session": "day",
            "tick": "0.05",
            "contractInitialMargin": "2500000",
        }
    ]

    (줄,) = 실행목록.rows()

    assert 줄["margin"] == 2_500_000.0
    assert 실행목록._engine("run1").run.margin == 2_500_000.0


# ── 기록 파일의 줄 모양 ─────────────────────────────────


def _사건들(실행목록) -> list[dict]:
    return 실행목록.journal.read(kind=journal_lib.EVENT)


def test_기록의_시각_칸은_한_이름이다(실행목록):
    """`time` 과 `at` 이 섞이면 읽는 쪽이 어느 칸을 볼지 고를 수 없습니다.

    한쪽 이름만 보고 그리면 다른 쪽 줄은 **시각이 빈 줄**로 나옵니다.
    """
    실행목록.add(**_물음())
    실행목록.pause("run1", 2_000)
    실행목록.end("run1", 3_000)

    사건들 = _사건들(실행목록)

    assert 사건들, "이벤트가 적힙니다."
    assert all("time" in one for one in 사건들), "시각 칸은 `time` 하나입니다."
    assert not [one for one in 사건들 if "at" in one], [one for one in 사건들 if "at" in one]


def test_시각_없는_줄을_안_남긴다(실행목록):
    """시각을 안 받고 적는 자리도 지금으로 적습니다 — `0` 은 시각이 아닙니다."""
    실행목록.add(**_물음())

    사건들 = _사건들(실행목록)

    assert 사건들, "이벤트가 적힙니다."
    assert [one for one in 사건들 if not one.get("time")] == []


def test_한_사건이_두_줄로_안_남는다(실행목록):
    """`_say` 가 이미 기록까지 갑니다 — 한 번 더 쓰면 같은 일이 두 줄이 됩니다."""
    실행목록.add(**_물음())
    실행목록.end("run1", 3_000)

    말들 = [one.get("text") for one in _사건들(실행목록)]

    assert 말들.count("검증 실행을 세웠습니다") == 1, 말들
    assert 말들.count("실행을 끝냈습니다") == 1, 말들


def test_모의_실행의_기록에는_모의_표지가_붙는다(tmp_path):
    """`record` 는 그 값이 어디서 나왔는지입니다. 모의 계좌 줄을 지어낸 값으로
    남기면 나중에 둘을 갈라 셀 수 없습니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())

    사건들 = _사건들(실행목록)

    assert 사건들, "이벤트가 적힙니다."
    assert {one["record"] for one in 사건들} == {runs.SIM}


def test_종이_실행의_기록에는_종이_표지가_붙는다(실행목록):
    실행목록.add(**_물음())

    assert {one["record"] for one in _사건들(실행목록)} == {runs.PAPER}


# ── 대사 (§7-3·§13-4) ───────────────────────────────────


def _계좌주문(order_no="5959762237", code="A7569000", status="1", filled=0, quantity=1):
    """계좌 주문내역 줄 하나. 칸 이름은 `domestic_account.order_history` 가 내는 것입니다."""
    return {
        "id": order_no,
        "code": code,
        "statusCode": status,
        "quantity": quantity,
        "filled": filled,
        "remaining": quantity - filled,
    }


def _계좌보유(code="A7569000", quantity=1, side="long"):
    return {"code": code, "quantity": quantity, "side": side}


def test_모의_실행은_대사를_지나_감시로_연다(tmp_path):
    """계좌에 아무것도 없고 장부도 비었으니 맞습니다. 처음 시작이라 `armed` 입니다."""
    실행목록 = _모의목록(tmp_path)

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ARMED
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert service_lib.RECONCILE_START in 말들
    assert service_lib.RECONCILE_DONE in 말들


def test_종이_실행은_대사를_안_지난다(tmp_path):
    """맞춰 볼 계좌가 없습니다. 봉만 받고 바로 봅니다(§7-3)."""
    실행목록 = _모의목록(tmp_path)

    줄 = 실행목록.add(**_물음())

    assert 줄["state"] == runs.ARMED
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert service_lib.RECONCILE_START not in 말들

    # 재접속 자리에서 불려도 종이 실행은 상태가 안 바뀝니다.
    assert 실행목록.reconcile("run1", 5_000)["state"] == runs.ARMED


def test_계좌_보유가_장부와_다르면_확인_필요다(tmp_path):
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유(quantity=2)]))

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ATTENTION
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    기대 = service_lib.WHY_POSITION.format(theirs=2, ours=0, code="A7569000")
    assert f"{service_lib.WHY_MISMATCH} {기대}" in 말들


def test_계좌에_모르는_미체결이_있으면_확인_필요다(tmp_path):
    """수동 주문이든 다른 프로그램이 낸 것이든, 우리가 모르는 주문은 맞춘 것이 아닙니다."""
    실행목록 = _모의목록(tmp_path, account=_계좌(orders=[_계좌주문(order_no="9999999999")]))

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ATTENTION
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    기대 = service_lib.WHY_UNKNOWN_ORDERS.format(code="A7569000", count=1)
    assert f"{service_lib.WHY_MISMATCH} {기대}" in 말들


def test_끝난_주문은_모르는_주문으로_안_센다(tmp_path):
    """주문내역은 그날 것이 다 옵니다. 체결이 끝난 줄까지 세면 늘 어긋납니다."""
    실행목록 = _모의목록(
        tmp_path,
        account=_계좌(orders=[_계좌주문(order_no="9999999999", status="6", filled=1)]),
    )

    assert 실행목록.add(**_모의물음())["state"] == runs.ARMED


def _취소된_줄(order_no, kind, cancelled):
    """취소가 확인된 주문내역 원문 한 줄. 주문상태 「3 확인」, 상태명 「취소완료」, 잔량 0.

    모의 계좌의 실제 응답과 같은 모양입니다 — 원주문 줄(주문구분 1)은 취소수량 1,
    취소 주문 줄(주문구분 3)은 취소수량 0 으로 옵니다.
    """
    return {
        "occurs1_ord_no": order_no,
        "occurs1_sym": "A7569000",
        "occurs1_trd_div": "2",
        "occurs1_ord_sts": "3",
        "occurs1_ord_sts_nm": "취소완료",
        "occurs1_ord_div_cd": kind,
        "occurs1_ord_qty": "1",
        "occurs1_exec_qty": "0",
        "occurs1_rem_ord_qty": "0",
        "occurs1_mod_qty": "0",
        "occurs1_cxl_qty": cancelled,
    }


@pytest.mark.parametrize("market", ["domestic", "overseas"])
def test_확인_상태라도_잔량이_0_이면_끝난_주문이다(market):
    """취소가 확인된 주문은 「3 확인」으로 남습니다. 잔량이 0 이면 끝난 것입니다."""
    원주문 = {"statusCode": "3", "orderKindCode": "1", "remaining": 0, "cancelled": 1, "market": market}
    취소주문 = {"statusCode": "3", "orderKindCode": "3", "remaining": 0, "cancelled": 0, "market": market}

    assert service_lib._order_open(원주문) is False
    assert service_lib._order_open(취소주문) is False


@pytest.mark.parametrize("market", ["domestic", "overseas"])
def test_확인_상태에_잔량이_남으면_열린_주문이다(market):
    """「3 확인」은 살아 있는 주문에도 붙습니다. 잔량이 남으면 진짜 미체결입니다."""
    줄 = {"statusCode": "3", "remaining": 1, "market": market}

    assert service_lib._order_open(줄) is True


@pytest.mark.parametrize("market", ["domestic", "overseas"])
@pytest.mark.parametrize("status", ["6", "8", "9"])
def test_끝난_상태는_잔량과_상관없이_끝난_주문이다(market, status):
    """잔량 칸이 없거나 남아 있다고 와도 끝난 상태면 끝난 것입니다."""
    assert service_lib._order_open({"statusCode": status, "market": market}) is False
    assert service_lib._order_open({"statusCode": status, "remaining": 1, "market": market}) is False


def test_잔량을_모르면_상태로만_판정한다():
    """잔량 칸이 없으면 「0」으로 치지 않습니다 — 상태가 살아 있으면 열린 주문입니다."""
    assert service_lib._order_open({"statusCode": "3"}) is True
    assert service_lib._order_open({"statusCode": "1", "remaining": None}) is True


def test_취소된_주문만_있으면_대사가_맞는다(tmp_path):
    """같은 날 취소한 원주문과 취소 주문 두 줄이 주문내역에 남아도 모르는 미체결이 아닙니다.

    줄은 주문내역 응답을 실제로 푸는 함수를 거쳐 만듭니다.
    """
    from backend.domestic_futureoption import domestic_account

    풀린 = domestic_account.order_history(
        {"Occurs1": [_취소된_줄("0000000002", "1", "1"), _취소된_줄("0000000004", "3", "0")]}
    )["orders"]
    assert [one["remaining"] for one in 풀린] == [0, 0]
    assert [one["statusCode"] for one in 풀린] == ["3", "3"]
    assert [one["orderKindCode"] for one in 풀린] == ["1", "3"]
    assert [one["cancelled"] for one in 풀린] == [1, 0]
    assert not any(one.get("editable") for one in 풀린)

    실행목록 = _모의목록(tmp_path, account=_계좌(orders=풀린))

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ARMED
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert not [one for one in 말들 if service_lib.WHY_MISMATCH in one], 말들


def test_취소된_줄_옆의_진짜_미체결은_센다(tmp_path):
    """취소된 줄을 빼더라도 잔량이 남은 「3 확인」 주문은 여전히 모르는 미체결입니다."""
    살아있는 = _계좌주문(order_no="0000000006", status="3")
    취소된 = {**_계좌주문(order_no="0000000002", status="3"), "remaining": 0, "cancelled": 1}
    실행목록 = _모의목록(tmp_path, account=_계좌(orders=[취소된, 살아있는]))

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ATTENTION
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    기대 = service_lib.WHY_UNKNOWN_ORDERS.format(code="A7569000", count=1)
    assert f"{service_lib.WHY_MISMATCH} {기대}" in 말들


def test_계좌를_못_읽으면_확인_필요다(tmp_path):
    """맞는지 모르는 채로 판정을 열면 계좌에 무엇이 있는지 모르고 주문을 냅니다."""

    def 막힌계좌(run):
        raise TimeoutError("읽지 못했습니다")

    실행목록 = _모의목록(tmp_path, account=막힌계좌)

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ATTENTION
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert [one for one in 말들 if service_lib.WHY_NO_ACCOUNT in one]


def test_재접속_대사가_맞으면_감시를_이어_간다(tmp_path):
    """끊겼다 붙은 동안 계좌가 장부와 맞으면 대사 전 상태(감시)로 돌아갑니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())

    줄 = 실행목록.reconcile("run1", 9_000)

    assert 줄["state"] == runs.ARMED
    마지막 = 실행목록._engine("run1").events[-1]
    assert 마지막["text"] == service_lib.RECONCILE_RESUME
    assert 마지막["reason"] == service_lib.RECONCILE_RESUME_REASON


def test_대사_중에는_시세만_받고_주문은_안_낸다(tmp_path):
    """`reconciling` 은 진입도 청산도 안 내는 자리입니다(§7-1)."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    실행 = 실행목록._engine("run1").run
    실행.state = runs.RECONCILING

    assert 실행.state not in runs.ENTRY_STATES
    assert 실행.state not in runs.EXIT_STATES
    assert [one.id for one in 실행목록.watching()] == ["run1"], "봉은 계속 받습니다."


def test_확인_필요에는_시세도_안_받는다(tmp_path):
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]))
    실행목록.add(**_모의물음())

    assert 실행목록.watching() == []


# ── 「확인」 (§13-5) ─────────────────────────────────────


def test_확인은_대사가_맞을_때만_푼다(tmp_path):
    """확인은 「보았다」이지 「맞다」가 아닙니다 — 한 번 더 맞춰 봅니다."""
    계좌 = {"orders": [], "positions": [_계좌보유()]}
    실행목록 = _모의목록(tmp_path, account=lambda run: 계좌)
    assert 실행목록.add(**_모의물음())["state"] == runs.ATTENTION

    # 계좌 쪽이 정리되면 풀립니다.
    계좌["positions"] = []

    assert 실행목록.acknowledge("run1", 9_000)["state"] == runs.PAUSED


def test_확인해도_어긋나_있으면_안_풀린다(tmp_path):
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]))
    assert 실행목록.add(**_모의물음())["state"] == runs.ATTENTION

    줄 = 실행목록.acknowledge("run1", 9_000)

    assert 줄["state"] == runs.ATTENTION
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    assert len([one for one in 말들 if service_lib.WHY_MISMATCH in one]) == 2, "다시 적힙니다."


def test_확인_필요가_아니면_확인을_못_받는다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.acknowledge("run1", 9_000)

    assert str(잡힘.value) == service_lib.WHY_NOT_ATTENTION


# ── 거래일 경계와 진행 탭 ────────────────────────────────


def test_거래일_경계는_상태를_안_내려놓는다(tmp_path):
    """탭을 열거나 날이 바뀌었다고 돌던 전략이 멈추면 안 됩니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    made = 실행목록._engine("run1")
    made.audit_wanted = True

    assert 실행목록.audit_wanted() == ["run1"]
    assert 실행목록.audit("run1", 9_000) == []
    assert made.run.state == runs.ARMED
    assert made.audit_wanted is False, "한 번 보고 표시를 내립니다."


def test_거래일_경계에_어긋나면_확인_필요다(tmp_path):
    계좌 = {"orders": [], "positions": []}
    실행목록 = _모의목록(tmp_path, account=lambda run: 계좌)
    실행목록.add(**_모의물음())
    계좌["positions"] = [_계좌보유()]

    찾음 = 실행목록.audit("run1", 9_000)

    assert 찾음, 찾음
    assert 실행목록._engine("run1").run.state == runs.ATTENTION


def test_진행_탭을_열면_모의_실행만_맞춰_본다(tmp_path):
    """종이 실행에는 맞춰 볼 계좌가 없습니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    실행목록.add(**_물음(run_id="run2"))

    답 = 실행목록.audit_all(9_000)

    assert 답["checked"] == ["run1"]
    assert 답["mismatched"] == {}
    assert [one["id"] for one in 답["runs"]] == ["run1", "run2"], "줄은 전부 냅니다."


def test_이미_확인_필요인_실행은_다시_안_부른다(tmp_path):
    """푸는 것은 사용자의 「확인」입니다. 탭을 열 때마다 계좌를 또 부를 까닭이 없습니다."""
    센것 = []

    def 계좌(run):
        센것.append(run.id)
        return {"orders": [], "positions": [_계좌보유()]}

    실행목록 = _모의목록(tmp_path, account=계좌)
    실행목록.add(**_모의물음())
    assert len(센것) == 1

    실행목록.audit_all(9_000)

    assert len(센것) == 1


# ── 대사 라우트 ─────────────────────────────────────────


@pytest.fixture
def 모의손님(tmp_path):
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]))
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        yield TestClient(app), 실행목록
    finally:
        app.dependency_overrides.clear()


def test_확인_라우트가_상태를_푼다(모의손님):
    앱, 실행목록 = 모의손님
    앱.post("/api/strategy/runs", json=_더하기(mode=runs.SIM, approved=True, environment="paper"))
    실행목록._account = _계좌()

    답 = 앱.post("/api/strategy/runs/run1/acknowledge")

    assert 답.status_code == 200
    assert 답.json()["state"] == runs.PAUSED


def test_확인_라우트는_확인_필요가_아니면_400_이다(모의손님):
    앱, 실행목록 = 모의손님
    실행목록._account = _계좌()
    앱.post("/api/strategy/runs", json=_더하기(mode=runs.SIM, approved=True, environment="paper"))

    답 = 앱.post("/api/strategy/runs/run1/acknowledge")

    assert 답.status_code == 400
    assert 답.json()["detail"] == {"message": service_lib.WHY_NOT_ATTENTION, "problems": []}


def test_확인_라우트는_없는_실행에_404_다(모의손님):
    앱, _ = 모의손님

    assert 앱.post("/api/strategy/runs/없어요/acknowledge").status_code == 404


def test_대사_라우트는_이미_확인_필요인_실행을_다시_안_부른다(모의손님):
    앱, _ = 모의손님
    앱.post("/api/strategy/runs", json=_더하기(mode=runs.SIM, approved=True, environment="paper"))

    답 = 앱.post("/api/strategy/reconcile")

    assert 답.status_code == 200
    assert (답.json()["checked"], 답.json()["mismatched"]) == ([], {})
    assert [one["state"] for one in 답.json()["runs"]] == [runs.ATTENTION]


def test_저장해_둔_계좌_기록으로_대사한다(재생자리, tmp_path):
    """#255 수집기 기록으로 **진짜 조회 함수를 지나** 맞춰 봅니다.

    저장본의 계좌에는 A7569000 한 계약이 들어 있고 우리 장부는 비어 있어
    어긋납니다. 가짜 계좌로는 조회 응답을 푸는 자리가 안 지나갑니다.
    """
    실행목록 = _모의목록(tmp_path, account=service_lib._fetch_account)

    줄 = 실행목록.add(**_모의물음())

    assert 줄["state"] == runs.ATTENTION
    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    기대 = service_lib.WHY_POSITION.format(theirs=1, ours=0, code="A7569000")
    assert f"{service_lib.WHY_MISMATCH} {기대}" in 말들


# ── 앱을 다시 켤 때 (§7-3) ───────────────────────────────


def test_앱을_켜면_모의_실행은_대사부터다(tmp_path):
    """꺼져 있던 동안 계좌에서 무슨 일이 있었는지 우리는 모릅니다."""
    세운것 = _모의목록(tmp_path)
    세운것.add(**_모의물음())

    다시 = _모의목록(tmp_path)
    다시.load()

    (줄,) = 다시.rows()
    assert 줄["state"] == runs.RECONCILING
    assert 다시.reconcile_wanted() == ["run1"]


def test_켠_뒤_대사가_맞으면_끝난다(tmp_path):
    """장부가 이어지지 않아 이어 갈 수 없습니다 — 계속 돌리려면 새로 세웁니다."""
    세운것 = _모의목록(tmp_path)
    세운것.add(**_모의물음())

    다시 = _모의목록(tmp_path)
    줄 = 다시.reconcile("run1", 9_000)

    assert 줄["state"] == runs.ENDED
    말들 = [one["text"] for one in 다시._engine("run1").events]
    assert service_lib.WHY_RESTORED_END in 말들
    assert 다시.reconcile_wanted() == [], "한 번 지나면 다시 안 섭니다."


def test_켠_뒤_대사가_어긋나도_끝나고_까닭이_남는다(tmp_path):
    """**「확인 필요」로 세우지 않습니다.** 확인 한 번이면 중지가 되고, 그러면
    앱을 껐다 켠 것만으로 「재개」 한 번에 다시 주문이 나갑니다. 계좌에 남은
    것은 잔고 탭에서 봅니다.
    """
    세운것 = _모의목록(tmp_path)
    세운것.add(**_모의물음())

    다시 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]))
    줄 = 다시.reconcile("run1", 9_000)

    assert 줄["state"] == runs.ENDED
    말들 = [one["text"] for one in 다시._engine("run1").events]
    기대 = service_lib.WHY_POSITION.format(theirs=1, ours=0, code="A7569000")
    assert f"{service_lib.WHY_MISMATCH} {기대}" in 말들


def test_되살린_실행은_진행_탭의_대사에서_빠진다(tmp_path):
    """화면이 탭을 여는 것만으로 「확인 필요」가 서면 안 됩니다 — 그 실행은
    곧 대사를 지나 끝납니다. 계좌 조회에는 초당 제한도 있습니다."""
    부른것 = []

    def 계좌(run):
        부른것.append(run.id)
        return {"orders": [], "positions": []}

    세운것 = _모의목록(tmp_path)
    세운것.add(**_모의물음())

    다시 = _모의목록(tmp_path, account=계좌)
    다시.load()

    assert 다시.audit("run1", 9_000) == []
    assert 부른것 == []
    assert 다시.rows()[0]["state"] == runs.RECONCILING


def test_시세가_돌아오면_대사_뒤_대사_전_상태로_돌아간다(tmp_path):
    """끊겼다 다시 붙은 자리에서 펌프가 대사를 청합니다. 맞으면 감시로 돌아갑니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    # 끊겼다 다시 붙은 자리입니다 — 펌프가 이때 대사를 청합니다.
    실행목록._engine("run1").run.move(runs.RECONCILE)

    줄 = 실행목록.reconcile("run1", 9_000)

    assert 줄["state"] == runs.ARMED
    assert 실행목록.reconcile_wanted() == [], "한 번 지나면 다시 안 섭니다."


def test_종이_실행은_켤_때_중지_그대로다(tmp_path):
    세운것 = _모의목록(tmp_path)
    세운것.add(**_물음())

    다시 = _모의목록(tmp_path)
    다시.load()

    (줄,) = 다시.rows()
    assert 줄["state"] == runs.PAUSED
    assert 다시.reconcile_wanted() == []


def test_대사_중인_실행은_다시_안_부른다(tmp_path):
    """라우트 스레드와 펌프가 같은 실행을 함께 집으면 계좌 조회가 두 벌 나갑니다."""
    본것 = []

    def 계좌(run):
        본것.append(실행목록.reconcile_wanted())
        return {"orders": [], "positions": []}

    실행목록 = _모의목록(tmp_path, account=계좌)
    실행목록.add(**_모의물음())

    assert 본것 == [[]], "대사를 도는 동안에는 대기 목록에서 빠집니다."


# ── 요청을 안 내는 상태 (§7-2·§7-3) ──────────────────────


@pytest.mark.parametrize(
    ("상태", "부름"),
    [
        (runs.ATTENTION, "pause"),
        (runs.ATTENTION, "flatten"),
        (runs.RECONCILING, "pause"),
        (runs.RECONCILING, "flatten"),
        (runs.RECONCILING, "end"),
    ],
)
def test_확인_필요와_대사_중에는_요청을_안_낸다(tmp_path, 상태, 부름):
    """중지는 취소를, 청산은 주문을 계좌로 보냅니다.

    계좌와 장부가 맞는지 모르는 자리에서 그것을 보내면, 무엇을 취소하는지
    모르는 채로 요청이 나가 어긋난 자리가 하나 더 생깁니다. 「확인 필요」의
    종료는 장부가 비었을 때 받습니다(`test_strategy_attention_exit.py`).
    """
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    실행목록._engine("run1").run.state = 상태

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        getattr(실행목록, 부름)("run1", 9_000)

    assert str(잡힘.value) == service_lib.WHY_QUIET


def test_확인_필요에서는_중지_라우트도_400_이다(모의손님):
    앱, _ = 모의손님
    앱.post("/api/strategy/runs", json=_더하기(mode=runs.SIM, approved=True, environment="paper"))

    답 = 앱.post("/api/strategy/runs/run1/stop")

    assert 답.status_code == 400
    assert 답.json()["detail"] == {"message": service_lib.WHY_QUIET, "problems": []}


def test_전체_중지는_확인_필요를_건너뛴다(tmp_path):
    """이미 세어 빼고 있습니다(§9) — 건너뛰지 않으면 전체 중지가 통째로 막힙니다."""
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]))
    실행목록.add(**_모의물음())
    assert 실행목록._engine("run1").run.state == runs.ATTENTION

    답 = 실행목록.stop_all(9_000)

    assert 답["paused"] == 0


# ── 증거금 넷 ───────────────────────────────────────────


def test_증거금_비율도_함께_받는다(시간표받아둠, 실마스터, tmp_path):
    """개시액만으로는 유지 수준을 알 수 없습니다 — 비율이 함께 와야 합니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=실마스터,
        hours=시간표받아둠,
        fetch=lambda run, minutes, count: [],
    )

    아는것 = 실행목록.instrument("domestic", "A016C000", "domestic-day")

    assert 아는것["margin"] == 59_816_850.0
    assert 아는것["initialMarginRate"] == "21.75%"
    assert 아는것["maintenanceMarginRate"] == "14.50%"
    assert 아는것["maintenanceMargin"] is None, "응답에 없는 값입니다."


def test_계약당_유지증거금은_안_지어낸다():
    """개시액 × 유지율 ÷ 개시율 로 셈할 수는 있지만 비율이 둘째 자리까지만 옵니다.

    받아 둔 응답의 3년국채선물이 0.98%·0.65% 로 오는데, 그대로 셈하면
    667,312 원이고 비율이 정확히 3분의 2라면 670,735 원입니다 — 증거금 부족을
    가리는 선을 0.5% 어긋난 값으로 그릴 수는 없습니다.
    """
    줄 = {
        "contractInitialMargin": 1_006_102.5,
        "initialMarginRate": "0.98%",
        "maintenanceMarginRate": "0.65%",
    }

    made = domestic_hours.margins(줄)

    assert made["maintenanceMargin"] is None
    assert made["maintenanceMarginRate"] == "0.65%"
    assert "유지증거금률" in domestic_hours.WHY_NO_MAINTENANCE


def test_옵션은_증거금_칸이_다_빈다(시간표받아둠):
    """매수는 프리미엄 전액이고 매도는 거래소가 셈합니다 — 품목마다 정해 둘 수 없습니다."""
    줄들 = 시간표받아둠.cached("domestic")["products"]
    옵션 = [one for one in 줄들 if one["kind"] == "option"]

    assert 옵션, "받아 둔 표에 옵션 줄이 있습니다."
    for one in 옵션:
        made = domestic_hours.margins(one)
        assert set(made.values()) == {None}, one["name"]


def test_실행_줄에_증거금_넷이_실린다(시간표받아둠, 실마스터, tmp_path):
    """화면이 예산 옆에 그리는 값입니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=실마스터,
        hours=시간표받아둠,
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음(code="A016C000"))

    (줄,) = 실행목록.rows()

    assert 줄["margin"] == 59_816_850.0
    assert 줄["initialMarginRate"] == "21.75%"
    assert 줄["maintenanceMarginRate"] == "14.50%"
    assert 줄["maintenanceMargin"] is None


def test_해외는_증거금_칸이_없다(tmp_path):
    """해외 품목별세부정보에는 그 칸 자체가 없습니다(§6-6 이월)."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_해외마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    아는것 = 실행목록.instrument("overseas", "MESU26")

    assert 아는것["margin"] is None
    assert 아는것["initialMarginRate"] is None
    assert 아는것["maintenanceMarginRate"] is None
    assert 아는것["maintenanceMargin"] is None


# ── 다시 켤 때의 상태 ────────────────────────────────────


def test_끝낸_실행은_끝난_채로_읽힌다(tmp_path):
    """**끝낸 것이 되살아나면 사용자는 또 끝내야 합니다.**

    상태를 안 담으면 파일에 남은 실행이 모두 중지로 서서, 끝낸 실행이 목록에
    「멈춰 있음」으로 보입니다.
    """
    담는것 = runs.RunStore(tmp_path / "runs.json")
    끝난것 = _실행(run_id="old", state=runs.ENDED)
    담는것.save([끝난것])

    (읽은것,) = 담는것.read()

    assert 읽은것.state == runs.ENDED


def test_돌던_실행은_중지로_읽힌다(tmp_path):
    """앱을 껐다 켜면 시세도 장부도 안 이어집니다 — 자동 재개는 없습니다(결정 12)."""
    담는것 = runs.RunStore(tmp_path / "runs.json")
    담는것.save([_실행(run_id="a", state=runs.ARMED), _실행(run_id="b", state=runs.HOLDING)])

    읽은것 = {one.id: one.state for one in 담는것.read()}

    assert 읽은것 == {"a": runs.PAUSED, "b": runs.PAUSED}


def test_상태가_없는_옛_줄은_중지로_읽힌다(tmp_path):
    """앞 판이 담은 파일입니다 — 상태 칸이 아예 없습니다."""
    길 = tmp_path / "runs.json"
    runs.RunStore(길).save([_실행(run_id="old", state=runs.ENDED)])
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    for one in 담긴것["runs"]:
        one.pop("state")
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    (읽은것,) = runs.RunStore(길).read()

    assert 읽은것.state == runs.PAUSED


def test_되살린_모의_실행은_대사로_서고_끝난_것은_그대로다(tmp_path):
    """앱을 껐다 켜면 모의 실행은 계좌와 한 번 맞춰 본 뒤 끝납니다.

    장부가 비어 있어 이어 갈 수 없고, 승인 표지만 남은 채 중지로 세우면 「재개」
    한 번에 다시 주문이 나갑니다. 끝난 실행은 맞춰 볼 것이 없습니다.
    """
    담는것 = runs.RunStore(tmp_path / "runs.json")
    담는것.save(
        [
            _실행(run_id="도는것", state=runs.ARMED, mode=runs.SIM),
            _실행(run_id="끝난것", state=runs.ENDED, mode=runs.SIM),
            _실행(run_id="종이것", state=runs.ARMED),
        ]
    )
    실행목록 = service_lib.RunService(
        store=담는것,
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
        account=_계좌(),
        sender=_보내는곳(),
        environment=lambda: "paper",
    )

    실행목록.load()

    상태 = {one["id"]: one["state"] for one in 실행목록.rows()}
    assert 상태 == {"도는것": runs.RECONCILING, "끝난것": runs.ENDED, "종이것": runs.PAUSED}
    assert 실행목록.reconcile_wanted() == ["도는것"], "끝난 실행은 물어볼 것이 없습니다."


def test_끝난_실행은_다시_켠_뒤에도_지울_수_있다(tmp_path):
    """지울 수 있는 것은 끝난 실행뿐입니다 — 중지로 서면 지우지도 못합니다."""
    담는것 = runs.RunStore(tmp_path / "runs.json")
    담는것.save([_실행(run_id="old", state=runs.ENDED)])
    실행목록 = service_lib.RunService(
        store=담는것,
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    실행목록.delete("old")

    assert 실행목록.rows() == []


def test_끝난_실행은_자리를_안_먹는다(tmp_path):
    """한도가 대는 까닭은 **실시간 구독 자리**입니다.

    끝난 실행은 시세를 안 받는데(`watching`) 수만 차지하면, 파일에 남은 끝난
    실행 일곱만으로 새 실행을 아예 못 세우게 됩니다.
    """
    담는것 = runs.RunStore(tmp_path / "runs.json")
    담는것.save(
        [_실행(run_id=f"끝난것{i}", state=runs.ENDED) for i in range(runs.MAX_RUNS + 3)]
    )
    실행목록 = service_lib.RunService(
        store=담는것,
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    assert len(실행목록.rows()) == runs.MAX_RUNS + 3
    assert 실행목록.watching() == [], "구독 자리를 하나도 안 씁니다."

    줄 = 실행목록.add(**_물음(run_id="새것"))

    assert 줄["state"] == runs.ARMED


def test_도는_실행은_자리를_먹는다(tmp_path):
    """한도 자체는 그대로입니다 — 끝난 것만 빼고 셉니다."""
    담는것 = runs.RunStore(tmp_path / "runs.json")
    담는것.save([_실행(run_id=f"r{i}", state=runs.ARMED) for i in range(runs.MAX_RUNS)])
    실행목록 = service_lib.RunService(
        store=담는것,
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.add(**_물음(run_id="새것"))

    assert str(잡힘.value) == runs.WHY_RUNS


def test_끝낸_실행은_다시_읽어도_끝난_채다(tmp_path):
    """**실제로 깨졌던 길입니다** — 끝낸다 → 파일 → 다시 읽는다.

    상태를 파일에 직접 넣는 시험만 있으면, 끝내는 자리가 담기를 빼먹어도
    아무 시험이 안 떨어집니다.
    """
    길 = tmp_path / "runs.json"
    실행목록 = service_lib.RunService(
        store=runs.RunStore(길),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음())

    실행목록.end("run1", 9_000)

    # **다시 켠 앱입니다** — 저장소도 실행 목록도 새로 세웁니다.
    다시 = service_lib.RunService(
        store=runs.RunStore(길),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    (줄,) = 다시.rows()
    assert 줄["state"] == runs.ENDED, "끝난 채로 섭니다."

    # 지울 수 있는 것은 끝난 실행뿐입니다 — 중지로 서면 지우지도 못했습니다.
    다시.delete("run1")

    assert 다시.rows() == []
    assert runs.RunStore(길).read() == [], "파일에서도 빠집니다."


def _실행(*, run_id: str, state: str, mode: str = runs.PAPER) -> runs.Run:
    return runs.Run(
        id=run_id,
        version_id="v1",
        code="A7569000",
        session="domestic-day",
        market="domestic",
        draft=_설정(),
        state=state,
        mode=mode,
        qty=1,
        cash=10_000_000.0,
    )


# ── 진입 미체결 수량 ─────────────────────────────────────


def test_실행_줄에_진입_미체결_수량이_실린다(시간표받아둠, 실마스터, tmp_path):
    """화면이 「사용 증거금」을 **서버 한도 검사와 같은 값**으로 세는 칸입니다.

    둘이 갈리면 사용자는 막힌 까닭을 못 찾습니다 — 화면은 자리가 남았다고
    보이는데 서버는 막습니다.
    """
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=실마스터,
        hours=시간표받아둠,
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음(code="A016C000"))
    made = 실행목록._engine("run1")

    (줄,) = 실행목록.rows()
    assert 줄["openEntry"] == 0, "나가 있는 주문이 없습니다."

    # 진입 주문 하나를 내고 채우지 않습니다.
    made.book.place("o1", side=paper.BUY, quantity=2, order_type="지정가", price=1.0, at=1_000)
    made._purpose["o1"] = "entry"

    (줄,) = 실행목록.rows()

    assert 줄["openEntry"] == 2
    assert 줄["openEntry"] == made.open_entry, "한도 검사가 보는 값과 같은 자리입니다."


def test_청산_주문은_진입_미체결로_안_센다(시간표받아둠, 실마스터, tmp_path):
    """청산은 자리를 **비우는** 주문이라 사용 증거금에 얹으면 두 번 셉니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=실마스터,
        hours=시간표받아둠,
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음(code="A016C000"))
    made = 실행목록._engine("run1")
    made.book.place("o1", side=paper.SELL, quantity=3, order_type="지정가", price=1.0, at=1_000)
    made._purpose["o1"] = "exit"

    (줄,) = 실행목록.rows()

    assert 줄["openEntry"] == 0


def test_실행_파일을_못_읽으면_답에_적는다(손님):
    """담아 둔 실행이 전부 사라지는 자리입니다 — 목록이 비어 온 까닭을 화면이 알아야 합니다."""
    앱, 실행목록 = 손님
    실행목록.store.path.write_text('{"version": 1, "runs": [{"id"', encoding="utf-8")

    첫번 = 앱.get(주소).json()

    assert 첫번["runs"] == []
    assert 첫번["store"] == {
        "status": "broken",
        "stored": False,
        "movedTo": "strategy-runs.json.broken",
        "otherApp": None,
    }
    assert 앱.get(주소).json()["store"] == 첫번["store"], "다음 요청에도 같은 말을 합니다."


def test_실행을_세우면_알림을_놓는다(손님):
    앱, 실행목록 = 손님
    실행목록.store.path.write_text('{"version": 1, "runs": [{"id"', encoding="utf-8")
    assert 앱.get(주소).json()["store"]["status"] == "broken"

    앱.post(주소, json=_더하기())

    assert 앱.get(주소).json()["store"] == {
        "status": "ok",
        "stored": True,
        "movedTo": None,
        "otherApp": None,
    }
# ── 조건이 없는 진입 규칙 ────────────────────────────────


def _조건없음(**규칙) -> dict:
    """진입 규칙을 켜 두기만 한 설정. 조건이 없으면 발동하지 않습니다."""
    설정 = _설정()
    for 이름, 켬 in 규칙.items():
        설정["rules"][이름] = {"on": 켬, "steps": [{"id": "s1", "join": "all", "conds": []}]}
    return 설정


def _막힌것(실행목록, 설정) -> list[dict]:
    return 실행목록.start_problems(
        draft=설정,
        market="domestic",
        code="A7569000",
        session="domestic-day",
        qty=1,
        cash=10_000_000.0,
        fee_per_contract=2_000.0,
    )


def test_켜_두고_조건이_없으면_시작하지_않는다(실행목록):
    """저장은 담아 주지만(적던 것을 잃지 않게) 시작하면 「감시 중」으로 선 채
    아무 일도 일어나지 않습니다 — 그 까닭을 알려 주는 자리가 없습니다.
    """
    찾은것 = _막힌것(실행목록, _조건없음(buyEntry=True))

    assert [one["field"] for one in 찾은것] == ["rules.buyEntry"]
    assert 찾은것[0]["message"] == validate_lib.NO_CONDS_START
    assert 찾은것[0]["severity"] == validate_lib.ERROR


def test_조건이_없으면_세우다_터진다(실행목록):
    설정 = _조건없음(buyEntry=True)

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        실행목록.add(**_물음(draft=설정))

    assert str(터짐.value) == validate_lib.NO_CONDS_START


def test_둘_다_조건이_없으면_앞엣것을_든다(실행목록):
    """고칠 자리는 둘인데 말은 하나입니다 — 차례는 매수 진입, 매도 진입."""
    찾은것 = _막힌것(실행목록, _조건없음(buyEntry=True, sellEntry=True))

    assert [one["field"] for one in 찾은것] == ["rules.buyEntry"]


def test_켜_둔_쪽이_매도뿐이면_매도를_든다(실행목록):
    """차례가 아니라 **켜 둔 것** 중 앞엣것입니다. 규칙 이름을 박아 두면 꺼 둔
    규칙을 고치라고 하게 되는데, 그 규칙은 켜도 이 전략이 안 돕니다.
    """
    설정 = _조건없음(sellEntry=True)
    설정["rules"]["buyEntry"]["on"] = False

    찾은것 = _막힌것(실행목록, 설정)

    assert [one["field"] for one in 찾은것] == ["rules.sellEntry"]
    assert 찾은것[0]["message"] == validate_lib.NO_CONDS_START


def test_한쪽에만_조건이_있으면_시작한다(실행목록):
    """발사할 수 있는 진입 규칙이 하나라도 있으면 도는 전략입니다."""
    설정 = _조건없음(sellEntry=True)

    assert _막힌것(실행목록, 설정) == []


def test_규칙이_둘_다_꺼져_있으면_말이_다르다(실행목록):
    """켜 둔 규칙이 없는 것과 켜 두고 안 적은 것은 고칠 자리가 다릅니다 —
    조건 없는 실행에 「진입 규칙이 없어」가 서면 이미 켜 둔 규칙을 또 켜러 갑니다.
    """
    설정 = _설정()
    설정["rules"]["buyEntry"]["on"] = False

    찾은것 = _막힌것(실행목록, 설정)

    assert [one["field"] for one in 찾은것] == ["rules"]
    assert 찾은것[0]["message"] == validate_lib.NO_ENTRY_START


def test_단계가_아예_없어도_조건이_없는_것이다(실행목록):
    """켜 두고 단계를 지운 설정입니다. 판정이 보는 자리와 같아야 합니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"] = {"on": True, "steps": []}

    찾은것 = _막힌것(실행목록, 설정)

    assert [one["field"] for one in 찾은것] == ["rules.buyEntry"]
    assert 찾은것[0]["message"] == validate_lib.NO_CONDS_START
def test_선물은_계약당_개시증거금이_실린다(시간표받아둠, 실마스터, tmp_path):
    """서버 예산 검사가 쓰는 값과 같아야 화면이 같은 자리에서 막힙니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=실마스터,
        hours=시간표받아둠,
        fetch=lambda run, minutes, count: [],
    )
    실행목록.add(**_물음(code="A016C000"))

    (줄,) = 실행목록.rows()

    assert 줄["perContract"] == 줄["margin"] == 59_816_850.0
    assert 줄["perContractBasis"] == engine_lib.BASIS_MARGIN


def test_옵션_매수는_지금_값으로_잰다(tmp_path):
    """**프리미엄 × 승수**입니다 — 산 옵션에는 증거금이 안 걸립니다."""
    설정 = _설정()
    설정["rules"]["sellEntry"] = {"on": False, "steps": []}
    실행목록 = _옵션목록(tmp_path)
    실행목록.add(**_물음(draft=설정))
    made = 실행목록._engine("run1")
    made.book.last_price = 3.5

    (줄,) = 실행목록.rows()

    assert 줄["margin"] is None, "옵션에는 계약당 개시증거금 칸이 없습니다."
    assert 줄["perContract"] == 3.5 * 250_000
    assert 줄["perContractBasis"] == engine_lib.BASIS_PREMIUM_NOW, (
        "지금 값으로 잰 것이라는 표지가 함께 나갑니다."
    )


def test_옵션_매도는_모른다(tmp_path):
    """거래소가 셈하는 값이라 앱이 셀 수 없습니다 — 0 으로 내면 안 막습니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"] = {"on": True, "steps": [{"id": "s1", "conds": []}]}
    설정["rules"]["sellEntry"] = _규칙한벌()
    실행목록 = _옵션목록(tmp_path)
    실행목록.add(**_물음(draft=설정))
    실행목록._engine("run1").book.last_price = 3.5

    (줄,) = 실행목록.rows()

    assert 줄["perContract"] is None
    assert 줄["perContractBasis"] == engine_lib.BASIS_SELL_UNKNOWN


def test_옵션에서_방향이_갈리면_안_적는다(tmp_path):
    """줄에는 방향이 없습니다. 숫자 하나를 내면 매도 쪽에는 거짓이 됩니다."""
    설정 = _설정()
    설정["rules"]["sellEntry"] = _규칙한벌()
    실행목록 = _옵션목록(tmp_path)
    실행목록.add(**_물음(draft=설정))
    실행목록._engine("run1").book.last_price = 3.5

    (줄,) = 실행목록.rows()

    assert 줄["perContract"] is None
    assert 줄["perContractBasis"] == engine_lib.BASIS_MIXED


def test_켜져만_있고_조건이_없는_규칙은_방향으로_안_센다(tmp_path):
    """**「켜짐」이 아니라 「발사할 수 있나」입니다.**

    규칙이 ON 인데 조건이 0 개인 설정을 저장이 받아 줍니다(§9 는 경고만).
    그 규칙은 절대 발사하지 않으므로, 매수만 나갈 수 있는 옵션 실행인데
    「방향이 갈린다」로 잡히면 화면이 사용 증거금을 못 그립니다.
    """
    설정 = _설정()
    # 매도는 켜 두었지만 조건을 아직 안 넣었습니다 — 나갈 수 없는 방향입니다.
    설정["rules"]["sellEntry"] = {"on": True, "steps": []}
    실행목록 = _옵션목록(tmp_path)
    실행목록.add(**_물음(draft=설정))
    실행목록._engine("run1").book.last_price = 3.5

    (줄,) = 실행목록.rows()

    assert 줄["perContract"] == 3.5 * 250_000
    assert 줄["perContractBasis"] == engine_lib.BASIS_PREMIUM_NOW


def test_체결가를_아직_못_받았으면_셀_재료가_없다(tmp_path):
    """**근거는 서고 값만 빕니다** — 그 방법으로 셀 수는 있는데 재료가 없습니다."""
    설정 = _설정()
    설정["rules"]["sellEntry"] = {"on": False, "steps": []}
    실행목록 = _옵션목록(tmp_path)
    실행목록.add(**_물음(draft=설정))

    (줄,) = 실행목록.rows()

    assert 실행목록._engine("run1").book.last_price is None
    assert 줄["perContract"] is None
    assert 줄["perContractBasis"] == engine_lib.BASIS_PREMIUM_NOW


def _규칙한벌():
    return {
        "on": True,
        "steps": [
            {
                "id": "s1",
                "join": "all",
                "withinBars": 0,
                "conds": [
                    {
                        "id": "c1",
                        "left": "close",
                        "op": "lt",
                        "rightKind": "number",
                        "right": "100",
                    }
                ],
            }
        ],
    }


def _옵션목록(tmp_path):
    """옵션 한 종목만 아는 목록. 계약당 증거금 칸이 비어 옵니다(실제 응답이 그렇습니다)."""
    마스터 = type(
        "마스터",
        (),
        {
            "locate": lambda self, market, code: {
                "rem_cnt": "30",
                "ctrt_size": "250000",
                "trd_code": "01",
                "kind": "option",
            }
        },
    )()
    시간표 = type(
        "시간표",
        (),
        {
            "cached": lambda self, market: {
                "products": [
                    {
                        "productCode": "01",
                        "kind": "option",
                        "session": "day",
                        "tick": "0.01",
                        "multiplier": "250000",
                        "contractInitialMargin": None,
                    }
                ]
            }
        },
    )()
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=마스터,
        hours=시간표,
        fetch=lambda run, minutes, count: [],
    )


# ── 숫자가 아닌 숫자 ─────────────────────────────────────


@pytest.mark.parametrize("값", ["nan", "NaN", "inf", "-inf", "1e3", "0x10"])
def test_실행이_읽는_숫자_칸도_nan_inf_지수를_안_받는다(값):
    assert service_lib._number(값) is None
    assert service_lib._whole(값) is None


@pytest.mark.parametrize("값, 읽은것", [("1,000", 1000.0), ("1000.5", 1000.5), ("-3", -3.0)])
def test_실행이_읽는_보통_십진수는_지금과_같다(값, 읽은것):
    assert service_lib._number(값) == 읽은것


def test_세_자리가_같은_도우미를_쓴다():
    """두 벌로 두면 한쪽만 고쳐지는 날 저장 검사와 실행이 다른 수를 봅니다."""
    from backend import market_values
    from backend.strategy import limits

    for 값 in ("nan", "1e3", "1,000", ""):
        기대 = market_values.plain_number(값)
        assert limits._number(값) == validate_lib._number(값) == service_lib._number(값) == 기대


class _해외선물마스터:
    """해외 종목 한 줄만 아는 마스터."""

    def locate(self, market, code):
        if market != "overseas" or code != "ESZ26":
            return None
        return {"ExchName": "FCME", "tsiz": "0.25", "ctrt_size": "50", "kind": "futures"}


def test_해외_선물은_예산_검사를_안_한다고_한_번만_남긴다(tmp_path):
    """해외 조회에는 계약당 증거금 칸이 없습니다. 알림은 한 줄이고 둘째 줄을 더하지 않습니다."""
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_해외선물마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )

    실행목록.add(
        **_물음(
            market="overseas",
            code="ESZ26",
            session="overseas",
            draft=_설정(session="해외 CME"),
        )
    )
    줄 = 실행목록.rows()[0]
    실행목록.rows()

    말들 = [one["text"] for one in 실행목록._engine("run1").events]
    증거금줄 = [
        one
        for one in 말들
        if service_lib.WHY_NO_MARGIN in one or one == service_lib.WHY_BUDGET_UNCHECKED
    ]
    assert 증거금줄 == [service_lib.WHY_BUDGET_UNCHECKED], 말들
    assert 줄["budgetUnchecked"] is True
    assert 줄["perContract"] is None
    assert 줄["perContractBasis"] == "no-margin-field"


# ── 주문당 수량을 안 보내면 ──────────────────────────────
#
# 화면이 수량을 안 보내면 설정의 주문당 수량으로 섭니다 — 백테스트와 같은 셈입니다
# (`strategy_routes.qty_of`). 범위는 보낸 때와 같은 검사·같은 문구로 막습니다.


def _수량_없이(**덮어쓰기) -> dict:
    본문 = _더하기(**덮어쓰기)
    del 본문["qty"]
    return 본문


def test_수량을_안_보내면_설정의_주문당_수량으로_선다(손님):
    앱, 실행목록 = 손님

    답 = 앱.post(주소, json=_수량_없이(draft=_설정(perOrder="3")))

    assert 답.status_code == 200, 답.text
    assert 실행목록._engine("run1").run.qty == 3


def test_주문당_수량이_없으면_1_이다():
    """셈 자체의 마지막 값입니다. 라우트에서는 설정 검사가 빈 주문당 수량을 먼저 막습니다(아래)."""
    from backend.strategy.strategy_routes import qty_of

    assert qty_of(None, {"aux": {}}) == 1
    assert qty_of(None, None) == 1
    assert qty_of(None, {"aux": {"perOrder": "글자"}}) == 1
    assert qty_of(4, {"aux": {"perOrder": "3"}}) == 4


def test_주문당_수량이_빈_설정은_시작_검사가_막는다(손님):
    앱, _ = 손님
    설정 = _설정()
    del 설정["aux"]["perOrder"]

    답 = 앱.post(주소, json=_수량_없이(draft=설정))

    assert 답.status_code == 400
    assert "aux.perOrder" in [one["field"] for one in 답.json()["detail"]["problems"]]


def test_수량을_보내면_그대로_쓴다(손님):
    앱, 실행목록 = 손님

    답 = 앱.post(주소, json=_더하기(qty=2, draft=_설정(perOrder="3")))

    assert 답.status_code == 200, 답.text
    assert 실행목록._engine("run1").run.qty == 2


def test_안_보낸_수량이_최대_보유를_넘으면_보낸_때와_같은_문구로_막는다(손님):
    앱, _ = 손님

    안보냄 = 앱.post(주소, json=_수량_없이(draft=_설정(perOrder="9", maxHold="5")))
    보냄 = 앱.post(주소, json=_더하기(qty=9, draft=_설정(perOrder="1", maxHold="5")))

    for 답 in (안보냄, 보냄):
        assert 답.status_code == 400
        (하나,) = [one for one in 답.json()["detail"]["problems"] if one["field"] == "qty"]
        assert 하나["message"] == service_lib.WHY_QTY


def test_모의_실행도_수량을_안_보내면_주문당_수량으로_선다(모의손님):
    앱, 실행목록 = 모의손님

    답 = 앱.post(
        주소,
        json=_수량_없이(draft=_설정(perOrder="3"), mode=runs.SIM, approved=True, environment="paper"),
    )

    assert 답.status_code == 200, 답.text
    assert 실행목록._engine("run1").run.qty == 3


def test_쓰지_않는_주문유형으로_시작하면_그_칸은_한_줄이다(손님):
    """담을 때의 오류와 「돌 수 있는지」가 같은 까닭을 같은 말로 짚습니다. 한 줄만 냅니다."""
    앱, _ = 손님

    답 = 앱.post(주소, json=_더하기(draft=_설정(orderType="조건부지정가")))

    assert 답.status_code == 400
    줄들 = [one for one in 답.json()["detail"]["problems"] if one["field"] == "aux.orderType"]
    assert [one["message"] for one in 줄들] == [
        "조건부지정가는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요"
    ]
