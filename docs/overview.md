# Charmed MySQL K8s Documentation

[note type="positive"]
This is **[K8s](https://canonical.com/data/docs)** operator. To deploy in **[IAAS/VM](https://canonical.com/data/docs)**, use [Charmed MySQL](https://charmhub.io/mysql).
[/note]

The Charmed MySQL K8s Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MySQL Community Edition](https://www.mysql.com/products/community/) relational database. It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/).

![image|690x424](upload://vpevillwv3S9C44LDFBxkGCxpGq.png)

MySQL is the world’s most popular open source database. A relational database stores data in separate tables rather than putting all the data in one big storeroom. The database structure is organized into physical files optimized for speed. The logical data model, with objects such as data tables, views, rows, and columns, offers a flexible programming environment.

This MySQL operator charm comes in two flavours to deploy and operate MySQL on [physical/virtual machines](https://github.com/canonical/mysql-operator) and [Kubernetes](https://github.com/canonical/mysql-k8s-operator). Both offer features such as replication, TLS, password rotation, and easy to use integration with applications. The Charmed MySQL K8s Operator meets the need of deploying MySQL in a structured and consistent manner while allowing the user flexibility in configuration. It simplifies deployment, scaling, configuration and management of MySQL in production at scale in a reliable way.

[note type="positive"]
**"Charmed MySQL K8s", "MariaDB", "OSM MariaDB", "Percona Cluster" or "Mysql Innodb Cluster"?**

This "Charmed MySQL K8s" operator is a new "[Charmed SDK](https://juju.is/docs/sdk)"-based charm to replace a "[MariaDB](https://charmhub.io/mariadb)", "[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)", "[Percona Cluster](https://charmhub.io/percona-cluster)" and "[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)" operators.<br/>Read more about [legacy charms here](https://discourse.charmhub.io/t/11236).
[/note]

## Project and community

Charmed MySQL K8s is an official distribution of MySQL. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/mysql)
- [Contribute](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/mysql-k8s-operator/issues/new/choose)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
- [Contacts us](/t/11868) for all further questions

## In this documentation

| | |
|--|--|
|  [Tutorials](/t/9677)</br>  Get started - a hands-on introduction to using Charmed MySQL operator for new users </br> |  [How-to guides](/t/9659) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/mysql-k8s/actions) </br> Technical information - specifications, APIs, architecture | [Explanation](/t/10249) </br> Concepts - discussion and clarification of key topics  |

# Navigation

[details=Navigation]

| Level | Path | Navlink |
|---------|---------|-------------|
| 1 | tutorial | [Tutorial]() |
| 2 | t-overview | [1. Introduction](/t/9677) |
| 2 | t-set-up | [2. Set up the environment](/t/9679) |
| 2 | t-deploy | [3. Deploy MySQL](/t/9667) |
| 2 | t-scale | [4. Scale replicas](/t/9675) |
| 2 | t-manage-passwords | [5. Manage passwords](/t/9673) |
| 2 | t-integrate | [6. Integrate applications](/t/9671)  |
| 2 | t-enable-tls | [7. Enable TLS encryption](/t/9669) |
| 2 | t-clean-up | [8. Clean up the environment](/t/9665) |
| 1 | how-to | [How To]() |
| 2 | h-setup | [Set up]() |
| 3 | h-deploy-microk8s | [Deploy on MicroK8s](/t/11869) |
| 3 | h-deploy-gke | [Deploy on GKE](/t/10875) |
| 3 | h-deploy-eks | [Deploy on EKS](/t/12105) |
| 3 | h-deploy-aks | [Deploy on AKS](/t/14306) |
| 3 | h-deploy-terraform | [Deploy via Terraform](/t/14926) |
| 3 |  h-scale | [Scale replicas](/t/9659) |
| 3 | h-enable-tls | [Enable TLS encryption](/t/9655) |
| 3 | h-manage-applications | [Manage client applications](/t/9657) |
| 2 | h-backups | [Back up and restore]() |
| 3 | h-configure-s3-aws | [Configure S3 AWS](/t/9651) |
| 3 | h-configure-s3-radosgw | [Configure S3 RadosGW](/t/10319) |
| 3 | h-create-backup | [Create a backup](/t/9653) |
| 3 | h-restore-backup | [Restore a backup](/t/9663) |
| 3 | h-migrate-cluster| [Migrate a cluster](/t/9661) |
| 2 | h-monitoring | [Monitoring (COS)]() |
| 3 | h-enable-monitoring | [Enable monitoring](/t/9981) |
| 3 | h-enable-tracing | [Enable tracing](/t/14448) |
| 2 | h-upgrade | [Upgrade]() |
| 3 | h-upgrade-intro | [Overview](/t/11754) |
| 3 | h-upgrade-juju | [Upgrade Juju](/t/14333) |
| 3 | h-upgrade-major | [Perform a major upgrade](/t/11750) |
| 3 | h-rollback-major | [Perform a major rollback](/t/11751) |
| 3 | h-upgrade-minor | [Perform a minor upgrade](/t/11752) |
| 3 | h-rollback-minor | [Perform a minor rollback](/t/11753) |
| 2 | h-integrate-your-charm | [Integrate with your charm]() |
| 3 | h-integrate-intro | [Intro](/t/11884) |
| 3 | h-integrate-db-with-your-charm | [Integrate a database with your charm](/t/11885) |
| 3 | h-migrate-mysqldump | [Migrate data via mysqldump](/t/11992) |
| 3 | h-migrate-mydumper | [Migrate data via mydumper](/t/12006) |
| 3 | h-migrate-backup-restore | [Migrate data via backup/restore](/t/12007) |
| 3 | h-troubleshooting | [Troubleshooting](/t/11886) |
| 2 | h-async | [Cross-regional async replication]() |
| 3 | h-async-deployment | [Deploy](/t/13458) |
| 3 | h-async-clients | [Clients](/t/13459) |
| 3 | h-async-failover | [Switchover / Failover](/t/13460) |
| 3 | h-async-recovery | [Recovery](/t/13467) |
| 3 | h-async-removal | [Removal](/t/13468) |
| 2 | h-contribute | [Contribute](/t/14655) |
| 1 | reference | [Reference]() |
| 2 | r-releases | [Release Notes]() |
| 3 | r-all-releases | [All releases](/t/11878) |
| 3 | r-revision-180-181 | [Revision 180/181](/t/15276) |
| 3 | r-revision-153 | [Revision 153](/t/14072) |
| 3 | r-revision-127 | [Revision 127](/t/13522) |
| 3 | r-revision-113 | [Revision 113](/t/12221) |
| 3 | r-revision-99 | [Revision 99](/t/11880) |
| 3 | r-revision-75 | [Revision 75](/t/11879) |
| 2 | r-requirements | [Requirements](/t/11421) |
| 2 | r-testing | [Testing](/t/11772) |
| 2 | r-profiles | [Profiles](/t/11892) |
| 2 | r-contacts | [Contacts](/t/11868) |
| 1 | explanation | [Explanation]() |
| 2 | e-architecture | [Architecture](/t/11757) |
| 2 | e-interfaces-endpoints | [Interfaces/endpoints](/t/10249) |
| 2 | e-statuses | [Statuses](/t/11866) |
| 2 | e-users | [Users](/t/10791) |
| 2 | e-logs | [Logs](/t/12080) |
| 2 | e-juju | [Juju](/t/11984) |
| 2 | e-flowcharts | [Flowcharts](/t/10031) |
| 2 | e-legacy-charm | [Legacy charm](/t/11236) |
| 1 | search | [Search](https://canonical.com/data/docs/mysql/k8s) |

[/details]