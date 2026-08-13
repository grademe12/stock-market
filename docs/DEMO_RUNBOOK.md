# 재현 가능한 거래 참여자 데모

이 runbook은 단일 backend와 외부 participant-runner로 주문·체결·TTL 취소 흐름을 재현한다. 성능 수치는 아직 k6 Stage 2의 대상이며, 여기서는 동일한 실험 입력을 만드는 데 집중한다.

## 실행

```bash
make demo-up
make demo-seed TRADER_COUNT=100 TRADER_SEED=42
make demo-runner-up
make demo-logs
```

- `demo-up`: backend를 Gunicorn worker 1개로 시작한다.
- `demo-seed`: `TRADER_STRATEGY`(기본값 `noise`)로 선택한 전략의 프로필만 생성 또는 갱신한다. 같은 count·seed는 같은 설정을 만든다.
- `demo-runner-up`: backend와 별도 컨테이너에서 HTTP 주문·취소를 전송한다.
- `demo-logs`: `event=trade_executed`와 `event=runner_status`를 함께 관찰한다.

기본 `demo-seed`는 Noise 프로필을 만든다. 다른 전략은 같은 명령에 전략을 지정해 추가한다.

```bash
make demo-seed TRADER_STRATEGY=momentum TRADER_COUNT=20 TRADER_SEED=42
make demo-seed TRADER_STRATEGY=mean_reversion TRADER_COUNT=20 TRADER_SEED=42
make demo-seed TRADER_STRATEGY=liquidity_provider TRADER_COUNT=5 TRADER_SEED=42
```

개인 runner 범위는 Git 제외 파일 `participant-runner/.env`에서 조정한다.

```env
MAX_TRADERS=100
TICK_INTERVAL_MS=1000
RUNNER_STATUS_LOG_INTERVAL_TICKS=60
```

## 종료와 초기화

```bash
make demo-down
```

이는 컨테이너와 네트워크만 제거하고 `postgres-data` volume은 유지한다. backend를 재시작하면 메모리 호가창은 비워지지만 트레이더 프로필과 KRX 참조 데이터는 남는다. volume까지 삭제하는 명령은 의도적으로 일반 runbook에 포함하지 않는다.

## Kubernetes로 확장할 때의 계약

현재 구성은 Kubernetes에 배포할 수 있는 컨테이너 경계를 만들지만, 수평 확장 가능한 거래소는 아니다.

- backend는 메모리 호가창을 공유해야 하므로 **active matcher replica 1개**만 허용한다.
- participant-runner도 같은 트레이더의 중복 실행을 막기 위해 replica 1개만 허용한다.
- runner 설정은 환경 변수만 읽는다. 로컬 `.env`는 Kubernetes의 ConfigMap/Secret 주입으로 대체할 수 있다.
- `seed_traders`는 Django management command이므로 이후 Kubernetes Job 또는 migration Job에서 실행할 수 있다.
- runner는 `SIGTERM`에서 주문 정리를 시도한다. 이후 Deployment에는 이 정리가 끝날 수 있는 `terminationGracePeriodSeconds`를 설정한다.
- 다중 runner는 profile ID 기반 deterministic sharding(`SHARD_INDEX`, `SHARD_COUNT`)을 도입한 후에만 허용한다.
- backend 수평 확장은 주문·체결 상태를 외부화하거나 종목별 matcher partitioning을 구현한 Stage 4~5 이후에 검토한다.
