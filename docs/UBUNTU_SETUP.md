# Ubuntu Setup Checklist

> 이 프로젝트는 필요한 기술을 단계적으로 도입한다. 지금은 Django/DRF 백엔드만 설치하면 되며, Docker·Kubernetes는 나중 단계의 선택 항목이다.

**관련 문서**: [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)

---

## 1. 현재 단계: Django/DRF 개발 환경

### 필수 패키지

```bash
sudo apt update
sudo apt install -y git make python3 python3-pip python3-venv
```

Python 3.12 이상을 사용한다.

### 프로젝트 설치와 확인

```bash
git clone https://github.com/grademe12/stock-market.git
cd stock-market

make backend-setup
make backend-migrate
make backend-test
make backend-run
```

개발 서버를 실행한 뒤 다음 요청이 성공해야 한다.

```bash
curl http://127.0.0.1:8000/api/v1/health/
# {"status":"ok"}
```

- 가상환경은 `backend/.venv/`에 생성되며 Git으로 관리하지 않는다.
- 로컬 단위 테스트는 Django 기본 SQLite를 사용하고 Compose backend는 PostgreSQL을 사용한다.
- `DJANGO_SECRET_KEY`와 `DJANGO_DEBUG`는 로컬 환경에서만 기본값을 사용한다. 배포 설정은 Stage 6에서 별도로 다룬다.

---

## 2. 나중 단계의 선택 도구

다음 도구는 현재 설치하지 않는다. 각 단계의 도입 조건이 충족되면 설치한다.

| 도구 | 가장 이른 도입 단계 | 목적 |
|---|---:|---|
| k6 | Stage 2 | HTTP 부하 테스트 |
| Docker / Docker Compose | Stage 3 | 관측성 스택의 반복 실행 |
| Prometheus / Grafana | Stage 3 | 애플리케이션 지표 관측 |
| Redpanda | Stage 4 | 비동기 주문 처리와 queue lag |
| PostgreSQL | Stage 2.5 | KRX 참조 데이터와 설정 영속화 |
| kind / kubectl / Helm / KEDA | Stage 6 | Kubernetes와 autoscaling 실험 |

---

## 3. WSL 사용 시

WSL2에서도 Stage 0~2는 문제없이 진행할 수 있다. 저장소는 Linux 파일시스템(예: `~/stock-market`)에 clone하는 편이 파일 감시와 권한 처리에 안정적이다.

Docker와 kind가 필요한 Stage 6에 들어갈 때 Windows의 Docker Desktop 메모리 설정과 Kubernetes 네트워크 구성을 별도로 확인한다.

---

*Last updated: 2026-07-25 — Django/DRF 단계형 설치 가이드로 변경*
