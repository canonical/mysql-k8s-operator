# Alert rules

This page contains a markdown version of the alert rules described in the `mysql-k8s operator` repository.

See the source of truth on GitHub for the latest information, or an older version:

[`prometheus_alert_rules/`](https://github.com/canonical/mysql-k8s-operator/blob/main/src/prometheus_alert_rules/)

## MySQL General Alerts

| Alert | Severity | Notes |
| ----- | -------- | ----- |
| MySQLDown | ![critical] | MySQL instance is down.<br>Please check if the MySQL process is running and the network connectivity. |
| MySQLMetricsScrapeError | ![warning] | MySQL Exporter encountered a metrics scrape error.<br>Check the MySQL Exporter logs for more details. |
| MySQLTooManyConnections(>90%) | ![warning] | MySQL instance is using > 90% of `max_connections`.<br>Consider checking the client application responsible for generating those additional connections. |
| MySQLHighThreadsRunning | ![warning] | MySQL instance is actively using > 80% of `max_connections`.<br>Consider reviewing the value of the `max-connections` config parameter or allocate more resources to your database server. |
| MySQLHighPreparedStatementsUtilization(>80%) | ![warning] | MySQL instance is using > 80% of `max_prepared_stmt_count`.<br>Too many prepared statements might consume a lot of memory. |
| MySQLSlowQueries | ![info] | MySQL instance has slow queries.<br>Consider optimizing the query by reviewing its execution plan, then rewrite the query and add any relevant indexes. |
| MySQLInnoDBLogWaits | ![warning] | MySQL instance has long InnoDB log waits.<br>MySQL InnoDB log writes might be stalling. Check I/O activity on your nodes to find the responsible process or query. |
| MySQLRestarted | ![info] | MySQL instance restarted.<br>MySQL restarted less than one minute ago. If the restart was unplanned or frequent, check Loki logs (e.g. `error.log`). |
| MySQLConnectionErrors | ![warning] | MySQL instance has connection errors.<br>Connection errors might indicate network issues, authentication problems, or resource limitations. Check the MySQL logs for more details. |

## MySQL Replication Alerts

| Alert | Severity | Notes |
| ----- | -------- | ----- |
| MySQLClusterUnitOffline | ![warning] | MySQL cluster member is marked **offline**.<br>The process might still be running, but the member is excluded from the cluster. |
| MySQLClusterNoPrimary | ![critical] | No **primary** in the cluster.<br>The cluster will likely be in a Read-Only state. Check cluster health and logs. |
| MySQLClusterTooManyPrimaries | ![critical] | More than one **primary** detected.<br>This can indicate a **split-brain** situation. Refer to troubleshooting docs. |
| MySQLNoReplication | ![warning] | No **secondary** members in the cluster.<br>The cluster is not redundant and failure of the primary will cause downtime. |
| MySQLGroupReplicationReduced | ![warning] | The number of ONLINE members in the replication group has reduced compared to the maximum observed in the last 6 hours.<br>Check cluster health and logs. |
| MySQLGroupReplicationConflicts | ![warning] | Conflicts detected in Group Replication.<br>Indicates concurrent writes to the same rows/keys across members. Investigate logs and cluster status. |
| MySQLGroupReplicationQueueSizeHigh | ![warning] | High number of transactions in Group Replication queue (>100).<br>May indicate network issues or overloaded nodes. Investigate cluster performance. |

<!-- Badges -->
[info]: https://img.shields.io/badge/info-blue
[warning]: https://img.shields.io/badge/warning-yellow
[critical]: https://img.shields.io/badge/critical-red
