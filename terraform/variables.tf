variable "model" {
  description = "UUID of the juju model to deploy to"
  type        = string
}

variable "app_name" {
  description = "Name of the juju application"
  type        = string
  default     = "mysql-k8s"
}

variable "base" {
  description = "Application base"
  type        = string
  default     = "ubuntu@22.04"
}

variable "config" {
  description = "Application configuration. Details at https://charmhub.io/mysql-k8s/configurations"
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Juju constraints for the application"
  type        = string
  default     = "arch=amd64"
}

variable "channel" {
  description = "Charm channel to deploy from"
  type        = string
  default     = "8.0/stable"
}

variable "revision" {
  description = "Charm revision to deploy"
  type        = number
  default     = null
}

variable "units" {
  description = "Number of units to deploy"
  type        = number
  default     = 3
}

variable "storage_size" {
  description = "Storage size"
  type        = string
  default     = "10G"
}
