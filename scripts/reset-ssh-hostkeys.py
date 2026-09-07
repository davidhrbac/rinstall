#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env
from lib.ssh_config import node_ssh_target


def reset_node_host_keys(config, known_hosts_file, node_name):
    if node_name not in config["nodes"]:
        raise SystemExit(f"unknown NODE: {node_name}")

    known_hosts_file = Path(known_hosts_file)
    if not known_hosts_file.exists():
        return

    target = node_ssh_target(config["nodes"][node_name])
    subprocess.run(
        ["ssh-keygen", "-R", target, "-f", str(known_hosts_file)],
        check=True,
        capture_output=True,
        text=True,
    )
    backup = known_hosts_file.with_name(f"{known_hosts_file.name}.old")
    backup.unlink(missing_ok=True)


def reset_all_host_keys(known_hosts_file):
    Path(known_hosts_file).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Reset instance-local SSH host keys")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    parser.add_argument("--known-hosts", required=True, help="Instance known_hosts path")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--node", help="Configured node name to reset")
    selection.add_argument("--all", action="store_true", help="Reset all instance host keys")
    args = parser.parse_args()

    known_hosts_file = Path(args.known_hosts)
    if args.all:
        reset_all_host_keys(known_hosts_file)
        print(f"Reset all instance SSH host keys in {known_hosts_file}")
        return

    config = load_env(args.env)
    reset_node_host_keys(config, known_hosts_file, args.node)
    print(f"Reset SSH host key for {args.node} in {known_hosts_file}")


if __name__ == "__main__":
    main()
