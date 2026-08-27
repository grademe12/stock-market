# Backend

Django 6 + Django REST Framework 기반의 독립 API 서버입니다.

## Local setup

프로젝트 루트에서 실행합니다.

```bash
make backend-setup
make backend-migrate
make backend-test
make backend-run
```

개발 서버가 시작되면 `GET http://127.0.0.1:8000/api/v1/health/`는 다음을 반환합니다.

```json
{"status": "ok"}
```

## Container run

프로젝트 루트에서 실행합니다. backend는 Gunicorn **worker 1개**로 실행한다. 현재 호가창은 프로세스 메모리에 있으므로 worker를 늘리면 호가창이 분리되기 때문이다. `--threads 4`는 같은 프로세스 안에서 HTTP 요청을 처리할 수 있게 한다.

```bash
docker compose up --build backend
# 또는 make container-backend-up
```

`http://127.0.0.1:8000/api/v1/health/`는 프로세스 liveness,
`http://127.0.0.1:8000/api/v1/ready/`는 데이터베이스 연결을 포함한 readiness
endpoint다. Compose backend는 별도 PostgreSQL 컨테이너를 사용하며 데이터는 named
volume `postgres-data`에 보존된다. 컨테이너를 내리려면 `make container-down`을
사용한다. volume까지 지우려면 명시적으로 `docker compose down --volumes`를 실행해야 한다.

Compose 설정은 backend 컨테이너를 CPU 1코어(`cpus: "1.0"`)와 메모리 4GiB(`memory: 4G`)로 제한한다. 이는 이미지 자체가 아니라 로컬 Compose 실행 정책이다.

`TRADE_EXECUTION_LOG_ENABLED=1`이면 체결 1건마다 backend 표준 출력에 `event=trade_executed`, 종목·가격·수량·매수/매도 주문 ID를 남긴다. Compose 개발 설정에서는 기본으로 켜져 있어 `docker compose logs -f backend`로 확인할 수 있다. k6처럼 성능을 측정하는 실험에서는 로그 I/O가 결과에 영향을 줄 수 있으므로 `0`으로 끈다.

외부 시장참여자까지 함께 실행하려면 활성 트레이더 프로필을 만든 후 다음을 사용한다.

```bash
docker compose --profile runner up --build
```

재현 가능한 데모는 아래 명령으로 실행한다. `seed_traders`는 선택한 전략의 전용 ID를 사용해 결정론적으로 upsert하며, 직접 만든 다른 트레이더는 변경하지 않는다.

```bash
make demo-up
make demo-seed TRADER_COUNT=100 TRADER_SEED=42
make demo-runner-up
make demo-logs
```

다른 전략 프로필은 `TRADER_STRATEGY`으로 결정론적으로 생성한다.

```bash
make demo-seed TRADER_STRATEGY=momentum TRADER_COUNT=20
make demo-seed TRADER_STRATEGY=mean_reversion TRADER_COUNT=20
make demo-seed TRADER_STRATEGY=liquidity_provider TRADER_COUNT=5
make demo-seed TRADER_STRATEGY=event_reactive TRADER_COUNT=50
```

`event_reactive`는 뉴스 반응용 휴면 풀이다. runner에 `--scenario` 또는 `SCENARIO_PATH`로 fixture를 줄 때만 반응 주문을 낸다.

정리와 상세 실행 순서는 [데모 runbook](../docs/DEMO_RUNBOOK.md)을 참고한다.

## Current API

초기에는 `005930` 종목 하나만 메모리에서 처리합니다.

| Endpoint | 설명 |
|---|---|
| `POST /api/v1/orders/` | 지정가 주문 제출·체결 결과 조회 |
| `DELETE /api/v1/orders/{order_id}/` | 미체결 잔량 주문 취소 |
| `GET /api/v1/books/005930/` | 가격별 호가 잔량 조회 |
| `GET /api/v1/health/` | 프로세스 liveness 확인 |
| `GET /api/v1/ready/` | 데이터베이스 연결 readiness 확인 |
| `GET` / `POST /api/v1/traders/` | 트레이더 환경설정 목록 조회 / 생성 |
| `GET` / `PATCH` / `DELETE /api/v1/traders/{trader_id}/` | 개별 트레이더 환경설정 조회 / 수정 / 삭제 |

주문 API의 입력은 `user_id`, `symbol`, `side` (`BUY` 또는 `SELL`), `price`, `qty`다. 가격과 수량은 양의 정수만 허용한다.

주문 취소는 idempotent하다. 열린 주문은 `status: CANCELED`로 취소되고, 이미 체결·취소되어 호가창에 없는 주문은 `status: ALREADY_CLOSED`로 정상 응답한다. 이는 TTL 기반 runner의 지연 취소를 오류와 구분하기 위한 현재 단계의 계약이다.

트레이더 설정은 PostgreSQL의 `TraderProfile`로 보관하며, 프론트엔드가 위 API를 통해 그대로 편집할 수 있다. 설정에는 이름·가상 사용자 ID·활성화 여부·종목·기준가·가격 단위·가격 오프셋·수량 범위·주문 TTL·개별 실행 주기·seed가 포함된다. 현재 지원 전략은 `noise`, `momentum`, `mean_reversion`, `liquidity_provider`, `event_reactive`이고 종목은 `005930` 하나다. `event_reactive`는 이벤트가 없으면 주문하지 않는다.

모든 트레이더는 backend 밖의 `participant-runner`에서만 실행한다. backend 내부 background thread와 start/stop/manual-tick API는 더 이상 제공하지 않는다. runner는 시작할 때 활성 프로필을 조회하며, `TRADER_IDS` 또는 `MAX_TRADERS`로 실행 대상을 제한한다. 설정 변경은 다음 runner 재시작부터 반영된다.

트레이더 설정 변경은 `DEBUG`가 활성화된 로컬 개발 환경에서만 허용한다. runner를 정상 종료하면 runner가 추적 중인 미체결 주문을 취소한다.

Compose 환경은 KRX 참조 데이터와 트레이더 설정을 PostgreSQL에 저장한다. 주문·체결과 호가창은 아직 메모리에만 있으며 backend 재시작 시 초기화된다. 로컬 `make backend-test`는 빠른 단위 테스트를 위해 SQLite를 사용한다.

`DATABASE_ENGINE`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `KRX_API_KEY`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `TRADE_EXECUTION_LOG_ENABLED`는 환경 변수로 설정할 수 있습니다. 기본값은 로컬 개발 전용이며 배포 환경에서는 사용하지 않습니다.

## KRX reference import

`db/.env.example`을 참고해 Git에서 제외된 `db/.env`를 준비한 후 실행한다.

```bash
make db-up
make db-migrate
make import-krx-top100
```

명령은 최근 확정 거래일의 KOSPI 거래대금 상위 100개를 `Symbol`과 `MarketDaily`에 upsert하고 `ReferenceImportRun`에 실행 상태를 기록한다. KRX API의 `유가증권 일별매매정보` 활용승인이 없는 키는 HTTP 401로 거절된다.
