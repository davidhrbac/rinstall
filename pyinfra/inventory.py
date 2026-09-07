import os as _os
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

from lib.env_config import load_env as _load_env
from lib.ssh_config import build_dir_for_env as _build_dir_for_env
from lib.ssh_config import node_ssh_target as _node_ssh_target
from lib.ssh_config import write_ssh_config as _write_ssh_config


def _host_entry(node_name, node, config, ssh_config_file, known_hosts_file):
    ssh = config.get("ssh", {})
    ssh_target = _node_ssh_target(node)
    address = ssh_target
    data = {
        "name": node_name,
        "role": node["role"],
        "ssh_hostname": ssh_target,
        "ssh_user": ssh.get("user", "root"),
        "ssh_key": _os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa")),
        "ssh_known_hosts_file": str(known_hosts_file),
        "ssh_strict_host_key_checking": "accept-new",
        "env_config": config,
        "node_config": node,
    }
    if ssh_config_file:
        data["ssh_config_file"] = str(ssh_config_file)
    return (address, data)


def _phase_hosts(phase, config):
    nodes = config["nodes"]
    primary = config["rke2"]["primary_node"]
    if phase in {"bastion", "rancher-install", "rancher-bootstrap"}:
        service_node = config["bastion"]["service_node"]
        return {service_node: nodes[service_node]}
    if phase in {"rke2-install-primary", "rke2-kubeconfig"}:
        return {primary: nodes[primary]}
    if phase == "rke2-install-join":
        return {name: node for name, node in nodes.items() if node["role"] == "rancher" and name != primary}
    return nodes


_env_config = _Path(_os.environ.get("ENV_CONFIG", "envs/example/env.yaml"))
_phase = _os.environ.get("PHASE", "bastion")
_config = _load_env(_env_config)
_runtime_dir = _build_dir_for_env(_env_config)
_ssh_config_file = _write_ssh_config(_config, _runtime_dir / "ssh_config")
_known_hosts_file = (_runtime_dir / "known_hosts").resolve()

all = [
    _host_entry(name, node, _config, _ssh_config_file, _known_hosts_file)
    for name, node in _phase_hosts(_phase, _config).items()
]
