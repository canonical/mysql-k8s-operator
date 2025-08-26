# Recovering from quorum loss

Quorum loss in MySQL happens when the majority of nodes (the quorum) required to make decisions and
maintain consistency is no longer available. This can happen due to network issues, node failures,
or other disruptions. When this occurs, the cluster may become unavailable or enter a read-only
state.

Although the charm cannot automatically recover from quorum loss, you can take the following steps
to manually recover the cluster.

```{warning}
Recovery from quorum loss should be performed with caution, as it can impact the availability and
cause loss of data.
```

## Ensure the cluster is in no-quorum state

A quorum loss will typically look like this in the juju status output:

```
Model   Controller  Cloud/Region             Version  SLA          Timestamp
mymodel localhost   default                  3.6.8    unsupported  17:52:19Z

App    Version                  Status   Scale  Charm      Channel           Rev  Address        Exposed  Message
mysql  8.0.42-0ubuntu0.22.04.2  waiting      3  mysql-k8s  8.0/edge          279  10.152.183.61  no       waiting for units to settle down

Unit      Workload     Agent  Address     Ports  Message
mysql/0*  maintenance  idle   10.1.2.48          offline
mysql/1   maintenance  idle   10.1.0.195         offline
mysql/2   active       idle   10.1.1.81
```

From an active unit, check the cluster status with:

```shell
juju run mysql/2 get-cluster-status
```

Which will output the current status of the cluster.

```
Running operation 17 with 1 task
  - task 18 on unit-mysql-2

Waiting for task 18...
status:
  clustername: cluster-3eab807dee6797402ecfc52b5a84d15b
  clusterrole: primary
  defaultreplicaset:
    name: default
    primary: mysql-0.mysql-endpoints.m3.svc.cluster.local.:3306
    ssl: required
    status: no_quorum
    statustext: cluster has no quorum as visible from 'mysql-2.mysql-endpoints.m3.svc.cluster.local.:3306'
      and cannot process write transactions. 2 members are not active.
    topology:
      mysql-0:
        address: mysql-0.mysql-endpoints.m3.svc.cluster.local.:3306
        instanceerrors: '[''note: group_replication is stopped.'']'
        memberrole: primary
        memberstate: offline
        mode: n/a
        role: ha
        status: unreachable
        version: 8.0.42
      mysql-1:
        address: mysql-1.mysql-endpoints.m3.svc.cluster.local.:3306
        instanceerrors: '[''note: group_replication is stopped.'']'
        memberrole: secondary
        memberstate: offline
        mode: n/a
        role: ha
        status: unreachable
        version: 8.0.42
      mysql-2:
        address: mysql-2.mysql-endpoints.m3.svc.cluster.local.:3306
        memberrole: secondary
        mode: r/o
        replicationlagfromimmediatesource: ""
        replicationlagfromoriginalsource: ""
        role: ha
        status: online
        version: 8.0.42
    topologymode: single-primary
  domainname: cluster-set-3eab807dee6797402ecfc52b5a84d15b
  groupinformationsourcemember: mysql-2.mysql-endpoints.m3.svc.cluster.local.:3306
success: "True"
```

Note from the output, we can see that the cluster is in a no-quorum state, with `status:
no_quorum`.

## Recover the cluster from the active unit

Using the available active unit, run the action:

```shell
juju run mysql/2 promote-to-primary scope=unit force=true
```

The unit will become the new primary. Other offline units, if reachable, will rejoin automatically on the follow up `update-status` events.
