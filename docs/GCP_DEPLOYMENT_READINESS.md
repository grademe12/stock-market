# GCP 배포 준비와 로컬 PostgreSQL 결정

> 결정일: 2026-08-27 KST

## 결정

현재 단계의 기본 DB는 Cloud SQL이 아니라 소유한 로컬 머신의 PostgreSQL 17로
운영한다. GCE backend와 local participant-runner는 Tailscale 사설망으로 연결한다.

이 결정의 근거:

- 실제 서비스가 아니며 GCP 자원은 실험할 때만 켠다.
- PostgreSQL은 트레이더 프로필과 KRX 참조 데이터에만 사용된다.
- 주문·체결·호가창은 아직 backend 메모리에 있어 DB가 주문 hot path가 아니다.
- Cloud SQL의 상시 비용과 중지·재개 관리보다 로컬 데이터 보존이 현재 목적에 맞다.

Stage 5에서 주문과 체결을 영속화할 때는 WAN 지연과 로컬 회선 장애가 주문 경로에
직접 영향을 주므로 이 결정을 다시 검토한다.

## 목표 구조

```text
Local machine
  PostgreSQL 17
  participant-runner
       | encrypted Tailscale network
       v
GCE backend VM
  custom image: Docker + Tailscale + gcloud
  Django/Gunicorn container
```

인터넷에는 PostgreSQL `5432`와 backend `8000`을 공개하지 않는다. GCE의 ephemeral
external IP는 package, Tailscale, Artifact Registry 등 outbound 통신에만 사용한다.

## 적용된 코드 경계

- Cloud SQL instance, user, database 및 Auth Proxy 제거
- VM의 `roles/cloudsql.client` 제거
- Tailscale, PostgreSQL password, Django key용 Secret Manager 구성
- VM service account에 secret별 accessor 권한 부여
- Docker·Tailscale·gcloud가 포함된 custom image family 사용
- startup script가 Tailscale 등록과 root 전용 backend env 파일 생성
- GitHub OIDC를 `main`과 deploy workflow로 제한
- 새 backend readiness 실패 시 이전 컨테이너 복구
- liveness `/health/`와 DB readiness `/ready/` 분리

## 첫 apply 전 체크리스트

- `terraform state list`에 기존 Cloud SQL 데이터가 없는지 확인
- `stock-market-base` custom image family 생성
- 환경별 Terraform backend config에서 `infra/dev` prefix 확인
- `postgres_host`를 local DB의 Tailscale IP 또는 MagicDNS로 설정
- `django_allowed_hosts`를 backend Tailscale hostname으로 설정
- Terraform으로 Secret Manager secret 컨테이너와 IAM 생성
- 세 secret에 실제 version 등록
- Tailscale ACL의 tag owner와 접근 규칙 설정
- local PostgreSQL application user와 database 생성
- `listen_addresses`, `pg_hba.conf`, host firewall 검증
- PostgreSQL backup과 restore 절차 확인

## 첫 배포 완료 조건

1. GCE VM 재부팅 후 Tailscale이 자동 재연결된다.
2. `/etc/stock-market/backend.env`가 root `600` 권한으로 생성된다.
3. GCE에서 local PostgreSQL에 접속할 수 있다.
4. 인터넷에서 VM `8000`과 local `5432`에 직접 접근할 수 없다.
5. `GET /api/v1/health/`와 `GET /api/v1/ready/`가 모두 200이다.
6. local runner가 Tailscale hostname으로 프로필 조회와 주문을 수행한다.
7. 새 backend가 DB에 연결하지 못하면 이전 컨테이너가 복구된다.

## 수용하는 한계

- local 정전, 재부팅, ISP 장애 시 profile·reference DB 기능이 중단된다.
- WAN 지연과 jitter가 profile 조회와 KRX import 측정에 포함된다.
- 단일 matcher이므로 backend 배포 시 메모리 주문과 호가창은 초기화된다.
- Tailscale control plane 또는 DERP 의존성이 추가된다.
- auth key 만료 또는 일회용 key 소비 시 VM 재생성 전에 secret rotation이 필요하다.

이 한계는 실험 조건과 운영 보고서에 명시한다.

## 후속 검토 시점

다음 중 하나가 발생하면 DB 위치를 다시 결정한다.

- 주문·체결 영속화가 주문 latency에 포함될 때
- local DB 장애가 정규장 자동 운영을 반복적으로 방해할 때
- 외부 사용자가 접근하는 실제 서비스로 전환할 때
- Cloud SQL 운영 경험 자체가 별도 학습 목표가 될 때
