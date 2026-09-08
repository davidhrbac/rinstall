import json
from ipaddress import ip_address, ip_network
from pathlib import Path
import re


MAC_ADDRESS_PATTERN = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")


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
        profile_mac = profile.get("mac_address", "").strip().lower()
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


def profile_rename_needed(source_uuid, target_uuid, source, target):
    source_uuid = source_uuid.strip()
    target_uuid = target_uuid.strip()
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
