# Interfaces and endpoints

Charmed MySQL K8s supports modern `mysql_client` and legacy `mysql` interfaces (in a backward compatible mode).

**Note:** do NOT relate both modern and legacy interfaces simultaneously!

## Modern interfaces

This charm provides modern ['mysql_client'](https://github.com/canonical/charm-relation-interfaces) interface. Applications can easily connect MySQL using ['data_interfaces'](https://charmhub.io/data-platform-libs/libraries/data_interfaces) library from ['data-platform-libs'](https://github.com/canonical/data-platform-libs/).

### Modern `mysql_client` interface (`database` endpoint):

Adding a relation is accomplished with `juju relate` (or `juju integrate` for Juju 3.x) via endpoint `database`. Read more about [Juju relations (integrations)](https://documentation.ubuntu.com/juju/3.6/reference/relation/). Example:

```shell
# Deploy Charmed MySQL cluster with 3 nodes
juju deploy mysql-k8s -n 3 --trust --channel 8.0

# Deploy the relevant charms, e.g. mysql-test-app
juju deploy mysql-test-app

# Relate MySQL with your application
juju relate mysql-k8s:database mysql-test-app:database

# Check established relation (using mysql_client interface):
juju status --relations

# Example of the properly established relation:
# > Relation provider      Requirer                 Interface     Type
# > mysql-k8s:database     mysql-test-app:database  mysql_client  regular
```
Find all details about default and extra DB user roles in “[Charm Users explanations](/explanation/users)”.

**Note:** In order to relate with this charm, every table created by the related application must have a primary key. This is required by the [group replication plugin](https://dev.mysql.com/doc/refman/8.0/en/group-replication-requirements.html) enabled in this charm.

## Legacy interfaces

**Note:** Legacy relations are deprecated and will be discontinued on future releases. Usage should be avoided. Check the legacy interface implementation limitations in the "[Legacy charm](/explanation/legacy-charm)" document.

### Legacy `mysql` interface (`mysql` and `mysql-root` endpoints):

This charm supports legacy interface `mysql` (endpoint `mysql` and `mysql-root`). It was a popular interface used by some legacy charms (e.g. "[MariaDB](https://charmhub.io/mariadb)", "[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)", "[Percona Cluster](https://charmhub.io/percona-cluster)" and "[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)"), often in [cross-model relations](https://documentation.ubuntu.com/juju/3.6/reference/relation/#cross-model):

```shell
juju deploy mysql-k8s --trust --channel 8.0
juju config mysql-k8s mysql-interface-database=wordpress mysql-interface-user=wordpress
juju deploy wordpress-k8s
juju relate mysql-k8s:mysql wordpress-k8s:db
```

**Note:** The endpoint `mysql-root` provides the same legacy interface `mysql` with MySQL root-level privileges. It is NOT recommended to use it from security point of view.

