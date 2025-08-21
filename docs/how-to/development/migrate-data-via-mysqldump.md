# Migrate database data via `mysqldump`

This guide describes how to copy data:
* from a legacy MySQL K8s charm to a modern MySQL K8s charm
* from a modern MySQL K8s charm to a different installation of the same modern MySQL K8s charm. 

Note that this guide describes how to migrate database **data** only.

For information about integrating your charm with a MySQL database, see [How to integrate a database with my charm](/how-to/development/integrate-with-your-charm).

```{seealso}
[How to migrate data via `mydumper`](/how-to/development/migrate-data-via-mydumper)

[How to migrate data via backup/restore](/how-to/development/migrate-data-via-backup-restore) (recommended for migrations between modern charms)
```

## Do you need to migrate?

Legacy MariaDB/MySQL charms for **Kubernetes**:

* [OSM MariaDB K8s](https://charmhub.io/charmed-osm-mariadb-k8s)

Legacy MariaDB/MySQL charms for **machines**:

* [MariaDB](https://charmhub.io/mariadb)
* [Percona Cluster](https://charmhub.io/percona-cluster)
* [MySQL InnoDB Cluster](https://charmhub.io/mysql-innodb-cluster)

See the [`mysqldump` guide for Charmed MySQL VM](https://canonical-charmed-mysql.readthedocs-hosted.com/how-to/development/migrate-data-via-mysqldump/)


To check if a database migration is required, run the following commands, where `DB_CHARM` is the name of your legacy database application:

```shell
DB_CHARM= < mydb | charmed-osm-mariadb-k8s >
juju show-application ${DB_CHARM} | yq '.[] | .charm'
```

No migration is necessary if the output above is `mysq-k8s`.

## Prepare

Before migrating data:
* check all [limitations of the modern Charmed MySQL](/reference/system-requirements) charm
* check [your application's compatibility](/explanation/legacy-charm) with Charmed MySQL

```{caution}
Always perform the migration in a test environment before performing it in production!
```

## Prerequisites

- Client machine with access to deployed legacy charm
- Juju 2.9 or later
  - See the [Juju explanation](/explanation/juju) for more details
- Enough storage in the cluster to support backup/restore of the databases
- `mysql-client` on client machine (install by running `sudo apt install mysql-client`)

```{caution}
Most legacy database charms support old Ubuntu series only, while [Juju 3.x does NOT support Ubuntu Bionic](https://documentation.ubuntu.com/juju/3.6/reference/juju/juju-roadmap-and-releases/#juju-3-0-0-22-oct-2022).

It is recommended to use the latest stable revision of the charm on Ubuntu Jammy and Juju 3.x
```

(mysqldump-obtain-existing-database-credentials)=
## Obtain existing database credentials

Set `DB_APP` to the name of the desired unit: 

```shell
DB_APP= < mydb/0 | charmed-osm-mariadb-k8s/0 >
```

Get username and password of the existing legacy database from the database relation. The username is usually `root`, and the password is specified in the `mysql` relation by `root_password`:

```shell
OLD_DB_RELATION_ID=$(juju show-unit ${DB_APP} | yq '.[] | .relation-info | select(.[].endpoint == "mysql") | .[0] | .relation-id')

OLD_DB_USER=root

OLD_DB_PASS=$(bash -c "juju run --unit ${DB_APP} 'relation-get -r ${OLD_DB_RELATION_ID} - ${DB_APP}' | grep root_password" | awk '{print $2}')

OLD_DB_IP=$(juju show-unit ${DB_APP} | yq '.[] | .address')
```

## Deploy new MySQL databases and obtain credentials

Deploy new MySQL databases. In this example, 3 units are deployed:

```shell
juju deploy mysql-k8s --trust --channel 8.0/stable -n 3
```

Obtain credentials for each new database by executing the following commands, once per database:

```shell
NEW_DB_USER=$(juju run mysql-k8s/leader get-password | yq '.username')
NEW_DB_PASS=$(juju run mysql-k8s/leader get-password | yq '.password')
NEW_DB_IP=$(juju show-unit mysql-k8s/0 | yq '.[] | .address')
```

## Migrate database

The next step is to use the credentials and information obtained in previous steps to perform the database migration.

First, ensure that there are no new connections are made and that database is not altered.

Remove the relation between your charm and the legacy MySQL charm:

```shell
juju remove-relation <your_charm> <mydb | charmed-osm-mariadb-k8s>
```

Connect to the legacy database to verify the connection:

```shell
mysql \
  --host=${OLD_DB_IP} \
  --user=${OLD_DB_USER} \
  --password=${OLD_DB_PASS} \
  -e "show databases"
```

Choose which databases to dump/migrate to the new charm (one by one!)

```shell
DB_NAME=< e.g. wordpress >
```

Create a backup of each database file using the `mysqldump` utility, username, password, and unit's IP address, obtained earlier. This will create a dump that can be used to restore the database.

```shell
OLD_DB_DUMP="legacy-mysql-${DB_NAME}.sql"

mysqldump \
  --host=${OLD_DB_IP} \
  --user=${OLD_DB_USER} \
  --password=${OLD_DB_PASS} \
  --column-statistics=0 \
  --databases ${OLD_DB_NAME} \
  > "${OLD_DB_DUMP}"
```

Connect to the new database using username, password, and unit's IP address, and restore database from backup:

```shell
mysql \
  --host=${NEW_DB_IP} \
  --user=${NEW_DB_USER} \
  --password=${NEW_DB_PASS} \
  < "${OLD_DB_DUMP}"
```

## Integrate with modern charm

Integrate your application and new MySQL database charm (using the `database` or `mysql` endpoint):

```shell
juju integrate <your_application> mysql-k8s:database
```

If the `mysql_client` interface is not yet supported, use the legacy mysql interface:

```shell
juju integrate <your_application> mysql-k8s:mysql
```

## Verify database migration

Create a dump for the new MySQL database and compare it to the backup created earlier:

```shell
NEW_DB_DUMP="new-mysql-${DB_NAME}.sql"

mysqldump \
  --host=${NEW_DB_IP} \
  --user=${NEW_DB_USER} \
  --password=${NEW_DB_PASS} \
  --column-statistics=0 \
  --databases ${DB_NAME}  \
  > "${NEW_DB_DUMP}"

diff "${OLD_DB_DUMP}" "${NEW_DB_DUMP}"
```

```{note}
Some variables will vary between legacy and modern charms, namely: `${NEW_DB_PASS}` and `${NEW_DB_IP}`. These must be adjusted for the correct database, accordingly.
```

The difference between two SQL backup files should be limited to server versions, IP addresses, timestamps and other non data related information.

````{dropdown} Example

```shell
diff "${OLD_DB_DUMP}" "${NEW_DB_DUMP}"
```

Output:

```text
< -- Host: 10.1.45.226    Database: katib
---
> -- Host: 10.1.46.40    Database: katib
5c5
< -- Server version	5.5.5-10.3.17-MariaDB-1:10.3.17+maria~bionic
---
> -- Server version	8.0.34-0ubuntu0.22.04.1
16a17,26
> SET @MYSQLDUMP_TEMP_LOG_BIN = @@SESSION.SQL_LOG_BIN;
> SET @@SESSION.SQL_LOG_BIN= 0;
> 
> --
> -- GTID state at the beginning of the backup 
> --
> 
> SET @@GLOBAL.GTID_PURGED=/*!80000 '+'*/ '0d3210b9-587f-11ee-acf3-b26305f815ec:1-4,
> 34442d83-587f-11ee-84f5-b26305f815ec:1-85,
> 34444583-587f-11ee-84f5-b26305f815ec:1';
22c32
< CREATE DATABASE /*!32312 IF NOT EXISTS*/ `katib` /*!40100 DEFAULT CHARACTER SET latin1 */;
---
> CREATE DATABASE /*!32312 IF NOT EXISTS*/ `katib` /*!40100 DEFAULT CHARACTER SET latin1 */ /*!80016 DEFAULT ENCRYPTION='N' */;
34c44
<   `id` int(11) NOT NULL,
---
>   `id` int NOT NULL,
60c70
<   `id` int(11) NOT NULL AUTO_INCREMENT,
---
>   `id` int NOT NULL AUTO_INCREMENT,
75a86
> SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
86c97
< -- Dump completed on 2023-09-21 17:05:54
---
> -- Dump completed on 2023-09-21 17:09:40
```
````

## Remove old databases

Test your application and if you are happy with a data migration, do not forget to remove legacy charms to keep the house clean:

```shell
juju remove-application --destroy-storage < mydb | charmed-osm-mariadb-k8s >
```