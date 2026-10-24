"""접속 토큰 보관 — 껐다 켜도 다시 받지 않는지.

**사용자 홈을 건드리지 않습니다.** 모든 시험이 `tmp_path` 아래를 가리킵니다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest

from backend.auth.auth_functions import TokenManager
from backend.auth.token_store import (
    TOKENS_PATH,
    Stored,
    TokenStore,
    fingerprint,
    key_of,
)
from backend.config import load_config

CONFIG = """
default_environment: paper
paper:
  base_url: "https://apidemo.example"
  domestic:
    app_key: "PAPERDOM"
    app_secret: "PAPERDOMSECRET"
  overseas:
    app_key: "PAPEROVS"
    app_secret: "PAPEROVSSECRET"
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return load_config(path)


class 발급서버:
    """토큰을 달라고 할 때마다 다른 값을 주고 횟수를 셉니다."""

    def __init__(self, *, lifetime="3600"):
        self.횟수 = 0
        self.lifetime = lifetime

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.횟수 += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"TOKEN{self.횟수}",
                "token_type": "Bearer",
                "expires_in": self.lifetime,
            },
        )


def 관리자(config, 서버, store):
    client = httpx.Client(transport=httpx.MockTransport(서버))
    return TokenManager(config, client=client, store=store)


def test_보관_자리는_설정_폴더_안이다():
    """화면 상태(`state/`)와 섞지 않습니다 — 담긴 것이 인증 자료입니다."""
    assert TOKENS_PATH.parent.name == "config"
    assert TOKENS_PATH.name == "tokens.json"


def test_지문은_키를_남기지_않는다():
    지문 = fingerprint("PAPERDOM")

    assert len(지문) == 16
    assert "PAPERDOM" not in 지문
    assert 지문 != fingerprint("PAPERDOM2")
    assert 지문 == fingerprint("PAPERDOM")


def test_껐다_켜도_다시_받지_않는다(config, tmp_path):
    """이 시험이 이 기능의 존재 이유입니다."""
    서버 = 발급서버()
    자리 = tmp_path / "tokens.json"

    첫번째 = 관리자(config, 서버, TokenStore(자리)).token("domestic")
    # 앱을 껐다 켠 것과 같습니다 — 메모리는 비었고 파일만 남았습니다.
    두번째 = 관리자(config, 서버, TokenStore(자리)).token("domestic")

    assert 서버.횟수 == 1, "두 번째 실행은 파일에서 읽습니다."
    assert 첫번째.access_token == 두번째.access_token


def test_시장마다_따로_담는다(config, tmp_path):
    서버 = 발급서버()
    자리 = tmp_path / "tokens.json"
    관리 = 관리자(config, 서버, TokenStore(자리))

    관리.token("domestic")
    관리.token("overseas")

    담긴것 = TokenStore(자리).read()
    assert set(담긴것) == {key_of("paper", "domestic"), key_of("paper", "overseas")}
    assert 서버.횟수 == 2


def test_만료가_가까우면_다시_받는다(config, tmp_path):
    자리 = tmp_path / "tokens.json"
    TokenStore(자리).put(
        key_of("paper", "domestic"),
        Stored(
            access_token="OLD",
            token_type="Bearer",
            # 여유(1분)보다 적게 남았습니다.
            expires_at=datetime.now() + timedelta(seconds=20),
            fingerprint=fingerprint("PAPERDOM"),
        ),
    )
    서버 = 발급서버()

    토큰 = 관리자(config, 서버, TokenStore(자리)).token("domestic")

    assert 토큰.access_token == "TOKEN1"
    assert 서버.횟수 == 1
    # 못 쓰는 것은 파일에서도 치웁니다.
    assert TokenStore(자리).read()[key_of("paper", "domestic")].access_token == "TOKEN1"


def test_APP_Key_가_바뀌면_담아_둔_것을_버린다(config, tmp_path):
    """옛 키로 받은 토큰은 서버가 안 받습니다."""
    자리 = tmp_path / "tokens.json"
    TokenStore(자리).put(
        key_of("paper", "domestic"),
        Stored(
            access_token="OLD",
            token_type="Bearer",
            expires_at=datetime.now() + timedelta(hours=1),
            fingerprint=fingerprint("다른키"),
        ),
    )
    서버 = 발급서버()

    토큰 = 관리자(config, 서버, TokenStore(자리)).token("domestic")

    assert 토큰.access_token == "TOKEN1"
    assert 서버.횟수 == 1


def test_담긴_파일에_APP_Key_가_없다(config, tmp_path):
    자리 = tmp_path / "tokens.json"
    관리자(config, 발급서버(), TokenStore(자리)).token("domestic")

    글자 = 자리.read_text(encoding="utf-8")
    assert "PAPERDOM" not in 글자
    assert "PAPERDOMSECRET" not in 글자
    assert fingerprint("PAPERDOM") in 글자


def test_깨진_파일은_남기지_않고_지운다(tmp_path):
    """`.broken` 으로 남기면 인증 자료가 파일로 하나 더 굴러다닙니다."""
    자리 = tmp_path / "tokens.json"
    자리.write_text('{"version": 1, "tokens": {"paper:domestic": {"access', encoding="utf-8")

    assert TokenStore(자리).read() == {}
    assert not 자리.exists()
    assert list(tmp_path.glob("*.broken*")) == []


def test_깨진_파일이어도_토큰은_다시_받는다(config, tmp_path):
    자리 = tmp_path / "tokens.json"
    자리.write_text("깨진 내용", encoding="utf-8")
    서버 = 발급서버()

    토큰 = 관리자(config, 서버, TokenStore(자리)).token("domestic")

    assert 토큰.access_token == "TOKEN1"


def test_형식이_다르면_읽지_않는다(tmp_path):
    자리 = tmp_path / "tokens.json"
    자리.write_text(json.dumps({"version": 99, "tokens": {"a": {}}}), encoding="utf-8")

    assert TokenStore(자리).read() == {}


def test_줄_하나가_어긋나면_그_줄만_버린다(tmp_path):
    자리 = tmp_path / "tokens.json"
    자리.write_text(
        json.dumps(
            {
                "version": 1,
                "tokens": {
                    "paper:domestic": {"access_token": "", "expires_at": "2026-09-10 10:00:00"},
                    "paper:overseas": {
                        "access_token": "GOOD",
                        "token_type": "Bearer",
                        "expires_at": "2026-09-10 10:00:00",
                        "key": "abc",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    담긴것 = TokenStore(자리).read()
    assert set(담긴것) == {"paper:overseas"}


def test_버리면_파일에서도_사라진다(config, tmp_path):
    자리 = tmp_path / "tokens.json"
    관리 = 관리자(config, 발급서버(), TokenStore(자리))
    관리.token("domestic")

    관리.forget("domestic")

    assert TokenStore(자리).read() == {}


def test_메모리만_비우면_파일은_그대로다(config, tmp_path):
    """`clear()` 는 이번 실행의 것만 버립니다."""
    자리 = tmp_path / "tokens.json"
    관리 = 관리자(config, 발급서버(), TokenStore(자리))
    관리.token("domestic")

    관리.clear()

    assert key_of("paper", "domestic") in TokenStore(자리).read()


def test_보관_자리가_없으면_파일을_안_만든다(config, tmp_path):
    """재생 모드가 이 길로 돕니다."""
    서버 = 발급서버()
    관리 = TokenManager(
        config, client=httpx.Client(transport=httpx.MockTransport(서버)), store=None
    )

    관리.token("domestic")
    관리.token("domestic")

    assert list(tmp_path.iterdir()) == [tmp_path / "config.yaml"]
    assert 서버.횟수 == 1, "메모리 보관은 그대로 돕니다."


def test_못_적어도_토큰은_나온다(config, tmp_path, monkeypatch):
    """파일에 못 남기는 것은 이번 실행에 손해가 없습니다."""
    자리 = tmp_path / "없는폴더" / "tokens.json"
    store = TokenStore(자리)

    def 못씀(*args, **kwargs):
        raise OSError("못 씁니다")

    monkeypatch.setattr("backend.auth.token_store.write_json", 못씀)

    토큰 = 관리자(config, 발급서버(), store).token("domestic")

    assert 토큰.access_token == "TOKEN1"


def test_설정이_바뀌면_그_자리를_버린다(tmp_path, monkeypatch):
    """설정 화면에서 인증 정보를 고치면 옛 토큰을 안 씁니다."""
    from backend.auth import token_store
    from backend.main import _forget_tokens

    자리 = tmp_path / "tokens.json"
    monkeypatch.setattr(token_store, "default_path", lambda: 자리)
    store = TokenStore(자리)
    for 이름 in (key_of("paper", "domestic"), key_of("paper", "overseas")):
        store.put(
            이름,
            Stored(
                access_token="OLD",
                token_type="Bearer",
                expires_at=datetime.now() + timedelta(hours=1),
                fingerprint="abc",
            ),
        )

    _forget_tokens({"paper": {"domestic": {"app_key": "새키"}}})

    남은것 = TokenStore(자리).read()
    assert set(남은것) == {key_of("paper", "overseas")}


def test_재생_모드는_파일을_안_만든다(tmp_path, monkeypatch):
    """만들어 낸 토큰이 파일에 남으면 다음 실행에서 진짜인 척 섞입니다."""
    from backend.auth import token_store
    from backend.nh_api.session import create_session

    자리 = tmp_path / "tokens.json"
    monkeypatch.setattr(token_store, "default_path", lambda: 자리)

    session = create_session(replay=True)
    try:
        session.tokens.token("domestic")
    finally:
        session.close()

    assert not 자리.exists()


def test_시험에서는_홈을_안_가리킨다():
    """자리를 안 주고 만들어도 사용자 홈이 아닙니다.

    시험 준비(`conftest.py`)가 자리를 임시 폴더로 돌려 둡니다. **규율이 아니라
    기본값이 지킵니다** — 실서버 세션을 만드는 시험이 뒷날 하나 생겨도 진짜
    설정 폴더에 인증 자료가 남지 않습니다. 이 시험이 그 준비를 지킵니다.
    """
    from backend.config import HOME_DIR

    자리 = TokenStore().path

    assert HOME_DIR not in 자리.parents, f"시험이 사용자 홈을 가리킵니다: {자리}"
    assert 자리.name == "tokens.json"


def test_실서버_세션이_받은_토큰은_임시_자리에_담긴다(config, monkeypatch):
    """**시험 준비의 보호가 실제로 걸리는 자리입니다.**

    실서버 세션은 토큰 보관 자리를 스스로 만듭니다(`TokenStore()`). 준비가
    그 자리를 임시 폴더로 돌려 두지 않으면, 가짜 서버에서 받은 토큰이 시험을
    돌린 사람의 진짜 설정 폴더에 써집니다.

    NH선물로는 안 나갑니다 — 세션이 만드는 클라이언트를 가짜 전송로로 바꿔 둡니다.
    """
    from backend.config import HOME_DIR
    from backend.nh_api import session as 세션모듈

    서버 = 발급서버()
    # 바꾸기 전의 진짜 클래스를 잡아 둡니다. 안 그러면 가짜가 가짜를 부릅니다.
    진짜클라이언트 = httpx.Client

    def 가짜클라이언트(*args, **kwargs):
        return 진짜클라이언트(transport=httpx.MockTransport(서버))

    monkeypatch.setattr(세션모듈.httpx, "Client", 가짜클라이언트)

    자리 = TokenStore().path
    assert HOME_DIR not in 자리.parents, "준비가 자리를 안 돌렸습니다."
    진짜자리 = HOME_DIR / "config" / "tokens.json"
    # 있던 파일을 건드리지 않는지 봅니다 — 쓰는 사람 홈에는 진짜 파일이 있을
    # 수 있어, 「없음」이 아니라 「그대로」로 판정합니다.
    앞서 = 진짜자리.stat().st_mtime if 진짜자리.exists() else None

    세션 = 세션모듈.create_session(replay=False, config=config)
    try:
        세션.tokens.token("domestic")
    finally:
        세션.close()

    assert 자리.is_file(), "임시 자리에 담겨야 합니다."
    assert key_of("paper", "domestic") in TokenStore(자리).read()
    뒤에 = 진짜자리.stat().st_mtime if 진짜자리.exists() else None
    assert 뒤에 == 앞서, "사용자 홈의 파일을 건드렸습니다."
