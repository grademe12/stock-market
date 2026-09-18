# 단일 진입점 · 종목 라우터 계획

> **상태**: G1–G3 구현. G4 Prometheus 진입점 스크레이프는 남음. 실기 컷오버는 이미지 배포 후.
>
> **학습 질문**: 이용자는 URL 하나만 보는데, 같은 종목 호가창은 프로세스 1개로 유지할 수 있는가?

**관련 문서**: [구현 계획](./IMPLEMENTATION_PLAN.md) · [GCP 배포](./GCP_DEPLOYMENT_READINESS.md) · [데모 runbook](./DEMO_RUNBOOK.md) · [Day 4 수직 스케일](../report/DAY4_VERTICAL_SCALE_REPORT.md)

---

## 1. 왜 지금인가

샤드를 CPU마다 나눈 뒤 막힌 것은 matcher가 아니라 **공개 포트와 라우팅 위치**다.

- host-network라 샤드 N은 `:8000+N`을 연다.
- Tailscale ACL은 당시 있던 `:8000`·`:8001`만 열렸다. `:8002`·`:8003`은 미니 PC에서 타임아웃이다.
- 러너·프론트가 `/ready/`를 보고 포트를 고른다. 이용자가 샤드를 알 일이 아니다.

일반 로드밸런서로 요청을 둥글게 뿌리면 같은 종목 호가창이 갈라진다. 뒤에 두는 것은 **종목 라우터**다. 바깥 URL 하나는 이후 샤드 수가 늘어도 유지한다.

---

## 2. 목표와 비목표

### 목표

- 공개 계약은 `http://stock-market-gce:8000` 하나다.
- 종목 소속은 서버가 본다. 러너·프론트·ACL은 샤드 포트를 모른다.
- matcher는 `127.0.0.1`만 듣고, 프로세스당 종목 슬라이스는 그대로다.
- 로컬 Compose도 같은 모양이다.
- Prometheus는 진입점 너머로 샤드별 `/metrics/`를 본다.

### 비목표

- Kubernetes, Ingress, GCP HTTP LB
- 같은 종목 replica, 호가창 외부화
- matcher 만료·O(n) 호가 개선
- `event_reactive` 켜기
- Caddy/nginx. `POST` 바디 `symbol`을 보려면 작은 프록시가 맞다.

---

## 3. 목표 구조

```text
이용자 / 러너 / 프론트 / Prometheus
        |  Tailscale :8000 only
        v
   [종목 라우터]          GCE host network
        |
        +--> 127.0.0.1:8001  shard 0
        +--> 127.0.0.1:8002  shard 1
        +--> 127.0.0.1:8003  shard 2
        +--> ...
```

샤드 수는 지금처럼 배포 시 `nproc`(최대 8) 또는 `SIMULATION_SHARD_COUNT`. 분배 규칙은 기존 `position % shard_count`를 라우터와 matcher가 같이 쓴다.

### 라우팅

| 요청 | 보는 값 | 대상 |
|---|---|---|
| `POST /api/v1/orders/` | 바디 `symbol` | 그 종목 샤드 |
| `DELETE /api/v1/orders/{id}/` | 쿼리 `symbol` | 그 종목 샤드. 없으면 400 |
| `GET /api/v1/books/{symbol}/` | 경로 | 그 종목 샤드 |
| `GET /api/v1/trades/?symbol=` | 쿼리 | 그 종목 샤드 |
| health / ready / symbols / traders | — | 샤드 0. ready는 라우터가 전 샤드 생존을 합쳐도 된다 |
| `/metrics/`, `/api/v1/prometheus-sd/` | — | 샤드별 경로 또는 라우터가 만드는 SD |

취소에 `symbol`이 없는 요청은 지금 샤드 환경과 같이 거절한다. 전 샤드 스캔은 하지 않는다.

---

## 4. 손대는 곳

### 4.1 추가

| 경로 | 내용 |
|---|---|
| `gateway/` (가칭) | 종목 라우터. `exchange.sharding`과 같은 규칙. 단위 테스트 |

### 4.2 배포·백엔드

| 경로 | 내용 |
|---|---|
| `infra/scripts/remote-deploy.sh` | matcher N개 localhost + 라우터 `:8000` |
| `infra/scripts/resize-backend-vm.sh` | 공개 ready는 `:8000`만 |
| Django `--bind` | 배포에서 `127.0.0.1` |
| `GET /api/v1/prometheus-sd/` | 포트 나열이 아니라 진입점 경로 |

### 4.3 클라이언트에서 제거

이용자 계약은 `BACKEND_BASE_URL` 하나.

| 경로 | 내용 |
|---|---|
| `participant-runner/.../__main__.py` | ready로 URL 늘리기 삭제 |
| `ShardedBackendClient` 주문 경로 | 단일 `BackendApiClient` |
| `frontend/lib/matcherShards.ts` | 삭제 |
| `frontend/app/api/backend/[...path]/route.ts` | upstream 하나 |
| runner/frontend `.env.example`, README | `BACKEND_SHARD_URLS` 삭제 |

`RUNNER_SHARD_INDEX`는 noise 부하 나눔용으로 남겨도 된다. 주문 경로가 아니다.

### 4.4 관측·로컬·문서

| 경로 | 내용 |
|---|---|
| `observability/prometheus/prometheus.yml` | `:8000` 또는 `/metrics/{shard}` |
| `compose.yaml` | 라우터 `:8000` + 내부 backend 서비스 |
| `infra/README.md` | ACL `tcp:8000`. `8001+`는 내부 |
| `docs/DEMO_RUNBOOK.md`, `backend/README.md` | 공개 포트 하나 |

---

## 5. 손대지 않는 것

- 같은 종목 = 프로세스 1개
- 메모리 호가창, 체결 알고리즘
- 배포 시 CPU로 샤드 수를 정하는 것
- Postgres·KRX 참조 경로

---

## 6. PR 나누기

한 PR은 한 질문에 답한다.

| PR | 질문 | 완료 조건 |
|---|---|---|
| G1 | 라우터가 종목으로 샤드를 고르는가 | gateway 단위 테스트. Django는 그대로 |
| G2 | GCE가 `:8000`만 여는가 | deploy가 localhost matcher + 라우터. 미니 PC에서 `:8001` 직접 접속 실패, `:8000` 주문 성공 |
| G3 | 클라이언트가 URL 하나만 쓰는가 | 러너·프론트에서 샤드 URL 코드 삭제. 기존 API 테스트 통과 |
| G4 | 스크레이프가 진입점을 통하는가 | Prometheus가 샤드별 지표를 `:8000`으로 수집 |

G2 전에 Tailscale ACL을 `tcp:8000`으로 좁혀도 된다. 지금 `8002`·`8003`을 여는 것은 이 계획의 목표가 아니다.

---

## 7. 이후에도 남는 것

진입점 URL은 샤드 수가 늘어도 같다. Kubernetes Ingress나 GCP HTTP LB를 나중에 붙여도 바깥 계약은 이 주소다.

그 LB들은 `POST /orders/` 바디의 `symbol`을 보고 백엔드를 고르지 못한다. 종목 라우터는 남거나, 호가창을 프로세스 밖으로 빼야 일반 LB가 된다.
