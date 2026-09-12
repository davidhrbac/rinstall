import ast
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from lib.env_config import expand_env, load_env
from lib.topology import (
    ADMINISTRATIVE,
    CONFIGURED,
    CORE_SERVICE,
    DNS_NAME,
    DERIVED,
    DEPLOYMENT,
    DESIRED_ONLY,
    DOWNSTREAM,
    EXTERNALLY_MANAGED,
    EXTERNAL,
    EXTERNAL_ROUTING_DEPENDENCY,
    EXTERNAL_UNRESOLVED,
    IP_ADDRESS,
    L2_SERVICE_INTENT,
    MONITORING_HOST_ONLY,
    NETWORK_CIDR,
    PARTIAL,
    REFERENCED_EXTERNAL,
    RESOLVED,
    RINSTALL_ARCHITECTURE,
    RINSTALL_CONFIGURED,
    RINSTALL_MANAGED,
    RKE2_RANCHER,
    RUNTIME_SUPPLIED,
    SYMBOLIC,
    _mermaid_id,
    SYMBOLIC_ADDRESS,
    UNVERIFIED,
    EntityReference,
    build_desired_topology,
    render_topology_json,
    render_topology_architecture_mermaid,
    render_topology_markdown,
    render_topology_ascii_overview,
    render_topology_network_mermaid,
    validate_topology,
)


ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "envs/example/env.yaml"
FULL_CONFIG = ROOT / "examples/full/config.yaml"
RENDER_TOPOLOGY = ROOT / "scripts/render-topology.py"


def raw_config():
    config = yaml.safe_load(EXAMPLE_CONFIG.read_text())
    config["nodes"]["bastion1"]["nics"][1]["cidr"] = "192.0.2.10/24"
    return config


def downstream_network(vlan, subnet):
    return {
        "vlan": vlan,
        "vmware_network": f"DOWNSTREAM_VLAN_{vlan}",
        "subnet": subnet,
        "bastion_address": 2,
        "gateway": 1,
        "dhcp": {"start": 4, "end": -2, "lease_time": "12h"},
    }


def topology_with(*downstreams):
    config = raw_config()
    config["bastion"]["downstream_networks"] = list(downstreams)
    return build_desired_topology(expand_env(config))


def test_existing_config_without_optional_vsphere_fields_builds_and_renders(tmp_path):
    config = raw_config()
    del config["infra"]["vsphere"]["clone_timeout"]
    del config["infra"]["vsphere"]["allow_unverified_ssl"]
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))

    expanded = load_env(config_path)
    topology = build_desired_topology(expanded)
    output_dir = tmp_path / ".rinstall"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER_TOPOLOGY),
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert topology.deployment_context.vsphere.clone_timeout_minutes is None
    assert topology.deployment_context.vsphere.allow_unverified_ssl is False
    for artifact in (
        "topology.json",
        "topology.md",
        "topology.txt",
        "architecture.mmd",
        "network-topology.mmd",
    ):
        assert (output_dir / artifact).is_file()
    assert json.loads((output_dir / "topology.json").read_text())["deployment_context"]["vsphere"]["clone_timeout_minutes"] is None
    assert "Terraform default: 60 minutes" in render_topology_markdown(topology)
    assert str(output_dir / "topology.json") in result.stdout


def test_topology_preserves_v03_accepted_unresolved_service_and_dns_values():
    config = raw_config()
    config["bastion"]["service_ip"] = "192.0.2.99"
    config["bastion"]["dnsmasq_upstream_servers"] = ["resolver.example.invalid"]
    config["nodes"]["bastion1"]["dns_servers"] = ["dns.example.invalid"]

    topology = build_desired_topology(expand_env(config))
    services = {service.id: service for service in topology.services}
    endpoints = {endpoint.id: endpoint for endpoint in topology.endpoints}

    assert services["proxy:squid"].address == "192.0.2.99"
    assert services["proxy:squid"].interface_id is None
    assert services["proxy:squid"].network is None
    assert services["proxy:squid"].resolution == PARTIAL
    assert endpoints["endpoint:dns-upstream:resolver.example.invalid"].resolutions[0].address_kind == "DNS_NAME"
    assert endpoints["endpoint:dns-management:dns.example.invalid"].resolutions[0].address_kind == "DNS_NAME"
    assert "resolver.example.invalid" in render_topology_json(topology)


def test_topology_tolerates_v03_accepted_hostname_ssh_target():
    config = raw_config()
    config["nodes"]["prom1"]["ssh_ip"] = "prometheus.example.invalid"

    topology = build_desired_topology(expand_env(config))
    host = next(host for host in topology.hosts if host.id == "prom1")
    path = next(path for path in topology.access_paths if path.destination.id == "prom1")
    rule = next(rule for rule in topology.connectivity_rules if rule.id == "admin-ssh:operator:prom1")

    assert host.ssh_target == "prometheus.example.invalid"
    assert path.target == "prometheus.example.invalid"
    assert rule.destination.resolved[0].address_kind == DNS_NAME


def test_topology_has_only_one_definition_for_each_canonical_renderer():
    source = (ROOT / "lib/topology.py").read_text()
    tree = ast.parse(source)
    function_names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    canonical_renderers = {
        "render_topology_json",
        "render_topology_architecture_mermaid",
        "render_topology_network_mermaid",
        "render_topology_markdown",
        "render_topology_ascii_overview",
    }
    assert all(function_names.count(name) == 1 for name in canonical_renderers)
    assert not any(
        name in function_names
        for name in (
            "render_topology_infrastructure_mermaid",
            "render_topology_ascii",
            "render_topology_mermaid",
            "_legacy_render_topology_markdown",
            "_legacy_render_topology_ascii_overview",
            "_render_topology_markdown",
        )
    )


@pytest.mark.parametrize(
    "optional_field",
    [
        "domain",
        "local.vlan.dns_nodes",
        "bastion.downstream_networks",
        "bastion.service_ip",
        "bastion.network_connection_names",
        "bastion.squid_http_port",
        "infra.vsphere.clone_timeout",
        "infra.vsphere.allow_unverified_ssl",
        "ssh",
        "rke2.primary_node",
        "rancher.edition",
        "rancher.agent_tls_mode",
    ],
)
def test_topology_accepts_each_production_optional_field_when_omitted(optional_field):
    config = raw_config()
    parts = optional_field.split(".")
    mapping = config
    for part in parts[:-1]:
        mapping = mapping[part]
    mapping.pop(parts[-1], None)

    expanded = expand_env(config)
    topology = build_desired_topology(expanded)

    assert render_topology_json(topology)
    assert render_topology_markdown(topology)
    assert render_topology_ascii_overview(topology)
    assert render_topology_architecture_mermaid(topology)
    assert render_topology_network_mermaid(topology)


def test_topology_preserves_explicit_vsphere_optional_values():
    config = raw_config()
    config["infra"]["vsphere"]["clone_timeout"] = 90
    config["infra"]["vsphere"]["allow_unverified_ssl"] = True

    topology = build_desired_topology(expand_env(config))
    vsphere = topology.deployment_context.vsphere

    assert vsphere.clone_timeout_minutes == 90
    assert vsphere.allow_unverified_ssl is True
    assert "90 minutes" in render_topology_markdown(topology)


def test_topology_uses_effective_dns_per_node_and_does_not_require_bastion_dns():
    config = raw_config()
    config["local"]["vlan"]["dns_nodes"] = ["prom1"]
    config["nodes"]["prom1"]["dns_servers"] = ["192.0.2.61", "192.0.2.62"]
    topology = build_desired_topology(expand_env(config))

    rules = {
        rule.id: rule
        for rule in topology.connectivity_rules
        if rule.id.startswith("core-dns:local-nodes")
    }
    assert set(rules) == {"core-dns:local-nodes", "core-dns:local-nodes:1"}
    assert {
        frozenset(item.reference.id for item in rule.source.resolved if item.reference)
        for rule in rules.values()
    } == {frozenset({"prom1"}), frozenset({"rancher1", "rancher2", "rancher3"})}


def test_topology_renders_ipv4_dns_resolver_endpoints():
    topology = topology_with()
    endpoints = by_id(topology.endpoints)

    assert endpoints["endpoint:dns-upstream:192.0.2.54"].resolutions[0].address_kind == IP_ADDRESS
    assert endpoints["endpoint:dns-upstream:192.0.2.54"].resolutions[0].addresses == ("192.0.2.54",)
    assert endpoints["endpoint:dns-management:192.0.2.53"].resolutions[0].address_kind == IP_ADDRESS
    assert endpoints["endpoint:dns-management:192.0.2.53"].resolutions[0].addresses == ("192.0.2.53",)


def test_topology_groups_each_node_by_its_effective_dns_destinations():
    config = raw_config()
    config["local"]["vlan"]["dns_nodes"] = ["bastion1", "prom1"]
    config["nodes"]["prom1"]["dns_servers"] = ["192.0.2.61", "192.0.2.62"]
    config = expand_env(config)
    config["nodes"]["rancher2"]["dns_servers"] = ["192.0.2.70"]
    topology = build_desired_topology(config)

    rules = {
        rule.id: rule
        for rule in topology.connectivity_rules
        if rule.id.startswith("core-dns:local-nodes")
    }
    grouped = {
        frozenset(item.reference.id for item in rule.source.resolved if item.reference): {
            item.address for item in rule.destination.resolved
        }
        for rule in rules.values()
    }
    assert grouped == {
        frozenset({"prom1"}): {"192.0.2.61", "192.0.2.62"},
        frozenset({"rancher2"}): {"192.0.2.70"},
        frozenset({"rancher1", "rancher3"}): {"10.14.17.4", "10.14.17.6"},
    }


def test_topology_preserves_configured_ports_and_vcenter_endpoint():
    config = raw_config()
    config["terraform"]["backend"]["url"] = "https://gitlab.example:9443"
    config["infra"]["vsphere"]["server"] = "vcenter.example.invalid"
    config["ssh"]["jump_host"] = {"alias": "jump", "hostname": "jump.example.invalid"}
    topology = build_desired_topology(expand_env(config))

    endpoints = {endpoint.id: endpoint for endpoint in topology.endpoints}
    assert endpoints["endpoint:terraform-backend"].ports == (9443,)
    assert endpoints["endpoint:vcenter"].name == "vcenter.example.invalid"
    assert endpoints["endpoint:vcenter"].provenance == CONFIGURED
    assert endpoints["endpoint:vcenter"].resolutions[0].provenance == CONFIGURED
    assert endpoints["endpoint:vcenter"].resolution == RESOLVED
    vcenter_rule = by_id(topology.connectivity_rules)["deployment:vcenter-api"]
    assert vcenter_rule.destination.symbolic == "endpoint:vcenter"
    assert vcenter_rule.destination.resolved[0].id == "vcenter.example.invalid"
    assert vcenter_rule.destination.resolved[0].address == "vcenter.example.invalid"
    assert vcenter_rule.destination.resolved[0].reference == EntityReference("endpoint", "endpoint:vcenter")
    assert vcenter_rule.destination_ports == (443,)
    assert topology.deployment_context.vsphere.resolution == RESOLVED
    assert endpoints["endpoint:rancher"].resolutions[1].provenance == EXTERNAL
    assert endpoints["endpoint:ssh-jump"].ports == (22,)

    config["ssh"]["jump_host"] = "opaque-alias"
    opaque = build_desired_topology(expand_env(config))
    assert next(endpoint for endpoint in opaque.endpoints if endpoint.id == "endpoint:ssh-jump").ports == ()


def test_topology_accepts_explicit_ssh_target_outside_node_interfaces():
    config = raw_config()
    config["nodes"]["prom1"]["ssh_ip"] = "192.0.2.99"
    topology = build_desired_topology(expand_env(config))

    assert next(host for host in topology.hosts if host.id == "prom1").ssh_target == "192.0.2.99"


def by_id(items):
    return {item.id: item for item in items}


def replace_at(items, index, item):
    return (*items[:index], item, *items[index + 1 :])


def invalid_duplicate_host(topology):
    return replace(topology, hosts=(*topology.hosts, topology.hosts[0]))


def invalid_interface_host(topology):
    interface = replace(topology.interfaces[0], host="missing-host")
    return replace(topology, interfaces=replace_at(topology.interfaces, 0, interface))


def invalid_cluster_primary(topology):
    cluster = replace(topology.clusters[0], primary_host_id="prom1")
    return replace(topology, clusters=(cluster,))


def invalid_endpoint_cluster(topology):
    endpoint = replace(by_id(topology.endpoints)["endpoint:rancher"], cluster_id="missing-cluster")
    endpoints = tuple(
        endpoint if item.id == endpoint.id else item for item in topology.endpoints
    )
    return replace(topology, endpoints=endpoints)


def invalid_access_hop(topology):
    path = replace(
        topology.access_paths[0],
        hops=(EntityReference("endpoint", "missing-jump"),),
    )
    return replace(topology, access_paths=replace_at(topology.access_paths, 0, path))


def invalid_service_network(topology):
    service = replace(topology.services[0], network="missing-network")
    return replace(topology, services=replace_at(topology.services, 0, service))


def invalid_connectivity_reference(topology):
    rule = topology.connectivity_rules[0]
    resolved = replace(
        rule.source.resolved[0],
        reference=EntityReference("downstream-consumer", "missing-consumer"),
    )
    source = replace(rule.source, resolved=replace_at(rule.source.resolved, 0, resolved))
    rule = replace(rule, source=source)
    return replace(
        topology,
        connectivity_rules=replace_at(topology.connectivity_rules, 0, rule),
    )


def invalid_missing_consumer(topology):
    return replace(topology, downstream_consumers=())


def invalid_gateway_address(topology):
    endpoint = by_id(topology.endpoints)["endpoint:gateway:vlan565"]
    resolution = replace(endpoint.resolutions[0], addresses=("10.20.56.35",))
    endpoint = replace(endpoint, resolutions=(resolution,))
    return replace(
        topology,
        endpoints=tuple(endpoint if item.id == endpoint.id else item for item in topology.endpoints),
    )


def invalid_host_summary(topology):
    host = replace(topology.hosts[0], local_ip="192.0.2.200")
    return replace(topology, hosts=replace_at(topology.hosts, 0, host))


def invalid_missing_admin_rule(topology):
    return replace(
        topology,
        connectivity_rules=tuple(
            rule for rule in topology.connectivity_rules if rule.category != ADMINISTRATIVE
        ),
    )


def invalid_admin_path_rule(topology):
    rule = next(rule for rule in topology.connectivity_rules if rule.category == ADMINISTRATIVE)
    destination = replace(
        rule.destination.resolved[0],
        id="prom1",
        address="10.14.17.6",
        reference=EntityReference("host", "prom1"),
    )
    rule = replace(rule, destination=replace(rule.destination, resolved=(destination,)))
    return replace(
        topology,
        connectivity_rules=tuple(
            rule if item.id == rule.id else item for item in topology.connectivity_rules
        ),
    )


def invalid_empty_resolved_side(topology):
    rule = by_id(topology.connectivity_rules)["downstream-dns:vlan565"]
    rule = replace(rule, source=replace(rule.source, resolved=()))
    return replace(
        topology,
        connectivity_rules=tuple(
            rule if item.id == rule.id else item for item in topology.connectivity_rules
        ),
    )


def invalid_route_link(topology):
    context = topology.deployment_context
    route = replace(
        context.vsphere.route,
        interface_ref=EntityReference("interface", "bastion1:0"),
        network_ref=EntityReference("network", "customer"),
    )
    context = replace(context, vsphere=replace(context.vsphere, route=route))
    return replace(topology, deployment_context=context)


def invalid_duplicate_endpoint_scope(topology):
    endpoint = by_id(topology.endpoints)["endpoint:rancher"]
    endpoint = replace(endpoint, resolutions=(endpoint.resolutions[0], endpoint.resolutions[0]))
    return replace(
        topology,
        endpoints=tuple(endpoint if item.id == endpoint.id else item for item in topology.endpoints),
    )


def test_v2_rke2_rancher_cluster_is_derived_from_roles_and_primary():
    topology = topology_with()
    cluster = topology.clusters[0]

    assert topology.metadata.topology_schema_version == 2
    assert topology.metadata.config_schema_version == 1
    assert cluster.kind == "rke2-rancher-control-cluster"
    assert cluster.member_host_ids == ("rancher1", "rancher2", "rancher3")
    assert cluster.primary_host_id == "rancher1"
    assert cluster.join_host_ids == ("rancher2", "rancher3")
    assert cluster.endpoint_ids == ("endpoint:rancher",)
    assert cluster.versions == {
        "rke2": "v1.35.7+rke2r1",
        "rancher": "2.14.4",
    }
    assert (cluster.ownership, cluster.provenance, cluster.resolution) == (
        RINSTALL_CONFIGURED,
        DERIVED,
        RESOLVED,
    )


def test_v2_architecture_map_consumes_semantic_entities_and_boundaries(monkeypatch):
    topology = build_desired_topology(load_env(FULL_CONFIG))

    def unexpected_config_read(*args, **kwargs):
        raise AssertionError("architecture renderer must consume V2 only")

    monkeypatch.setattr("builtins.open", unexpected_config_read)
    architecture = render_topology_architecture_mermaid(topology)

    assert architecture.startswith("flowchart LR\n")
    assert "Operator / rinstall" in architecture
    assert "SSH jump<br/>example-operator-jump<br/>external unresolved" in architecture
    assert "External dependencies" not in architecture
    assert "Bastion<br/>bastion1<br/>DNS · DHCP · proxy · SSH transit" in architecture
    assert 'Monitoring host<br/>prom1' in architecture
    assert 'subgraph cluster_rke2_rancher_' not in architecture
    assert 'RKE2 / Rancher cluster<br/>rancher1 primary<br/>rancher2<br/>rancher3' in architecture
    assert "Rancher endpoint<br/>rancher.full-example.example.invalid<br/>HTTPS / 443<br/>split-horizon DNS" in architecture
    assert "external exposure: unresolved" not in architecture
    assert "_note" not in architecture
    assert "Downstream nodes<br/>VLAN 565<br/>external lifecycle" in architecture
    assert "Downstream nodes<br/>VLAN 566<br/>external lifecycle" in architecture
    assert "vSphere<br/>vcenter.example.invalid" in architecture
    assert "Terraform state backend<br/>GitLab" in architecture
    assert "TCP/22" not in architecture
    assert "DNS" in architecture
    assert "DHCP" in architecture
    assert "/53" not in architecture
    assert "67/68" not in architecture
    assert "3128" not in architecture
    assert "9345" not in architecture
    assert "6443" not in architecture
    assert "198.51.100." not in architecture
    assert "private_key" not in architecture
    assert "TF_HTTP" not in architecture
    assert architecture.count(" --> ") == 9
    assert (
        f'  {_mermaid_id("actor", "operator-workstation")} --> '
        f'{_mermaid_id("endpoint", "endpoint:ssh-jump")}'
    ) in architecture
    assert (
        f'  {_mermaid_id("host", "bastion1")} --> '
        f'{_mermaid_id("host", "prom1")}'
    ) in architecture
    assert (
        f'  {_mermaid_id("host", "bastion1")} --> '
        f'{_mermaid_id("cluster", "cluster:rke2-rancher")}'
    ) in architecture
    assert (
        f'  {_mermaid_id("actor", "operator-workstation")} --> '
        f'{_mermaid_id("endpoint", "endpoint:vcenter")}'
    ) in architecture
    assert (
        f'  {_mermaid_id("actor", "operator-workstation")} --> '
        f'{_mermaid_id("endpoint", "endpoint:terraform-backend")}'
    ) in architecture


@pytest.mark.parametrize("count", [0, 1, 2, 5, 10])
def test_v2_architecture_map_supports_arbitrary_downstream_consumer_counts(count):
    config = raw_config()
    config["bastion"]["downstream_networks"] = [
        downstream_network(500 + index, f"10.20.{index}.0/24")
        for index in range(min(count, 8))
    ]
    topology = build_desired_topology(expand_env(config))
    if count > 8:
        consumers = tuple(
            replace(
                topology.downstream_consumers[index % len(topology.downstream_consumers)],
                id=f"consumer:architecture-test-{index}",
            )
            for index in range(count)
        )
        topology = replace(topology, downstream_consumers=consumers)
    architecture = render_topology_architecture_mermaid(topology)

    assert architecture.count("Downstream nodes<br/>") == count
    assert architecture.count("external lifecycle") == count
    if count:
        assert "Downstream environments" in architecture
    else:
        assert "Downstream environments" not in architecture


def test_v2_architecture_map_is_deterministic_and_reference_artifact_is_v2_only():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    first = render_topology_architecture_mermaid(topology)
    second = render_topology_architecture_mermaid(topology)

    assert first == second
    assert "network_" not in first


def test_v2_architecture_map_uses_arbitrary_cluster_members_from_v2():
    config = raw_config()
    config["local"]["rancher_nodes"].update({"count": 5, "start_host": 7})
    topology = build_desired_topology(expand_env(config))
    architecture = render_topology_architecture_mermaid(topology)

    assert "rancher1 primary" in architecture
    assert all(f"rancher{index}" in architecture for index in range(2, 6))


def test_v2_network_mermaid_covers_entities_and_attachments():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    mermaid = render_topology_network_mermaid(topology)

    assert mermaid.startswith("flowchart TB\n")
    for label in (
        "Management", "192.0.2.0/24", "EXAMPLE_MANAGEMENT_NETWORK",
        "Customer", "198.51.100.0/28", "EXAMPLE_CUSTOMER_NETWORK",
        "VLAN 565", "203.0.113.32/27", "EXAMPLE_DOWNSTREAM_NETWORK_565",
        "203.0.113.34", "203.0.113.33", "203.0.113.36-203.0.113.61",
        "VLAN 566", "203.0.113.64/27", "203.0.113.66", "203.0.113.65",
        "203.0.113.68-203.0.113.93", "prom1", "rancher1 primary",
        "rancher2", "rancher3", "not a router", "external routing / firewall",
    ):
        assert label in mermaid
    assert mermaid.count('host_bastion1_fd65cf69ce["') == 1
    assert "kind:" not in mermaid and "lease" not in mermaid
    assert "TCP" not in mermaid and "9345" not in mermaid and "6443" not in mermaid
    assert "ens" not in mermaid and "endpoint:rancher" not in mermaid
    assert mermaid == render_topology_network_mermaid(topology)


@pytest.mark.parametrize("count", [0, 1, 2, 5, 10])
def test_v2_network_topology_scales_downstream_networks(count):
    config = raw_config()
    config["bastion"]["downstream_networks"] = [
        downstream_network(500 + index, f"10.20.{index}.0/24")
        for index in range(min(count, 8))
    ]
    topology = build_desired_topology(expand_env(config))
    if count > 8:
        extra_downstreams = []
        extra_networks = []
        extra_consumers = []
        for index in range(8, count):
            vlan = 600 + index
            network_id = f"downstream:vlan{vlan}"
            subnet = f"10.30.{index}.0/24"
            source_downstream = topology.downstream_networks[0]
            source_network = next(
                network for network in topology.networks if network.id == source_downstream.id
            )
            source_consumer = topology.downstream_consumers[0]
            extra_downstreams.append(
                replace(
                    source_downstream,
                    id=network_id,
                    interface_name=f"vlan{vlan}",
                    vlan=vlan,
                    vmware_network=f"DOWNSTREAM_VLAN_{vlan}",
                    cidr=subnet,
                    bastion_address=f"10.30.{index}.2",
                    gateway=f"10.30.{index}.1",
                    dhcp_start=f"10.30.{index}.4",
                    dhcp_end=f"10.30.{index}.254",
                )
            )
            extra_networks.append(
                replace(
                    source_network,
                    id=network_id,
                    vlan=vlan,
                    vmware_network=f"DOWNSTREAM_VLAN_{vlan}",
                    cidr=subnet,
                    gateway=f"10.30.{index}.1",
                    interface_ids=(),
                    gateway_endpoint_id=f"endpoint:gateway:{network_id}",
                )
            )
            extra_consumers.append(
                replace(
                    source_consumer,
                    id=f"consumer:network-test-{index}",
                    network_id=network_id,
                    address_start=f"10.30.{index}.4",
                    address_end=f"10.30.{index}.254",
                    gateway_endpoint_id=f"endpoint:gateway:{network_id}",
                )
            )
        topology = replace(
            topology,
            downstream_networks=topology.downstream_networks + tuple(extra_downstreams),
            networks=topology.networks + tuple(extra_networks),
            downstream_consumers=topology.downstream_consumers + tuple(extra_consumers),
        )
    mermaid = render_topology_network_mermaid(topology)

    assert mermaid.count("External gateway") == count
    assert mermaid.count("Downstream nodes") == count


def test_v2_rke2_cluster_supports_arbitrary_member_names_and_count():
    config = raw_config()
    config["local"]["rancher_nodes"].update(
        {"name_prefix": "control", "count": 5, "start_host": 7}
    )

    topology = build_desired_topology(expand_env(config))
    cluster = topology.clusters[0]

    assert cluster.member_host_ids == tuple(f"control{index}" for index in range(1, 6))
    assert cluster.primary_host_id == "control1"
    assert cluster.join_host_ids == tuple(f"control{index}" for index in range(2, 6))


def test_v2_rancher_endpoint_has_local_and_unresolved_external_resolution():
    topology = topology_with()
    endpoint = by_id(topology.endpoints)["endpoint:rancher"]
    resolutions = {item.scope: item for item in endpoint.resolutions}

    assert endpoint.kind == "rancher-https"
    assert endpoint.name == "rancher.example.internal"
    assert endpoint.protocols == ("HTTPS",)
    assert endpoint.ports == (443,)
    assert endpoint.cluster_id == topology.clusters[0].id
    assert endpoint.resolution == PARTIAL
    assert resolutions["local"].addresses == (
        "10.14.17.11",
        "10.14.17.12",
        "10.14.17.13",
    )
    assert resolutions["local"].resolution == RESOLVED
    assert resolutions["external"].addresses == ()
    assert resolutions["external"].resolution == EXTERNAL_UNRESOLVED
    assert resolutions["external"].ownership == EXTERNALLY_MANAGED
    assert "VIP/load balancer" in resolutions["external"].reason
    assert all(
        "unknown" not in resolution.addresses
        for endpoint in topology.endpoints
        for resolution in endpoint.resolutions
        if resolution.resolution == RESOLVED
    )


def test_v2_monitoring_role_represents_host_only():
    topology = topology_with()
    prometheus = by_id(topology.hosts)["prom1"]

    assert prometheus.roles == ("prometheus",)
    assert prometheus.capabilities == (MONITORING_HOST_ONLY,)
    assert prometheus.service_status == "host-only/not-modeled"
    assert prometheus.ownership == RINSTALL_MANAGED
    assert not any(service.kind == "prometheus" for service in topology.services)


def test_v2_ownership_provenance_resolution_and_verification_are_separate():
    topology = topology_with(downstream_network(565, "10.20.56.32/27"))
    customer = by_id(topology.networks)["customer"]
    interface = by_id(topology.interfaces)["bastion1:0"]
    service = by_id(topology.services)["dns:vlan565"]
    vcenter = by_id(topology.endpoints)["endpoint:vcenter"]

    assert (customer.ownership, customer.provenance, customer.verification) == (
        REFERENCED_EXTERNAL,
        CONFIGURED,
        DESIRED_ONLY,
    )
    assert (interface.ownership, interface.provenance, interface.resolution) == (
        RINSTALL_MANAGED,
        DERIVED,
        RESOLVED,
    )
    assert service.ownership == RINSTALL_CONFIGURED
    assert service.provenance == "RINSTALL_ARCHITECTURE"
    assert vcenter.resolution == RUNTIME_SUPPLIED
    assert vcenter.verification == UNVERIFIED


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (invalid_duplicate_host, "duplicate host id"),
        (invalid_interface_host, "references missing host"),
        (invalid_cluster_primary, "primary prom1 is not a member"),
        (invalid_endpoint_cluster, "cluster reference is inconsistent"),
        (invalid_access_hop, "references missing endpoint"),
        (invalid_service_network, "references missing network"),
        (invalid_connectivity_reference, "references missing downstream-consumer"),
        (invalid_missing_consumer, "exactly one symbolic downstream consumer"),
        (invalid_gateway_address, "does not match network gateway"),
        (invalid_host_summary, "summary addresses do not match interfaces"),
        (invalid_missing_admin_rule, "missing administrative rule"),
        (invalid_admin_path_rule, "does not match access paths"),
        (invalid_empty_resolved_side, "has no references"),
        (invalid_route_link, "route linkage is inconsistent"),
        (invalid_duplicate_endpoint_scope, "duplicate resolution scopes"),
    ],
)
def test_v2_referential_integrity_fails_closed(mutate, message):
    topology = topology_with(downstream_network(565, "10.20.56.32/27"))

    with pytest.raises(ValueError, match=message):
        validate_topology(mutate(topology))


def test_topology_includes_expanded_hosts_roles_and_static_addresses():
    topology = topology_with()
    hosts = {host.id: host for host in topology.hosts}

    assert list(hosts) == ["bastion1", "prom1", "rancher1", "rancher2", "rancher3"]
    assert hosts["prom1"].roles == ("prometheus",)
    assert hosts["bastion1"].local_ip == "10.14.17.4"
    assert hosts["bastion1"].management_ip == "192.0.2.10"
    assert hosts["bastion1"].ssh_target == "192.0.2.10"
    assert [host.id for host in topology.hosts if "rancher" in host.roles] == [
        "rancher1",
        "rancher2",
        "rancher3",
    ]


def test_topology_binds_bastion_services_to_service_ip_interface():
    config = raw_config()
    config["nodes"]["bastion1"]["nics"][1]["cidr"] = "192.0.2.10/24"
    config["bastion"]["service_ip"] = "192.0.2.10"
    topology = build_desired_topology(expand_env(config))

    services = {service.id: service for service in topology.services}
    assert (services["proxy:squid"].network, services["proxy:squid"].interface_id) == (
        "management",
        "bastion1:1",
    )
    assert (services["dns:local"].network, services["dns:local"].interface_id) == (
        "management",
        "bastion1:1",
    )
    assert all(service.resolution == RESOLVED for service in services.values() if service.id in {"proxy:squid", "dns:local"})


def test_topology_route_linkage_uses_configured_renamed_connection():
    config = raw_config()
    config["bastion"]["network_connection_names"] = {
        "ens192": "local",
        "ens224": "mgmt",
    }
    config["bastion"]["vsphere_route_connection"] = "mgmt"
    topology = build_desired_topology(expand_env(config))

    route = topology.deployment_context.vsphere.route
    assert (route.connection, route.interface_ref, route.network_ref, route.resolution) == (
        "mgmt",
        EntityReference("interface", "bastion1:1"),
        EntityReference("network", "management"),
        RESOLVED,
    )


def test_topology_route_mapping_order_is_semantically_invariant():
    first = raw_config()
    second = raw_config()
    first["bastion"]["network_connection_names"] = {
        "ens192": "local",
        "ens224": "mgmt",
    }
    second["bastion"]["network_connection_names"] = {
        "ens224": "mgmt",
        "ens192": "local",
    }
    for config in (first, second):
        config["bastion"]["vsphere_route_connection"] = "mgmt"

    first_topology = build_desired_topology(expand_env(first))
    second_topology = build_desired_topology(expand_env(second))
    first_route = first_topology.deployment_context.vsphere.route
    second_route = second_topology.deployment_context.vsphere.route

    assert first_route == second_route
    assert all(
        renderer(first_topology) == renderer(second_topology)
        for renderer in (
            render_topology_json,
            render_topology_markdown,
            render_topology_architecture_mermaid,
            render_topology_network_mermaid,
        )
    )


def test_topology_partial_connection_mapping_uses_explicit_route_identity():
    config = raw_config()
    config["bastion"]["network_connection_names"] = {"ens224": "mgmt"}
    config["bastion"]["vsphere_route_connection"] = "mgmt"

    route = build_desired_topology(expand_env(config)).deployment_context.vsphere.route

    assert (route.interface_ref, route.network_ref) == (
        EntityReference("interface", "bastion1:1"),
        EntityReference("network", "management"),
    )


def test_topology_resolves_one_downstream_network_and_dhcp_pool():
    topology = topology_with(downstream_network(565, "10.20.56.32/27"))
    downstream = topology.downstream_networks[0]

    assert downstream.interface_name == "vlan565"
    assert downstream.cidr == "10.20.56.32/27"
    assert downstream.bastion_address == "10.20.56.34"
    assert downstream.gateway == "10.20.56.33"
    assert (downstream.dhcp_start, downstream.dhcp_end, downstream.dhcp_lease) == (
        "10.20.56.36",
        "10.20.56.61",
        "12h",
    )
    interface = next(interface for interface in topology.interfaces if interface.logical_name == "vlan565")
    assert interface.host == "bastion1"
    assert interface.address == "10.20.56.34"
    assert interface.network == downstream.id


def test_multiple_downstream_networks_and_services_remain_independent():
    topology = topology_with(
        downstream_network(565, "10.20.56.32/27"),
        downstream_network(566, "10.20.56.64/27"),
    )

    assert [network.bastion_address for network in topology.downstream_networks] == [
        "10.20.56.34",
        "10.20.56.66",
    ]
    assert [service.address for service in topology.services if service.kind == "dns"] == [
        "10.14.17.4",
        "10.20.56.34",
        "10.20.56.66",
    ]


def test_v2_external_ssh_alias_and_role_aware_access_paths(monkeypatch, tmp_path):
    config = yaml.safe_load(FULL_CONFIG.read_text())
    config["nodes"]["utility1"] = {
        "role": "utility",
        "template": "infra",
        "host": 7,
        "cpu": 1,
        "memory_mb": 1024,
        "disk_gb": 20,
        "nics": [{"network": "customer"}],
    }
    config = expand_env(config)
    monkeypatch.setenv("HOME", str(tmp_path / "home-without-ssh-config"))

    def unexpected_file_access(*args, **kwargs):
        raise AssertionError("topology derivation must not read external files")

    monkeypatch.setattr("builtins.open", unexpected_file_access)
    topology = build_desired_topology(config)
    endpoints = by_id(topology.endpoints)
    paths = {path.destination.id: path for path in topology.access_paths}

    jump = endpoints["endpoint:ssh-jump"]
    assert jump.name == "example-operator-jump"
    assert jump.resolution == EXTERNAL_UNRESOLVED
    assert jump.resolutions[0].addresses == ()
    assert "example-operator-jump" not in by_id(topology.hosts)
    assert paths["bastion1"].hops == (EntityReference("endpoint", jump.id),)
    assert paths["utility1"].hops == (EntityReference("endpoint", jump.id),)
    expected_core_hops = (
        EntityReference("endpoint", jump.id),
        EntityReference("host", "bastion1"),
    )
    assert paths["prom1"].hops == expected_core_hops
    assert paths["rancher1"].hops == expected_core_hops
    assert paths["bastion1"].target == "192.0.2.10"
    assert paths["rancher1"].target == "198.51.100.11"
    assert all(path.resolution == PARTIAL for path in paths.values())

    assert "Utility host" in render_topology_markdown(topology)
    assert "Utility host" in render_topology_architecture_mermaid(topology)
    assert "Utility host" in render_topology_network_mermaid(topology)


def test_v2_access_paths_are_direct_without_configured_jump_alias():
    topology = topology_with()
    architecture = render_topology_architecture_mermaid(topology)

    assert "endpoint:ssh-jump" not in by_id(topology.endpoints)
    assert all(path.hops == () for path in topology.access_paths)
    assert {path.destination.id for path in topology.access_paths} == {
        host.id for host in topology.hosts
    }
    assert all(path.resolution == RESOLVED for path in topology.access_paths)
    operator_id = _mermaid_id("actor", "operator-workstation")
    assert f"{operator_id} --> {_mermaid_id('host', 'prom1')}" in architecture
    assert f"{operator_id} --> {_mermaid_id('cluster', 'cluster:rke2-rancher')}" in architecture
    assert f"{_mermaid_id('host', 'bastion1')} --> {_mermaid_id('host', 'prom1')}" not in architecture
    assert f"{_mermaid_id('host', 'bastion1')} --> {_mermaid_id('cluster', 'cluster:rke2-rancher')}" not in architecture


def test_v2_access_paths_expand_comma_separated_proxyjump_chain():
    config = raw_config()
    config["ssh"]["jump_host"] = "edge-jump,admin-jump"
    topology = build_desired_topology(expand_env(config))
    endpoints = by_id(topology.endpoints)
    paths = {path.destination.id: path for path in topology.access_paths}

    assert endpoints["endpoint:ssh-jump-hop:1"].name == "edge-jump"
    assert endpoints["endpoint:ssh-jump"].name == "admin-jump"
    assert paths["bastion1"].hops == (
        EntityReference("endpoint", "endpoint:ssh-jump-hop:1"),
        EntityReference("endpoint", "endpoint:ssh-jump"),
    )
    assert paths["rancher1"].hops == (
        *paths["bastion1"].hops,
        EntityReference("host", "bastion1"),
    )


def test_v2_access_paths_expand_structured_nested_proxyjump_without_external_lookup(
    monkeypatch,
):
    config = raw_config()
    config["ssh"]["jump_host"] = {
        "hostname": "admin.example.invalid",
        "proxy_jump": "edge-jump",
    }
    config["ssh"]["extra_hosts"] = {
        "edge-jump": {
            "hostname": "edge.example.invalid",
            "proxy_jump": "opaque-entry",
        }
    }
    config = expand_env(config)

    def unexpected_file_access(*args, **kwargs):
        raise AssertionError("topology derivation must not read ~/.ssh/config")

    monkeypatch.setattr("builtins.open", unexpected_file_access)
    topology = build_desired_topology(config)
    endpoints = [endpoint for endpoint in topology.endpoints if endpoint.kind == "ssh-jump-alias"]
    rancher_path = next(
        path for path in topology.access_paths if path.destination.id == "rancher1"
    )

    assert [endpoint.name for endpoint in endpoints] == [
        "opaque-entry",
        "edge-jump",
        "rancher-env-jump",
    ]
    assert endpoints[0].resolution == EXTERNAL_UNRESOLVED
    assert endpoints[1].resolutions[0].addresses == ("edge.example.invalid",)
    assert endpoints[2].resolutions[0].addresses == ("admin.example.invalid",)
    assert rancher_path.hops == (
        EntityReference("endpoint", "endpoint:ssh-jump-hop:1"),
        EntityReference("endpoint", "endpoint:ssh-jump-hop:2"),
        EntityReference("endpoint", "endpoint:ssh-jump"),
        EntityReference("host", "bastion1"),
    )
    assert rancher_path.resolution == PARTIAL


def test_v2_symbolic_downstream_consumers_match_network_dhcp_and_gateway():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    consumers = by_id(topology.downstream_consumers)
    endpoints = by_id(topology.endpoints)

    assert len(consumers) == len(topology.downstream_networks) == 2
    for downstream in topology.downstream_networks:
        consumer = consumers[f"consumer:{downstream.id}"]
        gateway = endpoints[consumer.gateway_endpoint_id]
        network = by_id(topology.networks)[downstream.id]
        assert consumer.kind == "downstream-nodes-or-cluster"
        assert consumer.network_id == downstream.id
        assert consumer.downstream_network_ref == EntityReference(
            "downstream-network", downstream.id
        )
        assert downstream.network_ref == EntityReference("network", downstream.id)
        assert (
            network.cidr,
            network.vlan,
            network.vmware_network,
            network.gateway,
            network.gateway_endpoint_id,
        ) == (
            downstream.cidr,
            downstream.vlan,
            downstream.vmware_network,
            downstream.gateway,
            downstream.gateway_endpoint_id,
        )
        assert (consumer.address_start, consumer.address_end) == (
            downstream.dhcp_start,
            downstream.dhcp_end,
        )
        assert consumer.identities_known is False
        assert consumer.lifecycle == "external/downstream"
        assert (consumer.ownership, consumer.resolution) == (EXTERNALLY_MANAGED, SYMBOLIC)
        assert gateway.kind == "downstream-gateway"
        assert gateway.resolutions[0].addresses == (downstream.gateway,)
        assert gateway.ownership == REFERENCED_EXTERNAL
        assert downstream.bastion_is_router is False
        assert downstream.lifecycle_ownership == EXTERNALLY_MANAGED


def test_v2_deployment_context_is_config_only_and_resolves_configured_vcenter():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    context = topology.deployment_context
    endpoints = by_id(topology.endpoints)

    assert context.execution_actor_id == "actor:operator-workstation"
    assert context.terraform_root == "rinstall/terraform/infra"
    assert context.vsphere.datacenter == "EXAMPLE_DATACENTER"
    assert context.vsphere.datastore == "EXAMPLE_DATASTORE"
    assert context.vsphere.resource_pool == "EXAMPLE_CLUSTER/Resources"
    assert context.vsphere.folder == "Rancher/full-example"
    assert context.vsphere.clone_timeout_minutes == 60
    assert context.vsphere.allow_unverified_ssl is False
    assert context.resolution == PARTIAL
    assert (
        context.vsphere.route.destination,
        context.vsphere.route.gateway,
        context.vsphere.route.connection,
    ) == ("192.0.2.128/26", "192.0.2.1", "mgmt")
    assert context.vsphere.route.interface_ref == EntityReference("interface", "bastion1:1")
    assert context.vsphere.route.network_ref == EntityReference("network", "management")
    assert [(item.id, item.value) for item in context.vsphere.templates] == [
        ("infra", "EXAMPLE_TEMPLATE_INFRA"),
        ("rke2", "EXAMPLE_TEMPLATE_RKE2"),
    ]
    assert endpoints[context.vsphere.endpoint_id].name == "vcenter.example.invalid"
    assert endpoints[context.vsphere.endpoint_id].provenance == CONFIGURED
    assert endpoints[context.vsphere.endpoint_id].resolution == RESOLVED
    assert endpoints[context.vsphere.endpoint_id].resolutions[0].addresses == ("vcenter.example.invalid",)
    assert context.vsphere.resolution == RESOLVED
    assert context.terraform_backend.type == "gitlab"
    assert context.terraform_backend.project_id == 123456
    assert context.terraform_backend.state_name == "full-example-infra"
    assert context.terraform_backend.state_address.endswith(
        "/api/v4/projects/123456/terraform/state/full-example-infra"
    )
    assert {host.id: host.template_id for host in topology.hosts} == {
        "bastion1": "infra",
        "prom1": "infra",
        "rancher1": "rke2",
        "rancher2": "rke2",
        "rancher3": "rke2",
    }
    assert all(
        mapping.value is None
        and mapping.reference == EntityReference("network", mapping.id)
        for mapping in context.vsphere.networks
    )


def test_v2_topology_ignores_runtime_environment_enrichment(monkeypatch):
    config = load_env(FULL_CONFIG)
    config["ssh"]["private_key"] = "/sensitive/operator/id_rsa"
    before = build_desired_topology(config)
    monkeypatch.setenv("TF_VAR_vsphere_server", "secret-vcenter.example.invalid")
    monkeypatch.setenv("TF_VAR_vsphere_user", "secret-user")
    monkeypatch.setenv("TF_VAR_vsphere_password", "secret-password")
    monkeypatch.setenv("TF_HTTP_PASSWORD", "secret-backend-token")

    after = build_desired_topology(config)
    serialized = render_topology_json(after)

    assert after == before
    assert all(
        secret not in serialized
        for secret in (
            "secret-vcenter.example.invalid",
            "secret-user",
            "secret-password",
            "secret-backend-token",
            "/sensitive/operator/id_rsa",
        )
    )


def test_v2_runtime_vcenter_is_consistent_across_endpoint_rule_and_context():
    topology = build_desired_topology(expand_env(raw_config()))
    endpoint = by_id(topology.endpoints)["endpoint:vcenter"]
    rule = by_id(topology.connectivity_rules)["deployment:vcenter-api"]

    assert endpoint.provenance == EXTERNAL
    assert endpoint.resolution == RUNTIME_SUPPLIED
    assert endpoint.resolutions[0].addresses == ()
    assert rule.destination.symbolic == "endpoint:vcenter"
    assert rule.destination.resolved[0].id == endpoint.name
    assert rule.destination.resolved[0].address is None
    assert rule.destination.resolved[0].reference == EntityReference("endpoint", endpoint.id)
    assert topology.deployment_context.vsphere.resolution == RUNTIME_SUPPLIED


def test_v2_validator_rejects_unrelated_runtime_vcenter_for_configured_endpoint():
    config = yaml.safe_load(FULL_CONFIG.read_text())
    topology = build_desired_topology(load_env(FULL_CONFIG))
    rule = by_id(topology.connectivity_rules)["deployment:vcenter-api"]
    destination = replace(
        rule.destination.resolved[0],
        id="runtime-supplied vCenter endpoint",
        address=None,
        address_kind=SYMBOLIC_ADDRESS,
    )
    invalid_rule = replace(
        rule,
        destination=replace(rule.destination, resolved=(destination,)),
    )
    invalid = replace(
        topology,
        connectivity_rules=tuple(
            invalid_rule if item.id == rule.id else item
            for item in topology.connectivity_rules
        ),
    )

    assert config["infra"]["vsphere"]["server"] == "vcenter.example.invalid"
    with pytest.raises(ValueError, match="vCenter deployment relationship is inconsistent"):
        validate_topology(invalid)


def test_v2_operational_connectivity_registry_covers_core_and_downstream_contract():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    rules = by_id(topology.connectivity_rules)

    assert set(rules) == {
        "admin-ssh:operator-jump",
        "admin-ssh:jump:bastion1",
        "admin-ssh:bastion:prom1",
        "admin-ssh:bastion:rancher1",
        "admin-ssh:bastion:rancher2",
        "admin-ssh:bastion:rancher3",
        "deployment:terraform-backend",
        "deployment:vcenter-api",
        "core-dns:bastion-os",
        "core-dns:local-nodes",
        "core-dns:upstream",
        "core-proxy:rancher-nodes",
        "core-proxy:upstream",
        "rke2:join-primary",
        "rke2:bastion-kubernetes-api",
        "downstream-dns:vlan565",
        "downstream-dns:vlan566",
        "rancher-downstream-ssh:vlan565",
        "rancher-downstream-ssh:vlan566",
        "downstream-dhcp-request:vlan565",
        "downstream-dhcp-request:vlan566",
        "downstream-dhcp-response:vlan565",
        "downstream-dhcp-response:vlan566",
        "downstream-rancher-agent:vlan565",
        "downstream-rancher-agent:vlan566",
        "external-routing:customer:vlan565",
        "external-routing:customer:vlan566",
    }
    assert rules["rke2:join-primary"].destination_ports == (9345,)
    assert rules["rke2:bastion-kubernetes-api"].destination_ports == (6443,)
    assert rules["core-proxy:rancher-nodes"].destination_ports == (3128,)
    assert rules["core-dns:upstream"].destination_ports == (53,)
    assert rules["downstream-rancher-agent:vlan565"].destination_ports == (443,)
    assert rules["downstream-rancher-agent:vlan565"].destination.resolved[
        0
    ].reference == EntityReference("endpoint", "endpoint:rancher")
    assert all(rule.verification == UNVERIFIED for rule in rules.values())
    assert all(rule.verification_status == UNVERIFIED for rule in rules.values())
    assert all(
        "verification" in item and "verification_status" not in item
        for item in topology.to_dict()["connectivity_rules"]
    )
    assert {rule.category for rule in rules.values()} == {
        ADMINISTRATIVE,
        DEPLOYMENT,
        CORE_SERVICE,
        RKE2_RANCHER,
        DOWNSTREAM,
    }


def test_v2_connectivity_selects_deterministic_bastion_egress_interfaces():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    rules = by_id(topology.connectivity_rules)

    customer_source = rules["admin-ssh:bastion:rancher1"].source.resolved[0]
    upstream_source = rules["core-dns:upstream"].source.resolved[0]
    os_dns_source = rules["core-dns:bastion-os"].source.resolved[0]
    assert (customer_source.address, customer_source.egress_interface) == (
        "198.51.100.4",
        EntityReference("interface", "bastion1:0"),
    )
    assert (upstream_source.address, upstream_source.egress_interface) == (
        "192.0.2.10",
        EntityReference("interface", "bastion1:1"),
    )
    assert (os_dns_source.address, os_dns_source.egress_interface) == (
        "192.0.2.10",
        EntityReference("interface", "bastion1:1"),
    )


def test_v2_connectivity_leaves_undetermined_egress_source_symbolic():
    config = raw_config()
    config["bastion"]["dnsmasq_upstream_servers"] = ["203.0.113.10"]
    topology = build_desired_topology(expand_env(config))
    source = by_id(topology.connectivity_rules)["core-dns:upstream"].source.resolved[0]

    assert source.address is None
    assert source.address_kind == SYMBOLIC_ADDRESS
    assert source.egress_interface is None


def test_v2_downstream_agent_uses_local_rancher_endpoint_scope():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    rule = by_id(topology.connectivity_rules)["downstream-rancher-agent:vlan565"]

    assert rule.destination.resolution_scope == "local"
    assert tuple(item.address for item in rule.destination.resolved) == (
        "198.51.100.11",
        "198.51.100.12",
        "198.51.100.13",
    )
    assert all(
        item.reference == EntityReference("endpoint", "endpoint:rancher")
        and item.address_kind == IP_ADDRESS
        for item in rule.destination.resolved
    )


def test_v2_support_dependencies_are_typed_and_external_routing_is_symbolic():
    topology = build_desired_topology(load_env(FULL_CONFIG))
    rules = by_id(topology.connectivity_rules)

    assert rules["deployment:terraform-backend"].category == DEPLOYMENT
    assert rules["deployment:terraform-backend"].destination_ports == (443,)
    assert rules["deployment:vcenter-api"].destination.resolved[0].address == "vcenter.example.invalid"
    assert rules["deployment:vcenter-api"].destination_ports == (443,)
    assert rules["core-dns:bastion-os"].destination_ports == (53,)
    assert rules["core-proxy:upstream"].destination.resolved[0].address is None
    route = rules["external-routing:customer:vlan565"]
    assert route.semantics == EXTERNAL_ROUTING_DEPENDENCY
    assert route.protocols == ()
    assert route.via == (EntityReference("endpoint", "endpoint:external-routed-fabric"),)
    assert topology.downstream_networks[0].bastion_is_router is False


def test_downstream_dns_uses_same_vlan_bastion_address():
    topology = topology_with(
        downstream_network(565, "10.20.56.32/27"),
        downstream_network(566, "10.20.56.64/27"),
    )
    dns_rules = [rule for rule in topology.connectivity_rules if rule.id.startswith("downstream-dns:")]

    assert [rule.source.resolved[0].address for rule in dns_rules] == [
        "10.20.56.32/27",
        "10.20.56.64/27",
    ]
    assert [rule.destination.resolved[0].address for rule in dns_rules] == [
        "10.20.56.34",
        "10.20.56.66",
    ]
    assert [rule.source.resolved[0].reference for rule in dns_rules] == [
        EntityReference("downstream-consumer", "consumer:downstream:vlan565"),
        EntityReference("downstream-consumer", "consumer:downstream:vlan566"),
    ]
    assert [rule.destination.resolved[0].reference for rule in dns_rules] == [
        EntityReference("service", "dns:vlan565"),
        EntityReference("service", "dns:vlan566"),
    ]
    assert all(
        rule.protocols == ("TCP", "UDP")
        and rule.source_ports == ()
        and rule.destination_ports == (53,)
        for rule in dns_rules
    )
    assert all(rule.requirement_sources == ("RINSTALL_ARCHITECTURE",) for rule in dns_rules)
    assert all(rule.required is True for rule in dns_rules)


def test_every_rancher_host_has_required_ssh_rule_to_every_downstream_cidr():
    topology = topology_with(
        downstream_network(565, "10.20.56.32/27"),
        downstream_network(566, "10.20.56.64/27"),
    )
    ssh_rules = [rule for rule in topology.connectivity_rules if rule.id.startswith("rancher-downstream-ssh:")]

    assert len(ssh_rules) == 2
    assert all(
        [endpoint.id for endpoint in rule.source.resolved] == ["rancher1", "rancher2", "rancher3"]
        for rule in ssh_rules
    )
    assert [rule.destination.resolved[0].address for rule in ssh_rules] == [
        "10.20.56.32/27",
        "10.20.56.64/27",
    ]
    assert all(
        [endpoint.reference for endpoint in rule.source.resolved]
        == [
            EntityReference("host", "rancher1"),
            EntityReference("host", "rancher2"),
            EntityReference("host", "rancher3"),
        ]
        for rule in ssh_rules
    )
    assert [rule.destination.resolved[0].reference for rule in ssh_rules] == [
        EntityReference("downstream-consumer", "consumer:downstream:vlan565"),
        EntityReference("downstream-consumer", "consumer:downstream:vlan566"),
    ]
    assert all(
        rule.protocols == ("TCP",)
        and rule.source_ports == ()
        and rule.destination_ports == (22,)
        for rule in ssh_rules
    )
    assert all(rule.required is True for rule in ssh_rules)
    assert all(rule.verification == UNVERIFIED for rule in ssh_rules)
    assert all(rule.provenance == RINSTALL_ARCHITECTURE for rule in ssh_rules)
    assert all(rule.requirement_sources == (RINSTALL_ARCHITECTURE,) for rule in ssh_rules)
    assert all(rule.category == DOWNSTREAM for rule in ssh_rules)


def test_dhcp_rules_and_service_use_directional_upstream_protocol_ports():
    topology = topology_with(downstream_network(565, "10.20.56.32/27"))
    request = next(rule for rule in topology.connectivity_rules if rule.id.startswith("downstream-dhcp-request:"))
    response = next(rule for rule in topology.connectivity_rules if rule.id.startswith("downstream-dhcp-response:"))
    service = next(service for service in topology.services if service.id == "dhcp:vlan565")

    assert request.protocols == response.protocols == ("UDP",)
    assert (request.source_ports, request.destination_ports) == ((68,), (67,))
    assert (response.source_ports, response.destination_ports) == ((67,), (68,))
    assert request.requirement_sources == response.requirement_sources == (
        "RINSTALL_CODE",
        "UPSTREAM_PROTOCOL",
    )
    assert request.destination.resolved[0].address is None
    assert response.source.resolved[0].address is None
    assert request.source.resolved[0].address is None
    assert response.destination.resolved[0].address is None
    assert request.semantics == response.semantics == L2_SERVICE_INTENT
    assert request.source.resolution_scope == response.destination.resolution_scope == "same-l2-segment"
    assert "may broadcast" in request.purpose
    assert request.source.resolved[0].address_kind == SYMBOLIC_ADDRESS
    assert request.destination.resolved[0].id == "dhcp:vlan565"
    assert request.category == response.category == DOWNSTREAM
    assert request.source.resolved[0].reference == EntityReference(
        "downstream-consumer", "consumer:downstream:vlan565"
    )
    assert request.destination.resolved[0].reference == EntityReference(
        "service", "dhcp:vlan565"
    )
    assert service.address == "10.20.56.34"
    assert service.ports == (67, 68)


def test_json_and_markdown_share_one_topology_and_are_deterministic():
    topology = topology_with(downstream_network(565, "10.20.56.32/27"))

    first_json = render_topology_json(topology)
    second_json = render_topology_json(topology)
    first_markdown = render_topology_markdown(topology)
    second_markdown = render_topology_markdown(topology)

    assert first_json == second_json
    assert first_markdown == second_markdown
    assert json.loads(first_json) == topology.to_dict()
    assert "rancher1 (primary), rancher2 (member), rancher3 (member)" in first_markdown
    assert "downstream:vlan565" in first_markdown
    assert "10.20.56.34" in first_markdown
    assert "TCP/UDP * -&gt; 53" in first_markdown
    assert "TCP * -&gt; 22" in first_markdown


def test_v2_serialization_canonicalizes_unordered_config_mappings():
    original = yaml.safe_load(FULL_CONFIG.read_text())
    reordered = deepcopy(original)
    reordered["nodes"] = dict(reversed(tuple(reordered["nodes"].items())))
    reordered["infra"]["networks"] = dict(
        reversed(tuple(reordered["infra"]["networks"].items()))
    )
    reordered["infra"]["templates"] = dict(
        reversed(tuple(reordered["infra"]["templates"].items()))
    )
    reordered["bastion"]["dnsmasq_upstream_servers"].reverse()

    assert render_topology_json(build_desired_topology(expand_env(original))) == render_topology_json(
        build_desired_topology(expand_env(reordered))
    )


def test_topology_outputs_exclude_sensitive_config_values(tmp_path):
    config = raw_config()
    secrets = [
        "rke2-token-secret",
        "rancher-bootstrap-secret",
        "/sensitive/operator/key",
        "/sensitive/jump/key",
    ]
    config["rke2"]["token"] = secrets[0]
    config["rancher"]["bootstrap_password"] = secrets[1]
    config.setdefault("ssh", {})["private_key"] = secrets[2]
    config["ssh"]["jump_host"] = {
        "alias": "external-jump",
        "hostname": "jump.example.invalid",
        "private_key": secrets[3],
    }
    config["bastion"]["downstream_networks"] = [downstream_network(565, "10.20.56.32/27")]
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    output_dir = tmp_path / ".rinstall"

    command = [
        sys.executable,
        str(RENDER_TOPOLOGY),
        "--config",
        str(config_path),
        "--output-dir",
        str(output_dir),
    ]
    subprocess.run(
        command,
        check=True,
    )
    first_json = (output_dir / "topology.json").read_bytes()
    first_markdown = (output_dir / "topology.md").read_bytes()
    first_text = (output_dir / "topology.txt").read_bytes()
    first_network_mermaid = (output_dir / "network-topology.mmd").read_bytes()
    subprocess.run(
        command,
        check=True,
    )

    outputs = (
        (output_dir / "topology.json").read_text()
        + (output_dir / "topology.md").read_text()
        + (output_dir / "topology.txt").read_text()
        + (output_dir / "network-topology.mmd").read_text()
    )
    assert (output_dir / "topology.json").read_bytes() == first_json
    assert (output_dir / "topology.md").read_bytes() == first_markdown
    assert (output_dir / "topology.txt").read_bytes() == first_text
    assert (output_dir / "network-topology.mmd").read_bytes() == first_network_mermaid
    assert not (output_dir / "connectivity.mmd").exists()
    assert not (output_dir / "topology.svg").exists()
    assert all(secret not in outputs for secret in secrets)
    assert output_dir.stat().st_mode & 0o777 == 0o700
    assert (output_dir / "topology.json").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "topology.md").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "topology.txt").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "network-topology.mmd").stat().st_mode & 0o777 == 0o600
    assert not (output_dir / "topology.mmd").exists()
    assert not (output_dir / "network-topology.dot").exists()
    assert not (output_dir / "network-topology.svg").exists()


def test_markdown_escapes_configured_table_values():
    config = raw_config()
    config["infra"]["networks"]["customer"] = "CUSTOMER|NETWORK"
    config["rke2"]["version"] = "version|value"

    markdown = render_topology_markdown(build_desired_topology(expand_env(config)))

    assert "CUSTOMER\\|NETWORK" in markdown
    assert "version\\|value" in markdown


def test_topology_script_requires_explicit_config_and_output_directory():
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER_TOPOLOGY),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--config" in result.stderr
    assert "--output-dir" in result.stderr


def test_building_topology_does_not_change_expanded_config():
    expanded = expand_env(raw_config())
    before = deepcopy(expanded)

    build_desired_topology(expanded)

    assert expanded == before
