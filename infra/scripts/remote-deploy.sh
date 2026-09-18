#!/bin/bash
set -euo pipefail

IMAGE="${1:?image}"
REGISTRY_HOST="${2:?registry host}"
GATEWAY_IMAGE="${GATEWAY_IMAGE:-${3:-}}"
if [[ -z "${GATEWAY_IMAGE}" ]]; then
  echo "set GATEWAY_IMAGE or pass it as the third argument" >&2
  exit 1
fi

ENV_FILE=/etc/stock-market/backend.env
SHARDS_FILE=/etc/stock-market/shards.env
LEGACY_CONTAINER=stock-market-backend
SHARD_COUNT_MAXIMUM=8

detect_shard_count() {
  local raw cpus
  raw="${SIMULATION_SHARD_COUNT:-}"
  if [[ -n "${raw}" ]]; then
    if [[ ! "${raw}" =~ ^[1-9][0-9]*$ ]]; then
      echo "SIMULATION_SHARD_COUNT must be a positive integer" >&2
      exit 1
    fi
    if (( raw > SHARD_COUNT_MAXIMUM )); then
      echo "SIMULATION_SHARD_COUNT must be at most ${SHARD_COUNT_MAXIMUM}" >&2
      exit 1
    fi
    printf '%s' "${raw}"
    return
  fi
  cpus="$(nproc)"
  if (( cpus < 1 )); then
    cpus=1
  fi
  if (( cpus > SHARD_COUNT_MAXIMUM )); then
    cpus="${SHARD_COUNT_MAXIMUM}"
  fi
  printf '%s' "${cpus}"
}

SHARD_COUNT="$(detect_shard_count)"
echo "deploying gateway :8000 and ${SHARD_COUNT} matcher shard(s) on 127.0.0.1:8001+ (nproc=$(nproc) pin=${SIMULATION_SHARD_COUNT:-nproc})"

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

if [[ "${SKIP_PULL:-}" == "1" ]]; then
  sudo docker image inspect "${IMAGE}" >/dev/null
  sudo docker image inspect "${GATEWAY_IMAGE}" >/dev/null
else
  registry_token="$(gcloud auth print-access-token)"
  printf '%s' "${registry_token}" \
    | sudo docker login -u oauth2accesstoken --password-stdin "${REGISTRY_HOST}"
  unset registry_token
  sudo docker pull "${IMAGE}"
  sudo docker pull "${GATEWAY_IMAGE}"
fi

current_name() {
  printf 'stock-market-backend-%s' "$1"
}

previous_name() {
  printf 'stock-market-backend-%s-previous' "$1"
}

GATEWAY_NAME=stock-market-gateway
GATEWAY_PREVIOUS_NAME=stock-market-gateway-previous

shard_port() {
  printf '%s' "$((8001 + $1))"
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

running_shard_indices() {
  sudo docker ps -a --format '{{.Names}}' \
    | sed -n 's/^stock-market-backend-\([0-9][0-9]*\)$/\1/p' \
    | sort -n
}

remove_extra_shards() {
  local index
  for index in $(running_shard_indices); do
    if (( index >= SHARD_COUNT )); then
      sudo docker rm -f "$(current_name "${index}")" >/dev/null 2>&1 || true
      sudo docker rm -f "$(previous_name "${index}")" >/dev/null 2>&1 || true
    fi
  done
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
  for index in ${PREVIOUS_SHARD_INDICES:-}; do
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
  for index in $(running_shard_indices); do
    if [[ " ${PREVIOUS_SHARD_INDICES:-} " != *" ${index} "* ]]; then
      sudo docker rm -f "$(current_name "${index}")" >/dev/null 2>&1 || true
    fi
  done
  sudo docker rm -f "${GATEWAY_NAME}" >/dev/null 2>&1 || true
  if container_exists "${GATEWAY_PREVIOUS_NAME}"; then
    sudo docker rename "${GATEWAY_PREVIOUS_NAME}" "${GATEWAY_NAME}"
    sudo docker start "${GATEWAY_NAME}" >/dev/null
    echo "previous ${GATEWAY_NAME} restored" >&2
  fi
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
    -e "GUNICORN_BIND=127.0.0.1" \
    -e "SIMULATION_SHARD_COUNT=${SHARD_COUNT}" \
    -e "SIMULATION_SHARD_INDEX=${index}" \
    "${IMAGE}"
}

start_gateway() {
  sudo docker run -d \
    --name "${GATEWAY_NAME}" \
    --network host \
    --restart unless-stopped \
    -e "GATEWAY_BIND=0.0.0.0" \
    -e "GATEWAY_PORT=8000" \
    -e "GATEWAY_MATCHER_HOST=127.0.0.1" \
    -e "GATEWAY_FIRST_MATCHER_PORT=8001" \
    -e "GATEWAY_UNIVERSE_URL=http://127.0.0.1:8001" \
    -e "SIMULATION_SHARD_COUNT=${SHARD_COUNT}" \
    "${GATEWAY_IMAGE}"
}

# Recover a previous interrupted deployment before starting another one.
if ! container_exists "$(current_name 0)" && container_exists "$(previous_name 0)"; then
  PREVIOUS_SHARD_INDICES="$(sudo docker ps -a --format '{{.Names}}' \
    | sed -n 's/^stock-market-backend-\([0-9][0-9]*\)-previous$/\1/p' \
    | tr '\n' ' ')"
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

PREVIOUS_SHARD_INDICES="$(running_shard_indices | tr '\n' ' ')"

retire_current "${GATEWAY_NAME}" "${GATEWAY_PREVIOUS_NAME}"

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

if ! start_gateway; then
  restore_previous
  exit 1
fi
if ! backend_is_ready 8000; then
  echo "gateway container logs:" >&2
  sudo docker logs --tail 80 "${GATEWAY_NAME}" >&2 || true
  restore_previous
  exit 1
fi

for index in $(seq 0 $((SHARD_COUNT - 1))); do
  sudo docker rm -f "$(previous_name "${index}")" >/dev/null 2>&1 || true
done
sudo docker rm -f "${GATEWAY_PREVIOUS_NAME}" >/dev/null 2>&1 || true
remove_extra_shards
printf 'SIMULATION_SHARD_COUNT=%s\n' "${SHARD_COUNT}" | sudo tee "${SHARDS_FILE}" >/dev/null
sudo chmod 600 "${SHARDS_FILE}"
exit 0
