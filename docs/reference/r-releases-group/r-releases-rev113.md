# Charmed MySQL K8s revision 113
> :warning: The revision is currently available in `8.0/candidate` only (**WIP**).

Dear community, this is to inform you that new Canonical Charmed MySQL K8s is published in `8.0/stable` [charmhub](https://charmhub.io/mysql-k8s?channel=8.0/stable) channel for Kubernetes.

## The features you can start using today:

* Add [profile-limit-memory](https://charmhub.io/mysql-k8s/configure?channel=8.0/beta#profile-limit-memory) option [[PR#318](https://github.com/canonical/mysql-k8s-operator/pull/318)]
* Add [log rotation](https://charmhub.io/mysql-k8s/docs/e-logs) of error, general and slow query logs [[PR#312](https://github.com/canonical/mysql-k8s-operator/pull/312)][[DPE-1797](https://warthogs.atlassian.net/browse/DPE-1797)]
* Use Juju secret labels [[PR#333](https://github.com/canonical/mysql-k8s-operator/pull/333)][[DPE-2885](https://warthogs.atlassian.net/browse/DPE-2885)]
* Updated data-platform-libs for external secrets [[PR#314](https://github.com/canonical/mysql-k8s-operator/pull/314)]
* All the functionality from [the previous revisions](/t/11878)

## Bugfixes included:

Canonica Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-k8s-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/mysql-k8s-operator/releases) provide a detailed list of bugfixes/PRs/Git commits for each revision.<br/>Highlights for the current revision:

* Fixed dateformat in logrotate config to avoid causing filename conflicts after 24hrs of uptime [[PR#343](https://github.com/canonical/mysql-k8s-operator/pull/343)][[DPE-3063](https://warthogs.atlassian.net/browse/DPE-3063)]
* Fixed bug that resulted in wrong output displayed from list-backups action [[PR#340](https://github.com/canonical/mysql-k8s-operator/pull/340)]
* Fixed unit removal issue if TLS  operator is in use [[PR#347](https://github.com/canonical/mysql-k8s-operator/pull/347)]
* Fixed the single unit upgrade [[PR#324](https://github.com/canonical/mysql-k8s-operator/pull/324)][[DPE-2661](https://warthogs.atlassian.net/browse/DPE-2661)]
* Improved cluster metadata node addresses consistency [[PR#328](https://github.com/canonical/mysql-k8s-operator/pull/328)][[DPE-2774](https://warthogs.atlassian.net/browse/DPE-2774)]
* Fixed lib config file render [[#303](https://github.com/canonical/mysql-k8s-operator/pull/303)][[DPE-2124](https://warthogs.atlassian.net/browse/DPE-2124)]
* Prevent starting logrotate dispatcher or flush mysql logs until unit initialized [[PR#323](https://github.com/canonical/mysql-k8s-operator/pull/323)]
* Defer reconciling pebble layer for exporter [[PR#302](https://github.com/canonical/mysql-k8s-operator/pull/302)]

## What is inside the charms:

* Charmed MySQL K8s ships the latest MySQL “8.0.34-0ubuntu0.22.04.1”
* CLI mysql-shell updated to "8.0.34-0ubuntu0.22.04.1~ppa1"
* Backup tools xtrabackup/xbcloud  updated to "8.0.34-29"
* The Prometheus mysqld-exporter is "0.14.0-0ubuntu0.22.04.1~ppa1"
* K8s charms [based on our](https://github.com/orgs/canonical/packages?tab=packages&q=charmed) ROCK OCI (Ubuntu LTS “22.04” - ubuntu:22.04-based) based on SNAP revision 69
* Principal charms supports the latest LTS series “22.04” only
* Subordinate charms support LTS “22.04” and “20.04” only

## Technical notes:

* Upgrade (`juju refresh`) is possible from this revision 75+
* Use this operator together with a modern operator "[MySQL Router K8s](https://charmhub.io/mysql-router-k8s)"
* Please check additionally [the previously posted restrictions](/t/11878)

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/data-platform) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/11868).

Consider [opening a GitHub issue](https://github.com/canonical/mysql-k8s-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/mysql-k8s-operator/blob/main/CONTRIBUTING.md) to the project!

## Hints:

Please check [all the previous release notes](/t/11878) if you are jumping over the several stable revisions!