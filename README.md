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

The password will be the value for the key `MYSQL_ROOT_PASSWORD`


If required, you can remove the deployment completely:

```bash
$ juju destroy-model -y mysql-k8s --no-wait --force --destroy-storage
```

Note the `--destroy-storage` will delete any data stored by MySQL in its persistent store.


### Config

This charm implements the following configs:

- `MYSQL_USER`: Create a new user with superuser privileges. This is used in conjunction with `MYSQL_PASSWORD`.
- `MYSQL_PASSWORD`: Set the password for the `MYSQL_USER` user.
- `MYSQL_DATABASE`: Set the name of the default database.

And you can use it, like this:

```bash
$  juju deploy ./mysql-k8s.charm --config MYSQL_ROOT_PASSWORD=SuperSecretPassword --config MYSQL_USER=JohnDoe --config MYSQL_PASSWORD=SuperSecretUserPassword --config MYSQL_DATABASE=default_database --resource mysql-image=ubuntu/mysql:lates
```

### Relations

This charm provides a `database` relation so you can integrate this charm with others charms that requires a MySQL database.


## Developing

Create and activate a virtualenv with the development requirements:

```bash
$ virtualenv -p python3 venv
$ source venv/bin/activate
$ pip install -r requirements-dev.txt
    ```

### Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments to a [microk8s](https://microk8s.io/) cluster can be done using the following commands

```bash
$ sudo snap install microk8s --classic
$ microk8s.enable dns storage registry dashboard
$ sudo snap install juju --classic
$ juju bootstrap microk8s microk8s
$ juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath
```

### Build

Install the charmcraft tool

```bash
$ sudo snap install charmcraft
```

Build the charm in this git repository

```bash
$ charmcraft build
```

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
