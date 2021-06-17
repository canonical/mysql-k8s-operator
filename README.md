# MySQL Operator for K8s

![tests](https://github.com/canonical/mysql-operator/actions/workflows/run-tests.yaml/badge.svg)


## Description

The [MySQL](https://www.mysql.com/) operator provides an open-source relational database management system (RDBMS). This repository contains a Juju Charm for deploying MySQL on Kubernetes clusters.


## Deployment instructions


Create a Juju model for your operators, say "mysql-k8s"

```bash
$ juju add-model mysql-k8s
```

Deploy a single unit of MySQL using its default configuration

```bash
$ juju deploy ./mysql-k8s.charm --resource mysql-image=ubuntu/mysql:latest
```

As in this example we did not specify the password for the root user, the charm will generate one, and you can get it executing:


```bash
$ juju show-unit mysql-k8s/0

```

The password will be the value for the key `mysql_root_password`


If required, you can remove the deployment completely:

```bash
$ juju destroy-model -y mysql-k8s --no-wait --force --destroy-storage
```

Note the `--destroy-storage` will delete any data stored by MySQL in its persistent store.


### Config

This charm implements the following configs:

- `mysql_user`: Create a new user with superuser privileges. This is used in conjunction with `mysql_password`.
- `mysql_password`: Set the password for the `mysql_user` user.
- `mysql_database`: Set the name of the default database.

And you can use it, like this:

```bash
$  juju deploy ./mysql-k8s.charm --config mysql_root_password=SuperSecretPassword --config mysql_user=JohnDoe --config mysql_password=SuperSecretUserPassword --config mysql_database=default_database --resource mysql-image=ubuntu/mysql:latest
```

## Relations

This charm provides a `database` relation so you can integrate this charm with others charms that requires a MySQL database.
