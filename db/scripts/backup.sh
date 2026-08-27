#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/db/backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${BACKUP_DIR}/stock_market-${timestamp}.dump"
temporary_file="${backup_file}.tmp"

install -d -m 700 "${BACKUP_DIR}"
umask 077
trap 'rm -f "${temporary_file}"' EXIT

docker compose \
  --project-directory "${ROOT_DIR}" \
  -f "${ROOT_DIR}/compose.yaml" \
  exec -T postgres \
  sh -c 'pg_dump --format=custom --no-owner --username="$POSTGRES_USER" "$POSTGRES_DB"' \
  > "${temporary_file}"

mv "${temporary_file}" "${backup_file}"
trap - EXIT
echo "${backup_file}"
