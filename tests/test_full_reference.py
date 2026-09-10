from pathlib import Path
import json

from lib.env_config import load_env
from lib.topology import (
    render_topology_json,
    render_topology_markdown,
    render_topology_connectivity_mermaid,
    render_topology_infrastructure_mermaid,
    render_topology_svg,
    build_desired_topology,
)


ROOT = Path(__file__).parents[1]
REFERENCE_CONFIG = ROOT / "examples/full/config.yaml"
REFERENCE_OUTPUT = REFERENCE_CONFIG.parent


def reference_topology():
    return build_desired_topology(load_env(REFERENCE_CONFIG))


def test_full_reference_expands_static_management_and_two_downstreams():
    config = load_env(REFERENCE_CONFIG)

    assert list(config["nodes"]) == ["bastion1", "prom1", "rancher1", "rancher2", "rancher3"]
    assert config["nodes"]["bastion1"]["nics"][1]["cidr"] == "192.0.2.10/24"
    assert config["nodes"]["bastion1"]["nics"][1]["ip"] == "192.0.2.10"
    assert config["nodes"]["bastion1"]["ssh_ip"] == "192.0.2.10"
    assert [(item["vlan"], item["subnet"], item["bastion_address"]) for item in config["bastion"]["downstream_networks"]] == [
        (565, "203.0.113.32/27", "203.0.113.34"),
        (566, "203.0.113.64/27", "203.0.113.66"),
    ]


def test_full_reference_topology_has_expected_same_vlan_dns_and_ssh_rules():
    topology = reference_topology()
    dns_rules = [rule for rule in topology.connectivity_rules if rule.id.startswith("downstream-dns:")]
    ssh_rules = [rule for rule in topology.connectivity_rules if rule.id.startswith("rancher-downstream-ssh:")]

    assert len(dns_rules) == len(ssh_rules) == 2
    assert [rule.destination.resolved[0].address for rule in dns_rules] == [
        "203.0.113.34",
        "203.0.113.66",
    ]
    assert [rule.destination.resolved[0].address for rule in ssh_rules] == [
        "203.0.113.32/27",
        "203.0.113.64/27",
    ]
    assert all(len(rule.source.resolved) == 3 for rule in ssh_rules)
    assert all(rule.destination_ports == (22,) for rule in ssh_rules)


def test_full_reference_bastion_is_multihomed_and_core_nodes_use_customer_only():
    topology = reference_topology()
    bastion_interfaces = [interface for interface in topology.interfaces if interface.host == "bastion1"]
    core_interfaces = [interface for interface in topology.interfaces if interface.host != "bastion1"]

    assert [interface.network for interface in bastion_interfaces] == [
        "customer",
        "management",
        "downstream:vlan565",
        "downstream:vlan566",
    ]
    assert all(interface.network == "customer" for interface in core_interfaces)


def test_full_reference_generated_outputs_are_deterministic_and_sanitized():
    topology = reference_topology()
    expected = {
        "topology.json": render_topology_json(topology),
        "topology.md": render_topology_markdown(topology),
        "topology.mmd": render_topology_infrastructure_mermaid(topology),
        "connectivity.mmd": render_topology_connectivity_mermaid(topology),
        "topology.svg": render_topology_svg(topology),
    }

    assert all((REFERENCE_OUTPUT / name).read_text() == content for name, content in expected.items())
    assert json.loads(expected["topology.json"])["metadata"]["environment_id"] == "full-example"
    assert all(
        secret not in "".join(expected.values())
        for secret in ("EXAMPLE-ONLY-DUMMY-RKE2-TOKEN", "TF_VAR_vsphere_password", "private_key")
    )


def test_full_reference_outputs_show_both_downstream_visual_attachments():
    markdown = (REFERENCE_OUTPUT / "topology.md").read_text()
    mermaid = (REFERENCE_OUTPUT / "topology.mmd").read_text()
    connectivity = (REFERENCE_OUTPUT / "connectivity.mmd").read_text()

    assert "VLAN 565" in markdown and "VLAN 566" in markdown
    assert "203.0.113.34" in markdown and "203.0.113.66" in markdown
    assert "| prom1 |" in markdown and "| not attached |" in markdown
    assert mermaid.count('-->|"TCP/22 SSH"|') == 0
    assert connectivity.count('-->|"TCP/22 SSH"|') == 1
    assert connectivity.count('-->|"TCP/UDP 53 DNS"|') == 1
    svg = (REFERENCE_OUTPUT / "topology.svg").read_text()
    assert 'viewBox="0 0 1200 ' in svg
    assert "<svg " in markdown
    assert "TCP/22" not in svg and "DNS" not in svg and "DHCP" not in svg
    assert "network_downstream_vlan565" in mermaid
    assert "network_downstream_vlan566" in mermaid
