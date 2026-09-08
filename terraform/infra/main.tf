provider "vsphere" {
  user                 = var.vsphere_user
  password             = var.vsphere_password
  vsphere_server       = var.vsphere_server
  allow_unverified_ssl = var.vsphere_allow_unverified_ssl
}

data "vsphere_datacenter" "this" {
  name = var.datacenter
}

data "vsphere_datastore" "this" {
  name          = var.datastore
  datacenter_id = data.vsphere_datacenter.this.id
}

data "vsphere_resource_pool" "this" {
  name          = var.resource_pool
  datacenter_id = data.vsphere_datacenter.this.id
}

data "vsphere_network" "this" {
  for_each      = var.networks
  name          = each.value
  datacenter_id = data.vsphere_datacenter.this.id
}

data "vsphere_virtual_machine" "template" {
  for_each      = var.templates
  name          = each.value
  datacenter_id = data.vsphere_datacenter.this.id
}

resource "random_string" "vm_suffix_a" {
  for_each = var.nodes

  length  = 5
  lower   = true
  numeric = true
  special = false
  upper   = false
}

resource "random_string" "vm_suffix_b" {
  for_each = var.nodes

  length  = 5
  lower   = true
  numeric = true
  special = false
  upper   = false
}

locals {
  node_static_ips = {
    for name, node in var.nodes : name => try([for nic in node.nics : nic.ip if try(nic.ip, null) != null][0], null)
  }
  node_vsphere_names = {
    for name, node in var.nodes : name => "${name}-${random_string.vm_suffix_a[name].result}-${random_string.vm_suffix_b[name].result}"
  }
  bastion_downstream_nics = [
    for nic in var.nodes[var.bastion_service_node].nics : nic
    if try(nic.downstream_vlan, null) != null
  ]
  bastion_downstream_macs = [
    for index, nic in var.nodes[var.bastion_service_node].nics :
    try(data.vsphere_virtual_machine.bastion_fresh[0].network_interfaces[index].mac_address, null)
    if try(nic.downstream_vlan, null) != null
  ]
  bastion_mac_addresses = length(local.bastion_downstream_nics) > 0 ? data.vsphere_virtual_machine.bastion_fresh[0].network_interfaces[*].mac_address : module.vm[var.bastion_service_node].mac_addresses
}

module "vm" {
  for_each = var.nodes
  source   = "./modules/vsphere-vm"

  name             = local.node_vsphere_names[each.key]
  host_name        = each.key
  domain           = var.domain
  folder           = var.folder
  cpu              = each.value.cpu
  memory_mb        = each.value.memory_mb
  disk_gb          = each.value.disk_gb
  datastore_id     = data.vsphere_datastore.this.id
  resource_pool_id = data.vsphere_resource_pool.this.id
  template         = data.vsphere_virtual_machine.template[each.value.template]
  gateway          = try(each.value.gateway, null)
  dns_servers      = coalesce(try(each.value.dns_servers, null), var.local_vlan.dns_servers)
  clone_timeout    = var.clone_timeout

  nics = [for nic in each.value.nics : {
    network_id   = data.vsphere_network.this[nic.network].id
    ipv4_address = try(nic.ip, null)
    ipv4_netmask = try(nic.prefix, null)
    customize    = coalesce(try(nic.customize, null), try(nic.ip, null) != null)
  }]
}

resource "time_sleep" "bastion_nic_settle" {
  count = length(local.bastion_downstream_nics) > 0 ? 1 : 0

  create_duration = "5s"
  triggers = {
    downstream_nic_topology = jsonencode([
      for nic in local.bastion_downstream_nics : {
        network         = nic.network
        downstream_vlan = nic.downstream_vlan
      }
    ])
  }

  depends_on = [module.vm]
}

data "vsphere_virtual_machine" "bastion_fresh" {
  count         = length(local.bastion_downstream_nics) > 0 ? 1 : 0
  name          = module.vm[var.bastion_service_node].name
  datacenter_id = data.vsphere_datacenter.this.id

  depends_on = [time_sleep.bastion_nic_settle]
}
