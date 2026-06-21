# A+ Stock Exchange — Implementation Plan

> **문서 목적**: 부하 제어·테스트·모니터링을 1순위 학습 목표로 하는 이벤트 기반 주식시장 시뮬레이터(A+안)의 구현 계획.
> 에이전트가 Phase/PR 단위로 직접 참조·실행할 수 있도록 작성됨.

**관련 문서**: [README.md](../README.md)

---

## 목차

1. [Project Charter](#1-project-charter)
2. [Architecture](#2-architecture)
3. [Technology Decisions](#3-technology-decisions)
4. [Repository Layout](#4-repository-layout)
5. [Service Specifications](#5-service-specifications)
6. [Reference Data (KRX / pykrx)](#6-reference-data-krx--pykrx)
7. [Event Schema](#7-event-schema)
8. [Observability Contract](#8-observability-contract)
9. [Load Test Integration](#9-load-test-integration)
10. [Phase / PR Implementation Plan](#10-phase--pr-implementation-plan)
11. [Agent Execution Notes](#11-agent-execution-notes)
12. [Burst Scenario Runbook](#12-burst-scenario-runbook)
13. [Risks and Mitigations](#13-risks-and-mitigations)
14. [Open Decisions](#14-open-decisions)

---

## 1. Project Charter

### 1.1 Primary Learning Goals (우선순위)

| 순위 | 목표 | 학습 내용 |
|------|------|-----------|
| 1 | **Load control** | 계층별 rate limit, backpressure, circuit breaker, autoscaling |
| 2 | **Load testing** | 종목 스파이크 / 시장 전체 스파이크 / flash-event를 K8s Job으로 재현 |
| 3 | **Monitoring** | 서비스별 + 심볼별 golden signals, SLO 대시보드, alert 규칙 |

### 1.2 Secondary Goals

- **KRX 일봉 레퍼런스 데이터** (시가·종가 등)로 시뮬 기준가 시드
- 가격·시간 우선 Limit Order 매칭 (단일/다중 심볼)
- 이벤트 기반 파이프라인: 주문 → 체결 → 정산 → 시세
- K8s 네이티브 운영: Helm, HPA, KEDA, NetworkPolicy, PDB

### 1.3 Non-Goals (v1)

- 실제 금융 규제/감사 준수
- 모바일/웹 UI (CLI + k6만 제공)
- Kubernetes Operator / CRD (C안 요소는 KEDA만 차용)
- 다중 AZ 프로덕션 HA (로컬 kind 클러스터 기준)

### 1.4 Success Criteria (SLO)

기준 클러스터: 3-node kind

| Scenario | SLO |
|----------|-----|
| Steady state 100 order/s | p99 end-to-end latency < 200ms |
| Symbol spike 1000 order/s (단일 종목, 30s) | reject rate < 5%, 비스파이크 종목 p99 < 300ms |
| Market-wide spike 500 order/s (전 종목) | Kafka lag가 스파이크 종료 후 60s 이내 회복 |
| Flash event (주문 + WS 구독 동시 폭증) | Gateway 429 활성화, OOMKill 없음 |

---

## 2. Architecture

### 2.1 High-Level Diagram

```mermaid
flowchart TB
    subgraph clients [Clients]
        CLI[cli-client]
        K6[k6 LoadTest Job]
    end

    subgraph edge [Edge Layer]
        GW[order-gateway]
        WS[market-ws-gateway]
    end

    subgraph core [Core Layer]
        ME_A[matcher-005930]
        ME_G[matcher-035420]
        MD[market-data]
        ST[settlement]
        AC[account-service]
        RD_ING[reference-data]
    end

    subgraph external [External - batch only]
        KRX[KRX via pykrx]
    end

    subgraph data [Data Layer]
        KF[(Kafka/Redpanda)]
        RD[(Redis)]
        PG[(PostgreSQL)]
    end

    KRX -->|daily OHLCV| RD_ING
    RD_ING --> PG

    subgraph observe [Observability]
        Prom[Prometheus]
        Graf[Grafana]
    end

    CLI --> GW
    K6 --> GW
    K6 --> WS
    GW --> AC
    GW --> KF
    KF --> ME_A
    KF --> ME_G
    ME_A --> KF
    ME_G --> KF
    KF --> MD
    KF --> ST
    MD --> WS
    ST --> AC
    ME_A --> RD
    ME_G --> RD
    AC --> PG
    ST --> PG
    GW --> Prom
    ME_A --> Prom
    KF --> Prom
```

### 2.2 Control Layers (학습 핵심)

주식 시장 급등 트래픽은 단일 계층에서 제어할 수 없다. 아래 4계층 각각에서 독립적으로 제어·스케일·관측한다.

```mermaid
flowchart LR
    subgraph L1 [L1 Gateway]
        RL[per-user limit]
        SL[per-symbol limit]
        GL[global limit]
    end

    subgraph L2 [L2 Buffer]
        KQ[Kafka queue]
        LAG[consumer lag metric]
    end

    subgraph L3 [L3 Matcher]
        KEDA[KEDA scale by lag]
        ISO[symbol partition isolate]
    end

    subgraph L4 [L4 Fanout]
        WSL[WS connection limit]
        SMP[quote sampling]
    end

    L1 --> L2 --> L3 --> L4
```

| 계층 | 종목 스파이크 (T2) | 전체 스파이크 (T3/T4) | 제어 수단 |
|------|-------------------|----------------------|-----------|
| L1 Gateway | 심볼별 rate limit | 글로벌 + per-user limit | Token bucket, HTTP 429 |
| L2 Kafka | 해당 파티션 lag 증가 | 전 파티션 lag | retention, consumer pause |
| L3 Matcher | 해당 symbol Pod만 부하 | 전 Matcher 부하 | KEDA (kafka lag), symbol partition |
| L4 WS Gateway | 해당 종목 구독자만 | 전 종목 팬아웃 | connection limit, quote sampling |

### 2.3 Traffic Scenarios

| ID | Name | Pattern | Expected bottleneck |
|----|------|---------|-------------------|
| T1 | `steady` | 100 order/s, uniform | none |
| T2 | `symbol-spike` | 1 symbol 10x for 30s | matcher partition + KEDA |
| T3 | `market-open` | all symbols 5x for 60s | gateway + kafka lag |
| T4 | `flash-event` | T3 + 500 WS subscribe/s | market-ws-gateway |

---

## 3. Technology Decisions

| Area | Choice | Rationale |
|------|--------|-----------|
| Language | **Go 1.22+** | K8s client 생태계, 낮은 latency, 학습 곡선 |
| Local K8s | **kind** | CI 친화, 멀티노드 구성 쉬움 |
| Messaging | **Redpanda** (Kafka API 호환) | 로컬 리소스 절약, Strimzi 대비 경량 |
| Cache | Redis 7 | 호가 스냅샷, rate-limit counter |
| DB | PostgreSQL 16 | 계좌·체결 이력 |
| Metrics | Prometheus + kube-prometheus-stack | HPA/KEDA 메트릭 연동 |
| Dashboards | Grafana | burst scenario 전용 보드 |
| Load test | k6 (v1: K8s Job) | 시나리오-as-code |
| Autoscale | HPA (CPU/RPS) + **KEDA** (kafka lag) | 계층별 스케일 정책 |
| Packaging | **Helm** (umbrella chart) | 서비스별 subchart |
| Dev loop | **Tilt** | 로컬 hot-reload |
| Ingress | nginx-ingress (kind) | rate limit annotation + app-level limit |
| Reference data (primary) | **pykrx** → KRX | API 키 불필요, 일봉·종목 마스터, K8s CronJob 친화 |
| Reference data (fallback) | FinanceDataReader | pykrx 장애 시 KRX 백엔드 대체 |
| Reference data (later) | KRX Open API | 공식 인증키, 운영 안정화 시 전환 |
| Reference data (exclude) | 네이버, yfinance | 비공식·불안정, Primary로 사용 안 함 |

---

## 4. Repository Layout

```
stock-market/
├── README.md
├── docs/
│   └── IMPLEMENTATION_PLAN.md      # this document
├── proto/                          # optional; v1 uses JSON events
├── pkg/
│   ├── events/                     # event schemas + serde
│   ├── orderbook/                  # matching engine library
│   ├── metrics/                    # Prometheus helpers
│   └── ratelimit/                  # token bucket
├── services/
│   ├── reference-data/             # Python: pykrx ingestion CronJob
│   │   ├── Dockerfile
│   │   ├── requirements.txt        # pykrx, psycopg2, prometheus-client
│   │   ├── ingest.py               # KRX → PostgreSQL
│   │   └── calendar.py             # 거래일 판별
│   ├── order-gateway/
│   ├── matcher/
│   ├── market-data/
│   ├── market-ws-gateway/
│   ├── settlement/
│   ├── account-service/
│   ├── trading-bot/                # (Phase 1.6+) 전략·burst 봇
│   └── cli-client/
├── db/
│   └── migrations/
│       ├── 001_reference_data.sql
│       └── 002_accounts.sql
├── loadtest/
│   ├── scenarios/
│   │   ├── steady.js
│   │   ├── symbol-spike.js
│   │   ├── market-open.js
│   │   └── flash-event.js
│   └── k8s/                        # Job/CronJob manifests
├── deploy/
│   ├── helm/
│   │   └── stock-exchange/         # umbrella chart
│   │       ├── charts/
│   │       │   ├── order-gateway/
│   │       │   ├── matcher/
│   │       │   └── ...
│   │       └── values.yaml
│   ├── kind/
│   │   └── cluster.yaml            # 3 control-plane + workers
│   └── tilt/
│       └── Tiltfile
├── observability/
│   ├── dashboards/
│   │   ├── golden-signals.json
│   │   └── burst-scenarios.json
│   └── alerts/
│       └── slo-rules.yaml
├── Makefile
└── .github/workflows/
    ├── ci.yaml
    └── load-smoke.yaml
```

---

## 5. Service Specifications

### 5.1 order-gateway

| 항목 | 내용 |
|------|------|
| Role | REST 주문 접수, 검증, rate limit, Kafka publish |
| Endpoints | `POST /v1/orders`, `DELETE /v1/orders/{id}`, `GET /v1/health`, `GET /metrics` |
| Rate limits | `global_rps`, `per_user_rps`, `per_symbol_rps` (ConfigMap) |
| 초과 응답 | HTTP 429 + `X-RateLimit-*` headers |
| K8s | Deployment, HPA (CPU 70%), min 2 replicas |
| Publishes | `orders.submitted` (key = symbol) |

### 5.2 matcher (per-symbol StatefulSet)

| 항목 | 내용 |
|------|------|
| Role | in-memory order book, price-time priority matching |
| Input | `orders.submitted` (consumer group `matcher-{symbol}`) |
| Output | `orders.matched`, `trades.executed` |
| State | in-memory primary, Redis snapshot (recovery) |
| K8s | StatefulSet per symbol (v1: 005930, 035420), KEDA on `kafka_consumer_lag` |
| Metrics | `matcher_orders_processed_total{symbol}`, `matcher_match_latency_seconds`, `matcher_book_depth{symbol}` |

### 5.3 market-data

| 항목 | 내용 |
|------|------|
| Role | aggregate trades/quotes, publish to WS topic |
| Input | `trades.executed`, `orders.matched` |
| Output | `market.trades`, `market.quotes` |
| K8s | Deployment, HPA on consumer lag proxy metric |

### 5.4 market-ws-gateway

| 항목 | 내용 |
|------|------|
| Role | WebSocket fanout to clients |
| Endpoint | `WS /v1/stream?symbols=005930,035420` |
| Controls | max connections per IP, per-symbol subscription cap, quote sampling under load |
| K8s | Deployment, HPA on active connections metric |
| Metrics | `ws_active_connections`, `ws_messages_sent_total{symbol}`, `ws_backpressure_drops_total` |

### 5.5 settlement

| 항목 | 내용 |
|------|------|
| Role | T+0 virtual settlement, position update |
| Input | `trades.executed` |
| Output | `positions.updated` |
| K8s | Deployment (consumer), 1-2 replicas, idempotent processing |

### 5.6 account-service

| 항목 | 내용 |
|------|------|
| Role | balances, positions, order pre-check |
| Storage | PostgreSQL |
| Internal API | `GET /internal/accounts/{user}/balance`, `POST /internal/accounts/{user}/reserve` |
| K8s | Deployment + PVC, readiness on DB |

### 5.7 cli-client

| 항목 | 내용 |
|------|------|
| Role | manual testing (submit order, watch stream) |
| K8s | Job or local binary |

### 5.8 reference-data

| 항목 | 내용 |
|------|------|
| Role | KRX 일봉·종목 마스터 수집 → PostgreSQL 적재, 시뮬 기준가 시드 |
| Language | **Python 3.11+** (pykrx 의존; matcher 등 핵심 경로는 Go 유지) |
| Data source (primary) | [pykrx](https://github.com/sharebook-kr/pykrx) → 한국거래소(KRX) |
| Data source (fallback) | FinanceDataReader (pykrx 연속 실패 시) |
| K8s | CronJob (일 1회, 장마감 후) + 수동 Job (backfill) |
| Metrics | `reference_ingest_rows_total`, `reference_ingest_duration_seconds`, `reference_ingest_errors_total{reason}` |
| Non-Goals | 실시간 시세, 네이버 크롤링, 실제 증권 주문 |

**v1 시뮬 종목 (KRX 6자리 코드):**

| symbol | name | 용도 |
|--------|------|------|
| `005930` | 삼성전자 | T2 symbol-spike 대상 |
| `035420` | NAVER | 비스파이크 격리 관측용 |

---

## 6. Reference Data (KRX / pykrx)

### 6.1 데이터 흐름

```mermaid
flowchart LR
    pykrx[pykrx library]
    KRX[(KRX official data)]
    Cron[CronJob reference-data]
    PG[(PostgreSQL)]
    Matcher[matcher startup]
    Bot[trading-bot]

    KRX --> pykrx
    pykrx --> Cron
    Cron -->|UPSERT| PG
    PG -->|sim_seed.open_price| Matcher
    PG -->|daily_ohlcv| Bot
```

**원칙**: 레퍼런스 데이터는 **시드·전략 입력**만 담당. 장중 가격 형성은 **matcher 체결**이 담당.

### 6.2 수집 대상 (pykrx)

| 용도 | pykrx 함수 | 수집 필드 |
|------|------------|-----------|
| 종목 마스터 | `get_market_ticker_list(date, market)` | ticker, market (KOSPI/KOSDAQ) |
| 종목명 | `get_market_ticker_name(ticker)` | name |
| 기간별 일봉 | `get_market_ohlcv(from, to, ticker)` | 시가·고가·저가·종가·거래량 |
| 특정일 전 종목 | `get_market_ohlcv_by_date(date, market)` | 위와 동일 (배치 시드용) |
| 거래일 확인 | `get_previous_business_days(from, to)` | 거래일 캘린더 |

### 6.3 PostgreSQL Schema (`db/migrations/001_reference_data.sql`)

```sql
-- 종목 마스터
CREATE TABLE symbols (
    ticker      VARCHAR(6) PRIMARY KEY,   -- e.g. '005930'
    name        TEXT NOT NULL,
    market      VARCHAR(10) NOT NULL,     -- KOSPI | KOSDAQ | KONEX
    is_active   BOOLEAN NOT NULL DEFAULT true,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 일봉 OHLCV (KRX 기준, 가격은 원화 정수)
CREATE TABLE daily_ohlcv (
    ticker       VARCHAR(6) NOT NULL REFERENCES symbols(ticker),
    trade_date   DATE NOT NULL,
    open_price   BIGINT NOT NULL,         -- 시가 (원)
    high_price   BIGINT NOT NULL,         -- 고가
    low_price    BIGINT NOT NULL,         -- 저가
    close_price  BIGINT NOT NULL,         -- 종가
    volume       BIGINT NOT NULL,         -- 거래량 (주)
    source       VARCHAR(20) NOT NULL DEFAULT 'pykrx',
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, trade_date)
);

CREATE INDEX idx_daily_ohlcv_date ON daily_ohlcv(trade_date);

-- 시뮬 장 시작 시드 (matcher가 읽음)
CREATE TABLE sim_seed (
    ticker       VARCHAR(6) NOT NULL REFERENCES symbols(ticker),
    trade_date   DATE NOT NULL,
    open_price   BIGINT NOT NULL,         -- 당일 시가 → 기준가
    prev_close   BIGINT,                  -- 전일 종가 (봇 전략 참고)
    PRIMARY KEY (ticker, trade_date)
);

-- 수집 실행 이력 (idempotency·디버깅)
CREATE TABLE ingest_runs (
    run_id       UUID PRIMARY KEY,
    trade_date   DATE NOT NULL,
    source       VARCHAR(20) NOT NULL,
    status       VARCHAR(20) NOT NULL,    -- success | partial | failed
    rows_upserted INT NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ
);
```

**가격 단위**: KRX/pykrx는 **원화 정수**를 반환. DB·이벤트 스키마 모두 `BIGINT` 원 단위로 통일 (한국 주식 최소 호가와 일치).

### 6.4 Ingestion 동작 (`services/reference-data/ingest.py`)

| 모드 | 트리거 | 동작 |
|------|--------|------|
| `daily` | CronJob (평일 18:00 KST) | 당일 거래일 OHLCV + sim_seed UPSERT |
| `backfill` | 수동 Job | `--from YYYYMMDD --to YYYYMMDD --tickers 005930,035420` |
| `bootstrap` | 최초 설치 | 최근 30거래일 backfill + symbols 마스터 |

**의사 코드:**

```python
# 1. trade_date = 최근 확정 거래일 (주말·휴장 제외)
# 2. symbols 마스터 UPSERT (get_market_ticker_list)
# 3. v1 tickers에 대해 get_market_ohlcv(trade_date, trade_date, ticker)
# 4. daily_ohlcv UPSERT (ON CONFLICT UPDATE)
# 5. prev_close = 전 거래일 종가 조회 → sim_seed UPSERT
# 6. ingest_runs 기록
```

### 6.5 거래일 처리 (`calendar.py`)

| 규칙 | 처리 |
|------|------|
| 주말 | pykrx `get_previous_business_days`로 최근 거래일 사용 |
| 공휴일 | 데이터 없음 → ingest 실패 기록, **전일 데이터로 sim_seed 폴백 안 함** (stale 명시) |
| 당일 장중 | CronJob은 장마감 후만 실행 (미확정 OHLCV 방지) |
| pykrx 장애 | 3회 retry → FinanceDataReader fallback → 실패 시 `ingest_runs.status=failed` |

### 6.6 Matcher / Bot 연동

| 소비자 | 읽기 | 용도 |
|--------|------|------|
| matcher (startup) | `sim_seed` WHERE `trade_date = $today` | 호가창 초기 mid-price / 기준가 |
| trading-bot | `daily_ohlcv` 최근 N일 | 이동평균 등 전략 입력 |
| account-service | `symbols` | 주문 검증 시 유효 종목 |

matcher는 레퍼런스 가격을 **강제 적용하지 않음**. 기준가만 설정하고 이후 체결가는 주문 흐름으로 결정.

### 6.7 K8s 리소스

```yaml
# CronJob: exchange/reference-data-daily
# schedule: "0 9 * * 1-5"   # UTC 09:00 = KST 18:00 (하절기 기준 조정)
# Job: exchange/reference-data-backfill (수동)
```

| 리소스 | 설정 |
|--------|------|
| CronJob | `schedule` 평일 1회, `concurrencyPolicy: Forbid` |
| resources | requests 256Mi/200m, limits 512Mi/500m |
| env | `DATABASE_URL`, `INGEST_TICKERS=005930,035420`, `PYKRX_MARKETS=KOSPI,KOSDAQ` |
| Secret | DB credentials |

### 6.8 Makefile Targets (추가)

```bash
make ingest-bootstrap   # 최초 30거래일 backfill Job
make ingest-daily       # 수동 daily ingest Job
make ingest-backfill FROM=20250101 TO=20250620
```

---

## 7. Event Schema

v1은 JSON 사용. 가격은 float 회피를 위해 **원화 정수(int64)** 사용 (KRX 일봉과 동일 단위).

### 7.1 orders.submitted

```json
{
  "event_id": "uuid",
  "order_id": "uuid",
  "user_id": "string",
  "symbol": "005930",
  "side": "BUY",
  "type": "LIMIT",
  "price": 15000,
  "qty": 10,
  "timestamp": "2026-06-21T09:30:00Z"
}
```

### 7.2 orders.matched

```json
{
  "event_id": "uuid",
  "order_id": "uuid",
  "symbol": "005930",
  "matched_qty": 5,
  "remaining_qty": 5,
  "status": "PARTIAL",
  "timestamp": "2026-06-21T09:30:00Z"
}
```

### 7.3 trades.executed

```json
{
  "trade_id": "uuid",
  "symbol": "005930",
  "price": 15000,
  "qty": 5,
  "buy_order_id": "uuid",
  "sell_order_id": "uuid",
  "timestamp": "2026-06-21T09:30:01Z"
}
```

### 7.4 Kafka Topics

| Topic | Partitions (v1) | Key | Retention |
|-------|-----------------|-----|-----------|
| orders.submitted | 8 (symbol hash) | symbol | 24h |
| orders.matched | 8 | symbol | 24h |
| trades.executed | 8 | symbol | 7d |
| market.trades | 8 | symbol | 1h |
| market.quotes | 8 | symbol | 1h |
| positions.updated | 4 | user_id | 7d |

---

## 8. Observability Contract

### 8.1 Golden Signals (per service)

| Signal | Metric pattern |
|--------|----------------|
| Latency | histogram `*_duration_seconds` |
| Traffic | counter `*_requests_total` or `*_messages_total` |
| Errors | counter `*_errors_total{reason}` |
| Saturation | gauge `*_queue_depth`, `kafka_consumer_lag`, `go_goroutines` |

### 8.2 Symbol-Level Labels

Matcher, gateway, market-data 메트릭은 가능한 경우 **`symbol` label 필수**.

### 8.3 Grafana Dashboards

| Dashboard | Purpose |
|-----------|---------|
| `golden-signals.json` | 서비스 overview, RED method |
| `burst-scenarios.json` | T2/T3/T4 overlay: RPS, p99, lag, replica count, 429 rate |

### 8.4 Alert Rules (Prometheus)

| Alert | Condition |
|-------|-----------|
| `KafkaConsumerLagHigh` | lag > 1000 for 2m |
| `GatewayRejectRateHigh` | 429 rate > 10% for 1m |
| `MatcherLatencySLO` | p99 > 500ms for 3m |
| `PodOOMKilled` | any OOM in exchange namespace |
| `ReferenceIngestFailed` | `ingest_runs.status=failed` or CronJob failure |

---

## 9. Load Test Integration

### 9.1 k6 Scenarios (`loadtest/scenarios/`)

각 시나리오가 export하는 커스텀 메트릭:

- `orders_submitted_rate`
- `orders_rejected_rate`
- `end_to_end_latency` (WS 또는 poll 기반)

### 9.2 K8s Execution

`loadtest/k8s/` 아래에 시나리오별 Job manifest:

- `steady-job.yaml`
- `symbol-spike-job.yaml`
- `market-open-job.yaml`
- `flash-event-job.yaml`

### 9.3 CI Smoke

`.github/workflows/load-smoke.yaml`:

1. kind 클러스터 생성
2. Helm chart deploy
3. `steady.js` at 10 order/s for 60s
4. assert p99 < 500ms

---

## 10. Phase / PR Implementation Plan

### Phase 0 — Platform Foundation (Week 1)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-0.1 | `chore: scaffold repo layout + Makefile` | Makefile targets (`kind-up`, `kind-down`, `helm-install`, `tilt-up`), kind 3-node cluster config | `make kind-up` succeeds |
| PR-0.2 | `feat: deploy observability stack` | kube-prometheus-stack Helm values, Grafana dashboard shells, ServiceMonitor CRD pattern | Grafana accessible |
| PR-0.3 | `feat: deploy data layer` | Redpanda, Redis, PostgreSQL subcharts, NetworkPolicy | pods healthy in exchange namespace |
| PR-0.4 | `feat: k6 loadtest skeleton` | `steady.js` + mock HTTP server, Prometheus scrapes k6 metrics | k6 Job completes |

**Phase 0 exit gate**: `make kind-up && make helm-install` → infra + Grafana up; k6 Job completes.

---

### Phase 0.5 — Reference Data Ingestion (Week 1-2)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-0.5.1 | `feat: db migrations for reference data` | `db/migrations/001_reference_data.sql`, symbols/daily_ohlcv/sim_seed/ingest_runs | migration applies cleanly |
| PR-0.5.2 | `feat: reference-data ingest service` | Python `ingest.py`, `calendar.py`, pykrx daily + backfill modes, Dockerfile | local `ingest.py --date 20250620` upserts rows |
| PR-0.5.3 | `feat: reference-data Helm CronJob` | CronJob + backfill Job manifest, env ConfigMap, Prometheus metrics | `make ingest-bootstrap` populates PG |
| PR-0.5.4 | `test: reference data validation` | 005930/035420 시가·종가 존재 assert, ingest_runs success 기록 | `SELECT * FROM sim_seed` returns 2 rows |

**Phase 0.5 exit gate**: PostgreSQL에 005930·035420 최근 30거래일 OHLCV + 당일 `sim_seed` 존재.

---

### Phase 1 — Single Symbol Pipeline (Week 2-3)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-1.1 | `feat: pkg/orderbook matching engine` | Limit order, price-time priority, partial fill, cancel, table-driven unit tests | `go test ./pkg/orderbook/...` pass |
| PR-1.2 | `feat: matcher service (005930 only)` | Kafka consumer/producer, in-memory book, `sim_seed` 기준가 로드, `/metrics` | matcher processes orders |
| PR-1.3 | `feat: order-gateway v1` | POST /v1/orders, Kafka publish, basic validation (no rate limit yet) | curl POST returns 202 |
| PR-1.4 | `feat: account-service v1` | Seed users, balance check, reserve on submit | insufficient balance rejected |
| PR-1.5 | `test: symbol-spike scenario (matcher path)` | k6 → gateway → kafka → matcher, Grafana panel for latency + lag | T1 pass; T2 visible on dashboard |
| PR-1.6 | `feat: trading-bot skeleton` | 단순 랜덤 매수/매도 봇, `daily_ohlcv` 조회, order-gateway 호출 | bot Pod submits orders |

**Phase 1 exit gate**: T1 steady 100 order/s passes; T2 symbol-spike visible on dashboard; bot orders 체결됨.

---

### Phase 2 — Load Control Layer (Week 4)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-2.1 | `feat: gateway rate limiting` | `pkg/ratelimit` token bucket, ConfigMap limits, 429 metrics, integration tests | 429 rate metric non-zero under load |
| PR-2.2 | `feat: KEDA scaler for matcher` | ScaledObject on kafka lag per symbol | replicas scale up on T2 |
| PR-2.3 | `feat: gateway HPA + PDB` | min 2 replicas, PDB minAvailable 1 | pod kill during T3, no downtime |
| PR-2.4 | `test: market-open scenario` | T3 script + Job manifest, verify 429 + lag recovery | lag recovers < 60s |

**Phase 2 exit gate**: T3 completes without OOM; lag recovers < 60s.

---

### Phase 3 — Multi-Symbol + Isolation (Week 5)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-3.1 | `feat: matcher StatefulSet templating (Helm)` | Parametrize symbols `[005930, 035420]`, per-symbol consumer group | both matchers running |
| PR-3.2 | `feat: settlement + positions` | Consume trades.executed, update PostgreSQL | positions reflect trades |
| PR-3.3 | `test: symbol-spike isolation proof` | T2 on 005930 only; assert 035420 p99 unaffected | 035420 p99 < 300ms during 005930 spike |

**Phase 3 exit gate**: T2 spike on 005930, 035420 p99 stays < 300ms.

---

### Phase 4 — Market Data + WS Fanout (Week 6)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-4.1 | `feat: market-data service` | Publish market.trades, market.quotes | topics receive events |
| PR-4.2 | `feat: market-ws-gateway` | WebSocket stream, connection limits, sampling under load | WS clients receive quotes |
| PR-4.3 | `test: flash-event scenario` | T4 combined load, validate `ws_backpressure_drops_total` | no pod crash; backpressure metrics non-zero |

**Phase 4 exit gate**: T4 runs without pod crash; backpressure metrics validated.

---

### Phase 5 — Hardening + CI (Week 7)

| PR | Branch/Title | Tasks | Exit check |
|----|--------------|-------|------------|
| PR-5.1 | `feat: chaos tests (manual)` | `kubectl delete pod` on matcher during T2; assert recovery | matcher recovers, no data loss |
| PR-5.2 | `ci: load smoke workflow` | kind in GHA, steady.js smoke | CI green |
| PR-5.3 | `docs: burst scenario runbook` | Section 11 runbook 완성, README 업데이트 | all T1-T4 documented |

**Phase 5 exit gate**: CI green; all T1-T4 documented with commands.

---

## 11. Agent Execution Notes

### 11.1 Makefile Targets (to be created in PR-0.1)

```bash
make kind-up          # create 3-node kind cluster
make kind-down        # delete cluster
make deps             # add helm repos
make install-infra    # redpanda, redis, postgres, prometheus, keda
make install-apps     # exchange services
make tilt-up          # dev loop with hot-reload
make test-steady      # k6 steady scenario
make test-symbol-spike
make test-market-open
make test-flash-event
make ingest-bootstrap   # Phase 0.5
make ingest-daily
make ingest-backfill FROM=20250101 TO=20250620
```

### 11.2 PR Workflow Rules

1. Section 10의 PR **한 행 = PR 하나**
2. 각 PR 포함 항목: 코드 + Helm values + dashboard diff (메트릭 추가 시) + test scenario update
3. Merge 전 필수: `go test ./...` + 해당 phase k6 smoke
4. 새 메트릭 추가 시 `observability/dashboards/` 동시 업데이트

### 11.3 Config Knobs for Experiments

| Knob | Location | Purpose |
|------|----------|---------|
| `gateway.globalRps` | `deploy/helm/stock-exchange/values.yaml` | L1 global throttle |
| `gateway.perSymbolRps` | values.yaml | T2 symbol limit test |
| `keda.lagThreshold` | matcher subchart values | scale trigger sensitivity |
| `ws.maxConnections` | ws-gateway subchart values | T4 fanout limit |
| `k6.vus` | `loadtest/scenarios/*.js` | spike intensity |
| `reference.ingestTickers` | reference-data values.yaml | 수집 대상 종목 |
| `reference.backfillDays` | ingest Job args | bootstrap 기간 |

### 11.4 Phase 진행 시 에이전트 체크리스트

```
[ ] 이전 Phase exit gate 통과 확인
[ ] 현재 PR scope만 구현 (drive-by refactor 금지)
[ ] Helm values 기본값이 로컬 kind에서 동작하는지 확인
[ ] 새 env var는 ConfigMap/Secret으로 문서화
[ ] loadtest 시나리오 또는 CI smoke 업데이트
[ ] Grafana dashboard 패널 추가 (메트릭 변경 시)
```

---

## 12. Burst Scenario Runbook

> Phase 5 (PR-5.3)에서 상세화. 아래는 실행 골격.

### 12.1 Prerequisites

```bash
make kind-up
make install-infra
make install-apps
# Grafana: kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
```

### 12.2 T1 — Steady

```bash
make test-steady
```

**관측 포인트**: 전 서비스 p99 < 200ms, kafka lag ≈ 0, HPA replica 변동 없음.

### 12.3 T2 — Symbol Spike

```bash
make test-symbol-spike
# 또는: kubectl apply -f loadtest/k8s/symbol-spike-job.yaml
```

**관측 포인트**:
- `matcher_match_latency_seconds{symbol="005930"}` p99 상승
- `kafka_consumer_lag` 005930 파티션만 spike
- KEDA가 matcher-005930 replica 증가
- 035420 메트릭은 안정

### 12.4 T3 — Market Open

```bash
make test-market-open
```

**관측 포인트**:
- `gateway_requests_total{status="429"}` 증가
- 전 파티션 kafka lag spike → 60s 내 회복
- HPA gateway replica 증가

### 12.5 T4 — Flash Event

```bash
make test-flash-event
```

**관측 포인트**:
- `ws_active_connections` 급증
- `ws_backpressure_drops_total` > 0 (극한 설정 시)
- OOMKill 이벤트 없음

### 12.6 Chaos (수동)

```bash
# T2 실행 중
kubectl delete pod -n exchange -l app=matcher,symbol=005930
# 기대: 새 pod 기동, kafka lag 일시 증가 후 회복, 유실 주문 없음
```

---

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Local machine OOM under T3/T4 | 테스트 실패 | kind resource limits; 초기 RPS를 목표의 1/5로 시작 |
| Redpanda single broker lag | Phase 3 병목 | Phase 1부터 lag 모니터링; Phase 3 전 partition 수 증가 |
| Float price bugs | 체결 오류 | int64 KRW everywhere, JSON schema validation |
| KEDA install complexity | Phase 2 지연 | Makefile에 helm install 자동화; chart version pin |
| Redis snapshot race | matcher 재시작 시 상태 불일치 | snapshot + kafka offset 함께 저장; idempotent replay |
| pykrx/KRX 사이트 변경 | reference ingest 실패 | FinanceDataReader fallback; ingest_runs 알림; KRX Open API 전환 경로 |
| 휴장일·미확정 일봉 | sim_seed 누락 | 장마감 후 CronJob만 실행; stale seed 사용 금지 |

---

## 14. Open Decisions

| Decision | v1 Choice | Alternative (later) |
|----------|-----------|---------------------|
| Reference data source | **pykrx → KRX** | KRX Open API (공식 인증키) |
| Reference fallback | FinanceDataReader | 수동 CSV import |
| Message broker | Redpanda | Strimzi Kafka |
| Event format | JSON | Protobuf (`proto/` dir reserved) |
| Service mesh | None | Linkerd/Istio for mTLS |
| Symbols | 005930, 035420 (Helm values) | Dynamic via CRD/Operator |
| k6 operator | K8s Job | Grafana k6 operator |
| Realtime feed | None (v1) | KIS Open API WebSocket |

---

## Appendix: PR Dependency Graph

```mermaid
flowchart TD
    P01[PR-0.1 scaffold] --> P02[PR-0.2 observability]
    P01 --> P03[PR-0.3 data layer]
    P02 --> P04[PR-0.4 k6 skeleton]
    P03 --> P04

    P03 --> P051[PR-0.5.1 db migration]
    P051 --> P052[PR-0.5.2 ingest service]
    P052 --> P053[PR-0.5.3 CronJob]
    P053 --> P054[PR-0.5.4 validation]

    P04 --> P054
    P054 --> P11[PR-1.1 orderbook]
    P11 --> P12[PR-1.2 matcher]
    P03 --> P12
    P12 --> P13[PR-1.3 gateway]
    P13 --> P14[PR-1.4 account]
    P14 --> P15[PR-1.5 symbol-spike test]
    P15 --> P16[PR-1.6 trading-bot]

    P16 --> P21[PR-2.1 rate limit]
    P21 --> P22[PR-2.2 KEDA]
    P22 --> P23[PR-2.3 HPA PDB]
    P23 --> P24[PR-2.4 market-open test]

    P24 --> P31[PR-3.1 multi-symbol]
    P31 --> P32[PR-3.2 settlement]
    P32 --> P33[PR-3.3 isolation proof]

    P33 --> P41[PR-4.1 market-data]
    P41 --> P42[PR-4.2 ws-gateway]
    P42 --> P43[PR-4.3 flash-event test]

    P43 --> P51[PR-5.1 chaos]
    P43 --> P52[PR-5.2 CI smoke]
    P51 --> P53[PR-5.3 runbook]
    P52 --> P53
```

---

*Last updated: 2026-06-21 (Phase 0.5 reference-data 추가)*