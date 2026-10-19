"""같은 종목코드로 온 두 줄을 접을 때 **진짜 충돌만** 빼는지.

실물 배포본(2026-10-12)에는 같은 종목의 두 줄이 일부 칸만 다르게 오는 경우가 둘
있습니다. 둘 다 같은 종목이라 색인에서 빠지면 안 됩니다.

* 국내 위클리 옵션의 주간·야간 줄이 실시간상한가 적용여부(`dynmc_yn`)만 다른 경우 —
  세션마다 달라질 수 있는 칸이라 충돌로 세지 않고 종목은 살립니다
* 해외 옵션이 두 번 실리면서 한 줄만 공백 모양이 다른 경우 — 같은 줄로 봅니다

반대로 승수처럼 두 줄에서 같아야 할 칸이 갈리면 전처럼 빼고 알립니다.
"""
from __future__ import annotations

import pytest

from backend.master.master_files import MASTER_FILES_BY_NAME
from backend.master.master_index import NIGHT_SESSION, build_index
from backend.master.master_store import load_all, save_master
from tests.fixtures.master import folding_path

_LOGGER = "backend.master.master_index"

_위클리_풋 = (
    "CAFC1925",
    "CAFC1927",
    "CAFC1930",
    "CAFC1935",
    "CAFC1940",
    "CAFC1945",
    "CAFC1950",
    "CAFC1997",
)
_해외_옵션 = "O_CLQ28-C66.00"


def _lines(name: str) -> list[str]:
    return folding_path(name).read_text(encoding="utf-8").splitlines()


def _save(tmp_path, name: str, lines: list[str]) -> None:
    save_master(
        MASTER_FILES_BY_NAME[name],
        ("\n".join(lines) + "\n").encode("utf-8"),
        stamp="20261012",
        base_dir=tmp_path,
    )


def _build(tmp_path, caplog, *, fut_opt=None, cme_opt=None):
    _save(tmp_path, "fut_opt", fut_opt if fut_opt is not None else _lines("fut_opt"))
    _save(tmp_path, "cme_opt", cme_opt if cme_opt is not None else _lines("cme_opt"))
    with caplog.at_level("WARNING", logger=_LOGGER):
        return build_index(load_all(tmp_path))


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER]


def test_조각은_실물에서_본_모양_그대로다():
    """조각이 시험하려는 성질을 정말 담고 있는지부터 봅니다."""
    fut = [line.split(";") for line in _lines("fut_opt")]
    assert sorted({row[8] for row in fut}) == sorted(_위클리_풋)
    for row in fut:
        assert row[19] == ("Y" if row[5] == "day" else "N")

    first, second = _lines("cme_opt")
    assert first != second
    assert first.split(";")[0] == _해외_옵션
    assert second.split(";")[0] == _해외_옵션 + "   "


def test_세션별_칸과_공백만_다른_줄은_색인에서_안_빠진다(tmp_path, caplog):
    built = _build(tmp_path, caplog)
    payload = built.payload

    assert payload["folding_conflicts"] == []
    assert _warnings(caplog) == []

    # 국내 위클리 풋 8종 — 주간·야간이 한 종목으로 접혀 신원표에 한 번씩 섭니다.
    신원 = [row[0] for row in payload["domestic_option_index"]["rows"]]
    assert sorted(신원) == sorted(_위클리_풋)
    국내만기 = [e for e in payload["option_expiries"] if e["market"] == "domestic"]
    assert sum(e["contract_count"] for e in 국내만기) == len(_위클리_풋)
    for code in _위클리_풋:
        assert built.locate("domestic", code) is not None

    # 해외 옵션 — 두 번 실렸지만 한 종목입니다. 내보내는 이름은 첫 줄의 원문입니다.
    (해외만기,) = [e for e in payload["option_expiries"] if e["market"] == "overseas"]
    assert 해외만기["contract_count"] == 1
    줄 = built.locate("overseas", _해외_옵션)
    assert 줄 is not None
    assert 줄["enam"] == "NY CRUDE OIL option C66.00 (202808)"
    (체인줄,) = built.chain(market="overseas", product_code="O_CL", expiry="202808")
    assert 체인줄["code"] == _해외_옵션
    assert 체인줄["enam"] == "NY CRUDE OIL option C66.00 (202808)"


def test_세션별_칸은_접은_줄에서_빠지고_표에는_세션마다_남는다(tmp_path, caplog):
    built = _build(tmp_path, caplog)

    # 접어서 내보내는 줄에는 세션별 칸이 없습니다 — 어느 세션 값인지 사라지므로.
    접은줄 = built.locate("domestic", "CAFC1925")
    assert "dynmc_yn" not in 접은줄
    assert "dynmc_up_p" not in 접은줄
    assert "dynmc_dn_p" not in 접은줄

    # 읽어 둔 표에는 주간 줄과 야간 줄이 각자의 값으로 그대로 있습니다.
    table = built.tables["fut_opt"]
    세션별 = {
        row["cme_tp"]: row
        for row in (dict(zip(table.fields, raw)) for raw in table.rows)
        if row["series"] == "CAFC1925"
    }
    assert set(세션별) == {"day", NIGHT_SESSION}
    assert (세션별["day"]["dynmc_yn"], 세션별["day"]["dynmc_up_p"]) == ("Y", "0.00")
    assert (세션별[NIGHT_SESSION]["dynmc_yn"], 세션별[NIGHT_SESSION]["dynmc_up_p"]) == (
        "N",
        "2.81",
    )


@pytest.mark.parametrize(
    ("market", "code", "at", "value", "field"),
    [
        # 국내 야간 줄의 거래승수만 바꿉니다. 원래는 두 줄에서 같은 값입니다.
        ("domestic", "CAFC1925", 17, "999", "ctrt_size"),
        # 해외 둘째 줄의 거래단위만 바꿉니다.
        ("overseas", _해외_옵션, 10, "99.000000", "tsiz"),
    ],
)
def test_같아야_할_칸이_갈리면_전처럼_빼고_알린다(tmp_path, caplog, market, code, at, value, field):
    fut = _lines("fut_opt")
    cme = _lines("cme_opt")
    if market == "domestic":
        (night_at,) = [
            i for i, line in enumerate(fut)
            if line.split(";")[8] == code and line.split(";")[5] == NIGHT_SESSION
        ]
        row = fut[night_at].split(";")
        row[at] = value
        fut[night_at] = ";".join(row)
    else:
        row = cme[1].split(";")
        row[at] = value
        cme[1] = ";".join(row)

    built = _build(tmp_path, caplog, fut_opt=fut, cme_opt=cme)
    payload = built.payload

    assert payload["folding_conflicts"] == [
        {"market": market, "code": code, "fields": [field]}
    ]
    (경고,) = _warnings(caplog)
    assert "색인에서 뺐습니다" in 경고
    assert f"{code}({field})" in 경고

    # 그 종목만 빠지고 나머지는 그대로 섭니다.
    신원 = {row[0] for row in payload["domestic_option_index"]["rows"]}
    해외수 = sum(
        e["contract_count"] for e in payload["option_expiries"] if e["market"] == "overseas"
    )
    if market == "domestic":
        assert 신원 == set(_위클리_풋) - {code}
        assert 해외수 == 1
    else:
        assert 신원 == set(_위클리_풋)
        assert 해외수 == 0
