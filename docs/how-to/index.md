
# How-to guides

Key processes and common tasks for managing and using Charmed MySQL on Kubernetes.

## Deployment and setup

Guidance for different cloud services:
* [Canonical K8s]
* [MicroK8s]
* [GKE]
* [EKS]
* [AKS]
* [Multi-AZ]

Specific deployment scenarios and architectures:
* [Terraform]
* [Air-gapped]

## Usage and maintenance
* [Integrate with another application]
* [External network access]
* [Scale replicas]
* [Enable TLS]

## Back up and restore
* [Configure S3 AWS]
* [Configure S3 RadosGW]
* [Create a backup]
* [Restore a backup]
* [Migrate a cluster]

## Monitoring (COS)
* [Enable monitoring]
* [Enable alert rules]
* [Enable tracing]

## Upgrades
See the [Upgrades landing page] for more details.
* [Upgrade Juju]
* [Perform a minor upgrade]
* [Perform a minor rollback]

## Cross-regional (cluster-cluster) async replication
* [Deploy]
* [Clients]
* [Switchover / Failover]
* [Recovery] 
* [Removal]

## Development
* [Integrate with your charm]
* [Migrate data via mysqldump]
* [Migrate data via mydumper]
* [Migrate data via backup/restore]
* [Troubleshooting]

<!--Links-->

[Canonical K8s]: /how-to/deploy/canonical-k8s
[MicroK8s]: /how-to/deploy/microk8s
[GKE]: /how-to/deploy/gke
[EKS]: /how-to/deploy/eks
[AKS]: /how-to/deploy/aks
[Multi-AZ]: /how-to/deploy/multi-az
[Terraform]: /how-to/deploy/terraform
[Air-gapped]: /how-to/deploy/air-gapped

[Integrate with another application]: /how-to/integrate-with-another-application
[External network access]: /how-to/external-network-access
[Scale replicas]: /how-to/scale-replicas
[Enable TLS]: /how-to/enable-tls

[Configure S3 AWS]: /how-to/back-up-and-restore/configure-s3-aws
[Configure S3 RadosGW]: /how-to/back-up-and-restore/configure-s3-radosgw
[Create a backup]: /how-to/back-up-and-restore/create-a-backup
[Restore a backup]: /how-to/back-up-and-restore/restore-a-backup
[Migrate a cluster]: /how-to/back-up-and-restore/migrate-a-cluster

[Enable monitoring]: /how-to/monitoring-cos/enable-monitoring
[Enable alert rules]: /how-to/monitoring-cos/enable-alert-rules
[Enable tracing]: /how-to/monitoring-cos/enable-tracing

[Upgrades landing page]: /how-to/upgrade/index
[Upgrade Juju]: /how-to/upgrade/upgrade-juju
[Perform a minor upgrade]: /how-to/upgrade/perform-a-minor-upgrade
[Perform a minor rollback]: /how-to/upgrade/perform-a-minor-rollback

[Deploy]: /how-to/cross-regional-async-replication/deploy
[Clients]: /how-to/cross-regional-async-replication/clients
[Switchover / Failover]: /how-to/cross-regional-async-replication/switchover-failover
[Recovery]: /how-to/cross-regional-async-replication/recovery
[Removal]: /how-to/cross-regional-async-replication/removal

[Integrate with your charm]: /how-to/development/integrate-with-your-charm.md
[Migrate data via mysqldump]: /how-to/development/migrate-data-via-mysqldump.md
[Migrate data via mydumper]: /how-to/development/migrate-data-via-mydumper.md
[Migrate data via backup/restore]: /how-to/development/migrate-data-via-backup-restore.md
[Troubleshooting]: /how-to/development/troubleshooting.md

```{toctree}
:titlesonly:
:maxdepth: 2
:glob:
:hidden:

*
*/index
```
