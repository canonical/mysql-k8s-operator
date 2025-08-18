# Troubleshooting

```{warning}
At the moment, there is NO ability to [pause the operator](https://warthogs.atlassian.net/browse/DPE-2545)!

Make sure your troubleshooting activity will not interfere with the operator itself!
```

See [](/reference/troubleshooting/known-scenarios.md) for specific operational issues and how to solve them.

## Check status

The first troubleshooting step is to run `juju status` and check the statuses and messages of all applications and units. 

See [](/reference/charm-statuses) for additional recommendations based on status.

## Check logs

Always check the Juju logs before troubleshooting further:

```shell
juju debug-log --replay --tail
```

Focus on `ERRORS` (normally there should be none):

```shell
juju debug-log --replay | grep -c ERROR
```

Consider to enable `DEBUG` log level IF you are troubleshooting unexpected charm behavior:

```shell
juju model-config 'logging-config=<root>=INFO;unit=DEBUG'
```

The MySQL logs are located in `workload` container:

```shell
> ls -la /var/log/mysql/
-rw-r----- 1 mysql mysql 8783 Sep 18 21:14 error.log
```

See [Juju logs documentation](https://juju.is/docs/juju/log) to learn more about logging.

## Check Kubernetes pods

Check the operator [architecture](/explanation/architecture) first to be familiar with the `charm` and `workload` containers.

Make sure both containers are `Running` and `Ready` to continue troubleshooting inside the charm. 

To describe the running pod, use the following command (where `0` is a Juju unit id):

```shell
kubectl describe pod mysql-k8s-0 -n <juju_model_name>
...
Containers:
  charm:
    ...
    Image:          jujusolutions/charm-base:ubuntu-22.04
    State:          Running
    Ready:          True
    Restart Count:  0
    ...
  mysql:
    ...
   Image:         registry.jujucharms.com/charm/62ptdfbrjpw3n9tcnswjpart30jauc6wc5wbi/mysql-image@sha256:3d665bce5076c13f430d5ab2e0864b3677698a33b4f635fc829ecbe14089ae45
    State:          Running
    Ready:          True
    Restart Count:  0
    ...
```

## Access `charm` container

To enter the `charm` container, use:

```shell
juju ssh mysql-k8s/0 bash
```

Here you can make sure pebble is running, the Pebble plan is

```shell
root@mysql-k8s-0:/var/lib/juju# /charm/bin/pebble services
Service          Startup  Current  Since
container-agent  enabled  active   today at 21:13 UTC

root@mysql-k8s-0:/var/lib/juju# ps auxww
USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root           1  0.0  0.0 717688 10956 ?        Ssl  21:13   0:00 /charm/bin/pebble run --http :38812 --verbose
root          16  0.8  0.1 778372 59540 ?        Sl   21:13   0:03 /charm/bin/containeragent unit --data-dir /var/lib/juju --append-env PATH=$PATH:/charm/bin --show-log --charm-modified-version 0
```

## Access `mysql` (`workload`) container

To enter the `workload` container, run:

```shell
juju ssh --container mysql mysql-k8s/0 bash
```
You can check the list of running processes and Pebble plan:

```shell
root@mysql-k8s-0:/# /charm/bin/pebble services
Service          Startup   Current   Since
mysqld_exporter  disabled  inactive  -
mysqld_safe      enabled   active    today at 21:14 UTC

root@mysql-k8s-0:/# ps auxww
USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root           1  0.1  0.0 719288 13852 ?        Ssl  21:13   0:00 /charm/bin/pebble run --create-dirs --hold --http :38813 --verbose
mysql         70  0.0  0.0   2888  1884 ?        S    21:14   0:00 /bin/sh /usr/bin/mysqld_safe
mysql        366  2.4  7.2 26711784 2394252 ?    Sl   21:14   0:10 /usr/sbin/mysqld --basedir=/usr --datadir=/var/lib/mysql --plugin-dir=/usr/lib/mysql/plugin --log-error=/var/log/mysql/error.log --pid-file=mysql-k8s-0.pid
```

The list of running Pebble services will dependson whether the charm is integrated with [COS](/how-to/monitoring-cos/enable-monitoring) and/or has [backup](/how-to/back-up-and-restore/create-a-backup) functionality. 

The Pebble and its service `mysqld_safe` must always be enabled and currently running (the Linux processes `pebble`, `mysqld_safe` and `mysqld`).

## Access MySQL

To access MySQL, request `root` credentials to use `mysql`:

```shell
> juju run mysql-k8s/leader get-password username=root
password: xbodZvGTGXc6AdLbiEzAcyF9
username: root

> juju ssh --container mysql mysql-k8s/0 bash
>
> > mysql -h 127.0.0.1 -u root -pxbodZvGTGXc6AdLbiEzAcyF9 mysql -e "show databases"
> +-------------------------------+
> | Database                      |
> +-------------------------------+
> | information_schema            |
> | mysql                         |
> | mysql_innodb_cluster_metadata |
> | performance_schema            |
> | sys                           |
> +-------------------------------+
> 5 rows in set (0.00 sec)
> ...
```

Learn more about charm users in [](/explanation/users).

Continue troubleshooting your database/SQL related issues from here.

```{admonition} Recommendations to avoid split-brain scenarios
:class: warning

* Do NOT manage users, credentials, databases, or schema directly. 
  * This prevents a split-brain situation with the operator or related (integrated) applications.
* Do NOT restart services directly
  * This prevents a split-brain situation with the operator's internal state.
  * If you see a problem with a unit, consider [removing that unit and adding a new one](scale-replicas) to recover the cluster state.
```

[Contact us](/reference/contacts) if you cannot determinate the source of your issue, or if you'd like to help us improve this document.

## Installing extra software:

**We do not recommend installing any additionally software** as it may affect the stability and produce anomalies which is hard to troubleshoot and fix.

However, if you do so, always remove installed components manually at the end of troubleshooting.

To install additional software, use the standard approach:

```shell
root@mysql-k8s-0:/# apt update && apt install less
...
Setting up less (590-1ubuntu0.22.04.1) ...
root@mysql-k8s-0:/#
```

```{toctree}
:titlesonly:

Known scenarios <known-scenarios>
```
