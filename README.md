# MySQL Operator

## Description

The [MySQL](https://www.mysql.com/) operator provides an open-source relational database management system (RDBMS). This repository contains a Juju Charm for deploying MySQL on Kubernetes clusters.


## Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments to a [microk8s](https://microk8s.io/) cluster can be done using the following commands

```bash
$ sudo snap install microk8s --classic
$ microk8s.enable dns storage registry dashboard
$ sudo snap install juju --classic
$ juju bootstrap microk8s microk8s
$ juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath
```

## Build

Install the charmcraft tool

```bash
$ sudo snap install charmcraft
```

Build the charm in this git repository

```bash
$ charmcraft build
```

## Usage


Create a Juju model for your operators, say "mysql"

```bash
$ juju add-model mysql
```

Deploy a single unit of MySQL using its default configuration

```bash
$ juju deploy ./mysql.charm --resource mysql-image=ubuntu/mysql:lates
```

As in this example we did not especify the password for the root user, the charm will generate one, and you can get it watching the juju debug-log:


```bash
$ juju debug-log -l

...

application-mysql: 13:45:16 WARNING unit.mysql/0.juju-log The randomly generated MYSQL_ROOT_PASSWORD is: T4NgXUeXYlJBBD37icuM
application-mysql: 13:45:16 WARNING unit.mysql/0.juju-log Please change it as soon as possible!
```

If required, yo can remove the deployed completely:

```bash
$ juju destroy-model -y mysql --no-wait --force --destroy-storage
```

Note the `--destroy-storage` will delete any data stored by MySQL in its persistent store.


### Parameters

This charm implements the following parameters:

- `MYSQL_USER`: Create a new user with superuser privileges. This is used in conjunction with `MYSQL_PASSWORD`.
- `MYSQL_PASSWORD`: Set the password for the `MYSQL_USER` user.
- `MYSQL_DATABASE`: Set the name of the default database.

And you can use it, like this:

```bash
$  juju deploy ./mysql.charm --config MYSQL_ROOT_PASSWORD=SuperSecretPassword --config MYSQL_USER=JohnDoe --config MYSQL_PASSWORD=SuperSecretUserPassword --config MYSQL_DATABASE=default_database --resource mysql-image=ubuntu/mysql:lates
```


## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
