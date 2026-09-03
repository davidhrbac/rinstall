#!/usr/bin/env bash
set -euo pipefail

RANCHER_HOSTNAME=${RANCHER_HOSTNAME:?set RANCHER_HOSTNAME}
CERT_MANAGER_VERSION=${CERT_MANAGER_VERSION:-v1.15.3}
RANCHER_VERSION=${RANCHER_VERSION:-2.9.2}
RANCHER_REPO_NAME=${RANCHER_REPO_NAME:-rancher-stable}
RANCHER_REPO_URL=${RANCHER_REPO_URL:-https://releases.rancher.com/server-charts/stable}
RANCHER_BOOTSTRAP_PASSWORD=${RANCHER_BOOTSTRAP_PASSWORD:-}
RANCHER_PROXY=${RANCHER_PROXY:-}
RANCHER_NO_PROXY=${RANCHER_NO_PROXY:-}
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
    | sed -n 's/.*"chart":"[^"]*-\([^"]*\)".*/\1/p'
}

rancher_values_match() {
  local values

  values=$(helm get values rancher --namespace cattle-system --output yaml 2>/dev/null) || return 1
  grep -Fx "hostname: $RANCHER_HOSTNAME" <<<"$values" >/dev/null || return 1

  if [[ -n "$RANCHER_PROXY" ]]; then
    grep -Fx "proxy: $RANCHER_PROXY" <<<"$values" >/dev/null || return 1
  elif grep -E '^proxy:' <<<"$values" >/dev/null; then
    return 1
  fi

  if [[ -n "$RANCHER_NO_PROXY" ]]; then
    grep -Fx "noProxy: $RANCHER_NO_PROXY" <<<"$values" >/dev/null || return 1
  elif grep -E '^noProxy:' <<<"$values" >/dev/null; then
    return 1
  fi
}

helm repo add jetstack https://charts.jetstack.io --force-update
helm repo add "$RANCHER_REPO_NAME" "$RANCHER_REPO_URL" --force-update
helm repo update

cert_manager_current_version=$(release_chart_version cert-manager cert-manager || true)
if [[ -z "$cert_manager_current_version" ]]; then
  helm install cert-manager jetstack/cert-manager \
    --namespace cert-manager \
    --create-namespace \
    --version "$CERT_MANAGER_VERSION" \
    --set crds.enabled=true \
    --wait
elif [[ "$cert_manager_current_version" == "$CERT_MANAGER_VERSION" ]]; then
  printf 'cert-manager release already at requested chart version %s, skipping\n' "$CERT_MANAGER_VERSION"
else
  printf 'cert-manager release is at chart version %s, requested %s; rinstall does not manage cert-manager upgrades or downgrades\n' \
    "$cert_manager_current_version" "$CERT_MANAGER_VERSION" >&2
  exit 1
fi

rancher_current_version=$(release_chart_version cattle-system rancher || true)
if [[ -z "$rancher_current_version" ]]; then
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

  if [[ -n "$RANCHER_PROXY" ]]; then
    rancher_args+=(--set-string proxy="$RANCHER_PROXY")
  fi

  if [[ -n "$RANCHER_NO_PROXY" ]]; then
    rancher_args+=(--set-string noProxy="${RANCHER_NO_PROXY//,/\\,}")
  fi

  helm upgrade --install rancher "$RANCHER_REPO_NAME/rancher" "${rancher_args[@]}"
fi
