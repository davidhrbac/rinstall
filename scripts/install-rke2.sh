#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f /etc/rancher/rke2/config.yaml ]]; then
  printf '%s\n' '/etc/rancher/rke2/config.yaml is missing' >&2
  exit 1
fi

token_file=$(awk -F': *' '/^token-file:/ {print $2}' /etc/rancher/rke2/config.yaml)
if [[ -n "$token_file" && ! -s "$token_file" ]]; then
  printf 'RKE2 token file not found or empty: %s\n' "$token_file" >&2
  exit 1
fi

if ! command -v rke2 >/dev/null 2>&1; then
  curl -sfL https://get.rke2.io | sh -
fi

systemctl enable rke2-server.service --now
