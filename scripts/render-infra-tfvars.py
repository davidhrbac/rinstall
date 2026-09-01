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
        nodes[name] = rendered_node

    rendered = {
        "vsphere_allow_unverified_ssl": vsphere.get("allow_unverified_ssl", True),
        "datacenter": require(vsphere, "datacenter", "env.infra.vsphere"),
        "datastore": require(vsphere, "datastore", "env.infra.vsphere"),
        "resource_pool": require(vsphere, "resource_pool", "env.infra.vsphere"),
        "folder": require(vsphere, "folder", "env.infra.vsphere"),
        "networks": require(infra, "networks", "env.infra"),
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


def main():
    parser = argparse.ArgumentParser(description="Render Terraform infra variables from env.yaml")
    parser.add_argument("--env", required=True, help="Path to env.yaml")
    parser.add_argument("--out", required=True, help="Output .tfvars.json path")
    args = parser.parse_args()

    env = load_env(args.env)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(render(env), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
