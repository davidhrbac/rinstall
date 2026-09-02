#!/usr/bin/env bash
set -euo pipefail

RANCHER_URL=${RANCHER_URL:?set RANCHER_URL}
AGENT_TLS_MODE=${AGENT_TLS_MODE:-system-store}
KUBECONFIG=${KUBECONFIG:-/root/rke2.yaml}
export KUBECONFIG

kubectl -n cattle-system rollout status deploy/rancher --timeout=10m

kubectl patch setting.management.cattle.io server-url \
  --type=merge \
  -p "{\"value\":\"${RANCHER_URL}\"}"

kubectl patch setting.management.cattle.io agent-tls-mode \
  --type=merge \
  -p "{\"value\":\"${AGENT_TLS_MODE}\"}"

kubectl get setting.management.cattle.io server-url -o jsonpath='{.value}{"\n"}'
kubectl get setting.management.cattle.io agent-tls-mode -o jsonpath='{.value}{"\n"}'
