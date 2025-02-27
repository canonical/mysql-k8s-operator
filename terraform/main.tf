resource "juju_application" "k8s_mysql" {
  name  = var.app_name
  model = var.juju_model_name
  trust = true

  charm {
    name     = "mysql-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  storage_directives = {
    database = var.storage_size
  }

  units       = var.units
  constraints = var.constraints
  config      = var.config
  resources   = var.resources
}
