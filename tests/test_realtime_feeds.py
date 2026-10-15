"""실시간 메시지가 화면 모양으로 바뀌는지 — 반입해 둔 실제 메시지로 확인합니다."""
from __future__ import annotations

import pytest

from backend import quotes
from backend.nh_api.fixtures import load_fixtures
from backend.realtime import feeds
from backend.realtime.feeds import Feed
from backend.sessions.hours import KST


@pytest.fixture(scope="module")
def store():
    return load_fixtures()


def bodies(store, api_id: str) -> list[dict]:
    """반입해 둔 기록에서 자료 메시지 본문만 꺼냅니다."""
    made = []
    for fixture in store.streams:
        if fixture.api_id != api_id:
            continue
        for event in fixture.received:
            payload = event.payload
            if isinstance(payload, dict) and isinstance(payload.get("body"), dict):
                made.append(payload["body"])
    return made


# ── 구독 이름 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("context", "kind", "api_id"),
    [
        ("domestic-day", "quote", "KA"),
        ("domestic-day", "book", "KB"),
        ("domestic-night", "quote", "KC"),
        ("domestic-night", "book", "KD"),
        ("overseas", "quote", "FA"),
        ("overseas", "book", "FB"),
        ("domestic-day", "orders", "O1_K"),
        ("overseas", "orders", "O1"),
    ],
)
def test_맥락과_종류가_실시간_이름을_정한다(context, kind, api_id):
    feed = Feed(context, kind, "" if kind == "orders" else "A7569000")
    assert feed.api_id == api_id


def test_국내_주문체결은_이름과_보내는_값이_다르다():
    feed = Feed("domestic-day", "orders")
    assert feed.api_id == "O1_K"
    assert feed.action_code == "O1"


def test_주간과_야간의_주문체결은_같은_구독이다():
    from backend.realtime.ledger import stream_key

    assert stream_key(Feed("domestic-day", "orders")) == stream_key(
        Feed("domestic-night", "orders")
    )


def test_주문체결에_종목을_주면_막는다():
    with pytest.raises(ValueError):
        Feed("domestic-day", "orders", "A7569000")


def test_시세에_종목이_없으면_막는다():
    with pytest.raises(ValueError):
        Feed("domestic-day", "quote", "")


def test_모르는_맥락과_종류를_막는다():
    with pytest.raises(ValueError):
        Feed("domestic", "quote", "A7569000")
    with pytest.raises(ValueError):
        Feed("domestic-day", "candles", "A7569000")


# ── 시세 ────────────────────────────────────────────────────


def test_반입해_둔_국내_시세가_화면_항목으로_바뀐다(store):
    body = bodies(store, "KA")[0]
    patch = feeds.quote_patch(body, context="domestic-day")

    assert patch["last"] == float(body["last_pric"])
    assert patch["changePct"] == float(body["rt"])
    assert patch["volume"] == int(float(body["cum_trd_qty"]))
    assert patch["openInterest"] == int(float(body["opint"]))
    assert patch["upperLimit"] == float(body["up_act_pric"])


def test_전일대비는_실시간에서_이름이_다르다(store):
    body = bodies(store, "KA")[0]
    patch = feeds.quote_patch(body, context="domestic-day")
    # 조회는 `chg` 였고 실시간은 `diff_rt` 입니다.
    assert patch["change"] == float(body["diff_rt"])


def test_시세는_Quote_전체가_아니다(store):
    body = bodies(store, "KA")[0]
    patch = feeds.quote_patch(body, context="domestic-day")
    # 실시간에 오지 않는 항목입니다. 담으면 조회로 받아 둔 값이 지워집니다.
    for absent in ("name", "multiplier", "lastTradingDay", "daysLeft", "lifeHigh"):
        assert absent not in patch


def test_해외_시세에는_국내만_오는_항목이_없다(store):
    body = bodies(store, "FA")[0]
    patch = feeds.quote_patch(body, context="overseas")

    assert patch["last"] == float(body["last_pric"])
    for absent in ("upperLimit", "lowerLimit", "theory", "iv", "spot", "turnover"):
        assert absent not in patch


def test_현물가가_0_이면_없음으로_낸다():
    # 야간은 값과 상관없이 비워 싣습니다(아래 시험). 「0 이면 칸 없음」은 주간 규칙입니다.
    patch = feeds.quote_patch({"und_last_pric": "0.00"}, context="domestic-day")
    assert "spot" not in patch


#: 모의 야간 체결에서 받은 값의 모양 — 기초자산현재가가 현물 지수가 아닌 수로 옵니다.
_야간체결 = {"last_pric": "1102.20", "und_last_pric": "560.74", "mkt_bas": "541.46", "theo_pric": "1094.45", "dev_rt": "0.71"}


def test_야간_실시간은_현물가와_베이시스를_비워_싣는다():
    """칸을 빼면 주간에 받아 둔 값이 야간 화면에 남습니다 — null 로 싣습니다."""
    patch = feeds.quote_patch(dict(_야간체결), context="domestic-night")

    assert "spot" in patch and patch["spot"] is None
    assert "basisActual" in patch and patch["basisActual"] is None
    # 나머지는 그대로입니다.
    assert (patch["last"], patch["theory"], patch["disparity"]) == (1102.2, 1094.45, 0.71)


def test_주간_실시간의_현물가와_베이시스는_그대로다():
    patch = feeds.quote_patch(dict(_야간체결), context="domestic-day")

    assert (patch["spot"], patch["basisActual"]) == (560.74, 541.46)


def test_시세의_예상체결가는_0_이면_null_로_지운다(store):
    """동시호가 때 받은 예상체결가가 접속매매로 돌아온 뒤에도 남으면 안 됩니다."""
    body = bodies(store, "KA")[0]
    # 저장 기록은 접속매매 중이라 0 으로 옵니다 — 칸은 있되 값은 없음.
    patch = feeds.quote_patch(body, context="domestic-day")
    assert "expectedPrice" in patch and patch["expectedPrice"] is None

    동시호가 = feeds.quote_patch({**body, "est_exec_pric": "1338.50"}, context="domestic-day")
    assert 동시호가["expectedPrice"] == 1338.5
    # 칸 자체가 없는 메시지에는 담지 않습니다.
    assert "expectedPrice" not in feeds.quote_patch({"last_pric": "1.0"}, context="domestic-day")


def test_거래대금은_백만_단위_그대로_낸다(store):
    body = bodies(store, "KA")[0]
    patch = feeds.quote_patch(body, context="domestic-day")
    assert patch["turnover"] == float(body["cum_trd_amt"])


# ── 체결 ────────────────────────────────────────────────────


def test_반입해_둔_국내_체결이_한_건으로_나온다(store):
    body = bodies(store, "KA")[0]
    trade = feeds.trade_of(body, context="domestic-day")

    assert trade["price"] == float(body["last_pric"])
    assert trade["quantity"] == int(float(body["exec_qty"]))
    stamp = body["exch_tm"]
    assert trade["time"] == f"{stamp[0:2]}:{stamp[2:4]}:{stamp[4:6]}"


def test_국내는_틱구분이_1_인_것만_체결이다():
    body = {"tick_div": "0", "exec_qty": "5", "last_pric": "100"}
    assert feeds.trade_of(body, context="domestic-day") is None


def test_틱구분이_1_이_아니어도_시세_값은_갈아_끼운다():
    body = {"tick_div": "0", "exec_qty": "0", "last_pric": "100"}
    assert feeds.quote_patch(body, context="domestic-day")["last"] == 100


def test_해외에는_틱구분_규칙이_없다(store):
    body = bodies(store, "FA")[0]
    trade = feeds.trade_of(body, context="overseas")
    assert trade is not None
    assert trade["quantity"] == int(float(body["exec_qty"]))


def test_체결량이_0_이면_체결이_아니다():
    body = {"tick_div": "1", "exec_qty": "0", "last_pric": "100"}
    assert feeds.trade_of(body, context="domestic-day") is None


def test_국내_체결의_순간은_받은_날짜에_시각을_붙인_것이다(store):
    """국내 실시간에는 날짜가 없어 받은 순간의 날짜를 씁니다 — 조회 봉과 같은 시계."""
    from datetime import datetime

    body = bodies(store, "KA")[0]
    received = datetime(2026, 9, 9, 15, 21, 30, tzinfo=KST)
    trade = feeds.trade_of(body, context="domestic-day", received=received)

    assert trade["timestamp"] == quotes.timestamp("20260909", body["exch_tm"])
    # 봉 열쇠(분의 시작)는 체결 시각의 분과 같습니다 — 반입해 둔 체결 전부.
    for b in bodies(store, "KA"):
        made = feeds.trade_of(b, context="domestic-day", received=received)
        if made is None:
            continue
        minute = b["exch_tm"][:4] + "00"
        assert made["timestamp"] // 60000 * 60000 == quotes.timestamp("20260909", minute)


def test_자정_언저리의_국내_체결은_가까운_날로_앉는다():
    """23:59:59 체결이 자정 직후에 오면 어제, 00:00:01 체결이 자정 직전에 오면 내일입니다."""
    from datetime import datetime

    late = {"tick_div": "1", "exec_qty": "1", "last_pric": "100", "exch_tm": "235959"}
    just_after = datetime(2026, 9, 10, 0, 0, 0, 300000, tzinfo=KST)
    assert feeds.trade_of(late, context="domestic-night", received=just_after)["timestamp"] == (
        quotes.timestamp("20260909", "235959")
    )
    early = {"tick_div": "1", "exec_qty": "1", "last_pric": "100", "exch_tm": "000001"}
    just_before = datetime(2026, 9, 9, 23, 59, 59, tzinfo=KST)
    assert feeds.trade_of(early, context="domestic-night", received=just_before)["timestamp"] == (
        quotes.timestamp("20260910", "000001")
    )
    # 보통 때는 받은 날짜 그대로입니다.
    noon = datetime(2026, 9, 9, 12, 0, tzinfo=KST)
    plain = {"tick_div": "1", "exec_qty": "1", "last_pric": "100", "exch_tm": "115959"}
    assert feeds.trade_of(plain, context="domestic-day", received=noon)["timestamp"] == (
        quotes.timestamp("20260909", "115959")
    )


def test_해외_체결의_시각은_한국시각이다(store):
    """`exch_tm` 은 거래소 현지 시각입니다 — 조회 봉(한국시간)과 맞추려면 `ko_exec_tm`."""
    body = bodies(store, "FA")[0]
    trade = feeds.trade_of(body, context="overseas")

    ko = body["ko_exec_tm"]
    assert trade["time"] == f"{ko[0:2]}:{ko[2:4]}:{ko[4:6]}"
    assert trade["time"] != f"{body['exch_tm'][0:2]}:{body['exch_tm'][2:4]}:{body['exch_tm'][4:6]}"
    assert trade["timestamp"] == quotes.timestamp(body["ko_trd_dt"], ko)
    # 한국시각 칸이 없으면 현지 시각으로 대신하지 않고 비웁니다.
    without = {k: v for k, v in body.items() if k not in ("ko_exec_tm", "ko_trd_dt")}
    bare = feeds.trade_of(without, context="overseas")
    assert "time" not in bare and "timestamp" not in bare


def test_봉의_시각은_컴퓨터_시간대와_무관하게_한국시간이다():
    """2026-09-09 09:00 KST = 2026-09-09 00:00 UTC."""
    import calendar

    utc_midnight = calendar.timegm((2026, 9, 9, 0, 0, 0)) * 1000
    assert quotes.timestamp("20260909", "090000") == utc_midnight
    assert quotes.timestamp("20260909") == utc_midnight - 9 * 3600 * 1000


def test_체결의_매수매도는_정하지_않고_받은_글자를_올린다(store):
    domestic = feeds.trade_of(bodies(store, "KA")[0], context="domestic-day")
    overseas = feeds.trade_of(bodies(store, "FA")[0], context="overseas")

    # 명세에 체결구분의 뜻이 없어 매수·매도를 만들지 않습니다.
    assert "side" not in domestic
    assert "side" not in overseas
    assert domestic["sideCode"]
    assert overseas["sideCode"]


# ── 호가 ────────────────────────────────────────────────────


def test_반입해_둔_국내_호가가_다섯_단계로_나온다(store):
    body = bodies(store, "KB")[0]
    book = feeds.book_of(body, context="domestic-day")

    # 열 단계가 오지만 이 종목은 다섯 단계만 채워져 있습니다.
    assert len(book["asks"]) == 5
    assert len(book["bids"]) == 5


def test_호가는_매도를_뒤집어_먼_값부터_낸다(store):
    body = bodies(store, "KB")[0]
    book = feeds.book_of(body, context="domestic-day")

    asks = [level["price"] for level in book["asks"]]
    bids = [level["price"] for level in book["bids"]]
    assert asks == sorted(asks, reverse=True)
    assert bids == sorted(bids, reverse=True)
    # 최우선 매도는 배열의 끝입니다. 주문 단추가 여기서 값을 뽑습니다.
    assert asks[-1] == float(body["ask_pric_1"])
    assert bids[0] == float(body["bid_pric_1"])


def test_값이_안_채워진_호가_단계는_뺀다():
    body = {f"{side}_pric_{i}": "0.00" for side in ("ask", "bid") for i in range(1, 11)}
    book = feeds.book_of(body, context="domestic-day")
    assert book["asks"] == []
    assert book["bids"] == []


def test_호가의_예상체결가는_비어_오면_null_로_지운다(store):
    body = bodies(store, "KB")[0]
    # 저장 기록은 접속매매 중이라 빈 값으로 옵니다 — 칸은 있되 값은 없음.
    book = feeds.book_of(body, context="domestic-day")
    assert "expectedPrice" in book and book["expectedPrice"] is None

    동시호가 = feeds.book_of({**body, "est_exec_pric": "1338.50"}, context="domestic-day")
    assert 동시호가["expectedPrice"] == 1338.5


def test_해외_호가는_다섯_단계까지만_읽는다(store):
    body = bodies(store, "FB")[0]
    book = feeds.book_of(body, context="overseas")

    assert len(book["asks"]) <= 5
    assert len(book["bids"]) <= 5
    assert book["bids"][0]["price"] == float(body["bid_pric_1"])
    # 해외 호가에는 예상체결가 칸이 없습니다.
    assert "expectedPrice" not in book


def test_해외_호가의_시각은_한국시각_칸에서_온다(store):
    """`exch_tm` 은 거래소 현지 시각이라 한국시각 `ko_exec_tm` 을 씁니다."""
    body = bodies(store, "FB")[0]
    # 반입해 둔 기록은 CME 현지 19:17, 한국 09:17 입니다.
    assert body["exch_tm"] == "191730"
    assert body["ko_exec_tm"] == "091730"

    assert feeds.book_of(body, context="overseas")["time"] == "09:17:30"


def test_해외_호가의_한국시각이_비면_현지_시각으로_채우지_않는다(store):
    body = {**bodies(store, "FB")[0], "ko_exec_tm": ""}
    assert "time" not in feeds.book_of(body, context="overseas")


def test_국내_호가의_시각은_exch_tm_그대로다(store):
    """국내 거래소 시각은 한국시각이라 그대로 씁니다."""
    body = bodies(store, "KB")[0]
    book = feeds.book_of(body, context="domestic-day")
    raw = body["exch_tm"]
    assert book["time"] == f"{raw[:2]}:{raw[2:4]}:{raw[4:]}"


def test_조회와_실시간의_호가_규칙이_같다(store):
    """같은 규칙을 한 자리에서 쓰는지 — 두 경로가 갈리면 호가창이 달라집니다."""
    from backend.domestic_futureoption.domestic_quotes import book as rest_book

    body = bodies(store, "KB")[0]
    live = feeds.book_of(body, context="domestic-day")
    same = rest_book(
        {
            "Occurs1": [
                {
                    "occurs1_ask_best_pric": body.get(f"ask_pric_{i}"),
                    "occurs1_ask_qty": body.get(f"ask_qty_{i}"),
                    "occurs1_bid_best_pric": body.get(f"bid_pric_{i}"),
                    "occurs1_bid_qty": body.get(f"bid_qty_{i}"),
                }
                for i in range(1, 11)
            ]
        }
    )
    assert live["asks"] == same["asks"]
    assert live["bids"] == same["bids"]


# ── 주문/체결 알림 ───────────────────────────────────────────


def test_반입해_둔_주문알림이_화면_모양으로_나온다(store):
    events = [feeds.order_event(b, context="domestic-day") for b in bodies(store, "O1_K")]
    assert events

    first = events[0]
    assert first["market"] == "domestic"
    assert first["side"] == "buy"
    assert first["status"] == "accepted"
    assert first["quantity"] == 1


def test_주문알림이_접수에서_체결까지_이어진다(store):
    events = [feeds.order_event(b, context="domestic-day") for b in bodies(store, "O1_K")]
    first_order = events[0]["id"]
    steps = [e["status"] for e in events if e["id"] == first_order]
    assert steps == ["accepted", "confirmed", "filled"]


def test_체결된_주문에_체결가와_시각이_담긴다(store):
    events = [feeds.order_event(b, context="domestic-day") for b in bodies(store, "O1_K")]
    filled = [e for e in events if e["status"] == "filled"]
    assert filled
    assert filled[0]["fillPrice"] > 0
    assert filled[0]["filled"] == 1
    assert filled[0]["remaining"] == 0
    assert filled[0]["time"]


def test_체결_알림만_체결번호를_싣는다(store):
    """반입해 둔 알림에서 **접수 줄은 `0000000000`**, 체결 줄만 실제 번호입니다.

    0 을 번호로 담으면 접수 알림들이 서로 같은 번호를 갖게 되어, 체결을 가리려고
    둔 칸이 오히려 줄을 뭉칩니다.
    """
    events = [feeds.order_event(b, context="domestic-day") for b in bodies(store, "O1_K")]
    filled = [e for e in events if e["status"] == "filled"]
    assert filled, "반입 기록에 체결 줄이 있어야 이 시험이 섭니다."

    assert all(one["execNo"] and set(one["execNo"]) != {"0"} for one in filled)
    assert all("execNo" not in e for e in events if e["status"] != "filled")


def test_시장가_주문의_주문가격은_없음이다(store):
    events = [feeds.order_event(b, context="domestic-day") for b in bodies(store, "O1_K")]
    assert all("price" not in e for e in events)


def test_가격조건은_국내와_해외의_뜻이_다르다():
    body = {"pric_cnd": "2"}
    assert feeds.order_event(body, context="domestic-day")["orderType"] == "시장가"
    assert feeds.order_event(body, context="overseas")["orderType"] == "지정가"


def 알림(**덮어쓰기):
    """우리 매체로 낸, 잔량 남은, 접수 상태의 주문 알림 하나."""
    몸 = {"med_div": "R", "ord_sts": "1", "ord_qty": "3", "rem_ord_qty": "3"}
    몸.update(덮어쓰기)
    return feeds.order_event(몸, context="domestic-day")


def test_다른_길로_낸_주문은_화면에서_못_고친다():
    assert 알림()["editable"] is True
    남의것 = 알림(med_div="H")
    assert 남의것["editable"] is False
    assert 남의것["source"] == "HTS"


def test_체결이_끝난_알림은_못_고친다():
    """**화면이 목록 위에 알림을 이어 붙입니다.**

    여기서 매체만 보고 참을 내면, 주문내역 줄이 거짓으로 정한 값을 알림이
    덮어 끝난 주문에 정정 단추가 다시 섭니다.
    """
    for 끝난상태 in ("6", "8", "9"):
        assert 알림(ord_sts=끝난상태, rem_ord_qty="0")["editable"] is False, 끝난상태

    # 부분체결은 아직 고칠 수 있습니다.
    assert 알림(ord_sts="4", exec_qty="1", rem_ord_qty="2")["editable"] is True


def test_알림도_잔량을_모르면_못_고친다():
    assert 알림(rem_ord_qty="0")["editable"] is False
    assert 알림(rem_ord_qty="")["editable"] is False
    없는것 = feeds.order_event({"med_div": "R", "ord_sts": "1"}, context="domestic-day")
    assert "remaining" not in 없는것
    assert 없는것["editable"] is False


#: 같은 주문을 두 길로 받았을 때. (매체, 상태, 잔량, 고칠 수 있나)
#:
#: **앞의 둘이 화면에서 목록 값을 덮던 자리입니다** — 실시간이 참, 주문내역이
#: 거짓이라 알림이 닿는 순간 끝난 주문에 정정 단추가 다시 섰습니다.
같은주문 = [
    ("R", "6", "0", False),
    ("R", "1", None, False),
    ("R", "4", "1", True),
    ("H", "1", "1", False),
]


@pytest.mark.parametrize("매체,상태,잔량,기대", 같은주문)
def test_알림과_주문내역이_같은_규칙으로_고칠_수_있는지_정한다(매체, 상태, 잔량, 기대):
    """두 값이 같은 자리를 채웁니다 — 한쪽만 고쳐지면 화면이 덮어씁니다."""
    from backend.domestic_futureoption import domestic_account

    실시간몸 = {"med_div": 매체, "ord_sts": 상태}
    주문내역줄 = {"occurs1_med_div": 매체, "occurs1_ord_sts": 상태}
    if 잔량 is not None:
        실시간몸["rem_ord_qty"] = 잔량
        주문내역줄["occurs1_rem_ord_qty"] = 잔량

    알림값 = feeds.order_event(실시간몸, context="domestic-day")["editable"]
    줄값 = domestic_account.order_history({"Occurs1": [주문내역줄]})["orders"][0]["editable"]

    assert 알림값 == 줄값 == 기대


def test_두_길의_표가_같다():
    from backend.domestic_futureoption import domestic_account

    assert feeds.FINISHED_STATUS == domestic_account.FINISHED_STATUS
    assert feeds.OWN_SOURCE == domestic_account.OWN_SOURCE


def test_모르는_코드는_원문을_남기고_뜻은_비운다():
    made = feeds.order_event({"ord_sts": "7", "trd_div": "9"}, context="domestic-day")
    assert made["statusCode"] == "7"
    assert "status" not in made
    assert made["sideCode"] == "9"
    assert "side" not in made


def test_주문알림에는_밤낮_구분이_없다():
    day = feeds.order_event({"ord_no": "1"}, context="domestic-day")
    night = feeds.order_event({"ord_no": "1"}, context="domestic-night")
    assert day == night
    assert day["market"] == "domestic"


def test_주문알림_칸_이름이_화면_타입을_따른다():
    """주문내역 조회와 한 벌이어야 화면이 목록 위에 이어 붙일 수 있습니다."""
    made = feeds.order_event({"ord_no": "7", "sym": "A7569000"}, context="domestic-day")

    assert made["id"] == "7"
    assert made["code"] == "A7569000"
    # 옛 이름이 되살아나면 화면이 두 벌을 다루게 됩니다.
    for 옛이름 in ("orderNo", "sym", "priceCondition", "priceConditionCode"):
        assert 옛이름 not in made


def test_주문_종류는_명세의_한글_이름으로_낸다():
    """조회는 이름 칸으로 바로 오고 실시간은 코드만 옵니다. 낸 값은 같아야 합니다."""
    made = feeds.order_event({"pric_cnd": "1"}, context="domestic-day")
    assert made["orderType"] == "지정가"
    assert made["orderTypeCode"] == "1"

    바다 = feeds.order_event({"pric_cnd": "3"}, context="overseas")
    assert 바다["orderType"] == "STOP시장가"


def test_실시간_주문_알림도_원주문번호_규칙이_조회와_같다():
    같은번호 = feeds.order_event({"ord_no": "5959762237", "org_ord_no": "5959762237"}, context="domestic-day")
    영 = feeds.order_event({"ord_no": "0000000119", "org_ord_no": "0000000000"}, context="overseas")
    정정 = feeds.order_event({"ord_no": "0000000119", "org_ord_no": "0000000118"}, context="overseas")

    assert "originalOrderNo" not in 같은번호
    assert "originalOrderNo" not in 영
    assert 정정["originalOrderNo"] == "0000000118"


def test_국내_체결과_호가만_주간_야간_짝이_있다():
    from backend.realtime.feeds import Feed, paired

    assert paired(Feed("domestic-day", "quote", "A1")) == Feed("domestic-night", "quote", "A1")
    assert paired(Feed("domestic-night", "book", "A1")) == Feed("domestic-day", "book", "A1")
    assert paired(Feed("overseas", "quote", "ESZ26")) is None
    assert paired(Feed("domestic-day", "orders")) is None
