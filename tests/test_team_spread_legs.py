"""스프레드 다리 찾기 시험 — 줄은 실제 마스터(2026-11-04)·품목 세부정보 기록(2026-09-09)에서 옮긴 것."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.master.master_files import MASTER_FILES_BY_NAME
from backend.team_pyrun import api
from backend.team_spread.legs import Leg, LegError, master_rows, next_month, resolve

ROWS = json.loads((Path(__file__).parent / "fixtures" / "team_spread" / "legs.json").read_text("utf-8"))
TODAY = "20261109"


def _resolve(name, spec, **over):
    return resolve(name, spec, today=TODAY, **{**ROWS, **over})


def test_해외_뿌리는_만기일_기준_최근월물():
    leg = _resolve("ho", "HO")
    assert (leg.sym, leg.exchange, leg.market, leg.tick, leg.tick_value) == ("HOZ26", "FCME", "overseas", 0.0001, 4.2)
    assert leg.point_value == pytest.approx(42000) and leg.currency == "USD" and leg.expiry.startswith("202612")
    assert leg.product == "HO" and leg.name == "ho"


def test_표지가_없으면_만기년월이_가장_이른_줄():
    rows = [{**r, "lmon_my": "0"} for r in ROWS["overseas_rows"]]
    assert _resolve("rb", "RB", overseas_rows=rows).sym == "RBZ26"


def test_정확한_종목코드도_된다():
    leg = _resolve("ho", "HOF27")
    assert leg.sym == "HOF27" and leg.product == "HO" and leg.expiry == "202701"


def test_국내_미국달러선물():
    leg = _resolve("usd", "A75")
    assert leg.market == "domestic" and leg.tick == 0.1 and leg.tick_value == 1000 and leg.currency == "KRW"
    assert leg.sym == "A756B000" and leg.expiry == "20261116" and leg.point_value == pytest.approx(10000)
    assert (leg.tick, leg.tick_value) == api.usd_spec(ROWS["domestic_details"])


def test_국내_이미_지난_월물은_뺀다():
    assert resolve("usd", "A75", today="20261117", **ROWS).sym == "A756C000"


def test_국내_정확한_종목코드():
    assert _resolve("usd", "A756C000").expiry == "20261221"


def test_MKU_는_지금_파이썬_전략_탭과_같은_값():
    leg = _resolve("mku", "MKU")
    assert (leg.exchange, leg.tick, leg.tick_value) == ("FSGX", 0.0001, 2.5)
    assert (leg.tick, leg.tick_value) == api.mku_spec(ROWS["overseas_details"])
    assert leg.sym == "MKUX26"


@pytest.mark.parametrize("spec", ["XX", "HOZ99", "", "HO/Z26"])
def test_모르는_종목은_LegError(spec):
    with pytest.raises(LegError):
        _resolve("x", spec)


def test_세부정보에_품목이_없으면_통화를_지어내지_않는다():
    with pytest.raises(LegError, match="통화"):
        _resolve("ho", "HO", overseas_details=[d for d in ROWS["overseas_details"] if d["prd_cd"] != "HO"])


def test_국내_다른_품목은_틱을_추측하지_않는다():
    other = [{**r, "series": "A0163000", "under_name": "KOSPI"} for r in ROWS["domestic_rows"]]
    with pytest.raises(LegError, match="이 국내 품목의 틱을 찾지 못했습니다"):
        _resolve("k", "A01", domestic_rows=other)


def test_국내_틱가치가_다르면_LegError():
    bad = [{**d, "tick_val": "0000000000500.00000000"} for d in ROWS["domestic_details"]]
    with pytest.raises(LegError, match="틱"):
        _resolve("usd", "A75", domestic_details=bad)


def test_다음_월물():
    assert next_month(_resolve("ho", "HO"), **{k: ROWS[k] for k in ("overseas_rows", "domestic_rows")}) == "HOF27"
    assert next_month(_resolve("ho", "HOF27"), **{k: ROWS[k] for k in ("overseas_rows", "domestic_rows")}) == "HOG27"
    assert next_month(_resolve("usd", "A75"), overseas_rows=ROWS["overseas_rows"], domestic_rows=ROWS["domestic_rows"]) == "A756C000"


def test_다음_월물이_없으면_LegError():
    leg = _resolve("ho", "HOF27")
    with pytest.raises(LegError):
        next_month(leg, overseas_rows=[r for r in ROWS["overseas_rows"] if r["code"] != "HOG27"], domestic_rows=[])


def _write(base: Path, name: str, rows: list[dict], stamp: str = "20261104") -> None:
    folder = base / stamp
    folder.mkdir(parents=True, exist_ok=True)
    fields = MASTER_FILES_BY_NAME[name].fields
    (folder / f"{name}.mst").write_text(
        "\n".join(";".join(r[f] for f in fields) for r in rows) + "\n", encoding="utf-8")


def _write_all(base: Path, skip: str = "", stamps: dict | None = None) -> None:
    ov = ROWS["overseas_rows"]
    parts = {
        "cme_fut": [r for r in ov if r["comd"] != "MKU"], "etc_fut": [r for r in ov if r["comd"] == "MKU"],
        "idx_fut_opt": ROWS["domestic_rows"], "fut_opt": [], "stk_fut_opt": [],
    }
    for name, rows in parts.items():
        if name != skip:
            _write(base, name, rows, (stamps or {}).get(name, "20261104"))


def test_master_rows_는_해외_선물과_국내_선물_줄을_읽는다(tmp_path):
    _write_all(tmp_path)
    o, d = master_rows(tmp_path)
    assert {r["code"] for r in o} == {r["code"] for r in ROWS["overseas_rows"]}
    assert {r["series"] for r in d} == {"A756B000", "A756C000"}


def test_master_rows_마스터가_없으면_LegError(tmp_path):
    with pytest.raises(LegError, match="마스터"):
        master_rows(tmp_path)


def test_master_rows_파일_하나가_빠지면_그_이름을_담아_LegError(tmp_path):
    _write_all(tmp_path, skip="cme_fut")
    with pytest.raises(LegError, match="cme_fut"):
        master_rows(tmp_path)


def test_master_rows_파일마다_날짜가_다르면_LegError(tmp_path):
    _write_all(tmp_path, stamps={"cme_fut": "20261103"})
    with pytest.raises(LegError, match="날짜"):
        master_rows(tmp_path)


def test_국내_주야간_줄이_함께_있어도_늘_같은_값():
    rows = ROWS["domestic_rows"]
    assert {r["cme_tp"] for r in rows} == {"day", "night"}
    for order in (rows, rows[::-1]):
        for spec in ("A75", "A756B000"):
            leg = resolve("usd", spec, today=TODAY, **{**ROWS, "domestic_rows": order})
            assert (leg.exchange, leg.sym) == ("KRX", "A756B000")


def test_해외_근월_표지가_낡아_만기_지난_월물이면_다음_월물():
    rows = [{**r, "lmon_my": "1" if r["code"] == "HOZ26" else "0"} for r in ROWS["overseas_rows"]]
    assert resolve("ho", "HO", today="20261215", **{**ROWS, "overseas_rows": [r for r in rows if r["code"] != "x"]}).sym == "HOZ26"
    stale = [{**r, "yymm": "202610", "lmon_my": "1"} if r["code"] == "HOZ26" else {**r, "lmon_my": "0"} for r in ROWS["overseas_rows"]]
    assert resolve("ho", "HO", today=TODAY, **{**ROWS, "overseas_rows": stale}).sym == "HOF27"


def test_Leg_는_불변이다():
    leg = _resolve("ho", "HO")
    assert isinstance(leg, Leg)
    with pytest.raises(AttributeError):
        leg.tick = 1  # type: ignore[misc]
