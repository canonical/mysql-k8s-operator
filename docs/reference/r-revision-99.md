# Charmed MySQL K8s revision 99
<sub>September 18, 2023</sub>

Dear community, this is to inform you that new Canonical Charmed MySQL K8s is published in `8.0/stable` [charmhub](https://charmhub.io/mysql-k8s?channel=8.0/stable) channel for Kubernetes.

## The features you can start using today:

* [Add Juju 3 support](/t/11421) (Juju 2 is still supported) [[DPE-1790](https://warthogs.atlassian.net/browse/DPE-1790)]
* Peer secrets are now stored in [Juju secrets](https://juju.is/docs/juju/manage-secrets) [[DPE-1813](https://warthogs.atlassian.net/browse/DPE-1813)]
* Charm [minor upgrades](/t/11752) and [minor rollbacks](/t/11753) [[DPE-2206](https://warthogs.atlassian.net/browse/DPE-2206)]
* [Profiles configuration](/t/11892) support [[DPE-2154](https://warthogs.atlassian.net/browse/DPE-2154)]
* Workload updated to [MySQL 8.0.34](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-34.html) [[DPE-2426](https://warthogs.atlassian.net/browse/DPE-2426)]
* Support `juju expose` [[DPE-1215](https://warthogs.atlassian.net/browse/DPE-1215)]
* Add the first Prometheus alert rule (COS Loki) [[PR#244](https://github.com/canonical/mysql-k8s-operator/pull/244)]
* New documentation:
  * [Architecture (HLD/LLD)](/t/11757)
  * [Upgrade section](/t/11754)
  * [Release Notes](/t/11878)
  * [Requirements](/t/11421)
  * [Users](/t/10791)
  * [Statuses](/t/11866)
  * [Development](/t/11884)
  * [Testing reference](/t/11772)
  * [Legacy charm](/t/11236)
  * [Contacts](/t/11868)
* All the functionality from [the previous revisions](/t/11878)

## Bugfixes included:

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-k8s-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/mysql-k8s-operator/releases) provide a detailed list of bugfixes/PRs/Git commits for each revision.<br/>Highlights for the current revision:

* [DPE-1919](https://warthogs.atlassian.net/browse/DPE-1919) Fixed GKE [deployment support](/t/10875)
* [DPE-1519](https://warthogs.atlassian.net/browse/DPE-1519) Stabilized integration with mysql-route-k8s
* [DPE-2069](https://warthogs.atlassian.net/browse/DPE-2069) Fixed MySQL max_connections auto tune
* [DPE-2225](https://warthogs.atlassian.net/browse/DPE-2225) Fixed MySQL memory allocation (use K8s `Allocatable` memory instead of `free` + consider `group_replication_message_cache_size`)
* [DPE-988](https://warthogs.atlassian.net/browse/DPE-988) Fixed standby units (9+ cluster members are waiting to join the cluster)
* [DPE-2352](https://warthogs.atlassian.net/browse/DPE-2352) Start mysqld-exporter on COS relation only + restart upon monitoring password change
* [DPE-1512](https://warthogs.atlassian.net/browse/DPE-1512) Auto-generate `username`/`database` when config values are empty (for legacy `mysql` relation)
* [DPE-2178](https://warthogs.atlassian.net/browse/DPE-2178) Stop configuring mysql user `root@%` (removed as no longer necessary)

## What is inside the charms:

* Charmed MySQL K8s ships the latest MySQL “8.0.34-0ubuntu0.22.04.1”
* CLI mysql-shell updated to "8.0.34-0ubuntu0.22.04.1~ppa1"
* Backup tools xtrabackup/xbcloud  updated to "8.0.34-29"
* The Prometheus mysqld-exporter is "0.14.0-0ubuntu0.22.04.1~ppa1"
* K8s charms [based on our](https://github.com/orgs/canonical/packages?tab=packages&q=charmed) ROCK OCI (Ubuntu LTS “22.04” - ubuntu:22.04-based)
* Principal charms supports the latest LTS series “22.04” only.
* Subordinate charms support LTS “22.04” and “20.04” only.

## Technical notes:

* Upgrade (`juju refresh`) from the old-stable revision 75 to the current-revision 99 is **NOT** supported!!! The [upgrade](/t/11754) functionality is new and supported for revision 99+ only!
* Please check additionally [the previously posted restrictions](/t/11879).
* Ensure [the charm requirements](/t/11421) met.

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/data-platform) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/11868).

Consider [opening a GitHub issue](https://github.com/canonical/mysql-k8s-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) to the project!

## Hints:

Please check [all the previous release notes](/t/11878) if you are jumping over the several stable revisions!