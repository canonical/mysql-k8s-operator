# Log rotation

## Overview

The charm stores its logs in `/var/log/mysql`.

```
root@mysql-k8s-0:/# ls -lahR /var/log/mysql
/var/log/mysql:
total 28K
drwxr-xr-x 1 mysql mysql 4.0K Oct 23 20:46 .
drwxr-xr-x 1 root root 4.0K Sep 27 20:55 ..
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:46 archive_error
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:46 archive_general
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:45 archive_slowquery
-rw-r----- 1 mysql mysql 0 Oct 23 20:46 error.log
-rw-r----- 1 mysql mysql 1.7K Oct 23 20:46 general.log

/var/log/mysql/archive_error:
total 20K
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:46 .
drwxr-xr-x 1 mysql mysql 4.0K Oct 23 20:46 ..
-rw-r----- 1 mysql mysql 8.7K Oct 23 20:44 error.log-43_2045
-rw-r----- 1 mysql mysql 0 Oct 23 20:45 error.log-43_2046

/var/log/mysql/archive_general:
total 8.0M
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:46 .
drwxr-xr-x 1 mysql mysql 4.0K Oct 23 20:46 ..
-rw-r----- 1 mysql mysql 8.0M Oct 23 20:45 general.log-43_2045
-rw-r----- 1 mysql mysql 4.6K Oct 23 20:46 general.log-43_2046

/var/log/mysql/archive_slowquery:
total 8.0K
drwxrwx--- 2 mysql mysql 4.0K Oct 23 20:45 .
drwxr-xr-x 1 mysql mysql 4.0K Oct 23 20:46 ..
```

The following is a sample of the error logs, with format `time thread [label] [err_code] [subsystem] msg`:

```
2023-10-23T11:57:44.924594Z 0 [System] [MY-013169] [Server] /usr/sbin/mysqld (mysqld 8.0.34-0ubuntu0.22.04.1) initializing of server in progress as process 16                                              
2023-10-23T11:57:44.935004Z 1 [System] [MY-013576] [InnoDB] InnoDB initialization has started.         
2023-10-23T11:57:50.420672Z 1 [System] [MY-013577] [InnoDB] InnoDB initialization has ended.         
2023-10-23T11:57:54.614751Z 6 [Warning] [MY-010453] [Server] root@localhost is created with an empty password ! Please consider switching off the --initialize-insecure option.                             
2023-10-23T11:57:59.690483Z mysqld_safe Logging to '/var/log/mysql/error.log'.                      
2023-10-23T11:57:59.710530Z mysqld_safe Starting mysqld daemon with databases from /var/lib/mysql   
2023-10-23T11:58:00.049606Z 0 [Warning] [MY-010101] [Server] Insecure configuration for --secure-file-priv: Location is accessible to all OS users. Consider choosing a different directory.                
2023-10-23T11:58:00.049702Z 0 [System] [MY-010116] [Server] /usr/sbin/mysqld (mysqld 8.0.34-0ubuntu0.22.04.1) starting as process 285                                                                       
2023-10-23T11:58:00.061489Z 1 [System] [MY-013576] [InnoDB] InnoDB initialization has started.        
2023-10-23T11:58:04.897561Z 1 [System] [MY-013577] [InnoDB] InnoDB initialization has ended.       
2023-10-23T11:58:05.224159Z 0 [Warning] [MY-010068] [Server] CA certificate ca.pem is self signed.  
2023-10-23T11:58:05.224220Z 0 [System] [MY-013602] [Server] Channel mysql_main configured to support TLS. Encrypted connections are now supported for this channel.                                         
2023-10-23T11:58:05.236134Z 0 [Warning] [MY-011810] [Server] Insecure configuration for --pid-file: Location '/var/lib/mysql' in the path is accessible to all OS users. Consider choosing a different direc
tory.                                                                                               
2023-10-23T11:58:05.269381Z 0 [System] [MY-011323] [Server] X Plugin ready for connections. Bind-address: '0.0.0.0' port: 33060, socket: /var/run/mysqld/mysqlx.sock                                        
2023-10-23T11:57:44.924594Z 0 [System] [MY-013169] [Server] /usr/sbin/mysqld (mysqld 8.0.34-0ubuntu0.22.04.1) initializing of server in progress as process 16                                              
2023-10-23T11:57:44.935004Z 1 [System] [MY-013576] [InnoDB] InnoDB initialization has started.         
2023-10-23T11:57:50.420672Z 1 [System] [MY-013577] [InnoDB] InnoDB initialization has ended.         
2023-10-23T11:57:54.614751Z 6 [Warning] [MY-010453] [Server] root@localhost is created with an empty password ! Please consider switching off the --initialize-insecure option.                             
2023-10-23T11:57:59.690483Z mysqld_safe Logging to '/var/log/mysql/error.log'.                      
2023-10-23T11:57:59.710530Z mysqld_safe Starting mysqld daemon with databases from /var/lib/mysql   
2023-10-23T11:58:00.049606Z 0 [Warning] [MY-010101] [Server] Insecure configuration for --secure-file-priv: Location is accessible to all OS users. Consider choosing a different directory.                
2023-10-23T11:58:00.049702Z 0 [System] [MY-010116] [Server] /usr/sbin/mysqld (mysqld 8.0.34-0ubuntu0.22.04.1) starting as process 285                                                                       
2023-10-23T11:58:00.061489Z 1 [System] [MY-013576] [InnoDB] InnoDB initialization has started.        
2023-10-23T11:58:04.897561Z 1 [System] [MY-013577] [InnoDB] InnoDB initialization has ended.       
2023-10-23T11:58:05.224159Z 0 [Warning] [MY-010068] [Server] CA certificate ca.pem is self signed.  
2023-10-23T11:58:05.224220Z 0 [System] [MY-013602] [Server] Channel mysql_main configured to support TLS. Encrypted connections are now supported for this channel.                                         
2023-10-23T11:58:05.236134Z 0 [Warning] [MY-011810] [Server] Insecure configuration for --pid-file: Location '/var/lib/mysql' in the path is accessible to all OS users. Consider choosing a different direc
tory.                                                                                               
2023-10-23T11:58:05.269381Z 0 [System] [MY-011323] [Server] X Plugin ready for connections. Bind-address: '0.0.0.0' port: 33060, socket: /var/run/mysqld/mysqlx.sock                                        
```

The following is a sample of the general logs, with format `time thread_id command_type query_body`:

```
Time                 Id Command    Argument                                                          
2023-10-23T20:50:02.023329Z        94 Quit                                                        
2023-10-23T20:50:02.667063Z        95 Connect                                                       
2023-10-23T20:50:02.667436Z        95 Query     /* xplugin authentication */ SELECT /*+ SET_VAR(SQL_MODE = 'TRADITIONAL') */ @@require_secure_transport, `authentication_string`, `plugin`, (`account_locked
`='Y') as is_account_locked, (`password_expired`!='N') as `is_password_expired`, @@disconnect_on_expired_password as `disconnect_on_expired_password`, @@offline_mode and (`Super_priv`='N') as `is_offline_
mode_and_not_super_user`, `ssl_type`, `ssl_cipher`, `x509_issuer`, `x509_subject` FROM mysql.user WHERE 'serverconfig' = `user` AND '%' = `host`                                                            
2023-10-23T20:50:02.668277Z        95 Query     /* xplugin authentication */ SELECT /*+ SET_VAR(SQL_MODE = 'TRADITIONAL') */ @@require_secure_transport, `authentication_string`, `plugin`, (`account_locked
`='Y') as is_account_locked, (`password_expired`!='N') as `is_password_expired`, @@disconnect_on_expired_password as `disconnect_on_expired_password`, @@offline_mode and (`Super_priv`='N') as `is_offline_
mode_and_not_super_user`, `ssl_type`, `ssl_cipher`, `x509_issuer`, `x509_subject` FROM mysql.user WHERE 'serverconfig' = `user` AND '%' = `host`                                                            
2023-10-23T20:50:02.668778Z        95 Query     select @@lower_case_table_names, @@version, connection_id(), variable_value from performance_schema.session_status where variable_name = 'mysqlx_ssl_cipher'
2023-10-23T20:50:02.669991Z        95 Query     SET sql_log_bin = 0                       
2023-10-23T20:50:02.670389Z        95 Query     FLUSH SLOW LOGS                              
2023-10-23T20:50:02.670924Z        95 Quit  
```

The following is a sample of the slowquery log:

```
Time                 Id Command    Argument
# Time: 2023-10-23T22:22:47.564327Z
# User@Host: serverconfig[serverconfig] @ localhost [127.0.0.1]  Id:    21
# Query_time: 15.000332  Lock_time: 0.000000 Rows_sent: 0  Rows_examined: 1
SET timestamp=1698099752;
do sleep(15);
```

The charm currenly has error and general logs enabled by default, while slow query logs are disabled by default. All of these files are rotated if present into a separate dedicated archive folder under the logs directory.

We do not yet support the rotation of binary logs (binlog, relay log, undo log, redo log, etc).

## Log Rotation Configurations

For each log (error, general and slow query):

- The log file is rotated every minute (even if the log files are empty)
- The rotated log file is formatted with a date suffix of `-%V-%H%M` (-weeknumber-hourminute)
- The rotated log files are not compressed or mailed
- The rotated log files are owned by the `snap_daemon` user and group
- The rotated log files are retained for a maximux of 7 days before being deleted
- The most recent 10080 rotated log files are retained before older rotated log files are deleted

The following are logrotate config values used for log rotation:

| Option | Value |
| --- | --- |
| su | snap_daemon snap_daemon |
| createoldddir | 770 snap_daemon snap_daemon |
| hourly | true |
| maxage | 7 |
| rotate | 10080 |
| dateext | true |
| dateformat | -%V-%H%M |
| ifempty | true |
| missingok | true |
| nocompress | true |
| nomail | true |
| nosharedscripts | true |
| nocopytruncate | true |
| olddir | archive_error / archive_general / archive_slowquery |

## HLD (High Level Design)

There is a cron job on the machine where the charm exists that is triggered every minute and runs `logrotate`. The logrotate utility does *not* use `copytruncate`. Instead, the existing log file is moved into the archive directory by logrotate, and then the logrotate's postrotate script invokes `juju-run` (or `juju-exec` depending on the juju version) to dispatch a custom event. This custom event's handler flushes the MySQL log with the [FLUSH](https://dev.mysql.com/doc/refman/8.0/en/flush.html) statement that will result in a new and empty log file being created under `/var/snap/charmed-mysql/common/var/log/mysql` and the rotated file's descriptor being closed.

We use a custom event in juju to execute the FLUSH statement in order to avoid storing any credentials on the disk. The charm code has a mechanism that will retrieve credentials from the peer relation databag or juju secrets backend, if available, and keep these credentials in memory for the duration of the event handler.