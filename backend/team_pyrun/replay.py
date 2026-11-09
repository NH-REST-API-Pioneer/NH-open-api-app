"""받아 둔 1분봉으로 하루를 다시 돌린다 — 서버 접속도 주문도 없고, 체결은 종이 체결.

코드 점검과 week02·week03 결과 비교용입니다(해외 MKU 는 `market=OVERSEAS` — `tests/test_team_pyrun_orb.py` 골든). 순서는 week02 `replay()` 와 같습니다: 그 분의 시가로
`on_price`(진입·정리) → 종가와 고저로 `on_price`(손절·익절) → `on_minute_closed`(그 봉으로 신호).

    python -m backend.team_pyrun.replay <전략파일> <YYYYMMDD> <csv> [--market domestic|overseas] [--currency XXX]

`--market` 을 주면 csv 이름의 종목으로 시장 가드를 하지 않고(아무 품목) 그 시장으로 돕니다 — 통화는 기록·글에만(`--currency`,
수수료는 그대로), 하루 최소 봉 수는 A75 가 아니면 1. 자정을 넘는 전략이면 `<YYYYMMDD>` 는 거래일(봉은 거래일 시계로).

시장은 장중 실행과 같은 규칙(`live.run_market`: csv 이름의 종목, 없으면 전략 TICK)으로 정하고, 하루 봉 수 거르기·
종이 수수료·슬리피지·끝 정리 시각을 그 시장 값으로 씁니다(국내는 week02 그대로).

전략 파일 이름에 폴더가 없으면 전략 폴더에서 찾고, 결과는 `<상태 폴더>/pyruns/<날짜>_<NAME>_replay/` 에
(같은 이름 폴더가 있으면 비우고) 씁니다: `journal.jsonl` `summary.json` `run.json`.

## 실시간 리플레이 (leadlag — 원문 녹화)

    python -m backend.team_pyrun.replay <실시간 전략파일> <YYYYMMDD> <raw.jsonl[.gz]>

week03 `ws_trader.py` 가 남긴 원문 녹화(`results/live/<날짜>/raw.jsonl.gz`)를 **앱 실시간 실행기(`realtime.RealtimeRun`)의
넣기 길 그대로**(`handle` → 밀린 1초 타이머 `fire_timer` → `on_krx`/`on_quote`) 흘립니다. 규칙은 week03 `replay_live.py` 와 같습니다.

| 규칙 | replay_live.py | 여기 |
|---|---|---|
| 넣는 원문 | `KA`·`FB` 만 (`FA`·pingpong·`RT_INIT` 은 버림) | 같음 (`read_raw`) |
| 시각 | `recv_ts`(받은 순간, 한국시간) — 구간 계산도, 시각 글자도 | 같음 — 실행기의 단조 시계·벽시계를 `recv_ts` 로 돌림 |
| 1초 타이머 | 첫 타이머 = 첫 원문 시각, 그 뒤 1초마다, 원문을 넣기 전에 그 시각까지 | 같음 (`RealtimeRun.start_timers_at`) |
| 체결 | 신호 순간 반대 호가(종이) | 같음 — 실행기 「종이」 체결(반대 호가, 수수료 체결마다 US$2) |

서버 접속·주문은 없습니다(시작 때 틱 확인은 MKU 값 0.0001·US$2.5 로 답함). 앱 실행기의 규칙도 그대로라
녹화가 실행 끝 시각(`flatten_at` + 5분) 뒤에 시작하면 시작 거부. 다만 원문이 오래 없던 공백에서도 1초 타이머는
replay_live 처럼 다 돌립니다(장중의 `realtime.MAX_TIMER_CATCHUP` 건너뛰기를 끔 — 보유 중 공백의 시간 청산이 같게).
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import shutil
import sys
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend import storage
from backend.sessions.hours import KST, now_kst
from backend.team_pyrun.journal import Journal, summarize, write_summary
from backend.team_pyrun.live import RunSpec, StartRefused, run_plan
from backend.team_pyrun.loader import DEFAULT_FLATTEN, Loaded, load, strategies_dir
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, Market, paper_fee_of
from backend.team_pyrun.rawfeed import RawMessage
from backend.team_pyrun.realtime import RealtimeRun
from backend.team_pyrun.runner import PAPER_FEE, PAPER_SLIP_TICKS, Minute, PaperBroker, Runner

MIN_BARS_PER_DAY = DOMESTIC.min_day_bars   # 국내: 이보다 봉이 적은 날(거래가 드문 원월물 시절)은 뺍니다 (week02 와 같음)
DEFAULT_SYM = "A756B000"


def load_minutes(csv_path: Path, *, market: Market = DOMESTIC, min_bars: int | None = None) -> list[Minute]:
    """1분봉 csv(`ref_dt exch_tm open_pric …`)를 읽는다. 하루 봉이 `market.min_day_bars` 미만인 날은 뺀다.

    국내는 250봉(week02 그대로), 해외 MKU 는 빼지 않습니다(1봉) — 토요일 새벽처럼 봉이 적은 날도 열린 날이고,
    week03 백테스트도 빼지 않습니다. `min_bars` 를 주면 그 값이 먼저입니다(`--market` 으로 아무 품목을 돌릴 때 1)."""
    floor = market.min_day_bars if min_bars is None else min_bars
    with Path(csv_path).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    per_day: dict[str, int] = {}
    for r in rows:
        per_day[r["ref_dt"]] = per_day.get(r["ref_dt"], 0) + 1
    return [Minute(r["ref_dt"], r["exch_tm"], float(r["open_pric"]), float(r["high_pric"]),
                   float(r["low_pric"]), float(r["close_pric"]), float(r["cum_trd_qty"] or 0))
            for r in rows if per_day[r["ref_dt"]] >= floor]


def _stamp() -> str:
    return now_kst().isoformat(timespec="seconds").removesuffix("+09:00")


class _DefaultFee(float):
    """`replay()` 의 `fee` 기본값 표지 — 값은 국내 `PAPER_FEE`(옛 호출·시험이 보는 값)이지만, 안 준 것을 알아본다(`is`)."""


DEFAULT_FEE = _DefaultFee(PAPER_FEE)


def replay(loaded: Loaded, date: str | None, minutes: list[Minute], folder: Path, sym: str = DEFAULT_SYM, *,
           market: Market = DOMESTIC, fee: float = DEFAULT_FEE, slip_ticks: int = PAPER_SLIP_TICKS,
           currency: str | None = None) -> dict:
    """`date` 하루를 다시 돌려 `folder` 에 기록하고 `{"trades", "summary"}` 를 돌려준다.

    그 전 날들은 준비 봉으로 전략에만 넣습니다. `date` 가 None 이면 `minutes` 의 **모든 날을 날마다 이어** 돕니다
    (week03 `backtest.run` 처럼 — 전략은 한 번 만들어 날을 넘겨 이어지고, 날이 바뀌면 대기 신호는 버리고, 날마다
    끝에 남은 보유를 정리). `sym` 은 `run.json` 에 적을 종목.

    `market` 은 빠진 Params 장 시간 칸을 채우고(`loaded.new(market)`), 하루 끝 정리 시각(국내 153000 · 해외 235000,
    `loader.DEFAULT_FLATTEN`)을 정합니다. `fee`(체결마다, 그 시장 통화)·`slip_ticks`(불리한 쪽 틱)는 종이 체결 값.
    `fee` 를 안 주면(`DEFAULT_FEE`) `paper_fee_of(market, loaded.paper_fee)`(전략 `PAPER_FEE` 가 먼저). `currency` 는 기록·글에 적을 통화만
    바꿉니다(수수료는 그대로). 자정을 넘는 전략(`live.run_plan`)이면 봉을 거래일 시계로 바꾼 뒤 날을 묶습니다 — `date` 는
    거래일이고, 하루 끝 정리는 (바뀐) `flatten_at`. 기본값은 모두 국내(week02) 그대로입니다."""
    folder = Path(folder)
    started = _stamp()
    j = Journal(folder / "journal.jsonl")
    fee = paper_fee_of(market, loaded.paper_fee) if fee is DEFAULT_FEE else fee
    currency = currency or market.currency
    plan = run_plan(loaded, market)
    r = Runner(loaded.new(market, overnight=plan.overnight), j,
               PaperBroker(j, loaded.tick, fee=fee, slip_ticks=slip_ticks), loaded.tick, loaded.tick_value)
    r.currency = currency      # 기록 글의 손익 통화 (값은 TICK_VALUE 단위 그대로)
    if plan.overnight:      # 자정 뒤 봉은 앞 거래일에 24시를 더한 시각으로 (설계 4.4)
        minutes = [plan.clock.bar(m) for m in minutes]
    days = sorted({m.date for m in minutes}) if date is None else [date]
    flat_at = r.p.flatten_at if plan.overnight else DEFAULT_FLATTEN[market.id]
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
    write_summary(folder, {**result, "market": market.id, "currency": currency, "strategy": {
        "file": loaded.file, "name": loaded.name, "title": loaded.title,
        "sha256": loaded.sha256, "params": asdict(r.p)}})
    (folder / "run.json").write_text(json.dumps({
        "id": folder.name, "file": loaded.file, "name": loaded.name, "title": loaded.title,
        "sha256": loaded.sha256, "mode": "replay", "sym": sym, "state": "끝",
        "started_at": started, "ended_at": _stamp(), "ended_reason": "리플레이",
        "market": market.id, "currency": currency, "kind": "minute",
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


# ── 실시간 리플레이 ─────────────────────────────────────────

#: 녹화의 연결 이름(ws_trader `Recorder.message` 의 conn) → 원문 시장
_CONN_MARKET = {"국내": "domestic", "해외": "overseas"}
#: replay_live `stream` 이 넣는 원문
_RAW_CODES = ("KA", "FB")


def wall_of(mono: float) -> datetime:
    """리플레이 시계 `mono`(한국시간 epoch 초) 순간의 벽시계(한국시간)."""
    return datetime.fromtimestamp(mono, KST)


def _mono_of(recv_ts: str) -> float:
    """녹화의 `recv_ts`(한국시간, 시간대 없음) → 리플레이 시계(epoch 초). 이 PC 시간대와 상관없게 KST 로 붙인다."""
    t = datetime.fromisoformat(recv_ts)
    return (t if t.tzinfo else t.replace(tzinfo=KST)).timestamp()


def read_raw(path: Path | str, date: str | None = None) -> list[RawMessage]:
    """ws_trader 원문 녹화(`raw.jsonl` 또는 `.gz`) → `KA`·`FB` 원문(`RawMessage`) 목록, 받은 순서대로.

    `date`(YYYYMMDD)를 주면 `recv_ts` 가 그 날인 줄만. 종목은 머리의 `action_sym`(없으면 몸의 `sym`)."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    out: list[RawMessage] = []
    with opener(path, "rt", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                msg = r["msg"]
                head, body = msg.get("header") or {}, msg.get("body") or {}
                code = head.get("action_code")
                if code not in _RAW_CODES:
                    continue
                if date is not None and r["recv_ts"][:10].replace("-", "") != date:
                    continue
                market = _CONN_MARKET.get(r.get("conn"), "domestic" if code == "KA" else "overseas")
                sym = str(head.get("action_sym") or body.get("sym") or "").strip()
                out.append(RawMessage(market, code, sym, body, _mono_of(r["recv_ts"])))
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                raise ValueError(f"{path.name} {n}번째 줄을 읽을 수 없습니다: {e}") from e
    return out


class _ReplayClock:
    """실행기에 꽂는 시계 — 단조 시계와 벽시계가 둘 다 지금 넣는 원문의 `recv_ts`."""

    def __init__(self, mono: float):
        self.mono = mono

    def monotonic(self) -> float:
        return self.mono

    def now(self) -> datetime:
        return wall_of(self.mono)


class _OfflineApi:
    """리플레이용 api — NH 로 아무것도 보내지 않는다. 시작 검사의 틱 확인만 MKU 값으로 답하고, 그 밖은 오류."""

    def ovs_product_detail(self) -> list[dict]:
        return []

    def mku_spec(self, _details: list[dict]) -> tuple[float, float]:
        return OVERSEAS.tick, OVERSEAS.tick_value

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"리플레이는 NH API 를 부르지 않습니다 ({name})")


class _NoFeed:
    """원문 구독 자리 — 리플레이는 원문을 직접 `handle` 에 넣는다(쌓임 없음)."""

    pending = 0
    overflow = False
    closed = False

    def close(self) -> None:
        self.closed = True


def replay_realtime(loaded: Loaded, messages: Iterable[RawMessage], folder: Path, *, sym: str | None = None,
                    signal_sym: str | None = None, params: dict[str, Any] | None = None,
                    max_timer_catchup: int | None = None) -> dict:
    """원문 녹화를 앱 실시간 실행기(종이)에 흘려 `folder` 에 기록하고 `{"trades", "summary", "refused"}` 를 돌려준다.

    `sym`(MKU)·`signal_sym`(KRX)이 없으면 녹화의 첫 `FB`·`KA` 종목. `params` 는 기본 Params 에서 바꿀 칸
    (replay_live 의 `--move` 처럼). 시작 거부면 `refused` 에 까닭(거래 없음), 아니면 None.

    `max_timer_catchup` 은 기본 None — 녹화 공백이 길어도 1초 타이머를 replay_live 처럼 **다** 돌린다(장중 실행기는
    `realtime.MAX_TIMER_CATCHUP` 600번 넘게 밀리면 건너뜀. 보유 중 긴 공백이면 시간 청산 시각이 달라지므로)."""
    msgs = list(messages)
    if not msgs:
        raise ValueError("녹화에 KA·FB 원문이 없습니다")
    sym = sym or next((m.sym for m in msgs if m.api_id == "FB"), None)
    signal_sym = signal_sym or next((m.sym for m in msgs if m.api_id == "KA"), None)
    clock = _ReplayClock(msgs[0].recv_monotonic)
    folder = Path(folder)
    run = RealtimeRun(folder.name, folder, loaded, RunSpec(file=loaded.file, mode="replay", sym=sym,
                                                           signal_sym=signal_sym),
                      api_module=_OfflineApi(), feed_factory=lambda run_id, wants: _NoFeed(),
                      now=clock.now, monotonic=clock.monotonic, sleep=lambda seconds: None,
                      active_env=lambda: None, params=params, max_timer_catchup=max_timer_catchup)
    try:
        run.prepare()
    except StartRefused as e:
        return {"trades": [], "summary": summarize([]), "refused": str(e)}
    run.j.write("event", text=f"녹화 원문 {len(msgs):,}건(KA·FB) · 시각 = 받은 시각(recv_ts) · 타이머 건너뛰기 없음")
    run.start_timers_at(msgs[0].recv_monotonic)     # replay_live: 첫 타이머 = 첫 원문 시각
    last_sec = None
    for m in msgs:
        clock.mono = m.recv_monotonic
        sec = int(m.recv_monotonic)
        if sec != last_sec:         # 장중처럼 1초에 한 번 살림(끝 시각·1분 줄) — 원문을 넣기 전에
            last_sec = sec
            run.step(clock.now())
        run.handle(m)
        if run.state in ("끝", "오류"):
            break
    run.finish("리플레이")
    return {"trades": run.trades, "summary": summarize(run.trades), "refused": None}


def _is_raw(path: Path) -> bool:
    return path.name.endswith((".jsonl", ".jsonl.gz"))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    usage = ("사용법: python -m backend.team_pyrun.replay <전략파일> <YYYYMMDD> <csv | raw.jsonl[.gz]> "
             "[--market domestic|overseas] [--currency XXX]\n"
             "  1분봉 전략은 1분봉 csv, 실시간 전략(leadlag)은 원문 녹화 <raw.jsonl[.gz]>. "
             "자정을 넘는 전략이면 <YYYYMMDD> 는 거래일")
    flags: dict[str, str] = {}
    pos: list[str] = []
    it = iter(args)
    for a in it:
        if a in ("--market", "--currency"):
            flags[a] = next(it, "")
        else:
            pos.append(a)
    if (len(pos) != 3 or not re.fullmatch(r"\d{8}", pos[1]) or flags.get("--market", "overseas") not in ("domestic", "overseas")
            or ("--currency" in flags and not re.fullmatch(r"[A-Z]{3}", flags["--currency"]))):
        print(usage, file=sys.stderr)
        return 2
    file, date, data = pos
    from backend.team_pyrun.live import run_market     # 장중 실행과 같은 시장 규칙 (명령줄에서만 쓰므로 여기서)
    path = Path(file)
    folder, name = (path.parent, path.name) if path.parent != Path(".") else (strategies_dir(), file)
    loaded = load(folder, name)
    data_path = Path(data)
    if (loaded.kind == "realtime") != _is_raw(data_path):
        want = "원문 녹화(raw.jsonl[.gz])" if loaded.kind == "realtime" else "1분봉 csv"
        print(f"{loaded.name} 은 {'실시간' if loaded.kind == 'realtime' else '1분봉'} 전략입니다 — {want} 를 주세요",
              file=sys.stderr)
        return 2
    out = storage.state_dir() / "pyruns" / f"{date}_{loaded.name}_replay"
    if out.exists():
        shutil.rmtree(out)
    if loaded.kind == "realtime":
        got = replay_realtime(loaded, read_raw(data_path, date), out)
        if got["refused"]:
            print(f"시작 거부: {got['refused']}", file=sys.stderr)
            return 2
        s = got["summary"]
        print(f"{loaded.name} {date}: 거래 {s['trades']}건 · 손익 {s['net_pnl']:+,.2f} USD · {out}")
        return 0
    # 종목은 csv 이름(`bars_1m_<종목>[_<날짜>].csv`)에서, 시장은 실행과 같은 규칙(`live.run_market`)으로
    m = re.search(r"bars_1m_([A-Za-z0-9]+?)(?:_\d{8})?\.csv$", Path(data).name)
    sym = m.group(1) if m else None
    if "--market" in flags:     # 시장을 직접 줌 — csv 종목으로 시장 가드를 하지 않는다 (아무 품목)
        market = DOMESTIC if flags["--market"] == "domestic" else OVERSEAS
    else:
        market, refusal = run_market(sym, loaded)
        if refusal:
            print(f"시장이 맞지 않습니다: {refusal}", file=sys.stderr)
            return 2
    currency = flags.get("--currency") or market.currency
    # 하루 최소 봉 수 (설계 4.2): 시장을 줬고 A75 가 아닌 종목이면 1 — 아니면 그 시장 값
    min_bars = 1 if "--market" in flags and not (sym or "").startswith("A75") else None
    record_sym = sym or (DEFAULT_SYM if market is DOMESTIC else "MKU")
    result = replay(loaded, date, load_minutes(Path(data), market=market, min_bars=min_bars), out, sym=record_sym,
                    market=market, slip_ticks=market.paper_slip_ticks, currency=currency)
    s = result["summary"]
    money = f"{s['net_pnl']:+,}원" if currency == "KRW" else f"{s['net_pnl']:+,.2f} {currency}"
    print(f"{loaded.name} {date}: 거래 {s['trades']}건 · 손익 {money} · {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
