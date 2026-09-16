#!/usr/bin/env bash
# Wait until this machine has a Tailscale IPv4, then start exited containers
# that publish ports on that address. Docker restart policies do not retry
# when the first bind fails with "cannot assign requested address".
set -euo pipefail

DEADLINE_SECONDS="${TAILSCALE_BIND_WAIT_SECONDS:-120}"
deadline=$((SECONDS + DEADLINE_SECONDS))

tailscale_ipv4() {
  tailscale ip -4 2>/dev/null || true
}

address_is_local() {
  local ip="$1"
  ip -4 -o addr show | awk '{print $4}' | grep -q "^${ip}/"
}

wait_for_bind_address() {
  local ip=""
  while ((SECONDS < deadline)); do
    ip="$(tailscale_ipv4)"
    if [[ -n "${ip}" ]] && address_is_local "${ip}"; then
      printf '%s\n' "${ip}"
      return 0
    fi
    sleep 1
  done
  echo "Tailscale IPv4 was not on a local interface within ${DEADLINE_SECONDS}s" >&2
  return 1
}

bound_to_ip() {
  local container="$1"
  local ip="$2"
  docker inspect \
    --format '{{range $p, $conf := .HostConfig.PortBindings}}{{range $conf}}{{.HostIp}} {{end}}{{end}}' \
    "${container}" \
    | grep -Fqw "${ip}"
}

start_bound_containers() {
  local ip="$1"
  local id
  local started=0
  for id in $(docker ps -aq --filter status=exited); do
    if bound_to_ip "${id}" "${ip}"; then
      docker start "${id}" >/dev/null
      echo "started $(docker inspect --format '{{.Name}}' "${id}" | sed 's#^/##')"
      started=1
    fi
  done
  if ((started == 0)); then
    echo "no exited containers bound to ${ip}"
  fi
}

ip="$(wait_for_bind_address)"
start_bound_containers "${ip}"
