import os
import subprocess
import sys
from pathlib import Path

import yaml


ENGINE_ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ENGINE_ROOT / "envs/example/env.yaml"


def make_instance(tmp_path):
    instance_root = tmp_path / "instance"
    instance_root.mkdir()
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["nodes"]["bastion2"] = config["nodes"].pop("bastion1")
    config["nodes"]["prom2"] = config["nodes"].pop("prom1")
    config["bastion"]["service_node"] = "bastion2"
    (instance_root / "config.yaml").write_text(yaml.safe_dump(config))
    (instance_root / "rinstall").symlink_to(ENGINE_ROOT, target_is_directory=True)
    return instance_root


def public_key(tmp_path):
    key = tmp_path / "host-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
    )
    return key.with_suffix(".pub").read_text().split()[:2]


def run_make(instance_root, target, *arguments, home=None):
    env = {**os.environ}
    if home:
        env["HOME"] = str(home)
    return subprocess.run(
        [
            "make",
            "-f",
            "rinstall/Makefile",
            target,
            f"PYTHON={sys.executable}",
            *arguments,
        ],
        cwd=instance_root,
        capture_output=True,
        text=True,
        env=env,
    )


def test_selective_reset_removes_only_requested_node(tmp_path):
    instance_root = make_instance(tmp_path)
    runtime = instance_root / ".rinstall"
    runtime.mkdir()
    known_hosts = runtime / "known_hosts"
    key_type, key = public_key(tmp_path)
    known_hosts.write_text(
        f"10.14.17.4 {key_type} {key}\n"
        f"10.14.17.6 {key_type} {key}\n"
        f"10.14.17.11 {key_type} {key}\n"
    )
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    global_known_hosts = home / ".ssh" / "known_hosts"
    global_known_hosts.write_text(f"10.14.17.4 {key_type} {key}\n")

    result = run_make(instance_root, "ssh-hostkey-reset", "NODE=bastion2", home=home)

    assert result.returncode == 0, result.stderr
    remaining = known_hosts.read_text()
    assert "10.14.17.4 " not in remaining
    assert "10.14.17.6 " in remaining
    assert "10.14.17.11 " in remaining
    assert global_known_hosts.read_text() == f"10.14.17.4 {key_type} {key}\n"
    assert not (runtime / "known_hosts.old").exists()


def test_selective_reset_rejects_unknown_or_missing_node(tmp_path):
    instance_root = make_instance(tmp_path)

    missing = run_make(instance_root, "ssh-hostkey-reset")
    unknown = run_make(instance_root, "ssh-hostkey-reset", "NODE=missing")

    assert missing.returncode != 0
    assert "NODE is required" in missing.stderr
    assert unknown.returncode != 0
    assert "unknown NODE: missing" in unknown.stderr


def test_reset_commands_are_harmless_without_known_hosts(tmp_path):
    instance_root = make_instance(tmp_path)

    selective = run_make(instance_root, "ssh-hostkey-reset", "NODE=prom2")
    full = run_make(instance_root, "ssh-hostkeys-reset")

    assert selective.returncode == 0, selective.stderr
    assert full.returncode == 0, full.stderr
    assert not (instance_root / ".rinstall" / "known_hosts").exists()


def test_full_reset_removes_only_instance_known_hosts(tmp_path):
    instance_root = make_instance(tmp_path)
    runtime = instance_root / ".rinstall"
    runtime.mkdir()
    known_hosts = runtime / "known_hosts"
    known_hosts.write_text("instance host keys\n")
    retained = runtime / "infra-output.json"
    retained.write_text("{}\n")
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    global_known_hosts = home / ".ssh" / "known_hosts"
    global_known_hosts.write_text("global host keys\n")

    result = run_make(instance_root, "ssh-hostkeys-reset", home=home)

    assert result.returncode == 0, result.stderr
    assert not known_hosts.exists()
    assert retained.read_text() == "{}\n"
    assert global_known_hosts.read_text() == "global host keys\n"
