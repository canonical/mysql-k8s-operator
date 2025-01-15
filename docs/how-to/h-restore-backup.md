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

## Summary

* [List backups](#list-backups)
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

## Restore backup

To restore a backup from that list, run the `restore` command and pass the `backup-id` to restore:
 ```shell
juju run mysql-k8s/leader restore backup-id=YYYY-MM-DDTHH:MM:SSZ
```

Your restore will then be in progress.