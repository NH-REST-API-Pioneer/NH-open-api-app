"""「확인 필요」에 선 실행을 끝내고 지우는 길.

계좌와 장부가 어긋나 「확인 필요」가 된 실행은, 어긋난 자리가 이 실행 밖의 것
(이 실행이 모르는 보유·주문)이면 「확인」을 눌러도 같은 답입니다. 이 실행의 장부에
보유도 열린 주문도 없으면 「실행 종료」로 끝내고, 끝난 뒤에는 실행과 그 버전을
지울 수 있어야 합니다. 남은 것이 있으면 막고 무엇이 남았는지 말합니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.** 계좌 조회와 주문 전송은 가짜를 끼웁니다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.strategy import paper, runs, service as service_lib
from backend.strategy.store import StrategyStore
from backend.strategy.strategy_routes import get_master, get_service, get_store
from tests.test_strategy_backtest import _버전
from tests.test_strategy_backtest import _마스터 as _백테스트마스터
from tests.test_strategy_service import (
    _계좌,
    _계좌보유,
    _더하기,
    _모의목록,
    _모의물음,
    _물음,
    _보내는곳,
)

주소 = "/api/strategy/runs"


def _어긋난_실행(tmp_path, *, sender=None):
    """계좌에 이 실행이 모르는 보유가 있어 시작하자마자 「확인 필요」인 실행."""
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]), sender=sender)
    assert 실행목록.add(**_모의물음())["state"] == runs.ATTENTION
    return 실행목록


def _말들(실행목록, run_id="run1"):
    return [one["text"] for one in 실행목록._engine(run_id).events]


# ── 서비스 ──────────────────────────────────────────────


def test_장부가_빈_확인_필요_실행은_끝난다(tmp_path):
    실행목록 = _어긋난_실행(tmp_path)

    줄 = 실행목록.end("run1", 9_000)

    assert 줄["state"] == runs.ENDED
    assert 실행목록._engine("run1").run.stopped_at == 9_000
    실행목록.delete("run1")
    assert 실행목록.rows() == []


def test_보유가_남은_확인_필요_실행은_못_끝내고_남은_것을_말한다(tmp_path):
    실행목록 = _어긋난_실행(tmp_path)
    실행목록._engine("run1").ledger.add(
        {"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1_000}
    )

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.end("run1", 9_000)

    assert str(잡힘.value) == f"{service_lib.WHY_ATTENTION_LEFT} 보유 매수 1계약"
    assert 실행목록._engine("run1").run.state == runs.ATTENTION


def test_미체결이_남은_확인_필요_실행은_못_끝내고_번호를_말한다(tmp_path):
    실행목록 = _어긋난_실행(tmp_path, sender=_보내는곳(order_no="0000012345"))
    실행목록._engine("run1").book.place(
        "o1", side=paper.BUY, quantity=1, order_type="지정가", price=1.0, at=1_000
    )

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.end("run1", 9_000)

    assert str(잡힘.value) == f"{service_lib.WHY_ATTENTION_LEFT} 미체결 주문 1건(0000012345)"
    assert 실행목록._engine("run1").run.state == runs.ATTENTION


def test_취소_확인_대기도_남은_것으로_말한다(tmp_path):
    """취소를 낸 주문은 아직 열려 있습니다 — 계좌는 취소를 받고 나중에 답합니다."""
    실행목록 = _모의목록(tmp_path, sender=_보내는곳(order_no="0000012345"))
    실행목록.add(**_모의물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.book.place(
        "o1", side=paper.BUY, quantity=1, order_type="지정가", price=1.0, at=1_000
    )
    돌리는것._purpose["o1"] = "entry"
    실행목록.pause("run1", 2_000)
    assert 돌리는것.book.pending == 1
    돌리는것.run.state = runs.ATTENTION

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.end("run1", 3_000)

    assert str(잡힘.value) == (
        f"{service_lib.WHY_ATTENTION_LEFT} 미체결 주문 1건(0000012345), "
        "그 가운데 취소 확인 대기 1건"
    )


def test_종이_실행의_주문은_앱이_붙인_id_로_말한다(tmp_path):
    """종이 주문에는 계좌 주문번호가 없습니다."""
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_물음())
    돌리는것 = 실행목록._engine("run1")
    돌리는것.book.place(
        "o1", side=paper.BUY, quantity=1, order_type="지정가", price=1.0, at=1_000
    )
    돌리는것.run.state = runs.ATTENTION

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.end("run1", 9_000)

    assert str(잡힘.value) == f"{service_lib.WHY_ATTENTION_LEFT} 미체결 주문 1건(o1)"


def test_확인해도_어긋나면_끝낼_수_있다는_줄을_남긴다(tmp_path):
    실행목록 = _어긋난_실행(tmp_path)

    줄 = 실행목록.acknowledge("run1", 9_000)

    assert 줄["state"] == runs.ATTENTION
    assert _말들(실행목록).count(service_lib.ACK_CAN_END) == 1


def test_보유가_남았으면_끝낼_수_있다는_줄을_안_남긴다(tmp_path):
    실행목록 = _어긋난_실행(tmp_path)
    실행목록._engine("run1").ledger.add(
        {"side": paper.BUY, "quantity": 1, "price": 100.0, "time": 1_000}
    )

    실행목록.acknowledge("run1", 9_000)

    assert service_lib.ACK_CAN_END not in _말들(실행목록)


def test_확인이_맞으면_그대로_중지로_푼다(tmp_path):
    """끝낼 길이 생겨도 「확인」의 뜻은 그대로입니다 — 맞으면 중지입니다."""
    계좌 = {"orders": [], "positions": [_계좌보유()]}
    실행목록 = _모의목록(tmp_path, account=lambda run: 계좌)
    assert 실행목록.add(**_모의물음())["state"] == runs.ATTENTION
    계좌["positions"] = []

    assert 실행목록.acknowledge("run1", 9_000)["state"] == runs.PAUSED
    assert service_lib.ACK_CAN_END not in _말들(실행목록)


def test_대사_중인_실행은_그대로_못_끝낸다(tmp_path):
    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_모의물음())
    실행목록._engine("run1").run.state = runs.RECONCILING

    with pytest.raises(service_lib.StrategyRunError) as 잡힘:
        실행목록.end("run1", 9_000)

    assert str(잡힘.value) == service_lib.WHY_QUIET


def test_전이표가_확인_필요에서_종료로_간다():
    assert runs.next_state(runs.ATTENTION, runs.END) == runs.ENDED
    assert runs.next_state(runs.RECONCILING, runs.ACKNOWLEDGE) == runs.RECONCILING


# ── 라우트 ──────────────────────────────────────────────


@pytest.fixture
def 손님(tmp_path):
    실행목록 = _모의목록(tmp_path, account=_계좌(positions=[_계좌보유()]))
    저장소 = StrategyStore(tmp_path / "strategies.json")
    app.dependency_overrides.update(
        {
            get_service: lambda: 실행목록,
            get_store: lambda: 저장소,
            get_master: _백테스트마스터,
        }
    )
    try:
        앱 = TestClient(app, raise_server_exceptions=False)
        담음 = 앱.put("/api/strategy/versions/v1", json={"version": _버전()})
        assert 담음.status_code == 200, 담음.text
        세움 = 앱.post(주소, json=_더하기(mode=runs.SIM, approved=True, environment="paper"))
        assert 세움.status_code == 200, 세움.text
        assert 세움.json()["state"] == runs.ATTENTION
        yield 앱, 실행목록, 저장소
    finally:
        app.dependency_overrides.clear()


def test_라우트만으로_확인_필요_실행을_끝내고_지운다(손님):
    """화면에서 누르는 차례 그대로입니다 — 확인은 그대로, 종료·삭제·버전 삭제가 지나갑니다."""
    앱, 실행목록, 저장소 = 손님

    확인 = 앱.post(f"{주소}/run1/acknowledge")
    assert 확인.status_code == 200 and 확인.json()["state"] == runs.ATTENTION
    # 끝나기 전에는 버전을 못 지웁니다.
    assert 앱.delete("/api/strategy/versions/v1").status_code == 409

    끝 = 앱.post(f"{주소}/run1/end")
    assert 끝.status_code == 200, 끝.text
    assert 끝.json()["state"] == runs.ENDED

    지움 = 앱.delete(f"{주소}/run1")
    assert 지움.status_code == 200, 지움.text
    assert 지움.json()["runs"] == []

    버전 = 앱.delete("/api/strategy/versions/v1")
    assert 버전.status_code == 200, 버전.text
    assert [row["id"] for row in 저장소.read()["versions"]] == []


def test_보유가_남은_확인_필요_실행의_종료는_400_이고_남은_것을_싣는다(손님):
    앱, 실행목록, _ = 손님
    실행목록._engine("run1").ledger.add(
        {"side": paper.SELL, "quantity": 2, "price": 100.0, "time": 1_000}
    )

    답 = 앱.post(f"{주소}/run1/end")

    assert 답.status_code == 400
    assert 답.json()["detail"] == {
        "message": f"{service_lib.WHY_ATTENTION_LEFT} 보유 매도 2계약",
        "problems": [],
    }
    assert 앱.delete(f"{주소}/run1").json()["detail"]["message"] == service_lib.WHY_NOT_ENDED
    assert 앱.delete("/api/strategy/versions/v1").status_code == 409
