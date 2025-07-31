
# Switchover / Failover of Async replication

## Pre-requisits

Make sure both `Rome` and `Lisbon` Clusters are deployed using the [Async Deployment manual](/how-to/cross-regional-async-replication/deploy)!

## Switchover (safe)

Assuming `Rome` is currently `Primary` and you want to promote `Lisbon` to be new primary<br/>(`Rome` will be converted to `StandBy` member):

```shell
juju run -m lisbon db2/leader promote-to-primary 
```

## Failover (forced)

```{caution}

**Warning**: this is a **dangerous** operation which can cause the split-brain situation.<br/>It should be executed if Primary cluster is NOT recoverable any longer!<br/>Otherwise please use safe 'switchover' procedure above!

```

Assuming `Rome` was a `Primary` (before we lost the cluster `Rome`) and you want to promote `Lisbon` to be the new primary:

```shell
juju run -m lisbon db2/leader promote-to-primary force=True
```

> **Warning**: The `force` will cause the old primary to be invalidated.

