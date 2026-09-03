#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env


def main():
    parser = argparse.ArgumentParser(description="Print the configured admin jump-host SSH alias")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    args = parser.parse_args()

    jump_host = load_env(args.env).get("ssh", {}).get("jump_host")
    if isinstance(jump_host, str):
        print(jump_host)
        return
    if isinstance(jump_host, dict) and jump_host.get("alias"):
        print(jump_host["alias"])
        return
    raise SystemExit("env.ssh.jump_host must be configured or pass ADMIN_SSH_HOST=<SSH alias>")


if __name__ == "__main__":
    main()
