"""반입 스크립트.

수집 기록에는 열람용 응답과 테스트용 응답이 함께 들어 있습니다. 두 응답을
일부러 다르게 만들어 두고, 반입된 값이 **테스트용** 쪽인지 확인합니다.
값이 같으면 어느 쪽을 읽었는지 결과로는 구분되지 않습니다.
"""
import json

import pytest

from backend.nh_api.fixtures import INDEX_NAME
from scripts.import_nh_fixtures import (
    MASKED,
    SourceError,
    check_target,
    collect,
    main,
    read_record,
)

열람용_응답 = {"last_pric": "9999.99", "work_empl": "열람용"}
테스트용_응답 = {"last_pric": "1338.50", "work_empl": "emp01", "occurs1_ac_nm": "홍길동"}

열람용_메시지 = {"body": {"exec_pric": "9999.9"}}
테스트용_메시지 = {"body": {"exec_pric": "1335.9", "work_empl": "emp01"}}


def _http_record(run_id="20260909T000019_aaaa", api_id="domestic_price", **override):
    record = {
        "format_version": 2,
        "run_id": run_id,
        "started_at": "2026-09-09T00:00:19.563528+00:00",
        "environment": "real",
        "market": "domestic",
        "api_id": api_id,
        "scenario_id": f"{api_id}__base",
        "test_group": "조회실행_20260909",
        "status": "response_received",
        "http_status": 200,
        "request": {"sym": "A7569000"},
        "response": 열람용_응답,
        "response_headers": {"content-type": "application/json"},
        "account_alias": "<ID:1234>",
        "fixture_seed": {"request": {"sym": "A7569000"}, "response": 테스트용_응답},
    }
    record.update(override)
    return record


def _stream_record(run_id="20260909T062116_bbbb"):
    return {
        "format_version": 2,
        "run_id": run_id,
        "started_at": "2026-09-09T06:21:16.000000+00:00",
        "environment": "paper",
        "market": "domestic",
        "api_id": "KA",
        "scenario_id": "KA__base",
        "test_group": "모의왕복_20260909",
        "status": "stream_window_finished",
        "events_file": f"{run_id}.events.jsonl",
        "request": {"body": {"action_code": "KA", "action_sym": "A7569000"}},
        "fixture_seed": {"request": {"body": {"action_code": "KA", "action_sym": "A7569000"}}},
    }


def _events():
    return [
        {
            "seq": 2,
            "direction": "received",
            "elapsed_ms": 74.5,
            "payload": 열람용_메시지,
            "fixture_payload": 테스트용_메시지,
        },
        {
            "seq": 1,
            "direction": "sent",
            "elapsed_ms": 45.4,
            "payload": {"body": {"session_token": "<SECRET>"}},
            "fixture_payload": {"body": {"session_token": "FIXTURE_SECRET"}},
        },
    ]


@pytest.fixture
def source(tmp_path):
    """작은 수집 폴더를 만든다. 실제 수집 폴더는 읽지 않는다."""
    root = tmp_path / "수집결과"

    http_dir = root / "domestic_price" / "real" / "domestic"
    http_dir.mkdir(parents=True)
    record = _http_record()
    (http_dir / f"{record['run_id']}.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )

    stream_dir = root / "KA" / "paper" / "domestic"
    stream_dir.mkdir(parents=True)
    stream = _stream_record()
    (stream_dir / f"{stream['run_id']}.json").write_text(
        json.dumps(stream, ensure_ascii=False), encoding="utf-8"
    )
    (stream_dir / stream["events_file"]).write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in _events()), encoding="utf-8"
    )
    return root


def _run(source, target, extra=()):
    assert main(["--source", str(source), "--target", str(target), *extra]) == 0


def _read(target, relative):
    return json.loads((target / relative).read_text(encoding="utf-8"))


def test_열람용이_아니라_테스트용_응답을_반입한다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)

    fixture = _read(target, "domestic_price/real/domestic/20260909T000019_aaaa.json")
    assert fixture["response"]["last_pric"] == 테스트용_응답["last_pric"]
    assert fixture["response"]["last_pric"] != 열람용_응답["last_pric"]
    assert fixture["request"] == {"sym": "A7569000"}
    assert fixture["method"] == "POST"
    assert fixture["path"] == "/trade/v1/domestic/price"


def test_실시간도_테스트용_본문을_반입한다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)

    fixture = _read(target, "KA/paper/domestic/20260909T062116_bbbb.json")
    assert fixture["transport"] == "WEBSOCKET"
    # 파일에 적힌 순서가 아니라 순번대로 정리된다.
    assert [e["seq"] for e in fixture["events"]] == [1, 2]
    받은것 = [e for e in fixture["events"] if e["direction"] == "received"][0]
    assert 받은것["payload"]["body"]["exec_pric"] == 테스트용_메시지["body"]["exec_pric"]
    assert 받은것["payload"]["body"]["exec_pric"] != 열람용_메시지["body"]["exec_pric"]


def test_사람을_가리키는_항목을_가린다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)

    fixture = _read(target, "domestic_price/real/domestic/20260909T000019_aaaa.json")
    assert fixture["response"]["work_empl"] == MASKED
    assert fixture["response"]["occurs1_ac_nm"] == MASKED

    stream = _read(target, "KA/paper/domestic/20260909T062116_bbbb.json")
    받은것 = [e for e in stream["events"] if e["direction"] == "received"][0]
    assert 받은것["payload"]["body"]["work_empl"] == MASKED
    # 가리는 것은 사람을 가리키는 항목뿐이다. 값은 그대로 남는다.
    assert 받은것["payload"]["body"]["exec_pric"] == "1335.9"


def test_수집_기록의_다른_항목은_들어오지_않는다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)

    fixture = _read(target, "domestic_price/real/domestic/20260909T000019_aaaa.json")
    for field in ("fixture_seed", "response_headers", "account_alias"):
        assert field not in fixture
    assert "열람용" not in json.dumps(fixture, ensure_ascii=False)


def test_다시_돌려도_같은_파일이_나온다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)
    처음 = {p: p.read_bytes() for p in sorted(target.rglob("*.json"))}

    _run(source, target)
    다시 = {p: p.read_bytes() for p in sorted(target.rglob("*.json"))}

    assert 처음 == 다시


def test_이번에_만들지_않은_파일은_지운다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)

    남은것 = target / "domestic_price" / "real" / "domestic" / "옛날기록.json"
    남은것.write_text("{}", encoding="utf-8")

    _run(source, target)
    assert not 남은것.is_file()


def test_출처를_함께_적는다(source, tmp_path):
    target = tmp_path / "나온것"
    _run(source, target)

    index = _read(target, "index.json")
    assert index["record_count"] == 2
    assert index["groups"] == ["모의왕복_20260909", "조회실행_20260909"]
    첫줄 = index["records"][0]
    assert 첫줄["record_id"]
    assert 첫줄["collected_at"]
    assert 첫줄["scenario_id"]
    assert (target / 첫줄["file"]).is_file()


def test_실전_계좌_응답은_반입하지_않는다(source, tmp_path):
    """예수금 금액은 식별자와 달리 실제 값 그대로라 저장소에 두지 않는다."""
    폴더 = source / "domestic_deposit" / "real" / "domestic"
    폴더.mkdir(parents=True)
    기록 = _http_record(
        run_id="20260909T000030_dddd",
        api_id="domestic_deposit",
        fixture_seed={
            "request": {"biz_dt": "20260909"},
            "response": {"ord_psb_tot_amt": "100000000"},
        },
    )
    (폴더 / f"{기록['run_id']}.json").write_text(
        json.dumps(기록, ensure_ascii=False), encoding="utf-8"
    )

    built, _, _, excluded = collect(source)
    assert len(built) == 2
    assert excluded == {"domestic_deposit": 1}

    target = tmp_path / "나온것"
    _run(source, target)
    assert not (target / "domestic_deposit").exists()
    assert _read(target, "index.json")["excluded_live_account"] == {"domestic_deposit": 1}


def test_모의_계좌_응답은_반입한다(source, tmp_path):
    """모의 환경은 실제 돈이 아니라 그대로 둔다."""
    폴더 = source / "domestic_deposit" / "paper" / "domestic"
    폴더.mkdir(parents=True)
    기록 = _http_record(
        run_id="20260909T000031_eeee",
        api_id="domestic_deposit",
        environment="paper",
        fixture_seed={
            "request": {"biz_dt": "20260909"},
            "response": {"ord_psb_tot_amt": "100000000"},
        },
    )
    (폴더 / f"{기록['run_id']}.json").write_text(
        json.dumps(기록, ensure_ascii=False), encoding="utf-8"
    )

    built, _, _, excluded = collect(source)
    assert len(built) == 3
    assert excluded == {}


def test_실전_시세_응답은_반입한다(source):
    """시장 정보는 누가 물어도 같은 값이라 그대로 둔다."""
    built, _, _, excluded = collect(source)
    assert any(경로.parts[0] == "domestic_price" for 경로 in built)
    assert excluded == {}


def test_이전_형식은_반입하지_않는다(source, tmp_path):
    옛기록 = source / "domestic_price" / "real" / "domestic" / "옛형식.json"
    옛기록.write_text(json.dumps({"format_version": 1, "run_id": "x"}), encoding="utf-8")

    built, _, skipped, _ = collect(source)
    assert len(built) == 2
    assert any("형식 2" in message for message in skipped)


def test_반입으로_만든_폴더가_아니면_지우지_않는다(source, tmp_path):
    """--target 을 잘못 지정했을 때 남의 파일이 지워지지 않아야 한다."""
    남의폴더 = tmp_path / "남의폴더"
    남의폴더.mkdir()
    남의것 = 남의폴더 / "중요한파일.json"
    남의것.write_text('{"지우면": "안 됨"}', encoding="utf-8")

    with pytest.raises(SourceError):
        check_target(남의폴더)
    assert main(["--source", str(source), "--target", str(남의폴더)]) == 1
    assert 남의것.is_file()


def test_출처_폴더는_반드시_지정한다(tmp_path):
    """어디서 가져올지는 쓰는 사람마다 다르므로 기본값을 두지 않는다."""
    with pytest.raises(SystemExit):
        main(["--target", str(tmp_path)])


def test_테스트용_자료가_없으면_반입하지_않는다(tmp_path):
    기록 = _http_record()
    기록.pop("fixture_seed")
    경로 = tmp_path / "기록.json"
    경로.write_text(json.dumps(기록, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SourceError):
        read_record(경로)


def test_모르는_API_는_건너뛴다(source, tmp_path):
    폴더 = source / "lme_order" / "paper" / "domestic"
    폴더.mkdir(parents=True)
    기록 = _http_record(run_id="20260909T000020_cccc", api_id="lme_order", environment="paper")
    (폴더 / f"{기록['run_id']}.json").write_text(
        json.dumps(기록, ensure_ascii=False), encoding="utf-8"
    )

    built, _, skipped, _ = collect(source)
    assert len(built) == 2
    assert any("모르는 API" in message for message in skipped)


# ── 저장소에 안 올리는 자리 ──────────────────────────────────


def test_실전_계좌_응답은_기본적으로_안_들어온다(tmp_path):
    """켜지 않으면 지금까지처럼 버립니다."""
    source = tmp_path / "수집"
    source.mkdir()
    (source / "a.json").write_text(
        json.dumps(_http_record(run_id="live1", api_id="domestic_deposit", environment="real")),
        encoding="utf-8",
    )

    built, private, _, excluded = collect(source)
    assert built == {}
    assert private == {}
    assert excluded == {"domestic_deposit": 1}


def test_켜면_실전_계좌_응답이_따로_모인다(tmp_path):
    """저장소에 올리는 자리와 **섞이지 않아야** 합니다."""
    source = tmp_path / "수집"
    source.mkdir()
    (source / "a.json").write_text(
        json.dumps(_http_record(run_id="live1", api_id="domestic_deposit", environment="real")),
        encoding="utf-8",
    )
    (source / "b.json").write_text(
        json.dumps(_http_record(run_id="quote1", api_id="domestic_price", environment="real")),
        encoding="utf-8",
    )

    built, private, _, excluded = collect(source, keep_live_account=True)

    assert [p.parts[0] for p in built] == ["domestic_price"]
    assert [p.parts[0] for p in private] == ["domestic_deposit"]
    # 따로 모았어도 **공개 자리에 안 넣은 것**으로는 셉니다. 그래야 공개 색인이
    # 이 옵션을 켜든 끄든 같은 내용으로 나옵니다.
    assert excluded == {"domestic_deposit": 1}


def test_두_자리에_각각_쓰고_각자_색인을_만든다(tmp_path):
    source = tmp_path / "수집"
    source.mkdir()
    (source / "a.json").write_text(
        json.dumps(_http_record(run_id="live1", api_id="domestic_deposit", environment="real")),
        encoding="utf-8",
    )
    (source / "b.json").write_text(
        json.dumps(_http_record(run_id="quote1", api_id="domestic_price", environment="real")),
        encoding="utf-8",
    )
    공개 = tmp_path / "nh"
    비공개 = tmp_path / "nh_private"

    코드 = main(
        [
            "--source", str(source),
            "--target", str(공개),
            "--private-out", str(비공개),
        ]
    )

    assert 코드 == 0
    assert (공개 / "domestic_price" / "real" / "domestic" / "quote1.json").is_file()
    assert (비공개 / "domestic_deposit" / "real" / "domestic" / "live1.json").is_file()
    assert (공개 / INDEX_NAME).is_file()
    assert (비공개 / INDEX_NAME).is_file()
    # 실전 계좌 응답이 공개 자리에 하나도 없어야 합니다.
    assert not (공개 / "domestic_deposit").exists()


def test_콘솔이_한글을_못_받아도_안_죽는다(tmp_path, capsys, monkeypatch):
    """Windows 기본 콘솔(cp949)에서 반입이 도중에 멈출 수 있는 자리입니다."""
    import io
    import sys

    from scripts.import_nh_fixtures import speak_utf8

    좁은출력 = io.TextIOWrapper(io.BytesIO(), encoding="cp949", errors="strict")
    monkeypatch.setattr(sys, "stdout", 좁은출력)
    monkeypatch.setattr(sys, "stderr", 좁은출력)

    speak_utf8()
    # 좁은 콘솔에서는 여기서 UnicodeEncodeError 로 죽을 수 있는 자리입니다.
    print("넣지 않음 — 실전 계좌·주문 응답 3건")
    좁은출력.flush()


def _두기록(source):
    source.mkdir(exist_ok=True)
    (source / "a.json").write_text(
        json.dumps(_http_record(run_id="live1", api_id="domestic_deposit", environment="real")),
        encoding="utf-8",
    )
    (source / "b.json").write_text(
        json.dumps(_http_record(run_id="quote1", api_id="domestic_price", environment="real")),
        encoding="utf-8",
    )


def test_두_자리가_같으면_막는다(tmp_path):
    """겹치면 실전 계좌 응답이 공개 자리에 써집니다."""
    source = tmp_path / "수집"
    _두기록(source)
    같은자리 = tmp_path / "nh"

    코드 = main(
        ["--source", str(source), "--target", str(같은자리), "--private-out", str(같은자리)]
    )

    assert 코드 == 1
    # 한 건도 안 써야 합니다.
    assert not 같은자리.exists()


@pytest.mark.parametrize("안쪽", ["private", "깊이/더/안쪽"])
def test_한쪽이_다른_쪽_안이면_막는다(tmp_path, 안쪽):
    source = tmp_path / "수집"
    _두기록(source)
    공개 = tmp_path / "nh"

    코드 = main(
        ["--source", str(source), "--target", str(공개), "--private-out", str(공개 / 안쪽)]
    )

    assert 코드 == 1
    assert not 공개.exists()


def test_반대로_공개가_안쪽이어도_막는다(tmp_path):
    source = tmp_path / "수집"
    _두기록(source)
    비공개 = tmp_path / "nh_private"

    코드 = main(
        ["--source", str(source), "--target", str(비공개 / "nh"), "--private-out", str(비공개)]
    )

    assert 코드 == 1


def test_공개_색인은_옵션과_무관하게_같다(tmp_path):
    """추적되는 파일이 로컬 사정에 따라 두 내용 사이를 오가면 안 됩니다."""
    source = tmp_path / "수집"
    _두기록(source)

    끄고 = tmp_path / "끄고"
    main(["--source", str(source), "--target", str(끄고)])

    켜고 = tmp_path / "켜고"
    main(
        [
            "--source", str(source),
            "--target", str(켜고),
            "--private-out", str(tmp_path / "따로"),
        ]
    )

    한쪽 = (끄고 / INDEX_NAME).read_text(encoding="utf-8")
    다른쪽 = (켜고 / INDEX_NAME).read_text(encoding="utf-8")
    assert 한쪽 == 다른쪽
    # 「일부러 넣지 않은 것」 기록이 켠 쪽에서도 남아 있어야 합니다.
    assert json.loads(다른쪽)["excluded_live_account"] == {"domestic_deposit": 1}
