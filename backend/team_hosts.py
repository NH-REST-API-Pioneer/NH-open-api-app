"""이 서버가 어떤 주소(Host)로 불려도 되는지 — DNS 리바인딩 막기(팀).

로컬 서버(`just serve`)에는 로그인이 없다. 공격자가 자기 도메인(`rebind.attacker.tld`)의 DNS 를 나중에 127.0.0.1 로 돌리면
브라우저는 그 페이지를 「같은 출처」로 보고 `Origin` 도 `Host` 도 `rebind.attacker.tld:8000` 인 요청을 이 서버에 보낸다.
그래서 **Host 자체를 허용 목록으로 거른다**: localhost·127.0.0.1 과, 서버 배포에서 환경변수 `NH_PUBLIC_HOSTS` 로 적은 공개 주소.

    NH_PUBLIC_HOSTS=nh.example.com            (쉼표로 여러 개, 포트 없이)
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

#: 내 컴퓨터를 가리키는 호스트 이름. 개발 서버(vite)가 :5173 에서 :8000 으로 프록시하면 Host 는 127.0.0.1:8000 이다.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def public_hosts() -> frozenset[str]:
    """`NH_PUBLIC_HOSTS`(쉼표로 구분)의 호스트 이름들. 부를 때마다 환경변수를 읽는다. 스킴·포트를 적어도 호스트만 남긴다."""
    names: set[str] = set()
    for item in os.environ.get("NH_PUBLIC_HOSTS", "").split(","):
        item = item.strip()
        if not item:
            continue
        # `*`(와 `*.도메인`)이 목록에 들어가면 TrustedHostMiddleware 가 모든 Host 를 받아 리바인딩 방어가 조용히 꺼진다 → 버린다.
        if "*" in item:
            logging.getLogger(__name__).warning(
                "NH_PUBLIC_HOSTS 에서 와일드카드 항목을 뺐습니다: %r — 공개 주소는 호스트 이름을 하나씩 적어 주세요.", item
            )
            continue
        try:
            host = urlparse("//" + item.split("://")[-1]).hostname
        except ValueError:
            host = None
        if host:
            names.add(host)
    return frozenset(names)


def allowed_host_patterns() -> list[str]:
    """`TrustedHostMiddleware` 에 넘길 목록. 앱을 만들 때 한 번 읽는다.

    Starlette 는 Host 를 `:` 앞까지만 잘라 견주므로 `[::1]:8000` 같은 IPv6 주소 표기는 어느 쪽이든 맞지 않는다 —
    `http://localhost:8000` 으로 연다(그래서 `::1` 은 목록에 넣지 않는다)."""
    return sorted({"localhost", "127.0.0.1"} | public_hosts())
