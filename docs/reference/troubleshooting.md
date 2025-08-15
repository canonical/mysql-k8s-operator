


# Troubleshooting

> :warning: **WARNING**: at the moment, there is NO ability to [pause operator](https://warthogs.atlassian.net/browse/DPE-2545)!<br/>Make sure your activity will not interfere with the operator itself!

Ensure you went into the real issue which requires the manual activity. Run `juju status` and check the [list of charm statuses](/reference/charm-statuses) and recommended activities there.


## One offline unit and other units as secondaries

**Problem:** The primary unit went offline and primary reelection failed, rendered remaining units in RO mode.
**Solution:**
1. Restart `mysqld_safe` service on secondaries, i.e.:
    ```shell
    # for each secondarie unit `n`
    juju ssh --container mysql mysql-k8s/n pebble restart mysqld_safe
    ```
2.  Wait update-status hook to trigger recovery. For faster recovery, it's possible to speed up the update-status hook with:
    ```shell
    juju model-config update-status-hook-interval=30s -m mymodel
    # after recovery, set default interval of 5 minutes
    juju model-config update-status-hook-interval=5m -m mymodel
    ```

**Explanation:** When restarting secondaries, all MySQL instance will return as offline, which will trigger a cluster recovery.


## Two primaries, one in "split-brain" state

**Problem:** Original primary had a transitory network cut, and a new primary was elected. On returning, old primary enter split-brain state.

**Solution:** 
1. Restart `mysqld_safe` service on secondaries, i.e.:
    ```shell
    # using `n` as the unit in split brain state
    juju ssh --container mysql mysql-k8s/n pebble restart mysqld_safe
    ```
2. Wait unit rejoin the cluster

**Explanation:** On restart, unit will reset it state and try to rejoin the cluster as a secondary.

## Logs

Please be familiar with [Juju logs concepts](https://juju.is/docs/juju/log) and learn [how to manage Juju logs](https://juju.is/docs/juju/manage-logs).

Always check the Juju logs before troubleshooting further:
```shell
juju debug-log --replay --tail
```

Focus on `ERRORS` (normally there should be none):
```shell
juju debug-log --replay | grep -c ERROR
```

Consider to enable `DEBUG` log level IF you are troubleshooting wired charm behavior:
```shell
juju model-config 'logging-config=<root>=INFO;unit=DEBUG'
```

The MySQL logs are located in `workload` (see below) container:
```shell
> ls -la /var/log/mysql/
-rw-r----- 1 mysql mysql 8783 Sep 18 21:14 error.log
```

## Kubernetes

Check the operator [architecture](/explanation/architecture) first to be familiar with `charm` and `workload` containers. Make sure both containers are `Running` and `Ready` to continue troubleshooting inside the charm. To describe the running pod, use the following command (where `0` is a Juju unit id). :
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


## Container `charm`

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

Normally you should have no issues here, if you see some, please [contact us](/reference/contacts).<br/>
Feel free to improve this document!

## Container `mysql` (workload)

To enter the `workload` container, use:
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

The list of running Pebble services will depends on configured (enabled) [COS integration](/how-to/monitoring-cos/enable-monitoring) and/or [Backup](/how-to/back-up-and-restore/create-a-backup) functionality. The Pebble and it's service `mysqld_safe` must always be enabled and currently running (the Linux processes `pebble`, `mysqld_safe` and `mysqld`).

To connect inside the MySQL, check the [charm users concept](/explanation/users) and request admin credentials and use `mysql`:
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
Continue troubleshooting your DB/SQL related issues from here.<br/>
> :warning: **WARNING**: please do NOT manage users, credentials, databases, schema directly to avoid a split bran situation with the operator and/or related (integrated) applications.

It is NOT recommended to restart services directly as it might create a split brain situation with operator internal state. If you see the problem with a unit, consider to [scale-down and re-scale-up](/how-to/scale-replicas) to recover the cluster state.

As a last resort, [contact us](/reference/contacts) If you cannot determinate the source of your issue.
Also, feel free to improve this document!

## Installing extra software:

> :warning: **WARNING**: please do NOT install any additionally software as it may affect the stability and produce anomalies which is hard to troubleshoot and fix! Otherwise always remove manually installed components at the end of troubleshooting. Keep the house clean!

Sometimes it is necessary to install some extra troubleshooting software. Use the common approach:
```shell
root@mysql-k8s-0:/# apt update && apt install less
...
Setting up less (590-1ubuntu0.22.04.1) ...
root@mysql-k8s-0:/#
```

