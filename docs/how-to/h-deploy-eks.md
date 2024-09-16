# Deploy Charmed MySQL K8s on EKS

[Amazon Elastic Kubernetes Service](https://aws.amazon.com/eks/) (EKS) - one of the most popular and fully automated Kubernetes service from Amazon. To access EKS WEB interface, open the Console https://console.aws.amazon.com/eks/home

# Install EKS and Juju tooling

Install:

* [Juju](https://juju.is/docs/juju/install-juju) (an open source orchestration engine from Canonical)
* [kubectl](https://kubernetes.io/docs/tasks/tools/) (Kubernetes command line tool)
* [eksctl](https://eksctl.io/installation/) (the official CLI for Amazon EKS)
* [AWC CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (Amazon Web Services Command Line Interface)

Make sure all works:

```shell
> juju version
2.9.45-ubuntu-amd64

> kubectl version --client
Client Version: v1.28.2
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3

> eksctl info
eksctl version: 0.159.0
kubectl version: v1.28.2

> aws --version
aws-cli/2.13.25 Python/3.11.5 Linux/6.2.0-33-generic exe/x86_64.ubuntu.23 prompt/off
```

Create IAM account (or legacy Access keys) and login to AWS:
```shell
> aws configure
AWS Access Key ID [None]: SECRET_ACCESS_KEY_ID
AWS Secret Access Key [None]: SECRET_ACCESS_KEY_VALUE
Default region name [None]: eu-west-3
Default output format [None]:

> aws sts get-caller-identity
{
    "UserId": "1234567890",
    "Account": "1234567890",
    "Arn": "arn:aws:iam::1234567890:root"
}
```

# Bootstrap Kubernetes cluster (EKS)

Export the deployment name to be used further:
```shell
export JUJU_NAME=eks-$USER-$RANDOM
```

Feel free to fine-tune the location (`eu-west-3`) and/or K8s version (`1.27`):

```shell
cat <<-EOF > cluster.yaml
---
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
    name: ${JUJU_NAME}
    region: eu-west-3
    version: "1.27"
iam:
  withOIDC: true

addons:
- name: aws-ebs-csi-driver
  wellKnownPolicies:
    ebsCSIController: true

nodeGroups:
    - name: ng-1
      minSize: 3
      maxSize: 5
      iam:
        attachPolicyARNs:
        - arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
        - arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
        - arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
        - arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
        - arn:aws:iam::aws:policy/AmazonS3FullAccess
      instancesDistribution:
        maxPrice: 0.15
        instanceTypes: ["m5.xlarge", "m5.2xlarge"] # At least two instance types should be specified
        onDemandBaseCapacity: 0
        onDemandPercentageAboveBaseCapacity: 50
        spotInstancePools: 2
EOF
```
Bootstrap EKS cluster:
```shell
> eksctl create cluster -f cluster.yaml
...
2023-10-12 11:13:58 [ℹ]  using region eu-west-3
2023-10-12 11:13:59 [ℹ]  using Kubernetes version 1.27
...
2023-10-12 11:40:00 [✔]  EKS cluster "eks-taurus-27506" in "eu-west-3" region is ready
```

# Bootstrap Juju on EKS
> **TIP**: Juju 3.x https://bugs.launchpad.net/juju/+bug/2007848

```shell
# Add Juju K8s Clous
> juju add-k8s $JUJU_NAME

# Bootstrap Juju Controller
> juju bootstrap $JUJU_NAME

# Create a new Juju model (K8s namespace)
> juju add-model welcome

# (optional) Increase DEBUG level if you are troubleshooting charms 
> juju model-config logging-config='<root>=INFO;unit=DEBUG'
```

# Deploy Charms
```shell
> juju deploy mysql-k8s-bundle --channel 8.0/edge --trust
> juju deploy mysql-test-app
> juju relate mysql-test-app mysql-k8s:database
> juju status --watch 1s
```

# List
```shell

> juju controllers
Controller         Model    User   Access     Cloud/Region      Models  Nodes  HA  Version
eks-taurus-27506*  welcome  admin  superuser  eks-taurus-27506       2      1   -  2.9.45  

> kubectl cluster-info 
Kubernetes control plane is running at https://AAAAAAAAAAAAAAAAAAAAAAA.gr7.eu-west-3.eks.amazonaws.com
CoreDNS is running at https://AAAAAAAAAAAAAAAAAAAAAAA.gr7.eu-west-3.eks.amazonaws.com/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

> eksctl get cluster -A
NAME			    REGION		EKSCTL   CREATED
eks-taurus-27506	eu-west-3	True

> kubectl get node
NAME                                           STATUS   ROLES    AGE   VERSION
ip-192-168-14-61.eu-west-3.compute.internal    Ready    <none>   19m   v1.27.5-eks-43840fb
ip-192-168-51-96.eu-west-3.compute.internal    Ready    <none>   19m   v1.27.5-eks-43840fb
ip-192-168-78-167.eu-west-3.compute.internal   Ready    <none>   19m   v1.27.5-eks-43840fb
```

# Cleanup
**Note**: always clean no-longer necessary EKS resources as they all could be costly!!!

To [clean](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html) EKS cluster, resources and juju cloud, use:
```shell
> juju destroy-controller $JUJU_NAME --yes --destroy-all-models --destroy-storage --force
> juju remove-cloud $JUJU_NAME

> kubectl get svc --all-namespaces
> kubectl delete svc <service-name> # Delete any services that have an associated EXTERNAL-IP value (load balancers, ...)

> eksctl get cluster -A
> eksctl delete cluster <cluster_name> --region eu-west-3 --force --disable-nodegroup-eviction
```
Remove AWS CLI user credentials (to avoid forgetting and leaking):
```shell
> rm -f ~/.aws/credentials
```