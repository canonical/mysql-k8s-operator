# DB data migration using 'mydumper'

> :information_source: **Tip**: use ['mysqldump' manual](/t/11992) to migrate [legacy charms](/t/11236) data.

The [mydumper](https://github.com/mydumper/mydumper) tool is a powerful MySQL logical data-migration tool, including:

* `mydumper` - responsible to export a consistent of MySQL databases
* `myloader` - reads the dump from mydumper, connects the to destination database and imports the data

Both tools use multi-threading capabilities and support S3 storage to write/read dumps. MyDumper is Open Source and maintained by the community, it is not a Percona, MariaDB, MySQL or Canonical product.

Before the data migration check all [limitations of the modern Charmed MySQL K8s](/t/11421#mysql-gr-limits) charm!<br/>Please check [your application compatibility](/t/11236) with Charmed MySQL K8s before migrating production data from legacy charm!

## Installation:
Install the latest version from [GitHub](https://github.com/mydumper/mydumper/releases):
```shell
wget https://github.com/mydumper/mydumper/releases/download/v0.15.1-3/mydumper_0.15.1-3.jammy_amd64.deb && \
sudo apt install ./mydumper_0.15.1-3.jammy_amd64.deb
```

## Dumping:

Dump database using Charmed MySQL K8s operator user `serverconfig`:
```shell
# Collect credentials
DB_NAME=<your_db_name>
OLD_DB_IP=$(juju show-unit mysql-k8s/0 | yq '.[] | .public-address')
OLD_DB_USER=serverconfig
OLD_DB_PASS=$(juju run mysql-k8s/leader get-password username=${OLD_DB_USER}| yq '.password')

# Test connection:
mysql -h ${OLD_DB_IP} -u ${OLD_DB_USER} -p${OLD_DB_PASS} ${DB_NAME}

# Dump database using mydumper:
mydumper -h ${OLD_DB_IP} -u ${OLD_DB_USER} -p ${OLD_DB_PASS} -B ${DB_NAME}
```

The DB dump content stored in a newly created folder, e.g. `export-20230927-123337` (which can be stored on S3-compatible storage):
```shell
> ls -la export-20230927-123337
drwxr-x---  2 ubuntu ubuntu   4096 Sep 27 12:33 .
drwxr-x--- 18 ubuntu ubuntu   4096 Sep 27 12:34 ..
-rw-rw-r--  1 ubuntu ubuntu    175 Sep 27 12:33 your_db_name-schema-create.sql
-rw-rw-r--  1 ubuntu ubuntu      0 Sep 27 12:33 your_db_name-schema-triggers.sql
-rw-rw-r--  1 ubuntu ubuntu    298 Sep 27 12:33 your_db_name.data-schema.sql
-rw-rw-r--  1 ubuntu ubuntu 124131 Sep 27 12:33 your_db_name.data.00000.sql
-rw-rw-r--  1 ubuntu ubuntu    314 Sep 27 12:33 your_db_name.random_data-schema.sql
-rw-rw-r--  1 ubuntu ubuntu    153 Sep 27 12:33 your_db_name.random_data.00000.sql
-rw-rw-r--  1 ubuntu ubuntu    499 Sep 27 12:33 metadata
```

## Restoring:
```shell
NEW_DB_IP=...
NEW_DB_USER=serverconfig
NEW_DB_PASS=...

myloader -h ${NEW_DB_IP} -u ${NEW_DB_USER} -p ${NEW_DB_PASS} --directory=export-20230927-123337 --overwrite-tables
```