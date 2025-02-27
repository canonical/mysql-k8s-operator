# How to deploy on AKS

[Azure Kubernetes Service](https://learn.microsoft.com/en-us/azure/aks/) (AKS) allows you to quickly deploy a production ready Kubernetes cluster in Azure. To access the AKS Web interface, go to [https://portal.azure.com/](https://portal.azure.com/).

## Summary
* [Install AKS and Juju tooling](#install-aks-and-juju-tooling)
  * [Authenticate](#authenticate)
* [Create a new AKS cluster](#create-a-new-aks-cluster)
* [Bootstrap Juju on AKS](#bootstrap-juju-on-aks)
* [Deploy charms](#deploy-charms)
* [Display deployment information](#display-deployment-information)
* [Clean up](#clean-up)

---

## Install AKS and Juju tooling

Install Juju and Azure CLI tool:
```shell
sudo snap install juju
sudo apt install --yes azure-cli
```
Follow the installation guides for:
* [az](https://learn.microsoft.com/en-us/cli/azure/what-is-azure-cli) - the Azure CLI

To check they are all correctly installed, you can run the commands demonstrated below with sample outputs:

```shell
~$ juju version
3.4.2-genericlinux-amd64

~$ az --version
azure-cli                         2.61.0

core                              2.61.0
telemetry                          1.1.0

Dependencies:
msal                              1.28.0
azure-mgmt-resource               23.1.1
...
Your CLI is up-to-date.
```
### Authenticate
Login to your Azure account:
```shell
az login
```

## Create a new AKS cluster

Export the deployment name for further use:
```shell
export JUJU_NAME=aks-$USER-$RANDOM
```

This following examples in this guide will use the single server AKS in location `eastus` - feel free to change this for your own deployment.

Create a new [Azure Resource Group](https://learn.microsoft.com/en-us/cli/azure/manage-azure-groups-azure-cli):

```shell
az group create --name aks --location eastus
```
Bootstrap AKS with the following command (increase nodes count/size if necessary):
```shell
az aks create -g aks -n ${JUJU_NAME} --enable-managed-identity --node-count 1 --node-vm-size=Standard_D4s_v4 --generate-ssh-keys
```

Sample output:
```yaml
{
  "aadProfile": null,
  "addonProfiles": null,
  "agentPoolProfiles": [
    {
      "availabilityZones": null,
      "capacityReservationGroupId": null,
      "count": 1,
      "creationData": null,
      "currentOrchestratorVersion": "1.28.9",
      "enableAutoScaling": false,
      "enableEncryptionAtHost": false,
      "enableFips": false,
      "enableNodePublicIp": false,
...
```

Dump newly bootstraped AKS credentials:
```shell
az aks get-credentials --resource-group aks --name ${JUJU_NAME} --context aks
```

Sample output:
```shell
...
Merged "aks" as current context in ~/.kube/config
```

## Bootstrap Juju on AKS

Bootstrap Juju controller:
```shell
juju bootstrap aks aks
```
Sample output:
```shell
Creating Juju controller "aks" on aks/eastus
Bootstrap to Kubernetes cluster identified as azure/eastus
Creating k8s resources for controller "controller-aks"
Downloading images
Starting controller pod
Bootstrap agent now started
Contacting Juju controller at 20.231.233.33 to verify accessibility...

Bootstrap complete, controller "aks" is now available in namespace "controller-aks"

Now you can run
	juju add-model <model-name>
to create a new model to deploy k8s workloads.
```

Create a new Juju model (k8s namespace)
```shell
juju add-model welcome aks
```
[Optional] Increase DEBUG level if you are troubleshooting charms:
```shell
juju model-config logging-config='<root>=INFO;unit=DEBUG'
```

## Deploy charms

The following command deploys MySQL K8s:

```shell
juju deploy mysql-k8s --trust -n 3
```
Sample output:
```shell
Deployed "mysql-k8s" from charm-hub charm "mysql-k8s", revision 127 in channel 8.0/stable on ubuntu@22.04/stable
```

Check the status:
```shell
juju status --watch 1s
```
Sample output:
```shell
Model    Controller  Cloud/Region  Version  SLA          Timestamp
welcome  aks         aks/eastus    3.4.2    unsupported  16:42:15+02:00

App        Version                  Status  Scale  Charm      Channel     Rev  Address       Exposed  Message
mysql-k8s  8.0.35-0ubuntu0.22.04.1  active      3  mysql-k8s  8.0/stable  127  10.0.238.103  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.244.0.14         Primary
mysql-k8s/1   active    idle   10.244.0.15         
mysql-k8s/2   active    idle   10.244.0.16 
```

## Display deployment information

Display information about the current deployments with the following commands:
```shell
~$ kubectl cluster-info 
Kubernetes control plane is running at https://aks-user-aks-aaaaa-bbbbb.hcp.eastus.azmk8s.io:443
CoreDNS is running at https://aks-user-aks-aaaaa-bbbbb.hcp.eastus.azmk8s.io:443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
Metrics-server is running at https://aks-user-aks-aaaaa-bbbbb.hcp.eastus.azmk8s.io:443/api/v1/namespaces/kube-system/services/https:metrics-server:/proxy

~$ az aks list
...
        "count": 1,
        "currentOrchestratorVersion": "1.28.9",
        "enableAutoScaling": false,
...

~$ kubectl get node
NAME                                STATUS   ROLES   AGE   VERSION
aks-nodepool1-55146003-vmss000000   Ready    agent   11m   v1.28.9
```

## Clean up

[note type="caution"]
Always clean AKS resources that are no longer necessary -  they could be costly!
[/note]

To clean the AKS cluster, resources and juju cloud, run the following commands:

```shell
juju destroy-controller aks --destroy-all-models --destroy-storage --force
```
List all services and then delete those that have an associated EXTERNAL-IP value (load balancers, ...):
```shell
kubectl get svc --all-namespaces
kubectl delete svc <service-name> 
```
Next, delete the AKS resources (source: [Deleting an all Azure VMs]((https://learn.microsoft.com/en-us/cli/azure/delete-azure-resources-at-scale#delete-all-azure-resources-of-a-type) )) 
```shell
az aks delete -g aks -n ${JUJU_NAME}
```
Finally, logout from AKS to clean the local credentials (to avoid forgetting and leaking):
```shell
az logout
```