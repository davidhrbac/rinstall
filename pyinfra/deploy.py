import os
import shlex
from io import StringIO
from pathlib import Path

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import dnf, files, server, systemd

from lib.bastion_network import (
    dhcp_excluded_interfaces,
    dnsmasq_effective_config_changed,
    downstream_profile_actions,
    downstream_connection_needs_activation,
    profile_rename_needed,
    reconcile_ipv4_routes,
    route_device_is_active,
    route_needs_replacement,
)
from lib.ssh_config import build_dir_for_env


ENGINE_ROOT = Path(__file__).resolve().parents[1]


phase = os.environ.get("PHASE", "bastion")
config = host.data.env_config
node = host.data.node_config
name = host.data.name
role = host.data.role


def rancher_nodes():
    return {
        node_name: node_data
        for node_name, node_data in config["nodes"].items()
        if node_data["role"] == "rancher"
    }


def build_env_dir():
    return build_dir_for_env(os.environ.get("ENV_CONFIG", "envs/example/env.yaml"))


def local_kubeconfig_path():
    return Path.cwd() / build_env_dir() / "rke2.yaml"


def shell_env(values):
    return " ".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())


def command_output(command):
    return host.get_fact(Command, command=command) or ""


def connection_uuid(connection_name):
    quoted = shlex.quote(connection_name)
    return command_output(
        f"nmcli -g UUID connection show {quoted} 2>/dev/null || "
        f"nmcli -g GENERAL.CON-UUID device show {quoted} 2>/dev/null || true"
    ).strip()


def active_connection_id(device):
    return command_output(
        f"nmcli -g GENERAL.CONNECTION device show {shlex.quote(device)} 2>/dev/null || true"
    ).strip()


def connection_profiles():
    profiles = []
    for line in command_output("nmcli -t -f UUID,TYPE,DEVICE connection show").splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            continue
        uuid, profile_type, device = fields
        profiles.append(
            {
                "uuid": uuid,
                "type": profile_type,
                "device": device,
                "interface_name": command_output(
                    f"nmcli -g connection.interface-name connection show uuid {shlex.quote(uuid)} 2>/dev/null || true"
                ),
                "mac_address": command_output(
                    f"nmcli -g 802-3-ethernet.mac-address connection show uuid {shlex.quote(uuid)} 2>/dev/null || true"
                ),
                "autoconnect": command_output(
                    f"nmcli -g connection.autoconnect connection show uuid {shlex.quote(uuid)} 2>/dev/null || true"
                ),
            }
        )
    return profiles


def device_for_mac(mac_address):
    command = (
        f"wanted=$(printf '%s' {shlex.quote(mac_address)} | tr '[:upper:]' '[:lower:]'); "
        "udevadm settle >/dev/null 2>&1 || true; "
        "for attempt in $(seq 1 60); do found=''; duplicate=''; "
        "for path in /sys/class/net/*; do [ -e \"$path/address\" ] || continue; "
        "actual=$(tr '[:upper:]' '[:lower:]' < \"$path/address\"); "
        "if [ \"$actual\" = \"$wanted\" ]; then "
        "[ -z \"$found\" ] || duplicate=${path##*/}; found=${path##*/}; fi; done; "
        "if [ -n \"$duplicate\" ]; then printf 'MAC %s matched multiple devices\\n' \"$wanted\" >&2; exit 1; fi; "
        "if [ -n \"$found\" ]; then printf '%s' \"$found\"; exit 0; fi; "
        "[ \"$attempt\" -eq 60 ] || sleep 1; done; "
        "printf 'Timed out after 60s waiting for provider MAC %s; visible interfaces: ' \"$wanted\" >&2; "
        "first=1; for path in /sys/class/net/*; do [ -e \"$path/address\" ] || continue; "
        "[ \"$first\" -eq 1 ] || printf ', ' >&2; first=0; "
        "printf '%s (%s)' \"${path##*/}\" \"$(tr '[:upper:]' '[:lower:]' < \"$path/address\")\" >&2; done; "
        "printf '\\n' >&2; exit 1"
    )
    return command_output(command).strip()


def disable_rke2_repos():
    server.shell(
        name="Disable RKE2 package repositories",
        commands=[
            "dnf config-manager --set-disable 'rancher-rke2-*' >/dev/null",
        ],
        _if=lambda: bool(host.get_fact(Command, "command -v dnf >/dev/null 2>&1 && dnf -q repolist enabled | grep '^rancher-rke2-' || true")),
    )


def configure_asdf():
    files.template(
        name="Render root asdf shell environment",
        src=str(ENGINE_ROOT / "pyinfra/templates/asdf.sh.j2"),
        dest="/etc/profile.d/asdf.sh",
        mode="0644",
    )

    server.shell(
        name="Install asdf binary",
        commands=[
            "version='v0.20.0'; "
            "case \"$(uname -m)\" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) exit 1 ;; esac; "
            "if ! command -v asdf >/dev/null 2>&1; then "
            "tmpdir=$(mktemp -d); "
            "curl -fsSL \"https://github.com/asdf-vm/asdf/releases/download/${version}/asdf-${version}-linux-${arch}.tar.gz\" -o \"${tmpdir}/asdf.tar.gz\"; "
            "tar -xzf \"${tmpdir}/asdf.tar.gz\" -C \"$tmpdir\"; "
            "install -m 0755 \"${tmpdir}/asdf\" /usr/local/bin/asdf; "
            "rm -rf \"$tmpdir\"; "
            "fi; "
            "mkdir -p /root/.asdf"
        ],
    )

    server.shell(
        name="Install asdf diagnostic tools",
        commands=[
            "export ASDF_DATA_DIR=/root/.asdf; export PATH=\"${ASDF_DATA_DIR}/shims:${PATH}\"; "
            "asdf plugin list | grep -Fx helm >/dev/null || asdf plugin add helm https://github.com/Antiarchitect/asdf-helm.git; "
            "asdf plugin list | grep -Fx kubectl >/dev/null || asdf plugin add kubectl https://github.com/asdf-community/asdf-kubectl.git; "
            "helm_version=$(asdf latest helm); kubectl_version=$(asdf latest kubectl); "
            "asdf install helm \"$helm_version\"; asdf set -u helm \"$helm_version\"; "
            "asdf install kubectl \"$kubectl_version\"; asdf set -u kubectl \"$kubectl_version\"; "
            "asdf reshim helm; asdf reshim kubectl"
        ],
    )

    files.line(
        name="Set root asdf data dir",
        path="/root/.bashrc",
        line="export ASDF_DATA_DIR=/root/.asdf",
        present=True,
    )

    files.line(
        name="Add asdf shims to root PATH",
        path="/root/.bashrc",
        line='export PATH="${ASDF_DATA_DIR:-$HOME/.asdf}/shims:$PATH"',
        present=True,
    )

    files.line(
        name="Enable kubectl completion for root",
        path="/root/.bashrc",
        line="command -v kubectl >/dev/null 2>&1 && source <(kubectl completion bash)",
        present=True,
    )


if phase == "bastion-packages" and role == "bastion":
    dnf.packages(
        name="Install bastion services",
        packages=["dnsmasq", "squid", "NetworkManager"],
        present=True,
    )
    systemd.service(
        name="Enable and start NetworkManager",
        service="NetworkManager",
        running=True,
        enabled=True,
    )


if phase == "bastion" and role == "bastion":
    dnsmasq_dhcp_configs = []
    obsolete_dhcp_configs = []
    dnsmasq_effective_changes = []
    downstream_profiles = []
    downstream_devices = {}
    for downstream in config["bastion"]["downstream_networks"]:
        interface_name = downstream["interface_name"]
        mac_address = host.data.downstream_network_output[interface_name]["mac_address"]
        device = device_for_mac(mac_address)
        downstream_devices[interface_name] = device
        downstream["device_name"] = device
    if config["bastion"]["downstream_networks"]:
        files.directory(
            name="Ensure NetworkManager system connection directory exists",
            path="/etc/NetworkManager/system-connections",
            mode="0700",
            present=True,
        )
        files.directory(
            name="Ensure NetworkManager configuration directory exists",
            path="/etc/NetworkManager/conf.d",
            present=True,
        )

        no_auto_default = files.put(
            name="Disable NetworkManager automatic Ethernet profiles",
            src=StringIO("[main]\nno-auto-default=*\n"),
            dest="/etc/NetworkManager/conf.d/10-rinstall-no-auto-default.conf",
            mode="0644",
        )
        server.shell(
            name="Reload NetworkManager configuration",
            commands=["nmcli general reload conf"],
            _if=no_auto_default.did_change,
        )

    for downstream in config["bastion"]["downstream_networks"]:
        interface_name = downstream["interface_name"]
        device = downstream_devices[interface_name]
        mac_address = host.data.downstream_network_output[interface_name]["mac_address"]
        competing_profiles = downstream_profile_actions(
            connection_profiles(),
            downstream["connection_uuid"],
            mac_address,
            [device],
        )

        competitor_reconciliation = None
        competitor_commands = [
            f"nmcli connection modify uuid {shlex.quote(uuid)} connection.autoconnect no"
            for uuid in competing_profiles["disable"]
        ] + [
            f"nmcli connection down uuid {shlex.quote(uuid)}"
            for uuid in competing_profiles["deactivate"]
        ]
        if competitor_commands:
            competitor_reconciliation = server.shell(
                name=f"Reconcile competing NetworkManager profiles for {interface_name}",
                commands=competitor_commands,
            )

        files.file(
            name=f"Remove obsolete downstream interface naming rule {interface_name}",
            path=f"/etc/systemd/network/10-rinstall-{interface_name}.link",
            present=False,
        )

        profile = files.template(
            name=f"Render NetworkManager profile {interface_name}",
            src=str(ENGINE_ROOT / "pyinfra/templates/downstream-network.nmconnection.j2"),
            dest=f"/etc/NetworkManager/system-connections/rinstall-{interface_name}.nmconnection",
            mode="0600",
            downstream=downstream,
            mac_address=mac_address,
            device_name=device,
        )
        downstream_profiles.append(profile)

    for index, downstream in enumerate(config["bastion"]["downstream_networks"]):
        interface_name = downstream["interface_name"]
        device = downstream_devices[interface_name]
        mac_address = host.data.downstream_network_output[interface_name]["mac_address"]
        current_uuid = command_output(
            f"nmcli -g GENERAL.CON-UUID device show {shlex.quote(device)} 2>/dev/null || true"
        ).strip()
        current_addresses = command_output(
            f"ip -4 -o address show dev {shlex.quote(device)} 2>/dev/null || true"
        )
        activation_needed = downstream_connection_needs_activation(
            current_uuid,
            current_addresses,
            downstream,
        )
        profile = downstream_profiles[index]
        profile_path = f"/etc/NetworkManager/system-connections/rinstall-{interface_name}.nmconnection"
        server.shell(
            name=f"Activate downstream network {interface_name}",
            commands=[
                f"restorecon -F {shlex.quote(profile_path)} 2>/dev/null || true; "
                f"nmcli connection load {shlex.quote(profile_path)}; "
                f"nmcli connection up uuid {shlex.quote(downstream['connection_uuid'])} ifname {shlex.quote(device)}"
            ],
            _if=lambda profile=profile, competitor_reconciliation=competitor_reconciliation, activation_needed=activation_needed: (
                profile.did_change()
                or (competitor_reconciliation is not None and competitor_reconciliation.did_change())
                or activation_needed
            ),
        )

    for source_name, target_name in config["bastion"].get("network_connection_names", {}).items():
        source_uuid = connection_uuid(source_name)
        target_uuid = connection_uuid(target_name)
        rename_needed = profile_rename_needed(
            source_uuid,
            target_uuid,
            source_name,
            target_name,
            active_connection_id(source_name),
        )
        server.shell(
            name=f"Rename NetworkManager connection {source_name} to {target_name}",
            commands=[
                f"nmcli connection modify uuid {shlex.quote(source_uuid)} connection.id {shlex.quote(target_name)}"
            ],
            _if=lambda rename_needed=rename_needed: rename_needed,
        )

    route_connection_name = config["bastion"]["vsphere_route_connection"]
    route_source_names = [
        source
        for source, target in config["bastion"].get("network_connection_names", {}).items()
        if target == route_connection_name
    ]
    route_connection_uuid = connection_uuid(route_connection_name)
    if not route_connection_uuid and route_source_names:
        route_connection_uuid = connection_uuid(route_source_names[0])
    if not route_connection_uuid:
        raise SystemExit(f"cannot resolve NetworkManager route connection {route_connection_name!r}")
    route_device = command_output(
        f"nmcli -g GENERAL.DEVICES connection show uuid {shlex.quote(route_connection_uuid)} 2>/dev/null || true"
    ).strip()
    if not route_device_is_active(route_device):
        raise SystemExit(
            f"NetworkManager route connection {route_connection_name!r} is not active; refusing to activate it"
        )
    desired_route = config["bastion"]["vsphere_route"]
    current_route = command_output(
        f"nmcli -g ipv4.routes connection show uuid {shlex.quote(route_connection_uuid)} 2>/dev/null || true"
    )
    replacement_routes = reconcile_ipv4_routes(current_route, desired_route)
    server.shell(
        name="Configure vSphere route",
        commands=[
            f"nmcli connection modify uuid {shlex.quote(route_connection_uuid)} ipv4.routes {shlex.quote(replacement_routes)}; "
            f"device=$(nmcli -g GENERAL.DEVICES connection show uuid {shlex.quote(route_connection_uuid)}); "
            "[ -n \"$device\" ] && [ \"$device\" != '--' ] || "
            "{ printf 'Route connection became inactive; refusing to activate it\\n' >&2; exit 1; }; "
            "nmcli device reapply \"$device\""
        ],
        _if=lambda: route_needs_replacement(current_route, desired_route),
    )

    dnsmasq_candidate_dir = "/run/rinstall-dnsmasq-candidate"
    dnsmasq_rollback_dir = "/run/rinstall-dnsmasq-rollback"
    server.shell(
        name="Prepare complete dnsmasq candidate",
        commands=[
            f"rm -rf {dnsmasq_candidate_dir}; mkdir -p {dnsmasq_candidate_dir}/dnsmasq.d; "
            f"cp -a /etc/dnsmasq.conf {dnsmasq_candidate_dir}/dnsmasq.conf; "
            f"cp -a /etc/hosts {dnsmasq_candidate_dir}/hosts; "
            f"if [ -d /etc/dnsmasq.d ]; then cp -a /etc/dnsmasq.d/. {dnsmasq_candidate_dir}/dnsmasq.d/; fi; "
            f"sed -i -E 's#^([[:space:]]*conf-dir=)/etc/dnsmasq[.]d#\\1{dnsmasq_candidate_dir}/dnsmasq.d#' "
            f"{dnsmasq_candidate_dir}/dnsmasq.conf"
        ],
    )

    dnsmasq_binding = files.line(
        name="Disable mutually exclusive dnsmasq static binding",
        path=f"{dnsmasq_candidate_dir}/dnsmasq.conf",
        line=r"^bind-interfaces$",
        present=False,
    )

    dnsmasq_loopback_interface = files.line(
        name="Disable loopback-only dnsmasq interface restriction",
        path=f"{dnsmasq_candidate_dir}/dnsmasq.conf",
        line=r"^interface=lo$",
        present=False,
    )

    hosts_config = files.template(
        name="Render /etc/hosts DNS records",
        src=str(ENGINE_ROOT / "pyinfra/templates/hosts.j2"),
        dest=f"{dnsmasq_candidate_dir}/hosts",
        mode="0644",
        config=config,
        rancher_nodes=rancher_nodes(),
    )

    dnsmasq_local_config = files.template(
        name="Render dnsmasq local config",
        src=str(ENGINE_ROOT / "pyinfra/templates/dnsmasq-local.conf.j2"),
        dest=f"{dnsmasq_candidate_dir}/dnsmasq.d/10-rancher-local.conf",
        mode="0644",
        config=config,
    )

    obsolete_dhcp_configs.append(
        files.file(
            name="Remove obsolete aggregate dnsmasq DHCP config",
            path=f"{dnsmasq_candidate_dir}/dnsmasq.d/20-local-dhcp.conf",
            present=False,
        )
    )

    for downstream in config["bastion"]["downstream_networks"]:
        interface_name = downstream["interface_name"]
        device = downstream_devices[interface_name]
        dnsmasq_dhcp_configs.append(
            files.template(
                name=f"Render dnsmasq DHCP config {interface_name}",
                src=str(ENGINE_ROOT / "pyinfra/templates/dnsmasq-dhcp.conf.j2"),
                dest=f"{dnsmasq_candidate_dir}/dnsmasq.d/dnsmasq-{interface_name}.conf",
                mode="0644",
                config=config,
                network=downstream,
            )
        )

    if config["bastion"]["downstream_networks"]:
        excluded_interfaces = dhcp_excluded_interfaces(
            command_output("nmcli -t -f DEVICE,TYPE device status"), downstream_devices.values()
        )
        dnsmasq_dhcp_configs.append(
            files.template(
                name="Render common dnsmasq DHCP policy",
                src=str(ENGINE_ROOT / "pyinfra/templates/dnsmasq-dhcp-policy.conf.j2"),
                dest=f"{dnsmasq_candidate_dir}/dnsmasq.d/20-rinstall-dhcp.conf",
                mode="0644",
                excluded_interfaces=excluded_interfaces,
            )
        )

    stale_dhcp_configs = []
    desired_dhcp_paths = {
        f"/etc/dnsmasq.d/dnsmasq-{downstream['interface_name']}.conf"
        for downstream in config["bastion"]["downstream_networks"]
    }
    for path in command_output(
        "for path in /etc/dnsmasq.d/dnsmasq-vlan*.conf; do "
        "if [ -e \"$path\" ]; then printf '%s\\n' \"$path\"; fi; done"
    ).splitlines():
        if path not in desired_dhcp_paths:
            stale_dhcp_configs.append(
                files.file(
                    name=f"Remove obsolete candidate dnsmasq DHCP config {Path(path).name}",
                    path=f"{dnsmasq_candidate_dir}/dnsmasq.d/{Path(path).name}",
                    present=False,
                )
            )

    dnsmasq_effective_changes.extend(
        [
            dnsmasq_binding,
            dnsmasq_loopback_interface,
            hosts_config,
            dnsmasq_local_config,
            *obsolete_dhcp_configs,
            *dnsmasq_dhcp_configs,
            *stale_dhcp_configs,
        ]
    )

    dnsmasq_validation = server.shell(
        name="Validate changed dnsmasq configuration",
        commands=[
            f"hosts_args='--no-hosts --addn-hosts={dnsmasq_candidate_dir}/hosts'; "
            f"if grep -Eq '^[[:space:]]*no-hosts([[:space:]]|$)' {dnsmasq_candidate_dir}/dnsmasq.conf; then hosts_args=''; fi; "
            f"dnsmasq --test --conf-file={dnsmasq_candidate_dir}/dnsmasq.conf $hosts_args; status=$?; "
            f"if [ \"$status\" -ne 0 ]; then rm -rf {dnsmasq_candidate_dir}; "
            "printf 'dnsmasq candidate validation failed; live configuration was not changed\n' >&2; exit $status; fi"
        ],
        _if=lambda: dnsmasq_effective_config_changed(dnsmasq_effective_changes),
    )

    dnsmasq_install = server.shell(
        name="Install validated dnsmasq configuration and restart service",
        commands=[
            f"set -eu; rm -rf {dnsmasq_rollback_dir}; mkdir -p {dnsmasq_rollback_dir}/dhcp; "
            "atomic_replace() { "
            "src=$1; dest=$2; dir=$(dirname -- \"$dest\"); "
            "tmp=$(mktemp --tmpdir=\"$dir\" .rinstall-dnsmasq.XXXXXX); "
            "if ! cp -a -- \"$src\" \"$tmp\"; then rm -f -- \"$tmp\"; return 1; fi; "
            "if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then "
            "if [ -e \"$dest\" ]; then "
            "if ! chcon --reference=\"$dest\" \"$tmp\"; then rm -f -- \"$tmp\"; return 1; fi; "
            "elif command -v restorecon >/dev/null 2>&1; then "
            "if ! restorecon -F \"$tmp\"; then rm -f -- \"$tmp\"; return 1; fi; fi; fi; "
            "if ! sync -f \"$tmp\"; then rm -f -- \"$tmp\"; return 1; fi; "
            "if ! mv -f -- \"$tmp\" \"$dest\"; then rm -f -- \"$tmp\"; return 1; fi; "
            "if ! sync -f \"$dir\"; then return 1; fi; "
            "}; "
            "for path in /etc/dnsmasq.conf /etc/hosts "
            "/etc/dnsmasq.d/10-rancher-local.conf /etc/dnsmasq.d/20-local-dhcp.conf "
            "/etc/dnsmasq.d/20-rinstall-dhcp.conf; do "
            f"name=$(basename \"$path\"); if [ -e \"$path\" ]; then cp -a \"$path\" {dnsmasq_rollback_dir}/$name; "
            f"else : > {dnsmasq_rollback_dir}/$name.absent; fi; done; "
            "for path in /etc/dnsmasq.d/dnsmasq-vlan*.conf; do "
            f"[ -e \"$path\" ] || continue; cp -a \"$path\" {dnsmasq_rollback_dir}/dhcp/$(basename \"$path\"); done; "
            "was_active=0; if systemctl is-active --quiet dnsmasq; then was_active=1; fi; "
            "was_enabled=0; if systemctl is-enabled --quiet dnsmasq; then was_enabled=1; fi; "
            "rollback() { "
            "for path in /etc/dnsmasq.conf /etc/hosts /etc/dnsmasq.d/10-rancher-local.conf /etc/dnsmasq.d/20-local-dhcp.conf /etc/dnsmasq.d/20-rinstall-dhcp.conf; do "
            f"name=$(basename \"$path\"); if [ -e {dnsmasq_rollback_dir}/$name.absent ]; then rm -f \"$path\"; elif [ -e {dnsmasq_rollback_dir}/$name ]; then atomic_replace {dnsmasq_rollback_dir}/$name \"$path\" || true; fi; done; "
            f"rm -f /etc/dnsmasq.d/dnsmasq-vlan*.conf; for path in {dnsmasq_rollback_dir}/dhcp/*.conf; do [ -e \"$path\" ] || continue; atomic_replace \"$path\" /etc/dnsmasq.d/$(basename \"$path\") || true; done; "
            f"if [ \"$was_active\" -eq 1 ]; then systemctl restart dnsmasq || true; else systemctl stop dnsmasq || true; fi; "
            f"if [ \"$was_enabled\" -eq 1 ]; then systemctl enable dnsmasq || true; else systemctl disable dnsmasq || true; fi; }}; trap rollback 0; "
            f"sed -i -E 's#^([[:space:]]*conf-dir=){dnsmasq_candidate_dir}/dnsmasq.d#\\1/etc/dnsmasq.d#' {dnsmasq_candidate_dir}/dnsmasq.conf; "
            f"atomic_replace {dnsmasq_candidate_dir}/dnsmasq.conf /etc/dnsmasq.conf; "
            f"atomic_replace {dnsmasq_candidate_dir}/hosts /etc/hosts; "
            f"atomic_replace {dnsmasq_candidate_dir}/dnsmasq.d/10-rancher-local.conf /etc/dnsmasq.d/10-rancher-local.conf; "
            f"rm -f /etc/dnsmasq.d/20-local-dhcp.conf /etc/dnsmasq.d/dnsmasq-vlan*.conf; "
            f"if [ -e {dnsmasq_candidate_dir}/dnsmasq.d/20-rinstall-dhcp.conf ]; then atomic_replace {dnsmasq_candidate_dir}/dnsmasq.d/20-rinstall-dhcp.conf /etc/dnsmasq.d/20-rinstall-dhcp.conf; else rm -f /etc/dnsmasq.d/20-rinstall-dhcp.conf; fi; "
            f"for path in {dnsmasq_candidate_dir}/dnsmasq.d/dnsmasq-vlan*.conf; do [ -e \"$path\" ] || continue; atomic_replace \"$path\" /etc/dnsmasq.d/$(basename \"$path\"); done; "
            "if ! systemctl enable dnsmasq || ! systemctl start dnsmasq || ! systemctl restart dnsmasq; then "
            "printf 'dnsmasq restart failed; previous live configuration was restored\n' >&2; exit 1; fi; "
            "trap - 0; "
            f"rm -rf {dnsmasq_rollback_dir} {dnsmasq_candidate_dir}"
        ],
        _if=lambda: (
            dnsmasq_effective_config_changed(dnsmasq_effective_changes)
            and dnsmasq_validation.did_change()
        ),
    )

    server.shell(
        name="Discard unchanged dnsmasq candidate",
        commands=[f"rm -rf {dnsmasq_candidate_dir}"],
        _if=lambda: not dnsmasq_effective_config_changed(dnsmasq_effective_changes),
    )

    systemd.service(
        name="Enable and start dnsmasq",
        service="dnsmasq",
        running=True,
        enabled=True,
        _if=lambda: not dnsmasq_effective_config_changed(dnsmasq_effective_changes),
    )

    systemd.service(
        name="Enable and start squid",
        service="squid",
        running=True,
        enabled=True,
    )

if phase == "node-prep":
    server.hostname(
        name="Set local node hostname",
        hostname=f"{name}.{config['rancher_url']}",
    )

    files.template(
        name="Render shell prompt",
                src=str(ENGINE_ROOT / "pyinfra/templates/prompt.sh.j2"),
        dest="/etc/profile.d/prompt.sh",
        mode="0644",
        config=config,
    )

if phase == "node-prep" and role == "rancher":

    files.directory(
        name="Ensure NetworkManager config dir exists",
        path="/etc/NetworkManager/conf.d",
        present=True,
    )

    files.put(
        name="Copy RKE2 Canal NetworkManager config",
                src=str(ENGINE_ROOT / "files/rke2-canal.conf"),
        dest="/etc/NetworkManager/conf.d/rke2-canal.conf",
        mode="0644",
    )

    files.directory(
        name="Ensure RKE2 config dir exists",
        path="/etc/rancher/rke2",
        present=True,
    )

    if config["rke2"].get("token"):
        files.put(
            name="Write RKE2 token",
            dest=config["rke2"]["token_file"],
            src=StringIO(config["rke2"]["token"]),
            mode="0600",
            user="root",
            group="root",
        )

    files.template(
        name="Render RKE2 config",
            src=str(ENGINE_ROOT / "pyinfra/templates/rke2-config.yaml.j2"),
        dest="/etc/rancher/rke2/config.yaml",
        mode="0600",
        config=config,
        node=node,
        node_name=name,
    )

    files.template(
        name="Render proxy environment",
            src=str(ENGINE_ROOT / "pyinfra/templates/proxy.sh.j2"),
        dest="/etc/profile.d/proxy.sh",
        mode="0644",
        config=config,
    )

    files.template(
        name="Render RKE2 shell environment",
            src=str(ENGINE_ROOT / "pyinfra/templates/rke2.sh.j2"),
        dest="/etc/profile.d/rke2.sh",
        mode="0644",
    )

    files.template(
        name="Render RKE2 service proxy environment",
            src=str(ENGINE_ROOT / "pyinfra/templates/rke2-server.env.j2"),
        dest="/etc/default/rke2-server",
        mode="0644",
        config=config,
    )

if phase == "rke2-install-primary" and role == "rancher" and name == config["rke2"]["primary_node"]:
    files.put(
        name="Upload RKE2 install script on primary",
        src=str(ENGINE_ROOT / "scripts/install-rke2.sh"),
        dest="/tmp/install-rke2.sh",
        mode="0700",
    )

    server.shell(
        name="Install or start RKE2 primary server",
        commands=[shell_env({"RKE2_VERSION": config["rke2"]["version"]}) + " /tmp/install-rke2.sh"],
    )

    disable_rke2_repos()

if phase == "rke2-kubeconfig" and role == "rancher" and name == config["rke2"]["primary_node"]:
    files.get(
        name="Fetch RKE2 kubeconfig from primary",
        src="/etc/rancher/rke2/rke2.yaml",
        dest=str(Path.cwd() / build_env_dir() / "rke2.yaml.raw"),
        create_local_dir=True,
        force=True,
    )

if phase == "rke2-install-join" and role == "rancher" and name != config["rke2"]["primary_node"]:
    files.put(
        name="Upload RKE2 install script on join nodes",
        src=str(ENGINE_ROOT / "scripts/install-rke2.sh"),
        dest="/tmp/install-rke2.sh",
        mode="0700",
    )

    server.shell(
        name="Install or start RKE2 join servers",
        commands=[shell_env({"RKE2_VERSION": config["rke2"]["version"]}) + " /tmp/install-rke2.sh"],
    )

    disable_rke2_repos()

if phase == "rancher-install" and role == "bastion":
    dnf.packages(
        name="Install Rancher install dependencies",
        packages=["git", "curl", "tar"],
        present=True,
    )

    configure_asdf()

    files.put(
        name="Upload RKE2 kubeconfig to bastion",
        src=str(local_kubeconfig_path()),
        dest="/root/rke2.yaml",
        mode="0600",
        add_deploy_dir=False,
    )

    files.put(
        name="Upload Rancher install script",
        src=str(ENGINE_ROOT / "scripts/install-rancher.sh"),
        dest="/tmp/install-rancher.sh",
        mode="0700",
    )

    server.shell(
        name="Install or verify cert-manager and Rancher",
        commands=[
            shell_env(
                {
                    "RANCHER_HOSTNAME": config["rancher_url"],
                    "CERT_MANAGER_VERSION": config["rancher"]["cert_manager_version"],
                    "RANCHER_VERSION": config["rancher"]["rancher_chart_version"],
                    "RANCHER_REPO_NAME": config["rancher"]["chart_repo_name"],
                    "RANCHER_REPO_URL": config["rancher"]["chart_repo_url"],
                    "RANCHER_BOOTSTRAP_PASSWORD": config["rancher"].get("bootstrap_password", ""),
                    "RANCHER_PROXY": f"http://{config['bastion']['service_ip']}:{config['bastion']['squid_http_port']}",
                    "RANCHER_NO_PROXY": ",".join(config["proxy"]["no_proxy"]),
                }
            )
            + " /tmp/install-rancher.sh"
        ],
    )

if phase == "rancher-bootstrap" and role == "bastion":
    files.put(
        name="Upload RKE2 kubeconfig to bastion",
        src=str(local_kubeconfig_path()),
        dest="/root/rke2.yaml",
        mode="0600",
        add_deploy_dir=False,
    )

    files.put(
        name="Upload Rancher bootstrap script",
        src=str(ENGINE_ROOT / "scripts/bootstrap-rancher.sh"),
        dest="/tmp/bootstrap-rancher.sh",
        mode="0700",
    )

    server.shell(
        name="Configure Rancher runtime settings",
        commands=[
            "RANCHER_URL='https://{hostname}' AGENT_TLS_MODE='{agent_tls_mode}' /tmp/bootstrap-rancher.sh".format(
                hostname=config["rancher_url"],
                agent_tls_mode=config["rancher"].get("agent_tls_mode", "system-store"),
            )
        ],
    )
