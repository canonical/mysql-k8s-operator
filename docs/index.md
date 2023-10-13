# Charmed MySQL K8s Documentation

The Charmed MySQL K8s Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MySQL Community Edition](https://www.mysql.com/products/community/) relational database. It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/).

MySQL is the world’s most popular open source database. A relational database stores data in separate tables rather than putting all the data in one big storeroom. The database structure is organized into physical files optimized for speed. The logical data model, with objects such as data tables, views, rows, and columns, offers a flexible programming environment.

This MySQL operator charm comes in two flavours to deploy and operate MySQL on [physical/virtual machines](https://github.com/canonical/mysql-operator) and [Kubernetes](https://github.com/canonical/mysql-k8s-operator). Both offer features such as replication, TLS, password rotation, and easy to use integration with applications. The Charmed MySQL K8s Operator meets the need of deploying MySQL in a structured and consistent manner while allowing the user flexibility in configuration. It simplifies deployment, scaling, configuration and management of MySQL in production at scale in a reliable way.

[note type="positive"]
**"Charmed MySQL K8s", "MariaDB", "OSM MariaDB", "Percona Cluster" or "Mysql Innodb Cluster"?**

This "Charmed MySQL K8s" operator is a new "[Charmed Operator SDK](https://juju.is/docs/sdk)"-based charm to replace a "[MariaDB](https://charmhub.io/mariadb)", "[OSM MariaDB](https://charmhub.io/charmed-osm-mariadb-k8s)", "[Percona Cluster](https://charmhub.io/percona-cluster)" and "[Mysql Innodb Cluster](https://charmhub.io/mysql-innodb-cluster)" operators [providing](/t/10249) all juju-interfaces of [legacy charms](/t/11236).
[/note]

## Project and community

Charmed MySQL K8s is an official distribution of MySQL. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/mysql)
- [Contribute](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/mysql-k8s-operator/issues/new/choose)
-  [Contacts us](/t/11868) for all further questions

## In this documentation

| | |
|--|--|
|  [Tutorials](/t/9677)</br>  Get started - a hands-on introduction to using Charmed MySQL operator for new users </br> |  [How-to guides](/t/9659) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/mysql-k8s/actions) </br> Technical information - specifications, APIs, architecture | [Explanation](/t/10249) </br> Concepts - discussion and clarification of key topics  |


# Contents

1. [Tutorial](tutorial)
  1. [1. Introduction](tutorial/t-overview.md)
  1. [2. Set up the environment](tutorial/t-setup-environment.md)
  1. [3. Deploy MySQL](tutorial/t-deploy-charm.md)
  1. [4. Manage units](tutorial/t-managing-units.md)
  1. [5. Manage passwords](tutorial/t-manage-passwords.md)
  1. [6. Integrate applications](tutorial/t-integrations.md)
  1. [7. Enable security](tutorial/t-enable-security.md)
  1. [8. Cleanup environment](tutorial/t-cleanup-environment.md)
1. [How To](how-to)
  1. [Setup](how-to/h-setup)
    1. [Deploy on MicroK8s](how-to/h-setup/h-deploy-microk8s.md)
    1. [Deploy on GKE](how-to/h-setup/h-deploy-gke.md)
    1. [Deploy on EKS](how-to/h-setup/h-deploy-eks.md)
    1. [Manage units](how-to/h-setup/h-manage-units.md)
    1. [Enable encryption](how-to/h-setup/h-enable-encryption.md)
    1. [Manage applications](how-to/h-setup/h-manage-app.md)
  1. [Backup](how-to/h-to-manage-backups)
    1. [Configure S3 AWS](how-to/h-to-manage-backups/h-configure-s3-aws.md)
    1. [Configure S3 RadosGW](how-to/h-to-manage-backups/h-configure-s3-radosgw.md)
    1. [Create and List Backups](how-to/h-to-manage-backups/h-create-and-list-backups.md)
    1. [Restore Backup](how-to/h-to-manage-backups/h-restore-backup.md)
    1. [Restore foreign Backup](how-to/h-to-manage-backups/h-migrate-cluster-via-restore.md)
  1. [Monitoring (COS)](how-to/h-enable-monitoring.md)
  1. [Upgrade](how-to/h-upgrade)
    1. [Intro](how-to/h-upgrade/h-upgrade-intro.md)
    1. [Major upgrade](how-to/h-upgrade/h-upgrade-major.md)
    1. [Major rollback](how-to/h-upgrade/h-rollback-major.md)
    1. [Minor upgrade](how-to/h-upgrade/h-upgrade-minor.md)
    1. [Minor rollback](how-to/h-upgrade/h-rollback-minor.md)
  1. [Develop](how-to/h-develop)
    1. [Intro](how-to/h-develop/h-develop-intro.md)
    1. [Use in my charm](how-to/h-develop/h-develop-mycharm.md)
    1. [Migrate data by](how-to/h-develop/h-develop-migratedataby)
      1. [mysqldump](how-to/h-develop/h-develop-migratedataby/h-develop-mysqldump.md)
      1. [mydumper](how-to/h-develop/h-develop-migratedataby/h-develop-mydumper.md)
      1. [backup/restore](how-to/h-develop/h-develop-migratedataby/h-develop-backuprestore.md)
    1. [Troubleshooting](how-to/h-develop/h-troubleshooting.md)
    1. [Legacy charm](how-to/h-develop/h-legacy-charm.md)
1. [Reference](reference)
  1. [Release Notes](reference/r-releases-group)
    1. [All releases](reference/r-releases-group/r-releases.md)
    1. [Revision 99](reference/r-releases-group/r-releases-rev99.md)
    1. [Revision 75](reference/r-releases-group/r-releases-rev75.md)
  1. [Requirements](reference/r-requirements.md)
  1. [Contributing](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md)
  1. [Testing](reference/r-testing.md)
  1. [Actions](https://charmhub.io/mysql-k8s/actions)
  1. [Configurations](https://charmhub.io/mysql-k8s/configure)
  1. [Profiles](reference/r-profiles.md)
  1. [Libraries](https://charmhub.io/mysql-k8s/libraries/helpers)
  1. [Integrations](https://charmhub.io/mysql-k8s/integrations)
  1. [Contacts](reference/r-contacts.md)
1. [Explanation](explanation)
  1. [Architecture](explanation/e-architecture.md)
  1. [Interfaces/endpoints](explanation/e-interfaces.md)
  1. [Statuses](explanation/e-statuses.md)
  1. [Users](explanation/e-users.md)
  1. [Logs](explanation/e-logs.md)
  1. [Juju](explanation/e-juju-details.md)
  1. [Flowcharts](explanation/e-flowcharts.md)
  1. [Legacy charm](explanation/e-legacy-charm.md)