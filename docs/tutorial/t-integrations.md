# Integrating your Charmed MySQL

This is part of the [Charmed MySQL Tutorial](TODO). Please refer to this page for more information and the overview of the content.

## Integrations (Relations for Juju 2.9)
Relations, or what Juju 3.0+ documentation [describes as an Integration](https://juju.is/docs/sdk/integration), are the easiest way to create a user for MySQL in Charmed MySQL K8s. Relations automatically create a username, password, and database for the desired user/application. As mentioned earlier in the [Access MySQL section](#access-mysql) it is a better practice to connect to MySQL via a specific user rather than the admin user.

### Data Integrator Charm
Before relating to a charmed application, we must first deploy our charmed application. In this tutorial we will relate to the [Data Integrator Charm](https://charmhub.io/data-integrator). This is a bare-bones charm that allows for central management of database users, providing support for different kinds of data platforms (e.g. MySQL, PostgreSQL, MongoDB, Kafka, etc) with a consistent, opinionated and robust user experience. In order to deploy the Data Integrator Charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --channel edge --config database-name=test-database
```
The expected output:
```
Located charm "data-integrator" in charm-hub, revision 4
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 4 in channel edge on jammy
```

Checking the deployment progress using `juju status` will show you the `blocked` state for newly deployed charm:
```
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:54:31+01:00

App              Version    Status   Scale  Charm            Channel  Rev  Address         Exposed  Message
data-integrator             waiting      1  data-integrator  edge       4  10.152.183.180  no       installing agent
mysql-k8s        8.0.31     active       2  mysql-k8s        edge      36  10.152.183.234  no       

Unit                Workload  Agent  Address      Ports  Message
data-integrator/0*  blocked   idle   10.1.84.66          Please relate the data-integrator with the desired product
mysql-k8s/0*        active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1         active    idle   10.1.84.127         Unit is ready: Mode: RO
```
The `blocked` state is expected due to not-yet established relation (integration) between applications.

### Relate to MySQL
Now that the Database Integrator Charm has been set up, we can relate it to MySQL. This will automatically create a username, password, and database for the Database Integrator Charm. Relate the two applications with:
```shell
juju relate data-integrator mysql-k8s
```
Wait for `juju status --watch 1s` to show all applications/units as `active`:
```
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:55:44+01:00

App              Version    Status   Scale  Charm            Channel  Rev  Address         Exposed  Message
data-integrator             waiting      1  data-integrator  edge       4  10.152.183.180  no       installing agent
mysql-k8s        8.0.31     active       2  mysql-k8s        edge      36  10.152.183.234  no       

Unit                Workload  Agent  Address      Ports  Message
data-integrator/0*  active    idle   10.1.84.66          
mysql-k8s/0*        active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1         active    idle   10.1.84.127         Unit is ready: Mode: RO
```

To retrieve information such as the username, password, and database. Enter:
```shell
juju run-action data-integrator/leader get-credentials --wait
```
This should output something like:
```yaml
unit-data-integrator-0:
  UnitId: data-integrator/0
  id: "20"
  results:
    mysql:
      endpoints: mysql-k8s-0.mysql-k8s-endpoints:3306
      password: 7VRfmGjfUI1pVUPsfbMwmHFm
      read-only-endpoints: mysql-k8s-0.mysql-k8s-endpoints:3306,mysql-k8s-1.mysql-k8s-endpoints:3306
      username: relation-3
      version: 8.0.31-0ubuntu0.22.04.1
    ok: "True"
  status: completed
  timing:
    completed: 2023-02-15 21:56:22 +0000 UTC
    enqueued: 2023-02-15 21:56:17 +0000 UTC
    started: 2023-02-15 21:56:21 +0000 UTC
```
*Note: your hostnames, usernames, and passwords will likely be different.*

### Access the related database
Use `endpoints`, `username`, `password` from above to connect newly created database `test-database` on MySQL K8s server:
```shell
> mysql -h 10.1.84.74 -u relation-3 -p7VRfmGjfUI1pVUPsfbMwmHFm -e "show databases;"
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+

```

The newly created database `test-database` is also available on all other MySQL K8s cluster members:
```shell
> mysql -h 10.1.84.127 -u relation-3 -p7VRfmGjfUI1pVUPsfbMwmHFm -e "show databases;"
+--------------------+
| Database           |
+--------------------+
| information_schema |
| performance_schema |
| test-database      |
+--------------------+
```

When you relate two applications Charmed MySQL K8s automatically sets up a new user and database for you.
Please note the database name we specified when we first deployed the `data-integrator` charm: `--config database-name=test-database`.

### Remove the user
To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```shell
juju remove-relation mysql-k8s data-integrator
```

Now try again to connect to the same MySQL K8s you just used in [Access the related database](#access-the-related-database):
```shell
mysql -h 10.1.84.74 -u relation-3 -p7VRfmGjfUI1pVUPsfbMwmHFm -e "show databases;"
```

This will output an error message:
```
ERROR 1045 (28000): Access denied for user 'relation-3'@'10.76.203.127' (using password: YES)
```
As this user no longer exists. This is expected as `juju remove-relation mysql-k8s data-integrator` also removes the user.
Note: data stay remain on the server at this stage!

Relate the the two applications again if you wanted to recreate the user:
```shell
juju relate data-integrator mysql-k8s
```
Re-relating generates a new user and password:
```shell
juju run-action data-integrator/leader get-credentials --wait
```
You can connect to the database with this new credentials.
From here you will see all of your data is still present in the database.

