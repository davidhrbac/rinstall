import argparse
import shlex
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    with Path(args.env).open() as stream:
        backend = (yaml.safe_load(stream) or {}).get("terraform", {}).get("backend", {})
    if not backend:
        return
    address = f"{backend['url'].rstrip('/')}/api/v4/projects/{backend['project_id']}/terraform/state/{backend['state']}"
    values = {
        "TF_HTTP_ADDRESS": address,
        "TF_HTTP_LOCK_ADDRESS": f"{address}/lock",
        "TF_HTTP_UNLOCK_ADDRESS": f"{address}/lock",
        "TF_HTTP_LOCK_METHOD": "POST",
        "TF_HTTP_UNLOCK_METHOD": "DELETE",
        "TF_HTTP_RETRY_WAIT_MIN": "5",
    }
    print(" ".join(f"{key}={shlex.quote(value)}" for key, value in values.items()))


if __name__ == "__main__":
    main()
