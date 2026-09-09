#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env


def main():
    parser = argparse.ArgumentParser(description="Check whether downstream networks are configured")
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    config = load_env(args.env)
    print("1" if config["bastion"]["downstream_networks"] else "0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
