from copy import deepcopy
from ipaddress import ip_address, ip_interface, ip_network
from pathlib import Path
import re
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

import yaml

from lib.bastion_network import normalize_ipv4_route


DEFAULT_NO_PROXY_CIDRS = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
]

DEFAULT_NO_PROXY_NAMES = [
    "cattle-system.svc",
    ".svc",
    ".cluster.local",
]

SUPPORTED_SCHEMA_VERSION = 1
ENVIRONMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
RANCHER_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
DNSMASQ_LEASE_TIME_PATTERN = re.compile(r"^[1-9][0-9]*[smhdw]$")


def require(mapping, key, context):
    if key not in mapping or mapping[key] is None:
        raise SystemExit(f"missing {context}.{key}")
    return mapping[key]


def validate_ipv4_servers(servers, context):
    if (
        not isinstance(servers, list)
        or not servers
        or not all(isinstance(server, str) and server for server in servers)
    ):
        raise SystemExit(f"{context} must be a non-empty list of IPv4 DNS servers")
    for index, server in enumerate(servers):
        try:
            parsed = ip_address(server)
        except ValueError:
            raise SystemExit(f"{context}[{index}] must be a canonical IPv4 address") from None
        if parsed.version != 4 or str(parsed) != server:
            raise SystemExit(f"{context}[{index}] must be a canonical IPv4 address")


def gitlab_backend_state_address(backend, environment_id):
    return f"{backend['url'].rstrip('/')}/api/v4/projects/{backend['project_id']}/terraform/state/{environment_id}-infra"


def effective_local_dns_servers(node, local_vlan):
    """Return the DNS servers used by a local node after configuration coalescing."""
    return tuple(
        node["dns_servers"]
        if node.get("dns_servers") is not None
        else local_vlan.get("dns_servers", ())
    )


def validate_environment_identity(env):
    schema_version = require(env, "schema_version", "env")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise SystemExit(
            f"env.schema_version must be {SUPPORTED_SCHEMA_VERSION}, got {schema_version!r}"
        )

    environment = require(env, "environment", "env")
    environment_id = require(environment, "id", "env.environment")
    if not isinstance(environment_id, str) or not ENVIRONMENT_ID_PATTERN.fullmatch(environment_id):
        raise SystemExit(
            "env.environment.id must contain only lowercase letters, digits, dots, and hyphens"
        )

    rancher_url = require(env, "rancher_url", "env")
    try:
        is_ip_literal = isinstance(rancher_url, str) and ip_address(rancher_url) is not None
    except ValueError:
        is_ip_literal = False
    if (
        not isinstance(rancher_url, str)
        or is_ip_literal
        or not RANCHER_HOSTNAME_PATTERN.fullmatch(rancher_url)
    ):
        raise SystemExit("env.rancher_url must be a bare fully qualified DNS hostname")

    return environment_id


def address_from_host(network, host, context):
    if isinstance(host, bool) or not isinstance(host, int):
        raise SystemExit(f"{context} must be an integer host offset") from None

    offset = host
    if offset < 0 or offset >= network.num_addresses:
        raise SystemExit(f"{context}={offset} is outside {network}")

    address = network.network_address + offset
    if address == network.network_address:
        raise SystemExit(f"{context}={offset} resolves to network address {address}")
    if address == network.broadcast_address:
        raise SystemExit(f"{context}={offset} resolves to broadcast address {address}")

    return str(address)


def resolve_ipv4_address(network, value, context):
    if isinstance(value, bool):
        raise SystemExit(f"{context} must be a relative integer or absolute IPv4 address")

    if isinstance(value, int):
        if value == 0:
            raise SystemExit(f"{context}=0 is invalid; relative offsets start at 1 or -1")
        usable_hosts = network.num_addresses - 2
        if abs(value) > usable_hosts:
            raise SystemExit(f"{context}={value} is outside the usable host range of {network}")
        address = network.network_address + value if value > 0 else network.broadcast_address + value
    elif isinstance(value, str):
        if re.fullmatch(r"[+-]?[0-9]+", value):
            raise SystemExit(f"{context}={value!r} is ambiguous; use an integer offset")
        try:
            address = ip_address(value)
        except ValueError as error:
            raise SystemExit(f"{context} must be a relative integer or absolute IPv4 address: {error}") from None
        if address.version != 4:
            raise SystemExit(f"{context} must be an IPv4 address")
        if address not in network:
            raise SystemExit(f"{context}={address} is outside {network}")
    else:
        raise SystemExit(f"{context} must be a relative integer or absolute IPv4 address")

    if address == network.network_address:
        raise SystemExit(f"{context} resolves to network address {address}")
    if address == network.broadcast_address:
        raise SystemExit(f"{context} resolves to broadcast address {address}")
    return str(address)


def resolve_downstream_networks(bastion, local_network, environment_id):
    downstream_networks = bastion.setdefault("downstream_networks", [])
    if not isinstance(downstream_networks, list):
        raise SystemExit("env.bastion.downstream_networks must be a list")

    vlans = set()
    interface_names = set()
    vmware_networks = set()
    resolved_networks = []

    for index, downstream in enumerate(downstream_networks):
        context = f"env.bastion.downstream_networks[{index}]"
        if not isinstance(downstream, dict):
            raise SystemExit(f"{context} must be a mapping")

        vlan = require(downstream, "vlan", context)
        if isinstance(vlan, bool) or not isinstance(vlan, int) or not 1 <= vlan <= 4094:
            raise SystemExit(f"{context}.vlan must be an integer from 1 through 4094")
        if vlan in vlans:
            raise SystemExit(f"{context}.vlan duplicates VLAN {vlan}")
        vlans.add(vlan)

        interface_name = f"vlan{vlan}"
        if interface_name in interface_names:
            raise SystemExit(f"{context}.vlan derives duplicate interface name {interface_name}")
        interface_names.add(interface_name)

        vmware_network = require(downstream, "vmware_network", context)
        if not isinstance(vmware_network, str) or not vmware_network.strip():
            raise SystemExit(f"{context}.vmware_network must be a non-empty string")
        if vmware_network in vmware_networks:
            raise SystemExit(f"{context}.vmware_network duplicates VMware network {vmware_network!r}")
        vmware_networks.add(vmware_network)

        subnet = require(downstream, "subnet", context)
        if not isinstance(subnet, str):
            raise SystemExit(f"{context}.subnet must be a canonical IPv4 subnet")
        try:
            network = ip_network(subnet, strict=True)
        except ValueError as error:
            raise SystemExit(f"{context}.subnet is invalid or non-canonical: {error}") from None
        if network.version != 4:
            raise SystemExit(f"{context}.subnet must be IPv4")
        if network.prefixlen >= 31:
            raise SystemExit(f"{context}.subnet must provide usable host addresses")
        if network.overlaps(local_network):
            raise SystemExit(f"{context}.subnet {network} overlaps local VLAN {local_network}")
        for previous_network in resolved_networks:
            if network.overlaps(previous_network):
                raise SystemExit(f"{context}.subnet {network} overlaps downstream subnet {previous_network}")
        resolved_networks.append(network)

        gateway = resolve_ipv4_address(network, require(downstream, "gateway", context), f"{context}.gateway")
        bastion_address = resolve_ipv4_address(
            network,
            require(downstream, "bastion_address", context),
            f"{context}.bastion_address",
        )
        if gateway == bastion_address:
            raise SystemExit(f"{context}.gateway must differ from bastion_address")

        dhcp = require(downstream, "dhcp", context)
        if not isinstance(dhcp, dict):
            raise SystemExit(f"{context}.dhcp must be a mapping")
        dhcp_start = resolve_ipv4_address(network, require(dhcp, "start", f"{context}.dhcp"), f"{context}.dhcp.start")
        dhcp_end = resolve_ipv4_address(network, require(dhcp, "end", f"{context}.dhcp"), f"{context}.dhcp.end")
        if ip_address(dhcp_start) > ip_address(dhcp_end):
            raise SystemExit(f"{context}.dhcp.start must be less than or equal to dhcp.end")
        if ip_address(dhcp_start) <= ip_address(gateway) <= ip_address(dhcp_end):
            raise SystemExit(f"{context}.gateway must not be inside the DHCP pool")
        if ip_address(dhcp_start) <= ip_address(bastion_address) <= ip_address(dhcp_end):
            raise SystemExit(f"{context}.bastion_address must not be inside the DHCP pool")

        lease_time = require(dhcp, "lease_time", f"{context}.dhcp")
        if not isinstance(lease_time, str) or not DNSMASQ_LEASE_TIME_PATTERN.fullmatch(lease_time):
            raise SystemExit(f"{context}.dhcp.lease_time must be a positive integer followed by s, m, h, d, or w")

        downstream["subnet"] = str(network)
        downstream["prefix"] = network.prefixlen
        downstream["netmask"] = str(network.netmask)
        downstream["interface_name"] = interface_name
        downstream["connection_uuid"] = str(
            uuid5(NAMESPACE_URL, f"rinstall:{environment_id}:downstream:{interface_name}")
        )
        downstream["gateway"] = gateway
        downstream["bastion_address"] = bastion_address
        dhcp["start"] = dhcp_start
        dhcp["end"] = dhcp_end

    return resolved_networks


def validate_name_exists(name, collection, context):
    if name not in collection:
        raise SystemExit(f"{context} references unknown name: {name}")


def validate_role(name, nodes, role, context):
    validate_name_exists(name, nodes, context)
    actual = nodes[name].get("role")
    if actual != role:
        raise SystemExit(f"{context} references {name} with role {actual!r}, expected {role!r}")


def domain_from_rancher_url(rancher_url):
    parts = str(rancher_url).split(".", 1)
    if len(parts) != 2 or not parts[1]:
        raise SystemExit("env.rancher_url must be a fully qualified hostname when env.domain is omitted")
    return parts[1]


def validate_env_references(env):
    terraform = require(env, "terraform", "env")
    backend = require(terraform, "backend", "env.terraform")
    backend_type = require(backend, "type", "env.terraform.backend")
    if backend_type != "gitlab":
        raise SystemExit("env.terraform.backend.type must be 'gitlab'")
    if "state" in backend:
        raise SystemExit(
            "env.terraform.backend.state is no longer supported; state is derived from env.environment.id"
        )
    url = require(backend, "url", "env.terraform.backend")
    parsed_url = urlparse(str(url))
    if parsed_url.username is not None or parsed_url.password is not None:
        raise SystemExit("env.terraform.backend.url must not contain credentials")
    if (
        not isinstance(url, str)
        or not url.strip()
        or parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.path not in {"", "/"}
    ):
        raise SystemExit("env.terraform.backend.url must be a non-empty GitLab base URL")
    project_id = require(backend, "project_id", "env.terraform.backend")
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id <= 0:
        raise SystemExit("env.terraform.backend.project_id must be a positive integer")
    infra = require(env, "infra", "env")
    vsphere = require(infra, "vsphere", "env.infra")
    if "clone_timeout" in vsphere:
        clone_timeout = vsphere["clone_timeout"]
        if isinstance(clone_timeout, bool) or not isinstance(clone_timeout, int) or clone_timeout <= 0:
            raise SystemExit("env.infra.vsphere.clone_timeout must be a positive integer")
    networks = require(infra, "networks", "env.infra")
    templates = require(infra, "templates", "env.infra")
    local_vlan = require(require(env, "local", "env"), "vlan", "env.local")
    nodes = require(env, "nodes", "env")
    bastion_nodes = [name for name, node in nodes.items() if node.get("role") == "bastion"]
    if len(bastion_nodes) != 1:
        raise SystemExit("schema v1 supports exactly one bastion node")

    for node_name, node in nodes.items():
        validate_name_exists(
            require(node, "template", f"env.nodes.{node_name}"),
            templates,
            f"env.nodes.{node_name}.template",
        )
        for index, nic in enumerate(require(node, "nics", f"env.nodes.{node_name}")):
            validate_name_exists(
                require(nic, "network", f"env.nodes.{node_name}.nics[{index}]"),
                networks,
                f"env.nodes.{node_name}.nics[{index}].network",
            )

    bastion = require(env, "bastion", "env")
    service_node = require(bastion, "service_node", "env.bastion")

    connection_names = bastion.get("network_connection_names", {})
    if not isinstance(connection_names, dict):
        raise SystemExit("env.bastion.network_connection_names must be a mapping")
    if any(
        not isinstance(source, str)
        or not source
        or not isinstance(target, str)
        or not target
        for source, target in connection_names.items()
    ):
        raise SystemExit(
            "env.bastion.network_connection_names must map non-empty connection IDs"
        )
    for dns_node in local_vlan.get("dns_nodes", [service_node]):
        validate_name_exists(dns_node, nodes, "env.local.vlan.dns_nodes")

    validate_role(
        service_node,
        nodes,
        "bastion",
        "env.bastion.service_node",
    )
    bastion_nics = nodes[service_node]["nics"]
    connection_ids = []
    for index, nic in enumerate(bastion_nics):
        connection_name = nic.get("connection_name")
        if not isinstance(connection_name, str) or not connection_name:
            raise SystemExit(
                f"env.nodes.{service_node}.nics[{index}].connection_name must be a non-empty string"
            )
        if connection_name in connection_ids:
            raise SystemExit(
                f"env.nodes.{service_node}.nics[].connection_name must be unique: {connection_name}"
            )
        connection_ids.append(connection_name)
    unmapped_sources = sorted(set(connection_names) - set(connection_ids))
    if unmapped_sources:
        raise SystemExit(
            "env.bastion.network_connection_names sources missing bastion NIC connection_name: "
            + ", ".join(unmapped_sources)
        )
    final_connection_ids = [
        connection_names.get(connection_id, connection_id)
        for connection_id in connection_ids
    ]
    if len(final_connection_ids) != len(set(final_connection_ids)):
        raise SystemExit(
            "env.bastion.network_connection_names produces duplicate bastion connection IDs"
        )
    validate_role(
        require(require(env, "rke2", "env"), "primary_node", "env.rke2"),
        nodes,
        "rancher",
        "env.rke2.primary_node",
    )

    roles = {node.get("role") for node in nodes.values()}
    for role in env.get("ssh", {}).get("bastion_proxy_roles", []):
        if role not in roles:
            raise SystemExit(f"env.ssh.bastion_proxy_roles references unknown role: {role}")

    rancher = require(env, "rancher", "env")
    edition = rancher.get("edition", "community")
    if edition not in {"community", "prime"}:
        raise SystemExit("env.rancher.edition must be 'community' or 'prime'")
    editions = require(rancher, "editions", "env.rancher")
    validate_name_exists(edition, editions, "env.rancher.edition")
    selected = editions[edition]
    require(selected, "repo_name", f"env.rancher.editions.{edition}")
    require(selected, "repo_url", f"env.rancher.editions.{edition}")
    require(selected, "version", f"env.rancher.editions.{edition}")


def expand_node_pools(env):
    nodes = require(env, "nodes", "env")
    rancher_pool = env.get("local", {}).get("rancher_nodes")
    if not rancher_pool:
        return

    prefix = require(rancher_pool, "name_prefix", "env.local.rancher_nodes")
    count = int(require(rancher_pool, "count", "env.local.rancher_nodes"))
    start_host = int(require(rancher_pool, "start_host", "env.local.rancher_nodes"))
    if count < 1:
        raise SystemExit("env.local.rancher_nodes.count must be >= 1")

    for index in range(1, count + 1):
        name = f"{prefix}{index}"
        if name in nodes:
            raise SystemExit(f"env.local.rancher_nodes would overwrite existing node: {name}")
        nodes[name] = {
            "role": "rancher",
            "template": require(rancher_pool, "template", "env.local.rancher_nodes"),
            "host": start_host + index - 1,
            "cpu": require(rancher_pool, "cpu", "env.local.rancher_nodes"),
            "memory_mb": require(rancher_pool, "memory_mb", "env.local.rancher_nodes"),
            "disk_gb": require(rancher_pool, "disk_gb", "env.local.rancher_nodes"),
            "nics": deepcopy(require(rancher_pool, "nics", "env.local.rancher_nodes")),
        }

    env.setdefault("rke2", {}).setdefault("primary_node", f"{prefix}1")


def load_env(path):
    config_path = Path(path).resolve()
    with config_path.open() as stream:
        return expand_env(yaml.safe_load(stream))


def expand_env(raw_env):
    env = deepcopy(raw_env)
    environment_id = validate_environment_identity(env)
    env.setdefault("domain", domain_from_rancher_url(require(env, "rancher_url", "env")))
    expand_node_pools(env)
    validate_env_references(env)

    local_vlan = require(require(env, "local", "env"), "vlan", "env.local")
    env["local_vlan"] = local_vlan
    cidr = require(local_vlan, "cidr", "env.local.vlan")
    network = ip_network(cidr, strict=False)

    bastion = require(env, "bastion", "env")
    resolve_downstream_networks(bastion, network, environment_id)
    bastion_name = require(bastion, "service_node", "env.bastion")
    base_vmware_networks = {
        env["infra"]["networks"][nic["network"]]
        for nic in env["nodes"][bastion_name]["nics"]
    }
    for downstream in bastion["downstream_networks"]:
        if downstream["vmware_network"] in base_vmware_networks:
            raise SystemExit(
                "env.bastion.downstream_networks VMware network conflicts with an existing bastion NIC: "
                f"{downstream['vmware_network']}"
            )
    if len(env["nodes"][bastion_name]["nics"]) + len(bastion["downstream_networks"]) > 10:
        raise SystemExit("the configured bastion cannot have more than 10 VMware NICs")

    local_vlan["prefix"] = network.prefixlen
    local_vlan["gateway"] = address_from_host(
        network,
        require(local_vlan, "gateway_host", "env.local.vlan"),
        "env.local.vlan.gateway_host",
    )

    nodes = require(env, "nodes", "env")
    for name, node in nodes.items():
        if node.get("ip") is None and node.get("host") is not None:
            node["ip"] = address_from_host(network, node["host"], f"env.nodes.{name}.host")
        if node.get("gateway") is None and node.get("ip") is not None:
            node["gateway"] = local_vlan["gateway"]
        for nic in require(node, "nics", f"env.nodes.{name}"):
            if nic.get("cidr") is not None:
                try:
                    interface = ip_interface(nic["cidr"])
                except ValueError as error:
                    raise SystemExit(f"env.nodes.{name}.nics[].cidr is invalid: {error}") from None
                nic["ip"] = str(interface.ip)
                nic["prefix"] = interface.network.prefixlen
            if nic.get("ip") is None:
                if nic.get("host") is not None:
                    nic["ip"] = address_from_host(network, nic["host"], f"env.nodes.{name}.nics[].host")
                elif nic.get("network") == "customer" and node.get("ip") is not None:
                    nic["ip"] = node["ip"]
            if nic.get("prefix") is None and nic.get("ip") is not None:
                nic["prefix"] = local_vlan["prefix"]
            if nic.get("network") == "management" and nic.get("ip") is not None and node.get("ssh_ip") is None:
                node["ssh_ip"] = nic["ip"]
        if node.get("dns_servers") is not None:
            validate_ipv4_servers(node["dns_servers"], f"env.nodes.{name}.dns_servers")

    primary_ips = {}
    for name, node in nodes.items():
        ip = node.get("ip")
        if ip is None:
            continue
        if ip == local_vlan["gateway"]:
            raise SystemExit(f"env.nodes.{name}.ip {ip} conflicts with local VLAN gateway")
        previous_name = primary_ips.get(ip)
        if previous_name is not None:
            raise SystemExit(f"env.nodes.{name}.ip {ip} conflicts with env.nodes.{previous_name}.ip")
        primary_ips[ip] = name

    bastion.setdefault("squid_http_port", 3128)
    bastion["vsphere_route"] = normalize_ipv4_route(
        require(bastion, "vsphere_route", "env.bastion"),
        "env.bastion.vsphere_route",
    )
    vsphere_route_network = ip_network(bastion["vsphere_route"].split()[0])
    bastion_nic_networks = [
        ip_interface(f"{nic['ip']}/{nic['prefix']}").network
        for nic in nodes[bastion_name]["nics"]
        if nic.get("ip") is not None
    ]
    for downstream in bastion["downstream_networks"]:
        downstream_subnet = ip_network(downstream["subnet"])
        if downstream_subnet.overlaps(vsphere_route_network):
            raise SystemExit(
                "env.bastion.downstream_networks subnet overlaps env.bastion.vsphere_route: "
                f"{downstream_subnet}"
            )
        for nic_network in bastion_nic_networks:
            if downstream_subnet.overlaps(nic_network):
                raise SystemExit(
                    "env.bastion.downstream_networks subnet overlaps an existing bastion NIC network: "
                    f"{downstream_subnet}"
                )
    route_connection = require(bastion, "vsphere_route_connection", "env.bastion")
    if not isinstance(route_connection, str) or not route_connection:
        raise SystemExit("env.bastion.vsphere_route_connection must be a non-empty string")
    connection_names = bastion.get("network_connection_names", {})
    base_nics = nodes[bastion_name]["nics"]
    if route_connection in connection_names and connection_names[route_connection] != route_connection:
        raise SystemExit(
            "env.bastion.vsphere_route_connection refers to a bastion connection that is renamed"
        )
    management_interfaces = [
        source
        for source, target in connection_names.items()
        if target == route_connection
    ]
    if len(management_interfaces) > 1:
        raise SystemExit(
            "env.bastion.network_connection_names maps multiple devices to "
            "env.bastion.vsphere_route_connection"
        )
    bastion["management_interface"] = management_interfaces[0] if management_interfaces else route_connection
    route_nic_indices = [
        index
        for index, nic in enumerate(base_nics)
        if connection_names.get(nic["connection_name"], nic["connection_name"]) == route_connection
    ]
    if len(route_nic_indices) != 1:
        raise SystemExit(
            "env.bastion.vsphere_route_connection must match exactly one bastion NIC connection_name"
        )
    route_nic_index = route_nic_indices[0]
    bastion["route_nic_index"] = route_nic_index
    bastion["dnsmasq_upstream_servers"] = require(
        bastion, "dnsmasq_upstream_servers", "env.bastion"
    )
    validate_ipv4_servers(
        bastion["dnsmasq_upstream_servers"],
        "env.bastion.dnsmasq_upstream_servers",
    )
    bastion_dns_servers = require(nodes[bastion_name], "dns_servers", f"env.nodes.{bastion_name}")
    validate_ipv4_servers(bastion_dns_servers, f"env.nodes.{bastion_name}.dns_servers")
    dns_nodes = local_vlan.setdefault("dns_nodes", [bastion_name])
    local_vlan["dns_servers"] = [nodes[name]["ip"] for name in dns_nodes]

    if bastion.get("service_ip") is None:
        bastion["service_ip"] = nodes[bastion_name]["ip"]
    bastion_addresses = {
        nic["ip"]
        for nic in nodes[bastion_name]["nics"]
        if nic.get("ip") is not None
    }
    if bastion["service_ip"] not in bastion_addresses:
        raise SystemExit(
            "env.bastion.service_ip must match an IPv4 address assigned to a bastion NIC"
        )

    route_nic = nodes[bastion_name]["nics"][route_nic_index]
    if route_nic.get("ip") is not None:
        route_network = ip_interface(
            f"{route_nic['ip']}/{route_nic['prefix']}"
        ).network
        route_gateway = ip_address(bastion["vsphere_route"].split()[1])
        if route_gateway not in route_network:
            raise SystemExit(
                "env.bastion.vsphere_route_connection does not match the "
                "vSphere route gateway subnet"
            )

    rke2 = require(env, "rke2", "env")
    require(rke2, "version", "env.rke2")
    rke2.setdefault("token_file", "/etc/rancher/rke2/token")
    rke2.setdefault("selinux", True)
    rke2.setdefault("tls_sans", [require(env, "rancher_url", "env")])
    primary_name = require(rke2, "primary_node", "env.rke2")
    primary_ip = nodes[primary_name]["ip"]
    for name, node in nodes.items():
        if node.get("role") == "rancher" and node.get("rke2_server") is None and name != primary_name:
            node["rke2_server"] = f"https://{primary_ip}:9345"

    proxy = env.setdefault("proxy", {})
    no_proxy = list(proxy.get("no_proxy_cidrs", DEFAULT_NO_PROXY_CIDRS))
    no_proxy.extend(DEFAULT_NO_PROXY_NAMES)
    no_proxy.extend([local_vlan["cidr"], require(env, "rancher_url", "env")])
    no_proxy.extend(proxy.get("extra_no_proxy", []))
    proxy["no_proxy"] = no_proxy

    prompt = env.get("prompt") or {}
    env["prompt"] = prompt
    if prompt.get("host_suffix") not in (None, environment_id):
        raise SystemExit("env.prompt.host_suffix must match env.environment.id")
    prompt["host_suffix"] = environment_id
    colors = prompt.setdefault("colors", {})
    colors.setdefault("user", 183)
    colors.setdefault("at", 135)
    colors.setdefault("host", 129)
    colors.setdefault("path", 141)

    rancher = require(env, "rancher", "env")
    rancher.setdefault("edition", "community")
    rancher.setdefault("agent_tls_mode", "system-store")
    require(rancher, "cert_manager_version", "env.rancher")
    selected_edition = rancher["editions"][rancher["edition"]]
    selected_edition_context = f"env.rancher.editions.{rancher['edition']}"
    rancher["chart_repo_name"] = require(selected_edition, "repo_name", selected_edition_context)
    rancher["chart_repo_url"] = require(selected_edition, "repo_url", selected_edition_context)
    rancher["rancher_chart_version"] = require(selected_edition, "version", selected_edition_context)

    return env
