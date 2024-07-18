## Juju version

The charm supports both [Juju 2.9 LTS](https://github.com/juju/juju/releases) and [Juju 3.x](https://github.com/juju/juju/releases), however charm revisions may require different Juju versions. Always check the [charm release notes](/t/11878) to find the minimal Juju version for your deployment.

## Kubernetes requirements

* Kubernetes 1.27+
* Canonical MicroK8s 1.27+ (snap channel 1.27-strict/stable and newer)

## Minimum requirements

Make sure your machine meets the following requirements:
- Ubuntu 22.04 (Jammy) or later.
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required OCI/ROCKs and charms.

## Supported architectures

The charm is based on [ROCK OCI](https://github.com/canonical/charmed-mysql-rock) named "[charmed-mysql](https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql)", which is recursively based on SNAP "[charmed-mysql](https://snapcraft.io/charmed-mysql)", which is currently available for `amd64` only! The architecture `arm64` support is planned. Please [contact us](/t/11868) if you are interested in new architecture!

## Networking

At the moment IPv4 is supported only (see more [info](https://warthogs.atlassian.net/browse/DPE-4695)).

[Contact us](/t/11868) if you are interested in IPv6!

<a name="mysql-gr-limits"></a>
## MySQL Group Replication requirements
* In order to integrate with this charm, every table created by the integrated application [u]must[/u] have a [u]primary key[/u]. This is required by the [group replication plugin](https://dev.mysql.com/doc/refman/8.0/en/group-replication-requirements.html) enabled in this charm.
* the count of [Charmed MySQL K8s units](https://dev.mysql.com/doc/refman/8.0/en/group-replication-limitations.html) in a single Juju application is [u]limited to 9[/u]. Unit 10+ will start; however, they will not join the cluster but sleep in a hot-swap reserve.