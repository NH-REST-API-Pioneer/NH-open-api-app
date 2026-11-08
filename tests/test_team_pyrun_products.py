"""파이썬 전략 탭 종목 찾기 시험 — 국내 확인 표(설계 4.1)와 `find_product`."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.team_pyrun import api, markets, products
from backend.team_pyrun.live import StartRefused
from backend.team_spread.legs import Leg, LegError, resolve

HERE = Path(__file__).parent
ROWS = json.loads((HERE / "fixtures" / "team_spread" / "legs.json").read_text("utf-8"))
_REC = HERE / "fixtures/nh/domestic_product-detail/real/domestic/20260909T000211_6a8f237bf722.json"
DETAILS = api.rows(json.loads(_REC.read_text("utf-8"))["response"])
TODAY = "20261109"

# 뿌리 → (계약 크기, 틱, 틱 가치) — 설계 4.1 표
TABLE = {
    "A01": (250000, 0.05, 12500), "A05": (50000, 0.02, 1000), "A06": (10000, 0.1, 1000), "A08": (50000, 0.2, 10000),
    "A04": (250000, 0.05, 12500), "A65": (1000000, 0.01, 10000), "A66": (1000000, 0.01, 10000),
    "A67": (1000000, 0.01, 10000), "A70": (1000000, 0.01, 10000), "A75": (10000, 0.1, 1000),
    "A76": (10000, 0.1, 1000), "A77": (10000, 0.1, 1000), "A78": (100000, 0.01, 1000),
    "AAG": (10000, 0.1, 1000), "AAL": (10000, 0.2, 2000),
}


def _row(root, *, size="10000", key="KFXFNDV", cme="day", series=None, exp="20261211"):
    return {"series": series or f"{root}6C000", "kospi_key": key, "exp_ym": exp, "ctrt_size": size,
            "fo_tp": "F", "cme_tp": cme, "name_kor": f"{root} 테스트 F 202612", "under_name": root}


def _resolve(spec, rows):
    return resolve("main", spec, today=TODAY, overseas_rows=[], domestic_rows=rows,
                   overseas_details=[], domestic_details=DETAILS)


@pytest.mark.parametrize("root", list(TABLE))
def test_확인_표의_뿌리는_모두_찾는다(root):
    size, tick, value = TABLE[root]
    leg = _resolve(root, [_row(root, size=str(size))])
    assert (leg.tick, leg.tick_value, leg.market, leg.currency) == (pytest.approx(tick), pytest.approx(value), "domestic", "KRW")


def test_주식선물은_까닭을_말하고_거절():
    with pytest.raises(LegError, match="주식선물"):
        _resolve("A11", [_row("A11", key="STKFBASE")])


def test_표_밖_품목은_틱_확인_표에_없다고_거절():
    with pytest.raises(LegError, match="틱 확인 표에 없습니다") as e:
        _resolve("AA0", [_row("AA0")])
    assert "AA0" in str(e.value)


def test_야간_줄과_주간_줄이_같이_있으면_주간():
    rows = [_row("A01", size="250000", cme="night", series="A016C0N0"), _row("A01", size="250000", cme="day")]
    assert _resolve("A01", rows).sym == "A016C000"


class FakeApi:
    def product_detail(self):
        return DETAILS

    def ovs_product_detail_page(self, group, key=""):
        return list(ROWS["overseas_details"]), ""


def _find(spec, **kw):
    return products.find_product(spec, api_module=FakeApi(), today=TODAY,
                                 master=lambda: (ROWS["overseas_rows"], ROWS["domestic_rows"]), **kw)


def test_find_product_HO():
    leg = _find("HO")
    assert (leg.sym, leg.exchange, leg.tick, leg.tick_value, leg.currency) == ("HOZ26", "FCME", 0.0001, 4.2, "USD")


def test_find_product_A75와_MKU는_지금_상수와_같다():
    usd = _find("A75")
    assert (usd.sym, usd.currency, usd.tick, usd.tick_value) == ("A756B000", "KRW", 0.1, 1000)
    mku = _find("MKU")
    assert (mku.sym, mku.exchange, mku.tick, mku.tick_value, mku.currency) == ("MKUX26", "FSGX", 0.0001, 2.5, "USD")


def test_find_product_거부_메시지에_내부_다리_이름이_없다():
    with pytest.raises(StartRefused) as e:
        _find("ZZZ9")
    assert "main" not in str(e.value) and "ZZZ9" in str(e.value)
    assert not str(e.value).startswith("다리")


def _loaded(tick, value):
    return SimpleNamespace(tick=tick, tick_value=value)


def test_틱가치가_다른_전략은_거부_같으면_None():
    ho = _find("HO")
    msg = products.strategy_tick_refusal(ho, _loaded(0.0001, 2.5))
    assert msg == "틱·틱가치가 전략 가정과 다릅니다 — 종목 HOZ26 0.0001·4.2 USD, 전략 0.0001·2.5"
    assert products.strategy_tick_refusal(ho, _loaded(0.0001, 4.2)) is None


def test_domestic_roots_표_순서():
    got = products.domestic_roots()
    assert [r["root"] for r in got] == list(TABLE)
    assert got[0] == {"root": "A01", "name": "코스피200선물"} and got[9] == {"root": "A75", "name": "미국달러선물(USD)"}


def test_account_market과_is_mku():
    assert products.account_market(_find("HO")) is markets.OVERSEAS
    assert products.account_market(_find("A75")) is markets.DOMESTIC
    assert products.is_mku("MKU") and not products.is_mku("HO") and not products.is_mku(None)
    assert isinstance(_find("HO"), Leg)
