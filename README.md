# Rancher Environment Install

Automation scaffold for a manually operated Rancher environment build on vSphere.

The design intentionally separates infrastructure from Rancher API configuration so disaster recovery can restore the base layer before Rancher-dependent resources are reconciled.

## Scope

This repository is a Day-0/DR bootstrap engine only. It provisions vSphere infrastructure, configures the bastion and local hosts, bootstraps RKE2, and performs the initial Rancher installation.

Rancher API resources, Fleet configuration, downstream cluster lifecycle, and Rancher/Kubernetes upgrades are intentionally out of scope. Manage them in a separate per-environment Rancher lifecycle repository after Rancher exists.

## Layers

```text
Terraform infra  -> vSphere VMs, NICs, static IPs where required, VM inventory outputs
pyinfra          -> bastion dnsmasq/squid/routes and rancher node file prep
RKE2 scripts     -> local RKE2 cluster bootstrap
Helm scripts     -> cert-manager and Rancher install from bastion1

Hard boundary: a separate Rancher Environment repository manages Rancher upgrades,
Fleet, imported downstream clusters, downstream lifecycle, and Kubernetes upgrades.
```

## Production Instance Flow

Production use is a separate instance repository containing `config.yaml`, a
`.gitmodules` file, a `.gitignore` entry for `.rinstall/`, and the pinned
`rinstall` submodule. The sanitized layout fixture is in
`examples/instance-repository/`. No wrapper Makefile or `.envrc` is required:

```bash
make -f rinstall/Makefile verify
make -f rinstall/Makefile infra-plan
make -f rinstall/Makefile provision-all
```

Generated runtime files are kept under the ignored `.rinstall/` directory,
including Terraform metadata in `.rinstall/terraform-data/`.

Production `config.yaml` declares the GitLab state location:

```yaml
schema_version: 1
environment:
  id: customer-a-prod
terraform:
  backend:
    type: gitlab
    url: https://gitlab.example
    project_id: 1234
    state: infra
```

Only credentials come from the runtime environment: `TF_HTTP_USERNAME` and
`TF_HTTP_PASSWORD`. `rinstall` derives the address and lock/unlock URLs.
When both are present, config-derived non-secret values override matching
`TF_HTTP_*` values supplied by the shell.

## Development / Validation Fixture

For engine development and sanitized fixtures, use `envs/example/env.yaml` for
rendering, syntax checks, and tests. It is not a standalone Terraform
provisioning configuration; do not run infrastructure targets with it unless
you have added a GitLab backend configuration and runtime credentials.

```bash
make render-infra-vars ENV=envs/example
make ssh-config ENV=envs/example
```

For a development environment that needs Terraform provisioning, use an
explicit GitLab-backed instance configuration and provide
`TF_HTTP_USERNAME`/`TF_HTTP_PASSWORD` at runtime. The instance flow then uses
the same `make -f rinstall/Makefile infra-init`, `infra-plan`, `infra-apply`,
and `provision-all` targets documented above.

`make rancher-install` and `make rancher-bootstrap` automatically fetch `/etc/rancher/rke2/rke2.yaml` from the primary Rancher node, rewrite its Kubernetes API endpoint to the primary node IP, and upload the prepared kubeconfig to `bastion1:/root/rke2.yaml`. The helper target `make rke2-kubeconfig` is available for debugging that step directly.

Rancher Helm install receives `proxy` and `noProxy` values derived from the bastion Squid service IP/port and the generated `proxy.no_proxy` list. `noProxy` includes private CIDRs, Kubernetes service DNS suffixes, the local VLAN CIDR, the Rancher URL, and any explicit `proxy.extra_no_proxy` values. This is separate from the host-level proxy files rendered during node prep.

Prefer static addressing on the bastion management NIC. Set it as `cidr` on the management NIC and the env loader derives `nodes.bastion1.ssh_ip` from that address for generated SSH config.

Terraform commands use local workstation credentials/environment and talk to vSphere/GitLab from there. pyinfra and Helm/Rancher installation steps can also run from the workstation; SSH routing is handled by generated OpenSSH config.

## Destroying Production Infra

From the production instance repository, destroy Terraform-managed vSphere VMs
from the operator workstation with the same config and runtime credentials used
for creation:

```bash
make -f rinstall/Makefile infra-init
make -f rinstall/Makefile destroy-commands
```

Generated paths are under `.rinstall/` and the pinned Terraform root remains
`rinstall/terraform/infra`.

Run `infra-init` first on a fresh workstation or checkout. It initializes the
same config-derived GitLab backend using inherited runtime credentials. The
`destroy-commands` target only renders tfvars and prints commands; it does not
initialize Terraform, create a plan, or destroy resources automatically.

The helper prints the explicit Terraform commands to run, for example:

```bash
terraform -chdir=rinstall/terraform/infra plan -destroy -var-file=.rinstall/infra.tfvars.json
terraform -chdir=rinstall/terraform/infra destroy -var-file=.rinstall/infra.tfvars.json
```

Always confirm the instance repository, Terraform backend/state, and destroy plan before approving. There is intentionally no `make infra-destroy` or `make destroy-all` shortcut, because destroy is destructive and should stay explicit. Terraform destroy only removes resources tracked by the Terraform infra state; it does not clean Rancher API resources, downstream clusters, external DNS/LB records, DHCP reservations, or local generated files under `.rinstall/`.

`make -f rinstall/Makefile destroy-commands` prints a header with the selected instance config, runtime directory, Terraform directory, tfvars path, vSphere server/user when available from environment variables, backend/init settings, and then the explicit review/destroy commands. It never prints the vSphere password.

Keep vCenter connection details out of `env.yaml` unless there is a specific reason to pin them there. Terraform accepts them through environment variables, which can be loaded by `direnv` from an ignored `.envrc`:

```bash
export TF_VAR_vsphere_server="vcenter.example.internal"
export TF_VAR_vsphere_user="administrator@example.internal"
export TF_VAR_vsphere_password="change-me"
```

See `.envrc.example` for the expected variable names. `make render-infra-vars` omits `vsphere_server` and `vsphere_user` when they are not set in `env.yaml`, so Terraform will read `TF_VAR_vsphere_server` and `TF_VAR_vsphere_user` from the operator environment.

Standalone engine validation uses `terraform init -backend=false`. Production
instances use the static HTTP backend in the pinned engine and settings from
`config.yaml`; no backend files or Terraform source are generated at runtime.

If local nodes require a separate SSH jump host, configure it in the environment
config. pyinfra inventory will generate `build/<environment.id>/ssh_config` in
standalone mode or `.rinstall/ssh_config` in an instance repository. `bastion1`
goes through the first jump host; local-only nodes can go through the first jump
host and then `bastion1`:

```yaml
ssh:
  user: root
  private_key: ~/.ssh/id_rsa
  jump_host: existing-ssh-config-alias
  bastion_proxy_roles:
    - prometheus
    - rancher
```

The jump host alias should be defined in the operator's `~/.ssh/config`; `make ssh-config` generates `build/<environment.id>/ssh_config`, includes that file, and only adds target-node routing. Generated target entries use `ProxyCommand` so both OpenSSH and pyinfra's SSH connector can consume the same config. This keeps real internal hostnames, IPs, and upstream SSH topology out of the repo. Use `ssh_ip` per node only if the desired SSH target cannot be derived from a static management NIC.

For administrator access from an existing admin jump host, run
`make -f rinstall/Makefile admin-ssh-config` from an instance repository. It
renders `.rinstall/<environment.id>.conf` with aliases such as
`bastion1.<environment.id>` and `prom1.<environment.id>`. In standalone mode,
pass `ENV=envs/example` and the output is under `build/<environment.id>/`.
Configure that host once to include `~/.ssh/config.d/*.conf`, then upload the
fragment explicitly:

```bash
make -f rinstall/Makefile install-admin-ssh-config
```

The upload target uses `ssh.jump_host` unless `ADMIN_SSH_HOST=<SSH alias>` overrides it. It creates `/root/.ssh/config.d` and uploads the per-environment fragment with mode `0600`; it never modifies `/root/.ssh/config` or adds its `Include` directive.

For bastion access through the management NIC, prefer static NIC addressing with `cidr`. The loader derives `nodes.bastion1.ssh_ip` from the management NIC IP; `bastion.service_ip` and local DNS/proxy services still use the customer-facing static IP from `host: 4`.

The pyinfra inventory is phase-aware. `PHASE=bastion`, `PHASE=rancher-install`, and `PHASE=rancher-bootstrap` connect only to bastion; RKE2 install phases connect only to the relevant Rancher nodes. The inventory uses the resolved `ssh_ip`/node IP as the connection target and keeps the operational node name in pyinfra host data. This allows bastion DNS/hosts/proxy setup to run before the rest of the local cluster is reachable through bastion. If `prom1` and Rancher nodes live only on the local/customer VLAN, include both `prometheus` and `rancher` in `ssh.bastion_proxy_roles`.

## Local Infra Addressing

The local cluster VLAN is normally a `/28`:

```text
.1   gateway
.4   bastion1
.5   reserved
.6   prom1
.11  rancher1
.12  rancher2
.13  rancher3
```

The example defines three Rancher nodes through `local.rancher_nodes`; increase `count` for larger local clusters. If you need `rancher1-5`, use a subnet large enough for the selected host offsets; in `/28`, `.15` is broadcast, so `.11-.15` is not valid.

`bastion1` has a static IP on its primary/customer NIC and should use a static IP on the secondary management NIC for SSH. `prom1` and Rancher nodes also use static customer VLAN IPs. Terraform sets static IPs with vSphere clone customization, not cloud-init. DNS records are generated into dnsmasq from the same inventory; DHCP does not need to learn fixed Rancher nodes from leases.

For static management addresses outside the local VLAN, use `cidr` directly on the NIC:

```yaml
nodes:
  bastion1:
    host: 4
    nics:
      - network: customer
      - network: management
        cidr: 192.0.2.10/24
```

The loader expands that NIC to `ip`/`prefix` for Terraform and uses the same IP as the generated SSH target for `bastion1`, without repeating it as `ssh_ip`.

vSphere clone customization applies static NIC addressing during VM clone/provisioning. Adding or changing `nics[].cidr` on an already-created VM may update Terraform/vSphere customization metadata but does not reliably reconfigure the guest OS network. For existing VMs, either recreate the VM or adjust the NetworkManager profile in the guest manually/through pyinfra, then keep `env.yaml` aligned for the next redeploy.

dnsmasq uses `no-dhcp-interface=<management-device>` and `bind-dynamic`, so it may provide DNS on the management NIC but never DHCP. The loader derives that device from `bastion.vsphere_route_connection`: it uses the connection directly when it is a device name, or the source device in `bastion.network_connection_names` when the route connection is a renamed NetworkManager profile.

vSphere clone customization gives local nodes DNS servers derived from `local.vlan.dns_nodes`, normally `bastion1`. `nodes.bastion1.dns_servers` is required and supplies the separate management/vSphere DNS used by the bastion OS and Squid. Set `bastion.dnsmasq_upstream_servers` to the DNS resolvers that local clients may use through dnsmasq. dnsmasq renders `no-resolv` and explicit `server=` entries, so it never exposes the bastion's `/etc/resolv.conf` DNS to local clients.

vSphere VM object names are made globally unique by Terraform with a stable random suffix: `<node>-xxxxx-xxxxx`. The node key still stays the operational hostname, so guest hostnames, SSH aliases, DNS records, and pyinfra groups remain `bastion1`, `prom1`, `rancher1`, and so on. Terraform outputs include `vsphere_name` for mapping the operational node name to the actual vSphere object name.

Do not repeat the first octets of local IPs in every node. Define the local VLAN once, then use host offsets:

```yaml
rancher_url: rancher.example.internal

local:
  vlan:
    cidr: 10.14.17.0/28
    gateway_host: 1
  rancher_nodes:
    name_prefix: rancher
    count: 3
    start_host: 11
    template: rke2
    cpu: 4
    memory_mb: 16384
    disk_gb: 100
    nics:
      - network: customer

nodes:
  bastion1:
    host: 4

bastion:
  service_node: bastion1
```

The shared env loader derives `domain` from `rancher_url`, defaults `local.vlan.dns_nodes` to `bastion.service_node`, expands the Rancher node pool into concrete nodes like `rancher1`, `rancher2`, and `rancher3`, then expands host offsets into concrete IPs for both Terraform and pyinfra.
Host offsets are validated against the CIDR and may not resolve to the network or broadcast address.
Named references are validated too: node templates must exist, NIC networks must exist, `local.vlan.dns_nodes` must exist if explicitly set, `bastion.service_node` must have `role: bastion`, and `rke2.primary_node` must have `role: rancher`.

The bastion `/etc/hosts` template renders local node records and Rancher URL round-robin records for every node with `role: rancher`. Downstream ingress RR records live on downstream subnets and are intentionally out of scope for this local management-cluster scaffold.

`bastion.vsphere_route_connection` can be either a NetworkManager connection profile name or a device name such as `ens224`; the bastion phase resolves device names to the active profile before running `nmcli con mod`.

If VMware customization leaves unclear NetworkManager profile names, optionally rename them during the bastion phase:

```yaml
bastion:
  network_connection_names:
    ens192: local
    ens224: mgmt
  vsphere_route_connection: mgmt
```

The map keys are current device names or current profile names, and values are target profile names. This keeps the base interfaces readable as `local`/`mgmt`, while downstream VLAN interfaces can still be named `vlanXXX`.

## Proxy

Proxy files follow the production pattern: `HTTP_PROXY`/`HTTPS_PROXY` point at `bastion.service_ip:3128`, and `NO_PROXY` defaults to private CIDRs plus the local VLAN CIDR and Rancher URL. Add site-specific values under `proxy.extra_no_proxy` only when needed. Override `proxy.no_proxy_cidrs` only if the private-CIDR default is wrong for the environment.

## Hostnames

`make node-prep` sets local node hostnames to `<node>.<rancher_url>`, including `bastion1`, `prom1`, and all Rancher nodes.

It also renders `/etc/profile.d/prompt.sh`. The prompt suffix is always `environment.id`; prompt colors have defaults and are the only prompt-specific settings:

```yaml
schema_version: 1
environment:
  id: test.elo

prompt:
  colors:
    host: 129
```

## RKE2 Prep

For Rancher nodes, `make node-prep` renders these managed files:

```text
/etc/NetworkManager/conf.d/rke2-canal.conf
/etc/default/rke2-server
/etc/profile.d/proxy.sh
/etc/rancher/rke2/config.yaml
```

The primary node defaults to the first expanded Rancher node and gets a config without `server`; join nodes get `server: https://<rancher1-ip>:9345`. `rke2.token_file` defaults to `/etc/rancher/rke2/token`, `selinux` defaults to `true`, and `make rke2-install` runs the primary node phase first, then the join-node phase.

## Rancher Edition

Rancher edition selection and Helm chart repositories are environment data. Define both editions, then select the one to install:

```yaml
rancher:
  edition: community
  cert_manager_version: v1.21.1
  editions:
    community:
      repo_name: rancher-stable
      repo_url: https://releases.rancher.com/server-charts/stable
      version: 2.14.4
    prime:
      repo_name: rancher-prime
      repo_url: https://charts.rancher.com/server-charts/prime
      version: 2.14.4
```

For Rancher Prime, set `edition: prime` in the instance config and fill the Prime chart repository/version approved for that customer. The env loader resolves the selected edition into the values expected by the install script.
`agent_tls_mode` defaults to `system-store`. `rke2.version`, `rancher.cert_manager_version`, and the selected Rancher edition `version` are required; the environment config is the only version source of truth.

Set `rancher.bootstrap_password` only in instance configs when you want to control the one-time initial admin password. The install script uses it only when the Rancher Helm release does not exist yet; repeat runs and upgrades never pass `bootstrapPassword` again. When it is omitted, each successful `make rancher-install` prints a command that retrieves the generated password from `cattle-system/bootstrap-secret` if this was the first Rancher release. Change the password after first login.

`rinstall` installs cert-manager and Rancher only when their Helm releases are absent. An existing release must match the declared chart version; Rancher must also match the declared hostname, proxy, and no-proxy values. Any mismatch fails without an upgrade or downgrade, because Rancher and cert-manager lifecycle changes belong to the separate Rancher Environment repository. Synchronize the DR environment pins after those lifecycle changes.

## Source Of Truth

Edit only the committed `config.yaml` in an instance repository, or
`envs/<env>/env.yaml` in standalone engine mode. Every config requires
`schema_version: 1` and an immutable `environment.id`. Generated artifacts live
under `.rinstall/` for instances and `build/<environment.id>/` in standalone
mode. Do not edit generated files.

Use `envs/example` only for sanitized engine development fixtures. Real customer
configuration belongs in the separate instance repository, keeping hostnames,
IPs, and SSH topology out of this engine repository.

## Terraform State

Production instances use the static `backend "http" {}` declaration in the
pinned engine and GitLab state settings from `config.yaml`. Do not put GitLab
tokens in `config.yaml`; provide `TF_HTTP_USERNAME` and `TF_HTTP_PASSWORD` at
runtime.


## Secrets

Do not commit credentials in generated var files, backend config files with secrets, generated node files, kubeconfigs, Rancher tokens, or `.envrc`. Prefer environment variables, Bitwarden, or one-shot bootstrap scripts for secrets that should not land in Terraform state.

For scaffold/test environments, `rke2.token` may be placed directly in `env.yaml`; `make node-prep` writes it to `rke2.token_file` on Rancher nodes. For production, prefer omitting `rke2.token` and populating `rke2.token_file` from the approved secret source. `rke2.version` is required and pins the release installed by `get.rke2.io`; a rerun fails if an installed RKE2 version differs from the requested pin. RKE2 `tls-san` defaults to `rancher_url` to avoid hostname typos.
