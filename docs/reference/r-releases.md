# Release Notes

This page provides high-level overviews of the dependencies and features that are supported by each revision in every stable release.

To learn more about the different release tracks and channels, see the [Juju documentation about channels](https://juju.is/docs/juju/channel#heading--risk).

To see all releases and commits, check the [Charmed MySQL K8s Releases page on GitHub](https://github.com/canonical/mysql-k8s-operator/releases).

| Release | MySQL version | Juju version | [TLS encryption](/t/9655)* | [COS monitoring](/t/9981) | [Minor version upgrades](/t/11752) | [Cross-regional async replication](/t/13458) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| [210], [211] | 8.0.39 | `3.5.4+` | ![check] | ![check] | ![check] | ![check] |
| [180], [181] | 8.0.37 | `3.4.3+` | ![check] | ![check] | ![check] | ![check] |
| [153] | 8.0.36 | `3.4.3+` | ![check] | ![check] | ![check] | ![check] |
| [127] | 8.0.35 | `3.1.6+` |  | ![check] | ![check] |  |
| [113] | 8.0.34 | `3.1.6+` |  | ![check] | ![check] |  |
| [99] | 8.0.34 | `3.1.6+` |  | ![check] | ![check] |  |
| [75] | 8.0.32 | `2.9.32+` |  | ![check] | ![check] |  |

\* **TLS encryption**: Support for **`v2` or higher** of the [`tls-certificates` interface](https://charmhub.io/tls-certificates-interface/libraries/tls_certificates). This means that you can integrate with [modern TLS charms](https://charmhub.io/topics/security-with-x-509-certificates).

>For more details about a particular revision, refer to its dedicated Release Notes page.
For more details about each feature/interface, refer to the documentation linked in the column headers.

## Architecture and base
Several [revisions](https://juju.is/docs/sdk/revision) are released simultaneously for different [bases/series](https://juju.is/docs/juju/base) using the same charm code. In other words, one release contains multiple revisions.

> If you do not specify a revision on deploy time, Juju will automatically choose the revision that matches your base and architecture. 
> 
> See: [`juju set-constraints`](https://juju.is/docs/juju/juju-set-constraints), [`juju info`](https://juju.is/docs/juju/juju-info) 

### Release 210-211

| Revision | amd64 | arm64 | Ubuntu 22.04 LTS
|:--------:|:-----:|:-----:|:-----:|
|[210]  |![check] | | ![check]  |
|[211] |  | ![check]| ![check] |

[details=Older releases]
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
[210]: /t/16133
[211]: /t/16133
[180]: /t/15276
[181]: /t/15276
[153]: /t/14072
[127]: /t/13522
[113]: /t/12221
[99]: /t/11880
[75]: /t/11879

<!-- BADGES -->
[check]: https://img.icons8.com/color/20/checkmark--v1.png