# How to connect to your database outside of Kubernetes

## External K8s application (non-Juju)

**Use case**: the client application is a non-Juju application outside of DB K8s deployment.

To connect the Charmed MySQL K8s database from outside of the Kubernetes cluster, the charm MySQL Router K8s should be deployed. Please follow the [MySQL Router K8s documentation](https://charmhub.io/mysql-router-k8s/docs/h-external-access).

## External K8s relation (Juju)

**Use case**: the client application is a Juju application outside of DB K8s deployment (e.g. hybrid Juju deployment with mixed K8s and VM applications).

In this case the the cross-hybrid-relation is necessary. Please [contact](/reference/contacts) the Data team to discuss the possible option for your use case.

