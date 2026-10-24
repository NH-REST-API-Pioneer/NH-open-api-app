"""받아 둔 마스터를 날짜별로 두고 다시 읽는 자리.

실제 저장 위치는 사용자 홈(`~/NHFutures/master/`)이지만, **테스트는 임시 폴더만
씁니다.** 모든 함수가 폴더를 인자로 받도록 만든 이유가 이것입니다 — 테스트가 사용자
홈에 파일을 만들면 안 됩니다.
"""
from pathlib import Path

from backend.master.master_files import MASTER_FILES, MASTER_FILES_BY_NAME
from backend.master.master_store import (
    MASTER_DIR,
    date_dirs,
    find_master,
    has_all_files,
    load_all,
    load_master,
    prune_old_dates,
    save_master,
)
from tests.fixtures.master import fixture_text


def _put(base: Path, stamp: str, names) -> None:
    """조각 파일을 날짜 폴더에 마스터인 것처럼 놓습니다."""
    for name in names:
        save_master(
            MASTER_FILES_BY_NAME[name],
            fixture_text(name).encode("utf-8"),
            stamp=stamp,
            base_dir=base,
        )


def _all_names():
    return [m.name for m in MASTER_FILES]


def test_사용자_홈_아래에_둡니다():
    """저장소 안이 아니라 설정 파일과 같은 홈 폴더입니다."""
    assert MASTER_DIR == Path.home() / "NHFutures" / "master"


def test_날짜_폴더에_쓰고_다시_읽는다(tmp_path):
    _put(tmp_path, "20260902", ["fut_opt"])

    found = find_master(MASTER_FILES_BY_NAME["fut_opt"], tmp_path)

    assert found is not None
    path, stamp = found
    assert stamp == "20260902"
    assert path.name == "fut_opt.mst"

    loaded = load_master(MASTER_FILES_BY_NAME["fut_opt"], tmp_path)
    assert loaded.ok
    assert loaded.table is not None
    assert len(loaded.table) == 8


def test_오늘_것이_없으면_전날_것을_쓴다(tmp_path):
    """하나만 못 받았으면 그 파일만 옛것을 씁니다. 나머지는 오늘 것 그대로입니다."""
    _put(tmp_path, "20260901", ["fut_opt", "cme_fut"])
    _put(tmp_path, "20260902", ["cme_fut"])

    yesterday = find_master(MASTER_FILES_BY_NAME["fut_opt"], tmp_path)
    today = find_master(MASTER_FILES_BY_NAME["cme_fut"], tmp_path)

    assert yesterday is not None and yesterday[1] == "20260901"
    assert today is not None and today[1] == "20260902"


def test_하나도_없으면_없다고_답한다(tmp_path):
    loaded = load_master(MASTER_FILES_BY_NAME["fut_opt"], tmp_path)

    assert not loaded.ok
    assert loaded.table is None
    assert loaded.stamp is None


def test_아홉_개가_다_있어야_다_받은_것으로_본다(tmp_path):
    _put(tmp_path, "20260902", _all_names()[:-1])
    assert not has_all_files("20260902", tmp_path)

    _put(tmp_path, "20260902", _all_names())
    assert has_all_files("20260902", tmp_path)


def test_받기만_하는_파일은_파싱하지_않는다(tmp_path):
    """LME 는 화면에 없어서 받아 두기만 합니다. 파싱을 안 했다고 실패가 아닙니다."""
    _put(tmp_path, "20260902", ["lme_fut"])

    loaded = load_master(MASTER_FILES_BY_NAME["lme_fut"], tmp_path)

    assert loaded.ok
    assert loaded.table is None
    assert loaded.stamp == "20260902"


def test_깨진_파일은_그것만_실패로_두고_나머지는_쓴다(tmp_path, caplog):
    _put(tmp_path, "20260902", _all_names())
    (tmp_path / "20260902" / "cme_fut.mst").write_text("항목이;모자란;줄\n", encoding="utf-8")

    loaded = {item.master.name: item for item in load_all(tmp_path)}

    assert not loaded["cme_fut"].ok
    assert loaded["fut_opt"].ok
    assert loaded["fut_opt"].table is not None


def test_절반_넘게_실패하면_경고를_남긴다(tmp_path, caplog):
    """조용히 넘어가면 「종목이 몇 개 없네」로 보이고 아무도 알아채지 못합니다."""
    _put(tmp_path, "20260902", ["fut_opt"])

    with caplog.at_level("WARNING"):
        load_all(tmp_path)

    assert any("읽지 못했습니다" in message for message in caplog.messages)


def test_오래된_날짜_폴더를_지우고_최근_셋만_남긴다(tmp_path, caplog):
    for stamp in ("20260829", "20260830", "20260831", "20260901", "20260902"):
        _put(tmp_path, stamp, ["fut_opt"])

    with caplog.at_level("INFO"):
        removed = prune_old_dates(tmp_path)

    assert removed == ["20260830", "20260829"]
    assert [p.name for p in date_dirs(tmp_path)] == ["20260902", "20260901", "20260831"]
    # 사용자 홈에서 지우는 일이라 무엇을 지웠는지 남깁니다.
    assert any("20260830" in message for message in caplog.messages)


def test_지금_쓰는_사본이_든_폴더는_오래됐어도_안_지운다(tmp_path):
    """어떤 파일을 여러 날 못 받으면 그 파일의 마지막 사본이 옛 폴더에만 남습니다.

    날짜만 보고 지우면 그 종목들이 통째로 사라집니다 — 못 받은 파일일수록 옛 사본이
    필요하므로, 날짜 기준만으로 지우는 것은 앞뒤가 안 맞습니다.
    """
    _put(tmp_path, "20260820", ["cme_opt"])
    for stamp in ("20260830", "20260831", "20260901", "20260902"):
        _put(tmp_path, stamp, ["fut_opt"])

    removed = prune_old_dates(tmp_path)

    assert removed == ["20260830"]
    assert (tmp_path / "20260820" / "cme_opt.mst").is_file()
    found = find_master(MASTER_FILES_BY_NAME["cme_opt"], tmp_path)
    assert found is not None and found[1] == "20260820"


def test_날짜가_아닌_폴더는_건드리지_않는다(tmp_path):
    _put(tmp_path, "20260902", ["fut_opt"])
    (tmp_path / "사용자가_만든_폴더").mkdir()

    prune_old_dates(tmp_path, keep=0)

    assert (tmp_path / "사용자가_만든_폴더").is_dir()
