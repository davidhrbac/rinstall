from pathlib import Path

import yaml

from lib.env_config import expand_env
from lib.ssh_config import node_ssh_target


EXAMPLE_CONFIG = Path(__file__).parents[1] / "envs/example/env.yaml"


def raw_config():
    return yaml.safe_load(EXAMPLE_CONFIG.read_text())


def downstream_network(vlan, subnet, vmware_network=None):
    return {
        "vlan": vlan,
        "vmware_network": vmware_network or f"DOWNSTREAM_VLAN_{vlan}",
        "subnet": subnet,
        "bastion_address": 2,
        "gateway": 1,
        "dhcp": {"start": 4, "end": -2, "lease_time": "12h"},
    }


def host_contract(config):
    return {
        name: {
            "role": node["role"],
            "ip": node["ip"],
            "ssh_target": node_ssh_target(node),
            "nics": [
                {
                    "network": nic["network"],
                    "ip": nic.get("ip"),
                    "prefix": nic.get("prefix"),
                }
                for nic in node["nics"]
            ],
        }
        for name, node in config["nodes"].items()
    }


def test_expanded_config_topology_contract_without_downstream_networks():
    config = raw_config()
    config["nodes"]["bastion1"]["nics"][1]["cidr"] = "192.0.2.10/24"

    expanded = expand_env(config)

    assert host_contract(expanded) == {
        "bastion1": {
            "role": "bastion",
            "ip": "10.14.17.4",
            "ssh_target": "192.0.2.10",
            "nics": [
                {"network": "customer", "ip": "10.14.17.4", "prefix": 28},
                {"network": "management", "ip": "192.0.2.10", "prefix": 24},
            ],
        },
        "prom1": {
            "role": "prometheus",
            "ip": "10.14.17.6",
            "ssh_target": "10.14.17.6",
            "nics": [
                {"network": "customer", "ip": "10.14.17.6", "prefix": 28},
            ],
        },
        "rancher1": {
            "role": "rancher",
            "ip": "10.14.17.11",
            "ssh_target": "10.14.17.11",
            "nics": [
                {"network": "customer", "ip": "10.14.17.11", "prefix": 28},
            ],
        },
        "rancher2": {
            "role": "rancher",
            "ip": "10.14.17.12",
            "ssh_target": "10.14.17.12",
            "nics": [
                {"network": "customer", "ip": "10.14.17.12", "prefix": 28},
            ],
        },
        "rancher3": {
            "role": "rancher",
            "ip": "10.14.17.13",
            "ssh_target": "10.14.17.13",
            "nics": [
                {"network": "customer", "ip": "10.14.17.13", "prefix": 28},
            ],
        },
    }
    assert list(expanded["nodes"]) == ["bastion1", "prom1", "rancher1", "rancher2", "rancher3"]
    assert expanded["bastion"]["downstream_networks"] == []
    assert expanded["rke2"]["primary_node"] == "rancher1"
    assert expanded["nodes"]["rancher2"]["rke2_server"] == "https://10.14.17.11:9345"
    assert expanded["nodes"]["rancher3"]["rke2_server"] == "https://10.14.17.11:9345"


def test_expanded_config_topology_contract_for_one_downstream_network():
    config = raw_config()
    config["bastion"]["downstream_networks"] = [
        downstream_network(565, "10.20.56.32/27"),
    ]

    downstream = expand_env(config)["bastion"]["downstream_networks"][0]

    assert downstream == {
        "vlan": 565,
        "vmware_network": "DOWNSTREAM_VLAN_565",
        "subnet": "10.20.56.32/27",
        "bastion_address": "10.20.56.34",
        "gateway": "10.20.56.33",
        "dhcp": {
            "start": "10.20.56.36",
            "end": "10.20.56.61",
            "lease_time": "12h",
        },
        "prefix": 27,
        "netmask": "255.255.255.224",
        "interface_name": "vlan565",
        "connection_uuid": "7f4fe28e-3c7d-5367-8428-1de66868c344",
    }


def test_expanded_config_topology_contract_for_multiple_and_absolute_addresses():
    relative = raw_config()
    relative["bastion"]["downstream_networks"] = [
        downstream_network(565, "10.20.56.32/27"),
        downstream_network(566, "10.20.56.64/27"),
    ]
    absolute = raw_config()
    absolute["bastion"]["downstream_networks"] = [
        downstream_network(565, "10.20.56.32/27"),
        {
            "vlan": 566,
            "vmware_network": "DOWNSTREAM_VLAN_566",
            "subnet": "10.20.56.64/27",
            "bastion_address": "10.20.56.66",
            "gateway": "10.20.56.65",
            "dhcp": {
                "start": "10.20.56.68",
                "end": "10.20.56.93",
                "lease_time": "12h",
            },
        },
    ]

    relative_networks = expand_env(relative)["bastion"]["downstream_networks"]
    absolute_networks = expand_env(absolute)["bastion"]["downstream_networks"]

    assert relative_networks == absolute_networks
    assert [network["interface_name"] for network in relative_networks] == ["vlan565", "vlan566"]
    assert [network["bastion_address"] for network in relative_networks] == [
        "10.20.56.34",
        "10.20.56.66",
    ]
    assert [network["dhcp"]["start"] for network in relative_networks] == [
        "10.20.56.36",
        "10.20.56.68",
    ]
