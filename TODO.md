# TODO

## Next

### Operational Verification

- Add `make bastion-verify` to verify the hostname, `/etc/hosts`, `dnsmasq`,
  Squid, vSphere route, and Rancher URL round-robin DNS from the bastion.
- Add `make rke2-status` to verify the `rke2-server` service, ports `9345` and
  `6443`, and `kubectl get nodes` after installation.
- Add Rancher readiness and bootstrap verification through the configured
  Rancher URL, including `/ping`, pod readiness, `server-url`, and
  `agent-tls-mode`.

### DR Safety

- Define the DR version-sync contract with the separate Rancher lifecycle
  repository.
  - Every Rancher or local RKE2 upgrade must also update the bootstrap pins in
    the per-environment instance configuration before DR is considered
    complete.
  - Start with a documented Definition of Done or checklist; do not introduce
    shared Terraform state or cross-repository runtime coupling.
- Assess bootstrap helper CLI compatibility for Helm and kubectl.
  - Record a pinning or minimum-version policy against the configured
    RKE2/Rancher versions; do not blindly resolve `asdf latest kubectl`.
- Lock Python dependencies or provide an equivalent reproducibility lockfile.

## Later

- Add proxy-aware bootstrap and tool downloads.
- Add vCenter CA bootstrap for Linux and Windows.
- Add recovery for interrupted or partially completed vSphere create/apply
  workflows.
  - Keep this separate from the implemented refresh-free destroy recovery used
    when normal Terraform refresh cannot reach an external dependency.
  - Define orphan-VM discovery and cleanup, plus reconciliation after an
    interrupted create or apply.
- Harden GitLab `project_id` and backend identity handling beyond the current
  schema and base-URL validation.
- Run `make verify` in CI.
- Add supply-chain hardening for bootstrap and provisioning dependencies.
- Add a conservative downstream-network removal and migration workflow.
  - Coordinate with the separate downstream-cluster Terraform because rinstall
    cannot determine whether a VMware network is still in use.
  - Require explicit acknowledgement, remove guest DHCP/NetworkManager state
    before detaching the vNIC, and prevent attachment-order shifts for retained
    NICs.
- Split environment loading into parse, validate, and resolve stages if the
  configuration model grows enough to justify the separation.
- Split `pyinfra/deploy.py` by provisioning phase if maintaining one file
  becomes difficult.

## Open Questions

- Which secret source should own the production RKE2 token? The current engine
  consumes a supplied token or token file and does not integrate with a secret
  provider.
- What should rinstall own for the Prometheus node: VM provisioning only,
  monitoring configuration, or a different Day-0 boundary with lifecycle
  managed elsewhere?
- Should helper CLI versions be pinned, or should compatibility be enforced by
  minimum-version checks against the configured RKE2/Rancher versions?
- When should DR version-sync checking become automated after the process
  contract is established?
- After a real private-environment dry run, should stable follow-ups be tracked
  as GitLab issues or maintained in the instance-repository checklist?

## Completed / Historical

- Repo-per-instance architecture with a pinned engine submodule and private
  `.rinstall/` runtime state.
- GitLab HTTP backend support with derived Terraform state names from
  `environment.id`.
- Required schema identities, single-bastion validation, secure vSphere TLS
  defaults, configurable clone timeout, and instance-repository smoke testing.
- Downstream network/VLAN lifecycle protection, deterministic attachment
  ordering, provider-MAC mapping, and declarative bastion configuration.
- Desired topology model with deterministic JSON, Markdown, text, and Mermaid
  rendering.
- Optional committed `docs/topology/` generation and drift detection.
- Instance-local SSH known-hosts lifecycle and explicit refresh-free Terraform
  destroy recovery for missing external dependencies.
