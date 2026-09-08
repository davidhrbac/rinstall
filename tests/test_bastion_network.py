from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import pytest
import yaml

from lib.bastion_network import (
    downstream_profile_actions,
    downstream_connection_needs_activation,
    load_downstream_network_output,
    normalize_ipv4_route,
    profile_rename_needed,
    route_device_is_active,
    route_needs_replacement,
    wait_for_device,
    wait_for_interface,
)
from lib.env_config import expand_env


ROOT = Path(__file__).parents[1]
EXAMPLE_ENV = ROOT / "envs/example/env.yaml"
TEMPLATES = ROOT / "pyinfra/templates"


def downstream_network(vlan=121):
    return {
        "vlan": vlan,
        "vmware_network": f"DOWNSTREAM_VLAN_{vlan}",
        "subnet": f"10.20.{vlan}.32/27",
        "bastion_address": 2,
        "gateway": 1,
        "dhcp": {"start": 4, "end": -2, "lease_time": "12h"},
    }


def config_with(*networks):
    config = yaml.safe_load(EXAMPLE_ENV.read_text())
    config["bastion"]["downstream_networks"] = list(networks)
    return expand_env(config)


def render_template(name, **data):
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return environment.get_template(name).render(**data)


def terraform_output(config, mac="00:50:56:aa:bb:cc"):
    network = config["bastion"]["downstream_networks"][0]
    return {
        "bastion_downstream_networks": {
            "value": {
                network["interface_name"]: {
                    "vlan": network["vlan"],
                    "vmware_network": network["vmware_network"],
                    "vmware_network_id": "network-121",
                    "mac_address": mac,
                    "nic_index": 2,
                    "attachment_order": 3,
                }
            }
        }
    }


def test_loads_synthetic_network_to_mac_output(tmp_path):
    import json

    config = config_with(downstream_network())
    output_path = tmp_path / "infra-output.json"
    output_path.write_text(json.dumps(terraform_output(config)))

    output = load_downstream_network_output(output_path, config["bastion"]["downstream_networks"])

    assert output["vlan121"]["mac_address"] == "00:50:56:aa:bb:cc"
    assert output["vlan121"]["vmware_network_id"] == "network-121"


def test_rejects_missing_or_removed_network_output(tmp_path):
    import json

    config = config_with(downstream_network())
    output_path = tmp_path / "infra-output.json"
    output_path.write_text(json.dumps({"bastion_downstream_networks": {"value": {}}}))
    with pytest.raises(SystemExit, match="run infra-apply"):
        load_downstream_network_output(output_path, config["bastion"]["downstream_networks"])

    output_path.write_text(json.dumps(terraform_output(config)))
    with pytest.raises(SystemExit, match="removal is not supported"):
        load_downstream_network_output(output_path, [])


def test_renders_persistent_mac_matched_kernel_name():
    rendered = render_template(
        "downstream-network.link.j2",
        mac_address="00:50:56:aa:bb:cc",
        interface_name="vlan121",
    )

    assert "MACAddress=00:50:56:aa:bb:cc" in rendered
    assert "Name=vlan121" in rendered


def test_renders_complete_networkmanager_profile_without_gateway():
    downstream = config_with(downstream_network())["bastion"]["downstream_networks"][0]
    rendered = render_template(
        "downstream-network.nmconnection.j2",
        downstream=downstream,
        mac_address="00:50:56:aa:bb:cc",
    )

    assert "type=ethernet" in rendered
    assert "interface-name=vlan121" in rendered
    assert "mac-address=00:50:56:aa:bb:cc" in rendered
    assert "address1=10.20.121.34/27" in rendered
    assert "never-default=true" in rendered
    assert "gateway=" not in rendered


def test_renders_interface_scoped_dhcp_without_dns_option():
    config = config_with(downstream_network())
    rendered = render_template("dnsmasq-dhcp.conf.j2", config=config)

    assert "dhcp-authoritative" in rendered
    assert "dhcp-ignore=tag:!vlan121" in rendered
    assert "dhcp-range=tag:vlan121,10.20.121.36,10.20.121.61,255.255.255.224,12h" in rendered
    assert "dhcp-option=tag:vlan121,option:router,10.20.121.33" in rendered
    assert "option:dns-server" not in rendered
    assert "option:6" not in rendered
    assert "interface=*" not in rendered


def test_omits_authoritative_dhcp_without_downstream_networks():
    rendered = render_template("dnsmasq-dhcp.conf.j2", config=config_with())

    assert "dhcp-authoritative" not in rendered
    assert "dhcp-range=" not in rendered


def test_route_comparison_skips_equal_normalized_route_and_replaces_changed_route():
    desired = "192.0.2.128/26 192.0.2.1"

    assert route_needs_replacement("  192.0.2.128/26   192.0.2.1\n", desired) is False
    assert route_needs_replacement("192.0.2.192/26 192.0.2.1", desired) is True
    assert route_needs_replacement("", desired) is True


def test_wait_for_device_discovers_immediately_without_sleeping():
    sleeps = []

    assert wait_for_device(
        "AA:BB:CC:DD:EE:FF",
        lambda: [("ens256", "aa:bb:cc:dd:ee:ff")],
        sleep=sleeps.append,
    ) == "ens256"
    assert sleeps == []


def test_wait_for_device_discovers_after_retries():
    snapshots = [[], [("ens256", "00:11:22:33:44:55")]]
    sleeps = []

    assert wait_for_device(
        "00:11:22:33:44:55",
        lambda: snapshots.pop(0),
        sleep=sleeps.append,
    ) == "ens256"
    assert sleeps == [1]


def test_wait_for_device_timeout_includes_visible_interfaces():
    with pytest.raises(SystemExit, match=r"visible interfaces: ens224 \(00:11:22:33:44:55\)"):
        wait_for_device(
            "00:11:22:33:44:66",
            lambda: [("ens224", "00:11:22:33:44:55")],
            timeout=0,
        )


def test_wait_for_device_rejects_duplicate_mac():
    with pytest.raises(SystemExit, match="matched multiple devices"):
        wait_for_device(
            "00:11:22:33:44:55",
            lambda: [("ens224", "00:11:22:33:44:55"), ("ens256", "00:11:22:33:44:55")],
        )


def test_wait_for_interface_retries_until_sysfs_and_networkmanager_match():
    states = [(None, False), (("00:11:22:33:44:55", False),), (("00:11:22:33:44:55", True),)]
    sleeps = []

    def state(_name):
        value = states.pop(0)
        return value[0] if isinstance(value, tuple) and len(value) == 1 else value

    wait_for_interface("vlan121", "00:11:22:33:44:55", state, sleep=sleeps.append)
    assert sleeps == [1, 1]


def test_wait_for_interface_timeout_is_clear():
    with pytest.raises(SystemExit, match="NetworkManager to recognize vlan121"):
        wait_for_interface("vlan121", "00:11:22:33:44:55", lambda _name: None, timeout=0)


def test_correct_interface_state_is_immediate_no_op():
    sleeps = []
    wait_for_interface(
        "vlan121",
        "00:11:22:33:44:55",
        lambda _name: ("00:11:22:33:44:55", True),
        sleep=sleeps.append,
    )
    assert sleeps == []


def test_active_autogenerated_profile_on_same_device_is_disabled_and_deactivated():
    actions = downstream_profile_actions(
        [
            {"uuid": "auto", "type": "802-3-ethernet", "device": "ens256", "mac_address": "", "autoconnect": "yes"},
            {"uuid": "managed", "type": "802-3-ethernet", "device": "ens256", "mac_address": "00:11:22:33:44:55", "autoconnect": "yes"},
        ],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert actions == {"disable": ["auto"], "deactivate": ["auto"]}


def test_inactive_competitor_with_expected_mac_is_only_disabled():
    actions = downstream_profile_actions(
        [{"uuid": "auto", "type": "ethernet", "device": "--", "mac_address": "00:11:22:33:44:55", "autoconnect": "yes"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert actions == {"disable": ["auto"], "deactivate": []}


def test_placeholder_metadata_still_uses_current_device_association():
    actions = downstream_profile_actions(
        [{"uuid": "auto", "type": "802-3-ethernet", "device": "ens256", "mac_address": "--", "autoconnect": "yes"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert actions == {"disable": ["auto"], "deactivate": ["auto"]}


def test_disconnected_profile_with_matching_interface_name_is_selected():
    actions = downstream_profile_actions(
        [{"uuid": "auto", "type": "802-3-ethernet", "device": "--", "interface_name": "ens256", "mac_address": "--", "autoconnect": "yes"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert actions == {"disable": ["auto"], "deactivate": []}


def test_interface_name_for_another_device_is_not_an_association():
    actions = downstream_profile_actions(
        [{"uuid": "auto", "type": "ethernet", "device": "--", "interface_name": "ens224", "mac_address": "--", "autoconnect": "yes"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert actions == {"disable": [], "deactivate": []}


def test_already_disabled_competitor_is_not_modified_again():
    actions = downstream_profile_actions(
        [{"uuid": "auto", "type": "ethernet", "device": "--", "mac_address": "00:11:22:33:44:55", "autoconnect": "no"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert actions == {"disable": [], "deactivate": []}


def test_unrelated_and_unproven_profiles_are_untouched():
    profiles = [
        {"uuid": "managed", "type": "ethernet", "device": "ens256", "mac_address": "00:11:22:33:44:55", "autoconnect": "yes"},
        {"uuid": "other-device", "type": "ethernet", "device": "ens224", "mac_address": "", "autoconnect": "yes"},
        {"uuid": "management", "type": "ethernet", "device": "ens224", "mac_address": "00:aa:bb:cc:dd:ee", "autoconnect": "yes"},
        {"uuid": "unknown", "type": "ethernet", "device": "--", "mac_address": "", "autoconnect": "yes"},
        {"uuid": "wifi", "type": "wifi", "device": "ens256", "mac_address": "", "autoconnect": "yes"},
    ]

    assert downstream_profile_actions(profiles, "managed", "00:11:22:33:44:55", ["ens256", "vlan565"]) == {
        "disable": [],
        "deactivate": [],
    }


def test_competing_profile_reconciliation_is_idempotent_after_first_run():
    first = downstream_profile_actions(
        [{"uuid": "auto", "type": "ethernet", "device": "ens256", "mac_address": "", "autoconnect": "yes"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )
    second = downstream_profile_actions(
        [{"uuid": "auto", "type": "ethernet", "device": "--", "mac_address": "", "autoconnect": "no"}],
        "managed",
        "00:11:22:33:44:55",
        ["ens256", "vlan565"],
    )

    assert first == {"disable": ["auto"], "deactivate": ["auto"]}
    assert second == {"disable": [], "deactivate": []}


def test_route_helpers_require_active_device_and_reject_default_route():
    assert route_device_is_active("ens224") is True
    assert route_device_is_active("--") is False
    assert route_device_is_active("") is False
    with pytest.raises(SystemExit, match="must not be a default route"):
        normalize_ipv4_route("0.0.0.0/0 192.0.2.1", "env.bastion.vsphere_route")


def test_dnsmasq_validation_is_after_backup_and_restores_on_failure():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    backup = deploy.index("Back up project-owned dnsmasq configuration")
    validation = deploy.index("Validate changed dnsmasq configuration")

    assert backup < validation
    assert "dnsmasq --test; status=$?;" in deploy
    assert "previous project-owned configuration restored" in deploy


def test_dnsmasq_restart_only_follows_successful_validation():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    validation = deploy.index("Validate changed dnsmasq configuration")
    restart = deploy.index("Restart dnsmasq after validated configuration change")

    assert validation < restart
    assert "_if=lambda: dnsmasq_validation.did_change()" in deploy


def test_route_replacement_preserves_unrelated_static_routes():
    from lib.bastion_network import reconcile_ipv4_routes

    current = "198.51.100.0/24 192.0.2.2, 192.0.2.128/26 192.0.2.9"

    assert reconcile_ipv4_routes(current, "192.0.2.128/26 192.0.2.1") == (
        "198.51.100.0/24 192.0.2.2, 192.0.2.128/26 192.0.2.1"
    )


def test_profile_rename_comparison_skips_identical_state_and_rejects_collision():
    assert profile_rename_needed("uuid-1", "uuid-1", "ens224", "mgmt") is False
    assert profile_rename_needed("uuid-1", "", "ens224", "mgmt") is True
    with pytest.raises(SystemExit, match="different connection"):
        profile_rename_needed("uuid-1", "uuid-2", "ens224", "mgmt")


def test_identical_downstream_connection_state_needs_no_activation():
    downstream = config_with(downstream_network())["bastion"]["downstream_networks"][0]
    current_addresses = "3: vlan121 inet 10.20.121.34/27 brd 10.20.121.63 scope global vlan121"

    assert (
        downstream_connection_needs_activation(
            downstream["connection_uuid"],
            current_addresses,
            downstream,
        )
        is False
    )
    assert downstream_connection_needs_activation("another-uuid", current_addresses, downstream) is True
