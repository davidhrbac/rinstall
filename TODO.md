# TODO

## Completed In This Branch

- Repo-per-instance architecture with mandatory GitLab backend and derived Terraform state `<environment.id>-infra`.
- Verified vSphere TLS default, configurable clone timeout, and real instance-repository smoke testing.
- Schema validation for single bastion scope, configured topology names, and required backend/config identities.

## Next

- Define the DR version-sync contract with the separate Rancher lifecycle repository.
  - Every Rancher or local RKE2 upgrade must also update the bootstrap pins in the per-environment infra config before DR is considered complete.
  - Start with a documented Definition of Done or checklist; do not introduce cross-repository Terraform state dependencies.

- Make bootstrap tooling version-aware and lock Python dependencies for DR reproducibility.
  - Derive or select `kubectl` compatible with the configured RKE2/Kubernetes version; do not blindly use `asdf latest kubectl`.
  - Ensure Helm satisfies the configured Rancher release requirements without maintaining an independent historical pin unless DR policy requires it.
  - Replace minimum-version Python dependencies with exact pins or a lockfile.

- Add proxy-aware bootstrap/tool downloads.

- Add vCenter CA bootstrap for Linux and Windows.

- Add recovery for partial vSphere creates and orphan VMs.

- Harden GitLab `project_id` and backend identity handling.

- Run `make verify` in CI.

- Add supply-chain hardening for bootstrap and provisioning dependencies.

- Add multi-bastion/HA bastion support in a future schema; this remains outside schema v1 and v0.2.

- Add `make bastion-verify`.
  - Verify hostname, `/etc/hosts`, `dnsmasq`, `squid`, vSphere route, and Rancher URL round-robin DNS from bastion.

- Add `make rke2-status`.
  - Verify `rke2-server` service state, ports `9345`/`6443`, and `kubectl get nodes` after install.

## Later

- Add a conservative downstream-network removal workflow after v0.3.0.
  - Coordinate with the separate downstream-cluster Terraform because rinstall cannot determine whether a VMware network is still in use.
  - Require explicit acknowledgement, remove guest DHCP/NetworkManager state before detaching the vNIC, and prevent attachment-order shifts for retained NICs.

- Split environment loading into parse, validate, and resolve stages when the config model grows.

- Split `pyinfra/deploy.py` by provisioning phase when it becomes difficult to maintain as one file.

- Add Rancher bootstrap hardening.
  - Verify `server-url`, `agent-tls-mode`, Rancher pod readiness, and `/ping` through the Rancher URL.

- Add Prometheus node configuration.
   - Current `node-prep` only sets hostname/prompt for the Prometheus node; define actual monitoring setup later.

## Questions

- Which secret source should own the RKE2 token in production?
- Should GitLab issues be created from the stable items in this file after the first real dry-run?
