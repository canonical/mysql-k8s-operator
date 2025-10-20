# Cluster-cluster replication

Cluster-cluster asynchronous replication focuses on disaster recovery by distributing data across different servers.

For increased safety, it is recommended to deploy each cluster in a different geographical region.

## Substrate dependencies

The following table shows the source and target controller/model combinations that are currently supported:

|       |     AWS    |     GCP    |    Azure   |
|-------|------------|:----------:|:----------:|
| AWS   | ![ check ] |            |            |
| GCP   |            | ![ check ] |            |
| Azure |            |            | ![ check ] |

## Guides

```{toctree}
:titlesonly:
:maxdepth: 2

Deploy <deploy>
Clients <clients>
Switchover/failover <switchover-failover>
Recovery <recovery>
Removal <removal>
```

[check]: https://img.shields.io/badge/%E2%9C%93-brightgreen