# Charmed MySQL K8s operator

## Description

This repository contains a [Juju Charm](https://charmhub.io/mysql-k8s) for deploying [MySQL](https://www.mysql.com/) on [Kubernetes](https://microk8s.io/).

To deploy on [virtual machines](https://ubuntu.com/lxd), please use [Charmed MySQL VM operator](https://charmhub.io/mysql).

## Usage

To deploy this charm using Juju 2.9 or later, run:

```shell
juju add-model mysql-k8s
juju deploy mysql-k8s --trust
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

Please follow the [tutorial guide](https://discourse.charmhub.io/t/charmed-mysql-k8s-tutorial-overview/9677) with detailed explanation how to access DB, configure cluster, change credentials and/or enable TLS.

## Relations

The charm supports modern `mysql_client` and legacy `mysql` interfaces (in a backward compatible mode).

**Note:** do NOT relate both modern and legacy interfaces simultaneously.


### Modern relations

This charm implements the [provides data platform library](https://charmhub.io/data-platform-libs/libraries/database_provides), with the modern `mysql_client` interface.
To relate to it, use the [requires data-platform library](https://charmhub.io/data-platform-libs/libraries/database_requires).

Adding a relation is accomplished with `juju relate` (or `juju integrate` for Juju 3.x). Example:

```shell
# Deploy Charmed MySQL cluster with 3 nodes
juju deploy mysql-k8s -n 3 --trust

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

**Note:** In order to relate with this charm, every table created by the related application must have a primary key. This is required by the [group replication plugin](https://dev.mysql.com/doc/refman/5.7/en/group-replication-requirements.html), enable in this charm.


### Legacy relations

**Note:** Legacy relations are deprecated and will be discontinued on future releases. Usage should be avoided.

This charm supports legacy interface `mysql`. The `mysql` is a relation that's used from some k8s charms and can be used in cross-model relations.

```shell
juju deploy mysql-k8s --trust
juju deploy mediawiki
juju relate mysql-k8s:mysql mediawiki:db
```

**Note:** The endpoint `mysql-root` provides the same legacy interface `mysql` with MySQL root-level privileges. It is NOT recommended to use it from security point of view.

## OCI Images

This charm uses pinned and tested version of the [charmed-mysql](https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql) ROCK image.

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this
charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.

## License
The Charmed MySQL K8s Operator [is distributed](https://github.com/canonical/mysql-k8s-operator/blob/main/LICENSE) under the Apache Software License, version 2.0.
It installs/operates/depends on [MySQL Community Edition](https://github.com/mysql/mysql-server), which [is licensed](https://github.com/mysql/mysql-server/blob/8.0/LICENSE) under the GPL License, version 2.

## Trademark Notice
MySQL is a trademark or registered trademark of Oracle America, Inc.
Other trademarks are property of their respective owners.
