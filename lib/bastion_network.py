import json
from ipaddress import ip_address, ip_network
from pathlib import Path
import re
import shlex


MAC_ADDRESS_PATTERN = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")


def device_for_mac_command(
    mac_address,
    sysfs_root="/sys/class/net",
    attempts=60,
    retry_delay=1,
):
    wanted = shlex.quote(mac_address)
    root = shlex.quote(sysfs_root)
    return (
        f"wanted=$(printf '%s' {wanted} | tr '[:upper:]' '[:lower:]'); "
        f"net_root={root}; "
        "udevadm settle >/dev/null 2>&1 || true; "
        f"for attempt in $(seq 1 {attempts}); do found=''; duplicate=''; "
        "for path in \"$net_root\"/*; do [ -e \"$path/address\" ] || continue; "
        "actual=$(tr '[:upper:]' '[:lower:]' < \"$path/address\"); "
        "if [ \"$actual\" = \"$wanted\" ]; then "
        "[ -z \"$found\" ] || duplicate=${path##*/}; found=${path##*/}; fi; done; "
        "if [ -n \"$duplicate\" ]; then printf 'MAC %s matched multiple devices\\n' \"$wanted\" >&2; exit 1; fi; "
        "if [ -n \"$found\" ]; then printf '%s' \"$found\"; exit 0; fi; "
        f"[ \"$attempt\" -eq {attempts} ] || sleep {retry_delay}; done; "
        f"printf 'Timed out after {attempts}s waiting for provider MAC %s; visible interfaces: ' \"$wanted\" >&2; "
        "first=1; for path in \"$net_root\"/*; do [ -e \"$path/address\" ] || continue; "
        "[ \"$first\" -eq 1 ] || printf ', ' >&2; first=0; "
        "printf '%s (%s)' \"${path##*/}\" \"$(tr '[:upper:]' '[:lower:]' < \"$path/address\")\" >&2; done; "
        "printf '\\n' >&2; exit 1"
    )


def load_bastion_mac_addresses(path, service_node):
    output_path = Path(path)
    if not output_path.exists():
        return []
    try:
        outputs = json.loads(output_path.read_text())
        nodes = outputs["nodes"]["value"]
        mac_addresses = nodes[service_node]["mac_addresses"]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise SystemExit(
            f"Terraform output {output_path} has no valid MAC list for bastion node {service_node}"
        ) from None
    if not isinstance(mac_addresses, list) or len(mac_addresses) < 2:
        raise SystemExit(
            f"Terraform output {output_path} has an incomplete bastion MAC list; "
            "provider-reported management MAC is required at base NIC index 1"
        )
    for index, mac_address in enumerate(mac_addresses[:2]):
        normalized = str(mac_address).lower()
        if not isinstance(mac_address, str) or not MAC_ADDRESS_PATTERN.fullmatch(normalized):
            raise SystemExit(
                f"Terraform output {output_path} has an invalid bastion MAC at base NIC index {index}"
            )
        mac_addresses[index] = normalized
    return mac_addresses


def management_route_association_command(
    management_mac,
    route_connection,
    sysfs_root="/sys/class/net",
    nmcli_command="nmcli",
    attempts=60,
    retry_delay=1,
):
    expected_mac = shlex.quote(management_mac.lower())
    expected_route = shlex.quote(route_connection)
    net_root = shlex.quote(sysfs_root)
    nmcli = shlex.quote(nmcli_command)
    resolver = device_for_mac_command(management_mac, sysfs_root, attempts, retry_delay)
    return (
        "set -eu; "
        f"expected_mac={expected_mac}; route_connection={expected_route}; net_root={net_root}; "
        f"management_device=$({resolver}) || {{ "
        "printf 'cannot resolve provider management MAC %s to a current guest device; "
        "configured route connection %s\n' \"$expected_mac\" \"$route_connection\" >&2; exit 1; }; "
        "if [ -z \"$management_device\" ]; then "
        "printf 'cannot resolve provider management MAC %s to a current guest device; "
        "configured route connection %s\n' \"$expected_mac\" \"$route_connection\" >&2; exit 1; fi; "
        "actual_mac=$(tr '[:upper:]' '[:lower:]' < \"$net_root/$management_device/address\"); "
        "if [ \"$actual_mac\" != \"$expected_mac\" ]; then "
        "printf 'management MAC %s resolved to device %s but that device reports MAC %s; "
        "configured route connection %s\n' \"$expected_mac\" \"$management_device\" "
        "\"$actual_mac\" \"$route_connection\" >&2; exit 1; fi; "
        f"route_uuids=$({nmcli} -g UUID connection show \"$route_connection\" 2>/dev/null || true); "
        "if [ -z \"$route_uuids\" ]; then "
        f"route_uuids=$({nmcli} -g GENERAL.CON-UUID device show \"$route_connection\" 2>/dev/null || true); fi; "
        "route_uuid=''; route_uuid_count=0; "
        "while IFS= read -r candidate; do "
        "candidate=$(printf '%s' \"$candidate\" | tr -d '\\r'); "
        "[ -n \"$candidate\" ] || continue; route_uuid_count=$((route_uuid_count + 1)); "
        "route_uuid=$candidate; done <<EOF\n$route_uuids\nEOF\n"
        "if [ \"$route_uuid_count\" -eq 0 ]; then "
        "printf 'configured route connection %s does not exist after reconciliation; "
        "expected management MAC %s on device %s\n' \"$route_connection\" "
        "\"$expected_mac\" \"$management_device\" >&2; exit 1; fi; "
        "if [ \"$route_uuid_count\" -gt 1 ]; then "
        "printf 'configured route connection %s is ambiguous after reconciliation (%s profiles); "
        "expected management MAC %s on device %s\n' \"$route_connection\" \"$route_uuid_count\" "
        "\"$expected_mac\" \"$management_device\" >&2; exit 1; fi; "
        "active_count=0; active_device=''; active_profile=''; "
        "for path in \"$net_root\"/*; do [ -e \"$path/address\" ] || continue; "
        "device=${path##*/}; "
        f"active_uuid=$({nmcli} -g GENERAL.CON-UUID device show \"$device\" 2>/dev/null || true); "
        "if [ \"$active_uuid\" = \"$route_uuid\" ]; then "
        "active_count=$((active_count + 1)); active_device=$device; "
        f"active_profile=$({nmcli} -g GENERAL.CONNECTION device show \"$device\" 2>/dev/null || true); fi; done; "
        "if [ \"$active_count\" -eq 0 ]; then "
        f"actual_profile=$({nmcli} -g GENERAL.CONNECTION device show \"$management_device\" 2>/dev/null || true); "
        "printf 'configured route connection %s is not active on any device; expected management MAC %s "
        "on device %s, whose active profile is %s\n' \"$route_connection\" \"$expected_mac\" "
        "\"$management_device\" \"$actual_profile\" >&2; exit 1; fi; "
        "if [ \"$active_count\" -gt 1 ]; then "
        "printf 'configured route connection %s is active on multiple devices; expected management MAC %s "
        "on device %s\n' \"$route_connection\" \"$expected_mac\" \"$management_device\" >&2; exit 1; fi; "
        "if [ \"$active_device\" != \"$management_device\" ]; then "
        "printf 'configured route connection %s is active on device %s (profile %s), but expected "
        "management MAC %s on device %s\n' \"$route_connection\" \"$active_device\" "
        "\"$active_profile\" \"$expected_mac\" \"$management_device\" >&2; exit 1; fi"
    )


def normalize_ipv4_route(value, context="route"):
    if not isinstance(value, str):
        raise SystemExit(f"{context} must contain an IPv4 destination and next hop")
    fields = value.split()
    if len(fields) != 2:
        raise SystemExit(f"{context} must contain an IPv4 destination and next hop")
    try:
        destination = ip_network(fields[0], strict=True)
        next_hop = ip_address(fields[1])
    except ValueError as error:
        raise SystemExit(f"{context} is invalid: {error}") from None
    if destination.version != 4 or next_hop.version != 4:
        raise SystemExit(f"{context} must contain an IPv4 destination and next hop")
    if destination.prefixlen == 0:
        raise SystemExit(f"{context} must not be a default route")
    return f"{destination} {next_hop}"


def route_device_is_active(device):
    return bool(device and device.strip() and device.strip() != "--")


def dhcp_excluded_interfaces(device_status, downstream_devices):
    downstream_devices = set(downstream_devices)
    excluded = set()
    for line in device_status.splitlines():
        if ":" not in line:
            continue
        device, device_type = line.split(":", 1)
        if (
            device_type in {"ethernet", "802-3-ethernet"}
            and device not in downstream_devices
            and device not in {"", "--"}
        ):
            excluded.add(device)
    return sorted(excluded)


def dnsmasq_effective_config_changed(operations):
    return any(operation.did_change() for operation in operations)


def dnsmasq_recovery_command(rollback_dir, config_root="/etc"):
    rollback = shlex.quote(str(rollback_dir))
    root = shlex.quote(str(config_root))
    dropin = shlex.quote(str(Path(config_root) / "dnsmasq.d"))
    return (
        "set -eu; "
        f'rollback_dir={rollback}; config_root={root}; dropin_dir={dropin}; '
        'if [ ! -d "$rollback_dir" ]; then exit 0; fi; '
        'if [ ! -f "$rollback_dir/ready" ]; then rm -rf "$rollback_dir"; exit 0; fi; '
        'for name in dnsmasq.conf hosts 10-rancher-local.conf 20-local-dhcp.conf 20-rinstall-dhcp.conf; do '
        'if [ ! -e "$rollback_dir/$name" ] && [ ! -e "$rollback_dir/$name.absent" ]; then '
        'printf "incomplete dnsmasq rollback state: %s\\n" "$name" >&2; exit 1; fi; done; '
        'if [ ! -f "$rollback_dir/service.active" ] || [ ! -f "$rollback_dir/service.enabled" ]; then '
        'printf "incomplete dnsmasq rollback service state\\n" >&2; exit 1; fi; '
        'atomic_replace() { '
        'src=$1; dest=$2; dir=$(dirname -- "$dest"); '
        'tmp=$(mktemp --tmpdir="$dir" .rinstall-dnsmasq-recovery.XXXXXX); '
        'if ! cp -a -- "$src" "$tmp"; then rm -f -- "$tmp"; return 1; fi; '
        'if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then '
        'if [ -e "$dest" ]; then '
        'if ! chcon --reference="$dest" "$tmp"; then rm -f -- "$tmp"; return 1; fi; '
        'elif command -v restorecon >/dev/null 2>&1; then '
        'if ! restorecon -F "$tmp"; then rm -f -- "$tmp"; return 1; fi; fi; fi; '
        'if ! sync -f "$tmp"; then rm -f -- "$tmp"; return 1; fi; '
        'if ! mv -f -- "$tmp" "$dest"; then rm -f -- "$tmp"; return 1; fi; '
        'if ! sync -f "$dir"; then return 1; fi; '
        '}; '
        'for name in dnsmasq.conf hosts; do '
        'dest="$config_root/$name"; '
        'if [ -e "$rollback_dir/$name.absent" ]; then rm -f -- "$dest"; '
        'else atomic_replace "$rollback_dir/$name" "$dest"; fi; done; '
        'for name in 10-rancher-local.conf 20-local-dhcp.conf 20-rinstall-dhcp.conf; do '
        'dest="$dropin_dir/$name"; '
        'if [ -e "$rollback_dir/$name.absent" ]; then rm -f -- "$dest"; '
        'else atomic_replace "$rollback_dir/$name" "$dest"; fi; done; '
        'rm -f -- "$dropin_dir"/dnsmasq-vlan*.conf; '
        'for path in "$rollback_dir"/dhcp/*.conf; do [ -e "$path" ] || continue; '
        'atomic_replace "$path" "$dropin_dir/$(basename "$path")"; done; '
        'if [ "$(cat "$rollback_dir/service.active")" = 1 ]; then systemctl restart dnsmasq; '
        'else systemctl stop dnsmasq; fi; '
        'if [ "$(cat "$rollback_dir/service.enabled")" = 1 ]; then systemctl enable dnsmasq; '
        'else systemctl disable dnsmasq; fi; '
        'rm -rf "$rollback_dir"'
    )


def downstream_profile_actions(profiles, managed_uuid, expected_mac, device_names):
    managed_uuid = managed_uuid.strip()
    expected_mac = expected_mac.lower()
    device_names = set(device_names)
    disable = []
    deactivate = []
    for profile in profiles:
        uuid = profile.get("uuid", "").strip()
        if not uuid or uuid == managed_uuid or profile.get("type", "").lower() not in {
            "ethernet",
            "802-3-ethernet",
        }:
            continue
        profile_mac = profile.get("mac_address", "").strip().lower().replace("\\:", ":")
        if profile_mac == "--":
            profile_mac = ""
        device = profile.get("device", "").strip()
        if device == "--":
            device = ""
        interface_name = profile.get("interface_name", "").strip()
        if interface_name == "--":
            interface_name = ""
        if profile_mac and profile_mac != expected_mac:
            continue
        if not profile_mac and device not in device_names and interface_name not in device_names:
            continue
        if profile.get("autoconnect", "").strip().lower() in {"yes", "true", "on"}:
            disable.append(uuid)
        if device in device_names:
            deactivate.append(uuid)
    return {"disable": disable, "deactivate": deactivate}


def split_nmcli_routes(value):
    return [entry.strip() for entry in re.split(r",\s*(?=[0-9])|[\r\n]+", value) if entry.strip()]


def normalize_route_list(value):
    normalized = []
    for entry in split_nmcli_routes(value):
        try:
            normalized.append(normalize_ipv4_route(entry))
        except SystemExit:
            normalized.append(" ".join(entry.split()))
    return normalized


def reconcile_ipv4_routes(current, desired):
    desired = normalize_ipv4_route(desired)
    desired_destination = desired.split()[0]
    reconciled = []
    replaced = False
    for entry in split_nmcli_routes(current):
        if entry.split()[0] == desired_destination:
            if not replaced:
                reconciled.append(desired)
                replaced = True
        else:
            reconciled.append(entry)
    if not replaced:
        reconciled.append(desired)
    return ", ".join(reconciled)


def route_needs_replacement(current, desired):
    replacement = reconcile_ipv4_routes(current, desired)
    return normalize_route_list(current) != normalize_route_list(replacement)


def profile_rename_needed(source_uuid, target_uuid, source, target, source_connection_id=""):
    source_uuid = source_uuid.strip()
    target_uuid = target_uuid.strip()
    source_connection_id = source_connection_id.strip()
    if source_connection_id == target:
        return False
    if target_uuid:
        if source_uuid and source_uuid != target_uuid:
            raise SystemExit(
                f"NetworkManager profile {target!r} belongs to a different connection than {source!r}"
            )
        return False
    if not source_uuid:
        raise SystemExit(f"cannot resolve NetworkManager profile or device {source!r}")
    return True


def downstream_connection_needs_activation(current_uuid, current_addresses, downstream):
    expected_address = f"{downstream['bastion_address']}/{downstream['prefix']}"
    return not (
        current_uuid.strip() == downstream["connection_uuid"]
        and f" {expected_address} " in f" {current_addresses} "
    )


def load_downstream_network_output(path, downstream_networks):
    output_path = Path(path)
    if not output_path.exists():
        if not downstream_networks:
            return {}
        raise SystemExit(
            f"missing Terraform output {output_path}; run infra-apply or infra-output before bastion-configure"
        )
    try:
        outputs = json.loads(output_path.read_text())
        actual = outputs["bastion_downstream_networks"]["value"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        if not downstream_networks:
            return {}
        raise SystemExit(f"Terraform output {output_path} has no valid bastion_downstream_networks map") from error
    if not isinstance(actual, dict):
        raise SystemExit(f"Terraform output {output_path} has no valid bastion_downstream_networks map")

    desired = {network["interface_name"]: network for network in downstream_networks}
    removed = sorted(set(actual) - set(desired))
    if removed:
        raise SystemExit(
            "downstream network removal is not supported in v0.3.0; restore these entries: "
            + ", ".join(removed)
        )
    missing = sorted(set(desired) - set(actual))
    if missing:
        raise SystemExit(
            "Terraform output is missing downstream interfaces; run infra-apply before bastion-configure: "
            + ", ".join(missing)
        )

    macs = set()
    for name, network in desired.items():
        attachment = actual[name]
        if attachment.get("vlan") != network["vlan"]:
            raise SystemExit(f"Terraform output VLAN does not match configuration for {name}")
        if attachment.get("vmware_network") != network["vmware_network"]:
            raise SystemExit(f"Terraform output VMware network does not match configuration for {name}")
        mac_address = str(attachment.get("mac_address", "")).lower()
        if not MAC_ADDRESS_PATTERN.fullmatch(mac_address):
            raise SystemExit(f"Terraform output has invalid MAC address for {name}")
        if mac_address in macs:
            raise SystemExit(f"Terraform output reuses MAC address {mac_address}")
        macs.add(mac_address)
        attachment["mac_address"] = mac_address

    return actual
