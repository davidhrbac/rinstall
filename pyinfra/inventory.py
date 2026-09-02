import os as _os
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

from lib.env_config import load_env as _load_env
from lib.ssh_config import build_dir_for_env as _build_dir_for_env
from lib.ssh_config import node_ssh_target as _node_ssh_target
from lib.ssh_config import write_ssh_config as _write_ssh_config


def _host_entry(node_name, node, config, ssh_config_file):
    ssh = config.get("ssh", {})
    ssh_target = _node_ssh_target(node)
    address = ssh_target
    data = {
        "name": node_name,
        "role": node["role"],
        "ssh_hostname": ssh_target,
        "ssh_user": ssh.get("user", "root"),
        "ssh_key": _os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa")),
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
        return {name: node for name, node in nodes.items() if node["role"] == "bastion"}
    if phase in {"rke2-install-primary", "rke2-kubeconfig"}:
        return {primary: nodes[primary]}
    if phase == "rke2-install-join":
        return {name: node for name, node in nodes.items() if node["role"] == "rancher" and name != primary}
    return nodes


_env_config = _Path(_os.environ.get("ENV_CONFIG", "envs/example/env.yaml"))
_phase = _os.environ.get("PHASE", "bastion")
_config = _load_env(_env_config)
_ssh_config_file = None

if _config.get("ssh", {}).get("jump_host"):
    _ssh_config_file = _write_ssh_config(_config, _build_dir_for_env(_env_config) / "ssh_config")

all = [_host_entry(name, node, _config, _ssh_config_file) for name, node in _phase_hosts(_phase, _config).items()]
