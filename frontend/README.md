# Frontend dashboard

Next.js 기반의 읽기 전용 시장 시뮬레이션 운영 대시보드다. 브라우저는 Next.js의
동일 origin API만 호출하고, Next.js Route Handler가 Tailscale을 통해 GCE Django
backend로 요청을 전달한다.

## 현재 범위

- backend liveness와 PostgreSQL readiness, 응답시간 표시
- KRX 최신 거래일의 KOSPI 거래대금 상위 100종목 검색
- 시뮬 대상 종목의 매수·매도 호가 polling
- 최대 50건의 최근 체결 polling
- 기준정보만 있고 matcher가 없는 종목은 `REFERENCE ONLY`로 표시

주문 입력, 트레이더 설정 변경, 인증, WebSocket, Prometheus 지표와 공개 인터넷
접속은 현재 범위에 포함하지 않는다.

## Local development

Git에서 제외되는 로컬 설정을 준비한다.

```bash
cd frontend
cp .env.example .env
```

```dotenv
BACKEND_BASE_URL=http://stock-market-gce.example-tailnet.ts.net:8000
FRONTEND_BIND_ADDRESS=127.0.0.1
```

개발 서버를 실행한다.

```bash
npm install
npm run dev
```

`http://127.0.0.1:3000`에서 확인한다.

## Mini PC container

Linux host networking을 사용해 컨테이너가 호스트의 Tailscale DNS와 네트워크에
접근한다. `.env`의 `FRONTEND_BIND_ADDRESS`에는 미니 PC의 Tailscale IPv4를 넣어
LAN이나 인터넷 인터페이스에 대시보드를 공개하지 않는다.

```dotenv
BACKEND_BASE_URL=http://stock-market-gce.example-tailnet.ts.net:8000
FRONTEND_BIND_ADDRESS=100.64.0.1
```

프로젝트 루트에서 실행한다.

```bash
docker compose -f frontend/compose.yaml up -d --build
docker compose -f frontend/compose.yaml ps
docker compose -f frontend/compose.yaml logs -f dashboard
```

종료한다.

```bash
docker compose -f frontend/compose.yaml down
```

컨테이너는 production standalone build를 사용하고 `/api/health`로 자체 healthcheck를
수행한다. `restart: unless-stopped` 정책으로 Docker 재시작 후 자동 복구한다.

## Verification

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
npm audit --omit=dev
```

대시보드 데이터는 다음 backend API를 사용한다.

- `GET /api/v1/health/`
- `GET /api/v1/ready/`
- `GET /api/v1/symbols/?q=&limit=20`
- `GET /api/v1/books/{symbol}/`
- `GET /api/v1/trades/?symbol={symbol}&limit=50`
