import argparse
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.env_config import gitlab_backend_state_address, load_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--shell", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.env).resolve()
    env = load_env(config_path)
    backend = env["terraform"]["backend"]
    state_address = gitlab_backend_state_address(backend)

    if args.shell:
        for key, value in {
            "INSTANCE_ID": env["environment"]["id"],
            "RANCHER_URL": env["rancher_url"],
            "STATE_ADDRESS": state_address,
        }.items():
            print(f"{key}={shlex.quote(value)}")
        return

    print("=" * 60)
    print(f"rinstall :: {env['environment']['id']}")
    print()
    print(f"Rancher: {env['rancher_url']}")
    print(f"State:   {state_address}")
    print(f"Config:  {config_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
