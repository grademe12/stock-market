#!/bin/bash
set -euo pipefail

IMAGE="${1:?image}"
REGISTRY_HOST="${2:?registry host}"
SQL_CONNECTION="${3:?cloud sql connection name}"
ACCESS_TOKEN_FILE="${4:?access token file}"

ENV_FILE=/etc/stock-market/backend.env
PROXY_IMAGE=gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.15.2

sudo mkdir -p /etc/stock-market
sudo chmod 700 /etc/stock-market

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing ${ENV_FILE}; copy infra/backend.env.example on the VM first" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io
  sudo systemctl enable --now docker
fi

sudo docker login -u oauth2accesstoken --password-stdin "${REGISTRY_HOST}" < "${ACCESS_TOKEN_FILE}"
sudo docker pull "${IMAGE}"

if ! sudo docker container inspect cloud-sql-proxy >/dev/null 2>&1 \
  || [[ "$(sudo docker inspect -f '{{.State.Running}}' cloud-sql-proxy)" != "true" ]]; then
  sudo docker rm -f cloud-sql-proxy >/dev/null 2>&1 || true
  sudo docker run -d \
    --name cloud-sql-proxy \
    --network host \
    --restart unless-stopped \
    "${PROXY_IMAGE}" \
    "${SQL_CONNECTION}" --address 127.0.0.1 --port 5432
fi

sudo docker rm -f stock-market-backend >/dev/null 2>&1 || true
sudo docker run -d \
  --name stock-market-backend \
  --network host \
  --restart unless-stopped \
  --env-file "${ENV_FILE}" \
  "${IMAGE}"

if python3 - <<'PY'
from urllib.request import urlopen
from time import sleep
import sys

for _ in range(20):
    try:
        with urlopen("http://127.0.0.1:8000/api/v1/health/", timeout=2) as response:
            if response.status == 200:
                print("backend is healthy")
                sys.exit(0)
    except Exception:
        sleep(2)
print("backend health check failed", file=sys.stderr)
sys.exit(1)
PY
then
  exit 0
fi

echo "backend container logs:" >&2
sudo docker logs stock-market-backend | tail -n 80 >&2
exit 1
