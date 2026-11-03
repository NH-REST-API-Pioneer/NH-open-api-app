"""실행 기록 — 한 줄 = 한 사건(jsonl) 과 요약 파일.

실행 폴더 하나에 week02 와 같은 꼴로 남깁니다.

    journal.jsonl   사건 한 줄씩 (`{"kind", "at", ...}`)
    summary.json    끝난 뒤 한 번 쓰는 요약

**계좌 식별정보와 키·토큰은 쓰는 순간 지웁니다**(`scrub`). 주문내역·잔고 응답에는 계좌번호·이름·IP 가
들어 있어서, 응답을 그대로 기록에 넘겨도 파일에는 남지 않게 한 겹 더 막아 둔 것입니다.
`Journal.write` 는 실행 스레드와 요청 스레드가 같이 써도 줄이 섞이지 않습니다(잠금 + 한 번에 한 줄).
`summarize` 는 week02 `backtest.summarize` 를 칸·반올림까지 그대로 옮긴 것입니다.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from backend.sessions.hours import now_kst

#: 기록에 남기지 않는 칸 이름(소문자). 앞에 `occurs1_` 가 붙은 꼴도 같이 지웁니다.
PRIVATE_KEYS = frozenset({
    "ac_no", "ac_nm", "user_ip_addr", "ord_id", "user_id", "ip_addr", "action_acnt",
    "access_token", "authorization", "app_key", "app_secret", "appkey", "appsecret",
})
# 팀: 해외·실시간 응답은 같은 뜻의 칸을 다르게 이름 붙입니다(예: `cust_acnt_no`, `user_ip_addr`).
# 정확한 이름 목록으로는 빠지므로, 끝말이 이 꼴이면 가립니다.
PRIVATE_SUFFIXES = ("ip_addr", "user_id", "ac_no", "ac_nm", "acnt_no", "acnt")
_OCCURS = "occurs1_"


def _private(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    name = key.lower()
    if name.startswith(_OCCURS):
        name = name[len(_OCCURS):]
    return name in PRIVATE_KEYS or name.endswith(PRIVATE_SUFFIXES)


def scrub(obj: Any) -> Any:
    """dict·list 안(중첩 포함)의 금지 칸을 모두 지운 사본. 칸 이름은 대소문자를 가리지 않습니다."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if not _private(k)}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def _now() -> str:
    """`2026-10-30T09:24:33` 꼴(한국시간, 시간대 꼬리 없음 — week02 와 같은 모양)."""
    return now_kst().isoformat(timespec="seconds").removesuffix("+09:00")


class Journal:
    """`journal.jsonl` 한 파일. 열어 두지 않고 쓸 때마다 이어쓰기로 열어 한 줄 쓰고 바로 flush 합니다."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, kind: str, **data: Any) -> dict:
        """한 줄 기록하고 그 줄의 내용(dict)을 돌려줍니다."""
        rec = {"kind": kind, "at": _now(), **scrub(data)}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        return rec

    def _lines(self) -> list[bytes]:
        """줄바꿈으로 끝난 줄만 — 쓰는 중이라 덜 쓰인 마지막 줄은 아직 줄로 세지 않습니다."""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return []
        parts = raw.split(b"\n")
        parts.pop()     # 마지막 조각: 줄바꿈 뒤의 빈 값이거나 덜 쓰인 줄
        return parts

    def tail(self, after: int = 0) -> tuple[list[dict], int]:
        """`after` 번째 줄 다음부터의 기록과, 다음에 이어 읽을 번호(= 그 시점의 줄 수)를 **한 번에** 돌려줍니다.

        읽는 도중에 줄이 늘어도 기록과 번호가 같은 순간의 것이라, 이어 읽을 때 빠지거나 겹치지 않습니다.
        읽을 수 없는(깨진) 줄은 건너뛰되 번호에는 셉니다."""
        lines = self._lines()
        rows: list[dict] = []
        for raw in lines[max(after, 0):]:
            try:
                row = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows, len(lines)

    def read(self, after: int = 0) -> list[dict]:
        """`after` 번째 줄 다음부터의 기록. 읽을 수 없는(깨진) 줄은 건너뜁니다.

        줄 번호는 깨진 줄도 세므로, 이어 읽을 때는 읽은 개수가 아니라 `count()` 를 `after` 로 쓰세요
        (읽는 동안 줄이 늘 수 있으면 `tail()` 이 기록과 번호를 같이 줍니다)."""
        return self.tail(after)[0]

    def count(self) -> int:
        """지금까지 쓰인 줄 수(깨진 줄 포함)."""
        return len(self._lines())


def summarize(trades: list[dict]) -> dict:
    """거래 목록 요약 — week02 `backtest.summarize` 를 그대로 옮긴 것(칸·반올림 같음)."""
    n = len(trades)
    pnl = [t["pnl"] for t in trades]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    equity = peak = mdd = 0.0
    for x in pnl:
        equity += x
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    by_reason: dict[str, int] = {}
    by_day: dict[str, float] = {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
        by_day[t["exit_date"]] = by_day.get(t["exit_date"], 0) + t["pnl"]
    gp, gl = sum(wins), -sum(losses)
    out = {
        "trades": n, "wins": len(wins), "win_rate": round(len(wins) / n, 3) if n else None,
        "net_pnl": sum(pnl), "profit_factor": round(gp / gl, 2) if gl > 0 else None,
        "avg_win": round(gp / len(wins)) if wins else None,
        "avg_loss": round(-gl / len(losses)) if losses else None,
        "max_drawdown": mdd, "by_reason": by_reason, "by_day": by_day,
    }
    fees = [t.get("fee") for t in trades]
    if trades and None not in fees:      # 수수료를 아는 거래(실행기)만 — 백테스트 거래에는 fee 가 없음
        out["fee_total"] = sum(fees)
        out["net_pnl_after_fee"] = sum(pnl) - sum(fees)
    return out


def count_stops(folders: Iterable[Path], date: str) -> int:
    """`date`(YYYYMMDD)에 손절로 끝난 거래 수 — 여러 실행 폴더의 `journal.jsonl` 을 합쳐 셉니다.

    파일이 없거나 깨진 줄이 있어도 건너뜁니다(손실 한도 확인용이라 읽기만 합니다)."""
    total = 0
    for folder in folders:
        try:
            text = (Path(folder) / "journal.jsonl").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (isinstance(row, dict) and row.get("kind") == "trade"
                    and row.get("reason") == "손절" and row.get("exit_date") == date):
                total += 1
    return total


def entered_windows(folders: Iterable[Path], date: str) -> set:
    """`date`(YYYYMMDD)에 앞선 실행들이 **들어간 개장(window)** — 같은 날 다시 세운 실행이 개장마다 한 번 규칙을 이어받게.

    두 곳에서 읽습니다: `trade` 줄의 `window`(그날 청산한 것), 그리고 진입 `event` 줄의 `window` (진입만 하고
    trade 없이 끝난 실행 — 확인 필요로 멈췄거나 앱이 꺼진 것 — 도 들어간 개장으로 셉니다). event 줄엔 날짜 칸이
    없어서, 부르는 쪽이 그날 폴더만 넘깁니다(`Registry._folders_of`). 파일이 없거나 깨진 줄은 건너뜁니다."""
    out: set = set()
    for folder in folders:
        try:
            text = (Path(folder) / "journal.jsonl").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            window = row.get("window")
            if not isinstance(window, (str, int)) or isinstance(window, bool):
                continue
            if (row.get("kind") == "trade" and row.get("exit_date") == date) or row.get("kind") == "event":
                out.add(window)
    return out


def write_summary(folder: Path, data: dict) -> Path:
    """`summary.json` 을 쓰고 경로를 돌려줍니다(들여쓰기 1, 한글 그대로).

    내려받는 결과이므로 journal 과 같이 쓰는 순간 `scrub` 합니다(계좌 응답 원본이 들어올 수 있음)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "summary.json"
    path.write_text(json.dumps(scrub(data), indent=1, ensure_ascii=False), encoding="utf-8")
    return path
