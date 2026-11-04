"""매일 자동 시작 — 장이 열리는 날마다 정한 시각에 같은 전략 파일·같은 방식으로 새 실행을 세운다.

실행 하나는 하루치입니다(해외 23:55·국내 장 마감 정리 뒤 「끝」, 또는 전략 `flatten_at` 까지). 이 모듈은 실행을
**이어 돌리지 않고**, 날마다 `Registry.start()` 를 한 번 더 부를 뿐입니다. 그래서 시작 거부 규칙(주말·모의 환경 아님·
시작 잔고 0 아님·같은 종목 모의 계좌 실행·끝 시각 뒤)과 주문 안전 규칙은 손으로 누른 시작과 똑같이 걸립니다.

    예약 하나     = (전략 파일, 방식 orders|paper). 종목은 날마다 그날의 최근월물(실시간은 KRX 신호 종목도 최근월물)
    시작 시각     = 전략 시장의 장 시작 5분 전 — 해외 08:20, 국내 08:55 (장 전에 세우면 실행은 「대기」로 기다림)
    시도         = 그날 시작 시각 뒤 한 번, 거부되면 5분 뒤 다시 — 하루 3번까지. 끝 시각이 지나면 그날은 건너뜀
    저장         = `state_dir()/pyrun_schedules.json` (앱을 다시 켜도 남음)

**안 하는 것 (주문 재전송 금지 원칙)**
- 앞선 실행이 「확인 필요」·「오류」로 끝났거나, `summary.json` 에 결과 모름 주문(`unresolved_order`)·멈춤(`halted`)이
  남았거나, 끝내기가 실패했거나, 기록을 못 찾으면(**모르면 막는다**) **다음 날 시작하지 않고 예약을 막아 둡니다**(`blocked`).
  화면에서 계좌를 확인한 뒤 「다시 켜기」를 눌러야 풉니다 — 그날 시작 시각이 지난 뒤 켜면 그날은 건너뜁니다(`skip_day`).
  앞선 실행이 아직 도는 중이면(대기·진행 중) 그날은 기다립니다.
- 앱을 끌 때는 `Registry.close_starts()` 로 새 실행을 먼저 막고 이 루프를 멈춥니다(준비 조회 중이던 시작도 등록 전에 거부).
- 그날 이미 세운 실행이 있으면(앱을 다시 켰더라도) 그날은 다시 세우지 않습니다 — 하루 중간에 끊긴 실행을 이어 돌리는
  「재시작 시 자동 재개」가 되지 않게. 시도를 적은 **뒤에** 시작을 부릅니다(시작 도중 앱이 죽어도 다시 세우지 않음).
- 휴장일은 따로 알지 못합니다 — 그날도 실행은 세워지고, 시세가 없으니 거래 없이 끝납니다.

예약을 만들 때 이미 그날 시작 시각이 지났으면 첫 시작은 **다음 날**입니다(만든 순간 갑자기 실행이 서지 않게).
화면의 「매일 자동 시작」은 지금 실행을 세운 뒤 그 실행 id 를 함께 넘겨(`run_id`), 다음 날 그 실행의 끝을 보고 판단합니다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from backend.sessions.hours import now_kst, to_kst
from backend.team_pyrun.live import RunSpec, StartRefused, run_market
from backend.team_pyrun.loader import LoadError, load
from backend.team_pyrun.markets import DOMESTIC, OVERSEAS, Market

logger = logging.getLogger(__name__)

#: 그날 시작 시도 횟수 상한과 시도 사이 간격.
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=5)
#: 장 시작보다 이만큼 먼저 세운다(실행은 「대기」로 장을 기다림).
LEAD = timedelta(minutes=5)
#: 예약 루프가 깨는 간격(초).
TICK_SECONDS = 20.0
#: 앞선 실행이 아직 도는 중인 상태 — 그날은 건너뛴다.
RUNNING_STATES = ("대기", "진행 중")
MODES = ("orders", "paper")
_ID_SAFE = re.compile(r"[^0-9A-Za-z_]")
_MARKETS = {DOMESTIC.id: DOMESTIC, OVERSEAS.id: OVERSEAS}


class ScheduleError(ValueError):
    """예약을 만들거나 바꿀 수 없음 — 문장 그대로 화면에 보인다."""


class RegistryLike(Protocol):
    root: Path
    strategies: Path

    def start(self, spec: RunSpec) -> dict: ...
    def get(self, run_id: str) -> Any: ...


def fire_time(market: Market) -> str:
    """그 시장의 예약 시작 시각(HHMMSS) — 장 시작 5분 전."""
    t = datetime.strptime(market.session_start, "%H%M%S") - LEAD
    return t.strftime("%H%M%S")


def blocked_reason(state: str | None, ended_reason: str | None) -> str | None:
    """앞선 실행의 끝이 사람이 봐야 하는 끝이면 그 까닭, 아니면 None."""
    reason = ended_reason or ""
    if state == "확인 필요" or "확인 필요" in reason:
        return f"앞선 실행이 「확인 필요」로 끝남 — 계좌를 확인한 뒤 다시 켜세요 ({reason or state})"
    if state == "오류" or reason.startswith("오류"):
        return f"앞선 실행이 「오류」로 끝남 — 기록을 확인한 뒤 다시 켜세요 ({reason or state})"
    if "끝내기 처리 실패" in reason:
        return f"앞선 실행의 끝내기(정리·끝 잔고)가 실패함 — 계좌를 확인한 뒤 다시 켜세요 ({reason})"
    return None


def summary_reason(summary: dict | None) -> str | None:
    """앞선 실행의 `summary.json` 이 결과 모름 주문·멈춤을 남겼으면 그 까닭. 끝 까닭에 「확인 필요」가 없어도 막는다
    (잔고가 맞아 멈추지 않고 끝난 실행도 `unresolved_order` 를 남길 수 있다 — 그 주문이 나중에 체결될 수 있음)."""
    if not isinstance(summary, dict):
        return None
    if summary.get("unresolved_order"):
        return "앞선 실행에 결과를 모르는 주문이 남음 — 주문내역·잔고를 확인한 뒤 다시 켜세요"
    if summary.get("halted"):
        return f"앞선 실행이 멈춘 채 끝남 — 계좌를 확인한 뒤 다시 켜세요 ({summary.get('halted')})"
    return None


class Schedules:
    """예약 목록과 날마다 시작하는 일. 앱에 하나(`schedules()`)."""

    def __init__(self, path: Path, registry: RegistryLike, *, now: Callable[[], datetime] = now_kst):
        self.path, self.registry, self._now = Path(path), registry, now
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._closed = False                        # 한 번 멈추면(앱을 끄는 중) 다시 띄우지 않는다
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ 저장
    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("schedules") if isinstance(data, dict) else None
        return [s for s in items if isinstance(s, dict) and s.get("id")] if isinstance(items, list) else []

    def _write(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"schedules": items}, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _stamp(self) -> str:
        return to_kst(self._now()).replace(tzinfo=None).isoformat(timespec="seconds")

    # ------------------------------------------------------------ 조회·바꾸기
    def list(self) -> list[dict]:
        """예약들 + 다음 시작 예정(`next_start`, 막혔거나 꺼졌으면 None)."""
        with self._lock:
            items = self._read()
        now = to_kst(self._now())
        return [{**s, "next_start": self._next_start(s, now)} for s in items]

    def create(self, file: str, mode: str, run_id: str | None = None) -> dict:
        if mode not in MODES:
            raise ScheduleError(f"실행 방식이 올바르지 않습니다: {mode!r} (orders 또는 paper)")
        if Path(file).name != file or not file.endswith(".py"):
            raise ScheduleError(f"전략 파일 이름이 올바르지 않습니다: {file!r}")
        try:
            loaded = load(self.registry.strategies, file)
        except LoadError as e:
            raise ScheduleError(f"전략 파일을 불러오지 못했습니다 — {e}") from e
        market, refusal = run_market(None, loaded)
        if refusal:
            raise ScheduleError(refusal)
        if run_id is not None:
            run = self.registry.get(run_id)
            if run is None:
                raise ScheduleError(f"그 실행을 찾지 못했습니다: {run_id}")
            spec = getattr(run, "spec", None)
            if spec is None or spec.file != file or spec.mode != mode:
                raise ScheduleError(f"이은 실행({run_id})이 다른 전략·방식입니다 — 같은 파일·방식의 실행만 이을 수 있습니다")
        now = to_kst(self._now())
        sid = _ID_SAFE.sub("_", f"{Path(file).stem}_{mode}")
        with self._lock:
            items = self._read()
            for s in items:
                if s["id"] == sid:
                    raise ScheduleError(f"이 전략·방식의 자동 시작이 이미 있습니다 ({s['file']} · {mode})")
                if mode == "orders" and s.get("mode") == "orders" and s.get("market") == market.id:
                    # 같은 시장의 모의 계좌 실행은 날마다 같은 최근월물을 주문한다 — 둘째는 날마다 거부될 뿐이다
                    raise ScheduleError(f"같은 시장의 모의 계좌 자동 시작이 이미 있습니다 ({s['file']}) — 먼저 지우세요")
            at = fire_time(market)
            # 오늘 시작 시각이 이미 지났으면 첫 시작은 내일 — 만든 순간 실행이 서지 않게
            today = now.strftime("%Y%m%d")
            late = run_id is None and now.strftime("%H%M%S") >= at
            item = {
                "id": sid, "file": file, "mode": mode, "market": market.id, "at": at,
                "created_at": self._stamp(), "blocked": None,
                "last_day": today if run_id else None, "attempts": 0,
                "last_run_id": run_id, "skip_day": today if late else None,
                "last_result": ("지금 세운 실행과 이어짐" if run_id
                                else "오늘 시작 시각이 지나 다음 장 날부터" if late else None),
                "next_try": None,
            }
            items.append(item)
            self._write(items)
        return {**item, "next_start": self._next_start(item, now)}

    def delete(self, sid: str) -> None:
        with self._lock:
            items = self._read()
            kept = [s for s in items if s["id"] != sid]
            if len(kept) == len(items):
                raise KeyError(sid)
            self._write(kept)

    def resume(self, sid: str) -> dict:
        """막힌 예약을 푼다(사람이 계좌·기록을 확인한 뒤). 앞선 실행 연결도 끊어, 같은 끝으로 다시 막히지 않게."""
        with self._lock:
            items = self._read()
            for s in items:
                if s["id"] == sid:
                    # 오늘 시작 시각이 이미 지났으면 오늘은 세우지 않는다 — 다시 켜는 순간 확인 없이 실행이 서지 않게
                    # (시작 도중 꺼진 날이면 같은 날 두 번째 실행이 되기도 한다). 장 전에 켜면 오늘 시작 시각에 선다
                    now = to_kst(self._now())
                    late = now.strftime("%H%M%S") >= str(s.get("at") or "")
                    s.update(blocked=None, last_run_id=None, skip_day=now.strftime("%Y%m%d") if late else s.get("skip_day"),
                             last_result=f"다시 켬 ({self._stamp()})" + (" — 오늘은 시작 시각이 지나 다음 장 날부터" if late else ""))
                    self._write(items)
                    return {**s, "next_start": self._next_start(s, to_kst(self._now()))}
        raise KeyError(sid)

    # ------------------------------------------------------------ 날마다
    @staticmethod
    def _day_done(s: dict, key: str) -> bool:
        """그날(`key` YYYYMMDD) 할 일이 끝났나 — 실행을 세웠거나, 시도를 다 썼거나, 만든 날이라 건너뛰는 날."""
        if s.get("skip_day") == key:
            return True
        return s.get("last_day") == key and bool(s.get("last_run_id")
                                                 or int(s.get("attempts") or 0) >= MAX_ATTEMPTS)

    def _next_start(self, s: dict, now: datetime) -> str | None:
        """다음 시작 예정(ISO 초). 막혔으면 None. 오늘 시작 시각이 지났지만 아직 안 세웠으면 오늘(곧) 시각."""
        if s.get("blocked"):
            return None
        at = str(s.get("at") or "")
        naive = now.replace(tzinfo=None)
        day = naive.date()
        for _ in range(8):
            key = day.strftime("%Y%m%d")
            if day.weekday() < 5 and not self._day_done(s, key):
                if day > naive.date() or naive.strftime("%H%M%S") < self._end_of(s):
                    t = datetime.strptime(key + at, "%Y%m%d%H%M%S")
                    if s.get("last_day") == key and s.get("next_try"):
                        t = max(t, datetime.fromisoformat(s["next_try"]))
                    return t.isoformat(timespec="seconds")
            day += timedelta(days=1)
        return None

    def _end_of(self, s: dict) -> str:
        return _MARKETS.get(str(s.get("market")), DOMESTIC).end_time

    def _read_folder_json(self, run_id: str, name: str) -> dict | None:
        try:
            data = json.loads((self.registry.root / run_id / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _previous(self, run_id: str) -> tuple[str | None, str | None]:
        """앞선 실행 확인. (막는 까닭 | None, 상태). 도는 실행이면 그 객체, 아니면 폴더의 run.json 으로 상태를 보고,
        폴더의 summary.json 도 본다. **못 찾으면 막는다**(모르는 끝을 깨끗한 끝으로 치지 않는다)."""
        run = self.registry.get(run_id)
        if run is not None:
            state, reason = getattr(run, "state", None), getattr(run, "ended_reason", None)
        else:
            data = self._read_folder_json(run_id, "run.json")
            if data is None:
                return f"앞선 실행({run_id})의 기록을 찾지 못함 — 기록·계좌를 확인한 뒤 다시 켜세요", None
            state, reason = data.get("state"), data.get("ended_reason")
            if state in RUNNING_STATES or state == "확인 필요":
                # 이 앱에 그 실행 객체가 없는데 폴더는 아직 돈다고 적혀 있다 — 켤 때 정리(recover)가 못 닫은 것. 기다리면 영영 안 끝난다
                return f"앞선 실행({run_id})이 끝나지 않은 채 남음({state}) — 기록·계좌를 확인한 뒤 다시 켜세요", state
        if state in RUNNING_STATES:
            return None, state
        why = blocked_reason(state, reason) or summary_reason(self._read_folder_json(run_id, "summary.json"))
        if why is None and state not in ("끝", "오류"):
            why = f"앞선 실행({run_id})의 상태를 알 수 없음({state}) — 기록을 확인한 뒤 다시 켜세요"
        return why, state

    def tick(self) -> list[str]:
        """지금 시작할 예약을 시작하고, 세운 실행 id 들을 돌려준다. 예약 루프가 20초마다 부른다."""
        started: list[str] = []
        now = to_kst(self._now())
        if now.weekday() >= 5:
            return started
        today, clock = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
        with self._lock:
            ids = [s["id"] for s in self._read()]
        for sid in ids:
            if self._stop.is_set():                 # 앱을 끄는 중 — 새 실행을 세우지 않는다
                break
            run_id = self._tick_one(sid, today, clock, now)
            if run_id:
                started.append(run_id)
        return started

    def _tick_one(self, sid: str, today: str, clock: str, now: datetime) -> str | None:
        if self._stop.is_set():
            return None
        with self._lock:
            items = self._read()
            s = next((x for x in items if x["id"] == sid), None)
            if s is None or s.get("blocked") or self._day_done(s, today):
                return None
            if clock < str(s.get("at")) or clock >= self._end_of(s):
                return None
            if s.get("last_day") != today:            # 오늘 첫 시도 — 앞선 실행의 끝을 본다
                prev = s.get("last_run_id")
                if prev:
                    why, state = self._previous(prev)
                    if why:
                        s.update(blocked=why, last_result=why)
                        self._write(items)
                        logger.warning("자동 시작 막음 %s — %s", sid, why)
                        return None
                    if state in RUNNING_STATES:
                        return None             # 앞선 실행이 아직 돈다 — 끝나면 다음 깸에서 다시 본다
                s.update(last_day=today, attempts=0, next_try=None, last_run_id=None)
            elif s.get("next_try") and now.replace(tzinfo=None) < datetime.fromisoformat(s["next_try"]):
                return None
            # 시도를 **먼저** 적는다 — 시작 도중 앱이 죽어도 같은 날 다시 세우지 않게(다음 깸은 이 기록을 본다)
            s["attempts"] = int(s.get("attempts") or 0) + 1
            s["next_try"] = (now.replace(tzinfo=None) + RETRY_AFTER).isoformat(timespec="seconds")
            s["last_result"] = f"시작 시도 {s['attempts']}/{MAX_ATTEMPTS} ({self._stamp()})"
            s["starting"] = True                    # 시작이 끝나면 `_record` 가 지운다. 남아 있으면 앱이 시작 도중 꺼진 것
            self._write(items)
            spec = RunSpec(s["file"], s["mode"], None, None)
        try:
            status = self.registry.start(spec)      # 잠금 밖 — 준비(조회)가 오래 걸려도 목록·바꾸기를 막지 않게
        except StartRefused as e:
            self._record(sid, None, f"시작 거부 {s['attempts']}/{MAX_ATTEMPTS}: {e}")
            return None
        except Exception as e:                      # 뜻밖의 고장도 예약 루프를 죽이지 않는다
            logger.exception("자동 시작 실패 %s", sid)
            self._record(sid, None, f"시작 실패 {s['attempts']}/{MAX_ATTEMPTS}: {type(e).__name__}: {e}")
            return None
        run_id = str(status.get("id") or "")
        self._record(sid, run_id or None, f"시작함 {run_id} ({self._stamp()})")
        logger.info("자동 시작 %s → %s", sid, run_id)
        return run_id or None

    def _record(self, sid: str, run_id: str | None, result: str) -> None:
        with self._lock:
            items = self._read()
            for s in items:
                if s["id"] == sid:
                    if run_id:
                        s["last_run_id"] = run_id
                    s["last_result"] = result
                    s["starting"] = False
                    self._write(items)
                    return

    # ------------------------------------------------------------ 예약 루프 (앱을 켜고 끌 때)
    def start_loop(self) -> None:
        """예약 루프를 띄운다(앱이 켜질 때, 남은 실행 닫기 **뒤에**). 시작 도중 꺼진 예약은 먼저 막아 둔다."""
        if self._closed or (self._thread is not None and self._thread.is_alive()):
            return
        self.block_interrupted()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="pyrun-autostart", daemon=True)
        self._thread.start()

    def stop_loop(self, timeout: float = 5.0) -> None:
        self._closed = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def block_interrupted(self) -> list[str]:
        """앞선 앱이 시작을 부른 채 꺼진 예약(`starting`)을 막는다 — 그 실행이 섰는지·주문했는지 모르니
        같은 날 다시 세우지 않고 사람이 보게. 막은 id 들을 돌려준다."""
        out = []
        with self._lock:
            items = self._read()
            for s in items:
                if s.get("starting"):
                    why = "앱이 실행을 세우던 중에 꺼짐 — 실행 기록·계좌를 확인한 뒤 다시 켜세요"
                    s.update(starting=False, blocked=why, last_result=why)
                    out.append(s["id"])
            if out:
                self._write(items)
        return out

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("자동 시작 확인 실패 — 다음 깸에서 다시 봅니다")
            self._stop.wait(TICK_SECONDS)


_schedules: Schedules | None = None
_schedules_lock = threading.Lock()


def schedules() -> Schedules:
    """앱에 하나뿐인 `Schedules`(`state_dir()/pyrun_schedules.json`, 실행 관리는 `registry()`)."""
    global _schedules
    from backend import storage
    from backend.team_pyrun.registry import registry
    with _schedules_lock:
        if _schedules is None:
            _schedules = Schedules(storage.state_dir() / "pyrun_schedules.json", registry())
        return _schedules
