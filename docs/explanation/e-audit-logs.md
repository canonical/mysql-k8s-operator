# Audit Logs

The Audit Log plugin allows all login/logout records to be stored in a log file. It is enabled in Charmed MySQL K8s by default.

## Overview

The following is a sample of the audit logs, with format json with login/logout records:

```json
{"audit_record":{"name":"Quit","record":"6_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"992","status":0,"user":"clusteradmin","priv_user":"clusteradmin","os_login":"","proxy_user":"","host":"localhost","ip":"","db":""}}
{"audit_record":{"name":"Connect","record":"7_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"993","status":1156,"user":"","priv_user":"","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Connect","record":"8_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"994","status":0,"user":"serverconfig","priv_user":"serverconfig","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}} 
```

The logs are stored in the `/var/log/mysql` directory of the mysql container, and it's rotated
every minute to the `/var/log/mysql/archive_audit` directory.
It's recommended to integrate the charm with [COS](/t/9900), from where the logs can be easily persisted and queried using Loki/Grafana.

## Configurations

1. `plugin-audit-enabled` - The audit plugin is enabled by default in the charm, but it's possible to disable it by setting:

    ```bash
    juju config mysql-k8s plugin-audit-enabled=false
    ```
    Valid value are `false` and `true`. By setting it to false, existing logs are still kept in the `archive_audit` directory.

1. `logs_audit_policy` - Audit log policy:

    ```bash
    juju config mysql-k8s logs_audit_policy=queries
    ```
    Valid values are: "all", "logins" (default), "queries"

1. `plugin-audit-strategy` - By default the audit plugin writes logs in asynchronous mode for better performance.
    To ensure logs are written to disk on more timely fashion, this configuration can be set to semi-synchronous mode:

    ```bash
    juju config mysql-k8s plugin-audit-strategy=semi-async
    ```
    Valid values are `async` and `semi-async`.