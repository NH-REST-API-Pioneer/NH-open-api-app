"""전략 저장과 저장 시 검사, 그리고 라우트.

**사용자 홈을 건드리지 않습니다** — 임시 폴더를 쓰는 저장소를 따로 만들어 씁니다.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import rules, validate
from backend.strategy.strategy_routes import get_master, get_store
from backend.strategy.store import MAX_VERSIONS, StrategyStore, StrategyStoreError

주소 = "/api/strategy/versions"


def _해외버전(id_: str = "v1", **덮어쓰기):
    """해외 버전 하나. 품목까지 해외 것으로 바꿉니다 — 국내 품목을 단 채
    시장만 해외로 두면 그 줄은 이제 저장되지 않습니다(시장 불일치)."""
    return _버전(id_, market="overseas", productCode="ES", **덮어쓰기)


def _버전(id_: str = "v1", **덮어쓰기):
    made = {
        "id": id_,
        "groupId": "g1",
        "name": "추세추종",
        "version": "v1",
        "market": "domestic",
        "productCode": "KOSPI",
        "productKind": "futures",
        "role": "kospi200",
        "instrumentFallback": "코스피200 선물",
        "status": "초안",
        "record": "앱 시뮬레이션",
        "tags": ["추세"],
        "summary": "EMA 교차",
        "account": "모의",
        "marginBudget": 10_000_000,
        "dailyLoss": 300_000,
        "orderQty": 1,
        "currency": "KRW",
        "seed": "trend",
    }
    made.update(덮어쓰기)
    return made


def _조건(left="close", op="gt", right="100", kind="number"):
    return {"id": "c1", "left": left, "op": op, "rightKind": kind, "right": right}


def _설정(**덮어쓰기):
    made = {
        "memo": "",
        "baseBar": "5분봉",
        "evalMode": "마감",
        "rules": {
            "buyEntry": {
                "on": True,
                "steps": [{"id": "s1", "join": "all", "withinBars": 0, "conds": [_조건()]}],
            },
            "sellEntry": {"on": False, "steps": []},
            "buyExit": {"on": False, "steps": []},
            "sellExit": {"on": False, "steps": []},
        },
        "aux": {
            "orderType": "지정가",
            "priceBasis": "신호가 + 1틱",
            "stopBasis": "",
            "fillCond": "FAS",
            "stopTicks": "10",
            "takeTicks": "20",
            "perOrder": "1",
            "maxHold": "3",
            "session": "국내 주간",
            "addWhileOpen": False,
            "dailyLoss": "300000",
            "marginBudget": "10000000",
        },
    }
    made.update(덮어쓰기)
    return made


def _자리별(설정, market="domestic") -> dict[str, dict[str, str]]:
    """문제를 칸 이름으로 찾아 쓰기 좋게."""
    return {one["field"]: one for one in validate.problems(설정, market=market)}


def _한줄(*conds: dict, join="all") -> list[dict]:
    """조건만 다른 한 단계짜리 규칙의 단계 목록."""
    return [{"id": "s1", "join": join, "withinBars": 0, "conds": list(conds)}]


@pytest.fixture
def 저장소(tmp_path):
    return StrategyStore(tmp_path / "strategies.json")


# ── 저장소 ──────────────────────────────────────────────


def test_처음에는_비어_있고_파일도_안_만든다(저장소):
    """「아직 아무것도 담지 않음」이 오류가 아닙니다."""
    assert 저장소.read() == {"versions": [], "drafts": {}}
    assert not 저장소.path.exists()


def test_담고_다시_읽는다(저장소):
    저장소.save(_버전(), _설정())

    made = 저장소.read()
    assert [one["id"] for one in made["versions"]] == ["v1"]
    assert made["drafts"]["v1"]["baseBar"] == "5분봉"
    # 사용자 홈이 아니라 준 자리에 씁니다.
    assert 저장소.path.exists()


def test_같은_id_는_자리를_지키며_바뀐다(저장소):
    """저장할 때마다 목록이 뒤섞이면 화면이 고른 줄을 잃습니다."""
    저장소.save(_버전("v1"), None)
    저장소.save(_버전("v2"), None)
    저장소.save(_버전("v1", name="고친 이름"), None)

    made = 저장소.read()
    assert [one["id"] for one in made["versions"]] == ["v1", "v2"]
    assert made["versions"][0]["name"] == "고친 이름"


def test_모르는_이름은_받지_않는다(저장소):
    """화면의 임시 값까지 받으면 무엇이 저장된 값인지 흐려집니다."""
    with pytest.raises(StrategyStoreError) as 터짐:
        저장소.save(_버전(전략="딴것"), None)
    assert "전략" in str(터짐.value)

    with pytest.raises(StrategyStoreError):
        저장소.save(_버전(), {**_설정(), "몰라요": 1})


def test_id_가_없으면_안_담는다(저장소):
    with pytest.raises(StrategyStoreError):
        저장소.save(_버전(id_="  "), None)


def test_지우면_설정도_함께_사라진다(저장소):
    저장소.save(_버전(), _설정())

    assert 저장소.delete("v1") is True
    assert 저장소.read() == {"versions": [], "drafts": {}}
    assert 저장소.delete("v1") is False, "없던 것을 지우면 거짓입니다."


def test_파일이_깨져_있으면_비어_있는_것으로_시작한다(저장소):
    """한 줄이 깨졌다고 화면이 안 뜨면 사용자가 되돌릴 방법이 없습니다."""
    저장소.path.parent.mkdir(parents=True, exist_ok=True)
    저장소.path.write_text("{ 깨진", encoding="utf-8")

    assert 저장소.read() == {"versions": [], "drafts": {}}
    # 깨진 것은 옆에 남습니다.
    assert 저장소.path.with_suffix(".json.broken").exists()


def test_너무_많이_담지_않는다(저장소):
    for at in range(MAX_VERSIONS):
        저장소.save(_버전(f"v{at}"), None)

    with pytest.raises(StrategyStoreError) as 터짐:
        저장소.save(_버전("하나 더"), None)
    assert str(MAX_VERSIONS) in str(터짐.value)


# ── 저장할 때 거르는 것 ───────────────────────────────────


def test_제대로_적은_설정에는_할_말이_없다():
    assert validate.problems(_설정(), market="domestic") == []
    assert validate.blocked([]) is False


def test_손절은_1틱_이상이라고_따로_말한다():
    """손절은 비워 둘 선택지가 아니라 적어야 하는 값입니다."""
    for 적은값 in ("", "0", "0.5"):
        설정 = _설정()
        설정["aux"]["stopTicks"] = 적은값

        하나 = _자리별(설정)["aux.stopTicks"]

        assert 하나["severity"] == validate.ERROR
        assert 하나["message"] == "손절은 1틱 이상으로 적습니다"


def test_정수로_적는_칸과_수로_적는_칸이_갈린다():
    설정 = _설정()
    설정["aux"]["takeTicks"] = "1.5"
    설정["aux"]["perOrder"] = ""
    설정["aux"]["dailyLoss"] = "숫자아님"
    설정["aux"]["marginBudget"] = "1500000.5"

    찾은것 = _자리별(설정)

    # 화면(`StrategySettings.tsx` 의 `numberWhy`)이 쓰는 말과 같아야 합니다.
    assert 찾은것["aux.takeTicks"]["message"] == "1 이상의 정수로 적습니다"
    assert 찾은것["aux.perOrder"]["message"] == "1 이상의 정수로 적습니다"
    assert 찾은것["aux.dailyLoss"]["message"] == "0보다 큰 수로 적습니다"
    assert "aux.marginBudget" not in 찾은것, "돈은 정수가 아니어도 됩니다."
    assert all(하나["severity"] == validate.ERROR for 하나 in 찾은것.values())


def test_주문당_수량보다_적게_들_수는_없다():
    설정 = _설정()
    설정["aux"]["perOrder"] = "5"
    설정["aux"]["maxHold"] = "3"

    하나 = _자리별(설정)["aux.maxHold"]

    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == "최대 보유는 주문당 수량 이상으로 적습니다"


def test_값을_받는_주문유형은_가격_기준이_있어야_한다():
    설정 = _설정()
    설정["aux"]["priceBasis"] = ""

    assert _자리별(설정)["aux.priceBasis"]["message"] == "주문 가격 기준을 고르세요"

    # 시장가·STOP-M 은 값을 안 받습니다 — 기준이 비어 있어도 됩니다.
    설정["aux"]["orderType"] = "시장가"
    assert "aux.priceBasis" not in _자리별(설정)


def test_켜_두고_조건이_없으면_알리되_막지는_않는다():
    """켜 두기만 하고 아직 안 적은 상태입니다 — 고치던 것을 잃지 않게 담습니다."""
    설정 = _설정()
    설정["rules"]["buyExit"] = {"on": True, "steps": []}

    찾은것 = validate.problems(설정, market="domestic")

    (하나,) = [one for one in 찾은것 if one["field"] == "rules.buyExit"]
    assert 하나["severity"] == validate.WARNING
    assert 하나["message"] == "조건이 없어 발동하지 않습니다"
    assert validate.blocked(찾은것) is False


def test_한_단계만_비어_있으면_담지_않는다():
    """빈 관문은 통과하지 못해 뒤 단계가 영영 안 열립니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = [
        {"id": "s1", "join": "all", "withinBars": 2, "conds": [_조건()]},
        {"id": "s2", "join": "all", "withinBars": 0, "conds": []},
    ]

    하나 = _자리별(설정)["rules.buyEntry.steps.1"]

    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == "조건이 없는 단계가 있습니다 — 조건을 넣거나 단계를 지우세요"


def test_안_채운_조건_줄을_센다():
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = [
        {
            "id": "s1",
            "join": "all",
            "withinBars": 0,
            "conds": [_조건(left=""), {**_조건(op=""), "id": "c2"}, {**_조건(), "id": "c3"}],
        }
    ]

    찾은것 = _자리별(설정)

    # 줄마다 하나씩 — 화면이 그 줄로 데려다 놓습니다.
    assert "rules.buyEntry.steps.0.conds.0" in 찾은것
    assert "rules.buyEntry.steps.0.conds.1" in 찾은것
    assert "rules.buyEntry.steps.0.conds.2" not in 찾은것, "다 고른 줄입니다."
    assert 찾은것["rules.buyEntry.steps.0.conds.0"]["message"] == "안 채운 조건 줄이 있습니다"


def test_몇_봉_안에가_비어_있으면_담지_않는다():
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = [
        {"id": "s1", "join": "all", "withinBars": 0, "conds": [_조건()]},
        {"id": "s2", "join": "all", "withinBars": 0, "conds": [_조건(op="lt")]},
    ]

    찾은것 = _자리별(설정)

    하나 = 찾은것["rules.buyEntry.steps.0.withinBars"]
    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == "다음 단계 유효기간은 1봉 이상으로 적습니다"
    assert "rules.buyEntry.steps.1.withinBars" not in 찾은것, "마지막 단계는 뜻이 없습니다."


def test_교차는_선을_두고_본다():
    """오른쪽은 선 다섯, 왼쪽은 거기에 가격 넷을 더합니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = _한줄(
        _조건(left="rsi14", op="crossUp", right="ema20", kind="operand")
    )
    assert _자리별(설정)["rules.buyEntry.steps.0.conds.0"]["message"] == (
        "교차는 가격이나 선이 선을 지날 때 씁니다"
    )

    # 오른쪽이 선이 아니어도 같은 말입니다 — 수를 지나는 것은 교차가 아닙니다.
    설정["rules"]["buyEntry"]["steps"] = _한줄(_조건(left="close", op="crossUp", right="100"))
    assert "rules.buyEntry.steps.0.conds.0" in _자리별(설정)

    # 가격이 선을 지나는 것은 됩니다.
    설정["rules"]["buyEntry"]["steps"] = _한줄(
        _조건(left="close", op="crossDown", right="bbLower", kind="operand")
    )
    assert _자리별(설정) == {}


def test_이전_1봉_값은_왼쪽에_못_선다():
    """무엇과 견주는 값인지가 사라집니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = _한줄(
        _조건(left="prevHigh", op="gt", right="close", kind="operand")
    )

    하나 = _자리별(설정)["rules.buyEntry.steps.0.conds.0"]
    assert 하나["message"] == "이전 1봉의 고가·저가는 오른쪽에만 놓습니다"

    설정["rules"]["buyEntry"]["steps"] = _한줄(
        _조건(left="close", op="gt", right="prevHigh", kind="operand")
    )
    assert _자리별(설정) == {}, "오른쪽 자리는 제자리입니다."


def test_같은_값끼리는_교차할_수_없다():
    """늘 거짓이라 규칙이 죽습니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = [
        {
            "id": "s1",
            "join": "all",
            "withinBars": 0,
            "conds": [_조건(left="ema20", op="crossUp", right="ema20", kind="operand")],
        }
    ]

    하나 = _자리별(설정)["rules.buyEntry.steps.0.conds.0"]

    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == "같은 값끼리는 교차할 수 없습니다"


def test_조건이_다섯을_넘으면_담지_않는다():
    설정 = _설정()
    설정["rules"]["buyEntry"]["steps"] = [
        {
            "id": "s1",
            "join": "all",
            "withinBars": 0,
            "conds": [{**_조건(), "id": f"c{at}"} for at in range(6)],
        }
    ]

    하나 = _자리별(설정)["rules.buyEntry"]

    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == "조건은 규칙마다 5개까지입니다"


@pytest.mark.parametrize(
    ("칸", "값", "문구"),
    [
        ("baseBar", "3분봉", "기준 봉을 고르세요"),
        ("orderType", "STOP-L", "주문유형을 고르세요"),
        ("priceBasis", "전일 종가", "주문 가격 기준을 고르세요"),
        ("stopBasis", "전일 종가", "스탑 가격 기준을 고르세요"),
        ("fillCond", "IOC", "체결조건을 고르세요"),
        ("session", "해외 CME", "세션을 고르세요"),
    ],
)
def test_고를_것이_정해진_칸은_목록_안이어야_한다(칸, 값, 문구):
    """화면이 드롭다운으로 막아도 저장 요청은 화면 밖에서도 옵니다."""
    설정 = _설정()
    자리 = 칸 if 칸 == "baseBar" else f"aux.{칸}"
    if 칸 == "baseBar":
        설정[칸] = 값
    else:
        설정["aux"][칸] = 값

    하나 = _자리별(설정)[자리]

    assert 하나["severity"] == validate.ERROR
    assert 하나["message"] == 문구


def test_시장을_모르면_시장마다_다른_칸은_건너뛴다():
    """어느 목록에 대고 재야 할지 고를 수 없습니다."""
    설정 = _설정()
    설정["aux"]["orderType"] = "STOP-L"
    설정["aux"]["session"] = "해외 CME"

    assert _자리별(설정, market="overseas") == {}
    assert _자리별(설정, market="") == {}
    assert set(_자리별(설정, market="domestic")) == {"aux.orderType", "aux.session"}


def test_비워_둘_수_있는_칸은_적었을_때만_본다():
    """스탑 가격 기준은 STOP 주문에만, 체결조건은 국내 주문에만 뜻이 있습니다."""
    설정 = _설정()
    설정["aux"]["stopBasis"] = ""
    설정["aux"]["fillCond"] = ""

    assert _자리별(설정) == {}

    # 값을 안 받는 주문유형이면 가격 기준도 비어 있을 수 있습니다.
    설정["aux"]["orderType"] = "시장가"
    설정["aux"]["priceBasis"] = ""
    assert _자리별(설정) == {}


def test_진입_규칙이_둘_다_꺼져_있으면_알리되_막지는_않는다():
    """시작할 때 막히는 설정이지, 적을 수 없는 값은 아닙니다."""
    설정 = _설정()
    설정["rules"]["buyEntry"]["on"] = False

    찾은것 = validate.problems(설정)

    (하나,) = 찾은것
    assert 하나["severity"] == validate.WARNING
    assert 하나["field"] == "rules", "어느 쪽을 켜도 풀리는 일이라 탭 하나에 달지 않습니다."
    assert 하나["message"] == "진입 규칙이 없어 이 전략은 주문을 내지 않습니다"
    assert validate.blocked(찾은것) is False


def test_담기_전에_조용히_맞추는_두_자리():
    설정 = _설정()
    설정["evalMode"] = "분마다"

    국내 = validate.normalized(_버전(), 설정)
    해외 = validate.normalized(_버전(market="overseas"), 설정)

    assert 국내["evalMode"] == "마감", "모르는 평가 방식은 마감으로 읽습니다."
    assert 국내["aux"]["fillCond"] == "FAS", "국내 체결조건은 그대로 둡니다."
    assert 해외["aux"]["fillCond"] == "", "해외 주문에는 체결조건이 없습니다."
    assert 설정["evalMode"] == "분마다", "준 것을 고치지 않습니다."


@pytest.mark.parametrize("평가", ["", None, "없음", "tick", "분마다"])
def test_평가_모드가_비었거나_모르는_값이면_마감으로_담는다(평가):
    """빈 값도, 칸이 없는 것도, 모르는 값도 봉 마감입니다."""
    설정 = _설정()
    if 평가 == "없음":
        del 설정["evalMode"]
    else:
        설정["evalMode"] = 평가

    made = validate.normalized(_버전(), 설정)

    assert made["evalMode"] == validate.EVAL_MODE == "마감"


@pytest.mark.parametrize("평가", ["마감", "틱"])
def test_평가_모드_둘은_그대로_담는다(평가):
    made = validate.normalized(_버전(), _설정(evalMode=평가))

    assert made["evalMode"] == 평가
    assert 평가 in validate.EVAL_MODES


# ── 라우트 ──────────────────────────────────────────────


class _마스터:
    """품목 넷만 실린 색인. **앱이 쓰는 그 하나를 안 씁니다** — 열여덟 만 줄을
    읽어 둔 시험이 먼저 돌았는지에 따라 답이 갈리면, 이 파일의 시험은 혼자
    돌 때와 다 같이 돌 때가 달라집니다.
    """

    def index(self):
        return {
            "products": [
                {"market": "domestic", "product_code": "KOSPI"},
                {"market": "domestic", "product_code": "USD"},
                {"market": "overseas", "product_code": "ES"},
                {"market": "overseas", "product_code": "CL"},
            ]
        }

    def product_of(self, market, code):
        found = {"A016C000": "KOSPI", "A7569000": "USD", "ESU26": "ES"}.get(code)
        return None if found is None else {"market": market, "product_code": found}


@pytest.fixture
def 손님(tmp_path):
    바꾼것 = StrategyStore(tmp_path / "strategies.json")
    app.dependency_overrides[get_store] = lambda: 바꾼것
    app.dependency_overrides[get_master] = _마스터
    try:
        yield TestClient(app), 바꾼것
    finally:
        app.dependency_overrides.pop(get_store, None)
        app.dependency_overrides.pop(get_master, None)


def test_아직_아무것도_없으면_빈_목록이다(손님):
    앱, _ = 손님

    답 = 앱.get(주소)

    assert 답.status_code == 200
    assert 답.json() == {
        "versions": [],
        "drafts": {},
        "legacyOperands": rules.legacy_table(),
        "store": {"status": "missing", "stored": False, "movedTo": None, "otherApp": None},
    }


def test_담고_읽고_지운다(손님):
    앱, _ = 손님

    담기 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": _설정()})
    assert 담기.status_code == 200
    assert 담기.json()["problems"] == []

    목록 = 앱.get(주소).json()
    assert 목록["versions"][0]["name"] == "추세추종"
    assert 목록["drafts"]["v1"]["aux"]["stopTicks"] == "10"

    지우기 = 앱.delete(f"{주소}/v1")
    assert 지우기.status_code == 200 and 지우기.json()["versions"] == []
    assert 앱.delete(f"{주소}/v1").status_code == 404


def test_틱으로_보낸_설정은_틱으로_담겨_돌아온다(손님):
    앱, 저장소 = 손님

    담기 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": _설정(evalMode="틱")})
    assert 담기.status_code == 200

    assert 앱.get(주소).json()["drafts"]["v1"]["evalMode"] == "틱"
    assert 저장소.read()["drafts"]["v1"]["evalMode"] == "틱", "파일에도 틱으로 담깁니다."


def test_모르는_평가_방식으로_보낸_설정은_마감으로_담긴다(손님):
    앱, 저장소 = 손님

    앱.put(f"{주소}/v1", json={"version": _버전(), "draft": _설정(evalMode="분마다")})

    assert 저장소.read()["drafts"]["v1"]["evalMode"] == "마감"


def test_적을_수_없는_값이_있으면_담지_않는다(손님):
    """배지만 달고 받으면 손절 「abc」가 저장된 값이 됩니다."""
    앱, 저장소 = 손님
    설정 = _설정()
    설정["aux"]["stopTicks"] = "0"

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정})

    assert 답.status_code == 400
    속 = 답.json()["detail"]
    assert [one["field"] for one in 속["problems"]] == ["aux.stopTicks"]
    assert 속["problems"][0]["severity"] == validate.ERROR
    assert 저장소.read()["versions"] == [], "아무것도 담지 않습니다."


def test_돌지_않는_설정은_담고_함께_알린다(손님):
    """고치던 것을 저장하지 못하면 사용자가 적어 둔 조건을 잃습니다."""
    앱, 저장소 = 손님
    설정 = _설정()
    설정["rules"]["buyEntry"]["on"] = False
    설정["rules"]["buyExit"] = {"on": True, "steps": []}

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정})

    assert 답.status_code == 200
    자리들 = {one["field"]: one["severity"] for one in 답.json()["problems"]}
    assert 자리들 == {"rules": validate.WARNING, "rules.buyExit": validate.WARNING}
    assert 저장소.read()["drafts"]["v1"]["rules"]["buyEntry"]["on"] is False, "담기는 담습니다."


def test_시장에_맞는_목록으로_잰다(손님):
    """국내 버전의 「조건부지정가·국내 주간」이 해외 버전에서는 틀린 값입니다."""
    앱, _ = 손님
    설정 = _설정()
    설정["aux"]["orderType"] = "조건부지정가"

    답 = 앱.put(
        f"{주소}/v1",
        json={"version": _해외버전(), "draft": 설정},
    )

    assert 답.status_code == 400
    자리들 = {one["field"] for one in 답.json()["detail"]["problems"]}
    assert 자리들 == {"aux.orderType", "aux.session"}


def test_담을_때_다듬어_넣는다(손님):
    앱, 저장소 = 손님
    설정 = _설정()
    설정["evalMode"] = "분마다"
    설정["aux"]["session"] = "해외 CME"

    앱.put(f"{주소}/v1", json={"version": _해외버전(), "draft": 설정})

    담긴것 = 저장소.read()["drafts"]["v1"]
    assert 담긴것["evalMode"] == "마감"
    assert 담긴것["aux"]["fillCond"] == ""


def test_주소와_본문의_전략이_다르면_안_받는다(손님):
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전("v2"), "draft": None})

    assert 답.status_code == 400
    assert "다릅니다" in 답.json()["detail"]["message"]
    assert [one["field"] for one in 답.json()["detail"]["problems"]] == ["id"]


def test_모르는_항목은_400_이다(손님):
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(몰라요=1), "draft": None})

    assert 답.status_code == 400
    assert "몰라요" in 답.json()["detail"]["message"]


def test_전략_라우트에는_주문을_내는_자리가_따로_없다(손님):
    """엔진은 사람이 단추를 누르지 않아도 주문을 냅니다."""
    앱, _ = 손님

    assert "paperOnly" not in 앱.get(주소).json()
    # **주문을 내는 라우트가 따로 없습니다.** 계좌로 나가는 주문은 실행 엔진이 내고,
    # 그 문들은 `runs.py` 첫머리에 있습니다.
    길들 = {길 for 길 in app.openapi()["paths"] if 길.startswith("/api/strategy")}
    assert 길들 == {
        주소,
        f"{주소}/{{version_id}}",
        "/api/strategy/runs",
        "/api/strategy/runs/{run_id}",
        "/api/strategy/runs/{run_id}/stop",
        "/api/strategy/runs/{run_id}/resume",
        "/api/strategy/runs/{run_id}/close",
        "/api/strategy/runs/{run_id}/end",
        "/api/strategy/runs/{run_id}/acknowledge",
        "/api/strategy/reconcile",
        "/api/strategy/stop-all",
        "/api/strategy/limits",
        # 기록을 읽기만 합니다(GET 하나).
        "/api/strategy/records",
        # 지난 봉으로 셈만 합니다(POST 하나, 아무것도 남기지 않음).
        "/api/strategy/backtest",
    }
    assert set(app.openapi()["paths"]["/api/strategy/records"]) == {"get"}
    assert set(app.openapi()["paths"]["/api/strategy/backtest"]) == {"post"}
    assert not [길 for 길 in 길들 if "order" in 길]


def test_담긴_파일은_사람이_읽을_수_있다(손님):
    앱, 저장소 = 손님
    앱.put(f"{주소}/v1", json={"version": _버전(), "draft": _설정()})

    담긴것 = json.loads(저장소.path.read_text(encoding="utf-8"))

    assert 담긴것["version"] == 1
    assert 담긴것["versions"][0]["id"] == "v1"
    assert "rules" in 담긴것["drafts"]["v1"]


def test_목록_줄의_한도는_설정에서_채운다(손님):
    """둘이 갈리면 어느 쪽이 그 전략의 한도인지 고를 수 없습니다."""
    앱, 저장소 = 손님
    설정 = _설정()
    설정["aux"]["marginBudget"] = "7000000"
    설정["aux"]["perOrder"] = "2"
    설정["aux"]["dailyLoss"] = "150000"

    앱.put(f"{주소}/v1", json={"version": _버전(marginBudget=1, orderQty=9, dailyLoss=1), "draft": 설정})

    담긴것 = 저장소.read()["versions"][0]
    assert (담긴것["marginBudget"], 담긴것["orderQty"], 담긴것["dailyLoss"]) == (7000000, 2, 150000)


def test_설정_없이_담는_줄은_한도를_그대로_둔다(손님):
    """채울 값이 없는데 비우면 이미 적혀 있던 한도가 사라집니다."""
    앱, 저장소 = 손님

    앱.put(f"{주소}/v1", json={"version": _버전(orderQty=9), "draft": None})

    assert 저장소.read()["versions"][0]["orderQty"] == 9


# ── 줄이 가리키는 종목 ───────────────────────────────────


def test_품목_칸이_담기고_목록에_실린다(손님):
    앱, 저장소 = 손님

    답 = 앱.put(
        f"{주소}/v1",
        json={"version": _버전(contractCode="A016C000"), "draft": _설정()},
    )

    assert 답.status_code == 200
    (줄,) = 답.json()["versions"]
    assert (줄["productCode"], 줄["productKind"], 줄["contractCode"]) == (
        "KOSPI",
        "futures",
        "A016C000",
    )
    assert 저장소.read()["versions"][0]["productCode"] == "KOSPI"


def test_월물은_고른_줄에만_붙는다(손님):
    """대개는 품목만 들고 다닙니다 — 코드는 그때그때 색인이 답합니다."""
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": _설정()})

    assert 답.status_code == 200
    assert "contractCode" not in 답.json()["versions"][0]


def test_품목이_비면_안_담는다(손님):
    앱, 저장소 = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(productCode=""), "draft": _설정()})

    assert 답.status_code == 400
    자리들 = {one["field"] for one in 답.json()["detail"]["problems"]}
    assert 자리들 == {"productCode"}
    assert 저장소.read()["versions"] == [], "막았으면 아무것도 안 담습니다."


def test_모르는_갈래는_안_담는다(손님):
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(productKind="선물"), "draft": _설정()})

    assert 답.status_code == 400
    assert {one["field"] for one in 답.json()["detail"]["problems"]} == {"productKind"}


def test_색인에_없는_품목은_안_담는다(손님):
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(productCode="없어요"), "draft": _설정()})

    assert 답.status_code == 400
    (짚은것,) = 답.json()["detail"]["problems"]
    assert 짚은것["field"] == "productCode"
    assert "찾지 못했습니다" in 짚은것["message"]


def test_시장이_안_맞으면_어느_시장인지_말한다(손님):
    """「없습니다」로만 답하면 사용자가 시장을 잘못 고른 것을 모릅니다."""
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(productCode="ES"), "draft": _설정()})

    assert 답.status_code == 400
    (짚은것,) = 답.json()["detail"]["problems"]
    assert 짚은것["message"] == validate._OTHER_MARKET.format(market="해외")
    assert 짚은것["field"] == "market", "고칠 칸은 시장입니다 — 품목은 있는 품목입니다."


def test_다른_품목의_월물은_안_담는다(손님):
    앱, _ = 손님

    답 = 앱.put(
        f"{주소}/v1",
        json={"version": _버전(contractCode="A7569000"), "draft": _설정()},
    )

    assert 답.status_code == 400
    (짚은것,) = 답.json()["detail"]["problems"]
    assert 짚은것["field"] == "contractCode"


def test_색인에_없는_월물은_짚는다(손님):
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(contractCode="없어요"), "draft": _설정()})

    assert 답.status_code == 400
    assert {one["field"] for one in 답.json()["detail"]["problems"]} == {"contractCode"}


def test_설정을_안_보낸_줄도_품목을_본다(손님):
    """목록에만 있는 줄이 가리키는 종목도 그 줄의 것입니다."""
    앱, _ = 손님

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(productCode=""), "draft": None})

    assert 답.status_code == 400
    assert {one["field"] for one in 답.json()["detail"]["problems"]} == {"productCode"}


def test_색인을_아직_못_받았으면_모양만_본다():
    """없는 것과 아닌 것은 다릅니다 — 모르는 동안 멀쩡한 품목을 틀렸다고 하면
    앱을 켜자마자 저장하는 사용자가 막힙니다."""
    줄 = {"market": "domestic", "productCode": "없어요", "productKind": "futures"}

    assert validate.instrument_problems(줄, master=None) == []
    assert validate.instrument_problems(줄, master=_빈마스터()) == []
    assert validate.instrument_problems({**줄, "productCode": ""}, master=_빈마스터())


class _빈마스터:
    def index(self):
        return None

    def product_of(self, market, code):
        return None


# ── 옛 줄의 역할 ────────────────────────────────────────


def test_옛_줄은_읽을_때_품목이_채워진다(tmp_path):
    """역할만 들고 있던 줄입니다. **파일은 그대로 둡니다.**"""
    길 = tmp_path / "strategies.json"
    길.write_text(
        json.dumps(
            {
                "version": 1,
                "versions": [{"id": "v1", "market": "domestic", "role": "kospiCall"}],
                "drafts": {},
            }
        ),
        encoding="utf-8",
    )
    저장소 = StrategyStore(길)

    (줄,) = 저장소.read()["versions"]

    assert (줄["productCode"], 줄["productKind"]) == ("KOSPI", "option")
    assert 줄["role"] == "kospiCall", "역할은 그대로 둡니다."
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    assert "productCode" not in 담긴것["versions"][0], "파일은 안 고칩니다."


def test_품목을_들고_있으면_역할로_안_덮는다(tmp_path):
    """고치는 중에 역할이 남은 줄입니다. 덮으면 방금 고른 품목이 사라집니다."""
    길 = tmp_path / "strategies.json"
    길.write_text(
        json.dumps(
            {
                "version": 1,
                "versions": [
                    {
                        "id": "v1",
                        "market": "domestic",
                        "role": "kospiFutures",
                        "productCode": "USD",
                        "productKind": "futures",
                    }
                ],
                "drafts": {},
            }
        ),
        encoding="utf-8",
    )

    (줄,) = StrategyStore(길).read()["versions"]

    assert 줄["productCode"] == "USD"


def test_모르는_역할은_그냥_둔다(tmp_path):
    길 = tmp_path / "strategies.json"
    길.write_text(
        json.dumps(
            {"version": 1, "versions": [{"id": "v1", "role": "몰라요"}], "drafts": {}}
        ),
        encoding="utf-8",
    )

    (줄,) = StrategyStore(길).read()["versions"]

    assert "productCode" not in 줄


def test_역할_표는_화면과_같은_여덟이다():
    """둘이 갈리면 같은 줄이 화면에서는 코스피, 백엔드에서는 코스닥이 됩니다."""
    from backend.strategy import instrument

    assert set(instrument.ROLE_INSTRUMENTS) == {
        "kospiFutures",
        "kospiCall",
        "usdFutures",
        "kosdaqFutures",
        "jpyFutures",
        "esFutures",
        "wtiFutures",
        "goldFutures",
    }
    assert all(
        one["productKind"] in instrument.KINDS for one in instrument.ROLE_INSTRUMENTS.values()
    )
    assert instrument.ROLE_INSTRUMENTS["kospiCall"]["productKind"] == instrument.OPTION, (
        "콜인지 풋인지는 품목이 아니라 월물이 가릅니다."
    )


def _옛파일(tmp_path):
    """역할만 들고 있는 옛 줄 하나가 담긴 파일."""
    길 = tmp_path / "strategies.json"
    길.write_text(
        json.dumps(
            {
                "version": 1,
                "versions": [{"id": "old", "role": "kospiCall"}],
                "drafts": {},
            }
        ),
        encoding="utf-8",
    )
    return 길


def test_다른_줄을_저장해도_옛_줄은_안_고친다(tmp_path):
    """**한 줄을 담는 일이 파일 전체를 고치면 안 됩니다.**

    담고 지우는 자리는 읽은 목록을 그대로 다시 씁니다. 읽는 자리에서 품목을
    채우면 손대지 않은 옛 줄까지 새 칸을 달고 파일에 적히고, 앞 판의 앱으로
    돌아갔을 때 그 줄들이 통째로 안 열립니다(`_only` 가 모르는 항목으로 막습니다).
    """
    길 = _옛파일(tmp_path)
    저장소 = StrategyStore(길)

    저장소.save(_버전("new"), None)

    담긴것 = json.loads(길.read_text(encoding="utf-8"))["versions"]
    (옛것,) = [one for one in 담긴것 if one["id"] == "old"]
    assert 옛것 == {"id": "old", "role": "kospiCall"}, "손댄 적 없는 줄입니다."


def test_줄을_지워도_옛_줄은_안_고친다(tmp_path):
    길 = _옛파일(tmp_path)
    저장소 = StrategyStore(길)
    저장소.save(_버전("new"), None)

    저장소.delete("new")

    담긴것 = json.loads(길.read_text(encoding="utf-8"))["versions"]
    assert 담긴것 == [{"id": "old", "role": "kospiCall"}]


def test_저장_답에는_품목이_채워져_나온다(tmp_path):
    """화면은 답을 그대로 목록에 씁니다 — 파일과 내보내는 모양은 다릅니다."""
    길 = _옛파일(tmp_path)

    답 = StrategyStore(길).save(_버전("new"), None)

    (옛것,) = [one for one in 답["versions"] if one["id"] == "old"]
    assert (옛것["productCode"], 옛것["productKind"]) == ("KOSPI", "option")


def test_역할만_보낸_줄도_담고_품목을_채운다(손님):
    """품목 칸이 생기기 전의 화면이 이 모양으로 보냅니다.

    막아 버리면 화면이 새 칸을 싣기 전까지 저장이 통째로 안 됩니다 — 고치던
    조건을 잃는 쪽이 품목 한 칸이 비는 것보다 나쁩니다.
    """
    앱, 저장소 = 손님
    줄 = _버전(role="usdFutures")
    줄.pop("productCode")
    줄.pop("productKind")

    답 = 앱.put(f"{주소}/v1", json={"version": 줄, "draft": _설정()})

    assert 답.status_code == 200
    담긴것 = 저장소.read()["versions"][0]
    assert (담긴것["productCode"], 담긴것["productKind"]) == ("USD", "futures")


def test_역할도_품목도_없으면_안_담는다(손님):
    앱, _ = 손님
    줄 = _버전(role="")
    줄.pop("productCode")
    줄.pop("productKind")

    답 = 앱.put(f"{주소}/v1", json={"version": 줄, "draft": _설정()})

    assert 답.status_code == 400
    assert {one["field"] for one in 답.json()["detail"]["problems"]} == {
        "productCode",
        "productKind",
    }


@pytest.fixture(scope="module")
def 배포마스터():
    """**내려받아 둔 실물** 종목 마스터. 저장소 안의 조각이 아닙니다.

    다른 자리는 `tests/conftest.py` 의 `실마스터`(저장소 안 조각)를 씁니다. 여기만
    실물인 것은, 아래 시험이 붙잡는 것이 **배포되는 마스터에 그 품목이 다 있는가**
    이기 때문입니다 — 조각은 우리가 고른 것이라, 조각으로 재면 표와 조각이 함께
    틀려도 맞다고 답합니다. 재는 대상이 곧 실물이라 조각으로 바꿀 수 없습니다.

    **아직 한 번도 안 받은 환경에서는 건너뜁니다** — 받아 둔 파일이 없는 것은
    이 시험이 잡으려는 일이 아니고, 그때 터지면 「마스터를 안 받았다」가
    「표가 마스터와 갈렸다」로 읽힙니다.

    **바탕 폴더를 실물 쪽으로 못박고 읽습니다.** 앱이 쓰는 그 하나를 조각 쪽으로
    돌려 둔 판에서도 여기서는 실물을 봐야 하므로, 먼저 읽은 쪽이 이기는 자리를
    두지 않습니다. 열여덟 만 줄을 파싱하는 일이라 이 묶음에서 한 번만 읽습니다.
    """
    from backend.master import master_service
    from backend.master.master_store import MASTER_DIR

    바꾸기 = pytest.MonkeyPatch()
    바꾸기.setattr(master_service.service, "_base_dir", MASTER_DIR)
    master_service.service.reload()
    try:
        if master_service.service.index() is None:
            pytest.skip("종목 마스터를 아직 받지 않았습니다.")
        yield master_service.service
    finally:
        바꾸기.undo()


def test_역할이_가리키는_품목이_실물_마스터에_다_있다(배포마스터):
    """표가 배포되는 마스터와 갈리면 옛 줄이 통째로 못 열립니다.

    **지어낸 색인으로는 이것을 못 봅니다** — 시험이 쓰는 품목코드를 표에서
    베껴 오면 둘이 함께 틀려도 맞다고 답합니다. 저장소 안 조각으로도 못 봅니다 —
    조각에 담은 품목만 들어 있어, 표에 있고 배포본에 없는 품목을 못 잡습니다.
    """
    from backend.strategy import instrument

    실린것 = {
        (str(one.get("market") or ""), str(one.get("product_code") or ""))
        for one in 배포마스터.index()["products"]
    }
    없는것 = [
        f"{one['market']} {one['productCode']}"
        for one in instrument.ROLE_INSTRUMENTS.values()
        if (one["market"], one["productCode"]) not in 실린것
    ]

    assert 없는것 == [], 없는것


# ── 파일이 통째로 안 읽힐 때 ─────────────────────────────


def test_전략_파일이_깨지면_기록에_남긴다(tmp_path, caplog):
    """**담아 둔 전략이 말없이 사라집니다.**

    읽는 자리가 예외를 안 내고 옆으로 치운 뒤 빈 내용으로 답합니다. 기록이
    없으면 사용자는 전략이 전부 없어진 것만 보고, 그다음 저장이 그 빈 상태를
    파일에 굳힙니다.
    """
    길 = tmp_path / "strategies.json"
    StrategyStore(길).save(_버전("v1"), None)
    길.write_text('{"version": 1, "versions": [{"id"', encoding="utf-8")

    with caplog.at_level("WARNING", logger="backend.strategy.store"):
        읽은것 = StrategyStore(길).read()

    assert 읽은것 == {"versions": [], "drafts": {}}
    assert (tmp_path / "strategies.json.broken").exists(), "옆에 남깁니다."
    (남긴것,) = [one for one in caplog.records if one.name == "backend.strategy.store"]
    글 = 남긴것.getMessage()
    assert ".broken" in 글, "어디로 옮겼는지 말해야 합니다."
    assert "목록에 서지 않습니다" in 글, "영향을 적어야 합니다."


def test_전략_파일이_없으면_아무_말도_안_한다(tmp_path, caplog):
    """아직 안 담은 것과 못 읽은 것은 다릅니다 — 처음 켠 사람에게 경고가 서면 안 됩니다."""
    with caplog.at_level("WARNING", logger="backend.strategy.store"):
        읽은것 = StrategyStore(tmp_path / "없어요.json").read()

    assert 읽은것 == {"versions": [], "drafts": {}}
    assert [one for one in caplog.records if one.name == "backend.strategy.store"] == []


def test_못_읽으면_다시_담을_때까지_그렇다고_답한다(손님):
    """화면이 「못 읽었습니다」를 말하려면 답에 실려야 합니다 — 기록은 사용자가 못 봅니다.

    답이 다음 요청에 「없음」으로 돌아가도 안 됩니다. 깨진 파일은 읽는 순간
    옆으로 치워져 그다음 읽기가 늘 「없음」이라, 한 박자만 늦게 물어도 아무
    말도 못 듣게 됩니다.
    """
    앱, 바꾼것 = 손님
    바꾼것.path.write_text('{"version": 1, "versions": [{"id"', encoding="utf-8")

    첫번 = 앱.get(주소).json()
    assert 첫번["versions"] == [], "담아 둔 전략이 목록에 서지 않습니다."
    assert 첫번["store"] == {
        "status": "broken",
        "stored": False,
        "movedTo": "strategies.json.broken",
        "otherApp": None,
    }
    assert 앱.get(주소).json()["store"] == 첫번["store"], "다음 요청에도 같은 말을 합니다."

    담기 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": _설정()})

    assert 담기.status_code == 200
    assert 앱.get(주소).json()["store"] == {
        "status": "ok",
        "stored": True,
        "movedTo": None,
        "otherApp": None,
    }


# ── 방향별 가격 기준·추적 청산·연속 손실·시간 초과 초기화 ──


def _방향별(price="", buy=None, sell=None, order="지정가"):
    설정 = _설정()
    aux = dict(설정["aux"], orderType=order, priceBasis=price)
    if buy is not None:
        aux["buyPriceBasis"] = buy
    if sell is not None:
        aux["sellPriceBasis"] = sell
    설정["aux"] = aux
    return _자리별(설정)


_기준칸 = {"aux.priceBasis", "aux.buyPriceBasis", "aux.sellPriceBasis"}


def test_방향별_기준을_둘_다_적으면_공용_칸은_비어도_된다():
    assert not _기준칸 & set(_방향별(buy="신호가 + 1틱", sell="신호가"))


def test_방향별_기준을_하나만_적으면_빈_쪽이_공용_칸을_쓴다():
    """공용 칸도 비었으면 빈 방향 칸에 오류를 답니다."""
    found = _방향별(buy="신호가 + 1틱")

    assert _기준칸 & set(found) == {"aux.sellPriceBasis"}
    assert found["aux.sellPriceBasis"]["severity"] == "error"
    assert found["aux.sellPriceBasis"]["message"] == "매도 주문 가격 기준을 고르세요"
    assert not _기준칸 & set(_방향별(price="신호가", buy="신호가 + 1틱"))


def test_방향별_기준이_없으면_옛_검사_그대로다():
    found = _방향별()

    assert _기준칸 & set(found) == {"aux.priceBasis"}
    assert found["aux.priceBasis"]["message"] == "주문 가격 기준을 고르세요"
    assert not _기준칸 & set(_방향별(price="신호가"))


def test_모르는_방향별_기준은_오류다():
    """시장가라 값이 안 쓰여도, 적었다면 아는 값이어야 합니다."""
    found = _방향별(price="신호가", buy="신호가 + 2틱", order="시장가")

    assert _기준칸 & set(found) == {"aux.buyPriceBasis"}
    assert found["aux.buyPriceBasis"]["message"] == "매수 주문 가격 기준을 고르세요"


def test_공용_기준이_모르는_값이면_그_칸_하나에만_단다():
    """원인은 공용 칸 하나입니다. 빈 방향 칸에 같은 까닭을 또 달지 않습니다."""
    found = _방향별(price="신호가 + 2틱", buy="신호가")

    assert _기준칸 & set(found) == {"aux.priceBasis"}


@pytest.mark.parametrize("칸", ["trailTicks", "lossStreak"])
@pytest.mark.parametrize("값", ["-1", "1.5", "abc", "0"])
def test_추적_청산과_연속_손실은_1_이상의_정수다(칸, 값):
    설정 = _설정()
    설정["aux"] = dict(설정["aux"], **{칸: 값})

    found = _자리별(설정)

    assert found[f"aux.{칸}"]["severity"] == "error"
    assert found[f"aux.{칸}"]["message"] == "1 이상의 정수로 적습니다"


@pytest.mark.parametrize("칸", ["trailTicks", "lossStreak"])
def test_추적_청산과_연속_손실은_비워_둘_수_있다(칸):
    for 값 in ("", None, "3"):
        설정 = _설정()
        설정["aux"] = dict(설정["aux"], **{칸: 값})
        assert f"aux.{칸}" not in _자리별(설정), 값


def _두단계_설정(reset, *, steps=2):
    단계들 = [
        {"id": "s1", "join": "all", "withinBars": 3, "conds": [_조건()]},
        {"id": "s2", "join": "all", "withinBars": 0, "conds": [_조건(op="lt", right="90")]},
    ][:steps]
    설정 = _설정()
    설정["rules"] = dict(설정["rules"], buyEntry={"on": True, "steps": 단계들, "resetBars": reset})
    return _자리별(설정)


def test_시간_초과_초기화는_1_이상의_정수다():
    칸 = "rules.buyEntry.resetBars"
    for 값 in ("-2", "1.5", "abc", 0):
        found = _두단계_설정(값)
        assert found[칸]["severity"] == "error", 값
        assert found[칸]["message"] == "1 이상의 정수로 적습니다"
    for 값 in ("", None, 4, "4"):
        assert 칸 not in _두단계_설정(값), 값


def test_단계가_하나인_규칙의_시간_초과_초기화는_경고다():
    found = _두단계_설정(4, steps=1)["rules.buyEntry.resetBars"]

    assert found["severity"] == "warning"
    assert found["message"] == "단계가 하나뿐이라 처음으로 되돌리기가 쓰이지 않습니다"


def test_새_칸이_저장_왕복에서_살아남는다(저장소):
    """저장소는 설정의 최상위 칸만 거릅니다. 규칙과 보조 설정 안의 새 칸은 그대로 담깁니다."""
    설정 = _설정()
    설정["aux"] = dict(
        설정["aux"],
        buyPriceBasis="신호가 + 1틱",
        sellPriceBasis="신호가 − 1틱",
        trailTicks="4",
        lossStreak="3",
    )
    설정["rules"] = dict(설정["rules"], buyEntry=dict(설정["rules"]["buyEntry"], resetBars=5))
    저장소.save(_버전(), 설정)

    읽은것 = StrategyStore(저장소.path).read()["drafts"]["v1"]

    assert 읽은것["aux"]["buyPriceBasis"] == "신호가 + 1틱"
    assert 읽은것["aux"]["sellPriceBasis"] == "신호가 − 1틱"
    assert 읽은것["aux"]["trailTicks"] == "4"
    assert 읽은것["aux"]["lossStreak"] == "3"
    assert 읽은것["rules"]["buyEntry"]["resetBars"] == 5


# ── 호가·시간·포지션 값과 「같음」 ──────────────────────


_첫조건 = "rules.buyEntry.steps.0.conds.0"


def _한조건(cond: dict, *, bar: str = "5분봉") -> dict[str, dict[str, str]]:
    설정 = _설정(baseBar=bar)
    설정["rules"]["buyEntry"]["steps"] = _한줄(cond)
    return _자리별(설정)


def _문장(found: dict[str, dict[str, str]], field: str = _첫조건) -> str | None:
    one = found.get(field)
    return one["message"] if one else None


def test_새_값을_쓴_조건은_받는다():
    for cond in (
        _조건(left="clock", op="gte", right="09:30"),
        _조건(left="clock", op="eq", right="23:59"),
        _조건(left="barOrder", op="eq", right="1"),
        _조건(left="positionQty", op="eq", right="0"),
        _조건(left="openPl", op="lte", right="-50000"),
        _조건(left="bid1Qty", op="gt", right="ask1Qty", kind="operand"),
        _조건(left="ask1", op="gt", right="bid1", kind="operand"),
    ):
        assert _문장(_한조건(cond)) is None, cond


def test_시각은_HH_MM_으로만_적는다():
    for right in ("9:30", "24:00", "09:60", "0930", "930"):
        found = _한조건(_조건(left="clock", op="gte", right=right))
        assert _문장(found) == "시각은 HH:MM(00:00~23:59)으로 적습니다", right


def test_HH_MM_은_시각에만_쓴다():
    found = _한조건(_조건(left="close", op="gte", right="09:30"))

    assert _문장(found) == "HH:MM 은 시각에만 씁니다"


def test_일봉에서는_시각과_봉_순서를_쓸_수_없다():
    """칸은 그 조건의 왼쪽입니다."""
    for left, right in (("clock", "09:30"), ("barOrder", "3")):
        found = _한조건(_조건(left=left, op="gte", right=right), bar="일봉")
        assert _문장(found, f"{_첫조건}.left") == "일봉에서는 시각·봉 순서를 쓸 수 없습니다", left
    assert _문장(_한조건(_조건(left="positionQty", op="gt", right="0"), bar="일봉")) is None


def test_같음은_정수_값에만_쓴다():
    for left in ("close", "bid1", "ask1", "openPl", "ema20"):
        found = _한조건(_조건(left=left, op="eq", right="100"))
        assert _문장(found) == "같음은 정수 값(잔량·보유 수량·시각·봉 순서)에만 씁니다", left


def test_같음은_정수와_견준다():
    """0.1 + 0.2 처럼 끝자리가 남는 값도 막습니다."""
    for right in ("1.5", str(0.1 + 0.2)):
        found = _한조건(_조건(left="positionQty", op="eq", right=right))
        assert _문장(found) == "같음은 정수와 견줍니다", right


def test_호가는_호가끼리만_견준다():
    for left, right in (
        ("bid1", "close"),
        ("close", "ask1"),
        ("bid1", "bid1Qty"),
        ("positionQty", "barOrder"),
        ("clock", "close"),
        ("openPl", "close"),
    ):
        found = _한조건(_조건(left=left, op="gt", right=right, kind="operand"))
        assert _문장(found) == "호가는 호가끼리만 견줍니다 — 시간·보유는 수와 견줍니다", (left, right)


def test_교차에는_새_값을_쓸_수_없다():
    for left, right in (("bid1", "ema20"), ("close", "bid1")):
        found = _한조건(_조건(left=left, op="crossUp", right=right, kind="operand"))
        assert _문장(found) == "교차는 가격이나 선이 선을 지날 때 씁니다", (left, right)


# ── 숫자가 아닌 숫자 ─────────────────────────────────────


@pytest.mark.parametrize("값", ["nan", "NaN", "inf", "-inf", "1e3", "0x10"])
@pytest.mark.parametrize("칸", ["maxHold", "dailyLoss"])
def test_nan_inf_지수는_터지지_않고_문제_하나로_선다(칸, 값):
    """정수 칸의 nan·inf 가 예외로 터지면 저장이 문제 목록 대신 500 이 됩니다."""
    설정 = _설정()
    설정["aux"][칸] = 값

    찾은것 = _자리별(설정)

    assert f"aux.{칸}" in 찾은것
    assert 찾은것[f"aux.{칸}"]["severity"] == validate.ERROR


def test_nan_을_담으려_하면_문제_목록으로_거절한다(손님):
    앱, 저장소 = 손님
    설정 = _설정()
    설정["aux"]["maxHold"] = "inf"

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정})

    assert 답.status_code == 400
    assert "aux.maxHold" in [one["field"] for one in 답.json()["detail"]["problems"]]


@pytest.mark.parametrize("칸, 값", [("dailyLoss", "1,000"), ("dailyLoss", "1000.5"), ("maxHold", "3")])
def test_보통_십진수는_지금처럼_통과한다(칸, 값):
    설정 = _설정()
    설정["aux"][칸] = 값
    assert f"aux.{칸}" not in _자리별(설정)


def test_음수는_지금처럼_문제다():
    설정 = _설정()
    설정["aux"]["dailyLoss"] = "-3"
    assert "aux.dailyLoss" in _자리별(설정)


# ── 전략 주문에 쓰지 않는 주문유형 ───────────────────────
#
# 실행이 다루지 않는 유형(`paper.UNSUPPORTED_ORDER_TYPES`)은 담을 때 막습니다. 예전에
# 담아 둔 것은 그대로 열리고, 주문유형을 바꿔야 다시 담깁니다.


@pytest.mark.parametrize(
    ("유형", "문구"),
    [
        ("조건부지정가", "조건부지정가는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요"),
        ("최유리지정가", "최유리지정가는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요"),
    ],
)
def test_전략_주문에_쓰지_않는_주문유형은_담지_않는다(손님, 유형, 문구):
    앱, 저장소 = 손님
    설정 = _설정()
    설정["aux"]["orderType"] = 유형

    답 = 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정})

    assert 답.status_code == 400
    줄들 = [one for one in 답.json()["detail"]["problems"] if one["field"] == "aux.orderType"]
    assert 줄들 == [{"field": "aux.orderType", "severity": validate.ERROR, "message": 문구}]
    assert 저장소.read() == {"versions": [], "drafts": {}}, "담지 않습니다."


@pytest.mark.parametrize("유형", ["조건부지정가", "최유리지정가"])
def test_예전에_담아_둔_그_유형은_그대로_열리고_유형을_바꿔야_다시_담긴다(손님, 유형):
    앱, 저장소 = 손님
    설정 = _설정()
    설정["aux"]["orderType"] = 유형
    저장소.save(_버전(), 설정)  # 막기 전에 담아 둔 전략입니다.

    읽음 = 앱.get(주소)

    assert 읽음.status_code == 200
    assert 읽음.json()["drafts"]["v1"]["aux"]["orderType"] == 유형
    assert validate.normalized(_버전(), 설정)["aux"]["orderType"] == 유형, "읽을 때 값을 바꾸지 않습니다."

    설정["memo"] = "다른 칸만 고침"
    assert 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정}).status_code == 400
    설정["aux"]["orderType"] = "지정가"
    assert 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정}).status_code == 200


@pytest.mark.parametrize("유형", ["시장가", "지정가", "STOP-M", "STOP-L"])
def test_해외_주문유형은_그대로_담긴다(손님, 유형):
    앱, _ = 손님
    설정 = _설정()
    설정["aux"].update({"orderType": 유형, "session": "해외 CME", "fillCond": "", "stopBasis": "신호가"})

    답 = 앱.put(f"{주소}/v1", json={"version": _해외버전(), "draft": 설정})

    assert 답.status_code == 200, 답.text


@pytest.mark.parametrize("유형", ["지정가", "시장가"])
def test_국내_지정가_시장가는_그대로_담긴다(손님, 유형):
    앱, _ = 손님
    설정 = _설정()
    설정["aux"]["orderType"] = 유형

    assert 앱.put(f"{주소}/v1", json={"version": _버전(), "draft": 설정}).status_code == 200
