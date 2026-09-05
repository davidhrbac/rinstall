from pathlib import Path
import os
import shutil
import subprocess
import sys


ENGINE_ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ENGINE_ROOT / "envs/example/env.yaml"
INSTANCE_FIXTURE = ENGINE_ROOT / "examples/instance-repository"


def test_instance_fixture_ignores_runtime_files():
    assert ".rinstall/" in (INSTANCE_FIXTURE / ".gitignore").read_text().splitlines()
    assert (INSTANCE_FIXTURE / ".gitmodules").exists()
    assert (INSTANCE_FIXTURE / "config.yaml").exists()


def test_makefile_derives_instance_paths(tmp_path):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    shutil.copy(EXAMPLE_ENV, instance_root / "config.yaml")
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)

    result = subprocess.run(
        ["make", "-f", "rinstall/Makefile", "-n", "render-infra-vars"],
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

    init_result = subprocess.run(
        ["make", "-f", "rinstall/Makefile", "-n", "infra-init"],
        cwd=instance_root,
        check=True,
        capture_output=True,
        text=True,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if key not in {"ENV_FILE", "RUNTIME_DIR", "TF_DATA_DIR", "MAKEFLAGS", "MFLAGS"}
            },
            "TF_HTTP_ADDRESS": "https://gitlab.example/api/v4/projects/1/terraform/state/example",
        },
    )
    assert f"TF_DATA_DIR={instance_root}/.rinstall/terraform-data" in init_result.stdout
    assert f"-chdir={instance_root}/rinstall/terraform/infra" in init_result.stdout
    assert f"{instance_root}/.rinstall/terraform " not in init_result.stdout
    assert "-lockfile=readonly" in init_result.stdout

def test_verify_uses_instance_terraform_data_dir(tmp_path):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    shutil.copy(EXAMPLE_ENV, instance_root / "config.yaml")
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)

    result = subprocess.run(
        ["make", "-f", "rinstall/Makefile", "-n", "verify"],
        cwd=instance_root,
        check=True,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key not in {"ENV_FILE", "RUNTIME_DIR", "TF_DATA_DIR", "MAKEFLAGS", "MFLAGS"}},
    )

    terraform_lines = [line for line in result.stdout.splitlines() if "terraform -chdir=" in line]
    assert terraform_lines
    assert all(f"TF_DATA_DIR={instance_root}/.rinstall/terraform-data" in line for line in terraform_lines)
    init_lines = [line for line in terraform_lines if " init " in line]
    assert init_lines
    assert all("-backend=false" in line and "-lockfile=readonly" in line for line in init_lines)


def test_fresh_instance_infra_plan_initializes_and_renders_vars(tmp_path):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    shutil.copy(EXAMPLE_ENV, instance_root / "config.yaml")
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)

    result = subprocess.run(
        ["make", "-f", "rinstall/Makefile", "-n", "infra-plan"],
        cwd=instance_root,
        check=True,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key not in {"ENV_FILE", "RUNTIME_DIR", "TF_DATA_DIR", "MAKEFLAGS", "MFLAGS"}},
    )

    lines = result.stdout.splitlines()
    init_line = next(index for index, line in enumerate(lines) if " terraform -chdir=" in line and " init " in line)
    render_line = next(index for index, line in enumerate(lines) if "render-infra-tfvars.py" in line)
    plan_line = next(index for index, line in enumerate(lines) if " terraform -chdir=" in line and " plan " in line)
    assert init_line < render_line < plan_line
    assert f"TF_DATA_DIR={instance_root}/.rinstall/terraform-data" in lines[init_line]
    assert f"--out {instance_root}/.rinstall/infra.tfvars.json" in lines[render_line]


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
    assert (runtime / "rke2.yaml.raw").stat().st_mode & 0o777 == 0o600
    assert (runtime / "rke2.yaml").stat().st_mode & 0o777 == 0o600
