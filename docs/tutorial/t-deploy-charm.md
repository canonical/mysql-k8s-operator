# Get a Charmed MySQL up and running

This is part of the [Charmed MySQL Tutorial](/t/charmed-mysql-k8s-tutorial-overview/9677). Please refer to this page for more information and the overview of the content.

## Deploy Charmed MySQL K8s
To deploy Charmed MySQL K8s, all you need to do is run the following command, which will fetch the charm from [Charmhub](https://charmhub.io/mysql-k8s?channel=8.0) and deploy it to your model:

> **:information_source:** *Info: the miminum juju version supported is 2.9.44*

```shell
juju deploy mysql-k8s --channel 8.0 --trust
```
Note: `--trust` is required to create some K8s resources.

Juju will now fetch Charmed MySQL K8s and begin deploying it to the Microk8s Kubernetes. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is. You can track the progress by running:
```shell
juju status --watch 1s
```

This command is useful for checking the status of Charmed MySQL K8s and gathering information about the machines hosting Charmed MySQL. Some of the helpful information it displays include IP addresses, ports, state, etc. The command updates the status of Charmed MySQL K8s every second and as the application starts you can watch the status and messages of Charmed MySQL K8s change. Wait until the application is ready - when it is ready, `juju status` will show:
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.44   unsupported  22:33:45+01:00

App        Version   Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31    active      1  mysql-k8s  8.0/stable  36   10.152.183.234  no       Unit is ready: Mode: RW

Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74         Unit is ready: Mode: RW
```
To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`.
If you want to further inspect juju logs, can watch for logs with `juju debug-log`.
More info on logging at [juju logs](https://juju.is/docs/olm/juju-logs).

## Access MySQL
> **!** *Disclaimer: this part of the tutorial accesses MySQL via the `root` user. **Do not** directly interface with the root user in a production environment. In a production environment always create a separate user using [Data Integrator](https://charmhub.io/data-integrator) and connect to MySQL with that user instead. Later in the section covering Relations we will cover how to access MySQL without the root user.*

The first action most users take after installing MySQL is accessing MySQL. The easiest way to do this is via the [MySQL Command-Line Client](https://dev.mysql.com/doc/refman/8.0/en/mysql.html) `mysql`. Connecting to the database requires that you know the values for `host`, `username` and `password`. To retrieve the necessary fields please run Charmed MySQL K8s action `get-password`:
```shell
juju run-action mysql-k8s/leader get-password --wait
```
Running the command should output:
```yaml
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "2"
  results:
    password: sQI3Ojih7uL5UC4J1D9Xuqgx
    username: root
  status: completed
  timing:
    completed: 2023-02-15 21:35:56 +0000 UTC
    enqueued: 2023-02-15 21:35:55 +0000 UTC
    started: 2023-02-15 21:35:55 +0000 UTC
```

*Note: to request a password for a different user, use an option `username`:*
```shell
juju run-action mysql-k8s/leader get-password username=myuser --wait
```

The host’s IP address can be found with `juju status` (the unit hosting the MySQL K8s application):
```shell
...
Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74         Unit is ready: Mode: RW
...
```

To access the units hosting Charmed MySQL K8s use:
```shell
mysql -h 10.1.84.74 -uroot -p<password>
```
*Note: if at any point you'd like to leave the unit hosting Charmed MySQL, enter `Ctrl+d` or type `exit`*.

Inside MySQL list DBs available on the host `show databases`:
```shell
> mysql -h 10.1.84.74 -uroot -psQI3Ojih7uL5UC4J1D9Xuqgx

Server version: 8.0.31-0ubuntu0.22.04.1 (Ubuntu)
...

mysql> show databases;
+-------------------------------+
| Database                      |
+-------------------------------+
| information_schema            |
| mysql                         |
| mysql_innodb_cluster_metadata |
| performance_schema            |
| sys                           |
+-------------------------------+
5 rows in set (0.01 sec)
```
*Note: if at any point you'd like to leave the MySQL client, enter `Ctrl+d` or type `exit`*.

You can now interact with MySQL directly using any [MySQL Queries](https://dev.mysql.com/doc/refman/8.0/en/entering-queries.html). For example entering `SELECT VERSION(), CURRENT_DATE;` should output something like:
```shell
mysql> SELECT VERSION(), CURRENT_DATE;
+-------------------------+--------------+
| VERSION()               | CURRENT_DATE |
+-------------------------+--------------+
| 8.0.31-0ubuntu0.22.04.1 | 2023-02-15   |
+-------------------------+--------------+
1 row in set (0.00 sec)
```

Feel free to test out any other MySQL queries. When you’re ready to leave the MySQL shell you can just type `exit`. Now you will be in your original shell where you first started the tutorial; here you can interact with Juju and Microk8s.