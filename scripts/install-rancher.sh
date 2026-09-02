#!/usr/bin/env bash
set -euo pipefail

RANCHER_HOSTNAME=${RANCHER_HOSTNAME:?set RANCHER_HOSTNAME}
CERT_MANAGER_VERSION=${CERT_MANAGER_VERSION:-v1.15.3}
RANCHER_VERSION=${RANCHER_VERSION:-2.9.2}
RANCHER_REPO_NAME=${RANCHER_REPO_NAME:-rancher-stable}
RANCHER_REPO_URL=${RANCHER_REPO_URL:-https://releases.rancher.com/server-charts/stable}
RANCHER_BOOTSTRAP_PASSWORD=${RANCHER_BOOTSTRAP_PASSWORD:-}
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

release_chart_version() {
  local namespace=$1
  local release=$2

  helm get metadata "$release" --namespace "$namespace" --output json 2>/dev/null \
    | sed -n 's/.*"version":"\([^"]*\)".*/\1/p'
}

version_gt() {
  local left=$1
  local right=$2

  [[ "$left" != "$right" ]] && [[ "$(printf '%s\n%s\n' "$right" "$left" | sort -V | sed -n '1p')" == "$right" ]]
}

rancher_hostname_matches() {
  helm get values rancher --namespace cattle-system --output yaml 2>/dev/null \
    | grep -Fx "hostname: $RANCHER_HOSTNAME" >/dev/null
}

helm repo add jetstack https://charts.jetstack.io --force-update
helm repo add "$RANCHER_REPO_NAME" "$RANCHER_REPO_URL" --force-update
helm repo update

cert_manager_current_version=$(release_chart_version cert-manager cert-manager || true)
if [[ -n "$cert_manager_current_version" ]]; then
  printf 'cert-manager release already installed at chart version %s, skipping\n' "$cert_manager_current_version"
else
  helm upgrade --install cert-manager jetstack/cert-manager \
    --namespace cert-manager \
    --create-namespace \
    --version "$CERT_MANAGER_VERSION" \
    --set crds.enabled=true \
    --wait
fi

rancher_current_version=$(release_chart_version cattle-system rancher || true)
if [[ -n "$rancher_current_version" ]] && version_gt "$rancher_current_version" "$RANCHER_VERSION"; then
  printf 'rancher release is already at newer chart version %s, requested %s; configuration inconsistency, refusing downgrade\n' "$rancher_current_version" "$RANCHER_VERSION" >&2
  exit 1
fi

if [[ "$rancher_current_version" == "$RANCHER_VERSION" ]] && rancher_hostname_matches; then
  printf 'rancher release already at chart version %s with hostname %s, skipping\n' "$RANCHER_VERSION" "$RANCHER_HOSTNAME"
else
  rancher_args=(
    --namespace cattle-system
    --create-namespace
    --version "$RANCHER_VERSION"
    --set hostname="$RANCHER_HOSTNAME"
    --wait
  )

  if [[ -z "$rancher_current_version" && -n "$RANCHER_BOOTSTRAP_PASSWORD" ]]; then
    rancher_args+=(--set bootstrapPassword="$RANCHER_BOOTSTRAP_PASSWORD")
  fi

  helm upgrade --install rancher "$RANCHER_REPO_NAME/rancher" "${rancher_args[@]}"
fi
