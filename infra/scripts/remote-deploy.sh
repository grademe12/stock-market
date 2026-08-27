#!/bin/bash
set -euo pipefail

IMAGE="${1:?image}"
REGISTRY_HOST="${2:?registry host}"

ENV_FILE=/etc/stock-market/backend.env
CURRENT_CONTAINER=stock-market-backend
PREVIOUS_CONTAINER=stock-market-backend-previous

sudo mkdir -p /etc/stock-market
sudo chmod 700 /etc/stock-market

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing ${ENV_FILE}; VM bootstrap has not completed" >&2
  exit 1
fi

for command_name in docker gcloud tailscale; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "custom image contract violation: ${command_name} is not installed" >&2
    exit 1
  fi
done

if ! tailscale ip -4 >/dev/null 2>&1; then
  echo "Tailscale is not connected" >&2
  exit 1
fi

registry_token="$(gcloud auth print-access-token)"
printf '%s' "${registry_token}" \
  | sudo docker login -u oauth2accesstoken --password-stdin "${REGISTRY_HOST}"
unset registry_token
sudo docker pull "${IMAGE}"

backend_is_ready() {
  python3 - <<'PY'
from urllib.request import urlopen
from time import sleep
import sys

for _ in range(20):
    try:
        with urlopen("http://127.0.0.1:8000/api/v1/ready/", timeout=2) as response:
            if response.status == 200:
                print("backend is ready")
                sys.exit(0)
    except Exception:
        sleep(2)
print("backend readiness check failed", file=sys.stderr)
sys.exit(1)
PY
}

restore_previous() {
  sudo docker rm -f "${CURRENT_CONTAINER}" >/dev/null 2>&1 || true
  if sudo docker container inspect "${PREVIOUS_CONTAINER}" >/dev/null 2>&1; then
    sudo docker rename "${PREVIOUS_CONTAINER}" "${CURRENT_CONTAINER}"
    sudo docker start "${CURRENT_CONTAINER}" >/dev/null
    echo "previous backend container restored" >&2
  fi
}

# Recover a previous interrupted deployment before starting another one.
if ! sudo docker container inspect "${CURRENT_CONTAINER}" >/dev/null 2>&1 \
  && sudo docker container inspect "${PREVIOUS_CONTAINER}" >/dev/null 2>&1; then
  sudo docker rename "${PREVIOUS_CONTAINER}" "${CURRENT_CONTAINER}"
  sudo docker start "${CURRENT_CONTAINER}" >/dev/null
fi

if sudo docker container inspect "${CURRENT_CONTAINER}" >/dev/null 2>&1; then
  sudo docker rm -f "${PREVIOUS_CONTAINER}" >/dev/null 2>&1 || true
  sudo docker stop --time 30 "${CURRENT_CONTAINER}" >/dev/null
  sudo docker rename "${CURRENT_CONTAINER}" "${PREVIOUS_CONTAINER}"
fi

if ! sudo docker run -d \
  --name "${CURRENT_CONTAINER}" \
  --network host \
  --restart unless-stopped \
  --env-file "${ENV_FILE}" \
  "${IMAGE}"; then
  restore_previous
  exit 1
fi

if backend_is_ready; then
  sudo docker rm -f "${PREVIOUS_CONTAINER}" >/dev/null 2>&1 || true
  exit 0
fi

echo "backend container logs:" >&2
sudo docker logs --tail 80 "${CURRENT_CONTAINER}" >&2 || true
restore_previous
exit 1
