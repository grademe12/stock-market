# k6 기준 부하 측정

이 문서는 현재 단일 Django backend의 주문 API 기준 성능을 기록한다. 수치는 이후 rate limit, 관측성, 비동기 처리 도입 전후를 비교하는 출발점이다.

## 측정 대상과 조건

- 대상 API: `POST /api/v1/orders/`
- 종목: 개발용 `005930`
- 주문: 70,000원, 1주, 매 요청마다 매수·매도를 교차 생성
- 도구: `grafana/k6:latest` 컨테이너
- 실행 방식: k6 `constant-arrival-rate`, 목표 주문률 10·50·100 orders/s
- 각 실행 시간: 30초
- backend: Gunicorn worker 1개·thread 4개, CPU 1개·메모리 4GiB 제한
- 참여자 runner: 실행하지 않음
- 체결 로그: 비활성화 (`TRADE_EXECUTION_LOG_ENABLED=0`)

`orders/s`는 HTTP `POST /api/v1/orders/` 요청 수다. k6의 반복 수가 아닌 실제 주문 API 호출 수로 해석한다.

## 실행

```bash
make load-backend-up
make load-steady ORDER_RATE=10 TEST_DURATION=30s
make load-steady ORDER_RATE=50 TEST_DURATION=30s
make load-steady ORDER_RATE=100 TEST_DURATION=30s
```

테스트가 실행 중일 때 별도 터미널에서 backend 자원 표본을 한 번 확인한다.

```bash
make load-backend-stats
```

`load-steady`는 일회성 k6 컨테이너를 Compose 네트워크에서 실행한다. k6의 JSON summary는 `.artifacts/loadtest/`에 남으며 Git에는 포함하지 않는다.

## 결과

| 목표 주문률 | 실제 주문 수 | 평균 지연 | p95 | p99 | 실패율 | dropped iterations | backend CPU 표본 | backend 메모리 표본 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 orders/s | 300 | 1.99 ms | 2.31 ms | 2.60 ms | 0% | 0 | 0.02% | 58.43 MiB |
| 50 orders/s | 1,500 | 1.58 ms | 2.09 ms | 2.41 ms | 0% | 0 | 7.02% | 59.25 MiB |
| 100 orders/s | 3,000 | 1.45 ms | 1.80 ms | 2.07 ms | 0% | 0 | 39.34% | 59.11 MiB |

측정일은 2026-07-26이다. 각 실행은 30초 동안 정확히 목표 주문 수(목표 주문률 × 30초)를 제출했다. 실행별 지연시간 차이는 컨테이너·WSL 환경의 단발 측정값이므로, 현재 결과만으로 주문률이 높을수록 지연시간이 낮다고 해석하지 않는다.

현재 범위에서는 100 orders/s까지 HTTP 오류, 주문 거절, k6 iteration drop이 없었고 p99도 2.07ms 이하였다. 따라서 이 결과는 **현재 단일 종목·메모리 호가창 조건의 기준선**이며, 병목이 확인됐다는 근거는 아니다.

## 해석 기준

- `dropped iterations`가 0이면 k6가 목표 주문률을 모두 생성했다는 뜻이다. 0보다 크면 backend 성능뿐 아니라 k6에 할당한 VU 수가 충분했는지도 함께 확인한다.
- `http_req_failed`와 `order accepted` check는 주문 API의 HTTP 실패를 나타낸다. 현재 시나리오는 HTTP 201만 정상으로 본다.
- backend CPU·메모리는 테스트 중 단발 Docker 표본이다. 지속적인 시계열이나 최대값이 아니므로, 이후 Prometheus 도입 전까지의 보조 참고값으로만 사용한다.
- 이 결과는 단일 종목·메모리 호가창·잔고 검증 없음이라는 현재 구현 범위 안에서만 비교한다.
