# TODO

## Next

- Clarify the repository scope in `README.md`.
  - Keep this repository limited to Day-0/DR bootstrap: vSphere, bastion, RKE2, and initial Rancher installation.
  - State explicitly that Rancher API resources, Fleet, downstream cluster lifecycle, and Rancher/Kubernetes upgrades belong to a separate Rancher environment project.

- Review vSphere TLS verification defaults.
  - Prefer `allow_unverified_ssl: false`; retain an insecure override only where explicitly required.

- Consolidate Rancher and cert-manager version defaults.
  - Keep one source of truth in resolved environment config instead of duplicating fallback versions in pyinfra and shell scripts.

- Add `make bastion-verify`.
  - Verify hostname, `/etc/hosts`, `dnsmasq`, `squid`, vSphere route, and Rancher URL round-robin DNS from bastion.

- Add `make rke2-status`.
  - Verify `rke2-server` service state, ports `9345`/`6443`, and `kubectl get nodes` after install.

- Test a real private environment dry-run.
  - Use `envs/private/<env>/env.yaml` with sanitized repo examples unchanged.
  - Run `make render-infra-vars`, `make infra-plan`, and SSH config checks before any apply.

## Later

- Add declarative bastion service-network support for downstream VLANs.
  - Define logical network name/VLAN, vSphere portgroup, CIDR, gateway host offset, and DHCP range in env config.
  - Terraform must append the matching vNIC to bastion and expose logical network-to-MAC output for pyinfra.
  - pyinfra must resolve the guest interface by MAC, configure NetworkManager/dnsmasq declaratively, and never depend on `ens*` names or NIC ordering.
  - Render DHCP ranges only for explicit service interfaces; enable `dhcp-authoritative` only when dnsmasq serves those interfaces exclusively, and omit DHCP option 6 so clients receive the local dnsmasq address.
  - Removing a configured network must require an explicit safety acknowledgement because it can disconnect downstream clusters.

- Split environment loading into parse, validate, and resolve stages when the config model grows.

- Split `pyinfra/deploy.py` by provisioning phase when it becomes difficult to maintain as one file.

- Add Rancher bootstrap hardening.
  - Verify `server-url`, `agent-tls-mode`, Rancher pod readiness, and `/ping` through the Rancher URL.

- Add Prometheus node configuration.
  - Current `node-prep` only sets hostname/prompt for `prom1`; define actual monitoring setup later.

- Add downstream cluster automation as a separate layer.
  - Do not mix downstream ingress DNS, Rancher API resources, Fleet, or downstream lifecycle into the local infra/RKE2 bootstrap layer.

## Questions

- Which secret source should own the RKE2 token in production?
- Should real env directories live under `envs/private/` only, or should there be another ignored naming convention?
- Should the bastion VLAN section be named `bastion.service_networks` or `bastion.downstream_networks`?
- Should per-environment repositories consume this engine through a pinned Git submodule, or should the engine become a versioned CLI?
- Where should per-environment generated Terraform/runtime files live when the engine is consumed as a submodule?
- Should GitLab issues be created from the stable items in this file after the first real dry-run?
