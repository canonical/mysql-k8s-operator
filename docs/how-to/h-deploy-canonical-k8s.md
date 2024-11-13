# How to deploy on Canonical Kubernetes

[Canonical Kubernetes](https://ubuntu.com/kubernetes) is a Kubernetes service built on Ubuntu and optimized for most major public clouds. 

This guide shows you how to deploy Charmed MySQL K8s to Canonical Kubernetes.

## Summary
This guide assumes you have a spare hardware/VMs running Ubuntu 22.04 LTS (or newer). 

* [Install Canonical Kubernetes](#install-canonical-kubernetes)
* [Install Juju](#install-juju)
* [Deploy Charmed MySQL K8s](#deploy-charmed-mysql-k8s)

---

## Install Canonical Kubernetes

>The following instructions are a complete but summarized version of the steps for installing Canonical K8s. For more thorough instructions and details, see the official Canonical Kubernetes documentation: [Install Canonical Kubernetes from a snap](https://documentation.ubuntu.com/canonical-kubernetes/latest/src/snap/howto/install/snap/).

Install, bootstrap, and check the status of Canonical K8s with the following commands:
```shell
sudo snap install k8s --edge --classic
sudo k8s bootstrap
sudo k8s status --wait-ready
```

Once Canonical K8s is up and running, [enable the local storage](https://documentation.ubuntu.com/canonical-kubernetes/latest/snap/tutorial/getting-started/#enable-local-storage) (or any another persistent volumes provider, to be used by [Juju Storage](https://juju.is/docs/juju/storage) later):
```shell
sudo k8s enable local-storage
sudo k8s status --wait-ready
```

(Optional) Install kubectl tool and dump the K8s config:
```shell
sudo snap install kubectl --classic
mkdir ~/.kube
sudo k8s config > ~/.kube/config
kubectl get namespaces # to test the credentials
```

## Install Juju

Install Juju and bootstrap the first Juju controller in K8s:
```shell
sudo snap install juju --channel 3.6/candidate
juju add-k8s ck8s --client --context-name="k8s"
juju bootstrap ck8s
```

## Deploy Charmed MySQL K8s

```shell
juju add-model mysql
juju deploy mysql-k8s --trust
```

follow the deployment progress using:
```shell
juju status --watch 1s
```

Example output:
```shell
Model   Controller  Cloud/Region  Version  SLA          Timestamp
mysql   ck8s        ck8s          3.6-rc1  unsupported  18:32:38+01:00

App         Version                  Status  Scale  Charm           Channel     Rev  Address         Exposed  Message
mysql-k8s   8.0.37-0ubuntu0.22.04.3  active      1  mysql-k8s       8.0/stable  180  10.152.183.146  no       

Unit           Workload  Agent  Address    Ports  Message
mysql-k8s/0*   active    idle   10.1.0.11         Primary
```

>**Next steps:** Learn [how to scale your application](/t/9675), [relate with other applications](/t/9671) and [more](/t/9677)!