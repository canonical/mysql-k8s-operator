terraform {
  required_version = ">= 1.6.6"

  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 0.20.0, < 1.0.0"
    }
  }
}
