"""시험 전체에 걸리는 준비.

**저장소에 안 올리는 기록 폴더(`tests/fixtures/nh_private/`)를 끄고 돕니다.**

그 폴더는 실전 계좌 응답이라 받아 둔 사람에게만 있습니다. 켜 둔 채로 돌면
그 사람의 시험 결과와 저장소를 갓 받은 사람의 결과가 달라지고, 「내 컴퓨터에선
되는데」가 생깁니다. 시험은 **저장소에 있는 것만으로** 판정되어야 합니다.

그 폴더를 함께 읽는 길 자체는 시험합니다 — 임시 폴더를 만들어 확인하므로
누구 컴퓨터에서나 같게 돕니다.

**상태 파일도 사용자 홈 밖으로 돌려 둡니다.** `~/NHFutures/state/` 의 다섯 —
전략 실행·거래 기록·손실 한도·전략 목록·화면 상태 — 은 앱이 쓰는 저장소 하나를
그대로 시험도 씁니다. 돌려 두지 않으면 시험 결과가 그때 그 폴더에 무엇이 담겨
있는지에 따라 갈립니다 — 사용자가 실행을 하나 세워 둔 날에만 떨어지는 시험이
실제로 있었습니다. 쓰는 쪽도 막습니다: 앱 싱글턴을 그대로 부르는 시험 하나가
사용자의 실행 목록이나 화면 배치를 덮어쓰지 않습니다.

**접속 토큰 파일도 사용자 홈 밖으로 돌려 둡니다.** 시험이 실서버 세션을
만들면 토큰 보관 자리가 `~/NHFutures/config/tokens.json` 을 가리킵니다.
가짜 서버에서 받은 토큰이 그 파일에 써지면, 시험을 돌린 사람의 진짜 설정
폴더에 쓸모없는 인증 자료가 남습니다. 시험마다 조심하는 규율에 기대지 않고
여기서 한 번에 돌려 둡니다.

**종목 마스터도 저장소 안의 조각으로 돕니다**(`실마스터`). 앞서는 사용자 홈에
내려받아 둔 실물을 읽고 없으면 건너뛰었는데, 그러면 시험의 변별력이 **어느 날
사본이냐**에 따라 달라지고 갓 받은 사람에게서는 아예 돌지 않습니다.
"""
from __future__ import annotations

import pytest

from backend.nh_api.fixtures import PRIVATE_DIR_FLAG


@pytest.fixture(autouse=True, scope="session")
def _저장소에_있는_것만으로_돈다():
    """`NH_REPLAY_PRIVATE_DIR` 을 빈 값으로 두어 로컬 전용 기록을 안 읽습니다."""
    import os

    앞서 = os.environ.get(PRIVATE_DIR_FLAG)
    os.environ[PRIVATE_DIR_FLAG] = ""
    try:
        yield
    finally:
        if 앞서 is None:
            os.environ.pop(PRIVATE_DIR_FLAG, None)
        else:
            os.environ[PRIVATE_DIR_FLAG] = 앞서


@pytest.fixture(autouse=True, scope="session")
def _토큰_파일은_임시_자리로(tmp_path_factory):
    """토큰 보관 자리를 임시 폴더로 돌립니다. 사용자 홈을 안 건드립니다."""
    from backend.auth import token_store

    자리 = tmp_path_factory.mktemp("tokens") / "tokens.json"
    바꾸기 = pytest.MonkeyPatch()
    바꾸기.setattr(token_store, "default_path", lambda: 자리)
    try:
        yield 자리
    finally:
        바꾸기.undo()


@pytest.fixture(autouse=True, scope="session")
def _상태_파일은_임시_자리로(tmp_path_factory):
    """`~/NHFutures/state/` 의 파일 여섯을 임시 폴더로 돌립니다.

    **경로만 돌립니다.** 앱이 쓰는 저장소 객체를 그대로 두고 자리만 바꾸므로,
    그것을 들고 있는 자리(`strategy_service.service` 같은 싱글턴)도 함께
    따라갑니다.

    **자리만 옮기는 것이라 메모리는 그대로입니다.** 싱글턴이 이미 세워 둔
    것(`RunService._engines` 같은)은 한 판 안에서 다음 시험까지 따라오므로,
    그것까지 끊어야 하는 자리는 제 목록을 따로 세웁니다(`test_environment_switch`).
    """
    from backend import deposit_history
    from backend.strategy import journal as journal_lib
    from backend.strategy import limits as limits_lib
    from backend.strategy import runs as runs_lib
    from backend.strategy import store as store_lib
    from backend.ui import ui_store

    자리 = tmp_path_factory.mktemp("app-state")
    바꾸기 = pytest.MonkeyPatch()
    for 담는것, 이름 in (
        (runs_lib.store, "strategy-runs.json"),
        (journal_lib.journal, "strategy-trades.jsonl"),
        (limits_lib.store, "strategy-limits.json"),
        (store_lib.store, "strategies.json"),
        # 날짜별 예수금입니다. 라우트가 답을 낼 때마다 여기 쌓이므로, 자리를
        # 안 돌리면 **시험이 사용자 홈에 값을 적습니다.**
        (deposit_history.store, "deposit-history.json"),
        # 화면 배치·관심종목입니다. 전략 것은 아니지만 같은 폴더이고, 라우트가
        # 이 싱글턴을 그대로 쓰므로 의존성 바꿔 끼우기를 잊은 시험 하나면
        # 사용자의 화면 배치를 덮어씁니다.
        (ui_store.store, "ui.json"),
    ):
        바꾸기.setattr(담는것, "path", 자리 / 이름)
    try:
        yield 자리
    finally:
        바꾸기.undo()


#: 고정본 마스터를 놓는 날짜 폴더. 마스터는 날짜 폴더에서 읽히므로 이름이 필요하고,
#: 조각을 잘라 온 판본의 날짜를 그대로 씁니다(`tests/fixtures/master/__init__.py`).
PINNED_MASTER_STAMP = "20260923"


@pytest.fixture(scope="module")
def 실마스터(tmp_path_factory):
    """저장소 안의 종목 마스터 조각으로 세운 색인.

    **읽는 자리는 앱이 쓰는 그 하나입니다**(`master_service.service`). 라우트를
    지나는 시험이 같은 색인을 봐야 하므로, 다른 객체를 만들어 건네지 않고 앱의
    것이 조각을 읽게 바탕 폴더를 돌립니다.

    **묶음마다 제 손으로 다시 읽습니다.** 「이미 읽혀 있으면 그대로 쓴다」로 두면
    앞서 어느 묶음이 돌았느냐에 따라 조각을 볼 때도 실물을 볼 때도 있습니다 —
    고치려던 것이 바로 그 갈림입니다. 조각이 여덟 줄이라 다시 읽는 값이 쌉니다.

    조각에 무엇이 들어 있고 어느 줄에서 왔는지는 `tests/fixtures/master/` 의
    설명에 있습니다. 조각에 있는 종목만 풀리고 나머지는 **마스터에 없는 종목**으로
    풀리는 것까지 실물과 같습니다 — 두 갈래가 다 시험에 쓰입니다.

    **끝난 뒤에도 읽어 둔 색인은 조각 그대로 남습니다.** 바탕 폴더만 되돌리고 다시
    읽지는 않습니다 — 되돌리자고 열여덟 만 줄을 파싱할 일이 아니고, 남는 것이
    조각이면 어느 기계에서나 같습니다. 실물이 필요한 자리는 제 손으로 실물을
    읽습니다(`test_strategy_store.py` 의 `배포마스터`).

    **읽을 때 「아홉 개 중 일곱 개를 읽지 못했습니다」 경고가 남습니다.** 조각을 둔
    마스터가 둘뿐이라 그렇고, 시험에서는 그것이 맞는 상태입니다. 빈 파일 일곱을
    만들어 경고를 없앨 수도 있지만, 그 경고는 **배포 배치가 바뀌었거나 받는 쪽이
    고장 난 것**을 알리는 자리라 조용히 만들지 않았습니다.
    """
    from backend.master import master_service
    from backend.master.master_files import MASTER_FILES
    from backend.master.master_store import save_master
    from tests.fixtures.master import pinned_path

    자리 = tmp_path_factory.mktemp("master")
    for 하나 in MASTER_FILES:
        조각 = pinned_path(하나.name)
        if 조각.is_file():
            save_master(하나, 조각.read_bytes(), stamp=PINNED_MASTER_STAMP, base_dir=자리)

    바꾸기 = pytest.MonkeyPatch()
    바꾸기.setattr(master_service.service, "_base_dir", 자리)
    master_service.service.reload()
    try:
        yield master_service.service
    finally:
        바꾸기.undo()


@pytest.fixture(autouse=True, scope="session")
def _전략은_시험에서_계좌로_못_나간다():
    """전략 엔진이 **실제 계좌로 부르는 길**을 시험 내내 막아 둡니다.

    엔진은 사람이 단추를 누르지 않아도 주문을 냅니다. 가짜 보내는 곳을 끼우는 것을
    잊은 시험 하나가 그 기계의 설정으로 실제 주문·취소·계좌 조회를 부르지 않게,
    규율이 아니라 **구조로** 막습니다.

    두 가지를 바꿉니다.

    - 호출부를 주지 않고 부른 국내·해외 거래 함수(`api=None`)가 **실서버 세션**을
      쓰려 하면 곧바로 실패합니다. 전략이 계좌로 부르는 자리(`sim.NhSender`·대사
      조회)가 이 길이고, 호출부 없이 부른 거래시간표 받기(`sessions.service`)도
      같습니다. 저장해 둔 응답으로 도는 세션(재생)은 서버에 닿지
      않으므로 그대로 둡니다 — 반입해 둔 기록으로 이 길을 지나 보는 시험이 있습니다.
    - 전략이 보는 「지금 활성 환경」은 **모름**입니다. 그 기계의 설정이 모의인지
      실전인지에 시험 결과가 기대지 않고, 모르는 환경에서는 계좌 갈래가 서지도
      나가지도 않습니다. 환경이 필요한 시험은 제 값을 끼워 줍니다.
    """
    from backend.domestic_futureoption import domestic_futureoption_functions as domestic_api
    from backend.overseas_futureoption import overseas_futureoption_functions as overseas_api
    from backend.sessions import service as session_service
    from backend.strategy import sim

    def 지킴(원래):
        def 호출부():
            made = 원래()
            if not made.session.is_replay:
                raise AssertionError("시험이 호출부 없이 실서버로 부르려 했습니다.")
            return made

        return 호출부

    바꾸기 = pytest.MonkeyPatch()
    바꾸기.setattr(domestic_api, "default_client", 지킴(domestic_api.default_client))
    바꾸기.setattr(overseas_api, "default_client", 지킴(overseas_api.default_client))
    # 거래시간표 받기는 호출부를 직접 정해 환경을 고르므로 그 자리도 같이 막습니다.
    바꾸기.setattr(session_service, "default_client", 지킴(session_service.default_client))
    바꾸기.setattr(sim, "environment_now", lambda: "")
    try:
        yield
    finally:
        바꾸기.undo()


@pytest.fixture(autouse=True)
def _주문_결과_확인은_시험에서_끈다(monkeypatch):
    """접수 뒤 결과 확인(`backend/order_outcome.py`)을 기본으로 끕니다.

    켜 두면 주문 라우트를 지나는 시험마다 주문내역·주문오류내역 조회가 덧붙고,
    정해 둔 시간만큼 실제로 기다립니다. 결과 확인 자체는 그것을 보는 시험이 제
    값을 끼워 켭니다(`tests/test_order_outcome.py`).
    """
    from backend import order_outcome

    monkeypatch.setattr(order_outcome, "WAITS", ())
    monkeypatch.setattr(order_outcome, "sleep", lambda _초: None)
