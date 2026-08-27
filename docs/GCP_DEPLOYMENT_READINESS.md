# GCP 배포 준비와 데이터베이스 선택

> 기준일: 2026-08-27 KST
>
> 이 문서는 현재 인프라 작업의 최우선 순위와 첫 GCP 배포 전에 해결할 항목을 기록한다. 실제 리소스 생성은 각 항목을 확인한 뒤 진행한다.

## 1. 현재 최우선 순위

현재 Terraform state에는 관리 중인 VM과 Cloud SQL이 없다. 검토용 값으로 실행한 plan은 `32 add, 0 change, 0 destroy`였으며, 아직 `terraform apply`하지 않았다.

### P0 — apply 전에 반드시 처리

| 항목 | 현재 상태 | 완료 조건 |
|---|---|---|
| GitHub의 VM 서비스 계정 사용 권한 | 코드 추가, 미적용 | GitHub 배포 서비스 계정에 backend 서비스 계정의 `roles/iam.serviceAccountUser` 적용 |
| Terraform 필수 변수 | 미완료 | `github_repository`, `cloud_sql_password`를 Git 제외 `terraform.tfvars`에 추가 |
| runner 허용 IP | 예제값 | `runner_source_cidr`를 실제 로컬 runner PC의 공인 IP `/32`로 교체 |
| OS Login API 관리 | GCP에는 활성화됐지만 Terraform 외부 | `oslogin.googleapis.com`을 Terraform의 필수 API에 포함 |
| 배포 대상 브랜치 | `main`, `infra`가 같은 VM 사용 | 실제 배포는 `main`만 허용하거나 브랜치별 환경을 분리 |
| 실패 시 복구 | 미구현 | 새 backend가 건강하지 않으면 기존 컨테이너를 복구하거나 유지 |

### P1 — 첫 자동 배포 전에 처리

| 항목 | 현재 상태 | 완료 조건 |
|---|---|---|
| Cloud SQL Auth Proxy | `2.15.2` 고정 | 검증한 최신 v2 버전으로 갱신하고 이미지 digest 또는 명시 버전 고정 |
| Workload Identity 제한 | 저장소 이름만 검사 | 허용 branch 또는 workflow를 조건에 포함하고 가능하면 GitHub 숫자 ID 사용 |
| GitHub Actions Variables | 미등록 | Terraform output의 8개 값을 저장소 Variables에 등록 |
| VM backend 환경 파일 | 없음 | `/etc/stock-market/backend.env`를 root 전용 권한으로 생성 |
| 첫 배포 검증 | 미수행 | migration, Proxy 연결, backend health, 로컬 runner 연결 확인 |

최근 GitHub Actions의 성공 표시는 GCP 변수가 없어서 deploy job이 건너뛰어진 결과다. 테스트 성공과 실제 GCP 배포 성공을 구분한다.

## 2. 권장 진행 순서

```text
P0 코드 보완
  -> terraform fmt / validate / plan
  -> terraform apply
  -> GitHub Actions Variables 등록
  -> VM backend.env 생성
  -> main workflow 수동 실행
  -> VM health와 Cloud SQL 연결 확인
  -> 로컬 external runner 연결
  -> 뉴스 fixture spike 측정
```

Terraform state 버킷은 현재 버전 관리와 uniform bucket-level access가 활성화돼 있고 공개 IAM 주체는 없다.

## 3. 집 미니 PC에서 PostgreSQL을 운영하는 선택

### 결론

기술적으로 가능하다. 현재 주문·체결·호가창은 backend 메모리에 있고 PostgreSQL은 트레이더 프로필과 KRX 참조 데이터에만 사용되므로, 현재 단계에서는 DB 왕복 지연이 주문 API의 핵심 경로에 거의 들어오지 않는다.

하지만 포트폴리오의 기본 GCP 구성으로는 Cloud SQL을 유지하는 편이 낫다. 집 DB는 비용 절감 실험 또는 장애·네트워크 관찰용 선택 구성으로만 권장한다. Stage 5에서 주문과 체결을 영속화하면 WAN 지연과 집 회선 장애가 매 주문 경로에 직접 영향을 주므로 기본 구성으로 사용하지 않는다.

### 가능한 구조

```text
Compute Engine backend
        |
        | encrypted private tunnel
        v
집 미니 PC PostgreSQL 17
  - Docker volume 또는 전용 데이터 디스크
  - 주기적 backup
  - tunnel 주소만 pg_hba.conf에서 허용
```

공유기의 TCP 5432를 인터넷에 직접 포트 포워딩하는 구성은 사용하지 않는다. WireGuard처럼 암호화된 사설 tunnel을 사용하고 PostgreSQL은 tunnel 인터페이스에서만 접근 가능하게 제한한다. PostgreSQL 자체 TLS를 함께 사용하면 방어 계층과 서버 신원 검증을 추가할 수 있다.

### 장점

- Cloud SQL의 상시 compute·storage·backup 비용을 줄일 수 있다.
- 미니 PC의 CPU, 메모리와 디스크를 자유롭게 확장할 수 있다.
- PostgreSQL 운영, 백업, 복구, 모니터링을 직접 학습할 수 있다.
- 현재처럼 DB가 주문 매칭 핵심 경로 밖에 있을 때는 성능 영향이 비교적 작다.

### 단점

- 정전, 공유기 재부팅, ISP 장애가 곧 backend DB 장애가 된다.
- 동적 공인 IP와 CGNAT 환경에서는 GCE와의 안정적인 tunnel 구성이 더 복잡하다.
- 서울 GCP와 집 사이의 WAN 지연·jitter가 측정 결과에 섞인다.
- OS·PostgreSQL 보안 업데이트, 디스크 장애, 백업과 복구를 직접 책임져야 한다.
- 집 회선 업로드 대역폭과 데이터 사용 정책에 영향을 받는다.
- Cloud SQL의 자동 백업, PITR, 관리형 장애 복구와 IAM 기반 접속을 잃는다.
- 향후 주문·체결 영속화 시 WAN 장애가 거래 요청 실패로 바로 이어진다.

### 최소 운영 조건

- PostgreSQL 17과 영속 volume 또는 전용 SSD
- `scram-sha-256` 인증과 별도 애플리케이션 사용자
- tunnel IP만 허용하는 `listen_addresses`, 방화벽, `pg_hba.conf`
- DB 포트의 인터넷 직접 공개 금지
- 최소 일 1회 백업과 미니 PC 밖의 별도 보관 위치
- 정기적인 restore 검증
- 디스크 사용량·SMART, PostgreSQL 상태와 backup 실패 알림
- 재부팅 후 PostgreSQL과 tunnel 자동 기동
- 가능하면 UPS와 유선 네트워크

### Terraform과 배포 변경 범위

집 DB를 선택하면 단순히 `POSTGRES_HOST`만 바꾸는 것으로 끝나지 않는다.

- Cloud SQL instance, database, user 리소스 제거 또는 선택 변수로 비활성화
- backend 서비스 계정의 `roles/cloudsql.client` 제거
- Cloud SQL connection output과 GitHub variable 제거
- VM에서 Cloud SQL Auth Proxy 실행 제거
- GCE와 집 사이의 tunnel 및 필요한 최소 방화벽 규칙 추가
- `backend.env`의 `POSTGRES_HOST`를 tunnel 내부 주소로 변경
- tunnel과 DB가 준비된 뒤 backend를 시작하는 health/retry 처리 추가
- Cloud SQL 비용과 집 전력·장애·운영 시간의 비교 결과 기록

### 선택지 비교

| 선택지 | 비용 | 운영 난이도 | 지연 안정성 | 포트폴리오 적합성 |
|---|---:|---:|---:|---:|
| Cloud SQL `db-f1-micro` | 가장 높음 | 가장 낮음 | 높음 | GCP 관리형 서비스 경험에 적합 |
| GCE VM 내부 PostgreSQL | 중간 | 중간 | 가장 높음 | 저비용 단일 VM 데모에 적합 |
| 집 미니 PC PostgreSQL | 클라우드 비용 가장 낮음 | 가장 높음 | 가장 낮음 | 하이브리드 네트워크 실험에 적합 |

비용 절감만 목적이라면 먼저 backend와 PostgreSQL을 같은 GCE VM에서 실행하는 구성이 집 DB보다 단순하다. 집 미니 PC는 하이브리드 네트워크와 자가 운영 자체를 학습 목표로 삼을 때 선택한다.

## 4. 현재 권장 결정

첫 GCP 배포와 뉴스 spike 기준 측정은 Cloud SQL로 진행한다. 이 기준선을 확보한 뒤 집 미니 PC DB를 별도 구성으로 연결해 다음을 비교한다.

- backend 시작과 profile 조회 지연
- KRX import 시간과 실패율
- tunnel 장애 시 backend 동작
- 집 회선과 GCE 간 RTT·jitter
- 운영 비용과 수동 관리 시간

비교 결과가 나온 뒤 Cloud SQL 유지, GCE 내부 PostgreSQL, 집 미니 PC 중 하나를 다음 기본 구성으로 결정한다.

## 5. 참고 자료

- [PostgreSQL TLS 연결](https://www.postgresql.org/docs/current/ssl-tcp.html)
- [PostgreSQL pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html)
- [WireGuard Quick Start](https://www.wireguard.com/quickstart/)
- [Cloud SQL 가용성](https://docs.cloud.google.com/sql/docs/availability)
