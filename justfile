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

# 프로덕션 빌드 (프론트엔드를 backend/static 으로 빌드하여 백엔드가 서빙)
build:
    cd frontend && npm run build

# 데스크톱 앱 패키징 — 프론트엔드 빌드 후 단일 실행 파일 생성 (desktop/dist/NH FUTURES API.exe)
package: build
    uv run pyinstaller build/nhfutures.spec --distpath desktop/dist --workpath desktop/build --noconfirm

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
