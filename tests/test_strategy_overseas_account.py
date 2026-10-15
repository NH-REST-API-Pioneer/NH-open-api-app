"""해외 품목의 계좌 실행(모의·실전) — 전송·실패·알림·대사·통화·세션 끝.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 주문 함수와 계좌 조회는 가짜로 바꿔
끼우고, 보낸 몸만 견줍니다. 시험이 실서버로 부르려 하면 실패합니다(`conftest`).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.domestic_futureoption import domestic_futureoption_functions as domestic_api
from backend.nh_api.errors import BusinessError, GatewayError, TransportError
from backend.overseas_futureoption import overseas_futureoption_functions as overseas_api
from backend.overseas_futureoption.overseas_routes import OverseasOrderRequest
from backend.sessions import judge
from backend.sessions.hours import KST
from backend.strategy import engine, journal as journal_lib, limits, paper, pump as pump_lib, runs, sim
from backend.strategy import service as service_lib
from tests.test_strategy_engine import _설정
from tests.test_strategy_vwap_day import _표

해외 = "overseas"


def _실행(**덮어쓰기) -> runs.Run:
    made = {
        "id": "r1", "version_id": "v1", "code": "6AZ26", "session": 해외, "market": "overseas",
        "state": runs.ARMED, "qty": 1, "cash": 1.0, "draft": _설정(), "mode": runs.SIM,
        "approved_at": 1_000, "environment": "paper", "currency": "USD",
    }
    made.update(덮어쓰기)
    return runs.Run(**made)


@pytest.fixture
def 보낸것(monkeypatch):
    """해외 주문 함수가 받은 몸. 국내 주문 함수가 불리면 실패합니다."""
    몸들: list[dict] = []

    def 해외주문(sym, **몸):
        몸들.append({"sym": sym, **몸})
        return {"ord_no": "0000012345", "ord_qty": 몸["ord_qty"], "sym": sym}

    def 안됨(*args, **kwargs):
        raise AssertionError("해외 실행이 국내 거래 함수를 불렀습니다.")

    monkeypatch.setattr(overseas_api, "order", 해외주문)
    for name in ("order", "cancel", "order_history", "open_interest"):
        monkeypatch.setattr(domestic_api, name, 안됨)
    return 몸들


# ── 전송 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("order_type", "code", "ord_pric", "stop_pric"),
    [
        ("시장가", "1", "0", ""),
        ("지정가", "2", "0.6512", ""),
        ("STOP-M", "3", "0", "0.6512"),
        ("STOP-L", "4", "0.6512", "0.6512"),
    ],
)
def test_해외_신규_주문의_몸(보낸것, order_type, code, ord_pric, stop_pric):
    답 = sim.NhSender().order(
        run=_실행(), side=paper.BUY, quantity=2, order_type=order_type, price=0.65120000001,
        stop_price=0.6512, fill_condition="", tick=0.0001,
    )

    (몸,) = 보낸것
    assert 몸["qt_div_cd"] == "1" and 몸["org_ord_no"] == "0" and 몸["trd_div_cd"] == "1"
    assert 몸["glb_ord_tp_cd"] == code and 몸["ord_qty"] == "2"
    assert (몸["ord_pric"], 몸["stop_pric"]) == (ord_pric, stop_pric)
    assert 몸["environment"] == "paper", "실행이 선 환경을 적어 부릅니다."
    assert 답["id"] == "0000012345"


@pytest.mark.parametrize(
    ("price", "tick", "글자"),
    [
        (112.54687500000001, 0.015625, "112.546875"),  # 1/64
        (98.03125, 0.03125, "98.03125"),  # 1/32
        (4510.0, 0.25, "4510"),
        (4510.25, 0.25, "4510.25"),
        (0.000123, 0.0000005, "0.000123"),
        (0.6512000000000001, 0, "0.6512"),  # 틱을 모르면 소수 8자리에서 반올림
        (4510.0, 0, "4510"),
    ],
)
def test_분수_틱_가격은_정확한_십진_글자이고_화면_주문이_받는_모양이다(price, tick, 글자):
    made = sim.decimal_text(price, tick)

    assert made == 글자
    assert "e" not in made.lower()
    OverseasOrderRequest(  # 화면 주문 라우트의 가격 모양을 그대로 지납니다.
        environment="paper", sym="ZBZ26", side="buy", qt_div_cd="1", glb_ord_tp_cd="2",
        ord_qty=1, ord_pric=made,
    )


def test_해외_취소는_원주문_열_자리와_남은_수량으로_낸다(보낸것):
    주문 = sim.SimOrder(id="r1-1", side=paper.SELL, quantity=3, order_type="지정가", price=0.65,
                      stop_price=None, fill_condition="", created=1)
    주문.order_no, 주문.filled = "12345", 1

    sim.NhSender().cancel(run=_실행(), order=주문)

    (몸,) = 보낸것
    assert 몸["qt_div_cd"] == "3" and 몸["org_ord_no"] == "0000012345"
    assert 몸["ord_qty"] == "2" and 몸["trd_div_cd"] == "2" and 몸["glb_ord_tp_cd"] == "2"


def test_국내_실행은_해외_거래_함수를_안_부른다(monkeypatch):
    def 안됨(*args, **kwargs):
        raise AssertionError("국내 실행이 해외 거래 함수를 불렀습니다.")

    monkeypatch.setattr(overseas_api, "order", 안됨)
    monkeypatch.setattr(overseas_api, "order_history", 안됨)
    monkeypatch.setattr(overseas_api, "open_interest", 안됨)
    받음: list = []
    monkeypatch.setattr(domestic_api, "order", lambda sym, **몸: 받음.append(몸) or {"ord_no": "1"})

    sim.NhSender().order(
        run=_실행(market="domestic", session="domestic-day", code="A7569000", currency="KRW"),
        side=paper.BUY, quantity=1, order_type="시장가", price=None, stop_price=None,
        fill_condition="", tick=0.05,
    )
    assert len(받음) == 1


def test_시험에서_해외_주문이_실서버로_나가려_하면_막힌다():
    with pytest.raises(AssertionError):
        sim.NhSender().order(
            run=_실행(), side=paper.BUY, quantity=1, order_type="시장가", price=None,
            stop_price=None, fill_condition="", tick=0.0001,
        )


# ── 실패 → 확인 필요 ───────────────────────────────────────


@pytest.mark.parametrize(
    ("터짐", "상태"),
    [
        # 계좌가 받지 않은 것이 확실한 답 — 진입이면 중지입니다.
        (BusinessError("overseas_order", "E1234", "주문 거부", {}), runs.PAUSED),
        (GatewayError("overseas_order", "EGW053", "모의투자 미지원", {}, kind="paper-unavailable"), runs.PAUSED),
        # 접수됐는지 모르는 자리 — 확인 필요입니다.
        (GatewayError("overseas_order", "EGW00", "게이트웨이 거절", {}), runs.ATTENTION),
        (TransportError("overseas_order", "응답 없음"), runs.ATTENTION),
        (None, runs.ATTENTION),  # 주문번호 없는 답
    ],
    ids=["업무거부", "모의미지원", "게이트웨이", "답없음", "번호없음"],
)
def test_거부_모의미지원_답없음_번호없음은_다시_안_보내고_멈춘다(monkeypatch, 터짐, 상태):
    부름: list = []

    def 해외주문(sym, **몸):
        부름.append(몸)
        if 터짐 is not None:
            raise 터짐
        return {"ord_no": ""}

    monkeypatch.setattr(overseas_api, "order", 해외주문)
    run = _실행()
    엔진 = engine.RunEngine(run, tick=0.0001, book=sim.SimBroker(run, sender=sim.NhSender(), environment=lambda: "paper"))
    엔진.book.last_price = 0.65

    엔진._send(paper.BUY, 1, 0.65, "entry", 10)

    assert 엔진.run.state == 상태
    assert len(부름) == 1, "실패한 주문을 다시 보내지 않습니다."


# ── 알림 O1 ──────────────────────────────────────────────


def test_해외_알림의_누적_체결을_차분으로_적고_자동취소를_닫는다():
    run = _실행(qty=3)
    보냄 = type("S", (), {"order": lambda self, **물음: {"id": "0000012345"}})()
    장부 = sim.SimBroker(run, sender=보냄, environment=lambda: "paper")
    주문 = 장부.place("o1", side=paper.BUY, quantity=3, order_type="지정가", price=0.65, at=1)

    첫 = 장부.on_order({"id": "0000012345", "status": "partial", "statusCode": "4", "filled": 1, "fillPrice": 0.65}, at=2)
    둘 = 장부.on_order({"id": "0000012345", "status": "partial", "statusCode": "4", "filled": 2, "fillPrice": 0.65}, at=3)
    장부.on_order({"id": "0000012345", "status": "auto-cancelled", "statusCode": "8", "filled": 2}, at=4)

    assert [one["quantity"] for one in 첫 + 둘] == [1, 1]
    assert 주문.filled == 2 and not 주문.open


def test_해외_알림은_해외_실행에만_간다(tmp_path):
    목록 = _목록(tmp_path)
    받음: dict[str, list] = {"국내": [], "해외": []}

    class 엔진:
        def __init__(self, market, session, key):
            self.run = type("R", (), {"market": market, "session": session})()
            self.key = key

        def on_order(self, event, *, at):
            받음[self.key].append(event)

    목록.engines = lambda: [엔진("domestic", "domestic-day", "국내"), 엔진("overseas", 해외, "해외")]
    돌리는것 = pump_lib.RunPump(목록, hub=None, judge=lambda *a: True, replaying=lambda: False)
    돌리는것.take({"type": "orders", "market": "overseas", "events": [{"id": "1"}]}, at=1)

    assert 받음 == {"국내": [], "해외": [{"id": "1"}]}


# ── 대사 ─────────────────────────────────────────────────


def test_해외_대사는_해외_조회를_다음_쪽까지_다_읽는다(monkeypatch):
    물음: list = []

    def 주문내역(*, next_key="", environment=None, **_):
        물음.append(("orders", next_key, environment))
        if not next_key:
            return {"Occurs1": [{"occurs1_ord_no": "1", "occurs1_ord_sts": "1", "occurs1_sym": "6AZ26"}], "nxt_key": "K2"}
        return {"Occurs1": [{"occurs1_ord_no": "2", "occurs1_ord_sts": "6", "occurs1_sym": "6AZ26"}], "nxt_key": ""}

    def 잔고(*, next_key="", environment=None, **_):
        물음.append(("positions", next_key, environment))
        return {"Occurs1": [{"occurs1_sym": "6AZ26", "occurs1_trd_tp": "2", "occurs1_opint_qty": "1"}], "nxt_key": ""}

    monkeypatch.setattr(overseas_api, "order_history", 주문내역)
    monkeypatch.setattr(overseas_api, "open_interest", 잔고)

    계좌 = service_lib._fetch_account(_실행(environment="real", mode=runs.REAL))

    assert [(kind, key) for kind, key, _ in 물음] == [("orders", ""), ("orders", "K2"), ("positions", "")]
    assert {env for _, _, env in 물음} == {"real"}
    assert len(계좌["orders"]) == 2 and 계좌["positions"][0]["side"] == "short"
    assert [service_lib._order_open(one) for one in 계좌["orders"]] == [True, False], "6 은 끝난 주문입니다."


# ── 통화·거래소 ───────────────────────────────────────────


class _해외마스터:
    def __init__(self, exch="01", comd="6A"):
        self.exch, self.comd = exch, comd

    def locate(self, market, code):
        if market == "overseas" and code == "6AZ26":
            return {"tsiz": "0.0001", "ctrt_size": "100000", "ExchName": "CME", "kind": "futures"}
        return None

    def product_of(self, market, code):
        return {"exch": self.exch, "comd": self.comd} if code == "6AZ26" else None


class _해외표:
    def cached(self, market):
        if market == "overseas":
            return {
                "products": [
                    {**one, "currency": {"6A": "USD", "HCEI": "HKD"}[one["productCode"]]}
                    for one in _표["products"]
                ] + [{"exchange": "ICE", "productCode": "6A", "currency": "USD"}]
            }
        return {"products": []}


class _적는곳:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def order(self, **물음):
        self.sent.append(물음)
        return {"id": "0000012345"}

    def cancel(self, *, run, order):
        return {"id": order.order_no}


def _목록(tmp_path, master=None, account=None) -> service_lib.RunService:
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=master or _해외마스터(),
        hours=_해외표(),
        fetch=lambda run, minutes, count: [],
        account=account or (lambda run: {"orders": [], "positions": []}),
        sender=_적는곳(),
        environment=lambda: "paper",
        judged=lambda market, code, moment: {"source": judge.UNKNOWN},
    )


def _세우기(목록, run_id="r1", mode=runs.SIM, **덮어쓰기):
    물음 = {
        "run_id": run_id, "version_id": "v1", "draft": _설정(session="해외 CME", fillCond=""),
        "market": "overseas", "code": "6AZ26",
        "session": 해외, "qty": 1, "cash": 1.0, "fee_per_contract": 0.0, "mode": mode,
        "approved_at": 1_000, "environment": "paper",
    }
    물음.update(덮어쓰기)
    return 목록.add(**물음)


def test_해외_계좌_실행을_세우면_품목_통화를_담고_줄과_기록에_싣는다(tmp_path):
    목록 = _목록(tmp_path)

    줄 = _세우기(목록)

    assert 줄["state"] == runs.ARMED and 줄["currency"] == "USD"
    assert 목록._engine("r1").run.currency == "USD"
    기록 = 목록.journal.read(run_id="r1")
    assert 기록 and {one.get("currency") for one in 기록} == {"USD"}


def test_홍콩_품목은_홍콩달러다(tmp_path):
    목록 = _목록(tmp_path, master=_해외마스터(exch="HKEX", comd="HCEI"))

    assert _세우기(목록)["currency"] == "HKD"


def test_ICE_JPX_품목은_계좌_실행을_안_연다(tmp_path):
    목록 = _목록(tmp_path, master=_해외마스터(exch="ICE", comd="6A"))

    with pytest.raises(service_lib.StrategyRunError) as 터짐:
        _세우기(목록)
    assert service_lib.WHY_ACCOUNT_EXCHANGE in [one["message"] for one in 터짐.value.problems]
    assert _세우기(목록, mode=runs.PAPER)["mode"] == runs.PAPER, "앱 시뮬레이션은 그대로 엽니다."


def test_해외_계좌_실행은_예산_검사를_건너뛴다는_표지를_싣는다(tmp_path):
    목록 = _목록(tmp_path)

    줄 = _세우기(목록)

    assert 줄["budgetUnchecked"] is True, "해외 선물은 계약당 증거금 칸이 없어 화면이 안내합니다."


def test_손실_한도는_같은_통화의_실행만_더한다(tmp_path):
    목록 = _목록(tmp_path)
    _세우기(목록, run_id="usd")
    홍콩 = _목록(tmp_path / "hk", master=_해외마스터(exch="HKEX", comd="HCEI"))
    _세우기(홍콩, run_id="hkd")
    목록._engines["hkd"] = 홍콩._engine("hkd")
    목록._order.append("hkd")
    for one in ("usd", "hkd"):
        엔진 = 목록._engine(one)
        엔진.run.state = runs.ARMED
        엔진.ledger.realized = -5.0

    멈춤 = 목록.account_loss({"HKD": 1.0}, 10)

    assert 멈춤 == ["hkd"], "달러 실행의 손실은 홍콩달러 한도에 안 듭니다."
    assert 목록.account_loss(limits.daily_losses({"overseas": {"dailyLoss": 1.0}}), 20) == ["usd"]


def test_옛_실행의_통화는_시장으로_읽는다():
    assert runs.currency_of(_실행(currency="")) == "USD"
    assert runs.currency_of(_실행(currency="", market="domestic")) == "KRW"


# ── 세션 끝·쉼 ─────────────────────────────────────────────


def test_구간이_여럿인_품목은_거래일의_마지막_구간_끝에서만_정리한다():
    홍콩 = {"exch": "HKEX", "comd": "HCEI"}
    첫구간 = datetime(2026, 9, 16, 11, 0, tzinfo=KST)
    끝 = judge.overseas_day_end(홍콩, table=_표, now=첫구간)

    assert 끝 == datetime(2026, 9, 17, 4, 0, tzinfo=KST), "13:00 첫 구간 끝이 아니라 익일 04:00 입니다."
    assert judge.overseas_day_end(홍콩, table=_표, now=datetime(2026, 9, 16, 13, 30, tzinfo=KST)) is None


def test_해외_세션_끝_시각은_거래일_끝을_쓴다(monkeypatch):
    from backend.sessions import sessions_routes

    monkeypatch.setattr(
        sessions_routes, "judged",
        lambda market, code, now: {"source": "api", "state": judge.OPEN, "until": "2026-09-16T13:00:00+09:00"},
    )
    monkeypatch.setattr(
        sessions_routes, "trading_day_end",
        lambda market, code, now: datetime(2026, 9, 17, 4, 0, tzinfo=KST),
    )

    assert pump_lib._closing_now("overseas", "HCEIV26", 해외) == int(
        datetime(2026, 9, 17, 4, 0, tzinfo=KST).timestamp() * 1000
    )


def test_쉼은_닫힘이_아니라_세션을_닫지_않는다(monkeypatch):
    from backend.sessions import sessions_routes

    monkeypatch.setattr(sessions_routes, "judged", lambda market, code, now: {"source": "api", "state": judge.BREAK})

    assert pump_lib._open_now("overseas", "HCEIV26", 해외) is True

def _주문(no, status="1", code="6AZ26"):
    return {"id": no, "code": code, "statusCode": status, "quantity": 1, "filled": 0, "remaining": 1, "market": "overseas"}


@pytest.mark.parametrize(
    ("계좌", "상태"),
    [
        ({"orders": [], "positions": []}, runs.ARMED),
        ({"orders": [], "positions": [{"code": "6AZ26", "quantity": 1, "side": "long"}]}, runs.ATTENTION),
        ({"orders": [_주문("9999999999")], "positions": []}, runs.ATTENTION),
        ({"orders": [_주문("9999999999", status="6")], "positions": []}, runs.ARMED),
    ],
)
def test_해외_대사는_일치_수량_불일치_모르는_주문_끝난_주문을_가린다(tmp_path, 계좌, 상태):
    목록 = _목록(tmp_path, account=lambda run: 계좌)

    assert _세우기(목록)["state"] == 상태


def test_국내_실행의_주문번호는_해외_대사에서_아는_주문이_아니다(tmp_path):
    """국내와 해외는 다른 계좌라 번호가 같아도 다른 주문입니다."""
    목록 = _목록(tmp_path, account=lambda run: {"orders": [_주문("0000012345")], "positions": []})
    국내 = engine.RunEngine(
        runs.Run(id="d1", version_id="v", code="A7569000", session="domestic-day", market="domestic",
                 mode=runs.SIM, environment="paper", approved_at=1, draft=_설정()),
        tick=0.05,
        book=sim.SimBroker(
            runs.Run(id="d1", version_id="v", code="A7569000", session="domestic-day", market="domestic",
                     mode=runs.SIM, environment="paper", approved_at=1),
            sender=_적는곳(), environment=lambda: "paper",
        ),
    )
    국내.book.place("d1-1", side=paper.BUY, quantity=1, order_type="시장가", at=1)
    목록._engines["d1"] = 국내
    목록._order.append("d1")
    목록._loaded = True

    assert "0000012345" in 목록._order_numbers("paper", "domestic")
    assert "0000012345" not in 목록._order_numbers("paper", "overseas")


@pytest.mark.parametrize(
    ("order_type", "code", "ord_pric", "stop_pric"),
    [
        ("시장가", "1", "0", ""),
        ("지정가", "2", "0.6512", ""),
        ("STOP-M", "3", "0", "0.651"),
        ("STOP-L", "4", "0.6512", "0.651"),
    ],
)
def test_해외_취소는_원주문_가격_두_칸을_신규와_같은_규칙으로_싣는다(보낸것, order_type, code, ord_pric, stop_pric):
    run = _실행()
    장부 = sim.SimBroker(run, sender=sim.NhSender(), environment=lambda: "paper", tick=0.0001)
    주문 = 장부.place("r1-1", side=paper.BUY, quantity=2, order_type=order_type,
                      price=0.6512000000000001, stop_price=0.6510000000000001, at=1)
    보낸것.clear()

    assert 장부.cancel(주문, "시험")

    (몸,) = 보낸것
    assert 몸["qt_div_cd"] == "3" and 몸["glb_ord_tp_cd"] == code
    assert (몸["ord_pric"], 몸["stop_pric"]) == (ord_pric, stop_pric)
    화면 = OverseasOrderRequest(  # 화면 주문 라우트가 받는 취소 몸입니다.
        environment="paper", sym=run.code, side="buy", qt_div_cd="3", glb_ord_tp_cd=code,
        ord_qty=2, ord_pric=몸["ord_pric"], stop_pric=몸["stop_pric"], org_ord_no=몸["org_ord_no"],
    )
    assert (화면.price, 화면.stop) == (몸["ord_pric"], 몸["stop_pric"]), "라우트가 보낼 몸과 같은 글자입니다."
