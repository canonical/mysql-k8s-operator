


# Alert rules

This page contains a markdown version of the alert rules described in the `mysql-k8s-operator` repository.  The following file(s) are the source of truth:
* [`prometheus_alert_rules/metrics_alert_rules.yaml`](https://github.com/canonical/mysql-k8s-operator/blob/main/src/prometheus_alert_rules/metrics_alert_rules.yaml)

> This documentation describes the latest alert rule expressions. See the YAML file(s) on listed above if you require an older version.

## MySQLExporterK8s

| Alert | Severity | Notes |
|------|----------|-------|
| MySQLDown | ![critical] | MySQL instance is down.<br> |
| MySQLTooManyConnections(>90%) | ![warning] | MySQL instance is using > 90% of `max_connections`.<br>Consider checking the client application responsible for generating those additional connections. |
| MySQLHighThreadsRunning | ![warning] | MySQL instance is actively using > 80% of `max_connections`.<br>Consider reviewing the value of the `max-connections` config parameter or allocate more resources to your database server.  |
| MySQLHighPreparedStatementsUtilization(>80%) | ![warning] | MySQL instance is using > 80% of `max_prepared_stmt_count`.<br>Too many prepared statements might consume a lot of memory.  |
| MySQLSlowQueries | ![info] | MySQL instance has a slow query.<br>Consider optimizing the query by reviewing its execution plan, then rewrite the query and add any relevant indexes.  |
| MySQLInnoDBLogWaits | ![warning] | MySQL instance has long InnoDB log waits.<br>MySQL InnoDB log writes might be stalling. Check I/O activity on your nodes to find the responsible process or query. Consider using iotop and the performance_schema.  |
| MySQLRestarted | ![info] | MySQL instance restarted.<br>MySQL restarted less than one minute ago. If the restart was unplanned or frequent, check Loki logs (e.g. `error.log`).  |

<!-- Badges -->
[info]: https://img.shields.io/badge/info-blue
[warning]: https://img.shields.io/badge/warning-yellow
[critical]: https://img.shields.io/badge/critical-red

