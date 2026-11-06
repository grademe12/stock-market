# Stock Market

가상 트레이더 수천 명이 주문을 넣는 모의 주식 거래소입니다. 매칭 엔진을 클라우드 VM에 올려 두고, 부하를 키우면서 어디가 먼저 막히는지 재고, 그 결과에 따라 구조를 바꿔 온 기록입니다.

실제 증권사 주문이나 실제 자산은 다루지 않습니다. KRX 데이터는 종목 목록과 기준 가격을 가져오는 데만 씁니다.

| 단계 | 바꾼 것 | 결과 |
|---|---|---|
| Day 1 | 주문마다 원격 DB를 읽던 부분을 기동 시 캐시로 | 주문 평균 38ms → 1.8ms |
| Day 5 | 종목 라우터 하나 + 매칭 프로세스 4개 | 3일 연속 초당 약 146건, p50 2.7ms, 5xx 0 |
| Day 7 | 호가창 자료구조 재작성 | 잔량 약 510만 주에서 초당 주문 30 → 555건, p50 364ms → 2.7ms |

날짜별 측정 조건과 해석의 한계는 [`report/`](report/)에, 전체 과정은 [프로젝트 소개](https://woosupar.dev/projects/stock-market/)에 정리했습니다.

## 구조

```text
 participant-runner ──HTTP──▶ gateway :8000 ──▶ matcher 0  (127.0.0.1:8001)
 (가상 트레이더)               종목 → 샤드      ──▶ matcher 1  (127.0.0.1:8002)
                                                ──▶ ...
                                                       │
                                     PostgreSQL ◀──────┘  트레이더 설정, KRX 종목
 Prometheus / Grafana ◀── /metrics
```

| 구성 요소 | 하는 일 |
|---|---|
| `backend/` | Django REST API와 매칭 엔진. 호가창은 프로세스 메모리에 있고, 종목을 나눠 맡은 프로세스(샤드)마다 하나씩 돈다 |
| `gateway/` | 외부에 열린 유일한 입구. 주문의 종목을 보고 담당 샤드로 넘긴다 |
| `participant-runner/` | 거래소 밖에서 HTTP로만 주문하는 가상 트레이더. noise, momentum, mean reversion, 유동성 공급 전략이 있다 |
| `observability/` | Prometheus와 Grafana 설정, 대시보드 |
| `infra-azure/` | 백엔드 VM을 만드는 Terraform. 배포는 GitHub Actions가 이미지를 빌드해 VM에 올린다 |

설계에서 가장 큰 제약은 **한 종목의 호가창은 한 프로세스에만 있어야 한다**는 점입니다. 같은 종목을 두 프로세스가 나눠 가지면 매수와 매도가 서로 만나지 못합니다. 그래서 코어를 더 쓰려면 프로세스 안의 스레드를 늘리는 대신 종목 단위로 프로세스를 나누고, 그 앞에 라우터를 둡니다.

## 써 보려면

### 로컬에서 한 프로세스로 실행

Python 3.12와 make가 필요합니다. 데이터베이스는 SQLite를 씁니다.

```bash
make backend-setup
make backend-migrate
SIMULATION_MARKET_MODE=always_open make backend-run   # http://127.0.0.1:8000
```

다른 터미널에서 트레이더를 만들고 주문을 한 번 넣어 봅니다.

```bash
cd backend && .venv/bin/python manage.py seed_traders --strategy noise --count 20 --seed 1
cd ../participant-runner
BACKEND_BASE_URL=http://127.0.0.1:8000 SIMULATION_MARKET_MODE=always_open \
  PYTHONPATH=../backend python3 -m participant_runner --once
```

`--once`를 빼면 계속 돕니다. 호가와 체결은 `GET /api/v1/books/005930/`, `GET /api/v1/trades/?symbol=005930`으로 볼 수 있습니다.

### 알아 둘 것

- **장 시간:** 기본값은 정규장(평일 09:00~15:30 KST)에만 주문을 받습니다. 장외에 실행하면 주문이 `409 market is closed`로 거절됩니다. 위 예시처럼 백엔드와 러너 둘 다 `SIMULATION_MARKET_MODE=always_open`을 주면 시간과 상관없이 돕니다.
- **종목:** KRX 데이터를 넣지 않으면 개발용 `005930` 한 종목만 거래됩니다. 상위 종목을 쓰려면 PostgreSQL과 KRX API 키가 필요합니다([`db/README.md`](db/README.md)).
- **데이터는 메모리에만 있습니다:** 주문, 체결, 잔고는 저장하지 않습니다. 프로세스를 다시 시작하면 호가창이 비어 있습니다. 트레이더 설정과 종목 정보만 DB에 남습니다.
- **워커 수를 늘리지 마세요:** 한 매칭 프로세스는 Gunicorn 워커 1개로 돌아야 합니다. 워커를 늘리면 같은 종목의 호가창이 둘로 갈라집니다.

### 주요 API

| 요청 | 설명 |
|---|---|
| `POST /api/v1/orders/` | 지정가 주문 (`user_id`, `symbol`, `side`, `price`, `qty`) |
| `DELETE /api/v1/orders/{id}/?symbol=` | 미체결 주문 취소 |
| `GET /api/v1/books/{symbol}/` | 가격별 호가 잔량 |
| `GET /api/v1/trades/?symbol=&limit=50` | 최근 체결 |
| `GET /api/v1/ready/` | DB 연결을 포함한 준비 상태, 샤드 번호 |

전체 목록과 설정은 [`backend/README.md`](backend/README.md), 러너 설정은 [`participant-runner/README.md`](participant-runner/README.md)에 있습니다.

## 테스트

```bash
make backend-setup
make backend-test participant-runner-test gateway-test
```
