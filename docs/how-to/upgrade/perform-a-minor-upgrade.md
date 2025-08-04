# Perform a minor upgrade

**Example**: MySQL 8.0.33 -> MySQL 8.0.34<br/>
(including charm revision bump: e.g. Revision 193 -> Revision 196)

This is part of the [Upgrade section](/how-to/upgrade/index). Refer to the landing page for more information and an overview of the content.

We strongly recommend to **NOT** perform any other extraordinary operations on a Charmed MySQL K8s cluster, while upgrading. These may be (but not limited to) the following:

1. Adding or removing units
2. Creating or destroying new relations
3. Changes in workload configuration
4. Upgrading other connected/related/integrated applications simultaneously

The concurrency with other operations is not supported, and it can lead the cluster into inconsistent states.


**Note**: Make sure to have a backup of your data when running any type of upgrades!
See: [How to create a backup](/how-to/back-up-and-restore/create-a-backup)

It is recommended to deploy your application in conjunction with [Charmed MySQL Router K8s](https://charmhub.io/mysql-router-k8s). This will ensure minimal service disruption, if any.

## Summary of the upgrade steps

1. [**Collect**](#step-1-collect) all necessary pre-upgrade information. It will be necessary for the rollback (if requested). Do not skip this step!
2. [**Scale-up** (optional)](#step-2-scale-up-optional). The new unit will be the first one to be updated, and it will simplify the rollback procedure a lot in case of the upgrade failure.
3. [**Prepare**](#step-3-prepare) the Charmed MySQL K8s application for the in-place upgrade.
4. [**Upgrade**](#step-4-upgrade). Once started, only one unit in a cluster will be upgraded. In case of failure, the rollback is simple: remove newly added pod (via [step 2](#step-2-scale-up-optional)).
5. [**Resume** upgrade](#step-5-resume). If the new pod is OK after the refresh, the upgrade can be resumed for all other units in the cluster. All units in a cluster will be executed sequentially from the largest ordinal number to the lowest.
6. Consider a [**rollback**](#step-6-rollback-optional) in case of disaster. Please inform and include us in your case scenario troubleshooting to trace the source of the issue and prevent it in the future. [Contact us](/reference/contacts)!
7. [**Scale-back** (optional)](#step-7-scale-back). Remove no longer necessary K8s pod created in step 2 (if any).
8. [Post-upgrade **check**](#step-8-check). Make sure all units are in a healthy state.

## Step 1: Collect


**Note**:  This step is only valid when deploying from [charmhub](https://charmhub.io/). 

If a [local charm](https://juju.is/docs/sdk/deploy-a-charm) is deployed (revision is small, e.g. 0-10), make sure the proper/current local revision of the `.charm` file is available BEFORE going further. You might need it for a rollback.

The first step is to record the revision of the running application as a safety measure for a rollback action. To accomplish this, run the `juju status` command and look for the deployed Charmed MySQL K8s revision in the command output, e.g:

```shell
Model      Controller  Cloud/Region        Version  SLA          Timestamp
my-model   mkc         microk8s/localhost  2.9.44   unsupported  01:20:47Z

App        Version                  Status  Scale  Charm      Channel  Rev  Address         Exposed  Message
mysql-k8s  8.0.32-0ubuntu0.22.04.2  active      3  mysql-k8s  8.0/edge  88  10.152.183.102  no       Primary

Unit          Workload  Agent  Address       Ports  Message
mysql-k8s/0*  active    idle   10.1.148.184         Primary
mysql-k8s/1   active    idle   10.1.148.138         
mysql-k8s/2   active    idle   10.1.148.143
```

For this example, the current revision is `88`. Store it safely to use in case of rollback!

## Step 2: Scale-up (optional)

Optionally, it is recommended to scale the application up by one unit before starting the upgrade process.

The new unit will be the first one to be updated, and it will assert that the upgrade is possible. In case of failure, having the extra unit will ease a future rollback procedure without disrupting service. 

```shell
juju scale-application mysql-k8s <total number of units desired>
```
> To scale up by 1 unit, `<total number of units desired>` would be the current number of units + 1 

Wait for the new unit to be ready.

## Step 3: Prepare

After the application has settled, it’s necessary to run the `pre-upgrade-check` action against the leader unit:

```shell
juju run mysql-k8s/leader pre-upgrade-check
```

The output of the action should look like:

```shell
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  ...
  results: {}
  status: completed
  ...
```

The action will configure the charm to minimize the amount of primary switchover, among other preparations for the upgrade process. After successful execution, the charm is ready to be upgraded.

## Step 4: Upgrade

Use the [`juju refresh`](https://juju.is/docs/juju/juju-refresh) command to trigger the charm upgrade process.

Example with channel selection
```shell
juju refresh mysql-k8s --channel 8.0/edge --trust
```

Example with specific revision selection (do not forget the OCI resource)
```shell
juju refresh mysql-k8s --revision=89 --resource mysql-image=...  --trust
```

The upgrade will execute only on the highest ordinal unit.

For the running example `mysql-k8s/2`, `juju status` would look similar to the output below:

```shell
Model      Controller  Cloud/Region        Version  SLA          Timestamp
my-model   mkc         microk8s/localhost  2.9.44   unsupported  01:20:47Z

App        Version                  Status  Scale  Charm      Channel  Rev  Address         Exposed  Message
mysql-k8s  8.0.32-0ubuntu0.22.04.2  waiting     3  mysql-k8s  8.0/edge  89  10.152.183.102  no       waiting for units to settle down

Unit          Workload     Agent      Address       Ports  Message
mysql-k8s/0*  active       idle       10.1.148.184         other units upgrading first...
mysql-k8s/1   active       idle       10.1.148.138         other units upgrading first...
mysql-k8s/2   active       idle       10.1.148.143         other units upgrading first...
mysql-k8s/3   maintenance  executing  10.1.148.145         upgrading unit
```

**Do NOT trigger `rollback` procedure during the running `upgrade` procedure.**
It is expected to have some status changes during the process: `waiting`, `maintenance`, `active`. 

Make sure `upgrade` has failed/stopped and cannot be fixed/continued before triggering `rollback`!

**Please be patient during huge installations.**
Each unit should recover shortly after the upgrade, but time can vary depending on the amount of data written to the cluster while the unit was not part of it. 

## Step 5: Resume

After the unit is upgraded, the charm will set the unit upgrade state as completed. 

If the unit is healthy within the cluster, the next step is to resume the upgrade process by running:

```shell
juju run mysql-k8s/leader resume-upgrade
```

`resume-upgrade` will rollout the upgrade for the following unit, always from highest ordinal number to lowest, and for each successful upgraded unit, the process will rollout the next automatically.

```shell
Model      Controller  Cloud/Region        Version  SLA          Timestamp
my-model   mkc         microk8s/localhost  2.9.44   unsupported  01:20:47Z

App        Version                  Status  Scale  Charm      Channel  Rev  Address         Exposed  Message
mysql-k8s  8.0.32-0ubuntu0.22.04.2  waiting     3  mysql-k8s  8.0/edge  89  10.152.183.102  no       waiting for units to settle down

Unit          Workload     Agent      Address       Ports  Message
mysql-k8s/0*  active       idle       10.1.148.184         other units upgrading first...
mysql-k8s/1   maintenance  executing  10.1.148.138         upgrading unit
mysql-k8s/2   active       idle       10.1.148.143         
mysql-k8s/3   active       idle       10.1.148.145 
```

## Step 6: Rollback (optional)

The step must be skipped if the upgrade went well! 

If there was an issue with the upgrade, even if the underlying MySQL cluster continues to work, it’s important to roll back the charm to the previous revision. That way, the update can be attempted again after a further inspection of the failure. 

> See: [How to perform a minor rollback](/how-to/upgrade/perform-a-minor-rollback)

## Step 7: Scale-back

Case the application scale was changed for the upgrade procedure, it is now safe to scale it back to the desired unit count:

```shell
juju scale-application mysql-k8s <total number of units desired>
```
> To scale down by 1 unit, `<total number of units desired>` would be the current number of units - 1 

Example:

[![asciicast](https://asciinema.org/a/7ZMAsPWU3wv7ynZI1JvgRFG31.png)](https://asciinema.org/a/7ZMAsPWU3wv7ynZI1JvgRFG31)

## Step 8: Check

Future improvements are [planned](https://warthogs.atlassian.net/browse/DPE-2620) to check the state of the pod/cluster on a low level. 

For now, use `juju status` to make sure the cluster [state](/reference/charm-statuses) is OK.

<!---
**More TODOs:**

* Clearly describe "failure state"!!!
* How to check progress of upgrade (is it failed or running?)?
* Hints how to fix failed upgrade? mysql-shell hints....
* Describe pre-upgrade check: free space, etc.
--->

