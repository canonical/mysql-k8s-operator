# MySQL Operator for K8s

![tests](https://github.com/canonical/mysql-operator/actions/workflows/run-tests.yaml/badge.svg)

## Description

The [MySQL](https://www.mysql.com/) operator provides an open-source relational database management system (RDBMS). This repository contains a Juju Charm for deploying MySQL on Kubernetes clusters.

*Note:* This MySQL charm does not currently implement clustering.
Therefore, scaling up with `juju scale-application` will result in multiple units with the same users and passwords, but no data synchronization.

## Usage

Create a Juju model for your operators, say "mysql-k8s"

```bash
$ juju add-model mysql-k8s
```

The MySQL Operator may be deployed using the Juju command line

```bash
$ juju deploy mysql-k8s
```

If required, you can remove the deployment completely:

```bash
$ juju destroy-model -y mysql-k8s --no-wait --force --destroy-storage
```
Note the `--destroy-storage` will delete any data stored by MySQL in its persistent store.

### Config

This charm implements the following optional configs:

- `mysql_root_password`: If it is not specified, the charm will generate one.
- `mysql_user`: Create a new user with superuser privileges. This is used in conjunction with `mysql_password`.
- `mysql_password`: Set the password for the `mysql_user` user.
- `mysql_database`: Set the name of the default database.

And you can use it, like this:

```bash
$  juju deploy mysql-k8s --config mysql_user=JohnDoe --config mysql_password=SuperSecretUserPassword --config mysql_database=default_database
```

As in this example we did not specify the `mysql_root_password`, the charm will generate one, and you can get it executing:


```bash
$ juju show-unit mysql-k8s/0
```

The password will be the value for the key `mysql_root_password`


### Actions

This charm implements the following actions:

- `create-user`
- `delete-user`
- `set-user-password`
- `create-database`


These actions are defined in the actions.yaml file in which you can find the parameters each action supports.

For example if you want to create a new user in MySQL you can run:

```bash
$ juju run-action --wait mysql-k8s/0 create-user username=myuser password=SuperSecretPassword
unit-mysql-k8s-0:
  UnitId: mysql-k8s/0
  id: "16"
  log:
  - 2021-06-24 22:07:47 -0300 -03 Username myuser created
  results:
    username: myuser
  status: completed
  timing:
    completed: 2021-06-25 01:07:47 +0000 UTC
    enqueued: 2021-06-25 01:07:43 +0000 UTC
    started: 2021-06-25 01:07:46 +0000 UTC
```

For more information about actions, please refer to [Juju documentation](https://juju.is/docs/olm/working-with-actions).


## Relations

This charm provides a `mysql_datastore` relation so you can integrate this charm with others charms that requires a MySQL database.


## OCI Images

This charm by default uses the latest version of the [ubuntu/mysql](https://hub.docker.com/r/ubuntu/mysql) image.

