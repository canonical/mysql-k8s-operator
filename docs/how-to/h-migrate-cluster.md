[note]
**Note**: All commands are written for `juju >= v.3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# How to migrate a cluster

This is a guide on how to restore a backup that was made from a different cluster, (i.e. cluster migration via restore).

To perform a basic restore please reference the [Restore How-To](/t/charmed-mysql-k8s-how-to-restore-backup/9663).

## Prerequisites
Restoring a backup from a previous cluster to a current cluster requires that you:
- Have a single unit Charmed MySQL deployed and running
- Access to S3 storage
- [Have configured settings for S3 storage](/t/charmed-mysql-k8s-how-to-configure-s3/9651)
- Have the backups from the previous cluster in your S3-storage
- Have the passwords from your previous cluster

---

<a href="#heading--manage-cluster-passwords"><h2 id="heading--manage-cluster-passwords">Manage cluster passwords</h2></a>
When you restore a backup from an old cluster, it will restore the password from the previous cluster to your current cluster. Set the password of your current cluster to the previous cluster’s password:
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

## Restore backup
To restore your current cluster to the state of the previous cluster, run the `restore` command and pass the correct `backup-id` to the command:
 ```shell
juju run mysql-k8s/leader restore backup-id=YYYY-MM-DDTHH:MM:SSZ
```

Your restore will then be in progress, once it is complete your cluster will represent the state of the previous cluster.