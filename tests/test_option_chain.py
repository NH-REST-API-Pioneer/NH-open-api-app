"""옵션전체시세 응답이 옵션 체인 모양으로 바뀌는지 — 국내(주간·야간)·해외.

저장 기록(real)으로 봅니다: 국내 주간 코스피200 261줄(다음 행사가 있음)·미니·
코스닥150, 야간 400줄, 해외 `O_ESU26` 338줄.
"""
from __future__ import annotations

from backend.domestic_futureoption import domestic_chain
from backend.nh_api.fixtures import load_fixtures
from backend.overseas_futureoption import overseas_chain


def _기록(api_id: str, **요청):
    for fixture in load_fixtures().http:
        if fixture.api_id != api_id or fixture.http_status != 200:
            continue
        if all(fixture.request.get(k) == v for k, v in 요청.items()):
            return fixture.response
    raise AssertionError(f"{api_id} {요청} 기록이 없습니다")


# ── 국내 주간 ────────────────────────────────────────────────


def test_국내_주간_체인은_행사가마다_콜과_풋_코드가_실린다():
    체인 = domestic_chain.chain([_기록("domestic_price-all-option", prd="01")])

    assert 체인["market"] == "domestic" and 체인["session"] == "day"
    assert 체인["count"] == len(체인["rows"]) == 261
    첫줄 = 체인["rows"][0]
    assert 첫줄["strike"] == 1597.5
    assert (첫줄["call"]["code"], 첫줄["put"]["code"]) == ("B0169C42", "C0169C42")
    assert 첫줄["call"]["last"] == 0.01 and 첫줄["put"]["last"] == 462.3
    assert 첫줄["call"]["openInterest"] == 8372 and 첫줄["call"]["volume"] == 12
    assert 첫줄["call"]["iv"] == 113.8 and 첫줄["call"]["delta"] == 0.00032
    # 서버가 준 차례 그대로 — 행사가 높은 것부터.
    행사가들 = [줄["strike"] for 줄 in 체인["rows"]]
    assert 행사가들 == sorted(행사가들, reverse=True)
    # 모든 줄에 콜·풋 코드가 있다 — 화면이 이 코드로 조회·구독한다.
    assert all(줄["call"]["code"] and 줄["put"]["code"] for 줄 in 체인["rows"])
    # 원문 칸 이름은 밖으로 안 나간다.
    assert "occurs1_c_last_pric" not in str(체인)


def test_국내_주간_체인의_기초자산과_당월선물():
    체인 = domestic_chain.chain([_기록("domestic_price-all-option", prd="01")])

    assert 체인["underlying"]["code"] == "KRD020020016"
    assert 체인["underlying"]["price"] == 1102.41
    assert (체인["underlying"]["change"], 체인["underlying"]["changePct"]) == (2.33, 0.21)
    assert 체인["future"]["code"] == "A0169000"
    assert 체인["future"]["last"] == 1102.7
    assert 체인["future"]["daysLeft"] == 2


def test_가격_칸의_0_은_없음이고_대비의_0_은_값이다():
    줄 = domestic_chain.chain([_기록("domestic_price-all-option", prd="01")])["rows"][0]
    # 첫 줄(깊은 외가격 콜)의 매수호가·이론가는 0.00 으로 온다.
    assert 줄["call"]["bid"] is None and 줄["call"]["theory"] is None
    assert 줄["call"]["ask"] == 0.01
    assert 줄["call"]["change"] == 0.0 and 줄["call"]["changePct"] == 0.0


# ── 국내 야간 ────────────────────────────────────────────────


def test_국내_야간_체인은_코드와_미결제만_있고_시세는_null_이다():
    체인 = domestic_chain.chain([_기록("domestic_price-all-option-night", prd="01")], night=True)

    assert 체인["session"] == "night"
    assert 체인["future"] is None, "야간 응답에는 당월선물이 없다"
    assert 체인["underlying"]["price"] == 1103.02
    assert 체인["count"] == 400
    첫줄 = 체인["rows"][0]
    assert (첫줄["call"]["code"], 첫줄["put"]["code"]) == ("B0169C42", "C0169C42")
    assert 첫줄["call"]["prevClose"] == 0.01
    assert 첫줄["call"]["openInterest"] == 8734 and 첫줄["call"]["openInterestChange"] == 362
    assert 첫줄["put"]["openInterestChange"] == -1018
    for 칸 in ("last", "bid", "ask", "theory", "iv", "delta", "volume"):
        assert 첫줄["call"][칸] is None, 칸
    # 칸 목록은 주간과 같다.
    주간 = domestic_chain.chain([_기록("domestic_price-all-option", prd="01")])["rows"][0]
    assert set(첫줄["call"]) == set(주간["call"])


# ── 이어받기 ─────────────────────────────────────────────────


def _쪽(행사가들, 다음):
    return {
        "nxt_stkr_pric": 다음,
        "Occurs1": [
            {"occurs1_strk_pric": s, "occurs1_c_sym_exch": f"B{s}", "occurs1_p_sym_exch": f"C{s}"}
            for s in 행사가들
        ],
    }


def test_다음_행사가를_따라_쪽을_다_모으고_겹친_줄은_한_번만():
    쪽들 = {"99999999": _쪽(["300.00", "200.00"], "200.00"), "200.00": _쪽(["200.00", "100.00"], "")}
    부른것 = []

    def fetch(key):
        부른것.append(key)
        return 쪽들[key]

    pages = domestic_chain.collect(fetch, first_key="99999999")
    assert 부른것 == ["99999999", "200.00"]
    체인 = domestic_chain.chain(pages)
    assert [줄["strike"] for 줄 in 체인["rows"]] == [300.0, 200.0, 100.0]
    assert 체인["count"] == 3


def test_같은_쪽이_다시_오면_멈춘다():
    """저장본은 다음 쪽을 물어도 같은 기록을 준다 — 끝없이 돌지 않는다."""
    부른것 = []

    def fetch(key):
        부른것.append(key)
        return _쪽(["300.00", "200.00"], "200.00")

    pages = domestic_chain.collect(fetch, first_key="99999999")
    assert 부른것 == ["99999999", "200.00"]
    assert domestic_chain.chain(pages)["count"] == 2


def test_이어받기는_상한까지만():
    번호 = iter(range(1000))

    def fetch(key):
        n = next(번호)
        return _쪽([f"{900 - n}.00"], f"{900 - n}.00")

    pages = domestic_chain.collect(fetch, first_key="99999999")
    assert len(pages) == domestic_chain.MAX_PAGES


def test_줄이_없으면_빈_체인이다():
    """실제 0건 응답은 `Occurs1` 칸 자체가 없다."""
    체인 = domestic_chain.chain([{"nrec": "0000", "nxt_key": ""}])
    assert 체인["rows"] == [] and 체인["count"] == 0
    assert 체인["future"] is None
    assert domestic_chain.chain([])["underlying"] is None


# ── 해외 ─────────────────────────────────────────────────────


def test_해외_체인은_행마다_콜과_풋_종목코드가_실린다():
    체인 = overseas_chain.chain(_기록("overseas_price-all-option", sym="O_ESU26"), asked="O_ESU26")

    assert 체인["market"] == "overseas" and 체인["series"] == "O_ESU26"
    assert 체인["daysLeft"] == 11
    assert 체인["underlying"] is None and 체인["future"] is None
    assert 체인["count"] == len(체인["rows"]) == 338
    첫줄 = 체인["rows"][0]
    assert 첫줄["strike"] == 12000.0 and 첫줄["priceCode"] == "3"
    assert (첫줄["call"]["code"], 첫줄["put"]["code"]) == ("O_ESU26-C12000.0", "O_ESU26-P12000.0")
    assert 첫줄["call"]["exchange"] == "CME"
    assert 첫줄["call"]["ask"] == 0.05 and 첫줄["call"]["askQty"] == 305
    assert 첫줄["call"]["bid"] is None and 첫줄["call"]["bidQty"] == 0
    assert 첫줄["put"]["last"] == 4319.5
    assert all(줄["call"]["code"] and 줄["put"]["code"] for 줄 in 체인["rows"])
    등가 = [줄["strike"] for 줄 in 체인["rows"] if 줄["call"]["atm"] or 줄["put"]["atm"]]
    assert 등가 == [7680.0]


def test_해외_체인도_줄이_없으면_빈_체인이다():
    체인 = overseas_chain.chain({"nrec": "0000"}, asked="O_ZZZZ99")
    assert 체인["rows"] == [] and 체인["count"] == 0 and 체인["daysLeft"] is None
