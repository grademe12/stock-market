# Backend observability

Prometheus and Grafana run on the mini PC and reach the GCE backend over Tailscale. No monitoring port is bound to a public or LAN address.

## Components

- Prometheus scrapes Django `/metrics/` every 15 seconds and retains at most 30 days or 10 GB.
- Blackbox exporter probes `/api/v1/ready/`, including the backend database check.
- Grafana provisions the Prometheus datasource and the `Stock Market Backend` dashboard automatically.

The dashboard covers HTTP RPS and status, p99 latency, order and trade rates, rejected orders, order-book quantity, process CPU and memory, and readiness latency.

## Configure

Create the ignored runtime file and set the two Tailscale IPv4 addresses and a strong Grafana password.

```bash
cp observability/.env.example observability/.env
```

```dotenv
OBSERVABILITY_BIND_ADDRESS=100.x.y.z
BACKEND_TAILSCALE_IP=100.x.y.z
GRAFANA_ADMIN_PASSWORD=replace-me
```

## Run

```bash
make monitoring-config
make monitoring-up
make monitoring-status
make monitoring-logs
make monitoring-down
```

Open Grafana at `http://<OBSERVABILITY_BIND_ADDRESS>:3001` and Prometheus at `http://<OBSERVABILITY_BIND_ADDRESS>:9090`. Grafana login is `admin` with the password stored in `observability/.env`.

The readiness probe works against the existing backend immediately. Application metric panels begin receiving data after the backend containing `/metrics/` is deployed.
