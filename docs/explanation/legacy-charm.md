# Legacy charm

Historically, there were [several](https://documentation.ubuntu.com/juju/3.6/reference/charm/#by-generation) operators/charms to provide MySQL/MariaDB functionality: [MariaDB](https://charmhub.io/mariadb), [OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s), [Percona Cluster](https://charmhub.io/percona-cluster) and [Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster). These are **legacy charms**.

This Charmed MySQL operator is a **modern charm** - i.e. it is based on [Charmed Operator SDK](https://juju.is/docs/sdk) and designed to replace all legacy [interfaces and endpoints](/explanation/interfaces-and-endpoints) of legacy charms.

The legacy charm provided endpoints `mysql` and `mysql-root` (for the interface `mysql`). The modern charm provides old endpoints as well as the new endpoint `database` (for the interface `mysql_client`). 

See all available endpoints/interfaces for Charmed MySQL K8s on [Charmhub](https://charmhub.io/mysql-k8s/integrations).

## The default track `latest` vs. `8.0`

The [default track](https://docs.openstack.org/charm-guide/yoga/project/charm-delivery.html) has been switched from the `latest` to `8.0` for both VM and K8s MySQL charms. 

This was done to ensure all new deployments use a modern codebase. For more context, see this [Discourse topic](https://discourse.charmhub.io/t/request-switch-default-track-latest-8-0-for-charms-mysql-and-mysql-k8s/9977).

We strongly advise against using the `latest` track, as a future charm upgrade may result in a MySQL version incompatible with an integrated application. Track `8.0` guarantees MySQL `8.0` deployment only. 

The track `latest` is closed to avoid confusion.

## How to migrate from legacy to modern charm

The modern charm provides temporary support for legacy interfaces

**Quick try**: Relate the current application with new charm using endpoint `mysql` (set the channel to `8.0/stable`). No extra changes are necessary:

```yaml
  mysql:
    charm: mysql-k8s
    channel: 8.0/stable
    trust: true
```

```{note}
The `trust` option must be enabled if [Role Based Access Control (RBAC)](https://kubernetes.io/docs/concepts/security/rbac-good-practices/) is in use in your Kubernetes.
```

**Proper migration**: Migrate the application to the new interface [`mysql_client`](https://github.com/canonical/charm-relation-interfaces). 

The application will connect MySQL using [`data_interfaces`](https://charmhub.io/data-platform-libs/libraries/data_interfaces) library from [`data-platform-libs`](https://github.com/canonical/data-platform-libs/) via the `database` endpoint.

```{caution}
In-place upgrades from the legacy charm to the modern, Ops-based charm are **not supported**.

To migrate database data, see the following guides:
* [](/how-to/development/migrate-data-via-mysqldump)
* [](/how-to/development/migrate-data-via-mydumper)
* [](/how-to/development/migrate-data-via-backup-restore)
```

## How to deploy a legacy MySQL charm

```yaml
  osm-mariadb:
    charm: charmed-osm-mariadb-k8s
    channel: latest/stable

  mysql:
    charm: mysql-innodb-cluster
    channel: 8.0/stable
```

## Supported MySQL versions by modern charm

At the moment, both K8s and VM modern charms support MySQL 8.0 (based on Jammy/22.04 series) only.
Please [contact us](/reference/contacts) if you need different versions/series.

## Supported architectures: amd64, arm64, ...

Currently, the charm supports architecture `amd64` only. 

See: [](/reference/system-requirements)

## How to report issues and contact authors

The modern charm (from `8.0/stable`) is stored on [GitHub](https://github.com/canonical/mysql-k8s-operator), here is the link to report [modern charm issues](https://github.com/canonical/mysql-k8s-operator/issues/new/choose).

Do you have questions? [Contact us](/reference/contacts)!

