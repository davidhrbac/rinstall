# Agent Notes

- This repo is a scaffold for manually operated Rancher environment provisioning on vSphere.
- This repo is a Day-0/DR bootstrap engine only: vSphere infrastructure, bastion, RKE2, and initial Rancher installation.
- Do not add Rancher API resources, Fleet configuration, downstream cluster lifecycle, or Rancher/Kubernetes upgrades here; manage them outside rinstall in the separate per-environment Rancher Terraform project.
- Production configuration lives in a separate instance repository. Each instance repository contains `config.yaml` and a pinned `rinstall` Git submodule.
- The pinned `rinstall` submodule is the Terraform engine and root: Terraform runs directly from `rinstall/terraform/infra` on the operator workstation, not from `bastion1`; pyinfra/Helm steps run against provisioned hosts over SSH after infra exists.
- `.rinstall/` contains only per-instance runtime and generated data, including `infra.tfvars.json`, SSH artifacts, kubeconfigs, logs, and Terraform's `TF_DATA_DIR` under `.rinstall/terraform-data`.
- `envs/example` is only a development/test/rendering fixture; it is not a standalone production provisioning environment. Keep real customer/internal hostnames, IPs, and SSH topology names in the separate instance repository.
- Prefer `ssh.jump_host: <existing SSH config alias>` in instance configs; keep upstream SSH details in the operator's `~/.ssh/config`, not in this repo.
- Use `make ssh-config ENV=<env>` to generate `build/<environment.id>/ssh_config` without running pyinfra.
- Use `make admin-ssh-config ENV=<env>` to generate `build/<environment.id>/<environment.id>.conf` for an admin jump host. `make install-admin-ssh-config ENV=<env>` may upload that fragment to `/root/.ssh/config.d/` through `ssh.jump_host`, but must never modify `/root/.ssh/config` or add its `Include` directive.
- Prefer static addressing on `bastion1` management NIC using `nics[].cidr`; `lib/env_config.py` derives `nodes.bastion1.ssh_ip` from that management NIC IP for generated SSH config.
- Static `nics[].cidr` values are vSphere clone customization inputs; changing them after VM creation may not reconfigure guest networking. Recreate the VM or adjust NetworkManager in-guest, then test on fresh redeploy.
- If `ssh.jump_host` is set, generated SSH config includes `~/.ssh/config`; target host entries use `ProxyCommand` for pyinfra compatibility. `bastion1` proxies through `<jump_host>`, and local-only nodes proxy through `<jump_host>` then bastion when their roles are listed in `bastion_proxy_roles`, typically `prometheus` and `rancher`.
- pyinfra inventory is phase-aware: bastion/Rancher Helm/bootstrap phases connect only to bastion, RKE2 phases only to relevant Rancher nodes, and node-prep to all local nodes. Inventory connection targets use resolved `ssh_ip`/node IP while operational node names stay in host data.
- In production, instance `config.yaml` is the configuration source of truth; generated `infra.tfvars.json` and other runtime artifacts should not be edited.
- Environment configs require immutable `environment.id` for artifact/runtime isolation and `schema_version: 1`; do not infer stable identity only from `$(notdir $(ENV))`. `environment.id` is the canonical environment suffix: derive shell prompt suffixes, administrator SSH aliases, generated artifact paths, and per-environment SSH fragment names from it rather than configuring each independently.
- Prefer `allow_unverified_ssl: false` for vSphere. Any insecure TLS override must be explicit and justified in an instance config.
- RKE2, Rancher, and cert-manager versions are required environment-config values. Do not introduce fallback versions across pyinfra and shell scripts.
- Production Terraform state is GitLab-managed HTTP state. Non-secret GitLab backend metadata is declared in instance `config.yaml`; rinstall derives the GitLab backend URLs and uses the static HTTP backend in the pinned Terraform root. Credentials remain runtime-only.
- Do not add a `make infra-destroy`/`make destroy-all` shortcut; `make destroy-commands` may print explicit `terraform plan -destroy` and `terraform destroy` commands so destructive infra removal stays deliberate.
- Do not put vCenter credentials or GitLab backend tokens in `env.yaml`; use `.envrc`/environment variables such as `TF_VAR_vsphere_server`, `TF_VAR_vsphere_user`, `TF_VAR_vsphere_password`, `TF_HTTP_USERNAME`, and `TF_HTTP_PASSWORD`.
- Local VLAN addressing in `env.yaml` uses `local.vlan.cidr` plus node `host` offsets; `domain` defaults from `rancher_url`, `local.vlan.dns_nodes` defaults to `bastion.service_node`, and offsets/references are validated by `lib/env_config.py`.
- Identical local Rancher VMs should be defined with `local.rancher_nodes` (`name_prefix`, `count`, `start_host`, sizing, NIC template); `lib/env_config.py` expands them into concrete `role: rancher` nodes.
- Bastion `/etc/hosts` is rendered from `env.yaml`: local node records and Rancher URL round-robin to every node with `role: rancher`.
- Do not add downstream ingress RR records, such as `.40-.62` test aliases, to the local management-cluster DNS model; those belong to downstream subnet automation later.
- Proxy templates should keep `NO_PROXY` compact: private CIDRs, Kubernetes service DNS suffixes, `local.vlan.cidr`, Rancher URL, plus only explicit `proxy.extra_no_proxy` values.
- Use `make -f rinstall/Makefile infra-plan` from an instance repository as the review checkpoint, then `make -f rinstall/Makefile provision-all` to confirm, apply infra, run bastion/node/RKE2/Rancher install phases, and print timing summary. Use the `-yes` target only when the apply has already been reviewed and noninteractive execution is intended.
- `provision-all` writes full phase output to a private `.rinstall/provision-<timestamp>-<pid>.log` through a pseudo-terminal, preserving colors in both the terminal and log.
- Provision headers/logs record the pinned engine and instance-repository Git revisions plus clean/dirty worktree state.
- Set `PYINFRA_PROGRESS=off` by default for readable terminal transcripts and logs; it disables only pyinfra's redraw spinner, not its colors or operation output.
- Provision/destroy command headers may print `TF_VAR_vsphere_server` and `TF_VAR_vsphere_user` for operator confirmation; never print `TF_VAR_vsphere_password`.
- Use `make verify` for unit tests, syntax/format checks, and Terraform initialization/validation with `-backend=false`; it does not contact vSphere or Rancher.
- Do not commit real `*.auto.tfvars`, kubeconfigs, Rancher tokens, or RKE2 token files; `rke2.token` in committed examples must be dummy/test-only.
- Avoid `webfetch` when possible; prefer local/repo sources or CLI tools.
- Use `~/go/bin/gh` for GitHub tasks and `~/go/bin/glab` for GitLab tasks instead of assuming they are on `PATH`.
- For ChatGPT links, use the internal API rather than fetching them directly.

## Rancher Environment Workflow

- Inputs normally known before provisioning: customer VLAN, datastore, resource pool, VM folder, Rancher URL, bastion/prom template, and local Rancher/RKE2 VM template.
- Local cluster VLAN is usually `/28`: `.1` gateway, `.4` `bastion1`, `.5` reserved, `.6` `prom1`, `.11` `rancher1`, `.12` `rancher2`, `.13` `rancher3`.
- Use VM template 1 for `bastion1` and `prom1`; use VM template 2 for local Rancher/RKE2 VMs and downstream cluster VMs.
- vSphere VM object names must be unique; Terraform appends a stable random suffix as `<node>-xxxxx-xxxxx`, while guest hostname/DNS/SSH aliases stay as the unsuffixed node key.
- `bastion1` primary interface is on the customer VLAN and has a static IP; secondary interface is on the management VLAN and gets DHCP.
- `nodes.bastion1.dns_servers` is required management/vSphere DNS for bastion OS, Squid, and clone customization. Local nodes default to `local.vlan.dns_nodes`, normally bastion; `bastion.dnsmasq_upstream_servers` is a separate required list rendered as dnsmasq `server=` entries with `no-resolv`, so local clients do not inherit bastion management DNS.
- Set static IPs for `bastion1`, `prom1`, and Rancher nodes with Terraform/vSphere clone customization; do not require DHCP or cloud-init for these fixed local customer-VLAN addresses.
- Keep bastion customer-facing `service_ip` explicit because `dnsmasq` and `squid` should use it, not the dynamic management address.
- `bastion1` runs `dnsmasq` for DHCP/DNS and `squid` so Rancher/local nodes can reach vSphere.
- Optionally use `bastion.network_connection_names` to rename NetworkManager profiles on bastion, for example `ens192: local` and `ens224: mgmt`; downstream VLAN profiles can stay named `vlanXXX`.
- Add the vSphere route on bastion from `bastion.vsphere_route` using `bastion.vsphere_route_connection`; this may be a NetworkManager connection profile name or device name. Keep real route values in instance config, not committed examples.
- dnsmasq derives the known management device from `bastion.vsphere_route_connection`: use the direct device name or resolve the source device through `bastion.network_connection_names` when the route connection is a renamed NetworkManager profile. It renders `bind-dynamic` and `no-dhcp-interface=<management_device>` so management remains DNS-only.
- DHCP reservations are needed for fixed local nodes only if choosing DHCP over Terraform static customization; account for the MAC-address chicken/egg when designing provisioning.
- After `bastion1`, `prom1`, and Rancher nodes exist, run `make node-prep` before RKE2.
- `make node-prep` sets local node hostnames to `<node>.<rancher_url>` with `hostnamectl` and renders `/etc/profile.d/prompt.sh`; prompt colors come from `env.yaml` `prompt` and its suffix is `environment.id`.
- `make node-prep` copies `files/rke2-canal.conf` to `/etc/NetworkManager/conf.d/`, renders `/etc/default/rke2-server`, `/etc/profile.d/proxy.sh`, and `/etc/rancher/rke2/config.yaml`.
- `make node-prep` renders `/etc/profile.d/rke2.sh` on Rancher nodes so root shells get RKE2 `PATH`, `KUBECONFIG`, `CRI_CONFIG_FILE`, `k` alias, and kubectl/crictl Bash completion.
- If `rke2.token` is present in `env.yaml`, `make node-prep` writes it to `rke2.token_file`; use only dummy tokens in committed examples and prefer secret-source population for production.
- RKE2 config uses `token-file`, `selinux: true`, `tls-san` defaulted from `rancher_url`; only non-primary Rancher nodes get `server: https://<rancher1-ip>:9345`.
- `rke2.version` is required and passed to `get.rke2.io` as `INSTALL_RKE2_VERSION`. Existing nodes must already match the pin; this repo does not use reruns to upgrade or downgrade RKE2.
- `make rke2-install` runs two pyinfra phases: install/enable `rke2-server --now` on `rke2.primary_node` first, then on all other Rancher join nodes.
- RKE2 install disables Rancher RKE2 package repositories after installation because RKE2 is not upgraded through OS package updates.
- After RKE2 is ready, install `asdf` as a binary on `bastion1`, install Helm and kubectl through asdf for install/diagnostics, configure Helm repos, install cert-manager, then install Rancher.
- Rancher install/bootstrap fetch primary node `/etc/rancher/rke2/rke2.yaml`, rewrite the API endpoint to the primary node IP, write `.rinstall/rke2.yaml`, and upload it to `bastion1:/root/rke2.yaml`; `make -f rinstall/Makefile rke2-kubeconfig` is a helper/debug target for that step.
- Rancher edition is selected by `rancher.edition` (`community` or `prime`); Helm repo/version live under `rancher.editions.<edition>` as `repo_name`, `repo_url`, and `version`, then are resolved by `lib/env_config.py` for install.
- Rancher Helm install receives `proxy` from bastion Squid and `noProxy` from generated `proxy.no_proxy`; this is separate from OS/RKE2 proxy profile rendering.
- Optional `rancher.bootstrap_password` is a one-time initial admin password; keep real values in instance configs only. Install passes it to Helm only when the Rancher release does not exist yet, never on repeat upgrades. If omitted, every successful Rancher install prints a command that retrieves the generated password from `cattle-system/bootstrap-secret` if the release was newly installed.
- Cert-manager and Rancher use Day-0 Helm semantics: install only if absent, no-op only when the declared version matches, and fail on version mismatch. Rancher also fails when hostname/proxy/noProxy values differ; this repo never upgrades, downgrades, or reconfigures existing releases.

## Future Bastion Service Networks

- Do not implement this section until the environment schema is agreed; candidate names are `bastion.service_networks` and `bastion.downstream_networks`.
- A service-network config must define a logical network name, VLAN ID, vSphere portgroup, CIDR, gateway host offset, and DHCP range. It defines bastion network service, not a downstream cluster.
- Terraform must append the corresponding bastion vNIC and output the logical network-to-MAC mapping for pyinfra. Keep existing primary NIC ordering fixed and reject unsafe reorder/removal plans.
- pyinfra must discover the guest device by its Terraform-provided MAC, then render a stable NetworkManager profile, gateway address, and dnsmasq DHCP configuration. Never persist MACs, guest interface names, VM UUIDs, or vSphere MoRefs in `env.yaml`.
- Render NetworkManager and dnsmasq configuration declaratively as complete managed files, not append/patch operations.
- DHCP ranges must be scoped to explicit service interfaces; never use `interface=*` or serve DHCP on the management interface. Enable `dhcp-authoritative` only when dnsmasq serves DHCP exclusively on explicit service interfaces. Omit DHCP option 6 so dnsmasq advertises its own address in the matching VLAN.
- Removing a configured service network must require an explicit safety acknowledgement because it can disconnect existing downstream clusters.
- Instance repositories consume this engine as a pinned `rinstall` Git submodule; generated runtime artifacts remain in the instance repository's `.rinstall/` directory.

## Rancher DNS/TLS

- Use split-horizon DNS for the Rancher URL: external/users/remote downstreams go to F5 VIP, local cluster lookups go through bastion `dnsmasq`.
- For local round-robin DNS, add one `/etc/hosts` record per Rancher node for the Rancher URL, then restart `dnsmasq`.
- In split-horizon setups with different TLS endpoints, prefer Rancher `agent-tls-mode=system-store` over `strict`.
- Rancher Helm `hostname` and Rancher runtime `server-url` are separate; changing only Terraform/Helm hostname is not enough.
- Keep the old Rancher hostname alive during URL migrations, use dual-host ingress/cert SANs temporarily, fix `NO_PROXY`, then update Terraform/Helm last.
