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

If you have a cluster of one unit, you can run the `create-backup` action on `mysql-k8s/leader` (which will also be the primary unit). 

Otherwise, you must run the `create-backup` action on a non-primary unit (see `juju status` or run `juju run-action mysql-k8s/leader get-cluster-status` to find the primary unit).

## List backups

You can list your available, failed, and in progress backups by running the `list-backups` command:
```shell
juju run mysql-k8s/leader list-backups
```

