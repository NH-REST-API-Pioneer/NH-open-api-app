"""스프레드 재생 — 같은 실행기를 다리별 1분봉 csv 로 서버 없이 돌린다 (설계 12장).

    uv run python -m backend.team_spread.replay <실행기.py> <다리>=<csv>:<tick>:<tick_value>:<통화> ...
    uv run python -m backend.team_spread.replay <실행기.py> <다리>=<csv>[:<통화>] ... --legs-from-master

`SpreadRun` 을 그대로 쓴다(수명·정리·요약·기록 폴더 꼴이 실제 실행과 같다). 달라지는 것은 시세 공급(`ReplayFeed`)과
종이 장부(`ReplayPaperBook`), 그리고 다리를 마스터·서버 없이 직접 받는다는 것뿐이다. 서버 접속은 없다 —
넘긴 api 모듈은 불리지 않고(기본은 부르면 바로 오류), 전송(`runtime.client`)도 쓰지 않는다.

- 시계 = 봉 시각(그 분의 시작). 실행기가 `next_minute` 로 받은 분이 곧 지금이다.
- 체결 = 그 다음 분 시가 ± 슬리피지 1틱(사면 +, 팔면 −; 마지막 분 뒤·장 쉼/날 바뀜으로 안 이어질 때·그 다리 다음 봉이 채운 봉일 때는 지금 분 종가 ± 1틱), 수수료는 시장별 종이 값.
  `ctx.quote` 는 지금 분 종가, 매수·매도 호가 = 종가 ± ½틱.
- 장 쉼: 다리의 봉이 없는 분은 그 다리가 쉬는 분(`market_open` 거짓 → 주문 거부). 어느 다리에도 봉이 없는 구간은
  공백(`장 쉼`)으로 밝히고 건너뛴다.
- csv 가 끝나면 `next_minute` 가 `None` 을 주고 중지 표지를 세운다(`ctx.running()` 거짓) — 실행기가 돌려주면 보유를
  실제 실행처럼 정리한다(마지막 분 종가 ± 1틱). 같은 입력은 같은 거래·손익이다(기록의 `at` 만 실제 시각).
- 결과 폴더: `<상태 폴더>/spreads/<첫 봉 날짜>_<NAME>_replay[_n]/`. csv 칸은 파이썬 전략 재생과 같은 차트 칸.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend import storage
from backend.sessions.hours import KST
from backend.team_pyrun.live import StartRefused
from backend.team_pyrun.loader import LoadError
from backend.team_spread.bars import Minute, align
from backend.team_spread.book import PaperBook, market_of_leg
from backend.team_spread.feed import WAIT_CLOSED, WAIT_RUNNING, Quote
from backend.team_spread.legs import Leg, LegError, resolve
from backend.team_spread.run import SpreadRun, SpreadSpec, Timing
from backend.team_spread.runner_files import LoadedRunner, load_runner, spreads_dir

CSV_COLUMNS = ("ref_dt", "exch_tm", "open_pric", "high_pric", "low_pric", "close_pric")
REPLAY_TIMING = Timing(stop_wait=30.0, reconcile=3600.0, retry=0.0, poll=0.005)


class ReplayError(ValueError):
    """재생을 시작할 수 없다(csv·다리 인자 문제). 메시지는 그대로 보인다."""


class _NoApi:
    """재생이 서버를 부르면 바로 오류 — 부르지 않는다는 약속을 눈에 보이게."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"재생은 서버를 부르지 않습니다: {name}")


def read_rows(path: Path) -> list[dict]:
    """csv 의 차트 칸 줄(파이썬 전략 재생과 같은 칸). 칸이 모자라면 `ReplayError`."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ReplayError(f"{path} 에 칸이 없습니다: {', '.join(missing)}")
            rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as e:
        raise ReplayError(f"{path} 를 읽지 못했습니다 — UTF-8 csv 가 아닙니다 ({e})") from e
    for n, row in enumerate(rows, start=2):        # 머리줄이 1번째 줄
        for col in ("ref_dt", "exch_tm"):
            val = (row.get(col) or "").strip()
            if not (val.isdigit() and len(val) == (8 if col == "ref_dt" else 6)):
                raise ReplayError(f"{path} {n}번째 줄 {col} 이(가) 맞지 않습니다: {row.get(col)!r}")
        for col in CSV_COLUMNS[2:]:
            try:
                v = float(row[col])
            except (TypeError, ValueError, KeyError):
                raise ReplayError(f"{path} {n}번째 줄 {col} 이(가) 수가 아닙니다: {row.get(col)!r}") from None
            if not math.isfinite(v):
                raise ReplayError(f"{path} {n}번째 줄 {col} 이(가) 수가 아닙니다: {row.get(col)!r}")
        try:
            datetime.strptime(row["ref_dt"].strip() + row["exch_tm"].strip(), "%Y%m%d%H%M%S")
        except ValueError:
            raise ReplayError(f"{path} {n}번째 줄 시각이 맞지 않습니다: {row['ref_dt']} {row['exch_tm']}") from None
    return rows


def _at(m: Minute) -> datetime:
    return datetime.strptime(m.date + m.time, "%Y%m%d%H%M%S").replace(tzinfo=KST)


class ReplayFeed:
    """csv 로 채운 `Feed`. 시계는 지금까지 준 마지막 분의 시작 시각(아직 안 줬으면 첫 분)."""

    def __init__(self, minutes: list[Minute]):
        self._m = minutes
        self._i = -1
        self._on_wait: Callable[[str, list[str]], None] = lambda state, closed: None
        self._on_gap: Callable[[str, str, str], None] = lambda first, last, cause: None
        self.ended = False

    def attach(self, *, on_wait=None, on_gap=None, **_unused: Any) -> ReplayFeed:
        """`SpreadRun` 이 넘기는 알림 끈을 붙인다(feed_factory 자리)."""
        if on_wait:
            self._on_wait = on_wait
        if on_gap:
            self._on_gap = on_gap
        return self

    def _cur(self) -> Minute:
        return self._m[max(self._i, 0)]

    def now(self) -> datetime:
        return _at(self._cur())

    def sleep(self, seconds: float, stop: threading.Event) -> None:
        stop.wait(0)        # 시계는 봉만 움직인다 — 기다리지 않는다

    def history(self, legs: list[Leg], count: int) -> list[Minute]:
        """지금까지 준 분만(앞을 미리 보여 주지 않는다)."""
        return [self._pick(m, legs) for m in self._m[: self._i + 1]][-count:] if count > 0 else []

    @staticmethod
    def _pick(m: Minute, legs: list[Leg]) -> Minute:
        return Minute(m.date, m.time, {leg.name: m.legs[leg.name] for leg in legs})

    def next_minute(self, legs: list[Leg], stop: threading.Event) -> Minute | None:
        if stop.is_set():
            return None
        nxt = self._i + 1
        if nxt >= len(self._m):
            self.ended = True
            stop.set()          # csv 끝 — `while ctx.running()` 도 끝나게
            return None
        if self._i >= 0:
            prev, cur = _at(self._m[self._i]), _at(self._m[nxt])
            if cur - prev > timedelta(minutes=1):       # 어느 다리에도 봉이 없는 구간 — 장 쉼
                self._on_wait(WAIT_CLOSED, [leg.name for leg in legs])
                self._on_gap((prev + timedelta(minutes=1)).strftime("%Y%m%d %H%M%S"),
                             (cur - timedelta(minutes=1)).strftime("%Y%m%d %H%M%S"), "장 쉼")
                self._on_wait(WAIT_RUNNING, [])
        self._i = nxt
        return self._pick(self._m[nxt], legs)

    def quote(self, leg: Leg) -> Quote:
        bar = self._cur().legs[leg.name]
        px = bar.open if self._i < 0 else bar.close
        return Quote(px, px - leg.tick / 2, px + leg.tick / 2, self.now())

    def is_open(self, leg: Leg, now: datetime) -> bool:
        """지금 분에 그 다리의 진짜 봉이 있어야 열림(직전 종가로 채운 봉은 쉼)."""
        return self._i < 0 or not self._cur().legs[leg.name].filled

    def fill_price(self, leg: Leg, qty: int) -> float:
        """주문 체결가 — 다음 분 시가 ± 슬리피지(마지막 분 뒤엔 마지막 종가 ± 슬리피지)."""
        nxt = self._i + 1
        cur = self._cur()
        base = cur.legs[leg.name].close
        if 0 <= nxt < len(self._m):
            nm = self._m[nxt]
            # 다음 분이 바로 이어진 같은 날의 진짜 봉일 때만 그 시가 — 장 쉼·날 바뀜·채운 봉이면 지금 종가(밤새 틈은 손익에 넣지 않는다)
            contiguous = nm.date == cur.date and _at(nm) - _at(cur) <= timedelta(minutes=1)
            if contiguous and not nm.legs[leg.name].filled:
                base = nm.legs[leg.name].open
        slip = market_of_leg(leg).paper_slip_ticks * leg.tick
        return base + slip if qty > 0 else base - slip


class ReplayPaperBook(PaperBook):
    """종이 장부 — 체결가만 재생 규칙(다음 분 시가 ± 1틱)으로, 수수료·보유·기록은 `PaperBook` 그대로.
    (기록의 체결 글은 `PaperBook` 의 「반대 호가」 글이 그대로 남는다.)"""

    def __init__(self, source: ReplayFeed, feed: Any, journal: Any, *, positions: dict[str, int] | None = None):
        super().__init__(feed, journal, positions=positions)
        self._source = source

    def _opposite(self, leg: Leg, qty: int) -> tuple[float, bool]:
        return self._source.fill_price(leg, qty), True


# ---------------------------------------------------------------- 실행
def _fresh(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise ReplayError(f"결과 폴더가 이미 있습니다: {out}")


def replay(loaded: LoadedRunner, csvs: dict[str, Path], legs: dict[str, Leg], out: Path, *,
           api_module: Any = None) -> dict:
    """`csvs`(다리 → csv)를 맞춰 실행기를 끝까지 돌리고 `out` 에 기록한 뒤 요약(`summary.json`)을 돌려준다."""
    missing = [n for n in loaded.legs if n not in csvs or n not in legs]
    if missing:
        raise ReplayError(f"다리 {', '.join(missing)} 의 csv·다리 정보가 없습니다")
    extra = sorted((set(csvs) | set(legs)) - set(loaded.legs))
    if extra:
        raise ReplayError(f"실행기에 없는 다리입니다: {', '.join(extra)}")
    out = Path(out)
    _fresh(out)
    minutes = align({name: read_rows(csvs[name]) for name in loaded.legs})
    if not minutes:
        raise ReplayError("맞춘 봉이 없습니다 — 모든 다리에 봉이 있는 구간이 있어야 합니다(csv 에 봉이 없음)")
    feed = ReplayFeed(minutes)
    spec = SpreadSpec(loaded.file, "replay", dict(loaded.legs))
    run = SpreadRun(f"{minutes[0].date}_{loaded.name}_replay", out, loaded, spec,
                    api_module=api_module if api_module is not None else _NoApi(), now=feed.now, sleep=lambda s: None,
                    feed_factory=lambda **kw: feed.attach(**kw), master=lambda: ([], []), active_env=lambda: None,
                    timing=REPLAY_TIMING, legs={n: legs[n] for n in loaded.legs},
                    paper_book=lambda f, j, *, positions: ReplayPaperBook(feed, f, j, positions=positions))
    run.prepare()
    run.run_forever()
    return json.loads((out / "summary.json").read_text("utf-8"))


# ---------------------------------------------------------------- 명령줄
def _split(arg: str) -> tuple[str, list[str]]:
    name, sep, rest = arg.partition("=")
    if not sep or not name or not rest:
        raise ReplayError(f"다리 인자는 <다리>=<csv>... 꼴이어야 합니다: {arg!r}")
    return name, rest.rsplit(":", 3) if rest.count(":") >= 3 else rest.split(":")


def _positive(text: str, what: str, arg: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise ReplayError(f"{what} 이(가) 수가 아닙니다: {arg!r}") from None
    if not v > 0 or v == float("inf"):
        raise ReplayError(f"{what} 은(는) 양수여야 합니다: {arg!r}")
    return v


def parse_legs(args: list[str], specs: dict[str, str], *, from_master: bool = False,
               master: Callable[[], tuple[list, list]] | None = None) -> tuple[dict[str, Path], dict[str, Leg]]:
    """`<다리>=<csv>:<tick>:<tick_value>:<통화>`(또는 마스터에서 읽을 때 `<다리>=<csv>[:<통화>]`)를 csv 경로와 `Leg` 로.

    직접 준 꼴은 통화가 KRW 면 국내(거래소 KRX), 아니면 해외다. 종목 표기는 실행기 `LEGS` 에서 온다.
    마스터에서 읽는 꼴은 해외만 됩니다 — 통화는 품목 세부정보(서버)에만 있어 `:<통화>` 로 받고, 국내 틱도 세부정보라 직접 주어야 한다."""
    paths: dict[str, Path] = {}
    legs: dict[str, Leg] = {}
    rows: tuple[list, list] | None = None
    for arg in args:
        name, parts = _split(arg)
        if name not in specs:
            raise ReplayError(f"실행기에 없는 다리입니다: {name}")
        spec = specs[name]
        if from_master:
            if len(parts) > 2:
                raise ReplayError(f"마스터에서 읽을 땐 <다리>=<csv>[:<통화>] 꼴입니다: {arg!r}")
            currency = parts[1] if len(parts) == 2 else ""
            if not currency:
                raise ReplayError(f"다리 {name}: 통화는 마스터에 없어 <다리>=<csv>:<통화> 로 적어야 합니다")
            if rows is None:
                rows = (master or _master_rows)()
            try:
                leg = resolve(name, spec, overseas_rows=rows[0], domestic_rows=[],
                              overseas_details=[{"prd_cd": str(r.get("comd", "")).strip(), "cur_cd": currency}
                                                for r in rows[0]], domestic_details=[])
            except LegError as e:
                raise ReplayError(f"다리 {name}: {e} (국내 다리는 마스터만으로 틱을 알 수 없어 직접 적어야 합니다)") from e
            paths[name], legs[name] = Path(parts[0]), leg
            continue
        if len(parts) != 4:
            raise ReplayError(f"다리 인자는 <다리>=<csv>:<tick>:<tick_value>:<통화> 꼴이어야 합니다: {arg!r}")
        path, tick, value, currency = parts
        tick, value = _positive(tick, "tick", arg), _positive(value, "tick_value", arg)
        if not currency.strip():
            raise ReplayError(f"통화가 비었습니다: {arg!r}")
        domestic = currency.upper() == "KRW"
        paths[name] = Path(path)
        legs[name] = Leg(name, spec, spec, "domestic" if domestic else "overseas", "KRX" if domestic else "",
                         currency.upper(), tick, value, "")
    return paths, legs


def _master_rows() -> tuple[list, list]:
    from backend.team_spread.legs import master_rows
    return master_rows()


def _out_folder(first_date: str, name: str) -> Path:
    base = storage.state_dir() / "spreads"
    out = base / f"{first_date}_{name}_replay"
    n = 2
    while out.exists():
        out = base / f"{first_date}_{name}_replay_{n}"
        n += 1
    return out


USAGE = ("사용법: python -m backend.team_spread.replay <실행기.py> <다리>=<csv>:<tick>:<tick_value>:<통화> ...\n"
         "        python -m backend.team_spread.replay <실행기.py> <다리>=<csv>:<통화> ... --legs-from-master")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    from_master = "--legs-from-master" in args
    args = [a for a in args if a != "--legs-from-master"]
    if len(args) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    path = Path(args[0])
    folder, file = (path.parent, path.name) if path.parent != Path(".") else (spreads_dir(), args[0])
    try:
        loaded = load_runner(folder, file)
        csvs, legs = parse_legs(args[1:], loaded.legs, from_master=from_master)
        missing = [n for n in loaded.legs if n not in csvs]
        if missing:
            raise ReplayError(f"다리 {', '.join(missing)} 의 csv 를 주세요\n{USAGE}")
        first = align({n: read_rows(csvs[n]) for n in loaded.legs})
        if not first:
            raise ReplayError("맞춘 봉이 없습니다 — csv 에 봉이 없거나 다리끼리 겹치는 분이 없습니다")
        out = _out_folder(first[0].date, loaded.name)
        s = replay(loaded, csvs, legs, out)
    except (ReplayError, LoadError, StartRefused, OSError) as e:
        print(f"재생하지 못했습니다: {e}", file=sys.stderr)
        return 2
    pnl = " · ".join(f"{cur} {v.get('net', v.get('pnl', 0)):+,.2f}" for cur, v in (s.get("total") or {}).items()
                     if isinstance(v, dict)) or "손익 없음"
    print(f"{loaded.name}: {s['ended_reason']} · {pnl} · {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
