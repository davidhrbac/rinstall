output "nodes" {
  value = {
    for name, vm in module.vm : name => {
      id                 = vm.id
      vsphere_name       = vm.name
      role               = var.nodes[name].role
      static_ip          = local.node_static_ips[name]
      default_ip_address = vm.default_ip_address
      mac_addresses      = name == var.bastion_service_node ? local.bastion_mac_addresses : vm.mac_addresses
    }
  }
}

output "bastion_ip" {
  value = local.node_static_ips[var.bastion_service_node]
}

output "bastion_downstream_networks" {
  value = {
    for index, nic in var.nodes[var.bastion_service_node].nics : "vlan${nic.downstream_vlan}" => {
      vlan              = nic.downstream_vlan
      vmware_network    = var.networks[nic.network]
      vmware_network_id = data.vsphere_network.this[nic.network].id
      mac_address       = try(data.vsphere_virtual_machine.bastion_fresh[0].network_interfaces[index].mac_address, null)
      nic_index         = index
      attachment_order  = index + 1
    }
    if try(nic.downstream_vlan, null) != null
  }

  precondition {
    condition = alltrue([
      for network in local.bastion_downstream_fresh :
      network.mac_address != null && network.mac_address != "" && network.network_id == network.expected_network_id
    ])
    error_message = "fresh bastion vSphere data has no matching MAC/network for a configured downstream NIC"
  }
}

output "rancher_ips" {
  value = [for name, node in var.nodes : local.node_static_ips[name] if node.role == "rancher"]
}

output "rancher_url" {
  value = var.rancher_url
}
