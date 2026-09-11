from pathlib import Path
import json

from lib.env_config import load_env
from lib.topology import (
    render_topology_json,
    render_topology_architecture_mermaid,
    render_topology_markdown,
    render_topology_ascii_overview,
    render_topology_infrastructure_mermaid,
    render_topology_network_dot,
    render_topology_network_mermaid,
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


def test_full_reference_v2_derives_operational_entities_without_extra_config():
    config = load_env(REFERENCE_CONFIG)
    topology = build_desired_topology(config)
    endpoints = {endpoint.id: endpoint for endpoint in topology.endpoints}
    paths = {path.destination.id: path for path in topology.access_paths}

    assert config["schema_version"] == 1
    assert topology.metadata.topology_schema_version == 2
    assert topology.clusters[0].member_host_ids == ("rancher1", "rancher2", "rancher3")
    assert topology.clusters[0].primary_host_id == "rancher1"
    assert endpoints["endpoint:rancher"].name == "rancher.full-example.example.invalid"
    assert endpoints["endpoint:rancher"].resolutions[0].addresses == (
        "198.51.100.11",
        "198.51.100.12",
        "198.51.100.13",
    )
    assert endpoints["endpoint:rancher"].resolutions[1].addresses == ()
    assert endpoints["endpoint:ssh-jump"].name == "example-operator-jump"
    assert endpoints["endpoint:ssh-jump"].resolutions[0].addresses == ()
    assert [hop.id for hop in paths["rancher1"].hops] == [
        "endpoint:ssh-jump",
        "bastion1",
    ]
    assert [consumer.network_id for consumer in topology.downstream_consumers] == [
        "downstream:vlan565",
        "downstream:vlan566",
    ]
    assert topology.deployment_context.vsphere.datacenter == "EXAMPLE_DATACENTER"
    assert topology.deployment_context.terraform_backend.state_name == "full-example-infra"
    serialized = render_topology_json(topology)
    assert "EXAMPLE-ONLY-DUMMY-RKE2-TOKEN" not in serialized
    assert "VIP" not in " ".join(
        address
        for resolution in endpoints["endpoint:rancher"].resolutions
        for address in resolution.addresses
    )


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
        "architecture.mmd": render_topology_architecture_mermaid(topology),
        "topology.md": render_topology_markdown(topology),
        "topology.txt": render_topology_ascii_overview(topology),
        "topology.mmd": render_topology_infrastructure_mermaid(topology),
        "network-topology.dot": render_topology_network_dot(topology),
        "network-topology.mmd": render_topology_network_mermaid(topology),
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

    assert "VLAN 565" in markdown and "VLAN 566" in markdown
    assert "203.0.113.34" in markdown and "203.0.113.66" in markdown
    assert "| Monitoring: prom1 |" in markdown
    assert "TCP/22" not in mermaid and "DNS" not in mermaid and "DHCP" not in mermaid
    network_mermaid = (REFERENCE_OUTPUT / "network-topology.mmd").read_text()
    assert "```mermaid\n" + network_mermaid.rstrip() + "\n```" in markdown
    assert "<svg" not in markdown
    assert "network_downstream_vlan565" in mermaid
    assert "network_downstream_vlan566" in mermaid
    assert not (REFERENCE_OUTPUT / "connectivity.mmd").exists()
    assert not (REFERENCE_OUTPUT / "topology.svg").exists()


def test_full_reference_support_document_uses_canonical_v2_presentation():
    markdown = (REFERENCE_OUTPUT / "topology.md").read_text()
    text = (REFERENCE_OUTPUT / "topology.txt").read_text()

    expected_sections = [
        "## Architecture Map",
        "## Network Topology",
        "## Endpoint Resolution",
        "## Environment",
        "## Deployment Context",
        "## Hosts and Clusters",
        "## Networks",
        "## Key Connectivity",
        "## Resolved Connectivity",
        "## Details",
        "## Notes",
    ]
    assert [markdown.index(section) for section in expected_sections] == sorted(
        markdown.index(section) for section in expected_sections
    )
    assert "## Infrastructure Topology" not in markdown
    assert "Network Topology — Mermaid" not in markdown
    assert "Network Topology — Graphviz" not in markdown
    assert "network-topology.svg" not in markdown
    assert "external VIP/LB - unresolved" in markdown
    assert "internal / rinstall DNS" in markdown
    assert "Rancher endpoint" in markdown
    assert "internal / rinstall DNS: 198.51.100.11" in markdown
    assert "endpoint:" not in markdown
    assert all(category in markdown for category in (
        "### Administrative", "### Deployment", "### Core services",
        "### RKE2 / Rancher", "### Downstream",
    ))
    assert "same-L2 service intent" in markdown
    assert "EXAMPLE_DATACENTER" in markdown
    assert "private_key" not in markdown
    assert "TF_HTTP_PASSWORD" not in markdown
    assert "split-horizon DNS" in text
    assert all(category in text for category in (
        "Administrative", "Deployment", "Core services", "RKE2 / Rancher", "Downstream",
    ))
