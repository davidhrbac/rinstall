from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import pytest
import yaml

from lib.bastion_network import (
    downstream_connection_needs_activation,
    load_downstream_network_output,
    profile_rename_needed,
    route_needs_replacement,
)
from lib.env_config import expand_env


ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ROOT / "envs/example/env.yaml"
TEMPLATES = ROOT / "pyinfra/templates"


def downstream_network(vlan=121):
    return {
        "vlan": vlan,
        "vmware_network": f"DOWNSTREAM_VLAN_{vlan}",
        "subnet": f"10.20.{vlan}.32/27",
        "bastion_address": 2,
        "gateway": 1,
        "dhcp": {"start": 4, "end": -2, "lease_time": "12h"},
    }


def config_with(*networks):
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["bastion"]["downstream_networks"] = list(networks)
    return expand_env(config)


def render_template(name, **data):
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return environment.get_template(name).render(**data)


def terraform_output(config, mac="00:50:56:aa:bb:cc"):
    network = config["bastion"]["downstream_networks"][0]
    return {
        "bastion_downstream_networks": {
            "value": {
                network["interface_name"]: {
                    "vlan": network["vlan"],
                    "vmware_network": network["vmware_network"],
                    "vmware_network_id": "network-121",
                    "mac_address": mac,
                    "nic_index": 2,
                    "attachment_order": 3,
                }
            }
        }
    }


def test_loads_synthetic_network_to_mac_output(tmp_path):
    import json

    config = config_with(downstream_network())
    output_path = tmp_path / "infra-output.json"
    output_path.write_text(json.dumps(terraform_output(config)))

    output = load_downstream_network_output(output_path, config["bastion"]["downstream_networks"])

    assert output["vlan121"]["mac_address"] == "00:50:56:aa:bb:cc"
    assert output["vlan121"]["vmware_network_id"] == "network-121"


def test_rejects_missing_or_removed_network_output(tmp_path):
    import json

    config = config_with(downstream_network())
    output_path = tmp_path / "infra-output.json"
    output_path.write_text(json.dumps({"bastion_downstream_networks": {"value": {}}}))
    with pytest.raises(SystemExit, match="run infra-apply"):
        load_downstream_network_output(output_path, config["bastion"]["downstream_networks"])

    output_path.write_text(json.dumps(terraform_output(config)))
    with pytest.raises(SystemExit, match="removal is not supported"):
        load_downstream_network_output(output_path, [])


def test_renders_persistent_mac_matched_kernel_name():
    rendered = render_template(
        "downstream-network.link.j2",
        mac_address="00:50:56:aa:bb:cc",
        interface_name="vlan121",
    )

    assert "MACAddress=00:50:56:aa:bb:cc" in rendered
    assert "Name=vlan121" in rendered


def test_renders_complete_networkmanager_profile_without_gateway():
    downstream = config_with(downstream_network())["bastion"]["downstream_networks"][0]
    rendered = render_template(
        "downstream-network.nmconnection.j2",
        downstream=downstream,
        mac_address="00:50:56:aa:bb:cc",
    )

    assert "type=ethernet" in rendered
    assert "interface-name=vlan121" in rendered
    assert "mac-address=00:50:56:aa:bb:cc" in rendered
    assert "address1=10.20.121.34/27" in rendered
    assert "never-default=true" in rendered
    assert "gateway=" not in rendered


def test_renders_interface_scoped_dhcp_without_dns_option():
    config = config_with(downstream_network())
    rendered = render_template("dnsmasq-dhcp.conf.j2", config=config)

    assert "dhcp-authoritative" in rendered
    assert "dhcp-ignore=tag:!vlan121" in rendered
    assert "dhcp-range=tag:vlan121,10.20.121.36,10.20.121.61,255.255.255.224,12h" in rendered
    assert "dhcp-option=tag:vlan121,option:router,10.20.121.33" in rendered
    assert "option:dns-server" not in rendered
    assert "option:6" not in rendered
    assert "interface=*" not in rendered


def test_omits_authoritative_dhcp_without_downstream_networks():
    rendered = render_template("dnsmasq-dhcp.conf.j2", config=config_with())

    assert "dhcp-authoritative" not in rendered
    assert "dhcp-range=" not in rendered


def test_route_comparison_skips_equal_normalized_route_and_replaces_changed_route():
    desired = "192.0.2.128/26 192.0.2.1"

    assert route_needs_replacement("  192.0.2.128/26   192.0.2.1\n", desired) is False
    assert route_needs_replacement("192.0.2.192/26 192.0.2.1", desired) is True
    assert route_needs_replacement("", desired) is True


def test_route_replacement_preserves_unrelated_static_routes():
    from lib.bastion_network import reconcile_ipv4_routes

    current = "198.51.100.0/24 192.0.2.2, 192.0.2.128/26 192.0.2.9"

    assert reconcile_ipv4_routes(current, "192.0.2.128/26 192.0.2.1") == (
        "198.51.100.0/24 192.0.2.2, 192.0.2.128/26 192.0.2.1"
    )


def test_profile_rename_comparison_skips_identical_state_and_rejects_collision():
    assert profile_rename_needed("uuid-1", "uuid-1", "ens224", "mgmt") is False
    assert profile_rename_needed("uuid-1", "", "ens224", "mgmt") is True
    with pytest.raises(SystemExit, match="different connection"):
        profile_rename_needed("uuid-1", "uuid-2", "ens224", "mgmt")


def test_identical_downstream_connection_state_needs_no_activation():
    downstream = config_with(downstream_network())["bastion"]["downstream_networks"][0]
    current_addresses = "3: vlan121 inet 10.20.121.34/27 brd 10.20.121.63 scope global vlan121"

    assert (
        downstream_connection_needs_activation(
            downstream["connection_uuid"],
            current_addresses,
            downstream,
        )
        is False
    )
    assert downstream_connection_needs_activation("another-uuid", current_addresses, downstream) is True
