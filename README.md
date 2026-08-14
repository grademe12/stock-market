# Stock Market

주식 거래 애플리케이션을 모방한 학습용 프로젝트입니다.  
단일 Django 매칭 엔진에서 시작해 부하 제어·테스트·모니터링·이벤트 파이프라인을 필요한 시점에 하나씩 도입합니다.

## 문서

| 문서 | 내용 |
|------|------|
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | 프로젝트 목적과 현재 구현 범위 |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | 점진적 학습 단계와 기술 도입 기준 |
| [docs/LOAD_TEST_BASELINE.md](docs/LOAD_TEST_BASELINE.md) | k6 기준 부하 측정 조건과 결과 |
| [docs/TRADING_PARTICIPANT_SIMULATION_PLAN.md](docs/TRADING_PARTICIPANT_SIMULATION_PLAN.md) | 가상 거래 참여자와 트레이더 설정 계획 |
| [docs/NEWS_TRIGGERED_LOAD_SPIKE_PLAN.md](docs/NEWS_TRIGGERED_LOAD_SPIKE_PLAN.md) | 뉴스 발생을 모사한 트레이더 주문 spike 미확정 계획 |
| [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md) | 재현 가능한 backend·runner 실험 실행 절차 |
| [docs/UBUNTU_SETUP.md](docs/UBUNTU_SETUP.md) | Ubuntu/WSL 1회 셋업 체크리스트 |

## 프로젝트 구조

```text
backend/       Django + Django REST Framework 거래소 API와 매칭 엔진
participant-runner/ 별도 프로세스/컨테이너로 실행되는 HTTP 시장참여자
db/            PostgreSQL·KRX 환경 설정 (실제 `.env`는 Git 제외)
frontend/      향후 웹 클라이언트 (현재는 계획만 존재)
docs/          구현·학습 계획
loadtest/      부하 테스트 시나리오 (Stage 2부터)
deploy/        Compose·Kubernetes 배포 구성 (필요 시 도입)
observability/ 대시보드·알림 구성 (Stage 3부터)
```

## 현재 단계의 사전 요구사항

- Python 3.12 이상, make
- Docker는 현재 Compose 실행과 PostgreSQL에 필요하다. kind·kubectl·helm은 Stage 6에서 필요해질 때 설치한다.
- 환경별 설치 참고: [docs/UBUNTU_SETUP.md](docs/UBUNTU_SETUP.md)

## 컨테이너 실행

backend와 외부 시장참여자 runner는 각각 독립 이미지로 패키징된다. 현재 호가창은 한 프로세스의 메모리에 있으므로 backend 컨테이너는 Gunicorn worker 1개로 실행한다.

```bash
docker compose up --build backend
# runner까지 실행: docker compose --profile runner up --build
```

상세 설정과 실행 순서는 [backend README](backend/README.md), [participant-runner README](participant-runner/README.md)를 참고한다.

## 진행 방식

Stage 0~2에서는 `backend/`의 Django 단일 프로세스와 k6만 사용한다. `frontend/`는 독립적으로 유지하며, 아직 구현하지 않는다. 기술을 추가하기 전에는 반드시 현재 구조의 측정 결과와 도입 가설을 계획 문서에 정의된 형식으로 남긴다.

## 개발 상태

프로젝트는 기술을 한꺼번에 도입하지 않고, **기능 구현 → 부하 측정 → 병목 관찰 → 다음 기술 도입** 순서로 진행합니다. 상세 기준은 [점진적 학습 계획](docs/IMPLEMENTATION_PLAN.md)을 참고하세요.

| Stage | 상태 |
|-------|------|
| 기존 kind/Makefile·observability 스캐폴딩 | 완료 (나중 단계에서 재사용) |
| Stage 0: Django/DRF 개발 기반 정리 | 완료 |
| Stage 1: 단일 프로세스 매칭 엔진 | 완료 |
| Stage 1.5: 거래 참여자 시뮬레이션 | 완료 (외부 HTTP runner와 4개 전략) |
| Stage 2: k6 부하 테스트·기본 rate limit | 진행 중 (steady 기준 측정 완료, rate limit 예정) |
| Stage 2.5: PostgreSQL·KRX KOSPI 참조 데이터 | 완료 (2026-07-27 상위 100개 적재 검증) |
| Stage 3+: 관측성·queue·영속화·K8s | 측정 결과에 따라 순차 도입 |
