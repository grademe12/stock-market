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

초기 단계는 SQLite를 사용합니다. 주문·체결 이력을 재시작 후에도 보존해야 할 실제 필요가 확인되면 PostgreSQL로 전환합니다.

`DJANGO_SECRET_KEY`와 `DJANGO_DEBUG`는 환경 변수로 설정할 수 있습니다. 기본값은 로컬 개발 전용이며 배포 환경에서는 사용하지 않습니다.
