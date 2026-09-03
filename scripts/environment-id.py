#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env


def main():
    parser = argparse.ArgumentParser(description="Print the validated environment ID")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    args = parser.parse_args()

    print(load_env(args.env)["environment"]["id"])


if __name__ == "__main__":
    main()
