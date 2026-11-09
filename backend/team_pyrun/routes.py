"""파이썬 전략 실행 라우트 — `/api/team/pyrun/...`.

    GET  /strategies · POST /strategies/reload   전략 폴더의 파일 목록(읽을 때마다 폴더를 다시 본다)
    POST /strategies                             전략 파일 올리기 `{file, content, overwrite}` → 201 목록(`folder` `strategies` `modules`)(같은 이름은 409, 이름·크기는 400)
    DELETE /strategies/{file}                    전략 파일 지우기 → 200 목록(없으면 404)
    GET  /convention                             전략 파일 작성 규칙 `{"markdown": 문서 글}`(문서가 없으면 404)
    GET  /runs · POST /runs                      실행 목록 / 시작 `{file, mode, sym?, signal_sym?}`(거부는 409 `{"detail": 거부 문장}`)
    GET  /runs/{id}                              도는 실행은 `status()`, 끝난 실행은 `run.json` + 요약 (`kind` 로 1분봉·실시간 구별)
    GET  /runs/{id}/journal · /api-log           `?after=N` 이어 읽기 → `{"rows": […], "next": 줄 수}`
    GET  /runs/{id}/bars                         차트용 `{"kind": "minute"|"realtime", "bars": […], "marks": […]}`
    POST /runs/{id}/stop · /flatten              204 (요청만 하고 바로 돌아온다)
    GET  /runs/{id}/download                     결과 zip(`journal` `summary` `api_log` 만 — `run.json` 은 넣지 않는다)
    GET  /schedules · POST /schedules            매일 자동 시작 목록 / 만들기 `{file, mode, run_id?}`(거부는 409) — `autostart.py`
    DELETE /schedules/{id} · POST /schedules/{id}/resume   지우기 204 / 막힌 예약 다시 켜기 (모르는 id 는 404)

없는 실행·이상한 id 는 404. `stop`·`flatten` 은 **이 앱에서 세운 실행**에만 된다(이전 실행 폴더는 409).
앱을 켜고 끌 때 하는 일(호출 관찰자 꽂기·남은 실행 닫기 뒤 자동 시작 루프 띄우기·자동 시작 멈춘 뒤 모두 중지)도 여기서 만든 함수를 `main.py` 의 `lifespan` 이 부른다.
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
from pydantic import BaseModel, ConfigDict

from backend.nh_api import client as nh_client
from backend.team_hosts import LOCAL_HOSTS, public_hosts
from backend.team_pyrun import apilog, rawfeed, strategy_files
from backend.team_pyrun.autostart import ScheduleError, schedules
from backend.team_pyrun.journal import Journal
from backend.team_pyrun.live import RunSpec, StartRefused
from backend.team_pyrun.loader import scan_all
from backend.team_pyrun.registry import FINISHED_STATES, registry

logger = logging.getLogger(__name__)

#: 쓰는(상태를 바꾸는) 메서드 — 다른 사이트 검사를 받는다.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: 로컬 호스트 이름 — `Origin` 의 포트는 가리지 않는다(개발 서버는 :5173 에서 프록시로 부른다). `backend/team_hosts.py`.
FOREIGN_SITE = "다른 사이트에서 온 요청은 받지 않습니다"


#: 주소에 포트가 없을 때의 기본 포트.
DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_endpoint(origin: str) -> tuple[str, int] | None:
    """`Origin` 을 (호스트, 포트)로. 뜻을 못 알아보면(`null`·빈 호스트·이상한 포트) `None`."""
    try:
        parts = urlparse(origin)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host or parts.scheme not in DEFAULT_PORTS:
        return None
    return host, port if port is not None else DEFAULT_PORTS[parts.scheme]


def _host_header(request: Request) -> tuple[str, int | None] | None:
    """`Host` 머리글을 (호스트, 포트)로. 포트가 없으면 `None`. 뜻을 못 알아보면 `None` 전체.

    `X-Forwarded-Host`·`X-Forwarded-Proto` 는 보지 않는다(밖에서 마음대로 적어 보낼 수 있고, 터널이 붙여 주는지도 확인할 수 없다)."""
    raw = request.headers.get("host")
    if not raw:
        return None
    try:
        parts = urlparse("//" + raw)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    return host, port


def _origin_allowed(request: Request, origin: str) -> bool:
    """`Origin` 을 받아도 되는지.

    - 로컬 Origin(localhost·127.0.0.1·::1, 포트 불문)은 **Host 도 로컬일 때만**. 리바인딩된 `rebind.attacker.tld` 나 공개 주소의
      Host 에 localhost Origin 이 붙은 요청은 거절한다.
    - Host 의 호스트가 `NH_PUBLIC_HOSTS` 에 있으면 받는 Origin 은 정확히 `https://<그 호스트>`(또는 `:443`) 뿐이다.
      공개 주소는 Cloudflare 가 늘 https 로만 내보내므로 요청이 서버에 http 로 들어와도(전달 머리글이 와도 안 와도) 같게 판정한다.
      `http://…`·다른 포트는 거절한다.
    - 그 밖(`null`·뜻을 알 수 없는 값·모르는 호스트)은 거절."""
    endpoint = _origin_endpoint(origin)
    host = _host_header(request)
    if endpoint is None or host is None:
        return False
    if endpoint[0] in LOCAL_HOSTS:
        return host[0] in LOCAL_HOSTS
    if host[0] not in public_hosts() or host[1] not in (None, 443):
        return False
    return urlparse(origin).scheme == "https" and endpoint == (host[0], 443)


def refuse_cross_site(request: Request) -> None:
    """다른 사이트의 웹 페이지가 사용자 브라우저로 보낸 쓰기 요청을 막는다(CSRF) — 이 앱은 로그인이 없고,
    흘려보낸 `POST .../flatten` 한 번이 모의계좌 주문이 되며 `POST /strategies` 는 서버에서 파이썬을 돌린다. 조회(GET)는 보지 않는다.
    (Host 자체를 거르는 DNS 리바인딩 방어는 `main.py` 의 `TrustedHostMiddleware` 가 앱 전체에 한다.)

    - `Sec-Fetch-Site: cross-site` 면 거절.
    - `Origin` 이 있으면 `_origin_allowed` 를 통과해야 한다(`null` 포함 거절).
    - `Origin` 이 없으면 통과(curl·시험은 보내지 않는다). 브라우저의 쓰기 요청에는 늘 붙는다."""
    if request.method not in UNSAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail=FOREIGN_SITE)
    origin = request.headers.get("origin")
    # 팀: 서버 배포(Cloudflare Tunnel 뒤)에서는 Origin 이 공개 주소다 — Host 와 같고 NH_PUBLIC_HOSTS 에 있을 때만 받는다.
    if origin is not None and not _origin_allowed(request, origin):
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
#: 전략 파일 작성 규칙 문서. 이 패키지의 `guide/` 에 있고(도커 이미지에도 backend/ 와 함께 들어감), 부를 때마다 읽는다.
CONVENTION_DOC = Path(__file__).resolve().parent / "guide" / "strategy-file-convention.md"


class StartBody(BaseModel):
    """시작 요청. `mode` 는 일부러 문자열로 받는다 — 이상한 값은 422 가 아니라 거부 문장(409)으로 알린다.

    `sym` 은 주문하는 종목, `signal_sym` 은 실시간 전략이 시세로만 보는 KRX 종목(빈칸·생략 = 국내 최근월물, 1분봉은 비움).
    종목 글자·시장 검사는 registry 가 한다(거부는 409). 모르는 칸은 422 — 칸 이름을 잘못 쓴 종목(`symbol`·`signalSym`)이
    조용히 버려져 최근월물로 시작하지 않게."""

    model_config = ConfigDict(extra="forbid")

    file: str
    mode: str
    sym: str | None = None
    signal_sym: str | None = None


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
    """전략 폴더의 파일 목록. 못 쓰는 파일은 `error` 에 까닭이, 알림(예: 익절 목표 없음)은 `notes` 에 담긴다.
    `modules` 는 오류 없이 불러와지지만 전략 파일이 아닌 파일(공용 코드)의 이름 — 실행은 못 세우고 지울 수는 있다.
    앱에 든 기본 공용 모듈(`strategy`)은 어디에도 나오지 않는다."""
    folder = registry().strategies
    strategies, modules = scan_all(folder)
    return {"folder": str(folder), "strategies": [dataclasses.asdict(s) for s in strategies], "modules": modules}


@router.post("/strategies/reload")
def reload_strategies() -> dict[str, Any]:
    """`GET /strategies` 와 같다 — 목록은 부를 때마다 폴더를 다시 읽는다."""
    return list_strategies()


class UploadBody(BaseModel):
    """전략 파일 올리기. 타입 검사는 `strategy_files` 가 한다 — 이상한 값이 422 가 아니라 문장 있는 400 으로 가게 `Any` 로 받는다."""

    file: Any
    content: Any
    overwrite: Any = False


@router.post("/strategies", status_code=201, dependencies=[Depends(require_json)])
def upload_strategy(body: UploadBody) -> dict[str, Any]:
    """전략 파일 하나를 올린다. 컴파일·실행은 하지 않는다(고장 난 파일은 목록에 오류로 보인다).
    같은 이름이 있고 `overwrite` 가 `true` 가 아니면 409 — 화면이 덮어쓸지 묻는 데 쓴다."""
    try:
        strategy_files.save(registry().strategies, body.file, body.content, body.overwrite is True)
    except strategy_files.BadFile as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except strategy_files.FileExists as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except strategy_files.StoreFailed as e:
        raise HTTPException(status_code=500, detail=str(e)) from None
    return list_strategies()


@router.delete("/strategies/{file}")
def delete_strategy(file: str) -> dict[str, Any]:
    """전략 파일 하나를 지운다. 돌고 있는 실행은 처음 불러온 코드로 계속 간다."""
    try:
        strategy_files.delete(registry().strategies, file)
    except strategy_files.BadFile as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except strategy_files.NoSuchFile as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except strategy_files.StoreFailed as e:
        raise HTTPException(status_code=500, detail=str(e)) from None
    return list_strategies()


@router.get("/convention")
def strategy_convention() -> dict[str, str]:
    """전략 파일 작성 규칙(마크다운 글 그대로). 화면은 꾸미지 않고 글로 보인다."""
    try:
        text = CONVENTION_DOC.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=404, detail="작성 규칙 문서를 찾지 못했습니다") from None
    return {"markdown": text}


# ---------------------------------------------------------------- 실행
@router.get("/runs")
def list_runs() -> dict[str, Any]:
    return {"runs": registry().list()}


# 팀: 반드시 `def`(동기) — FastAPI 가 스레드 풀에서 부른다. 실시간 실행의 `prepare()` 는 원문 구독(RawFeed)을 만들며
# 이벤트 루프에 일을 맡기고 **기다리므로**, `async def` 로 바꿔 루프 스레드에서 부르면 루프가 막힌다
# (시험 `test_시작_라우트는_동기라_원문_구독이_이벤트_루프_밖에서_만들어진다`).
@router.post("/runs", status_code=201, dependencies=[Depends(require_json)])
def start_run(body: StartBody) -> dict[str, Any]:
    """실행을 세운다. 거부는 409(문장 그대로 `detail`). 준비(준비 봉 조회·원문 구독)가 끝난 뒤에 돌아온다."""
    try:
        return registry().start(RunSpec(body.file, body.mode, body.sym, body.signal_sym))  # type: ignore[arg-type]
    except StartRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """도는(이 앱에서 세운) 실행은 `status()`, 그 밖에는 `run.json`. 끝난 실행(끝·오류)이면 이 앱에서 세운 것이어도
    요약 파일에서 `summary`(없으면 null)·`halted`·`unresolved_order`·`params` 를 합친다."""
    live = registry().get(run_id)
    if live is not None:
        data = live.status()
        if data.get("state") in FINISHED_STATES:  # 끝난 실행은 폴더에서 읽은 것과 같은 칸을 보인다
            _merge_summary(data, live.folder)
        return data
    folder = _folder(run_id)
    data = _read_json(folder / "run.json")
    if data is None:
        raise HTTPException(status_code=404, detail=f"실행 기록을 읽지 못했습니다: {run_id}")
    data.setdefault("id", run_id)
    _merge_summary(data, folder)
    return data


def _merge_summary(data: dict[str, Any], folder: Path) -> None:
    """요약 파일(`summary.json`)의 `summary`·`halted`·`unresolved_order`·`params` 를 data 에 넣는다(이미 값이 있는 칸은 그대로)."""
    summary = _read_json(folder / "summary.json") or {}
    data["summary"] = summary.get("summary")
    for key in ("halted", "unresolved_order"):
        if summary.get(key) is not None and data.get(key) is None:
            data[key] = summary[key]
    # 그 실행이 쓴 Params(요약 파일의 `strategy.params`). 없으면 null — 화면은 지금 파일 값을 단서와 함께 쓴다
    if data.get("params") is None:
        strategy = summary.get("strategy")
        data["params"] = strategy.get("params") if isinstance(strategy, dict) else None


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


#: 실시간 차트 줄(`minute`)에서 내보내는 칸 — 실행기가 1분마다 쓰는 요약(`realtime._minute_line`).
REALTIME_BAR_KEYS = ("date", "time", "krx", "mku_mid", "bid", "ask", "spread_ticks", "mku_last", "position")


def _run_info(run_id: str, folder: Path) -> dict[str, Any]:
    """실행의 `kind`·`started_at` — 도는 실행은 객체에서, 아니면 `run.json`(없으면 빈 dict → 1분봉으로 본다)."""
    live = registry().get(run_id)
    if live is not None:
        return {"kind": live.kind, "started_at": live.started_at}
    return _read_json(folder / "run.json") or {}


@router.get("/runs/{run_id}/bars")
def run_bars(run_id: str) -> dict[str, Any]:
    """차트용 `{"kind", "bars", "marks"}`. `kind` 는 실행의 종류(`minute` 1분봉 · `realtime` 실시간).

    1분봉: `bars` 는 판정 봉마다(= `signal` 줄) `date start end open high low close` + 지표 칸 + `side reason stop_ticks`.
    시가·고가·저가는 이 기능 이전에 남긴 기록에는 없어 null 이다.
    실시간: `bars` 는 1분 요약(`minute` 줄)마다 `date time krx mku_mid bid ask spread_ticks mku_last position`
    (`time` 은 그 분의 시작 HHMMSS, 값이 없던 칸은 null). 실시간의 `signal` 줄(Engine 행동)은 봉이 아니라 내보내지 않는다.

    `marks` 는 두 종류 같은 모양 — 체결(`fill`)의 `entry`/`exit` 와 거래(`trade`, 손익·까닭 라벨용) 줄.
    체결이 없는 기록에서는 `trade` 만 나온다. 체결 줄에는 날짜가 없어 앞선 신호(1분봉)·1분(실시간) 줄의 날짜를 따른다
    (실시간은 그 줄이 아직 없으면 실행 시작 날짜)."""
    folder = _folder(run_id)
    info = _run_info(run_id, folder)
    rows, _ = Journal(folder / "journal.jsonl").tail(0)
    if info.get("kind") == "realtime":
        return _realtime_bars(rows, str(info.get("started_at") or "")[:10].replace("-", ""))
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
        elif kind in ("fill", "trade"):
            holding = _mark(marks, row, day or str(row.get("at", ""))[:10], day, holding)
    return {"kind": "minute", "bars": bars, "marks": marks}


def _mark(marks: list[dict[str, Any]], row: dict[str, Any], fill_day: str, trade_day: str, holding: bool) -> bool:
    """체결·거래 줄 하나를 표시로 더하고 다음 `holding`(진입 체결 뒤 = 보유 중)을 돌려준다. 두 종류가 같이 쓴다.
    날짜는 체결 줄이 `fill_day`, 거래 줄은 `exit_date` 가 없을 때 `trade_day`."""
    if row.get("kind") == "fill":
        marks.append({"kind": "exit" if holding else "entry", "date": fill_day,
                      "time": row.get("clock"), "side": row.get("side"), "price": row.get("price")})
        return not holding
    marks.append({"kind": "trade", "date": row.get("exit_date") or trade_day, "time": row.get("exit_time"),
                  "side": row.get("side"), "price": row.get("exit"), "reason": row.get("reason"),
                  "pnl": row.get("pnl"), "ticks": row.get("ticks"), "entry": row.get("entry"),
                  "entry_time": row.get("entry_time")})
    return False


def _realtime_bars(rows: list[dict[str, Any]], start_day: str) -> dict[str, Any]:
    """실시간 실행의 차트 — `minute` 줄이 봉, 체결·거래 줄이 표시(`run_bars` 문서)."""
    bars: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []
    day, holding = start_day, False
    for row in rows:
        kind = row.get("kind")
        if kind == "minute":
            day = row.get("date") or day
            bars.append({k: row.get(k) for k in REALTIME_BAR_KEYS})
        elif kind in ("fill", "trade"):
            holding = _mark(marks, row, day or str(row.get("at", ""))[:10].replace("-", ""), day, holding)
    return {"kind": "realtime", "bars": bars, "marks": marks}


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


# ---------------------------------------------------------------- 매일 자동 시작
class ScheduleBody(BaseModel):
    """자동 시작 만들기. `run_id` = 지금 막 세운 실행(그날은 그 실행으로 치고, 다음 날 그 끝을 본다). 모르는 칸은 422."""

    model_config = ConfigDict(extra="forbid")

    file: str
    mode: str
    run_id: str | None = None


@router.get("/schedules")
def list_schedules() -> dict[str, Any]:
    return {"schedules": schedules().list()}


@router.post("/schedules", status_code=201, dependencies=[Depends(require_json)])
def create_schedule(body: ScheduleBody) -> dict[str, Any]:
    try:
        return schedules().create(body.file, body.mode, body.run_id)
    except ScheduleError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str) -> Response:
    try:
        schedules().delete(schedule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"그 자동 시작을 찾지 못했습니다: {schedule_id}") from None
    return Response(status_code=204)


@router.post("/schedules/{schedule_id}/resume")
def resume_schedule(schedule_id: str) -> dict[str, Any]:
    try:
        return schedules().resume(schedule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"그 자동 시작을 찾지 못했습니다: {schedule_id}") from None


# ---------------------------------------------------------------- 앱을 켜고 끌 때 (main.py lifespan 이 부른다)
async def _recover() -> None:
    """남은 실행 폴더를 닫는다(스레드에서). 실패는 기록만 하고 앱은 계속 뜬다."""
    try:
        closed = await asyncio.to_thread(lambda: registry().recover())
        if closed:
            logger.info("끝나지 않고 남은 파이썬 전략 실행을 닫았습니다: %s", ", ".join(closed))
    except Exception:
        logger.exception("파이썬 전략 실행 복구에 실패했습니다 — 앱은 그대로 뜹니다")
    try:
        # 남은 실행을 닫은 **뒤에** 띄운다 — 자동 시작이 앞선 실행의 끝(「재시작 · 확인 필요」 포함)을 보고 판단하게
        await asyncio.to_thread(lambda: schedules().start_loop())
    except Exception:
        logger.exception("파이썬 전략 자동 시작을 띄우지 못했습니다 — 손으로 시작은 됩니다")


def pyrun_startup() -> asyncio.Task:
    """앱이 뜰 때(이벤트 루프 안에서): NH 호출 관찰자를 꽂고 남은 실행 닫기를 따로 시작한다(기다리지 않는다)."""
    nh_client.call_observer = apilog.observe
    rawfeed.bind_loop(asyncio.get_running_loop())  # 실시간 실행이 허브 구독을 이 루프에 맡긴다
    return asyncio.create_task(_recover())


async def pyrun_shutdown(recover_task: asyncio.Task | None) -> None:
    """앱이 꺼질 때: 모든 실행에 중지를 요청하고(스레드에서 — 이벤트 루프를 막지 않게) 관찰자를 뗀다."""
    if recover_task is not None and not recover_task.done():
        recover_task.cancel()
        await asyncio.gather(recover_task, return_exceptions=True)
    try:
        # 새 실행을 먼저 막고(준비 조회 중이던 자동 시작도 등록 전에 거부됨) 자동 시작 루프를 멈춘다 — 그 뒤에 stop_all
        registry().close_starts()
        await asyncio.to_thread(lambda: schedules().stop_loop())
    except Exception:
        logger.exception("파이썬 전략 자동 시작을 멈추지 못했습니다")
    try:
        try:
            pending = await asyncio.to_thread(lambda: registry().stop_all())
            if pending:
                logger.warning("꺼질 때까지 끝나지 않은 파이썬 전략 실행: %s", ", ".join(pending))
        except Exception:
            logger.exception("파이썬 전략 실행 중지에 실패했습니다")
        finally:
            # 팀: 중지가 취소 등(BaseException)으로 끝나도 남은 원문 구독은 닫는다
            try:
                # 실행이 닫지 않고 남긴 실시간 원문 구독을 허브를 내리기 전에 닫는다(스레드에서 — 루프 일을 기다리므로).
                left = await asyncio.to_thread(rawfeed.close_all)
                if left:
                    logger.warning("닫히지 않고 남은 실시간 원문 구독을 닫았습니다: %s", ", ".join(left))
            except Exception:
                logger.exception("실시간 원문 구독 정리에 실패했습니다")
    finally:
        # 무엇이 실패해도 관찰자와 루프 참조는 놓는다
        if nh_client.call_observer is apilog.observe:
            nh_client.call_observer = None
        rawfeed.unbind_loop()
