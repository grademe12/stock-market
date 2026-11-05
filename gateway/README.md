# Symbol gateway

공개 진입점. 이용자는 `:8000`만 보고, 종목 소속은 이 프로세스가 고른다. matcher는 `127.0.0.1:8001`부터 듣는다.

계획: [단일 진입점 · 종목 라우터](../docs/SINGLE_ENTRY_SYMBOL_ROUTER_PLAN.md). Prometheus는 `/metrics/{shard}/`로 샤드를 본다.

## 게이트웨이 자체 메트릭

`GET /gateway/metrics`. matcher를 거치지 않고 게이트웨이가 바로 답한다. 표준 라이브러리만 쓴다(`gateway/metrics.py`).

| 메트릭 | 뜻 |
|---|---|
| `gateway_listen_queue` | 커널이 받아 두고 게이트웨이가 아직 `accept()`하지 않은 연결 수. 스크레이프 시점의 `/proc/net/tcp` rx_queue(= `ss` Recv-Q) |
| `gateway_accept_wait_seconds` | `accept()`부터 처리 스레드가 실제로 돌기 시작할 때까지. GIL을 기다리면 늘어난다 |
| `gateway_request_duration_seconds{method}` | 처리 스레드 시작부터 응답을 다 쓸 때까지 |
| `gateway_upstream_duration_seconds{shard}` | 그중 matcher 왕복(연결, 요청, 응답 읽기) |
| `gateway_upstream_errors_total{shard}` | matcher 왕복 실패(502) |
| `gateway_requests_total{method,status}` | 응답 수 |
| `gateway_in_flight_requests`, `gateway_threads` | 처리 중인 요청, 살아 있는 스레드 |
| `process_cpu_seconds_total`, `process_resident_memory_bytes` | 게이트웨이 프로세스 CPU·메모리 |

요청 1건의 시간은 `커널 대기열 → accept_wait → (request_duration − upstream) → upstream`으로 나뉜다. 커널 대기열에서 기다린 시간은 직접 잴 수 없어서 길이만 본다. 메트릭 요청도 같은 대기열을 지나므로, 게이트웨이가 포화되면 스크레이프가 늦어질 수 있다.

```bash
make gateway-test
# GCE: matcher는 127.0.0.1:8001+, 공개는 :8000
# Compose: GATEWAY_SHARD_URLS=http://backend:8000,http://backend-1:8000
```
