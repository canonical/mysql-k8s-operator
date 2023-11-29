# Minor Upgrade

> :information_source: **Example**: MySQL 8.0.33 -> MySQL 8.0.34<br/>
(including simple charm revision bump: from revision 99 to revision 102)

This is part of the [Charmed MySQL K8s Upgrade](/t/11754). Please refer to this page for more information and the overview of the content.

We strongly recommend to **NOT** perform any other extraordinary operations on Charmed MySQL K8s cluster, while upgrading. As an examples, these may be (but not limited to) the following:

1. Adding or removing units
2. Creating or destroying new relations
3. Changes in workload configuration
4. Upgrading other connected/related/integrated applications simultaneously

The concurrency with other operations is not supported, and it can lead the cluster into inconsistent states.

> **:warning: NOTE:** Make sure to have a [backup](/t/9653) of your data when running any type of upgrades.

> **:information_source: TIP:** It’s recommended to deploy your application in conjunction with the [Charmed MySQL Router K8s](https://charmhub.io/mysql-router-k8s). This will ensure minimal service disruption, if any.

## Minor upgrade steps

1. **Collect** all necessary pre-upgrade information. It will be necessary for the rollback (if requested). Do NOT skip this step, it is better safe the sorry!
2. (optional) **Scale-up**. The new unit will be the first one to be updated, and it will simplify the rollback procedure a lot in case of the upgrade failure.
3. **Prepare** "Charmed MySQL" Juju application for the in-place upgrade. See the step description below for all technical details executed by charm here.
4. **Upgrade** (phase 1). Once started, only one unit in a cluster will be upgraded. In case of failure, the rollback is simple: remove newly added pod (in step 2).
5. **Resume** upgrade (phase 2). If the new pod is OK after the refresh, the upgrade can be resumed for all other units in the cluster. All units in a cluster will be executed sequentially: from biggest ordinal to the lowest one.
6. (optional) Consider to [**Rollback**](/t/11749) in case of disaster. Please inform and include us in your case scenario troubleshooting to trace the source of the issue and prevent it in the future. [Contact us](https://chat.charmhub.io/charmhub/channels/data-platform)!
7. (optional) **Scale-back**. Remove no longer necessary K8s pod created in step 2 (if any).
8. Post-upgrade **Check**. Make sure all units are in the proper state and the cluster is healthy.

## Step 1: Collect

> **:information_source: NOTE:** The step is only valid when deploying from charmhub. If the [local charm](https://juju.is/docs/sdk/deploy-a-charm) deployed (revision is small, e.g. 0-10), make sure the proper/current local revision of the `.charm` file is available BEFORE going further. You might need it for rollback.

The first step is to record the revision of the running application, as a safety measure for a rollback action. To accomplish this, simply run the `juju status` command and look for the deployed Charmed MySQL revision in the command output, e.g.:

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

For this example, the current revision is `88` . Store it safely to use in case of rollback!

## Step 2: Scale-up (optional)

Optionally, it is recommended to scale the application up by one unit before starting the upgrade process.

The new unit will be the first one to be updated, and it will assert that the upgrade is possible. In case of failure, having the extra unit will ease the rollback procedure, without disrupting service. More on the [Minor rollback](/t/11753) tutorial.

```shell
juju scale-application mysql-k8s <current_units_count+1>
```

Wait for the new unit up and ready.

## Step 3: Prepare

After the application has settled, it’s necessary to run the `pre-upgrade-check` action against the leader unit:

```shell
juju run-action mysql-k8s/leader pre-upgrade-check --wait
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

Use the [`juju refresh`](https://juju.is/docs/juju/juju-refresh) command to trigger the charm upgrade process. If using juju version 3 or higher, it is necessary to add the `--trust` option.

```shell
# example with channel selection and juju 2.9.x
juju refresh mysql-k8s --channel 8.0/edge

# example with channel selection and juju 3.x
juju refresh mysql-k8s --channel 8.0/edge --trust

# example with specific revision selection
juju refresh mysql-k8s --revision=89
```

> **:information_source: IMPORTANT:** The upgrade will execute only on the highest ordinal unit, for the running example `mysql-k8s/2`, the `juju status` will look like*:

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

> **:information_source: Note:** It is expected to have some status changes during the process: waiting, maintenance, active. Do NOT trigger `rollback` procedure during the running `upgrade` procedure. Make sure `upgrade` has failed/stopped and cannot be fixed/continued before triggering `rollback`!

> **:information_source: Note:** The unit should recover shortly after, but the time can vary depending on the amount of data written to the cluster while the unit was not part of the cluster. Please be patient on the huge installations.

## Step 5: Resume

After the unit is upgraded, the charm will set the unit upgrade state as completed. If deemed necessary the user can further assert the success of the upgrade. Being the unit healthy within the cluster, the next step is to resume the upgrade process, by running:

```shell
juju run-action mysql-k8s/leader resume-upgrade --wait
```

The `resume-upgrade` will rollout the upgrade for the following unit, always from highest from lowest, and for each successful upgraded unit, the process will rollout the next automatically.

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

Although the underlying MySQL Cluster continue to work, it’s important to rollback the charm to previous revision so an update can be later attempted after a further inspection of the failure. Please switch to the dedicated [minor rollback](/t/11753) tutorial if necessary.

## Step 7: Scale-back

Case the application scale was changed for the upgrade procedure, it is now safe to scale it back to the desired unit count:

```shell
juju scale-application mysql-k8s <unit_count>
```

An example on the following video:
[![asciicast](https://asciinema.org/a/7ZMAsPWU3wv7ynZI1JvgRFG31.png)](https://asciinema.org/a/7ZMAsPWU3wv7ynZI1JvgRFG31)

## Step 8: Check

The future [improvement is planned](https://warthogs.atlassian.net/browse/DPE-2620) to check the state on pod/cluster on a low level. At the moment check `juju status` to make sure the cluster [state](/t/11866) is OK.

<!---
**More TODOs:**

* Clearly describe "failure state"!!!
* How to check progress of upgrade (is it failed or running?)?
* Hints how to fix failed upgrade? mysql-shell hints....
* Describe pre-upgrade check: free space, etc.
--->