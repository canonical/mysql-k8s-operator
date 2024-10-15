> Reference > Release Notes > [All releases] > Revision 180/181

# Revision 180/181 
<sub>September 2, 2024</sub>

Dear community,

Canonical's newest Charmed MySQL K8s operator has been published in the [8.0/stable channel].

Due to the newly added support for arm64 architecture, the MySQL K8s charm now releases two revisions simultaneously:
* Revision 180 is built for `amd64` ( mysql-image  r113 )
* Revision 181 is built for `arm64` ( mysql-image  r113 )

To make sure you deploy for the right architecture, we recommend setting an [architecture constraint](https://juju.is/docs/juju/constraint#heading--arch) for your entire Juju model.

Otherwise, you can specify the architecture at deploy time with the `--constraints` flag as follows:

```shell
juju deploy mysql-k8s --constraints arch=<arch> --trust
```
where `<arch>` can be `amd64` or `arm64`.

[note]
This release of Charmed MySQL K8s requires Juju `v.3.4.3` or `3.5.2+`. See the [Requirements and compatibility](#requirements-and-compatibility) section for more information.
[/note]

---

## Highlights

Below is an overview of the major highlights, enhancements, and bugfixes in this revision. For a detailed list of all commits since the last stable release, see the [GitHub release notes].

### Enhancements
* Upgraded MySQL from `v8.0.36` -> `v8.0.37` (see [Packaging](#packaging))
* Added support or ARM64 architecture ([PR #448](https://github.com/canonical/mysql-k8s-operator/pull/448)) 
* Added support for Audit plugin ([PR #474](https://github.com/canonical/mysql-k8s-operator/pull/474)) ([DPE-4970](https://warthogs.atlassian.net/browse/DPE-4970))
*  Add first Awesome Alert Rules ([PR #469](https://github.com/canonical/mysql-k8s-operator/pull/469)) ([DPE-2477](https://warthogs.atlassian.net/browse/DPE-2477))
* Added support for rescanning cluster for unit rejoin after node drain ([PR #433](https://github.com/canonical/mysql-k8s-operator/pull/433)) ([DPE-4118](https://warthogs.atlassian.net/browse/DPE-4118))
* Changed binlog retention period (one week by default) ([PR #478](https://github.com/canonical/mysql-k8s-operator/pull/478)) ([DPE-4247](https://warthogs.atlassian.net/browse/DPE-4247))

### Bugfixes
* Removed passwords from outputs and tracebacks ([PR #473](https://github.com/canonical/mysql-k8s-operator/pull/473)) ([DPE-4266](https://warthogs.atlassian.net/browse/DPE-4266))
* Fixed intermittent issue on AKS deployments (unknown/idle state) ([PR #458](https://github.com/canonical/mysql-k8s-operator/pull/458)) ([DPE-4850](https://warthogs.atlassian.net/browse/DPE-4850))
* Strip passwords from command execute output and tracebacks ([PR #473](https://github.com/canonical/mysql-k8s-operator/pull/473)) ([DPE-4266](https://warthogs.atlassian.net/browse/DPE-4266))
* Address drained units rejoining the cluster with a new PV ([PR #433](https://github.com/canonical/mysql-k8s-operator/pull/433)) ([DPE-4118](https://warthogs.atlassian.net/browse/DPE-4118))
* Ensure username uniqueness ([PR #439](https://github.com/canonical/mysql-k8s-operator/pull/439)) ([DPE-4643](https://warthogs.atlassian.net/browse/DPE-4643))
* Backup stabilization fixes ([PR #444](https://github.com/canonical/mysql-k8s-operator/pull/444)) ([DPE-4699](https://warthogs.atlassian.net/browse/DPE-4699))
* Idempotent configure method ([PR #451](https://github.com/canonical/mysql-k8s-operator/pull/451)) ([DPE-4800](https://warthogs.atlassian.net/browse/DPE-4800))
* Show global-primary on endpoint ([PR #440](https://github.com/canonical/mysql-k8s-operator/pull/440)) ([DPE-4658](https://warthogs.atlassian.net/browse/DPE-4658))
* Fix metrics-endpoint created on scale up ([PR #483](https://github.com/canonical/mysql-k8s-operator/pull/483))

## Technical details
This section contains some technical details about the charm's contents and dependencies. 

If you are jumping over several stable revisions, check [previous release notes][All releases] before upgrading.

## Requirements and compatibility
This charm revision features the following changes in dependencies:
* (increased) MySQL version `v8.0.37`

> This release of Charmed MySQL K8s requires Juju `v.3.4.3` or `3.5.2+`. See the guide [How to upgrade Juju for a new database revision].

See the [system requirements] page for more details about software and hardware prerequisites.

### Integration tests
Below are the charm integrations tested with this revision on different Juju environments and architectures:
* Juju `v2.9.50` on `amd64`
* Juju  `v3.4.5` on `amd64` and `arm64`

**Juju `v2.9.50` on `amd64`:**

| Software | Version | |
|-----|-----|-----|
| [tls-certificates-operator] | `rev 22`, `legacy/stable` | 

**Juju `v3.4.5` on `amd64` and `arm64`:**
| Software | Version | |
|-----|-----|-----|
| [self-signed-certificates] | `rev 155`, `latest/stable` | 

**All:**
| Software | Version | |
|-----|-----|-----|
| [microk8s] | `v1.28.12` | |
| [s3-integrator] | `rev31` | |
| [mysql-test-app] |  `0.0.2` | |
| [mongodb-k8s] | `rev36` | |
| [kafka-k8s] | `rev5` | |
| [osm-keystone] | `rev10` | |
| [osm-pol] | `rev337` | |
| [zookeeper] | `10` | |

See the [`/lib/charms` directory on GitHub] for a full list of supported libraries.

See the [Integrations tab] for a full list of supported integrations/interfaces/endpoints


### Packaging
This charm is based on the [`charmed-mysql` rock]  (CharmHub  `mysql-image` resource-revision `113`). It packages:
- mysql-server-8.0: [8.0.37-0ubuntu0.22.04.1]
- mysql-router `v8.0.37`: [8.0.37-0ubuntu0.22.04.1]
- mysql-shell `v8.0.37`: [8.0.37+dfsg-0ubuntu0.22.04.1~ppa3]
- prometheus-mysqld-exporter `v0.14.0`: [0.14.0-0ubuntu0.22.04.1~ppa2]
- prometheus-mysqlrouter-exporter `v5.0.1`: [5.0.1-0ubuntu0.22.04.1~ppa1]
- percona-xtrabackup `v8.0.35`: [8.0.35-31-0ubuntu0.22.04.1~ppa3]

## Contact us
  
Charmed MySQL K8s is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/mysql-k8s-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.

<!-- LINKS -->
[8.0/stable channel]: https://charmhub.io/mysql-k8s?channel=8.0/stable
[GitHub release notes]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev181

[All releases]: /t/11878
[system requirements]: /t/11421
[How to upgrade Juju for a new database revision]: /t/14333

[Integrations tab]: https://charmhub.io/mysql-k8s/integrations
[Libraries tab]: https://charmhub.io/mysql/libraries

[`/lib/charms` directory on GitHub]: https://github.com/canonical/mysql-k8s-operator/tree/main/lib/charms

[juju]: https://juju.is/docs/juju/
[lxd]: https://documentation.ubuntu.com/lxd/en/latest/
[data-integrator]: https://charmhub.io/data-integrator
[s3-integrator]: https://charmhub.io/s3-integrator
[microk8s]: https://charmhub.io/microk8s
[tls-certificates-operator]: https://charmhub.io/tls-certificates-operator
[self-signed-certificates]: https://charmhub.io/self-signed-certificates
[mysql-test-app]: https://charmhub.io/mysql-test-app
[landscape-client]: https://charmhub.io/landscape-client
[ubuntu-advantage]: https://charmhub.io/ubuntu-advantage
[mongodb-k8s]: https://charmhub.io/mongodb-k8s
[kafka-k8s]: https://charmhub.io/kafka-k8s
[osm-keystone]: https://charmhub.io/osm-keystone
[osm-pol]: https://charmhub.io/osm-pol
[zookeeper]: https://charmhub.io/zookeeper

[`charmed-mysql` rock]: https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql
[8.0.37-0ubuntu0.22.04.1]: https://launchpad.net/ubuntu/+source/mysql-8.0/8.0.37-0ubuntu0.22.04.3
[8.0.37+dfsg-0ubuntu0.22.04.1~ppa3]: https://launchpad.net/~data-platform/+archive/ubuntu/mysql-shell
[0.14.0-0ubuntu0.22.04.1~ppa2]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqld-exporter
[5.0.1-0ubuntu0.22.04.1~ppa1]: https://launchpad.net/~data-platform/+archive/ubuntu/mysqlrouter-exporter
[8.0.35-31-0ubuntu0.22.04.1~ppa3]: https://launchpad.net/~data-platform/+archive/ubuntu/xtrabackup