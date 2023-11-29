# Architecture

[MySQL](https://www.mysql.com/) is the world’s most popular open source database. The “[Charmed MySQL K8s](https://charmhub.io/mysql-k8s)” is a Juju-based operator to deploy and support MySQL from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/), it is based on the [MySQL Community Edition](https://www.mysql.com/products/community/) using the built-in cluster functionality: [MySQL InnoDB ClusterSet](https://dev.mysql.com/doc/mysql-shell/8.0/en/innodb-clusterset.html).

## Juju K8s Concept

The charm design leverages the [sidecar](https://kubernetes.io/blog/2015/06/the-distributed-system-toolkit-patterns/#example-1-sidecar-containers) pattern to allow multiple containers in each pod with [Pebble](https://juju.is/docs/sdk/pebble) running as the workload container’s entrypoint.

Pebble is a lightweight, API-driven process supervisor that is responsible for configuring processes to run in a container and controlling those processes throughout the workload lifecycle.

Pebble `services` are configured through [layers](https://github.com/canonical/pebble#layer-specification), and the following containers represent each one a layer forming the effective Pebble configuration, or `pebble plan`:

1. a [charm]() container runs Juju operator code: `juju ssh mysql-k8s/0 bash`
1. a [mysql](https://www.mysql.com/) (workload) container runs the MySQL application along with other services (like monitoring metrics exporters, etc): `juju ssh --container mysql mysql-k8s/0 bash`

As a result, if you run a `kubectl get pods` on a namespace named for the Juju model you’ve deployed the "Charmed MySQL K8s" charm into, you’ll see something like the following:

```shell
NAME           READY   STATUS    RESTARTS   AGE
mysql-k8s-0    2/2     Running   0          65m
```

This shows there are 2 containers in the pod: `charm` and `workload` mentioned above.

And if you run `kubectl describe pod mysql-k8s-0`, all the containers will have as Command `/charm/bin/pebble`. That’s because Pebble is responsible for the processes startup as explained above.

<a name="hld"></a>
## HLD (High Level Design)

The "Charmed MySQL K8s" (`workload` container) based on `mysql-image` resource defined in the [charm metadata.yaml](https://github.com/canonical/mysql-k8s-operator/blob/main/metadata.yaml). It is an official Canonical "[charmed-mysql](https://github.com/canonical/charmed-mysql-rock)" [OCI/ROCK](https://ubuntu.com/server/docs/rock-images/introduction) image, which is recursively based on Canonical SNAP “[charmed-mysql](https://snapcraft.io/charmed-mysql)” (read more about the SNAP details [here](/t/11756)).

[Charmcraft](https://juju.is/docs/sdk/install-charmcraft) uploads an image as a [charm resource](https://charmhub.io/mysql-k8s/resources/mysql-image) to [Charmhub](https://charmhub.io/mysql-k8s) during the [publishing](https://github.com/canonical/mysql-k8s-operator/blob/main/.github/workflows/release.yaml#L40-L53), as described in the [Juju SDK How-to guides](https://juju.is/docs/sdk/publishing).

The charm supports Juju deploymed to all Kubernetes environments: [MicroK8s](https://microk8s.io/), [Charmed Kubernetes](https://ubuntu.com/kubernetes/charmed-k8s), [GKE](https://charmhub.io/mysql-k8s/docs/h-deploy-gke), [Amazon EKS](https://aws.amazon.com/eks/), ...

The OCI/ROCK ships the following components:

* MySQL Community Edition (based on SNAP "[charmed-mysql](/t/11756)") 
* MySQL Router (based on SNAP "[charmed-mysql](/t/11756)") 
* MySQL Shell (based on SNAP "[charmed-mysql](/t/11756)") 
* Percona XtraBackup (based on SNAP "[charmed-mysql](/t/11756)") 
* Prometheus MySQLd Exporter (based on SNAP "[charmed-mysql](/t/11756)") 
* Prometheus MySQL Router Exporter (based on SNAP "[charmed-mysql](/t/11756)") 
* Prometheus Grafana dashboards and Loki alert rules are part of the charm revision and missing in SNAP.

SNAP-based ROCK images guaranties the same components versions and functionality between VM and K8s charm flavors.

Pebble runs layers of all the currently enabled services, e.g. monitoring, backups, etc: 
```shell
> juju ssh --container mysql mysql-k8s/0 /charm/bin/pebble plan
services:
    mysqld_exporter:
        summary: mysqld exporter
        startup: disabled                   <= COS Monitoring disabled
        override: replace
        command: /start-mysqld-exporter.sh
        environment:
            DATA_SOURCE_NAME: user:password@unix(/var/run/mysqld/mysqld.sock)/
        user: mysql
        group: mysql
    mysqld_safe:
        summary: mysqld safe
        startup: enabled                    <= MySQL is up and running
        override: replace
        command: mysqld_safe
        user: mysql
        group: mysql
        kill-delay: 24h0m0s
```

The `mysqld_safe` is a main MySQL wrapper which is normally up and running right after the charm deployment.

The `mysql-router` used in [Charmed MySQL Router K8s](https://charmhub.io/mysql-router-k8s?channel=8.0/edge) only and should be stopped on [Charmed MySQL K8s](https://charmhub.io/mysql-k8s) deployments.

All `exporter` services are activated after the relation with [COS Monitoring](/t/9981) only.

> **:information_source: Note:** it is possible to star/stop/restart pebble services manually but it is NOT recommended to avoid a split brain with a charm state machine! Do it with a caution!!!

> **:warning: Important:** all pebble resources must be executed under the proper user (defined in  user:group options of pebble layer)!

The ROCK "charmed-mysql" also ships list of tools used by charm:
* `mysql` - mysql client to connect `mysqld`.
* `mysqlsh` - new [mysql-shell](https://dev.mysql.com/doc/mysql-shell/8.0/en/) client to configure MySQL cluster.
* `xbcloud` - a tool to download and upload full or part of xbstream archive from/to the cloud.
* `xbstream` - a tool to support simultaneous compression and streaming.
* `xtrabackup` - a tool to backup/restore MySQL DB.

The `mysql` and `mysqlsh` are well known and popular tools to manage MySQL.
The `xtrabackup (xbcloud+xbstream)` used for [MySQL Backups](/t/9653) only to store backups on S3 compatible storage.

<a name="integrations"></a>
## Integrations

### MySQL Router

[MySQL Router](https://dev.mysql.com/doc/mysql-router/8.0/en/) is part of MySQL InnoDB Cluster, and is lightweight middle-ware that provides transparent routing between your application and back-end MySQL Servers. The "[Charmed MySQL Router K8s](https://charmhub.io/mysql-router-k8s)" is an independent charm "Charmed MySQL K8s" can be related with.

### TLS Certificates Operator

[TLS Certificates](https://charmhub.io/tls-certificates-operator) charm responsible for distributing certificates through relationship. Certificates are provided by the operator through Juju configs. For the playground deployments, the [self-signed operator](https://charmhub.io/self-signed-certificates) is available as well.

### S3 Integrator

[S3 Integrator](https://charmhub.io/s3-integrator) is an integrator charm for providing S3 credentials to Charmed MySQL which seek to access shared S3 data. Store the credentials centrally in the integrator charm and relate consumer charms as needed.

### Data Integrator

[Data Integrator](https://charmhub.io/data-integrator) charm is a solution to request DB credentials for non-native Juju applications. Not all applications implement a data_interfaces relation but allow setting credentials via config. Also, some of the applications are run outside of juju. This integrator charm allows receiving credentials which can be passed into application config directly without implementing juju-native relation.

### MySQL Test App

The charm "[MySQL Test App](https://charmhub.io/mysql-test-app)" is a Canonical test application to validate the charm installation / functionality and perform the basic performance tests.

### Grafana

Grafana is an open-source visualization tools that allows to query, visualize, alert on, and visualize metrics from mixed datasources in configurable dashboards for observability. This charms is shipped with its own Grafana dashboard and supports integration with the [Grafana Operator](https://charmhub.io/grafana-k8s) to simplify observability. Please follow [COS Monitoring](/t/9981) setup.

### Loki

Loki is an open-source fully-featured logging system. This charms is shipped with support for the [Loki Operator](https://charmhub.io/loki-k8s) to collect the generated logs. Please follow [COS Monitoring](/t/9981) setup.

### Prometheus

Prometheus is an open-source systems monitoring and alerting toolkit with a dimensional data model, flexible query language, efficient time series database and modern alerting approach. This charm is shipped with a Prometheus exporters, alerts and support for integrating with the [Prometheus Operator](https://charmhub.io/prometheus-k8s) to automatically scrape the targets. Please follow [COS Monitoring](/t/9981) setup.

<a name="lld"></a>
## LLD (Low Level Design)

Please check the charm state machines displayed on [workflow diagrams](/t/10031). The low-level logic is mostly common for both VM and K8s charm flavors.

<!--- TODO: Describe all possible installations? Cross-model/controller? --->

### Juju Events

Accordingly to the [Juju SDK](https://juju.is/docs/sdk/event): “an event is a data structure that encapsulates part of the execution context of a charm”.

For this charm, the following events are observed:

1. [mysql_pebble_ready](https://juju.is/docs/sdk/container-name-pebble-ready-event): informs charm about the availability of the ROCK "charmed-mysql"-based `workload` K8s container. Also performs basic preparations to bootstrap the cluster on the first leader (or join the already configured cluster). 
2. [leader-elected](https://juju.is/docs/sdk/leader-elected-event): generate all the secrets to bootstrap the cluster.
5. [config_changed](https://juju.is/docs/sdk/config-changed-event): usually fired in response to a configuration change using the GUI or CLI. Create and set default cluster and cluster-set names in the peer relation databag (on the leader only).
6. [update-status](https://juju.is/docs/sdk/update-status-event): Takes care of workload health checks.
<!--- 7. database_storage_detaching: TODO: ops? event?
8. TODO: any other events? relation_joined/changed/created/broken
--->

### Charm Code Overview

The "[src/charm.py](https://github.com/canonical/mysql-k8s-operator/blob/main/src/charm.py)" is the default entry point for a charm and has the [MySQLCharmBase](https://github.com/canonical/mysql-k8s-operator/blob/main/lib/charms/mysql/v0/mysql.py) Python class which inherits from CharmBase.

CharmBase is the base class from which all Charms are formed, defined by [Ops](https://juju.is/docs/sdk/ops) (Python framework for developing charms). See more information in [Charm](https://juju.is/docs/sdk/constructs#heading--charm).

The `__init__` method guarantees that the charm observes all events relevant to its operation and handles them.

The VM and K8s charm flavors shares the codebase via [charm libraries](https://juju.is/docs/sdk/libraries) in [lib/charms/mysql/v0/](https://github.com/canonical/mysql-operator/blob/main/lib/charms/mysql/v0/) (of VM flavor of the charm!):
```
charmcraft list-lib mysql
Library name    API    Patch                                                                                                                                                                                                                          
backups         0      7                                                                                                                                                                                                                              
mysql           0      45                                                                                                                                                                                                                             
s3_helpers      0      4                                                                                                                                                                                                                              
tls             0      2                                     
```