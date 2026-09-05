import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.env_config import gitlab_backend_state_address, load_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    config_path = Path(args.env).resolve()
    env = load_env(config_path)
    backend = env.get("terraform", {}).get("backend")
    state_address = gitlab_backend_state_address(backend) if backend else "(not configured)"

    print("=" * 60)
    print("rinstall instance")
    print(f"Environment ID:  {env['environment']['id']}")
    print(f"Rancher:         {env['rancher_url']}")
    print(f"Terraform state: {state_address}")
    print(f"Config:          {config_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
