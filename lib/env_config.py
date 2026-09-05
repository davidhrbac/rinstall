from copy import deepcopy
from ipaddress import ip_interface, ip_network
from pathlib import Path
import re
from urllib.parse import urlparse

import yaml


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
TERRAFORM_STATE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def require(mapping, key, context):
    if key not in mapping or mapping[key] is None:
        raise SystemExit(f"missing {context}.{key}")
    return mapping[key]


def gitlab_backend_state_address(backend):
    return f"{backend['url'].rstrip('/')}/api/v4/projects/{backend['project_id']}/terraform/state/{backend['state']}"


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

    return environment_id


def address_from_host(network, host, context):
    try:
        offset = int(host)
    except (TypeError, ValueError):
        raise SystemExit(f"{context} must be an integer host offset") from None

    if offset < 0 or offset >= network.num_addresses:
        raise SystemExit(f"{context}={offset} is outside {network}")

    address = network.network_address + offset
    if address == network.network_address:
        raise SystemExit(f"{context}={offset} resolves to network address {address}")
    if address == network.broadcast_address:
        raise SystemExit(f"{context}={offset} resolves to broadcast address {address}")

    return str(address)


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
    url = require(backend, "url", "env.terraform.backend")
    parsed_url = urlparse(str(url))
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
    state = require(backend, "state", "env.terraform.backend")
    if not isinstance(state, str) or not TERRAFORM_STATE_PATTERN.fullmatch(state):
        raise SystemExit(
            "env.terraform.backend.state must contain only letters, digits, dots, hyphens, and underscores"
        )

    infra = require(env, "infra", "env")
    networks = require(infra, "networks", "env.infra")
    templates = require(infra, "templates", "env.infra")
    local_vlan = require(require(env, "local", "env"), "vlan", "env.local")
    nodes = require(env, "nodes", "env")

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

    for dns_node in local_vlan.get("dns_nodes", [service_node]):
        validate_name_exists(dns_node, nodes, "env.local.vlan.dns_nodes")

    validate_role(
        service_node,
        nodes,
        "bastion",
        "env.bastion.service_node",
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

    prefix = rancher_pool.get("name_prefix", "rancher")
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
    with Path(path).open() as stream:
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

    bastion = require(env, "bastion", "env")
    bastion.setdefault("squid_http_port", 3128)
    bastion_name = require(bastion, "service_node", "env.bastion")
    route_connection = require(bastion, "vsphere_route_connection", "env.bastion")
    management_interfaces = [
        source
        for source, target in bastion.get("network_connection_names", {}).items()
        if target == route_connection
    ]
    if len(management_interfaces) > 1:
        raise SystemExit(
            "env.bastion.network_connection_names maps multiple devices to "
            "env.bastion.vsphere_route_connection"
        )
    bastion["management_interface"] = management_interfaces[0] if management_interfaces else route_connection
    bastion["dnsmasq_upstream_servers"] = require(
        bastion, "dnsmasq_upstream_servers", "env.bastion"
    )
    if (
        not isinstance(bastion["dnsmasq_upstream_servers"], list)
        or not bastion["dnsmasq_upstream_servers"]
        or not all(isinstance(server, str) and server for server in bastion["dnsmasq_upstream_servers"])
    ):
        raise SystemExit("env.bastion.dnsmasq_upstream_servers must be a non-empty list of DNS servers")
    bastion_dns_servers = require(nodes[bastion_name], "dns_servers", f"env.nodes.{bastion_name}")
    if (
        not isinstance(bastion_dns_servers, list)
        or not bastion_dns_servers
        or not all(isinstance(server, str) and server for server in bastion_dns_servers)
    ):
        raise SystemExit(f"env.nodes.{bastion_name}.dns_servers must be a non-empty list of DNS servers")
    dns_nodes = local_vlan.setdefault("dns_nodes", [bastion_name])
    local_vlan["dns_servers"] = [nodes[name]["ip"] for name in dns_nodes]

    if bastion.get("service_ip") is None:
        bastion["service_ip"] = nodes[bastion_name]["ip"]

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
