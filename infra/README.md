# GCP infrastructure

Infrastructure and a single-VM backend deploy for the in-memory matcher.

첫 배포 전 필수 보완 항목과 집 미니 PC PostgreSQL 대안은
[GCP_DEPLOYMENT_READINESS.md](../docs/GCP_DEPLOYMENT_READINESS.md)를 먼저 확인한다.

```text
GitHub Actions
  | OIDC / Workload Identity
  | push image to Artifact Registry
  | IAP SSH
  v
Compute Engine VM
  - Cloud SQL Auth Proxy container
  - Django backend container (Gunicorn worker 1)
        |
        v
Cloud SQL for PostgreSQL

Local participant runners
  | runner_source_cidr -> TCP 8000
  v
same VM
```

Terraform creates:

- one custom VPC and regional subnet;
- one static external IP and a backend firewall rule limited to `runner_source_cidr`;
- IAP SSH from GitHub Actions (`35.235.240.0/20`);
- one Compute Engine VM;
- one Artifact Registry Docker repository;
- one public-IP Cloud SQL PostgreSQL instance with no authorized network;
- one application database user;
- a VM service account (Cloud SQL client, Artifact Registry reader, telemetry);
- a GitHub Actions service account plus Workload Identity Federation.

The development database uses the Cloud SQL `ENTERPRISE` edition explicitly so
the shared-core `db-f1-micro` tier remains valid with PostgreSQL 17.

Terraform state is stored in the versioned GCS bucket
`stock-market-505109-terraform-state` under the `infra/dev` prefix.

Cloud SQL Auth Proxy is not a Terraform resource. GitHub Actions starts it as a
container on the VM. The proxy uses the VM service account, so no JSON key is
required. A separate monitoring VM is not created.

## Validate and apply

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Set runner_source_cidr, github_repository, and cloud_sql_password.
terraform init
terraform fmt -check
terraform validate
terraform plan
terraform apply
terraform output github_actions_variables
```

The Cloud SQL instance has Terraform deletion protection enabled.

## Values you must set

These are not in Git. Terraform and GitHub Actions only read them from local
files or GitHub repository settings.

### 1. `infra/terraform.tfvars`

| Name | Meaning |
|---|---|
| `project_id` | GCP project |
| `runner_source_cidr` | Public IP of the machine that will run `participant-runner`, as `x.x.x.x/32` |
| `github_repository` | `owner/name` of this GitHub repo, used as the OIDC allowlist |
| `cloud_sql_password` | Password for the `stock_market` Cloud SQL user |

### 2. GitHub repository variables

Settings → Secrets and variables → Actions → **Variables** (not Secrets).
Copy the map from `terraform output github_actions_variables`.

| Variable | Source |
|---|---|
| `GCP_PROJECT_ID` | `project_id` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | GitHub Actions service account email |
| `GCP_REGION` | region, default `asia-northeast3` |
| `ARTIFACT_REGISTRY_REPOSITORY` | Artifact Registry repository id |
| `GCE_INSTANCE` | VM name |
| `GCE_ZONE` | zone, default `asia-northeast3-a` |
| `CLOUD_SQL_CONNECTION_NAME` | `project:region:instance` |

No GCP JSON key is stored in GitHub. The workflow uses OIDC (`id-token: write`).

### 3. Env file on the VM

Create this **once** after `terraform apply`, before the first deploy. It stays
on the VM and is not in GitHub Actions.

```bash
gcloud compute ssh stock-market-dev-backend --zone asia-northeast3-a --tunnel-through-iap
sudo mkdir -p /etc/stock-market
sudo chmod 700 /etc/stock-market
sudo cp /dev/stdin /etc/stock-market/backend.env
```

Use `infra/backend.env.example` as the template.

| Name | Meaning |
|---|---|
| `POSTGRES_PASSWORD` | Same value as `cloud_sql_password` |
| `DJANGO_SECRET_KEY` | Long random string, not the Django default |
| `DJANGO_ALLOWED_HOSTS` | VM external IP from `terraform output backend_external_ip` |
| `DJANGO_DEBUG` | `0` on GCP |
| `POSTGRES_HOST` | `127.0.0.1` (the Auth Proxy on the VM) |

`DJANGO_SECRET_KEY` is only on the VM. Do not put it in GitHub variables.

## Deploy

After the three setup steps:

```text
GitHub → Actions → Deploy backend → Run workflow
```

Pushes to `infra` or `main` that change `backend/` also trigger the workflow.
It runs backend tests, pushes an image tagged with the commit SHA, then SSHs
through IAP to restart the backend container. Matcher replica remains 1.

The first SSH from your laptop to the VM may still need OS Login / IAP
permissions for your user, separate from the GitHub service account.
