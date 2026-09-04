from pathlib import Path
import os
import shutil
import subprocess


ENGINE_ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ENGINE_ROOT / "envs/example/env.yaml"


def test_makefile_derives_instance_paths(tmp_path):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    shutil.copy(EXAMPLE_ENV, instance_root / "config.yaml")

    result = subprocess.run(
        ["make", "-f", str(ENGINE_ROOT / "Makefile"), "-n", "render-infra-vars"],
        cwd=instance_root,
        check=True,
        capture_output=True,
        text=True,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"ENV_FILE", "RUNTIME_DIR", "TF_DATA_DIR", "MAKEFLAGS", "MFLAGS"}
        },
    )

    command = result.stdout
    assert f"--env {instance_root}/config.yaml" in command
    assert f"--out {instance_root}/.rinstall/infra.tfvars.json" in command
