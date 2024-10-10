> [Charmed MySQL K8s Tutorial](/t/9677) > 3. Scale your replicas

# Scale your replicas

In this section, you will learn to scale your Charmed MySQL K8s by adding or removing juju units.

The Charmed MySQL K8s operator uses [MySQL InnoDB Cluster](https://dev.mysql.com/doc/refman/8.0/en/mysql-innodb-cluster-introduction.html) for scaling. It is built on MySQL [Group Replication](https://dev.mysql.com/doc/refman/8.0/en/group-replication.html), providing features such as automatic membership management, fault tolerance, and automatic failover. 

An InnoDB Cluster usually runs in a single-primary mode, with one primary instance (read-write) and multiple secondary instances (read-only). 

<!-- TODO: clarify "future" Future versions on Charmed MySQL will take advantage of a multi-primary mode, where multiple instances are primaries. Users can even change the topology of the cluster while InnoDB Cluster is online, to ensure the highest possible availability. -->

[note type="caution"]
**Disclaimer:** This tutorial hosts replicas all on the same machine. **This should not be done in a production environment.** 

To enable high availability in a production environment, replicas should be hosted on different servers to [maintain isolation](https://canonical.com/blog/database-high-availability).
[/note]

## Summary
* [Add replicas](#add-replicas)
* [Remove replicas](#remove-replicas)

---

Currently, your deployment has only one [juju unit](https://juju.is/docs/juju/unit), known in juju as the leader unit.  For each MySQL replica, a new juju unit (non-leader) is created. All units are members of the same database cluster.

## Add replicas
You can add two replicas to your deployed MySQL K8s application by scaling it to a total of three units with `juju scale-application`:
```shell
juju scale-application mysql-k8s 3
```

You can now watch the scaling process in live using: `juju status --watch 1s`. It usually takes several minutes for new cluster members to be added. 

You’ll know that all three nodes are in sync when `juju status` reports `Workload=active` and `Agent=idle`:
```
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  8.0/stable  36   10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1   active    idle   10.1.84.127         Unit is ready: Mode: RO
mysql-k8s/2   active    idle   10.1.84.73          Unit is ready: Mode: RO
```

[note]
The maximum number of Charmed MySQL units in a single Juju application is 9. This is a limitation of MySQL Group replication. Read more about all limitations in the [official MySQL documentation](https://dev.mysql.com/doc/refman/8.0/en/group-replication-limitations.html).
[/note]

## Remove replicas
Removing a unit from the application scales down the replicas. 

Before we scale down, list all the units with `juju status`. You will see three units: `mysql-k8s/0`, `mysql-k8s/1`, and `mysql-k8s/2`. Each of these units hosts a MySQL K8s replica. 

To scale the application down to two units, run:
```shell
juju scale-application mysql-k8s 2
```

You’ll know that the replica was successfully removed when `juju status --watch 1s` reports:
```
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  8.0/stable  36   10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1   active    idle   10.1.84.127         Unit is ready: Mode: RO
```

> Next step: [4. Manage passwords](/t/9673)