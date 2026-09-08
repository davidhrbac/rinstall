from pathlib import Path

import pytest
import yaml

from lib.env_config import expand_env, resolve_ipv4_address


EXAMPLE_ENV = Path(__file__).parents[1] / "envs/example/env.yaml"


def raw_example():
    return yaml.safe_load(EXAMPLE_ENV.read_text())


def downstream_network(vlan=121, subnet="10.20.121.32/27", vmware_network=None):
    return {
        "vlan": vlan,
        "vmware_network": vmware_network or f"DOWNSTREAM_VLAN_{vlan}",
        "subnet": subnet,
        "bastion_address": 2,
        "gateway": 1,
        "dhcp": {"start": 4, "end": -2, "lease_time": "12h"},
    }


def resolved_with(*networks):
    config = raw_example()
    config["bastion"]["downstream_networks"] = list(networks)
    return expand_env(config)


def test_omitted_downstream_networks_defaults_to_empty_list():
    assert expand_env(raw_example())["bastion"]["downstream_networks"] == []


@pytest.mark.parametrize(
    ("subnet", "expected"),
    [
        (
            "10.20.121.32/27",
            {
                "gateway": "10.20.121.33",
                "bastion_address": "10.20.121.34",
                "start": "10.20.121.36",
                "end": "10.20.121.61",
                "prefix": 27,
            },
        ),
        (
            "10.20.121.32/28",
            {
                "gateway": "10.20.121.33",
                "bastion_address": "10.20.121.34",
                "start": "10.20.121.36",
                "end": "10.20.121.45",
                "prefix": 28,
            },
        ),
    ],
)
def test_resolves_relative_addresses_for_small_subnets(subnet, expected):
    network = resolved_with(downstream_network(subnet=subnet))["bastion"]["downstream_networks"][0]

    assert network["gateway"] == expected["gateway"]
    assert network["bastion_address"] == expected["bastion_address"]
    assert network["dhcp"]["start"] == expected["start"]
    assert network["dhcp"]["end"] == expected["end"]
    assert network["prefix"] == expected["prefix"]
    assert network["interface_name"] == "vlan121"


def test_resolves_absolute_addresses():
    network = downstream_network()
    network["gateway"] = "10.20.121.33"
    network["bastion_address"] = "10.20.121.34"
    network["dhcp"]["start"] = "10.20.121.36"
    network["dhcp"]["end"] = "10.20.121.61"

    resolved = resolved_with(network)["bastion"]["downstream_networks"][0]

    assert resolved["gateway"] == "10.20.121.33"
    assert resolved["bastion_address"] == "10.20.121.34"
    assert resolved["dhcp"]["start"] == "10.20.121.36"
    assert resolved["dhcp"]["end"] == "10.20.121.61"


@pytest.mark.parametrize("value", [0, 31, -31])
def test_rejects_zero_and_out_of_range_relative_addresses(value):
    network = downstream_network()
    network["bastion_address"] = value

    with pytest.raises(SystemExit, match="bastion_address"):
        resolved_with(network)


@pytest.mark.parametrize("value", [True, 2.0, "4"])
def test_rejects_ambiguous_relative_address_values(value):
    network = downstream_network()
    network["bastion_address"] = value

    with pytest.raises(SystemExit, match="bastion_address"):
        resolved_with(network)


@pytest.mark.parametrize("value", [True, 121.0, "121", 0, 4095])
def test_rejects_invalid_vlan_values(value):
    with pytest.raises(SystemExit, match="vlan must be an integer from 1 through 4094"):
        resolved_with(downstream_network(vlan=value))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("not-an-ip", "absolute IPv4 address"),
        ("10.20.121.32", "network address"),
        ("10.20.121.63", "broadcast address"),
        ("10.20.122.34", "outside"),
        ("2001:db8::1", "IPv4"),
    ],
)
def test_rejects_invalid_absolute_addresses(value, message):
    network = downstream_network()
    network["bastion_address"] = value

    with pytest.raises(SystemExit, match=message):
        resolved_with(network)


@pytest.mark.parametrize("subnet", ["10.20.121.33/27", "10.20.121.32/31", "10.20.121.32/32", "2001:db8::/64"])
def test_rejects_unsupported_or_noncanonical_subnets(subnet):
    with pytest.raises(SystemExit, match="subnet"):
        resolved_with(downstream_network(subnet=subnet))


def test_rejects_gateway_bastion_collision():
    network = downstream_network()
    network["bastion_address"] = 1

    with pytest.raises(SystemExit, match="gateway must differ from bastion_address"):
        resolved_with(network)


@pytest.mark.parametrize(("field", "value"), [("gateway", 4), ("bastion_address", 4)])
def test_rejects_infrastructure_addresses_inside_dhcp_pool(field, value):
    network = downstream_network()
    network[field] = value

    with pytest.raises(SystemExit, match=rf"{field} must not be inside the DHCP pool"):
        resolved_with(network)


def test_rejects_reversed_dhcp_pool():
    network = downstream_network()
    network["dhcp"] = {"start": -2, "end": 4, "lease_time": "12h"}

    with pytest.raises(SystemExit, match="dhcp.start must be less than or equal to dhcp.end"):
        resolved_with(network)


@pytest.mark.parametrize("lease_time", ["", "0h", "12", "12hours", 12, True])
def test_rejects_unsupported_lease_times(lease_time):
    network = downstream_network()
    network["dhcp"]["lease_time"] = lease_time

    with pytest.raises(SystemExit, match="lease_time"):
        resolved_with(network)


def test_rejects_duplicate_vlan_and_vmware_network():
    with pytest.raises(SystemExit, match="duplicates VLAN 121"):
        resolved_with(downstream_network(), downstream_network(vmware_network="ANOTHER_NETWORK"))

    with pytest.raises(SystemExit, match="duplicates VMware network"):
        resolved_with(downstream_network(), downstream_network(vlan=122, vmware_network="DOWNSTREAM_VLAN_121"))


def test_rejects_overlapping_downstream_subnets():
    with pytest.raises(SystemExit, match="overlaps downstream subnet"):
        resolved_with(
            downstream_network(),
            downstream_network(vlan=122, subnet="10.20.121.48/28"),
        )


def test_rejects_overlap_with_local_vlan():
    with pytest.raises(SystemExit, match="overlaps local VLAN"):
        resolved_with(downstream_network(subnet="10.14.17.0/28"))


def test_reusable_resolver_counts_from_both_ends():
    from ipaddress import ip_network

    network = ip_network("10.20.121.32/27")

    assert resolve_ipv4_address(network, 1, "address") == "10.20.121.33"
    assert resolve_ipv4_address(network, -1, "address") == "10.20.121.62"
