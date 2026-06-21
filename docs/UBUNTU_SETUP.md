# Ubuntu Setup Checklist

> 네이티브 Ubuntu(별도 디스크 부팅 포함) 또는 WSL2에서 이 프로젝트를 올리기 위한 1회 셋업 가이드.
> 클러스터·DB 데이터는 이전되지 않으며, 새 환경에서는 `git clone` 후 아래 순서로 재배포한다.

**관련 문서**: [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)

---

## 1. 하드웨어 최소 권장

| 항목 | 최소 | 권장 (Phase 0~5 로컬) |
|------|------|------------------------|
| CPU | 4코어 | 8코어 / 16스레드 |
| RAM | 16GB | **32GB** |
| Disk | 40GB 여유 | **100GB+** 여유 |
| Swap | 4GB | 8GB |

동일 PC(Ryzen 7800X3D + 32GB) 기준: Phase 0~5 + T1~T4 부하 테스트 가능.

---

## 2. OS 선택

| 환경 | 비고 |
|------|------|
| **네이티브 Ubuntu 22.04/24.04** | 권장. kind/ingress가 WSL보다 안정적인 경우 많음 |
| WSL2 Ubuntu | 개발 가능. Windows RAM 할당 16GB+ 권장 |

코드는 Ubuntu 홈 디렉토리에 clone (`~/stock-market`). NTFS 공유 파티션은 I/O·권한 이슈로 비권장.

---

## 3. 패키지 설치 (1회)

### 3.1 기본 도구

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl git make \
  apt-transport-https gnupg lsb-release
```

### 3.2 Docker

```bash
# 공식 convenience script (또는 Ubuntu docker.io 패키지)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker   # 또는 로그아웃 후 재로그인

docker info     # Server Version 확인
```

### 3.3 kubectl

```bash
curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
  -o kubectl
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
kubectl version --client
```

### 3.4 kind

```bash
curl -fsSL https://kind.sigs.k8s.io/dl/v0.27.0/kind-linux-amd64 -o kind
chmod +x kind
sudo mv kind /usr/local/bin/
kind version
```

### 3.5 Helm

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

### 3.6 (선택) Phase 1+ 개발 도구

```bash
# Go 1.22+
sudo apt install -y golang-go   # 또는 go.dev 공식 바이너리

# Python 3.11+ (reference-data, Phase 0.5)
sudo apt install -y python3 python3-pip python3-venv
```

---

## 4. 설치 확인 체크리스트

```bash
docker info | grep -E "Server Version|Total Memory"
kind version
kubectl version --client
helm version
make --version
git --version
```

| 체크 | 기대 |
|------|------|
| Docker daemon | running, user in `docker` group |
| RAM (Docker) | 16GB+ 인식 (32GB 환경 권장) |
| kind / kubectl / helm | 명령 성공 |

---

## 5. 프로젝트 배포 순서

```bash
git clone https://github.com/grademe12/stock-market.git
cd stock-market

make help
make kind-up          # PR-0.1+
make deps             # helm repo 등록
# Phase 0.2+
make install-infra
# Phase 0.5+
make ingest-bootstrap
```

---

## 6. WSL → 네이티브 Ubuntu 이전 시

| 항목 | 이전 여부 |
|------|-----------|
| Git repo (`git clone`) | **재 clone** |
| kind 클러스터 / kubeconfig | **재생성** (`make kind-up`) |
| PostgreSQL·Redpanda 데이터 | **재적재** (`make ingest-bootstrap` 등) |
| 로컬만 빌드한 container image | **재빌드** 또는 registry에서 pull |

WSL에서 쓰던 클러스터를 그대로 가져올 수 없다. Makefile·Helm으로 동일 스택을 재현하는 것이 목표.

---

## 7. 자주 막히는 지점

| 증상 | 조치 |
|------|------|
| `permission denied` (docker) | `sudo usermod -aG docker $USER` 후 재로그인 |
| kind 생성 실패 (RAM) | 다른 앱 종료; worker 노드 1개로 줄이기 (임시) |
| ingress 접속 안 됨 (WSL) | 네이티브 Ubuntu 시도; `kubectl get svc -A` 확인 |
| helm repo 오래됨 | `make deps` 재실행 |

---

## 8. 도구가 PATH에 없을 때 (개발 환경)

시스템에 `sudo` 없이 개발하는 경우, 프로젝트 `bin/`에 바이너리를 둘 수 있다 (`bin/`은 gitignore).

```bash
mkdir -p bin
# kind, kubectl — UBUNTU_SETUP.md §3.3, §3.4와 동일 URL로 bin/에 설치
export PATH="$(pwd)/bin:$PATH"
```

`Makefile`은 `bin/`을 PATH 앞에 붙인다. **Ubuntu 정식 셋업은 §3 Docker/kind/kubectl/helm 시스템 설치를 권장.**

## 9. 다음 단계

- [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) Phase 0 PR 순서 참고
- PR-0.1 완료 후: `make kind-up` → 3노드 Ready 확인

---

*Last updated: 2026-06-21*