# Deploy product module

## Install Terraform tooling

This guide assumes Juju is installed, and you have a K8s controller already bootstrapped. For more information, check the [Charmed MySQL tutorial](/tutorial/index).

Let's install Terraform Provider and example modules:
```shell
sudo snap install terraform --classic
```

Switch to the K8s provider and create a new model:
```shell
juju switch microk8s
juju add-model my-model
```

Clone the MySQL operator repository and navigate to the terraform module:
```shell
git clone https://github.com/canonical/mysql-k8s-bundle.git
cd terraform
```

Initialise the Juju Terraform Provider:
```shell
terraform init
```

## Verify the deployment

Open the `main.tf` file to see the brief contents of the Terraform module, and run `terraform plan` to get a preview of the changes that will be made:

```shell
terraform plan -var 'model=my-model'
```

## Apply the deployment

### Default charms

The default MySQL product module deploys MySQL Server, MySQL Router and S3 Integrator charms.
In order to deploy those resources:

```shell
terraform apply -auto-approve \
    -var 'model=my-model'
```

### Extended charms

The extended MySQL product module deploys [self-signed-certificates](https://charmhub.io/self-signed-certificates) and [grafana-agent-k8s](https://charmhub.io/grafana-agent-k8s) charms on top.
In order to deploy all resources:

```shell
terraform apply -auto-approve \
    -var 'model=my-model' \
    -var 'tls_offer=certificates' \
    -var 'cos_offers={"dashboard"="grafana-dashboards-consumer","metrics"="metrics-endpoint"}'
```

It is possible to substitute both of these charms by overwriting some of the module variables.

For instance, the `self-signed-certificates` charm is used to provide the TLS certificates,
but it is not a _production-ready_ charm. It must be changed before deploying on a real environment.
As an alternative, the [manual-tls-certificates](https://charmhub.io/manual-tls-certificates) could be used.

```shell
terraform apply -auto-approve \
    -var 'model=my-model' \
    -var 'tls_offer=certificates' \
    -var 'certificates={"app_name"="manual-tls-certificates","base"="ubuntu@22.04","channel"="latest/stable"}'
```

## Configure the deployment

The S3 Integrator charm needs to be configured for it to work properly.
Wait until it reaches `active` status and run:

```shell
juju run s3-integrator/leader sync-s3-credentials \
    access-key=<access-key> \
    secret-key=<secret-key>
```

```{seealso}
[](/how-to/back-up-and-restore/configure-s3-aws)
```

## Check deployment status

Check the deployment status with 

```shell
juju status --model k8s:my-model --watch 1s
```

Sample output:

```shell
Model     Controller      Cloud/Region         Version  SLA          Timestamp
my-model  k8s-controller  microk8s/localhost   3.5.3    unsupported  12:49:34Z

App               Version          Status  Scale  Charm              Channel        Rev  Address         Exposed  Message                                
mysql-k8s         8.0.41-0ubun...  active      3  mysql-k8s          8.0/stable     255  10.152.183.112  no
mysql-router-k8s                   blocked     1  mysql-router-k8s   8.0/stable     748  10.152.183.140  no       Missing relation: database
s3-integrator                      active      1  s3-integrator      1/stable       241  10.152.183.160  no

Unit                 Workload  Agent  Address         Ports           Message
mysql-k8s/0*         active    idle   10.1.77.76      3306,33060/tcp  Primary
mysql-k8s/1          active    idle   10.1.77.77
mysql-k8s/2          active    idle   10.1.77.78
mysql-router-k8s/0*  active    idle   10.1.77.79    
s3-integrator/0*     active    idle   10.1.77.80
```

Continue to operate the charm as usual from here or apply further Terraform changes.

## Clean up

To keep the house clean, remove the newly deployed MySQL K8s charm by running
```shell
terraform destroy -var 'model=my-model'
```

---

Feel free to [contact us](/reference/contacts) if you have any question and collaborate with us on GitHub!
