#!/usr/bin/env bash
set -euo pipefail

RKE2_VERSION=${RKE2_VERSION:?set RKE2_VERSION}

if [[ ! -f /etc/rancher/rke2/config.yaml ]]; then
  printf '%s\n' '/etc/rancher/rke2/config.yaml is missing' >&2
  exit 1
fi

token_file=$(awk -F': *' '/^token-file:/ {print $2}' /etc/rancher/rke2/config.yaml)
if [[ -n "$token_file" && ! -s "$token_file" ]]; then
  printf 'RKE2 token file not found or empty: %s\n' "$token_file" >&2
  exit 1
fi

if command -v rke2 >/dev/null 2>&1; then
  installed_version=$(rke2 --version | sed -n 's/^rke2 version \([^ ]*\).*/\1/p')
  if [[ -z "$installed_version" ]]; then
    printf 'unable to determine installed RKE2 version\n' >&2
    exit 1
  fi
  if [[ "$installed_version" != "$RKE2_VERSION" ]]; then
    printf 'installed RKE2 version %s does not match requested version %s; refusing change\n' "$installed_version" "$RKE2_VERSION" >&2
    exit 1
  fi
else
  curl -sfL https://get.rke2.io | INSTALL_RKE2_VERSION="$RKE2_VERSION" sh -
fi

systemctl enable rke2-server.service --now
