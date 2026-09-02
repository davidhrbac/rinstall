import os

from pyinfra import host
from pyinfra.operations import dnf, files, server, systemd
from io import StringIO


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


if phase == "bastion" and role == "bastion":
    dnf.packages(
        name="Install bastion services",
        packages=["dnsmasq", "squid", "NetworkManager"],
        present=True,
    )

    files.directory(
        name="Ensure dnsmasq config dir exists",
        path="/etc/dnsmasq.d",
        present=True,
    )

    files.template(
        name="Render /etc/hosts DNS records",
        src="pyinfra/templates/hosts.j2",
        dest="/etc/hosts",
        mode="0644",
        config=config,
        rancher_nodes=rancher_nodes(),
    )

    files.template(
        name="Render dnsmasq local config",
        src="pyinfra/templates/dnsmasq-local.conf.j2",
        dest="/etc/dnsmasq.d/10-rancher-local.conf",
        mode="0644",
        config=config,
    )

    files.template(
        name="Render dnsmasq DHCP config",
        src="pyinfra/templates/dnsmasq-dhcp.conf.j2",
        dest="/etc/dnsmasq.d/20-local-dhcp.conf",
        mode="0644",
        config=config,
    )

    for source_name, target_name in config["bastion"].get("network_connection_names", {}).items():
        server.shell(
            name=f"Rename NetworkManager connection {source_name} to {target_name}",
            commands=[
                "target='{target}'; source='{source}'; "
                "if nmcli -t -f NAME con show \"$target\" >/dev/null 2>&1; then "
                "exit 0; "
                "fi; "
                "if nmcli -t -f NAME con show \"$source\" >/dev/null 2>&1; then "
                "connection=\"$source\"; "
                "else "
                "connection=$(nmcli -g GENERAL.CONNECTION device show \"$source\"); "
                "fi; "
                "nmcli con mod \"$connection\" connection.id \"$target\"".format(
                    source=source_name,
                    target=target_name,
                )
            ],
        )

    server.shell(
        name="Add vSphere route",
        commands=[
            "connection='{connection}'; route='{route}'; "
            "if ! nmcli -t -f NAME con show \"$connection\" >/dev/null 2>&1; then "
            "connection=$(nmcli -g GENERAL.CONNECTION device show \"$connection\"); "
            "fi; "
            "if ! nmcli -g ipv4.routes con show \"$connection\" | grep -F -- \"$route\" >/dev/null; then "
            "nmcli con mod \"$connection\" +ipv4.routes \"$route\"; "
            "fi".format(
                connection=config["bastion"]["vsphere_route_connection"],
                route=config["bastion"]["vsphere_route"],
            )
        ],
    )

    systemd.service(
        name="Enable and restart dnsmasq",
        service="dnsmasq",
        running=True,
        restarted=True,
        enabled=True,
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
        src="pyinfra/templates/prompt.sh.j2",
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
        src="files/rke2-canal.conf",
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
        src="pyinfra/templates/rke2-config.yaml.j2",
        dest="/etc/rancher/rke2/config.yaml",
        mode="0600",
        config=config,
        node=node,
        node_name=name,
    )

    files.template(
        name="Render proxy environment",
        src="pyinfra/templates/proxy.sh.j2",
        dest="/etc/profile.d/proxy.sh",
        mode="0644",
        config=config,
    )

    files.template(
        name="Render RKE2 shell environment",
        src="pyinfra/templates/rke2.sh.j2",
        dest="/etc/profile.d/rke2.sh",
        mode="0644",
    )

    files.template(
        name="Render RKE2 service proxy environment",
        src="pyinfra/templates/rke2-server.env.j2",
        dest="/etc/default/rke2-server",
        mode="0644",
        config=config,
    )

if phase == "rke2-install-primary" and role == "rancher" and name == config["rke2"]["primary_node"]:
    files.put(
        name="Upload RKE2 install script on primary",
        src="scripts/install-rke2.sh",
        dest="/tmp/install-rke2.sh",
        mode="0700",
    )

    server.shell(
        name="Install or start RKE2 primary server",
        commands=["/tmp/install-rke2.sh"],
    )

if phase == "rke2-install-join" and role == "rancher" and name != config["rke2"]["primary_node"]:
    files.put(
        name="Upload RKE2 install script on join nodes",
        src="scripts/install-rke2.sh",
        dest="/tmp/install-rke2.sh",
        mode="0700",
    )

    server.shell(
        name="Install or start RKE2 join servers",
        commands=["/tmp/install-rke2.sh"],
    )

if phase == "rancher-install" and role == "bastion":
    files.put(
        name="Upload Rancher install script",
        src="scripts/install-rancher.sh",
        dest="/tmp/install-rancher.sh",
        mode="0700",
    )

    server.shell(
        name="Install cert-manager and Rancher",
        commands=[
            "RANCHER_HOSTNAME='{hostname}' CERT_MANAGER_VERSION='{cert_manager_version}' RANCHER_VERSION='{rancher_version}' RANCHER_REPO_NAME='{repo_name}' RANCHER_REPO_URL='{repo_url}' /tmp/install-rancher.sh".format(
                hostname=config["rancher_url"],
                cert_manager_version=config["rancher"].get("cert_manager_version", "v1.15.3"),
                rancher_version=config["rancher"].get("rancher_chart_version", "2.9.2"),
                repo_name=config["rancher"]["chart_repo_name"],
                repo_url=config["rancher"]["chart_repo_url"],
            )
        ],
    )

if phase == "rancher-bootstrap" and role == "bastion":
    files.put(
        name="Upload Rancher bootstrap script",
        src="scripts/bootstrap-rancher.sh",
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
