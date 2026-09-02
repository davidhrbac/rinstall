#!/usr/bin/env bash
set -euo pipefail

RANCHER_HOSTNAME=${RANCHER_HOSTNAME:?set RANCHER_HOSTNAME}
CERT_MANAGER_VERSION=${CERT_MANAGER_VERSION:-v1.15.3}
RANCHER_VERSION=${RANCHER_VERSION:-2.9.2}
RANCHER_REPO_NAME=${RANCHER_REPO_NAME:-rancher-stable}
RANCHER_REPO_URL=${RANCHER_REPO_URL:-https://releases.rancher.com/server-charts/stable}
KUBECONFIG=${KUBECONFIG:-/root/rke2.yaml}
export KUBECONFIG

if [[ ! -s "$KUBECONFIG" ]]; then
  printf 'KUBECONFIG not found or empty: %s\n' "$KUBECONFIG" >&2
  exit 1
fi

if [[ ! -d "$HOME/.asdf" ]]; then
  git clone https://github.com/asdf-vm/asdf.git "$HOME/.asdf" --branch v0.14.1
fi

# shellcheck source=/dev/null
. "$HOME/.asdf/asdf.sh"

asdf plugin add helm https://github.com/Antiarchitect/asdf-helm.git || true
asdf install helm latest
asdf global helm latest

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
