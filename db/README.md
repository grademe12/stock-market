# Local PostgreSQL

로컬 머신이 트레이더 프로필과 KRX 참조 데이터의 영속 저장소를 담당한다.
PostgreSQL은 Docker named volume에 저장하고 GCE backend에는 Tailscale로만 공개한다.

```text
db/
├── compose.tailscale.yaml
├── config/
│   ├── postgresql.conf.example
│   └── pg_hba.conf.example
├── scripts/
│   ├── backup.sh
│   ├── restore.sh
│   └── healthcheck.sh
└── backups/                 # dump 파일은 Git 제외
```

## 1. 로컬 개발용 실행

환경 파일을 만든 뒤 PostgreSQL만 실행한다.

```bash
cp db/.env.example db/.env
cp db/postgres.env.example db/postgres.env
make db-up
make db-health
```

`db/.env`에는 KRX API key, `db/postgres.env`에는 PostgreSQL database, user,
password가 들어간다. 두 파일은 Git과 Docker build context에서 제외된다.

기본 Compose에는 PostgreSQL host port가 없다. 로컬 backend는 Compose 내부
`postgres:5432`로 접속한다.

## 2. GCE에 Tailscale로 공개

설정 예제를 복사하고 `pg_hba.conf`의 placeholder를 GCE backend의 Tailscale
IPv4로 교체한다.

```bash
cp db/config/postgresql.conf.example db/config/postgresql.conf
cp db/config/pg_hba.conf.example db/config/pg_hba.conf
tailscale ip -4
```

현재 머신의 Tailscale IPv4에만 host port를 bind한다.

```bash
export POSTGRES_BIND_ADDRESS="$(tailscale ip -4)"
make db-tailscale-up
make db-health
```

실제 실행 구성은 다음 두 Compose 파일을 합친 결과다.

```bash
docker compose \
  -f compose.yaml \
  -f db/compose.tailscale.yaml \
  config
```

공유기나 공인 interface에 `5432`를 포트 포워딩하지 않는다. Tailnet ACL에서도
`tag:stock-market-backend`에서 이 머신의 `5432`로 오는 연결만 허용한다.

Docker Desktop이 원격 주소를 내부 gateway로 변환하는 환경에서는 PostgreSQL 로그의
`client=` 주소를 확인해 `pg_hba.conf`에 해당 subnet을 추가해야 할 수 있다. 이 경우에도
host bind와 Tailnet ACL은 그대로 유지한다.

## 3. 백업과 복구

timestamp가 포함된 custom-format dump를 `db/backups/`에 생성한다.

```bash
make db-backup
```

복구는 기존 schema object를 교체하는 파괴적 작업이므로 backend를 먼저 중지하고
명시적인 확인값을 전달한다.

```bash
RESTORE_CONFIRM=stock_market \
  make db-restore BACKUP_FILE=db/backups/stock_market-YYYYMMDDTHHMMSSZ.dump
```

named volume은 컨테이너 재생성에는 유지되지만 디스크 장애를 막지 못한다. dump를
주기적으로 이 머신 밖의 별도 위치에 복사하고 실제 restore를 검증한다.

## 4. 데이터와 migration 소유권

PostgreSQL data는 `postgres-data` named volume에 저장된다. Django가 application
schema를 소유하므로 migration은 계속 `backend/exchange/migrations/`에서만 관리한다.
`db/`에는 별도의 schema migration 체계를 만들지 않는다.
