[note]
**Note**: All commands are written for `juju >= v.3.0`

If you are using an earlier version, check the [Juju 3.0 Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# How to scale units

Replication in MySQL is the process of creating copies of the stored data. This provides redundancy, which means the application can provide self-healing capabilities in case one replica fails. In this context, each replica is equivalent to one juju unit.

This guide will show you how to establish and change the amount of juju units used to replicate your data. 

## Deploy MySQL K8s with replicas

To deploy MySQL K8s with multiple replicas, specify the number of desired units with the `-n` option.
```shell
juju deploy mysql-k8s --channel 8.0 --trust -n <number_of_replicas>
```
> It is recommended to use an odd number to prevent a [split-brain](https://en.wikipedia.org/wiki/Split-brain_(computing)) scenario.

### Primary vs. leader unit 

The MySQL primary server unit may or may not be the same as the [juju leader unit](https://juju.is/docs/juju/leader).

The juju leader unit is the represented in `juju status` by an asterisk (*) next to its name. 

To retrieve the juju unit that corresponds to the MySQL K8s primary, use the action `get-primary` on any of the units running ` mysql-k8s`:
```shell
juju run mysql-k8s/leader get-primary
```

Similarly, the primary replica is displayed as a status message in `juju status`. However, one should note that this hook gets called on regular time intervals and the primary may be outdated if the status hook has not been called recently.

[note]
**We highly suggest configuring the `update-status` hook to run frequently.** In addition to reporting the primary, secondaries, and other statuses, the [status hook](https://juju.is/docs/sdk/update-status-event) performs self-healing in the case of a network cut. 

To change the frequency of the `update-status` hook, run
```shell
juju model-config update-status-hook-interval=<time(s/m/h)>
```
<!--Note that this hook executes a read query to PostgreSQL. On a production level server, this should be configured to occur at a frequency that doesn't overload the server with read requests. Similarly, the hook should not be configured at too quick of a frequency, as this can delay other hooks from running. -->
[/note]

## Scale replicas on an existing application
Both scaling-up and scaling-down operations are performed using `juju scale-application` and specifying the total amount of units you want to have in the cluster:
```shell
juju scale-application mysql-k8s <total number of units>
```

[note type=negative]
**Warning**: Do not remove the last unit, it will destroy your data!
[/note]