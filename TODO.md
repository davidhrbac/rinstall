# TODO

## Next

- Define the DR version-sync contract with the separate Rancher lifecycle repository.
  - Every Rancher or local RKE2 upgrade must also update the bootstrap pins in the per-environment infra config before DR is considered complete.
  - Start with a documented Definition of Done or checklist; do not introduce cross-repository Terraform state dependencies.

- Review vSphere TLS verification defaults.
  - Prefer `allow_unverified_ssl: false`; retain an insecure override only where explicitly required.

- Make bootstrap tooling version-aware and lock Python dependencies for DR reproducibility.
  - Derive or select `kubectl` compatible with the configured RKE2/Kubernetes version; do not blindly use `asdf latest kubectl`.
  - Ensure Helm satisfies the configured Rancher release requirements without maintaining an independent historical pin unless DR policy requires it.
  - Replace minimum-version Python dependencies with exact pins or a lockfile.

- Protect kubeconfig artifacts explicitly.
  - Enforce mode `0700` on the per-environment build/runtime directory and `0600` on `rke2.yaml.raw` and `rke2.yaml`, including standalone `make rke2-kubeconfig` runs.

- Add per-environment SSH known-hosts handling for DR.
  - Keep generated host keys outside global `~/.ssh/known_hosts` so redeploying VMs at the same IP does not block SSH.
  - Add an explicit reset operation for that environment-only known-hosts file.

- Add `make bastion-verify`.
  - Verify hostname, `/etc/hosts`, `dnsmasq`, `squid`, vSphere route, and Rancher URL round-robin DNS from bastion.

- Add `make rke2-status`.
  - Verify `rke2-server` service state, ports `9345`/`6443`, and `kubectl get nodes` after install.

- Test a real instance repository dry-run.
  - Keep customer configuration in the separate instance repository.
  - Run the instance Makefile targets and SSH config checks before any apply.

## Later

- Add declarative bastion service-network support for downstream VLANs.
  - Define a stable logical network `id`, append-only attachment `slot`, VLAN ID, vSphere portgroup, CIDR, gateway host offset, and DHCP range in env config.
  - Terraform must preserve base NIC ordering, append service NICs by slot, and expose logical network-to-MAC output for pyinfra.
  - pyinfra must resolve the guest interface by MAC, configure NetworkManager/dnsmasq declaratively, and never depend on `ens*` names or NIC ordering.
  - Render DHCP ranges only for explicit service interfaces; enable `dhcp-authoritative` only when dnsmasq serves those interfaces exclusively, and omit DHCP option 6 so clients receive the local dnsmasq address.
  - Support additions and DHCP changes first; refuse removal by default. Any removal requires an explicit safety acknowledgement because it can disconnect downstream clusters.

- Split environment loading into parse, validate, and resolve stages when the config model grows.

- Split `pyinfra/deploy.py` by provisioning phase when it becomes difficult to maintain as one file.

- Add Rancher bootstrap hardening.
  - Verify `server-url`, `agent-tls-mode`, Rancher pod readiness, and `/ping` through the Rancher URL.

- Add Prometheus node configuration.
  - Current `node-prep` only sets hostname/prompt for `prom1`; define actual monitoring setup later.

## Questions

- Which secret source should own the RKE2 token in production?
- Should the bastion VLAN section be named `bastion.service_networks` or `bastion.downstream_networks`?
- Should the engine distribution remain a pinned Git submodule until a versioned CLI has a concrete operational advantage?
- Should GitLab issues be created from the stable items in this file after the first real dry-run?
