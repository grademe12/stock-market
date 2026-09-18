# Symbol gateway

공개 진입점. 이용자는 `:8000`만 보고, 종목 소속은 이 프로세스가 고른다. matcher는 `127.0.0.1:8001`부터 듣는다.

계획: [단일 진입점 · 종목 라우터](../docs/SINGLE_ENTRY_SYMBOL_ROUTER_PLAN.md) G1.

```bash
make gateway-test
# GCE: matcher는 127.0.0.1:8001+, 공개는 :8000
# Compose: GATEWAY_SHARD_URLS=http://backend:8000,http://backend-1:8000
```
