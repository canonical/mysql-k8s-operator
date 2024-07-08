# Recovery of Async replication
> **WARNING**: it is an '8.0/candidate' article. Do NOT use it in production!<br/>Contact [Canonical Data Platform team](/t/11868) if you are interested in the topic.

## Pre-requisits
Make sure both `Rome` and `Lisbon` Clusters are deployed using the [Async Deployment manual](/t/13458)!

## Recovery detached cluster

If relation between clusters was removed and one side went into detached/blocked state: simply relate async replication back to restore ClusterSet.

## Recovery lost cluster

If a Cluster has been lost and the ClusterSet need new member: deploy new db application and init async replication. The data will be copied automatically and the new Cluster will join ClusterSet.

## Recovery invalidated cluster

A cluster in the cluster-set gets invalidated when async replication auto-recovery fails on a disconnection event or when a failover is run against another cluster-set member while this cluster is unreachable. If the invalidated cluster connections is restored, it's status will be displayed in juju status as:

```
App  Version                  Status  Scale  Charm      Channel   Rev  Address         Exposed  Message
db2  8.0.36-0ubuntu0.22.04.1  active      3  mysql-k8s  8.0/edge  137  10.152.183.241  no

Unit    Workload  Agent  Address       Ports  Message
db2/0   active    idle   10.1.124.208      
db2/1*  active    idle   10.1.124.203         Primary (standby, invalidated)
db2/2   active    idle   10.1.124.200      
```

Which indicates that connectivity is possible, but replication channel is stopped.
To restore replication operation, run:

```shell
juju run db2/leader rejoin-cluster cluster-name=rome
```

Being `rome` the name of the invalidated cluster.