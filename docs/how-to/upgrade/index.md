# Upgrade

This section contains documentation about performing upgrades (and rollbacks) on:
* [MySQL Server (workload)](#mysql-upgrades-workload)
* [Juju version](#juju-upgrades)

## MySQL upgrades (workload)
There are two types of in-place workload upgrades:
* **Major upgrades** -  E.g. MySQL `8.0` -> MySQL `9.0`
  * *Not supported*
* **Minor upgrades** -  E.g. MySQL `8.0.33` -> `8.0.34` (includes charm revision bump)
  * See: [How to perform a minor upgrade](/how-to/upgrade/perform-a-minor-upgrade)
  * See: [How to perform a minor rollback](/how-to/upgrade/perform-a-minor-rollback)

```{caution}
This charm only supports in-place **minor** upgrades. 

To upgrade to a major MySQL version, one must install a new cluster separately and migrate the data from the old to the new installation. This documentation will be updated with the migration instructions when a new MySQL version becomes available.
```

## Juju upgrades

New revisions of the charm may require that you do a major or minor Juju upgrade.

See: [How to upgrade Juju](/how-to/upgrade/upgrade-juju)

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

Upgrade Juju <upgrade-juju>
Perform a minor rollback <perform-a-minor-rollback>
Perform a minor upgrade <perform-a-minor-upgrade>
```
