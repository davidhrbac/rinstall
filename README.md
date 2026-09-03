# Rancher Environment Install

Automation scaffold for a manually operated Rancher environment build on vSphere.

The design intentionally separates infrastructure from Rancher API configuration so disaster recovery can restore the base layer before Rancher-dependent resources are reconciled.

## Layers

```text
Terraform infra  -> vSphere VMs, NICs, static IPs where required, VM inventory outputs
pyinfra          -> bastion dnsmasq/squid/routes and rancher node file prep
RKE2 scripts     -> local RKE2 cluster bootstrap
Helm scripts     -> cert-manager and Rancher install from bastion1
Rancher layer    -> downstream clusters and Rancher API resources after Rancher exists
```

## Operator Flow

Run Terraform from the operator workstation, not from `bastion1`. Use a single environment inventory under `envs/`. Start from `envs/example/env.yaml`; generated Terraform var-files go to `build/`.

```bash
make infra-init ENV=envs/example
make render-infra-vars ENV=envs/example
make ssh-config ENV=envs/example
make infra-plan ENV=envs/example
make provision-all ENV=envs/example
```

`make provision-all` asks for confirmation, runs `infra-apply`, configures bastion, prepares nodes, installs RKE2, installs Rancher, and prints a duration summary at the end. `make rancher-install` prepares the RKE2 kubeconfig automatically before the Helm phase. Use `make infra-plan` first as the review checkpoint before applying changes. For unattended runs use `make provision-all-yes ENV=envs/example`; it passes `-auto-approve` to Terraform apply and `--yes` to pyinfra.

`make rancher-install` and `make rancher-bootstrap` automatically fetch `/etc/rancher/rke2/rke2.yaml` from the primary Rancher node, rewrite its Kubernetes API endpoint to the primary node IP, and upload the prepared kubeconfig to `bastion1:/root/rke2.yaml`. The helper target `make rke2-kubeconfig` is available for debugging that step directly.

Rancher Helm install receives `proxy` and `noProxy` values derived from the bastion Squid service IP/port and the generated `proxy.no_proxy` list. `noProxy` includes private CIDRs, Kubernetes service DNS suffixes, the local VLAN CIDR, the Rancher URL, and any explicit `proxy.extra_no_proxy` values. This is separate from the host-level proxy files rendered during node prep.

Prefer static addressing on the bastion management NIC. Set it as `cidr` on the management NIC and the env loader derives `nodes.bastion1.ssh_ip` from that address for generated SSH config.

Terraform commands use local workstation credentials/environment and talk to vSphere/GitLab from there. pyinfra and Helm/Rancher installation steps can also run from the workstation; SSH routing is handled by generated OpenSSH config.

## Destroying Infra

Destroy Terraform-managed vSphere VMs from the operator workstation with the same env and backend/state settings used for creation:

```bash
make destroy-commands ENV=envs/example
```

The helper prints the explicit Terraform commands to run, for example:

```bash
terraform -chdir=terraform/infra plan -destroy -var-file=../../build/example/infra.tfvars.json
terraform -chdir=terraform/infra destroy -var-file=../../build/example/infra.tfvars.json
```

Always confirm `ENV`, Terraform workspace/backend, and the destroy plan before approving. There is intentionally no `make infra-destroy` or `make destroy-all` shortcut, because destroy is destructive and should stay explicit. Terraform destroy only removes resources tracked by the Terraform infra state; it does not clean Rancher API resources, downstream clusters, external DNS/LB records, DHCP reservations, or local generated files under `build/`.

`make destroy-commands` prints a header with the selected env, build directory, Terraform directory, tfvars path, vSphere server/user when available from environment variables, optional backend/init settings, and then the explicit review/destroy commands. It never prints the vSphere password.

Keep vCenter connection details out of `env.yaml` unless there is a specific reason to pin them there. Terraform accepts them through environment variables, which can be loaded by `direnv` from an ignored `.envrc`:

```bash
export TF_VAR_vsphere_server="vcenter.example.internal"
export TF_VAR_vsphere_user="administrator@example.internal"
export TF_VAR_vsphere_password="change-me"
```

See `.envrc.example` for the expected variable names. `make render-infra-vars` omits `vsphere_server` and `vsphere_user` when they are not set in `env.yaml`, so Terraform will read `TF_VAR_vsphere_server` and `TF_VAR_vsphere_user` from the operator environment.

The committed scaffold uses Terraform's default local state, so `make infra-init` works without GitLab backend settings. If an environment should use GitLab Terraform state, copy `terraform/infra/backend.tf.example` to the ignored `terraform/infra/backend.tf` and put GitLab HTTP backend settings in `.envrc` or pass them with `TF_BACKEND_CONFIG=<file>`.

If local nodes require a separate SSH jump host, configure it in `env.yaml`. pyinfra inventory will generate `build/<environment.id>/ssh_config` with per-host proxy rules. `bastion1` goes through the first jump host; local-only nodes can go through the first jump host and then `bastion1`:

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

For administrator access from an existing admin jump host, run `make admin-ssh-config ENV=envs/private/<env>`. It renders `build/<environment.id>/<environment.id>.conf` with aliases such as `bastion1.<environment.id>` and `prom1.<environment.id>`. Configure that host once to include `~/.ssh/config.d/*.conf`, then upload the fragment explicitly:

```bash
make install-admin-ssh-config ENV=envs/private/<env>
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

Set `bastion.management_interface` to the bastion guest management device, such as `ens224`. dnsmasq uses `no-dhcp-interface=<management_interface>` and `bind-dynamic`, so it may provide DNS there but never DHCP. When `bastion.vsphere_route_connection` is already a device name, it is the default management interface; set `management_interface` explicitly when the route connection is a NetworkManager profile name.

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

For Rancher nodes, `make node-prep` mirrors the manual `clush` file copy flow:

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
  editions:
    community:
      repo_name: rancher-stable
      repo_url: https://releases.rancher.com/server-charts/stable
      version: 2.9.2
    prime:
      repo_name: rancher-prime
      repo_url: https://charts.example.invalid/rancher-prime
      version: 2.9.2
```

For Rancher Prime, set `edition: prime` in the private env and fill the Prime chart repository/version approved for that customer. The env loader resolves the selected edition into the values expected by the install script.
`agent_tls_mode` defaults to `system-store`, and `cert_manager_version` defaults to `v1.15.3`.

Set `rancher.bootstrap_password` only in private env configs when you want to control the one-time initial admin password. The install script uses it only when the Rancher Helm release does not exist yet; repeat runs and upgrades never pass `bootstrapPassword` again. Change the password after first login.

## Source Of Truth

Edit only `envs/<env>/env.yaml` for environment data. Every config requires `schema_version: 1` and an immutable `environment.id`. The ID is the canonical suffix for shell prompts and administrator SSH aliases, and it names generated artifacts under `build/<environment.id>/`. `make infra-plan` and `make infra-apply` render `build/<environment.id>/infra.tfvars.json` from that YAML before invoking Terraform. Do not edit generated files under `build/`.

Use `envs/example` only for sanitized examples. Put real customer/internal environments under `envs/private/` or another untracked path if hostnames, IPs, or topology names should not be visible in the repo.

## Terraform State

The committed infra layer defaults to local Terraform state so the scaffold can be initialized and planned without GitLab backend setup.

For environments that need GitLab Terraform state, create an ignored `terraform/infra/backend.tf` from `terraform/infra/backend.tf.example`, then run `make infra-init` with `TF_HTTP_ADDRESS`/`TF_HTTP_LOCK_ADDRESS` environment variables or `TF_BACKEND_CONFIG=<backend-config-file>`. Do not put GitLab tokens in `env.yaml`; provide backend credentials via Terraform-supported environment variables, for example `TF_HTTP_USERNAME` and `TF_HTTP_PASSWORD`.


## Secrets

Do not commit credentials in generated var files, backend config files with secrets, generated node files, kubeconfigs, Rancher tokens, or `.envrc`. Prefer environment variables, Bitwarden, or one-shot bootstrap scripts for secrets that should not land in Terraform state.

For scaffold/test environments, `rke2.token` may be placed directly in `env.yaml`; `make node-prep` writes it to `rke2.token_file` on Rancher nodes. For production, prefer omitting `rke2.token` and populating `rke2.token_file` from the approved secret source. `rke2.version` is required and pins the release installed by `get.rke2.io`; a rerun fails if an installed RKE2 version differs from the requested pin. RKE2 `tls-san` defaults to `rancher_url` to avoid hostname typos.
