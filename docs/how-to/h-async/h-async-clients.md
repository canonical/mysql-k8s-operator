# Clients for Async replication
> **WARNING**: it is an '8.0/candidate' article. Do NOT use it in production!<br/>Contact [Canonical Data Platform team](/t/11868) if you are interested in the topic.

## Pre-requisits
Make sure both `Rome` and `Lisbon` Clusters are deployed using the [Async Deployment manual](/t/13458)!

## Offer and consume DB endpoints
```shell
juju switch rome
juju offer db1:database db1-database

juju switch lisbon
juju offer db2:database db2-database

juju add-model app ; juju switch app
juju consume rome.db1-database
juju consume lisbon.db2-database
```

## Internal Juju app/clients
```shell
juju switch app

juju deploy mysql-test-app
juju deploy mysql-router-k8s --trust --channel 8.0/edge

juju relate mysql-test-app mysql-router-k8s
juju relate mysql-router-k8s db1-database
```

## External Juju clients
```shell
juju switch app

juju deploy data-integrator --config database-name=mydatabase
juju deploy mysql-router-k8s mysql-router-external --trust --channel 8.0/edge

juju relate data-integrator mysql-router-external
juju relate mysql-router-external db1-database

juju run data-integrator/leader get-credentials
```