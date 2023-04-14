# Scale your Charmed MySQL

This is part of the [Charmed MySQL Tutorial](/t/charmed-mysql-k8s-tutorial-overview/9677). Please refer to this page for more information and the overview of the content.

## Adding and Removing units

Charmed MySQL K8s operator uses [MySQL InnoDB Cluster](https://dev.mysql.com/doc/refman/8.0/en/mysql-innodb-cluster-introduction.html) for scaling. Being built on MySQL [Group Replication](https://dev.mysql.com/doc/refman/8.0/en/group-replication.html), provides features such as automatic membership management, fault tolerance, automatic failover, and so on. An InnoDB Cluster usually runs in a single-primary mode, with one primary instance (read-write) and multiple secondary instances (read-only). The future versions on Charmed MySQL K8s will take advantage of a multi-primary mode, where multiple instances are primaries. Users can even change the topology of the cluster while InnoDB Cluster is online, to ensure the highest possible availability.

> **!** *Disclaimer: this tutorial hosts replicas all on the same machine, this should not be done in a production environment. To enable high availability in a production environment, replicas should be hosted on different servers to [maintain isolation](https://canonical.com/blog/database-high-availability).*

### Add cluster members (replicas)
You can add two replicas to your deployed MySQL application by scaling it to three units using:
```shell
juju scale-application mysql-k8s 3
```

You can now watch the scaling process in live using: `juju status --watch 1s`. It usually takes several minutes for new cluster members to be added. You’ll know that all three nodes are in sync when `juju status` reports `Workload=active` and `Agent=idle`:
```
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel  Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  edge      36  10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1   active    idle   10.1.84.127         Unit is ready: Mode: RO
mysql-k8s/2   active    idle   10.1.84.73          Unit is ready: Mode: RO
```

### Remove cluster members (replicas)
Removing a unit from the application, scales the replicas down. Before we scale down the replicas, list all the units with `juju status`, here you will see three units `mysql-k8s/0`, `mysql-k8s/1`, and `mysql-k8s/2`. Each of these units hosts a MySQL replica. To scale the application down to two units, enter:
```shell
juju scale-application mysql-k8s 2
```

You’ll know that the replica was successfully removed when `juju status --watch 1s` reports:
```
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel  Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  edge      36  10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1   active    idle   10.1.84.127         Unit is ready: Mode: RO
```