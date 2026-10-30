# Azure backend infra

GCP 무료 체험이 끝난 뒤 백엔드 VM 하나를 Azure로 옮긴 Terraform이다. GCP 버전(`../infra`)은 기록과 복구 runbook으로 남겨 둔다.

러너, Prometheus/Grafana, PostgreSQL은 그대로 미니 PC에 있고 Tailscale로 붙는다. 이 디렉터리가 만드는 것은 백엔드 VM과 그 주변뿐이다.

## 무엇을 만드나

| 파일 | 리소스 | GCP에서 대응하던 것 |
|---|---|---|
| `main.tf` | 리소스 그룹 | 프로젝트 |
| `network.tf` | VNet, 서브넷, NSG, 공인 IP, NIC | VPC, 서브넷, 방화벽, 임시 외부 IP |
| `compute.tf` | Ubuntu 24.04 VM + cloud-init | 커스텀 이미지 VM + startup-script |
| `secrets.tf` | Key Vault + 역할 2개 | Secret Manager |
| `github.tf` | 사용자 할당 관리 ID + GitHub OIDC 연동 | Workload Identity Federation |

- 들어오는 연결은 Tailscale(UDP 41641)만 허용한다. 백엔드 포트 `:8000`은 Tailnet 안에서만 보인다.
- 공인 IP는 나가는 통신용이다. 새 VNet에는 기본 외부 통신이 없고, NAT 게이트웨이보다 싸다.
- 시크릿 값은 Terraform 밖에서 넣는다. state에 값이 남지 않게 하려는 것이다.
- Tailscale 호스트 이름은 `stock-market-gce`를 그대로 쓴다. 미니 PC의 Prometheus, 러너 설정을 바꾸지 않기 위해서다.

## 부팅 순서

1. cloud-init이 Docker, Tailscale을 설치하고 `/etc/stock-market/bootstrap.conf`(시크릿 아닌 설정)를 쓴다.
2. `stock-market-bootstrap.service`가 VM 관리 ID로 Key Vault 토큰을 받는다.
3. Tailscale 인증 키로 Tailnet에 붙고, `/etc/stock-market/backend.env`를 쓴다.
4. 시크릿이 아직 없으면 30초마다 다시 시도한다. 재부팅할 때마다 다시 돈다.

## 적용 순서 (맥에서)

```bash
cd infra-azure
az login
az account show --query id -o tsv          # subscription_id
cp terraform.tfvars.example terraform.tfvars  # 값 채우기
terraform init
terraform plan
terraform apply
```

적용 후 시크릿 세 개를 넣는다. Tailscale 인증 키는 `tag:stock-market-backend` 태그가 붙은 키여야 한다.

```bash
vault="$(terraform output -raw key_vault_name)"
az keyvault secret set --vault-name "$vault" --name tailscale-auth-key --value '...'
az keyvault secret set --vault-name "$vault" --name postgres-password  --value '...'
az keyvault secret set --vault-name "$vault" --name django-secret-key  --value '...'
```

1분쯤 지나면 Tailscale 관리 화면에 `stock-market-gce`가 보인다.

## 비용

- 무료 체험은 보통 30일, $200, 지역당 vCPU 4개다. `Standard_D4as_v5`가 한도를 꽉 채운다.
- 측정하지 않는 시간에는 `az vm deallocate`로 할당을 해제한다. `stop`만 하면 계속 과금된다.
- 공인 IP와 디스크는 할당 해제 중에도 소액 과금된다.
