"""수집해 둔 NH선물 Open API 응답을 테스트용 자료로 반입합니다.

    uv run python scripts/import_nh_fixtures.py --source <수집 폴더>

수집 기록에는 열람용 응답과 테스트용 응답이 함께 들어 있습니다. 열람용은
사람이 눈으로 보려고 가린 것이고, 테스트용은 인증값과 식별자를 바꿔 둔
것입니다. **반입하는 것은 테스트용뿐입니다.** 열람용 응답과 인증값,
계좌 별칭은 저장소로 들어오지 않습니다.

사람을 가리키는 항목(작업사원 등)은 값이 남아 있는 경우가 있어 반입할 때
정해진 문구로 바꿉니다.

**계좌번호와 주문번호는 자릿수를 보존해 만든 가명이라 실제 번호와 생김새가
같습니다.** 자리마다 숫자를 다른 숫자로 바꾸어 만든 값이고 실제 번호가
아닙니다. 12자리 숫자가 보인다고 해서 진짜가 남은 것이 아니며, 가리려고
하지 마세요 — 왜 그대로 두는지는 아래 `PERSON_FIELDS` 옆에 있습니다.

같은 자료로 다시 실행하면 같은 파일이 나옵니다. 이전에 만들었지만 이번에
만들지 않은 파일은 지웁니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.nh_api.catalog import HTTP_APIS, STREAM_APIS, is_account_api  # noqa: E402
from backend.nh_api.fixtures import FIXTURE_FORMAT, INDEX_NAME  # noqa: E402

DEFAULT_TARGET = REPO_ROOT / "tests" / "fixtures" / "nh"

INDEX_FORMAT = "nh-fixture-index-1"

# 기록에서 이 항목만 읽습니다. 여기 없는 항목은 결과 파일에 들어가지 않습니다.
SEED_FIELD = "fixture_seed"
EVENT_FIELD = "fixture_payload"
META_FIELDS = ("api_id", "environment", "market", "scenario_id", "test_group", "status")

# 사람을 가리키는 항목. 값이 있으면 이 문구로 바꿉니다. 응답 명세에서
# 작업사원, 주문ID, 계좌명에 해당하는 항목을 모은 것이고, 같은 항목이 배열
# 안에서는 `occurs1_` 를 붙여 오므로 두 형태를 함께 적습니다.
#
# 계좌번호(`ac_no`·`occurs1_ac_no`·`action_acnt`)는 수집할 때 이미 다른 번호로
# 바뀝니다. 여기서 다시 덮지 않는 이유는 **같은 가명 하나가 주문 알림·잔고·
# 주문내역을 한 계좌로 이어 주기 때문**입니다. 가리면 그 연결이 끊기고, 세
# 응답이 같은 계좌의 것인지 확인할 방법이 없어집니다.
PERSON_FIELDS = (
    "work_empl",
    "user_id",
    "occurs1_user_id",
    "ord_id",
    "occurs1_ord_id",
    "fst_ord_id",
    "occurs1_fst_ord_id",
    "ac_nm",
    "occurs1_ac_nm",
    "mrgn_ac_nm",
    "prr_aff_mrgn_ac_nm",
)
MASKED = "FIXTURE_MASKED"

ENVIRONMENTS = ("paper", "real")
MARKETS = ("domestic", "overseas")

# 실전 환경에서 받은 계좌·주문 응답은 반입하지 않습니다. 계좌번호 같은
# 식별자는 수집할 때 바뀌지만 예수금·잔고·손익 금액은 실제 값 그대로여서,
# 저장소에 두면 저장소를 받는 사람이 모두 보게 됩니다.
#
# 반입하는 것은 두 가지입니다.
#
#   모의 환경의 계좌·주문 응답   실제 돈이 아닙니다
#   실전 환경의 시장 정보        누가 물어도 같은 값입니다
LIVE_ENVIRONMENT = "real"


class SourceError(Exception):
    """반입할 수 없는 기록을 만났습니다."""


def mask_people(value: Any) -> Any:
    """사람을 가리키는 항목의 값을 정해진 문구로 바꿉니다.

    비어 있는 값은 그대로 둡니다. 원래 값이 없던 자리를 채우면 없던 자료가
    생긴 것처럼 보입니다.
    """
    if isinstance(value, dict):
        return {
            key: MASKED if key in PERSON_FIELDS and isinstance(item, str) and item.strip() else mask_people(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_people(item) for item in value]
    return value


def read_record(path: Path) -> dict[str, Any]:
    """기록 하나를 읽고 반입할 수 있는지 확인합니다."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SourceError(f"{path.name}: 파일을 읽을 수 없습니다.") from exc

    if not isinstance(raw, dict):
        raise SourceError(f"{path.name}: 기록 형식이 아닙니다.")
    if raw.get("format_version") != 2:
        raise SourceError(
            f"{path.name}: 형식 2 기록만 반입합니다. 이전 형식에는 테스트용 자료가 없습니다."
        )
    seed = raw.get(SEED_FIELD)
    if not isinstance(seed, dict) or "request" not in seed:
        raise SourceError(f"{path.name}: 테스트용 자료({SEED_FIELD})가 없습니다.")

    environment = raw.get("environment")
    market = raw.get("market")
    if environment not in ENVIRONMENTS or market not in MARKETS:
        raise SourceError(f"{path.name}: 환경 또는 시장을 알 수 없습니다.")
    if not raw.get("run_id") or not raw.get("started_at"):
        raise SourceError(f"{path.name}: 기록 번호나 수집 시각이 없습니다.")
    return raw


def read_events(path: Path) -> list[dict[str, Any]]:
    """실시간 기록의 메시지를 읽습니다. 테스트용 본문만 가져옵니다."""
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if EVENT_FIELD not in raw:
            raise SourceError(f"{path.name}: 테스트용 본문({EVENT_FIELD})이 없는 메시지가 있습니다.")
        events.append(
            {
                "seq": raw["seq"],
                "direction": raw["direction"],
                "offset_ms": raw["elapsed_ms"],
                "payload": mask_people(raw[EVENT_FIELD]),
            }
        )
    events.sort(key=lambda e: e["seq"])
    return events


def build(record: dict[str, Any], events: list[dict[str, Any]] | None) -> dict[str, Any]:
    """반입 파일 하나의 내용을 만듭니다."""
    seed = record[SEED_FIELD]
    api_id = record["api_id"]

    fixture: dict[str, Any] = {
        "format": FIXTURE_FORMAT,
        "record_id": record["run_id"],
        "collected_at": record["started_at"],
        **{key: record.get(key) or "" for key in META_FIELDS},
        "request": mask_people(seed["request"]),
    }

    if events is not None:
        if api_id not in STREAM_APIS:
            raise SourceError(f"{api_id}: 모르는 실시간 API 입니다.")
        fixture["transport"] = "WEBSOCKET"
        fixture["events"] = events
        return fixture

    spec = HTTP_APIS.get(api_id)
    if spec is None:
        raise SourceError(f"{api_id}: 모르는 API 입니다.")
    if "response" not in seed or record.get("http_status") is None:
        raise SourceError(f"{record['run_id']}: 응답을 받지 못한 기록입니다.")

    fixture["transport"] = "HTTP"
    fixture["method"] = spec.method
    fixture["path"] = spec.path
    fixture["http_status"] = record["http_status"]
    fixture["response"] = mask_people(seed["response"])
    return fixture


def excluded_reason(record: dict[str, Any]) -> str | None:
    """반입하지 않기로 한 기록이면 그 이유를, 아니면 None 을 돌려줍니다."""
    if record["environment"] == LIVE_ENVIRONMENT and is_account_api(record["api_id"]):
        return "실전 계좌·주문 응답"
    return None


def collect(
    source: Path,
    *,
    keep_live_account: bool = False,
) -> tuple[
    dict[Path, dict[str, Any]], dict[Path, dict[str, Any]], list[str], dict[str, int]
]:
    """수집 폴더를 훑어 반입할 내용을 모읍니다.

    돌려주는 것은 넷입니다 — 저장소에 올릴 것, **올리지 않을 것**, 읽지 못해
    건너뛴 것, 넣지 않기로 한 것.

    `keep_live_account` 를 켜면 실전 계좌·주문 응답을 버리지 않고 두 번째
    자리에 모읍니다. 그 응답에는 금액이 실제 값 그대로 들어 있어 **저장소에
    올리는 자리와 절대 섞이면 안 됩니다.**
    """
    if not source.is_dir():
        raise SourceError(f"수집 폴더를 찾을 수 없습니다: {source}")

    built: dict[Path, dict[str, Any]] = {}
    private: dict[Path, dict[str, Any]] = {}
    skipped: list[str] = []
    excluded: dict[str, int] = {}

    for path in sorted(source.rglob("*.json")):
        if path.name.endswith((".review.json", ".test.json", ".summary.json")):
            continue
        try:
            record = read_record(path)
        except SourceError as exc:
            skipped.append(str(exc))
            continue

        live_account = excluded_reason(record) is not None
        if live_account:
            # **어디로 보내든 「공개 자리에 안 넣은 것」으로 셉니다.** 공개 색인은
            # 공개 폴더를 설명하는 글이라, 이 수가 `--private-out` 유무에 따라
            # 달라지면 **추적되는 파일이 로컬 사정에 따라 두 내용 사이를
            # 오갑니다.** 그러면 그 파일의 diff 가 뜻을 잃습니다.
            key = record["api_id"]
            excluded[key] = excluded.get(key, 0) + 1
            if not keep_live_account:
                continue

        events_name = record.get("events_file")
        events = None
        if events_name:
            events_path = path.parent / events_name
            if not events_path.is_file():
                skipped.append(f"{path.name}: 실시간 메시지 파일이 없습니다.")
                continue
            events = read_events(events_path)

        try:
            fixture = build(record, events)
        except SourceError as exc:
            skipped.append(str(exc))
            continue

        relative = Path(record["api_id"]) / record["environment"] / record["market"] / f"{record['run_id']}.json"
        into = private if live_account else built
        if relative in into:
            raise SourceError(f"기록 번호가 겹칩니다: {relative}")
        into[relative] = fixture

    return built, private, skipped, excluded


def index_of(built: dict[Path, dict[str, Any]], excluded: dict[str, int] | None = None) -> dict[str, Any]:
    """어디서 온 자료인지 남깁니다."""
    records = [
        {
            "file": relative.as_posix(),
            "api_id": fixture["api_id"],
            "environment": fixture["environment"],
            "market": fixture["market"],
            "record_id": fixture["record_id"],
            "collected_at": fixture["collected_at"],
            "scenario_id": fixture["scenario_id"],
            "test_group": fixture["test_group"],
            "transport": fixture["transport"],
            "status": fixture["status"],
            **(
                {"events": len(fixture["events"])}
                if fixture["transport"] == "WEBSOCKET"
                else {"http_status": fixture["http_status"]}
            ),
        }
        for relative, fixture in sorted(built.items())
    ]
    collected = sorted(record["collected_at"] for record in records)
    return {
        "format": INDEX_FORMAT,
        "generated_by": "scripts/import_nh_fixtures.py",
        "record_count": len(records),
        "collected_from": collected[0] if collected else "",
        "collected_to": collected[-1] if collected else "",
        "groups": sorted({record["test_group"] for record in records if record["test_group"]}),
        # 일부러 넣지 않은 것. 실전 환경의 계좌·주문 응답입니다.
        "excluded_live_account": dict(sorted((excluded or {}).items())),
        "records": records,
    }


def write(path: Path, payload: dict[str, Any]) -> bool:
    """내용이 달라졌을 때만 씁니다. 썼으면 True."""
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def check_target(target: Path) -> None:
    """쓰기 전에, 여기가 반입으로 만든 폴더가 맞는지 확인합니다.

    반입은 이 폴더에서 자기가 만들지 않은 파일을 지웁니다. `--target` 을 잘못
    지정했을 때 남의 파일이 지워지지 않도록 막습니다.
    """
    if target.is_dir() and any(target.iterdir()) and not (target / INDEX_NAME).is_file():
        raise SourceError(
            f"{target} 은 반입으로 만든 폴더가 아닙니다 ({INDEX_NAME} 이 없습니다). "
            "빈 폴더나 이전 반입 결과 폴더를 지정해 주세요."
        )


def prune(target: Path, keep: set[Path]) -> list[Path]:
    """이번에 만들지 않은 파일을 지웁니다. 이 폴더는 전부 만들어진 것입니다."""
    removed = []
    for path in sorted(target.rglob("*.json")):
        relative = path.relative_to(target)
        if relative == Path(INDEX_NAME) or relative in keep:
            continue
        path.unlink()
        removed.append(relative)

    for directory in sorted(target.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return removed


def check_apart(target: Path, private: Path) -> None:
    """두 자리가 겹치면 막습니다.

    **겹치면 실전 계좌 응답이 공개 자리에 써집니다.** 같은 경로를 주면 공개
    기록이 지워지고 그 자리에 실전 응답이 들어앉고, 공개 자리 **안쪽**을 주면
    공개 트리 밑에 실전 파일이 생겨 그대로 커밋됩니다. 둘 다 조용히 성공하는
    모양이라, 알아채는 것은 금액이 저장소에 올라간 뒤입니다.
    """
    one = target.resolve()
    other = private.resolve()
    if one == other:
        raise SourceError(
            "저장소에 올리는 자리와 안 올리는 자리가 같습니다. "
            f"둘을 다른 폴더로 지정해 주세요: {one}"
        )
    if one in other.parents or other in one.parents:
        raise SourceError(
            "저장소에 올리는 자리와 안 올리는 자리가 한쪽 안에 있습니다. "
            f"서로 겹치지 않는 폴더로 지정해 주세요: {one} / {other}"
        )


def speak_utf8() -> None:
    """콘솔이 한글과 기호를 못 받아 죽지 않게 합니다.

    Windows 기본 콘솔은 cp949 라 「—」 같은 글자를 못 씁니다. 그대로 두면
    **반입 도중에 `UnicodeEncodeError` 로 죽습니다** — 자료를 반쯤 쓰고 멈추는
    셈이라 글자가 깨지는 것보다 나쁩니다. 그래서 못 쓰는 글자는 물음표로
    바꾸고 하던 일을 끝내게 합니다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    speak_utf8()
    parser = argparse.ArgumentParser(description="수집한 NH선물 Open API 응답을 테스트용 자료로 반입합니다.")
    parser.add_argument("--source", type=Path, required=True, help="수집 기록 폴더")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="반입할 자리")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 결과만 봅니다")
    parser.add_argument(
        "--private-out",
        type=Path,
        default=None,
        help=(
            "실전 계좌·주문 응답을 버리지 않고 이 자리에 씁니다. "
            "금액이 실제 값이라 저장소에 올리지 않는 폴더여야 합니다."
        ),
    )
    args = parser.parse_args(argv)

    keep = args.private_out is not None
    try:
        check_target(args.target)
        if keep:
            check_apart(args.target, args.private_out)
            check_target(args.private_out)
        built, private, skipped, excluded = collect(args.source, keep_live_account=keep)
    except SourceError as exc:
        print(f"반입할 수 없습니다: {exc}")
        return 1

    if not built:
        print(f"반입할 기록이 없습니다: {args.source}")
        return 1

    index = index_of(built, excluded)
    events = sum(len(f["events"]) for f in built.values() if f["transport"] == "WEBSOCKET")
    streams = sum(1 for f in built.values() if f["transport"] == "WEBSOCKET")

    print(f"기록 {len(built)}건 (HTTP {len(built) - streams}, 실시간 {streams}) / 실시간 메시지 {events}건")
    if excluded:
        print(f"  넣지 않음 — 실전 계좌·주문 응답 {sum(excluded.values())}건")
        for api_id, count in sorted(excluded.items()):
            print(f"    {api_id} {count}건")
    if keep:
        print(f"  저장소에 안 올리는 자리로 — 실전 계좌·주문 응답 {len(private)}건")
        for api_id, count in sorted(_by_api(private).items()):
            print(f"    {api_id} {count}건")
    for message in skipped:
        print(f"  건너뜀 — {message}")

    if args.dry_run:
        print("(--dry-run 이라 쓰지 않았습니다)")
        return 0

    changed = _write_all(args.target, built, index)
    removed = prune(args.target, set(built))
    print(f"바뀐 파일 {changed}개 / 지운 파일 {len(removed)}개 → {args.target}")

    if keep:
        changed = _write_all(args.private_out, private, index_of(private))
        removed = prune(args.private_out, set(private))
        print(f"바뀐 파일 {changed}개 / 지운 파일 {len(removed)}개 → {args.private_out}")
        print("  이 자리는 저장소에 올리지 않습니다. `git status` 에 안 뜨는지 확인해 주세요.")
    return 0


def _by_api(built: dict[Path, dict[str, Any]]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for fixture in built.values():
        counted[fixture["api_id"]] = counted.get(fixture["api_id"], 0) + 1
    return counted


def _write_all(
    target: Path, built: dict[Path, dict[str, Any]], index: dict[str, Any]
) -> int:
    changed = 0
    for relative, fixture in sorted(built.items()):
        if write(target / relative, fixture):
            changed += 1
    if write(target / INDEX_NAME, index):
        changed += 1
    return changed


if __name__ == "__main__":
    sys.exit(main())
