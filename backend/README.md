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

`http://127.0.0.1:8000/api/v1/health/`가 준비 상태 확인 endpoint다. SQLite의 트레이더 설정은 Docker named volume `backend-data`에 보존된다. 컨테이너를 내리려면 `make container-down`을 사용한다. volume까지 지우려면 명시적으로 `docker compose down --volumes`를 실행해야 한다.

외부 시장참여자까지 함께 실행하려면 활성 트레이더 프로필을 만든 후 다음을 사용한다.

```bash
docker compose --profile runner up --build
```

## Current API

초기에는 `005930` 종목 하나만 메모리에서 처리합니다.

| Endpoint | 설명 |
|---|---|
| `POST /api/v1/orders/` | 지정가 주문 제출·체결 결과 조회 |
| `DELETE /api/v1/orders/{order_id}/` | 미체결 잔량 주문 취소 |
| `GET /api/v1/books/005930/` | 가격별 호가 잔량 조회 |
| `GET /api/v1/health/` | 서버 상태 확인 |
| `GET` / `POST /api/v1/traders/` | 트레이더 환경설정 목록 조회 / 생성 |
| `GET` / `PATCH` / `DELETE /api/v1/traders/{trader_id}/` | 개별 트레이더 환경설정 조회 / 수정 / 삭제 |
| `POST /api/v1/simulations/participants/tick/` | NoiseTrader 시뮬레이션 한 tick 실행 |
| `POST /api/v1/simulations/participants/start/` | NoiseTrader background 실행 시작 |
| `GET` / `DELETE /api/v1/simulations/participants/` | 참여자 시뮬레이션 상태 조회 / 중지 |

주문 API의 입력은 `user_id`, `symbol`, `side` (`BUY` 또는 `SELL`), `price`, `qty`다. 가격과 수량은 양의 정수만 허용한다.

트레이더 설정은 SQLite의 `TraderProfile`로 보관하며, 프론트엔드가 위 API를 통해 그대로 편집할 수 있다. 설정에는 이름·가상 사용자 ID·활성화 여부·종목·기준가·가격 단위·가격 오프셋·수량 범위·주문 TTL·개별 실행 주기·seed가 포함된다. 현재 지원 전략은 `noise`, 종목은 `005930` 하나다.

활성화된 설정이 하나 이상 있으면 시뮬레이션은 해당 트레이더들만 실행한다. 설정이 아직 없을 때만 기존 요청의 `participants` 값으로 임시 NoiseTrader를 생성한다. `trader_ids` 배열을 start/tick 요청에 넣으면 실행할 활성 트레이더를 명시적으로 고를 수 있다. 설정 변경은 다음 시뮬레이션 시작에 반영한다.

트레이더 설정 변경과 참여자 시뮬레이션 제어는 `DEBUG`가 활성화된 로컬 개발 환경에서만 허용한다. `NoiseTrader`는 재현 가능한 seed를 기반으로 여러 가상 사용자의 매수·매도 지정가 주문을 생성한다. 시뮬레이션을 중지하면 남은 봇 주문은 취소된다.

초기 단계는 SQLite를 사용합니다. 주문·체결 이력을 재시작 후에도 보존해야 할 실제 필요가 확인되면 PostgreSQL로 전환합니다.

`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_DB_PATH`는 환경 변수로 설정할 수 있습니다. 기본값은 로컬 개발 전용이며 배포 환경에서는 사용하지 않습니다.
