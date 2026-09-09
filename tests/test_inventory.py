from pathlib import Path
import importlib.util

import yaml

from lib.env_config import expand_env


INVENTORY = Path(__file__).parents[1] / "pyinfra/inventory.py"
_SPEC = importlib.util.spec_from_file_location("rinstall_inventory", INVENTORY)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_host_entry = _MODULE._host_entry
_phase_hosts = _MODULE._phase_hosts


EXAMPLE_ENV = Path(__file__).parents[1] / "envs/example/env.yaml"


def configured_bastion2():
    with EXAMPLE_ENV.open() as stream:
        config = yaml.safe_load(stream)
    config["nodes"]["bastion2"] = config["nodes"].pop("bastion1")
    config["bastion"]["service_node"] = "bastion2"
    return expand_env(config)


def test_bastion_phases_select_only_configured_service_node():
    config = configured_bastion2()

    for phase in ("bastion-packages", "bastion", "rancher-install", "rancher-bootstrap"):
        assert set(_phase_hosts(phase, config)) == {"bastion2"}


def test_target_inventory_uses_instance_known_hosts(tmp_path):
    config = configured_bastion2()
    known_hosts = tmp_path / ".rinstall" / "known_hosts"

    _, data = _host_entry(
        "bastion2",
        config["nodes"]["bastion2"],
        config,
        tmp_path / ".rinstall" / "ssh_config",
        known_hosts,
    )

    assert data["ssh_known_hosts_file"] == str(known_hosts)
    assert data["ssh_strict_host_key_checking"] == "accept-new"
