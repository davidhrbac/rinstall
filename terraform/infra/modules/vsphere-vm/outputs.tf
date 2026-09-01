output "id" {
  value = vsphere_virtual_machine.this.id
}

output "name" {
  value = vsphere_virtual_machine.this.name
}

output "default_ip_address" {
  value = vsphere_virtual_machine.this.default_ip_address
}

output "mac_addresses" {
  value = vsphere_virtual_machine.this.network_interface[*].mac_address
}
