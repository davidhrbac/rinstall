#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env


def main():
    parser = argparse.ArgumentParser(
        description="Print the Rancher generated bootstrap password retrieval command"
    )
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    args = parser.parse_args()

    if load_env(args.env)["rancher"].get("bootstrap_password"):
        return

    print("============================================================")
    print("Rancher Bootstrap Password")
    print("============================================================")
    print("If this was the first Rancher installation, retrieve the generated password with:")
    print(
        "kubectl get secret --namespace cattle-system bootstrap-secret "
        "-o go-template='{{.data.bootstrapPassword|base64decode}}{{\"\\n\"}}'"
    )
    print("Change the Rancher admin password after first login.")
    print("============================================================")


if __name__ == "__main__":
    main()
