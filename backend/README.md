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

## Current API

초기에는 `005930` 종목 하나만 메모리에서 처리합니다.

| Endpoint | 설명 |
|---|---|
| `POST /api/v1/orders/` | 지정가 주문 제출·체결 결과 조회 |
| `DELETE /api/v1/orders/{order_id}/` | 미체결 잔량 주문 취소 |
| `GET /api/v1/books/005930/` | 가격별 호가 잔량 조회 |
| `GET /api/v1/health/` | 서버 상태 확인 |

주문 API의 입력은 `user_id`, `symbol`, `side` (`BUY` 또는 `SELL`), `price`, `qty`다. 가격과 수량은 양의 정수만 허용한다.

초기 단계는 SQLite를 사용합니다. 주문·체결 이력을 재시작 후에도 보존해야 할 실제 필요가 확인되면 PostgreSQL로 전환합니다.

`DJANGO_SECRET_KEY`와 `DJANGO_DEBUG`는 환경 변수로 설정할 수 있습니다. 기본값은 로컬 개발 전용이며 배포 환경에서는 사용하지 않습니다.
