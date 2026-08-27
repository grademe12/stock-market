#!/bin/bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run this script as root on a disposable Debian 12 builder VM" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl docker.io gnupg

if ! command -v tailscale >/dev/null 2>&1; then
  curl --fail --silent --show-error \
    https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl --fail --silent --show-error \
    https://pkgs.tailscale.com/stable/debian/bookworm.tailscale-keyring.list \
    -o /etc/apt/sources.list.d/tailscale.list
fi

if ! command -v gcloud >/dev/null 2>&1; then
  curl --fail --silent --show-error \
    https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor --yes -o /usr/share/keyrings/cloud.google.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list
fi

apt-get update
apt-get install -y --no-install-recommends google-cloud-cli tailscale

systemctl enable docker
systemctl enable tailscaled
systemctl stop tailscaled || true

# A custom image must contain the client software, never a cloned node identity.
rm -rf /var/lib/tailscale/*
rm -rf /var/lib/cloud/instances/*
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "base image is ready; stop the builder VM before creating the custom image"
