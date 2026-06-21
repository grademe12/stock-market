# Observability Examples

## ServiceMonitor

`order-gateway-servicemonitor.yaml` is the template for scraping `/metrics` from exchange services.

Requirements for each service:

1. Service exposes a port named `metrics` (or set `port` in ServiceMonitor).
2. Pod serves Prometheus text format on `/metrics`.
3. ServiceMonitor lives in `exchange` namespace (or update `namespaceSelector`).

Prometheus is configured to discover **all** ServiceMonitors cluster-wide (`serviceMonitorNamespaceSelector: {}`).

## PrometheusRule (alerts)

See `observability/alerts/slo-rules.yaml` for SLO alert rules (applied in Phase 2+).