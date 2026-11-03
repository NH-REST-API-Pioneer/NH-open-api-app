"""파이썬 전략 실행 라우트 — `/api/team/pyrun/...`.

    GET  /strategies · POST /strategies/reload   전략 폴더의 파일 목록(읽을 때마다 폴더를 다시 본다)
    GET  /runs · POST /runs                      실행 목록 / 시작(거부는 409 `{"detail": 거부 문장}`)
    GET  /runs/{id}                              도는 실행은 `status()`, 끝난 실행은 `run.json` + 요약
    GET  /runs/{id}/journal · /api-log           `?after=N` 이어 읽기 → `{"rows": […], "next": 줄 수}`
    GET  /runs/{id}/bars                         차트용 `{"bars": […], "marks": […]}`
    POST /runs/{id}/stop · /flatten              204 (요청만 하고 바로 돌아온다)
    GET  /runs/{id}/download                     결과 zip(`journal` `summary` `api_log` 만 — `run.json` 은 넣지 않는다)

없는 실행·이상한 id 는 404. `stop`·`flatten` 은 **이 앱에서 세운 실행**에만 된다(이전 실행 폴더는 409).
앱을 켜고 끌 때 하는 일(호출 관찰자 꽂기·남은 실행 닫기·모두 중지)도 여기서 만든 함수를 `main.py` 의 `lifespan` 이 부른다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from backend.nh_api import client as nh_client
from backend.team_pyrun import apilog
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import RunSpec, StartRefused
from backend.team_pyrun.loader import scan
from backend.team_pyrun.registry import FINISHED_STATES, registry

logger = logging.getLogger(__name__)

#: 쓰는(상태를 바꾸는) 메서드 — 다른 사이트 검사를 받는다.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: `Origin` 으로 받는 호스트 이름 — 포트는 가리지 않는다(개발 서버는 :5173 에서 프록시로 부른다).
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
FOREIGN_SITE = "다른 사이트에서 온 요청은 받지 않습니다"


def refuse_cross_site(request: Request) -> None:
    """다른 사이트의 웹 페이지가 사용자 브라우저로 보낸 쓰기 요청을 막는다(CSRF) — 이 앱은 로컬에서 돌아 로그인이 없고,
    흘려보낸 `POST .../flatten` 한 번이 모의계좌 주문이 된다. 조회(GET)는 보지 않는다.

    - `Sec-Fetch-Site: cross-site` 면 거절.
    - `Origin` 이 있는데 호스트가 localhost·127.0.0.1·::1 이 아니면(`null` 포함) 거절.
    - `Origin` 이 없으면 통과(curl·시험은 보내지 않는다). 브라우저의 쓰기 요청에는 늘 붙는다."""
    if request.method not in UNSAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail=FOREIGN_SITE)
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            host = urlparse(origin).hostname
        except ValueError:
            host = None
        if host not in LOCAL_HOSTS:
            raise HTTPException(status_code=403, detail=FOREIGN_SITE)


def require_json(request: Request) -> None:
    """본문을 JSON 으로만 받는다(415). `text/plain`·폼 본문은 다른 사이트의 「단순 요청」이라 사전 확인 없이 갈 수 있다 —
    JSON 이어야 하면 브라우저가 먼저 사전 확인(CORS preflight)을 하고, 이 앱은 그것을 허락하지 않는다."""
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media != "application/json":
        raise HTTPException(status_code=415, detail="본문은 application/json 으로 보내야 합니다")


router = APIRouter(prefix="/api/team/pyrun", tags=["team-pyrun"], dependencies=[Depends(refuse_cross_site)])

#: 내려받는 zip 에 넣는 파일(이 순서). `run.json` 과 그 밖의 파일은 넣지 않는다.
DOWNLOAD_FILES = ("journal.jsonl", "summary.json", "api_log.jsonl")
#: 차트용 봉에서 신호 줄의 꼬리표 칸 — 봉 칸이 아니다.
_ROW_TAGS = ("kind", "at", "clock", "bar", "date")


class StartBody(BaseModel):
    """시작 요청. `mode` 는 일부러 문자열로 받는다 — 이상한 값은 422 가 아니라 거부 문장(409)으로 알린다."""

    file: str
    mode: str
    sym: str | None = None


def _folder(run_id: str) -> Path:
    """기록 폴더. 모르는 id(이상한 글자 포함)는 404."""
    try:
        return registry().folder(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"그 실행을 찾지 못했습니다: {run_id}") from None


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- 전략 파일
@router.get("/strategies")
def list_strategies() -> dict[str, Any]:
    """전략 폴더의 파일 목록. 못 쓰는 파일은 `error` 에 까닭이 담긴다."""
    folder = registry().strategies
    return {"folder": str(folder), "strategies": [dataclasses.asdict(s) for s in scan(folder)]}


@router.post("/strategies/reload")
def reload_strategies() -> dict[str, Any]:
    """`GET /strategies` 와 같다 — 목록은 부를 때마다 폴더를 다시 읽는다."""
    return list_strategies()


# ---------------------------------------------------------------- 실행
@router.get("/runs")
def list_runs() -> dict[str, Any]:
    return {"runs": registry().list()}


@router.post("/runs", status_code=201, dependencies=[Depends(require_json)])
def start_run(body: StartBody) -> dict[str, Any]:
    """실행을 세운다. 거부는 409(문장 그대로 `detail`). 준비(준비 봉 조회)가 끝난 뒤에 돌아온다."""
    try:
        return registry().start(RunSpec(body.file, body.mode, body.sym))  # type: ignore[arg-type]
    except StartRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """도는(이 앱에서 세운) 실행은 `status()`, 그 밖에는 `run.json` + `summary`(요약 파일의 `summary`, 없으면 null)."""
    live = registry().get(run_id)
    if live is not None:
        return live.status()
    folder = _folder(run_id)
    data = _read_json(folder / "run.json")
    if data is None:
        raise HTTPException(status_code=404, detail=f"실행 기록을 읽지 못했습니다: {run_id}")
    data.setdefault("id", run_id)
    summary = _read_json(folder / "summary.json") or {}
    data["summary"] = summary.get("summary")
    for key in ("halted", "unresolved_order"):
        if summary.get(key) is not None:
            data.setdefault(key, summary[key])
    # 그 실행이 쓴 Params(요약 파일의 `strategy.params`). 없으면 null — 화면은 지금 파일 값을 단서와 함께 쓴다
    strategy = summary.get("strategy")
    data.setdefault("params", strategy.get("params") if isinstance(strategy, dict) else None)
    return data


def _tail(folder: Path, name: str, after: int) -> dict[str, Any]:
    rows, nxt = Journal(folder / name).tail(after)
    return {"rows": rows, "next": nxt}


@router.get("/runs/{run_id}/journal")
def run_journal(run_id: str, after: int = Query(0, ge=0)) -> dict[str, Any]:
    """`after` 번째 줄 다음부터. `next` 를 다음 `after` 로 쓴다."""
    return _tail(_folder(run_id), "journal.jsonl", after)


@router.get("/runs/{run_id}/api-log")
def run_api_log(run_id: str, after: int = Query(0, ge=0)) -> dict[str, Any]:
    return _tail(_folder(run_id), "api_log.jsonl", after)


@router.get("/runs/{run_id}/bars")
def run_bars(run_id: str) -> dict[str, Any]:
    """차트용. `bars` 는 판정 봉마다(= `signal` 줄) `date start end open high low close` + 지표 칸 + `side reason stop_ticks`.

    시가·고가·저가는 이 기능 이전에 남긴 기록에는 없어 null 이다.
    `marks` 는 체결(`fill`)의 `entry`/`exit` 와 거래(`trade`, 손익·까닭 라벨용) 줄 —
    체결이 없는 기록에서는 `trade` 만 나온다. 체결 줄에는 날짜가 없어 앞선 신호 줄의 날짜를 따른다."""
    rows, _ = Journal(_folder(run_id) / "journal.jsonl").tail(0)
    bars: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []
    day = ""                 # 가장 최근 신호 줄의 날짜 — 체결·거래 줄에는 봉 날짜가 없다
    holding = False          # 체결을 진입/청산으로 나누기 위한 상태(진입 체결 뒤엔 청산 체결이 온다)
    for row in rows:
        kind = row.get("kind")
        if kind == "signal":
            day = row.get("date") or day
            bar = {"date": row.get("date"), "start": row.get("bar"), "end": row.get("clock")}
            for k in ("open", "high", "low"):
                bar[k] = row.get(k)
            bar["close"] = row.get("close")
            bar.update({k: v for k, v in row.items() if k not in bar and k not in _ROW_TAGS})
            bars.append(bar)
        elif kind == "fill":
            marks.append({"kind": "exit" if holding else "entry", "date": day or str(row.get("at", ""))[:10],
                          "time": row.get("clock"), "side": row.get("side"), "price": row.get("price")})
            holding = not holding
        elif kind == "trade":
            holding = False
            marks.append({"kind": "trade", "date": row.get("exit_date") or day, "time": row.get("exit_time"),
                          "side": row.get("side"), "price": row.get("exit"), "reason": row.get("reason"),
                          "pnl": row.get("pnl"), "ticks": row.get("ticks"), "entry": row.get("entry"),
                          "entry_time": row.get("entry_time")})
    return {"bars": bars, "marks": marks}


@router.get("/runs/{run_id}/download")
def download_run(run_id: str) -> Response:
    """결과 zip(메모리에서 만든다). 진행 중이면 `<id>_partial.zip`. 안에는 `<id>/<파일>` 만, `run.json` 은 없다."""
    folder = _folder(run_id)
    live = registry().get(run_id)
    partial = live is not None and live.state not in FINISHED_STATES
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in DOWNLOAD_FILES:
            try:
                z.writestr(f"{run_id}/{name}", (folder / name).read_bytes())
            except OSError:
                continue         # 아직 없는 파일(요약은 끝난 뒤에야 생긴다)
    filename = f"{run_id}_partial.zip" if partial else f"{run_id}.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _live_or_error(run_id: str) -> None:
    """이 앱에서 세운 실행이 아니면 오류: 폴더도 없으면 404, 이전 실행 폴더면 409."""
    if registry().get(run_id) is not None:
        return
    _folder(run_id)
    raise HTTPException(status_code=409, detail="이 앱에서 지금 세운 실행이 아닙니다 — 이전 실행은 중지·정리할 수 없습니다")


@router.post("/runs/{run_id}/stop", status_code=204)
def stop_run(run_id: str) -> Response:
    _live_or_error(run_id)
    registry().stop(run_id)
    return Response(status_code=204)


@router.post("/runs/{run_id}/flatten", status_code=204)
def flatten_run(run_id: str) -> Response:
    _live_or_error(run_id)
    registry().flatten(run_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- 앱을 켜고 끌 때 (main.py lifespan 이 부른다)
async def _recover() -> None:
    """남은 실행 폴더를 닫는다(스레드에서). 실패는 기록만 하고 앱은 계속 뜬다."""
    try:
        closed = await asyncio.to_thread(lambda: registry().recover())
        if closed:
            logger.info("끝나지 않고 남은 파이썬 전략 실행을 닫았습니다: %s", ", ".join(closed))
    except Exception:
        logger.exception("파이썬 전략 실행 복구에 실패했습니다 — 앱은 그대로 뜹니다")


def pyrun_startup() -> asyncio.Task:
    """앱이 뜰 때(이벤트 루프 안에서): NH 호출 관찰자를 꽂고 남은 실행 닫기를 따로 시작한다(기다리지 않는다)."""
    nh_client.call_observer = apilog.observe
    return asyncio.create_task(_recover())


async def pyrun_shutdown(recover_task: asyncio.Task | None) -> None:
    """앱이 꺼질 때: 모든 실행에 중지를 요청하고(스레드에서 — 이벤트 루프를 막지 않게) 관찰자를 뗀다."""
    if recover_task is not None and not recover_task.done():
        recover_task.cancel()
        await asyncio.gather(recover_task, return_exceptions=True)
    try:
        pending = await asyncio.to_thread(lambda: registry().stop_all())
        if pending:
            logger.warning("꺼질 때까지 끝나지 않은 파이썬 전략 실행: %s", ", ".join(pending))
    except Exception:
        logger.exception("파이썬 전략 실행 중지에 실패했습니다")
    finally:
        if nh_client.call_observer is apilog.observe:
            nh_client.call_observer = None
