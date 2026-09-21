# Regular Market Session Automation Plan

## 1. 목적

현재 시뮬레이션은 participant runner가 실행되는 동안 시간대와 무관하게 주문을 생성하고, matcher backend도 언제든 주문을 수락한다.

이 문서의 목적은 시뮬레이션을 한국 주식시장 정규장과 유사한 운영 리듬으로 바꾸는 것이다.

초기 목표 세션은 다음과 같이 단순화한다.

- 시간대: `Asia/Seoul`
- 거래 가능 요일: 월요일 ~ 금요일
- 개장: 09:00:00
- 장 마감: 15:30:00
- 거래 가능 범위: `09:00 <= now < 15:30`
- 주말: 휴장
- 법정공휴일, 임시휴장일, 조기폐장일: 첫 구현 범위에서 제외

실제 KRX 주문 체계 전체를 재현하는 것이 목적은 아니다. 핵심은 장중에만 시뮬레이션 부하가 발생하고, 장 마감 이후 상태가 다음 거래일로 잘못 이어지지 않도록 만드는 것이다.

---

## 2. 현재 문제

현재 구조에서는 다음 문제가 있다.

### 2.1 backend가 장외 주문도 수락한다

`POST /api/v1/orders/`는 현재 시간이나 거래일을 확인하지 않는다.

따라서 participant runner, k6, 수동 API 호출 등 어느 경로에서든 24시간 주문을 넣을 수 있다.

### 2.2 participant runner가 24시간 tick을 수행한다

`run_until_stopped()`는 프로세스가 살아 있는 동안 계속 `tick_once()`를 호출한다.

그 결과 새벽, 주말에도 다음 작업이 계속 발생할 수 있다.

- 호가창 snapshot 조회
- trader decision
- 신규 주문 제출
- TTL 주문 취소
- event-reactive trader 처리

### 2.3 in-memory order book이 세션 경계를 모른다

matcher의 주문과 호가창은 프로세스 메모리에 존재한다.

프로세스가 계속 실행된 상태에서 장 마감 처리 없이 다음 날이 되면 전날 미체결 주문이 다음 거래일에 남을 수 있다.

이는 세션 기반 시장 시뮬레이션에서는 잘못된 상태다.

### 2.4 observability 상태도 세션과 어긋날 수 있다

order book을 비우더라도 Prometheus의 `orderbook_depth` gauge를 갱신하지 않으면 Grafana에 전날 depth가 남아 있을 수 있다.

세션 종료는 실제 메모리 상태와 관측 상태를 함께 정리해야 한다.

---

## 3. 설계 원칙

### 3.1 MarketSession을 단일 진실로 둔다

backend와 participant runner가 각각 별도의 시간 조건을 구현하지 않는다.

공통 모듈을 추가한다.

예상 위치:

```text
backend/exchange/market_session.py
```

participant runner 이미지가 이미 `backend/exchange`를 함께 복사하므로 별도 공유 패키지를 만들지 않고 동일 모듈을 재사용할 수 있다.

MarketSession이 책임지는 것은 다음 범위다.

```text
timezone = Asia/Seoul
weekday check
09:00 open
15:30 close
is_open(now)
session_date(now)
next_open(now)
```

시간은 테스트에서 주입할 수 있어야 한다.

### 3.2 backend가 최종 주문 수락 권한을 가진다

runner가 장 시간을 지키더라도 backend는 반드시 자체적으로 장 상태를 검증한다.

이유:

- 다른 client가 직접 주문할 수 있음
- runner 버그가 있어도 matcher가 방어해야 함
- 여러 shard가 동일한 규칙을 적용해야 함

따라서 정규장 밖의 `POST /orders/`는 backend에서 최종 거부한다.

### 3.3 조회와 주문 취소는 장외에도 허용한다

다음 API는 장 마감 후에도 사용할 수 있어야 한다.

- order book 조회
- 최근 체결 조회
- symbol 조회
- health/readiness/metrics
- 미체결 주문 취소

특히 `DELETE /orders/{id}/`를 장외에 막으면 15:30 직후 runner가 남은 주문을 정리할 수 없다.

### 3.4 runner 프로세스는 장외에도 살아 있는다

15:30에 runner 프로세스를 종료하지 않는다.

장외에는 주문 생성 tick을 멈추고 다음 개장을 기다린다.

장점:

- metrics endpoint 유지
- Docker/Kubernetes/GCE에서 별도 cron 재기동 불필요
- 다음 평일 09:00 자동 재개
- 운영 상태 추적 용이

### 3.5 부하 실험용 우회 모드를 유지한다

이 프로젝트는 실제 운영 서비스가 아니라 인프라 병목/포화 실험 프로젝트이기도 하다.

정규장 밖에서도 의도적인 부하 테스트를 실행할 수 있도록 다음 모드를 둔다.

```text
SIMULATION_MARKET_MODE=scheduled
SIMULATION_MARKET_MODE=always_open
```

기본값은 `scheduled`.

`always_open`은 CI, 개발 테스트, 수동 부하 실험에서 명시적으로 선택하는 용도다.

---

## 4. 목표 구조

```text
                         MarketSession
                     Asia/Seoul / weekday
                      09:00 <= t < 15:30
                         /           \
                        /             \
                       v               v
                matcher backend   participant runner
                ---------------   ------------------
                POST order gate   market-open tick
                session rollover  closed-state wait
                book reset        close transition
                depth reset       cancel open orders
                        \             /
                         \           /
                          session boundary
                                |
                                v
                      next trading session
                        starts cleanly
```

gateway는 shard routing만 담당하므로 세션 시간 판정 책임을 추가하지 않는다.

---

## 5. 구현 단계

## Phase 1 — 공통 MarketSession 도입

### 작업

`exchange.market_session`에 공통 세션 정책을 구현한다.

최소 API 예시:

```python
class MarketSession:
    def is_open(self, now: datetime | None = None) -> bool: ...
    def session_date(self, now: datetime | None = None) -> date | None: ...
    def next_open(self, now: datetime | None = None) -> datetime: ...
```

또는 같은 책임을 가지는 순수 함수 형태도 허용한다.

### 테스트 기준

최소 다음 경계값을 검증한다.

| KST 시각 | 예상 |
|---|---|
| 월 08:59:59 | closed |
| 월 09:00:00 | open |
| 월 15:29:59 | open |
| 월 15:30:00 | closed |
| 토 12:00:00 | closed |
| 일 12:00:00 | closed |

UTC datetime을 입력해도 KST 기준으로 동일한 결과가 나와야 한다.

### 완료 조건

- backend와 runner가 동일 모듈을 import할 수 있음
- 현재 시각을 직접 고정하지 않고 테스트 가능
- timezone-naive datetime 처리 정책이 명확함

---

## Phase 2 — backend 주문 gate

### 작업

`exchange.views.create_order` 진입부에서 장 상태를 검사한다.

장외 주문은 order serializer 생성 및 order book 변경 전에 거절한다.

권장 응답:

```http
HTTP 409 Conflict
```

예시 payload:

```json
{
  "detail": "market is closed"
}
```

Prometheus rejection reason도 추가한다.

```text
orders_rejected_total{reason="market_closed"}
```

### 변경하지 않는 API

다음 API는 장외에도 정상 제공한다.

- `GET /health/`
- `GET /ready/`
- `GET /metrics/`
- `GET /books/{symbol}/`
- `GET /trades/`
- `GET /symbols/`
- `DELETE /orders/{id}/`

### 완료 조건

- 08:59:59 주문 거부
- 09:00:00 주문 허용
- 15:29:59 주문 허용
- 15:30:00 주문 거부
- 주말 주문 거부
- `always_open` 모드에서는 시간과 무관하게 허용

---

## Phase 3 — session rollover 및 order book 정리

### 문제

runner가 모든 자신 소유 주문을 취소하더라도 matcher에는 다음 경우의 주문이 남을 수 있다.

- 다른 client가 만든 주문
- runner 내부 추적에서 누락된 주문
- 취소 실패 주문
- 테스트/수동 API 호출로 생성된 주문

따라서 세션 청소를 runner에만 의존하지 않는다.

### 작업

`OrderBookRegistry`에 세션 경계를 인지하는 reset 절차를 추가한다.

권장 방식은 새로운 거래 세션으로 진입할 때 현재 registry가 이전 session date의 상태라면 전체 in-memory book을 비우는 lazy rollover다.

필요 상태 예시:

```text
active_session_date
books
order_symbols
```

새 장 시작 시:

```text
old session != current session
        |
        v
clear books
clear order_symbols
reset orderbook depth metrics
set active_session_date
```

장 마감 시 즉시 clear하는 방식도 가능하지만, matcher가 잠시 중단되어 있었다가 다음 날 시작되는 경우까지 안전하게 처리하려면 다음 session 진입 시 rollover 검증이 반드시 있어야 한다.

### 주의

현재 `books.reset()`은 simulation ticker cache까지 초기화한다.

세션 rollover가 종목 universe cache까지 매번 날려야 하는지 검토하고, 필요하면 다음 두 책임을 분리한다.

```text
reset_books()
reset_all_for_tests()
```

### 완료 조건

- 전날 미체결 주문이 다음 날 첫 주문과 체결되지 않음
- order id registry도 함께 정리됨
- 모든 `orderbook_depth` gauge가 세션 reset 후 0
- shard별 backend가 각자 동일하게 rollover 수행

---

## Phase 4 — participant runner 장시간 연동

### 현재

`run_until_stopped()`:

```text
tick
sleep
tick
sleep
...
```

### 목표

```text
market closed
    |
    +--> no trading tick
    +--> wait
    |
09:00
    |
    +--> begin ticks
    |
15:30
    |
    +--> stop creating new orders
    +--> wait for in-flight HTTP
    +--> cancel runner-owned resting orders
    +--> enter closed state
```

### 작업

runner loop에 명시적인 session state transition을 둔다.

예상 상태:

```text
CLOSED
OPEN
```

최소 transition:

```text
CLOSED -> OPEN
OPEN -> CLOSED
```

`OPEN -> CLOSED` 시 한 번만 `cancel_all_open_orders()`를 수행한다.

장외에는 `tick_once()`를 호출하지 않는다.

### 대기 전략

장외에 기존 `TICK_INTERVAL_MS` 단위로 계속 polling할 필요는 없다.

다음 개장 시각을 계산하여 비교적 긴 sleep/wait을 하되, SIGINT/SIGTERM에는 즉시 반응할 수 있도록 `stop_event.wait(timeout)` 형태를 사용한다.

### 완료 조건

- 09:00 이전에는 신규 주문 없음
- 09:00 이후 tick 자동 시작
- 15:30 이후 신규 주문 없음
- 마감 transition에서 runner-owned 미체결 주문 정리
- 주말에는 거래 tick 없음
- 프로세스 및 metrics endpoint는 살아 있음
- `always_open`에서는 기존 24시간 동작 유지

---

## Phase 5 — event-reactive trader와 세션 경계

첫 장시간 PR에서는 실제 뉴스 source 정책까지 해결하지 않는다.

다만 세션 연동 이후 event 처리 정책을 명시적으로 결정해야 한다.

예:

```text
17:00 공시 감지
      |
      +--> 즉시 주문 생성 X
      |
      +--> 다음 장 09:00까지 보존?
      |
      +--> stale 처리?
      |
      +--> opening burst로 변환?
```

후속 설계에서 다음 값을 고려한다.

- event `occurred_at`
- event `detected_at`
- 다음 market open
- 최대 허용 stale duration
- 장 시작 직후 reaction scheduling

이 결정은 `market-event-analyzer` 연동 시 별도 PR로 다룬다.

---

## Phase 6 — 실제 KRX 휴장일 지원

첫 구현은 월~금만 사용한다.

그 이후 참조 데이터 또는 별도 calendar source를 이용하여 다음을 추가할 수 있다.

- 법정공휴일
- 임시공휴일
- KRX 임시휴장
- 연말 휴장
- 필요 시 조기폐장

이 단계 전에는 프로젝트 문서에 정확히 다음 한계를 표시한다.

> scheduled mode는 KST 평일 09:00~15:30을 기준으로 하며 실제 KRX 휴장일 calendar까지는 아직 반영하지 않는다.

---

## 6. 설정 계획

초기 설정은 최소화한다.

```env
SIMULATION_MARKET_MODE=scheduled
```

허용값:

| 값 | 동작 |
|---|---|
| `scheduled` | KST 평일 09:00~15:30 |
| `always_open` | 시간 제한 없음 |

초기 단계에서는 open/close 시각까지 환경변수화하지 않는다.

09:00/15:30은 프로젝트가 재현하려는 시장 규칙이므로 코드의 명시적인 domain constant로 둔다.

테스트가 특정 시각을 필요로 하면 clock injection을 사용한다.

---

## 7. 관측성

세션 자동화 도입 후 최소한 다음 상태를 관찰할 수 있어야 한다.

추천 metric 후보:

```text
market_session_open 0|1
market_session_transitions_total{transition="open"}
market_session_transitions_total{transition="close"}
orders_rejected_total{reason="market_closed"}
```

필수 구현 범위는 PR별로 결정한다.

우선순위는:

1. `orders_rejected_total{reason="market_closed"}`
2. 실제 orderbook depth reset
3. runner log의 open/close transition
4. 필요성이 확인되면 별도 session gauge/counter

로그 예시:

```text
event=market_open session_date=2026-09-22
event=market_close session_date=2026-09-22
event=runner_market_open
event=runner_market_close canceled_orders=123
```

---

## 8. 테스트 시나리오

### Unit

MarketSession:

- 평일 개장 직전
- 정확한 개장 시각
- 마감 직전
- 정확한 마감 시각
- 토요일
- 일요일
- UTC 입력
- always_open

OrderBook rollover:

- 같은 session에서는 상태 유지
- 다음 session에서는 기존 bids/asks 제거
- 이전 order id cancel이 새 session에 영향을 주지 않음

Runner:

- closed 상태에서 tick 미호출
- open transition 후 tick 시작
- close transition에서 cancel 한 번
- close 상태 장기 유지 중 중복 cancel 없음
- always_open 기존 동작 유지

### Integration

```text
08:59 order POST -> rejected
09:00 order POST -> 201
15:29 order POST -> 201
15:30 order POST -> rejected
15:30 cancel DELETE -> allowed
next day 09:00 -> empty previous-session book
```

시간을 실제 벽시계로 기다리는 테스트는 만들지 않는다. 주입 가능한 clock으로 재현한다.

---

## 9. PR 분리 계획

### PR A — MarketSession + backend enforcement

범위:

- 공통 MarketSession
- `SIMULATION_MARKET_MODE`
- backend POST order gate
- 경계 시간 테스트
- market_closed rejection metric

이 PR에서는 runner loop를 수정하지 않는다.

### PR B — matcher session rollover

범위:

- order book session ownership
- next-session reset
- order id map reset
- orderbook depth metric reset
- rollover 테스트

### PR C — participant runner session-aware loop

범위:

- OPEN/CLOSED transition
- 장중에만 tick
- 마감 시 runner-owned order cancel
- 다음 개장까지 interruptible wait
- runner config/docs/tests

### PR D — observability/documentation polish

필요할 경우:

- market session gauge
- transition counters
- Grafana annotation/panel
- runbook 업데이트

### PR E — news event session policy

`market-event-analyzer`가 실 이벤트를 공급하기 시작할 때 수행한다.

---

## 10. 비목표

이번 계획에서 바로 구현하지 않는다.

- 동시호가
- 장전/장후 시간외 거래
- VI
- 가격제한폭
- 실제 KRX holiday calendar
- 종가 단일가
- 실제 증권사 주문 수명 규칙
- 실시간 시세 feed
- 장외 뉴스의 최종 reaction 정책

이 기능들은 현재 프로젝트의 핵심 목표인 인프라 부하와 세션 운영 실험에 필요성이 확인된 경우에만 확장한다.

---

## 11. 최종 완료 기준

정규장 세션 자동화가 완료되었다고 판단하려면 다음 조건을 모두 만족해야 한다.

- 기본 모드에서 KST 평일 09:00~15:30에만 신규 주문이 체결 시스템에 들어감
- backend가 장외 주문을 독립적으로 거부함
- runner가 장외에 신규 trader tick을 만들지 않음
- runner 프로세스와 metrics endpoint는 장외에도 유지됨
- 15:30 이후 runner-owned open order가 정리됨
- 이전 거래일 in-memory order book이 다음 거래일로 넘어가지 않음
- session reset 뒤 Prometheus orderbook depth가 실제 상태와 일치함
- `always_open` 모드로 기존 실험/CI 흐름을 유지할 수 있음
- 모든 시간 경계 테스트가 wall-clock 대기 없이 결정적으로 실행됨

이 완료 기준을 만족한 뒤 실제 뉴스 이벤트의 장외 발생/다음 장 반영 정책으로 넘어간다.
