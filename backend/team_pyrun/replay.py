"""받아 둔 1분봉으로 하루를 다시 돌린다 — 서버 접속도 주문도 없고, 체결은 종이 체결.

코드 점검과 week02·week03 결과 비교용입니다(해외 MKU 는 `market=OVERSEAS` — `tests/test_team_pyrun_orb.py` 골든). 순서는 week02 `replay()` 와 같습니다: 그 분의 시가로
`on_price`(진입·정리) → 종가와 고저로 `on_price`(손절·익절) → `on_minute_closed`(그 봉으로 신호).

    python -m backend.team_pyrun.replay <전략파일> <YYYYMMDD> <csv>

전략 파일 이름에 폴더가 없으면 전략 폴더에서 찾고, 결과는 `<상태 폴더>/pyruns/<날짜>_<NAME>_replay/` 에
(같은 이름 폴더가 있으면 비우고) 씁니다: `journal.jsonl` `summary.json` `run.json`.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from backend import storage
from backend.sessions.hours import now_kst
from backend.team_pyrun.journal import Journal, summarize, write_summary
from backend.team_pyrun.loader import DEFAULT_FLATTEN, Loaded, load, strategies_dir
from backend.team_pyrun.markets import DOMESTIC, Market
from backend.team_pyrun.runner import PAPER_FEE, PAPER_SLIP_TICKS, Minute, PaperBroker, Runner

MIN_BARS_PER_DAY = 250      # 이보다 봉이 적은 날(거래가 드문 원월물 시절)은 뺍니다 (week02 와 같음)
DEFAULT_SYM = "A756B000"


def load_minutes(csv_path: Path) -> list[Minute]:
    """1분봉 csv(`ref_dt exch_tm open_pric …`)를 읽는다. 하루 250봉 미만인 날은 뺀다."""
    with Path(csv_path).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    per_day: dict[str, int] = {}
    for r in rows:
        per_day[r["ref_dt"]] = per_day.get(r["ref_dt"], 0) + 1
    return [Minute(r["ref_dt"], r["exch_tm"], float(r["open_pric"]), float(r["high_pric"]),
                   float(r["low_pric"]), float(r["close_pric"]), float(r["cum_trd_qty"] or 0))
            for r in rows if per_day[r["ref_dt"]] >= MIN_BARS_PER_DAY]


def _stamp() -> str:
    return now_kst().isoformat(timespec="seconds").removesuffix("+09:00")


def replay(loaded: Loaded, date: str | None, minutes: list[Minute], folder: Path, sym: str = DEFAULT_SYM, *,
           market: Market = DOMESTIC, fee: float = PAPER_FEE, slip_ticks: int = PAPER_SLIP_TICKS) -> dict:
    """`date` 하루를 다시 돌려 `folder` 에 기록하고 `{"trades", "summary"}` 를 돌려준다.

    그 전 날들은 준비 봉으로 전략에만 넣습니다. `date` 가 None 이면 `minutes` 의 **모든 날을 날마다 이어** 돕니다
    (week03 `backtest.run` 처럼 — 전략은 한 번 만들어 날을 넘겨 이어지고, 날이 바뀌면 대기 신호는 버리고, 날마다
    끝에 남은 보유를 정리). `sym` 은 `run.json` 에 적을 종목.

    `market` 은 빠진 Params 장 시간 칸을 채우고(`loaded.new(market)`), 하루 끝 정리 시각(국내 153000 · 해외 235000,
    `loader.DEFAULT_FLATTEN`)을 정합니다. `fee`(체결마다, 그 시장 통화)·`slip_ticks`(불리한 쪽 틱)는 종이 체결 값.
    기본값은 모두 국내(week02) 그대로입니다."""
    folder = Path(folder)
    started = _stamp()
    j = Journal(folder / "journal.jsonl")
    r = Runner(loaded.new(market), j, PaperBroker(j, loaded.tick, fee=fee, slip_ticks=slip_ticks),
               loaded.tick, loaded.tick_value)
    days = sorted({m.date for m in minutes}) if date is None else [date]
    flat_at = DEFAULT_FLATTEN[market.id]
    if days:
        r.warmup([m for m in minutes if m.date < days[0]])
    for day in days:
        if r.pending is not None:      # 전날 마지막 신호 — 다음 날로 넘기지 않는다 (백테스트도 날이 바뀌면 버림)
            j.write("event", text="날이 바뀌어 대기 신호를 버림")
            r.pending = None
        r.live_date = day
        for m in (m for m in minutes if m.date == day):
            if not (r.p.session_start <= m.time < r.p.session_end):
                r.feed(m)
                continue
            # 그 분의 가격 범위를 한 번에 줌: 시가에서 진입·정리, 고저로 손절·익절 (백테스트와 같은 순서)
            r.on_price(m.time, m.open)
            r.on_price(m.time, m.close, ref_low=m.low, ref_high=m.high)
            r.on_minute_closed(m)
        r.force_flat(flat_at)
    result = {"trades": r.trades, "summary": summarize(r.trades)}
    # 실시간 실행의 summary.json 과 같은 꼴로 전략 정보도 남긴다 — 지난 실행 화면이 그때의 Params 를 보인다
    write_summary(folder, {**result, "strategy": {
        "file": loaded.file, "name": loaded.name, "title": loaded.title,
        "sha256": loaded.sha256, "params": asdict(r.p)}})
    (folder / "run.json").write_text(json.dumps({
        "id": folder.name, "file": loaded.file, "name": loaded.name, "title": loaded.title,
        "sha256": loaded.sha256, "mode": "replay", "sym": sym, "state": "끝",
        "started_at": started, "ended_at": _stamp(), "ended_reason": "리플레이",
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or not re.fullmatch(r"\d{8}", args[1]):
        print("사용법: python -m backend.team_pyrun.replay <전략파일> <YYYYMMDD> <csv>", file=sys.stderr)
        return 2
    file, date, data = args
    path = Path(file)
    folder, name = (path.parent, path.name) if path.parent != Path(".") else (strategies_dir(), file)
    loaded = load(folder, name)
    out = storage.state_dir() / "pyruns" / f"{date}_{loaded.name}_replay"
    if out.exists():
        shutil.rmtree(out)
    m = re.search(r"bars_1m_([A-Za-z0-9]+)_\d{8}", Path(data).name)
    result = replay(loaded, date, load_minutes(Path(data)), out, sym=m.group(1) if m else DEFAULT_SYM)
    s = result["summary"]
    print(f"{loaded.name} {date}: 거래 {s['trades']}건 · 손익 {s['net_pnl']:+,}원 · {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
