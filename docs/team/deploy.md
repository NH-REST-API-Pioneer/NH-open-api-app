# 서버에 배포하기 — Docker + Cloudflare Tunnel + Access

내 서버에서 앱을 도커로 띄우고, **나와 팀원만** `https://nh.<내 도메인>` 링크로 들어오게 한다.

- 서버 포트는 하나도 열지 않는다. 밖에서는 Cloudflare Tunnel로만 들어온다.
- 누가 들어올 수 있는지는 Cloudflare Access(이메일 허용 목록)가 정한다.
- 앱에는 자체 로그인이 없다. 그래서 **Access가 유일한 문**이다.

```
브라우저 → Cloudflare(Access: 이메일 코드 로그인) → Tunnel → [서버] cloudflared → app:8000
```

## 준비물

- 도커를 설치할 수 있는 서버(리눅스 권장). 외부에서 서버로 들어오는 포트는 열 필요가 없다(나가는 연결만 있으면 된다).
- Cloudflare 계정(무료 플랜으로 된다).
- 도메인 하나.

## 1. 도메인을 Cloudflare에 올린다

1. 도메인을 산다. Cloudflare Registrar에서 사면 이미 Cloudflare에 올라가 있다. 다른 곳에서 샀다면 Cloudflare 대시보드에서 **Add a domain** 으로 추가하고, 안내하는 네임서버로 바꾼다.
2. 도메인 상태가 **Active** 가 될 때까지 기다린다.

## 2. 터널을 만들고 토큰을 복사한다

1. Cloudflare 대시보드 → **Zero Trust** (처음이면 팀 이름을 정하고 Free 플랜을 고른다).
2. **Networks → Tunnels → Create a tunnel** → 종류는 **Cloudflared** → 이름은 `nh` 같이 아무거나.
3. 환경 선택에서 **Docker** 를 고른다. 아래에 `docker run cloudflare/cloudflared ... --token <긴 문자열>` 이 나온다.
4. 그 **긴 문자열(토큰)만** 복사해 둔다. 이 값이 5번의 `.env` 에 들어간다. 토큰은 비밀번호와 같다. 메신저·저장소·캡처에 올리지 않는다.
5. 이 화면의 명령은 실행하지 않는다(컴포즈가 대신 띄운다). **Next** 로 넘어간다.

## 3. 공개 호스트 이름을 붙인다

터널 설정의 **Public Hostname** 에서 **Add a public hostname**:

| 칸 | 값 |
|---|---|
| Subdomain | `nh` |
| Domain | 내 도메인 |
| Service Type | `HTTP` |
| URL | `app:8000` |

`app` 은 docker-compose.yml의 서비스 이름이다. 터널 컨테이너와 앱 컨테이너가 같은 컴포즈 망에 있어서 이 이름으로 닿는다.

## 4. Access로 들어올 사람을 제한한다

1. Zero Trust → **Access → Applications → Add an application → Self-hosted**.
2. Application name `nh`, Domain `nh.<내 도메인>`(3번과 같은 주소).
3. 정책(Policy) 추가: Action **Allow**, Include 규칙은 **Emails** 로 내 이메일과 팀원 이메일을 하나씩 적는다.
4. 로그인 방법은 **One-time PIN**(이메일로 오는 일회용 코드)을 켠다. Zero Trust 설정의 Authentication에서 기본으로 켜져 있다.
5. 저장한다.

**허용(Allow) 정책이 없으면 Access는 모두 거부한다. 정책을 저장한 뒤 6번에서 허용 목록에 없는 이메일로도 시도해 막히는지 반드시 확인한다.**

## 5. 서버에서 띄운다

```bash
# 도커 설치(우분투 예시 — 다른 배포판은 https://docs.docker.com/engine/install/)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # 다시 로그인해야 적용된다

git clone <저장소 주소> nh-open-api-app
cd nh-open-api-app
git checkout <배포할 브랜치>       # 예: main

cp .env.example .env
nano .env                          # TUNNEL_TOKEN= 뒤에 2번에서 복사한 토큰을 붙여 넣는다

docker compose up -d --build
docker compose ps                  # app 이 healthy, cloudflared 가 running 이면 된다
```

`.env` 는 `.gitignore` 에 들어 있어 커밋되지 않는다. 토큰이 없으면 컴포즈가 시작을 거부한다.

## 6. 접속하고 모의 키를 넣는다

1. `https://nh.<내 도메인>` 을 연다. Cloudflare 로그인 화면이 나온다.
2. 허용 목록의 이메일을 적으면 코드가 메일로 온다. 코드를 넣으면 앱 화면이 열린다.
3. 허용 목록에 **없는** 이메일로도 시도해서 막히는지 확인한다.
4. 앱의 **⚙ 설정 → 인증 정보** 에서 NH **모의** 키(국내/해외)를 넣는다. 실전 키는 넣지 않는다.
5. 키는 서버의 도커 볼륨(`/data/NHFutures/config/config.yaml`)에만 저장된다. 이미지와 저장소에는 들어가지 않는다.

## 7. 업데이트

```bash
cd nh-open-api-app
git pull
docker compose up -d --build
```

볼륨은 그대로라 키와 기록이 남는다. 앱이 새로 뜨는 동안 잠깐(수 초~수십 초) 접속이 끊긴다. 11번도 읽는다.

## 8. 로그 보기

```bash
docker compose logs -f app            # 앱
docker compose logs -f cloudflared    # 터널 (접속이 안 될 때 먼저 본다)
docker compose ps                     # 상태·healthcheck
```

## 9. 백업과 복구

데이터는 `nhdata` 볼륨 하나에 있다(키, 토큰, 전략 파일, 실행 기록, 종목 마스터). 컴포즈는 볼륨 이름 앞에 프로젝트 이름을 붙인다(보통 폴더 이름). 먼저 실제 이름을 확인한다.

```bash
docker volume ls | grep nhdata        # 예: nh-open-api-app_nhdata
```

백업(현재 폴더에 `nhdata-날짜.tar.gz` 생성). 일관된 백업을 위해 앱을 잠시 멈추고 한다:

```bash
docker compose stop app
docker run --rm -v nh-open-api-app_nhdata:/data -v "$PWD":/b alpine \
  tar czf /b/nhdata-$(date +%Y%m%d).tar.gz -C /data .
docker compose start app
```

복구(같은 이름의 새 볼륨에 푼다. **현재 내용 위에 덮어쓴다**):

```bash
docker compose stop app
docker run --rm -v nh-open-api-app_nhdata:/data -v "$PWD":/b alpine \
  sh -c "cd /data && tar xzf /b/nhdata-20261103.tar.gz && chown -R 10001:10001 /data"
docker compose start app
```

백업 파일에는 **NH 키가 들어 있다.** 저장소에 넣지 말고, 서버 밖으로 옮길 때는 암호화한다.

## 10. 멈추기

```bash
docker compose down        # 컨테이너만 지운다. 데이터(볼륨)는 남는다
docker compose up -d       # 다시 켠다
```

**`docker compose down -v` 는 볼륨까지 지워 키와 기록이 사라진다.** 쓰지 않는다.

## 11. 알아둘 것

- **끄거나 재시작하면 열린 포지션을 정리한다.** 앱이 지금도 꺼질 때 돌던 전략 실행에 중지를 요청하고, 서버가 다시 뜰 때 계좌 실행은 잔고를 맞춰 본 뒤 끝낸다(자동 재개 없음). `docker compose up -d --build` 로 업데이트하는 것도 같다. 장중에는 업데이트하지 않는다.
- **앱은 볼륨 하나당 하나만 띄운다.** 같은 볼륨을 두 컨테이너가 쓰면 같은 전략을 두 번 돌리거나 같은 주문을 두 번 낼 수 있다. 서버를 옮길 때는 옛 서버를 먼저 `down` 한다.
- **앱에는 자체 로그인이 없다.** 그래서 `docker-compose.yml` 에 `ports:` 를 절대 넣지 않는다(넣으면 서버 IP로 누구나 주문 화면에 들어온다). 막는 것은 Cloudflare Access뿐이다. 허용 목록에서 사람을 뺄 때는 Access 정책에서 지우고, 이미 로그인한 세션은 Zero Trust → Users 에서 취소한다.
- 서버 시계는 컨테이너가 `Asia/Seoul` 로 맞춘다. 서버 자체 시계가 틀리면 NH 인증이 거절될 수 있으니 서버에서 시간 동기화(NTP)가 켜져 있는지 본다.
- 모의/실전 전환은 지금처럼 ⚙ 설정에서 한다. 서버에는 **실전 키를 넣지 않는 것**이 안전장치다.
- 저장소의 `just dev`·`just serve` 로컬 실행은 그대로 쓸 수 있다. 도커는 서버용이다.

## 문제가 생기면

| 증상 | 확인 |
|---|---|
| `docker compose up` 이 `TUNNEL_TOKEN` 이 없다고 함 | `.env` 에 토큰이 들어 있는지, 앞뒤에 따옴표·공백이 없는지 |
| 링크가 Cloudflare 오류(502/1033) | `docker compose logs cloudflared` — 토큰, 그리고 3번의 URL이 `app:8000`(HTTP)인지 |
| 로그인은 되는데 시작·중지·업로드가 「다른 사이트에서 온 요청은 받지 않습니다」 | 앱은 브라우저가 연 주소(Host)와 Origin이 같아야 쓰기 요청을 받는다. 터널 설정에서 Host 머리글을 바꾸는 옵션(HTTP Host Header)을 쓰고 있지 않은지 |
| 메일 코드가 안 온다 | 4번 정책의 이메일 철자, 스팸함 |
| app이 `unhealthy` | `docker compose logs app` |
