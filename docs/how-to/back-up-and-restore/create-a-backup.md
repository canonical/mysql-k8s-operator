# How to create and list backups

This guide contains recommended steps and useful commands for creating and managing backups to ensure smooth restores.

## Prerequisites
* A [deployed](/how-to/scale-replicas) MySQL K8s cluster
* Access to S3 storage
* [Configured settings for S3 storage](/how-to/back-up-and-restore/configure-s3-aws)

---

## Create a backup

Once `juju status` shows Charmed MySQL K8s as `active` and `idle` you can create your first backup with the `create-backup` command:
```shell
juju run mysql-k8s/leader create-backup
```

If you have a cluster of one unit, you can run the `create-backup` action on the leader (which will also be the primary unit).
Otherwise, you must run the `create-backup` action on a non-primary unit. To find the primary, see `juju status` or
run `juju run mysql-k8s/leader get-cluster-status` to find the primary unit.

The `create-backup` action validates that the unit in charge of the backup is healthy, by:
- Checking that the MySQL cluster is in a valid state (`OK` or `OK_PARTIAL` from the InnoDB [cluster status](https://dev.mysql.com/doc/mysql-shell/8.0/en/monitoring-innodb-cluster.html))
- Checking that the MySQL instance is in a valid state (`ONLINE` from Replication [member states](https://dev.mysql.com/doc/refman/8.0/en/group-replication-server-states.html).

In order to override these precautions, use the `force` flag:
```shell
juju run mysql-k8s/leader create-backup force=True
```

## List backups

You can list your available, failed, and in progress backups by running the `list-backups` command:
```shell
juju run mysql-k8s/leader list-backups
```

