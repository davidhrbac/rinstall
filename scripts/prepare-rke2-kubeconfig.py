#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env
from lib.ssh_config import build_dir_for_env


def main():
    parser = argparse.ArgumentParser(description="Prepare bastion kubeconfig for Rancher install")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    args = parser.parse_args()

    env_path = Path(args.env)
    config = load_env(env_path)
    build_dir = build_dir_for_env(env_path)
    raw_path = build_dir / "rke2.yaml.raw"
    out_path = build_dir / "rke2.yaml"

    if not raw_path.exists():
        raise SystemExit(f"RKE2 kubeconfig not found: {raw_path}")

    primary = config["rke2"]["primary_node"]
    primary_ip = config["nodes"][primary]["ip"]
    endpoint = f"https://{primary_ip}:6443"

    content = raw_path.read_text()
    content, count = re.subn(
        r"^(\s*server:\s*)https://[^\s:]+:6443[^\S\r\n]*$",
        lambda match: f"{match.group(1)}{endpoint}",
        content,
        flags=re.MULTILINE,
    )
    if count == 0:
        raise SystemExit(f"No Kubernetes API server endpoint found in {raw_path}")

    out_path.write_text(content)


if __name__ == "__main__":
    main()
