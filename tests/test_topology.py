from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import yaml

from lib.env_config import expand_env
from lib.topology import (
    HostTopology,
    build_desired_topology,
    render_topology_json,
    render_topology_markdown,
    render_topology_ascii_overview,
    render_topology_connectivity_mermaid,
    render_topology_infrastructure_mermaid,
    render_topology_svg,
)


ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "envs/example/env.yaml"
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
        rule.protocols == ("TCP",)
        and rule.source_ports == ()
        and rule.destination_ports == (22,)
        for rule in ssh_rules
    )
    assert all(rule.required is True for rule in ssh_rules)
    assert all(rule.verification_status == "external/unverified" for rule in ssh_rules)


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
    assert request.destination.resolved[0].address == "10.20.56.34"
    assert response.source.resolved[0].address == "10.20.56.34"
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
    assert "rancher1 (10.14.17.11), rancher2 (10.14.17.12), rancher3 (10.14.17.13)" in first_markdown
    assert "vlan565 (10.20.56.32/27)" in first_markdown
    assert "bastion1:vlan565 (10.20.56.34)" in first_markdown
    assert "TCP/UDP 53" in first_markdown
    assert "TCP 22" in first_markdown


def test_ascii_and_mermaid_are_deterministic_secondary_artifacts():
    topology = topology_with(downstream_network(565, "10.20.56.32/27"))

    ascii_overview = render_topology_ascii_overview(topology)
    mermaid = render_topology_infrastructure_mermaid(topology)
    connectivity = render_topology_connectivity_mermaid(topology)
    markdown = render_topology_markdown(topology)

    assert render_topology_infrastructure_mermaid(topology) == mermaid
    assert render_topology_ascii_overview(topology) == ascii_overview
    assert "<svg " in markdown
    assert mermaid not in markdown
    assert connectivity not in markdown
    assert ascii_overview not in markdown
    assert "## Infrastructure Map" in markdown
    assert "## Key Connectivity" in markdown
    assert "Rancher nodes -> Downstream nodes       TCP/22" in markdown
    assert markdown.index("## Infrastructure Map") < markdown.index("## Environment")
    assert markdown.index("## Key Connectivity") < markdown.index("## Resolved Connectivity")
    assert "bastion1" in ascii_overview
    assert "management  192.0.2.10/24" in ascii_overview
    assert "vlan565     10.20.56.34/27" in ascii_overview
    assert "rancher1" in ascii_overview and "prom1" in ascii_overview
    assert "DNS, DHCP" in ascii_overview
    assert ascii_overview.count("DNS, DHCP") == 1
    assert all(len(line) <= 80 for line in ascii_overview.splitlines())


def test_mermaid_shows_all_core_nodes_and_same_vlan_relationships():
    topology = topology_with(
        downstream_network(565, "10.20.56.32/27"),
        downstream_network(566, "10.20.56.64/27"),
    )

    infrastructure = render_topology_infrastructure_mermaid(topology)
    mermaid = render_topology_connectivity_mermaid(topology)

    assert all(host in infrastructure for host in ("rancher1", "rancher2", "rancher3", "prom1", "bastion1"))
    assert '"TCP' not in infrastructure
    assert '"DNS' not in infrastructure
    assert "DHCP" not in infrastructure
    assert all("---|" not in line for line in infrastructure.splitlines())
    assert mermaid.count('-->|"TCP/22 SSH"|') == 1
    assert mermaid.count('-->|"TCP/UDP 53 DNS"|') == 1
    assert mermaid.count('-.->|"logical DHCP service UDP 67/68"|') == 1
    assert "each downstream VLAN" in mermaid
    assert "10.20.56.34" not in mermaid
    assert "10.20.56.66" not in mermaid


def test_mermaid_supports_arbitrary_rancher_names_and_safe_ids():
    config = raw_config()
    config["local"]["rancher_nodes"]["name_prefix"] = 'control.east/"] {'
    config["local"]["rancher_nodes"]["count"] = 2
    topology = build_desired_topology(expand_env(config))

    mermaid = render_topology_infrastructure_mermaid(topology)

    assert "control.east/\"] {1" not in mermaid
    assert "control.east/" in mermaid
    for line in mermaid.splitlines():
        if not line.strip().startswith("host_") or "[" not in line:
            continue
        node_id = line.strip().split("[", 1)[0]
        assert node_id.replace("_", "").isalnum()


def test_mermaid_shows_external_jump_only_when_topology_represents_it():
    topology = topology_with()
    external = HostTopology(
        id="operator.jump/eu-1",
        hostname="operator.jump/eu-1",
        fqdn="operator.jump/eu-1",
        roles=("external-jump",),
        capabilities=("jump-host",),
        primary_ip=None,
        local_ip=None,
        management_ip=None,
        ssh_target="192.0.2.200",
    )
    represented = replace(topology, hosts=(external, *topology.hosts))

    without_external = render_topology_infrastructure_mermaid(topology)
    with_external = render_topology_infrastructure_mermaid(represented)

    assert "External jump" not in without_external
    assert "External jump" not in with_external


def test_connectivity_mermaid_has_constant_symbolic_shape():
    one = render_topology_connectivity_mermaid(topology_with(downstream_network(565, "10.20.56.32/27")))
    many = render_topology_connectivity_mermaid(
        topology_with(
            downstream_network(565, "10.20.56.32/27"),
            downstream_network(566, "10.20.56.64/27"),
        )
    )

    assert one == many


def test_svg_is_deterministic_hierarchical_and_has_no_service_edges():
    topology = topology_with(
        downstream_network(565, "10.20.56.32/27"),
        downstream_network(566, "10.20.56.64/27"),
    )

    first = render_topology_svg(topology)
    second = render_topology_svg(topology)

    assert first == second
    assert 'viewBox="0 0 980 478"' in first
    assert "bastion1" in first and "prom1" in first
    assert all(name in first for name in ("rancher1", "rancher2", "rancher3"))
    assert all(value in first for value in ("192.0.2.0/24", "10.14.17.0/28", "10.20.56.34", "10.20.56.66"))
    assert all(value not in first for value in ("TCP/22", "DNS", "DHCP", "SSH"))
    assert "Bastion IP" not in first
    assert first.count('class="rancher-cluster"') == 1
    assert first.count('data-connection="') == 5

    root = ET.fromstring(first)
    namespace = "{http://www.w3.org/2000/svg}"
    connectors = {
        item.attrib["data-connection"]: [
            tuple(map(int, point.split(","))) for point in item.attrib["points"].split()
        ]
        for item in root.iter(f"{namespace}polyline")
    }
    assert connectors == {
        "management-bastion": [(435, 74), (435, 100)],
        "bastion-customer": [(325, 141), (180, 141), (180, 235)],
        "customer-monitoring": [(150, 293), (150, 340)],
        "customer-rancher": [(250, 293), (250, 320), (400, 320), (400, 340)],
        "bastion-downstream": [(545, 141), (558, 141), (558, 245), (570, 245)],
    }
    assert not list(root.iter(f"{namespace}line"))
    for coordinates in connectors.values():
        assert all(x1 == x2 or y1 == y2 for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:]))
        assert all(x < 600 and y < 350 for x, y in coordinates)

    groups = {
        group.attrib["id"]: group
        for group in root.iter(f"{namespace}g")
        if "id" in group.attrib
    }

    def on_boundary(point, group_id):
        rect = next(groups[group_id].iter(f"{namespace}rect"))
        x, y, width, height = (float(rect.attrib[name]) for name in ("x", "y", "width", "height"))
        px, py = point
        return (
            (px in (x, x + width) and y <= py <= y + height)
            or (py in (y, y + height) and x <= px <= x + width)
        )

    endpoints = {
        "management-bastion": ("management-network", "bastion"),
        "bastion-customer": ("bastion", "customer-network"),
        "customer-monitoring": ("customer-network", "monitoring"),
        "customer-rancher": ("customer-network", "rancher-cluster"),
        "bastion-downstream": ("bastion", "downstream-networks"),
    }
    assert all(
        on_boundary(connectors[name][0], source) and on_boundary(connectors[name][-1], destination)
        for name, (source, destination) in endpoints.items()
    )

    def intersects(first, second):
        (ax1, ay1), (ax2, ay2) = first
        (bx1, by1), (bx2, by2) = second
        if ax1 == ax2 and bx1 == bx2:
            return ax1 == bx1 and max(min(ay1, ay2), min(by1, by2)) <= min(
                max(ay1, ay2), max(by1, by2)
            )
        if ay1 == ay2 and by1 == by2:
            return ay1 == by1 and max(min(ax1, ax2), min(bx1, bx2)) <= min(
                max(ax1, ax2), max(bx1, bx2)
            )
        if ay1 == ay2:
            return min(ax1, ax2) <= bx1 <= max(ax1, ax2) and min(by1, by2) <= ay1 <= max(by1, by2)
        return min(bx1, bx2) <= ax1 <= max(bx1, bx2) and min(ay1, ay2) <= by1 <= max(ay1, ay2)

    connector_segments = {
        name: list(zip(points, points[1:])) for name, points in connectors.items()
    }
    names = list(connector_segments)
    assert not any(
        intersects(first, second)
        for index, name in enumerate(names)
        for other_name in names[index + 1 :]
        for first in connector_segments[name]
        for second in connector_segments[other_name]
    )


def test_svg_wraps_five_and_ten_downstream_networks_without_overlap():
    for count in (1, 2, 5, 10):
        if count <= 8:
            topology = topology_with(
                *(downstream_network(565 + index, f"10.20.{56 + index}.0/27") for index in range(count))
            )
        else:
            base = topology_with(
                *(downstream_network(565 + index, f"10.20.{56 + index}.0/27") for index in range(8))
            )
            extra = tuple(
                replace(
                    base.downstream_networks[0],
                    id=f"downstream:vlan{565 + index}",
                    interface_name=f"vlan{565 + index}",
                    vlan=565 + index,
                    cidr=f"10.20.{56 + index}.0/27",
                    bastion_address=f"10.20.{56 + index}.2",
                    gateway=f"10.20.{56 + index}.1",
                )
                for index in range(8, count)
            )
            topology = replace(base, downstream_networks=base.downstream_networks + extra)
        svg = render_topology_svg(topology)
        root = ET.fromstring(svg)
        viewbox = [float(value) for value in root.attrib["viewBox"].split()]
        assert viewbox[:2] == [0.0, 0.0]
        assert viewbox[2] == 980.0
        assert viewbox[3] <= (500.0 if count <= 2 else 800.0)
        boxes = [
            (float(rect.attrib["x"]), float(rect.attrib["y"]), float(rect.attrib["width"]), float(rect.attrib["height"]))
            for rect in root.iter("{http://www.w3.org/2000/svg}rect")
            if rect.attrib.get("class") == "downstream"
        ]
        assert len(boxes) == count
        assert all(x + width <= viewbox[2] and y + height <= viewbox[3] for x, y, width, height in boxes)
        for index, (x, y, width, height) in enumerate(boxes):
            for other_x, other_y, other_width, other_height in boxes[index + 1 :]:
                assert x + width <= other_x or other_x + other_width <= x or y + height <= other_y or other_y + other_height <= y


def test_topology_outputs_exclude_sensitive_config_values(tmp_path):
    config = raw_config()
    secrets = [
        "rke2-token-secret",
        "rancher-bootstrap-secret",
        "/sensitive/operator/key",
    ]
    config["rke2"]["token"] = secrets[0]
    config["rancher"]["bootstrap_password"] = secrets[1]
    config.setdefault("ssh", {})["private_key"] = secrets[2]
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
    first_mermaid = (output_dir / "topology.mmd").read_bytes()
    first_connectivity = (output_dir / "connectivity.mmd").read_bytes()
    first_svg = (output_dir / "topology.svg").read_bytes()
    subprocess.run(
        command,
        check=True,
    )

    outputs = (
        (output_dir / "topology.json").read_text()
        + (output_dir / "topology.md").read_text()
        + (output_dir / "topology.txt").read_text()
        + (output_dir / "topology.mmd").read_text()
        + (output_dir / "connectivity.mmd").read_text()
        + (output_dir / "topology.svg").read_text()
    )
    assert (output_dir / "topology.json").read_bytes() == first_json
    assert (output_dir / "topology.md").read_bytes() == first_markdown
    assert (output_dir / "topology.txt").read_bytes() == first_text
    assert (output_dir / "topology.mmd").read_bytes() == first_mermaid
    assert (output_dir / "connectivity.mmd").read_bytes() == first_connectivity
    assert (output_dir / "topology.svg").read_bytes() == first_svg
    assert all(secret not in outputs for secret in secrets)
    assert output_dir.stat().st_mode & 0o777 == 0o700
    assert (output_dir / "topology.json").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "topology.md").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "topology.txt").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "topology.mmd").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "connectivity.mmd").stat().st_mode & 0o777 == 0o600
    assert (output_dir / "topology.svg").stat().st_mode & 0o777 == 0o600


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
