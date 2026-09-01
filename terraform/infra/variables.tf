variable "vsphere_server" {
  type = string
}

variable "vsphere_user" {
  type = string
}

variable "vsphere_password" {
  type      = string
  sensitive = true
  default   = null
}

variable "vsphere_allow_unverified_ssl" {
  type    = bool
  default = true
}

variable "datacenter" {
  type = string
}

variable "datastore" {
  type = string
}

variable "resource_pool" {
  type = string
}

variable "folder" {
  type = string
}

variable "networks" {
  type = map(string)
}

variable "templates" {
  type = map(string)
}

variable "domain" {
  type = string
}

variable "rancher_url" {
  type = string
}

variable "local_vlan" {
  type = object({
    prefix      = number
    gateway     = string
    dns_servers = list(string)
  })
}

variable "nodes" {
  type = map(object({
    role        = string
    template    = string
    gateway     = optional(string)
    dns_servers = optional(list(string))
    cpu         = number
    memory_mb   = number
    disk_gb     = number
    nics = list(object({
      network   = string
      ip        = optional(string)
      prefix    = optional(number)
      customize = optional(bool)
    }))
  }))
}
