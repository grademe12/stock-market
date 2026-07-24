# 거래 참여자 시뮬레이션 계획

> **목적**: 여러 가상 시장참여자가 각기 다른 주문 결정을 내리도록 해, 내부 order book에서 체결·잔량·취소·가격 움직임이 발생하는 시장을 만든다.
>
> 이 문서의 기본 대상은 시장조성자가 아닌 일반 거래 참여자다. 시장조성자/유동성공급자 전략은 비교 실험을 위한 선택 항목으로만 둔다.

**관련 문서**: [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) · [KRX_TOP100_REFERENCE_DATA_PLAN.md](./KRX_TOP100_REFERENCE_DATA_PLAN.md)

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

참여자는 한 번에 매수 또는 매도 한 방향 주문만 낸다. 따라서 시장에 양방향 유동성이 생기는 것은 여러 참여자의 집합 행동 결과다.

### P2 — Momentum Trader

최근 체결가 또는 최근 주문 흐름이 상승이면 매수 확률을 높이고, 하락이면 매도 확률을 높인다. 가격에 추세가 생길 때 체결률과 호가 잔량이 어떻게 달라지는지 관찰하는 용도다.

### P3 — Mean-Reversion Trader

기준가보다 충분히 높은 가격에서는 매도, 낮은 가격에서는 매수 확률을 높인다. Momentum Trader와 함께 사용할 때 상반된 전략이 시장에 미치는 영향을 비교한다.

### P4 — Optional Liquidity Provider

기준가 양쪽에 수동적 양방향 호가를 유지하고, 체결·취소 후 재호가한다. 기본 시나리오의 전제가 아니라 비교 플래그로만 사용한다.

---

## 4. 아키텍처 제약과 구성

현재 order book은 Django 서버 프로세스의 메모리에 존재한다. 따라서 별도 `manage.py` 프로세스나 별도 worker에서 봇을 실행하면 서로 다른 order book을 보게 된다.

초기 구현은 단일 Django 프로세스 안에서만 동작한다.

```text
DRF API / Bot control API
             │
             ▼
     ParticipantOrchestrator
       ├─ participant registry
       ├─ deterministic random generator
       ├─ outstanding-order TTL 관리
       └─ tick loop (daemon thread)
             │
             ▼
      동일 프로세스의 OrderBook
```

`ParticipantOrchestrator.tick()`은 동기 함수로 먼저 구현한다. background thread는 이 함수를 일정 주기로 호출하는 얇은 실행 계층으로만 둔다. 이렇게 하면 테스트에서 시간·thread 의존 없이 tick 단위로 결과를 검증할 수 있다.

---

## 5. API 초안

제어 API는 로컬 개발·실험 목적이다. 인증·권한은 계좌 기능을 도입할 때 별도 설계한다.

| Method | Endpoint | 용도 |
|---|---|---|
| `POST` | `/api/v1/simulations/participants/start/` | 시뮬레이션 시작 |
| `DELETE` | `/api/v1/simulations/participants/` | 실행 중지 |
| `GET` | `/api/v1/simulations/participants/` | 상태·tick·주문·체결 통계 확인 |
| `POST` | `/api/v1/simulations/participants/tick/` | 수동으로 한 tick 실행 |

시작 요청 예시:

```json
{
  "strategy": "noise",
  "participants": 20,
  "reference_price": 70000,
  "price_step": 100,
  "max_offset_steps": 5,
  "quantity_min": 1,
  "quantity_max": 10,
  "order_ttl_ticks": 5,
  "interval_ms": 1000,
  "seed": 42
}
```

---

## 6. 구현 단위와 완료 기준

### P1.1 — 참여자 도메인 모델

- `TradingParticipant` 프로토콜
- `NoiseTrader` 주문 생성
- 주문 의도(`OrderIntent`)와 난수 seed 관리

**완료 기준**: 같은 seed와 tick 번호에서 동일한 주문 의도가 생성된다.

### P1.2 — Orchestrator와 주문 수명주기

- 참가자별 `user_id` 생성
- `OrderBook.submit()` 호출
- 미체결 주문 ID와 TTL 추적
- TTL 만료 주문 취소
- 제출·체결·취소 카운터 기록

**완료 기준**: 여러 tick 실행 후 봇 주문이 무한히 누적되지 않고, 체결·취소 통계를 확인할 수 있다.

### P1.3 — DRF 제어 API

- start/stop/status/tick endpoint
- 시작 중복 호출 방지
- stop 후 thread 종료 확인
- `DEBUG` 환경에서만 start endpoint 사용 허용

**완료 기준**: HTTP API로 20명 참여자 시뮬레이션을 시작하고 상태를 조회할 수 있다.

### P1.4 — 통합 테스트와 실험 시나리오

- 수동 tick이 주문·체결·취소를 만든다.
- 동일 seed 실행 결과가 재현된다.
- 사용자 주문이 봇 주문과 체결된다.
- LP 활성화 여부를 제외한 일반 참가자 시나리오가 동작한다.

**완료 기준**: `make backend-test`와 수동 tick 시나리오가 성공한다.

---

## 7. 관측 항목

Stage 3 Prometheus 도입 전에는 status API와 테스트 결과로 확인한다.

| 항목 | 의미 |
|---|---|
| `ticks_total` | 실행된 tick 수 |
| `orders_submitted_total` | 봇이 낸 주문 수 |
| `orders_canceled_total` | TTL로 취소된 주문 수 |
| `trades_generated_total` | 봇 주문으로 발생한 체결 수 |
| `open_bot_orders` | 현재 미체결 봇 주문 수 |
| `last_tick_at` | 마지막 실행 시각 |
| `last_error` | 마지막 실행 오류 |

Prometheus 도입 후에는 위 항목을 metric으로 승격하고, k6 주문 흐름과 함께 대시보드에서 비교한다.

---

## 8. KRX 참조 데이터와의 연결

KRX 상위 100개 종목 수집은 별도 작업이다. 이 시뮬레이터의 첫 버전은 고정 `reference_price`만 사용한다.

참조 데이터 적재가 안정되면 다음을 별도 작업으로 검토한다.

- 상위 100개 중 선택한 종목을 participant 대상 심볼로 사용
- 최근 종가를 `reference_price` 기본값으로 사용
- 거래대금을 참가자 수·주문 빈도 가중치에 반영

외부 API 호출은 tick 또는 주문 요청 경로에서 수행하지 않는다.

---

*Last updated: 2026-07-25*
