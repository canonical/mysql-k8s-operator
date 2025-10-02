output "app_name" {
  description = "Name of the MySQL Server K8s application"
  value       = juju_application.mysql_server.name
}

output "provides" {
  description = "Map of all the provided endpoints"
  value = {
    database          = "database"
    grafana_dashboard = "grafana-dashboard"
    metrics_endpoint  = "metrics-endpoint"
  }
}

output "requires" {
  description = "Map of all the required endpoints"
  value = {
    certificates  = "certificates"
    s3_parameters = "s3-parameters"
    logging       = "logging"
    tracing       = "tracing"
  }
}
