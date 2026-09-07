import argparse
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.env_config import gitlab_backend_state_address, load_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--format", choices=["shell", "multiline"], default="shell")
    args = parser.parse_args()
    env = load_env(args.env)
    backend = env["terraform"]["backend"]
    address = gitlab_backend_state_address(backend, env["environment"]["id"])
    values = {
        "TF_HTTP_ADDRESS": address,
        "TF_HTTP_LOCK_ADDRESS": f"{address}/lock",
        "TF_HTTP_UNLOCK_ADDRESS": f"{address}/lock",
        "TF_HTTP_LOCK_METHOD": "POST",
        "TF_HTTP_UNLOCK_METHOD": "DELETE",
        "TF_HTTP_RETRY_WAIT_MIN": "5",
    }
    assignments = [f"{key}={shlex.quote(value)}" for key, value in values.items()]
    if args.format == "multiline":
        print(" \\\n".join(assignments) + " \\")
    else:
        print(" ".join(assignments))


if __name__ == "__main__":
    main()
