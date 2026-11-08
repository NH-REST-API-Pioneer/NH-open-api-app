"""스프레드 문서·예제 — 예제 실행기가 불러와지고 재생으로 돌며, 문서의 코드 블록이 불러와지고, 문서가 ctx 이름을 다 설명한다."""
import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.team_spread import replay as rp
from backend.team_spread.legs import Leg
from backend.team_spread.runner_files import load_runner

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "team" / "examples"
DOC = ROOT / "docs" / "team" / "spread-runner-convention.md"
PROMPT = ROOT / "docs" / "team" / "strategy-file-prompt.md"

HO = Leg("ho", "HO", "HO", "overseas", "", "USD", 0.0001, 4.2, "")
RB = Leg("rb", "RB", "RB", "overseas", "", "USD", 0.0001, 4.2, "")
T0 = datetime(2026, 11, 9, 9, 0, 0)


def _csv(path: Path, closes: list[float]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ref_dt", "exch_tm", "open_pric", "high_pric", "low_pric", "close_pric", "cum_trd_qty"])
        for i, c in enumerate(closes):
            t = T0 + timedelta(minutes=i)
            w.writerow([t.strftime("%Y%m%d"), t.strftime("%H%M%S"), c, c, c, c, 10])
    return path


def test_example_loads():
    r = load_runner(EXAMPLES, "spread_rolling_beta.py")
    assert r.legs == {"ho": "HO", "rb": "RB"} and r.name == "spread_rolling_beta" and r.max_qty == 2


def test_example_replays_and_makes_a_paired_trade(tmp_path):
    loaded = load_runner(EXAMPLES, "spread_rolling_beta.py")
    n = 140
    rb = [2.5 + 0.001 * ((i * 7) % 5) for i in range(n)]
    ho = [2.6 + 1.2 * (r - 2.5) + 0.0005 * ((i * 3) % 4) for i, r in enumerate(rb)]
    for i in range(100, 104):          # HO 만 갑자기 튀어 스프레드가 벌어졌다가 돌아온다
        ho[i] += 0.05
    csvs = {"ho": _csv(tmp_path / "ho.csv", ho), "rb": _csv(tmp_path / "rb.csv", rb)}
    out = tmp_path / "out"
    summary = rp.replay(loaded, csvs, {"ho": HO, "rb": RB}, out)
    rows = [json.loads(x) for x in (out / "journal.jsonl").read_text("utf-8").splitlines()]
    fills = [r for r in rows if r["kind"] == "fill"]
    assert any(r["kind"] == "log" and r["name"] == "z" and "beta" in r for r in rows)
    assert {(f["leg"]) for f in fills} == {"ho", "rb"}
    first = [f for f in fills if f["clock"] == fills[0]["clock"]]
    assert sorted(f["qty"] for f in first) == [-1, 1]           # 한 번에 짝
    assert summary["total"]["USD"]["fills"] >= 2


def _python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, re.S)


def test_every_runner_block_in_the_convention_loads(tmp_path):
    blocks = [b for b in _python_blocks(DOC.read_text("utf-8")) if "LEGS" in b]
    assert blocks
    for i, code in enumerate(blocks):
        (tmp_path / f"b{i}.py").write_text(code, encoding="utf-8")
        load_runner(tmp_path, f"b{i}.py")


@pytest.mark.parametrize("name", ["leg", "bars", "next_minute", "quote", "position", "inherited", "running", "now",
                                  "sleep", "market_open", "log", "roll", "order", "target", "Fill", "price_known",
                                  "OrderRejected", "Halted", "LEGS", "run(ctx)", "TITLE", "NAME", "MAX_QTY"])
def test_convention_mentions_public_names(name):
    text = DOC.read_text("utf-8")
    assert (f"ctx.{name}" in text) if name in {"leg", "bars", "next_minute", "quote", "position", "inherited", "running",
                                               "now", "sleep", "market_open", "log", "roll", "order", "target"} \
        else name in text


def test_prompt_has_spread_section():
    text = PROMPT.read_text("utf-8")
    assert "스프레드 실행기" in text and "ctx.target" in text and "OrderRejected" in text
