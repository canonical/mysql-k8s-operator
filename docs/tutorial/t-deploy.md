> [Charmed MySQL K8s Tutorial](/t/9677) > 2. Deploy MySQL

# Deploy Charmed MySQL

In this section, you will deploy Charmed MySQL K8s, access a unit, and interact with the MySQL databases that exist inside the application.

## Summary
* [Deploy MySQL](#deploy-mysql)
* [Access MySQL](#access-mysql)
  * [Retrieve credentials](#retrieve-credentials)
  * [ Access MySQL via the `mysql` client](#access-mysql-via-the-mysql-client)

---

## Deploy MySQL

To deploy Charmed MySQL K8s, run the following command:
```shell
juju deploy mysql-k8s --trust
```
> The `--trust` flag is necessary to create some K8s resources

Juju will now fetch Charmed MySQL K8s from [Charmhub](https://charmhub.io/mysql-k8s?channel=8.0) and deploy it to MicroK8s. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is. You can track the progress by running:
```shell
juju status --watch 1s
```

>This command is useful for checking the real-time information about the state of a charm and the machines hosting it. Check the [`juju status` documentation](https://juju.is/docs/juju/juju-status) for more information about its usage.

When the application is ready, `juju status` will show the `mysql` app as `active` and the `mysql-k8s/0*` unit as `idle`, like the example below:
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2   unsupported  22:33:45+01:00

App        Version   Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31    active      1  mysql-k8s  8.0/stable  36   10.152.183.234  no       Unit is ready: Mode: RW

Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74         Unit is ready: Mode: RW
```
> To exit the screen with `juju status --watch 1s`, enter `Ctrl+C`.

You can also watch juju logs with the [`juju debug-log`](https://juju.is/docs/juju/juju-debug-log) command. More info on logging in the [juju logs documentation](https://juju.is/docs/olm/juju-logs).

## Access MySQL
[note type="caution"]
**Warning:** This part of the tutorial accesses MySQL via the `root` user. 

**Do not directly interface with the `root` user in a production environment.**

In a [later section about integrations](/t/9671), we will cover how to safely access MySQL via a separate user.
[/note]

 The easiest way to access MySQL is via the [MySQL Command-Line Client](https://dev.mysql.com/doc/refman/8.0/en/mysql.html) (`mysql`). For this, we must first retrieve the credentials.

### Retrieve credentials
Connecting to the database requires that you know the values for `host` (IP address), `username` and `password`. 

To retrieve `username` and `password`, run the [Juju action](https://juju.is/docs/juju/action) `get-password` on the leader unit as follows:
```shell
juju run mysql-k8s/leader get-password
```
Example output:
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

To request a password for a different user, use the option `username`:
```shell
juju run mysql-k8s/leader get-password username=<username>
```

To retrieve the host’s IP address, run `juju status`. This should be listed under the "Public address" of the unit hosting the MySQL application:
```shell
...
Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74         Unit is ready: Mode: RW
...
```

### Access MySQL via the `mysql` client

To access the unit hosting Charmed MySQL, one could normally use the following command:

```
mysql -h <ip_address> -u<username> -p<password>
```

However, this is not possible with the `root` user. For security reasons, the `root` user is restricted to only allow connections from localhost. 

The way to access MySQL server with the `root` user is to first ssh into the primary Juju unit:
```shell
juju ssh mysql-k8s/leader
```
> In this case, we know the primary unit is the [juju leader unit](https://juju.is/docs/juju/leader), since it is the only existing unit. 
>
> In a cluster with more units, **the primary is not necessarily equivalent to the leader**. To identify the primary unit in a cluster, run `juju run mysql/<any_unit> get-cluster-status`. This will display the entire cluster topology.

Once inside the Juju virtual machine, the `root` user can access MySQL by calling
```
mysql -h 127.0.0.1 -uroot -psQI3Ojih7uL5UC4J1D9Xuqgx
```
> Remember, your password will be different to the example above. Make sure to insert it without a space as `-p<password>`

You will then see the `mysql>` command prompt, similar to the output below:
```none
Welcome to the MySQL monitor.  Commands end with ; or \g.
Your MySQL connection id is 56
Server version: 8.0.32-0ubuntu0.22.04.2 (Ubuntu)

Copyright (c) 2000, 2023, Oracle and/or its affiliates.

Oracle is a registered trademark of Oracle Corporation and/or its
affiliates. Other names may be trademarks of their respective
owners.

Type 'help;' or '\h' for help. Type '\c' to clear the current input statement.

mysql>
```
> If at any point you'd like to leave the mysql client, enter `Ctrl+D` or type `exit`.

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

Feel free to test out any other MySQL queries. When you’re ready to leave the MySQL shell you can just type `exit`. Now you will be in your original shell where you first started the tutorial; here you can interact with Juju and MicroK8s.

> Next step: [3. Scale your replicas](/t/9675)