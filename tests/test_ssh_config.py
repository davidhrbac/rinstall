from pathlib import Path

import yaml

from lib.env_config import expand_env, load_env
from lib.ssh_config import render_admin_ssh_config, render_ssh_config, write_ssh_config


EXAMPLE_ENV = Path(__file__).parents[1] / "envs/example/env.yaml"


def raw_example():
    with EXAMPLE_ENV.open() as stream:
        return yaml.safe_load(stream)


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


def test_write_ssh_config_creates_private_runtime_known_hosts(tmp_path):
    config = load_env(EXAMPLE_ENV)
    runtime = tmp_path / ".rinstall"

    output = write_ssh_config(config, runtime / "ssh_config")

    known_hosts = runtime / "known_hosts"
    assert output.exists()
    assert known_hosts.exists()
    assert known_hosts.stat().st_mode & 0o777 == 0o600
    assert f"UserKnownHostsFile {known_hosts.resolve()}" in output.read_text()
