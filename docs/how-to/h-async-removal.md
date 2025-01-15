# Removal of Async replication

## Pre-requisits

Make sure both `Rome` and `Lisbon` Clusters are deployed using the [Async Deployment manual](/t/13458)!

## Detach Cluster from ClusterSet

> **Note**: It is important to [switchover](/t/13460) the `Primary` Cluster before detaching it from ClusterSet!

Assuming the `Lisbon` is a current `Primary` and we want to detach `Rome` (for removal or reuse):

```shell

juju remove-relation replication-offer db2:replication

```

The command above will move cluster `Rome` into the detached state `blocked` keeping all the data in place.

All units in `Rome` will be in a standalone (non-clusterized) read-only state.

From this points, there are three options, as described in the following sections.

## Rejoin detached cluster into previous ClusterSet

At this stage, the detached/blocked cluster `Rome` can re-join the previous ClusterSet by restoring async integration/relation:

```shell

juju switch rome

juju integrate replication-offer db1:replication

juju switch lisbon

juju run db2/leader create-replication

```

## Removing detached cluster

Remove no-longer necessary Cluster `Rome` (and destroy storage if Rome data is no longer necessary):

```shell

juju remove-application db1 # --destroy-storage

```

## New ClusterSet from detached Cluster

Convert `Rome` to the new Cluster/ClusterSet keeping the current data in use:

```shell

juju run -m rome db1/leader recreate-cluster

```