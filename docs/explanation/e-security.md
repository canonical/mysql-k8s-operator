# Security hardening guide

This document provides an overview of security features and guidance for hardening the security of [Charmed MySQL K8s](https://charmhub.io/mysql-k8s) deployments, including setting up and managing a secure environment.

## Environment

The environment where Charmed MySQL K8s operates can be divided into two components:

1. Kubernetes
2. Juju

### Kubernetes

Charmed MySQL K8s can be deployed on top of several Kubernetes distributions. The following table provides references for the security documentation for the main supported cloud platforms.

| Cloud              | Security guides                                                                                                                                                                                                                                                                                                                                   |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Charmed Kubernetes | [Security in Charmed Kubernetes](https://ubuntu.com/kubernetes/docs/security)                                                                                                                                                                                                                                                                    |
| AWS EKS            | [Best Practices for Security, Identity and Compliance](https://aws.amazon.com/architecture/security-identity-compliance), [AWS security credentials](https://docs.aws.amazon.com/IAM/latest/UserGuide/security-creds.html#access-keys-and-secret-access-keys), [Security in EKS](https://docs.aws.amazon.com/eks/latest/userguide/security.html) | 
| Azure              | [Azure security best practices and patterns](https://learn.microsoft.com/en-us/azure/security/fundamentals/best-practices-and-patterns), [Managed identities for Azure resource](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/), [Security in AKS](https://learn.microsoft.com/en-us/azure/aks/concepts-security)                                                      |
| GCP GKE              |  [Google security overview](https://cloud.google.com/kubernetes-engine/docs/concepts/security-overview), [Harden your cluster's security](https://cloud.google.com/kubernetes-engine/docs/concepts/security-overview)                                                    |

### Juju 

Juju is the component responsible for orchestrating the entire lifecycle, from deployment to Day 2 operations. For more information on Juju security hardening, see the
[Juju security page](/t/juju-security/15684) and the [How to harden your deployment](https://juju.is/docs/juju/harden-your-deployment) guide.

#### Cloud credentials

When configuring cloud credentials to be used with Juju, ensure that users have the correct permissions to operate at the required level on the Kubernetes cluster. Juju superusers responsible for bootstrapping and managing controllers require elevated permissions to manage several kinds of resources. For this reason, the K8s user for bootstrapping and managing the deployments should have full permissions, such as: 

* create, delete, patch, and list:
    * namespaces
    * services
    * deployments
    * stateful sets
    * pods
    * PVCs

In general, it is common practice to run Juju using the admin role of K8s, to have full permissions on the Kubernetes cluster. 

#### Juju users

It is very important that Juju users are set up with minimal permissions depending on the scope of their operations. Please refer to the [User access levels](https://juju.is/docs/juju/user-permissions) documentation for more information on the access levels and corresponding abilities.

Juju user credentials must be stored securely and rotated regularly to limit the chances of unauthorized access due to credentials leakage.

## Applications

In the following sections, we provide guidance on how to harden your deployment using:

1. Base images
2. Charmed operator security upgrades
3. Encryption 
4. Authentication
5. Monitoring and auditing

### Base images

Charmed MySQL K8s and Charmed MySQL Router K8s run on top of the same rock (OCI-compliant rockcraft-based image). The rock is based on Ubuntu 22.04 and ships the MySQL distribution binaries built by Canonical. It is stored in a [GitHub registry](https://github.com/canonical/charmed-mysql-rock/pkgs/container/charmed-mysql) and is used as the base image for different pods providing MySQL services. 

### Charmed operator security upgrades

[Charmed MySQL K8s operator](https://github.com/canonical/mysql-k8s-operator) and [Charmed MySQL Router K8s operator](https://github.com/canonical/mysql-router-k8s-operator) install pinned versions of the rock to provide reproducible and secure environments. New versions (revisions) of charmed operators can be released to update the operator's code, workloads, or both. It is important to refresh the charm regularly to make sure the workload is as secure as possible.

For more information on upgrading Charmed MySQL K8s, see the [How to upgrade MySQL](https://canonical.com/data/docs/mysql/k8s/h-upgrade) and [How to upgrade MySQL Router](https://charmhub.io/mysql-router-k8s/docs/h-upgrade-intro) guides, as well as the [Release notes](https://canonical.com/data/docs/mysql/k8s/r-releases).

### Encryption

By default, encryption is optional for external connections. Internal communication between cluster members is always encrypted with TLS with self-signed certificates.

To enforce encryption in transit for external connections, integrate Charmed MySQL K8s with a TLS certificate provider. Please refer to the [Charming Security page](https://charmhub.io/topics/security-with-x-509-certificates) for more information on how to select the right certificate provider for your use case.

Encryption in transit for backups is provided by the storage service (Charmed MySQL K8s is a client for an S3-compatible storage).

For more information on encryption, see the [Cryptography](https://discourse.charmhub.io/t/charmed-mysql-k8s-explanations-cryptography/16783) explanation page and [How to enable encryption](https://canonical.com/data/docs/mysql/k8s/h-enable-tls) guide.

### Authentication

Charmed MySQL K8s uses the [caching_sha2_password](https://dev.mysql.com/doc/refman/8.0/en/caching-sha2-pluggable-authentication.html) plugin for authentication. 

### Monitoring and auditing

Charmed MySQL K8s provides native integration with the [Canonical Observability Stack (COS)](https://charmhub.io/topics/canonical-observability-stack). To reduce the blast radius of infrastructure disruptions, the general recommendation is to deploy COS and the observed application into separate environments, isolated from one another. Refer to the [COS production deployments best practices](https://charmhub.io/topics/canonical-observability-stack/reference/best-practices) for more information or see the How to guides for MySQL K8s [monitoring](https://canonical.com/data/docs/mysql/k8s/h-enable-monitoring), [alert rules](https://canonical.com/data/docs/mysql/k8s/h-enable-alert-rules), and [tracing](https://canonical.com/data/docs/mysql/k8s/h-enable-tracing) for practical instructions.

The Audit log plugin is enabled by default and produces login/logout logs. See the [Audit Logs](https://charmhub.io/mysql-k8s/docs/e-audit-logs) guide for further configuration. These logs are stored in the /var/log/mysql directory of the MySQL container and are rotated every minute to the /var/log/mysql/archive_audit directory. It’s recommended to integrate the charm with [COS](https://discourse.charmhub.io/t/9900), from where the logs can be easily persisted and queried using [Loki](https://charmhub.io/loki-k8s)/[Grafana](https://charmhub.io/grafana).

## Additional Resources

For details on the cryptography used by Charmed MySQL K8s, see the [Cryptography](https://discourse.charmhub.io/t/charmed-mysql-k8s-explanations-cryptography/16783) explanation page.