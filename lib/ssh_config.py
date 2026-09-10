import os
from pathlib import Path

from lib.env_config import load_env


def build_dir_for_env(env_config_path):
    runtime_dir = os.environ.get("RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir)
    return Path("build") / load_env(env_config_path)["environment"]["id"]


def node_ssh_target(node):
    return node.get("ssh_ip") or node.get("management_ip") or node["ip"]


def proxy_command_via(proxy_jump):
    hops = str(proxy_jump).split(",")
    if len(hops) == 1:
        return f"ssh -F ~/.ssh/config -W %h:%p {hops[0]}"
    return f"ssh -F ~/.ssh/config -J {','.join(hops[:-1])} -W %h:%p {hops[-1]}"


def node_ssh_hops(config, node_name, node):
    ssh = config.get("ssh", {})
    jump_host = ssh.get("jump_host")
    if not jump_host:
        return ()

    jump_alias = jump_host if isinstance(jump_host, str) else jump_host.get("alias", "rancher-env-jump")
    bastion_name = config["bastion"]["service_node"]
    if node_name == bastion_name or node["role"] not in set(ssh.get("bastion_proxy_roles", [])):
        return (jump_alias,)
    return (jump_alias, bastion_name)


def node_proxy_command(config, node_name, node, known_hosts_file=None):
    hops = node_ssh_hops(config, node_name, node)
    if not hops:
        return None

    jump_alias = hops[0]
    if len(hops) == 1:
        return proxy_command_via(jump_alias)

    ssh = config.get("ssh", {})
    bastion_name = config["bastion"]["service_node"]
    bastion_node = config["nodes"][bastion_name]
    bastion_ssh_target = node_ssh_target(bastion_node)
    ssh_user = ssh.get("user", "root")
    ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
    host_key_options = ""
    if known_hosts_file:
        host_key_options = (
            f" -o UserKnownHostsFile={known_hosts_file}"
            " -o GlobalKnownHostsFile=/dev/null"
            " -o StrictHostKeyChecking=accept-new"
        )
    return f"ssh -F ~/.ssh/config{host_key_options} -i {ssh_key} -l {ssh_user} -J {jump_alias} -W %h:%p {bastion_ssh_target}"


def render_ssh_config(config, known_hosts_file=None):
    ssh = config.get("ssh", {})
    ssh_user = ssh.get("user", "root")
    ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
    jump_host = ssh.get("jump_host")
    jump_alias = None
    environment_id = config["environment"]["id"]
    default_runtime_dir = os.environ.get("RUNTIME_DIR") or Path("build") / environment_id
    known_hosts_file = Path(known_hosts_file or Path(default_runtime_dir) / "known_hosts").resolve()
    lines = []

    for node_name, node in config["nodes"].items():
        lines.extend(
            [
                f"Host {node_name} {node_name}.{environment_id} {node_ssh_target(node)}",
                f"  UserKnownHostsFile {known_hosts_file}",
                "  GlobalKnownHostsFile /dev/null",
                "  StrictHostKeyChecking accept-new",
                "",
            ]
        )

    lines.extend(["Include ~/.ssh/config", ""])

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
        proxy_command = node_proxy_command(config, node_name, node, known_hosts_file)

        lines.extend(
            [
                f"Host {node_name} {node_name}.{environment_id} {node_ssh_target(node)}",
                f"  HostName {node_ssh_target(node)}",
                f"  User {ssh_user}",
                f"  IdentityFile {ssh_key}",
                *([f"  ProxyCommand {proxy_command}"] if proxy_command else []),
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def render_admin_ssh_config(config):
    ssh = config.get("ssh", {})
    ssh_user = ssh.get("user", "root")
    ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
    environment_id = config["environment"]["id"]
    bastion_name = config["bastion"]["service_node"]
    bastion_alias = f"{bastion_name}.{environment_id}"
    lines = []

    for node_name, node in config["nodes"].items():
        is_bastion = node_name == bastion_name
        target = node_ssh_target(node) if is_bastion else node["ip"]
        lines.extend(
            [
                f"Host {node_name}.{environment_id}",
                f"  HostName {target}",
                f"  User {ssh_user}",
                f"  IdentityFile {ssh_key}",
                *([] if is_bastion else [f"  ProxyJump {bastion_alias}" ]),
                "",
            ]
        )

    return "\n".join(lines)


def write_ssh_config(config, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    known_hosts_file = (path.parent / "known_hosts").resolve()
    known_hosts_file.touch(mode=0o600, exist_ok=True)
    known_hosts_file.chmod(0o600)
    path.write_text(render_ssh_config(config, known_hosts_file))
    return path


def write_admin_ssh_config(config, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_admin_ssh_config(config))
    return path
