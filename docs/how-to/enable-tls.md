# How to enable encryption

<!-- Update and move to explanation
MySQL will enable encrypted connections by default with self generated certificates. Though also by default, connecting clients can disable encryption by setting the connection ssl-mode as disabled.
When related with the `tls-certificates-operator` the charmed operator for MySQL will require that every client connection (new and running connections) use encryption, rendering an error when attempting to establish an unencrypted connection.--->

This guide will show how to enable TLS using the [`self-signed-certificates` operator](https://github.com/canonical/self-signed-certificates-operator) as an example.

```{caution}
**[Self-signed certificates](https://en.wikipedia.org/wiki/Self-signed_certificate) are not recommended for a production environment.**

Check [this guide](https://discourse.charmhub.io/t/11664) for an overview of the TLS certificates charms available. 
```

---
## Enable TLS

First, deploy the TLS charm:
```shell
juju deploy self-signed-certificates
```
To enable TLS on MySQL, integrate the two applications:
```shell
juju integrate self-signed-certificates mysql-k8s
```

## Manage keys

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action. Note that passing keys to external/internal keys should *only be done with* `base64 -w0`, *not* `cat`.

With three replicas, this schema should be followed:

Generate a shared internal (private) key
```shell
openssl genrsa -out internal-key.pem 3072
```

Apply the newly generated internal key on each `juju` unit:
```shell
juju run-action mysql-k8s/0 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)" --wait
juju run-action mysql-k8s/1 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)" --wait
juju run-action mysql-k8s/2 set-tls-private-key "internal-key=$(base64 -w0 internal-key.pem)" --wait
```

Updates can also be done with auto-generated keys:
```shell
juju run-action mysql-k8s/0 set-tls-private-key --wait
juju run-action mysql-k8s/1 set-tls-private-key --wait
juju run-action mysql-k8s/2 set-tls-private-key --wait
```

## Disable TLS
Disable TLS by removing the integration:
```shell
juju remove-relation tls-certificates-operator mysql-k8s
```

