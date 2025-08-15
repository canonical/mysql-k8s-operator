# Tutorial

This hands-on tutorial aims to help you learn how to deploy Charmed MySQL on Kubernetes and become familiar with its available operations.

## Prerequisites

While this tutorial intends to guide you as you deploy Charmed MySQL K8s for the first time, it will be most beneficial if:
- You have some experience using a Linux-based CLI
- You are familiar with MySQL concepts such as replication and users.
- Your computer fulfils the [minimum system requirements](/reference/system-requirements)

---

## Set up the environment

First, we will set up a cloud environment using [Multipass](https://multipass.run/) with [MicroK8s](https://microk8s.io/docs) and [Juju](https://documentation.ubuntu.com/juju/3.6/). This is the quickest and easiest way to get your machine ready for using Charmed MySQL K8s. 

To learn about other types of deployment environments and methods (e.g. bootstrapping other clouds, using Terraform), see [](/how-to/deploy/index).

(create-multipass-vm)=
### Create a Multipass VM

Multipass is a quick and easy way to launch virtual machines running Ubuntu. It uses the [cloud-init](https://cloud-init.io/) standard to install and configure all the necessary parts automatically.

Install Multipass from the [snap store](https://snapcraft.io/multipass):

```{terminal}
:input: sudo snap install multipass
:user: user
:host: my-pc
```

Spin up a new VM using [`multipass launch`](https://multipass.run/docs/launch-command) with the [charm-dev](https://github.com/canonical/multipass-blueprints/blob/main/v1/charm-dev.yaml) cloud-init configuration:

```{terminal}
:input: multipass launch --cpus 4 --memory 8G --disk 30G --name my-vm charm-dev
:user: user
:host: my-pc
```

This may take several minutes if it's the first time you launch this VM.

As soon as the new VM has started, access it:

```{terminal}
:input: multipass shell my-vm
:user: user
:host: my-pc

Welcome to Ubuntu 24.04.2 LTS (GNU/Linux 6.8.0-63-generic x86_64)

 * Documentation:  https://help.ubuntu.com
 * Management:     https://landscape.canonical.com
 * Support:        https://ubuntu.com/pro
...
```

```{tip}
All necessary components have been pre-installed inside VM already, like MicroK8s and Juju. The files `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` contain all low-level installation details. 
```

### Set up Juju

Since `my-vm` already has Juju MicroK8s installed, we can go ahead and [bootstrap](https://documentation.ubuntu.com/juju/3.6/reference/juju-cli/list-of-juju-cli-commands/bootstrap/#details) a cloud. In this tutorial, we will use a MicroK8s [controller](https://documentation.ubuntu.com/juju/3.6/reference/controller/). 

We will call our new controller “overlord”, but you can give it any name you’d like:

```{terminal}
:input: juju bootstrap microk8s overlord
:user: ubuntu
:host: my-vm
``` 

The controller can work with different [Juju models](https://juju.is/docs/juju/model). Set up a specific model for Charmed MySQL K8s named `tutorial`:

```{terminal}
:input: juju add-model tutorial
:user: ubuntu
:host: my-vm
``` 

You can now view the model you created by running the command [`juju status`](https://juju.is/docs/juju/juju-status). 

```{terminal}
:input: juju status
:user: ubuntu
:host: my-vm

Model    Controller  Cloud/Region         Version  SLA          Timestamp
tutorial overlord    microk8s/localhost   3.5.2    unsupported  23:20:53+01:00

Model "admin/tutorial" is empty.
```

## Deploy Charmed MySQL K8s

To deploy Charmed MySQL K8s, run the following command:

```{terminal}
:input: juju deploy mysql-k8s --trust
:user: ubuntu
:host: my-vm
```

The `--trust` flag is necessary to create some K8s resources.

Juju will now fetch Charmed MySQL K8s from [Charmhub](https://charmhub.io/mysql-k8s?channel=8.0) and deploy it to MicroK8s. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is.

```{terminal}
:input: juju status --watch 1s
:user: ubuntu
:host: my-vm
```

```{tip}
You can open a separate terminal window, enter the same Multipass VM, and keep `juju status --watch 1s` permanently running in it.
```

When the application is ready, `juju status` will show something similar to the sample output below:

```text
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2   unsupported  22:33:45+01:00

App        Version   Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31    active      1  mysql-k8s  8.0/stable  36   10.152.183.234  no       Unit is ready: Mode: RW

Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74         Unit is ready: Mode: RW
```

You can also watch juju logs with the [`juju debug-log`](https://juju.is/docs/juju/juju-debug-log) command.

## Access MySQL

In this section, you will learn how to get the credentials of your deployment, connect to the MySQL instance, and interact with the database directly.

This is where we are introduced to internal database [users](/explanation/users). 

```{caution}
This part of the tutorial accesses MySQL via the charm's `root` user. 

**Do not directly interface with the `root` user in a production environment.**

In a later section, we will cover how to safely access MySQL more safely.
```

The easiest way to access MySQL is via the [MySQL Command-Line Client](https://dev.mysql.com/doc/refman/8.0/en/mysql.html) (`mysql`). For this, we must first retrieve the credentials.

### Retrieve credentials

Connecting to the database requires that you know the values for `host` (IP address), `username` and `password`. 

To retrieve `username` and `password`, run the [Juju action](https://juju.is/docs/juju/action) `get-password` on the leader unit as follows:

```{terminal}
:input: juju run mysql-k8s/leader get-password
:user: ubuntu
:host: my-vm

...
password: sQI3Ojih7uL5UC4J1D9Xuqgx
username: root
```

To retrieve the host’s IP address, run `juju status`. This should be listed under the "Public address" of the unit hosting the MySQL application:

```{terminal}
:input: juju status
:user: ubuntu
:host: my-vm

...
Unit          Workload  Agent  Address     Ports   Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
...
```

### Interact with MySQL

To access the unit hosting Charmed MySQL in production, one would normally use the following command:

```shell
mysql -h <ip_address> -u<username> -p<password>
```

However, this is not possible with the `root` user, which is what we are using in this tutorial for learning purposes. For security reasons, the `root` user is restricted to only allow connections from `localhost`. 

The way to access MySQL server with the `root` user is to first ssh into the primary Juju unit:

```{terminal}
:input: juju ssh mysql-k8s/leader
:user: ubuntu
:host: my-vm
```

```{note}
In this case, we know the MySQL primary unit is also the [Juju leader unit](https://juju.is/docs/juju/leader), since it is the only existing unit. 

In a cluster with more units, **the primary is not necessarily equivalent to the leader**. To identify the primary unit in a cluster, run `juju run mysql/<any_unit> get-cluster-status`. 
```

Once inside the Juju virtual machine, the `root` user can access MySQL with the following command:

```
mysql -h 127.0.0.1 -uroot -p<password>
```

As an example, using the password we obtained earlier:

```{terminal}
:input: mysql -h 127.0.0.1 -uroot -psQI3Ojih7uL5UC4J1D9Xuqgx
:user: ubuntu
:host: juju-ff9064-0

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

You can now interact with MySQL directly using any [MySQL Queries](https://dev.mysql.com/doc/refman/8.0/en/entering-queries.html). 

For example:

```sql
SELECT VERSION(), CURRENT_DATE;
```

```text
+-------------------------+--------------+
| VERSION()               | CURRENT_DATE |
+-------------------------+--------------+
| 8.0.32-0ubuntu0.22.04.2 | 2023-01-29   |
+-------------------------+--------------+
1 row in set (0.00 sec)
```

Feel free to test out any other MySQL queries. 

When you’re ready to leave the mysql shell you can just type `exit`. Once you've typed `exit` you will be back in the host of Charmed MySQL K8s (`mysql-k8s/0`). 

Exit this host by once again typing `exit`. Now you will be in your original shell where you first started the tutorial; here you can interact with Juju.

(scale-replicas)=
## Scale your replicas

The Charmed MySQL K8s operator uses [MySQL InnoDB Cluster](https://dev.mysql.com/doc/refman/8.0/en/mysql-innodb-cluster-introduction.html) for scaling. It is built on MySQL [group replication](https://dev.mysql.com/doc/refman/8.0/en/group-replication.html), providing features such as automatic membership management, fault tolerance, and automatic failover. 

An InnoDB Cluster usually runs in a single-primary mode, with one primary instance (read-write) and multiple secondary instances (read-only). 

<!-- TODO: clarify "future" Future versions on Charmed MySQL will take advantage of a multi-primary mode, where multiple instances are primaries. Users can even change the topology of the cluster while InnoDB Cluster is online, to ensure the highest possible availability. -->

```{caution}
This tutorial hosts replicas all on the same machine. **This should not be done in a production environment.** 

To enable high availability in a production environment, replicas should be hosted on different servers to [maintain isolation](https://canonical.com/blog/database-high-availability).
```

### Add units

Currently, your deployment has only one [juju unit](https://juju.is/docs/juju/unit), known as the leader unit.  For each MySQL replica, a new juju unit (non-leader) is created. All units are members of the same database cluster.

To add two replicas to your deployed MySQL application, scale it to 3 total units:

```{terminal}
:input: juju scale-application mysql-k8s 3
:user: ubuntu
:host: my-vm
```

You can now watch the scaling process in live using: `juju status --watch 1s`. It usually takes several minutes for new cluster members to be added. 

You’ll know that all three nodes are in sync when `juju status` reports `Workload=active` and `Agent=idle`:

```text
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  8.0/stable  36   10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1   active    idle   10.1.84.127         Unit is ready: Mode: RO
mysql-k8s/2   active    idle   10.1.84.73          Unit is ready: Mode: RO
```

```{note}
The maximum possible number of Charmed MySQL units in a single Juju application is 9. This is a limitation of MySQL group replication. 

Read more about all limitations in the [official MySQL documentation](https://dev.mysql.com/doc/refman/8.0/en/group-replication-limitations.html).
```

### Remove units

Removing a unit from the application scales down the replicas. 

Before we scale down, list all the units with `juju status`. You will see three units: `mysql-k8s/0`, `mysql-k8s/1`, and `mysql-k8s/2`. Each of these units hosts a MySQL replica. 

To remove one replica, scale the application down to two total units:

```{terminal}
:input: juju scale-application mysql-k8s 2
:user: ubuntu
:host: my-vm
```

You’ll know that the replica was successfully removed when you no longer see them in the `juju status` output:

```text
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  8.0/stable  36   10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1   active    idle   10.1.84.127         Unit is ready: Mode: RO
```

## Integrate with other applications

[Integrations](https://documentation.ubuntu.com/juju/3.6/reference/relation/), also known as "relations", are the easiest way to create a user for MySQL. 

Integrations automatically create a username, password, and database for the desired user/application. The best practice is to connect to MySQL via a specific user rather than the admin user, like we did earlier with the `root` user.

In this tutorial, we will relate to the [data integrator charm](https://charmhub.io/data-integrator). This is a bare-bones charm that allows for central management of database users. It automatically provides credentials and endpoints that are needed to connect with a charmed database application.

To deploy `data-integrator` and associate it to a new database called `test-database`:

```{terminal}
:input: juju deploy data-integrator --config database-name=test-database
:user: ubuntu
:host: my-vm

Located charm "data-integrator" in charm-hub, revision 13
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 3 in channel edge on jammy
```

Running `juju status` will show you `data-integrator` in a `blocked` state. This state is expected due to not-yet established relation (integration) between applications:

```text
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

Now that the `data-integrator` charm has been set up, we can relate it to MySQL. This will automatically create a username, password, and database for `data-integrator`:

```{terminal}
:input: juju integrate data-integrator mysql-k8s
:user: ubuntu
:host: my-vm
```

Wait for `juju status` to show all applications/units as `active`:

```text
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

To retrieve the username, password and database name, run the `get-credentials` Juju action:

```{terminal}
:input: juju run data-integrator/leader get-credentials
:user: ubuntu
:host: my-vm

mysql:
  database: test-database
  endpoints: mysql-k8s-0.mysql-k8s-endpoints:3306
  password: 7VRfmGjfUI1pVUPsfbMwmHFm
  read-only-endpoints: mysql-k8s-0.mysql-k8s-endpoints:3306,mysql-k8s-1.mysql-k8s-endpoints:3306
  username: relation-3
  version: 8.0.31-0ubuntu0.22.04.1
ok: "True"
```

(access-the-integrated-database)=
### Access the integrated database

Use `endpoints`, `username`, `password` from above to connect newly created database `test-database` on MySQL server:

```{terminal}
:scroll:
:input: mysql -h 10.1.84.74 -urelation-3 -p7VRfmGjfUI1pVUPsfbMwmHFm -e "show databases"
:user: ubuntu
:host: my-vm

+--------------------+
| Database           |
+--------------------+
| test-database      |
+--------------------+
```

The newly created database `test-database` is also available on all other MySQL cluster members:

```{terminal}
:scroll:
:input: mysql -h 10.1.84.127 -P 3306 -urelation-5 -p7VRfmGjfUI1pVUPsfbMwmHFm -e "show databases"
:user: ubuntu
:host: my-vm

+--------------------+
| Database           |
+--------------------+
| test-database      |
+--------------------+
```

You've successfully set up a new user and database by integrating your Charmed MySQL K8s app with the Data Integrator app. 

### Remove the user

Removing the integration automatically removes the user that was created when the integration was created.

To remove the integration, run the following command:

```{terminal}
:input: juju remove-relation mysql-k8s data-integrator
:user: ubuntu
:host: my-vm
```

If you try to connect to the same MySQL you just used in the [previous section](access-the-integrated-database), you'll get an "Access denied" error. This is expected, since the user no longer exists after removing the integration. However, note that **data remains on the server** at this stage.

To create a user again, re-integrate the applications:

```{terminal}
:scroll:
:input: juju integrate data-integrator mysql-k8s
:user: ubuntu
:host: my-vm
```
Re-integrating generates a new user and password. You can obtain these credentials as before, with the `get-credentials` action, and connect to the database with this new credentials. 

From here you will see all of your data is still present in the database.

## Enable encryption with TLS

[Transport Layer Security (TLS)](https://en.wikipedia.org/wiki/Transport_Layer_Security) is a protocol used to encrypt data exchanged between two applications. Essentially, it secures data transmitted over a network.

Typically, enabling TLS internally within a highly available database or between a highly available database and client/server applications requires a high level of expertise. This has all been encoded into Charmed MySQL so that configuring TLS requires minimal effort on your end.

TLS is enabled by integrating Charmed MySQL with the [Self-signed certificates charm](https://charmhub.io/self-signed-certificates). This charm centralises TLS certificate management consistently and handles operations like providing, requesting, and renewing TLS certificates.

```{caution}
**[Self-signed certificates](https://en.wikipedia.org/wiki/Self-signed_certificate) are not recommended for a production environment.**

Check [this guide](https://discourse.charmhub.io/t/11664) for an overview of the TLS certificates charms available. 
```

Before enabling TLS on Charmed MySQL, we must deploy the `self-signed-certificates` charm:

```{terminal}
:scroll:
:input: juju deploy self-signed-certificates --config ca-common-name="Tutorial CA"
:user: ubuntu
:host: my-vm
```

Wait until `self-signed-certificates` is up and active, using `juju status --watch 1s` to monitor its progress:

```text
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  3.5.2  unsupported  23:04:02+01:00

App                        Version   Status  Scale  Charm                      Channel      Rev  Address         Exposed  Message
mysql-k8s                  8.0.31    active      2  mysql-k8s                  8.0/stable   36   10.152.183.234  no       
self-signed-certificates             active      1  self-signed-certificates   stable   72   10.152.183.76   no       

Unit                          Workload  Agent  Address      Ports  Message
mysql-k8s/0*                  active    idle   10.1.84.74          Unit is ready: Mode: RW
mysql-k8s/1                   active    idle   10.1.84.127         Unit is ready: Mode: RO
self-signed-certificates/0*   active    idle   10.1.84.71 
```

To enable TLS on Charmed MySQL, integrate the two applications:

```{terminal}
:scroll:
:input: juju integrate mysql-k8s self-signed-certificates
:user: ubuntu
:host: my-vm
```

MySQL is now using TLS certificate generated by the `self-signed-certificates` charm.

Use `openssl` to connect to MySQL and check the TLS certificate in use:

```{terminal}
:scroll:
:input: openssl s_client -starttls mysql -connect 10.1.84.74:3306 | grep Issuer
:user: ubuntu
:host: my-vm

...
depth=1 C = US, CN = Tutorial CA
...
```

To remove the external TLS and return to the locally generate one, remove the integration from the applications:

```{terminal}
:input: juju remove-relation mysql-k8s self-signed-certificates
:user: ubuntu
:host: my-vm
```

If you once again check the TLS certificates in use via the OpenSSL client, you will see something similar to the output below:

```{terminal}
:input: openssl s_client -starttls mysql -connect 10.1.84.74:3306 | grep Issuer
:user: ubuntu
:host: my-vm

...
Issuer: CN = MySQL_Server_8.0.31_Auto_Generated_CA_Certificate
...
```

The Charmed MySQL application reverted to the placeholder certificate that was created locally during the MySQL Server installation.

## Clean up your environment

In this tutorial we've successfully deployed and accessed MySQL on MicroK8s, added and removed cluster members, added and removed database users, and enabled a layer of security with TLS.

You may now keep your MySQL deployment running and write to the database, or remove it entirely using the steps in this page.

If you'd like to keep your environment for later, simply stop your VM with:

```{terminal}
:input: multipass stop my-vm
:user: user
:host: my-pc
```

```{caution}
When you remove VM as shown below, you will lose all the data in MySQL and any other applications inside Multipass VM! 

For more information, see the docs for [`multipass delete`](https://multipass.run/docs/delete-command).
```

**Delete your VM and its data** by running:

```{terminal}
:input: multipass delete --purge my-vm
:user: user
:host: my-pc
```

## Next steps

- Run [Charmed MySQL VM on VM/IAAS](https://github.com/canonical/mysql-operator).
- Check out our Charmed offerings of [PostgreSQL K8s](https://charmhub.io/postgresql-k8s?channel=14) and [Kafka K8s](https://charmhub.io/kafka-k8s?channel=edge).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/mysql-k8s-operator/issues) any problems you encountered.
- [Give us your feedback](/reference/contacts).
- [Contribute to the code base](https://github.com/canonical/mysql-k8s-operator)

