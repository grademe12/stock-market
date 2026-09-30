# 재현 가능한 거래 참여자 데모

이 runbook은 단일 backend와 외부 participant-runner로 주문·체결·TTL 취소 흐름을 재현한다. 성능 수치는 아직 k6 Stage 2의 대상이며, 여기서는 동일한 실험 입력을 만드는 데 집중한다.

## 실행

로컬 Compose 매처와 게이트웨이를 띄우던 `make demo-up`, `make container-backend-up`, `make demo-runner-up`은 제거했다. 운영 진입점은 GCE 게이트웨이 `:8000`이고, 시장참여자는 `participant-runner/compose.yaml`로 실행한다.

`make demo-seed`는 이미 떠 있는 로컬 backend 컨테이너에만 프로필을 넣는다. `TRADER_STRATEGY`(기본값 `noise`)로 선택한 전략의 프로필만 생성 또는 갱신하며, 같은 count·seed는 같은 설정을 만든다.

`event_reactive` 프로필은 휴면 풀이다. 시나리오 fixture가 없으면 주문을 내지 않는다. 라이브 이벤트는 analyzer가 GCE `POST /api/v1/events/`로 넣고, 이벤트 러너가 pending을 읽어 반응한다.

개인 runner 범위는 Git 제외 파일 `participant-runner/.env`에서 조정한다.

```env
MAX_TRADERS=100
TICK_INTERVAL_MS=1000
RUNNER_STATUS_LOG_INTERVAL_TICKS=60
```

## 종료와 초기화

운영 러너는 `participant-runner/compose.yaml` 프로젝트에서 내린다. `make demo-down`은 루트 Compose 프로젝트 전체를 내리므로 PostgreSQL 컨테이너도 함께 멈춘다. `postgres-data` volume은 유지된다.

## Kubernetes로 확장할 때의 계약

현재 구성은 Kubernetes에 배포할 수 있는 컨테이너 경계를 만들지만, 수평 확장 가능한 거래소는 아니다.

- backend는 메모리 호가창을 쓰므로 **같은 종목의 active matcher는 1개**만 허용한다. 공개 URL은 gateway `:8000` 하나다. 종목 샤드마다 프로세스 1개이며, GCE 배포는 기본적으로 CPU 1개당 샤드 1개다.
- participant-runner도 같은 트레이더의 중복 실행을 막기 위해 replica 1개만 허용한다.
- runner 설정은 환경 변수만 읽는다. 로컬 `.env`는 Kubernetes의 ConfigMap/Secret 주입으로 대체할 수 있다.
- `seed_traders`는 Django management command이므로 이후 Kubernetes Job 또는 migration Job에서 실행할 수 있다.
- runner는 `SIGTERM`에서 주문 정리를 시도한다. 이후 Deployment에는 이 정리가 끝날 수 있는 `terminationGracePeriodSeconds`를 설정한다.
- 다중 runner는 profile ID 기반 deterministic sharding(`SHARD_INDEX`, `SHARD_COUNT`)을 도입한 후에만 허용한다.
- backend 수평 확장은 주문·체결 상태를 외부화하거나 종목별 matcher partitioning을 구현한 Stage 4~5 이후에 검토한다.
