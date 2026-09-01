# TODO

## Next

- Add `make bastion-verify`.
  - Verify hostname, `/etc/hosts`, `dnsmasq`, `squid`, vSphere route, and Rancher URL round-robin DNS from bastion.

- Add `make rke2-status`.
  - Verify `rke2-server` service state, ports `9345`/`6443`, and `kubectl get nodes` after install.

- Test a real private environment dry-run.
  - Use `envs/private/<env>/env.yaml` with sanitized repo examples unchanged.
  - Run `make render-infra-vars`, `make infra-plan`, and SSH config checks before any apply.

## Later

- Add Rancher bootstrap hardening.
  - Verify `server-url`, `agent-tls-mode`, Rancher pod readiness, and `/ping` through the Rancher URL.

- Add Prometheus node configuration.
  - Current `node-prep` only sets hostname/prompt for `prom1`; define actual monitoring setup later.

- Add downstream cluster automation as a separate layer.
  - Do not mix downstream ingress DNS or Rancher API resources into the local infra/RKE2 bootstrap layer.

## Questions

- Which secret source should own the RKE2 token in production?
- Should real env directories live under `envs/private/` only, or should there be another ignored naming convention?
- Should GitLab issues be created from the stable items in this file after the first real dry-run?
