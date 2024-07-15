# Switchover / Failover of Async replication

> **WARNING**: it is an '8.0/edge' article. Do NOT use it in production!<br/>Contact [Canonical Data Platform team](/t/11868) if you are interested in the topic.

## Pre-requisits

Make sure both `Rome` and `Lisbon` Clusters are deployed using the [Async Deployment manual](/t/13458)!

## Switchover (safe)

Assuming `Rome` is currently `Primary` and you want to promote `Lisbon` to be new primary<br/>(`Rome` will be converted to `StandBy` member):

```shell
juju run -m lisbon db2/leader promote-to-primary 
```

## Failover (forced)

[note type="caution"]

**Warning**: this is a **dangerous** operation which can cause the split-brain situation.<br/>It should be executed if Primary cluster is NOT recoverable any longer!<br/>Otherwise please use safe 'switchover' procedure above!

[/note]

Assuming `Rome` was a `Primary` (before we lost the cluster `Rome`) and you want to promote `Lisbon` to be the new primary:

```shell
juju run -m lisbon db2/leader promote-to-primary force=True
```

> **Warning**: The `force` will cause the old primary to be invalidated.