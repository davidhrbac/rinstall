#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.env_config import load_env, require


def render(env):
    infra = require(env, "infra", "env")
    vsphere = require(infra, "vsphere", "env.infra")
    local_vlan = require(env, "local_vlan", "env")

    nodes = {}
    for name, node in require(env, "nodes", "env").items():
        nics = []
        for nic in require(node, "nics", f"env.nodes.{name}"):
            rendered_nic = {"network": require(nic, "network", f"env.nodes.{name}.nics[]")}
            if nic.get("ip") is not None:
                rendered_nic["ip"] = nic["ip"]
            if nic.get("prefix") is not None:
                rendered_nic["prefix"] = nic["prefix"]
            if nic.get("customize") is not None:
                rendered_nic["customize"] = nic["customize"]
            nics.append(rendered_nic)

        rendered_node = {
            "role": require(node, "role", f"env.nodes.{name}"),
            "template": require(node, "template", f"env.nodes.{name}"),
            "cpu": require(node, "cpu", f"env.nodes.{name}"),
            "memory_mb": require(node, "memory_mb", f"env.nodes.{name}"),
            "disk_gb": require(node, "disk_gb", f"env.nodes.{name}"),
            "nics": nics,
        }
        if node.get("gateway") is not None:
            rendered_node["gateway"] = node["gateway"]
        if node.get("dns_servers") is not None:
            rendered_node["dns_servers"] = node["dns_servers"]
        nodes[name] = rendered_node

    networks = dict(require(infra, "networks", "env.infra"))
    bastion_service_node = require(env["bastion"], "service_node", "env.bastion")
    for downstream in env["bastion"]["downstream_networks"]:
        vlan = downstream["vlan"]
        lookup_name = f"__downstream_vlan_{vlan}"
        if lookup_name in networks:
            raise SystemExit(f"generated downstream network lookup name conflicts with env.infra.networks: {lookup_name}")
        networks[lookup_name] = downstream["vmware_network"]
        nodes[bastion_service_node]["nics"].append(
            {
                "network": lookup_name,
                "customize": False,
                "downstream_vlan": vlan,
                "downstream_subnet": downstream["subnet"],
                "downstream_bastion_address": downstream["bastion_address"],
                "downstream_gateway": downstream["gateway"],
            }
        )

    rendered = {
        "vsphere_allow_unverified_ssl": vsphere.get("allow_unverified_ssl", False),
        "clone_timeout": vsphere.get("clone_timeout", 60),
        "bastion_service_node": bastion_service_node,
        "datacenter": require(vsphere, "datacenter", "env.infra.vsphere"),
        "datastore": require(vsphere, "datastore", "env.infra.vsphere"),
        "resource_pool": require(vsphere, "resource_pool", "env.infra.vsphere"),
        "folder": require(vsphere, "folder", "env.infra.vsphere"),
        "networks": networks,
        "templates": require(infra, "templates", "env.infra"),
        "domain": require(env, "domain", "env"),
        "rancher_url": require(env, "rancher_url", "env"),
        "local_vlan": {
            "prefix": require(local_vlan, "prefix", "env.local_vlan"),
            "gateway": require(local_vlan, "gateway", "env.local_vlan"),
            "dns_servers": require(local_vlan, "dns_servers", "env.local_vlan"),
        },
        "nodes": nodes,
    }
    if vsphere.get("server") is not None:
        rendered["vsphere_server"] = vsphere["server"]
    if vsphere.get("user") is not None:
        rendered["vsphere_user"] = vsphere["user"]
    return rendered


def validate_no_downstream_removal(rendered, existing_outputs):
    output = existing_outputs.get("bastion_downstream_networks", {})
    if not isinstance(output, dict):
        raise SystemExit("existing Terraform bastion_downstream_networks output is invalid")
    existing = output.get("value", {})
    if existing == {}:
        return
    if not isinstance(existing, dict):
        raise SystemExit("existing Terraform bastion_downstream_networks output is invalid")

    bastion = rendered["nodes"][rendered["bastion_service_node"]]
    desired = {
        f"vlan{nic['downstream_vlan']}": {
            "vlan": nic["downstream_vlan"],
            "nic_index": index,
            "vmware_network": rendered["networks"][nic["network"]],
            "subnet": nic["downstream_subnet"],
            "bastion_address": nic["downstream_bastion_address"],
            "gateway": nic["downstream_gateway"],
        }
        for index, nic in enumerate(bastion["nics"])
        if nic.get("downstream_vlan") is not None
    }

    removed = sorted(set(existing) - set(desired))
    if removed:
        raise SystemExit(
            "downstream network removal is not supported in v0.3.0; restore these entries: "
            + ", ".join(removed)
        )

    incomplete = [
        name
        for name, network in existing.items()
        if not isinstance(network, dict)
        or any(
            field not in network
            for field in ("vlan", "nic_index", "vmware_network", "subnet", "bastion_address", "gateway")
        )
    ]
    if incomplete:
        raise SystemExit(
            "existing downstream lifecycle identity is incomplete for: " + ", ".join(sorted(incomplete))
        )

    reordered = [
        name
        for name in existing
        if existing[name].get("nic_index") != desired[name]["nic_index"]
    ]
    if reordered:
        raise SystemExit(
            "existing downstream NIC attachment order must not change; restore the previous order for: "
            + ", ".join(sorted(reordered))
        )

    moved = [
        name
        for name in existing
        if existing[name].get("vmware_network") != desired[name]["vmware_network"]
    ]
    if moved:
        raise SystemExit(
            "changing an existing downstream VMware network is not supported in v0.3.0: "
            + ", ".join(sorted(moved))
        )

    changed_addressing = [
        name
        for name in existing
        if any(
            existing[name].get(field) != desired[name][field]
            for field in ("vlan", "subnet", "bastion_address", "gateway")
        )
    ]
    if changed_addressing:
        raise SystemExit(
            "changing existing downstream addressing is not supported in v0.3.0: "
            + ", ".join(sorted(changed_addressing))
        )


def validate_bastion_base_nics(rendered, existing_outputs):
    if "bastion_base_nics" not in existing_outputs:
        if existing_outputs:
            raise SystemExit(
                "existing Terraform output has no bastion_base_nics topology; "
                "refresh/apply the infrastructure before changing bastion NICs"
            )
        return
    output = existing_outputs["bastion_base_nics"]
    if not isinstance(output, dict):
        raise SystemExit("existing Terraform bastion_base_nics output is invalid")
    existing = output.get("value")
    if not isinstance(existing, list):
        raise SystemExit("existing Terraform bastion_base_nics output is invalid")

    bastion = rendered["nodes"][rendered["bastion_service_node"]]
    desired = [
        {
            "nic_index": index,
            "vmware_network": rendered["networks"][nic["network"]],
        }
        for index, nic in enumerate(bastion["nics"])
        if nic.get("downstream_vlan") is None
    ]
    if existing != desired:
        raise SystemExit(
            "existing bastion base NIC order or VMware network identity changed; "
            "restore the previous base NIC topology"
        )


def main():
    parser = argparse.ArgumentParser(description="Render Terraform infra variables from env.yaml")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    parser.add_argument("--out", required=True, help="Output .tfvars.json path")
    parser.add_argument("--existing-infra-output", help="Existing Terraform output used to reject NIC removal")
    args = parser.parse_args()

    env = load_env(args.env)
    rendered = render(env)
    if args.existing_infra_output:
        existing_path = Path(args.existing_infra_output)
        if existing_path.exists():
            existing_outputs = json.loads(existing_path.read_text())
            validate_bastion_base_nics(rendered, existing_outputs)
            validate_no_downstream_removal(rendered, existing_outputs)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rendered, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
