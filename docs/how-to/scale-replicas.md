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

````{note}
**We highly suggest configuring the `update-status` hook to run frequently.** In addition to reporting the primary, secondaries, and other statuses, the [status hook](https://documentation.ubuntu.com/juju/3.6/reference/hook/#update-status) performs self-healing in the case of a network cut. 

To change the frequency of the `update-status` hook, run
```shell
juju model-config update-status-hook-interval=<time(s/m/h)>
```
````

## Scale replicas on an existing application
Both scaling-up and scaling-down operations are performed using `juju scale-application` and specifying the total amount of units you want to have in the cluster:
```shell
juju scale-application mysql-k8s <total number of units>
```

```{warning}
Do not remove the last unit, it will destroy your data!
```

