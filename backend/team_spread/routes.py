"""스프레드 실행 라우트 — `/api/team/spread/...`. 파이썬 전략 라우트(`team_pyrun/routes.py`)를 본뜬다.

    GET  /runners · POST /runners/reload   실행기 폴더의 파일 목록(`folder` `runners` `modules`, 읽을 때마다 폴더를 다시 본다)
    POST /runners                          올리기 `{file, content, overwrite}` → 201 목록(같은 이름 409, 이름·크기 400)
    DELETE /runners/{file}                 지우기 → 목록(없으면 404)
    GET  /convention                       작성 규칙 `{"markdown": 글}`(문서가 없으면 404)
    GET  /runs · POST /runs                목록 / 시작 `{file, mode, syms?, max_qty?, orders_per_min?}`(거부 409 `detail` = 거부 문장, 모르는 칸 422)
    GET  /runs/{id}                        도는 실행은 `status()`, 아니면 `run.json`
    GET  /runs/{id}/journal · /api-log     `?after=N` 이어 읽기 → `{"rows", "next"}`
    GET  /runs/{id}/bars                   차트용 `{"legs", "logs", "fills"}` — 기록에 남은 점만(아래 `run_bars`)
    POST /runs/{id}/stop                   204
    GET  /runs/{id}/download               zip(`journal` `summary` `api_log` 만)
    GET · POST /runs/{id}/inherit          이어받기 미리 보기 / 시작 `{file, expect}`

없는 실행·이상한 id 는 404. 앱을 켜고 끌 때 하는 일은 `spread_startup`·`spread_shutdown` — `main.py` 의 `lifespan` 이 부른다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import io
import logging
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from backend.team_pyrun import strategy_files
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import StartRefused
from backend.team_pyrun.routes import _read_json, refuse_cross_site, require_json
from backend.team_spread.registry import registry
from backend.team_spread.run import FINISHED, SpreadSpec
from backend.team_spread.runner_files import scan

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team/spread", tags=["team-spread"], dependencies=[Depends(refuse_cross_site)])

DOWNLOAD_FILES = ("journal.jsonl", "summary.json", "api_log.jsonl")
CONVENTION_DOC = Path(__file__).resolve().parents[2] / "docs" / "team" / "spread-runner-convention.md"


class StartBody(BaseModel):
    """시작 요청. `mode` 는 문자열로 받아 이상한 값을 거부 문장(409)으로 알린다. 모르는 칸은 422."""

    model_config = ConfigDict(extra="forbid")

    file: str
    mode: str
    syms: dict[str, str] | None = None
    max_qty: int | None = None
    orders_per_min: int | None = None


class InheritBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    expect: dict[str, int]


class UploadBody(BaseModel):
    """올리기 — 타입 검사는 `strategy_files` 가 한다(이상한 값이 422 가 아니라 문장 있는 400 으로 가게)."""

    file: Any
    content: Any
    overwrite: Any = False


def _folder(run_id: str) -> Path:
    try:
        return registry().folder(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"그 실행을 찾지 못했습니다: {run_id}") from None


# ---------------------------------------------------------------- 실행기 파일
@router.get("/runners")
def list_runners() -> dict[str, Any]:
    folder = registry().folder_of_runners
    runners, modules = scan(folder)
    return {"folder": str(folder), "runners": [dataclasses.asdict(r) for r in runners], "modules": modules}


@router.post("/runners/reload")
def reload_runners() -> dict[str, Any]:
    return list_runners()


@router.post("/runners", status_code=201, dependencies=[Depends(require_json)])
def upload_runner(body: UploadBody) -> dict[str, Any]:
    try:
        strategy_files.save(registry().folder_of_runners, body.file, body.content, body.overwrite is True)
    except strategy_files.BadFile as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except strategy_files.FileExists as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except strategy_files.StoreFailed as e:
        raise HTTPException(status_code=500, detail=str(e)) from None
    return list_runners()


@router.delete("/runners/{file}")
def delete_runner(file: str) -> dict[str, Any]:
    try:
        strategy_files.delete(registry().folder_of_runners, file)
    except strategy_files.BadFile as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except strategy_files.NoSuchFile as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except strategy_files.StoreFailed as e:
        raise HTTPException(status_code=500, detail=str(e)) from None
    return list_runners()


@router.get("/convention")
def runner_convention() -> dict[str, str]:
    try:
        text = CONVENTION_DOC.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=404, detail="작성 규칙 문서를 찾지 못했습니다") from None
    return {"markdown": text}


# ---------------------------------------------------------------- 실행
@router.get("/runs")
def list_runs() -> dict[str, Any]:
    return {"runs": registry().list()}


# 팀: 반드시 `def`(동기) — 준비(시세·잔고 조회)가 막는 입출력이라 스레드 풀에서 불려야 이벤트 루프가 안 막힌다.
@router.post("/runs", status_code=201, dependencies=[Depends(require_json)])
def start_run(body: StartBody) -> dict[str, Any]:
    spec = SpreadSpec(body.file, body.mode, body.syms, body.max_qty, body.orders_per_min)  # type: ignore[arg-type]
    try:
        return registry().start(spec)
    except StartRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    live = registry().get(run_id)
    if live is not None:
        return live.status()
    data = _read_json(_folder(run_id) / "run.json")
    if data is None:
        raise HTTPException(status_code=404, detail=f"실행 기록을 읽지 못했습니다: {run_id}")
    data.setdefault("id", run_id)
    return data


def _tail(folder: Path, name: str, after: int) -> dict[str, Any]:
    rows, nxt = Journal(folder / name).tail(after)
    return {"rows": rows, "next": nxt}


@router.get("/runs/{run_id}/journal")
def run_journal(run_id: str, after: int = Query(0, ge=0)) -> dict[str, Any]:
    return _tail(_folder(run_id), "journal.jsonl", after)


@router.get("/runs/{run_id}/api-log")
def run_api_log(run_id: str, after: int = Query(0, ge=0)) -> dict[str, Any]:
    return _tail(_folder(run_id), "api_log.jsonl", after)


@router.get("/runs/{run_id}/bars")
def run_bars(run_id: str) -> dict[str, Any]:
    """차트용 `{"legs": {다리: [{at, close}]}, "logs": {이름: [{at, value}]}, "fills": [...]}`.

    실행은 분마다의 시세를 기록하지 않는다 — 기록에 있는 것은 체결(`fill`)·`log` 점뿐이다. 그래서 `legs` 는 체결가가
    있는 체결의 (시각, 가격)이고(`close` 칸 이름은 화면 약속), 분 봉 시계열이 아니다. `fills` 는 체결 줄(다리·수량·가격·수수료)."""
    rows, _ = Journal(_folder(run_id) / "journal.jsonl").tail(0)
    legs: dict[str, list[dict[str, Any]]] = {}
    logs: dict[str, list[dict[str, Any]]] = {}
    fills: list[dict[str, Any]] = []
    for row in rows:
        kind = row.get("kind")
        if kind == "fill":
            fills.append({k: row.get(k) for k in ("at", "clock", "leg", "sym", "qty", "price", "fee")})
            if row.get("price") is not None and row.get("leg"):
                legs.setdefault(row["leg"], []).append({"at": row.get("at"), "close": row["price"]})
        elif kind == "log" and isinstance(row.get("value"), (int, float)) and row.get("name"):
            logs.setdefault(row["name"], []).append({"at": row.get("at"), "value": row["value"]})
    return {"legs": legs, "logs": logs, "fills": fills}


@router.get("/runs/{run_id}/download")
def download_run(run_id: str) -> Response:
    folder = _folder(run_id)
    live = registry().get(run_id)
    partial = live is not None and live.state not in FINISHED
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in DOWNLOAD_FILES:
            try:
                z.writestr(f"{run_id}/{name}", (folder / name).read_bytes())
            except OSError:
                continue
    filename = f"{run_id}_partial.zip" if partial else f"{run_id}.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/runs/{run_id}/stop", status_code=204)
def stop_run(run_id: str) -> Response:
    if registry().get(run_id) is None:
        _folder(run_id)
        raise HTTPException(status_code=409, detail="이 앱에서 지금 세운 실행이 아닙니다 — 이전 실행은 중지할 수 없습니다")
    registry().stop(run_id)
    return Response(status_code=204)


@router.get("/runs/{run_id}/inherit")
def inherit_preview(run_id: str) -> dict[str, Any]:
    _folder(run_id)
    try:
        return registry().inherit_preview(run_id)
    except StartRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/runs/{run_id}/inherit", status_code=201, dependencies=[Depends(require_json)])
def inherit_run(run_id: str, body: InheritBody) -> dict[str, Any]:
    _folder(run_id)
    try:
        return registry().start(SpreadSpec(body.file, "orders", inherit_from=run_id), expect=body.expect)
    except StartRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


# ---------------------------------------------------------------- 앱을 켜고 끌 때 (main.py lifespan 이 부른다)
async def spread_startup(after: asyncio.Task | None = None) -> None:
    """남은 스프레드 실행 폴더를 닫는다(스레드에서). `after` = 파이썬 전략 복구 작업 — 그것이 끝난 뒤에 한다.
    실패는 기록만 하고 앱은 계속 뜬다."""
    if after is not None:
        await asyncio.gather(after, return_exceptions=True)
    try:
        closed = await asyncio.to_thread(lambda: registry().recover())
        if closed:
            logger.info("끝나지 않고 남은 스프레드 실행을 닫았습니다: %s", ", ".join(closed))
    except Exception:
        logger.exception("스프레드 실행 복구에 실패했습니다 — 앱은 그대로 뜹니다")


async def spread_shutdown(recover_task: asyncio.Task | None = None) -> None:
    """새 시작을 막고 모든 스프레드 실행에 중지를 요청한다(스레드에서). 실패는 기록만 한다."""
    if recover_task is not None and not recover_task.done():
        recover_task.cancel()
        await asyncio.gather(recover_task, return_exceptions=True)
    try:
        registry().close_starts()
        pending = await asyncio.to_thread(lambda: registry().stop_all())
        if pending:
            logger.warning("꺼질 때까지 끝나지 않은 스프레드 실행: %s", ", ".join(pending))
    except Exception:
        logger.exception("스프레드 실행 중지에 실패했습니다")
