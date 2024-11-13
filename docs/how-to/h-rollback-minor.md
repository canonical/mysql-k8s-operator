[note]
**Note**: All commands are written for `juju >= v.3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Perform a minor rollback
**Example**: MySQL 8.0.34 -> MySQL 8.0.33<br/>
(including charm revision bump: e.g Revision 43 -> Revision 42)

After a `juju refresh`, if there are any version incompatibilities in charm revisions, its dependencies, or any other unexpected failure in the upgrade process, the process will be halted and enter a failure state.

Even if the underlying MySQL cluster continue to work, it’s important to roll back the charm to a previous revision so that an update can be attempted after further inspection of the failure.

[note type="caution"]
**Warning:** Do NOT trigger `rollback` during the running `upgrade` action! It may cause an  unpredictable MySQL cluster state!
[/note]

## Summary of the rollback steps
1. **Prepare** the Charmed MySQL K8s application for the in-place rollback.
2. **Rollback**. Perform the first charm rollback on the first unit only. The unit with the maximal ordinal will be chosen.
3. **Resume**. Continue rolling back the rest of the units if the first unit rolled back successfully.
4. **Check**. Make sure the charm and cluster are in healthy state again.

## Step 1: Prepare

To execute a rollback, we use a similar procedure to the upgrade. The difference is the charm revision to upgrade to. In this guide's example, we will refresh the charm back to revision `88`.

It is necessary to re-run `pre-upgrade-check` action on the leader unit, to enter the upgrade recovery state:
```shell
juju run mysql-k8s/leader pre-upgrade-check
```

## Step 2: Rollback

When using charm from charmhub:
```shell
juju refresh mysql-k8s --revision=88
```

When deploying from a local charm file, one must have the previous revision charm file and the `mysql-image` resource, then run:
```shell
juju refresh mysql-k8s --path=<path to charm file> --resource mysql-image=<image URL>
```
For example:
```shell
juju refresh mysql-k8s --path=./mysql-k8s_ubuntu-22.04-amd64.charm \
       --resource mysql-image=ghcr.io/canonical/charmed-mysql@sha256:753477ce39712221f008955b746fcf01a215785a215fe3de56f525380d14ad97
```
> where `mysql-k8s_ubuntu-22.04-amd64.charm` is the previous revision charm file. 

The reference for the resource for a given revision can be found in the [`metadata.yaml`](https://github.com/canonical/mysql-k8s-operator/blob/e4beca6b34313a977eab5ab2c74fa43586f1154c/metadata.yaml) file in the charm's repository under the key `upstream-source`.

The first unit will be rolled out and should rejoin the cluster after settling down. After the `refresh` command, the juju controller revision for the application will be back in sync with the running Charmed MySQL K8s revision.

## Step 3: Resume

To resume the upgrade on the remaining units use the `resume-upgrade` action:
```shell
juju run mysql-k8s/leader resume-upgrade
```

This will roll out the pods in the remaining units to the same charm revision.

## Step 4: Check

Future [improvements are planned](https://warthogs.atlassian.net/browse/DPE-2621) to check the state on pods/clusters on a low level. 

For now, check `juju status` to make sure the cluster [state](/t/11866) is OK.