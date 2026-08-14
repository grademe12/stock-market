# 거래 참여자 시뮬레이션 계획

> **목적**: 여러 가상 시장참여자가 각기 다른 주문 결정을 내리도록 해, 내부 order book에서 체결·잔량·취소·가격 움직임이 발생하는 시장을 만든다.
>
> 이 문서의 기본 대상은 시장조성자가 아닌 일반 거래 참여자다. 시장조성자/유동성공급자 전략은 비교 실험을 위한 선택 항목으로만 둔다.

**관련 문서**: [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) · [KRX_TOP100_REFERENCE_DATA_PLAN.md](./KRX_TOP100_REFERENCE_DATA_PLAN.md) · [NEWS_TRIGGERED_LOAD_SPIKE_PLAN.md](./NEWS_TRIGGERED_LOAD_SPIKE_PLAN.md)

**현재 상태**: Noise·Momentum·Mean-Reversion·선택적 LP, TTL 기반 주문 취소, 트레이더별 영속 설정 CRUD API와 별도 HTTP participant-runner 구현 완료. 모든 트레이더는 external runner에서만 실행하며 Django 내부 runtime은 사용하지 않는다.

---

## 1. 문제와 목표

현재 order book은 주문 API를 받지만, 외부 주문이 없으면 호가와 체결이 자연스럽게 누적되지 않는다. k6가 주문을 보내더라도 한쪽 주문만 쌓이거나 체결 비율이 낮을 수 있다.

해결하려는 문제는 “항상 호가를 내는 봇”을 만드는 것이 아니라, 여러 참가자의 서로 다른 판단이 주문 흐름을 만들도록 하는 것이다.

### 목표

- 복수의 가상 사용자 ID가 독립적으로 매수·매도 지정가 주문을 낸다.
- 일부 주문은 체결되고, 일부는 미체결 후 취소 또는 만료된다.
- 동일 random seed에서 동일한 시나리오를 재현할 수 있다.
- 주문 제출·체결·취소·호가 조회의 전체 경로를 부하 테스트 전에 검증한다.

### 비목표

- 실제 투자 수익 예측 또는 투자 조언
- 실제 증권사 계좌·주문 API 연동
- 실제 계좌 잔고·포지션 강제 (후속 account 단계에서 도입)
- 실시간 KRX/KIS 데이터를 매 tick마다 조회
- 시장 미시구조를 현실과 동일하게 재현한다고 주장하는 것

---

## 2. 유동성의 두 종류

### 2.1 자연 발생 유동성: 기본 시뮬레이션 대상

일반 시장에서의 호가창 유동성은 개인·기관·알고리즘 등 다수 참여자가 각자의 기대와 제약에 따라 낸 미체결 주문의 집합이다. 시뮬레이터에서는 여러 `TradingParticipant`의 주문·취소 행동으로 이 효과를 모델링한다.

```text
Noise / Momentum / Mean-Reversion 참여자
  → 서로 다른 시점·가격·방향의 지정가 주문
  → order book에 미체결 호가 축적
  → 교차 주문 체결 또는 만료·취소
```

### 2.2 지정 유동성 공급자: 선택적 비교 대상

시장조성자(MM) 또는 유동성공급자(LP)는 특정 상품에서 양방향 호가를 지속 제시하도록 명시적으로 운영되는 전문 참여자다. 시뮬레이터에서는 일반 참여자와 구분된 `LiquidityProvider` 전략으로 표현한다.

이 전략은 기본 시장을 성립시키기 위한 필수 요소가 아니다. 다음 비교가 필요할 때만 활성화한다.

- LP 유무에 따른 best bid/ask spread 변화
- LP 유무에 따른 체결률·미체결 주문 수 변화
- 급격한 주문 유입 시 호가 공백과 가격 변동성 변화

---

## 3. 단계적 전략 도입

### P1 — Noise Trader (첫 구현)

가장 단순한 일반 참여자다. 정해진 난수 seed로 매수/매도, 수량, 지정가 오프셋, 주문 간격을 생성한다.

| 설정 | 예시 | 의미 |
|---|---:|---|
| `participants` | 20 | 가상 참여자 수 |
| `reference_price` | 70,000 | 가격 생성 기준 |
| `price_step` | 100 | 기준가에서 이동하는 최소 단위 |
| `max_offset_steps` | 5 | 가격 오프셋 범위 |
| `quantity_range` | 1~10 | 주문 수량 범위 |
| `order_ttl_ticks` | 5 | 미체결 주문 만료 tick |
| `seed` | 42 | 재현 가능한 난수 seed |

각 참가자는 위 기본값을 공유하지 않아도 된다. `TraderProfile`은 `name`, `user_id`, `enabled`와 함께 가격·수량·TTL·실행 주기(`interval_ticks`)·seed를 개별적으로 보관한다. 이는 Django 모델과 DRF API에만 의존하며, 봇 도메인 코드는 `TraderSettings`로 변환된 값만 받는다.

Noise·Momentum·Mean-Reversion 참여자는 한 tick에 매수 또는 매도 한 방향 주문만 낸다. LP는 예외적으로 양방향 호가를 함께 낸다.

### P2 — Momentum Trader (구현 완료)

runner가 읽은 현재 midpoint를 직전 실행 tick의 midpoint와 비교한다. 상승하면 best ask 가격으로 매수하고, 하락하면 best bid 가격으로 매도한다. 첫 관측과 보합에서는 주문하지 않는다. 현재 거래 API가 최근 체결가 이력을 제공하지 않으므로 이 단계에서는 호가 midpoint를 추세 신호로 사용한다.

### P3 — Mean-Reversion Trader (구현 완료)

midpoint가 프로필의 `reference_price`보다 `price_step` 이상 낮으면 best ask 가격으로 매수하고, 같은 폭 이상 높으면 best bid 가격으로 매도한다. 기준가 주변 한 호가 범위에서는 주문하지 않는다. Momentum Trader와 함께 사용할 때 상반된 전략이 시장에 미치는 영향을 비교한다.

### P4 — Optional Liquidity Provider (구현 완료)

현재 midpoint의 한 호가 아래에 매수, 한 호가 위에 매도를 같은 tick에 제출한다. 중심가는 프로필 기준가의 `max_offset_steps × price_step` 범위를 벗어나지 않게 제한한다. 주문은 다른 전략과 같은 TTL 규칙으로 취소·재제출되며, 기본 시나리오의 전제가 아니라 비교용 프로필로만 사용한다.

---

## 4. 아키텍처 제약과 구성

현재 order book은 Django 서버 프로세스의 메모리에 존재한다. 따라서 트레이더는 별도 프로세스에서 `OrderBook`을 직접 호출하지 않고, 모두 HTTP API를 거쳐 backend의 단일 호가창에 접근한다.

```text
participant-runner
  ├─ GET /traders/로 활성 프로필 로드
  ├─ tick마다 GET /books/{symbol}/
  ├─ 전략별 0~2개 주문 의도 생성
  ├─ POST /orders/
  └─ TTL 뒤 DELETE /orders/{id}/
             │ HTTP
             ▼
      Django의 단일 OrderBook
```

runner는 종목별 호가를 tick당 한 번만 조회한다. 같은 tick에 있는 여러 트레이더는 동일한 스냅샷으로 판단하므로, 앞선 트레이더의 주문 결과는 다음 tick부터 전략 입력에 반영된다. midpoint는 양쪽 호가가 있으면 best bid와 best ask의 정수 평균, 한쪽만 있으면 그 가격, 호가가 없으면 각 프로필의 기준가다.

### 4.1 외부 participant-runner

루트의 `participant-runner/`는 별도 프로세스/컨테이너로 동작하며, `GET /traders/`로 활성 프로필을 읽고 `GET /books/{symbol}/`, `POST /orders/`, `DELETE /orders/{id}/`만 호출한다. 즉 runner는 API 소비자이고, 매칭 상태를 공유하지 않는다. backend 내부 start/stop/manual-tick API는 제거했다.

```text
participant-runner container
  └─ HTTP requests → Django REST API → in-memory OrderBook
```

프로필 수가 가상 트레이더 수의 기준이며, 컨테이너 환경 변수 `MAX_TRADERS`와 `TRADER_IDS`는 실행 범위만 제한한다. 첫 버전은 중복 주문 방지를 위해 runner 컨테이너 한 개만 지원한다. 자세한 실행·컨테이너 설정은 [`participant-runner/README.md`](../participant-runner/README.md)를 따른다.

---

## 5. API

트레이더 프로필 변경 API는 로컬 개발·실험 목적이다. 인증·권한은 계좌 기능을 도입할 때 별도 설계한다.

| Method | Endpoint | 용도 |
|---|---|---|
| `GET` / `POST` | `/api/v1/traders/` | 트레이더 설정 목록 조회 / 생성 |
| `GET` / `PATCH` / `DELETE` | `/api/v1/traders/{trader_id}/` | 트레이더 설정 조회 / 수정 / 삭제 |
| `GET` | `/api/v1/books/{symbol}/` | 전략 입력용 호가 스냅샷 조회 |
| `POST` | `/api/v1/orders/` | runner 주문 제출 |
| `DELETE` | `/api/v1/orders/{order_id}/` | runner 미체결 주문 취소 |

트레이더 프로필의 `POST`, `PATCH`, `DELETE`는 현재 인증이 없는 로컬 실험 기능이므로 `DEBUG` 환경에서만 허용한다. 목록·상세 `GET` 응답은 runner와 프론트엔드 폼이 그대로 사용할 수 있도록 모든 설정 필드와 생성·수정 시각을 반환한다.

runner는 `enabled=true`인 트레이더만 실행한다. `TRADER_IDS`와 `MAX_TRADERS` 환경 변수로 실행 대상을 좁힐 수 있으며, 설정이 없으면 주문을 생성하지 않는다.

트레이더 생성 요청 예시:

```json
{
  "name": "momentum-1",
  "user_id": "momentum-profile-001",
  "strategy": "momentum",
  "enabled": true,
  "symbol": "005930",
  "reference_price": 70000,
  "price_step": 100,
  "max_offset_steps": 5,
  "quantity_min": 1,
  "quantity_max": 10,
  "order_ttl_ticks": 5,
  "interval_ticks": 2,
  "seed": 42
}
```

---

## 6. 구현 단위와 완료 기준

### P1.1 — 참여자 도메인 모델

- `TradingParticipant` 프로토콜
- 네 가지 전략의 0~2개 주문 의도 생성
- 주문 의도(`OrderIntent`)와 난수 seed 관리

**완료 기준**: 같은 seed·tick·호가 스냅샷에서 동일한 주문 의도가 생성되고, 각 전략의 방향·가격 규칙이 단위 테스트로 검증된다.

### P1.2 — External runner와 주문 수명주기

- 활성 프로필 조회 및 전략 객체 생성
- 종목별 호가 스냅샷 조회
- HTTP 주문 API 호출
- 미체결 주문 ID와 TTL 추적
- TTL 만료 주문 취소
- 제출·취소·이미 종료·요청 실패 카운터 기록

**완료 기준**: 여러 tick 실행 후 봇 주문이 무한히 누적되지 않고, 체결·취소 통계를 확인할 수 있다.

### P1.3 — 트레이더 프로필과 거래 API

- 트레이더 프로필 CRUD endpoint
- 호가 조회·주문 제출·주문 취소 endpoint
- `DEBUG` 환경에서만 프로필 변경 허용
- backend 내부 실행 endpoint를 제공하지 않음

**완료 기준**: runner가 HTTP API만으로 활성 프로필을 실행하고, backend 프로세스에는 봇 tick thread가 존재하지 않는다.

### P1.4 — 통합 테스트와 실험 시나리오

- external runner의 tick이 호가 조회·주문·취소를 만든다.
- 동일 seed 실행 결과가 재현된다.
- 네 전략의 주문 방향과 가격이 정의된 규칙을 따른다.
- LP가 같은 tick에 bid와 ask를 모두 제출한다.

**완료 기준**: `make backend-test`와 `make participant-runner-test`가 성공한다.

---

## 7. 관측 항목

Stage 3 Prometheus 도입 전에는 runner의 주기적 상태 로그와 테스트 결과로 확인한다.

| 항목 | 의미 |
|---|---|
| `ticks_total` | 실행된 tick 수 |
| `orders_submitted_total` | 봇이 낸 주문 수 |
| `orders_canceled_total` | TTL로 취소된 주문 수 |
| `orders_already_closed_total` | TTL 취소 전에 이미 체결·취소된 주문 수 |
| `request_failures_total` | 호가 조회·주문·취소 HTTP 실패 수 |
| `open_runner_orders` | runner가 추적하는 현재 미체결 주문 수 |

Prometheus 도입 후에는 위 항목을 metric으로 승격하고, k6 주문 흐름과 함께 대시보드에서 비교한다.

---

## 8. KRX 참조 데이터와의 연결

KRX 상위 100개 종목 수집은 별도 작업이다. 이 시뮬레이터의 첫 버전은 고정 `reference_price`만 사용한다.

참조 데이터 적재가 안정되면 다음을 별도 작업으로 검토한다.

- 상위 100개 중 선택한 종목을 participant 대상 심볼로 사용
- 최근 종가를 `reference_price` 기본값으로 사용
- 거래대금을 참가자 수·주문 빈도 가중치에 반영

KRX 같은 외부 참조 API 호출은 tick 또는 주문 요청 경로에서 수행하지 않는다.

---

*Last updated: 2026-08-13 — external runner 전용 실행과 4개 전략 반영*
