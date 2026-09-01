import os
from pathlib import Path


def build_dir_for_env(env_config_path):
    return Path("build") / Path(env_config_path).parent.name


def render_ssh_config(config):
    ssh = config.get("ssh", {})
    ssh_user = ssh.get("user", "root")
    ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
    jump_host = ssh.get("jump_host")
    jump_alias = None
    lines = ["Include ~/.ssh/config", ""]

    if jump_host:
        if isinstance(jump_host, str):
            jump_alias = jump_host
            jump_host = None
        else:
            jump_alias = jump_host.get("alias", "rancher-env-jump")
            if "hostname" not in jump_host and "host" in jump_host:
                jump_host["hostname"] = jump_host["host"]

    for alias, extra_host in ssh.get("extra_hosts", {}).items():
        lines.extend(
            [
                f"Host {alias}",
                f"  HostName {extra_host['hostname']}",
                *([f"  User {extra_host['user']}"] if extra_host.get("user") else []),
                *([f"  Port {extra_host['port']}"] if extra_host.get("port") else []),
                *([f"  IdentityFile {os.path.expanduser(extra_host['private_key'])}"] if extra_host.get("private_key") else []),
                *([f"  ProxyJump {extra_host['proxy_jump']}"] if extra_host.get("proxy_jump") else []),
                "",
            ]
        )

    if jump_host:
        jump_user = jump_host.get("user")
        jump_key = jump_host.get("private_key")
        lines.extend(
            [
                f"Host {jump_alias}",
                f"  HostName {jump_host.get('hostname') or jump_host.get('host')}",
                *([f"  User {jump_user}"] if jump_user else []),
                *([f"  Port {jump_host['port']}"] if jump_host.get("port") else []),
                *([f"  IdentityFile {os.path.expanduser(jump_key)}"] if jump_key else []),
                *([f"  ProxyJump {jump_host['proxy_jump']}"] if jump_host.get("proxy_jump") else []),
                "",
            ]
        )

    bastion_proxy_roles = set(ssh.get("bastion_proxy_roles", []))
    for node_name, node in config["nodes"].items():
        proxy_jump = None
        if jump_alias:
            proxy_jump = jump_alias
            if node["role"] in bastion_proxy_roles and node_name != "bastion1":
                proxy_jump = f"{jump_alias},bastion1"

        lines.extend(
            [
                f"Host {node_name}",
                f"  HostName {node.get('ssh_ip') or node['ip']}",
                f"  User {ssh_user}",
                f"  IdentityFile {ssh_key}",
                *([f"  ProxyJump {proxy_jump}"] if proxy_jump else []),
                "",
            ]
        )

    lines.extend(["Host *", "  StrictHostKeyChecking accept-new"])
    return "\n".join(lines) + "\n"


def write_ssh_config(config, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ssh_config(config))
    return path
