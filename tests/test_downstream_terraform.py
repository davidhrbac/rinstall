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
        "downstream_subnet": "10.20.121.32/27",
        "downstream_bastion_address": "10.20.121.34",
        "downstream_gateway": "10.20.121.33",
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


def base_output(rendered):
    return {
        "bastion_base_nics": {
            "value": [
                {
                    "nic_index": index,
                    "vmware_network": rendered["networks"][nic["network"]],
                }
                for index, nic in enumerate(rendered["nodes"]["bastion1"]["nics"])
                if nic.get("downstream_vlan") is None
            ]
        }
    }


def downstream_output(rendered):
    bastion = rendered["nodes"]["bastion1"]
    return {
        "bastion_downstream_networks": {
            "value": {
                f"vlan{nic['downstream_vlan']}": {
                    "vlan": nic["downstream_vlan"],
                    "nic_index": index,
                    "vmware_network": rendered["networks"][nic["network"]],
                    "subnet": nic["downstream_subnet"],
                    "bastion_address": nic["downstream_bastion_address"],
                    "gateway": nic["downstream_gateway"],
                }
                for index, nic in enumerate(bastion["nics"])
                if nic.get("downstream_vlan") is not None
            }
        }
    }


def test_base_nic_topology_guard_allows_unchanged_and_appended_downstream_nics():
    base = render_with()
    one_downstream = render_with(downstream_network(565, 165))
    two_downstream = render_with(downstream_network(565, 165), downstream_network(610, 166))

    RENDERER.validate_bastion_base_nics(base, base_output(base))
    RENDERER.validate_bastion_base_nics(one_downstream, base_output(base))
    RENDERER.validate_bastion_base_nics(two_downstream, base_output(base))


def test_base_nic_topology_guard_rejects_swap_and_network_replacement():
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    base = RENDERER.render(expand_env(config))
    existing = base_output(base)

    swapped_config = yaml.safe_load(EXAMPLE_ENV.read_text())
    swapped_config["nodes"]["bastion1"]["nics"] = list(reversed(swapped_config["nodes"]["bastion1"]["nics"]))
    swapped = RENDERER.render(expand_env(swapped_config))
    with pytest.raises(SystemExit, match="base NIC order or VMware network identity changed"):
        RENDERER.validate_bastion_base_nics(swapped, existing)

    replaced_config = yaml.safe_load(EXAMPLE_ENV.read_text())
    replaced_config["infra"]["networks"]["customer"] = "REPLACED_CUSTOMER_PORTGROUP"
    replaced = RENDERER.render(expand_env(replaced_config))
    with pytest.raises(SystemExit, match="base NIC order or VMware network identity changed"):
        RENDERER.validate_bastion_base_nics(replaced, existing)


def test_base_nic_topology_guard_allows_dhcp_only_changes_and_fresh_output():
    original = downstream_network(565, 165)
    changed = downstream_network(565, 165)
    changed["dhcp"]["start"] = 5
    rendered = render_with(changed)

    RENDERER.validate_bastion_base_nics(rendered, {})
    RENDERER.validate_bastion_base_nics(rendered, base_output(rendered))
    assert render_with(original) == rendered


def test_base_nic_topology_guard_rejects_existing_output_without_base_topology():
    with pytest.raises(SystemExit, match="has no bastion_base_nics topology"):
        RENDERER.validate_bastion_base_nics(render_with(), {"nodes": {}})


def test_rejects_downstream_removal_and_attachment_reorder():
    rendered = render_with(downstream_network(121), downstream_network(122))
    existing = downstream_output(rendered)

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


def test_downstream_addressing_identity_is_persisted_and_dhcp_only_changes_are_allowed():
    original = render_with(downstream_network(121))
    existing = downstream_output(original)

    changed_dhcp = downstream_network(121)
    changed_dhcp["dhcp"] = {"start": 5, "end": -3, "lease_time": "24h"}
    RENDERER.validate_no_downstream_removal(render_with(changed_dhcp), existing)

    equivalent = downstream_network(121)
    equivalent["bastion_address"] = "10.20.121.34"
    equivalent["gateway"] = "10.20.121.33"
    RENDERER.validate_no_downstream_removal(render_with(equivalent), existing)

    assert original["nodes"]["bastion1"]["nics"][2]["downstream_subnet"] == "10.20.121.32/27"
    assert original["nodes"]["bastion1"]["nics"][2]["downstream_bastion_address"] == "10.20.121.34"
    assert original["nodes"]["bastion1"]["nics"][2]["downstream_gateway"] == "10.20.121.33"


def test_fresh_and_appended_downstream_networks_are_allowed():
    first = render_with(downstream_network(121))
    second = render_with(downstream_network(121), downstream_network(122))

    RENDERER.validate_no_downstream_removal(first, {})
    RENDERER.validate_no_downstream_removal(second, downstream_output(first))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("subnet", "10.20.122.32/27", "addressing"),
        ("bastion_address", "10.20.121.35", "addressing"),
        ("gateway", "10.20.121.35", "addressing"),
    ],
)
def test_rejects_existing_downstream_addressing_changes(field, value, message):
    original = render_with(downstream_network(121))
    existing = downstream_output(original)
    changed = downstream_network(121)
    changed[field] = value

    with pytest.raises(SystemExit, match=message):
        RENDERER.validate_no_downstream_removal(render_with(changed), existing)


def test_rejects_incomplete_non_empty_downstream_lifecycle_output():
    rendered = render_with(downstream_network(121))
    existing = downstream_output(rendered)
    del existing["bastion_downstream_networks"]["value"]["vlan121"]["gateway"]

    with pytest.raises(SystemExit, match="lifecycle identity is incomplete"):
        RENDERER.validate_no_downstream_removal(rendered, existing)

    with pytest.raises(SystemExit, match="bastion_downstream_networks output is invalid"):
        RENDERER.validate_no_downstream_removal(
            rendered,
            {"bastion_downstream_networks": {"value": []}},
        )


def test_terraform_output_exposes_provider_network_and_mac_identity():
    output_source = (ROOT / "terraform/infra/outputs.tf").read_text()

    assert 'output "bastion_downstream_networks"' in output_source
    assert "vmware_network_id = data.vsphere_network.this[nic.network].id" in output_source
    assert "mac_address       = try(data.vsphere_virtual_machine.bastion_fresh[0].network_interfaces[index].mac_address, null)" in output_source
    assert "nic_index         = index" in output_source
    assert "subnet            = nic.downstream_subnet" in output_source
    assert "bastion_address   = nic.downstream_bastion_address" in output_source
    assert "gateway           = nic.downstream_gateway" in output_source


def test_terraform_output_exposes_ordered_base_nic_topology():
    output_source = (ROOT / "terraform/infra/outputs.tf").read_text()

    assert 'output "bastion_base_nics"' in output_source
    assert "if try(nic.downstream_vlan, null) == null" in output_source
    assert "nic_index      = index" in output_source
    assert "vmware_network = var.networks[nic.network]" in output_source


def test_addressing_guard_runs_before_terraform_plan_and_apply():
    makefile = (ROOT / "Makefile").read_text()

    assert "render-infra-vars-checked: infra-output config-validate" in makefile
    assert "infra-plan:" in makefile and "render-infra-vars-checked" in makefile
    assert "infra-apply:" in makefile and "render-infra-vars-checked" in makefile
    assert "render-infra-tfvars.py --env $(ENV_CONFIG) --out $(INFRA_TFVARS) --existing-infra-output" in makefile


def test_fresh_bastion_view_waits_for_vm_update_and_topology_changes():
    main_source = (ROOT / "terraform/infra/main.tf").read_text()
    module_source = (ROOT / "terraform/infra/modules/vsphere-vm/main.tf").read_text()
    module_variables = (ROOT / "terraform/infra/modules/vsphere-vm/variables.tf").read_text()

    assert 'resource "time_sleep" "nic_settle"' in module_source
    assert 'create_duration = "5s"' in module_source
    assert "replace_triggered_by = [vsphere_virtual_machine.this]" in module_source
    assert "depends_on = [vsphere_virtual_machine.this]" in module_source
    assert 'variable "settle_after_change"' in module_variables
    assert "settle_after_change = each.key == var.bastion_service_node" in main_source
    assert 'data "vsphere_virtual_machine" "bastion_fresh"' in main_source
    assert "depends_on = [module.vm]" in main_source
    assert 'resource "time_sleep"' not in main_source
    assert "bastion_vm_mac_topology" not in main_source
    assert "change_version" not in main_source


def test_fresh_bastion_output_guards_missing_mac_and_keeps_no_networks_path():
    main_source = (ROOT / "terraform/infra/main.tf").read_text()
    module_source = (ROOT / "terraform/infra/modules/vsphere-vm/main.tf").read_text()
    output_source = (ROOT / "terraform/infra/outputs.tf").read_text()

    assert "count = var.settle_after_change ? 1 : 0" in module_source
    assert "count         = length(local.bastion_downstream_nics) > 0 ? 1 : 0" in main_source
    assert "precondition" in output_source
    assert "fresh bastion vSphere data has no matching MAC/network" in output_source


def test_fresh_bastion_output_validates_network_identity_and_reuses_ordered_macs():
    main_source = (ROOT / "terraform/infra/main.tf").read_text()
    output_source = (ROOT / "terraform/infra/outputs.tf").read_text()

    assert "network_id          = try(data.vsphere_virtual_machine.bastion_fresh[0].network_interfaces[index].network_id, null)" in main_source
    assert "expected_network_id = data.vsphere_network.this[nic.network].id" in main_source
    assert "network.network_id == network.expected_network_id" in output_source
    assert "network_interfaces[*].mac_address" in main_source
    assert "mac_addresses      = name == var.bastion_service_node ? local.bastion_mac_addresses : vm.mac_addresses" in output_source


def test_nodes_output_reuses_fresh_bastion_macs_only_when_downstream_exists():
    main_source = (ROOT / "terraform/infra/main.tf").read_text()
    output_source = (ROOT / "terraform/infra/outputs.tf").read_text()

    assert "bastion_mac_addresses = length(local.bastion_downstream_nics) > 0 ? data.vsphere_virtual_machine.bastion_fresh[0].network_interfaces[*].mac_address : module.vm[var.bastion_service_node].mac_addresses" in main_source
    assert "mac_addresses      = name == var.bastion_service_node ? local.bastion_mac_addresses : vm.mac_addresses" in output_source
    assert "for index, nic in var.nodes[var.bastion_service_node].nics" in output_source
