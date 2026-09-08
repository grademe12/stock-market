#!/bin/bash
set -euo pipefail

IMAGE="${1:?image}"
REGISTRY_HOST="${2:?registry host}"

ENV_FILE=/etc/stock-market/backend.env
LEGACY_CONTAINER=stock-market-backend
SHARD_COUNT=2

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

current_name() {
  printf 'stock-market-backend-%s' "$1"
}

previous_name() {
  printf 'stock-market-backend-%s-previous' "$1"
}

shard_port() {
  printf '%s' "$((8000 + $1))"
}

backend_is_ready() {
  local port="$1"
  python3 - "${port}" <<'PY'
from urllib.request import urlopen
from time import sleep
import sys

port = sys.argv[1]
for _ in range(20):
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/v1/ready/", timeout=2) as response:
            if response.status == 200:
                print(f"backend :{port} is ready")
                sys.exit(0)
    except Exception:
        sleep(2)
print(f"backend readiness check failed on :{port}", file=sys.stderr)
sys.exit(1)
PY
}

container_exists() {
  sudo docker container inspect "$1" >/dev/null 2>&1
}

retire_current() {
  local current="$1"
  local previous="$2"
  if container_exists "${current}"; then
    sudo docker rm -f "${previous}" >/dev/null 2>&1 || true
    sudo docker stop --time 30 "${current}" >/dev/null
    sudo docker rename "${current}" "${previous}"
  fi
}

restore_previous() {
  local index
  for index in $(seq 0 $((SHARD_COUNT - 1))); do
    local current previous
    current="$(current_name "${index}")"
    previous="$(previous_name "${index}")"
    sudo docker rm -f "${current}" >/dev/null 2>&1 || true
    if container_exists "${previous}"; then
      sudo docker rename "${previous}" "${current}"
      sudo docker start "${current}" >/dev/null
      echo "previous ${current} restored" >&2
    fi
  done
}

start_shard() {
  local index="$1"
  local port current
  port="$(shard_port "${index}")"
  current="$(current_name "${index}")"
  sudo docker run -d \
    --name "${current}" \
    --network host \
    --restart unless-stopped \
    --env-file "${ENV_FILE}" \
    -e "PORT=${port}" \
    -e "SIMULATION_SHARD_COUNT=${SHARD_COUNT}" \
    -e "SIMULATION_SHARD_INDEX=${index}" \
    "${IMAGE}"
}

# Recover a previous interrupted deployment before starting another one.
if ! container_exists "$(current_name 0)" && container_exists "$(previous_name 0)"; then
  restore_previous
fi

# First sharded deploy: keep the old single-process container as shard 0 previous.
if container_exists "${LEGACY_CONTAINER}" && ! container_exists "$(current_name 0)"; then
  sudo docker rm -f "$(previous_name 0)" >/dev/null 2>&1 || true
  sudo docker stop --time 30 "${LEGACY_CONTAINER}" >/dev/null
  sudo docker rename "${LEGACY_CONTAINER}" "$(previous_name 0)"
fi
if container_exists "${LEGACY_CONTAINER}"; then
  sudo docker rm -f "${LEGACY_CONTAINER}" >/dev/null 2>&1 || true
fi

index=0
for index in $(seq 0 $((SHARD_COUNT - 1))); do
  retire_current "$(current_name "${index}")" "$(previous_name "${index}")"
done

for index in $(seq 0 $((SHARD_COUNT - 1))); do
  if ! start_shard "${index}"; then
    restore_previous
    exit 1
  fi
done

for index in $(seq 0 $((SHARD_COUNT - 1))); do
  if ! backend_is_ready "$(shard_port "${index}")"; then
    echo "backend container logs ($(current_name "${index}")):" >&2
    sudo docker logs --tail 80 "$(current_name "${index}")" >&2 || true
    restore_previous
    exit 1
  fi
done

for index in $(seq 0 $((SHARD_COUNT - 1))); do
  sudo docker rm -f "$(previous_name "${index}")" >/dev/null 2>&1 || true
done
exit 0
