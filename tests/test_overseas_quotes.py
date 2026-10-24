"""해외 시세 응답이 화면 모양으로 바뀌는지.

**저장소에 해외 시세 기록이 있습니다**(현재가·호가·분봉·일봉). 계좌 쪽과 달리
여기서는 저장해 둔 실제 응답으로 봅니다 — 값이 아니라 **모양과 규칙**을 봅니다.
"""
from __future__ import annotations

import json

from backend import quotes
from backend.nh_api.fixtures import FIXTURE_ROOT
from backend.overseas_futureoption import overseas_quotes


def 반입본(api: str) -> list[dict]:
    """그 API 로 저장해 둔 응답 전부."""
    return [
        json.loads(경로.read_text(encoding="utf-8"))["response"]
        for 경로 in sorted((FIXTURE_ROOT / api).rglob("*.json"))
    ]


def 현재가줄(자리: int = 0) -> dict:
    return 반입본("overseas_price")[자리]["Occurs1"][0]


# ── 현재가 ──────────────────────────────────────────────────


def test_국내와_같은_칸_이름을_쓴다():
    """화면의 시세 카드가 시장을 가리지 않고 같은 이름을 읽습니다."""
    from backend.domestic_futureoption import domestic_quotes

    해외 = overseas_quotes.quote(현재가줄(), asked="MESU26")
    국내 = domestic_quotes.quote({"sym_exch": "A7569000"}, asked="A7569000")

    빠진것 = set(국내) - set(해외)
    assert 빠진것 == set(), f"국내에 있는 칸이 해외에 없습니다: {빠진것}"


def test_해외에_없는_값은_비워서_낸다():
    """칸을 빼면 화면이 `undefined` 를 만납니다. 예수금(목록)과 다른 자리입니다."""
    한줄 = overseas_quotes.quote(현재가줄(), asked="MESU26")

    for 없는것 in ("openInterest", "iv", "upperLimit", "spot", "theory", "multiplier"):
        assert 없는것 in 한줄
        assert 한줄[없는것] is None


def test_등락폭과_등락률을_안_바꿔_담는다():
    """`occurs1_diff_rt` 는 이름이 `rt` 로 끝나지만 등락폭입니다."""
    원문 = 현재가줄()
    한줄 = overseas_quotes.quote(원문, asked="MESU26")

    assert 한줄["change"] == float(원문["occurs1_diff_rt"])
    assert 한줄["changePct"] == float(원문["occurs1_rt"])


def test_최종결제일은_안_만든다():
    """명세는 `occurs1_pre_sett_dy` 를 최종결제일이라 적었지만 값은 직전 영업일로 옵니다."""
    원문 = 현재가줄()
    한줄 = overseas_quotes.quote(원문, asked="MESU26")

    assert 한줄["lastTradingDay"] is None
    # 원문 값은 제 이름으로만 나갑니다.
    assert 한줄["prevSettlementDate"] is not None
    assert 한줄["prevSettlementDate"] < str(한줄["businessDate"])


def test_해외에만_있는_값이_함께_온다():
    한줄 = overseas_quotes.quote(현재가줄(), asked="MESU26")

    assert 한줄["settlement"] is not None
    assert 한줄["exchange"]
    # 실시간 구독이 쓰는 코드입니다.
    assert 한줄["realCode"]
    assert 한줄["market"] == "overseas"


def test_거래가_없으면_시가_고가_저가가_비어_온다():
    """옵션 기록이 그렇습니다. 빈 문자열이 `null` 로 나가야 합니다."""
    비어있는줄 = [줄 for 줄 in [현재가줄(0), 현재가줄(1)] if not 줄["occurs1_open_pric"]]
    assert 비어있는줄, "빈 칸이 담긴 기록이 있어야 이 시험이 뜻을 가집니다."

    한줄 = overseas_quotes.quote(비어있는줄[0], asked="")
    assert 한줄["open"] is None
    assert 한줄["high"] is None
    assert 한줄["low"] is None
    # 현재가는 있습니다.
    assert 한줄["last"] is not None


def test_여러_종목이_한_번에_온다():
    응답 = {"Occurs1": [현재가줄(0), 현재가줄(1)]}

    답 = overseas_quotes.quotes_of(응답, asked=["MESU26", "O_ESU26-C7600.0"])

    assert len(답["quotes"]) == 2
    assert 답["quotes"][0]["code"] != 답["quotes"][1]["code"]


def test_종목_칸이_비면_물어본_코드를_같은_자리에서_쓴다():
    응답 = {"Occurs1": [{"occurs1_last_pric": "1"}, {"occurs1_last_pric": "2"}]}

    답 = overseas_quotes.quotes_of(응답, asked=["첫째", "둘째"])

    assert [줄["code"] for 줄 in 답["quotes"]] == ["첫째", "둘째"]


def test_원문_종목이_있으면_그것을_쓴다():
    """대조하는 뜻이 사라지지 않게 원문이 이깁니다."""
    응답 = {"Occurs1": [{"occurs1_sym": "진짜"}]}

    답 = overseas_quotes.quotes_of(응답, asked=["물어본것"])

    assert 답["quotes"][0]["code"] == "진짜"


def test_현재가가_비어_올_수_있다():
    for 빈것 in ({"Occurs1": []}, {}, {"Occurs1": "줄이_아님"}):
        assert overseas_quotes.quotes_of(빈것)["quotes"] == []


# ── 호가 ────────────────────────────────────────────────────


def test_호가는_다섯_단계다():
    책 = overseas_quotes.book(반입본("overseas_bid-price")[0], asked="MESU26")

    assert len(책["asks"]) == 5
    assert len(책["bids"]) == 5


def test_매도는_먼_값부터_매수는_가까운_값부터():
    책 = overseas_quotes.book(반입본("overseas_bid-price")[0], asked="MESU26")

    asks = [단계["price"] for 단계 in 책["asks"]]
    bids = [단계["price"] for 단계 in 책["bids"]]
    assert asks == sorted(asks, reverse=True)
    assert bids == sorted(bids, reverse=True)
    # 매도의 끝과 매수의 처음이 서로 가장 가까운 값입니다.
    assert asks[-1] > bids[0]


def test_값이_안_채워진_단계는_뺀다():
    """해외는 그 단계가 빈 문자열로 옵니다(국내는 0)."""
    비어있는것 = [책 for 책 in 반입본("overseas_bid-price") if not 책["ask_pric_4"]]
    assert 비어있는것, "빈 단계가 담긴 기록이 있어야 이 시험이 뜻을 가집니다."

    책 = overseas_quotes.book(비어있는것[0], asked="")
    assert len(책["asks"]) == 3
    assert len(책["bids"]) == 3


def test_호가에_딸려_온_현재가는_안_담는다():
    """같은 값을 두 자리에서 내면 어느 쪽이 새 값인지 화면이 못 가립니다."""
    책 = overseas_quotes.book(반입본("overseas_bid-price")[0], asked="MESU26")

    assert set(책) == {"code", "market", "time", "asks", "bids"}


def test_호가_시각은_호가접수시간이다():
    """실시간 호가의 `time` 과 같은 `HH:MM:SS` 한국시각입니다."""
    원문 = 반입본("overseas_bid-price")[0]
    assert 원문["qt_rcv_tm"] == "090336"

    assert overseas_quotes.book(원문, asked="MESU26")["time"] == "09:03:36"
    assert overseas_quotes.book({**원문, "qt_rcv_tm": ""}, asked="MESU26")["time"] is None


def test_음수_0_은_0_으로_편다():
    """실물 호가에 `-0.00` 이 있습니다. 그대로 두면 화면이 내림세로 칠합니다."""
    있는것 = [책 for 책 in 반입본("overseas_bid-price") if 책.get("bid_rt_3") == "-0.00"]
    assert 있는것, "`-0.00` 이 담긴 기록이 있어야 이 시험이 뜻을 가집니다."

    from backend import market_values

    폄 = market_values.number("-0.00")
    assert 폄 == 0
    assert str(폄) == "0.0"


# ── 봉 ──────────────────────────────────────────────────────


def test_봉은_오래된_것부터_온다():
    응답 = 반입본("overseas_chart-minute")[0]

    봉 = quotes.bars(응답, minute=True, asked="MESU26")

    시각들 = [하나["timestamp"] for 하나 in 봉["bars"]]
    assert 시각들 == sorted(시각들)
    assert len(시각들) == len(응답["Occurs1"])
    assert 봉["skipped"] == 0


def test_봉의_종목은_물어본_코드로_채워진다():
    """**해외 차트는 응답의 종목 칸이 비어 옵니다** — 기록 넷이 다 그렇습니다."""
    for 응답 in 반입본("overseas_chart-minute"):
        assert 응답.get("sym") == ""

    봉 = quotes.bars(반입본("overseas_chart-minute")[0], minute=True, asked="MESU26")
    assert 봉["code"] == "MESU26"


def test_봉의_날짜는_기준일이다():
    """해외영업일은 장 세션 날짜라 가로축에 쓰면 봉이 하루씩 밀립니다."""
    응답 = 반입본("overseas_chart-minute")[0]
    갈리는줄 = [
        줄 for 줄 in 응답["Occurs1"] if 줄["occurs1_ref_dt"] != 줄["occurs1_glb_biz_dt"]
    ]
    assert 갈리는줄, "두 날짜가 갈리는 줄이 있어야 이 시험이 뜻을 가집니다."

    한줄 = 갈리는줄[0]
    봉 = quotes.bars({"Occurs1": [한줄]}, minute=True, asked="X")["bars"][0]

    기준일로_센것 = quotes.timestamp(한줄["occurs1_ref_dt"], 한줄["occurs1_exch_tm"])
    assert 봉["timestamp"] == 기준일로_센것


def test_두_시장이_같은_봉_규칙을_쓴다():
    """한쪽만 고쳐지면 차트가 시장에 따라 달라집니다."""
    from backend.domestic_futureoption import domestic_quotes

    응답 = 반입본("overseas_chart-minute")[0]

    assert domestic_quotes.bars(응답, minute=True, asked="X") == quotes.bars(
        응답, minute=True, asked="X"
    )


def test_봉_시각은_한국_시간으로_보인다():
    """근거를 붙잡아 둡니다 — 기록이 늘었을 때 어긋나면 여기서 깨집니다.

    **시각을 못박지 않고 관계로 봅니다.** 겨울 기록이 들어오면 경계가 한 시간
    옮겨 가는데, 그때 헛되이 깨지면 안 됩니다. 관계는 그대로입니다 — 쉬는
    한 시간이 **영업일이 바뀌는 자리 바로 앞**에 붙어 있습니다.

    관계만으로는 시간대를 못 가립니다(현지 시간이어도 16~17시가 비고 17시에
    바뀝니다). 그래서 그 경계가 **한국의 아침 자리**에 있는지도 함께 봅니다.

    경계 시각은 기록 안의 관계로만 가립니다. 자세한 까닭은 `overseas_quotes.py` 첫머리에.
    """
    큰것 = [응답 for 응답 in 반입본("overseas_chart-minute") if len(응답.get("Occurs1") or []) > 50]
    assert 큰것, "줄이 넉넉한 기록이 있어야 이 시험이 뜻을 가집니다."

    for 응답 in 큰것:
        차례 = sorted(응답["Occurs1"], key=lambda 줄: 줄["occurs1_exch_tm"])
        경계 = [
            차례[i]["occurs1_exch_tm"]
            for i in range(1, len(차례))
            if 차례[i]["occurs1_glb_biz_dt"] != 차례[i - 1]["occurs1_glb_biz_dt"]
        ]
        assert len(경계) == 1, f"영업일이 한 번만 바뀌어야 합니다: {경계}"

        바뀌는시각 = 경계[0]
        assert 바뀌는시각.endswith("0000"), f"정각이 아닙니다: {바뀌는시각}"

        # 쉬는 한 시간이 그 자리 바로 앞에 붙어 있습니다(거래소 정비 시간).
        앞시각 = f"{int(바뀌는시각[:2]) - 1:02d}0000"
        쉬는시간 = [줄 for 줄 in 차례 if 앞시각 < 줄["occurs1_exch_tm"] < 바뀌는시각]
        assert 쉬는시간 == [], f"{앞시각}~{바뀌는시각} 에 봉이 있습니다."

        # 그 경계가 한국 아침 자리입니다. CME 가 17:00 CT 에 다음 거래일을 여는데,
        # 한국으로는 서머타임이면 07시, 표준시면 08시입니다. 거래소 현지 시간이면
        # 저녁 17시라 여기서 걸립니다.
        assert 바뀌는시각 in ("070000", "080000"), f"한국 아침이 아닙니다: {바뀌는시각}"
