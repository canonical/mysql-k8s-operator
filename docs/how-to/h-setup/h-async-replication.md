# Configuring asynchronous replication: MySQL InnoDB ClusterSet

> **WARNING**: it is an internal article. Do NOT use it in production! Contact [Canonical Data Platform team](https://chat.charmhub.io/charmhub/channels/data-platform) if you are interested in the topic.

To avoid copy&paste manuals in design document,  please follow [Charmed MySQL Async Replication](https://charmhub.io/mysql/docs/h-async-replication) PoC with a difference:
```
- juju ssh mysql/0 ...
+ juju ssh --container mysql mysql-k8s/0 ...
```