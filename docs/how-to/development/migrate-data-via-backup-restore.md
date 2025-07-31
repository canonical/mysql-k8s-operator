
# DB data migration using ‘backup/restore’

> :information_source: **Tip**: use ['mysqldump' manual](/how-to/development/migrate-data-via-mysqldump) to migrate [legacy charms](/explanation/legacy-charm) data.

This Charmed MySQL K8s operator is able to restore [it's own backups](/how-to/back-up-and-restore/restore-a-backup) stored on [S3-compatible storage](/how-to/back-up-and-restore/configure-s3-aws). The same restore approach is applicable to restore [foreign backups](/how-to/back-up-and-restore/migrate-a-cluster) made by different Charmed MySQL installation or even another MySQL charms. The backup have to be created manually using Percona XtraBackup!

> :warning: Canonical Data team describes here the general approach and does NOT support nor guaranties the restoration results. Always test migration in LAB before performing it in Production!

Before the data migration check all [limitations of the modern Charmed MySQL K8s](/reference/system-requirements) charm!<br/>Please check [your application compatibility](/explanation/legacy-charm) with Charmed MySQL K8s before migrating production data from legacy charm!

The approach:

* retrieve root/admin level credentials from legacy charm. See examples [here](/how-to/development/migrate-data-via-mysqldump).
* install [Percona XtraBackup for MySQL](https://www.percona.com/software/mysql-database/percona-xtrabackup) inside the old charm OR remotely. Ensure version is compatible with xtrabackup in `Charmed MySQL K8s` revision you are going to deploy! See [examples](https://docs.percona.com/percona-xtrabackup/8.0/installation.html). BTW, you can use `charmed-mysql` [SNAP](https://snapcraft.io/charmed-mysql)/[ROCK](https://github.com/canonical/charmed-mysql-rock) directly (more details [here](/explanation/architecture)).
* configure storage for database backup (local or remote, S3-based is recommended).
* create a first full logical backup during the off-peak, [example of backup command](https://github.com/canonical/mysql-k8s-operator/blob/bc5f255e579033e2d501c3412d87913593ad62a3/lib/charms/mysql/v0/mysql.py#L2160-L2185).
* [restore the foreign backup](/how-to/back-up-and-restore/migrate-a-cluster) to Charmed MySQL Lab installation.
* perform all the necessary tests to make sure your application accepted new DB.
* schedule and perform the final production migration re-using the last steps above.

Do you have questions? [Contact us](https://chat.charmhub.io/charmhub/channels/data-platform) if you are interested in such a data migration!

