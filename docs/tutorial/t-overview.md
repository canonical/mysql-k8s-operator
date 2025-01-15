# Charmed MySQL K8s Tutorial

This section of our documentation contains comprehensive, hands-on tutorials to help you learn how to deploy Charmed MySQL on Kubernetes and become familiar with its available operations.

## Prerequisites

While this tutorial intends to guide you as you deploy Charmed MySQL K8s for the first time, it will be most beneficial if:
- You have some experience using a Linux-based CLI
- You are familiar with MySQL concepts such as replication and users.
- Your computer fulfils the [minimum system requirements](/t/11421)

## Tutorial contents

| Step | Details |
| ------- | ---------- |
| 1. **[Set up your environment]** | Set up a cloud environment for your deployment using [Multipass](https://multipass.run/) with [Microk8s](https://microk8s.io/) and [Juju](https://juju.is/).
| 2. **[Deploy MySQL]** | Learn to deploy MySQL using a single command and access the database directly.
| 3. **[Scale your replicas]** | Learn how to enable high availability with [MySQL InnoDB Cluster](https://dev.mysql.com/doc/refman/8.0/en/mysql-innodb-cluster-introduction.html)
| 4. **[Manage passwords]** | Learn how to request and change passwords.
| 5. **[Integrate MySQL with other applications]** | Learn how to integrate with other applications using the Data Integrator Charm, access the integrated database, and manage users.
| 6. **[Enable TLS encryption]** | Learn how to enable TLS encryption on your MySQL cluster
| 7. **[Clean up your environment]** | Free up your machine's resources.

<!-- LINKS -->
[Set up your environment]: /t/9679
[Deploy MySQL]: /t/9667
[Scale your replicas]: /t/9675
[Manage passwords]: /t/9673
[Integrate MySQL with other applications]: /t/9671
[Enable TLS encryption]: /t/9669
[Upgrade charm]: /t/11754
[Clean up your environment]: /t/9665