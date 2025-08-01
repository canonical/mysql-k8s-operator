# Deploy on MicroK8s

This guide assumes you have a running Juju and MicroK8s environment. 

For a detailed walkthrough of setting up an environment and deploying the charm on MicroK8s, refer to the [Tutorial](/tutorial/index).

[Bootstrap](https://juju.is/docs/juju/juju-bootstrap) a juju controller and create a [model](https://juju.is/docs/juju/juju-add-model) if you haven't already:
```shell
juju bootstrap microk8s <controller name>
juju add-model <model name>
```

Deploy MySQL:
```shell
juju deploy mysql-k8s --channel 8.0/stable --trust
```
> :warning: The `--trust` flag is necessary to create some K8s resources.

> See the [`juju deploy` documentation](https://juju.is/docs/juju/juju-deploy) for all available options at deploy time.
> 
> See the [Configurations tab](https://charmhub.io/mysql/configurations) for specific MySQL parameters.

Sample output of `juju status --watch 1s`:
```shell
Model   Controller  Cloud/Region        Version  SLA          Timestamp
mysql   overlord    microk8s/localhost  2.9.38   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      1  mysql-k8s  8.0/stable  75   10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Primary
```

