from pathlib import Path
import os
import shutil
import subprocess
import sys


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


def test_kubeconfig_artifacts_are_private(tmp_path):
    runtime = tmp_path / ".rinstall"
    runtime.mkdir()
    (runtime / "rke2.yaml.raw").write_text("server: https://rancher1.example:6443\n")

    subprocess.run(
        [
            sys.executable,
            str(ENGINE_ROOT / "scripts/prepare-rke2-kubeconfig.py"),
            "--env",
            str(EXAMPLE_ENV),
        ],
        cwd=ENGINE_ROOT,
        check=True,
        env={**os.environ, "RUNTIME_DIR": str(runtime)},
    )

    assert runtime.stat().st_mode & 0o777 == 0o700
    assert (runtime / "rke2.yaml").stat().st_mode & 0o777 == 0o600
