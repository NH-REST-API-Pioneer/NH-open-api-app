"""사용자 홈에 파일을 남기고 읽는 자리."""
import json
import os

import pytest

from backend.storage import (
    BROKEN,
    MISSING,
    OK,
    ORIGIN,
    ReadState,
    from_other_app,
    keep_broken,
    read_json,
    write_json,
)


def test_없는_파일과_빈_내용을_가른다(tmp_path):
    """아직 안 쓴 것과 써 놓고 비운 것은 다르다."""
    없는것, status = read_json(tmp_path / "없다.json")
    assert (없는것, status) == ({}, MISSING)

    빈것 = tmp_path / "있다.json"
    write_json(빈것, {})
    assert read_json(빈것) == ({}, OK)


def test_쓴_것을_그대로_읽는다(tmp_path):
    경로 = tmp_path / "값.json"
    내용 = {"version": 1, "values": {"nh.home.watch": ["A7569000", "MESU26"]}}
    write_json(경로, 내용)
    assert read_json(경로) == (내용, OK)


def test_폴더가_없으면_만든다(tmp_path):
    경로 = tmp_path / "state" / "ui.json"
    write_json(경로, {"a": 1})
    assert 경로.is_file()


def test_깨진_파일은_옆에_남기고_비어_있는_것으로_답한다(tmp_path):
    경로 = tmp_path / "깨진것.json"
    경로.write_text("{이건 JSON 이 아니다", encoding="utf-8")

    내용, status = read_json(경로)

    assert (내용, status) == ({}, BROKEN)
    assert not 경로.is_file()
    남긴것 = tmp_path / "깨진것.json.broken"
    assert 남긴것.is_file()
    # 원본을 지우지 않고 옮겨만 둔다. 나중에 열어 볼 수 있어야 한다.
    assert 남긴것.read_text(encoding="utf-8") == "{이건 JSON 이 아니다"


def test_두_번_깨져도_먼저_남긴_것을_덮지_않는다(tmp_path):
    """처음 무엇 때문에 깨졌는지 볼 수 있어야 한다."""
    경로 = tmp_path / "값.json"

    경로.write_text("첫 번째로 깨진 것", encoding="utf-8")
    read_json(경로)
    경로.write_text("두 번째로 깨진 것", encoding="utf-8")
    read_json(경로)

    남긴것 = sorted(tmp_path.iterdir())
    assert len(남긴것) == 2
    assert {p.read_text(encoding="utf-8") for p in 남긴것} == {
        "첫 번째로 깨진 것",
        "두 번째로 깨진 것",
    }


def test_같은_초에_여러_번_깨져도_다_남는다(tmp_path):
    """시각만 붙이면 같은 초에 깨진 것끼리 서로를 덮는다."""
    경로 = tmp_path / "값.json"

    적은것 = {f"{회차}번째로 깨진 것" for 회차 in range(5)}
    for 내용 in 적은것:
        경로.write_text(내용, encoding="utf-8")
        read_json(경로)

    남긴것 = sorted(tmp_path.iterdir())
    assert len(남긴것) == 5
    assert {p.read_text(encoding="utf-8") for p in 남긴것} == 적은것


def test_사전이_아닌_JSON_도_깨진_것으로_본다(tmp_path):
    경로 = tmp_path / "목록.json"
    경로.write_text("[1, 2, 3]", encoding="utf-8")
    assert read_json(경로) == ({}, BROKEN)
    assert (tmp_path / "목록.json.broken").is_file()


def test_다시_쓰면_이전_파일을_덮는다(tmp_path):
    경로 = tmp_path / "값.json"
    write_json(경로, {"a": 1})
    write_json(경로, {"a": 2})
    assert read_json(경로)[0] == {"a": 2}
    # 임시 파일이 남지 않는다.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["값.json"]


def test_쓰다_실패하면_이전_파일이_남는다(tmp_path, monkeypatch):
    """반쪽 파일이 남으면 다음 실행에서 「깨진 파일」이 된다."""
    경로 = tmp_path / "값.json"
    write_json(경로, {"a": 1})

    def 실패(*args, **kwargs):
        raise OSError("디스크가 가득 찼다")

    monkeypatch.setattr(os, "replace", 실패)
    with pytest.raises(OSError):
        write_json(경로, {"a": 2})

    assert json.loads(경로.read_text(encoding="utf-8")) == {"a": 1}
    # 실패한 임시 파일도 치운다.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["값.json"]


def test_남길_수_없으면_그렇다고_답한다(tmp_path, monkeypatch):
    경로 = tmp_path / "값.json"
    경로.write_text("깨짐", encoding="utf-8")

    def 실패(*args, **kwargs):
        raise OSError("옮길 수 없다")

    monkeypatch.setattr(os, "replace", 실패)
    assert keep_broken(경로) is None


# ── 읽은 결과를 들고 있는 자리 ──────────────────────────


def test_읽을_때마다_상태에_적는다(tmp_path):
    경로 = tmp_path / "값.json"
    상태 = ReadState()

    read_json(경로, state=상태)
    assert 상태.payload == {"status": MISSING, "stored": False, "movedTo": None, "otherApp": None}

    write_json(경로, {"a": 1})
    read_json(경로, state=상태)
    assert 상태.payload == {"status": OK, "stored": True, "movedTo": None, "otherApp": None}


def test_깨진_사실은_다음_읽기로_덮이지_않는다(tmp_path):
    """치운 뒤의 읽기는 늘 「없음」이다. 덮이면 한 번 읽는 사이에 알림이 사라진다."""
    경로 = tmp_path / "값.json"
    경로.write_text("깨짐", encoding="utf-8")
    상태 = ReadState()

    read_json(경로, state=상태)
    깨진것 = 상태.payload
    read_json(경로, state=상태)

    assert 깨진것 == {
        "status": BROKEN,
        "stored": False,
        "movedTo": "값.json.broken",
        "otherApp": None,
    }
    assert 상태.payload == 깨진것

    상태.wrote()
    assert 상태.payload == {"status": OK, "stored": True, "movedTo": None, "otherApp": None}


def test_상태는_실제로_옮긴_이름을_든다(tmp_path):
    """두 번째로 깨진 것은 시각이 붙은 다른 이름으로 남는다 — 먼저 남긴 것을 덮지 않으려.

    **상태도 그때마다 따라가야 한다.** 첫 이름에 멈추면 사용자가 더 옛날
    자료가 든 파일을 열고 「내 것이 없다」고 한다 — 방금 잃은 것은 옆에 있는데.
    """
    경로 = tmp_path / "값.json"
    상태 = ReadState()

    이름들 = []
    for 내용 in ("첫 번째로 깨진 것", "두 번째로 깨진 것"):
        경로.write_text(내용, encoding="utf-8")
        read_json(경로, state=상태)
        이름 = 상태.payload["movedTo"]
        이름들.append(이름)
        assert (tmp_path / 이름).read_text(encoding="utf-8") == 내용

    assert 이름들[0] != 이름들[1], "같은 상태를 계속 써도 새로 깨진 자리를 든다."


def test_지운_경우에는_옮겼다고_안_한다(tmp_path):
    """담긴 것 자체가 인증 자료인 파일은 남기지 않고 지운다(`keep=False`)."""
    경로 = tmp_path / "토큰.json"
    경로.write_text("깨짐", encoding="utf-8")
    상태 = ReadState()

    read_json(경로, keep=False, state=상태)

    assert 상태.payload == {"status": BROKEN, "stored": False, "movedTo": None, "otherApp": None}
    assert not 경로.exists() and not (tmp_path / "토큰.json.broken").exists()
    assert "지웠습니다" in 상태.kept()


def test_못_옮겼으면_옮겼다고_하지_않는다(tmp_path, monkeypatch):
    경로 = tmp_path / "값.json"
    경로.write_text("깨짐", encoding="utf-8")
    상태 = ReadState()

    def 실패(*args, **kwargs):
        raise OSError("옮길 수 없다")

    monkeypatch.setattr(os, "replace", 실패)
    read_json(경로, state=상태)

    assert 상태.payload == {"status": BROKEN, "stored": False, "movedTo": None, "otherApp": None}
    assert 경로.is_file(), "못 옮겼으면 원래 자리에 그대로 있다."
    assert "그 자리에" in 상태.kept(), "기록에도 옮겼다고 적으면 안 된다."
    assert "지웠습니다" not in 상태.kept(), "지운 것과 못 옮긴 것은 다르다."


# ── 어느 앱이 쓴 파일인가 ───────────────────────────────


def test_다른_앱이_쓴_파일을_알아본다():
    """저장본으로 도는 앱과 실제 서버에 붙는 앱은 돌던 것을 나눠 담는다."""
    상태 = ReadState()
    상태.saw(OK)

    assert from_other_app({ORIGIN: "replay", "runs": []}, "live", state=상태) is True
    assert 상태.other_app == "replay"
    assert 상태.payload["stored"] is False, "읽었어도 안 쓴 것이다."
    assert 상태.payload["otherApp"] == "replay"


@pytest.mark.parametrize("담긴것", [{}, {ORIGIN: ""}, {ORIGIN: "live"}, {ORIGIN: " live "}, []])
def test_표지가_없거나_같으면_우리_것이다(담긴것):
    """앞 판이 담은 파일에는 이 칸이 없다 — 없다고 버리면 안 된다."""
    상태 = ReadState()

    assert from_other_app(담긴것, "live", state=상태) is False
    assert 상태.other_app == ""


def test_우리_파일을_다시_읽으면_알림이_풀린다(tmp_path):
    """저쪽 파일을 치우고 우리 것을 쓰면 알림도 함께 놓여야 한다."""
    경로 = tmp_path / "값.json"
    상태 = ReadState()
    from_other_app({ORIGIN: "replay"}, "live", state=상태)

    write_json(경로, {ORIGIN: "live"})
    담긴것, _ = read_json(경로, state=상태)

    assert 상태.other_app == ""
    assert from_other_app(담긴것, "live", state=상태) is False
    assert 상태.payload["otherApp"] is None
