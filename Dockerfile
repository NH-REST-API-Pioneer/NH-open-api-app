# syntax=docker/dockerfile:1
# 팀: 서버 배포용 이미지 — 화면(React)을 빌드하고, 백엔드(FastAPI) 하나가 화면과 API 를 함께 서빙한다(`just serve` 와 같은 모양).
# 안내: docs/team/deploy.md. 키·토큰은 이미지에 넣지 않는다 — 앱이 /data/NHFutures/ (볼륨)에 쓴다.

# ---------------------------------------------------------------------------
# 1) 화면 빌드 — 산출물은 /src/backend/static (vite 설정의 outDir 이 ../backend/static)
# ---------------------------------------------------------------------------
FROM node:24-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# 2) 파이썬 의존성 — uv.lock 그대로(--frozen), 개발용 묶음(pytest·ruff)은 뺀다
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS deps
# uv 는 PyPI 에서 버전을 못 박아 설치한다(uv.lock 을 만든 0.7 계열).
RUN pip install --no-cache-dir uv==0.7.18
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
# pyproject 의 [tool.uv] package = false — 프로젝트 자체는 설치하지 않고 의존성만 깐다.
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# 3) 실행 이미지
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm
# tzdata: 장 시간표가 한국 시각(KST)으로 돈다. ca-certificates: NH 서버 HTTPS(truststore 가 시스템 인증서를 쓴다).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# HOME=/data → 앱이 남기는 모든 것(설정·키·토큰·상태·전략·종목 마스터)이 /data/NHFutures/ 에 쌓인다. /data 는 볼륨.
ENV TZ=Asia/Seoul \
    HOME=/data \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 루트가 아닌 사용자. /data 를 이 사용자 소유로 만든 뒤 VOLUME 을 선언해야 새 볼륨이 같은 소유로 시작한다.
RUN useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data
VOLUME /data

WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY backend/ ./backend/
# 전략 파일 작성 규칙 문서 — /api/team/pyrun/convention 이 읽는다.
COPY docs/team/strategy-file-convention.md ./docs/team/strategy-file-convention.md
COPY --from=web /src/backend/static ./backend/static

USER app
EXPOSE 8000

# 밖(인터넷)에서 오는 요청은 cloudflared 컨테이너만 compose 내부망으로 보낸다 → 전달 머리글(--proxy-headers)을 믿는다.
# 작업자 하나, reload 없음 — 전략 실행이 이 프로세스 안에서 돈다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
