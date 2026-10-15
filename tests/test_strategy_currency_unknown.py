"""통화를 모르는 해외 실행은 계좌 손실 한도 합계에 넣지 않습니다.

세울 때 품목의 통화를 찾지 못한 해외 실행(종이 — 계좌 실행은 시작에서 막힘)은
`currency_unknown` 표지를 달고, 어느 통화의 계좌 손실 한도 합계에도 들지 않습니다.
달러로 더하면 다른 통화의 손익이 달러 한도에 섞여, 손실을 안 낸 달러 실행까지 멈춥니다.
표지 칸이 없던 때 담아 둔 해외 실행은 그때처럼 달러로 셉니다. 세울 때 한 번 알립니다.

**계좌에도 NH선물 서버에도 닿지 않습니다.**
"""
from __future__ import annotations

import json

from backend.strategy import engine as engine_lib, journal as journal_lib, paper, runs
from backend.strategy import service as service_lib
from tests.test_strategy_service import _시간표, _해외마스터, _해외물음

USD = "USD"


def _목록(tmp_path) -> service_lib.RunService:
    return service_lib.RunService(
        store=runs.RunStore(tmp_path / "runs.json"),
        journal=journal_lib.Journal(tmp_path / "trades.jsonl"),
        master=_해외마스터(),
        hours=_시간표(),
        fetch=lambda run, minutes, count: [],
    )


def _잃게(엔진, 차이: float) -> None:
    """한 계약을 사고 `차이` 만큼 낮게 팔아 그날 손실을 냅니다."""
    엔진.ledger.add({"side": paper.BUY, "quantity": 1, "price": 7000.0, "time": 1})
    엔진.ledger.add({"side": paper.SELL, "quantity": 1, "price": 7000.0 - 차이, "time": 2})


def _모름_줄(엔진) -> list[dict]:
    return [one for one in 엔진.events if one.get("reason") == service_lib.CURRENCY_UNKNOWN_REASON]


def _세운(tmp_path):
    실행목록 = _목록(tmp_path)
    실행목록.add(**_해외물음(run_id="unknown"))
    # 통화를 아는 실행입니다(장운영정보 품목 줄에 USD 가 있던 경우).
    실행목록._currency_of = lambda market, code: USD
    실행목록.add(**_해외물음(run_id="usd"))
    모름, 달러 = 실행목록._engine("unknown"), 실행목록._engine("usd")
    assert 모름.run.currency_unknown and 모름.run.multiplier is not None
    assert 달러.run.currency == USD and not 달러.run.currency_unknown
    return 실행목록, 모름, 달러


def test_통화를_모르는_실행의_큰_손실이_달러_실행을_멈추지_않는다(tmp_path):
    실행목록, 모름, 달러 = _세운(tmp_path)
    _잃게(달러, 1.0)  # 승수 5 → −5
    _잃게(모름, 100.0)  # 승수 5 → −500

    assert 실행목록.account_loss({USD: 100.0}, 10) == []
    assert 달러.run.state == runs.ARMED and 모름.run.state == runs.ARMED


def test_통화를_아는_달러_실행은_그대로_한도에_든다(tmp_path):
    실행목록, 모름, 달러 = _세운(tmp_path)
    _잃게(달러, 100.0)

    assert 실행목록.account_loss({USD: 100.0}, 10) == ["usd"]
    assert 모름.run.state == runs.ARMED, "통화를 모르는 실행은 그 합계의 실행이 아닙니다."


def test_표지_칸이_없던_옛_해외_실행은_달러로_센다(tmp_path):
    실행목록, 모름, _ = _세운(tmp_path)
    모름.run.currency_unknown = False  # 칸이 없던 때 담긴 실행처럼
    _잃게(모름, 100.0)

    assert 실행목록.account_loss({USD: 100.0}, 10) == ["unknown", "usd"], "달러 합계에 들어 함께 멈춥니다."


def test_세울_때_한_번만_알리고_아는_실행에는_없다(tmp_path):
    실행목록, 모름, 달러 = _세운(tmp_path)
    for at in (10, 20):
        실행목록.account_loss({USD: 100.0}, at)

    (줄,) = _모름_줄(모름)
    assert (줄["kind"], 줄["text"]) == (engine_lib.READY, service_lib.WHY_CURRENCY_UNKNOWN_LIMIT)
    assert _모름_줄(달러) == []
    assert 모름.run.draft and 모름.run.currency == ""


def test_국내_실행에는_표지가_없다(tmp_path):
    from tests.test_strategy_service import _모의목록, _물음

    실행목록 = _모의목록(tmp_path)
    실행목록.add(**_물음())

    엔진 = 실행목록._engine("run1")
    assert 엔진.run.currency_unknown is False and _모름_줄(엔진) == []


def test_표지는_파일에_담기고_칸이_없는_옛_줄은_거짓으로_읽힌다(tmp_path):
    실행목록, _, _ = _세운(tmp_path)
    길 = tmp_path / "runs.json"
    담긴것 = json.loads(길.read_text(encoding="utf-8"))
    assert {one["id"]: one["currency_unknown"] for one in 담긴것["runs"]} == {
        "unknown": True,
        "usd": False,
    }

    for one in 담긴것["runs"]:
        one.pop("currency_unknown")
    길.write_text(json.dumps(담긴것, ensure_ascii=False), encoding="utf-8")

    읽은것 = {one.id: one.currency_unknown for one in runs.RunStore(길).read()}
    assert 읽은것 == {"unknown": False, "usd": False}


def test_코드는_다른_코드와_겹치지_않는다():
    다른것 = set(engine_lib.BLOCK_REASONS.values()) | {
        engine_lib.OTHER_REASON,
        engine_lib.ENTRY_REASON,
        service_lib.ACCOUNT_LOSS_REASON,
        service_lib.RECONCILE_RESUME_REASON,
        service_lib.RECONCILE_KEPT_PAUSED_REASON,
    }
    assert service_lib.CURRENCY_UNKNOWN_REASON not in 다른것
