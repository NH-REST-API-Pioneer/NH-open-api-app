"""국내 시세 응답을 화면 모양으로 바꾸는 규칙."""
import json
from datetime import datetime

import pytest

from backend.domestic_futureoption.domestic_quotes import all_futures, bars, book, quote
from backend.nh_api.fixtures import FIXTURE_ROOT
from backend.sessions.hours import KST

# 일봉 두 기록은 수집기가 연속조회 키를 가리면서 봉의 날짜까지 함께 덮었습니다.
# 연속조회 키가 조회한 날짜와 글자가 같았기 때문입니다.
DATE_MASKED_RECORDS = ("20260909T000036_c04bdf9e9d81", "20260909T000038_ffa484283d9a")
MASKED_DATE = "59532247"


def _midnight(date_text: str) -> int:
    """그날 0시, 한국시간. 봉의 시각은 컴퓨터 시간대와 무관합니다."""
    return int(datetime.strptime(date_text, "%Y%m%d").replace(tzinfo=KST).timestamp() * 1000)


# 부호가 따로 오는 항목. 값과 부호칸이 어긋나는지 전수로 봅니다.
SIGN_PAIRS = (
    ("chg", "chg_sign"),
    ("opint_chg", "opint_chg_sign"),
    ("spt_chg", "spt_chg_sign"),
    ("occurs1_chg", "occurs1_chg_sign"),
)


def 현재가(**override):
    raw = {
        "sym_exch": "A7569000",
        "sym_nm": "미국달러 F 202609",
        "last_pric": "1338.50",
        "chg": "-6.20",
        "chg_sign": "-",
        "rt": "-0.46",
        "open_pric": "1340.30",
        "high_pric": "1340.80",
        "low_pric": "1338.40",
        "trd_qty": "6850",
        "trd_amt": "91767",
        "opint": "1188964",
        "opint_chg": "-2346",
        "opint_chg_sign": "-",
        "up_act_pric": "1351.90",
        "lo_act_pric": "1325.10",
        "spt_pric": "1338.70",
        "spt_chg": "-4.10",
        "spt_chg_sign": "-",
        "lst_trd_dt": "20260921",
        "rem_dy": "13",
        "mltplr": "10000",
    }
    raw.update(override)
    return raw


def 호가단계(ask, ask_qty, bid, bid_qty):
    return {
        "occurs1_ask_best_pric": ask,
        "occurs1_ask_qty": ask_qty,
        "occurs1_bid_best_pric": bid,
        "occurs1_bid_qty": bid_qty,
    }


def test_문자열로_온_값을_숫자로_낸다():
    나온것 = quote(현재가())
    assert 나온것["last"] == 1338.5
    assert 나온것["volume"] == 6850
    assert isinstance(나온것["volume"], int)
    assert 나온것["code"] == "A7569000"


def test_빈_값은_숫자가_아니라_없음이다():
    """0 으로 채우면 화면이 「0원」을 그린다."""
    나온것 = quote(현재가(last_pric="", high_pric="   "))
    assert 나온것["last"] is None
    assert 나온것["high"] is None


def test_숫자로_읽지_못한_값도_없음이다():
    assert quote(현재가(last_pric="가격없음"))["last"] is None


def test_부호는_값에서_만든다():
    나온것 = quote(현재가())
    assert 나온것["change"] == -6.2
    assert 나온것["openInterestChange"] == -2346


def test_부호칸이_값과_어긋나면_값을_따르고_경고한다(caplog):
    """부호칸을 적용하면 0 이 −0 이 된다. 값이 참이다."""
    with caplog.at_level("WARNING"):
        나온것 = quote(현재가(chg="6.20", chg_sign="-"))

    assert 나온것["change"] == 6.2
    assert any("chg" in r.getMessage() for r in caplog.records)


def test_실시간_상하한을_쓴다():
    """상한가·하한가가 아니라 실시간 쪽을 화면이 그린다."""
    나온것 = quote(현재가(up="1405.20", lo="1284.20"))
    assert (나온것["upperLimit"], 나온것["lowerLimit"]) == (1351.9, 1325.1)


def test_야간_현물가는_없음으로_낸다():
    """야간에는 현물가가 0.00 으로 온다. 0 을 그대로 내면 「현물가 0원」이 선다."""
    나온것 = quote(현재가(spt_pric="0.00", spt_chg="0", spt_chg_sign="-"))
    assert 나온것["spot"] is None
    assert 나온것["spotChange"] is None


def test_최종거래일은_날짜_모양으로():
    assert quote(현재가())["lastTradingDay"] == "2026-09-21"
    assert quote(현재가(lst_trd_dt=""))["lastTradingDay"] is None
    assert quote(현재가(lst_trd_dt="99999999"))["lastTradingDay"] is None


def test_거래대금은_백만_단위_그대로_낸다():
    """원 단위로 바꾸지 않는다 — 화면이 백만을 받아 「억원」으로 적는다."""
    assert quote(현재가())["turnover"] == 91767


def test_호가는_매도를_뒤집어_먼_값부터_낸다():
    """주문 화면이 매수·매도 단추 가격을 배열 끝에서 뽑는다.

    안 뒤집으면 단추에 가장 나쁜 호가가 붙는다.
    """
    나온것 = book(
        {
            "Occurs1": [
                호가단계("1338.60", "53", "1338.50", "13"),
                호가단계("1338.70", "71", "1338.40", "64"),
                호가단계("1338.80", "65", "1338.30", "83"),
            ]
        }
    )

    assert [단계["price"] for 단계 in 나온것["asks"]] == [1338.8, 1338.7, 1338.6]
    assert [단계["price"] for 단계 in 나온것["bids"]] == [1338.5, 1338.4, 1338.3]
    # 최우선은 매도의 끝, 매수의 앞.
    assert 나온것["asks"][-1]["price"] == 1338.6
    assert 나온것["bids"][0]["price"] == 1338.5


def test_잔량도_함께_낸다():
    나온것 = book({"Occurs1": [호가단계("1338.60", "53", "1338.50", "13")]})
    assert 나온것["asks"] == [{"price": 1338.6, "quantity": 53}]
    assert 나온것["bids"] == [{"price": 1338.5, "quantity": 13}]


def test_값이_안_채워진_호가_단계는_뺀다():
    """열 단계가 오지만 그 종목에 없는 단계는 0 으로 온다."""
    나온것 = book(
        {
            "Occurs1": [
                호가단계("1338.60", "53", "1338.50", "13"),
                호가단계("0.00", "0", "0.00", "0"),
                호가단계("0.00", "0", "0.00", "0"),
            ]
        }
    )
    assert len(나온것["asks"]) == 1
    assert len(나온것["bids"]) == 1


def test_호가_시각을_실시간과_같은_모양으로_낸다():
    """조회 뒤와 실시간 뒤의 호가 시각 자리가 같아야 화면이 한 자리로 그린다."""
    나온것 = book({"qt_tm": "090023", "Occurs1": [호가단계("1338.60", "53", "1338.50", "13")]})
    assert 나온것["time"] == "09:00:23"


def test_예상체결가는_단일가_때만_값이_있다():
    """접속매매 중에는 0 으로 오므로 0 은 값이 아니라 없음이다."""
    동시호가 = book({"est_exec_pric": "1338.50", "Occurs1": []})
    assert 동시호가["expectedPrice"] == 1338.5
    없음들 = ({"est_exec_pric": "0.00", "Occurs1": []}, {"est_exec_pric": "", "Occurs1": []}, {})
    for 없음 in 없음들:
        assert book(없음)["expectedPrice"] is None, 없음


def test_마감_동시호가의_예상체결가_원문_모양():
    """실서버 마감 동시호가(15:35~15:45)에 관찰한 값 — 두 자리 소수 문자열이고
    15:45 를 지나면 `0.00` 으로 돌아온다."""
    관찰 = ["1368.00", "1365.00", "1366.50", "1368.00"]
    for 원문 in 관찰:
        assert book({"est_exec_pric": 원문, "Occurs1": []})["expectedPrice"] == float(원문)
    assert book({"est_exec_pric": "0.00", "Occurs1": []})["expectedPrice"] is None


def test_호가_시각이_없거나_시각이_아니면_null_이다():
    assert book({"Occurs1": []})["time"] is None
    assert book({"qt_tm": "", "Occurs1": []})["time"] is None
    assert book({"qt_tm": "9시", "Occurs1": []})["time"] is None


def test_호가가_통째로_비어_올_수_있다():
    """받는 쪽이 빈 배열을 다룰 수 있어야 한다."""

    def 사다리(raw):
        나온것 = book(raw)
        return {"asks": 나온것["asks"], "bids": 나온것["bids"]}

    assert 사다리({"Occurs1": []}) == {"asks": [], "bids": []}
    assert 사다리({}) == {"asks": [], "bids": []}
    assert 사다리({"Occurs1": [호가단계("0.00", "0", "0.00", "0")]}) == {"asks": [], "bids": []}


def test_분봉은_오래된_것부터_낸다():
    """NH 는 최신부터 보내고 차트는 반대다."""
    나온것 = bars(
        {
            "Occurs1": [
                {
                    "occurs1_ref_dt": "20260909",
                    "occurs1_exch_tm": "090100",
                    "occurs1_open_pric": "2",
                    "occurs1_high_pric": "2",
                    "occurs1_low_pric": "2",
                    "occurs1_close_pric": "2",
                    "occurs1_cum_trd_qty": "20",
                },
                {
                    "occurs1_ref_dt": "20260909",
                    "occurs1_exch_tm": "090000",
                    "occurs1_open_pric": "1",
                    "occurs1_high_pric": "1",
                    "occurs1_low_pric": "1",
                    "occurs1_close_pric": "1",
                    "occurs1_cum_trd_qty": "10",
                },
            ]
        },
        minute=True,
    )

    assert [봉["close"] for 봉 in 나온것["bars"]] == [1, 2]
    시각 = [봉["timestamp"] for 봉 in 나온것["bars"]]
    assert 시각[1] - 시각[0] == 60_000
    assert 나온것["skipped"] == 0


def test_시각을_읽지_못한_줄은_빼고_몇_줄인지_알린다():
    """조용히 사라지면 차트에 구멍이 난 것을 알 방법이 없다."""
    나온것 = bars(
        {
            "Occurs1": [
                {"occurs1_ref_dt": "날짜아님", "occurs1_close_pric": "1341.00"},
                {"occurs1_ref_dt": "20260909", "occurs1_close_pric": "1338.00"},
            ]
        },
        minute=False,
    )
    assert len(나온것["bars"]) == 1
    assert 나온것["skipped"] == 1


def test_일봉은_시각을_날짜에서만_읽는다():
    나온것 = bars({"Occurs1": [{"occurs1_ref_dt": "20260909"}]}, minute=False)
    assert len(나온것["bars"]) == 1


def test_이어_받을_키를_함께_낸다():
    assert bars({"Occurs1": [], "nxt_key": "30919151086003"}, minute=True)["nextKey"] == (
        "30919151086003"
    )


# -- 반입해 둔 응답으로 --------------------------------------------------


def _fixtures(api_id: str) -> list[dict]:
    폴더 = FIXTURE_ROOT / api_id
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(폴더.rglob("*.json"))]


def test_반입해_둔_현재가가_그대로_바뀐다():
    for 기록 in _fixtures("domestic_price"):
        나온것 = quote(기록["response"])
        assert 나온것["code"]
        assert 나온것["last"] is not None
        assert 나온것["change"] is not None


def test_선물전체시세가_월물_목록으로_나온다():
    """줄 하나가 월물이고, 칸 이름은 현재가 조회와 같습니다."""
    기록 = next(
        하나 for 하나 in _fixtures("domestic_price-all-futures") if 하나["request"]["prd"] == "01"
    )

    나온것 = all_futures(기록["response"], asked="01")

    assert (나온것["product"], 나온것["count"]) == ("01", 7)
    assert len(나온것["rows"]) == 7
    첫줄 = 나온것["rows"][0]
    assert (첫줄["code"], 첫줄["name"]) == ("A0169000", "코스피200 F 202609")
    assert (첫줄["last"], 첫줄["change"], 첫줄["changePct"]) == (1105.3, 6.9, 0.63)
    assert (첫줄["volume"], 첫줄["openInterest"]) == (2498, 99203)
    assert (첫줄["open"], 첫줄["high"], 첫줄["low"]) == (1104.25, 1106.45, 1100.55)
    # 명세는 `YYYYMM` 이라 적었는데 실제는 `YY/MM` 입니다. 가공하지 않고 그대로.
    assert 첫줄["expiryMonth"] == "26/09"
    # 만기 목록에 자리가 없는 칸은 안 냅니다.
    assert not ({"theory", "basisTheory", "disparity"} & set(첫줄))


def test_반입해_둔_품목_스물둘이_모두_월물을_낸다():
    """기록이 품목코드 전부를 덮습니다 — 한 품목이라도 비면 그 만기 목록이 빕니다."""
    품목들 = {}
    for 기록 in _fixtures("domestic_price-all-futures"):
        prd = 기록["request"]["prd"]
        품목들[prd] = all_futures(기록["response"], asked=prd)

    assert len(품목들) == 22
    for prd, 나온것 in 품목들.items():
        assert 나온것["rows"], prd
        assert 나온것["count"] == len(나온것["rows"]), prd
        assert all(줄["code"] for 줄 in 나온것["rows"]), prd
        assert all(줄["last"] is not None for 줄 in 나온것["rows"]), prd


def test_건수는_낸_줄_수이고_원문과_다르면_알린다(caplog):
    """원문 건수를 그대로 옮기면 「7개」라 적으면서 여섯 줄을 그리는 날이 옵니다."""
    한줄 = {"occurs1_sym_exch": "A0169000", "occurs1_prd": "01", "occurs1_last_pric": "1105.30"}

    with caplog.at_level("WARNING"):
        나온것 = all_futures({"nrec": "7", "Occurs1": [한줄]}, asked="01")

    assert 나온것["count"] == 1
    assert any("건수" in 남긴것.getMessage() for 남긴것 in caplog.records)

    # 맞으면 아무 말도 안 합니다.
    caplog.clear()
    with caplog.at_level("WARNING"):
        all_futures({"nrec": "1", "Occurs1": [한줄]}, asked="01")
    assert not caplog.records


def test_줄이_없으면_부른_품목을_그대로_낸다():
    """재생에 기록이 없으면 빈 응답이 옵니다 — 그때도 무엇을 물었는지 남깁니다."""
    나온것 = all_futures({"nrec": "0000", "nxt_key": ""}, asked="ZZ")

    assert (나온것["product"], 나온것["rows"], 나온것["count"]) == ("ZZ", [], 0)
    # 모양이 다른 응답도 다룹니다.
    assert all_futures({"Occurs1": "줄이 아님"}, asked="01")["rows"] == []


def test_반입해_둔_호가가_다섯_단계로_나온다():
    """열 단계가 오지만 채워진 것은 다섯이다."""
    for 기록 in _fixtures("domestic_price-bid"):
        나온것 = book(기록["response"])
        assert 나온것["asks"], 기록["record_id"]
        assert 나온것["bids"], 기록["record_id"]
        # 매도는 내림차순(먼 값부터), 매수는 내림차순(가까운 값부터).
        assert [단계["price"] for 단계 in 나온것["asks"]] == sorted(
            (단계["price"] for 단계 in 나온것["asks"]), reverse=True
        )
        assert [단계["price"] for 단계 in 나온것["bids"]] == sorted(
            (단계["price"] for 단계 in 나온것["bids"]), reverse=True
        )
        # 최우선 매도가 최우선 매수보다 비싸다.
        assert 나온것["asks"][-1]["price"] > 나온것["bids"][0]["price"]
        # 저장 기록에는 호가 시각이 늘 있다(장중 09:00:23, 장전 06:00:00).
        assert 나온것["time"] is not None, 기록["record_id"]
        assert len(나온것["time"]) == 8
        # 접속매매 중 기록이라 예상체결가는 0 → 없음.
        assert 나온것["expectedPrice"] is None


def test_반입해_둔_분봉이_오래된_것부터_나온다():
    본것 = 0
    for 기록 in _fixtures("domestic_chart-minute"):
        나온것 = bars(기록["response"], minute=True)
        if not 나온것["bars"]:
            continue
        본것 += 1
        시각 = [봉["timestamp"] for 봉 in 나온것["bars"]]
        assert 시각 == sorted(시각)
        assert 나온것["skipped"] == 0
    assert 본것, "분봉이 든 기록이 있어야 한다"


def test_일봉_표본은_날짜_칸만_가려진_채로_들어왔다():
    """일봉 표본은 **있습니다.** 날짜 칸만 수집할 때 가려졌습니다.

    수집기는 연속조회 키를 가명으로 바꾸면서 그 응답 안의 같은 문자열을 전부
    같은 값으로 바꿉니다. 아래 두 기록은 연속조회 키가 조회한 날짜와 글자가
    똑같아서, 봉의 날짜까지 함께 덮였습니다. **NH선물이 날짜 자리에 이상한
    값을 보낸 것이 아닙니다.**

    그래서 지금 자료로는 일봉이 0개로 나옵니다. 회사에서 다시 수집하면 날짜가
    살아 있는 표본이 들어오고, 그때 이 시험이 실패하므로 계약을 다시 봅니다.
    """
    행이_있는것 = {}
    for 기록 in _fixtures("domestic_chart-daily"):
        줄들 = 기록["response"].get("Occurs1") or []
        if 줄들:
            행이_있는것[기록["record_id"]] = 줄들[0]

    assert set(행이_있는것) == set(DATE_MASKED_RECORDS)
    for 기록번호, 첫줄 in 행이_있는것.items():
        assert 첫줄["occurs1_ref_dt"] == MASKED_DATE, 기록번호
        # 연속조회 키와 같은 값이라는 것이 덮였다는 근거다.
        assert bars({"Occurs1": [첫줄], "nxt_key": MASKED_DATE}, minute=False)["bars"] == []


def test_일봉은_날짜가_살아_있으면_봉이_나온다():
    """가려진 날짜를 조회한 날짜로 되돌리면 그 행이 그대로 봉이 된다.

    반입해 둔 파일은 손대지 않고 이 시험 안에서만 되돌립니다.
    """
    기록 = next(
        하나
        for 하나 in _fixtures("domestic_chart-daily")
        if 하나["record_id"] == DATE_MASKED_RECORDS[0]
    )
    응답 = json.loads(json.dumps(기록["response"]))
    응답["Occurs1"][0]["occurs1_ref_dt"] = 기록["request"]["inq_ed_dt"]

    나온것 = bars(응답, minute=False)

    assert 나온것["skipped"] == 0
    assert len(나온것["bars"]) == 1
    봉 = 나온것["bars"][0]
    assert 봉["close"] == 1341.0
    assert 봉["open"] == 1344.8
    assert 봉["volume"] == 13833
    # 일봉에는 시각이 없어 그날 0시로 앉는다.
    assert 봉["timestamp"] == _midnight(기록["request"]["inq_ed_dt"])


@pytest.mark.parametrize(
    "api_id",
    [
        "domestic_price",
        "domestic_price-night",
        "domestic_price-all-futures",
        "domestic_price-all-option",
        "domestic_price-all-option-night",
    ],
)
def test_부호칸과_값이_어긋나는_것은_값이_0_일_때뿐이다(api_id):
    """값의 부호를 믿기로 한 근거를 반입 자료 전수로 굳힌다.

    값이 양수인데 부호칸이 「−」인 기록이 하나라도 있으면 그 규칙이 위험해진다.
    """
    어긋남 = []
    for 기록 in _fixtures(api_id):
        응답 = 기록["response"]
        줄들 = [응답] if isinstance(응답, dict) else []
        안쪽 = 응답.get("Occurs1") if isinstance(응답, dict) else None
        if isinstance(안쪽, list):
            줄들 += [줄 for 줄 in 안쪽 if isinstance(줄, dict)]

        for 값키, 부호키 in SIGN_PAIRS:
            for 줄 in 줄들:
                if 값키 not in 줄 or 부호키 not in 줄:
                    continue
                값 = str(줄[값키] or "").strip()
                부호 = str(줄[부호키] or "").strip()
                if not 값:
                    continue
                if 부호 == "-" and not 값.startswith("-"):
                    어긋남.append((기록["record_id"], 값키, 값, 부호))

    양수인데_음수표시 = [하나 for 하나 in 어긋남 if float(하나[2]) != 0]
    assert 양수인데_음수표시 == [], 양수인데_음수표시


# ── 어느 종목의 답인지 ────────────────────────────────────────


def test_호가와_봉도_어느_종목의_답인지_함께_낸다():
    """화면이 세 응답을 요청 종목과 대조해 섞이는 것을 막습니다."""
    assert book({"sym": "A7569000", "Occurs1": []})["code"] == "A7569000"
    assert bars({"sym": "A7569000", "Occurs1": []}, minute=True)["code"] == "A7569000"
    assert quote({"sym_exch": "A7569000"})["code"] == "A7569000"


def test_원문에_종목이_비어_오면_부를_때_쓴_코드를_적는다():
    비었음 = {"sym": "", "Occurs1": []}
    assert book(비었음, asked="A7569000")["code"] == "A7569000"
    assert bars(비었음, minute=False, asked="A7569000")["code"] == "A7569000"
    assert quote({"sym_exch": ""}, asked="A7569000")["code"] == "A7569000"


def test_원문에_종목이_있으면_그_값이_이긴다():
    """대신 답한 기록이면 원문 종목이 요청과 다를 수 있고, 그것이 사실입니다."""
    assert book({"sym": "B0169A34", "Occurs1": []}, asked="A7569000")["code"] == "B0169A34"


def test_반입해_둔_호가와_분봉에도_종목이_실린다():
    import json

    for api_id, 함수 in (
        ("domestic_price-bid", lambda raw: book(raw)),
        ("domestic_chart-minute", lambda raw: bars(raw, minute=True)),
    ):
        경로 = sorted((FIXTURE_ROOT / api_id).rglob("*.json"))[0]
        raw = json.loads(경로.read_text(encoding="utf-8"))["response"]
        assert 함수(raw)["code"] == raw["sym"]


def test_앞뒤_공백은_털어_낸다():
    assert book({"sym": "  A7569000 ", "Occurs1": []})["code"] == "A7569000"
    assert book({"sym": "", "Occurs1": []}, asked="  A7569000 ")["code"] == "A7569000"


# -- 체결 없는 시가·고가·저가, 스프레드 빈 칸, 야간 베이시스, 야간 자리표 봉 --------


def test_선물전체시세에서_체결_없는_월물은_시가_고가_저가가_null():
    """반입본의 코스피200 27/03 은 거래량 0 에 시가·고가·저가가 0.00 으로 옵니다."""
    기록 = next(
        하나 for 하나 in _fixtures("domestic_price-all-futures") if 하나["request"]["prd"] == "01"
    )
    줄들 = {줄["expiryMonth"]: 줄 for 줄 in all_futures(기록["response"], asked="01")["rows"]}

    빈월물 = 줄들["27/03"]
    assert 빈월물["volume"] == 0
    assert (빈월물["open"], 빈월물["high"], 빈월물["low"]) == (None, None, None)
    assert 빈월물["last"] is not None, "현재가(전일 값)는 그대로입니다."
    # 체결이 있던 월물은 그대로입니다.
    assert (줄들["26/09"]["open"], 줄들["26/09"]["high"], 줄들["26/09"]["low"]) == (
        1104.25,
        1106.45,
        1100.55,
    )


def test_현재가도_거래량_0_이면_시가_고가_저가가_null():
    나온것 = quote(현재가(trd_qty="0", open_pric="0.00", high_pric="0.00", low_pric="0.00"))

    assert 나온것["volume"] == 0
    assert (나온것["open"], 나온것["high"], 나온것["low"]) == (None, None, None)
    assert 나온것["last"] == 1338.5


def test_거래가_있으면_스프레드의_0_이나_음수_가격도_그대로():
    """값이 아니라 거래량으로 가릅니다 — 스프레드 가격은 0 이나 음수가 정상입니다."""
    나온것 = quote(
        현재가(trd_qty="3", open_pric="0.00", high_pric="0.05", low_pric="-0.10"), spread=True
    )
    assert (나온것["open"], 나온것["high"], 나온것["low"]) == (0.0, 0.05, -0.1)


def test_야간_현재가는_야간_거래량으로_가른다():
    """야간 응답의 거래량은 야간의 것입니다 — 야간 체결이 0 이면 야간 시가·고가·저가도 없습니다."""
    for 기록 in _fixtures("domestic_price-night"):
        원문 = {**기록["response"], "trd_qty": "0"}
        나온것 = quote(원문)
        assert (나온것["open"], 나온것["high"], 나온것["low"]) == (None, None, None)
        assert quote(기록["response"])["open"] is not None, "야간 체결이 있으면 그대로입니다."


def test_스프레드면_뜻없는_칸이_null():
    나온것 = quote(
        현재가(theo_pric="0.00", dev_rt="0.00", ivol="0.00", theo_bas="0.00", fact_bas="0.00"),
        spread=True,
    )
    for 칸 in ("upperLimit", "lowerLimit", "theory", "disparity", "iv", "basisTheory", "basisActual"):
        assert 나온것[칸] is None, 칸
    assert 나온것["last"] == 1338.5


def test_스프레드가_아니면_0_도_값이다():
    """선물의 괴리율 0 은 정상값입니다 — 종목이 스프레드일 때만 비웁니다."""
    나온것 = quote(현재가(dev_rt="0.00", theo_pric="1338.50"))

    assert 나온것["disparity"] == 0.0
    assert 나온것["theory"] == 1338.5
    assert 나온것["upperLimit"] == 1351.9


def test_야간_현재가는_현물가가_없어_베이시스도_null():
    """반입본 야간 응답은 현물가 0.00 에 베이시스(-87.90 등)가 옵니다 — 현물가 없이 센 값입니다."""
    for 기록 in _fixtures("domestic_price-night"):
        나온것 = quote(기록["response"])
        assert 나온것["spot"] is None
        assert (나온것["basisTheory"], 나온것["basisActual"]) == (None, None)


def test_주간_현재가의_베이시스는_그대로():
    기록 = next(하나 for 하나 in _fixtures("domestic_price") if 하나["request"]["sym"] == "A7569000")
    나온것 = quote(기록["response"])

    assert 나온것["spot"] == 1338.7
    assert (나온것["basisTheory"], 나온것["basisActual"]) == (1.49, -0.2)


def test_상장_후_최고_최저는_life_이름으로():
    나온것 = quote(현재가(life_high_pric="1480.00", life_low_pric="1300.00"))

    assert (나온것["lifeHigh"], 나온것["lifeLow"]) == (1480.0, 1300.0)
    assert "monthHigh" not in 나온것


def _봉(날, 시, 고, 저, 종, 량):
    return {"timestamp": 날, "open": 시, "high": 고, "low": 저, "close": 종, "volume": 량}


def test_야간_자리표_봉을_세_조건이_다_맞을_때만_뺀다():
    from backend.domestic_futureoption.domestic_quotes import drop_placeholders

    자리표 = _봉(1, 1338.5, 1338.5, 1338.5, 1338.5, 0)
    체결있음 = _봉(2, 1338.5, 1338.5, 1338.5, 1338.5, 4)
    가격다름 = _봉(3, 1338.5, 1339.0, 1338.5, 1338.5, 0)
    보통 = _봉(4, 1338.0, 1340.0, 1337.0, 1339.0, 120)

    나온것 = drop_placeholders({"code": "A7569000", "bars": [자리표, 체결있음, 가격다름, 보통], "skipped": 1})

    assert [봉["timestamp"] for 봉 in 나온것["bars"]] == [2, 3, 4]
    assert 나온것["skipped"] == 2, "원래 뺀 수에 더합니다."


def test_뺄_봉이_없으면_받은_그대로():
    from backend.domestic_futureoption.domestic_quotes import drop_placeholders

    받은것 = {"code": "A7569000", "bars": [_봉(1, 1.0, 2.0, 0.5, 1.5, 3)], "skipped": 0}
    assert drop_placeholders(받은것) is 받은것
