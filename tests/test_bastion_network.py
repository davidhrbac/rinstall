from pathlib import Path
import re
import subprocess

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import pytest
import yaml

from lib.bastion_network import (
    dhcp_excluded_interfaces,
    downstream_profile_actions,
    downstream_connection_needs_activation,
    dnsmasq_effective_config_changed,
    dnsmasq_recovery_command,
    load_downstream_network_output,
    normalize_ipv4_route,
    profile_rename_needed,
    route_device_is_active,
    route_needs_replacement,
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


def test_renders_complete_networkmanager_profile_without_gateway():
    downstream = config_with(downstream_network())["bastion"]["downstream_networks"][0]
    rendered = render_template(
        "downstream-network.nmconnection.j2",
        downstream=downstream,
        mac_address="00:50:56:aa:bb:cc",
        device_name="ens256",
    )

    assert "type=ethernet" in rendered
    assert "id=vlan121" in rendered
    assert "interface-name=ens256" in rendered
    assert "mac-address=00:50:56:aa:bb:cc" in rendered
    assert "address1=10.20.121.34/27" in rendered
    assert "never-default=true" in rendered
    assert "gateway=" not in rendered


def test_renders_tagged_dhcp_range_without_dns_option():
    config = config_with(downstream_network())
    network = config["bastion"]["downstream_networks"][0]
    network["device_name"] = "ens256"
    rendered = render_template("dnsmasq-dhcp.conf.j2", config=config, network=network)

    assert "dhcp-range=set:vlan121,10.20.121.36,10.20.121.61,255.255.255.224,12h" in rendered
    assert "dhcp-option=tag:vlan121,option:router,10.20.121.33" in rendered
    assert "bind-dynamic" not in rendered
    assert "dhcp-authoritative" not in rendered
    assert "no-dhcp-interface" not in rendered
    assert "option:dns-server" not in rendered
    assert "option:6" not in rendered
    assert "dhcp-ignore=" not in rendered


def test_multiple_downstream_dhcp_files_use_logical_vlan_tags():
    config = config_with(downstream_network(121), downstream_network(122))
    networks = config["bastion"]["downstream_networks"]
    networks[0]["device_name"] = "ens256"
    networks[1]["device_name"] = "ens257"

    first = render_template("dnsmasq-dhcp.conf.j2", config=config, network=networks[0])
    second = render_template("dnsmasq-dhcp.conf.j2", config=config, network=networks[1])

    assert "dhcp-range=set:vlan121," in first
    assert "dhcp-range=set:vlan122," in second
    assert "vlan122" not in first
    assert "vlan121" not in second
    assert "ens256" not in first
    assert "ens257" not in second


def test_renders_common_dhcp_policy_for_non_downstream_interfaces():
    rendered = render_template(
        "dnsmasq-dhcp-policy.conf.j2",
        excluded_interfaces=["ens192", "ens224"],
    )

    assert "bind-dynamic" in rendered
    assert "dhcp-authoritative" in rendered
    assert "no-dhcp-interface=ens192" in rendered
    assert "no-dhcp-interface=ens224" in rendered


def test_excludes_base_and_management_interfaces_without_hard_coded_names():
    assert dhcp_excluded_interfaces(
        "customer0:ethernet\nmgmt0:802-3-ethernet\nens256:ethernet\nvlan565:vlan\n",
        ["ens256"],
    ) == ["customer0", "mgmt0"]


def test_project_owned_dnsmasq_files_are_separate_from_manual_files():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()

    assert "/etc/dnsmasq.d/20-rinstall-dhcp.conf" in deploy
    assert "dnsmasq-vlan*.conf" in deploy
    assert "dnsmasq-ens256.conf" not in deploy
    assert deploy.count("/etc/dnsmasq.d/20-rinstall-dhcp.conf") >= 2


@pytest.mark.parametrize("filenames", [[], ["dnsmasq-vlan565.conf"], ["dnsmasq-vlan565.conf", "dnsmasq-vlan566.conf"]])
def test_dnsmasq_vlan_discovery_handles_empty_and_multiple_matches(tmp_path, filenames):
    config_dir = tmp_path / "dnsmasq.d"
    config_dir.mkdir()
    for filename in filenames:
        (config_dir / filename).write_text("")

    command = (
        "for path in /etc/dnsmasq.d/dnsmasq-vlan*.conf; do "
        "if [ -e \"$path\" ]; then printf '%s\\n' \"$path\"; fi; done"
    ).replace("/etc/dnsmasq.d", str(config_dir))
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [str(config_dir / filename) for filename in filenames]


def test_current_common_policy_is_not_an_obsolete_cleanup_target():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    cleanup_start = deploy.index("obsolete_dhcp_configs.append")
    cleanup_end = deploy.index("    for downstream in config", cleanup_start)
    cleanup = deploy[cleanup_start:cleanup_end]

    assert "20-local-dhcp.conf" in cleanup
    assert "20-rinstall-dhcp.conf" not in cleanup


def test_rendering_same_common_policy_twice_is_byte_identical():
    first = render_template(
        "dnsmasq-dhcp-policy.conf.j2",
        excluded_interfaces=["customer0", "mgmt0"],
    )
    second = render_template(
        "dnsmasq-dhcp-policy.conf.j2",
        excluded_interfaces=["customer0", "mgmt0"],
    )

    assert first == second


def test_common_dhcp_policy_is_rendered_once_for_multiple_vlans():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()

    assert deploy.count('name="Render common dnsmasq DHCP policy"') == 1
    assert deploy.count("src=str(ENGINE_ROOT / \"pyinfra/templates/dnsmasq-dhcp-policy.conf.j2\")") == 1


def test_downstream_runtime_keeps_real_device_names_without_kernel_rename():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()

    assert not (ROOT / "pyinfra/templates/downstream-network.link.j2").exists()
    assert "ip link set" not in deploy
    assert "udevadm control --reload" not in deploy
    assert "Set kernel interface name" not in deploy
    assert "Wait for NetworkManager to recognize" not in deploy
    assert "ifname {shlex.quote(device)}" in deploy


def test_downstream_networkmanager_no_auto_default_is_reloaded_idempotently():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()

    assert "no-auto-default=*" in deploy
    assert "/etc/NetworkManager/conf.d/10-rinstall-no-auto-default.conf" in deploy
    assert "nmcli general reload conf" in deploy
    assert "_if=no_auto_default.did_change" in deploy


def test_route_comparison_skips_equal_normalized_route_and_replaces_changed_route():
    desired = "192.0.2.128/26 192.0.2.1"

    assert route_needs_replacement("  192.0.2.128/26   192.0.2.1\n", desired) is False
    assert route_needs_replacement("192.0.2.192/26 192.0.2.1", desired) is True
    assert route_needs_replacement("", desired) is True


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


def test_dnsmasq_candidate_is_staged_and_validated_before_install():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    candidate = deploy.index("Prepare complete dnsmasq candidate")
    validation = deploy.index("Validate changed dnsmasq configuration")
    install = deploy.index("Install validated dnsmasq configuration and restart service")

    assert candidate < validation < install
    assert "dnsmasq --test --conf-file={dnsmasq_candidate_dir}/dnsmasq.conf $hosts_args" in deploy
    assert "live configuration was not changed" in deploy


def test_dnsmasq_recovery_precedes_candidate_staging_and_records_completion():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    recovery = deploy.index("Recover interrupted dnsmasq transaction")
    candidate = deploy.index("Prepare complete dnsmasq candidate")
    install = deploy.index("Install validated dnsmasq configuration and restart service")

    assert recovery < candidate < install
    assert "dnsmasq_recovery_command(dnsmasq_rollback_dir)" in deploy
    assert "service.active" in deploy
    assert "service.enabled" in deploy
    assert ": > {dnsmasq_rollback_dir}/ready" in deploy


def test_dnsmasq_recovery_restores_known_good_state_and_restarts_service(tmp_path):
    config_root = tmp_path / "etc"
    dropin_dir = config_root / "dnsmasq.d"
    rollback_dir = tmp_path / "rollback"
    dropin_dir.mkdir(parents=True)
    rollback_dir.mkdir()

    (config_root / "dnsmasq.conf").write_text("new")
    (config_root / "hosts").write_text("new")
    (dropin_dir / "10-rancher-local.conf").write_text("new")
    (dropin_dir / "dnsmasq-vlan565.conf").write_text("new")
    (rollback_dir / "dnsmasq.conf").write_text("old")
    (rollback_dir / "hosts").write_text("old")
    (rollback_dir / "10-rancher-local.conf").write_text("old")
    (rollback_dir / "20-local-dhcp.conf.absent").write_text("")
    (rollback_dir / "20-rinstall-dhcp.conf.absent").write_text("")
    (rollback_dir / "dhcp").mkdir()
    (rollback_dir / "dhcp" / "dnsmasq-vlan565.conf").write_text("old")
    (rollback_dir / "service.active").write_text("1\n")
    (rollback_dir / "service.enabled").write_text("1\n")
    (rollback_dir / "ready").write_text("")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "systemctl.log"
    (bin_dir / "systemctl").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
    (bin_dir / "systemctl").chmod(0o700)

    result = subprocess.run(
        ["bash", "-c", dnsmasq_recovery_command(rollback_dir, config_root)],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (config_root / "dnsmasq.conf").read_text() == "old"
    assert (config_root / "hosts").read_text() == "old"
    assert (dropin_dir / "10-rancher-local.conf").read_text() == "old"
    assert (dropin_dir / "dnsmasq-vlan565.conf").read_text() == "old"
    assert log.read_text().splitlines() == ["restart dnsmasq", "enable dnsmasq"]
    assert not rollback_dir.exists()


def test_dnsmasq_recovery_discards_pre_install_state_without_restart(tmp_path):
    config_root = tmp_path / "etc"
    config_root.mkdir()
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    (rollback_dir / "partial").write_text("not ready")

    result = subprocess.run(
        ["bash", "-c", dnsmasq_recovery_command(rollback_dir, config_root)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not rollback_dir.exists()
    assert "systemctl" not in result.stdout


def test_dnsmasq_recovery_without_pending_state_does_not_restart(tmp_path):
    config_root = tmp_path / "etc"
    config_root.mkdir()
    rollback_dir = tmp_path / "rollback"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "systemctl.log"
    (bin_dir / "systemctl").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
    (bin_dir / "systemctl").chmod(0o700)

    result = subprocess.run(
        ["bash", "-c", dnsmasq_recovery_command(rollback_dir, config_root)],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists()


def test_dnsmasq_candidate_includes_manual_dropins_and_hosts():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    route = deploy.index("Configure vSphere route")
    candidate = deploy.index("Prepare complete dnsmasq candidate")
    validation = deploy.index("Validate changed dnsmasq configuration")

    assert route < candidate < validation
    assert "cp -a /etc/hosts {dnsmasq_candidate_dir}/hosts" in deploy
    assert "cp -a /etc/dnsmasq.d/. {dnsmasq_candidate_dir}/dnsmasq.d/" in deploy
    assert "--no-hosts --addn-hosts={dnsmasq_candidate_dir}/hosts" in deploy
    assert "conf-dir=/etc/dnsmasq.d" not in deploy[deploy.index("Prepare complete dnsmasq candidate") : validation]


def test_dnsmasq_live_replacements_are_atomic_and_same_directory():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    install = deploy[deploy.index("Install validated dnsmasq configuration and restart service") : deploy.index("Discard unchanged dnsmasq candidate")]

    assert 'tmp=$(mktemp --tmpdir=\\"$dir\\" .rinstall-dnsmasq.XXXXXX)' in install
    assert 'cp -a -- \\"$src\\" \\"$tmp\\"' in install
    assert 'mv -f -- \\"$tmp\\" \\"$dest\\"' in install
    assert 'sync -f \\"$tmp\\"' in install
    assert 'sync -f \\"$dir\\"' in install
    assert 'cp -a {dnsmasq_candidate_dir}/dnsmasq.conf /etc/dnsmasq.conf' not in install
    assert 'cp -a {dnsmasq_candidate_dir}/hosts /etc/hosts' not in install


def test_dnsmasq_rollback_uses_atomic_replacements_and_preserves_selinux_context():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    install = deploy[deploy.index("Install validated dnsmasq configuration and restart service") : deploy.index("Discard unchanged dnsmasq candidate")]

    assert install.count("atomic_replace ") >= 6
    assert "chcon --reference=\\\"$dest\\\" \\\"$tmp\\\"" in install
    assert "restorecon -F \\\"$tmp\\\"" in install
    assert "systemctl restart dnsmasq || true" in install


def test_dnsmasq_restart_failure_restores_live_config_and_service_state():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    install = deploy.index("Install validated dnsmasq configuration and restart service")
    failure = deploy.index("if ! systemctl enable dnsmasq || ! systemctl start dnsmasq || ! systemctl restart dnsmasq; then")
    restore = deploy.index("rollback()")

    assert install < restore < failure
    assert "was_active=0; if systemctl is-active --quiet dnsmasq; then was_active=1; fi" in deploy
    assert "systemctl restart dnsmasq || true; else systemctl stop dnsmasq || true" in deploy
    assert "systemctl enable dnsmasq || true; else systemctl disable dnsmasq || true" in deploy
    assert '_if=lambda: not dnsmasq_effective_config_changed(dnsmasq_effective_changes)' in deploy


def test_dnsmasq_restart_only_follows_successful_validation():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    validation = deploy.index("Validate changed dnsmasq configuration")
    install = deploy.index("Install validated dnsmasq configuration and restart service")

    assert validation < install
    assert "dnsmasq_effective_config_changed(dnsmasq_effective_changes)" in deploy
    assert "and dnsmasq_validation.did_change()" in deploy


def test_dnsmasq_candidate_cleanup_has_no_persistent_transaction_marker():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    assert "dnsmasq_pending_restart" not in deploy
    assert ".validated" not in deploy
    assert "/var/lib" not in deploy[deploy.index("if phase == \"bastion\" and role == \"bastion\":") : deploy.index("if phase == \"node-prep\":")]
    assert "Discard unchanged dnsmasq candidate" in deploy


def test_dnsmasq_backup_is_not_an_effective_configuration_change():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    effective_changes = deploy[deploy.index("dnsmasq_effective_changes.extend") : deploy.index("dnsmasq_validation =")]

    assert "Prepare complete dnsmasq candidate" not in effective_changes
    assert "dnsmasq_binding" in effective_changes
    assert "dnsmasq_local_config" in effective_changes
    assert "obsolete_dhcp_configs" in effective_changes
    assert "dnsmasq_dhcp_configs" in effective_changes
    assert "dnsmasq_effective_config_changed(dnsmasq_effective_changes)" in deploy


def test_dnsmasq_real_change_sources_drive_validation():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    effective_changes = deploy[deploy.index("dnsmasq_effective_changes.extend") : deploy.index("dnsmasq_validation =")]

    assert "dnsmasq_binding" in effective_changes
    assert "dnsmasq_loopback_interface" in effective_changes
    assert "hosts_config" in effective_changes
    assert "dnsmasq_local_config" in effective_changes
    assert "obsolete_dhcp_configs" in effective_changes
    assert "dnsmasq_dhcp_configs" in effective_changes
    assert deploy.count("dnsmasq_effective_config_changed(dnsmasq_effective_changes)") == 4


def test_dnsmasq_normalizes_only_the_exact_loopback_interface_directive():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()
    normalization = deploy[deploy.index("dnsmasq_binding =") : deploy.index("hosts_config =")]

    assert 'line=r"^bind-interfaces$"' in normalization
    assert 'line=r"^interface=lo$"' in normalization
    assert normalization.count("present=False") == 2
    assert "interface=eth0" not in normalization
    assert "except-interface" not in normalization
    assert "listen-address" not in normalization


def test_dnsmasq_normalization_patterns_preserve_comments_and_unrelated_directives():
    patterns = [r"^bind-interfaces$", r"^interface=lo$"]
    lines = [
        "bind-interfaces",
        "interface=lo",
        "#bind-interfaces",
        "# bind-interfaces",
        "#interface=lo",
        "# interface=lo",
        "interface=eth0",
        "interface=ens192",
        "except-interface=lo",
        "listen-address=127.0.0.1",
        "bind-dynamic",
    ]

    matches = {line for line in lines if any(re.search(pattern, line) for pattern in patterns)}

    assert matches == {"bind-interfaces", "interface=lo"}


def test_dnsmasq_change_detection_is_only_evaluated_after_candidate_operations_execute():
    class Operation:
        def __init__(self, changed):
            self.changed = changed
            self.executed = False

        def did_change(self):
            assert self.executed
            return self.changed

    common = Operation(False)
    vlan = Operation(True)

    # Candidate operations report effective changes only after they execute.
    common.executed = True
    vlan.executed = True
    assert dnsmasq_effective_config_changed([common, vlan]) is True


def test_dnsmasq_change_detection_does_not_treat_backup_as_effective_change():
    class Backup:
        def did_change(self):
            raise AssertionError("backup must not be inspected")

    class Managed:
        def did_change(self):
            return False

    assert dnsmasq_effective_config_changed([Managed()]) is False


def test_route_replacement_preserves_unrelated_static_routes():
    from lib.bastion_network import reconcile_ipv4_routes

    current = "198.51.100.0/24 192.0.2.2, 192.0.2.128/26 192.0.2.9"

    assert reconcile_ipv4_routes(current, "192.0.2.128/26 192.0.2.1") == (
        "198.51.100.0/24 192.0.2.2, 192.0.2.128/26 192.0.2.1"
    )


def test_profile_rename_comparison_skips_identical_state_and_rejects_collision():
    assert profile_rename_needed("uuid-1", "uuid-1", "ens224", "mgmt") is False
    assert profile_rename_needed("uuid-1", "", "ens224", "mgmt") is True
    assert profile_rename_needed("uuid-1", "", "ens224", "mgmt", "mgmt") is False
    with pytest.raises(SystemExit, match="different connection"):
        profile_rename_needed("uuid-1", "uuid-2", "ens224", "mgmt")


def test_base_profile_rename_lifecycle_uses_connection_id_not_device_name():
    assert profile_rename_needed("uuid-ens192", "", "ens192", "local", "ens192") is True
    assert profile_rename_needed("uuid-ens192", "", "ens192", "local", "local") is False
    assert profile_rename_needed("uuid-ens224", "", "ens224", "mgmt", "ens224") is True
    assert profile_rename_needed("uuid-ens224", "", "ens224", "mgmt", "mgmt") is False


def test_base_profile_rename_resolves_active_connection_id_from_device():
    deploy = (ROOT / "pyinfra/deploy.py").read_text()

    assert "nmcli -g GENERAL.CONNECTION device show" in deploy
    assert "active_connection_id(source_name)" in deploy
    assert "nmcli connection modify uuid" in deploy


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
