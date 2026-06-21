#!/usr/bin/env bash
# Apply Grafana dashboard ConfigMaps for sidecar auto-discovery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
NS="${MONITORING_NAMESPACE:-monitoring}"

kubectl get namespace "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"

for name in golden-signals burst-scenarios; do
  kubectl create configmap "grafana-dashboard-${name}" \
    --from-file="${name}.json=${ROOT}/observability/dashboards/${name}.json" \
    -n "$NS" \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl label configmap "grafana-dashboard-${name}" -n "$NS" \
    grafana_dashboard=1 --overwrite
done

echo "Dashboards applied in namespace ${NS}"