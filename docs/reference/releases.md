# Releases

This page provides high-level overviews of the dependencies and features that are supported by each revision in every stable release.

To learn more about the different release tracks and channels, see the [Juju documentation about channels](https://documentation.ubuntu.com/juju/3.6/reference/charm/#risk).

To see all releases and commits, check the [Charmed MySQL K8s Releases page on GitHub](https://github.com/canonical/mysql-k8s-operator/releases).

| Release | MySQL version | Juju version | [TLS encryption](/how-to/enable-tls)* | [COS monitoring](/how-to/monitoring-cos/enable-monitoring) | [Minor version upgrades](/how-to/refresh/single-cluster/refresh-single-cluster) | [Cross-regional async replication](/how-to/cross-regional-async-replication/deploy) | [Point-in-time recovery](point-in-time-recovery)
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| [254], [255] | 8.0.41 | `3.5.4+` | ![check] | ![check] | ![check] | ![check] | ![check] |
| [240], [241] | 8.0.41 | `3.5.4+` | ![check] | ![check] | ![check] | ![check] | |
| [210], [211] | 8.0.39 | `3.5.4+` | ![check] | ![check] | ![check] | ![check] | |
| [180], [181] | 8.0.37 | `3.4.3+` | ![check] | ![check] | ![check] | ![check] | |
| [153] | 8.0.36 | `3.4.3+` | ![check] | ![check] | ![check] | ![check] | |
| [127] | 8.0.35 | `3.1.6+` |  | ![check] | ![check] |  | |
| [113] | 8.0.34 | `3.1.6+` |  | ![check] | ![check] |  | |
| [99] | 8.0.34 | `3.1.6+` |  | ![check] | ![check] |  | |
| [75] | 8.0.32 | `2.9.32+` |  | ![check] | ![check] |  | |

\* **TLS encryption**: Support for **`v2` or higher** of the [`tls-certificates` interface](https://charmhub.io/tls-certificates-interface/libraries/tls_certificates). This means that you can integrate with [modern TLS charms](https://charmhub.io/topics/security-with-x-509-certificates).

>For more details about a particular revision, refer to its dedicated Release Notes page.
For more details about each feature/interface, refer to the documentation linked in the column headers.

## Architecture and base
Several [revisions](https://documentation.ubuntu.com/juju/3.6/reference/charm/#charm-revision) are released simultaneously for different [bases/series](https://juju.is/docs/juju/base) using the same charm code. In other words, one release contains multiple revisions.

> If you do not specify a revision on deploy time, Juju will automatically choose the revision that matches your base and architecture. 
> 
> See: [`juju set-constraints`](https://juju.is/docs/juju/juju-set-constraints), [`juju info`](https://juju.is/docs/juju/juju-info) 

### Release 254-255

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[254]  || ![check]  | ![check]  |
|[255] |   ![check]| |  ![check] |

[details=Older releases]

### Release 240-241

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[240]  |![check] | | ![check]  |
|[241] |  | ![check]| ![check] |

### Release 210-211

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[210]  |![check] | | ![check]  |
|[211] |  | ![check]| ![check] |

### Release 180-181

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[180]  |![check] | | ![check]  |
|[181] |  | ![check]| ![check] |

### Release 153

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[153] |![check]| | ![check]   |

### Release 127

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[127] |![check]| | ![check]   |

### Release 113

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[113] |![check]| | ![check]   |

### Release 99

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[99] |![check]| | ![check]   |

### Release 75

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[75] |![check]| | ![check]   |
[/details]

<!-- LINKS -->
[255]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev255
[254]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev255
[240]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev240
[241]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev240
[210]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev210
[211]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev210
[180]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev180
[181]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev180
[153]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev153
[127]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev127
[113]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev113
[99]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev99
[75]: https://github.com/canonical/mysql-k8s-operator/releases/tag/rev75

<!-- BADGES -->
[check]: https://img.icons8.com/color/20/checkmark--v1.png

