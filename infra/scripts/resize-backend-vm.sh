#!/bin/bash
# Stop the backend VM, change its machine type, and wait until matcher
# shards answer /api/v1/ready/. In-memory books are discarded on stop.
set -euo pipefail

INSTANCE="${GCE_INSTANCE:-stock-market-dev-backend}"
ZONE="${GCE_ZONE:-asia-northeast3-a}"
TARGET_MACHINE_TYPE="${TARGET_MACHINE_TYPE:-e2-standard-4}"
SSH=(gcloud compute ssh "${INSTANCE}" --zone "${ZONE}" --tunnel-through-iap --quiet --command)

die() {
  echo "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

instance_status() {
  gcloud compute instances describe "${INSTANCE}" \
    --zone "${ZONE}" \
    --format='value(status)'
}

instance_machine_type() {
  gcloud compute instances describe "${INSTANCE}" \
    --zone "${ZONE}" \
    --format='value(machineType.basename())'
}

wait_for_status() {
  local want="$1"
  local i
  for i in $(seq 1 60); do
    if [[ "$(instance_status)" == "${want}" ]]; then
      return 0
    fi
    sleep 5
  done
  die "instance did not reach ${want}"
}

remote() {
  "${SSH[@]}" "$1"
}

wait_for_ssh() {
  local i
  for i in $(seq 1 36); do
    if remote 'true' >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  die "IAP SSH did not come back"
}

preflight() {
  require_cmd gcloud
  require_cmd docker
  require_cmd python3

  [[ "$(instance_status)" == "RUNNING" ]] || die "instance is not RUNNING"
  local current
  current="$(instance_machine_type)"
  [[ "${current}" != "${TARGET_MACHINE_TYPE}" ]] || die "already ${TARGET_MACHINE_TYPE}"

  gcloud compute machine-types describe "${TARGET_MACHINE_TYPE}" \
    --zone "${ZONE}" \
    --format='value(name,guestCpus,memoryMb,isSharedCpu)' \
    >/dev/null

  docker inspect stock-market-postgres-1 --format '{{.State.Health.Status}}' \
    | grep -qx healthy || die "local Postgres is not healthy"

  remote "$(cat <<'REMOTE'
set -euo pipefail
sudo test -f /etc/stock-market/backend.env
sudo docker image inspect stock-market-backend:interval-seconds >/dev/null
mapfile -t shards < <(sudo docker ps --format '{{.Names}}' | grep -E '^stock-market-backend-[0-9]+$' | sort)
test "${#shards[@]}" -ge 1
for name in "${shards[@]}"; do
  sudo docker inspect "${name}" --format '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}' \
    | grep -qx 'running unless-stopped'
done
tailscale ip -4 >/dev/null
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ready/", timeout=15) as response:
    payload = json.load(response)
if payload.get("status") != "ready":
    raise SystemExit("shard 0 is not ready")
for index in range(int(payload["shard_count"])):
    urllib.request.urlopen(f"http://127.0.0.1:{8000 + index}/api/v1/ready/", timeout=15)
PY
REMOTE
  )" || die "VM preflight failed"

  echo "preflight ok current=$(instance_machine_type) target=${TARGET_MACHINE_TYPE}"
}

verify() {
  wait_for_status RUNNING
  wait_for_ssh
  local i
  for i in $(seq 1 60); do
    if remote "$(cat <<'REMOTE'
set -euo pipefail
test "$(nproc)" -ge 4
tailscale ip -4 >/dev/null
python3 - <<'PY'
import json
import subprocess
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ready/", timeout=15) as response:
    payload = json.load(response)
if payload.get("status") != "ready":
    raise SystemExit("shard 0 is not ready")
shard_count = int(payload["shard_count"])
running = subprocess.check_output(["sudo", "docker", "ps", "--format", "{{.Names}}"], text=True)
names = [
    line
    for line in running.splitlines()
    if line.startswith("stock-market-backend-") and line.rsplit("-", 1)[-1].isdigit()
]
if len(names) != shard_count:
    raise SystemExit(f"expected {shard_count} shards, found {len(names)}")
for index in range(shard_count):
    urllib.request.urlopen(f"http://127.0.0.1:{8000 + index}/api/v1/ready/", timeout=15)
PY
REMOTE
    )" >/dev/null 2>&1; then
      echo "verify ok machine=$(instance_machine_type) nproc=$(remote nproc)"
      remote 'echo ==== shards ====; sudo docker ps --filter name=stock-market-backend --format "{{.Names}} {{.Status}} {{.Image}}"; echo ==== mem ====; free -h | head -2'
      return 0
    fi
    echo "waiting for Tailscale, Docker, and ready (${i}/60)"
    sleep 5
  done
  echo "backend container logs:" >&2
  remote 'sudo docker ps -a --filter name=stock-market-backend; sudo docker logs --tail 40 stock-market-backend-0; sudo docker logs --tail 40 stock-market-backend-1' >&2 || true
  die "shards did not become ready after resize"
}

resize() {
  echo "stopping ${INSTANCE}"
  gcloud compute instances stop "${INSTANCE}" --zone "${ZONE}" --quiet
  wait_for_status TERMINATED
  echo "setting machine type ${TARGET_MACHINE_TYPE}"
  gcloud compute instances set-machine-type "${INSTANCE}" \
    --zone "${ZONE}" \
    --machine-type "${TARGET_MACHINE_TYPE}"
  echo "starting ${INSTANCE}"
  gcloud compute instances start "${INSTANCE}" --zone "${ZONE}" --quiet
}

usage() {
  cat <<'EOF'
Usage: resize-backend-vm.sh preflight|resize|verify|run

  preflight  Check VM, image, env, Tailscale, ready, and local Postgres
  resize     Stop the VM, set e2-standard-4, start it (wipes in-memory books)
  verify     Wait until both shards are ready on the new machine type
  run        preflight && resize && verify

Terraform apply is not used. Update vm_machine_type so a later apply
does not move the VM back to e2-medium.
EOF
}

cmd="${1:-}"
case "${cmd}" in
  preflight) preflight ;;
  resize) resize ;;
  verify) verify ;;
  run)
    preflight
    resize
    verify
    ;;
  *)
    usage
    exit 1
    ;;
esac
