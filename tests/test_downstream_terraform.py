from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import yaml

from lib.env_config import expand_env


ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ROOT / "envs/example/env.yaml"
RENDERER_PATH = ROOT / "scripts/render-infra-tfvars.py"
SPEC = spec_from_file_location("render_infra_tfvars", RENDERER_PATH)
RENDERER = module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def downstream_network(vlan, third_octet=None):
    third_octet = vlan if third_octet is None else third_octet
    return {
        "vlan": vlan,
        "vmware_network": f"DOWNSTREAM_VLAN_{vlan}",
        "subnet": f"10.20.{third_octet}.32/27",
        "bastion_address": 2,
        "gateway": 1,
        "dhcp": {"start": 4, "end": -2, "lease_time": "12h"},
    }


def render_with(*networks):
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["bastion"]["downstream_networks"] = list(networks)
    return RENDERER.render(expand_env(config))


def test_appends_one_downstream_nic_after_existing_bastion_nics():
    rendered = render_with(downstream_network(121))
    nics = rendered["nodes"]["bastion1"]["nics"]

    assert [nic["network"] for nic in nics[:2]] == ["customer", "management"]
    assert nics[2] == {
        "network": "__downstream_vlan_121",
        "customize": False,
        "downstream_vlan": 121,
    }
    assert rendered["networks"]["__downstream_vlan_121"] == "DOWNSTREAM_VLAN_121"


def test_appends_two_downstream_nics_in_stable_declaration_order():
    rendered = render_with(downstream_network(122), downstream_network(121))
    nics = rendered["nodes"]["bastion1"]["nics"]

    assert [nic.get("downstream_vlan") for nic in nics] == [None, None, 122, 121]


def test_dhcp_only_change_does_not_change_terraform_input():
    first = downstream_network(121)
    second = downstream_network(121)
    second["dhcp"]["start"] = 5

    assert render_with(first) == render_with(second)


def test_rejects_downstream_removal_and_attachment_reorder():
    rendered = render_with(downstream_network(121), downstream_network(122))
    existing = {
        "bastion_downstream_networks": {
            "value": {
                "vlan121": {"nic_index": 2, "vmware_network": "DOWNSTREAM_VLAN_121"},
                "vlan122": {"nic_index": 3, "vmware_network": "DOWNSTREAM_VLAN_122"},
            }
        }
    }

    RENDERER.validate_no_downstream_removal(rendered, existing)

    with pytest.raises(SystemExit, match="removal is not supported"):
        RENDERER.validate_no_downstream_removal(render_with(downstream_network(121)), existing)

    with pytest.raises(SystemExit, match="attachment order must not change"):
        RENDERER.validate_no_downstream_removal(
            render_with(downstream_network(122), downstream_network(121)),
            existing,
        )

    moved = render_with(downstream_network(121), downstream_network(122))
    moved["networks"]["__downstream_vlan_121"] = "MOVED_NETWORK"
    with pytest.raises(SystemExit, match="changing an existing downstream VMware network"):
        RENDERER.validate_no_downstream_removal(moved, existing)


def test_terraform_output_exposes_provider_network_and_mac_identity():
    output_source = (ROOT / "terraform/infra/outputs.tf").read_text()

    assert 'output "bastion_downstream_networks"' in output_source
    assert "vmware_network_id = data.vsphere_network.this[nic.network].id" in output_source
    assert "mac_address       = module.vm[var.bastion_service_node].mac_addresses[index]" in output_source
    assert "nic_index         = index" in output_source
