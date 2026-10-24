# NH-open-api-app

NH선물 REST API Pioneer 1기 6팀 저장소입니다. 운영자 프로그램 [NH FUTURES API](https://github.com/PetterChanHyuk/nh-futures-open-api)(원본 `ec7fe0d`)를 포크해 고쳐 씁니다.

**데스크톱 실행 파일 대신, 로컬에서 백엔드 서버를 띄우고 브라우저로 `http://localhost:8000` 에 접속해 씁니다.** 브라우저를 닫아도 백엔드는 계속 돕니다.

```bash
just setup    # 처음 한 번
just serve    # 화면 빌드 → 백엔드 실행 → http://localhost:8000
```

원본과 달라진 점: 데스크톱 창(PyWebView)·실행 파일(PyInstaller)·Windows 설치 도우미(`Setup.exe`, `scripts/bootstrap.ps1`)를 지우고 `just serve` 를 더했습니다. 원본 갱신은 `git fetch upstream && git merge upstream/main` 으로 받습니다. 팀이 고친 자리는 `팀:` 주석으로 찾을 수 있습니다.

---

## 목차

- [이용 시 유의사항](#이용-시-유의사항)
- [시작하기](#시작하기)
- [실행이 되지 않을 때](#실행이-되지-않을-때)
- [개발](#개발)
- [프로젝트 구조](#프로젝트-구조)
- [설정 파일](#설정-파일)
- [주요 기능](#주요-기능)
- [기술 스택과 아키텍처](#기술-스택과-아키텍처)

---

## 이용 시 유의사항

- 실제 거래에 쓰기 전에 반드시 **모의환경에서 충분히 시험**해 주세요.
- 이 코드로 만든 프로그램의 동작과 거래 결과에 대한 최종 확인과 책임은 사용자에게 있습니다.
- 백엔드는 `127.0.0.1` 에만 열려 이 컴퓨터의 브라우저에서만 접속됩니다. 방화벽·백신 프로그램이 막으면 예외로 등록해 주세요.

---

## 시작하기

### 1. NH선물 Open API 신청

1. 모의거래를 신청하고 모의계좌를 개설합니다.
2. 리얼 HTS 의 **[6128] REST API 신청** 화면에서 이용할 계좌를 골라 API 를 신청합니다.
3. 신청이 끝나면 **APP Key** 와 **APP Secret Key** 발급을 확인합니다(카카오톡 알림).

**APP Key 와 APP Secret Key 는 국내와 해외가 따로 발급됩니다.** 모의환경과 운영환경의 인증 정보도 구분해서 쓰세요. 키는 설치 중에 묻지 않고, 프로그램을 처음 켤 때 설정 화면에서 넣습니다.

[👉 NH선물 Open API 신청 및 설정 안내](https://apidev.futures.co.kr/#/)

### 2. 설치하기

`git clone https://github.com/NH-REST-API-Pioneer/NH-open-api-app.git` 으로 받은 뒤, 터미널에서 `justfile` 이 있는 폴더로 이동합니다. Node.js 는 **22.15.0 이상**이어야 합니다 — 운영체제의 인증서 저장소를 쓰는 `NODE_OPTIONS=--use-system-ca` 가 22.15 부터 있기 때문입니다.

```bash
# uv (Python 버전과 의존성을 관리합니다)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node.js 22.15.0 이상 — https://nodejs.org 에서 조건을 만족하는 LTS 설치(npm 포함)

# just (태스크 러너)
brew install just                                                                             # macOS
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/bin  # Linux
# Windows: winget install astral-sh.uv OpenJS.NodeJS.LTS Casey.Just  (설치 후 PowerShell 을 새로 엽니다)

# 설치 확인과 구성 요소 준비
uv --version && node --version && just --version
just setup
```

macOS 의 `brew` 는 Homebrew 가 설치된 환경을 전제로 합니다. Linux 에서 just 를 `~/bin` 에 설치했다면 그 경로가 `PATH` 에 있어야 합니다.

### 3. 처음 실행하기

```bash
just serve
```

화면을 빌드한 뒤 백엔드가 뜹니다. 브라우저로 **http://localhost:8000** 에 접속합니다. 끌 때는 터미널에서 `Ctrl+C` 입니다. 화면을 이미 빌드했다면 `just serve-only` 로 빌드를 건너뜁니다. 맥에서 장중에 켜 둘 때는 잠들지 않게 `caffeinate -dims just serve` 로 띄웁니다.

**지금 접속하는 환경에 인증 정보가 하나도 없으면, 켤 때 설정 화면이 자동으로 열립니다.** 국내·해외 중 한 시장만 채워도 시작할 수 있습니다.

1. **인증 정보** 탭에서 이용할 환경(모의투자 / 실전투자)과 시장(국내 / 해외)의 **APP Key**, **APP Secret Key** 를 넣습니다. 쓰지 않는 칸은 비워 둡니다. 비워 둔 시장은 계좌·일반주문 화면에서 그 시장을 고를 때 인증 정보가 없다고 알려 줍니다.
2. **저장**을 누르면 그 값으로 접속을 한 번 확인하고 결과를 보여 줍니다.
3. 모의투자와 실전투자 중 어디로 접속할지는 **일반** 탭에서 바꿉니다. 처음에는 모의투자입니다.

설정은 언제든 오른쪽 위 **⚙ 설정**에서 바꿉니다. 입력한 값은 사용자 홈의 [설정 파일](#설정-파일)에만 저장되고, 화면에는 가려서 보입니다. 바꾸려는 칸만 다시 입력하면 됩니다.

---

## 실행이 되지 않을 때

| 증상 | 조치 |
| --- | --- |
| 설치를 마쳤는데 명령을 찾지 못합니다 | 터미널(PowerShell) 창을 새로 여세요. 그래도 같으면 로그아웃 후 다시 로그인하세요 |
| `http://localhost:8000` 이 빈 화면·404 입니다 | 화면을 빌드하지 않았습니다. `just serve-only` 대신 `just serve` 로 띄우세요 |
| `address already in use` 로 안 뜹니다 | 이전 서버가 8000 을 쓰고 있습니다. `lsof -i :8000`(Windows `netstat -ano \| findstr :8000`)으로 찾아 끄세요 |
| 방화벽·백신 프로그램이 경고합니다 | 백엔드가 이 컴퓨터 안(127.0.0.1)에서만 받는 연결입니다. 예외로 등록하세요 |
| 켤 때 설정 화면이 열립니다 | 지금 접속하는 환경에 인증 정보가 없습니다. 그 환경의 APP Key 와 APP Secret Key 를 넣으세요 |
| 인증 확인에 실패합니다 | 모의투자 키를 실전투자 칸에 넣었거나 그 반대일 수 있습니다. 환경과 시장을 확인하세요 |

---

## 개발

### 명령 목록

모든 명령은 `just` 로 실행합니다. `just` 만 입력하면 목록이 나옵니다.

| 명령 | 내용 |
| --- | --- |
| `just setup` | 백엔드(`uv sync`)와 프론트엔드(`npm install`) 의존성 설치 |
| `just dev` | 백엔드(8000)와 프론트엔드(5173)를 함께 hot reload 로 실행 |
| `just typecheck` | 프론트엔드 타입 검사 |
| `just lint` | 코드 검사 — 백엔드(ruff), 프론트엔드(eslint) |
| `just test` | 백엔드 테스트 실행 |
| `just build` | 프론트엔드를 `backend/static/` 으로 빌드 |
| `just serve` | 빌드 후 백엔드 하나로 실행(reload 없음) → http://localhost:8000 |
| `just serve-only` | 빌드 없이 백엔드만 실행 |

### 개발 모드

```bash
just dev
```

백엔드와 프론트엔드가 함께 뜹니다. **개발 중에는 http://localhost:5173 을 쓰세요.** `/api` 요청은 개발 서버가 백엔드로 넘기므로 이 주소 하나면 됩니다.

http://127.0.0.1:8000 은 `just build` 로 만든 이전 빌드 결과를 보여 주고 hot reload 가 되지 않습니다. **`just dev` 는 저장할 때마다 백엔드가 재시작되어 돌던 전략도 끊기므로, 장중에는 `just serve` 를 씁니다.** 일반 모드와의 차이는 [개발 모드 비교](docs/development.md#개발-모드)에 있습니다.

> Windows 에서는 이미 쓰는 포트에도 바인딩이 성공합니다. `just dev` 를 다시 켰는데 고친 코드가 반영되지 않으면 이전 서버가 남아 있는지 `netstat -ano | findstr :8000` 으로 확인하세요.

### 저장해 둔 응답으로 실행하기

NH선물 서버에 접속할 수 없는 곳에서 화면을 확인할 때 쓰는 개발용 방식입니다. 환경 변수 `NH_REPLAY` 를 켜면 서버 대신 `tests/fixtures/nh/` 의 저장해 둔 응답으로 답하고, `/api/health` 의 `mode` 가 `replay` 가 됩니다. 화면의 값은 실제 시세나 잔고가 아닙니다.

```bat
set NH_REPLAY=1
just dev
```

PowerShell 에서는 첫 줄을 `$env:NH_REPLAY = "1"` 로 씁니다.

달라지는 동작과 저장해 둔 응답을 만드는 법은 [저장해 둔 응답으로 실행하기](docs/development.md#저장해-둔-응답으로-실행하기)에 있습니다.

### 지켜야 할 규칙 둘

**1) 백엔드 주소는 `/api` 아래에 만듭니다.** `/` 는 화면 파일이 차지하므로 그 밖에 만들면 배포 상태에서 가려집니다.

**2) 화면에서 백엔드를 부를 때는 경로만 적습니다.** 개발(5173)과 로컬 서버(8000)의 주소가 다르므로, 경로만 적어야 두 방식에서 모두 맞습니다.

```ts
fetch("/api/health"); // 이렇게

fetch("http://127.0.0.1:8000/api/health"); // 이렇게 하지 마세요
```

무엇을 고치려면 어느 파일을 보는지는 [어디를 고치면 되나요](docs/development.md#어디를-고치면-되나요)에 있습니다.

---

## 프로젝트 구조

```
NH-open-api-app/
├── backend/                      # Python 백엔드 — FastAPI 서버 + NH선물 API 래퍼
│   ├── main.py                       # 진입점. 기능별 라우터를 /api 아래에 붙이고 화면 정적 파일 서빙
│   ├── config.py                     # 설정 파일 읽기·저장 (사용자 홈의 config.yaml)
│   ├── storage.py                    # 상태 파일 읽기·쓰기 공통 (깨진 파일 처리, 재생 표지)
│   ├── auth/                         # 접속 토큰 발급·갱신·폐기, 웹소켓 접속키
│   ├── nh_api/                       # 거래 API 공통 호출부 — API 목록, 호출 제한, 재생 모드
│   ├── master/                       # 종목 마스터 — 시작 시 내려받기·파싱·색인
│   ├── domestic_futureoption/        # 국내 선물·옵션 API 함수와 마스터 레이아웃
│   ├── overseas_futureoption/        # 해외 선물·옵션 API 함수와 마스터 레이아웃
│   ├── quotes.py, orders.py          # 시세·주문 응답을 두 시장 공통 모양으로 맞추는 규칙
│   ├── realtime/                     # 실시간 시세 허브 (웹소켓 구독·방송)
│   ├── sessions/                     # 장 시간·세션 판정
│   ├── strategy/                     # 전략주문 — 규칙·엔진·종이 장부·모의 계좌·기록·분석 조회
│   ├── ui/                           # 화면 배치·관심 종목 저장
│   └── static/                       # just build 산출물 (저장소에 포함되지 않음)
├── frontend/src/                 # React + TypeScript UI
│   ├── app/                          # 상단 바, 사이드바, 설정 모달, 종목 검색 등 공통 골격
│   ├── screens/                      # 화면 — home, instruments, trade, account, strategy, settings
│   ├── lib/                          # 숫자 표기, 조회 상태, 스파크라인 등 공용 코드
│   ├── data/                         # 서버 호출과 화면 저장소 — 시세·주문·계좌·전략·기록 조회
│   └── assets/                       # CI 마크
├── docs/                         # 개발 안내 상세
├── scripts/
│   ├── check_identifiers.py          # 코드 식별자 규칙 검사
│   └── import_nh_fixtures.py         # 수집한 응답을 테스트용 자료로 반입
├── tests/                        # pytest
│   ├── fixtures/nh/                  # 저장해 둔 NH선물 Open API 응답
│   └── fixtures/master/              # 시험용 종목 마스터
├── config.example.yaml           # 설정 파일 서식 (실제 설정은 ~/NHFutures/config/config.yaml)
├── justfile                      # 태스크 러너 명령 정의
└── pyproject.toml                # Python 의존성과 코드 검사 설정 (uv, ruff)
```

시세·주문 라우트는 각 카테고리 폴더의 `*_routes.py` 에 있습니다.

---

## 설정 파일

설정 화면에서 저장하면 아래 경로에 만들어집니다. 직접 열어 고쳐도 됩니다.

| 운영체제 | 경로 |
| --- | --- |
| Windows | `C:\Users\{사용자 이름}\NHFutures\config\config.yaml` |
| macOS / Linux | `~/NHFutures/config/config.yaml` |

**환경**(모의/실전) 아래에 **시장**(국내/해외)별로 인증 정보를 넣는 구조입니다. 쓰지 않는 환경이나 시장은 비워 둡니다.

```yaml
default_environment: paper # 프로그램을 켤 때 접속할 환경

paper: # 모의투자
  base_url: "" # 접속 주소. 비워 두면 기본값을 씁니다
  domestic: # 국내 선물/옵션
    app_key: ""
    app_secret: ""
  overseas: # 해외 선물/옵션
    app_key: ""
    app_secret: ""

real: # 실전투자 — 구조는 paper 와 같습니다
  base_url: ""
  domestic: { ... }
  overseas: { ... }
```

`default_environment` 는 프로그램 안에서 환경을 바꾸면 함께 바뀌어, 다음에 켤 때 마지막에 쓰던 환경으로 섭니다. 저장소의 `config.example.yaml` 이 같은 구조의 빈 템플릿입니다. **실제 값이 든 설정 파일을 프로젝트 폴더 안에 두지 마세요.**

프로그램은 `~/NHFutures/` 아래에 설정(`config/`)과 함께 종목 마스터(`master/`)와 화면·전략 상태(`state/`)를 남깁니다. **`config` 폴더는 누구에게도 보내지 마세요.** 파일별 내용은 [프로그램이 사용자 폴더에 남기는 것](docs/development.md#프로그램이-사용자-폴더에-남기는-것)에 있습니다.

---

## 주요 기능

아래 홈·일반주문 그림의 계좌 값은 모의투자 계좌의 값입니다. 전략 설정 그림은 [저장해 둔 응답](#저장해-둔-응답으로-실행하기)으로 띄운 화면입니다.

### 인증

- APP Key / APP Secret 으로 접속 토큰 발급(REST / WebSocket 각각)과 자동 갱신
- 모의환경 / 운영환경 구분 접속

### 시세 및 조회

**홈** — 국내·해외 계좌 요약, 주문 내역, 관심종목 시세를 한 화면에 모읍니다.

![홈 화면](docs/images/home.png)

- 국내 선물·옵션 시세(REST / WebSocket) — 주간·야간 세션을 자동으로 판정하고, 야간에는 야간 현재가와 월물별 야간 시세를 보입니다
- 해외 선물·옵션 시세(거래소별 REST / WebSocket)
- 스프레드 종목의 시세·차트(가격이 음수로 오는 종목도 그대로 보입니다)
- 계좌 조회 — 예수금, 잔고, 미체결, 체결, 주문 오류 내역과 추이
- 종목 화면 — 받아 둔 종목 마스터로 국내·해외 상품과 월물을 시장·거래소·선물/옵션별로 찾아봅니다. 옵션 월물을 누르면 옵션 체인이 열립니다

### 주문

**일반주문** — 차트, 호가, 시세체결, 주문 폼, 주문체결상세를 한 화면에서 봅니다.

![일반주문 화면](docs/images/trade.png)

- 국내·해외 선물·옵션 주문과 응답 확인, 미체결 주문의 정정·취소
- 국내 스프레드 종목은 주문할 수 있습니다. 해외 스프레드 종목은 보기만 하고 주문할 수 없습니다

> **주문은 지금 접속해 있는 환경으로 나갑니다.** 실전투자로 두고 주문을 내면 실제 주문이 접수됩니다. 접속 환경은 **⚙ 설정 → 일반** 탭에서 바꾸고, 처음에는 모의투자입니다. 화면에 표시된 환경과 서버가 실제로 접속한 환경이 다르거나 아직 확인되지 않았으면 주문을 보내지 않고 알립니다.

### 전략주문

**전략 설정 편집기** — 진입·청산 규칙을 단계와 조건으로 적고, 오른쪽에서 문장으로 다시 읽어 확인합니다.

![전략 설정 화면](docs/images/strategy-editor.png)

- **전략 설정** — 매수·매도 진입과 청산 규칙을 단계와 조건으로 적습니다. 조건 값은 가격·지표(이동평균, RSI, ATR, 볼린저 밴드, 거래량)·호가·봉 시각·보유 수량과 평가손익입니다. 단계 사이 유효기간, 시간 초과 초기화, 방향별 주문 가격 기준, 손절·익절·추적 청산, 하루 손실·연속 손실 한도를 둘 수 있고, 저장할 수 없는 값은 칸 아래에 미리 알립니다
- **전략 검증** — 앱 안의 시뮬레이션 장부로 실제 시세에 규칙을 돌려 체결·손익을 봅니다. 차트의 체결 표지를 누르면 체결 이유·수수료·체결 당시 지표 값이 보입니다
- **전략 진행** — **계좌로 실제 주문이 나가는** 실행입니다. 모의 계좌와 실전 계좌 두 갈래가 있고, 지금 접속한 환경과 같은 갈래만 세울 수 있습니다. 어느 갈래든 확인창에서 승인해야 시작됩니다. 여러 실행을 함께 중지·청산·종료할 수 있고, 체결 줄에 계좌 주문번호가 남습니다
- **전략 분석** — 기록에서 기간·시장·전략·종목으로 걸러 누적 곡선, 버전 비교, 거래 내역, 체결 품질을 봅니다

> 전략 진행의 주문은 지금 접속한 환경의 계좌로 실제 접수됩니다. 실전투자로 접속해 있으면 실전 계좌로 나갑니다.

### 로컬 서버 실행

- `just serve` 한 줄로 백엔드가 화면과 API 를 함께 서빙
- 브라우저는 보기만 합니다 — 창을 닫아도 백엔드와 전략 실행은 계속 돕니다
- 운영체제 알림은 브라우저 알림(Notification)으로 냅니다. 글씨 크기는 브라우저의 Ctrl + / − 로 바꿉니다

---

## 기술 스택과 아키텍처

| 영역 | 항목 | 역할 |
| --- | --- | --- |
| 백엔드 | Python 3.11+ | 언어 및 런타임 |
| 백엔드 | FastAPI | HTTP API 및 WebSocket 서버 |
| 백엔드 | uv | Python 버전 · 의존성 · 가상 환경 관리 |
| 프론트엔드 | React | UI 라이브러리 |
| 프론트엔드 | TypeScript | 정적 타입 언어 |
| 프론트엔드 | Vite | 개발 서버 및 번들러 |
| 프론트엔드 | npm | Node.js 패키지 관리자 |
| 프론트엔드 | KLineChart | 캔들 차트와 보조지표 |
| 개발 환경 | Node.js 22.15.0+ | 프론트엔드 개발·빌드 및 npm 실행(운영체제 공통) |
| 태스크 러너 | just | 설치 / 개발 / 빌드 / 서버 실행 명령 통합 |

```mermaid
flowchart TB
    User(("사용자"))
    subgraph Local["이 컴퓨터 (just serve)"]
        direction LR
        Browser["브라우저<br/>http://localhost:8000"]
        Backend["Backend<br/>Python + FastAPI<br/>(화면 정적 파일 + /api)"]
        Browser <-->|HTTP / WebSocket| Backend
    end
    NH["NH선물 Open API<br/>REST + WebSocket"]
    User --> Browser
    Backend <-->|HTTPS / WebSocket| NH
```
