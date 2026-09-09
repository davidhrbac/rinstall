from dataclasses import asdict, dataclass
from html import escape
from ipaddress import ip_interface, ip_network
import json

RINSTALL_ARCHITECTURE = "RINSTALL_ARCHITECTURE"
RINSTALL_CODE = "RINSTALL_CODE"
UPSTREAM_PROTOCOL = "UPSTREAM_PROTOCOL"
EXTERNAL_UNVERIFIED = "external/unverified"


@dataclass(frozen=True)
class TopologyMetadata:
    topology_schema_version: int
    config_schema_version: int
    topology_kind: str
    environment_id: str
    rancher_url: str
    domain: str
    bastion_host: str
    versions: dict[str, str]


@dataclass(frozen=True)
class HostTopology:
    id: str
    hostname: str
    fqdn: str
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    primary_ip: str | None
    local_ip: str | None
    management_ip: str | None
    ssh_target: str | None


@dataclass(frozen=True)
class InterfaceTopology:
    id: str
    host: str
    nic_index: int
    logical_name: str
    network: str
    network_kind: str
    address: str | None
    prefix: int | None
    addressing: str


@dataclass(frozen=True)
class NetworkTopology:
    id: str
    kind: str
    cidr: str | None
    vlan: int | None
    vmware_network: str
    gateway: str | None
    interface_ids: tuple[str, ...]


@dataclass(frozen=True)
class LifecyclePolicy:
    collection: str
    identity: str
    mutable_fields: tuple[str, ...]
    immutable_fields: tuple[str, ...]


@dataclass(frozen=True)
class DownstreamNetworkTopology:
    id: str
    interface_name: str
    vlan: int
    vmware_network: str
    cidr: str
    bastion_host: str
    bastion_address: str
    gateway: str
    dhcp_start: str
    dhcp_end: str
    dhcp_lease: str
    lifecycle: LifecyclePolicy


@dataclass(frozen=True)
class ServiceTopology:
    id: str
    kind: str
    host: str
    network: str | None
    address: str
    protocols: tuple[str, ...]
    ports: tuple[int, ...]
    purpose: str


@dataclass(frozen=True)
class ResolvedEndpoint:
    id: str
    address: str


@dataclass(frozen=True)
class ConnectivityEndpoint:
    symbolic: str
    resolved: tuple[ResolvedEndpoint, ...]


@dataclass(frozen=True)
class ConnectivityRule:
    id: str
    source: ConnectivityEndpoint
    destination: ConnectivityEndpoint
    protocols: tuple[str, ...]
    source_ports: tuple[int, ...]
    destination_ports: tuple[int, ...]
    purpose: str
    requirement_sources: tuple[str, ...]
    required: bool
    verification_status: str


@dataclass(frozen=True)
class ArchitectureRule:
    id: str
    protocols: tuple[str, ...]
    source_ports: tuple[int, ...]
    destination_ports: tuple[int, ...]
    purpose: str
    requirement_sources: tuple[str, ...]
    required: bool = True
    verification_status: str = EXTERNAL_UNVERIFIED


@dataclass(frozen=True)
class EnvironmentTopology:
    metadata: TopologyMetadata
    hosts: tuple[HostTopology, ...]
    interfaces: tuple[InterfaceTopology, ...]
    networks: tuple[NetworkTopology, ...]
    services: tuple[ServiceTopology, ...]
    downstream_networks: tuple[DownstreamNetworkTopology, ...]
    connectivity_rules: tuple[ConnectivityRule, ...]
    notes: tuple[str, ...]

    def to_dict(self):
        return _json_value(asdict(self))


DOWNSTREAM_DNS_RULE = ArchitectureRule(
    id="downstream-dns",
    protocols=("TCP", "UDP"),
    source_ports=(),
    destination_ports=(53,),
    purpose="DNS for downstream nodes",
    requirement_sources=(RINSTALL_ARCHITECTURE,),
)

RANCHER_DOWNSTREAM_SSH_RULE = ArchitectureRule(
    id="rancher-downstream-ssh",
    protocols=("TCP",),
    source_ports=(),
    destination_ports=(22,),
    purpose="Administrator SSH from Rancher nodes to downstream nodes",
    requirement_sources=(RINSTALL_ARCHITECTURE,),
)

DOWNSTREAM_DHCP_REQUEST_RULE = ArchitectureRule(
    id="downstream-dhcp-request",
    protocols=("UDP",),
    source_ports=(68,),
    destination_ports=(67,),
    purpose="Downstream DHCP request",
    requirement_sources=(RINSTALL_CODE, UPSTREAM_PROTOCOL),
)

DOWNSTREAM_DHCP_RESPONSE_RULE = ArchitectureRule(
    id="downstream-dhcp-response",
    protocols=("UDP",),
    source_ports=(67,),
    destination_ports=(68,),
    purpose="Downstream DHCP response",
    requirement_sources=(RINSTALL_CODE, UPSTREAM_PROTOCOL),
)


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _network_kind(network_name):
    if network_name == "customer":
        return "local/customer"
    if network_name == "management":
        return "management"
    return "other"


def _interface_network(address, prefix):
    if address is None or prefix is None:
        return None
    return str(ip_interface(f"{address}/{prefix}").network)


def _single_network_cidr(interfaces):
    cidrs = {
        cidr
        for interface in interfaces
        if (cidr := _interface_network(interface.address, interface.prefix)) is not None
    }
    return next(iter(cidrs)) if len(cidrs) == 1 else None


def _service_network(address, interfaces):
    return next((interface.network for interface in interfaces if interface.address == address), None)


def _endpoint_text(endpoint):
    return ", ".join(
        item.address if item.id == item.address else f"{item.id} ({item.address})"
        for item in endpoint.resolved
    ) or "unknown"


def _protocol_port(rule):
    protocols = "/".join(rule.protocols)
    destination_ports = "/".join(str(port) for port in rule.destination_ports)
    if rule.source_ports:
        source_ports = "/".join(str(port) for port in rule.source_ports)
        return f"{protocols} {source_ports} -> {destination_ports}"
    return f"{protocols} {destination_ports}"


def _markdown(value):
    return escape(str(value), quote=False).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def build_desired_topology(config):
    environment_id = config["environment"]["id"]
    bastion_host = config["bastion"]["service_node"]
    interfaces = []
    hosts = []

    for host_id, node in config["nodes"].items():
        host_interfaces = []
        for nic_index, nic in enumerate(node["nics"]):
            network_id = nic["network"]
            interface = InterfaceTopology(
                id=f"{host_id}:{nic_index}",
                host=host_id,
                nic_index=nic_index,
                logical_name=network_id,
                network=network_id,
                network_kind=_network_kind(network_id),
                address=nic.get("ip"),
                prefix=nic.get("prefix"),
                addressing="static" if nic.get("ip") is not None else "unknown",
            )
            interfaces.append(interface)
            host_interfaces.append(interface)

        local_ip = next(
            (interface.address for interface in host_interfaces if interface.network == "customer"),
            None,
        )
        management_ip = next(
            (interface.address for interface in host_interfaces if interface.network == "management"),
            None,
        )
        capabilities = ()
        if host_id == bastion_host:
            capabilities = ("jump-host", "dns", "dhcp", "proxy")
        hosts.append(
            HostTopology(
                id=host_id,
                hostname=host_id,
                fqdn=f"{host_id}.{config['rancher_url']}",
                roles=(node["role"],),
                capabilities=capabilities,
                primary_ip=node.get("ip"),
                local_ip=local_ip,
                management_ip=management_ip,
                ssh_target=node.get("ssh_ip") or node.get("management_ip") or node.get("ip"),
            )
        )

    downstream_networks = []
    base_nic_count = len(config["nodes"][bastion_host]["nics"])
    for index, downstream in enumerate(config["bastion"]["downstream_networks"]):
        network_id = f"downstream:{downstream['interface_name']}"
        interfaces.append(
            InterfaceTopology(
                id=f"{bastion_host}:{downstream['interface_name']}",
                host=bastion_host,
                nic_index=base_nic_count + index,
                logical_name=downstream["interface_name"],
                network=network_id,
                network_kind="downstream",
                address=downstream["bastion_address"],
                prefix=downstream["prefix"],
                addressing="static",
            )
        )
        downstream_networks.append(
            DownstreamNetworkTopology(
                id=network_id,
                interface_name=downstream["interface_name"],
                vlan=downstream["vlan"],
                vmware_network=downstream["vmware_network"],
                cidr=downstream["subnet"],
                bastion_host=bastion_host,
                bastion_address=downstream["bastion_address"],
                gateway=downstream["gateway"],
                dhcp_start=downstream["dhcp"]["start"],
                dhcp_end=downstream["dhcp"]["end"],
                dhcp_lease=downstream["dhcp"]["lease_time"],
                lifecycle=LifecyclePolicy(
                    collection="append-only",
                    identity="immutable-after-create",
                    mutable_fields=("dhcp.start", "dhcp.end", "dhcp.lease_time"),
                    immutable_fields=(
                        "vlan",
                        "vmware_network",
                        "subnet",
                        "bastion_address",
                        "gateway",
                        "attachment_order",
                    ),
                ),
            )
        )

    networks = []
    for network_id, vmware_network in config["infra"]["networks"].items():
        attached = tuple(interface for interface in interfaces if interface.network == network_id)
        kind = _network_kind(network_id)
        cidr = (
            str(ip_network(config["local_vlan"]["cidr"], strict=False))
            if kind == "local/customer"
            else _single_network_cidr(attached)
        )
        gateway = config["local_vlan"]["gateway"] if kind == "local/customer" else None
        networks.append(
            NetworkTopology(
                id=network_id,
                kind=kind,
                cidr=cidr,
                vlan=None,
                vmware_network=vmware_network,
                gateway=gateway,
                interface_ids=tuple(interface.id for interface in attached),
            )
        )

    for downstream in downstream_networks:
        networks.append(
            NetworkTopology(
                id=downstream.id,
                kind="downstream",
                cidr=downstream.cidr,
                vlan=downstream.vlan,
                vmware_network=downstream.vmware_network,
                gateway=downstream.gateway,
                interface_ids=(f"{bastion_host}:{downstream.interface_name}",),
            )
        )

    services = []
    bastion_service_ip = config["bastion"]["service_ip"]
    services.append(
        ServiceTopology(
            id="proxy:squid",
            kind="proxy",
            host=bastion_host,
            network=_service_network(bastion_service_ip, interfaces),
            address=bastion_service_ip,
            protocols=("TCP",),
            ports=(config["bastion"]["squid_http_port"],),
            purpose="HTTP and HTTPS forward proxy for local services",
        )
    )
    services.append(
        ServiceTopology(
            id="dns:local",
            kind="dns",
            host=bastion_host,
            network=_service_network(bastion_service_ip, interfaces),
            address=bastion_service_ip,
            protocols=("TCP", "UDP"),
            ports=(53,),
            purpose="DNS for local nodes",
        )
    )
    for downstream in downstream_networks:
        services.extend(
            [
                ServiceTopology(
                    id=f"dns:{downstream.interface_name}",
                    kind="dns",
                    host=bastion_host,
                    network=downstream.id,
                    address=downstream.bastion_address,
                    protocols=("TCP", "UDP"),
                    ports=(53,),
                    purpose="DNS for downstream nodes on the same VLAN",
                ),
                ServiceTopology(
                    id=f"dhcp:{downstream.interface_name}",
                    kind="dhcp",
                    host=bastion_host,
                    network=downstream.id,
                    address=downstream.bastion_address,
                    protocols=("UDP",),
                    ports=(67, 68),
                    purpose="DHCP for downstream nodes on the same VLAN",
                ),
            ]
        )

    rancher_sources = tuple(
        ResolvedEndpoint(host.id, host.local_ip or host.primary_ip or "unknown")
        for host in hosts
        if "rancher" in host.roles
    )
    connectivity_rules = []
    for downstream in downstream_networks:
        downstream_source = ConnectivityEndpoint(
            symbolic=f"network:downstream:{downstream.vlan}",
            resolved=(ResolvedEndpoint(downstream.interface_name, downstream.cidr),),
        )
        downstream_bastion = ConnectivityEndpoint(
            symbolic=f"service:dns@bastion:same-vlan:{downstream.vlan}",
            resolved=(
                ResolvedEndpoint(
                    f"{bastion_host}:{downstream.interface_name}",
                    downstream.bastion_address,
                ),
            ),
        )
        connectivity_rules.extend(
            [
                ConnectivityRule(
                    id=f"{DOWNSTREAM_DNS_RULE.id}:{downstream.interface_name}",
                    source=downstream_source,
                    destination=downstream_bastion,
                    protocols=DOWNSTREAM_DNS_RULE.protocols,
                    source_ports=DOWNSTREAM_DNS_RULE.source_ports,
                    destination_ports=DOWNSTREAM_DNS_RULE.destination_ports,
                    purpose=DOWNSTREAM_DNS_RULE.purpose,
                    requirement_sources=DOWNSTREAM_DNS_RULE.requirement_sources,
                    required=DOWNSTREAM_DNS_RULE.required,
                    verification_status=DOWNSTREAM_DNS_RULE.verification_status,
                ),
                ConnectivityRule(
                    id=f"{RANCHER_DOWNSTREAM_SSH_RULE.id}:{downstream.interface_name}",
                    source=ConnectivityEndpoint(
                        symbolic="role:rancher",
                        resolved=rancher_sources,
                    ),
                    destination=ConnectivityEndpoint(
                        symbolic=f"network:downstream:{downstream.vlan}",
                        resolved=(ResolvedEndpoint(downstream.interface_name, downstream.cidr),),
                    ),
                    protocols=RANCHER_DOWNSTREAM_SSH_RULE.protocols,
                    source_ports=RANCHER_DOWNSTREAM_SSH_RULE.source_ports,
                    destination_ports=RANCHER_DOWNSTREAM_SSH_RULE.destination_ports,
                    purpose=RANCHER_DOWNSTREAM_SSH_RULE.purpose,
                    requirement_sources=RANCHER_DOWNSTREAM_SSH_RULE.requirement_sources,
                    required=RANCHER_DOWNSTREAM_SSH_RULE.required,
                    verification_status=RANCHER_DOWNSTREAM_SSH_RULE.verification_status,
                ),
                ConnectivityRule(
                    id=f"{DOWNSTREAM_DHCP_REQUEST_RULE.id}:{downstream.interface_name}",
                    source=downstream_source,
                    destination=ConnectivityEndpoint(
                        symbolic=f"service:dhcp@bastion:same-vlan:{downstream.vlan}",
                        resolved=downstream_bastion.resolved,
                    ),
                    protocols=DOWNSTREAM_DHCP_REQUEST_RULE.protocols,
                    source_ports=DOWNSTREAM_DHCP_REQUEST_RULE.source_ports,
                    destination_ports=DOWNSTREAM_DHCP_REQUEST_RULE.destination_ports,
                    purpose=DOWNSTREAM_DHCP_REQUEST_RULE.purpose,
                    requirement_sources=DOWNSTREAM_DHCP_REQUEST_RULE.requirement_sources,
                    required=DOWNSTREAM_DHCP_REQUEST_RULE.required,
                    verification_status=DOWNSTREAM_DHCP_REQUEST_RULE.verification_status,
                ),
                ConnectivityRule(
                    id=f"{DOWNSTREAM_DHCP_RESPONSE_RULE.id}:{downstream.interface_name}",
                    source=ConnectivityEndpoint(
                        symbolic=f"service:dhcp@bastion:same-vlan:{downstream.vlan}",
                        resolved=downstream_bastion.resolved,
                    ),
                    destination=downstream_source,
                    protocols=DOWNSTREAM_DHCP_RESPONSE_RULE.protocols,
                    source_ports=DOWNSTREAM_DHCP_RESPONSE_RULE.source_ports,
                    destination_ports=DOWNSTREAM_DHCP_RESPONSE_RULE.destination_ports,
                    purpose=DOWNSTREAM_DHCP_RESPONSE_RULE.purpose,
                    requirement_sources=DOWNSTREAM_DHCP_RESPONSE_RULE.requirement_sources,
                    required=DOWNSTREAM_DHCP_RESPONSE_RULE.required,
                    verification_status=DOWNSTREAM_DHCP_RESPONSE_RULE.verification_status,
                ),
            ]
        )

    notes = [
        "Desired topology only; provider state, guest runtime state, and network reachability are not verified."
    ]
    management_networks = [network for network in networks if network.kind == "management"]
    for network in management_networks:
        if network.cidr is None:
            notes.append(
                f"Management network {network.id} CIDR/address is not represented in desired config."
            )
    for host in hosts:
        if any(interface.network_kind == "management" for interface in interfaces if interface.host == host.id):
            if host.management_ip is None:
                notes.append(f"Host {host.id} management address is unknown in desired config.")

    metadata = TopologyMetadata(
        topology_schema_version=1,
        config_schema_version=config["schema_version"],
        topology_kind="desired",
        environment_id=environment_id,
        rancher_url=config["rancher_url"],
        domain=config["domain"],
        bastion_host=bastion_host,
        versions={
            "rke2": config["rke2"]["version"],
            "rancher": config["rancher"]["rancher_chart_version"],
            "cert_manager": config["rancher"]["cert_manager_version"],
        },
    )
    return EnvironmentTopology(
        metadata=metadata,
        hosts=tuple(hosts),
        interfaces=tuple(interfaces),
        networks=tuple(networks),
        services=tuple(services),
        downstream_networks=tuple(downstream_networks),
        connectivity_rules=tuple(connectivity_rules),
        notes=tuple(notes),
    )


def render_topology_json(topology):
    return json.dumps(topology.to_dict(), indent=2) + "\n"


def render_topology_markdown(topology):
    metadata = topology.metadata
    lines = [
        f"# Desired Topology: {metadata.environment_id}",
        "",
        "## Environment Overview",
        "",
        "| Environment | Rancher URL | Domain | RKE2 | Rancher | cert-manager |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {_markdown(metadata.environment_id)} | {_markdown(metadata.rancher_url)} | "
        f"{_markdown(metadata.domain)} | {_markdown(metadata.versions['rke2'])} | "
        f"{_markdown(metadata.versions['rancher'])} | "
        f"{_markdown(metadata.versions['cert_manager'])} |",
        "",
        "## Hosts And Roles",
        "",
        "| Host | FQDN | Roles | Local IP | Management IP | SSH target |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for host in topology.hosts:
        lines.append(
            f"| {_markdown(host.id)} | {_markdown(host.fqdn)} | {_markdown(', '.join(host.roles))} | "
            f"{_markdown(host.local_ip or 'unknown')} | {_markdown(host.management_ip or 'unknown')} | "
            f"{_markdown(host.ssh_target or 'unknown')} |"
        )

    lines.extend(
        [
            "",
            "## Bastion",
            "",
            f"Host {_markdown(metadata.bastion_host)} provides jump-host, DNS, DHCP, and proxy capabilities.",
            "",
            "| Interface | Network | Kind | Address | Addressing |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for interface in topology.interfaces:
        if interface.host != metadata.bastion_host:
            continue
        address = (
            f"{interface.address}/{interface.prefix}"
            if interface.address is not None and interface.prefix is not None
            else "unknown"
        )
        lines.append(
            f"| {_markdown(interface.logical_name)} | {_markdown(interface.network)} | "
            f"{_markdown(interface.network_kind)} | {_markdown(address)} | {_markdown(interface.addressing)} |"
        )

    lines.extend(
        [
            "",
            "### Bastion Services",
            "",
            "| Service | Network | Endpoint | Proto/Port | Purpose |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for service in topology.services:
        protocols = "/".join(service.protocols)
        ports = "/".join(str(port) for port in service.ports)
        lines.append(
            f"| {_markdown(service.kind)} | {_markdown(service.network or 'unknown')} | "
            f"{_markdown(service.address)} | {protocols} {ports} | {_markdown(service.purpose)} |"
        )

    lines.extend(
        [
            "",
            "## Networks",
            "",
            "| Network | Kind | VMware network | CIDR | VLAN | Gateway |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for network in topology.networks:
        lines.append(
            f"| {_markdown(network.id)} | {_markdown(network.kind)} | {_markdown(network.vmware_network)} | "
            f"{_markdown(network.cidr or 'unknown')} | "
            f"{_markdown(network.vlan if network.vlan is not None else '-')} | "
            f"{_markdown(network.gateway or 'unknown')} |"
        )

    lines.extend(
        [
            "",
            "## Downstream Networks",
            "",
            "| VLAN | VMware network | CIDR | Bastion IP | Gateway | DHCP pool | Lease |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if topology.downstream_networks:
        for downstream in topology.downstream_networks:
            lines.append(
                f"| {_markdown(downstream.vlan)} | {_markdown(downstream.vmware_network)} | "
                f"{_markdown(downstream.cidr)} | {_markdown(downstream.bastion_address)} | "
                f"{_markdown(downstream.gateway)} | "
                f"{_markdown(f'{downstream.dhcp_start}-{downstream.dhcp_end}')} | "
                f"{_markdown(downstream.dhcp_lease)} |"
            )
    else:
        lines.append("| - | - | - | - | - | No downstream networks configured | - |")

    lines.extend(
        [
            "",
            "## Connectivity Requirements",
            "",
            "| Source | Destination | Proto/Port | Purpose | Requirement | Verification |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if topology.connectivity_rules:
        for rule in topology.connectivity_rules:
            lines.append(
                f"| {_markdown(_endpoint_text(rule.source))} | "
                f"{_markdown(_endpoint_text(rule.destination))} | {_protocol_port(rule)} | "
                f"{_markdown(rule.purpose)} | {_markdown('+'.join(rule.requirement_sources))} | "
                f"{_markdown(rule.verification_status)} |"
            )
    else:
        lines.append("| - | - | - | No downstream connectivity rules | - | - |")

    lines.extend(
        [
            "",
            "## Notes / Unknowns",
            "",
            *[f"- {_markdown(note)}" for note in topology.notes],
            "",
        ]
    )
    return "\n".join(lines)
