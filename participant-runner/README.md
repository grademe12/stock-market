# Participant runner

`participant-runner`는 백엔드와 별도 프로세스(또는 컨테이너)에서 실행되는 유일한 시장참여자 실행 경로다. 활성 `TraderProfile`을 백엔드 API에서 읽고, HTTP 호가 조회·주문·취소 요청으로만 거래소에 접근한다. 모든 전략이 HTTP/DRF/매칭 경로 전체에 실제 부하를 만든다.

## Strategies

runner는 매 tick마다 종목별 호가를 한 번 조회하고 아래 전략에 같은 스냅샷을 전달한다.

| Strategy | 주문 규칙 |
|---|---|
| `noise` | seed 기반으로 매수/매도, 기준가 주변 오프셋, 수량을 무작위 선택 |
| `momentum` | 직전 midpoint 대비 상승 시 best ask 매수, 하락 시 best bid 매도, 최초·보합 tick은 대기 |
| `mean_reversion` | midpoint가 기준가보다 한 호가 이상 낮으면 best ask 매수, 높으면 best bid 매도 |
| `liquidity_provider` | midpoint 한 호가 아래 bid와 한 호가 위 ask를 같은 tick에 제출 |

midpoint는 양쪽 호가가 있으면 두 최우선 호가의 평균, 한쪽만 있으면 해당 가격, 빈 호가창이면 프로필의 `reference_price`다. LP의 중심가는 `max_offset_steps × price_step` 범위 안에서 기준가 주변으로 제한한다. 모든 미체결 주문에는 프로필의 `order_ttl_ticks`가 적용된다.

## Configuration layers

- **트레이더 설정**: `GET /api/v1/traders/`의 활성 프로필. 트레이더 수, 전략, 수량·가격 범위, TTL, 개별 실행 주기를 결정한다. 프론트엔드는 백엔드의 트레이더 CRUD API로 이를 관리한다.
- **runner 환경 설정**: 컨테이너가 어느 백엔드에 어떤 범위·속도로 요청할지를 결정한다. `.env.example`을 `.env`로 복사해 개인 실행값을 저장한다. `.env`는 Git에서 제외된다.

| Variable | Default | Meaning |
|---|---:|---|
| `BACKEND_BASE_URL` | `http://127.0.0.1:8000` | Django backend base URL |
| `TICK_INTERVAL_MS` | `1000` | runner tick 간격 |
| `REQUEST_TIMEOUT_MS` | `5000` | HTTP 요청 timeout |
| `RUNNER_STATUS_LOG_INTERVAL_TICKS` | `60` | 상태 요약 로그 출력 주기 |
| `MAX_TRADERS` | unlimited | 활성 프로필 중 이 컨테이너가 실행할 최대 수 |
| `TRADER_IDS` | all enabled | 쉼표로 구분한 특정 트레이더 ID |

`MAX_TRADERS=20`은 20명을 자동 생성하지 않는다. 백엔드에서 활성 프로필을 20개 만든 뒤, 이 runner가 최대 20개를 선택하도록 제한한다.

## Local run

먼저 별도 터미널에서 백엔드를 실행하고, 활성 트레이더 프로필을 하나 이상 만듭니다.

```bash
make backend-run
cd participant-runner
PYTHONPATH=../backend python -m participant_runner --once
PYTHONPATH=../backend python -m participant_runner
```

시작 시 프로필을 한 번 읽는다. 실행 중 프로필 변경은 다음 runner 재시작부터 적용된다. 종료 신호(`Ctrl+C`, `SIGTERM`)를 받으면 추적 중인 미체결 runner 주문을 취소한다.

## Container run

프로젝트 루트에서 이미지를 빌드합니다.

```bash
docker build -f participant-runner/Dockerfile -t stock-market-participant-runner .
```

호스트에서 실행 중인 Django에 연결하는 Linux Docker 예시입니다.

```bash
docker run --rm --add-host=host.docker.internal:host-gateway \
  --env-file participant-runner/.env \
  stock-market-participant-runner
```

backend와 runner를 같은 Docker network에 둘 때는 `BACKEND_BASE_URL`에 backend 컨테이너 서비스명(예: `http://backend:8000`)을 지정한다.

Compose profile은 `participant-runner/.env`가 있으면 자동으로 읽는다. 이 파일은 Git에서 제외되며, `MAX_TRADERS=100`처럼 개인 실험 범위를 둘 수 있다. 설정이 없으면 runner의 기본값을 사용한다.

## Test

```bash
cd participant-runner
PYTHONPATH=../backend python -m unittest discover
```

첫 버전은 runner 컨테이너 하나만 실행한다. 같은 트레이더 프로필을 여러 컨테이너가 동시에 실행하면 중복 주문이 발생하므로, 복제 실행은 profile shard 규칙을 도입한 뒤 진행한다.

runner가 정상 종료되면 자신이 추적 중인 미체결 주문을 취소한다. 체결된 뒤 TTL 취소 대상이 된 주문은 backend가 `ALREADY_CLOSED`로 idempotent하게 응답하며, runner 상태 요약의 `already_closed`로 집계된다. 강제 종료나 네트워크 단절로 종료 처리가 실행되지 않은 주문은 현재 메모리 order book에 남을 수 있으므로, 부하 실험 뒤에는 주문을 재시작하거나 정리해야 한다. 서버 측 만료 처리는 주문 영속화 단계에서 별도로 도입한다.
