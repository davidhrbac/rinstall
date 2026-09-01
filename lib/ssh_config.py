import os
from pathlib import Path


def build_dir_for_env(env_config_path):
    return Path("build") / Path(env_config_path).parent.name


def node_ssh_target(node):
    return node.get("ssh_ip") or node.get("management_ip") or node["ip"]


def proxy_command_via(proxy_jump):
    hops = str(proxy_jump).split(",")
    if len(hops) == 1:
        return f"ssh -F ~/.ssh/config -W %h:%p {hops[0]}"
    return f"ssh -F ~/.ssh/config -J {','.join(hops[:-1])} -W %h:%p {hops[-1]}"


def node_proxy_command(config, node_name, node):
    ssh = config.get("ssh", {})
    jump_host = ssh.get("jump_host")
    if not jump_host:
        return None

    jump_alias = jump_host if isinstance(jump_host, str) else jump_host.get("alias", "rancher-env-jump")
    bastion_name = config.get("bastion", {}).get("service_node", "bastion1")
    bastion_proxy_roles = set(ssh.get("bastion_proxy_roles", []))
    if node["role"] not in bastion_proxy_roles or node_name == bastion_name:
        return proxy_command_via(jump_alias)

    bastion_node = config["nodes"][bastion_name]
    bastion_ssh_target = node_ssh_target(bastion_node)
    ssh_user = ssh.get("user", "root")
    ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
    return f"ssh -F ~/.ssh/config -i {ssh_key} -l {ssh_user} -J {jump_alias} -W %h:%p {bastion_ssh_target}"


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
                *([f"  ProxyCommand {proxy_command_via(extra_host['proxy_jump'])}"] if extra_host.get("proxy_jump") else []),
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
                *([f"  ProxyCommand {proxy_command_via(jump_host['proxy_jump'])}"] if jump_host.get("proxy_jump") else []),
                "",
            ]
        )

    for node_name, node in config["nodes"].items():
        proxy_command = node_proxy_command(config, node_name, node)

        lines.extend(
            [
                f"Host {node_name} {node_ssh_target(node)}",
                f"  HostName {node_ssh_target(node)}",
                f"  User {ssh_user}",
                f"  IdentityFile {ssh_key}",
                *([f"  ProxyCommand {proxy_command}"] if proxy_command else []),
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
