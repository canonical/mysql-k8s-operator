# Charm types "legacy" vs "modern"

Historically, there were  [several](https://juju.is/docs/sdk/charm-taxonomy#charm-types-by-generation) operators/charms to provide MySQL/MariaDB functionality: "[MariaDB](https://charmhub.io/mariadb)", "[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)", "[Percona Cluster](https://charmhub.io/percona-cluster)" and "[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)". All of them are named "legacy" charms.

This "Charmed MySQL" operator is a modern "[Charmed Operator SDK](https://juju.is/docs/sdk)"-based charm to replace all legacy operators [interfaces/endpoints](/explanation/interfaces-and-endpoints) of legacy charms.

The legacy charm provided endpoints `mysql` and `mysql-root` (for the interface `mysql`). The modern charm provides old endpoints as well + new endpoint `database` (for the interface `mysql_client`). Read more detail about the available endpoints/interfaces for [VM](https://charmhub.io/mysql/docs/e-interfaces) and [K8s](https://charmhub.io/mysql-k8s/docs/e-interfaces) charms.

**Note**: Please choose one endpoint to use. No need to relate all of them simultaneously!

## The default track "latest" vs "8.0"

The [default track](https://docs.openstack.org/charm-guide/yoga/project/charm-delivery.html) has been switched from the `latest` to `8.0` for both VM and K8s MySQL charms. It is [to ensure](https://discourse.charmhub.io/t/request-switch-default-track-latest-8-0-for-charms-mysql-and-mysql-k8s/9977) all new deployments use a modern codebase. We strongly advise against using the latest track due to its implicit nature. In doing so, a future charm upgrade may result in a MySQL version incompatible with an integrated application. Track "8.0" guarantees MySQL 8.0 deployment only. The track `latest` is closed to avoid confusion.

## How to migrate from "legacy" to "modern" charm

The "modern" charm provides temporary support for the legacy interfaces:

* **quick try**: relate the current application with new charm using endpoint `mysql` (set the channel to `8.0/stable`). No extra changes necessary:

```
  mysql:
    charm: mysql-k8s
    channel: 8.0/stable
    trust: true
```

* **proper migration**: migrate the application to the new interface "[mysql_client](https://github.com/canonical/charm-relation-interfaces)". The application will connect MySQL using "[data_interfaces](https://charmhub.io/data-platform-libs/libraries/data_interfaces)" library from "[data-platform-libs](https://github.com/canonical/data-platform-libs/)" via endpoint `database`.

**Warning**: NO in-place upgrades possible! Legacy charm cannot be upgraded to Operator-framework-based one. To move DB data, the second/modern DB application must be launched nearby and data should be copied from "legacy" application to the "modern" one. Canonical Data Platform team will prepare the copy&paste guide. Please [contact us](https://chat.charmhub.io/charmhub/channels/data-platform) if you need migration instructions.

**Note**: the `trust` option must be enabled if [ Role Based Access Control (RBAC)](https://kubernetes.io/docs/concepts/security/rbac-good-practices/) is in use on your Kubernetes.

## How to deploy old "legacy" mysql charm

Deploy the charm using the proper charm/channel:

```
  osm-mariadb:
    charm: charmed-osm-mariadb-k8s
    channel: latest/stable

  mysql:
    charm: mysql-innodb-cluster
    channel: 8.0/stable
```

## Supported MySQL versions by modern charm

At the moment, both K8s and VM modern charms support MySQL 8.0 (based on Jammy/22.04 series) only.
Please [contact us](https://chat.charmhub.io/charmhub/channels/data-platform) if you need different versions/series.

## Supported architectures: amd64, arm64, ...

Currently, the charm supports architecture `amd64` only. See the technical details in "[Supported architectures](/reference/system-requirements)".

## How to report issues and contact authors

The "modern charm" (from `8.0/stable`) is stored on [GitHub](https://github.com/canonical/mysql-k8s-operator), here is the link to report [modern charm issues](https://github.com/canonical/mysql-k8s-operator/issues/new/choose).

Do you have questions? [Contact us](https://chat.charmhub.io/charmhub/channels/data-platform)!

