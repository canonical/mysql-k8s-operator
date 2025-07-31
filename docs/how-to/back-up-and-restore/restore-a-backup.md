```{note}
**Note**: All commands are written for `juju >= v3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#juju-3-0-0---22-oct-2022).
```

# How to restore a backup

This is a How-To for performing a basic restore (restoring a locally made backup).
To restore a backup that was made from the a *different* cluster, (i.e. cluster migration via restore), please reference the [Cluster Migration via Restore How-To](/):

## Prerequisites

- [Scale-down to the single MySQL unit (scale it up after the backup is restored).](/)
- Access to S3 storage
- [Have configured settings for S3 storage](/)
- [Have existing backups in your S3-storage](/)
- Point-in-time recovery requires the following MySQL K8s charm revisions:
  * 248+ for arm64
  * 249+ for amd64

## List backups

To view the available backups to restore you can enter the command `list-backups`:
```shell
juju run mysql-k8s/leader list-backups
```

This should show your available backups
```shell
    backups: |-
      backup-id             | backup-type  | backup-status
