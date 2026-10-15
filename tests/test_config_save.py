"""설정 저장 — 바뀐 항목만 쓰는지 확인합니다.

화면이 가린 값(「••••」)을 되돌려 보내 실제 값을 덮어쓰는 사고를 막는 것이
`save_markets` 의 존재 이유이므로, 그 성질을 테스트로 붙잡아 둡니다.
"""
import yaml

from backend.config import config_view, save_markets


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_빠진_항목은_그대로_남는다(tmp_path):
    path = tmp_path / "config.yaml"
    _write(
        path,
        {
            "default_environment": "paper",
            "paper": {
                "domestic": {"app_key": "KEY-D", "app_secret": "SEC-D"},
                "overseas": {"app_key": "KEY-O", "app_secret": "SEC-O"},
            },
        },
    )

    # 국내 App Key 하나만 고칩니다.
    save_markets({"paper": {"domestic": {"app_key": "KEY-D2"}}}, path=path)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["paper"]["domestic"]["app_key"] == "KEY-D2"
    # 안 보낸 항목은 건드리지 않습니다.
    assert saved["paper"]["domestic"]["app_secret"] == "SEC-D"
    assert saved["paper"]["overseas"] == {"app_key": "KEY-O", "app_secret": "SEC-O"}


def test_파일이_없으면_만들고_모의로_시작한다(tmp_path):
    path = tmp_path / "없던폴더" / "config.yaml"

    save_markets({"real": {"overseas": {"app_key": "KEY"}}}, path=path)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["real"]["overseas"]["app_key"] == "KEY"
    # 실전이 기본이면 잘못 눌렀을 때 실제 계좌로 주문이 나갑니다.
    assert saved["default_environment"] == "paper"


def test_보여줄_때_값은_안_나간다(tmp_path):
    path = tmp_path / "config.yaml"
    _write(
        path,
        {
            "default_environment": "paper",
            "paper": {"domestic": {"app_key": "APPKEY-0000-XXXX", "app_secret": "SECRET-0000"}},
        },
    )

    view = config_view(path)
    domestic = view["environments"]["paper"]["domestic"]

    assert domestic["app_key"]["set"] is True
    assert domestic["app_secret"]["set"] is True
    # 이제 항목은 둘뿐입니다.
    assert set(domestic) == {"app_key", "app_secret"}

    # 가린 표시 안에 원래 값이 통째로 들어 있지 않아야 합니다.
    assert "APPKEY-0000-XXXX" not in domestic["app_key"]["masked"]
    assert "SECRET-0000" not in domestic["app_secret"]["masked"]


def test_없는_환경이나_항목은_거부한다(tmp_path):
    path = tmp_path / "config.yaml"

    for bad in (
        {"stage": {"domestic": {"app_key": "x"}}},
        {"paper": {"lme": {"app_key": "x"}}},
        {"paper": {"domestic": {"password": "x"}}},
        # 계좌번호는 더 이상 받지 않습니다.
        {"paper": {"domestic": {"account": "1234"}}},
    ):
        try:
            save_markets(bad, path=path)
        except ValueError:
            continue
        raise AssertionError(f"거부했어야 합니다: {bad}")


def test_항목마다_가리는_정도가_다르다(tmp_path):
    from backend.config import SECRET_MASK, _mask_field

    # App Key 는 어느 키인지 알아볼 만큼만 남깁니다.
    assert _mask_field("app_key", "UYMjabcdefgh") == "UYMj********"
    # Secret 은 한 글자도 안 보여줍니다. 길이도 안 흘립니다.
    assert _mask_field("app_secret", "SECRETVALUE123") == SECRET_MASK
    assert _mask_field("app_secret", "짧음") == SECRET_MASK
    # 남길 자리보다 짧으면 통째로 가립니다.
    assert _mask_field("app_key", "ab") == "**"
    assert _mask_field("app_key", "") == ""
