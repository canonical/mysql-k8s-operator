# How to create and list backups

Creating and listing backups requires that you:
* [Have a Charmed MySQL K8s deployed](/t/charmed-mysql-k8s-how-to-manage-units/9659)
* Access to S3 storage
* [Have configured settings for S3 storage](/t/charmed-mysql-k8s-how-to-configure-s3/9651)

Once Charmed MySQL K8s is `active` and `idle` (check `juju status`), you can create your first backup with the `create-backup` command:
```shell
juju run-action mysql-k8s/leader create-backup --wait
```

[note]
If you have a cluster of one unit, you can run the `create-backup` action on `mysql-k8s/leader` (which will also be the primary unit). 

Otherwise, you must run the `create-backup` action on a non-primary unit (see `juju status` or run `juju run-action mysql-k8s/leader get-cluster-status` to find the primary unit).
[/note]

You can list your available, failed, and in progress backups by running the `list-backups` command:
```shell
juju run-action mysql-k8s/leader list-backups --wait
```