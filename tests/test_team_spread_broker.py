"""스프레드용으로 넓힌 공유 부품 시험 — 수량 주문 브로커(`fill(..., qty=)`)와 해외 어댑터의 거래소·통화 코드.

파이썬 전략 탭은 늘 1계약이라 기본값 그대로 동작해야 한다. 여기서는 qty>1 일 때 체결 뒤 보유·`blind`·`unresolved`
의 `post` 가 qty 만큼 움직이는지, qty<1 이 주문 전에 거절되는지를 가짜 해외 api 로 본다."""
import pytest

from backend.nh_api.errors import TransportError
from backend.team_pyrun.markets import OVERSEAS, adapter, adapter_for
from tests.test_team_pyrun_markets import MKU, FakeOvsApi, ovs_broker


def test_수량_3계약_체결_뒤_보유가_3_늘어야_통과(tmp_path):
    fake = FakeOvsApi()
    b = ovs_broker(tmp_path, fake, exp=[0])
    px = b.fill("buy", 0.7447, "101500", "진입", qty=3)
    assert px is not None
    assert fake.orders == [(MKU, "buy", 3)]       # 한 번, 3계약
    assert fake.held == 3 and b.position() == 3
    assert b.blind is None and b.unresolved is None


def test_수량_주문_결과_모름이면_blind_의_post_는_qty_만큼(tmp_path):
    fake = FakeOvsApi()
    fake.held = 2
    fake.fill = False
    fake.order_error = TransportError("overseas_order", "응답 없음")
    b = ovs_broker(tmp_path, fake, exp=[2])
    assert b.fill("sell", 0.7447, "101500", "청산", qty=2) is None
    assert b.blind == {"side": "sell", "pre": 2, "post": 0}
    assert len(fake.orders) == 1


def test_수량_주문_번호_없는_응답도_blind_post_는_qty_만큼(tmp_path):
    fake = FakeOvsApi()
    fake.fill = False
    fake.reply = {"ord_no": "", "err_cd": "00000"}
    b = ovs_broker(tmp_path, fake, exp=[0])
    assert b.fill("buy", 0.7447, "101500", "진입", qty=4) is None
    assert b.blind == {"side": "buy", "pre": 0, "post": 4}


def test_수량_2계약_접수_미확인은_잔고가_pre_플러스_2일_때만_풀린다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "2"                  # 접수만 — 15초가 지나도 전체체결이 아님
    exp = [0]
    b = ovs_broker(tmp_path, fake, exp=exp)
    assert b.fill("buy", 0.7447, "101500", "진입", qty=2) is None
    assert (b.unresolved_pre, b.unresolved_post, b.unresolved_side) == (0, 2, "buy")

    # 주문내역은 체결, 잔고는 1계약만(부분 반영) — pre±1 이므로 풀리지 않고 blind 로 바뀌어 계속 막는다
    fake.history[0]["ord_sts"] = "6"
    fake.held = 1
    assert b.fill("sell", 0.7447, "101501", "청산", qty=2) is None
    assert b.unresolved is None and b.blind is not None and b.blind["post"] == 2
    assert len(fake.orders) == 1

    # 잔고가 pre+2 를 보이면 blind 가 풀린다(그 다음 주문은 잔고 관문에 맡김)
    fake.held = 2
    exp[0] = 2
    fake.status = "6"
    assert b.fill("sell", 0.7447, "101502", "청산", qty=2) is not None
    assert b.blind is None and len(fake.orders) == 2
    assert fake.held == 0


def test_수량_2계약_접수_미확인_후_잔고가_pre_플러스_2면_바로_풀린다(tmp_path):
    fake = FakeOvsApi()
    fake.status = "2"
    exp = [0]
    b = ovs_broker(tmp_path, fake, exp=exp)
    assert b.fill("buy", 0.7447, "101500", "진입", qty=2) is None
    fake.history[0]["ord_sts"] = "6"
    fake.held = 2
    exp[0] = 2
    fake.status = "6"
    assert b.fill("sell", 0.7447, "101501", "청산", qty=2) is not None
    assert b.unresolved is None and fake.held == 0


@pytest.mark.parametrize("qty", [0, -1])
def test_수량이_1_미만이면_주문_전에_ValueError(tmp_path, qty):
    fake = FakeOvsApi()
    b = ovs_broker(tmp_path, fake)
    with pytest.raises(ValueError):
        b.fill("buy", 0.7447, "101500", "진입", qty=qty)
    assert fake.orders == [] and fake.calls == []


def test_기본_수량은_1계약(tmp_path):
    fake = FakeOvsApi()
    b = ovs_broker(tmp_path, fake)
    assert b.fill("buy", 0.7447, "101500", "진입") is not None
    assert fake.orders == [(MKU, "buy", 1)]


class FakeCmeApi(FakeOvsApi):
    """거래소·통화 코드를 받는 해외 api 가짜."""

    def ovs_price(self, sym, *, exch_cd="FSGX"):
        self.calls.append(("ovs_price", sym, exch_cd))
        return {"last_pric": "2.5", "sym": sym}

    def ovs_chart_minute(self, sym, *, req_qty, exch_cd="FSGX"):
        self.calls.append(("ovs_chart_minute", sym, req_qty, exch_cd))
        return []


def test_해외_어댑터는_거래소_코드를_차트와_현재가에_넘긴다():
    fake = FakeCmeApi()
    a = adapter_for(OVERSEAS, fake, exch_cd="FCME", cur_cd="USD")
    a.price("HOZ26")
    a.chart_minute("HOZ26", req_qty=5)
    assert ("ovs_price", "HOZ26", "FCME") in fake.calls
    assert ("ovs_chart_minute", "HOZ26", 5, "FCME") in fake.calls


def test_해외_어댑터는_통화_코드를_예수금에_넘긴다():
    fake = FakeOvsApi()
    adapter_for(OVERSEAS, fake, cur_cd="EUR").deposit("20261109")
    assert ("ovs_deposit", "EUR", "20261109") in fake.calls


def test_코드를_안_주면_지금처럼_기본값을_쓴다():
    fake = FakeCmeApi()
    a = adapter_for(OVERSEAS, fake)
    a.price(MKU)
    assert fake.calls[-1] == ("ovs_price", MKU, "FSGX")     # 인자를 안 넘김 — 가짜의 기본값이 찍힌 것
    plain = FakeOvsApi()                                     # exch_cd 를 모르는 가짜도 그대로 동작
    adapter(OVERSEAS, plain).price(MKU)
    assert plain.calls[-1] == ("ovs_price", MKU)
