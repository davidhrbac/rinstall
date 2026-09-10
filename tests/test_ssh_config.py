from copy import deepcopy
import os
from pathlib import Path

import yaml

from lib.env_config import expand_env, load_env
from lib.ssh_config import (
    node_proxy_command,
    node_ssh_hops,
    node_ssh_target,
    render_admin_ssh_config,
    render_ssh_config,
    write_ssh_config,
)


EXAMPLE_ENV = Path(__file__).parents[1] / "envs/example/env.yaml"


def raw_example():
    with EXAMPLE_ENV.open() as stream:
        return yaml.safe_load(stream)


def legacy_node_proxy_command(config, node_name, node, known_hosts_file=None):
    """Exact node_proxy_command implementation before node_ssh_hops extraction."""
    ssh = config.get("ssh", {})
    jump_host = ssh.get("jump_host")
    if not jump_host:
        return None

    jump_alias = (
        jump_host
        if isinstance(jump_host, str)
        else jump_host.get("alias", "rancher-env-jump")
    )
    bastion_name = config["bastion"]["service_node"]
    bastion_proxy_roles = set(ssh.get("bastion_proxy_roles", []))
    if node["role"] not in bastion_proxy_roles or node_name == bastion_name:
        hops = str(jump_alias).split(",")
        if len(hops) == 1:
            return f"ssh -F ~/.ssh/config -W %h:%p {hops[0]}"
        return (
            f"ssh -F ~/.ssh/config -J {','.join(hops[:-1])} "
            f"-W %h:%p {hops[-1]}"
        )

    bastion_node = config["nodes"][bastion_name]
    bastion_ssh_target = node_ssh_target(bastion_node)
    ssh_user = ssh.get("user", "root")
    ssh_key = os.path.expanduser(ssh.get("private_key", "~/.ssh/id_rsa"))
    host_key_options = ""
    if known_hosts_file:
        host_key_options = (
            f" -o UserKnownHostsFile={known_hosts_file}"
            " -o GlobalKnownHostsFile=/dev/null"
            " -o StrictHostKeyChecking=accept-new"
        )
    return (
        f"ssh -F ~/.ssh/config{host_key_options} -i {ssh_key} -l {ssh_user} "
        f"-J {jump_alias} -W %h:%p {bastion_ssh_target}"
    )


def test_generated_ssh_config_uses_environment_aliases_and_management_ip(tmp_path):
    config = raw_example()
    config["nodes"]["bastion1"]["nics"][1]["cidr"] = "192.0.2.10/24"
    config = expand_env(config)

    known_hosts = tmp_path / "runtime" / "known_hosts"
    rendered = render_ssh_config(config, known_hosts)

    assert "Host bastion1 bastion1.example 192.0.2.10" in rendered
    assert "  HostName 192.0.2.10" in rendered
    assert "Host rancher1 rancher1.example 10.14.17.11" in rendered
    assert f"  UserKnownHostsFile {known_hosts}" in rendered
    assert "  GlobalKnownHostsFile /dev/null" in rendered
    assert "  StrictHostKeyChecking accept-new" in rendered
    assert "HostKeyAlias" not in rendered


def test_admin_fragment_uses_bastion_proxy_for_local_nodes():
    config = load_env(EXAMPLE_ENV)

    rendered = render_admin_ssh_config(config)

    assert "Host bastion1.example\n  HostName 10.14.17.4" in rendered
    assert "Host prom1.example\n  HostName 10.14.17.6" in rendered
    assert "ProxyJump bastion1.example" in rendered
    assert "Include ~/.ssh/config" not in rendered


def test_ssh_config_uses_configured_bastion_service_node():
    config = raw_example()
    config["nodes"]["bastion2"] = config["nodes"].pop("bastion1")
    config["nodes"]["prom2"] = config["nodes"].pop("prom1")
    config["bastion"]["service_node"] = "bastion2"
    config = expand_env(config)

    assert config["bastion"]["service_ip"] == config["nodes"]["bastion2"]["ip"]
    assert config["local"]["vlan"]["dns_nodes"] == ["bastion2"]
    assert config["nodes"]["bastion2"]["dns_servers"] == ["192.0.2.53"]
    rendered = render_ssh_config(config)

    assert "Host bastion2 bastion2.example" in rendered
    assert "Host prom2 prom2.example" in rendered
    assert "bastion1" not in rendered
    assert "prom1" not in rendered


def test_generated_ssh_config_routes_nodes_through_configured_jump_host(tmp_path):
    config = load_env(EXAMPLE_ENV)
    config["ssh"]["jump_host"] = "admin-jump"

    known_hosts = tmp_path / "known_hosts"
    rendered = render_ssh_config(config, known_hosts)

    assert "  ProxyCommand ssh -F ~/.ssh/config -W %h:%p admin-jump\n" in rendered
    assert f"ProxyCommand ssh -F ~/.ssh/config -o UserKnownHostsFile={known_hosts} -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new -i" in rendered
    assert "-J admin-jump -W %h:%p 10.14.17.4" in rendered

    assert "Host admin-jump" not in rendered
    assert "UserKnownHostsFile" not in render_admin_ssh_config(config)
    assert node_ssh_hops(config, "bastion1", config["nodes"]["bastion1"]) == (
        "admin-jump",
    )
    assert node_ssh_hops(config, "prom1", config["nodes"]["prom1"]) == (
        "admin-jump",
        "bastion1",
    )
    assert node_ssh_hops(config, "rancher1", config["nodes"]["rancher1"]) == (
        "admin-jump",
        "bastion1",
    )


def test_node_ssh_hops_extraction_preserves_every_legacy_proxy_command_case(tmp_path):
    base = load_env(EXAMPLE_ENV)
    jump_hosts = (
        None,
        "",
        "admin-jump",
        "edge-jump,admin-jump",
        {"alias": "structured-jump", "hostname": "jump.example.invalid"},
        {"hostname": "jump.example.invalid"},
    )
    proxy_role_sets = (
        (),
        ("rancher",),
        ("prometheus", "rancher"),
        ("bastion", "prometheus", "rancher"),
    )
    known_hosts_values = (None, tmp_path / "known_hosts")
    credentials = (
        (None, None),
        ("support-user", "~/keys/support_rsa"),
    )
    comparisons = 0

    for jump_host in jump_hosts:
        for proxy_roles in proxy_role_sets:
            for known_hosts in known_hosts_values:
                for ssh_user, private_key in credentials:
                    config = deepcopy(base)
                    config["ssh"]["jump_host"] = deepcopy(jump_host)
                    config["ssh"]["bastion_proxy_roles"] = list(proxy_roles)
                    if ssh_user is None:
                        config["ssh"].pop("user", None)
                        config["ssh"].pop("private_key", None)
                    else:
                        config["ssh"]["user"] = ssh_user
                        config["ssh"]["private_key"] = private_key

                    for node_name, node in config["nodes"].items():
                        expected = legacy_node_proxy_command(
                            config, node_name, node, known_hosts
                        )
                        actual = node_proxy_command(config, node_name, node, known_hosts)
                        assert actual == expected
                        comparisons += 1

    config_without_ssh = deepcopy(base)
    config_without_ssh.pop("ssh")
    for node_name, node in config_without_ssh["nodes"].items():
        assert node_proxy_command(config_without_ssh, node_name, node) is None
        assert legacy_node_proxy_command(config_without_ssh, node_name, node) is None
        comparisons += 1

    assert comparisons == 485


def test_write_ssh_config_creates_private_runtime_known_hosts(tmp_path):
    config = load_env(EXAMPLE_ENV)
    runtime = tmp_path / ".rinstall"

    output = write_ssh_config(config, runtime / "ssh_config")

    known_hosts = runtime / "known_hosts"
    assert output.exists()
    assert known_hosts.exists()
    assert known_hosts.stat().st_mode & 0o777 == 0o600
    assert f"UserKnownHostsFile {known_hosts.resolve()}" in output.read_text()
