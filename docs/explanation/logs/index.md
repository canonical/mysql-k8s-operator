# Logs

This explanation goes over the types of logging in MySQL and the configuration parameters for log rotation.

The charm currently has audit and error logs enabled by default. All of these files are rotated if present into a separate dedicated archive folder under the logs directory. We do not yet support the rotation of binary logs (binlog, relay log, undo log, redo log, etc).

We do not yet support the rotation of binary logs (binlog, relay log, undo log, redo log, etc).

## Log types

The charm stores its logs in `/var/log/mysql`. 

```shell
$ ls -lahR /var/log/mysql

/var/log/mysql:
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:46 archive_audit
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:46 archive_error
-rw-r----- 1 mysql mysql 1.1K Oct 23 20:46 audit.log
-rw-r----- 1 mysql mysql 1.1K Oct 23 20:46 error.log

/var/log/mysql/archive_audit:
-rw-r----- 1 snap_daemon root         43K Sep  3 01:24 audit.log-20240903_0124.gz
-rw-r----- 1 snap_daemon root        109K Sep  3 01:25 audit.log-20240903_0125.gz

/var/log/mysql/archive_error:
-rw-r----- 1 mysql mysql 8.7K Oct 23 20:44 error.log-43_2045.gz
-rw-r----- 1 mysql mysql 2.3K Oct 23 20:45 error.log-43_2046.gz
```

It is recommended to set up a [COS integration] so that these log files can be streamed to Loki. This leads to better persistence and security of the logs.

### Audit logs
The Audit Log plugin allows all login/logout records to be stored in a log file.

<details>
<summary>Example of audit logs in JSON format with login/logout records</summary>

```json
{"audit_record":{"name":"Connect","record":"17_2024-09-03T01:52:14","timestamp":"2024-09-03T01:53:14Z","connection_id":"988","status":1156,"user":"","priv_user":"","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Connect","record":"18_2024-09-03T01:52:14","timestamp":"2024-09-03T01:53:14Z","connection_id":"989","status":0,"user":"serverconfig","priv_user":"serverconfig","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Quit","record":"1_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:14Z","connection_id":"989","status":0,"user":"serverconfig","priv_user":"serverconfig","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Connect","record":"2_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"990","status":1156,"user":"","priv_user":"","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Connect","record":"3_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"991","status":0,"user":"serverconfig","priv_user":"serverconfig","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Quit","record":"4_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"991","status":0,"user":"serverconfig","priv_user":"serverconfig","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Connect","record":"5_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"992","status":0,"user":"clusteradmin","priv_user":"clusteradmin","os_login":"","proxy_user":"","host":"localhost","ip":"","db":""}}
{"audit_record":{"name":"Quit","record":"6_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"992","status":0,"user":"clusteradmin","priv_user":"clusteradmin","os_login":"","proxy_user":"","host":"localhost","ip":"","db":""}}
{"audit_record":{"name":"Connect","record":"7_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"993","status":1156,"user":"","priv_user":"","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
{"audit_record":{"name":"Connect","record":"8_2024-09-03T01:53:14","timestamp":"2024-09-03T01:53:33Z","connection_id":"994","status":0,"user":"serverconfig","priv_user":"serverconfig","os_login":"","proxy_user":"","host":"juju-da2225-8","ip":"10.207.85.214","db":""}}
```
</details>

For more details, see the [Audit Logs explanation].

### Error logs

<details>
<summary>Example of error logs with format <code>time thread [label] [err_code] [subsystem] msg</code></summary>
```shell
2023-10-24T23:28:07.048728Z mysqld_safe Number of processes running now: 0
2023-10-24T23:28:07.063027Z mysqld_safe mysqld restarted
2023-10-24T23:28:07.472084Z 0 [Warning] [MY-010101] [Server] Insecure configuration for --secure-file-priv: Location is accessible to all OS users. Consider choosing a different directory.
2023-10-24T23:28:07.472149Z 0 [System] [MY-010116] [Server] /snap/charmed-mysql/69/usr/sbin/mysqld (mysqld 8.0.34-0ubuntu0.22.04.1) starting as process 4134
2023-10-24T23:28:07.482044Z 1 [System] [MY-013576] [InnoDB] InnoDB initialization has started.
2023-10-24T23:28:11.219123Z 1 [System] [MY-013577] [InnoDB] InnoDB initialization has ended.
2023-10-24T23:28:11.486308Z 0 [Warning] [MY-010068] [Server] CA certificate ca.pem is self signed.
2023-10-24T23:28:11.487473Z 0 [System] [MY-013602] [Server] Channel mysql_main configured to support TLS. Encrypted connections are now supported for this channel.
2023-10-24T23:28:11.538807Z 0 [System] [MY-011323] [Server] X Plugin ready for connections. Bind-address: '0.0.0.0' port: 33060, socket: /var/snap/charmed-mysql/common/var/run/mysqld/mysqlx.sock
2023-10-24T23:28:11.538957Z 0 [System] [MY-010931] [Server] /snap/charmed-mysql/69/usr/sbin/mysqld: ready for connections. Version: '8.0.34-0ubuntu0.22.04.1'  socket: '/var/snap/charmed-mysql/common/var/run/mysqld/mysqld.sock'  port: 3306  (Ubuntu).
2023-10-24T23:28:17.983851Z 12 [Warning] [MY-010604] [Repl] Neither --relay-log nor --relay-log-index were used; so replication may break when this MySQL server acts as a replica and has his hostname changed!! Please use '--relay-log=juju-9860bb-0-relay-bin' to avoid this problem.
2023-10-24T23:28:17.999093Z 12 [System] [MY-010597] [Repl] 'CHANGE REPLICATION SOURCE TO FOR CHANNEL 'mysqlsh.test' executed'. Previous state source_host='', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''. New state source_host='juju-9860bb-0.lxd', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''.
2023-10-24T23:28:18.025941Z 15 [Warning] [MY-010897] [Repl] Storing MySQL user name or password information in the connection metadata repository is not secure and is therefore not recommended. Please consider using the USER and PASSWORD connection options for START REPLICA; see the 'START REPLICA Syntax' in the MySQL Manual for more information.
2023-10-24T23:28:18.046893Z 15 [ERROR] [MY-013117] [Repl] Replica I/O for channel 'mysqlsh.test': Fatal error: The replica I/O thread stops because source and replica have equal MySQL server ids; these ids must be different for replication to work (or the --replicate-same-server-id option must be used on replica but this does not always make sense; please check the manual before using it). Error_code: MY-013117
2023-10-24T23:28:18.415923Z 12 [ERROR] [MY-011685] [Repl] Plugin group_replication reported: 'The group_replication_group_name option is mandatory'
2023-10-24T23:28:18.415960Z 12 [ERROR] [MY-011660] [Repl] Plugin group_replication reported: 'Unable to start Group Replication on boot'
2023-10-24T23:28:18.442291Z 12 [System] [MY-010597] [Repl] 'CHANGE REPLICATION SOURCE TO FOR CHANNEL '__mysql_innodb_cluster_creating_cluster__' executed'. Previous state source_host='', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''. New state source_host='', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''.
2023-10-24T23:28:18.508247Z 12 [System] [MY-010597] [Repl] 'CHANGE REPLICATION SOURCE TO FOR CHANNEL 'group_replication_recovery' executed'. Previous state source_host='', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''. New state source_host='', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''.
2023-10-24T23:28:18.572495Z 12 [System] [MY-013587] [Repl] Plugin group_replication reported: 'Plugin 'group_replication' is starting.'
2023-10-24T23:28:18.622821Z 20 [System] [MY-010597] [Repl] 'CHANGE REPLICATION SOURCE TO FOR CHANNEL 'group_replication_applier' executed'. Previous state source_host='', source_port= 3306, source_log_file='', source_log_pos= 4, source_bind=''. New state source_host='<NULL>', source_port= 0, source_log_file='', source_log_pos= 4, source_bind=''.
2023-10-24T23:28:18.875230Z 0 [System] [MY-011565] [Repl] Plugin group_replication reported: 'Setting super_read_only=ON.'
2023-10-24T23:28:18.875322Z 0 [System] [MY-013471] [Repl] Plugin group_replication reported: 'Distributed recovery will transfer data using: Incremental recovery from a group donor'
2023-10-24T23:28:18.875561Z 0 [System] [MY-011565] [Repl] Plugin group_replication reported: 'Setting super_read_only=ON.'
2023-10-24T23:28:18.875596Z 0 [System] [MY-011503] [Repl] Plugin group_replication reported: 'Group membership changed to juju-9860bb-0.lxd:3306 on view 16981900988747955:1.'
2023-10-24T23:28:19.176137Z 0 [System] [MY-011490] [Repl] Plugin group_replication reported: 'This server was declared online within the replication group.'
2023-10-24T23:28:19.176342Z 0 [System] [MY-011507] [Repl] Plugin group_replication reported: 'A new primary with address juju-9860bb-0.lxd:3306 was elected. The new primary will execute all previous group transactions before allowing writes.'
2023-10-24T23:28:19.176967Z 31 [System] [MY-011565] [Repl] Plugin group_replication reported: 'Setting super_read_only=ON.'
2023-10-24T23:28:19.179244Z 28 [System] [MY-013731] [Repl] Plugin group_replication reported: 'The member action "mysql_disable_super_read_only_if_primary" for event "AFTER_PRIMARY_ELECTION" with priority "1" will be run.'
2023-10-24T23:28:19.179289Z 28 [System] [MY-011566] [Repl] Plugin group_replication reported: 'Setting super_read_only=OFF.'
2023-10-24T23:28:19.179408Z 28 [System] [MY-013731] [Repl] Plugin group_replication reported: 'The member action "mysql_start_failover_channels_if_primary" for event "AFTER_PRIMARY_ELECTION" with priority "10" will be run.'
2023-10-24T23:28:19.179600Z 31 [System] [MY-011510] [Repl] Plugin group_replication reported: 'This server is working as primary member.'
2023-10-24T23:28:19.875216Z 12 [System] [MY-014010] [Repl] Plugin group_replication reported: 'Plugin 'group_replication' has been started.'                            
```
</details>

## Log rotation configuration

Following the configuration options exposed by the charm:

| Configuration option | Description | Default value |
| --- | --- | --- |
| `plugin-audit-enabled` | Enable or disable the audit log | `true` |
| `logs_audit_policy` | The audit log policy ("all", "logins", "queries") | `logins` |
| `logs_retention_period` | The number of days to keep the rotated logs | `auto` |

The `logs_retention_period` option accepts an integer value of 3 or greater, or the special value
`auto`. When set to "auto" (default), the retention period is 3 days, except when COS-related,
where it is 1 day

For each log (audit, error):

- The log file is rotated every minute (even if the log files are empty)
- The rotated log file is formatted with a date suffix of `-%V-%H%M` (-weeknumber-hourminute)
- The rotated log files are compressed but not mailed
- The rotated log files are owned by the `snap_daemon` user and group
- By default the rotated log files are retained for 3 days before being deleted, but this can be configured.

The following are logrotate config values used for log rotation:

| Option | Value |
| --- | --- |
| `su` | snap_daemon snap_daemon |
| `createoldddir` | 770 snap_daemon snap_daemon |
| `hourly` | true |
| `maxage` | 7 |
| `rotate` | 10080 |
| `dateext` | true |
| `dateformat` | -%V-%H%M |
| `ifempty` | true |
| `missingok` | true |
| `compress` | true |
| `nomail` | true |
| `nosharedscripts` | true |
| `nocopytruncate` | true |
| `olddir` | archive_<log_name> |

## High Level Design

There is a cron job on the machine where the charm exists that is triggered every minute and runs `logrotate`. The logrotate utility does *not* use `copytruncate`. Instead, the existing log file is moved into the archive directory by logrotate, and then the logrotate's postrotate script invokes `juju-run` (or `juju-exec` depending on the juju version) to dispatch a custom event. This custom event's handler flushes the MySQL log with the [FLUSH](https://dev.mysql.com/doc/refman/8.0/en/flush.html) statement that will result in a new and empty log file being created under `/var/log/mysql` and the rotated file's descriptor being closed.

We use a custom event in juju to execute the FLUSH statement in order to avoid storing any credentials on the disk. The charm code has a mechanism that will retrieve credentials from the peer relation databag or juju secrets backend, if available, and keep these credentials in memory for the duration of the event handler.


<!-- LINKS -->

[COS integration]: /how-to/monitoring-cos/enable-monitoring
[Audit Logs explanation]: /explanation/logs/audit-logs


```{toctree}
:titlesonly:
:maxdepth: 2
:glob:
:hidden:

*
```
