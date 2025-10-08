resource "juju_application" "mysql_server" {
  name  = var.app_name
  model = var.model_name
  trust = true

  charm {
    name     = "mysql-k8s"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }

  storage_directives = {
    database = var.storage_size
  }

  config      = var.config
  constraints = var.constraints
  units       = var.units
}
