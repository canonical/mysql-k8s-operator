# Migrate data via backup/restore

Charmed MySQL K8s is able to restore [its own backups](/how-to/back-up-and-restore/restore-a-backup) stored on [S3-compatible storage](/how-to/back-up-and-restore/configure-s3-aws). 

The same restore approach is applicable to restore [external backups](/how-to/back-up-and-restore/migrate-a-cluster) made by a different Charmed MySQL installation, or even another MySQL charm. (Note that, in this case, the backup must be created manually using Percona XtraBackup)

```{seealso}
For data stored in [legacy charms](/explanation/legacy-charm), see [How to migrate data via `mysqldump`](/how-to/development/migrate-data-via-mysqldump)
```

## Prepare

Before migrating data:
* check all [limitations of the modern Charmed MySQL](/reference/system-requirements) charm
* check [your application's compatibility](/explanation/legacy-charm) with Charmed MySQL

## Migrate via backup/restore

The approach described below is a general recommendation, but we **cannot guarantee restoration results**. [Contact us](/reference/contacts) if you have any doubts about data migration/restoration.

And, as always, try it out in a test environment before migrating in production!

* Retrieve root/admin level credentials from legacy charm.
  * Example: [](mysqldump-obtain-legacy-credentials)
* Install [Percona XtraBackup](https://www.percona.com/software/mysql-database/percona-xtrabackup) inside the old charm OR remotely.
  * Ensure the version is compatible with xtrabackup in `Charmed MySQL` revision you are going to deploy. See [installation examples](https://docs.percona.com/percona-xtrabackup/8.0/installation.html).
  * You can also use the [`charmed-mysql` snap](https://snapcraft.io/charmed-mysql) or [rock](https://github.com/canonical/charmed-mysql-rock) directly. For more details, see [](/explanation/architecture).
* Configure storage for database backup
  * S3-based is recommended. See [](/how-to/back-up-and-restore/configure-s3-aws)
* Create a first full logical backup during the off-peak
  * [Example of backup command](https://github.com/canonical/mysql-k8s-operator/blob/bc5f255e579033e2d501c3412d87913593ad62a3/lib/charms/mysql/v0/mysql.py#L2160-L2185).  <!--TODO: probably incorrect, better to hardcode example in docs -->
* Restore the external backup to a Charmed MySQL installation in a test environment
  * See [](/how-to/back-up-and-restore/migrate-a-cluster)
* Test your application to make sure it accepted the new database
* Schedule and perform the final production migration

Do you have questions? [Contact us](/reference/contacts) if you are interested in such a data migration!

