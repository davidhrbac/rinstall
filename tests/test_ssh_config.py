from pathlib import Path

import yaml

from lib.env_config import expand_env, load_env
from lib.ssh_config import render_admin_ssh_config, render_ssh_config


EXAMPLE_ENV = Path(__file__).parents[1] / "envs/example/env.yaml"


def raw_example():
    with EXAMPLE_ENV.open() as stream:
        return yaml.safe_load(stream)


def test_generated_ssh_config_uses_environment_aliases_and_management_ip():
    config = raw_example()
    config["nodes"]["bastion1"]["nics"][1]["cidr"] = "192.0.2.10/24"
    config = expand_env(config)

    rendered = render_ssh_config(config)

    assert "Host bastion1 bastion1.example 192.0.2.10" in rendered
    assert "  HostName 192.0.2.10" in rendered
    assert "Host rancher1 rancher1.example 10.14.17.11" in rendered
    assert "  StrictHostKeyChecking accept-new" in rendered


def test_admin_fragment_uses_bastion_proxy_for_local_nodes():
    config = load_env(EXAMPLE_ENV)

    rendered = render_admin_ssh_config(config)

    assert "Host bastion1.example\n  HostName 10.14.17.4" in rendered
    assert "Host prom1.example\n  HostName 10.14.17.6" in rendered
    assert "ProxyJump bastion1.example" in rendered
    assert "Include ~/.ssh/config" not in rendered


def test_generated_ssh_config_routes_nodes_through_configured_jump_host():
    config = load_env(EXAMPLE_ENV)
    config["ssh"]["jump_host"] = "admin-jump"

    rendered = render_ssh_config(config)

    assert "ProxyCommand ssh -F ~/.ssh/config -W %h:%p admin-jump" in rendered
    assert "ProxyCommand ssh -F ~/.ssh/config -i" in rendered
    assert "-J admin-jump -W %h:%p 10.14.17.4" in rendered
