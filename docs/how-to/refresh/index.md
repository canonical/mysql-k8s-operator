# Refresh (upgrade)

This charm supports in-place upgrades to higher versions via Juju's [`refresh`](https://documentation.ubuntu.com/juju/3.6/reference/juju-cli/list-of-juju-cli-commands/refresh/#details) command.

## Supported refreshes

```{eval-rst}
+------------+------------+----------+------------+
| From                    | To                    |
+------------+------------+----------+------------+
| Charm      | MySQL      | Charm    | MySQL      |
| revision   | Version    | revision | Version    |
+============+============+==========+============+
| 254, 255   | ``8.0.41`` |          |            |
+------------+------------+----------+------------+
| 240, 241   | ``8.0.41`` | 254, 255 | ``8.0.41`` |
+------------+------------+----------+------------+
| 210, 211   | ``8.0.39`` | 254, 255 | ``8.0.41`` |
|            |            +----------+------------+
|            |            | 240, 241 | ``8.0.41`` |
+------------+------------+----------+------------+
| 180, 181   | ``8.0.37`` | 254, 255 | ``8.0.41`` |
|            |            +----------+------------+
|            |            | 240, 241 | ``8.0.41`` |
|            |            +----------+------------+
|            |            | 210, 211 | ``8.0.39`` |
+------------+------------+----------+------------+
| 153        | ``8.0.36`` | 254, 255 | ``8.0.41`` |
|            |            +----------+------------+
|            |            | 240, 241 | ``8.0.41`` |
|            |            +----------+------------+
|            |            | 210, 211 | ``8.0.39`` |
|            |            +----------+------------+
|            |            | 180, 181 | ``8.0.37`` |
+------------+------------+----------+------------+
| 127        | ``8.0.35`` | None     |            |
+------------+------------+----------+------------+
| 113        | ``8.0.34`` | 127      | ``8.0.35`` |
+------------+------------+----------+------------+
| 99         | ``8.0.34`` | 127      | ``8.0.35`` |
|            |            +----------+------------+
|            |            | 113      | ``8.0.35`` |
+------------+------------+----------+------------+
| 75         | ``8.0.32`` | 127      | ``8.0.35`` |
|            |            +----------+------------+
|            |            | 113      | ``8.0.35`` |
|            |            +----------+------------+
|            |            | 99       | ``8.0.34`` |
+------------+------------+----------+------------+

```

Due to an upstream issue with MySQL Server version `8.0.35`, Charmed MySQL versions below [Revision 153](https://github.com/canonical/mysql-operator/releases/tag/rev153) **cannot** be upgraded using Juju's `refresh`.

To upgrade from older versions to Revision 153 or higher, the data must be migrated manually. See: [](/how-to/development/migrate-data-via-backup-restore).

### Juju version upgrade

Before refreshing the charm, make sure to check the [](/reference/releases) page to see if there any requirements for the new revision, such as a Juju version upgrade.

* [](/how-to/refresh/upgrade-juju)

## Refresh guides

To refresh a **single cluster**, see:

* [](/how-to/refresh/single-cluster/refresh-single-cluster)
* [](/how-to/refresh/single-cluster/roll-back-single-cluster)

To refresh a **multi-cluster** deployment, see

* [](/how-to/refresh/multi-cluster/refresh-multi-cluster)
* [](/how-to/refresh/multi-cluster/roll-back-multi-cluster)

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Single cluster <single-cluster/index>
Multi-cluster <multi-cluster/index>
Upgrade Juju <upgrade-juju>
```

<!--Links-->

[cross]: https://img.icons8.com/?size=16&id=CKkTANal1fTY&format=png&color=D00303
[check]: https://img.icons8.com/color/20/checkmark--v1.png