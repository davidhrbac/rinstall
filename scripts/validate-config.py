import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.env_config import load_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    config_path = Path(args.env).resolve()

    try:
        load_env(config_path)
    except SystemExit as error:
        message = str(error)
        if message.startswith("missing env."):
            field = message.removeprefix("missing env.")
            detail = f"Missing required field:\n  {field}"
        else:
            detail = f"Validation error:\n  {message.removeprefix('env.')}"
        error_prefix = "ERROR:" if "NO_COLOR" in os.environ else "\033[31mERROR:\033[0m"
        print(
            f"{error_prefix} invalid configuration\n\n{detail}\n\nConfig:\n  {config_path}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
