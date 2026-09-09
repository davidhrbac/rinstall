resource "vsphere_virtual_machine" "this" {
  name             = var.name
  folder           = var.folder
  resource_pool_id = var.resource_pool_id
  datastore_id     = var.datastore_id

  num_cpus = var.cpu
  memory   = var.memory_mb

  shutdown_wait_timeout = 1
  force_power_off       = true

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
    size             = max(var.disk_gb, var.template.disks[0].size)
    thin_provisioned = true
  }

  clone {
    template_uuid = var.template.id
    timeout       = var.clone_timeout

    customize {
      linux_options {
        host_name = var.host_name
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

resource "time_sleep" "nic_settle" {
  count = var.settle_after_change ? 1 : 0

  create_duration = "5s"

  depends_on = [vsphere_virtual_machine.this]

  lifecycle {
    replace_triggered_by = [vsphere_virtual_machine.this]
  }
}
