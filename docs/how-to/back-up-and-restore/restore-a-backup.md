# How to restore a local backup

This is a guide for performing a basic restore (restoring a locally made backup).

To restore a backup that was made from the a *different* cluster, (i.e. cluster migration via restore), see [](/how-to/back-up-and-restore/migrate-a-cluster).

## Prerequisites

- [Scale-down to the single MySQL unit (scale it up after the backup is restored).](/how-to/scale-replicas)
- Access to S3 storage
- [Have configured settings for S3 storage](/how-to/back-up-and-restore/configure-s3-aws)
- [Have existing backups in your S3-storage](/how-to/back-up-and-restore/create-a-backup)
- Point-in-time recovery requires the following MySQL K8s charm revisions:
  * rev248+ for `arm64`
  * rev249+ for `amd64`

## List backups

To view the available backups to restore you can enter the command `list-backups`:

```shell
juju run mysql-k8s/leader list-backups
```

This should show your available backups
```shell
backups: |-
  backup-id             | backup-type  | backup-status
  ----------------------------------------------------
  YYYY-MM-DDTHH:MM:SSZ  | physical     | finished
```

(point-in-time-recovery)=
## Point-in-time recovery

Point-in-time recovery (PITR) is a MySQL feature that enables restorations to the database state at specific points in time. The feature is enabled by default when there's a working relation with S3 storage.

## Restore a backup

To restore a backup from that list, run the `restore` command and pass the `backup-id` to restore:

 ```shell
juju run mysql-k8s/leader restore backup-id=YYYY-MM-DDTHH:MM:SSZ
```

Your restore will then be in progress.

However, if the user needs to restore to a specific point in time between different backups (e.g. to restore only specific transactions made between those backups), they can use the restore-to-time parameter to pass a timestamp related to the moment they want to restore.

 ```shell
juju run mysql-k8s/leader restore restore-to-time="YYYY-MM-DD HH:MM:SS"
```

Your restore will then be in progress.

It’s also possible to restore to the latest point from a specific timeline by passing the ID of a backup taken on that timeline and restore-to-time=latest when requesting a restore:

 ```shell
juju run mysql-k8s/leader restore restore-to-time=latest
```

