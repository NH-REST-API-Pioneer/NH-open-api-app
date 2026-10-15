"""화면이 기억해 두는 것을 담는 파일."""
import json
import threading

import pytest

from backend.storage import BROKEN, MISSING, OK
from backend.ui.ui_store import (
    DEVICE_KEYS,
    MAX_VALUE_BYTES,
    STORED_KEYS,
    UiStateError,
    UiStore,
)


@pytest.fixture
def store(tmp_path):
    """임시 폴더를 쓴다. 사용자 홈은 건드리지 않는다."""
    return UiStore(tmp_path / "state" / "ui.json")


def test_처음에는_아무것도_없다(store):
    읽은것 = store.read()
    assert 읽은것["stored"] is False
    assert 읽은것["status"] == MISSING
    assert 읽은것["values"] == {}


def test_담고_다시_읽는다(store):
    store.patch({"nh.home.watch": ["A7569000", "MESU26"]})

    읽은것 = store.read()
    assert 읽은것["stored"] is True
    assert 읽은것["status"] == OK
    assert 읽은것["values"] == {"nh.home.watch": ["A7569000", "MESU26"]}


def test_알림_설정을_담고_다시_읽는다(store):
    """여러 창이 같은 알림 설정을 보도록 파일에 담습니다. 값은 화면이 정한 객체 그대로입니다."""
    설정 = {"toast": True, "sound": False, "kinds": {"fill": {"toast": True, "sound": True}}, "simRuns": False}
    store.patch({"nh.alerts": 설정})

    assert UiStore(store.path).read()["values"]["nh.alerts"] == 설정


def test_보낸_항목만_바꾸고_나머지는_둔다(store):
    """한 화면이 제 항목만 고쳐도 다른 화면의 값이 지워지면 안 된다."""
    store.patch({"nh.home.watch": ["A7569000"]})
    store.patch({"nh.trade.split": {"count": 2}})

    값 = store.read()["values"]
    assert 값["nh.home.watch"] == ["A7569000"]
    assert 값["nh.trade.split"] == {"count": 2}


def test_같은_항목은_덮어쓴다(store):
    store.patch({"nh.home.watch": ["A7569000"]})
    store.patch({"nh.home.watch": []})
    assert store.read()["values"]["nh.home.watch"] == []


def test_담지_않는_항목은_거절한다(store):
    """이 기기에 남아야 하는 것이 파일로 새어 들어오면 안 된다."""
    for key in DEVICE_KEYS:
        with pytest.raises(UiStateError):
            store.patch({key: "무엇이든"})
    assert store.read()["values"] == {}


def test_모르는_이름도_거절한다(store):
    with pytest.raises(UiStateError):
        store.patch({"nh.무엇인가": 1})


def test_옮기는_항목과_남기는_항목이_겹치지_않는다():
    assert set(STORED_KEYS) & set(DEVICE_KEYS) == set()
    assert len(STORED_KEYS) == 6
    assert len(DEVICE_KEYS) == 7


def test_파일에_이미_있는_모르는_이름은_지우지_않는다(store, tmp_path):
    """새 판이 담아 둔 것을 옛 판이 열었다고 지워 버리면 안 된다."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"version": 1, "values": {"nh.다음판.항목": "값"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    store.patch({"nh.home.watch": ["A7569000"]})

    값 = store.read()["values"]
    assert 값["nh.다음판.항목"] == "값"
    assert 값["nh.home.watch"] == ["A7569000"]


def test_너무_큰_값은_거절한다(store):
    with pytest.raises(UiStateError):
        store.patch({"nh.trade.drawings": "가" * MAX_VALUE_BYTES})
    assert store.read()["values"] == {}


def test_담을_수_없는_값은_거절한다(store):
    with pytest.raises(UiStateError):
        store.patch({"nh.home.watch": {1, 2}})


def test_깨진_파일이면_비어_있는_것으로_시작한다(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{망가짐", encoding="utf-8")

    읽은것 = store.read()

    assert 읽은것["status"] == BROKEN
    # 파일이 있었지만 못 읽었으므로 「담겨 있다」가 아니다. 화면이 이관을 다시
    # 시도할 수 있어야 한다.
    assert 읽은것["stored"] is False
    assert 읽은것["values"] == {}
    assert store.path.with_name(store.path.name + ".broken").is_file()


def test_깨진_파일_뒤에도_다시_담을_수_있다(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{망가짐", encoding="utf-8")
    store.read()

    store.patch({"nh.home.watch": ["A7569000"]})
    assert store.read()["values"] == {"nh.home.watch": ["A7569000"]}


def test_담는_형식(store):
    store.patch({"nh.home.watch": []})
    적힌것 = json.loads(store.path.read_text(encoding="utf-8"))
    assert 적힌것["version"] == 1
    assert 적힌것["values"] == {"nh.home.watch": []}


def test_브라우저에_있던_값을_옮겨_받는다(store):
    결과 = store.import_missing({"nh.home.watch": ["A7569000"], "nh.trade.split": {"count": 2}})

    assert 결과["imported"] == ["nh.home.watch", "nh.trade.split"]
    assert store.read()["values"]["nh.home.watch"] == ["A7569000"]


def test_이미_담긴_항목은_덮지_않는다(store):
    """뒤늦게 옮기려는 요청이 그 뒤에 고친 값을 덮으면 안 된다."""
    store.patch({"nh.home.watch": ["새 값"]})

    결과 = store.import_missing({"nh.home.watch": ["옛 브라우저 값"]})

    assert 결과["imported"] == []
    assert store.read()["values"]["nh.home.watch"] == ["새 값"]


def test_비어_있는_항목만_채운다(store):
    """항목마다 따로 본다. 다른 항목이 담겨 있다고 이관이 막히면 안 된다."""
    store.patch({"nh.trade.split": {"count": 2}})

    결과 = store.import_missing(
        {"nh.home.watch": ["A7569000"], "nh.trade.split": {"count": 99}}
    )

    assert 결과["imported"] == ["nh.home.watch"]
    값 = store.read()["values"]
    assert 값["nh.home.watch"] == ["A7569000"]
    assert 값["nh.trade.split"] == {"count": 2}


def test_먼저_저장한_뒤에도_관심종목이_옮겨진다(store):
    """화면이 무엇을 먼저 저장하든 이관은 걸려야 한다.

    「파일이 있으면 아무것도 안 함」이면 차트 분할 하나만 먼저 바꿔도 브라우저에
    있던 관심종목이 영영 버려진다.
    """
    store.patch({"nh.trade.split": {"count": 2}})

    결과 = store.import_missing({"nh.home.watch": ["A7569000"]})

    assert 결과["imported"] == ["nh.home.watch"]
    assert store.read()["values"]["nh.home.watch"] == ["A7569000"]


def test_두_번_옮겨도_안전하다(store):
    store.import_missing({"nh.home.watch": ["A7569000"]})
    store.patch({"nh.home.watch": ["그 뒤에 고친 값"]})

    결과 = store.import_missing({"nh.home.watch": ["A7569000"]})

    assert 결과["imported"] == []
    assert store.read()["values"]["nh.home.watch"] == ["그 뒤에 고친 값"]


def test_깨진_파일이면_다시_옮길_수_있다(store):
    """못 읽은 것은 담긴 것이 아니므로 이관이 다시 걸린다."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{망가짐", encoding="utf-8")

    결과 = store.import_missing({"nh.home.watch": ["A7569000"]})

    assert 결과["imported"] == ["nh.home.watch"]
    assert store.read()["values"]["nh.home.watch"] == ["A7569000"]


def test_옮길_때도_담지_않는_항목은_거절한다(store):
    with pytest.raises(UiStateError):
        store.import_missing({"nh.theme": "dark"})
    assert store.read()["stored"] is False


def test_동시에_다른_항목을_담아도_둘_다_남는다(store):
    """요청은 여러 스레드에서 들어온다.

    읽고 합쳐 쓰는 세 걸음 사이에 다른 요청이 끼어들면 둘 다 같은 내용을 읽고
    각자 제 항목만 얹어 쓰기 때문에, 나중에 쓴 쪽이 앞선 쪽의 항목을 지운다.
    화면 하나가 배치와 그린 것을 동시에 보내는 것만으로도 일어난다.
    """
    사라진것 = []

    for 회차 in range(50):
        store.path.unlink(missing_ok=True)
        문 = threading.Barrier(2)

        def 담기(key, value=회차):
            문.wait()
            store.patch({key: {"회차": value}})

        스레드들 = [
            threading.Thread(target=담기, args=("nh.trade.layout",)),
            threading.Thread(target=담기, args=("nh.trade.drawings",)),
        ]
        for 하나 in 스레드들:
            하나.start()
        for 하나 in 스레드들:
            하나.join()

        남은것 = set(store.read()["values"])
        if 남은것 != {"nh.trade.layout", "nh.trade.drawings"}:
            사라진것.append((회차, sorted(남은것)))

    assert 사라진것 == []


def test_동시에_읽고_써도_오류가_나지_않는다(store):
    """Windows 에서는 다른 쪽이 읽는 중인 파일을 바꿔치기하지 못한다."""
    store.patch({"nh.home.watch": []})
    오류 = []

    def 쓰기():
        for 회차 in range(30):
            try:
                store.patch({"nh.home.watch": [str(회차)]})
            except OSError as exc:
                오류.append(exc)

    def 읽기():
        for _ in range(30):
            try:
                store.read()
            except OSError as exc:
                오류.append(exc)

    스레드들 = [threading.Thread(target=쓰기), threading.Thread(target=읽기)]
    for 하나 in 스레드들:
        하나.start()
    for 하나 in 스레드들:
        하나.join()

    assert 오류 == []


def test_빈_요청은_파일을_만들지_않는다(store):
    """바꿀 것이 없는 요청이 파일을 만들면 「아직 아무것도 안 담았다」가 거짓이 된다."""
    결과 = store.patch({})

    assert 결과["stored"] is False
    assert not store.path.is_file()

    # 그래서 그 뒤에도 이관이 걸린다.
    assert store.import_missing({"nh.home.watch": ["A7569000"]})["imported"] == ["nh.home.watch"]


def test_인증_정보는_담지_않는다(store):
    """APP Key 나 토큰은 config 폴더에만 둔다."""
    for key in ("app_key", "app_secret", "access_token", "nh.config.app_key"):
        with pytest.raises(UiStateError):
            store.patch({key: "값"})
