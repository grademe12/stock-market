# GCP 인프라 복구·이전·철거 Runbook

> 작성일: 2026-10-10 KST  
> 대상: `infra/`의 Terraform 구성과 Tailscale로 연결된 로컬 PostgreSQL

## 1. 목적

이 문서는 비용 때문에 GCP 실행 인프라를 제거한 뒤 다음 상황에서 동일한 환경을
재구축하기 위한 절차를 기록한다.

- 기존 GCP 프로젝트에서 인프라를 다시 실행한다.
- 다른 GCP 계정의 새 프로젝트나 무료 체험 크레딧으로 이전한다.
- 짧은 실험을 마친 뒤 과금 리소스를 다시 안전하게 철거한다.

Terraform 코드와 애플리케이션 소스가 복구의 기준이다. PostgreSQL 데이터는 GCP가
아니라 로컬 머신의 `db/` 환경에 유지한다. Terraform state나 이 문서에는 실제
비밀번호, API key, Tailscale auth key를 기록하지 않는다.

## 2. 재구축 가능한 범위

Terraform이 생성하는 항목은 다음과 같다.

- custom VPC, subnet, IAP SSH 방화벽
- 단일 Compute Engine backend VM과 boot disk
- Artifact Registry Docker repository
- Tailscale, PostgreSQL, Django용 Secret Manager secret 컨테이너
- backend 및 GitHub Actions service account와 IAM
- GitHub Actions용 Workload Identity Pool과 Provider
- 필요한 GCP API 활성화

다음 항목은 Terraform 밖에서 준비해야 한다.

- GCP 프로젝트, billing 연결, Terraform state용 GCS bucket
- Terraform 실행 주체와 bootstrap 권한
- Docker, Tailscale, Google Cloud CLI가 포함된 custom Compute Image
- Secret Manager에 등록할 실제 secret version
- 로컬 PostgreSQL 데이터와 계정
- Tailscale ACL과 auth key
- GitHub Actions repository variables

## 3. 삭제 전에 보존할 것

### 필수

- Git 저장소의 `infra/`, `.github/workflows/`, 배포 스크립트
- 로컬 PostgreSQL 데이터와 검증된 backup
- PostgreSQL application user의 비밀번호
- 실제로 사용했던 `terraform.tfvars`의 비밀이 아닌 설정값
- 사용한 region, zone, image family, Tailscale hostname/tag 기록

### 조건부

- `DJANGO_SECRET_KEY`: 기존 세션이나 서명 데이터의 연속성이 필요할 때 보존한다.
  완전한 새 환경이면 새 값으로 교체할 수 있다.
- Tailscale auth key: 만료·일회용 여부에 따라 재사용하지 말고 새 key를 발급하는 편이
  안전하다.
- Terraform state bucket: 같은 프로젝트를 곧 복구한다면 유지할 수 있다. 완전 철거나
  다른 계정 이전이면 destroy 완료를 확인한 뒤 삭제해도 된다.
- Terraform bootstrap service account: 자체 과금은 없지만 강한 권한이므로 다시 쓸
  계획이 없다면 삭제한다.

Artifact Registry 이미지는 소스에서 다시 빌드할 수 있으므로 별도 보존 대상이 아니다.

## 4. 새 GCP 프로젝트 준비

### 4.1 프로젝트와 비용 경계

1. 새 프로젝트를 만들고 사용할 billing account 또는 무료 체험 계정을 연결한다.
2. project ID와 project number를 기록한다. 두 값은 서로 다르다.
3. 예산과 알림을 먼저 설정한다. 예산 알림은 자원을 자동 중지하지 않는다.
4. 배포 시점의 무료 체험·무료 사용 조건과 대상 region/machine type을 다시 확인한다.
5. 실험 종료 날짜와 담당자를 기록한다.

아래 예시는 환경에 맞게 값을 바꿔 사용한다.

```bash
export PROJECT_ID="새-project-id"
export REGION="asia-northeast3"
export ZONE="asia-northeast3-a"
export STATE_BUCKET="전역에서-유일한-terraform-state-bucket"
export GITHUB_REPOSITORY="owner/repository"

gcloud config set project "${PROJECT_ID}"
```

무료 체험 크레딧과 Always Free는 같은 개념이 아니다. 크레딧 소진 후에도 남아 있는
리소스는 일반 과금으로 전환될 수 있으므로, 이 문서의 철거 절차를 별도로 수행한다.

### 4.2 Terraform 실행 권한

Terraform 실행 주체는 최소한 다음 작업을 수행할 수 있어야 한다.

- Project Service 활성화
- Compute, VPC, firewall 생성·삭제
- Artifact Registry와 Secret Manager 생성·삭제
- service account, project IAM, Workload Identity 관리
- state bucket object 읽기·쓰기

개인 계정의 광범위한 권한을 장기 사용하지 않는다. bootstrap service account를
사용한다면 사용자 관리 JSON key 대신 `gcloud auth application-default login`, 계정
impersonation 또는 조직에서 허용한 단기 인증 방식을 사용한다. 권한 부여 방식은 새
계정의 조직 정책에 맞춘다.

### 4.3 원격 state bucket

state bucket 이름은 전역에서 유일해야 한다.

```bash
gcloud storage buckets create "gs://${STATE_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access

gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning
```

`infra/backend.dev.hcl`을 생성한다. 이 파일은 `.gitignore` 대상이다.

```hcl
bucket = "전역에서-유일한-terraform-state-bucket"
prefix = "infra/dev"
```

Versioning은 state 복구에 유용하지만 오래된 generation도 저장 비용을 발생시킨다.
운영 기간에 맞는 lifecycle 정책으로 오래된 noncurrent version을 제거하거나, 철거 시
모든 generation과 bucket을 마지막에 삭제한다.

## 5. Custom Compute Image 준비

현재 Terraform은 `stock-market-base` image family를 data source로 조회한다. 따라서
전체 `terraform plan/apply`보다 먼저 이미지가 존재해야 한다.

1. Debian 12 임시 builder VM을 만든다.
2. builder에 `infra/scripts/prepare-base-image.sh`를 복사한다.
3. VM에서 `sudo bash prepare-base-image.sh`를 실행한다.
4. VM을 종료한 뒤 boot disk로 custom image를 만든다.
5. image family를 `stock-market-base` 또는 `terraform.tfvars`의 값과 일치시킨다.
6. 이미지 생성 확인 후 builder VM과 builder disk를 삭제한다.

예시:

```bash
gcloud compute images create "stock-market-base-$(date +%Y%m%d)" \
  --project="${PROJECT_ID}" \
  --source-disk="stock-market-image-builder" \
  --source-disk-zone="${ZONE}" \
  --family="stock-market-base" \
  --storage-location="asia"

gcloud compute images list \
  --project="${PROJECT_ID}" \
  --filter='family=stock-market-base'
```

이미지에는 Tailscale의 `/var/lib/tailscale` node identity, application secret, 저장소
credential을 포함하지 않는다.

## 6. Terraform 입력값과 초기화

예제 파일로 로컬 설정을 만든다.

```bash
cd infra
cp backend.dev.hcl.example backend.dev.hcl
cp terraform.tfvars.example terraform.tfvars
```

`backend.dev.hcl`과 `terraform.tfvars`에서 최소한 다음 값을 변경한다.

- `project_id`
- `github_repository`
- `postgres_host`: 로컬 DB 머신의 Tailscale IP 또는 MagicDNS
- `django_allowed_hosts`
- 필요한 경우 `region`, `zone`, `backend_image_project`
- 필요한 경우 `backend_image_family`, `vm_machine_type`
- `tailscale_hostname`, `tailscale_tags`

새 프로젝트에서는 기존 project ID, service account 주소, Workload Identity 전체 경로를
복사하지 않는다. Terraform output으로 새 값을 얻는다.

```bash
terraform init -reconfigure -backend-config=backend.dev.hcl
terraform fmt -check -recursive
terraform validate
terraform plan
```

plan에서 예상하지 않은 기존 리소스 import, 다른 프로젝트 ID, 다른 state prefix가
보이면 apply하지 않는다.

## 7. Secret과 인프라 생성

실제 secret 값은 Terraform input이나 state에 넣지 않는다. 먼저 secret 컨테이너와
접근 권한을 생성한다.

```bash
terraform apply \
  -target=google_secret_manager_secret.runtime \
  -target=google_secret_manager_secret_iam_member.backend_accessor

terraform output runtime_secret_names
```

그다음 각 secret에 version을 등록한다. 값을 명령행 인자로 직접 노출하지 않는다.

```bash
printf '%s' "${TAILSCALE_AUTH_KEY}" | \
  gcloud secrets versions add stock-market-dev-tailscale-auth-key --data-file=-

printf '%s' "${POSTGRES_PASSWORD}" | \
  gcloud secrets versions add stock-market-dev-postgres-password --data-file=-

python3 -c 'import secrets; print(secrets.token_urlsafe(64), end="")' | \
  gcloud secrets versions add stock-market-dev-django-secret-key --data-file=-
```

기존 `DJANGO_SECRET_KEY`를 복구해야 한다면 마지막 명령 대신 안전하게 보관한 기존 값을
stdin으로 등록한다. shell history, 문서, Git에는 값을 남기지 않는다.

전체 plan을 다시 검토하고 적용한다.

```bash
terraform plan -out=tfplan
terraform show tfplan
terraform apply tfplan
```

## 8. GitHub Actions 복구

```bash
terraform output github_actions_variables
```

출력된 새 값을 GitHub repository variables에 등록한다.

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `GCP_REGION`
- `ARTIFACT_REGISTRY_REPOSITORY`
- `GCE_INSTANCE`
- `GCE_ZONE`

이전 프로젝트의 variables가 남아 있으면 새 배포가 잘못된 프로젝트를 참조할 수 있다.
모든 값을 한 번에 교체하고 `.github/workflows/deploy-backend.yml`의 허용 branch와
Terraform의 `github_deploy_ref`가 일치하는지 확인한다.

## 9. 복구 완료 검증

다음을 모두 만족해야 복구 완료로 본다.

1. `terraform plan`이 변경 없음으로 끝난다.
2. builder VM과 임시 disk가 남아 있지 않다.
3. backend VM 재부팅 후 Tailscale이 자동 연결된다.
4. `/etc/stock-market/backend.env`가 root 소유, 권한 `600`이다.
5. backend VM에서 로컬 PostgreSQL에 연결된다.
6. 인터넷에서 backend `8000`과 PostgreSQL `5432`에 직접 접근할 수 없다.
7. `/api/v1/health/`와 `/api/v1/ready/`가 모두 200이다.
8. 로컬 participant-runner가 Tailscale hostname으로 주문 API를 호출한다.
9. GitHub Actions가 새 Artifact Registry에 이미지를 push하고 새 VM에 배포한다.
10. GCP Billing에서 예상한 서비스 외 사용량이 없는지 확인한다.

## 10. 비용 방지 운영 원칙

- VM은 실험 시간에만 실행하고 종료 후 `TERMINATED` 상태를 확인한다. 정지된 VM도
  persistent disk와 image 저장 비용은 남을 수 있다.
- Artifact Registry에는 오래된 commit image를 정리하는 cleanup policy를 둔다.
- custom image, snapshot, unattached disk, static external IP를 정기적으로 확인한다.
- Secret Manager version을 불필요하게 누적하지 않는다.
- state bucket의 noncurrent generation과 soft-delete 보존 기간을 확인한다.
- Cloud Logging retention과 로그 유입량을 확인한다.
- 무료 체험 종료일만 믿지 말고 실험 종료 시 아래 철거 절차를 수행한다.

## 11. 안전한 철거 절차

### 11.1 사전 확인

- PostgreSQL backup과 필요한 secret을 GCP 밖에 안전하게 보존한다.
- GitHub Actions deploy workflow를 비활성화하거나 GCP repository variables를 제거한다.
- 적용할 project ID와 state prefix를 다시 확인한다.
- `terraform state list`와 실제 GCP 인벤토리를 대조한다.
- state bucket은 이 단계에서 삭제하지 않는다.

### 11.2 Terraform 관리 리소스 삭제

custom image를 먼저 삭제하면 `data.google_compute_image.backend` 조회가 실패할 수 있다.
정상적인 순서는 Terraform destroy가 먼저이고 custom image 삭제가 나중이다.

```bash
terraform plan -destroy -out=destroy.tfplan
terraform show destroy.tfplan
terraform apply destroy.tfplan
terraform state list
```

이미 custom image나 다른 리소스를 수동 삭제해 refresh가 실패한다면 먼저 실제 GCP
인벤토리와 state의 삭제 대상을 대조한다. 일치가 확인된 경우에만 다음 복구 절차를
사용한다.

```bash
terraform plan -destroy -refresh=false -out=destroy.tfplan
terraform show destroy.tfplan
terraform apply destroy.tfplan
```

`-refresh=false`는 오래된 state를 신뢰하므로 일반적인 기본값으로 사용하지 않는다.

### 11.3 Terraform 밖의 리소스 삭제

Terraform state가 비었고 실제 과금 리소스가 없음을 확인한 다음 다음 순서로 정리한다.

1. custom image, builder VM/disk, snapshot 등 수동 생성 Compute 리소스
2. state bucket의 모든 object generation
3. state bucket
4. 더 이상 필요 없는 bootstrap service account와 IAM
5. 프로젝트를 다시 쓰지 않는다면 project 종료

API 활성화, default VPC, service account 자체는 일반적으로 주된 과금원이 아니지만
완전 철거 기준에서는 함께 검토한다. project 종료는 그 프로젝트를 다른 용도로 쓰지
않는다는 것이 확실할 때만 수행한다.

## 12. 현재 철거 인계 상태

2026-10-10 KST 철거 및 재검증 기준:

- `-refresh=false` destroy plan의 29개 항목 삭제 완료
- Terraform state: 관리 항목 없음
- GCE VM, persistent disk, custom image, snapshot, static address, Cloud SQL: 없음
- Terraform custom VPC/subnet/firewall: 없음
- Artifact Registry repository 및 image: 없음
- Secret Manager secret: 없음
- GitHub Workload Identity Pool/Provider: 없음
- Terraform이 생성했던 backend/GitHub service account와 IAM: 없음
- state bucket `stock-market-505109-terraform-state`: 의도적으로 유지
  - live data 약 1.90 KiB
  - 모든 object generation 합계 약 603 KiB
  - Versioning 활성
  - soft delete 7일 활성
- `infra-manager`와 Compute Engine 기본 service account: Terraform 밖에서 관리되며 유지

현재 별도로 결정할 저장 과금 대상은 state bucket이다. 같은 프로젝트에서 빠르게
복구하려면 유지하고, 완전 철거 또는 다른 계정으로만 이전한다면 모든 object generation과
bucket을 삭제한다.
