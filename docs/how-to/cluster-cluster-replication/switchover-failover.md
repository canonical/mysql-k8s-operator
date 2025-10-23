# Switchover / Failover

## Pre-requisites

Make sure both `Rome` and `Lisbon` Clusters are deployed using the [Async Deployment manual](/how-to/cluster-cluster-replication/deploy)!

## Switchover (safe)

Assuming `Rome` is currently `Primary` and you want to promote `Lisbon` to be new primary:

```shell
juju run -m lisbon db2/leader promote-to-primary scope=cluster
```

`Rome` will be converted to `StandBy` member.

## Failover (forced)

```{danger}
This is a **dangerous** operation which can cause a split-brain situation. 

It should ONLY be executed if Primary cluster is no longer exist (i.e. it is lost). Otherwise please use the safe switchover procedure described above!
```

Assuming `Rome` was a `Primary` (before we lost the cluster `Rome`) and you want to promote `Lisbon` to be the new primary:

```shell
juju run -m lisbon db2/leader promote-to-primary scope=cluster force=True
```

```{caution}
`force=True` will cause the old primary to be invalidated.
```

