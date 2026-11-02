"""실행별 API 호출 기록 — `api_log.jsonl` 한 줄 = NH 호출 한 번.

전략 실행이 부른 호출만 남깁니다(문제 추적 + 「API 활용」 평가 근거). 화면이 부른 호출은 남기지 않습니다.
어느 실행의 호출인지는 `contextvars` 로 가립니다 — 실행 쪽이 `with bind(log), purpose("현재가"):` 로 감싸면
그 안에서 `TradeClient.call()` 이 부른 것만 `log` 로 갑니다. 바인딩이 없으면 아무것도 안 남깁니다.

앱 시작 때 `backend.nh_api.client.call_observer = apilog.observe` 로 꽂습니다.

한 줄 칸: `at run purpose api_id env request http code message ms waited_ms reissued ok error` +
`body`(실패·`FULL_BODY_APIS`) 또는 `summary`(그 밖의 성공). 계좌 식별정보와 키·토큰은 `journal.scrub` 로 지웁니다.
"""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.team_pyrun.journal import _now, scrub

#: 성공해도 응답 본문을 통째로 남기는 API(주문·잔고·종목 정보 — 확인 근거라서).
FULL_BODY_APIS = frozenset({
    "domestic_order", "domestic_order-history", "domestic_open-interest",
    "domestic_deposit", "domestic_product-detail", "domestic_price-all-futures",
    "overseas_order", "overseas_order-history", "overseas_open-interest",
    "overseas_deposit", "overseas_product-detail",
})

_log: ContextVar["ApiLog | None"] = ContextVar("pyrun_apilog", default=None)
_purpose: ContextVar[str | None] = ContextVar("pyrun_apilog_purpose", default=None)


@contextmanager
def bind(run_log: "ApiLog") -> Iterator[None]:
    """이 안에서 `TradeClient.call()` 이 부른 호출을 `run_log` 에 남깁니다(스레드·작업마다 따로)."""
    token = _log.set(run_log)
    try:
        yield
    finally:
        _log.reset(token)


@contextmanager
def purpose(name: str) -> Iterator[None]:
    """이 안의 호출에 「왜 불렀는지」 이름을 붙입니다(`현재가` `준비 봉` `진입 주문` …)."""
    token = _purpose.set(name)
    try:
        yield
    finally:
        _purpose.reset(token)


def observe(call: dict) -> None:
    """`client.call_observer` 자리에 꽂는 함수. 현재 바인딩이 있을 때만 그 기록으로 넘깁니다."""
    run_log = _log.get()
    if run_log is not None:
        run_log.record({**call, "purpose": _purpose.get()})


_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
#: `access_token: 'x'` · `"app_key": "x"` · `appsecret=x` 꼴(따옴표 종류·이스케이프 무관)의 값
_SECRET_FIELD = re.compile(
    r"""(?P<key>access_token|app_key|app_secret|appkey|appsecret|authorization)(?P<mid>\\?["']?\s*[:=]\s*)"""
    r"""(?:(?P<q>\\?["']).*?(?P=q)|[^\s,}\]]+)""",
    re.IGNORECASE,
)
ERROR_MAX = 500


def _redact_error(text: Any) -> Any:
    """오류 문구에서 토큰·키 값을 가립니다. 인증 오류 문구에는 서버 응답 본문(토큰 포함)이 실려 올 수 있습니다.

    `Bearer xxx` → `Bearer ***`, 토큰·키 칸의 값 → `***`. 500자를 넘으면 자릅니다."""
    if not isinstance(text, str):
        return text
    text = _BEARER.sub("Bearer ***", text)
    text = _SECRET_FIELD.sub(lambda m: f"{m['key']}{m['mid']}{m['q'] or ''}***{m['q'] or ''}", text)
    return text[:ERROR_MAX]


def _bar_time(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return f"{row.get('occurs1_ref_dt', '')} {row.get('occurs1_exch_tm', '')}".strip()


def _summary(body: Any) -> dict:
    """본문을 통째로 남기지 않는 성공 호출의 요약. 현재가·차트가 아닌 모양은 최상위 칸 이름만."""
    if not isinstance(body, dict):
        return {}
    rows = body.get("Occurs1")
    if isinstance(rows, list):
        # 받은 순서 그대로의 처음·끝 봉(최신 봉이 먼저 옴)
        return {"rows": len(rows), "first": _bar_time(rows[0]) if rows else "",
                "last": _bar_time(rows[-1]) if rows else ""}
    if "last_pric" in body:
        return {"last_pric": body["last_pric"]}
    return {"keys": sorted(body)}


class ApiLog:
    """실행 하나의 `api_log.jsonl` 과 호출 통계. 실행 스레드·요청 스레드가 같이 써도 줄이 섞이지 않습니다."""

    def __init__(self, path: Path, run_id: str):
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self._failures: dict[str, int] = {}
        self._codes: dict[str, int] = {}
        self._ms_sum: dict[str, float] = {}
        self._ms_max: dict[str, float] = {}
        self._waited_total = 0
        self._reissued = 0

    def record(self, call: dict) -> None:
        """호출 한 건을 한 줄로 쓰고(이어쓰기, 바로 flush) 통계에 셉니다."""
        api_id = call["api_id"]
        error = _redact_error(call.get("error"))
        ok = error is None
        body = call.get("body")
        row: dict[str, Any] = {
            "at": _now(), "run": self.run_id, "purpose": call.get("purpose"),
            "api_id": api_id, "env": call.get("env"), "request": call.get("request"),
            "http": call.get("http"), "code": call.get("code"), "message": call.get("message"),
            "ms": call.get("ms"), "waited_ms": call.get("waited_ms", 0),
            "reissued": bool(call.get("reissued")), "ok": ok, "error": error,
        }
        if ok and api_id not in FULL_BODY_APIS:
            row["summary"] = _summary(body)
        elif body is not None:
            row["body"] = body
        line = json.dumps(scrub(row), ensure_ascii=False, default=str) + "\n"
        ms = call.get("ms") or 0
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
            self._calls[api_id] = self._calls.get(api_id, 0) + 1
            if not ok:
                self._failures[api_id] = self._failures.get(api_id, 0) + 1
            if call.get("code"):
                code = str(call["code"])
                self._codes[code] = self._codes.get(code, 0) + 1
            self._ms_sum[api_id] = self._ms_sum.get(api_id, 0) + ms
            self._ms_max[api_id] = max(self._ms_max.get(api_id, 0), ms)
            self._waited_total += call.get("waited_ms") or 0
            self._reissued += 1 if call.get("reissued") else 0

    def stats(self) -> dict:
        """summary.json 에 넣는 호출 통계."""
        with self._lock:
            return {
                "calls": dict(self._calls),
                "failures": dict(self._failures),
                "codes": dict(self._codes),
                "ms_avg": {k: round(self._ms_sum[k] / n, 1) for k, n in self._calls.items()},
                "ms_max": dict(self._ms_max),
                "waited_ms_total": self._waited_total,
                "reissued": self._reissued,
            }
