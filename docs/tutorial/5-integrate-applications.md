# Integrate with other applications

[Integrations](https://juju.is/docs/sdk/integration), known as "relations" in Juju 2.9, are the easiest way to create a user for a Charmed MySQL application. 

Integrations automatically create a username, password, and database for the desired user/application. As mentioned in the [earlier section about accessing MySQL](/), it is better practice to connect to MySQL via a specific user instead of the `root` user.

In this section, you will learn how to integrate your Charmed MySQL with another application (charmed or not) via the Data Integrator charm. 

## Deploy `data-integrator`

In this tutorial, we will relate to the [Data Integrator charm](https://charmhub.io/data-integrator). This is a bare-bones charm that allows for central management of database users. It automatically provides credentials and endpoints that are needed to connect with a charmed database application.

 In order to deploy the Data Integrator charm we can use the command `juju deploy` we have learned above:

To deploy `data-integrator`, run

```shell
juju deploy data-integrator --config database-name=test-database
```

Example output:
```shell
Located charm "data-integrator" in charm-hub, revision 13
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 3 in channel edge on jammy
```

Running `juju status` will show you `data-integrator` in a `blocked` state. This state is expected due to not-yet established relation (integration) between applications.
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2   unsupported  22:54:31+01:00

App              Version    Status   Scale  Charm            Channel     Rev  Address         Exposed  Message
data-integrator             waiting      1  data-integrator  edge        4    10.152.183.180  no       installing agent
mysql-k8s        8.0.31     active       2  mysql-k8s        8.0/stable  36   10.152.183.234  no       

Unit                Workload  Agent  Address      Ports  Message
data-integrator/0*  blocked   idle   10.1.84.66          Please relate the data-integrator with the desired product
mysql-k8s/0*        active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1         active    idle   10.1.84.127         Unit is ready: Mode: RO
```
The `blocked` state is expected due to not-yet established relation (integration) between applications.

## Integrate with MySQL

Now that the `data-integrator` charm has been set up, we can relate it to MySQL. This will automatically create a username, password, and database for `data-integrator`.

Relate the two applications with:
```shell
juju relate data-integrator mysql-k8s
```

Wait for `juju status --watch 1s` to show all applications/units as `active`:
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2   unsupported  22:55:44+01:00

App              Version    Status   Scale  Charm            Channel     Rev  Address         Exposed  Message
data-integrator             waiting      1  data-integrator  edge        4    10.152.183.180  no       installing agent
mysql-k8s        8.0.31     active       2  mysql-k8s        8.0/stable  36   10.152.183.234  no       

Unit                Workload  Agent  Address      Ports  Message
data-integrator/0*  active    idle   10.1.84.66          
mysql-k8s/0*        active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1         active    idle   10.1.84.127         Unit is ready: Mode: RO
```

To retrieve the username, password and database name, run the command
```shell
juju run data-integrator/leader get-credentials
```

Example output:
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
> Note that your hostnames, usernames, and passwords will be different.

## Access the integrated database

Use `endpoints`, `username`, `password` from above to connect newly created database `test-database` on MySQL server:
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

When you integratetwo applications, Charmed MySQL K8s automatically sets up a new user and database for you. Note the database name we specified when we first deployed the `data-integrator` charm: `--config database-name=test-database`.

## Remove the user
To remove the user, remove the integration. Removing the integration automatically removes the user that was created when the integration was created. 

To remove the integration, run the following command:
```shell
juju remove-relation mysql-k8s data-integrator
```

Try to connect to the same MySQL you just used in the previous section ([Access the related database](#access-the-related-database)):
```shell
mysql -h 10.1.84.74 -u relation-3 -p7VRfmGjfUI1pVUPsfbMwmHFm -e "show databases;"
```

This will output an error message, since the user no longer exists.
```shell
ERROR 1045 (28000): Access denied for user 'relation-3'@'10.76.203.127' (using password: YES)
``` 
This is expected, as `juju remove-relation mysql-k8s data-integrator` also removes the user.

> **Note**: Data remains on the server at this stage.

To create a user again, re-integrate the applications:
```shell
juju integrate data-integrator mysql-k8s
```

Re-integrating generates a new user and password. Obtain these credentials as before, with the `get-credentials` action:
```shell
juju run data-integrator/leader get-credentials
```

You can connect to the database with this new credentials. From here you will see all of your data is still present in the database.

> Next step: [6. Enable TLS encryption](/tutorial/6-enable-tls-encryption)

