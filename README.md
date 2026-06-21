# Stock Market

주식 거래 애플리케이션을 모방한 학습용 프로젝트입니다.  
K8s·컨테이너 기반 이벤트 파이프라인 + 부하 제어·테스트·모니터링이 핵심 학습 목표입니다.

## 문서

| 문서 | 내용 |
|------|------|
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | 전체 아키텍처, Phase/PR 계획 |
| [docs/UBUNTU_SETUP.md](docs/UBUNTU_SETUP.md) | Ubuntu/WSL 1회 셋업 체크리스트 |

## 사전 요구사항

- Docker, [kind](https://kind.sigs.k8s.io/), kubectl, helm, make
- 권장: 32GB RAM, 8코어 CPU
- 설치: [docs/UBUNTU_SETUP.md](docs/UBUNTU_SETUP.md) 참고

## Quick Start (PR-0.1+)

```bash
git clone https://github.com/grademe12/stock-market.git
cd stock-market

make help
make kind-up        # 3-node kind cluster
make cluster-info   # nodes Ready 확인
make deps           # helm repo 등록
```

## 개발 상태

| Phase | 상태 |
|-------|------|
| PR-0.1 scaffold | 진행 중 |
| PR-0.2~0.4 infra | 예정 |
| Phase 0.5 reference-data (pykrx) | 예정 |
| Phase 1+ exchange services | 예정 |