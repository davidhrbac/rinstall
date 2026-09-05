from pathlib import Path
import os
import subprocess
import sys

import pytest
import yaml

from lib.env_config import expand_env, load_env


EXAMPLE_ENV = Path(__file__).parents[1] / "envs/example/env.yaml"
BACKEND_HELPER = EXAMPLE_ENV.parents[2] / "scripts/terraform-backend-env.py"


def raw_example():
    with EXAMPLE_ENV.open() as stream:
        return yaml.safe_load(stream)


def test_example_resolves_component_versions_and_local_addresses():
    config = load_env(EXAMPLE_ENV)

    assert config["rke2"]["version"] == "v1.35.7+rke2r1"
    assert config["rancher"]["cert_manager_version"] == "v1.21.1"
    assert config["rancher"]["rancher_chart_version"] == "2.14.4"
    assert config["local_vlan"]["gateway"] == "10.14.17.1"
    assert config["nodes"]["bastion1"]["ip"] == "10.14.17.4"
    assert config["nodes"]["rancher3"]["ip"] == "10.14.17.13"


def test_environment_id_is_required_and_drives_prompt_suffix():
    missing_id = raw_example()
    del missing_id["environment"]["id"]

    with pytest.raises(SystemExit, match="missing env.environment.id"):
        expand_env(missing_id)

    config = raw_example()
    config["environment"]["id"] = "customer-prod"
    resolved = expand_env(config)

    assert resolved["prompt"]["host_suffix"] == "customer-prod"


def test_rejects_unsupported_schema_and_invalid_environment_id():
    unsupported_schema = raw_example()
    unsupported_schema["schema_version"] = 2

    with pytest.raises(SystemExit, match="env.schema_version must be 1"):
        expand_env(unsupported_schema)

    invalid_id = raw_example()
    invalid_id["environment"]["id"] = "Customer Prod"

    with pytest.raises(SystemExit, match="env.environment.id must contain"):
        expand_env(invalid_id)


@pytest.mark.parametrize(
    ("host", "message"),
    [
        (0, "network address"),
        (15, "broadcast address"),
        (16, "outside"),
    ],
)
def test_rejects_invalid_local_node_host_offsets(host, message):
    config = raw_example()
    config["nodes"]["prom1"]["host"] = host

    with pytest.raises(SystemExit, match=message):
        expand_env(config)


def test_expands_rancher_pool_and_uses_first_node_as_primary():
    config = raw_example()
    resolved = expand_env(config)

    assert [name for name in resolved["nodes"] if name.startswith("rancher")] == [
        "rancher1",
        "rancher2",
        "rancher3",
    ]
    assert resolved["rke2"]["primary_node"] == "rancher1"
    assert resolved["nodes"]["rancher2"]["rke2_server"] == "https://10.14.17.11:9345"


def test_rejects_unknown_network_template_and_primary_node_role():
    unknown_network = raw_example()
    unknown_network["nodes"]["prom1"]["nics"][0]["network"] = "missing"

    with pytest.raises(SystemExit, match="references unknown name: missing"):
        expand_env(unknown_network)

    unknown_template = raw_example()
    unknown_template["nodes"]["prom1"]["template"] = "missing"

    with pytest.raises(SystemExit, match="references unknown name: missing"):
        expand_env(unknown_template)

    invalid_primary = raw_example()
    invalid_primary["rke2"] = {"primary_node": "prom1", "version": "v1.35.7+rke2r1"}

    with pytest.raises(SystemExit, match="expected 'rancher'"):
        expand_env(invalid_primary)


def test_keeps_bastion_and_client_dns_separate():
    config = load_env(EXAMPLE_ENV)

    assert config["nodes"]["bastion1"]["dns_servers"] == ["192.0.2.53"]
    assert config["local_vlan"]["dns_servers"] == ["10.14.17.4"]
    assert config["bastion"]["dnsmasq_upstream_servers"] == ["192.0.2.54"]


def test_derives_management_ssh_ip_from_static_management_nic():
    config = raw_example()
    config["nodes"]["bastion1"]["nics"][1]["cidr"] = "192.0.2.10/24"

    resolved = expand_env(config)

    assert resolved["nodes"]["bastion1"]["ssh_ip"] == "192.0.2.10"


def test_resolves_renamed_management_profile_to_its_device():
    config = raw_example()
    config["bastion"]["network_connection_names"] = {"ens224": "mgmt"}
    config["bastion"]["vsphere_route_connection"] = "mgmt"

    resolved = expand_env(config)

    assert resolved["bastion"]["management_interface"] == "ens224"


def test_resolves_selected_rancher_edition_and_requires_versions():
    prime = raw_example()
    prime["rancher"]["edition"] = "prime"
    resolved = expand_env(prime)

    assert resolved["rancher"]["chart_repo_name"] == "rancher-prime"
    assert resolved["rancher"]["rancher_chart_version"] == "2.14.4"

    missing_cert_manager = raw_example()
    del missing_cert_manager["rancher"]["cert_manager_version"]
    with pytest.raises(SystemExit, match="missing env.rancher.cert_manager_version"):
        expand_env(missing_cert_manager)

    missing_rancher_version = raw_example()
    del missing_rancher_version["rancher"]["editions"]["community"]["version"]
    with pytest.raises(SystemExit, match="missing env.rancher.editions.community.version"):
        expand_env(missing_rancher_version)


def test_generates_compact_no_proxy_list_with_kubernetes_suffixes():
    config = load_env(EXAMPLE_ENV)

    assert config["proxy"]["no_proxy"] == [
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "cattle-system.svc",
        ".svc",
        ".cluster.local",
        "10.14.17.0/28",
        "rancher.example.internal",
    ]


def test_validates_gitlab_backend_without_credentials():
    config = raw_example()
    config["terraform"] = {"backend": {"type": "gitlab", "url": "https://gitlab.example", "project_id": 1234, "state": "infra"}}
    assert expand_env(config)["terraform"]["backend"]["project_id"] == 1234


@pytest.mark.parametrize("missing", ["terraform", "backend", "type", "url", "project_id", "state"])
def test_rejects_missing_required_gitlab_backend_configuration(missing):
    config = raw_example()
    config["terraform"] = {"backend": {"type": "gitlab", "url": "https://gitlab.example", "project_id": 1234, "state": "infra"}}
    if missing == "terraform":
        del config["terraform"]
    elif missing == "backend":
        del config["terraform"]["backend"]
    else:
        del config["terraform"]["backend"][missing]
    with pytest.raises(SystemExit):
        expand_env(config)


@pytest.mark.parametrize("url", ["http://gitlab.example", "https://gitlab.example/"])
@pytest.mark.parametrize("state", ["infra", "prod_state-1.v2"])
def test_accepts_valid_gitlab_backend_url_and_state(url, state):
    config = raw_example()
    config["terraform"] = {
        "backend": {"type": "gitlab", "url": url, "project_id": 1234, "state": state}
    }
    assert expand_env(config)["terraform"]["backend"]["state"] == state


@pytest.mark.parametrize("backend", [
    {"type": "s3"},
    {"type": "gitlab", "url": "", "project_id": 1, "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example", "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example", "project_id": "bad", "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example", "project_id": 1, "state": ""},
    {"type": "gitlab", "url": "ftp://gitlab.example", "project_id": 1, "state": "infra"},
    {"type": "gitlab", "url": "https:///missing-host", "project_id": 1, "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example?project=1", "project_id": 1, "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example#state", "project_id": 1, "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example/gitlab", "project_id": 1, "state": "infra"},
    {"type": "gitlab", "url": "https://gitlab.example", "project_id": 1, "state": "/"},
    {"type": "gitlab", "url": "https://gitlab.example", "project_id": 1, "state": "prod/state"},
    {"type": "gitlab", "url": "https://gitlab.example", "project_id": 1, "state": "prod state"},
])
def test_rejects_invalid_gitlab_backend(backend):
    config = raw_example()
    config["terraform"] = {"backend": backend}
    with pytest.raises(SystemExit):
        expand_env(config)


def test_derives_gitlab_backend_values_without_credentials(tmp_path):
    config = raw_example()
    config["terraform"] = {
        "backend": {
            "type": "gitlab",
            "url": "https://gitlab.example",
            "project_id": 1234,
            "state": "infra",
        }
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))

    result = subprocess.run(
        [sys.executable, str(BACKEND_HELPER), "--env", str(config_path)],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TF_HTTP_ADDRESS": "https://conflicting.example/state",
            "TF_HTTP_LOCK_ADDRESS": "https://conflicting.example/lock",
            "TF_HTTP_USERNAME": "runtime-user",
            "TF_HTTP_PASSWORD": "runtime-secret",
        },
    )

    assert result.stdout.strip().split() == [
        "TF_HTTP_ADDRESS=https://gitlab.example/api/v4/projects/1234/terraform/state/infra",
        "TF_HTTP_LOCK_ADDRESS=https://gitlab.example/api/v4/projects/1234/terraform/state/infra/lock",
        "TF_HTTP_UNLOCK_ADDRESS=https://gitlab.example/api/v4/projects/1234/terraform/state/infra/lock",
        "TF_HTTP_LOCK_METHOD=POST",
        "TF_HTTP_UNLOCK_METHOD=DELETE",
        "TF_HTTP_RETRY_WAIT_MIN=5",
    ]
    assert "runtime-user" not in result.stdout
    assert "runtime-secret" not in result.stdout
