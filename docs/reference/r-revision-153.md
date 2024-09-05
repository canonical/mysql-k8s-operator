>Reference > Release Notes > [All revisions](/t/11878) > Revision 153
# Revision 153
  
<sub>June 27, 2024</sub>
  
Dear community,
  
We'd like to announce that Canonical's newest Charmed MySQL K8s operator has been published in the '8.0/stable' [channel](https://charmhub.io/mysql-k8s/docs/r-releases?channel=8.0/stable) :tada:
  
[note]
If you are jumping over several stable revisions, make sure to check [previous release notes](/t/11878) before upgrading to this revision.
[/note]  

> **IMPORTANT**: current charm revision requires **[Juju 3.4.3/3.5.2+](/t/11878)**!<br/>[BTW, it is trivial to update Juju](/t/14333)! [Check all other requirements](/t/11421).
## Features you can start using today
  
* New workload version [MySQL 8.0.36](https://dev.mysql.com/doc/relnotes/mysql/8.0/en/news-8-0-36.html)
* [Async replication between clouds](/t/13458) [[DPE-2959](https://warthogs.atlassian.net/browse/DPE-2959)]
* [Add COS Tempo tracing support](/t/14448) [[#424](https://github.com/canonical/mysql-k8s-operator/pull/424)][[DPE-4368](https://warthogs.atlassian.net/browse/DPE-4368)]
* Add [experimental_max_connections](https://charmhub.io/mysql-k8s/configuration?channel=8.0/candidate#experimental-max-connections) config [[#425](https://github.com/canonical/mysql-k8s-operator/pull/425)][[DPE-3706](https://warthogs.atlassian.net/browse/DPE-3706)]
* Latest ROCK latest version [[DPE-3717](https://warthogs.atlassian.net/browse/DPE-3717)] 
* Internal disable operator mode [[DPE-2184](https://warthogs.atlassian.net/browse/DPE-2184)]
* TLS CA chain support [[PR#383](https://github.com/canonical/mysql-k8s-operator/pull/383)]
* All the functionality from [previous revisions](/t/11878)

## Bugfixes
   
Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/mysql-k8s-operator/issues) platforms.  
[GitHub Releases](https://github.com/canonical/mysql-k8s-operator/releases) provide a detailed list of bugfixes, PRs, and commits for each revision.  
 
* Updated shared libraries
* Applied the latest Juju secrets related fixes
* Fixed Sunbeam: charm is trying fail to set `report_host` on scale up [#435](https://github.com/canonical/mysql-k8s-operator/pull/435),  [DPE-3896](https://warthogs.atlassian.net/browse/DPE-3896)
* Skip config change when no pebble connection in [#445](https://github.com/canonical/mysql-k8s-operator/pull/445), [DPE-4768](https://warthogs.atlassian.net/browse/DPE-4768) 
* Fix restart for single-unit in [#438](https://github.com/canonical/mysql-k8s-operator/pull/438), [DPE-4411](https://warthogs.atlassian.net/browse/DPE-4411)
* Updated ROCK image

## Inside the charms
  
* Charmed MySQL K8s ships MySQL `8.0.36-0ubuntu0.22.04.1`
* CLI mysql-shell updated to `8.0.36+dfsg-0ubuntu0.22.04.1~ppa4`
* Backup tools xtrabackup/xbcloud is `8.0.35-30`
* The Prometheus mysqld-exporter is `0.14.0-0ubuntu0.22.04.1~ppa2`
* K8s charms [based on our ROCK OCI](https://github.com/canonical/charmed-mysql-rock) (Ubuntu LTS  `22.04.4`) revision `103`
* Principal charms support the latest Ubuntu 22.04 LTS only

## Technical notes
  
* Upgrade (`juju refresh`) is possible from revision 75+
* [Creating Async replication](/t/13458) under significant write load to Primary could lead to MySQL DB deadlock and replication setup failures, more details in official [charm bugreport](https://github.com/canonical/mysql-k8s-operator/issues/399) and [MySQL bug](https://bugs.mysql.com/bug.php?id=114624&thanks=sub).
* Use this operator together with modern operator [MySQL Router K8s](https://charmhub.io/mysql-router-k8s)
* Please check restrictions from [previous release notes](/t/11878)  
* Ensure [the charm requirements](/t/11421) met.
  
## Contact us
  
Charmed MySQL K8s is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/mysql-k8s-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.