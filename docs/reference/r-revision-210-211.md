>Reference > Release Notes > [All revisions] > Revision 211/210

# Revision 211/210
<sub>January 6, 2025</sub>

Dear community,

Canonical's newest Charmed MySQL K8s operator has been published in the [8.0/stable channel]:
* Revision 210 is built for `amd64` on Ubuntu 22.04 LTS
* Revision 211 is built for `arm64` on Ubuntu 22.04 LTS

If you are jumping over several stable revisions, check [previous release notes][All revisions] before upgrading.

---

## Highlights 
* Updated MySQL to `v8.0.39` ([PR #488](https://github.com/canonical/mysql-k8s-operator/pull/488)) ([DPE-4573](https://warthogs.atlassian.net/browse/DPE-4573))
* Added fully-featured terraform module ([PR #522](https://github.com/canonical/mysql-k8s-operator/pull/522)) ([DPE-5627](https://warthogs.atlassian.net/browse/DPE-5627))
  * See also: [How to deploy on Terraform](/t/14926)
* Updated COS alert rule descriptions ([PR #519](https://github.com/canonical/mysql-k8s-operator/pull/519)) ([DPE-5659](https://warthogs.atlassian.net/browse/DPE-5659))
  * See also: [How to enable alert rules](/t/15488), 
* Bumped juju versions ([PR #517](https://github.com/canonical/mysql-k8s-operator/pull/517))
  * `v2.9.50` -> `v2.9.51`
  * `v3.4.5` -> `v3.5.4`

## Features and improvements
* Integrated with Tempo HA and tested relay support of tracing traffic through `grafana-agent-k8s` ([PR #518](https://github.com/canonical/mysql-k8s-operator/pull/518)) ([DPE-5312](https://warthogs.atlassian.net/browse/DPE-5312))
* Adopted admin address throughout charm ([PR #502](https://github.com/canonical/mysql-k8s-operator/pull/502)) ([DPE-5178](https://warthogs.atlassian.net/browse/DPE-5178))
* Avoid ambiguous service selector when multiple `mysql` apps in a model have the same cluster-name ([PR #501](https://github.com/canonical/mysql-k8s-operator/pull/501)) ([DPE-4861](https://warthogs.atlassian.net/browse/DPE-4861))
* Ensure that uninitialized variable not referenced in `_is_cluster_blocked` helper ([PR #507](https://github.com/canonical/mysql-k8s-operator/pull/507)) ([DPE-5481](https://warthogs.atlassian.net/browse/DPE-5481))
* Recover from pod restarts during cluster creation during setup ([PR #499](https://github.com/canonical/mysql-k8s-operator/pull/499))
* Added timeout on node count query ([PR #514](https://github.com/canonical/mysql-k8s-operator/pull/514)) ([DPE-5582](https://warthogs.atlassian.net/browse/DPE-5582))

## Bugfixes and maintenance

* Fixed unit-initialized test may break when run too early ([PR #491](https://github.com/canonical/mysql-k8s-operator/pull/491)) ([DPE-5209](https://warthogs.atlassian.net/browse/DPE-5209))
* Common credentials fixture and `exec` timeout workaround ([PR #493](https://github.com/canonical/mysql-k8s-operator/pull/493)) ([DPE-5210](https://warthogs.atlassian.net/browse/DPE-5210))
* Fixed /database requested wait container ([PR #500](https://github.com/canonical/mysql-k8s-operator/pull/500)) ([DPE-5385](https://warthogs.atlassian.net/browse/DPE-5385))
* Attempted to stabilize failing integration tests ([PR #496](https://github.com/canonical/mysql-k8s-operator/pull/496))
* Add test to ensure correct k8s endpoints created for clusters with the same name ([PR #508](https://github.com/canonical/mysql-k8s-operator/pull/508))
* Add check to ensure peer databag populated before reconciling mysqld exporter pebble layers ([PR #505](https://github.com/canonical/mysql-k8s-operator/pull/505)) ([DPE-5417](https://warthogs.atlassian.net/browse/DPE-5417))
* Add base in test_multi_relations to workaround libjuju bug ([PR #506](https://github.com/canonical/mysql-k8s-operator/pull/506)) ([DPE-5480](https://warthogs.atlassian.net/browse/DPE-5480))

[details=Libraries, testing, and CI]

* increased key logs verbosity (s/debug/info/) ([PR #513](https://github.com/canonical/mysql-k8s-operator/pull/513))
* Run juju 3.6 nightly tests against 3.6/stable ([PR #533](https://github.com/canonical/mysql-k8s-operator/pull/533))
* Test for multi-relation scale in/out ([PR #489](https://github.com/canonical/mysql-k8s-operator/pull/489)) ([DPE-4613](https://warthogs.atlassian.net/browse/DPE-4613))
* Test against juju 3.6/candidate + upgrade dpw to v23.0.5 ([PR #527](https://github.com/canonical/mysql-k8s-operator/pull/527))
* Added workflow for nightly scheduled tests with juju 3.6 ([PR #490](https://github.com/canonical/mysql-k8s-operator/pull/490)) ([DPE-4976](https://warthogs.atlassian.net/browse/DPE-4976))
* Switch from tox build wrapper to charmcraft.yaml overrides ([PR #509](https://github.com/canonical/mysql-k8s-operator/pull/509))
* Update canonical/charming-actions action to v2.6.3 ([PR #497](https://github.com/canonical/mysql-k8s-operator/pull/497))
* Update codecov/codecov-action action to v5 ([PR #526](https://github.com/canonical/mysql-k8s-operator/pull/526))
* Update data-platform-workflows to v23.1.0 ([PR #532](https://github.com/canonical/mysql-k8s-operator/pull/532))
* Update dependency canonical/microk8s to v1.31 ([PR #495](https://github.com/canonical/mysql-k8s-operator/pull/495))
* Update dependency cryptography to v43 [SECURITY] ([PR #498](https://github.com/canonical/mysql-k8s-operator/pull/498))

[/details]

## Requirements and compatibility
* (increased) MySQL version: `v8.0.37` -> `v8.0.39`
* (increased) Minimum Juju 2 version:`v2.9.50` -> `v2.9.51`
* (increased) Minimum Juju 3 version:`v3.4.5` -> `v3.5.4`

See the [system requirements] for more details about Juju versions and other software and hardware prerequisites.

### Packaging

This charm is based on the Charmed MySQL K8s [rock image]. It packages:
* [mysql-server-8.0] `v8.0.39`
* [mysql-router] `v8.0.39`
* [mysql-shell] `v8.0.38`
* [prometheus-mysqld-exporter] `v0.14.0`
* [prometheus-mysqlrouter-exporter] `v5.0.1`
* [percona-xtrabackup] `v8.0.35`

See the [`/lib/charms` directory on GitHub] for more details about all supported libraries.

See the [`metadata.yaml` file on GitHub] for a full list of supported interfaces.


<!-- Topics -->
[All revisions]: /t/11878
[system requirements]: /t/11421

<!-- GitHub -->
[`/lib/charms` directory on GitHub]: https://github.com/canonical/mysql-k8s-operator/tree/main/lib/charms
[`metadata.yaml` file on GitHub]: https://github.com/canonical/mysql-k8s-operator/blob/main/metadata.yaml

<!-- Charmhub -->
[8.0/stable channel]: https://charmhub.io/mysql?channel=8.0/stable

<!-- Snap/Rock -->
[`charmed-mysql` packaging]: https://github.com/canonical/charmed-mysql-rock

[MySQL Libraries tab]: https://charmhub.io/mysql/libraries

[113/114]: https://github.com/canonical/charmed-mysql-snap/releases/tag/rev114
[rock image]: https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql

[mysql-server-8.0]: https://launchpad.net/ubuntu/+source/mysql-8.0/
[mysql-router]: https://launchpad.net/ubuntu/+source/mysql-8.0/
[mysql-shell]: https://launchpad.net/~data-platform/+archive/ubuntu/mysql-shell
[prometheus-mysqld-exporter]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqld-exporter
[prometheus-mysqlrouter-exporter]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqlrouter-exporter
[percona-xtrabackup]: https://launchpad.net/~data-platform/+archive/ubuntu/xtrabackup


<!-- Badges -->
[juju-2_amd64]: https://img.shields.io/badge/Juju_2.9.51-amd64-darkgreen?labelColor=ea7d56 
[juju-3_amd64]: https://img.shields.io/badge/Juju_3.4.6-amd64-darkgreen?labelColor=E95420 
[juju-3_arm64]: https://img.shields.io/badge/Juju_3.4.6-arm64-blue?labelColor=E95420