import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env
from lib.ssh_config import build_dir_for_env, write_ssh_config


env_config = Path(os.environ.get("ENV_CONFIG", "envs/example/env.yaml"))
config = load_env(env_config)

ssh = config.get("ssh", {})
ssh_user = ssh.get("user", "root")
ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
ssh_config_file = None

if ssh.get("jump_host"):
    ssh_config_file = write_ssh_config(config, build_dir_for_env(env_config) / "ssh_config")

bastion = []
rancher_nodes = []
all_nodes = []

for name, node in config["nodes"].items():
    address = name if ssh_config_file else node.get("ssh_ip") or node.get("management_ip") or node["ip"]
    data = {
        "name": name,
        "role": node["role"],
        "ssh_user": ssh_user,
        "ssh_key": ssh_key,
        "env_config": config,
        "node_config": node,
    }
    if ssh_config_file:
        data["ssh_config_file"] = str(ssh_config_file)

    host = (
        address,
        data,
    )
    all_nodes.append(host)
    if node["role"] == "bastion":
        bastion.append(host)
    if node["role"] == "rancher":
        rancher_nodes.append(host)
