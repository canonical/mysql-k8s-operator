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
$ microk8s.enable dns storage
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

Unit tests are implemented using the Operator Framework test [harness](https://ops.readthedocs.io/en/latest/#module-ops.testing). These tests may executed by doing:


```bash
$ ./run_tests
```


## Code Overview

The core implementation of this charm is represented by the [`MySQLCharm`](src/charm.py) class.
`MySQLCharm` responds to

- configuation changes,

In response to any change in its configuration, `MySQLCharm` regenerates its config file, and restarts itself.

The `MySQLCharm` object interacts with its consumers using a [charm library](lib/charms/prometheus_k8s/v1/prometheus.py). Using this library requires that MySQL informs its "Consumers" of the actual MySQL version that was deployed. In order to determine this version at runtime `MySQLCharm` uses the [`MySQL`](src/prometheus_server.py) object.
The `MySQL` object provides an interface to a running MySQL instance. This interface is limited to only those aspects of MySQL required by this charm.


## Design Choices

This MySQL charm does not support (yet) any kind of clustering. As a result of this decision scaling MySQL units only results in standalone units with the same configuration.


## Road Map

Roughly by order of priority

- Support primary-secondary replication
- Improve MySQL charm actions (backup, restore, etc)
- Support tuning the MySQL config
