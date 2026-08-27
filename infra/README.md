# GCP infrastructure

필요할 때만 실행하는 단일 GCE backend와 로컬 PostgreSQL을 Tailscale로 연결한다.
Cloud SQL, 공인 backend 포트, JSON 서비스 계정 키는 사용하지 않는다.

```text
Local machine
  - PostgreSQL 17
  - participant-runner
       | Tailscale ACL
       v
Compute Engine VM
  - custom image: Docker + Tailscale + gcloud
  - Django backend container (Gunicorn worker 1)

GitHub Actions
  - OIDC / Workload Identity
  - Artifact Registry push
  - IAP SSH deploy
```

Terraform이 생성하는 항목:

- custom VPC와 subnet
- outbound 전용 ephemeral external IP를 가진 GCE VM
- GitHub Actions용 IAP SSH 방화벽
- Artifact Registry
- Tailscale, PostgreSQL, Django용 Secret Manager secret 컨테이너
- 최소 runtime 권한의 VM service account
- GitHub Actions service account와 branch 제한 Workload Identity Federation

DB 데이터와 PostgreSQL 프로세스는 로컬 머신에 유지한다. VM의 `8000`과
로컬 DB의 `5432`는 Tailscale 네트워크에서만 접근한다.

## 1. Custom image 준비

Debian 12 임시 builder VM에서 저장소의 스크립트를 실행한다.

```bash
sudo bash infra/scripts/prepare-base-image.sh
sudo poweroff
```

builder VM이 정지된 뒤 boot disk로 이미지를 만든다.

```bash
gcloud compute images create stock-market-base-20260827 \
  --project stock-market-505109 \
  --source-disk stock-market-image-builder \
  --source-disk-zone asia-northeast3-a \
  --family stock-market-base \
  --storage-location asia
```

이미지에는 Docker, Tailscale client, Google Cloud CLI만 포함한다.
Tailscale의 `/var/lib/tailscale` 상태와 모든 secret은 이미지에 포함하지 않는다.

## 2. Terraform backend와 입력값

환경별 state prefix를 명시적으로 분리한다.

```bash
cd infra
cp backend.dev.hcl.example backend.dev.hcl
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=backend.dev.hcl
terraform fmt -check -recursive
terraform validate
```

`terraform.tfvars`에서 다음 값을 실제 환경에 맞게 변경한다.

- `project_id`
- `github_repository`
- `postgres_host`: 로컬 DB 머신의 Tailscale IP 또는 MagicDNS
- `django_allowed_hosts`: backend의 Tailscale hostname과 MagicDNS
- 필요한 경우 custom image project/family와 Tailscale hostname/tag

## 3. Secret 생성과 값 등록

Secret 값은 Terraform에 전달하지 않는다. 먼저 secret 컨테이너와 IAM을 만든다.

```bash
terraform apply \
  -target=google_secret_manager_secret.runtime \
  -target=google_secret_manager_secret_iam_member.backend_accessor
terraform output runtime_secret_names
```

각 값은 로컬 파일이나 stdin을 통해 직접 Secret Manager에 등록한다.

```bash
printf '%s' "$TAILSCALE_AUTH_KEY" | \
  gcloud secrets versions add stock-market-dev-tailscale-auth-key --data-file=-
printf '%s' "$POSTGRES_PASSWORD" | \
  gcloud secrets versions add stock-market-dev-postgres-password --data-file=-
python3 -c 'import secrets; print(secrets.token_urlsafe(64), end="")' | \
  gcloud secrets versions add stock-market-dev-django-secret-key --data-file=-
```

Tailscale key는 `tag:stock-market-backend`를 광고할 수 있어야 한다. VM을 재생성할
때 key가 만료됐거나 일회용으로 소비됐다면 secret에 새 version을 등록한다.

이후 전체 plan과 apply를 실행한다.

```bash
terraform plan
terraform apply
```

VM startup script가 다음 작업을 멱등하게 수행한다.

1. Docker와 Tailscale service 시작
2. 미인증 VM만 Tailscale 등록
3. PostgreSQL 및 Django secret 조회
4. root 전용 `/etc/stock-market/backend.env` 생성

bootstrap 로그는 다음 명령으로 확인한다.

```bash
gcloud compute ssh stock-market-dev-backend \
  --zone asia-northeast3-a \
  --tunnel-through-iap \
  --command 'sudo journalctl -u google-startup-scripts.service'
```

## 4. 로컬 PostgreSQL과 Tailscale ACL

로컬 PostgreSQL은 인터넷에 포트 포워딩하지 않는다.

- `listen_addresses`: localhost와 로컬 머신의 Tailscale 주소
- `pg_hba.conf`: backend VM의 Tailscale IP에서 오는 application user만 허용
- 인증: `scram-sha-256`
- 재부팅 후 PostgreSQL 자동 시작
- 일일 backup과 주기적인 restore 검증

Tailnet 정책은 최소한 다음 흐름만 허용한다.

```text
local participant-runner -> stock-market-gce:8000
tag:stock-market-backend -> local-db:5432
```

## 5. GitHub Actions 변수와 배포

`terraform output github_actions_variables` 결과를 GitHub Actions Variables에 등록한다.

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `GCP_REGION`
- `ARTIFACT_REGISTRY_REPOSITORY`
- `GCE_INSTANCE`
- `GCE_ZONE`

workflow는 `main`에서만 배포 토큰을 받을 수 있다. backend·runner 테스트와 Terraform
검증 후 이미지를 push하고 IAP SSH로 배포한다. VM은 자신의 service account로
Artifact Registry에 로그인한다.

배포는 기존 컨테이너를 `stock-market-backend-previous`로 보존한다. 새 컨테이너의
`/api/v1/ready/`가 DB 연결까지 확인한 후에만 이전 컨테이너를 삭제하며, 실패하면
이전 컨테이너를 복구한다. 메모리 호가창 특성상 배포 중 주문 상태는 유지되지 않는다.

runner의 endpoint:

```bash
BACKEND_BASE_URL=http://stock-market-gce:8000
```
