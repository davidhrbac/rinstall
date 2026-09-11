from dataclasses import asdict, dataclass
from hashlib import sha256
from html import escape
from ipaddress import ip_address, ip_interface, ip_network
import json
import re
from urllib.parse import urlparse

from lib.env_config import effective_local_dns_servers, gitlab_backend_state_address
from lib.ssh_config import configured_ssh_jump_hops, node_ssh_hops, node_ssh_target

RINSTALL_ARCHITECTURE = "RINSTALL_ARCHITECTURE"
RINSTALL_CODE = "RINSTALL_CODE"
UPSTREAM_PROTOCOL = "UPSTREAM_PROTOCOL"
UNVERIFIED = "UNVERIFIED"
EXTERNAL_UNVERIFIED = UNVERIFIED

RINSTALL_MANAGED = "RINSTALL_MANAGED"
RINSTALL_CONFIGURED = "RINSTALL_CONFIGURED"
REFERENCED_EXTERNAL = "REFERENCED_EXTERNAL"
EXTERNALLY_MANAGED = "EXTERNALLY_MANAGED"
SYMBOLIC = "SYMBOLIC"

CONFIGURED = "CONFIGURED"
DERIVED = "DERIVED"
UPSTREAM_REQUIREMENT = "UPSTREAM_REQUIREMENT"
EXTERNAL = "EXTERNAL"

RESOLVED = "RESOLVED"
PARTIAL = "PARTIAL"
EXTERNAL_UNRESOLVED = "EXTERNAL_UNRESOLVED"
RUNTIME_SUPPLIED = "RUNTIME_SUPPLIED"

DESIRED_ONLY = "DESIRED_ONLY"

IP_ADDRESS = "IP_ADDRESS"
NETWORK_CIDR = "NETWORK_CIDR"
DNS_NAME = "DNS_NAME"
URL = "URL"
SSH_ALIAS = "SSH_ALIAS"
SYMBOLIC_ADDRESS = "SYMBOLIC"

ADMINISTRATIVE = "ADMINISTRATIVE"
DEPLOYMENT = "DEPLOYMENT"
CORE_SERVICE = "CORE_SERVICE"
RKE2_RANCHER = "RKE2_RANCHER"
DOWNSTREAM = "DOWNSTREAM"

ROUTED = "ROUTED"
L2_SERVICE_INTENT = "L2_SERVICE_INTENT"
EXTERNAL_ROUTING_DEPENDENCY = "EXTERNAL_ROUTING_DEPENDENCY"

MONITORING_HOST_ONLY = "monitoring-host-only"


@dataclass(frozen=True)
class EntityReference:
    kind: str
    id: str


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
    service_status: str | None = None
    template_id: str | None = None
    ownership: str = RINSTALL_MANAGED
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY
    dns_servers: tuple[str, ...] = ()


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
    ownership: str = RINSTALL_MANAGED
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY


@dataclass(frozen=True)
class NetworkTopology:
    id: str
    kind: str
    cidr: str | None
    vlan: int | None
    vmware_network: str
    gateway: str | None
    interface_ids: tuple[str, ...]
    gateway_endpoint_id: str | None = None
    ownership: str = REFERENCED_EXTERNAL
    provenance: str = CONFIGURED
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY


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
    interface_id: str | None = None
    gateway_endpoint_id: str | None = None
    network_ref: EntityReference | None = None
    bastion_is_router: bool = False
    ownership: str = RINSTALL_CONFIGURED
    lifecycle_ownership: str = EXTERNALLY_MANAGED
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY


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
    interface_id: str | None = None
    ownership: str = RINSTALL_CONFIGURED
    provenance: str = RINSTALL_ARCHITECTURE
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY


@dataclass(frozen=True)
class ResolvedEndpoint:
    id: str
    address: str | None
    reference: EntityReference | None = None
    address_kind: str = SYMBOLIC_ADDRESS
    egress_interface: EntityReference | None = None


@dataclass(frozen=True)
class ConnectivityEndpoint:
    symbolic: str
    resolved: tuple[ResolvedEndpoint, ...]
    resolution_scope: str | None = None


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
    verification: str
    provenance: str = RINSTALL_ARCHITECTURE
    category: str = DOWNSTREAM
    semantics: str = ROUTED
    via: tuple[EntityReference, ...] = ()

    @property
    def verification_status(self):
        return self.verification


@dataclass(frozen=True)
class ClusterTopology:
    id: str
    kind: str
    member_host_ids: tuple[str, ...]
    primary_host_id: str
    join_host_ids: tuple[str, ...]
    endpoint_ids: tuple[str, ...]
    versions: dict[str, str]
    ownership: str = RINSTALL_CONFIGURED
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY


@dataclass(frozen=True)
class EndpointResolutionTopology:
    scope: str
    addresses: tuple[str, ...]
    ownership: str
    provenance: str
    resolution: str
    address_kind: str = SYMBOLIC_ADDRESS
    verification: str = DESIRED_ONLY
    reason: str | None = None


@dataclass(frozen=True)
class EndpointTopology:
    id: str
    kind: str
    name: str
    protocols: tuple[str, ...]
    ports: tuple[int, ...]
    cluster_id: str | None
    resolutions: tuple[EndpointResolutionTopology, ...]
    ownership: str
    provenance: str
    resolution: str
    verification: str = DESIRED_ONLY


@dataclass(frozen=True)
class ActorTopology:
    id: str
    kind: str
    ownership: str
    provenance: str
    resolution: str
    verification: str = DESIRED_ONLY


@dataclass(frozen=True)
class AccessPathTopology:
    id: str
    source_actor_id: str
    destination: EntityReference
    hops: tuple[EntityReference, ...]
    protocol: str
    destination_port: int
    target: str
    ownership: str = RINSTALL_CONFIGURED
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = EXTERNAL_UNVERIFIED


@dataclass(frozen=True)
class DownstreamConsumerTopology:
    id: str
    kind: str
    network_id: str
    address_start: str
    address_end: str
    identities_known: bool
    lifecycle: str
    gateway_endpoint_id: str
    downstream_network_ref: EntityReference | None = None
    ownership: str = EXTERNALLY_MANAGED
    provenance: str = RINSTALL_ARCHITECTURE
    resolution: str = SYMBOLIC
    verification: str = EXTERNAL_UNVERIFIED


@dataclass(frozen=True)
class DeploymentMappingTopology:
    id: str
    value: str | None
    reference: EntityReference | None = None
    ownership: str = REFERENCED_EXTERNAL
    provenance: str = CONFIGURED
    resolution: str = RESOLVED


@dataclass(frozen=True)
class VsphereRouteTopology:
    destination: str
    gateway: str
    connection: str
    interface_ref: EntityReference | None = None
    network_ref: EntityReference | None = None
    ownership: str = RINSTALL_CONFIGURED
    provenance: str = CONFIGURED
    resolution: str = RESOLVED
    verification: str = EXTERNAL_UNVERIFIED


@dataclass(frozen=True)
class VsphereDeploymentTopology:
    endpoint_id: str
    datacenter: str
    datastore: str
    resource_pool: str
    folder: str
    templates: tuple[DeploymentMappingTopology, ...]
    networks: tuple[DeploymentMappingTopology, ...]
    route: VsphereRouteTopology
    clone_timeout_minutes: int | None
    allow_unverified_ssl: bool
    ownership: str = REFERENCED_EXTERNAL
    provenance: str = CONFIGURED
    resolution: str = RUNTIME_SUPPLIED
    verification: str = EXTERNAL_UNVERIFIED


@dataclass(frozen=True)
class TerraformBackendTopology:
    endpoint_id: str
    type: str
    url: str
    project_id: int
    state_name: str
    state_address: str
    ownership: str = REFERENCED_EXTERNAL
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = EXTERNAL_UNVERIFIED


@dataclass(frozen=True)
class DeploymentContextTopology:
    execution_actor_id: str
    terraform_root: str
    vsphere: VsphereDeploymentTopology
    terraform_backend: TerraformBackendTopology
    ownership: str = RINSTALL_CONFIGURED
    provenance: str = DERIVED
    resolution: str = RESOLVED
    verification: str = DESIRED_ONLY


@dataclass(frozen=True)
class ArchitectureRule:
    id: str
    protocols: tuple[str, ...]
    source_ports: tuple[int, ...]
    destination_ports: tuple[int, ...]
    purpose: str
    requirement_sources: tuple[str, ...]
    required: bool = True
    verification: str = UNVERIFIED
    category: str = DOWNSTREAM
    semantics: str = ROUTED

    @property
    def verification_status(self):
        return self.verification


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
    clusters: tuple[ClusterTopology, ...] = ()
    endpoints: tuple[EndpointTopology, ...] = ()
    actors: tuple[ActorTopology, ...] = ()
    access_paths: tuple[AccessPathTopology, ...] = ()
    downstream_consumers: tuple[DownstreamConsumerTopology, ...] = ()
    deployment_context: DeploymentContextTopology | None = None

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
    semantics=L2_SERVICE_INTENT,
)

DOWNSTREAM_DHCP_RESPONSE_RULE = ArchitectureRule(
    id="downstream-dhcp-response",
    protocols=("UDP",),
    source_ports=(67,),
    destination_ports=(68,),
    purpose="Downstream DHCP response",
    requirement_sources=(RINSTALL_CODE, UPSTREAM_PROTOCOL),
    semantics=L2_SERVICE_INTENT,
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


def _service_interface(address, interfaces):
    return next((interface for interface in interfaces if interface.address == address), None)


def _address_kind(value):
    if value is None:
        return SYMBOLIC_ADDRESS
    try:
        parsed = ip_address(value)
    except ValueError:
        return DNS_NAME
    return IP_ADDRESS if parsed.version == 4 else SYMBOLIC_ADDRESS


def _source_interface_for_destinations(host_id, destinations, interfaces, networks):
    network_by_id = {network.id: network for network in networks}
    selected = None
    for destination in destinations:
        try:
            destination_ip = ip_address(destination)
        except ValueError:
            return None
        candidates = [
            interface
            for interface in interfaces
            if interface.host == host_id
            and interface.address is not None
            and (network := network_by_id.get(interface.network)) is not None
            and network.cidr is not None
            and destination_ip in ip_network(network.cidr)
        ]
        if len(candidates) != 1:
            return None
        if selected is not None and selected.id != candidates[0].id:
            return None
        selected = candidates[0]
    return selected


def _single_resolved(endpoint, context):
    if len(endpoint.resolved) != 1:
        raise ValueError(f"invalid topology: {context} requires exactly one resolved reference")
    return endpoint.resolved[0]


def _administrative_rule_id(source_reference, destination_reference):
    if source_reference.kind == "actor":
        return (
            "admin-ssh:operator-jump"
            if destination_reference.kind == "endpoint"
            else f"admin-ssh:operator:{destination_reference.id}"
        )
    if source_reference.kind == "endpoint":
        return (
            f"admin-ssh:jump-hop:{destination_reference.id.rsplit(':', 1)[-1]}"
            if destination_reference.kind == "endpoint"
            else f"admin-ssh:jump:{destination_reference.id}"
        )
    return f"admin-ssh:bastion:{destination_reference.id}"


def _administrative_path_edges(paths):
    actor = EntityReference("actor", "actor:operator-workstation")
    edges = {}
    for path in paths:
        chain = (actor, *path.hops, path.destination)
        for source, destination in zip(chain, chain[1:]):
            edges.setdefault(_administrative_rule_id(source, destination), (source, destination))
    return edges


def _reference_symbolic(reference):
    prefix = f"{reference.kind}:"
    return reference.id if reference.id.startswith(prefix) else f"{prefix}{reference.id}"


def _markdown(value):
    return escape(str(value), quote=False).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _plain(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("`", "'")


def _mermaid(value):
    return (
        escape(_plain(value), quote=True)
        .replace("`", "&#96;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("&lt;br/&gt;", "<br/>")
    )


def _mermaid_id(kind, value):
    text = str(value)
    slug = re.sub(r"[^A-Za-z0-9_]", "_", text).strip("_")[:32] or "item"
    digest = sha256(text.encode()).hexdigest()[:10]
    return f"{kind}_{slug}_{digest}"


def local_dns_connectivity_rule_ids(topology):
    """Return one rule id for every distinct effective local DNS destination set."""
    groups = {
        tuple(host.dns_servers)
        for host in topology.hosts
        if host.id != topology.metadata.bastion_host and host.dns_servers
    }
    return {
        "core-dns:local-nodes" if index == 0 else f"core-dns:local-nodes:{index}"
        for index, _ in enumerate(sorted(groups))
    }


def validate_topology(topology):
    metadata = topology.metadata
    if metadata.topology_schema_version != 2 or metadata.config_schema_version != 1:
        raise ValueError("invalid topology: unsupported topology/config schema identity")
    if metadata.topology_kind != "desired" or not metadata.environment_id:
        raise ValueError("invalid topology: topology must have a desired environment identity")
    if not metadata.rancher_url or not metadata.domain:
        raise ValueError("invalid topology: Rancher URL and domain are required")

    collections = {
        "host": topology.hosts,
        "interface": topology.interfaces,
        "network": topology.networks,
        "service": topology.services,
        "downstream-network": topology.downstream_networks,
        "cluster": topology.clusters,
        "endpoint": topology.endpoints,
        "actor": topology.actors,
        "access-path": topology.access_paths,
        "downstream-consumer": topology.downstream_consumers,
        "connectivity-rule": topology.connectivity_rules,
    }
    indexes = {}
    for kind, items in collections.items():
        index = {}
        for item in items:
            if item.id in index:
                raise ValueError(f"invalid topology: duplicate {kind} id {item.id}")
            index[item.id] = item
        indexes[kind] = index

    def resolve(reference, context):
        if reference.kind not in indexes:
            raise ValueError(
                f"invalid topology: {context} references unsupported kind {reference.kind}"
            )
        if reference.id not in indexes[reference.kind]:
            raise ValueError(
                f"invalid topology: {context} references missing {reference.kind} {reference.id}"
            )
        return indexes[reference.kind][reference.id]

    hosts = indexes["host"]
    interfaces = indexes["interface"]
    networks = indexes["network"]
    services = indexes["service"]
    endpoints = indexes["endpoint"]
    consumers = indexes["downstream-consumer"]

    if topology.metadata.bastion_host not in hosts:
        raise ValueError(
            f"invalid topology: missing bastion host {topology.metadata.bastion_host}"
        )
    for interface in topology.interfaces:
        if interface.host not in hosts:
            raise ValueError(
                f"invalid topology: interface {interface.id} references missing host {interface.host}"
            )
        if interface.network not in networks:
            raise ValueError(
                f"invalid topology: interface {interface.id} references missing network {interface.network}"
            )
        if interface.resolution == RESOLVED and (
            interface.address is None or interface.prefix is None or interface.address == "unknown"
        ):
            raise ValueError(
                f"invalid topology: resolved interface {interface.id} has no concrete address"
            )
    for host in topology.hosts:
        host_interfaces = tuple(
            interface for interface in topology.interfaces if interface.host == host.id
        )
        interface_addresses = {interface.address for interface in host_interfaces}
        expected_local = next(
            (
                interface.address
                for interface in host_interfaces
                if interface.network_kind == "local/customer"
            ),
            None,
        )
        expected_management = next(
            (
                interface.address
                for interface in host_interfaces
                if interface.network_kind == "management"
            ),
            None,
        )
        if (
            host.local_ip != expected_local
            or host.management_ip != expected_management
            or (host.primary_ip is not None and host.primary_ip not in interface_addresses)
        ):
            raise ValueError(
                f"invalid topology: host {host.id} summary addresses do not match interfaces"
            )
    for network in topology.networks:
        expected = tuple(
            interface.id for interface in topology.interfaces if interface.network == network.id
        )
        if len(network.interface_ids) != len(set(network.interface_ids)) or set(
            network.interface_ids
        ) != set(expected):
            raise ValueError(
                f"invalid topology: network {network.id} interface references do not match interfaces"
            )
        if network.resolution == RESOLVED and network.cidr is None:
            raise ValueError(f"invalid topology: resolved network {network.id} has no CIDR")
    for service in topology.services:
        if service.host not in hosts:
            raise ValueError(
                f"invalid topology: service {service.id} references missing host {service.host}"
            )
        if service.network is not None and service.network not in networks:
            raise ValueError(
                f"invalid topology: service {service.id} references missing network {service.network}"
            )
        if service.interface_id is not None:
            if service.interface_id not in interfaces:
                raise ValueError(
                    f"invalid topology: service {service.id} references missing interface {service.interface_id}"
                )
            interface = interfaces[service.interface_id]
            if (
                interface.host != service.host
                or interface.network != service.network
                or interface.address != service.address
            ):
                raise ValueError(
                    f"invalid topology: service {service.id} interface binding is inconsistent"
                )
        elif service.resolution == RESOLVED:
            raise ValueError(
                f"invalid topology: resolved service {service.id} has no interface binding"
            )

    if set(consumers) != {f"consumer:{downstream.id}" for downstream in topology.downstream_networks}:
        raise ValueError(
            "invalid topology: exactly one symbolic downstream consumer is required per downstream network"
        )
    base_bastion_nic_count = len(
        [
            interface
            for interface in topology.interfaces
            if interface.host == metadata.bastion_host and interface.network_kind != "downstream"
        ]
    )
    for downstream_index, downstream in enumerate(topology.downstream_networks):
        if downstream.id not in networks:
            raise ValueError(
                f"invalid topology: downstream network {downstream.id} has no network entity"
            )
        if downstream.interface_id not in interfaces:
            raise ValueError(
                f"invalid topology: downstream network {downstream.id} has no bastion interface"
            )
        interface = interfaces[downstream.interface_id]
        network = networks[downstream.id]
        if (
            downstream.network_ref != EntityReference("network", network.id)
            or interface.host != downstream.bastion_host
            or interface.network != downstream.id
            or interface.address != downstream.bastion_address
            or interface.prefix != ip_network(network.cidr).prefixlen
            or interface.nic_index != base_bastion_nic_count + downstream_index
            or network.cidr != downstream.cidr
            or network.gateway != downstream.gateway
            or network.vlan != downstream.vlan
            or network.vmware_network != downstream.vmware_network
            or network.gateway_endpoint_id != downstream.gateway_endpoint_id
        ):
            raise ValueError(
                f"invalid topology: downstream network {downstream.id} references are inconsistent"
            )
        consumer = consumers[f"consumer:{downstream.id}"]
        if (
            consumer.network_id != downstream.id
            or consumer.downstream_network_ref
            != EntityReference("downstream-network", downstream.id)
            or consumer.address_start != downstream.dhcp_start
            or consumer.address_end != downstream.dhcp_end
            or consumer.gateway_endpoint_id != downstream.gateway_endpoint_id
        ):
            raise ValueError(
                f"invalid topology: downstream consumer {consumer.id} does not match {downstream.id}"
            )
        gateway = endpoints.get(downstream.gateway_endpoint_id)
        if gateway is None or gateway.kind != "downstream-gateway":
            raise ValueError(
                f"invalid topology: downstream network {downstream.id} gateway endpoint is missing"
            )
        gateway_resolution = _single_resolved(
            ConnectivityEndpoint(
                gateway.id,
                tuple(
                    ResolvedEndpoint(
                        address,
                        address,
                        EntityReference("endpoint", gateway.id),
                        resolution.address_kind,
                    )
                    for resolution in gateway.resolutions
                    for address in resolution.addresses
                ),
            ),
            f"gateway endpoint {gateway.id}",
        )
        if gateway_resolution.address != network.gateway:
            raise ValueError(
                f"invalid topology: gateway endpoint {gateway.id} does not match network gateway"
            )
        for service_id in (
            f"dns:{downstream.interface_name}",
            f"dhcp:{downstream.interface_name}",
        ):
            service = services.get(service_id)
            if (
                service is None
                or service.host != downstream.bastion_host
                or service.interface_id != downstream.interface_id
            ):
                raise ValueError(
                    f"invalid topology: downstream network {downstream.id} service {service_id} is inconsistent"
                )
        if downstream.bastion_is_router:
            raise ValueError(
                f"invalid topology: bastion cannot be the router for {downstream.id}"
            )

    rancher_clusters = tuple(
        cluster
        for cluster in topology.clusters
        if cluster.kind == "rke2-rancher-control-cluster"
    )
    if len(rancher_clusters) != 1:
        raise ValueError("invalid topology: exactly one RKE2/Rancher cluster is required")
    for cluster in topology.clusters:
        for host_id in cluster.member_host_ids:
            if host_id not in hosts:
                raise ValueError(
                    f"invalid topology: cluster {cluster.id} references missing host {host_id}"
                )
        if cluster.primary_host_id not in cluster.member_host_ids:
            raise ValueError(
                f"invalid topology: cluster {cluster.id} primary {cluster.primary_host_id} is not a member"
            )
        if "rancher" not in hosts[cluster.primary_host_id].roles:
            raise ValueError(
                f"invalid topology: cluster {cluster.id} primary is not a Rancher host"
            )
        expected_joins = tuple(
            host_id for host_id in cluster.member_host_ids if host_id != cluster.primary_host_id
        )
        if cluster.join_host_ids != expected_joins:
            raise ValueError(f"invalid topology: cluster {cluster.id} join members are inconsistent")
        if cluster.kind == "rke2-rancher-control-cluster" and cluster.member_host_ids != tuple(
            host.id for host in topology.hosts if "rancher" in host.roles
        ):
            raise ValueError(
                f"invalid topology: cluster {cluster.id} members do not match Rancher-role hosts"
            )
        for endpoint_id in cluster.endpoint_ids:
            if endpoint_id not in endpoints:
                raise ValueError(
                    f"invalid topology: cluster {cluster.id} references missing endpoint {endpoint_id}"
                )
    for endpoint in topology.endpoints:
        scopes = [resolution.scope for resolution in endpoint.resolutions]
        if len(scopes) != len(set(scopes)):
            raise ValueError(
                f"invalid topology: endpoint {endpoint.id} has duplicate resolution scopes"
            )
        for resolution in endpoint.resolutions:
            if resolution.address_kind not in {
                IP_ADDRESS,
                NETWORK_CIDR,
                DNS_NAME,
                URL,
                SSH_ALIAS,
                SYMBOLIC_ADDRESS,
            }:
                raise ValueError(
                    f"invalid topology: endpoint {endpoint.id} has an invalid address kind"
                )
            if resolution.resolution == RESOLVED and (
                not resolution.addresses or "unknown" in resolution.addresses
            ):
                raise ValueError(
                    f"invalid topology: endpoint {endpoint.id} has an invalid resolved scope"
                )
            try:
                if resolution.address_kind == IP_ADDRESS:
                    for address in resolution.addresses:
                        ip_address(address)
                elif resolution.address_kind == NETWORK_CIDR:
                    for address in resolution.addresses:
                        ip_network(address)
                elif resolution.address_kind == URL:
                    for address in resolution.addresses:
                        if not urlparse(address).scheme:
                            raise ValueError
            except ValueError:
                raise ValueError(
                    f"invalid topology: endpoint {endpoint.id} address kind does not match its values"
                ) from None
        statuses = {resolution.resolution for resolution in endpoint.resolutions}
        expected_resolution = (
            RESOLVED
            if statuses == {RESOLVED}
            else next(iter(statuses))
            if len(statuses) == 1
            else PARTIAL
        )
        if endpoint.resolution != expected_resolution:
            raise ValueError(
                f"invalid topology: endpoint {endpoint.id} aggregate resolution is inconsistent"
            )
        if endpoint.cluster_id is not None:
            cluster = indexes["cluster"].get(endpoint.cluster_id)
            if cluster is None or endpoint.id not in cluster.endpoint_ids:
                raise ValueError(
                    f"invalid topology: endpoint {endpoint.id} cluster reference is inconsistent"
                )

    endpoint_protocol_contract = {
        "rancher-https": (("HTTPS",), (443,)),
        "vcenter": (("HTTPS",), (443,)),
        "ssh-jump-alias": (("SSH",), None),
        "downstream-gateway": ((), ()),
        "dns-upstream": (("DNS",), (53,)),
        "management-dns": (("DNS",), (53,)),
        "proxy-upstream-destinations": (("HTTP", "HTTPS"), (80, 443)),
        "external-routed-fabric": ((), ()),
    }
    for endpoint in topology.endpoints:
        contract = endpoint_protocol_contract.get(endpoint.kind)
        if contract is None:
            if endpoint.kind == "terraform-backend" and (
                endpoint.protocols not in {("HTTP",), ("HTTPS",)}
                or len(endpoint.ports) != 1
                or not 1 <= endpoint.ports[0] <= 65535
            ):
                raise ValueError(
                    "invalid topology: Terraform backend protocol/port is inconsistent"
                )
            continue
        protocols, ports = contract
        if endpoint.protocols != protocols or (ports is not None and endpoint.ports != ports):
            raise ValueError(
                f"invalid topology: endpoint {endpoint.id} protocol/port is inconsistent"
            )

    for path in topology.access_paths:
        if path.source_actor_id not in indexes["actor"]:
            raise ValueError(
                f"invalid topology: access path {path.id} references missing actor {path.source_actor_id}"
            )
        destination = resolve(path.destination, f"access path {path.id} destination")
        if path.destination.kind != "host" or destination.ssh_target != path.target:
            raise ValueError(
                f"invalid topology: access path {path.id} destination target is inconsistent"
            )
        if path.protocol != "SSH" or path.destination_port != 22:
            raise ValueError(
                f"invalid topology: access path {path.id} protocol/port is inconsistent"
            )
        expected_path_resolution = RESOLVED
        for hop in path.hops:
            resolved_hop = resolve(hop, f"access path {path.id} hop")
            if hop.kind == "host" and resolved_hop.id != topology.metadata.bastion_host:
                raise ValueError(
                    f"invalid topology: access path {path.id} internal hop is not the bastion"
                )
            if hop.kind == "endpoint" and resolved_hop.resolution != RESOLVED:
                expected_path_resolution = PARTIAL
        if path.destination in path.hops:
            raise ValueError(f"invalid topology: access path {path.id} contains its destination as a hop")
        if path.target is None:
            expected_path_resolution = PARTIAL
        if path.resolution != expected_path_resolution:
            raise ValueError(
                f"invalid topology: access path {path.id} aggregate resolution is inconsistent"
            )
    if len(topology.access_paths) != len(hosts) or {
        path.destination.id for path in topology.access_paths
    } != set(hosts):
        raise ValueError("invalid topology: exactly one administrative access path is required per host")

    for rule in topology.connectivity_rules:
        if rule.category not in {
            ADMINISTRATIVE,
            DEPLOYMENT,
            CORE_SERVICE,
            RKE2_RANCHER,
            DOWNSTREAM,
        }:
            raise ValueError(f"invalid topology: connectivity rule {rule.id} has invalid category")
        if rule.semantics not in {ROUTED, L2_SERVICE_INTENT, EXTERNAL_ROUTING_DEPENDENCY}:
            raise ValueError(f"invalid topology: connectivity rule {rule.id} has invalid semantics")
        if not rule.required or rule.verification != UNVERIFIED:
            raise ValueError(f"invalid topology: connectivity rule {rule.id} status is inconsistent")
        if any(protocol not in {"TCP", "UDP"} for protocol in rule.protocols):
            raise ValueError(
                f"invalid topology: connectivity rule {rule.id} must use transport protocols"
            )
        if rule.semantics == EXTERNAL_ROUTING_DEPENDENCY and rule.protocols:
            raise ValueError(
                f"invalid topology: external routing rule {rule.id} cannot claim transport protocols"
            )
        for via in rule.via:
            resolve(via, f"connectivity rule {rule.id} route dependency")
        for side_name, side in (("source", rule.source), ("destination", rule.destination)):
            if not side.resolved:
                raise ValueError(
                    f"invalid topology: connectivity rule {rule.id} {side_name} has no references"
                )
            for resolved in side.resolved:
                if resolved.reference is None:
                    raise ValueError(
                        f"invalid topology: connectivity rule {rule.id} {side_name} has no entity reference"
                    )
                referenced = resolve(
                    resolved.reference, f"connectivity rule {rule.id} {side_name}"
                )
                if resolved.address_kind not in {
                    IP_ADDRESS,
                    NETWORK_CIDR,
                    DNS_NAME,
                    URL,
                    SSH_ALIAS,
                    SYMBOLIC_ADDRESS,
                }:
                    raise ValueError(
                        f"invalid topology: connectivity rule {rule.id} has invalid address kind"
                    )
                if resolved.address == "unknown":
                    raise ValueError(
                        f"invalid topology: connectivity rule {rule.id} contains unknown as an address"
                    )
                if resolved.address_kind == IP_ADDRESS and resolved.address is not None:
                    try:
                        ip_address(resolved.address)
                    except ValueError:
                        raise ValueError(
                            f"invalid topology: connectivity rule {rule.id} has invalid IP address"
                        ) from None
                if resolved.address_kind == NETWORK_CIDR and resolved.address is not None:
                    try:
                        ip_network(resolved.address)
                    except ValueError:
                        raise ValueError(
                            f"invalid topology: connectivity rule {rule.id} has invalid network CIDR"
                        ) from None
                if resolved.address is None and resolved.address_kind not in {
                    SYMBOLIC_ADDRESS,
                    SSH_ALIAS,
                }:
                    raise ValueError(
                        f"invalid topology: connectivity rule {rule.id} has a non-symbolic empty address"
                    )
                if resolved.egress_interface is not None:
                    egress = resolve(
                        resolved.egress_interface,
                        f"connectivity rule {rule.id} egress interface",
                    )
                    if (
                        resolved.egress_interface.kind != "interface"
                        or egress.address != resolved.address
                        or (
                            resolved.reference.kind == "host"
                            and egress.host != referenced.id
                        )
                        or (
                            resolved.reference.kind == "service"
                            and egress.host != referenced.host
                        )
                    ):
                        raise ValueError(
                            f"invalid topology: connectivity rule {rule.id} egress address is inconsistent"
                        )
                elif resolved.address is not None:
                    if resolved.reference.kind == "host":
                        valid_addresses = {
                            referenced.primary_ip,
                            referenced.local_ip,
                            referenced.management_ip,
                            referenced.ssh_target,
                        }
                        if resolved.address not in valid_addresses:
                            raise ValueError(
                                f"invalid topology: connectivity rule {rule.id} host address is inconsistent"
                            )
                    elif resolved.reference.kind == "interface" and resolved.address != referenced.address:
                        raise ValueError(
                            f"invalid topology: connectivity rule {rule.id} interface address is inconsistent"
                        )
                    elif resolved.reference.kind == "network" and resolved.address != referenced.cidr:
                        raise ValueError(
                            f"invalid topology: connectivity rule {rule.id} network address is inconsistent"
                        )
                    elif resolved.reference.kind == "service" and resolved.address != referenced.address:
                        raise ValueError(
                            f"invalid topology: connectivity rule {rule.id} service address is inconsistent"
                        )
                    elif resolved.reference.kind == "downstream-consumer":
                        consumer_network = networks[referenced.network_id]
                        if resolved.address != consumer_network.cidr:
                            raise ValueError(
                                f"invalid topology: connectivity rule {rule.id} consumer address is inconsistent"
                            )
                    elif resolved.reference.kind == "endpoint":
                        scopes = (
                            tuple(
                                item
                                for item in referenced.resolutions
                                if item.scope == side.resolution_scope
                            )
                            if side.resolution_scope
                            else referenced.resolutions
                        )
                        if resolved.address not in {
                            address for item in scopes for address in item.addresses
                        }:
                            raise ValueError(
                                f"invalid topology: connectivity rule {rule.id} endpoint address is inconsistent"
                            )

    rancher_hosts = tuple(host.id for host in topology.hosts if "rancher" in host.roles)
    rancher_endpoint = next(
        (endpoint for endpoint in topology.endpoints if endpoint.kind == "rancher-https"), None
    )
    if rancher_endpoint is None:
        raise ValueError("invalid topology: Rancher HTTPS endpoint is missing")
    local_resolution = next(
        (item for item in rancher_endpoint.resolutions if item.scope == "local"), None
    )
    expected_local_addresses = tuple(
        address
        for host_id in rancher_hosts
        if (address := hosts[host_id].local_ip or hosts[host_id].primary_ip) is not None
    )
    expected_local_status = (
        RESOLVED if len(expected_local_addresses) == len(rancher_hosts) else PARTIAL
    )
    if (
        rancher_endpoint.name != metadata.rancher_url
        or rancher_endpoint.protocols != ("HTTPS",)
        or rancher_endpoint.ports != (443,)
        or rancher_endpoint.resolution != PARTIAL
        or local_resolution is None
        or local_resolution.addresses != expected_local_addresses
        or local_resolution.resolution != expected_local_status
        or local_resolution.address_kind != IP_ADDRESS
    ):
        raise ValueError("invalid topology: Rancher local endpoint resolution is inconsistent")
    external_resolution = next(
        (item for item in rancher_endpoint.resolutions if item.scope == "external"), None
    )
    if (
        external_resolution is None
        or external_resolution.addresses
        or external_resolution.resolution != EXTERNAL_UNRESOLVED
    ):
        raise ValueError("invalid topology: Rancher external endpoint must remain unresolved")

    for downstream in topology.downstream_networks:
        dns_rule_id = f"downstream-dns:{downstream.interface_name}"
        ssh_rule_id = f"rancher-downstream-ssh:{downstream.interface_name}"
        if dns_rule_id not in indexes["connectivity-rule"]:
            raise ValueError(f"invalid topology: missing same-VLAN DNS rule {dns_rule_id}")
        dns_rule = indexes["connectivity-rule"][dns_rule_id]
        dns_service = services.get(f"dns:{downstream.interface_name}")
        if dns_service is None:
            raise ValueError(
                f"invalid topology: downstream network {downstream.id} has no DNS service"
            )
        dns_source = _single_resolved(dns_rule.source, f"same-VLAN DNS rule {dns_rule_id} source")
        dns_destination = _single_resolved(
            dns_rule.destination, f"same-VLAN DNS rule {dns_rule_id} destination"
        )
        if (
            dns_source.reference
            != EntityReference("downstream-consumer", f"consumer:{downstream.id}")
            or dns_destination.reference != EntityReference("service", dns_service.id)
            or dns_destination.address != downstream.bastion_address
            or dns_rule.protocols != ("TCP", "UDP")
            or dns_rule.destination_ports != (53,)
            or dns_rule.category != DOWNSTREAM
        ):
            raise ValueError(f"invalid topology: same-VLAN DNS rule {dns_rule_id} is inconsistent")
        if ssh_rule_id not in indexes["connectivity-rule"]:
            raise ValueError(f"invalid topology: missing Rancher SSH rule {ssh_rule_id}")
        ssh_rule = indexes["connectivity-rule"][ssh_rule_id]
        if (
            tuple(item.reference.id for item in ssh_rule.source.resolved) != rancher_hosts
            or ssh_rule.protocols != ("TCP",)
            or ssh_rule.destination_ports != (22,)
            or not ssh_rule.required
            or ssh_rule.provenance != RINSTALL_ARCHITECTURE
            or ssh_rule.requirement_sources != (RINSTALL_ARCHITECTURE,)
            or ssh_rule.category != DOWNSTREAM
        ):
            raise ValueError(f"invalid topology: Rancher SSH rule {ssh_rule_id} has incomplete sources")
        consumer_id = f"consumer:{downstream.id}"
        ssh_destination = _single_resolved(
            ssh_rule.destination, f"Rancher SSH rule {ssh_rule_id} destination"
        )
        if ssh_destination.reference != EntityReference(
            "downstream-consumer", consumer_id
        ):
            raise ValueError(f"invalid topology: Rancher SSH rule {ssh_rule_id} has wrong consumer")
        for direction, source_reference, destination_reference, source_ports, destination_ports in (
            (
                "request",
                EntityReference("downstream-consumer", consumer_id),
                EntityReference("service", f"dhcp:{downstream.interface_name}"),
                (68,),
                (67,),
            ),
            (
                "response",
                EntityReference("service", f"dhcp:{downstream.interface_name}"),
                EntityReference("downstream-consumer", consumer_id),
                (67,),
                (68,),
            ),
        ):
            rule_id = f"downstream-dhcp-{direction}:{downstream.interface_name}"
            rule = indexes["connectivity-rule"].get(rule_id)
            if rule is None:
                raise ValueError(f"invalid topology: missing DHCP {direction} rule {rule_id}")
            source = _single_resolved(rule.source, f"DHCP {direction} rule source")
            destination = _single_resolved(
                rule.destination, f"DHCP {direction} rule destination"
            )
            if (
                source.reference != source_reference
                or destination.reference != destination_reference
                or source.address is not None
                or destination.address is not None
                or rule.source_ports != source_ports
                or rule.destination_ports != destination_ports
                or rule.protocols != ("UDP",)
                or rule.category != DOWNSTREAM
                or rule.semantics != L2_SERVICE_INTENT
            ):
                raise ValueError(
                    f"invalid topology: DHCP {direction} rule {rule_id} has wrong endpoint types"
                )
        agent_rule_id = f"downstream-rancher-agent:{downstream.interface_name}"
        agent_rule = indexes["connectivity-rule"].get(agent_rule_id)
        agent_source = (
            _single_resolved(agent_rule.source, f"downstream Rancher agent rule {agent_rule_id} source")
            if agent_rule is not None
            else None
        )
        if (
            agent_rule is None
            or agent_source.reference
            != EntityReference("downstream-consumer", consumer_id)
            or not agent_rule.destination.resolved
            or any(
                item.reference != EntityReference("endpoint", rancher_endpoint.id)
                for item in agent_rule.destination.resolved
            )
            or tuple(item.address for item in agent_rule.destination.resolved)
            != local_resolution.addresses
            or agent_rule.destination.resolution_scope != "local"
            or agent_rule.protocols != ("TCP",)
            or agent_rule.destination_ports != (443,)
            or agent_rule.category != DOWNSTREAM
        ):
            raise ValueError(
                f"invalid topology: downstream Rancher agent rule {agent_rule_id} is inconsistent"
            )

    if topology.deployment_context is None:
        raise ValueError("invalid topology: deployment context is missing")
    context = topology.deployment_context
    if context.execution_actor_id not in indexes["actor"]:
        raise ValueError("invalid topology: deployment context execution actor is missing")
    for endpoint_id in (
        context.vsphere.endpoint_id,
        context.terraform_backend.endpoint_id,
    ):
        if endpoint_id not in endpoints:
            raise ValueError(
                f"invalid topology: deployment context references missing endpoint {endpoint_id}"
            )
    if (
        endpoints[context.vsphere.endpoint_id].kind != "vcenter"
        or endpoints[context.terraform_backend.endpoint_id].kind != "terraform-backend"
        or context.resolution != PARTIAL
    ):
        raise ValueError("invalid topology: deployment context endpoint semantics are inconsistent")

    vcenter_endpoint = endpoints[context.vsphere.endpoint_id]
    vcenter_reference = EntityReference("endpoint", vcenter_endpoint.id)
    vcenter_resolution = next(
        (item for item in vcenter_endpoint.resolutions if item.scope == "external"), None
    )
    vcenter_rule = indexes["connectivity-rule"].get("deployment:vcenter-api")
    if vcenter_resolution is None or vcenter_rule is None:
        raise ValueError("invalid topology: vCenter deployment relationship is incomplete")
    vcenter_destination = _single_resolved(
        vcenter_rule.destination, "vCenter API deployment destination"
    )
    expected_vcenter_address = vcenter_resolution.addresses[0] if vcenter_resolution.addresses else None
    if (
        context.vsphere.resolution != vcenter_endpoint.resolution
        or vcenter_rule.destination.symbolic != _reference_symbolic(vcenter_reference)
        or vcenter_destination.id != vcenter_endpoint.name
        or vcenter_destination.reference != vcenter_reference
        or vcenter_destination.address != expected_vcenter_address
        or vcenter_destination.address_kind != vcenter_resolution.address_kind
    ):
        raise ValueError("invalid topology: vCenter deployment relationship is inconsistent")

    template_ids = {mapping.id for mapping in context.vsphere.templates}
    for host in topology.hosts:
        if host.template_id not in template_ids:
            raise ValueError(
                f"invalid topology: host {host.id} references missing template {host.template_id}"
            )
    network_mapping_ids = {mapping.id for mapping in context.vsphere.networks}
    if network_mapping_ids != set(networks):
        raise ValueError("invalid topology: vSphere network mappings do not match networks")
    for mapping in context.vsphere.networks:
        if mapping.value is not None or mapping.reference != EntityReference("network", mapping.id):
            raise ValueError(
                f"invalid topology: vSphere network mapping {mapping.id} is not authoritative"
            )
        resolve(mapping.reference, f"vSphere network mapping {mapping.id}")

    route = context.vsphere.route
    if (route.interface_ref is None) != (route.network_ref is None):
        raise ValueError("invalid topology: vSphere route linkage is incomplete")
    if route.interface_ref is None:
        if route.resolution != PARTIAL:
            raise ValueError("invalid topology: unlinked vSphere route must be partial")
    else:
        route_interface = resolve(route.interface_ref, "vSphere route interface")
        route_network = resolve(route.network_ref, "vSphere route network")
        if (
            route.interface_ref.kind != "interface"
            or route.network_ref.kind != "network"
            or route_interface.host != metadata.bastion_host
            or route_interface.network != route_network.id
            or route_interface.address is None
            or route_interface.prefix is None
            or ip_address(route.gateway)
            not in ip_interface(
                f"{route_interface.address}/{route_interface.prefix}"
            ).network
            or route.resolution != RESOLVED
        ):
            raise ValueError("invalid topology: vSphere route linkage is inconsistent")

    expected_admin_edges = _administrative_path_edges(topology.access_paths)
    for rule_id, (source_reference, destination_reference) in expected_admin_edges.items():
        rule = indexes["connectivity-rule"].get(rule_id)
        if rule is None:
            raise ValueError(f"invalid topology: missing administrative rule {rule_id}")
        source = _single_resolved(rule.source, f"administrative rule {rule_id} source")
        destination = _single_resolved(
            rule.destination, f"administrative rule {rule_id} destination"
        )
        expected_ports = (
            (22,)
            if destination_reference.kind == "host"
            else endpoints[destination_reference.id].ports
        )
        if (
            source.reference != source_reference
            or destination.reference != destination_reference
            or rule.protocols != ("TCP",)
            or rule.destination_ports != expected_ports
            or rule.category != ADMINISTRATIVE
        ):
            raise ValueError(
                f"invalid topology: administrative rule {rule_id} does not match access paths"
            )

    local_dns_rule_ids = local_dns_connectivity_rule_ids(topology)
    required_rule_ids = {
        *expected_admin_edges,
        "core-dns:bastion-os",
        "core-dns:upstream",
        "core-proxy:rancher-nodes",
        "core-proxy:upstream",
        "deployment:terraform-backend",
        "deployment:vcenter-api",
        "rke2:bastion-kubernetes-api",
    }
    required_rule_ids.update(local_dns_rule_ids)
    if rancher_clusters[0].join_host_ids:
        required_rule_ids.add("rke2:join-primary")
    for downstream in topology.downstream_networks:
        required_rule_ids.update(
            {
                f"downstream-dns:{downstream.interface_name}",
                f"rancher-downstream-ssh:{downstream.interface_name}",
                f"downstream-dhcp-request:{downstream.interface_name}",
                f"downstream-dhcp-response:{downstream.interface_name}",
                f"downstream-rancher-agent:{downstream.interface_name}",
                f"external-routing:customer:{downstream.interface_name}",
            }
        )
    actual_rule_ids = set(indexes["connectivity-rule"])
    if actual_rule_ids != required_rule_ids:
        missing = sorted(required_rule_ids - actual_rule_ids)
        unexpected = sorted(actual_rule_ids - required_rule_ids)
        raise ValueError(
            f"invalid topology: support connectivity registry mismatch; missing={missing}, unexpected={unexpected}"
        )

    fixed_contracts = {
        "core-dns:bastion-os": (CORE_SERVICE, ("TCP", "UDP"), (53,)),
        "core-dns:upstream": (CORE_SERVICE, ("TCP", "UDP"), (53,)),
        "core-proxy:rancher-nodes": (
            CORE_SERVICE,
            ("TCP",),
            services["proxy:squid"].ports,
        ),
        "core-proxy:upstream": (CORE_SERVICE, ("TCP",), (80, 443)),
        "deployment:terraform-backend": (DEPLOYMENT, ("TCP",), endpoints[context.terraform_backend.endpoint_id].ports),
        "deployment:vcenter-api": (DEPLOYMENT, ("TCP",), (443,)),
        "rke2:bastion-kubernetes-api": (RKE2_RANCHER, ("TCP",), (6443,)),
    }
    for rule_id in local_dns_rule_ids:
        fixed_contracts[rule_id] = (CORE_SERVICE, ("TCP", "UDP"), (53,))
    if "rke2:join-primary" in required_rule_ids:
        fixed_contracts["rke2:join-primary"] = (RKE2_RANCHER, ("TCP",), (9345,))
    for rule_id, (category, protocols, destination_ports) in fixed_contracts.items():
        rule = indexes["connectivity-rule"][rule_id]
        if (
            rule.category != category
            or rule.protocols != protocols
            or rule.destination_ports != destination_ports
        ):
            raise ValueError(f"invalid topology: connectivity rule {rule_id} contract is inconsistent")

    for index, rule_id in enumerate(sorted(local_dns_rule_ids)):
        rule = indexes["connectivity-rule"][rule_id]
        expected_hosts = {
            host.id
            for host in topology.hosts
            if host.id != metadata.bastion_host and host.dns_servers
            and tuple(host.dns_servers) == tuple(
                item.address for item in rule.destination.resolved
            )
        }
        actual_hosts = {
            item.reference.id for item in rule.source.resolved if item.reference is not None
        }
        if actual_hosts != expected_hosts:
            raise ValueError(f"invalid topology: local DNS rule {rule_id} source set is inconsistent")

    for downstream in topology.downstream_networks:
        route_rule_id = f"external-routing:customer:{downstream.interface_name}"
        route_rule = indexes["connectivity-rule"][route_rule_id]
        if (
            route_rule.category != DOWNSTREAM
            or route_rule.semantics != EXTERNAL_ROUTING_DEPENDENCY
            or route_rule.via
            != (EntityReference("endpoint", "endpoint:external-routed-fabric"),)
            or downstream.bastion_is_router
        ):
            raise ValueError(
                f"invalid topology: external routing dependency {route_rule_id} is inconsistent"
            )


def build_desired_topology(config):
    environment_id = config["environment"]["id"]
    bastion_host = config["bastion"]["service_node"]
    vsphere = config["infra"]["vsphere"]
    vsphere_server = vsphere.get("server")
    interfaces = []
    hosts = []

    for host_id in sorted(config["nodes"]):
        node = config["nodes"][host_id]
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
                resolution=RESOLVED if nic.get("ip") is not None else SYMBOLIC,
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
        elif node["role"] in {"prometheus", "monitoring"}:
            capabilities = (MONITORING_HOST_ONLY,)
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
                ssh_target=node_ssh_target(node),
                service_status=(
                    "host-only/not-modeled"
                    if node["role"] in {"prometheus", "monitoring"}
                    else None
                ),
                template_id=node["template"],
                dns_servers=effective_local_dns_servers(node, config["local_vlan"]),
            )
        )

    downstream_networks = []
    base_nic_count = len(config["nodes"][bastion_host]["nics"])
    for index, downstream in enumerate(config["bastion"]["downstream_networks"]):
        network_id = f"downstream:{downstream['interface_name']}"
        interface_id = f"{bastion_host}:{downstream['interface_name']}"
        gateway_endpoint_id = f"endpoint:gateway:{downstream['interface_name']}"
        interfaces.append(
            InterfaceTopology(
                id=interface_id,
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
                interface_id=interface_id,
                gateway_endpoint_id=gateway_endpoint_id,
                network_ref=EntityReference("network", network_id),
            )
        )

    networks = []
    for network_id in sorted(config["infra"]["networks"]):
        vmware_network = config["infra"]["networks"][network_id]
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
                resolution=RESOLVED if cidr is not None else PARTIAL,
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
                interface_ids=(downstream.interface_id,),
                gateway_endpoint_id=downstream.gateway_endpoint_id,
            )
        )

    services = []
    bastion_service_ip = config["bastion"]["service_ip"]
    bastion_service_interface = _service_interface(bastion_service_ip, interfaces)
    services.append(
        ServiceTopology(
            id="proxy:squid",
            kind="proxy",
            host=bastion_host,
            network=(bastion_service_interface.network if bastion_service_interface else None),
            address=bastion_service_ip,
            protocols=("TCP",),
            ports=(config["bastion"]["squid_http_port"],),
            purpose="HTTP and HTTPS forward proxy for local services",
            interface_id=(bastion_service_interface.id if bastion_service_interface else None),
        )
    )
    services.append(
        ServiceTopology(
            id="dns:local",
            kind="dns",
            host=bastion_host,
            network=(bastion_service_interface.network if bastion_service_interface else None),
            address=bastion_service_ip,
            protocols=("TCP", "UDP"),
            ports=(53,),
            purpose="DNS for local nodes",
            interface_id=(bastion_service_interface.id if bastion_service_interface else None),
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
                    interface_id=downstream.interface_id,
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
                    interface_id=downstream.interface_id,
                ),
            ]
        )

    rancher_hosts = tuple(host for host in hosts if "rancher" in host.roles)
    rancher_host_ids = tuple(host.id for host in rancher_hosts)
    rancher_local_addresses = tuple(
        address
        for host in rancher_hosts
        if (address := host.local_ip or host.primary_ip) is not None
    )
    rancher_local_resolution = (
        RESOLVED if len(rancher_local_addresses) == len(rancher_hosts) else PARTIAL
    )
    rke2_primary_host = config["rke2"]["primary_node"]
    rancher_endpoint_id = "endpoint:rancher"
    cluster_id = "cluster:rke2-rancher"

    clusters = (
        ClusterTopology(
            id=cluster_id,
            kind="rke2-rancher-control-cluster",
            member_host_ids=rancher_host_ids,
            primary_host_id=rke2_primary_host,
            join_host_ids=tuple(
                host_id for host_id in rancher_host_ids if host_id != rke2_primary_host
            ),
            endpoint_ids=(rancher_endpoint_id,),
            versions={
                "rke2": config["rke2"]["version"],
                "rancher": config["rancher"]["rancher_chart_version"],
            },
        ),
    )

    endpoints = [
        EndpointTopology(
            id=rancher_endpoint_id,
            kind="rancher-https",
            name=config["rancher_url"],
            protocols=("HTTPS",),
            ports=(443,),
            cluster_id=cluster_id,
            resolutions=(
                EndpointResolutionTopology(
                    scope="local",
                    addresses=rancher_local_addresses,
                    ownership=RINSTALL_CONFIGURED,
                    provenance=DERIVED,
                    resolution=rancher_local_resolution,
                    address_kind=IP_ADDRESS,
                ),
                EndpointResolutionTopology(
                    scope="external",
                    addresses=(),
                    ownership=EXTERNALLY_MANAGED,
                    provenance=EXTERNAL,
                    resolution=EXTERNAL_UNRESOLVED,
                    verification=UNVERIFIED,
                    reason="External Rancher VIP/load balancer is not represented in config.yaml.",
                ),
            ),
            ownership=RINSTALL_CONFIGURED,
            provenance=CONFIGURED,
            resolution=PARTIAL,
        ),
        EndpointTopology(
            id="endpoint:vcenter",
            kind="vcenter",
            name=vsphere_server or "runtime-supplied vCenter endpoint",
            protocols=("HTTPS",),
            ports=(443,),
            cluster_id=None,
            resolutions=(
                EndpointResolutionTopology(
                    scope="external",
                    addresses=((vsphere_server,) if vsphere_server else ()),
                    ownership=REFERENCED_EXTERNAL,
                    provenance=(CONFIGURED if vsphere_server else EXTERNAL),
                    resolution=(RESOLVED if vsphere_server else RUNTIME_SUPPLIED),
                    verification=UNVERIFIED,
                    reason=(None if vsphere_server else "vCenter endpoint is supplied at runtime outside config.yaml."),
                ),
            ),
            ownership=REFERENCED_EXTERNAL,
            provenance=(CONFIGURED if vsphere_server else EXTERNAL),
            resolution=(RESOLVED if vsphere_server else RUNTIME_SUPPLIED),
            verification=UNVERIFIED,
        ),
    ]

    backend = config["terraform"]["backend"]
    backend_url = backend["url"]
    backend_scheme = urlparse(backend_url).scheme.lower()
    backend_protocols = (backend_scheme.upper(),) if backend_scheme else ()
    parsed_backend_url = urlparse(backend_url)
    backend_ports = ((parsed_backend_url.port,) if parsed_backend_url.port else ((443,) if backend_scheme == "https" else ((80,) if backend_scheme == "http" else ())))
    endpoints.append(
        EndpointTopology(
            id="endpoint:terraform-backend",
            kind="terraform-backend",
            name=backend_url,
            protocols=backend_protocols,
            ports=backend_ports,
            cluster_id=None,
            resolutions=(
                EndpointResolutionTopology(
                    scope="external",
                    addresses=(backend_url,),
                    ownership=REFERENCED_EXTERNAL,
                    provenance=CONFIGURED,
                    resolution=RESOLVED,
                    address_kind=URL,
                    verification=UNVERIFIED,
                ),
            ),
            ownership=REFERENCED_EXTERNAL,
            provenance=CONFIGURED,
            resolution=RESOLVED,
            verification=UNVERIFIED,
        )
    )
    local_dns_addresses = sorted(
        {
            address
            for node in config["nodes"].values()
            for address in effective_local_dns_servers(node, config["local_vlan"])
        }
    )
    for address in local_dns_addresses:
        endpoints.append(
            EndpointTopology(
                id=f"endpoint:dns-local:{address}",
                kind="local-dns",
                name=address,
                protocols=("DNS",),
                ports=(53,),
                cluster_id=None,
                resolutions=(
                    EndpointResolutionTopology(
                        scope="local",
                        addresses=(address,),
                        ownership=REFERENCED_EXTERNAL,
                        provenance=CONFIGURED,
                        resolution=RESOLVED,
                        address_kind=IP_ADDRESS,
                        verification=UNVERIFIED,
                    ),
                ),
                ownership=REFERENCED_EXTERNAL,
                provenance=CONFIGURED,
                resolution=RESOLVED,
                verification=UNVERIFIED,
            )
        )

    jump_hops = configured_ssh_jump_hops(config)
    jump_endpoint_refs = []
    for index, jump_hop in enumerate(jump_hops):
        jump_endpoint_id = (
            "endpoint:ssh-jump"
            if index == len(jump_hops) - 1
            else f"endpoint:ssh-jump-hop:{index + 1}"
        )
        jump_resolution = RESOLVED if jump_hop.hostname else EXTERNAL_UNRESOLVED
        jump_endpoint_refs.append(EntityReference("endpoint", jump_endpoint_id))
        endpoints.append(
            EndpointTopology(
                id=jump_endpoint_id,
                kind="ssh-jump-alias",
                name=jump_hop.alias,
                protocols=("SSH",),
                ports=((jump_hop.port or 22,) if jump_hop.hostname else ()),
                cluster_id=None,
                resolutions=(
                    EndpointResolutionTopology(
                        scope="operator-ssh-config",
                        addresses=((jump_hop.hostname,) if jump_hop.hostname else ()),
                        ownership=REFERENCED_EXTERNAL,
                        provenance=CONFIGURED,
                        resolution=jump_resolution,
                        address_kind=(
                            _address_kind(jump_hop.hostname)
                            if jump_hop.hostname
                            else SSH_ALIAS
                        ),
                        verification=UNVERIFIED,
                        reason=(
                            None
                            if jump_hop.hostname
                            else "SSH alias network identity is defined outside config.yaml."
                        ),
                    ),
                ),
                ownership=REFERENCED_EXTERNAL,
                provenance=CONFIGURED,
                resolution=jump_resolution,
                verification=UNVERIFIED,
            )
        )

    for downstream in downstream_networks:
        endpoints.append(
            EndpointTopology(
                id=downstream.gateway_endpoint_id,
                kind="downstream-gateway",
                name=f"gateway for VLAN {downstream.vlan}",
                protocols=(),
                ports=(),
                cluster_id=None,
                resolutions=(
                    EndpointResolutionTopology(
                        scope=f"downstream-vlan-{downstream.vlan}",
                        addresses=(downstream.gateway,),
                        ownership=REFERENCED_EXTERNAL,
                        provenance=CONFIGURED,
                        resolution=RESOLVED,
                        address_kind=IP_ADDRESS,
                        verification=UNVERIFIED,
                    ),
                ),
                ownership=REFERENCED_EXTERNAL,
                provenance=CONFIGURED,
                resolution=RESOLVED,
                verification=UNVERIFIED,
            )
        )

    dns_upstream_endpoint_ids = []
    for address in sorted(config["bastion"]["dnsmasq_upstream_servers"]):
        endpoint_id = f"endpoint:dns-upstream:{address}"
        dns_upstream_endpoint_ids.append(endpoint_id)
        endpoints.append(
            EndpointTopology(
                id=endpoint_id,
                kind="dns-upstream",
                name=address,
                protocols=("DNS",),
                ports=(53,),
                cluster_id=None,
                resolutions=(
                    EndpointResolutionTopology(
                        scope="external",
                        addresses=(address,),
                        ownership=REFERENCED_EXTERNAL,
                        provenance=CONFIGURED,
                        resolution=RESOLVED,
                        address_kind=IP_ADDRESS,
                        verification=UNVERIFIED,
                    ),
                ),
                ownership=REFERENCED_EXTERNAL,
                provenance=CONFIGURED,
                resolution=RESOLVED,
                verification=UNVERIFIED,
            )
        )

    management_dns_endpoint_ids = []
    for address in sorted(config["nodes"][bastion_host]["dns_servers"]):
        endpoint_id = f"endpoint:dns-management:{address}"
        management_dns_endpoint_ids.append(endpoint_id)
        endpoints.append(
            EndpointTopology(
                id=endpoint_id,
                kind="management-dns",
                name=address,
                protocols=("DNS",),
                ports=(53,),
                cluster_id=None,
                resolutions=(
                    EndpointResolutionTopology(
                        scope="management",
                        addresses=(address,),
                        ownership=REFERENCED_EXTERNAL,
                        provenance=CONFIGURED,
                        resolution=RESOLVED,
                        address_kind=IP_ADDRESS,
                        verification=UNVERIFIED,
                    ),
                ),
                ownership=REFERENCED_EXTERNAL,
                provenance=CONFIGURED,
                resolution=RESOLVED,
                verification=UNVERIFIED,
            )
        )

    endpoints.append(
        EndpointTopology(
            id="endpoint:proxy-upstream",
            kind="proxy-upstream-destinations",
            name="external repositories and service endpoints",
            protocols=("HTTP", "HTTPS"),
            ports=(80, 443),
            cluster_id=None,
            resolutions=(
                EndpointResolutionTopology(
                    scope="external",
                    addresses=(),
                    ownership=REFERENCED_EXTERNAL,
                    provenance=RINSTALL_ARCHITECTURE,
                    resolution=EXTERNAL_UNRESOLVED,
                    address_kind=SYMBOLIC_ADDRESS,
                    verification=UNVERIFIED,
                    reason="Proxy upstream destinations are not enumerated in config.yaml.",
                ),
            ),
            ownership=REFERENCED_EXTERNAL,
            provenance=RINSTALL_ARCHITECTURE,
            resolution=EXTERNAL_UNRESOLVED,
            verification=UNVERIFIED,
        )
    )
    if downstream_networks:
        endpoints.append(
            EndpointTopology(
                id="endpoint:external-routed-fabric",
                kind="external-routed-fabric",
                name="external routing and firewalling",
                protocols=(),
                ports=(),
                cluster_id=None,
                resolutions=(
                    EndpointResolutionTopology(
                        scope="external",
                        addresses=(),
                        ownership=EXTERNALLY_MANAGED,
                        provenance=RINSTALL_ARCHITECTURE,
                        resolution=EXTERNAL_UNRESOLVED,
                        address_kind=SYMBOLIC_ADDRESS,
                        verification=UNVERIFIED,
                        reason="The bastion is not the router between customer and downstream networks.",
                    ),
                ),
                ownership=EXTERNALLY_MANAGED,
                provenance=RINSTALL_ARCHITECTURE,
                resolution=EXTERNAL_UNRESOLVED,
                verification=UNVERIFIED,
            )
        )

    actors = (
        ActorTopology(
            id="actor:operator-workstation",
            kind="operator-workstation",
            ownership=REFERENCED_EXTERNAL,
            provenance=RINSTALL_ARCHITECTURE,
            resolution=SYMBOLIC,
        ),
    )
    access_paths = []
    endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
    for host_id in sorted(config["nodes"]):
        node = config["nodes"][host_id]
        runtime_hops = node_ssh_hops(config, host_id, node)
        hops = list(jump_endpoint_refs) if runtime_hops else []
        if len(runtime_hops) > 1:
            hops.append(EntityReference("host", bastion_host))
        path_resolution = RESOLVED
        if any(
            hop.kind == "endpoint" and endpoint_by_id[hop.id].resolution != RESOLVED
            for hop in hops
        ) or node_ssh_target(node) is None:
            path_resolution = PARTIAL
        access_paths.append(
            AccessPathTopology(
                id=f"access:ssh:{host_id}",
                source_actor_id="actor:operator-workstation",
                destination=EntityReference("host", host_id),
                hops=tuple(hops),
                protocol="SSH",
                destination_port=22,
                target=node_ssh_target(node),
                resolution=path_resolution,
            )
        )

    downstream_consumers = tuple(
        DownstreamConsumerTopology(
            id=f"consumer:{downstream.id}",
            kind="downstream-nodes-or-cluster",
            network_id=downstream.id,
            address_start=downstream.dhcp_start,
            address_end=downstream.dhcp_end,
            identities_known=False,
            lifecycle="external/downstream",
            gateway_endpoint_id=downstream.gateway_endpoint_id,
            downstream_network_ref=EntityReference("downstream-network", downstream.id),
        )
        for downstream in downstream_networks
    )

    vsphere_route_destination, vsphere_route_gateway = config["bastion"][
        "vsphere_route"
    ].split()
    route_nic_index = config["bastion"].get("route_nic_index")
    route_interface = (
        next(
            (
                interface
                for interface in interfaces
                if interface.host == bastion_host and interface.nic_index == route_nic_index
            ),
            None,
        )
        if route_nic_index is not None
        else _source_interface_for_destinations(
            bastion_host,
            (vsphere_route_gateway,),
            interfaces,
            networks,
        )
    )
    state_name = f"{environment_id}-infra"
    deployment_context = DeploymentContextTopology(
        execution_actor_id="actor:operator-workstation",
        terraform_root="rinstall/terraform/infra",
        vsphere=VsphereDeploymentTopology(
            endpoint_id="endpoint:vcenter",
            datacenter=vsphere["datacenter"],
            datastore=vsphere["datastore"],
            resource_pool=vsphere["resource_pool"],
            folder=vsphere["folder"],
            templates=tuple(
                DeploymentMappingTopology(id=name, value=value)
                for name, value in sorted(config["infra"]["templates"].items())
            ),
            networks=tuple(
                DeploymentMappingTopology(
                    id=network.id,
                    value=None,
                    reference=EntityReference("network", network.id),
                )
                for network in networks
            ),
            route=VsphereRouteTopology(
                destination=vsphere_route_destination,
                gateway=vsphere_route_gateway,
                connection=config["bastion"]["vsphere_route_connection"],
                interface_ref=(
                    EntityReference("interface", route_interface.id)
                    if route_interface
                    else None
                ),
                network_ref=(
                    EntityReference("network", route_interface.network)
                    if route_interface
                    else None
                ),
                resolution=RESOLVED if route_interface else PARTIAL,
            ),
            clone_timeout_minutes=vsphere.get("clone_timeout"),
            allow_unverified_ssl=vsphere.get("allow_unverified_ssl", False),
            resolution=RESOLVED if vsphere_server else RUNTIME_SUPPLIED,
        ),
        terraform_backend=TerraformBackendTopology(
            endpoint_id="endpoint:terraform-backend",
            type=backend["type"],
            url=backend_url,
            project_id=backend["project_id"],
            state_name=state_name,
            state_address=gitlab_backend_state_address(backend, environment_id),
        ),
        resolution=PARTIAL,
    )

    rancher_sources = tuple(
        ResolvedEndpoint(
            host.id,
            host.local_ip or host.primary_ip,
            EntityReference("host", host.id),
            IP_ADDRESS if host.local_ip or host.primary_ip else SYMBOLIC_ADDRESS,
        )
        for host in rancher_hosts
    )
    connectivity_rules = []

    def add_connectivity_rule(
        rule_id,
        source,
        destination,
        protocols,
        source_ports,
        destination_ports,
        purpose,
        category,
        provenance=RINSTALL_ARCHITECTURE,
        requirement_sources=(RINSTALL_ARCHITECTURE,),
        semantics=ROUTED,
        via=(),
    ):
        connectivity_rules.append(
            ConnectivityRule(
                id=rule_id,
                source=source,
                destination=destination,
                protocols=tuple(protocols),
                source_ports=tuple(source_ports),
                destination_ports=tuple(destination_ports),
                purpose=purpose,
                requirement_sources=tuple(requirement_sources),
                required=True,
                verification=UNVERIFIED,
                provenance=provenance,
                category=category,
                semantics=semantics,
                via=tuple(via),
            )
        )

    for downstream in downstream_networks:
        consumer_reference = EntityReference(
            "downstream-consumer", f"consumer:{downstream.id}"
        )
        downstream_endpoint = ConnectivityEndpoint(
            symbolic=f"network:downstream:{downstream.vlan}",
            resolved=(
                ResolvedEndpoint(
                    downstream.interface_name,
                    downstream.cidr,
                    consumer_reference,
                    NETWORK_CIDR,
                ),
            ),
        )
        downstream_dns = ConnectivityEndpoint(
            symbolic=f"service:dns@bastion:same-vlan:{downstream.vlan}",
            resolved=(
                ResolvedEndpoint(
                    f"{bastion_host}:{downstream.interface_name}",
                    downstream.bastion_address,
                    EntityReference("service", f"dns:{downstream.interface_name}"),
                    IP_ADDRESS,
                ),
            ),
        )
        dhcp_consumer = ConnectivityEndpoint(
            symbolic=f"l2:dhcp-client@vlan:{downstream.vlan}",
            resolved=(
                ResolvedEndpoint(
                    downstream.interface_name,
                    None,
                    consumer_reference,
                    SYMBOLIC_ADDRESS,
                ),
            ),
            resolution_scope="same-l2-segment",
        )
        downstream_dhcp = ConnectivityEndpoint(
            symbolic=f"service:authoritative-dhcp@bastion:vlan:{downstream.vlan}",
            resolved=(
                ResolvedEndpoint(
                    f"dhcp:{downstream.interface_name}",
                    None,
                    EntityReference("service", f"dhcp:{downstream.interface_name}"),
                    SYMBOLIC_ADDRESS,
                ),
            ),
            resolution_scope="same-l2-segment",
        )
        for architecture_rule, source, destination, purpose in (
            (DOWNSTREAM_DNS_RULE, downstream_endpoint, downstream_dns, DOWNSTREAM_DNS_RULE.purpose),
            (
                RANCHER_DOWNSTREAM_SSH_RULE,
                ConnectivityEndpoint("role:rancher", rancher_sources),
                downstream_endpoint,
                RANCHER_DOWNSTREAM_SSH_RULE.purpose,
            ),
            (
                DOWNSTREAM_DHCP_REQUEST_RULE,
                dhcp_consumer,
                downstream_dhcp,
                "Authoritative same-VLAN dnsmasq DHCP request; initial requests may broadcast",
            ),
            (
                DOWNSTREAM_DHCP_RESPONSE_RULE,
                downstream_dhcp,
                dhcp_consumer,
                "Authoritative same-VLAN dnsmasq DHCP response",
            ),
        ):
            add_connectivity_rule(
                f"{architecture_rule.id}:{downstream.interface_name}",
                source,
                destination,
                architecture_rule.protocols,
                architecture_rule.source_ports,
                architecture_rule.destination_ports,
                purpose,
                architecture_rule.category,
                requirement_sources=architecture_rule.requirement_sources,
                semantics=architecture_rule.semantics,
            )

    hosts_by_id = {host.id: host for host in hosts}
    endpoints_by_id = {endpoint.id: endpoint for endpoint in endpoints}
    actor_reference = EntityReference("actor", "actor:operator-workstation")
    operator_endpoint = ResolvedEndpoint(
        "operator-workstation", None, actor_reference, SYMBOLIC_ADDRESS
    )

    def reference_endpoint(reference, destination_addresses=()):
        if reference.kind == "actor":
            return operator_endpoint
        if reference.kind == "host":
            host = hosts_by_id[reference.id]
            address = host.ssh_target
            egress = None
            if destination_addresses:
                selected = _source_interface_for_destinations(
                    host.id, destination_addresses, interfaces, networks
                )
                address = selected.address if selected else None
                egress = EntityReference("interface", selected.id) if selected else None
            return ResolvedEndpoint(
                host.id,
                address,
                reference,
                IP_ADDRESS if address else SYMBOLIC_ADDRESS,
                egress,
            )
        endpoint = endpoints_by_id[reference.id]
        resolution = next(
            (item for item in endpoint.resolutions if item.addresses), None
        )
        address = resolution.addresses[0] if resolution else None
        return ResolvedEndpoint(
            endpoint.name,
            address,
            reference,
            resolution.address_kind
            if resolution
            else endpoint.resolutions[0].address_kind
            if endpoint.resolutions
            else SYMBOLIC_ADDRESS,
        )

    administrative_edges = _administrative_path_edges(access_paths)
    for rule_id in sorted(administrative_edges):
        source_reference, destination_reference = administrative_edges[rule_id]
        destination_addresses = ()
        destination_ports = ()
        if destination_reference.kind == "host":
            destination_host = hosts_by_id[destination_reference.id]
            destination_addresses = tuple(
                address for address in (destination_host.ssh_target,) if address
            )
            destination_resolved = ResolvedEndpoint(
                destination_host.id,
                destination_host.ssh_target,
                destination_reference,
                IP_ADDRESS if destination_host.ssh_target else SYMBOLIC_ADDRESS,
            )
            destination_ports = (22,)
        else:
            destination_resolved = reference_endpoint(destination_reference)
            destination_addresses = tuple(
                address for address in (destination_resolved.address,) if address
            )
            destination_endpoint = endpoints_by_id[destination_reference.id]
            destination_ports = destination_endpoint.ports
        source_resolved = reference_endpoint(source_reference, destination_addresses)
        add_connectivity_rule(
            rule_id,
            ConnectivityEndpoint(_reference_symbolic(source_reference), (source_resolved,)),
            ConnectivityEndpoint(
                _reference_symbolic(destination_reference),
                (destination_resolved,),
            ),
            ("TCP",),
            (),
            destination_ports,
            "Administrative SSH path segment",
            ADMINISTRATIVE,
            provenance=DERIVED,
        )

    local_dns_groups = {}
    for host in hosts:
        if host.id != bastion_host and host.dns_servers:
            local_dns_groups.setdefault(tuple(host.dns_servers), []).append(host)
    for index, (dns_servers, source_hosts) in enumerate(sorted(local_dns_groups.items())):
        rule_id = "core-dns:local-nodes" if index == 0 else f"core-dns:local-nodes:{index}"
        add_connectivity_rule(
            rule_id,
            ConnectivityEndpoint(
                "hosts:local-core",
                tuple(
                    ResolvedEndpoint(
                        host.id,
                        host.local_ip or host.primary_ip,
                        EntityReference("host", host.id),
                        IP_ADDRESS,
                    )
                    for host in source_hosts
                ),
            ),
            ConnectivityEndpoint(
                f"service:dns:local:{index}",
                tuple(
                    ResolvedEndpoint(
                        address,
                        address,
                        EntityReference("endpoint", f"endpoint:dns-local:{address}"),
                        IP_ADDRESS,
                    )
                    for address in dns_servers
                ),
            ),
            ("TCP", "UDP"),
            (),
            (53,),
            "Local nodes use their effective configured DNS servers",
            CORE_SERVICE,
        )

    if dns_upstream_endpoint_ids:
        upstream_addresses = tuple(
            endpoint_id.removeprefix("endpoint:dns-upstream:")
            for endpoint_id in dns_upstream_endpoint_ids
        )
        source_interface = _source_interface_for_destinations(
            bastion_host, upstream_addresses, interfaces, networks
        )
        add_connectivity_rule(
            "core-dns:upstream",
            ConnectivityEndpoint(
                "service:dns:local",
                (
                    ResolvedEndpoint(
                        "dns:local",
                        source_interface.address if source_interface else None,
                        EntityReference("service", "dns:local"),
                        IP_ADDRESS if source_interface else SYMBOLIC_ADDRESS,
                        EntityReference("interface", source_interface.id)
                        if source_interface
                        else None,
                    ),
                ),
            ),
            ConnectivityEndpoint(
                "endpoints:dns-upstream",
                tuple(
                    ResolvedEndpoint(
                        address,
                        address,
                        EntityReference("endpoint", endpoint_id),
                        IP_ADDRESS,
                    )
                    for endpoint_id, address in zip(
                        dns_upstream_endpoint_ids, upstream_addresses
                    )
                ),
                resolution_scope="external",
            ),
            ("TCP", "UDP"),
            (),
            (53,),
            "Bastion DNS forwards to configured upstream resolvers",
            CORE_SERVICE,
        )

    management_dns_addresses = tuple(
        endpoint_id.removeprefix("endpoint:dns-management:")
        for endpoint_id in management_dns_endpoint_ids
    )
    management_dns_source = _source_interface_for_destinations(
        bastion_host, management_dns_addresses, interfaces, networks
    )
    add_connectivity_rule(
        "core-dns:bastion-os",
        ConnectivityEndpoint(
            f"host:{bastion_host}",
            (
                ResolvedEndpoint(
                    bastion_host,
                    management_dns_source.address if management_dns_source else None,
                    EntityReference("host", bastion_host),
                    IP_ADDRESS if management_dns_source else SYMBOLIC_ADDRESS,
                    EntityReference("interface", management_dns_source.id)
                    if management_dns_source
                    else None,
                ),
            ),
        ),
        ConnectivityEndpoint(
            "endpoints:management-dns",
            tuple(
                ResolvedEndpoint(
                    address,
                    address,
                    EntityReference("endpoint", endpoint_id),
                    IP_ADDRESS,
                )
                for endpoint_id, address in zip(
                    management_dns_endpoint_ids, management_dns_addresses
                )
            ),
            resolution_scope="management",
        ),
        ("TCP", "UDP"),
        (),
        (53,),
        "Bastion operating system uses configured management DNS resolvers",
        CORE_SERVICE,
    )

    add_connectivity_rule(
        "core-proxy:rancher-nodes",
        ConnectivityEndpoint("cluster:rke2-rancher", rancher_sources),
        ConnectivityEndpoint(
            "service:proxy:squid",
            (
                ResolvedEndpoint(
                    "proxy:squid",
                    bastion_service_ip,
                    EntityReference("service", "proxy:squid"),
                    IP_ADDRESS,
                ),
            ),
        ),
        ("TCP",),
        (),
        (config["bastion"]["squid_http_port"],),
        "RKE2 and Rancher nodes use configured bastion Squid proxy",
        CORE_SERVICE,
    )
    add_connectivity_rule(
        "core-proxy:upstream",
        ConnectivityEndpoint(
            "service:proxy:squid",
            (
                ResolvedEndpoint(
                    "proxy:squid",
                    None,
                    EntityReference("service", "proxy:squid"),
                    SYMBOLIC_ADDRESS,
                ),
            ),
        ),
        ConnectivityEndpoint(
            "endpoint:proxy-upstream",
            (
                ResolvedEndpoint(
                    "external repositories and service endpoints",
                    None,
                    EntityReference("endpoint", "endpoint:proxy-upstream"),
                    SYMBOLIC_ADDRESS,
                ),
            ),
        ),
        ("TCP",),
        (),
        (80, 443),
        "Squid reaches required external repositories and service endpoints",
        CORE_SERVICE,
    )

    add_connectivity_rule(
        "deployment:terraform-backend",
        ConnectivityEndpoint("actor:operator-workstation", (operator_endpoint,)),
        ConnectivityEndpoint(
            "endpoint:terraform-backend",
            (
                ResolvedEndpoint(
                    backend_url,
                    backend_url,
                    EntityReference("endpoint", "endpoint:terraform-backend"),
                    URL,
                ),
            ),
            resolution_scope="external",
        ),
        ("TCP",),
        (),
        backend_ports,
        "Operator Terraform uses the configured GitLab HTTP backend",
        DEPLOYMENT,
    )
    add_connectivity_rule(
        "deployment:vcenter-api",
        ConnectivityEndpoint("actor:operator-workstation", (operator_endpoint,)),
        ConnectivityEndpoint(
            _reference_symbolic(EntityReference("endpoint", "endpoint:vcenter")),
            (reference_endpoint(EntityReference("endpoint", "endpoint:vcenter")),),
            resolution_scope="external",
        ),
        ("TCP",),
        (),
        (443,),
        "Operator Terraform uses the vCenter provider API",
        DEPLOYMENT,
    )

    primary_host = next(host for host in rancher_hosts if host.id == rke2_primary_host)
    join_hosts = tuple(host for host in rancher_hosts if host.id != rke2_primary_host)
    if join_hosts:
        add_connectivity_rule(
            "rke2:join-primary",
            ConnectivityEndpoint(
                "cluster:rke2-rancher:join-members",
                tuple(
                    ResolvedEndpoint(
                        host.id,
                        host.local_ip or host.primary_ip,
                        EntityReference("host", host.id),
                        IP_ADDRESS,
                    )
                    for host in join_hosts
                ),
            ),
            ConnectivityEndpoint(
                "cluster:rke2-rancher:primary",
                (
                    ResolvedEndpoint(
                        primary_host.id,
                        primary_host.local_ip or primary_host.primary_ip,
                        EntityReference("host", primary_host.id),
                        IP_ADDRESS,
                    ),
                ),
            ),
            ("TCP",),
            (),
            (9345,),
            "RKE2 server join connection to primary",
            RKE2_RANCHER,
        )

    bastion = hosts_by_id[bastion_host]
    add_connectivity_rule(
        "rke2:bastion-kubernetes-api",
        ConnectivityEndpoint(
            f"host:{bastion_host}",
            (
                ResolvedEndpoint(
                    bastion.id,
                    bastion.local_ip or bastion.primary_ip,
                    EntityReference("host", bastion.id),
                    IP_ADDRESS,
                ),
            ),
        ),
        ConnectivityEndpoint(
            "cluster:rke2-rancher:primary-api",
            (
                ResolvedEndpoint(
                    primary_host.id,
                    primary_host.local_ip or primary_host.primary_ip,
                    EntityReference("host", primary_host.id),
                    IP_ADDRESS,
                ),
            ),
        ),
        ("TCP",),
        (),
        (6443,),
        "Bastion administrative tooling uses the primary Kubernetes API",
        RKE2_RANCHER,
    )

    for downstream in downstream_networks:
        consumer_id = f"consumer:{downstream.id}"
        add_connectivity_rule(
            f"downstream-rancher-agent:{downstream.interface_name}",
            ConnectivityEndpoint(
                f"consumer:{downstream.interface_name}:rancher-agents",
                (
                    ResolvedEndpoint(
                        downstream.interface_name,
                        downstream.cidr,
                        EntityReference("downstream-consumer", consumer_id),
                        NETWORK_CIDR,
                    ),
                ),
            ),
            ConnectivityEndpoint(
                "endpoint:rancher:https",
                tuple(
                    ResolvedEndpoint(
                        address,
                        address,
                        EntityReference("endpoint", rancher_endpoint_id),
                        IP_ADDRESS,
                    )
                    for address in rancher_local_addresses
                ),
                resolution_scope="local",
            ),
            ("TCP",),
            (),
            (443,),
            "Downstream Rancher agents connect to the locally resolved Rancher endpoint",
            DOWNSTREAM,
            provenance=UPSTREAM_REQUIREMENT,
            requirement_sources=(UPSTREAM_PROTOCOL,),
        )
        add_connectivity_rule(
            f"external-routing:customer:{downstream.interface_name}",
            ConnectivityEndpoint(
                "network:customer",
                (
                    ResolvedEndpoint(
                        "customer",
                        next(network.cidr for network in networks if network.id == "customer"),
                        EntityReference("network", "customer"),
                        NETWORK_CIDR,
                    ),
                ),
            ),
            ConnectivityEndpoint(
                f"network:{downstream.id}",
                (
                    ResolvedEndpoint(
                        downstream.interface_name,
                        downstream.cidr,
                        EntityReference("network", downstream.id),
                        NETWORK_CIDR,
                    ),
                ),
            ),
            (),
            (),
            (),
            "Customer/downstream traffic depends on external routing and firewalling; bastion is not the router",
            DOWNSTREAM,
            semantics=EXTERNAL_ROUTING_DEPENDENCY,
            via=(EntityReference("endpoint", "endpoint:external-routed-fabric"),),
        )

    category_order = {
        ADMINISTRATIVE: 0,
        DEPLOYMENT: 1,
        CORE_SERVICE: 2,
        RKE2_RANCHER: 3,
        DOWNSTREAM: 4,
    }
    connectivity_rules.sort(key=lambda rule: (category_order[rule.category], rule.id))

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
        topology_schema_version=2,
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
    topology = EnvironmentTopology(
        metadata=metadata,
        hosts=tuple(hosts),
        interfaces=tuple(interfaces),
        networks=tuple(networks),
        services=tuple(services),
        downstream_networks=tuple(downstream_networks),
        connectivity_rules=tuple(connectivity_rules),
        notes=tuple(notes),
        clusters=clusters,
        endpoints=tuple(endpoints),
        actors=actors,
        access_paths=tuple(access_paths),
        downstream_consumers=downstream_consumers,
        deployment_context=deployment_context,
    )
    validate_topology(topology)
    return topology


def render_topology_json(topology):
    return json.dumps(topology.to_dict(), indent=2) + "\n"


def render_topology_architecture_mermaid(topology):
    """Render the support-oriented architecture view from V2 entities only."""
    metadata = topology.metadata
    hosts = {host.id: host for host in topology.hosts}
    endpoints = {endpoint.id: endpoint for endpoint in topology.endpoints}
    downstream_consumers = tuple(topology.downstream_consumers)
    bastion = hosts[metadata.bastion_host]
    operator_id = _mermaid_id("actor", "operator-workstation")
    bastion_id = _mermaid_id("host", bastion.id)
    cluster_ids = {
        cluster.id: _mermaid_id("cluster", cluster.id) for cluster in topology.clusters
    }
    endpoint_ids = {
        endpoint.id: _mermaid_id("endpoint", endpoint.id)
        for endpoint in topology.endpoints
    }
    consumer_ids = {
        consumer.id: _mermaid_id("consumer", consumer.id)
        for consumer in downstream_consumers
    }
    cluster_member_ids = {
        host_id for cluster in topology.clusters for host_id in cluster.member_host_ids
    }
    managed_hosts = tuple(
        host
        for host in topology.hosts
        if host.id != bastion.id and host.id not in cluster_member_ids
    )
    managed_ids = {
        host.id: _mermaid_id("host", host.id) for host in managed_hosts
    }
    access_paths = {path.destination.id: path for path in topology.access_paths}
    lines = ["flowchart LR", f'  {operator_id}["Operator / rinstall"]']

    jump_endpoints = tuple(
        endpoint
        for endpoint in topology.endpoints
        if endpoint.kind == "ssh-jump-alias"
    )
    if jump_endpoints:
        for endpoint in jump_endpoints:
            resolution = endpoint.resolution.lower().replace("_", " ")
            lines.append(
                f'  {endpoint_ids[endpoint.id]}["SSH jump<br/>{_mermaid(endpoint.name)}<br/>'
                f'{_mermaid(resolution)}"]'
            )

    lines.append(
        f'  {bastion_id}["Bastion<br/>{_mermaid(bastion.id)}<br/>'
        'DNS · DHCP · proxy · SSH transit"]'
    )
    if managed_hosts:
        lines.append('  subgraph managed_hosts["Managed hosts"]')
        lines.append("    direction TB")
        for host in managed_hosts:
            host_kind = "Monitoring" if MONITORING_HOST_ONLY in host.capabilities else host.roles[0].title()
            lines.append(
                f'    {managed_ids[host.id]}["{_mermaid(host_kind)} host<br/>{_mermaid(host.id)}"]'
            )
        lines.append("  end")

    for cluster in topology.clusters:
        cluster_id = cluster_ids[cluster.id]
        members = [
            f"{_mermaid(member_id)} primary"
            if member_id == cluster.primary_host_id
            else _mermaid(member_id)
            for member_id in cluster.member_host_ids
        ]
        lines.append(f'  {cluster_id}["RKE2 / Rancher cluster<br/>{"<br/>".join(members)}"]')

    rancher_endpoint = next(
        (endpoint for endpoint in topology.endpoints if endpoint.kind == "rancher-https"),
        None,
    )
    if rancher_endpoint is not None:
        endpoint_id = endpoint_ids[rancher_endpoint.id]
        external_resolution = next(
            (item for item in rancher_endpoint.resolutions if item.scope == "external"),
            None,
        )
        endpoint_label = (
            f'Rancher endpoint<br/>{_mermaid(rancher_endpoint.name)}<br/>'
            f'{_mermaid(" / ".join(rancher_endpoint.protocols))} / '
            f'{_mermaid(" / ".join(str(port) for port in rancher_endpoint.ports))}'
        )
        endpoint_label += "<br/>split-horizon DNS"
        lines.append(f'  {endpoint_id}["{endpoint_label}"]')

    if downstream_consumers:
        lines.append('  subgraph downstream["Downstream environments"]')
        lines.append("    direction TB")
        for consumer in downstream_consumers:
            downstream = next(
                item
                for item in topology.downstream_networks
                if item.id == consumer.network_id
            )
            lines.append(
                f'    {consumer_ids[consumer.id]}["Downstream nodes<br/>VLAN '
                f'{_mermaid(downstream.vlan)}<br/>external lifecycle"]'
            )
        lines.append("  end")

    context = topology.deployment_context
    if context is not None:
        vsphere_id = _mermaid_id("endpoint", context.vsphere.endpoint_id)
        backend_id = _mermaid_id("endpoint", context.terraform_backend.endpoint_id)
        lines.extend(
            [
                f'  {vsphere_id}["vSphere<br/>{_mermaid("runtime endpoint unresolved" if next(endpoint for endpoint in topology.endpoints if endpoint.id == context.vsphere.endpoint_id).resolution == RUNTIME_SUPPLIED else next(endpoint for endpoint in topology.endpoints if endpoint.id == context.vsphere.endpoint_id).name)}"]',
                f'  {backend_id}["Terraform state backend<br/>GitLab"]',
            ]
        )

    visual_ids = {
        "actor:operator-workstation": operator_id,
        bastion.id: bastion_id,
        **managed_ids,
    }
    for cluster in topology.clusters:
        visual_ids.update(
            {host_id: cluster_ids[cluster.id] for host_id in cluster.member_host_ids}
        )
    visual_ids.update(
        {
            endpoint.id: endpoint_ids[endpoint.id]
            for endpoint in jump_endpoints
        }
    )
    access_edges = set()
    for path in topology.access_paths:
        chain = (
            EntityReference("actor", "actor:operator-workstation"),
            *path.hops,
            path.destination,
        )
        for source, destination in zip(chain, chain[1:]):
            source_id = visual_ids.get(source.id)
            destination_id = visual_ids.get(destination.id)
            if source_id is not None and destination_id is not None:
                access_edges.add((source_id, destination_id))
    for source_id, destination_id in sorted(access_edges):
        lines.append(f"  {source_id} --> {destination_id}")

    for cluster in topology.clusters:
        cluster_id = cluster_ids[cluster.id]
        if rancher_endpoint is not None and rancher_endpoint.id in cluster.endpoint_ids:
            lines.append(f"  {cluster_id} --> {endpoint_ids[rancher_endpoint.id]}")

    if rancher_endpoint is not None:
        for consumer in downstream_consumers:
            if any(
                rule.category == DOWNSTREAM
                and any(
                    item.reference == EntityReference("downstream-consumer", consumer.id)
                    for item in rule.source.resolved
                )
                and any(
                    item.reference == EntityReference("endpoint", rancher_endpoint.id)
                    for item in rule.destination.resolved
                )
                for rule in topology.connectivity_rules
            ):
                lines.append(
                    f"  {consumer_ids[consumer.id]} --> {endpoint_ids[rancher_endpoint.id]}"
                )

    if context is not None:
        lines.append(f"  {operator_id} --> {vsphere_id}")
        lines.append(f"  {operator_id} --> {backend_id}")

    return "\n".join(lines) + "\n"


def render_topology_network_mermaid(topology):
    """Render the parallel network attachment view from V2 entities only."""
    metadata = topology.metadata
    hosts = {host.id: host for host in topology.hosts}
    networks = {network.id: network for network in topology.networks}
    bastion = hosts[metadata.bastion_host]
    downstream_by_id = {item.id: item for item in topology.downstream_networks}
    consumers_by_network = {
        consumer.network_id: consumer for consumer in topology.downstream_consumers
    }
    interfaces_by_network_host = {
        (interface.network, interface.host): interface for interface in topology.interfaces
    }
    host_ids = {host.id: _mermaid_id("host", host.id) for host in topology.hosts}
    network_ids = {
        network.id: _mermaid_id("network", network.id) for network in topology.networks
    }
    lines = ["flowchart TB"]

    def host_label(host_id, suffix=""):
        interface = interfaces_by_network_host.get(("customer", host_id))
        address = f"<br/>{_mermaid(interface.address)}" if interface is not None else ""
        return f"{_mermaid(host_id)}{_mermaid(suffix)}{address}"

    management = networks.get("management")
    if management is not None:
        management_interface = interfaces_by_network_host.get(("management", bastion.id))
        management_label = (
            f"Management<br/>{_mermaid(management.cidr or 'unknown')}<br/>"
            f"VMware: {_mermaid(management.vmware_network)}<br/>"
            f"bastion: {_mermaid(management_interface.address if management_interface else 'unknown')}"
        )
        lines.append(f'  {network_ids["management"]}["{management_label}"]')
    lines.append(
        f'  {host_ids[bastion.id]}["{_mermaid(bastion.id)}<br/>multi-homed<br/>not a router"]'
    )

    customer = networks.get("customer")
    if customer is not None:
        customer_interface = interfaces_by_network_host.get(("customer", bastion.id))
        customer_label = [
            "Customer",
            _mermaid(customer.cidr or "unknown"),
            f"VMware: {_mermaid(customer.vmware_network)}",
        ]
        if customer_interface is not None and customer_interface.address is not None:
            customer_label.append(f"bastion: {_mermaid(customer_interface.address)}")
        if customer.gateway is not None:
            customer_label.append(f"gateway: {_mermaid(customer.gateway)}")
        lines.append(f'  {network_ids[customer.id]}["' + "<br/>".join(customer_label) + '"]')

    cluster_member_ids = {
        host_id for cluster in topology.clusters for host_id in cluster.member_host_ids
    }
    managed_hosts = [
        host
        for host in topology.hosts
        if host.id != bastion.id and host.id not in cluster_member_ids
    ]
    for host in managed_hosts:
        role = host.roles[0].title() if host.roles else "Managed"
        lines.append(f'  {host_ids[host.id]}["{_mermaid(role)} host<br/>{host_label(host.id)}"]')

    for cluster in topology.clusters:
        cluster_id = _mermaid_id("cluster", cluster.id)
        lines.extend([
            f'  subgraph {cluster_id}["RKE2 / Rancher"]',
            "    direction TB",
        ])
        for host_id in cluster.member_host_ids:
            suffix = " primary" if host_id == cluster.primary_host_id else ""
            lines.append(f'    {host_ids[host_id]}["{host_label(host_id, suffix)}"]')
        lines.append("  end")

    for downstream in topology.downstream_networks:
        consumer = consumers_by_network[downstream.id]
        gateway_id = _mermaid_id(
            "external", downstream.gateway_endpoint_id or f"gateway:{downstream.id}"
        )
        consumer_id = _mermaid_id("consumer", consumer.id)
        network_id = network_ids[downstream.id]
        lines.extend([
            f'  subgraph {_mermaid_id("downstream", downstream.id)}["VLAN {downstream.vlan}"]',
            "    direction TB",
            f'    {network_id}["VLAN {_mermaid(downstream.vlan)}<br/>{_mermaid(downstream.cidr)}<br/>'
            f'VMware: {_mermaid(downstream.vmware_network)}<br/>bastion: {_mermaid(downstream.bastion_address)}"]',
            f'    {consumer_id}["Downstream nodes<br/>DHCP {_mermaid(consumer.address_start)}-'
            f'{_mermaid(consumer.address_end)}<br/>external lifecycle"]',
            f'    {gateway_id}["External gateway<br/>{_mermaid(downstream.gateway)}"]',
            "  end",
            f"  {network_id} --- {consumer_id}",
            f"  {network_id} --- {gateway_id}",
        ])

    for interface in topology.interfaces:
        if interface.host == bastion.id and interface.network == "management" and management is not None:
            lines.append(f"  {network_ids[interface.network]} --- {host_ids[interface.host]}")
        elif interface.host == bastion.id:
            lines.append(f"  {host_ids[interface.host]} --- {network_ids[interface.network]}")
        else:
            lines.append(f"  {network_ids[interface.network]} --- {host_ids[interface.host]}")

    if customer is not None:
        for downstream in topology.downstream_networks:
            lines.append(
                f'  {network_ids[customer.id]} -. "external routing / firewall" .-> '
                f'{network_ids[downstream.id]}'
            )
    return "\n".join(lines) + "\n"


def render_topology_ascii_overview(topology):
    metadata = topology.metadata
    lines = [
        f"Desired topology: {metadata.environment_id}",
        f"Bastion: {metadata.bastion_host} (multi-homed, not a router)",
        "Rancher endpoint (split-horizon DNS):",
        f"  https://{metadata.rancher_url}:443",
        "  internal / rinstall DNS: local Rancher node addresses",
        "  external DNS: external VIP/LB - unresolved",
        "",
        "Networks:",
    ]
    for network in topology.networks:
        lines.append(
            f"  {network.id:<24} {network.cidr or 'unknown':<18} {network.vmware_network}"
        )
    lines.extend(["", "Key connectivity:"])
    for category in (ADMINISTRATIVE, DEPLOYMENT, CORE_SERVICE, RKE2_RANCHER, DOWNSTREAM):
        count = sum(rule.category == category for rule in topology.connectivity_rules)
        if count:
            lines.append(f"  {_support_category(category):<18} {count} rules")
    lines.extend([
        "",
        "Status: desired only; reachability unverified;",
        "bastion is not the downstream router.",
    ])
    return "\n".join(lines) + "\n"


def _support_category(category):
    return {
        ADMINISTRATIVE: "Administrative",
        DEPLOYMENT: "Deployment",
        CORE_SERVICE: "Core services",
        RKE2_RANCHER: "RKE2 / Rancher",
        DOWNSTREAM: "Downstream",
    }.get(category, "Other")


def _support_entity_label(reference, topology):
    hosts = {host.id: host for host in topology.hosts}
    endpoints = {endpoint.id: endpoint for endpoint in topology.endpoints}
    services = {service.id: service for service in topology.services}
    networks = {network.id: network for network in topology.networks}
    clusters = {cluster.id: cluster for cluster in topology.clusters}
    consumers = {consumer.id: consumer for consumer in topology.downstream_consumers}
    if reference.kind == "host" and reference.id in hosts:
        return hosts[reference.id].id
    if reference.kind == "actor":
        return "Operator / rinstall"
    if reference.kind == "cluster" and reference.id in clusters:
        return "RKE2 / Rancher cluster"
    if reference.kind == "endpoint" and reference.id in endpoints:
        endpoint = endpoints[reference.id]
        if endpoint.kind == "ssh-jump-alias":
            return "SSH jump"
        if endpoint.kind == "vcenter":
            return "vCenter API"
        if endpoint.kind == "terraform-backend":
            return "Terraform backend"
        if endpoint.kind == "rancher-https":
            return "Rancher endpoint"
        if endpoint.kind == "proxy-upstream":
            return "External/upstream destinations"
        if endpoint.kind in {"dns-management", "dns-upstream"}:
            return "Management DNS" if endpoint.kind == "dns-management" else "Upstream DNS"
        return endpoint.name
    if reference.kind == "service" and reference.id in services:
        service = services[reference.id]
        if service.kind == "dns":
            return "Bastion DNS"
        if service.kind == "proxy":
            return "Bastion Squid proxy"
        if service.kind == "dhcp":
            return "Same-VLAN bastion DHCP"
        return service.purpose
    if reference.kind == "network" and reference.id in networks:
        network = networks[reference.id]
        return "Customer network" if network.kind == "local/customer" else f"VLAN {network.vlan}"
    if reference.kind == "downstream-consumer" and reference.id in consumers:
        consumer = consumers[reference.id]
        downstream = next(item for item in topology.downstream_networks if item.id == consumer.network_id)
        return f"Downstream nodes (VLAN {downstream.vlan})"
    return {
        "hosts:local-core": "Local nodes",
        "role:rancher": "Rancher nodes",
        "l2:dhcp-client@vlan:565": "DHCP clients (VLAN 565)",
        "l2:dhcp-client@vlan:566": "DHCP clients (VLAN 566)",
        "network:downstream:565": "VLAN 565",
        "network:downstream:566": "VLAN 566",
        "network:customer": "Customer network",
        "endpoints:management-dns": "Management DNS",
        "endpoints:dns-upstream": "Upstream DNS",
        "endpoint:proxy-upstream": "External/upstream destinations",
        "service:proxy:squid": "Bastion Squid proxy",
        "service:dns:local": "Bastion DNS",
        "service:authoritative-dhcp@bastion:vlan:565": "Same-VLAN bastion DHCP",
        "service:authoritative-dhcp@bastion:vlan:566": "Same-VLAN bastion DHCP",
        "endpoint:rancher:https": "Rancher endpoint",
        "cluster:rke2-rancher:primary-api": "Kubernetes API",
        "cluster:rke2-rancher:join-members": "RKE2 join nodes",
        "cluster:rke2-rancher:primary": "RKE2 primary",
    }.get(reference.id, reference.id)


def _support_endpoint_label(endpoint, topology):
    labels = []
    for resolved in endpoint.resolved:
        if resolved.reference is not None:
            label = _support_entity_label(resolved.reference, topology)
            if label == resolved.reference.id and resolved.id != resolved.reference.id:
                label = resolved.id
            labels.append(label)
    if labels:
        return ", ".join(dict.fromkeys(labels))
    return {
        "hosts:local-core": "Local nodes",
        "role:rancher": "Rancher nodes",
        "endpoint:rancher:https": "Rancher endpoint",
    }.get(endpoint.symbolic, endpoint.symbolic)


def _support_transport(rule):
    protocols = "/".join(rule.protocols)
    if rule.source_ports or rule.destination_ports:
        source = "/".join(str(port) for port in rule.source_ports) or "*"
        destination = "/".join(str(port) for port in rule.destination_ports) or "*"
        return f"{protocols} {source} -> {destination}"
    if rule.semantics == EXTERNAL_ROUTING_DEPENDENCY:
        return "external routing / firewall"
    return protocols or "service intent"


def _support_resolution(rule, topology):
    if rule.semantics == L2_SERVICE_INTENT:
        return "same-L2 service intent"
    scoped_endpoints = [
        endpoint
        for endpoint in (rule.source, rule.destination)
        if endpoint.resolution_scope == "local"
    ]
    endpoints = scoped_endpoints or (rule.source, rule.destination)
    values = []
    for endpoint in endpoints:
        for resolved in endpoint.resolved:
            if resolved.address is not None:
                values.append(resolved.address)
    if values:
        resolution_scopes = {
            endpoint.resolution_scope
            for endpoint in (rule.source, rule.destination)
            if endpoint.resolution_scope is not None
        }
        resolution = ", ".join(dict.fromkeys(values))
        if "local" in resolution_scopes:
            return f"internal / rinstall DNS: {resolution}"
        return resolution
    if any(endpoint.resolution_scope == "local" for endpoint in (rule.source, rule.destination)):
        return "internal / rinstall DNS"
    if rule.semantics == EXTERNAL_ROUTING_DEPENDENCY:
        return "symbolic external routing"
    return "symbolic / unresolved"


def _support_rule_row(rule, topology, include_category=False):
    source = _support_endpoint_label(rule.source, topology)
    destination = _support_endpoint_label(rule.destination, topology)
    cells = []
    if include_category:
        cells.append(_support_category(rule.category))
    cells.extend([source, destination, _support_transport(rule), rule.purpose])
    return cells


def _support_connectivity_tables(lines, topology, resolved=False):
    for category in (ADMINISTRATIVE, DEPLOYMENT, CORE_SERVICE, RKE2_RANCHER, DOWNSTREAM):
        rules = [rule for rule in topology.connectivity_rules if rule.category == category]
        if not rules:
            continue
        lines.extend([f"### {_support_category(category)}", ""])
        if resolved:
            lines.extend([
                "| Category | Source | Destination | Transport | Purpose | Resolution | Verification |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ])
            for rule in rules:
                cells = _support_rule_row(rule, topology, include_category=True)
                cells.extend([_support_resolution(rule, topology), rule.verification.lower()])
                lines.append("| " + " | ".join(_markdown(cell) for cell in cells) + " |")
        else:
            lines.extend([
                "| Source | Destination | Transport | Purpose |",
                "| --- | --- | --- | --- |",
            ])
            for rule in rules:
                lines.append("| " + " | ".join(_markdown(cell) for cell in _support_rule_row(rule, topology)) + " |")
        lines.append("")


def _render_support_topology_markdown(topology):
    metadata = topology.metadata
    endpoint_rows = []
    hosts_by_address = {
        address: host.id
        for host in topology.hosts
        for address in (host.local_ip, host.primary_ip)
        if address is not None
    }
    for endpoint in topology.endpoints:
        if endpoint.kind != "rancher-https":
            continue
        endpoint_name = f"https://{endpoint.name}:{endpoint.ports[0]}"
        for resolution in endpoint.resolutions:
            if resolution.scope == "local":
                desired = ", ".join(
                    f"{hosts_by_address.get(address, 'Rancher node')} {address}"
                    for address in resolution.addresses
                )
                scope = "internal / rinstall DNS"
            else:
                desired = "external VIP/LB - unresolved"
                scope = "external DNS"
            endpoint_rows.append((endpoint_name, scope, desired))

    lines = [
        f"# Desired Topology: {metadata.environment_id}",
        "",
        "> Status: desired configuration only; runtime state and network reachability are not verified.",
        "> External dependencies may be unresolved; downstream lifecycle is external; the bastion is not the downstream router.",
        "",
        "## Architecture Map", "", "```mermaid",
        render_topology_architecture_mermaid(topology).rstrip(), "```", "",
        "## Network Topology", "", "```mermaid",
        render_topology_network_mermaid(topology).rstrip(), "```", "",
        "## Endpoint Resolution", "",
        "| Endpoint | Scope | Desired resolution |",
        "| --- | --- | --- |",
    ]
    lines.extend("| " + " | ".join(_markdown(cell) for cell in row) + " |" for row in endpoint_rows)
    lines.extend([
        "", "## Environment", "",
        "| Environment | Rancher URL | Domain | RKE2 | Rancher | cert-manager |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {_markdown(metadata.environment_id)} | {_markdown(metadata.rancher_url)} | {_markdown(metadata.domain)} | {_markdown(metadata.versions['rke2'])} | {_markdown(metadata.versions['rancher'])} | {_markdown(metadata.versions['cert_manager'])} |",
        "", "## Deployment Context", "",
        "| Property | Desired value |", "| --- | --- |",
    ])
    context = topology.deployment_context
    if context is not None:
        vsphere = context.vsphere
        deployment_rows = [
            ("vCenter endpoint", next(endpoint.name for endpoint in topology.endpoints if endpoint.id == vsphere.endpoint_id)),
            ("Datacenter", vsphere.datacenter), ("Resource pool", vsphere.resource_pool),
            ("Datastore", vsphere.datastore), ("VM folder", vsphere.folder),
            (
                "Clone timeout",
                (
                    f"{vsphere.clone_timeout_minutes} minutes"
                    if vsphere.clone_timeout_minutes is not None
                    else "not configured (Terraform default: 60 minutes)"
                ),
            ),
            ("TLS verification", "disabled" if vsphere.allow_unverified_ssl else "enabled"),
            ("Terraform backend", f"{context.terraform_backend.type} ({context.terraform_backend.state_name})"),
        ]
        deployment_rows.extend((f"Template: {item.id}", item.value or "unresolved") for item in vsphere.templates)
        network_by_id = {item.id: item for item in topology.networks}
        deployment_rows.extend(
            (
                f"VMware network: {item.id}",
                network_by_id[item.reference.id].vmware_network if item.reference else item.value or "unresolved",
            )
            for item in vsphere.networks
        )
        lines.extend(f"| {_markdown(key)} | {_markdown(value)} |" for key, value in deployment_rows)
    lines.extend(["", "## Hosts and Clusters", "", "| Component | Desired addresses / membership | SSH target |", "| --- | --- | --- |"])
    bastion = next(host for host in topology.hosts if host.id == metadata.bastion_host)
    lines.append(f"| Bastion: {_markdown(bastion.id)} | customer {_markdown(bastion.local_ip or 'unknown')}; management {_markdown(bastion.management_ip or 'unknown')} | {_markdown(bastion.ssh_target or 'unknown')} |")
    for host in topology.hosts:
        if host.id == bastion.id:
            continue
        if any(host.id in cluster.member_host_ids for cluster in topology.clusters):
            continue
        host_kind = "Monitoring" if MONITORING_HOST_ONLY in host.capabilities else host.roles[0].title()
        lines.append(f"| {_markdown(host_kind)}: {_markdown(host.id)} | {_markdown(host.local_ip or 'unknown')} | {_markdown(host.ssh_target or 'unknown')} |")
    for cluster in topology.clusters:
        members = ", ".join(
            f"{host_id} ({'primary' if host_id == cluster.primary_host_id else 'member'})"
            for host_id in cluster.member_host_ids
        )
        lines.append(f"| RKE2 / Rancher cluster | {_markdown(members)} | - |")
    lines.extend(["", "## Networks", "", "| Network | Kind | CIDR | VMware network | VLAN | Bastion IP | Gateway | DHCP |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    downstream_by_id = {item.id: item for item in topology.downstream_networks}
    for network in topology.networks:
        downstream = downstream_by_id.get(network.id)
        bastion_ip = next((interface.address for interface in topology.interfaces if interface.host == bastion.id and interface.network == network.id), "-")
        dhcp = f"{downstream.dhcp_start}-{downstream.dhcp_end}" if downstream else "-"
        lines.append(f"| {_markdown(network.id)} | {_markdown(network.kind)} | {_markdown(network.cidr or 'unknown')} | {_markdown(network.vmware_network)} | {_markdown(network.vlan if network.vlan is not None else '-')} | {_markdown(bastion_ip or '-')} | {_markdown(network.gateway or '-')} | {_markdown(dhcp)} |")
    lines.extend(["", "## Key Connectivity", ""])
    _support_connectivity_tables(lines, topology)
    lines.extend(["## Resolved Connectivity", ""])
    _support_connectivity_tables(lines, topology, resolved=True)
    lines.extend(["## Details", "", "<details>", "<summary>Interfaces</summary>", "", "| Host | Logical interface | Network | Address | Addressing |", "| --- | --- | --- | --- | --- |"])
    for interface in topology.interfaces:
        address = f"{interface.address}/{interface.prefix}" if interface.address and interface.prefix else "unknown"
        lines.append(f"| {_markdown(interface.host)} | {_markdown(interface.logical_name)} | {_markdown(interface.network)} | {_markdown(address)} | {_markdown(interface.addressing)} |")
    lines.extend(["", "</details>", "", "<details>", "<summary>Bastion services, routes, and lifecycle notes</summary>", ""])
    for service in topology.services:
        lines.append(f"- Service: {_markdown(service.purpose)} ({_markdown(service.address)})")
    if context is not None:
        lines.append(f"- vSphere route: {_markdown(context.vsphere.route.destination)} via {_markdown(context.vsphere.route.gateway)}")
    lines.extend(["", "</details>", "", "## Notes", "", *[f"- {_markdown(note)}" for note in topology.notes], "- Runtime state, network reachability, and external endpoint reachability are not verified.", "- The bastion provides downstream services but is not the downstream router.", ""])
    return "\n".join(lines)


def render_topology_markdown(topology):
    return _render_support_topology_markdown(topology)
