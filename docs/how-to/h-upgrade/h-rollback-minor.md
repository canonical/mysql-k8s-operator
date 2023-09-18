# Minor Rollback

Example: MySQL 8.0.34 -> MySQL 8.0.33<br/>
including simple charm revision bump (from revision 43 to revision 42).

> **:warning: WARNING**: it is an internal article. Do NOT use it in production! Contact [Canonical Data Platform team](https://chat.charmhub.io/charmhub/channels/data-platform) if you are interested in the topic.

> **:warning: WARNING**: do NOT trigger `rollback` during the running `upgrade` action! It may cause unpredictable MySQL Cluster state!

## Minor rollback steps

1. **Prepare** "Charmed MySQL K8s" Juju application for the in-place rollback. See the step description below for all technical details executed by charm here.
2. **Rollback**. Perform the first charm rollback, the first unit only. The unit with the maximal ordinal will be chosen.
3. **Resume**. Continue rollback to all other units if the first unit rolled-back successfully.
4. **Check**. Make sure the charm and cluster are in healthy state again.

## Manual Rollback

After a `juju refresh`, case there any version incompatibilities in charm revisions or it dependencies, or any other unexpected failure in the upgrade process, the upgrade process will be halted an enter a failure state.

Although the underlying MySQL Cluster continue to work, it’s important to rollback the charm to previous revision so an update can be later attempted after a further inspection of the failure.

To execute a rollback we take the same procedure as the upgrade, the difference being the charm revision to upgrade to. In case of this tutorial example, one would refresh the charm back to revision `88`, the steps being:

## Step 1: Prepare

TODO: No prepare? P.S. remove from steps above too!

## Step 2: Rollback

When using charm from charmhub:

```
juju refresh mysql-k8s --revision=88
```

Case deploying from local charm file, one need to have the previous revision charm file and the `mysql-image` resource, then run:

```
juju refresh mysql-k8s --path=./mysql-k8s_ubuntu-22.04-amd64.charm \
       --resource mysql-image=ghcr.io/canonical/charmed-mysql@sha256:753477ce39712221f008955b746fcf01a215785a215fe3de56f525380d14ad97
```

Where `mysql-k8s_ubuntu-22.04-amd64.charm` is the previous revision charm file. The reference for the resource for a given revision can be found at the `metadata.yaml` file in the [charm repository](https://github.com/canonical/mysql-k8s-operator/blob/e4beca6b34313a977eab5ab2c74fa43586f1154c/metadata.yaml#L35).

The first unit will be rolled out and should rejoin the cluster after settling down. After the refresh command, the juju controller revision for the application will be back in sync with the running Charmed MySQL K8s revision.

## Step 3: Resume

There still a need to resume the upgrade on the remaining units, which is done with the `resume-upgrade` action.

```shell
juju run-action mysql-k8s/leader resume-upgrade --wait
```

This will rollout the Pods in the remaining units, but to the same charm revision.

## Step 4: Check

TODO: add / describe `goss`?