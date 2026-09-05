from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest
import yaml


ENGINE_ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ENGINE_ROOT / "envs/example/env.yaml"
INSTANCE_FIXTURE = ENGINE_ROOT / "examples/instance-repository"
CONTEXT_HELPER = ENGINE_ROOT / "scripts/print-instance-context.py"
BACKEND_HELPER = ENGINE_ROOT / "scripts/terraform-backend-env.py"
SECRET_VALUES = [
    "TF_HTTP_USERNAME",
    "TF_HTTP_PASSWORD",
    "TF_VAR_vsphere_password",
    "rke2-token-secret",
    "rancher-bootstrap-secret",
    "runtime-user",
    "runtime-secret",
]


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


def test_instance_context_prints_resolved_identity_without_credentials(tmp_path):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["terraform"] = {
        "backend": {
            "type": "gitlab",
            "url": "https://gitlab.example",
            "project_id": 1234,
            "state": "infra",
        }
    }
    config["rke2"]["token"] = "rke2-token-secret"
    config["rancher"]["bootstrap_password"] = "rancher-bootstrap-secret"
    (instance_root / "config.yaml").write_text(yaml.safe_dump(config))
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)

    result = subprocess.run(
        ["make", "-f", "rinstall/Makefile", "instance-context", f"PYTHON={sys.executable}"],
        cwd=instance_root,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TF_HTTP_USERNAME": "runtime-user",
            "TF_HTTP_PASSWORD": "runtime-secret",
            "TF_VAR_vsphere_password": "vsphere-password-secret",
        },
    )
    assert result.returncode == 0, result.stderr

    assert "rinstall :: example\n\n" in result.stdout
    assert "Rancher: rancher.example.internal" in result.stdout
    assert "State:   https://gitlab.example/api/v4/projects/1234/terraform/state/infra" in result.stdout
    assert f"Config:  {instance_root / 'config.yaml'}" in result.stdout
    assert all(secret not in result.stdout for secret in SECRET_VALUES)
    assert "vsphere-password-secret" not in result.stdout


@pytest.mark.parametrize("helper", [CONTEXT_HELPER, BACKEND_HELPER])
def test_backend_helpers_reject_missing_backend(tmp_path, helper):
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    del config["terraform"]
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))

    result = subprocess.run(
        [sys.executable, str(helper), "--env", str(config_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "not configured" not in result.stdout


@pytest.mark.parametrize("target", ["infra-plan", "infra-apply", "destroy-commands"])
def test_operator_targets_include_instance_context_banner(tmp_path, target):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["terraform"] = {
        "backend": {
            "type": "gitlab",
            "url": "https://gitlab.example",
            "project_id": 1234,
            "state": "infra",
        }
    }
    (instance_root / "config.yaml").write_text(yaml.safe_dump(config))
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)

    result = subprocess.run(
        ["make", "-f", "rinstall/Makefile", "-n", target, f"PYTHON={sys.executable}"],
        cwd=instance_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "print-instance-context.py --env" in result.stdout


def test_provision_all_banner_is_complete_and_logged(tmp_path):
    instance_root = tmp_path / "customer-a-prod-infra"
    instance_root.mkdir()
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["terraform"] = {
        "backend": {
            "type": "gitlab",
            "url": "https://gitlab.example",
            "project_id": 1234,
            "state": "infra",
        }
    }
    config["rke2"]["token"] = "rke2-token-secret"
    config["rancher"]["bootstrap_password"] = "rancher-bootstrap-secret"
    (instance_root / "config.yaml").write_text(yaml.safe_dump(config))
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)
    fake_make = tmp_path / "fake-make"
    fake_make.write_text("#!/bin/sh\nexit 0\n")
    fake_make.chmod(0o700)

    result = subprocess.run(
        [
            "make",
            "-f",
            "rinstall/Makefile",
            "provision-all",
            "DEPLOY_YES=1",
            f"PYTHON={sys.executable}",
            f"MAKE={fake_make}",
        ],
        cwd=instance_root,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TF_HTTP_USERNAME": "runtime-user",
            "TF_HTTP_PASSWORD": "runtime-secret",
            "TF_VAR_vsphere_password": "vsphere-password-secret",
        },
    )

    output = result.stdout
    assert output.count("rinstall :: provision-all\n\n") == 1
    assert "Environment ID:  example" in output
    assert "Rancher:         rancher.example.internal" in output
    assert "State:           https://gitlab.example/api/v4/projects/1234/terraform/state/infra" in output
    assert f"Config:          {instance_root / 'config.yaml'}" in output
    assert f"Runtime dir:     {instance_root / '.rinstall'}" in output
    assert f"Terraform:       {instance_root / 'rinstall/terraform/infra'}" in output
    assert "Engine version:" in output and "Engine worktree:" in output
    assert "Environment version:" in output and "Environment worktree:" in output
    assert "Mode:             noninteractive" in output
    phases = [
        "make -f rinstall/Makefile infra-apply",
        "make -f rinstall/Makefile bastion-configure",
        "make -f rinstall/Makefile node-prep",
        "make -f rinstall/Makefile rke2-install",
        "make -f rinstall/Makefile rancher-install",
    ]
    phase_positions = [output.index(phase) for phase in phases]
    assert phase_positions == sorted(phase_positions)
    phase_lines = [next(line for line in output.splitlines() if phase in line) for phase in phases]
    opening_columns = [line.index("(") for line in phase_lines]
    assert len(set(opening_columns)) == 1
    assert all(secret not in output for secret in SECRET_VALUES)
    assert "vsphere-password-secret" not in output

    log_path = next(instance_root.glob(".rinstall/provision-*.log"))
    log = log_path.read_text()
    assert "rinstall :: provision-all\n\n" in log
    assert "Environment ID:  example" in log
    assert "State:           https://gitlab.example/api/v4/projects/1234/terraform/state/infra" in log
    assert log.count("rinstall :: provision-all\n\n") == 1
    assert all(secret not in log for secret in SECRET_VALUES)
    assert "vsphere-password-secret" not in log


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
