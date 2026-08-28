#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_FILE="${1:-}"

if [[ -z "${BACKUP_FILE}" || ! -f "${BACKUP_FILE}" ]]; then
  echo "usage: RESTORE_CONFIRM=stock_market bash db/scripts/restore.sh <backup.dump>" >&2
  exit 2
fi

if [[ "${RESTORE_CONFIRM:-}" != "stock_market" ]]; then
  echo "restore replaces existing schema objects; set RESTORE_CONFIRM=stock_market" >&2
  exit 2
fi

docker compose \
  --project-directory "${ROOT_DIR}" \
  -f "${ROOT_DIR}/compose.yaml" \
  exec -T postgres \
  sh -c 'pg_restore --clean --if-exists --no-owner --exit-on-error --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  < "${BACKUP_FILE}"

echo "restore completed from ${BACKUP_FILE}"
