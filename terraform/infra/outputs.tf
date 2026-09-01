output "nodes" {
  value = {
    for name, vm in module.vm : name => {
      id                 = vm.id
      vsphere_name       = vm.name
      role               = var.nodes[name].role
      static_ip          = local.node_static_ips[name]
      default_ip_address = vm.default_ip_address
      mac_addresses      = vm.mac_addresses
    }
  }
}

output "bastion_ip" {
  value = local.node_static_ips["bastion1"]
}

output "rancher_ips" {
  value = [for name, node in var.nodes : local.node_static_ips[name] if node.role == "rancher"]
}

output "rancher_url" {
  value = var.rancher_url
}
