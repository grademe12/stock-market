# 뉴스 트리거 기반 휴면 트레이더 주문 spike 구현 계획

> **상태**: B0 planner와 B1 `EventReactiveTrader`·프로필까지 구현 완료. B2 이후의 runner fixture 연동은 미구현. 수치와 외부 뉴스 제공자는 미확정.
>
> **목적**: 뉴스·공시·풍문 같은 외부 사건을 접한 휴면 상태의 가상 트레이더들이 무작위·시간차를 두고 시장에 진입하게 해 backend API에 갑작스런 주문 spike를 만든다.
>
> 뉴스의 투자 가치를 정확히 판단하거나 수익성 있는 매매 알고리즘을 만드는 것은 목표가 아니다.

**관련 문서**: [거래 참여자 시뮬레이션 계획](./TRADING_PARTICIPANT_SIMULATION_PLAN.md) · [부하 기준선](./LOAD_TEST_BASELINE.md) · [전체 구현 계획](./IMPLEMENTATION_PLAN.md)

---

## 1. 목표와 비목표

### 목표

- 평소에는 주문하지 않는 `EventReactiveTrader` 풀을 둔다.
- 사건이 발생하면 휴면 트레이더 중 일부만 seed 기반으로 선택한다.
- 선택된 트레이더는 개별 반응 지연 후 일정 횟수의 주문을 낸다.
- 주문 횟수·간격·방향·수량·TTL의 집합 결과로 spike가 생기게 한다.
- 같은 이벤트·프로필·seed에서 같은 반응 계획을 재현한다.
- runner와 backend의 자원·처리량·지연·오류율을 함께 측정한다.

### 비목표

- 기사 원문 크롤러 구축
- 정교한 감성 분석·LLM·주가 예측
- 뉴스 반응을 이용한 실제 수익률 검증
- 실제 증권사 계좌·주문 API 연동
- 뉴스 피드의 밀리초 단위 저지연 처리
- 측정 근거 없이 queue·다중 replica·Kubernetes 도입

---

## 2. 핵심 개념

이 실험에서 뉴스는 가격 예측 데이터가 아니라 **잠재 참여자를 시장으로 유입시키는 trigger**다.

```text
평상시
├─ NoiseTrader
├─ MomentumTrader
├─ MeanReversionTrader
├─ LiquidityProvider
└─ EventReactiveTrader N명: 휴면, 주문 없음

뉴스 발생
└─ EventReactiveTrader 중 무작위 일부 활성화
    ├─ 다른 반응 시각
    ├─ 다른 주문 횟수·간격·수량
    ├─ 다른 매수·매도 선호
    └─ 반응 종료 후 다시 휴면
```

현재 가격 midpoint를 추종하는 `MomentumTrader`와 뉴스로 깨어나는 `EventReactiveTrader`는 서로 다른 전략으로 구분한다.

spike 강도는 사용자가 매번 숫자로 지정하지 않는다. 기본 실행은 이벤트 preset의 분포에서 seed로 결정한다. 목표 RPS가 필요한 capacity test에서만 명시적 override를 허용한다.

---

## 3. 전체 아키텍처

```text
                    ┌─ SyntheticEventSource
                    │  scenario JSON / replay clock
이벤트 입력 ──────────┤
                    │  ExternalNewsEventSource (후속)
                    └─ DART RSS / 허가된 뉴스 API
                              │
                              ▼
                       NewsShockEvent
                    정규화·중복 제거·cooldown
                              │
                              ▼
                 participant-runner (external only)
                    ├─ 기존 baseline traders
                    ├─ EventCoordinator
                    ├─ EventReactiveTrader pool
                    └─ reaction plan / metrics
                              │ HTTP
                              ▼
                 Django 호가·주문·취소 API
                              │
                              ▼
                    in-memory order book
```

모든 트레이더는 `participant-runner` 외부 프로세스에서만 실행한다. Django backend에 봇 start·stop·manual-tick API를 다시 넣지 않는다.

### 초기 실행 경로

runner가 `--scenario` CLI 인자로 JSON fixture를 로드하고, runner 시작 후 상대 시각에 이벤트를 발생시킨다. 초기에는 이벤트용 서버·queue·별도 네트워크를 추가하지 않는다.

시계는 다음을 구분한다.

- 로그·보고용: timezone이 있는 절대 시각
- reaction delay·주문 간격 계산용: monotonic 경과 시간
- 단위 테스트용: 주입 가능한 fake clock

---

## 4. 도메인 모델 초안

### 4.1 NewsShockEvent

```json
{
  "event_id": "news-20260814-001",
  "symbol": "005930",
  "starts_after_ms": 30000,
  "preset": "breaking_news",
  "direction_hint": "MIXED",
  "label": "005930 related breaking news",
  "source": "fixture",
  "seed": 42
}
```

| 필드 | 의미 |
|---|---|
| `event_id` | runner별 중복 적용을 막는 식별자 |
| `symbol` | 반응 주문을 보낼 종목 |
| `starts_after_ms` | fixture 실행 시 runner 시작 후 발생 시점 |
| `preset` | 반응 분포의 종류 |
| `direction_hint` | `BUY`, `SELL`, `MIXED`, `NONE`. 정확한 뉴스 판단이 아님 |
| `label` | 실험 로그용 설명. 거래 판단에 사용하지 않음 |
| `source` | `fixture`, `replay`, `dart`, `news_api` 등 trigger 출처 |
| `seed` | 반응 대상·지연·주문 계획 재현 |

실제 뉴스는 `starts_after_ms` 대신 `occurred_at`과 `detected_at`을 기록한다. replay에서는 `detected_at`보다 빠르게 트레이더를 활성화하지 않는다.

### 4.2 EventReactiveTrader

`TraderProfile.strategy` 선택값에 `event_reactive`를 추가한다. 기존 필드는 다음처럼 재사용한다.

| 기존 프로필 필드 | 이벤트 반응 용도 |
|---|---|
| `reference_price`, `price_step` | 호가가 빈 경우 주문 가격 생성 |
| `quantity_min`, `quantity_max` | 반응 주문 수량 범위 |
| `order_ttl_ticks` | 미체결 반응 주문 취소 시점 |
| `interval_ticks` | 활성 중 주문 간 최소 간격 |
| `seed` | 개별 반응 패턴 재현 |

프로필은 `enabled=true`여도 이벤트가 없으면 주문하지 않는다. `seed_traders --strategy event_reactive --count N`으로 휴면 풀을 결정론적으로 만들 수 있게 한다.

### 4.3 ResolvedReactionPlan

이벤트가 발생하면 `EventCoordinator`가 휴면 트레이더별 계획을 한 번 계산해 고정한다.

```text
ResolvedReactionPlan
  event_id
  trader_user_id
  activated             boolean
  reaction_at           monotonic offset
  order_count           integer
  order_interval_ticks  integer
  buy_probability_bps   integer
  sides                 BUY/SELL[]
  quantity sequence     integer[]
  ttl sequence          integer[]
  order_tick_offsets    integer[]
```

계획을 미리 고정하면 runner 처리 지연이 있어도 예정 부하와 실제 부하를 비교할 수 있다. 늦은 주문을 무한정 따라잡아 더 큰 연쇄 spike를 만들지 않도록 시나리오별 최대 scheduler lag를 넘긴 예정 주문은 `dropped` 처리한다.

---

## 5. 이벤트 preset

사용자는 기본 실행에서 preset과 seed만 선택한다. 아래 범위는 B0에서 구현한 preset v1 기본값이며, B3 측정 결과로 조정할 때는 preset 버전을 올린다.

| preset | 활성 비율 | 반응 지연 | 1인당 주문 | 기본 방향 |
|---|---:|---:|---:|---|
| `minor_news` | 10~30% | 10~60초 | 1~2회 | 혼합 |
| `breaking_news` | 40~80% | 0~20초 | 1~4회 | 혼합 또는 hint |
| `market_panic` | 70~100% | 0~3초 | 2~6회 | 한 방향 편향 |
| `mixed_reaction` | 40~80% | 0~20초 | 1~4회 | 매수·매도 균등 |
| `rumor` | 15~50% | 10~120초 | 1~3회 | 혼합, 빠른 소멸 |

실행 시 preset에서 해결된 다음 값을 구조화 로그와 실험 결과에 남긴다.

- 휴면 풀 크기와 활성화 인원
- 개별 반응 시각
- 예정 주문 수와 시간 버킷별 예정 RPS
- 매수·매도 예정 비율
- 수량·TTL 분포
- 사용한 preset 버전과 seed

### Capacity override

정확한 backend 용량 비교가 필요한 실험에서만 `target_peak_order_rps`·`peak_duration_ms`를 설정한다. 이 모드는 트레이더 자연 반응 시뮬레이션과 결과를 분리해 보고한다.

---

## 6. 이벤트 처리 순서

1. `SyntheticEventSource`가 fake/monotonic clock 기준으로 이벤트를 발행한다.
2. `EventCoordinator`가 이미 처리한 `event_id`인지 확인한다.
3. 이벤트 종목과 같은 `EventReactiveTrader` 풀을 선택한다.
4. preset·event seed·trader seed로 트레이더별 `ResolvedReactionPlan`을 생성한다.
5. runner는 기존 트레이더와 함께 현재 tick에 due된 반응 계획을 확인한다.
6. 종목별 호가 스냅샷을 tick당 한 번만 조회해 모든 due 트레이더에 공유한다.
7. 각 트레이더는 계획된 방향·수량으로 `OrderIntent`를 만든다.
8. BUY는 best ask, SELL은 best bid를 우선 사용한다. 반대편 호가가 없으면 프로필 기준가와 `price_step`으로 지정가를 만든다.
9. runner는 주문 응답의 잔량을 추적하고 기존 TTL 취소 경로를 그대로 사용한다.
10. 모든 반응 주문을 소진하면 트레이더는 다시 휴면 상태가 된다.

평상시 baseline 트레이더는 이벤트와 관계없이 계속 실행한다. 이벤트 풀이 비었거나 트리거 처리가 실패해도 baseline 주문 루프를 중단하지 않는다.

---

## 7. 가상 뉴스와 실제 뉴스

### 7.1 기본: 가상 뉴스 fixture

```json
{
  "events": [
    {
      "event_id": "shock-001",
      "symbol": "005930",
      "starts_after_ms": 30000,
      "preset": "breaking_news",
      "direction_hint": "MIXED",
      "seed": 42
    }
  ]
}
```

실제 기사 제목이나 본문이 없어도 시장 진입 spike를 검증할 수 있다. 같은 fixture·프로필·seed로 실험을 반복한다.

### 7.2 선택: 실제 뉴스 adapter

실제 뉴스는 다음 최소 처리만 수행한다.

1. DART RSS 또는 허가된 뉴스 API에서 새 항목 확인
2. provider ID·URL·제목 hash로 중복 제거
3. 명시적인 회사명·종목코드로 관심 종목 연결
4. 종목별 cooldown 동안 유사 기사를 하나의 이벤트로 병합
5. 방향 판단을 할 수 없으면 `MIXED`로 `NewsShockEvent` 발행

실제 뉴스 adapter는 트레이더 로직을 변경하지 않고 fixture와 같은 이벤트 계약을 사용한다. 뉴스 API·LLM·외부 네트워크 지연을 runner tick 경로에 넣지 않는다.

초기에는 별도 마이크로서비스를 만들지 않는다. 필요하면 독립 collector 프로세스가 PostgreSQL의 이벤트 테이블에 저장하고 runner가 cursor API로 조회하는 최소 구성부터 검토한다.

---

## 8. k6와 participant-runner의 역할

| 도구 | 역할 |
|---|---|
| k6 | 목표 RPS·duration을 정확히 제어해 backend 순수 용량 확인 |
| participant-runner | 휴면 참여자의 활성화, 호가 조회, 주문, 체결, TTL 취소가 함께 있는 상태 기반 경로 확인 |

k6로 backend의 용량 기준을 먼저 만든다. runner 실험에서는 휴면 트레이더의 무작위 반응으로 만들어진 실제 부하 곡선을 측정한다. 두 결과를 비교하되 같은 RPS가 자연스럽게 발생했다고 가정하지 않는다.

runner가 예정한 주문을 보내지 못했을 때는 backend 병목으로 판단하지 않고 runner CPU·network·scheduler lag·동시성을 먼저 확인한다.

---

## 9. 관측 및 보고 항목

### 이벤트·runner

- `events_received_total`, `events_deduplicated_total`
- `dormant_traders_total`, `activated_traders_total`
- `reactions_planned_total`, `reactions_submitted_total`, `reactions_dropped_total`
- 시간 버킷별 예정·실제 order RPS
- `scheduler_lag_ms`의 max·p95
- 호가 조회·주문·취소별 요청 수와 실패율
- preset 버전, event seed, runner ID

### backend·인프라

- 처리량과 p50·p95·p99 지연
- 4xx·5xx·timeout·연결 오류율
- backend·runner CPU, 메모리, network 표본
- spike 종료 후 baseline 복구 시간

### 시장 현상

- 주문·체결·TTL 취소량
- 미체결 주문과 호가 단계 수
- spread·midpoint·매수/매도 잔량 불균형

보고서에는 조건, 처리량, 지연, 오류율, 자원 표본과 함께 로컬 PC가 병목일 수 있는 해석 한계를 반드시 남긴다.

---

## 10. 단계별 구현 계획

### B0 — 도메인 계약과 결정론적 planner (완료)

- `NewsShockEvent`, preset, `ResolvedReactionPlan` 타입과 검증
- 주입 가능한 clock과 seed 기반 난수
- 반응 대상·지연·주문 횟수·방향·수량·TTL 계획
- 중복 `event_id`의 idempotency
- 같은 입력에서 같은 계획이 나오는 단위 테스트

**Exit gate 달성**: HTTP 없이 휴면 풀의 활성 대상과 tick별 주문 예정 수를 재현하고, 입력 순서가 달라도 같은 계획을 생성하는 테스트를 통과한다.

### B1 — EventReactiveTrader와 프로필 (완료)

- `TraderProfile.Strategy.EVENT_REACTIVE` 선택값과 migration
- 평상시 주문하지 않는 `EventReactiveTrader`
- 활성 계획을 `OrderIntent`로 변환하는 로직
- `seed_traders --strategy event_reactive`와 휴면 풀 생성 문서
- 빈 호가창·한쪽 호가·가격 하한 테스트

**Exit gate 달성**: 이벤트 전에는 주문이 없고, 이벤트 활성 계획에서만 정해진 주문을 만든다. runner가 fixture를 주기 전에는 seed된 프로필도 주문을 내지 않는다.

### B2 — external runner fixture 연동

- `--scenario` 로더와 JSON schema 검증
- `EventCoordinator`를 기존 runner tick·호가 스냅샷·TTL 취소 경로와 결합
- 기존 baseline 트레이더와 동시 실행
- 이벤트 수신·활성·첫 반응·종료 구조화 로그
- 예정·제출·유실 반응과 scheduler lag 카운터
- runner 정상 종료 시 미체결 주문 정리 유지

**Exit gate**: baseline 구간 → 휴면 트레이더 spike → baseline 구간을 하나의 fixture로 재현한다.

### B3 — 비교 실험과 계측

- `breaking_news`, `market_panic`, `mixed_reaction` 기본 fixture
- 휴면 풀 크기·preset·seed별 실제 spike 곡선 비교
- k6 capacity 기준선과 runner의 상태 기반 부하 비교
- backend·runner 자원과 API 지연·오류율 기록
- 조건·처리량·지연·오류율·자원 표본·해석 한계 보고

**Exit gate**: 다른 환경에서 같은 프로필·fixture·seed로 spike를 재현하고 runner와 backend 병목을 구분한다.

### B4 — 선택적 실제 뉴스 adapter

- provider 약관·저장 범위·호출 한도 확정
- provider item ID·URL·hash 중복 제거와 종목별 cooldown
- 명시적인 종목 연결만 허용하는 최소 mapper
- `occurred_at`·`detected_at`·provider delay 기록
- 실제 항목을 공통 `NewsShockEvent` 계약으로 변환
- adapter 장애가 runner baseline·fixture 실험을 중단하지 않는 테스트

**Exit gate**: 실제 뉴스 항목 하나가 중복 없이 이벤트 하나로 변환되고, 휴면 트레이더가 fixture와 같은 경로로 반응한다.

---

## 11. 테스트 전략

### 단위 테스트

- event·preset validation
- 같은 seed의 동일 활성 대상·지연·주문 sequence
- 다른 seed의 다른 반응 패턴
- 중복 `event_id` 무시
- 이벤트 전·종료 후 휴면 상태
- direction hint과 `MIXED`의 방향 분포
- max scheduler lag를 넘긴 주문의 dropped 처리

### Runner 통합 테스트

- 같은 종목의 baseline·event trader가 tick당 호가 스냅샷 하나를 공유
- 이벤트 반응 주문이 HTTP client port로 제출됨
- 잔량이 있는 주문의 TTL 취소
- 호가 조회·주문 실패가 카운터에 반영되고 다른 트레이더 루프를 중단하지 않음
- runner 종료 시 추적 중인 미체결 주문 정리

### 부하 테스트

- 이벤트 전·중·후 구간을 분리한 시계열 결과
- 예정 order RPS와 실제 제출·backend 처리 RPS 비교
- 동일 환경의 k6 기준선과 runner 결과 비교
- backend·runner 자원 표본과 복구 시간 포함

---

## 12. 위험과 방어 조치

| 위험 | 방어 조치 |
|---|---|
| 로컬 PC 포화를 backend 병목으로 오판 | runner 자원·scheduler lag·예정/실제 RPS를 함께 측정 |
| 동기 HTTP runner가 예정 spike를 내지 못함 | B3 측정 후에만 worker·async·다중 runner 검토 |
| 느린 주문을 따라잡으며 연쇄 spike 발생 | scheduler lag 상한과 dropped 정책 |
| 단방향 주문만 쌓여 체결 경로 미사용 | BUY·SELL·MIXED 이벤트를 분리 실행 |
| 동일 기사 재전송으로 spike 중첩 | provider ID·URL·hash·종목 cooldown |
| 모호한 회사명이 잘못된 종목을 활성화 | 정확 종목코드·정식 회사명만 허용, 불확실하면 무시 |
| 실제 뉴스 연동이 핵심 목표를 잠식 | B0~B3 완료 전 B4 시작 금지 |

---

## 13. 완료 기준

- 휴면 트레이더는 이벤트 전·후에 주문하지 않는다.
- 같은 fixture·프로필·seed의 활성 명단과 주문 계획이 동일하다.
- 이벤트 중 실제 주문 RPS가 baseline보다 증가하고 종료 후 baseline으로 복구한다.
- 예정·제출·유실·처리 주문 수를 서로 구분해 보고한다.
- backend와 runner의 자원 표본을 함께 기록해 병목 위치를 구분한다.
- k6 기준선과 휴면 트레이더 spike 결과를 동일 보고서에서 비교한다.
- 실험 조건, 처리량, 지연, 오류율, 자원 표본과 해석 한계를 함께 남긴다.

---

## 14. 미확정 의사결정

1. 첫 휴면 풀 크기와 baseline 트레이더 수
2. preset별 활성 비율·반응 지연·1인당 주문 범위
3. 첫 기본 preset을 `breaking_news`로 할지 `mixed_reaction`으로 할지
4. runner가 예정 주문을 유실 처리할 scheduler lag 상한
5. 단일 runner 프로세스의 목표 상한과 다중 runner 도입 판단 기준
6. B3 이후 실제 뉴스 adapter가 포트폴리오에 추가 가치를 주는지

현재 권장 순서는 **B0 계약·planner → B1 휴면 트레이더 → B2 external runner fixture → B3 계측 실험**이다. 실제 뉴스 연동은 핵심 목표에 필수가 아니므로 B4 선택 항목으로 둔다.

---

*Last updated: 2026-08-18 — B1 EventReactiveTrader·event_reactive 프로필 구현 반영*
