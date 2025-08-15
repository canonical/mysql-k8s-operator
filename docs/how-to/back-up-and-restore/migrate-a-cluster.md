# How to migrate a cluster

This guide describes how to restore a backup that was made from a different cluster, (i.e. cluster migration via restore).

```{seealso}
To perform a basic restore from a *local* backup, see [](/how-to/back-up-and-restore/restore-a-backup).
```

## Prerequisites

- Have a single unit Charmed MySQL deployed and running
- Access to S3 storage
- [Have configured settings for S3 storage](/how-to/back-up-and-restore/configure-s3-aws.md)
- Have the backups from the previous cluster in your S3-storage
- Have the passwords from your previous cluster

---

## Manage cluster passwords

When you restore a backup from an old cluster, it will restore the password from the previous cluster to your current cluster. 

Set the password of your current cluster to the previous cluster’s password:

```shell
juju run mysql-k8s/leader set-password username=root password=<previous cluster password>
juju run mysql-k8s/leader set-password username=clusteradmin password=<previous cluster password>
juju run mysql-k8s/leader set-password username=serverconfig password=<previous cluster password>
```

## List backups

To view the available backups to restore you can enter the command `list-backups`:

```shell
juju run mysql-k8s/leader list-backups
```

This shows a list of the available backups (it is up to you to identify which `backup-id` corresponds to the previous-cluster):

```shell
backups: |-
  backup-id             | backup-type  | backup-status
  ----------------------------------------------------
  YYYY-MM-DDTHH:MM:SSZ  | physical     | finished
```

## Restore a backup

To restore your current cluster to the state of the previous cluster, run the `restore` command and pass the correct `backup-id` to the command:

 ```shell
juju run mysql-k8s/leader restore backup-id=YYYY-MM-DDTHH:MM:SSZ
```

Your restore will then be in progress, once it is complete your cluster will represent the state of the previous cluster.