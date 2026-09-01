variable "name" {
  type = string
}

variable "host_name" {
  type = string
}

variable "domain" {
  type = string
}

variable "folder" {
  type = string
}

variable "cpu" {
  type = number
}

variable "memory_mb" {
  type = number
}

variable "disk_gb" {
  type = number
}

variable "datastore_id" {
  type = string
}

variable "resource_pool_id" {
  type = string
}

variable "template" {
  type = object({
    id                      = string
    guest_id                = string
    scsi_type               = string
    firmware                = string
    #disk_size               = number
    network_interface_types = list(string)
  })
}

variable "gateway" {
  type    = string
  default = null
}

variable "dns_servers" {
  type = list(string)
}

variable "nics" {
  type = list(object({
    network_id   = string
    ipv4_address = optional(string)
    ipv4_netmask = optional(number)
    customize    = bool
  }))
}
