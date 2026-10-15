"""모의 계좌로 나가는 주문.

**계좌에 한 건도 안 보냅니다.** 보내는 자리(`sender`)와 활성 환경을 답하는
자리를 지어 끼우고, 그 사이의 우리 코드를 다 지나갑니다. 알림은 허브가 내는
모양(`feeds.order_event`) 그대로 지어 넣습니다.
"""
from __future__ import annotations

import pytest

from backend.strategy import engine as engine_lib
from backend.strategy import paper, runs, sim

주간 = "domestic-day"


class _보내는곳:
    """주문을 받아 적기만 하는 자리. 계좌에 닿지 않습니다."""

    def __init__(self, order_no: str = "0000012345", fails: Exception | None = None):
        self.order_no = order_no
        self.fails = fails
        self.sent: list[dict] = []
        self.cancelled: list[str] = []

    def order(self, **물음):
        if self.fails is not None:
            raise self.fails
        self.sent.append(물음)
        return {"id": self.order_no}

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
        "mode": runs.SIM,
        "approved_at": 1_000,
        "environment": "paper",
        "qty": 1,
    }
    made.update(덮어쓰기)
    return runs.Run(**made)


def _장부(run=None, sender=None, environment="paper") -> sim.SimBroker:
    return sim.SimBroker(
        run if run is not None else _실행(),
        sender=sender if sender is not None else _보내는곳(),
        environment=lambda: environment,
    )


def _알림(**덮어쓰기) -> dict:
    made = {"id": "0000012345", "status": "accepted", "filled": 0, "remaining": 1}
    made.update(덮어쓰기)
    return made


def _내기(장부, quantity: int = 1, **덮어쓰기):
    물음 = {
        "side": paper.BUY,
        "quantity": quantity,
        "order_type": "지정가",
        "price": 405.25,
        "at": 5_000,
    }
    물음.update(덮어쓰기)
    return 장부.place("o1", **물음)


# ── 실전으로 가는 길이 없습니다 ───────────────────────────


def test_갈래는_셋이고_계좌_갈래는_둘이다():
    assert runs.MODES == ("paper", "sim", "real")
    assert runs.ACCOUNT_MODES == ("sim", "real")
    assert runs.ENVIRONMENT_OF == {"sim": "paper", "real": "real"}


def test_승인_표지가_없으면_한_건도_안_낸다():
    """엔진은 사람이 단추를 누르지 않아도 주문을 내는 자리입니다."""
    보낸곳 = _보내는곳()
    장부 = _장부(_실행(approved_at=0), sender=보낸곳)

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(장부)

    assert str(터짐.value) == runs.WHY_NOT_APPROVED
    assert 보낸곳.sent == [], "만들기 전에 막습니다 — 보내고 나서가 아닙니다."
    assert 터짐.value.flag is True, "「확인 필요」로 갑니다."


def test_모의_환경이_아니면_한_건도_안_낸다():
    보낸곳 = _보내는곳()
    장부 = _장부(sender=보낸곳, environment="real")

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(장부)

    assert str(터짐.value) == runs.why_environment("paper", "real")
    assert 보낸곳.sent == []


def test_종이_실행은_이_자리를_안_쓴다():
    보낸곳 = _보내는곳()
    장부 = _장부(_실행(mode=runs.PAPER), sender=보낸곳)

    with pytest.raises(sim.SimRefused):
        _내기(장부)

    assert 보낸곳.sent == []


# ── 접수 ────────────────────────────────────────────────


def test_주문번호를_받아_적는다():
    보낸곳 = _보내는곳(order_no="0000098765")
    장부 = _장부(sender=보낸곳)

    주문 = _내기(장부, quantity=2)

    assert 주문.order_no == "0000098765"
    assert (주문.quantity, 주문.remaining, 주문.filled) == (2, 2, 0)
    assert 보낸곳.sent[0]["quantity"] == 2
    assert 보낸곳.sent[0]["order_type"] == "지정가"


def test_주문번호가_없으면_다시_보내지_않는다():
    """나갔는지 모르는 주문을 한 번 더 내면 같은 자리에 둘이 들어갑니다."""
    보낸곳 = _보내는곳(order_no="")
    장부 = _장부(sender=보낸곳)

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(장부)

    assert str(터짐.value) == sim.WHY_NO_ORDER_NO
    assert len(보낸곳.sent) == 1, "한 번 나갔고 다시 안 보냅니다."
    assert 장부.orders == [], "장부에도 안 남깁니다 — 번호가 없어 이을 수가 없습니다."


def test_답을_못_받아도_다시_보내지_않는다():
    보낸곳 = _보내는곳(fails=TimeoutError("응답 없음"))
    장부 = _장부(sender=보낸곳)

    with pytest.raises(sim.SimRefused) as 터짐:
        _내기(장부)

    assert sim.WHY_NO_REPLY in str(터짐.value)
    assert "TimeoutError" in str(터짐.value), "무엇 때문인지도 남습니다."
    assert 장부.orders == []


# ── 체결 ────────────────────────────────────────────────


def test_알림의_체결_수량은_누적이다():
    """그대로 더하면 한 주문이 여러 번 세어집니다."""
    장부 = _장부()
    주문 = _내기(장부, quantity=3)

    첫번 = 장부.on_order(_알림(filled=1, remaining=2, fillPrice=405.25), at=6_000)
    둘번 = 장부.on_order(_알림(filled=3, remaining=0, fillPrice=405.3), at=7_000)

    assert [one["quantity"] for one in 첫번] == [1]
    assert [one["quantity"] for one in 둘번] == [2], "1 에서 3 으로 늘어난 만큼입니다."
    assert 주문.filled == 3 and 주문.status == paper.FILLED


def test_같은_알림이_두_번_와도_한_번만_센다():
    장부 = _장부()
    _내기(장부, quantity=2)

    장부.on_order(_알림(filled=1, remaining=1), at=6_000)
    다시 = 장부.on_order(_알림(filled=1, remaining=1), at=6_100)

    assert 다시 == []


def test_다른_주문번호는_안_받는다():
    """같은 계좌를 보는 실행 모두에 들어가므로 제 것만 골라야 합니다."""
    장부 = _장부()
    주문 = _내기(장부)

    assert 장부.on_order(_알림(id="0000099999", filled=1), at=6_000) == []
    assert 주문.filled == 0


def test_거부되면_닫힌다():
    장부 = _장부()
    주문 = _내기(장부, quantity=2)

    장부.on_order(_알림(status="rejected", filled=0, remaining=2), at=6_000)

    assert 주문.status == paper.CANCELLED
    assert 주문.last_status == "rejected"
    assert 주문.reason.startswith(sim.WHY_REJECTED), "접수 자리의 거부와 같은 글 머리입니다."


def test_공백_중에도_계좌_체결은_받는다():
    """시세 공백과 상관없이 계좌에서 실제로 난 체결입니다. 버리면 주문이 안 닫힙니다."""
    장부 = _장부()
    주문 = _내기(장부)
    장부.gap = True

    (줄,) = 장부.on_order(_알림(filled=1), at=6_000)

    assert 줄["quantity"] == 1
    assert 주문.filled == 1


def test_체결은_계좌가_하고_우리는_값만_따라간다():
    """호가와 체결로는 아무것도 안 채웁니다 — 종이와 다른 자리입니다."""
    장부 = _장부()
    _내기(장부)

    assert 장부.on_trade({"price": 405.5, "quantity": 1}, at=6_000) == []
    assert 장부.on_book({"asks": [], "bids": []}, at=6_000) == []
    assert 장부.last_price == 405.5, "손절·익절이 볼 값은 따라갑니다."


# ── 취소 ────────────────────────────────────────────────


def test_취소는_요청이고_확인이_와야_닫힌다():
    """거부된 취소를 끝난 것으로 적으면 화면에 없는 주문이 계좌에 남습니다."""
    보낸곳 = _보내는곳()
    장부 = _장부(sender=보낸곳)
    주문 = _내기(장부, quantity=2)

    보냈나 = 장부.cancel(주문, "신규 진입 중지로 취소했습니다")

    assert 보냈나 is True
    assert 보낸곳.cancelled == ["0000012345"]
    assert 주문.open is True, "아직 열려 있습니다."
    assert 주문.pending is True and 장부.pending == 1

    장부.on_order(_알림(status="cancelled", filled=0, remaining=2), at=7_000)

    assert 주문.open is False and 장부.pending == 0


def test_계좌가_준_체결번호를_체결_줄에_싣는다():
    """한 주문이 나뉘어 채워지면 **주문번호만으로는 줄을 못 가립니다.**"""
    장부 = _장부()
    _내기(장부, quantity=3)

    첫번 = 장부.on_order(_알림(filled=1, remaining=2, execNo="557"), at=6_000)
    둘번 = 장부.on_order(_알림(filled=3, remaining=0, execNo="558"), at=6_000)

    assert [one["execNo"] for one in 첫번 + 둘번] == ["557", "558"]


def test_알림에_체결번호가_없으면_장부가_매긴다():
    """비워 두면 화면이 체결을 시각으로 가리게 되어 **같은 밀리초의 두 체결이
    한 줄로 뭉칩니다.** 그래서 종이와 같은 규칙으로 장부가 매깁니다.
    """
    장부 = _장부()
    주문 = _내기(장부, quantity=3)

    첫번 = 장부.on_order(_알림(filled=1, remaining=2), at=6_000)
    둘번 = 장부.on_order(_알림(filled=3, remaining=0), at=6_000)

    assert [one["execNo"] for one in 첫번 + 둘번] == [f"{주문.id}#1", f"{주문.id}#2"]


def test_같은_주문에_취소를_두_번_안_낸다():
    보낸곳 = _보내는곳()
    장부 = _장부(sender=보낸곳)
    주문 = _내기(장부)

    장부.cancel(주문, "첫 번")
    다시 = 장부.cancel(주문, "두 번")

    assert 다시 is False
    assert 보낸곳.cancelled == ["0000012345"]


def test_취소를_못_내도_멈추지_않는다():
    class _취소가터짐(_보내는곳):
        def cancel(self, *, run, order):
            raise RuntimeError("취소 실패")

    장부 = _장부(sender=_취소가터짐())
    주문 = _내기(장부)

    assert 장부.cancel(주문, "중지") is False
    assert 주문.cancel_sent is False, "안 나갔으니 확인을 기다리지도 않습니다."
    assert 장부.pending == 0


def test_취소_중_부분체결은_남은_수량으로_잇는다():
    장부 = _장부()
    주문 = _내기(장부, quantity=3)
    장부.cancel(주문, "중지")

    장부.on_order(_알림(status="partial", filled=1, remaining=2), at=7_000)

    assert 주문.filled == 1 and 주문.remaining == 2
    assert 주문.open is True and 장부.pending == 1


# ── 반입해 둔 모의 주문 기록으로 ──────────────────────────


@pytest.fixture
def 재생자리(monkeypatch):
    """저장해 둔 응답으로 도는 접속 자리. **계좌에 나가지 않습니다.**"""
    from backend.nh_api import runtime
    from backend.nh_api.session import create_session

    monkeypatch.setenv("NH_REPLAY", "1")
    runtime.use(create_session(replay=True))
    try:
        yield
    finally:
        runtime.reset()


def _기록된주문() -> dict:
    """반입해 둔 국내 모의 주문 기록 하나."""
    import json
    from pathlib import Path

    root = Path(__file__).parent / "fixtures" / "nh" / "domestic_order"
    for path in sorted(root.rglob("*.json")):
        held = json.loads(path.read_text(encoding="utf-8"))
        ask = held.get("request", {}).get("body") or held.get("request", {})
        if str(ask.get("trd_div")) == "1":
            return {"ask": ask, "reply": held.get("response") or {}}
    pytest.skip("국내 모의 주문 기록이 반입되어 있지 않습니다.")


def _알림들() -> list[dict]:
    """그 주문의 실시간 알림. 접수 → 확인 → 체결로 옵니다."""
    import json
    from pathlib import Path

    from backend.realtime import feeds

    root = Path(__file__).parent / "fixtures" / "nh" / "O1_K"
    made: list[dict] = []
    for path in sorted(root.rglob("*.json")):
        held = json.loads(path.read_text(encoding="utf-8"))
        for event in held.get("events", []):
            payload = event.get("payload")
            if event.get("direction") != "received" or not isinstance(payload, dict):
                continue
            body = payload.get("body")
            if isinstance(body, dict):
                made.append(feeds.order_event(body, context=주간))
    if not made:
        pytest.skip("주문 알림 기록이 반입되어 있지 않습니다.")
    return made


def test_저장해_둔_모의_주문으로_접수_답을_읽는다(재생자리):
    """가짜 `sender` 로는 이 자리를 못 봅니다 — 인자 이름과 값이 맞아야
    저장본이 답합니다."""
    기록 = _기록된주문()
    장부 = sim.SimBroker(
        _실행(code=기록["ask"]["sym"]), sender=sim.NhSender(), environment=lambda: "paper"
    )

    주문 = 장부.place(
        "o1",
        side=paper.BUY,
        quantity=int(기록["ask"]["ord_qty"]),
        order_type="시장가",
        price=None,
        # 주문 기록은 **요청이 통째로 같아야** 답합니다 — 체결조건까지.
        fill_condition="FAS",
        at=5_000,
    )

    assert 주문.order_no == 기록["reply"]["ord_no"], "저장본이 준 주문번호입니다."
    assert 주문.open is True and 주문.filled == 0


def test_시장가는_주문가격을_0_으로_보낸다(재생자리):
    """저장해 둔 요청이 `ord_pric: "0"` 입니다 — 빈 글자면 화면과 달라집니다."""
    기록 = _기록된주문()

    assert 기록["ask"]["ord_pric"] == "0"
    assert sim.price_text(None, 0.05, "2") == "0"
    assert sim.price_text(405.25, 0.05, "2") == "0", "값이 있어도 안 싣습니다."
    assert sim.price_text(405.25, 0.05, "4") == "0", "최유리도 같습니다."


@pytest.mark.parametrize(
    ("price", "tick", "글자"),
    [(405.25, 0.05, "405.25"), (406.0, 1.0, "406"), (3.5, 0.01, "3.50")],
)
def test_지정가는_틱_자릿수만큼_적는다(price, tick, 글자):
    """자릿수가 들쭉날쭉하면 같은 값이 요청마다 다른 글자로 나갑니다."""
    assert sim.price_text(price, tick, "1") == 글자


def test_저장해_둔_알림으로_체결까지_간다(재생자리):
    """접수 → 확인 → 체결이 각각 한 건으로 옵니다."""
    기록 = _기록된주문()
    알림들 = _알림들()
    장부 = sim.SimBroker(
        _실행(code=기록["ask"]["sym"]), sender=sim.NhSender(), environment=lambda: "paper"
    )
    주문 = 장부.place(
        "o1",
        side=paper.BUY,
        quantity=1,
        order_type="시장가",
        price=None,
        fill_condition="FAS",
        at=5_000,
    )
    내것 = [one for one in 알림들 if one.get("id") == 주문.order_no]
    assert 내것, "그 주문번호의 알림이 기록에 있습니다."

    채운것 = []
    for at, one in enumerate(내것):
        채운것 += 장부.on_order(one, at=6_000 + at)

    assert [one["quantity"] for one in 채운것] == [1], "체결 한 건뿐입니다."
    assert 채운것[0]["price"] == 1335.9, "기록의 체결가입니다."
    assert 주문.status == paper.FILLED and 주문.remaining == 0


# ── 취소 왕복 ───────────────────────────────────────────


def test_취소_왕복은_저장해_둔_기록이_없다():
    """**이 자리는 저장본으로 확인하지 못했습니다.**

    주문과 주문내역·잔고내역에는 실제로 주고받은 기록이 있어 재생으로 지나가
    볼 수 있지만, **취소에는 기록이 한 건도 없습니다.** 그래서 취소 접수 답은
    지어낸 값으로 두고, 실제 계좌가 무엇을 주는지는 아직 모릅니다.

    이 시험은 그 「모름」이 조용히 사라지지 않게 잡아 둡니다 — 기록이 들어오면
    여기가 떨어지고, 그때 실제 답으로 `NhSender.cancel` 을 맞추면 됩니다.
    """
    from backend.nh_api.catalog import HTTP_APIS
    from backend.nh_api.fixtures import FixtureStore

    취소길 = {
        (HTTP_APIS[name].method, HTTP_APIS[name].path)
        for name in ("domestic_cancel", "domestic_cancel-night")
    }
    담긴것 = [one for one in FixtureStore.load().http if (one.method, one.path) in 취소길]

    assert 담긴것 == [], "취소 기록이 들어왔습니다. 지어낸 답을 실제 답으로 바꿔 주세요."


def test_취소_접수_답은_주문번호_한_칸뿐이다():
    """기록이 없어 **주문번호만** 받아 둡니다(위 참고).

    계좌가 더 주더라도 우리가 쓰는 것은 이 한 칸이고, 취소가 실제로 됐는지는
    주문/체결 알림으로 확인합니다(§13-3).
    """
    보낸것 = []

    class _부름:
        def cancel(self, sym, *, org_ord_no, trd_div, ord_qty, night=False, environment=None):
            보낸것.append({"sym": sym, "org_ord_no": org_ord_no, "ord_qty": ord_qty})
            return {"ord_no": "5959762237", "더": "쓰지 않는 칸"}

    보냄 = sim.NhSender()
    주문 = sim.SimOrder(id="o1", side=paper.BUY, quantity=2, order_type="지정가")
    주문.order_no = "5959762237"
    실행 = _실행()

    import backend.domestic_futureoption.domestic_futureoption_functions as 진짜

    이전 = 진짜.cancel
    진짜.cancel = _부름().cancel
    try:
        답 = 보냄.cancel(run=실행, order=주문)
    finally:
        진짜.cancel = 이전

    assert 답 == {"id": "5959762237"}
    assert 보낸것[0]["ord_qty"] == "2", "남은 수량으로 냅니다."


def test_스탑_가격을_주문에도_담는다():
    """계좌로 함께 나간 값입니다. 안 담으면 걸어 둔 주문의 발동가를 우리가 모릅니다."""
    보내는곳 = _보내는곳()
    장부 = _장부(sender=보내는곳)

    낸것 = _내기(장부, order_type="STOP-L", price=405.25, stop_price=405.0)

    assert 낸것.stop_price == 405.0
    assert 보내는곳.sent[-1]["stop_price"] == 405.0, "보내는 값과 같은 값입니다."


def test_스탑이_아니면_비어_있다():
    assert _내기(_장부()).stop_price is None


# ── 화면에 내는 줄 ──────────────────────────────────────


def test_모의_실행도_같은_줄을_낸다():
    """**모의 주문은 계좌에 나가 있습니다.** 줄을 못 내면 그 실행 하나로 끝나지
    않습니다 — 한 박자 묶음이 통째로 안 나가 화면이 멈춰 보입니다.
    """
    실행 = _실행()
    장부 = _장부(실행)
    돌리는것 = engine_lib.RunEngine(실행, tick=0.05, book=장부)
    _내기(장부, order_type="STOP-L", price=405.25, stop_price=405.0)
    돌리는것._purpose["o1"] = "entry"

    (줄,) = 돌리는것.open_orders

    assert 줄["orderId"] == "o1" and 줄["runId"] == "r1"
    assert 줄["orderType"] == "STOP-L"
    assert 줄["price"] == 405.25
    assert 줄["stopPrice"] == 405.0, "걸어 둔 발동가를 화면이 읽을 수 있어야 합니다."
    assert 줄["quantity"] == 1 and 줄["remaining"] == 1
    assert 줄["status"] == paper.WAITING
    assert 돌리는것.snapshot()["openOrders"] == [줄], "한 벌에도 같은 줄이 실립니다."


def test_채워지면_모의_실행도_목록에서_빠진다():
    실행 = _실행()
    장부 = _장부(실행)
    돌리는것 = engine_lib.RunEngine(실행, tick=0.05, book=장부)
    _내기(장부)
    돌리는것._purpose["o1"] = "entry"

    장부.on_order(_알림(status="filled", filled=1, remaining=0, price=405.25), at=6_000)

    assert 돌리는것.open_orders == []


def test_모의_주문에는_가상_표지를_안_단다():
    """**계좌에 나가 있는 주문입니다.** 「가상」으로 적으면 사용자가 실제로 걸린
    주문을 지어낸 것으로 읽습니다.
    """
    실행 = _실행()
    장부 = _장부(실행)
    돌리는것 = engine_lib.RunEngine(실행, tick=0.05, book=장부)
    _내기(장부)
    돌리는것._purpose["o1"] = "entry"

    (줄,) = 돌리는것.open_orders

    assert 돌리는것.virtual is False
    assert 줄["virtual"] is False


def test_모의_체결에도_가상_표지를_안_단다():
    """**계좌가 채운 체결입니다** — 알림(`on_order`)으로 들어옵니다. 표지가
    주문 줄과 갈리면 한 주문이 표마다 다르게 섭니다.
    """
    실행 = _실행()
    장부 = _장부(실행)
    돌리는것 = engine_lib.RunEngine(실행, tick=0.05, book=장부)
    _내기(장부)
    돌리는것._purpose["o1"] = "entry"

    돌리는것.on_order(_알림(status="filled", filled=1, remaining=0, price=405.25), at=6_000)

    (체결,) = 돌리는것.fills
    assert 체결["virtual"] is False
