#!/bin/bash
set -euo pipefail

readonly METADATA_URL="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
readonly METADATA_HEADER="Metadata-Flavor: Google"
readonly ENV_DIR="/etc/stock-market"
readonly ENV_FILE="${ENV_DIR}/backend.env"

metadata_value() {
  curl --fail --silent --show-error \
    -H "${METADATA_HEADER}" \
    "${METADATA_URL}/$1"
}

secret_value() {
  gcloud secrets versions access latest \
    --project "${project_id}" \
    --secret "$1"
}

for command_name in docker gcloud tailscale; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "custom image contract violation: ${command_name} is not installed" >&2
    exit 1
  fi
done

project_id="$(metadata_value stock-market-project-id)"
tailscale_hostname="$(metadata_value stock-market-tailscale-hostname)"
tailscale_tags="$(metadata_value stock-market-tailscale-tags)"
tailscale_secret="$(metadata_value stock-market-tailscale-secret)"
postgres_secret="$(metadata_value stock-market-postgres-secret)"
django_secret="$(metadata_value stock-market-django-secret)"
postgres_host="$(metadata_value stock-market-postgres-host)"
postgres_port="$(metadata_value stock-market-postgres-port)"
postgres_database="$(metadata_value stock-market-postgres-database)"
postgres_user="$(metadata_value stock-market-postgres-user)"
django_allowed_hosts="$(metadata_value stock-market-django-allowed-hosts)"

systemctl enable --now docker
systemctl enable --now tailscaled

if ! tailscale ip -4 >/dev/null 2>&1; then
  tailscale_auth_key="$(secret_value "${tailscale_secret}")"
  tailscale up \
    --auth-key="${tailscale_auth_key}" \
    --hostname="${tailscale_hostname}" \
    --advertise-tags="${tailscale_tags}"
  unset tailscale_auth_key
fi

postgres_password="$(secret_value "${postgres_secret}")"
django_secret_key="$(secret_value "${django_secret}")"

install -d -m 700 "${ENV_DIR}"
temporary_env="$(mktemp "${ENV_DIR}/backend.env.XXXXXX")"
trap 'rm -f "${temporary_env}"' EXIT
chmod 600 "${temporary_env}"

cat > "${temporary_env}" <<EOF
DATABASE_ENGINE=postgresql
POSTGRES_DB=${postgres_database}
POSTGRES_USER=${postgres_user}
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_HOST=${postgres_host}
POSTGRES_PORT=${postgres_port}
POSTGRES_CONNECT_TIMEOUT_SECONDS=3
DJANGO_SECRET_KEY=${django_secret_key}
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=${django_allowed_hosts}
TRADE_EXECUTION_LOG_ENABLED=0
EOF

mv "${temporary_env}" "${ENV_FILE}"
trap - EXIT
unset postgres_password django_secret_key

echo "stock-market VM bootstrap completed"
