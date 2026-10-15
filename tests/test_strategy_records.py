"""성과분석 기록 — 기록 파일 읽기와 집계, 조회 라우트.

**임시 폴더의 기록 파일만 씁니다.** 사용자 홈의 상태 폴더는 읽지도 쓰지도
않습니다(파일 자리를 바꿔 끼움).
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.sessions.hours import KST
from backend.strategy import journal as journal_lib
from backend.strategy import records, runs
from backend.strategy import service as service_lib
from backend.strategy.store import StrategyStore
from backend.strategy.strategy_routes import get_journal, get_service, get_store


def _때(day: int, hour: int, minute: int = 0, month: int = 9) -> int:
    return int(datetime(2026, month, day, hour, minute, tzinfo=KST).timestamp() * 1000)


def _거래(
    closed: int,
    *,
    net: float = 100.0,
    gross: float | None = None,
    fee: float = 10.0,
    run: str = "r1",
    version: str = "v1",
    strategy: str | None = "g1",
    market: str = "domestic",
    record: str = "paper",
    session: str = "domestic-day",
    side: str = "buy",
    quantity: int = 1,
    code: str = "A0166000",
    opened: int | None = None,
) -> dict:
    row = {
        "kind": "trade",
        "runId": run,
        "versionId": version,
        "market": market,
        "code": code,
        "session": session,
        "record": record,
        "openedAt": opened if opened is not None else closed - 600_000,
        "closedAt": closed,
        "side": side,
        "quantity": quantity,
        "avgEntry": 400.0,
        "avgExit": 401.0,
        "grossPl": gross if gross is not None else net + fee,
        "fee": fee,
        "netPl": net,
    }
    if strategy is not None:
        row["groupId"] = strategy
    return row


def _쓰기(path, *rows: dict, tail: bytes = b"") -> None:
    body = "".join(json.dumps(one, ensure_ascii=False) + "\n" for one in rows).encode("utf-8")
    with open(path, "ab") as file:
        file.write(body + tail)


@pytest.fixture
def 기록(tmp_path):
    return journal_lib.Journal(tmp_path / "strategy-trades.jsonl")


def _조건(**덮어쓰기) -> records.Query:
    made = {
        "record": "paper",
        "market": "domestic",
        "start": date(2026, 9, 1),
        "end": date(2026, 9, 30),
        "versions": frozenset(),
        "code": "",
    }
    made.update(덮어쓰기)
    return records.Query(**made)


# ── 읽기 ────────────────────────────────────────────────


def test_잘린_마지막_줄만_버리고_앞_줄은_다_읽는다(기록):
    """끝 줄이 한글 글자 가운데에서 잘려도 파일 전체가 빈 것으로 보이지 않습니다."""
    이벤트 = {"kind": "event", "runId": "r1", "text": "준비 봉 3개를 받았습니다"}
    반쪽 = json.dumps({"kind": "event", "text": "세션이 끝났습니다"}, ensure_ascii=False).encode("utf-8")
    _쓰기(기록.path, _거래(_때(17, 10)), 이벤트, tail=반쪽[:-5])

    assert [one["kind"] for one in 기록.read()] == ["trade", "event"]
    줄들, 온전 = 기록.trades()
    assert len(줄들) == 1 and 온전


def test_앞_파일부터_시각_차례로_읽는다(기록):
    _쓰기(기록.old_path, _거래(_때(17, 10), run="앞"))
    _쓰기(기록.path, _거래(_때(18, 10), run="뒤"))

    줄들, _ = 기록.trades()

    assert [one["runId"] for one in 줄들] == ["앞", "뒤"]


def test_체결과_이벤트_줄은_거래로_세지_않는다(기록):
    _쓰기(
        기록.path,
        {"kind": "fill", "runId": "r1", "orderId": "r1-1", "price": 1.0},
        {"kind": "event", "runId": "r1", "text": '"kind": "trade" 라는 글자가 든 이벤트'},
        _거래(_때(17, 10)),
    )

    줄들, _ = 기록.trades()

    assert len(줄들) == 1 and 줄들[0]["kind"] == "trade"


def test_읽는_사이에_교대가_나면_한_번_다시_읽는다(기록):
    """앞 파일을 읽은 뒤 교대가 나면 본 파일의 줄이 새 앞 파일로 옮겨 가 양쪽에서 빠집니다."""
    _쓰기(기록.old_path, _거래(_때(16, 10), run="처음"))
    _쓰기(기록.path, _거래(_때(17, 10), run="가운데"))
    원래 = 기록.read_bytes
    읽은수 = {"번": 0}

    def 교대를_끼운다(path):
        읽은수["번"] += 1
        data = 원래(path)
        if 읽은수["번"] == 1:
            기록.old_path.unlink()
            기록.path.rename(기록.old_path)
            _쓰기(기록.path, _거래(_때(18, 10), run="나중"))
        return data

    기록.read_bytes = 교대를_끼운다

    줄들, 온전 = 기록.trades()

    assert 온전
    assert [one["runId"] for one in 줄들] == ["가운데", "나중"]


def test_두_번_다_어긋나면_읽은_그대로_온전하지_않다고_답한다(기록):
    _쓰기(기록.path, _거래(_때(17, 10)))
    원래 = 기록.read_bytes
    횟수 = {"번": 0}

    def 늘_덧붙인다(path):
        data = 원래(path)
        if path == 기록.path:
            횟수["번"] += 1
            _쓰기(기록.path, _거래(_때(17, 11 + 횟수["번"])))
        return data

    기록.read_bytes = 늘_덧붙인다

    줄들, 온전 = 기록.trades()

    assert not 온전
    assert len(줄들) >= 1


def test_읽다_막히면_한_번_다시_읽는다(기록):
    _쓰기(기록.path, _거래(_때(17, 10)))
    원래 = 기록.read_bytes
    막힘 = {"남은": 1}

    def 한_번_막힌다(path):
        if path == 기록.path and 막힘["남은"]:
            막힘["남은"] -= 1
            raise PermissionError("교대 중")
        return 원래(path)

    기록.read_bytes = 한_번_막힌다

    줄들, 온전 = 기록.trades()

    assert 온전 and len(줄들) == 1


def test_파일이_안_바뀌면_다시_풀지_않는다(기록):
    _쓰기(기록.path, _거래(_때(17, 10)))
    기록.trades()
    앞 = 기록.parsed

    기록.trades()
    assert 기록.parsed == 앞, "같은 두 파일이면 풀지 않습니다."

    _쓰기(기록.path, _거래(_때(17, 11)))
    줄들, _ = 기록.trades()
    assert 기록.parsed > 앞 and len(줄들) == 2, "덧붙이면 다시 읽습니다."

    다음 = 기록.parsed
    기록.path.rename(기록.old_path)
    줄들, _ = 기록.trades()
    assert 기록.parsed > 다음 and len(줄들) == 2, "교대 뒤에도 다시 읽습니다."


def test_기록_줄에_전략_묶음을_싣는다(기록):
    run = runs.Run(id="r1", version_id="v1", code="A", session="domestic-day", market="domestic")
    run.group_id = "g1"

    기록.write(journal_lib.TRADE, run, {"closedAt": 1})
    기록.write(journal_lib.TRADE, runs.Run(id="r2", version_id="v2", code="A", session="s", market="domestic"), {})

    첫, 둘 = 기록.read()
    assert 첫["groupId"] == "g1"
    assert 둘["groupId"] == "", "모르면 빈 글자입니다 — 읽을 때 버전으로 찾습니다."


def test_칸이_없던_실행_파일도_전략_묶음은_빈_글자로_읽힌다(tmp_path):
    assert "group_id" in runs._SAVED and "strategy_id" not in runs._SAVED
    길 = tmp_path / "strategy-runs.json"
    옛 = {"version": 1, "runs": [{"id": "r1", "version_id": "v1", "code": "A", "session": "domestic-day", "market": "domestic", "state": "ended"}]}
    길.write_text(json.dumps(옛), encoding="utf-8")

    (읽은것,) = runs.RunStore(길).read()

    assert 읽은것.group_id == ""


def test_실행을_세울_때_전략_묶음을_찾아_적는다():
    assert service_lib._group_or_blank(lambda version_id: "g9", "v1") == "g9"
    assert service_lib._group_or_blank(lambda version_id: None, "v1") == ""

    def 터진다(version_id):
        raise OSError("못 읽음")

    assert service_lib._group_or_blank(터진다, "v1") == "", "실행을 세우는 일은 막지 않습니다."


# ── 집계 ────────────────────────────────────────────────


def test_겹친_줄은_하나로_세고_다른_거래는_뭉치지_않는다():
    한 = _거래(_때(17, 10))
    다른 = _거래(_때(17, 11))

    made = records.picked([한, dict(한), 다른], _조건())

    assert len(made) == 2
    assert records.trade_key(한) != records.trade_key(다른)


def test_야간_자정_전_청산은_다음_거래일이다():
    밤 = _거래(_때(28, 23, 30), session="domestic-night")

    assert records.trading_day(밤["closedAt"], "domestic-night") == date(2026, 9, 29)
    assert records.picked([밤], _조건(start=date(2026, 9, 29), end=date(2026, 9, 29))) == [밤]
    assert records.picked([밤], _조건(start=date(2026, 9, 28), end=date(2026, 9, 28))) == []


def test_기간은_양_끝을_포함한다():
    그날 = _거래(_때(17, 15, 30))

    assert records.picked([그날], _조건(start=date(2026, 9, 17), end=date(2026, 9, 17))) == [그날]


def test_시장과_기록_유형으로_가르고_섞지_않는다():
    줄들 = [
        _거래(_때(17, 10), record="paper"),
        _거래(_때(17, 11), record="sim"),
        _거래(_때(17, 12), market="overseas"),
    ]

    assert len(records.picked(줄들, _조건())) == 1
    assert len(records.picked(줄들, _조건(record="sim"))) == 1
    assert len(records.picked(줄들, _조건(market="overseas"))) == 1


def test_버전과_종목으로_거른다():
    줄들 = [_거래(_때(17, 10), version="v1"), _거래(_때(17, 11), version="v2", code="B")]

    assert len(records.picked(줄들, _조건(versions=frozenset({"v2"})))) == 1
    assert len(records.picked(줄들, _조건(code="B"))) == 1


def test_합과_곡선이_거래와_맞는다():
    줄들 = [
        _거래(_때(16, 10), net=300.0, fee=20.0),
        _거래(_때(16, 11), net=-120.0, fee=20.0),
        _거래(_때(18, 10), net=50.0, fee=10.0),
    ]

    made = records.dataset(줄들, _조건(), versions=[{"id": "v1", "groupId": "g1", "name": "추세", "version": "v3"}])

    (전략,) = made["strategies"]
    assert 전략["gross"] == pytest.approx(sum(one["grossPl"] for one in 줄들))
    assert 전략["fee"] == pytest.approx(sum(one["fee"] for one in 줄들))
    net = sum(one["netPl"] for one in 줄들)
    assert 전략["gross"] - 전략["fee"] == pytest.approx(net)
    assert made["dates"] == ["2026-09-16", "2026-09-18"]
    assert 전략["curve"] == [180.0, 230.0] and 전략["curve"][-1] == pytest.approx(net)
    assert made["curveBasis"] == records.CURVE_REALIZED == "realized"
    assert made["currency"] == "KRW" and made["kind"] == "앱 시뮬레이션"
    assert made["quality"] is None


def test_거래_줄은_화면이_찾는_열쇠와_히트맵_칸을_싣는다():
    made = records.dataset([_거래(_때(17, 10))], _조건(), versions=[{"id": "v1", "groupId": "g1"}])

    (거래,) = made["trades"]
    assert 거래["strategyId"] == made["strategies"][0]["id"] == "v1", "화면은 전략 줄을 버전 id 로 찾습니다."
    assert 거래["groupId"] == "g1"
    assert {"code", "openedAt", "market", "session", "at", "side", "qty", "net"} <= set(거래)
    assert 거래["at"] == "2026-09-17T10:00:00+09:00"


@pytest.mark.parametrize(
    ("줄의_묶음", "버전들", "이름", "묶음"),
    [
        ("g1", [], records.UNKNOWN_NAME, "g1"),  # 새 줄, 버전은 지워짐
        (None, [{"id": "v1", "groupId": "g7", "name": "추세", "version": "v2"}], "추세", "g7"),  # 옛 줄 + 버전 있음
        (None, [], records.UNKNOWN_NAME, None),  # 옛 줄 + 버전 없음
    ],
)
def test_전략_묶음은_줄에_없으면_버전으로_찾는다(줄의_묶음, 버전들, 이름, 묶음):
    made = records.dataset([_거래(_때(17, 10), strategy=줄의_묶음)], _조건(), versions=버전들)

    (전략,) = made["strategies"]
    assert (전략["name"], 전략["groupId"]) == (이름, 묶음)
    assert 전략["id"] == "v1"
    assert made["trades"][0]["groupId"] == 묶음


def test_빈_묶음_글자도_버전으로_찾는다():
    """되살린 실행은 묶음 칸이 빈 글자라 새로 쓰는 줄도 빌 수 있습니다."""
    made = records.dataset(
        [_거래(_때(17, 10), strategy="")], _조건(), versions=[{"id": "v1", "groupId": "g5"}]
    )

    assert made["strategies"][0]["groupId"] == "g5"


def test_상한을_넘으면_최근_것부터_남긴다():
    줄들 = [_거래(_때(17, 9) + at * 1000, run=f"r{at}") for at in range(records.MAX_TRADES + 1)]

    made = records.dataset(줄들, _조건())

    assert len(made["trades"]) == records.MAX_TRADES
    assert made["truncated"] is True
    assert made["earliestAt"] == made["trades"][0]["at"]
    assert made["trades"][0]["id"] == records.trade_key(줄들[1]), "가장 오래된 한 건이 빠집니다."


def test_상한과_같으면_자르지_않는다():
    줄들 = [_거래(_때(17, 9) + at * 1000, run=f"r{at}") for at in range(records.MAX_TRADES)]

    made = records.dataset(줄들, _조건())

    assert len(made["trades"]) == records.MAX_TRADES and made["truncated"] is False


def test_기록이_없으면_빈_장부다():
    made = records.dataset([], _조건())

    assert (made["dates"], made["strategies"], made["trades"]) == ([], [], [])
    assert made["earliestAt"] is None and made["truncated"] is False


# ── 목록의 최근 30일 ────────────────────────────────────


def _버전줄(**덮어쓰기) -> dict:
    made = {"id": "v1", "groupId": "g1", "market": "domestic", "record": "앱 시뮬레이션"}
    made.update(덮어쓰기)
    return made


def test_최근_30일은_오늘_포함_달력일이다():
    오늘 = date(2026, 9, 30)
    줄들 = [
        _거래(_때(31, 10, month=8), net=999.0),  # 30일 전 — 빠짐
        _거래(_때(1, 10), net=100.0),  # 29일 전 — 오늘까지 30일째라 듦
        _거래(_때(30, 10), net=-40.0),
    ]

    made = records.recent(줄들, _버전줄(), "paper", today=오늘)

    assert made == {"pl": 60.0, "winRate": 50.0, "trades": 2, "maxDrawdown": 40.0}


def test_목록_성과는_두_갈래를_따로_싣고_섞지_않는다():
    """한 버전에 앱 시뮬레이션과 모의 계좌 기록이 다 있으면 둘 다 서고 서로의 수에 들지 않습니다."""
    줄들 = [_거래(_때(29, 10), record="paper", net=10.0), _거래(_때(29, 11), record="sim", net=-5.0)]

    made = records.performance_of(줄들, _버전줄(), today=date(2026, 9, 30))

    assert made["performance"]["paper"]["trades"] == 1 and made["performance"]["paper"]["pl"] == 10.0
    assert made["performance"]["sim"]["trades"] == 1 and made["performance"]["sim"]["pl"] == -5.0


def test_한쪽_갈래만_있으면_다른_쪽은_없음이다():
    줄들 = [_거래(_때(29, 10), record="sim", net=10.0)]

    made = records.performance_of(줄들, _버전줄(), today=date(2026, 9, 30))

    assert made["performance"]["paper"] is None, "0 이 아니라 없음입니다."
    assert made["performance"]["sim"]["trades"] == 1


@pytest.mark.parametrize("유형", ["앱 시뮬레이션", "모의 계좌 거래"])
def test_평평한_칸_넷은_그_버전_기록_유형_갈래와_같다(유형):
    줄들 = [_거래(_때(29, 10), record="paper", net=10.0), _거래(_때(29, 11), record="sim", net=-5.0)]

    made = records.performance_of(줄들, _버전줄(record=유형), today=date(2026, 9, 30))

    갈래 = records.kind_of_label(유형)
    assert {이름: made[이름] for 이름 in records.NO_PERF} == made["performance"][갈래]


def test_기록_유형을_모르거나_거래가_없으면_평평한_칸은_없음이다():
    줄들 = [_거래(_때(29, 10), record="paper", net=10.0)]

    모름 = records.performance_of(줄들, _버전줄(record="없는 계좌 거래"), today=date(2026, 9, 30))
    빔 = records.performance_of([], _버전줄(), today=date(2026, 9, 30))

    assert {이름: 모름[이름] for 이름 in records.NO_PERF} == records.NO_PERF
    assert 빔 == {**records.NO_PERF, "performance": {"paper": None, "sim": None, "real": None}}


# ── 라우트 ──────────────────────────────────────────────


@pytest.fixture
def 손님(tmp_path, 기록):
    저장소 = StrategyStore(tmp_path / "strategies.json")
    실행목록 = service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"), journal=기록, fetch=lambda *args: []
    )
    app.dependency_overrides[get_store] = lambda: 저장소
    app.dependency_overrides[get_journal] = lambda: 기록
    app.dependency_overrides[get_service] = lambda: 실행목록
    try:
        yield TestClient(app), 기록
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("쿼리", "문장"),
    [
        ("record=paper", records.WHY_MARKET),
        ("record=paper&market=asia", records.WHY_MARKET),
        ("market=domestic", records.WHY_RECORD),
        ("record=live&market=domestic", records.WHY_RECORD),
        ("record=paper&market=domestic&from=2026/09/01", records.WHY_DATE),
        ("record=paper&market=domestic&to=2026-02-30", records.WHY_DATE),
        ("record=paper&market=domestic&from=2026-09-10&to=2026-09-01", records.WHY_RANGE),
    ],
)
def test_요청이_틀리면_400_과_문장_하나다(손님, 쿼리, 문장):
    앱, _ = 손님

    답 = 앱.get(f"/api/strategy/records?{쿼리}")

    assert 답.status_code == 400
    assert 답.json()["detail"] == {"message": 문장, "problems": []}


def test_기록_한_벌을_답한다(손님):
    앱, 기록 = 손님
    _쓰기(기록.path, _거래(_때(17, 10)), _거래(_때(17, 11), record="sim"))

    답 = 앱.get("/api/strategy/records?record=paper&market=domestic&from=2026-09-01&to=2026-09-20")

    assert 답.status_code == 200
    몸 = 답.json()
    assert len(몸["trades"]) == 1
    assert 몸["period"] == "2026-09-01 ~ 2026-09-20"
    assert 몸["openPlKnown"] is False, "지난 기간의 기간 말 평가손익은 모릅니다."
    assert 몸["incomplete"] is False


def test_기간이_오늘에_닿으면_평가손익을_안다(손님):
    from backend.sessions.hours import now_kst

    앱, _ = 손님
    오늘 = now_kst().date().isoformat()

    몸 = 앱.get(f"/api/strategy/records?record=paper&market=domestic&to={오늘}").json()

    assert 몸["openPlKnown"] is True and 몸["openPl"] == 0.0, "도는 실행이 없으면 0 입니다."


def test_목록_줄에_최근_30일_성과를_싣는다(손님, tmp_path):
    from backend.sessions.hours import now_kst

    앱, 기록 = 손님
    저장소 = app.dependency_overrides[get_store]()
    저장소.save({"id": "v1", "groupId": "g1", "market": "domestic", "record": "앱 시뮬레이션"}, None)
    저장소.save({"id": "v2", "groupId": "g2", "market": "domestic", "record": "앱 시뮬레이션"}, None)
    한시간전 = int(now_kst().timestamp() * 1000) - 3_600_000
    # 주간 맥락이라 거래일이 그 시각의 달력일입니다(야간이면 12시 뒤가 다음 날).
    _쓰기(기록.path, _거래(한시간전, net=70.0, session="domestic-day"))

    줄들 = {one["id"]: one for one in 앱.get("/api/strategy/versions").json()["versions"]}

    assert (줄들["v1"]["pl"], 줄들["v1"]["trades"], 줄들["v1"]["winRate"]) == (70.0, 1, 100.0)
    assert 줄들["v1"]["performance"]["paper"]["pl"] == 70.0
    assert 줄들["v1"]["performance"]["sim"] is None
    assert 줄들["v2"]["pl"] is None, "기록이 없는 버전은 비어 있습니다."


def test_두_번_다_어긋나면_답에_온전하지_않다는_표지가_선다(손님):
    앱, 기록 = 손님
    _쓰기(기록.path, _거래(_때(17, 10)))
    원래 = 기록.read_bytes

    def 늘_덧붙인다(path):
        data = 원래(path)
        if path == 기록.path:
            _쓰기(기록.path, {"kind": "event", "text": "쓰는 중"})
        return data

    기록.read_bytes = 늘_덧붙인다

    몸 = 앱.get("/api/strategy/records?record=paper&market=domestic&from=2026-09-01&to=2026-09-20").json()

    assert 몸["incomplete"] is True
    assert len(몸["trades"]) == 1, "읽은 것은 그대로 답합니다."


def test_쓰는_모양이_글자_거름을_지난다(기록):
    """거래 줄을 글자로 먼저 고르는 것은 `write` 가 쓰는 모양에 기댑니다 — 그 모양을 굳힙니다."""
    run = runs.Run(id="r1", version_id="v1", code="A", session="domestic-day", market="domestic")
    기록.write(journal_lib.TRADE, run, {"openedAt": 1, "closedAt": 2, "side": "buy", "quantity": 1})
    기록.write(journal_lib.FILL, run, {"orderId": "r1-1"})

    assert journal_lib._TRADE_MARK in 기록.path.read_bytes().splitlines()[0]
    줄들, 온전 = 기록.trades()
    assert 온전 and [one["closedAt"] for one in 줄들] == [2]


def test_묶음은_어디서나_groupId_이고_strategyId_는_버전_id_뿐이다(기록):
    """한 이름은 한 뜻입니다. 기록 줄·전략 줄·거래 줄 어디에도 묶음이 strategyId 로 나가지 않습니다."""
    run = runs.Run(id="r1", version_id="v1", code="A", session="domestic-day", market="domestic")
    run.group_id = "g1"
    기록.write(journal_lib.TRADE, run, {"openedAt": 1, "closedAt": _때(17, 10), "side": "buy", "quantity": 1})
    (줄,) = 기록.read()
    made = records.dataset([줄], _조건(), versions=[{"id": "v1", "groupId": "g1"}])

    assert "strategyId" not in 줄 and 줄["groupId"] == "g1"
    (전략,) = made["strategies"]
    assert "strategyId" not in 전략 and 전략["groupId"] == "g1"
    (거래,) = made["trades"]
    assert 거래["strategyId"] == "v1" and 거래["groupId"] == "g1"


# ── 거래일 잔고 줄·주문 결과 줄 ─────────────────────────


def _잔고(day: int, equity: float, *, run: str = "r1", version: str = "v1", late: bool = False, peak=None, month: int = 9) -> dict:
    return {
        "kind": "day",
        "runId": run,
        "versionId": version,
        "market": "domestic",
        "code": "A0166000",
        "session": "domestic-day",
        "record": "paper",
        "day": date(2026, month, day).isoformat(),
        "equity": equity,
        "marginPeak": peak,
        "late": late,
    }


def _주문(ended: int, outcome: str, *, order: str = "o1", run: str = "r1", record: str = "paper") -> dict:
    return {
        "kind": "order",
        "runId": run,
        "versionId": "v1",
        "market": "domestic",
        "code": "A0166000",
        "session": "domestic-day",
        "record": record,
        "orderId": order,
        "outcome": outcome,
        "endedAt": ended,
    }


def test_쓰는_모양이_잔고와_주문_줄_거름을_지난다(기록):
    run = runs.Run(id="r1", version_id="v1", code="A", session="domestic-day", market="domestic")
    기록.write(journal_lib.DAY, run, {"day": "2026-09-17", "equity": 1.0})
    기록.write(journal_lib.ORDER, run, {"orderId": "r1-1", "outcome": "filled", "endedAt": 1})
    기록.write(journal_lib.EVENT, run, {"text": '{"kind": "day" 라는 글자'})

    줄들, 온전 = 기록.rows()

    assert 온전
    assert [one["day"] for one in 줄들["day"]] == ["2026-09-17"]
    assert [one["orderId"] for one in 줄들["order"]] == ["r1-1"]
    assert 줄들["trade"] == []


def test_거래마다_잔고_줄이_있으면_평가_기준_곡선이다():
    거래들 = [_거래(_때(16, 10), net=100.0), _거래(_때(18, 10), net=-50.0)]
    잔고들 = [_잔고(15, 1000.0), _잔고(16, 1150.0), _잔고(17, 1180.0), _잔고(18, 1120.0)]

    made = records.dataset(거래들, _조건(start=date(2026, 9, 16), end=date(2026, 9, 18)), day_rows=잔고들)

    assert made["curveBasis"] == records.CURVE_EQUITY
    assert made["dates"] == ["2026-09-16", "2026-09-17", "2026-09-18"]
    assert made["strategies"][0]["curve"] == [150.0, 180.0, 120.0], "기간 앞 마지막 값(1000)을 뺍니다."


def test_잔고_줄이_없는_옛_기록은_실현_기준이다():
    made = records.dataset([_거래(_때(16, 10), net=100.0)], _조건())

    assert made["curveBasis"] == records.CURVE_REALIZED
    assert made["quality"] is None


def test_잔고_줄이_빠진_거래일이_하나라도_있으면_기간_전체가_실현_기준이다():
    거래들 = [_거래(_때(16, 10), net=100.0), _거래(_때(18, 10), net=-50.0)]
    잔고들 = [_잔고(16, 1150.0)]  # 18일 줄이 없음

    made = records.dataset(거래들, _조건(), day_rows=잔고들)

    assert made["curveBasis"] == records.CURVE_REALIZED
    assert made["strategies"][0]["curve"] == [100.0, 50.0]


def test_늦게_쓴_잔고_줄도_평가_곡선에_든다():
    made = records.dataset(
        [_거래(_때(16, 10), net=100.0)], _조건(), day_rows=[_잔고(16, 120.0, late=True)]
    )

    assert made["curveBasis"] == records.CURVE_EQUITY


def test_같은_실행_같은_날_잔고_줄이_둘이면_늦지_않은_줄을_쓴다():
    잔고들 = [_잔고(16, 999.0, late=True), _잔고(16, 120.0)]

    made = records.dataset([_거래(_때(16, 10), net=100.0)], _조건(), day_rows=잔고들)

    assert made["strategies"][0]["curve"] == [120.0]


def test_한_버전의_여러_실행은_더하고_쉰_날은_앞_값을_잇는다():
    잔고들 = [_잔고(16, 100.0, run="a"), _잔고(16, 10.0, run="b"), _잔고(17, 30.0, run="b")]

    made = records.dataset([], _조건(), day_rows=잔고들)

    assert made["curveBasis"] == records.CURVE_EQUITY
    assert made["strategies"][0]["curve"] == [110.0, 130.0]


def test_체결_품질은_분자와_분모를_함께_싣는다():
    끝 = _때(17, 11)
    주문들 = [
        _주문(끝, "filled", order="o1"),
        _주문(끝, "partial", order="o2"),
        _주문(끝, "cancelled", order="o3"),
        _주문(끝, "rejected", order="o4"),
        _주문(끝, "refused", order="o5"),
        _주문(끝, "filled", order="o1"),  # 겹친 줄
    ]
    잔고들 = [_잔고(17, 0.0, peak=0.25), _잔고(16, 0.0, peak=0.5, run="다른")]
    거래 = _거래(_때(17, 11), opened=_때(17, 10))

    made = records.dataset([거래], _조건(start=date(2026, 9, 17), end=date(2026, 9, 17)), day_rows=잔고들, order_rows=주문들)

    품질 = made["quality"]
    assert 품질["fillRate"] == "50.0% (2/4건)"
    assert 품질["rejectRate"] == "40.0% (2/5건)"
    assert 품질["marginPeak"] == "25.0%", "기간 밖(16일)의 최대는 들지 않습니다."
    assert 품질["holding"] == "1시간"
    assert 품질["counts"] == {
        "filled": 2,
        "ended": 4,
        "rejected": 2,
        "attempts": 5,
        "marginPeak": 0.25,
        "holdingMs": 3_600_000.0,
    }


def test_체결_품질은_기록_갈래를_섞지_않는다():
    끝 = _때(17, 11)
    made = records.dataset([], _조건(), order_rows=[_주문(끝, "filled", record="sim")])

    assert made["quality"] is None


def test_주문_줄은_끝난_시각의_거래일로_기간을_가른다():
    밤 = _주문(_때(28, 23, 30), "filled")
    밤["session"] = "domestic-night"

    안 = records.dataset([], _조건(start=date(2026, 9, 29), end=date(2026, 9, 29)), order_rows=[밤])
    밖 = records.dataset([], _조건(start=date(2026, 9, 28), end=date(2026, 9, 28)), order_rows=[밤])

    assert 안["quality"]["counts"]["ended"] == 1
    assert 밖["quality"] is None


def test_조회_라우트가_잔고와_주문_줄을_읽는다(손님):
    앱, 기록 = 손님
    _쓰기(
        기록.path,
        _거래(_때(16, 10), net=100.0),
        _잔고(16, 100.0),
        _주문(_때(16, 10), "filled"),
    )

    몸 = 앱.get("/api/strategy/records?record=paper&market=domestic&from=2026-09-16&to=2026-09-16").json()

    assert 몸["curveBasis"] == "equity"
    assert 몸["quality"]["counts"]["filled"] == 1


def test_가운데_빈_거래일은_실행의_직전_값을_잇는다():
    """day1·day3 에만 줄이 있는 실행의 day2 점은 day1 값입니다 — 0 으로 떨어지면 가짜 낙폭이 섭니다."""
    잔고들 = [_잔고(16, 100.0, run="a"), _잔고(18, 160.0, run="a"), _잔고(17, 5.0, run="b")]

    made = records.dataset([], _조건(), day_rows=잔고들)

    assert made["dates"] == ["2026-09-16", "2026-09-17", "2026-09-18"]
    assert made["strategies"][0]["curve"] == [100.0, 105.0, 165.0]
