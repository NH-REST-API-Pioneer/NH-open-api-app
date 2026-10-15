"""해외 만기일 조회 응답이 화면 모양으로 바뀌는지.

저장 기록(real)은 종목 하나짜리 조회 둘(선물 MESU26, 옵션 시리즈)에 줄이 하나씩
있고, 나머지 여섯은 잔존일 기준이 짧아 0줄입니다.
"""
from __future__ import annotations

from backend.nh_api.fixtures import load_fixtures
from backend.overseas_futureoption.overseas_products import expiries


def 만기줄(**덮어쓰기):
    한줄 = {
        "occurs1_sym": "ZZZZ26",
        "occurs1_sym_nm": "지어낸 선물",
        "occurs1_sett_nm": "현금결제",
        "occurs1_exch_cd": "CME",
        "occurs1_fst_ntf_dt": "20260918",
        "occurs1_exp_dt": "20260918",
        "occurs1_lst_sett_dt": "20260921",
        "occurs1_rem_dy": "000009",
        "occurs1_prd_cd": "ZZZ",
    }
    한줄.update(덮어쓰기)
    return 한줄


def test_만기_한_줄이_화면_이름으로_바뀐다():
    답 = expiries(
        {"nrec": "0001", "nxt_key": "", "Occurs1": [만기줄()]},
        asked="ZZZZ26",
        remaining_days_limit="999",
    )

    assert 답["code"] == "ZZZZ26"
    assert 답["market"] == "overseas"
    assert 답["count"] == 1
    assert 답["nextKey"] == ""
    assert 답["remainingDaysLimit"] == 999
    assert 답["rows"] == [
        {
            "code": "ZZZZ26",
            "name": "지어낸 선물",
            "productCode": "ZZZ",
            "exchange": "CME",
            "settlement": "현금결제",
            "firstNotice": "2026-09-18",
            "expiry": "2026-09-18",
            "lastSettlement": "2026-09-21",
            "remainingDays": 9,
        }
    ]


def test_날짜가_없거나_날짜가_아니면_null_이다():
    줄 = expiries(
        {"Occurs1": [만기줄(occurs1_fst_ntf_dt="", occurs1_exp_dt="20261345", occurs1_rem_dy="")]},
        asked="ZZZZ26",
        remaining_days_limit="30",
    )["rows"][0]
    assert 줄["firstNotice"] is None
    assert 줄["expiry"] is None
    assert 줄["lastSettlement"] == "2026-09-21"
    assert 줄["remainingDays"] is None


def test_줄이_없으면_빈_목록이다():
    """실제 0건 응답은 `Occurs1` 칸 자체가 없습니다."""
    for 빈것 in ({"nrec": "0000", "nxt_key": ""}, {"Occurs1": []}, {"Occurs1": None}):
        답 = expiries(빈것, asked="ZZZZ26", remaining_days_limit="999")
        assert 답["rows"] == [], 빈것
        assert 답["code"] == "ZZZZ26"


def test_저장_기록의_만기가_날짜_셋으로_나온다():
    기록들 = [f for f in load_fixtures().http if f.api_id == "overseas_product-expiry"]
    assert 기록들, "저장 기록이 없습니다"
    줄있음 = 0
    for 기록 in 기록들:
        답 = expiries(
            기록.response, asked=기록.request["sym"], remaining_days_limit=기록.request["rem_dy"]
        )
        assert 답["remainingDaysLimit"] == int(기록.request["rem_dy"])
        for 줄 in 답["rows"]:
            줄있음 += 1
            assert 줄["expiry"] and 줄["firstNotice"] and 줄["lastSettlement"]
            assert 줄["remainingDays"] is not None
            assert 줄["productCode"] and 줄["exchange"]
    assert 줄있음 >= 2, "선물·옵션 한 줄씩은 있어야 합니다"


def test_만기_조회로_받은_만기일로_남은_날을_센다(monkeypatch):
    from datetime import date

    from backend.overseas_futureoption import overseas_products

    monkeypatch.setattr(overseas_products, "_EXPIRIES", {})
    expiries(
        {"Occurs1": [{"occurs1_sym": "ZZZZ26", "occurs1_exp_dt": "20261218"}, {"occurs1_sym": "ZZZH27"}]},
        asked="ZZZZ26",
        remaining_days_limit="999",
    )

    # 만기 조회의 잔존일과 같은 셈(만기일 − 오늘)입니다.
    assert overseas_products.days_left("ZZZZ26", date(2026, 9, 29)) == 80
    assert overseas_products.days_left("ZZZZ26", date(2026, 12, 18)) == 0
    assert overseas_products.days_left("ZZZZ26", date(2026, 12, 20)) == 0, "지난 만기는 0 입니다."
    assert overseas_products.days_left("ZZZH27", date(2026, 9, 29)) is None, "만기일이 없던 줄"
    assert overseas_products.days_left("ZZZM27", date(2026, 9, 29)) is None, "받은 적 없는 종목"
