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
$ juju add-model lma
```

Deploy a single unit of MySQL using its default configuration

```bash
$ juju deploy ./mysql.charm
```


If required, remove the deployed monitoring model completely

```bash
$ juju destroy-model -y mysql --no-wait --force --destroy-storage
```

Note the `--destroy-storage` will delete any data stored by MongoDB in
its persistent store.


## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
