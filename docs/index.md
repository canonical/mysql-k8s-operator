---
relatedlinks: "[Charmhub](https://charmhub.io/mysql-k8s)"
---

# Charmed MySQL K8s documentation

Charmed MySQL K8s is an open-source software operator that deploys and operates [MySQL Community Edition](https://www.mysql.com/products/community/) relational databases on Kubernetes via [Juju](https://juju.is/). 

This operator is built with the [charm SDK](https://juju.is/docs/sdk) replaces [**MariaDB**](https://charmhub.io/mariadb), [**OSM MariaDB**](https://charmhub.io/charmed-osm-mariadb-k8s), [**Percona cluster**](https://charmhub.io/percona-cluster) and [**MySQL InnoDB cluster**](https://charmhub.io/mysql-innodb-cluster) operators.

Charmed MySQL K8s includes features such as cluster-to-cluster replication, TLS encryption, password rotation, backups, and easy integration with other applications both inside and outside of Juju. It meets the need of deploying MySQL in a structured and consistent manner while allowing the user flexibility in configuration, simplifying reliable management of MySQL in production environments.

```{note}
This is a **Kubernetes** operator. To deploy on IAAS/VM, see [Charmed MySQL VM](https://charmhub.io/mysql).
```

## In this documentation

| | |
|--|--|
|  [Tutorials](/tutorial/index)</br>  Get started - a hands-on introduction to using Charmed MySQL operator for new users </br> |  [How-to guides](/how-to/index) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](/reference/index) </br> Technical information - specifications, APIs, architecture | [Explanation](/explanation/index) </br> Concepts - discussion and clarification of key topics  |

## Project and community

Charmed MySQL K8s is an official distribution of MySQL. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/mysql)
- [Contribute](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/mysql-k8s-operator/issues/new/choose)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contacts us](/reference/contacts) for all further questions


```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Home <self>
tutorial/index
how-to/index
reference/index
explanation/index
```
