"""계좌 전체 손실 한도 — 파일과 라우트.

**사용자 홈을 건드리지 않습니다** — 임시 폴더를 쓰는 한도 파일을 따로 만들어 씁니다.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.nh_api import session
from backend.strategy import limits
from backend.strategy.strategy_routes import get_limits

주소 = "/api/strategy/limits"


@pytest.fixture
def 한도(tmp_path):
    return limits.LimitStore(tmp_path / "strategy-limits.json")


@pytest.fixture
def 손님(한도):
    app.dependency_overrides[get_limits] = lambda: 한도
    try:
        yield TestClient(app), 한도
    finally:
        app.dependency_overrides.pop(get_limits, None)


def test_처음에는_아무것도_안_걸려_있다(한도):
    """`null` 은 안 건 것입니다 — 0 이 아닙니다."""
    assert 한도.read() == {
        "KRW": {"dailyLoss": None},
        "USD": {"dailyLoss": None},
        "domestic": {"dailyLoss": None},
        "overseas": {"dailyLoss": None},
    }, "통화 칸과 앞 판의 두 이름(원·달러)을 함께 답합니다."
    assert not 한도.path.exists()


def test_담고_다시_읽는다(한도):
    한도.save({"domestic": {"dailyLoss": 1_000_000}, "overseas": {"dailyLoss": 500}})

    읽은것 = 한도.read()

    assert 읽은것["domestic"]["dailyLoss"] == 1_000_000.0
    assert 읽은것["overseas"]["dailyLoss"] == 500.0
    담긴것 = json.loads(한도.path.read_text(encoding="utf-8"))
    assert 담긴것["version"] == limits.VERSION


def test_안_보낸_시장은_안_건_것이_된다(한도):
    한도.save({"domestic": {"dailyLoss": 1_000_000}})

    assert 한도.read()["overseas"]["dailyLoss"] is None


def test_모르는_이름은_안_담는다(한도):
    한도.save({"domestic": {"dailyLoss": 100, "몰라요": 1}, "화성": {"dailyLoss": 5}})

    담긴것 = json.loads(한도.path.read_text(encoding="utf-8"))["limits"]
    assert set(담긴것) == {"KRW", "USD"}, "파일은 통화 칸으로 담습니다."
    assert set(담긴것["KRW"]) == {"dailyLoss"}


def test_파일이_깨져_있으면_안_건_것으로_읽는다(한도):
    한도.path.parent.mkdir(parents=True, exist_ok=True)
    한도.path.write_text("{ 깨진", encoding="utf-8")

    assert 한도.read() == limits.with_legacy(limits.blank())


@pytest.mark.parametrize("값", [0, -1, "글자"])
def test_0_이하나_수가_아니면_안_받는다(값):
    """0 은 「한 푼도 잃으면 안 된다」라 첫 수수료에 멈추게 됩니다."""
    찾은것 = limits.problems({"domestic": {"dailyLoss": 값}})

    assert [one["field"] for one in 찾은것] == ["domestic.dailyLoss"]
    assert 찾은것[0]["message"] == limits.WHY_LOSS


def test_비워_두는_것은_받는다():
    assert limits.problems({"domestic": {"dailyLoss": None}}) == []
    assert limits.problems({}) == []


def test_모르는_시장은_안_받는다():
    찾은것 = limits.problems({"화성": {"dailyLoss": 1}})

    assert [one["field"] for one in 찾은것] == ["화성"]
    assert 찾은것[0]["message"] == limits.WHY_MARKET


def test_판정이_바로_받는_모양으로_낸다():
    """안 건 시장은 빠집니다."""
    걸린것 = limits.daily_losses({"domestic": {"dailyLoss": 100}, "overseas": {"dailyLoss": None}})

    assert 걸린것 == {"KRW": 100.0}, "판정은 통화마다입니다."


# ── 라우트 ──────────────────────────────────────────────


def test_안_걸어_두었으면_비어_온다(손님):
    앱, _ = 손님

    답 = 앱.get(주소)

    assert 답.status_code == 200
    assert 답.json() == {
        "limits": limits.with_legacy(limits.blank()),
        "real": limits.with_legacy(limits.blank()),
        "store": {"status": "missing", "stored": False, "movedTo": None, "otherApp": None},
    }


def test_담고_읽는다(손님):
    앱, _ = 손님

    담기 = 앱.put(주소, json={"domestic": {"dailyLoss": 1_000_000}})

    assert 담기.status_code == 200
    assert 담기.json()["limits"]["domestic"]["dailyLoss"] == 1_000_000.0
    assert 앱.get(주소).json()["limits"]["overseas"]["dailyLoss"] is None


def test_못_받는_값은_전략_저장과_같은_규약이다(손님):
    """400 + `{message, problems}` — 화면이 한 갈래로 읽습니다."""
    앱, 한도 = 손님

    답 = 앱.put(주소, json={"domestic": {"dailyLoss": 0}})

    assert 답.status_code == 400
    속 = 답.json()["detail"]
    assert [one["field"] for one in 속["problems"]] == ["domestic.dailyLoss"]
    assert 속["problems"][0]["severity"] == "error"
    assert not 한도.path.exists(), "안 담습니다."


def test_파일은_한_번만_읽는다(한도, monkeypatch):
    """판정은 초마다 보는데 한도는 이 앱이 아니면 아무도 안 고치는 값입니다."""
    from backend.strategy import limits as limits_module

    한도.save({"domestic": {"dailyLoss": 100}})
    센것 = {"수": 0}
    원래 = limits_module.read_json

    def 세기(path):
        센것["수"] += 1
        return 원래(path)

    monkeypatch.setattr(limits_module, "read_json", 세기)

    for _ in range(5):
        한도.read()

    assert 센것["수"] == 0, "담을 때 읽어 둔 것을 씁니다."


def test_담으면_읽어_둔_값도_바뀐다(한도):
    한도.read()

    한도.save({"domestic": {"dailyLoss": 7}})

    assert 한도.read()["domestic"]["dailyLoss"] == 7.0


def test_읽어_둔_값을_고쳐도_안_새어_나간다(한도):
    """부르는 쪽이 받은 것을 고쳐도 담긴 값은 그대로여야 합니다."""
    한도.save({"domestic": {"dailyLoss": 100}})

    받은것 = 한도.read()
    받은것["domestic"]["dailyLoss"] = 999

    assert 한도.read()["domestic"]["dailyLoss"] == 100.0


# ── 파일이 통째로 안 읽힐 때 ─────────────────────────────


def test_한도_파일이_깨지면_기록에_남긴다(tmp_path, caplog):
    """**걸어 둔 한도가 말없이 풀립니다.**

    읽는 자리가 예외를 안 내고 옆으로 치운 뒤 빈 내용으로 답하므로, 기록이
    없으면 사용자는 한도를 걸어 두었다고 믿는데 아무것도 안 막습니다.
    """
    길 = tmp_path / "strategy-limits.json"
    limits.LimitStore(길).save({"domestic": {"dailyLoss": 300_000}})
    길.write_text('{"version": 1, "limits": {"domestic"', encoding="utf-8")

    with caplog.at_level("WARNING", logger="backend.strategy.limits"):
        읽은것 = limits.LimitStore(길).read()

    assert 읽은것 == limits.with_legacy(limits.blank()), "아무것도 안 건 것으로 답합니다."
    assert (tmp_path / "strategy-limits.json.broken").exists(), "옆에 남깁니다."
    (남긴것,) = [one for one in caplog.records if one.name == "backend.strategy.limits"]
    글 = 남긴것.getMessage()
    assert ".broken" in 글, "어디로 옮겼는지 말해야 합니다."
    assert "한도가 풀립니다" in 글, "영향을 적어야 합니다."


def test_한도_파일이_없으면_아무_말도_안_한다(tmp_path, caplog):
    """아직 안 건 것과 못 읽은 것은 다릅니다 — 처음 켠 사람에게 경고가 서면 안 됩니다."""
    with caplog.at_level("WARNING", logger="backend.strategy.limits"):
        읽은것 = limits.LimitStore(tmp_path / "없어요.json").read()

    assert 읽은것 == limits.with_legacy(limits.blank())
    assert [one for one in caplog.records if one.name == "backend.strategy.limits"] == []


def test_못_읽으면_다시_걸_때까지_그렇다고_답한다(손님):
    """한도는 **말없이 풀립니다** — 사용자는 걸어 두었다고 믿는데 아무것도 안 막습니다."""
    앱, 한도 = 손님
    한도.path.write_text('{"version": 1, "limits": {"domestic"', encoding="utf-8")

    첫번 = 앱.get(주소).json()
    assert 첫번["limits"] == limits.with_legacy(limits.blank()), "아무것도 안 건 것으로 답합니다."
    assert 첫번["store"] == {
        "status": "broken",
        "stored": False,
        "movedTo": "strategy-limits.json.broken",
        "otherApp": None,
    }
    assert 앱.get(주소).json()["store"] == 첫번["store"], "다음 요청에도 같은 말을 합니다."

    앱.put(주소, json={"domestic": {"dailyLoss": 1_000_000}})

    다시 = 앱.get(주소).json()
    assert 다시["store"] == {"status": "ok", "stored": True, "movedTo": None, "otherApp": None}
    assert 다시["limits"]["domestic"]["dailyLoss"] == 1_000_000.0


def test_다른_앱이_쓴_한도_파일은_안_쓴다(tmp_path, caplog):
    """저장본으로 도는 앱이 걸어 둔 한도로 실제 주문을 막거나 열면 안 됩니다."""
    길 = tmp_path / "strategy-limits.json"
    limits.LimitStore(길).save({"domestic": {"dailyLoss": 300_000}})
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    담긴것["origin"] = "replay" if session.current_mode() == "live" else "live"
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    저장소 = limits.LimitStore(길)
    with caplog.at_level("WARNING", logger="backend.strategy.limits"):
        읽은것 = 저장소.read()

    assert 읽은것 == limits.with_legacy(limits.blank()), "아무것도 안 건 것으로 답합니다."
    assert 저장소.state.payload["otherApp"] == 담긴것["origin"]
    assert "다시 걸어" in " ".join(one.getMessage() for one in caplog.records)


# ── 숫자가 아닌 숫자 ─────────────────────────────────────


@pytest.mark.parametrize("값", ["nan", "NaN", "inf", "-inf", "1e3", "0x10"])
def test_nan_inf_지수는_숫자가_아닌_것과_같이_거절한다(손님, 값):
    """`float()` 가 받아 주는 글자들입니다 — nan 은 「0 보다 큰가」를 빠져나갑니다."""
    앱, 한도 = 손님

    assert [one["message"] for one in limits.problems({"domestic": {"dailyLoss": 값}})] == [limits.WHY_LOSS]
    답 = 앱.put(주소, json={"domestic": {"dailyLoss": 값}})

    assert 답.status_code == 400
    assert not 한도.path.exists(), "안 담습니다."
    assert limits.daily_losses({"domestic": {"dailyLoss": 값}}) == {}


@pytest.mark.parametrize("값, 담긴것", [("1,000", 1000.0), ("1000.5", 1000.5)])
def test_보통_십진수는_그대로_받는다(손님, 값, 담긴것):
    앱, _ = 손님

    답 = 앱.put(주소, json={"domestic": {"dailyLoss": 값}})

    assert 답.status_code == 200
    assert 답.json()["limits"]["domestic"]["dailyLoss"] == 담긴것


def test_음수는_지금처럼_거절한다():
    assert [one["message"] for one in limits.problems({"domestic": {"dailyLoss": "-3"}})] == [limits.WHY_LOSS]


# ── 실전 계좌 한도는 따로 ────────────────────────────────────


def test_앞_판이_담은_한도는_모의_쪽이고_실전은_비어_시작한다(한도):
    한도.path.write_text(
        json.dumps({"version": 1, "limits": {"domestic": {"dailyLoss": 300000}}}),
        encoding="utf-8",
    )

    assert 한도.read()["domestic"]["dailyLoss"] == 300000
    assert 한도.read(limits.REAL) == limits.with_legacy(limits.blank())


def test_실전_한도를_담아도_모의_한도는_그대로다(한도):
    한도.save({"domestic": {"dailyLoss": 100}})
    한도.save({"domestic": {"dailyLoss": 500}}, limits.REAL)

    다시 = limits.LimitStore(한도.path)
    assert 다시.read()["domestic"]["dailyLoss"] == 100
    assert 다시.read(limits.REAL)["domestic"]["dailyLoss"] == 500


def test_실전_한도를_안_보내면_실전_한도는_그대로다(손님):
    앱, 한도 = 손님
    한도.save({"domestic": {"dailyLoss": 500}}, limits.REAL)

    답 = 앱.put(주소, json={"domestic": {"dailyLoss": 100}})

    assert 답.status_code == 200
    assert 답.json()["real"]["domestic"]["dailyLoss"] == 500, "PUT 답에도 실전 한도가 늘 실립니다."
    assert 앱.get(주소).json()["real"]["domestic"]["dailyLoss"] == 500
    # 파일 칸도 그대로입니다 — 새로 읽는 저장소로 봅니다.
    다시 = limits.LimitStore(한도.path)
    assert 다시.read(limits.REAL)["domestic"]["dailyLoss"] == 500
    assert 다시.read()["domestic"]["dailyLoss"] == 100


def test_실전_한도를_보내면_담고_답에_싣는다(손님):
    앱, 한도 = 손님
    한도.save({"domestic": {"dailyLoss": 100}})

    답 = 앱.put(
        주소,
        json={"domestic": {"dailyLoss": 100}, "real": {"domestic": {"dailyLoss": 700}}},
    )

    assert 답.status_code == 200
    assert 답.json()["real"]["domestic"]["dailyLoss"] == 700
    assert 답.json()["limits"]["domestic"]["dailyLoss"] == 100
    다시 = limits.LimitStore(한도.path)
    assert 다시.read(limits.REAL)["domestic"]["dailyLoss"] == 700
    assert 다시.read()["domestic"]["dailyLoss"] == 100


def test_실전_한도도_같은_규약으로_거른다(손님):
    앱, _ = 손님

    답 = 앱.put(주소, json={"real": {"domestic": {"dailyLoss": -1}}})

    assert 답.status_code == 400
    assert [one["field"] for one in 답.json()["detail"]["problems"]] == ["real.domestic.dailyLoss"]


def test_실행의_손실은_제_계좌_한도로만_센다():
    from backend.strategy import runs

    assert limits.environment_of(runs.Run(id="a", version_id="v", code="c", session="s", market="domestic", mode="real")) == limits.REAL
    for mode in ("sim", "paper"):
        assert limits.environment_of(runs.Run(id="a", version_id="v", code="c", session="s", market="domestic", mode=mode)) == limits.PAPER


def test_모의_시장을_하나도_안_보내면_모의_한도는_그대로다(손님):
    """실전 한도만 고치는 요청이 모의 한도를 풀지 않습니다."""
    앱, 한도 = 손님
    한도.save({"domestic": {"dailyLoss": 100}, "overseas": {"dailyLoss": 50}})

    답 = 앱.put(주소, json={"real": {"domestic": {"dailyLoss": 700}}})

    assert 답.status_code == 200
    assert 답.json()["limits"]["domestic"]["dailyLoss"] == 100
    assert 답.json()["real"]["domestic"]["dailyLoss"] == 700
    다시 = limits.LimitStore(한도.path)
    assert 다시.read() == limits.with_legacy({"KRW": {"dailyLoss": 100}, "USD": {"dailyLoss": 50}})
    assert 다시.read(limits.REAL)["domestic"]["dailyLoss"] == 700


def test_모의_시장을_하나라도_보내면_안_보낸_시장은_안_건_것이다(손님):
    앱, 한도 = 손님
    한도.save({"domestic": {"dailyLoss": 100}, "overseas": {"dailyLoss": 50}})

    답 = 앱.put(주소, json={"domestic": {"dailyLoss": 200}})

    assert 답.status_code == 200
    assert 답.json()["limits"] == limits.with_legacy({"KRW": {"dailyLoss": 200}, "USD": {"dailyLoss": None}})
    assert limits.LimitStore(한도.path).read()["overseas"]["dailyLoss"] is None
