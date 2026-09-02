#!/usr/bin/env bash
set -euo pipefail

RANCHER_HOSTNAME=${RANCHER_HOSTNAME:?set RANCHER_HOSTNAME}
CERT_MANAGER_VERSION=${CERT_MANAGER_VERSION:-v1.15.3}
RANCHER_VERSION=${RANCHER_VERSION:-2.9.2}
RANCHER_REPO_NAME=${RANCHER_REPO_NAME:-rancher-stable}
RANCHER_REPO_URL=${RANCHER_REPO_URL:-https://releases.rancher.com/server-charts/stable}
KUBECONFIG=${KUBECONFIG:-/root/rke2.yaml}
ASDF_DATA_DIR=${ASDF_DATA_DIR:-/root/.asdf}
export KUBECONFIG
export ASDF_DATA_DIR
export PATH="${ASDF_DATA_DIR}/shims:${PATH}"

if [[ ! -s "$KUBECONFIG" ]]; then
  printf 'KUBECONFIG not found or empty: %s\n' "$KUBECONFIG" >&2
  exit 1
fi

if ! command -v helm >/dev/null 2>&1; then
  printf 'helm not found; run rancher-install through pyinfra so bastion tooling is configured first\n' >&2
  exit 1
fi

helm repo add jetstack https://charts.jetstack.io
helm repo add "$RANCHER_REPO_NAME" "$RANCHER_REPO_URL"
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version "$CERT_MANAGER_VERSION" \
  --set crds.enabled=true \
  --wait

helm upgrade --install rancher "$RANCHER_REPO_NAME/rancher" \
  --namespace cattle-system \
  --create-namespace \
  --version "$RANCHER_VERSION" \
  --set hostname="$RANCHER_HOSTNAME" \
  --wait
