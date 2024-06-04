# Charmed MySQL K8s operator
[![CharmHub Badge](https://charmhub.io/mysql-k8s/badge.svg)](https://charmhub.io/mysql-k8s)
[![Release](https://github.com/canonical/mysql-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/mysql-k8s-operator/actions/workflows/release.yaml)
[![Tests](https://github.com/canonical/mysql-k8s-operator/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/canonical/mysql-k8s-operator/actions/workflows/ci.yaml?query=branch%3Amain)
[![Docs](https://github.com/canonical/mysql-k8s-operator/actions/workflows/sync_docs.yaml/badge.svg)](https://github.com/canonical/mysql-k8s-operator/actions/workflows/sync_docs.yaml)

## Description

This repository contains a [Juju Charm](https://charmhub.io/mysql-k8s) for deploying [MySQL](https://www.mysql.com/) on [Kubernetes](https://microk8s.io/).

To deploy on [virtual machines](https://ubuntu.com/lxd), please use [Charmed MySQL VM operator](https://charmhub.io/mysql).

## Usage

Bootstrap a Kubernetes (e.g. [Multipass-based MicroK8s](https://discourse.charmhub.io/t/charmed-environment-charm-dev-with-canonical-multipass/8886)) and create a new model using Juju 2.9+:

```shell
juju add-model mysql-k8s
juju deploy mysql-k8s --trust --channel 8.0
```

**Note:** the `--trust` flag is required when relating using `mysql_client` interface.

**Note:** the above model must be created on K8s environment. Use [another](https://charmhub.io/mysql) charm for VMs!

To confirm the deployment, you can run:

```shell
juju status --watch 1s
```

Once MySQL starts up, it will be running on the default port (3306).

If required, you can remove the deployment completely by running:

```shell
juju destroy-model mysql-k8s --destroy-storage --yes
```

**Note:** the `--destroy-storage` will delete any data persisted by MySQL.

## Documentation

This operator provides a MySQL database with replication enabled: one primary instance and one (or more) hot standby replicas. The Operator in this repository is a Python-based framework which wraps MySQL distributed by Ubuntu Jammy providing lifecycle management and handling events (install, configure, integrate, remove, etc).

Please follow the [tutorial guide](https://discourse.charmhub.io/t/charmed-mysql-k8s-tutorial-overview/9677) with detailed explanation how to access DB, configure cluster, change credentials and/or enable TLS.

## Integrations ([relations](https://juju.is/docs/olm/relations))

The charm supports modern `mysql_client` and legacy `mysql` interfaces (in a backward compatible mode).

**Note:** do NOT relate both modern and legacy interfaces simultaneously!


### Modern interfaces

This charm provides modern ['mysql_client' interface](https://github.com/canonical/charm-relation-interfaces). Applications can easily connect MySQL using ['data_interfaces' library](https://charmhub.io/data-platform-libs/libraries/data_interfaces) from ['data-platform-libs'](https://github.com/canonical/data-platform-libs/).

#### Modern `mysql_client` interface (`database` endpoint):

Adding a relation is accomplished with `juju relate` (or `juju integrate` for Juju 3.x) via endpoint `database`. Example:

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

**Note:** In order to relate with this charm, every table created by the related application must have a primary key. This is required by the [group replication plugin](https://dev.mysql.com/doc/refman/8.0/en/group-replication-requirements.html) enabled in this charm.

### Legacy interfaces

**Note:** Legacy relations are deprecated and will be discontinued on future releases. Usage should be avoided.

#### Legacy `mysql` interface (`mysql` and `mysql-root` endpoints):

This charm supports legacy interface `mysql` (endpoint `mysql` and `mysql-root`). It was a popular interface used by some legacy charms (e.g. "[MariaDB](https://charmhub.io/mariadb)", "[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)", "[Percona Cluster](https://charmhub.io/percona-cluster)" and "[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)"), often in [cross-model relations](https://juju.is/docs/olm/cross-model-integration):

```shell
juju deploy mysql-k8s --trust --channel 8.0
juju config mysql-k8s mysql-interface-database=wordpress mysql-interface-user=wordpress
juju deploy wordpress-k8s
juju relate mysql-k8s:mysql wordpress-k8s:db
```

**Note:** The endpoint `mysql-root` provides the same legacy interface `mysql` with MySQL root-level privileges. It is NOT recommended to use it from security point of view.

## OCI Images
This charm uses pinned and tested version of the [charmed-mysql](https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql) rock.

## Security
Security issues in the Charmed MySQL K8s Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.

## Contributing
Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this
charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.

## License
The Charmed MySQL K8s Operator [is distributed](https://github.com/canonical/mysql-k8s-operator/blob/main/LICENSE) under the Apache Software License, version 2.0.
It installs/operates/depends on [MySQL Community Edition](https://github.com/mysql/mysql-server), which [is licensed](https://github.com/mysql/mysql-server/blob/8.0/LICENSE) under the GPL License, version 2.

## Trademark Notice
MySQL is a trademark or registered trademark of Oracle America, Inc.
Other trademarks are property of their respective owners.
