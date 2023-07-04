# Deploy Charmed MySQL K8s on GKE

Google Kubernetes Engine (GKE) - the most scalable and fully automated Kubernetes service from Google. To access GKE WEB interface, open https://console.cloud.google.com/compute/

# Install GKE and Juju tooling
Install juju and gcloud tool using SNAP:
```shell
> sudo snap install juju --classic
> sudo snap install kubectl --classic
> sudo snap install google-cloud-cli --classic
```
Login to Google Account
```shell
> gcloud auth login

Go to the following link in your browser:

    https://accounts.google.com/o/oauth2/...

Enter authorization code: 4/0Absad3s...

You are now logged in as [your_account@gmail.com].
```

Now you need to associate this installation with GCloud project, using "Project ID" from [resource-management](https://console.cloud.google.com/cloud-resource-manager):
```shell
> gcloud config set project <PROJECT_ID>

Updated property [core/project].
```

As a last step, install the Debian package `google-cloud-sdk-gke-gcloud-auth-plugin` using [Google manual](https://cloud.google.com/sdk/docs/install#deb).

# Create new GKE cluster
The following command will start three [compute engines](https://cloud.google.com/compute/) on Google Cloud (imagine them as three physical servers in clouds) and deploy K8s cluster there.  To simplify the manual, the following command will use high-availability zone `europe-west1` and compute engine type `n1-standard-4` (which can be adopted for your needs if necessary):
```shell
gcloud container clusters create --zone europe-west1-c $USER-$RANDOM --cluster-version 1.25 --machine-type n1-standard-4 --preemptible --num-nodes=3 --no-enable-autoupgrade
```

Now, let's assign our account as an admin of newly created K8s:
```shell
kubectl create clusterrolebinding cluster-admin-binding-$USER --clusterrole=cluster-admin --user=$(gcloud config get-value core/account)
```

# Bootstrap Juju on GKE
Bootstrap new juju controller on fresh cluster, copying commands one-by-one:
```shell
> juju add-k8s gke-jun-9 --storage=standard --client
> juju bootstrap gke-jun-9
> juju add-model welcome-model
```
At this stage Juju is ready to use GKE, check the list of currently running K8s pods and juju status:
```shell
> kubectl get pods -n welcome-model
> juju status
```

# Deploy Charms
```shell
> juju deploy mysql-k8s-bundle --channel 8.0/edge --trust
> juju deploy mysql-test-app
> juju relate mysql-test-app mysql-k8s:database
> juju status --watch 1s
```

# List
To list GKE clusters and juju clouds, use:
```shell
> gcloud container clusters list

NAME          LOCATION        MASTER_VERSION   MASTER_IP      MACHINE_TYPE   NODE_VERSION     NUM_NODES  STATUS
mykola-18187  europe-west1-c  1.25.9-gke.2300  31.210.22.127  n1-standard-4  1.25.9-gke.2300  3          RUNNING
taurus-7485   europe-west1-c  1.25.9-gke.2300  142.142.21.25  n1-standard-4  1.25.9-gke.2300  3          RUNNING
```
Juju can handle multiply clouds simultaneously. The list of clouds with registered credentials on Juju:
```shell
> juju clouds
Clouds available on the controller:
Cloud      Regions  Default       Type
gke-jun-9  1        europe-west1  k8s  

Clouds available on the client:
Cloud           Regions  Default       Type  Credentials  Source    Description
gke-jun-9       1        europe-west1  k8s   1            local     A Kubernetes Cluster
localhost       1        localhost     lxd   1            built-in  LXD Container Hypervisor
microk8s        0                      k8s   1            built-in  A local Kubernetes context
```

# Cleanup
**Note**: always clean no-longer necessary GKE resources as they all could be costly!!!

To clean GKE clusters and juju clouds, use:
```shell
> juju destroy-controller gke-jun-9-europe-west1 --yes --destroy-all-models --destroy-storage --force
> juju remove-cloud gke-jun-9 # --client --controller gke-jun-9-europe-west1

> gcloud container clusters list
> gcloud container clusters delete <$USER-$RANDOM> --zone europe-west1-c
```
Revoke the GCloud user credentials:
```shell
> gcloud auth revoke your_account@gmail.com

Revoked credentials:
 - your_account@gmail.com
```