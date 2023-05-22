The Charmed MySQL K8s Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MySQL Community Edition](https://www.mysql.com/products/community/) relational database. It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/).

MySQL is the world’s most popular open source database. A relational database stores data in separate tables rather than putting all the data in one big storeroom. The database structure is organized into physical files optimized for speed. The logical data model, with objects such as data tables, views, rows, and columns, offers a flexible programming environment.

This MySQL operator charm comes in two flavours to deploy and operate MySQL on [physical/virtual machines](https://github.com/canonical/mysql-operator) and [Kubernetes](https://github.com/canonical/mysql-k8s-operator). Both offer features such as replication, TLS, password rotation, and easy to use integration with applications. The Charmed MySQL K8s Operator meets the need of deploying MySQL in a structured and consistent manner while allowing the user flexibility in configuration. It simplifies deployment, scaling, configuration and management of MySQL in production at scale in a reliable way.

[note type="positive"]
**"Charmed MySQL K8s", "MariaDB", "OSM MariaDB", "Percona Cluster" or "Mysql Innodb Cluster"?**

This "Charmed MySQL K8s" operator is a new "[Charmed Operator SDK](https://juju.is/docs/sdk)"-based charm to replace a "[MariaDB](https://charmhub.io/mariadb)", "[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)", "[Percona Cluster](https://charmhub.io/percona-cluster)" and "[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)" operators [providing](/t/charmed-mysql-k8s-explanations-interfaces-endpoints/10249) all juju-interfaces of legacy charms.
[/note]

## Project and community

Charmed MySQL K8s is an official distribution of MySQL. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/mysql)
- Contribute and report bugs to [machine](https://github.com/canonical/mysql-operator) and [K8s](https://github.com/canonical/mysql-k8s-operator) operators

## In this documentation

| | |
|--|--|
|  [Tutorials](/t/charmed-mysql-k8s-tutorial-overview/9677)</br>  Get started - a hands-on introduction to using Charmed MySQL operator for new users </br> |  [How-to guides](/t/charmed-mysql-k8s-how-to-manage-units/9659) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/mysql-k8s/actions) </br> Technical information - specifications, APIs, architecture | [Explanation](/t/charmed-mysql-k8s-explanations-interfaces-endpoints/10249) </br> Concepts - discussion and clarification of key topics  |

# Navigation

| Level | Path                          | Navlink                                                                                        |
|-------|-------------------------------|------------------------------------------------------------------------------------------------|
| 1     | tutorial                      | [Tutorial]()                                                                                   |
| 2     | t-overview                    | [1. Introduction](/t/charmed-mysql-k8s-tutorial-overview/9677)                                 |
| 2     | t-setup-environment           | [2. Set up the environment](/t/charmed-mysql-k8s-tutorial-setup-environment/9679)              |
| 2     | t-deploy-mysql                | [3. Deploy MySQL](/t/charmed-mysql-k8s-tutorial-deploy-mysql/9667)                             |
| 2     | t-managing-units              | [4. Manage your units](/t/charmed-mysql-k8s-tutorial-managing-units/9675)                      |
| 2     | t-manage-passwords            | [5. Manage passwords](/t/charmed-mysql-k8s-tutorial-manage-passwords/9673)                     |
| 2     | t-integrations                | [6. Relate your MySQL to other applications](/t/charmed-mysql-k8s-tutorial-integrations/9671)  |
| 2     | t-enable-security             | [7. Enable security](/t/charmed-mysql-k8s-tutorial-enable-security/9669)                       |
| 2     | t-cleanup-environment         | [8. Cleanup your environment](/t/charmed-mysql-k8s-tutorial-cleanup-environment/9665)          |
| 1     | how-to                        | [How To]()                                                                                     |
| 2     | h-manage-units                | [Manage units](/t/charmed-mysql-k8s-how-to-manage-units/9659)                                  |
| 2     | h-enable-encryption           | [Enable encryption](/t/charmed-mysql-k8s-how-to-enable-encryption/9655)                        |
| 2     | h-manage-app                  | [Manage applications](/t/charmed-mysql-k8s-how-to-manage-app/9657)                             |
| 2     | h-configure-s3-aws               | [Configure S3 AWS](/t/charmed-mysql-k8s-how-to-configure-s3-for-aws/9651)                                  |
| 2     | h-configure-s3-radosgw                | [Configure S3 RadosGW](/t/charmed-mysql-k8s-how-to-configure-s3-for-radosgw/10319)                                  |
| 2     | h-create-and-list-backups     | [Create and List Backups](/t/charmed-mysql-k8s-how-to-create-and-list-backups/9653)            |
| 2     | h-restore-backup              | [Restore a Backup](/t/charmed-mysql-k8s-how-to-restore-backup/9663)                            |
| 2     | h-migrate-cluster-via-restore | [Cluster Migration with Restore](/t/charmed-mysql-k8s-how-to-migrate-cluster-via-restore/9661) |
| 2     | h-enable-monitoring           | [Enable Monitoring](/t/charmed-mysql-k8s-how-to-enable-monitoring/9981)                        |
| 1     | reference                     | [Reference]()                                                                                  |
| 2     | r-actions                     | [Actions](https://charmhub.io/mysql-k8s/actions)                                               |
| 2     | r-configurations              | [Configurations](https://charmhub.io/mysql-k8s/configure)                                      |
| 2     | r-libraries                   | [Libraries](https://charmhub.io/mysql-k8s/libraries/helpers)                                   |
| 2     | r-integrations                   | [Integrations](https://charmhub.io/mysql-k8s/integrations)                                   |
| 1     | explanation                    | [Explanation]()                                                                                                      |
| 2     | e-interfaces                | [ Interfaces/endpoints](/t/charmed-mysql-k8s-explanations-interfaces-endpoints/10249) |
| 2     | e-flowcharts                | [ Charm flowcharts](/t/charmed-mysql-k8s-explanation-charm-lifecycle-flowcharts/10031) |

# Redirects

[details=Mapping table]
| Path | Location |
| ---- | -------- |
[/details]