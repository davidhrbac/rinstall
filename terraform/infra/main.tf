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

locals {
  node_static_ips = {
    for name, node in var.nodes : name => try([for nic in node.nics : nic.ip if try(nic.ip, null) != null][0], null)
  }
}

module "vm" {
  for_each = var.nodes
  source   = "./modules/vsphere-vm"

  name             = each.key
  domain           = var.domain
  folder           = var.folder
  cpu              = each.value.cpu
  memory_mb        = each.value.memory_mb
  disk_gb          = each.value.disk_gb
  datastore_id     = data.vsphere_datastore.this.id
  resource_pool_id = data.vsphere_resource_pool.this.id
  template         = data.vsphere_virtual_machine.template[each.value.template]
  gateway          = try(each.value.gateway, null)
  dns_servers      = var.local_vlan.dns_servers

  nics = [for nic in each.value.nics : {
    network_id   = data.vsphere_network.this[nic.network].id
    ipv4_address = try(nic.ip, null)
    ipv4_netmask = try(nic.prefix, null)
    customize    = coalesce(try(nic.customize, null), try(nic.ip, null) != null)
  }]
}
