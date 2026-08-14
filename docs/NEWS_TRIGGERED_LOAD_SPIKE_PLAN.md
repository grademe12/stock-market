# 뉴스 발생 기반 트레이더 주문 spike 미확정 계획

> **상태**: 논의 초안. 구현 승인되지 않음.
>
> **목적**: 뉴스·공시·풍문 같은 외부 사건이 알려졌을 때 다수의 가상 트레이더가 일시적으로 주문 빈도·방향·수량을 변화시켜 backend API에 갑작스런 부하 spike를 만든다.
>
> 뉴스의 투자 가치를 정확히 판단하거나 수익성 있는 매매 알고리즘을 만드는 것은 목표가 아니다.

**관련 문서**: [거래 참여자 시뮬레이션 계획](./TRADING_PARTICIPANT_SIMULATION_PLAN.md) · [부하 기준선](./LOAD_TEST_BASELINE.md) · [전체 구현 계획](./IMPLEMENTATION_PLAN.md)

---

## 1. 핵심 판단

이 실험에서 “뉴스”는 정확한 예측 데이터가 아니라 **거래 요청을 동시에 증가시키는 외부 충격 trigger**다.

따라서 초기 구현에는 다음이 필요하지 않다.

- 기사 원문 수집·크롤링
- 고도의 감성 분석·LLM
- 뉴스와 실제 주가 상관관계 예측
- 뉴스 제공자별 실시간 연동
- 실제 증권사 계좌·주문 API

일단 고정된 사건 fixture와 시계를 사용해 같은 조건에서 같은 spike를 재현한다. 실제 뉴스는 외부 사건을 해당 fixture 형식으로 변환하는 선택적 adapter로만 나중에 붙인다.

---

## 2. 실험이 답해야 할 질문

1. baseline 대비 몇 배의 주문 요청을 어디까지 정상 처리하는가?
2. spike 진입 시 p95·p99 지연과 오류율이 어떻게 변하는가?
3. backend CPU·메모리·network와 로컬 runner 자원 중 어느 쪽이 먼저 포화되는가?
4. spike가 끝난 후 정상 지연과 오류율로 복구하는 데 얼마나 걸리는가?
5. 단방향 주문과 양방향 주문이 호가창·체결·취소 경로에 어떤 차이를 만드는가?
6. 동일한 부하 곡선에서 k6와 상태를 가진 트레이더 runner의 결과가 어떻게 다른가?

---

## 3. 제안 아키텍처

```text
NewsShockEvent fixture / scheduler
             │
             ▼
participant-runner (external only)
  ├─ 사건 적용 대상 트레이더 선택
  ├─ 개별 reaction delay 적용
  ├─ 주문 빈도·방향·수량 임시 변경
  └─ 시간 감쇠 후 baseline으로 복귀
             │ HTTP
             ▼
Django API → in-memory order book
```

모든 트레이더는 계속 `participant-runner` 외부 프로세스에서만 실행한다. Django backend에 보트 start·stop·manual-tick API를 다시 넣지 않는다.

첫 구현은 runner가 JSON scenario를 로드하고 시작 후 정해진 시점에 사건을 자체 발생시키는 방식으로 충분하다. 여러 runner를 동시에 실행할 때는 같은 절대 시각과 서로 다른 `runner_id`·seed를 사용한다.

---

## 4. NewsShockEvent 계약 초안

```json
{
  "event_id": "news-shock-001",
  "symbol": "005930",
  "starts_after_ms": 30000,
  "rise_ms": 5000,
  "peak_ms": 20000,
  "decay_ms": 30000,
  "affected_trader_ratio_bps": 7000,
  "order_rate_multiplier_bps": 50000,
  "buy_bias_bps": 8000,
  "quantity_multiplier_bps": 20000,
  "reaction_delay_min_ms": 0,
  "reaction_delay_max_ms": 3000,
  "seed": 42
}
```

모든 비율과 배수는 재현성을 위해 basis point 정수로 표현한다.

| 필드 | 의미 |
|---|---|
| `starts_after_ms` | runner 시작 후 사건 발생 시점 |
| `rise_ms` | baseline에서 peak로 증가하는 기간 |
| `peak_ms` | 최대 부하를 유지하는 기간 |
| `decay_ms` | peak에서 baseline으로 돌아오는 기간 |
| `affected_trader_ratio_bps` | 반응하는 트레이더 비율 |
| `order_rate_multiplier_bps` | 반응 중 개별 주문 빈도 배수 |
| `buy_bias_bps` | 매수 방향 확률. `5000`은 양방향 균등 |
| `quantity_multiplier_bps` | 주문 수량 배수 |
| `reaction_delay_*` | 모든 트레이더가 동일 순간에 반응하지 않게 하는 지연 범위 |
| `seed` | 반응 대상·지연·방향 재현 |

“호재”와 “악재”를 정확히 판단하는 것은 중요하지 않다. `buy_bias_bps`를 바꾸어 매수 편향, 매도 편향, 양방향 혼합 spike를 각각 비교하면 된다.

---

## 5. 부하 곡선

### 5.1 Consumer propagation

소비자가 포털·앱·SNS에서 순차적으로 뉴스를 접하는 모습을 모사한다.

```text
baseline → 5~30초 ramp-up → peak → 30~120초 decay → baseline
```

트레이더별 reaction delay를 넓게 두고 참여자 중 일부만 반응한다.

### 5.2 Thundering herd

push 알림이나 동시 전파로 많은 트레이더가 짧은 시간에 반응하는 최악 조건을 모사한다.

```text
baseline → 0~1초 급증 → 짧은 peak → 빠른 decay
```

이 시나리오는 일반적인 사용자 행동이라고 주장하기 위한 것이 아니라 순간 포화와 복구 특성을 보기 위한 스트레스 테스트다.

---

## 6. 트레이더 반응 규칙

기존 Noise·Momentum·Mean-Reversion·LP 전략을 교체하지 않는다. `NewsShockEvent` 활성 중에만 일부 트레이더의 설정을 임시 변형하는 decorator/controller로 구성한다.

- 주문 주기를 줄여 제출 빈도 증가
- 매수·매도 선택에 사건 편향 적용
- 프로필 상한 안에서 주문 수량 증가
- 개별 reaction delay 후 반응 시작
- rise·peak·decay 진행도에 따라 효과 감쇠
- 사건 종료 후 원래 전략 설정으로 복구

같은 `event_id`는 runner별로 한 번만 적용하고, 사건 중복 수신이 주문 배수를 중첩시키지 않게 한다.

---

## 7. k6와 participant-runner의 역할

두 도구는 경쟁 관계가 아니다.

| 도구 | 역할 |
|---|---|
| k6 | 목표 RPS·duration을 정확히 제어해 backend 순수 용량 확인 |
| participant-runner | 호가 조회, 주문, 체결, TTL 취소가 함께 있는 상태 기반 실제 경로 확인 |

먼저 k6로 정해진 spike 곡선의 용량 기준을 만들고, participant-runner가 같은 목표 곡선을 얼마나 재현하는지 비교한다. runner가 목표 요청량을 내지 못하면 backend 병목으로 해석하지 않고 runner CPU·network·동시성을 먼저 확인한다.

---

## 8. 관측 및 보고 항목

### 부하 입력

- baseline·목표 peak·실제 달성 RPS
- 동시 runner·트레이더 수
- 사건 반응 비율·주문 빈도 배수·방향 편향
- rise·peak·decay 기간과 seed

### API·인프라

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

## 9. 단계별 구현 계획

### B0 — 결정론적 burst planner

- `NewsShockEvent` dataclass와 설정 검증
- 반응 트레이더 선택·지연·부하 배수 계산
- rise·peak·decay 단계별 정수 계산
- 같은 seed·tick에서 같은 계획 테스트

**Exit gate**: HTTP 없이 정해진 tick별 제출 예정 수·방향·수량을 재현한다.

### B1 — external runner 연동

- scenario JSON·환경변수·CLI 로딩 경로
- 기존 전략에 burst controller 적용
- 사건 시작·peak·종료 구조화 로그
- 정상 종료 시 기존 TTL 주문 정리 유지

**Exit gate**: baseline에서 spike로 증가했다가 설정 시간 후 baseline으로 복구한다.

### B2 — 비교 실험과 계측

- consumer propagation·thundering herd 시나리오
- k6와 runner의 동일 목표 곡선 비교
- backend·runner 자원과 API 지연·오류율 기록
- 결과와 해석 한계를 `.artifacts` 또는 실험 문서로 보존

**Exit gate**: 다른 환경에서 같은 seed·시나리오로 실험을 재현하고 병목을 구분한다.

### B3 — 선택적 실제 뉴스 adapter

- DART RSS·허가된 뉴스 API의 새 항목을 `NewsShockEvent`로 변환
- 최소한의 종목 연결·방향 편향만 적용
- provider 지연·중복·장애는 trigger 품질 지표로 별도 기록

**Exit gate**: 실제 뉴스 adapter를 끄거나 장애가 나도 fixture 기반 부하 실험은 영향받지 않는다.

---

## 10. 위험과 방어 조치

| 위험 | 방어 조치 |
|---|---|
| 로컬 PC 포화를 backend 병목으로 오판 | runner 자원·실제 제출 RPS를 함께 측정 |
| 모든 트레이더의 완전 동시 반응 | 재현 가능한 reaction delay 분포 적용 |
| 단방향 주문만 쌓여 체결 경로 미사용 | 매수·매도·혼합 편향 시나리오를 따로 실행 |
| 트레이더 로직이 부하량을 정확히 만들지 못함 | 동일 곡선을 k6로 먼저 실행해 기준 설정 |
| 시계 차이로 여러 runner spike 엇갈림 | KST/UTC 절대 시각과 monotonic 경과 시간을 구분 |
| 실제 뉴스 API 작업이 주요 목표를 잠식 | B0~B2 완료 전 B3 시작 금지 |

---

## 11. 미확정 의사결정

1. 첫 목표 baseline·peak RPS와 유지 시간
2. 단일 runner 프로세스로 시작할지, 로컬에서 여러 프로세스를 동시 실행할지
3. 주문 빈도 증가만 볼지, 수량·방향 편향도 포함할지
4. consumer propagation과 thundering herd 중 첫 기본 시나리오
5. 실험 실패 기준과 종료 조건
6. B2 이후 실제 뉴스 adapter가 포트폴리오에 추가 가치를 주는지

현재 권장 순서는 **B0 결정론적 burst planner → B1 external runner 연동 → B2 k6 비교 실험**이다. 실제 뉴스 연동은 이 목표에 필수가 아니므로 나중 선택 항목으로 둔다.

---

*Last updated: 2026-08-14 — 뉴스 분석이 아닌 주문 spike 재현을 핵심 목표로 수정*
