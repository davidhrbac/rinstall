import os
import shlex
from io import StringIO
from pathlib import Path

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import dnf, files, server, systemd
from pyinfra.operations.util import any_changed

from lib.bastion_network import (
    downstream_connection_needs_activation,
    profile_rename_needed,
    reconcile_ipv4_routes,
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


def device_for_mac(mac_address):
    command = (
        f"wanted={shlex.quote(mac_address)}; found=''; "
        "for path in /sys/class/net/*; do "
        "actual=$(tr '[:upper:]' '[:lower:]' < \"$path/address\"); "
        "if [ \"$actual\" = \"$wanted\" ]; then "
        "[ -z \"$found\" ] || { printf 'MAC %s matched multiple devices\\n' \"$wanted\" >&2; exit 1; }; "
        "found=${path##*/}; fi; done; "
        "[ -n \"$found\" ] || { printf 'No device found for provider MAC %s\\n' \"$wanted\" >&2; exit 1; }; "
        "printf '%s' \"$found\""
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


if phase == "bastion" and role == "bastion":
    files.directory(
        name="Ensure dnsmasq config dir exists",
        path="/etc/dnsmasq.d",
        present=True,
    )

    dnsmasq_binding = files.line(
        name="Disable mutually exclusive dnsmasq static binding",
        path="/etc/dnsmasq.conf",
        line="bind-interfaces",
        present=False,
    )

    hosts_config = files.template(
        name="Render /etc/hosts DNS records",
        src=str(ENGINE_ROOT / "pyinfra/templates/hosts.j2"),
        dest="/etc/hosts",
        mode="0644",
        config=config,
        rancher_nodes=rancher_nodes(),
    )

    dnsmasq_local_config = files.template(
        name="Render dnsmasq local config",
        src=str(ENGINE_ROOT / "pyinfra/templates/dnsmasq-local.conf.j2"),
        dest="/etc/dnsmasq.d/10-rancher-local.conf",
        mode="0644",
        config=config,
    )

    dnsmasq_dhcp_config = files.template(
        name="Render dnsmasq DHCP config",
        src=str(ENGINE_ROOT / "pyinfra/templates/dnsmasq-dhcp.conf.j2"),
        dest="/etc/dnsmasq.d/20-local-dhcp.conf",
        mode="0644",
        config=config,
    )

    if config["bastion"]["downstream_networks"]:
        files.directory(
            name="Ensure persistent network naming directory exists",
            path="/etc/systemd/network",
            present=True,
        )
        files.directory(
            name="Ensure NetworkManager system connection directory exists",
            path="/etc/NetworkManager/system-connections",
            mode="0700",
            present=True,
        )

    downstream_links = []
    downstream_profiles = []
    downstream_devices = {}
    for downstream in config["bastion"]["downstream_networks"]:
        interface_name = downstream["interface_name"]
        mac_address = host.data.downstream_network_output[interface_name]["mac_address"]
        device = device_for_mac(mac_address)
        downstream_devices[interface_name] = device

        link = files.template(
            name=f"Persist kernel interface name {interface_name}",
            src=str(ENGINE_ROOT / "pyinfra/templates/downstream-network.link.j2"),
            dest=f"/etc/systemd/network/10-rinstall-{interface_name}.link",
            mode="0644",
            mac_address=mac_address,
            interface_name=interface_name,
        )
        downstream_links.append(link)

        profile = files.template(
            name=f"Render NetworkManager profile {interface_name}",
            src=str(ENGINE_ROOT / "pyinfra/templates/downstream-network.nmconnection.j2"),
            dest=f"/etc/NetworkManager/system-connections/rinstall-{interface_name}.nmconnection",
            mode="0600",
            downstream=downstream,
            mac_address=mac_address,
        )
        downstream_profiles.append(profile)

    if downstream_links:
        server.shell(
            name="Reload persistent network naming rules",
            commands=["udevadm control --reload"],
            _if=any_changed(*downstream_links),
        )

    for index, downstream in enumerate(config["bastion"]["downstream_networks"]):
        interface_name = downstream["interface_name"]
        device = downstream_devices[interface_name]
        mac_address = host.data.downstream_network_output[interface_name]["mac_address"]
        rename = server.shell(
            name=f"Set kernel interface name {interface_name}",
            commands=[
                "if [ -e {target_path} ] && [ \"$(cat {target_path}/address)\" != {mac} ]; then "
                "printf 'Interface %s already belongs to another MAC\\n' {target} >&2; exit 1; fi; "
                "nmcli device disconnect {source} >/dev/null 2>&1 || true; "
                "ip link set dev {source} down; ip link set dev {source} name {target}".format(
                    target_path=shlex.quote(f"/sys/class/net/{interface_name}"),
                    mac=shlex.quote(mac_address),
                    source=shlex.quote(device),
                    target=shlex.quote(interface_name),
                )
            ],
            _if=lambda device=device, interface_name=interface_name: device != interface_name,
        )

        current_uuid = command_output(
            f"nmcli -g GENERAL.CON-UUID device show {shlex.quote(interface_name)} 2>/dev/null || true"
        ).strip()
        current_addresses = command_output(
            f"ip -4 -o address show dev {shlex.quote(interface_name)} 2>/dev/null || true"
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
                f"nmcli connection up uuid {shlex.quote(downstream['connection_uuid'])} ifname {shlex.quote(interface_name)}"
            ],
            _if=lambda profile=profile, rename=rename, activation_needed=activation_needed: (
                profile.did_change() or rename.did_change() or activation_needed
            ),
        )

    for source_name, target_name in config["bastion"].get("network_connection_names", {}).items():
        source_uuid = connection_uuid(source_name)
        target_uuid = connection_uuid(target_name)
        rename_needed = profile_rename_needed(source_uuid, target_uuid, source_name, target_name)
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
            "if [ -n \"$device\" ] && [ \"$device\" != '--' ]; then "
            "nmcli device reapply \"$device\"; else "
            f"nmcli connection up uuid {shlex.quote(route_connection_uuid)}; fi"
        ],
        _if=lambda: route_needs_replacement(current_route, desired_route),
    )

    dnsmasq_validation = server.shell(
        name="Validate changed dnsmasq configuration",
        commands=["dnsmasq --test"],
        _if=any_changed(dnsmasq_binding, hosts_config, dnsmasq_local_config, dnsmasq_dhcp_config),
    )

    systemd.service(
        name="Enable and start dnsmasq",
        service="dnsmasq",
        running=True,
        enabled=True,
    )

    systemd.service(
        name="Restart dnsmasq after validated configuration change",
        service="dnsmasq",
        running=True,
        restarted=True,
        _if=lambda: dnsmasq_validation.did_change(),
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
