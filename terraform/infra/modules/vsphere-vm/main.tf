resource "vsphere_virtual_machine" "this" {
  name             = var.name
  folder           = var.folder
  resource_pool_id = var.resource_pool_id
  datastore_id     = var.datastore_id

  num_cpus = var.cpu
  memory   = var.memory_mb

  guest_id  = var.template.guest_id
  scsi_type = var.template.scsi_type
  firmware  = var.template.firmware

  dynamic "network_interface" {
    for_each = var.nics
    content {
      network_id   = network_interface.value.network_id
      adapter_type = try(var.template.network_interface_types[network_interface.key], null)
    }
  }

  disk {
    label            = "disk0"
    size             = max(var.disk_gb, var.template.disk_size)
    thin_provisioned = true
  }

  clone {
    template_uuid = var.template.id

    customize {
      linux_options {
        host_name = var.name
        domain    = var.domain
      }

      dynamic "network_interface" {
        for_each = var.nics
        content {
          ipv4_address = network_interface.value.customize ? network_interface.value.ipv4_address : null
          ipv4_netmask = network_interface.value.customize ? network_interface.value.ipv4_netmask : null
        }
      }

      ipv4_gateway    = var.gateway
      dns_server_list = var.dns_servers
      dns_suffix_list = [var.domain]
    }
  }
}
