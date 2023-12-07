# Charmed MySQL K8s revision 75
<sub>Thursday, April 20, 2023</sub>

Dear community, this is to inform you that new Canonical Charmed MySQL K8s charm is published in `8.0/stable` charmhub channel for Kubernetes.

## The features you can start using today:

* Deploying on Kubernetes (tested with MicroK8s, GKE)
  * juju constraints are supported to limit CPU/RAM/Storage size
* Scaling up/down in one simple juju command
* HA using [Innodb Group replication](https://dev.mysql.com/doc/refman/8.0/en/group-replication.html)
* Full backups and restores are supported when using any S3-compatible storage
* TLS support (using “[tls-certificates](https://charmhub.io/tls-certificates-operator)” operator)
* DB access outside of Juju using “[data-integrator](https://charmhub.io/data-integrator)”
* Data import using standard tools e.g. mysqldump, etc.
* Documentation:

|Charm|Version|Charm channel|Documentation|License|
| --- | --- | --- | --- | --- |
|[MySQL K8s](https://github.com/canonical/mysql-k8s-operator)|8.0.32|[8.0/stable](https://charmhub.io/mysql-k8s) (r75)|[Tutorial](https://charmhub.io/mysql-k8s/docs/t-overview?channel=8.0/edge), [Readme](https://github.com/canonical/mysql-k8s-operator/blob/main/README.md), [Contributing](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md)|[Apache 2.0](https://github.com/canonical/mysql-k8s-operator/blob/main/LICENSE)|

## What is inside the charms:

* Charmed MySQL K8s charm ships the latest MySQL “8.0.32-0ubuntu0.22.04.2”
* K8s charms [based on our](https://github.com/orgs/canonical/packages?tab=packages&q=charmed) ROCK OCI (Ubuntu LTS “22.04” - ubuntu:22.04-based)
* Principal charms supports the latest LTS series “22.04” only.
* Subordinate charms support LTS “22.04” and “20.04” only.

## Technical notes:

Compatibility with legacy charms:
  * New MySQL charm is a juju-interface compatible replacement for legacy charms such as “[MariaDB](https://charmhub.io/mariadb)”, “[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)”, “[Percona Cluster](https://charmhub.io/percona-cluster)” and “[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)” (using legacy interface “mysql”, via endpoints “mysql” and “mysql-root”). Other legacy interfaces such as “[mysql-router](https://github.com/canonical/mysql-operator/#mysql-router-interface-db-router-endpoint)” interface (“db-router” endpoint) and “[mysql-shared](https://github.com/canonical/mysql-operator/#mysql-router-interface-db-router-endpoint)” interface (“shared-db” endpoint) are also supported. However, it is highly recommended to migrate to the modern interface ‘[mysql_client ](https://github.com/canonical/charm-relation-interfaces)’. It can be easily done using the charms library ‘[data_interfaces](https://charmhub.io/data-platform-libs/libraries/data_interfaces)’ from ‘[data-platform-libs](https://github.com/canonical/data-platform-libs/)’.

Please contact us, see details below, if you are considering migrating from other “legacy” charms not mentioned above. Additionally:
* Tracks description:
  * Charm MySQL K8s charm follows the SNAP track “8.0” (through repacked ROCK/OCI image).
* No “latest” track in use (no surprises in tracking “latest/stable”)!
  * Charmed MySQL K8s charms provide [legacy charm](/t/11236) through “latest/stable”.
* Charm lifecycle flowchart diagrams: [MySQL](https://github.com/canonical/mysql-k8s-operator/tree/main/docs/reference).
* Modern interfaces are well described in “[Interfaces catalogue](https://github.com/canonical/charm-relation-interfaces)” and implemented by '[data-platform-libs](https://github.com/canonical/data-platform-libs/)'.

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/data-platform) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/11868).

Consider [opening a GitHub issue](https://github.com/canonical/mysql-k8s-operator/issues) if you want to open a bug report. [Contribute](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) to the project!

## Footer:

The document was originally posted [here](https://discourse.charmhub.io/t/juju-operators-for-postgresql-and-mysql-are-now-stable/10223).