#!/bin/bash
set -euo pipefail

readonly CONFIG_FILE="/etc/stock-market/bootstrap.conf"
readonly ENV_DIR="/etc/stock-market"
readonly ENV_FILE="${ENV_DIR}/backend.env"
readonly IMDS_TOKEN_URL="http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net"

for command_name in curl docker python3 tailscale; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "cloud-init contract violation: ${command_name} is not installed" >&2
    exit 1
  fi
done

# shellcheck source=/dev/null
source "${CONFIG_FILE}"

json_field() {
  python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

# The VM's managed identity gets a Key Vault token from the instance metadata
# service, so no credential is stored on disk.
vault_token="$(curl --fail --silent --show-error -H "Metadata: true" "${IMDS_TOKEN_URL}" | json_field access_token)"

secret_value() {
  local response
  if ! response="$(curl --fail --silent --show-error \
    -H "Authorization: Bearer ${vault_token}" \
    "https://${KEY_VAULT_NAME}.vault.azure.net/secrets/$1?api-version=7.4")"; then
    echo "cannot read Key Vault secret '$1' from ${KEY_VAULT_NAME}; set it with az keyvault secret set" >&2
    return 1
  fi
  printf '%s' "${response}" | json_field value
}

systemctl enable --now docker
systemctl enable --now tailscaled

if ! tailscale ip -4 >/dev/null 2>&1; then
  tailscale_auth_key="$(secret_value "${TAILSCALE_SECRET}")"
  tailscale up \
    --auth-key="${tailscale_auth_key}" \
    --hostname="${TAILSCALE_HOSTNAME}" \
    --advertise-tags="${TAILSCALE_TAGS}"
  unset tailscale_auth_key
fi

postgres_password="$(secret_value "${POSTGRES_SECRET}")"
django_secret_key="$(secret_value "${DJANGO_SECRET}")"
unset vault_token

install -d -m 700 "${ENV_DIR}"
temporary_env="$(mktemp "${ENV_DIR}/backend.env.XXXXXX")"
trap 'rm -f "${temporary_env}"' EXIT
chmod 600 "${temporary_env}"

cat > "${temporary_env}" <<ENV
DATABASE_ENGINE=postgresql
POSTGRES_DB=${POSTGRES_DATABASE}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_HOST=${POSTGRES_HOST}
POSTGRES_PORT=${POSTGRES_PORT}
POSTGRES_CONNECT_TIMEOUT_SECONDS=3
DJANGO_SECRET_KEY=${django_secret_key}
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS}
TRADE_EXECUTION_LOG_ENABLED=0
SIMULATION_SYMBOL_LIMIT=10
ENV

mv "${temporary_env}" "${ENV_FILE}"
trap - EXIT
unset postgres_password django_secret_key

echo "stock-market VM bootstrap completed"
