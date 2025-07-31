# Tutorial

This section of our documentation contains comprehensive, hands-on tutorials to help you learn how to deploy Charmed MySQL on Kubernetes and become familiar with its available operations.

## Prerequisites

While this tutorial intends to guide you as you deploy Charmed MySQL K8s for the first time, it will be most beneficial if:
- You have some experience using a Linux-based CLI
- You are familiar with MySQL concepts such as replication and users.
- Your computer fulfils the [minimum system requirements](/reference/system-requirements)

## Tutorial contents

| Step | Details |
| ------- | ---------- |
| 1. **Set up your environment** | Set up a cloud environment for your deployment using [Multipass](https://multipass.run/) with [Microk8s](https://microk8s.io/) and [Juju](https://juju.is/).
| 2. **Deploy MySQL** | Learn to deploy MySQL using a single command and access the database directly.
| 3. **Scale your replicas** | Learn how to enable high availability with [MySQL InnoDB Cluster](https://dev.mysql.com/doc/refman/8.0/en/mysql-innodb-cluster-introduction.html)
| 4. **[Manage passwords]** | Learn how to request and change passwords.
| 5. **Integrate MySQL with other applications** | Learn how to integrate with other applications using the Data Integrator Charm, access the integrated database, and manage users.
| 6. **Enable TLS encryption** | Learn how to enable TLS encryption on your MySQL cluster
| 7. **Clean up your environment** | Free up your machine's resources.


```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

1. Set up the environment <1-set-up-the-environment.md>
2. Deploy MySQL <2-deploy-mysql.md>
3. Scale replicas <3-scale-replicas.md>
4. Manage passwords <4-manage-passwords.md>
5. Integrate applications <5-integrate-applications.md>
6. Enable TLS encryption <6-enable-tls-encryption.md>
7. Clean up the environment <7-clean-up-the-environment.md>
```
