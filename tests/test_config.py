"""설정 로더 테스트."""
from pathlib import Path

import pytest

from backend.config import DEFAULT_BASE_URLS, ConfigError, load_config

VALID = """
default_environment: paper
paper:
  base_url: ""
  domestic:
    app_key: "PAPERDOM123"
    app_secret: "PAPERDOMSECRET456"
  overseas:
    app_key: "PAPEROVS123"
    app_secret: "PAPEROVSSECRET456"
real:
  base_url: ""
  domestic:
    app_key: "REALDOM123"
    app_secret: "REALDOMSECRET456"
  overseas:
    app_key: "REALOVS123"
    app_secret: "REALOVSSECRET456"
"""

ONLY_PAPER_DOMESTIC = """
default_environment: paper
paper:
  domestic:
    app_key: "PAPERDOM123"
    app_secret: "PAPERDOMSECRET456"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --- 환경과 시장 조회 ---------------------------------------------------------


def test_국내와_해외의_인증정보를_각각_읽는다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    domestic = config.market("domestic")
    overseas = config.market("overseas")

    assert domestic.app_key == "PAPERDOM123"
    assert overseas.app_key == "PAPEROVS123"
    assert domestic.app_secret != overseas.app_secret


def test_환경을_지정하지_않으면_기본_환경을_쓴다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.environment().name == "paper"
    assert config.market("domestic").app_key == "PAPERDOM123"


def test_두_환경을_동시에_조회할_수_있다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    paper = config.market("domestic", environment="paper")
    real = config.market("domestic", environment="real")

    # 기본 환경이 paper 여도 real 을 함께 쓸 수 있어야 한다.
    assert paper.app_key == "PAPERDOM123"
    assert real.app_key == "REALDOM123"
    assert config.default_environment == "paper"


def test_환경마다_접속_주소가_다르다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.environment("paper").base_url == DEFAULT_BASE_URLS["paper"]
    assert config.environment("real").base_url == DEFAULT_BASE_URLS["real"]


def test_접속_주소를_환경별로_지정할_수_있다(tmp_path):
    text = VALID.replace(
        'paper:\n  base_url: ""', 'paper:\n  base_url: "https://example.test:9999/"'
    )
    config = load_config(write(tmp_path, text))

    # 뒤에 붙은 슬래시는 제거되고, 지정하지 않은 환경은 기본값을 유지한다.
    assert config.environment("paper").base_url == "https://example.test:9999"
    assert config.environment("real").base_url == DEFAULT_BASE_URLS["real"]


def test_설정된_조합_목록을_알려준다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.configured == (
        ("paper", "domestic"),
        ("paper", "overseas"),
        ("real", "domestic"),
        ("real", "overseas"),
    )


# --- 일부만 채워진 경우 -------------------------------------------------------


def test_한쪽_환경_한쪽_시장만_설정해도_로딩된다(tmp_path):
    config = load_config(write(tmp_path, ONLY_PAPER_DOMESTIC))

    assert config.configured == (("paper", "domestic"),)
    assert config.market("domestic").app_key == "PAPERDOM123"


def test_설정되지_않은_시장을_쓰면_안내와_함께_거부한다(tmp_path):
    config = load_config(write(tmp_path, ONLY_PAPER_DOMESTIC))

    with pytest.raises(ConfigError) as exc:
        config.market("overseas")

    assert "모의 해외" in str(exc.value)
    assert "paper > overseas" in str(exc.value)


def test_설정되지_않은_환경을_쓰면_안내와_함께_거부한다(tmp_path):
    config = load_config(write(tmp_path, ONLY_PAPER_DOMESTIC))

    with pytest.raises(ConfigError) as exc:
        config.market("domestic", environment="real")

    assert "실전 국내" in str(exc.value)
    assert "real > domestic" in str(exc.value)


# --- 잘못된 입력 --------------------------------------------------------------


def test_알_수_없는_시장은_거부한다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    with pytest.raises(ValueError):
        config.market("unknown")


def test_알_수_없는_환경은_거부한다(tmp_path):
    config = load_config(write(tmp_path, VALID))

    with pytest.raises(ValueError):
        config.environment("staging")


def test_파일이_없으면_경로를_알려준다(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "없는파일.yaml")

    assert "없는파일.yaml" in str(exc.value)
    assert "config.example.yaml" in str(exc.value)


def test_default_environment_값이_잘못되면_거부한다(tmp_path):
    text = VALID.replace("default_environment: paper", "default_environment: staging")

    with pytest.raises(ConfigError, match="default_environment"):
        load_config(write(tmp_path, text))


def test_어느_환경에도_인증정보가_없으면_거부한다(tmp_path):
    text = """
default_environment: paper
paper:
  domestic:
    app_key: ""
    app_secret: ""
real:
  domestic:
    app_key: ""
    app_secret: ""
"""
    with pytest.raises(ConfigError, match="사용할 수 있는 인증 정보가 없습니다"):
        load_config(write(tmp_path, text))


def test_예전_파일에_남은_계좌번호는_무시한다(tmp_path):
    """예전 형식으로 저장된 파일에는 `account` 가 남아 있습니다.

    그 값은 이제 쓰지 않지만, 남아 있다고 파일을 못 읽으면 사용자는 자기가
    안 건드린 이유로 앱을 못 켭니다. 모르는 항목은 조용히 지나갑니다.
    """
    text = """
default_environment: paper
paper:
  domestic:
    app_key: "PAPERDOM123"
    app_secret: "PAPERDOMSECRET456"
    account: "111111111111"
"""
    config = load_config(write(tmp_path, text))
    market = config.market("domestic")

    assert market.app_key == "PAPERDOM123"
    assert not hasattr(market, "account")


def test_형식이_깨진_파일은_거부한다(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "default_environment: paper\n  잘못된: 들여쓰기\n:::\n"))


# --- 마스킹 -------------------------------------------------------------------


def test_masked는_인증정보를_그대로_노출하지_않는다(tmp_path):
    config = load_config(write(tmp_path, VALID))
    dumped = str(config.masked())

    assert "PAPERDOM123" not in dumped
    assert "PAPERDOMSECRET456" not in dumped
    assert "REALOVSSECRET456" not in dumped
    assert "111111111111" not in dumped
    assert config.masked()["default_environment"] == "paper"
