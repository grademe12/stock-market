# Backend observability

Prometheus and Grafana run on the mini PC and reach the GCE backend over Tailscale. No monitoring port is bound to a public or LAN address.

## Components

- Prometheus scrapes each matcher shard `/metrics/` every 15 seconds via `GET /api/v1/prometheus-sd/` on `:8000` and retains at most 30 days or 10 GB. Reload Prometheus after a backend that serves that endpoint is up.
- Blackbox exporter probes `/api/v1/ready/`, including the backend database check.
- Grafana provisions the Prometheus datasource and the `Stock Market Backend` dashboard automatically.

The dashboard covers HTTP RPS and status, order POST throughput and p50/p95/p99 latency, runner `http_in_flight` and submit rate, rejected orders, order-book quantity, process CPU and memory, and readiness latency.

Runner containers expose `/metrics` on host ports 9101–9112. Prometheus runs on the host network and scrapes `127.0.0.1:9101`–`9112`.

## Configure

Create the ignored runtime file and set the two Tailscale IPv4 addresses and a strong Grafana password.

```bash
cp observability/.env.example observability/.env
```

```dotenv
OBSERVABILITY_BIND_ADDRESS=100.x.y.z
BACKEND_TAILSCALE_IP=100.x.y.z
```

`observability/secrets/admin_credential` 파일을 만들고 직접 생성한 강한 비밀번호 한 줄을 저장한다. 이 디렉터리의 실제 secret 파일은 Git에서 제외된다. Grafana는 Docker secret으로 마운트된 파일을 읽는다.

## Run

```bash
make monitoring-config
make monitoring-up
make monitoring-status
make monitoring-logs
make monitoring-down
make after-tailscale
make after-tailscale-install
```

`make after-tailscale` starts Prometheus and Grafana if they exited because the Tailscale bind address was missing at boot. Install the unit once so that happens after reboot.


Open Grafana at `http://<OBSERVABILITY_BIND_ADDRESS>:3001` and Prometheus at `http://<OBSERVABILITY_BIND_ADDRESS>:9090`. Grafana login is `admin` with the password stored in `observability/.env`. Prometheus and Grafana use the host network so they can scrape local runner ports and still stay bound to the Tailscale IPv4.

The readiness probe works against the existing backend immediately. Application metric panels begin receiving data after the backend containing `/metrics/` is deployed.
