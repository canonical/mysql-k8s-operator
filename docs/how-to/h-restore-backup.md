[note]
**Note**: All commands are written for `juju >= v3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# How to restore backup

This is a How-To for performing a basic restore (restoring a locally made backup).
To restore a backup that was made from the a *different* cluster, (i.e. cluster migration via restore), please reference the [Cluster Migration via Restore How-To](/t/charmed-mysql-k8s-how-to-migrate-cluster-via-restore/9661):

## Prerequisites

- [Scale-down to the single MySQL unit (scale it up after the backup is restored).](/t/charmed-mysql-k8s-how-to-manage-units/9659)
- Access to S3 storage
- [Have configured settings for S3 storage](/t/charmed-mysql-k8s-how-to-configure-s3/9651)
- [Have existing backups in your S3-storage](/t/charmed-mysql-k8s-how-to-create-and-list-backups/9653)
- Point-in-time recovery requires the following MySQL K8s charm revisions:
  * 248+ for arm64
  * 249+ for amd64


## Summary

* [List backups](#list-backups)
* [Point-in-time recovery](#point-in-time-recovery)
* [Restore backup](#restore-backup)

---

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

## Point-in-time recovery

Point-in-time recovery (PITR) is a MySQL K8s feature that enables restorations to the database state at specific points in time. The feature is enabled by default when there’s a working relation with S3 storage.

## Restore backup

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