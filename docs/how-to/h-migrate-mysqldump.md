[note]
**Note**: All commands are written for `juju >= v.3.0`

For more information, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Migrate database data via `mysqldump`

This document describes database **data** migration only!

> For information about integrating charms via juju interfaces, see [How to integrate a database with my charm](/t/11885).

The list of MariaDB/MySQL **legacy VM charms**:

* [OSM MarkiaDB K8s](https://charmhub.io/charmed-osm-mariadb-k8s)
* <s>[MariaDB](https://charmhub.io/mariadb)</s> (machine charm, use [separate manual](https://charmhub.io/mysql/docs/h-develop-mysqldump))
* <s>[Percona Cluster](https://charmhub.io/percona-cluster)</s> (machine charm, use [separate manual](https://charmhub.io/mysql/docs/h-develop-mysqldump))
* <s>[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)</s> (machine charm, use [separate manual](https://charmhub.io/mysql/docs/h-develop-mysqldump))

The minor difference in commands necessary for each of the legacy charm, but the general logic is common:

* deploy the modern charm nearby
* request credentials from legacy charm
* remove relation to legacy charm (to stop data changes)
* perform legacy DB dump (using the credentials above)
* upload the legacy charm dump into the modern charm
* add relation to modern charm
* validate results and remove legacy charm

Before the data migration check all [limitations of the modern Charmed MySQL K8s](/t/11421#mysql-gr-limits) charm!<br/>Please check [your application compatibility](/t/11236) with Charmed MySQL K8s before migrating production data from legacy charm!

> :warning: Always perform the migration in a test environment before performing it in production!

## Do you need to migrate?

A database migration is only required if the output of the following command is NOT `mysql-k8s`:

```shell
# replace DB_CHARM with your legacy DB application name
DB_CHARM= < mydb | charmed-osm-mariadb-k8s >
juju show-application ${DB_CHARM} | yq '.[] | .charm'
```
[note type=caution]
No migration is necessary if the output above is `mysql-k8s`! 

Still, this manual can be used to copy data between different installations of the same (modern) charm `mysql-k8s`. The [backup/restore method](/t/9653) is recommended for migrations between modern charms.
[/note]

## Prerequisites

- Client machine with access to deployed legacy charm
- Juju version 2.9+  (check the [Juju tech details](/t/11984) for the different Juju versions)
- Enough storage in the cluster to support backup/restore of the databases.
- `mysql-client` on client machine (install by running `sudo apt install mysql-client`).

[note type=caution]
Most legacy database charms support old Ubuntu series only, while Juju 3.x does [NOT support](https://discourse.charmhub.io/t/roadmap-releases/5064#heading--juju-3-0-0---22-oct-2022) Ubuntu Bionic.

It is recommended to use the latest stable revision of the charm on Ubuntu Jammy and Juju 3.x
[/note]

## Obtain existing database credentials

To obtain credentials for existing databases execute the following commands [u]for each database to be migrated[/u]. Use those credentials in migration steps.

```shell
# replace DB_APP with desired unit name
DB_APP= < mydb/0 | charmed-osm-mariadb-k8s/0 >

# obtain username and password of existing legacy database from DB relation
# username is usually `root` and password is specified in `mysql` relation by 'root_password'
OLD_DB_RELATION_ID=$(juju show-unit ${DB_APP} | yq '.[] | .relation-info | select(.[].endpoint == "mysql") | .[0] | .relation-id')
OLD_DB_USER=root
OLD_DB_PASS=$(bash -c "juju run --unit ${DB_APP} 'relation-get -r ${OLD_DB_RELATION_ID} - ${DB_APP}' | grep root_password" | awk '{print $2}')
OLD_DB_IP=$(juju show-unit ${DB_APP} | yq '.[] | .address')
```

## Deploy new MySQL databases and obtain credentials

Deploy new MySQL databases and obtain credentials for each new database by executing the following commands, once per database:

```shell
# deploy new MySQL database charm
juju deploy mysql-k8s --trust --channel 8.0/stable -n 3

# obtain username and password of new MySQL database from MySQL charm
NEW_DB_USER=$(juju run mysql-k8s/leader get-password | yq '.username')
NEW_DB_PASS=$(juju run mysql-k8s/leader get-password | yq '.password')
NEW_DB_IP=$(juju show-unit mysql-k8s/0 | yq '.[] | .address')
```

## DB migration

Use the credentials and information obtained in previous steps to perform the database migration by executing the following commands:

```shell
# ensure that there are no new connections are made and that database is not altered
# remove relation between your_application charm and  legacy charm
juju remove-relation <your_application> <mydb | charmed-osm-mariadb-k8s>

# connect to the legacy database to verify connection
mysql \
  --host=${OLD_DB_IP} \
  --user=${OLD_DB_USER} \
  --password=${OLD_DB_PASS} \
  -e "show databases"

# choose which databases to dump/migrate to the new charm (one by one!)
DB_NAME=< e.g. wordpress >

# create backup of each database file using `mysqldump` utility, username, password, and unit's IP address, obtained earlier
# The dump will be created that can be used to restore database

OLD_DB_DUMP="legacy-mysql-${DB_NAME}.sql"

mysqldump \
  --host=${OLD_DB_IP} \
  --user=${OLD_DB_USER} \
  --password=${OLD_DB_PASS} \
  --column-statistics=0 \
  --databases ${OLD_DB_NAME} \
  > "${OLD_DB_DUMP}"

# connect to new DB using username, password, and unit's IP address and restore database from backup
mysql \
  --host=${NEW_DB_IP} \
  --user=${NEW_DB_USER} \
  --password=${NEW_DB_PASS} \
  < "${OLD_DB_DUMP}"
```

## Integrate with modern charm

```shell
# integrate your application and new MySQL database charm (using modern `database` endpoint)
juju integrate <your_application> mysql-k8s:database

# IF `database` endpoint (mysql_client interface) is not yes supported, use legacy `mysql` interface: 
juju integrate <your_application> mysql-k8s:mysql
```

## Verify DB migration

Note: some variables will vary for legacy and modern charms, namely: `${NEW_DB_PASS}` and `${NEW_DB_IP}`. These must be adjusted for the correct database, accordingly.

```shell
# compare new MySQL database and compare it to the backup created earlier
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

The difference between two SQL backup files should be limited to server versions, IP addresses, timestamps and other non data related information. Example of difference:

```python
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

## Remove old databases

Test your application and if you are happy with a data migration, do not forget to remove legacy charms to keep the house clean:

```shell
juju remove-application --destroy-storage < mydb | charmed-osm-mariadb-k8s >
```

## Links

Database data migration is also possible using [`mydumper`](/t/12006).

> :tipping_hand_man: This manual based on [Kubeflow DB migration guide](https://github.com/canonical/bundle-kubeflow/blob/main/docs/db-migration-guide.md).