# System requirements

The following are the minimum software and hardware requirements to run Charmed MySQL on Kubernetes.

## Summary

* [Software](#software)
  * [Juju](#juju)
  * [MySQL Group replication requirements](#mysql-group-replication-requirements)
* [Hardware](#hardware)
* [Networking](#networking)

---

## Software
* Ubuntu 22.04 (Jammy) or later
* Kubernetes 1.27+
* Canonical MicroK8s 1.27+ (snap channel 1.27-strict/stable and newer)

### Juju

The charm supports several Juju releases from [2.9 LTS](https://juju.is/docs/juju/roadmap#juju-juju-29) onwards. The table below shows which minor versions of each major Juju release are supported by the stable Charmhub releases of MySQL K8s. 

| Juju major release | Supported minor versions | Compatible charm revisions |Comment |
|:--------|:-----|:-----|:-----|
| ![3.5] | `3.5.2+` | [153]+ |     |
| ![3.4] | `3.4.3+` | [153]+ | Known issues with `3.4.2`: [bug #1](https://bugs.launchpad.net/juju/+bug/2065284), [bug #2](https://bugs.launchpad.net/juju/+bug/2064772)   |
| ![3.1] | `3.1.6+` | [99]+ |     |
| ![2.9 LTS] | `2.9.32+` | [75 ]+ |     |

### MySQL Group Replication requirements

* In order to integrate with this charm, every table created by the integrated application **must have a primary key**. This is required by the [group replication plugin](https://dev.mysql.com/doc/refman/8.0/en/group-replication-requirements.html) enabled in this charm.
* The count of [Charmed MySQL K8s units](https://dev.mysql.com/doc/refman/8.0/en/group-replication-limitations.html) in a single Juju application is limited to 9. Unit 10+ will start; however, they will not join the cluster but sleep in a hot-swap reserve.

## Hardware

Make sure your machine meets the following requirements:
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.

The charm is based on the [charmed-mysql ROCK OCI](https://github.com/canonical/charmed-mysql-rock), which is recursively based on the [charmed-mysql snap](https://snapcraft.io/charmed-mysql). It currently supports:
* `amd64`
* `arm64` (from revision 180+)

[Contact us](/t/11868) if you are interested in a new architecture!

## Networking
* Access to the internet for downloading the required OCI/ROCKs and charms.
* Only IPv4 is supported at the moment
  * See more information about this limitation in [this Jira issue](https://warthogs.atlassian.net/browse/DPE-4695)
  * [Contact us](/t/11868) if you are interested in IPv6!

<!-- LINKS -->
[153]: /t/14072
[99]: /t/11880
[75]: /t/11879

<!-- BADGES -->
[2.9 LTS]: https://img.shields.io/badge/2.9_LTS-%23E95420?label=Juju
[3.1]: https://img.shields.io/badge/3.1-%23E95420?label=Juju
[3.4]: https://img.shields.io/badge/3.4-%23E95420?label=Juju
[3.5]: https://img.shields.io/badge/3.5-%23E95420?label=Juju