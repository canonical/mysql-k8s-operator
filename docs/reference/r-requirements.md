## Juju version

The charm supports both [Juju 2.9 LTS](https://github.com/juju/juju/releases) and [Juju 3.1](https://github.com/juju/juju/releases).

Note: Juju 3.1 is supported from the charm revision 92+ only.

The minimum supported Juju versions are:

* 2.9.44+ (due to [missing](https://warthogs.atlassian.net/browse/DPE-2396) pebble `kill-delay` feature + fixes for [K8s scale-down](https://bugs.launchpad.net/juju/+bug/1977582) + [managing storage](https://bugs.launchpad.net/juju/+bug/1971937) issues).
* 3.1.6+ (due to issues with Juju secrets in previous versions, see [#1](https://bugs.launchpad.net/juju/+bug/2029285) and [#2](https://bugs.launchpad.net/juju/+bug/2029282))

## Minimum requirements

Make sure your machine meets the following requirements:
- Ubuntu 20.04 (Focal) or later.
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required OCI/ROCKs and charms.

## Supported architectures

The charm is based on [ROCK OCI](https://github.com/canonical/charmed-mysql-rock) named "[charmed-mysql](https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql)", which is recursively based on SNAP "[charmed-mysql](https://snapcraft.io/charmed-mysql)", which is currently available for `amd64` only! The architecture `arm64` support is planned. Please [contact us](https://chat.charmhub.io/charmhub/channels/data-platform) if you are interested in new architecture!

<a name="mysql-gr-limits"></a>
## MySQL Group Replication requirements
* In order to integrate with this charm, every table created by the integrated application [u]must[/u] have a [u]primary key[/u]. This is required by the [group replication plugin](https://dev.mysql.com/doc/refman/8.0/en/group-replication-requirements.html) enabled in this charm.
* the count of [Charmed MySQL K8s units](https://dev.mysql.com/doc/refman/8.0/en/group-replication-limitations.html) in a single Juju application is [u]limited to 9[/u]. Unit 10+ will start; however, they will not join the cluster but sleep in a hot-swap reserve.