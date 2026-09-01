#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env
from lib.ssh_config import build_dir_for_env, write_ssh_config


def main():
    parser = argparse.ArgumentParser(description="Render OpenSSH config for pyinfra access")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    parser.add_argument("--out", help="Output ssh_config path")
    args = parser.parse_args()

    env_path = Path(args.env)
    config = load_env(env_path)
    out = Path(args.out) if args.out else build_dir_for_env(env_path) / "ssh_config"
    write_ssh_config(config, out)
    print(out)


if __name__ == "__main__":
    main()
