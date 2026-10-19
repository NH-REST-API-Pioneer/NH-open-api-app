"""날짜별 예수금 스냅샷 — 쌓고 읽는 자리.

**사용자 홈을 안 건드립니다** — 임시 폴더를 쓰는 저장소를 따로 만들어 씁니다.

NH선물에는 날짜별 줄을 주는 계좌 API 가 없어, 화면이 빠진 날을 하루씩 물으면
그때마다 여기 쌓입니다. 그래서 이 시험이 보는 것은 **「무엇을 다시 묻게 되는가」**
입니다 — 잘못 쌓으면 화면이 같은 날을 영영 다시 묻습니다.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend import deposit_history
from backend.deposit_history import DepositHistory

월요일 = date(2026, 9, 21)
화요일 = date(2026, 9, 22)
수요일 = date(2026, 9, 23)


@pytest.fixture
def 기록(tmp_path):
    return DepositHistory(tmp_path / "deposit-history.json")


def _쌓기(기록, day: str, **값):
    기록.keep(environment="paper", market="domestic", day=day, row={"assets": 1.0, **값})


def _읽기(기록, first=월요일, last=수요일, *, market="domestic", environment="paper"):
    return 기록.read(environment=environment, market=market, first=first, last=last)


# ── 쌓기 ────────────────────────────────────────────────


def test_쌓아_두면_다시_안_묻는다(기록):
    _쌓기(기록, "20260922")

    made = _읽기(기록)

    assert [one["day"] for one in made["days"]] == ["20260922"]
    assert made["missing"] == ["20260921", "20260923"], "아직 안 받은 날만 묻습니다."


def test_받은_순간을_함께_적는다(기록):
    """오늘 값은 장중 내내 바뀝니다 — 「방금 값」과 「아침 값」을 가려야 합니다."""
    _쌓기(기록, "20260922")

    (줄,) = _읽기(기록)["days"]

    assert 줄["fetchedAt"], "언제 받았는지가 있어야 합니다."
    assert "final" not in 줄, "확정됐는지는 알 길이 없어 안 적습니다."


def test_늘_덮어쓴다(기록):
    """나중에 받은 것이 더 맞습니다."""
    _쌓기(기록, "20260922", assets=1.0)
    _쌓기(기록, "20260922", assets=2.0)

    (줄,) = _읽기(기록)["days"]

    assert 줄["assets"] == 2.0


def test_빈_날도_적어_다시_안_묻는다(기록):
    """휴장일이 이렇게 옵니다. 안 적으면 화면이 갈 때마다 그 날을 다시 묻습니다."""
    기록.keep_empty(environment="paper", market="domestic", day="20260922")

    made = _읽기(기록)

    assert [one["day"] for one in made["days"]] == [], "그릴 점이 없습니다."
    assert "20260922" not in made["missing"], "없는 것과 아직 안 받은 것은 다릅니다."


def test_주말은_묻지_않는다(기록):
    """주말은 달력만으로 확실합니다 — 휴장일과 달리 물어 볼 것도 없습니다."""
    made = _읽기(기록, date(2026, 9, 18), date(2026, 9, 22))

    assert made["missing"] == ["20260918", "20260921", "20260922"]


def test_환경과_시장을_안_섞는다(기록):
    """모의와 실전 값이 한 그래프에 섞이면 그 그래프는 어느 계좌의 것도 아닙니다."""
    _쌓기(기록, "20260922")

    assert _읽기(기록, environment="real")["days"] == []
    assert _읽기(기록, market="overseas")["days"] == []
    assert len(_읽기(기록)["days"]) == 1


def test_환경을_모르면_안_쌓는다(기록):
    기록.keep(environment="", market="domestic", day="20260922", row={"assets": 1.0})
    기록.keep(environment="paper", market="domestic", day="아무날", row={"assets": 1.0})

    assert not 기록.path.exists(), "적을 자리를 모르면 파일도 안 만듭니다."


def test_못_써도_조회를_막지_않는다(tmp_path):
    """쌓기 실패로 예수금 화면이 안 뜨면 안 됩니다."""
    기록 = DepositHistory(tmp_path / "없는폴더" / "x" / "deposit-history.json")
    기록.path.parent.parent.write_text("폴더가 아니라 파일", encoding="utf-8")

    기록.keep(environment="paper", market="domestic", day="20260922", row={"assets": 1.0})

    assert _읽기(기록)["days"] == []


def test_너무_많으면_오래된_것부터_버린다(기록, monkeypatch):
    monkeypatch.setattr(deposit_history, "MAX_DAYS", 2)
    for day in ("20260921", "20260922", "20260923"):
        _쌓기(기록, day)

    담긴것 = json.loads(기록.path.read_text(encoding="utf-8"))["days"]["paper/domestic"]

    assert sorted(담긴것) == ["20260922", "20260923"]


# ── 파일을 못 읽을 때 ───────────────────────────────────


def test_못_읽으면_답에_적는다(기록):
    """지난 값이 통째로 비어 보이는 자리입니다 — 화면이 그 사실을 알아야 합니다."""
    기록.path.write_text('{"version": 1, "days": {', encoding="utf-8")

    made = _읽기(기록)

    assert made["days"] == []
    assert 기록.state.payload["status"] == "broken"
    assert 기록.state.payload["movedTo"] == "deposit-history.json.broken"


def test_다시_쌓으면_알림을_놓는다(기록):
    기록.path.write_text('{"version": 1, "days": {', encoding="utf-8")
    _읽기(기록)

    _쌓기(기록, "20260922")

    assert 기록.state.payload["status"] == "ok"


# ── 값이 있는 줄인지 ────────────────────────────────────


def test_숫자가_하나도_없으면_빈_줄이다():
    assert deposit_history.is_empty({"date": "2026-09-22", "items": [{"values": [None]}]})
    assert not deposit_history.is_empty({"items": [{"values": [0.0]}]}), "0 도 값입니다."
    assert not deposit_history.is_empty({"totalPl": 1.5})
    assert deposit_history.is_empty({"marginCall": True}), "참·거짓은 수가 아닙니다."


# ── 재생은 폴더가 다릅니다 ──────────────────────────────


def test_재생은_다른_폴더에_쌓는다():
    """저장해 둔 응답으로 받은 값이 실서버 추이에 섞이면 안 됩니다."""
    실서버 = deposit_history.history_path({})
    재생 = deposit_history.history_path({"NH_REPLAY": "1"})

    assert 실서버 != 재생
    assert 실서버.name == 재생.name == "deposit-history.json"
    assert 재생.parent.name == "state-replay"


# ── 라우트 ──────────────────────────────────────────────


def test_기간_조회가_쌓인_것과_안_받은_날을_낸다(tmp_path, monkeypatch):
    """화면이 이 답으로 **무엇을 더 물을지** 정합니다."""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.nh_api import runtime as nh_runtime

    기록 = DepositHistory(tmp_path / "deposit-history.json")
    monkeypatch.setattr(deposit_history, "store", 기록)
    monkeypatch.setattr(nh_runtime, "active_environment", lambda: "paper")
    기록.keep(environment="paper", market="domestic", day="20260922", row={"assets": 3.0})

    답 = TestClient(app).get("/api/domestic/deposit-history?from=20260921&to=20260923")

    assert 답.status_code == 200
    made = 답.json()
    assert [one["day"] for one in made["days"]] == ["20260922"]
    assert made["missing"] == ["20260921", "20260923"]
    assert made["store"] == {"status": "ok", "stored": True, "movedTo": None, "otherApp": None}


def test_해외도_같은_모양으로_낸다(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.nh_api import runtime as nh_runtime

    기록 = DepositHistory(tmp_path / "deposit-history.json")
    monkeypatch.setattr(deposit_history, "store", 기록)
    monkeypatch.setattr(nh_runtime, "active_environment", lambda: "paper")
    기록.keep(environment="paper", market="overseas", day="20260922", row={"assets": 4.0})

    made = TestClient(app).get("/api/overseas/deposit-history?from=20260922&to=20260922").json()

    assert [one["assets"] for one in made["days"]] == [4.0]
    assert made["missing"] == []


def test_기간이_거꾸로면_안_받는다(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(deposit_history, "store", DepositHistory(tmp_path / "d.json"))
    앱 = TestClient(app)

    assert 앱.get("/api/domestic/deposit-history?from=20260923&to=20260921").status_code == 422
    assert 앱.get("/api/domestic/deposit-history?from=2026-09-21&to=20260923").status_code == 422
    assert 앱.get("/api/domestic/deposit-history?from=20260921").status_code == 422


# ── 예수금 답이 나갈 때 저절로 쌓입니다 ────────────────
#
# **저장하는 라우트는 없습니다.** 화면이 빠진 날을 하루씩 물으면 그 답이 나갈
# 때 쌓이는 것이 전부입니다 — 따로 두면 화면이 같은 값을 두 번 보내고 둘이
# 어긋날 자리가 생깁니다.


class _답하는곳:
    """정해 둔 원문을 내는 호출부. 계좌에 닿지 않습니다."""

    def __init__(self, body, environment="paper"):
        from types import SimpleNamespace

        self.body = body
        self.보낸것: list[tuple[str, dict]] = []
        self.session = SimpleNamespace(
            config=SimpleNamespace(default_environment=environment), is_replay=False
        )

    def call(self, api_id, payload, environment=None):
        from backend.nh_api.client import ApiResult

        self.보낸것.append((api_id, dict(payload)))
        return ApiResult(
            api_id=api_id,
            environment="paper",
            market="domestic" if api_id.startswith("domestic") else "overseas",
            http_status=200,
            body=self.body,
            headers={},
        )


def _앱(호출부, monkeypatch, tmp_path, *, 시장="domestic"):
    from fastapi.testclient import TestClient

    from backend.domestic_futureoption.domestic_routes import get_client as 국내문
    from backend.main import app
    from backend.overseas_futureoption.overseas_routes import get_client as 해외문

    기록 = DepositHistory(tmp_path / "deposit-history.json")
    monkeypatch.setattr(deposit_history, "store", 기록)
    app.dependency_overrides[국내문 if 시장 == "domestic" else 해외문] = lambda: 호출부
    monkeypatch.setattr(
        "backend.nh_api.runtime.active_environment", lambda: "paper", raising=False
    )
    return TestClient(app), 기록


def test_국내_예수금을_부르면_그날이_쌓인다(tmp_path, monkeypatch):
    호출부 = _답하는곳({"dps_aset_tot_amt": "1000", "pl_tot_pric": "5"})
    앱, 기록 = _앱(호출부, monkeypatch, tmp_path)
    try:
        앱.post("/api/domestic/deposit", json={"biz_dt": "20260922"})
    finally:
        _문닫기()

    made = 기록.read(environment="paper", market="domestic", first=화요일, last=화요일)
    assert [one["day"] for one in made["days"]] == ["20260922"]
    assert made["missing"] == []


def test_빈_답이면_빈_날로_쌓인다(tmp_path, monkeypatch):
    """휴장일입니다. 다시 묻지 않도록 적어 둡니다."""
    앱, 기록 = _앱(_답하는곳({"nrec": "0000", "nxt_key": ""}), monkeypatch, tmp_path)
    try:
        앱.post("/api/domestic/deposit", json={"biz_dt": "20260922"})
    finally:
        _문닫기()

    made = 기록.read(environment="paper", market="domestic", first=화요일, last=화요일)
    assert made["days"] == [] and made["missing"] == []


def test_해외는_원화_환산만_쌓는다(tmp_path, monkeypatch):
    """기준마다 쌓으면 빠진 날 채우기가 기준 수만큼 늘어납니다."""
    호출부 = _답하는곳({"biz_dt": "20260922", "dps_aset_amt": "7", "pl_amt": "1"})
    앱, 기록 = _앱(호출부, monkeypatch, tmp_path, 시장="overseas")
    try:
        앱.post("/api/overseas/deposit", json={})
        기준밖 = 기록.read(environment="paper", market="overseas", first=화요일, last=화요일)
        앱.post("/api/overseas/deposit", json={"cur_cd": "USD", "cvs_div": "1"})
        뒤 = 기록.read(environment="paper", market="overseas", first=화요일, last=화요일)
    finally:
        _문닫기()

    assert [one["day"] for one in 기준밖["days"]] == ["20260922"], "기본이 원화 환산입니다."
    assert 뒤["days"] == 기준밖["days"], "통화를 나눠 부른 답은 안 쌓입니다."


def test_해외_통화별로_부른_답이_쌓인_값을_덮지_않는다(tmp_path, monkeypatch):
    """통화를 나눠 부른 답이 들면 추이에 통화가 섞입니다."""
    호출부 = _답하는곳({"biz_dt": "20260922", "dps_aset_amt": "7", "pl_amt": "1"})
    앱, 기록 = _앱(호출부, monkeypatch, tmp_path, 시장="overseas")
    try:
        앱.post("/api/overseas/deposit", json={})
        앞 = 기록.read(environment="paper", market="overseas", first=화요일, last=화요일)
        호출부.body = {"biz_dt": "20260922", "dps_aset_amt": "99", "pl_amt": "50", "cur_cd": "USD"}
        앱.post("/api/overseas/deposit", json={"cur_cd": "USD", "cvs_div": "1"})
        뒤 = 기록.read(environment="paper", market="overseas", first=화요일, last=화요일)
    finally:
        _문닫기()

    assert 뒤 == 앞
    assert "USD" not in json.dumps(뒤, ensure_ascii=False)


def _문닫기():
    from backend.main import app

    app.dependency_overrides.clear()


# ── 어느 앱이 쓴 파일인가 ───────────────────────────────


def _남의것으로(기록):
    """파일의 표지만 다른 앱 것으로 바꿔 둡니다."""
    담긴것 = json.loads(기록.path.read_text(encoding="utf-8"))
    남 = "replay" if 담긴것["origin"] == "live" else "live"
    담긴것["origin"] = 남
    기록.path.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")
    return 남


def test_쌓을_때_어느_앱이_썼는지_적는다(기록):
    _쌓기(기록, "20260921")

    담긴것 = json.loads(기록.path.read_text(encoding="utf-8"))

    assert 담긴것["origin"] == deposit_history.current_mode()


def test_다른_앱이_쌓은_값은_안_읽는다(기록):
    """저장본으로 도는 앱이 쌓은 잔고를 추이에 이어 붙이면, 그래프는 있었던 적
    없는 흐름을 그립니다."""
    _쌓기(기록, "20260921")
    남 = _남의것으로(기록)

    읽은것 = _읽기(기록)

    assert 읽은것["days"] == []
    assert "20260921" in 읽은것["missing"], "다시 물어야 하는 날입니다."
    assert 기록.state.payload["otherApp"] == 남


def test_다른_앱이_쌓은_값을_이어받지_않는다(기록):
    """이 앱이 쌓을 때 저쪽 값이 이 앱의 파일로 딸려 오면 안 됩니다."""
    _쌓기(기록, "20260921")
    _남의것으로(기록)

    _쌓기(기록, "20260922")

    담긴것 = json.loads(기록.path.read_text(encoding="utf-8"))
    (열쇠,) = 담긴것["days"]
    assert list(담긴것["days"][열쇠]) == ["20260922"]
    assert 담긴것["origin"] == deposit_history.current_mode()


# ── 최근 날은 다시 받습니다 ─────────────────────────────
#
# 해외 예수금은 그날 정산 전에 물으면 앞 영업일 값을 그날 날짜로 답할 때가
# 있습니다. 오늘 값도 장중 내내 바뀝니다. 그래서 최근 두 영업일은 쌓여 있어도
# `refresh` 로 내 화면이 다시 묻게 합니다.

금요일 = date(2026, 10, 2)
다음_월요일 = date(2026, 10, 5)


def _오늘(monkeypatch, 날: date):
    from datetime import datetime

    from backend.sessions.hours import KST

    monkeypatch.setattr(
        deposit_history, "now_kst", lambda: datetime(날.year, 날.month, 날.day, 10, tzinfo=KST)
    )


def test_최근_두_영업일은_쌓여_있어도_다시_받는다(기록, monkeypatch):
    _오늘(monkeypatch, 금요일)
    for 날 in ("20260930", "20261001", "20261002"):
        _쌓기(기록, 날)

    made = _읽기(기록, date(2026, 9, 30), 금요일)

    assert made["refresh"] == ["20261001", "20261002"], "3영업일 전은 안 듭니다."
    assert made["missing"] == [], "missing 은 안 받은 날만입니다."
    assert [one["day"] for one in made["days"]] == ["20260930", "20261001", "20261002"], (
        "다시 받는 동안 화면이 그릴 값은 남습니다."
    )


def test_월요일이면_금요일이_든다(기록, monkeypatch):
    _오늘(monkeypatch, 다음_월요일)

    assert _읽기(기록, date(2026, 9, 28), 다음_월요일)["refresh"] == ["20261002", "20261005"]


def test_주말이면_금요일과_목요일이다(기록, monkeypatch):
    _오늘(monkeypatch, date(2026, 10, 4))

    assert _읽기(기록, date(2026, 9, 28), date(2026, 10, 4))["refresh"] == [
        "20261001",
        "20261002",
    ]


def test_기간이_다_지난_날이면_다시_받을_날이_없다(기록, monkeypatch):
    _오늘(monkeypatch, 금요일)
    _쌓기(기록, "20260922")

    made = _읽기(기록)

    assert made["refresh"] == []
    assert made["missing"] == ["20260921", "20260923"], "missing 은 지금과 같습니다."


def test_기간과_겹치는_날만_다시_받는다(기록, monkeypatch):
    _오늘(monkeypatch, 금요일)

    assert _읽기(기록, date(2026, 9, 28), date(2026, 10, 1))["refresh"] == ["20261001"]


def test_빈_날로_적힌_최근_날도_다시_받는다(기록, monkeypatch):
    """장 열기 전에 받은 빈 답이 그날로 굳으면 안 됩니다."""
    _오늘(monkeypatch, 금요일)
    기록.keep_empty(environment="paper", market="domestic", day="20261002")

    made = _읽기(기록, 금요일, 금요일)

    assert made["refresh"] == ["20261002"]
    assert made["missing"] == [] and made["days"] == []


def test_빈_답이_쌓인_값을_지우지_않는다(기록):
    """다시 물은 날에 빈 답이 와도 이미 받은 값은 남습니다."""
    _쌓기(기록, "20260922", assets=5.0)
    기록.keep_empty(environment="paper", market="domestic", day="20260922")

    (줄,) = _읽기(기록)["days"]

    assert 줄["assets"] == 5.0


def test_빈_날은_값이_오면_덮인다(기록):
    기록.keep_empty(environment="paper", market="domestic", day="20260922")
    _쌓기(기록, "20260922", assets=6.0)

    (줄,) = _읽기(기록)["days"]

    assert 줄["assets"] == 6.0


def test_덮어쓰면_받은_시각도_새로_적는다(기록, monkeypatch):
    from datetime import datetime

    from backend.sessions.hours import KST

    monkeypatch.setattr(deposit_history, "now_kst", lambda: datetime(2026, 10, 2, 9, tzinfo=KST))
    _쌓기(기록, "20260922", assets=1.0)
    monkeypatch.setattr(deposit_history, "now_kst", lambda: datetime(2026, 10, 2, 15, tzinfo=KST))
    _쌓기(기록, "20260922", assets=2.0)

    (줄,) = _읽기(기록)["days"]

    assert 줄["assets"] == 2.0
    assert 줄["fetchedAt"] == "2026-10-02T15:00:00+09:00"


def test_저장_파일에는_다시_받을_날을_안_적는다(기록, monkeypatch):
    _오늘(monkeypatch, 금요일)
    _쌓기(기록, "20261002")
    _읽기(기록, 금요일, 금요일)

    body = json.loads(기록.path.read_text(encoding="utf-8"))

    assert body["version"] == 1
    assert set(body) == {"version", deposit_history.ORIGIN, "basis", "days"}


@pytest.mark.parametrize("시장", ["domestic", "overseas"])
def test_라우트가_다시_받을_날을_낸다(tmp_path, monkeypatch, 시장):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.nh_api import runtime as nh_runtime

    _오늘(monkeypatch, 금요일)
    기록 = DepositHistory(tmp_path / "deposit-history.json")
    monkeypatch.setattr(deposit_history, "store", 기록)
    monkeypatch.setattr(nh_runtime, "active_environment", lambda: "paper")
    기록.keep(environment="paper", market=시장, day="20261001", row={"assets": 7.0})

    made = TestClient(app).get(f"/api/{시장}/deposit-history?from=20260930&to=20261002").json()

    assert made["refresh"] == ["20261001", "20261002"]
    assert made["missing"] == ["20260930", "20261002"]
    assert [one["day"] for one in made["days"]] == ["20261001"]
