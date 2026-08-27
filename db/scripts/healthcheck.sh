#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

docker compose \
  --project-directory "${ROOT_DIR}" \
  -f "${ROOT_DIR}/compose.yaml" \
  exec -T postgres \
  sh -c 'pg_isready --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" &&
    psql --no-psqlrc --tuples-only --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --command="SELECT 1"'
