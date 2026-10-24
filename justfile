# NH선물 Open API 태스크 러너
# 사용법: `just` 만 입력하면 사용 가능한 명령 목록이 출력됩니다.

# Windows에서는 cmd.exe 로 recipe를 실행합니다.
# just의 기본값은 `sh` 인데, Git for Windows의 sh.exe 는 PATH에 등록되지 않는
# usr\bin 에 설치되므로 일반 사용자 환경에서는 찾지 못합니다.
set windows-shell := ["cmd.exe", "/c"]

# 회사 망처럼 HTTPS 를 중간에서 다시 서명하는 곳에서는 uv 와 Node 가 제 인증서 목록만
# 믿어 내려받기가 막힙니다. 검증을 끄지 않고 운영체제의 인증서 저장소를 쓰게 합니다.
export UV_SYSTEM_CERTS := "1"
export NODE_OPTIONS := "--use-system-ca"

default:
    @just --list

# ---------------------------------------------------------------------------
# 통합 명령
# ---------------------------------------------------------------------------

# 전체 의존성 설치 (백엔드 + 프론트엔드)
setup: setup-backend setup-frontend

# 개발 모드 실행 — 백엔드(8000) + 프론트엔드(5173) 동시 hot reload, 접속은 5173
[parallel]
dev: dev-backend dev-frontend

# 백엔드 테스트 실행
test:
    uv run pytest

# 프론트엔드 타입 검사 (tsconfig.json 은 참조만 가진 해답 파일이라 tsc --noEmit 을 그대로 쓰면 아무것도 검사하지 않음)
typecheck:
    cd frontend && npm run typecheck

# 코드 검사 — 백엔드(ruff) + 프론트엔드(eslint). 설정은 pyproject.toml 의 [tool.ruff] 와 frontend/eslint.config.js
lint:
    uv run ruff check .
    cd frontend && npm run lint

# 프로덕션 빌드 (프론트엔드를 backend/static 으로 빌드하여 백엔드가 서빙)
build:
    cd frontend && npm run build

# 팀: 데스크톱 실행 파일(`just package`) 대신 로컬 서버로 띄우고 브라우저로 봅니다.
# 로컬 서버 실행 — 화면 빌드 후 백엔드 하나가 화면과 API 를 함께 서빙, 접속은 http://localhost:8000
# reload 가 없어 코드를 저장해도 재시작되지 않습니다(장중 실행용). 맥에서 잠들지 않게: `caffeinate -dims just serve`
serve: build serve-only

# 화면 빌드 없이 로컬 서버만 실행 (backend/static 이 이미 있을 때)
serve-only:
    uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# ---------------------------------------------------------------------------
# Backend (Python + FastAPI)
# ---------------------------------------------------------------------------

# 백엔드 Python 의존성 설치 (uv sync)
setup-backend:
    uv sync

# 백엔드 개발 모드 실행 (uvicorn hot reload, http://127.0.0.1:8000)
dev-backend:
    uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# ---------------------------------------------------------------------------
# Frontend (React + TypeScript + Vite)
# ---------------------------------------------------------------------------

# 프론트엔드 Node.js 의존성 설치 (npm install)
setup-frontend:
    cd frontend && npm install

# 프론트엔드 개발 모드 실행 (vite hot reload, http://127.0.0.1:5173)
dev-frontend:
    cd frontend && npm run dev
