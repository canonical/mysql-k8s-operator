# Deploy charm module

The MySQL K8s _charm_ Terraform module is the smallest unit that can be deployed using Terraform,
only containing the MySQL Server charm. It is supposed to be deployed alongside other charms
to build a more complex setup.

## Install Terraform tooling

This guide assumes Juju is installed, and you have a K8s controller already bootstrapped. For more information, check the [Charmed MySQL tutorial](/tutorial/index).

Let's install the Terraform and YQ snaps:
```shell
sudo snap install terraform --classic
sudo snap install yq
```

Switch to the K8s provider and create a new model:
```shell
juju switch microk8s
juju add-model my-model
juju show-model my-model | yq '."my-model"."model-uuid"'
```

Clone the MySQL operator repository and navigate to the terraform module:
```shell
git clone https://github.com/canonical/mysql-k8s-operator.git
cd terraform
```

Initialise the Juju Terraform Provider:
```shell
terraform init
```

## Verify the deployment

Open the `main.tf` file to see the brief contents of the Terraform module, and run `terraform plan` to get a preview of the changes that will be made:

```shell
terraform plan -var 'model=<model-uuid>'
```

## Apply the deployment

If everything looks correct, deploy the resources (skip the approval):

```shell
terraform apply -auto-approve -var 'model=<model-uuid>'
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

App        Version          Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.41-0ubun...  active      1  mysql-k8s  8.0/stable  255  10.152.183.112  no

Unit          Workload  Agent  Machine  Address     Ports           Message
mysql-k8s/0*  active    idle   0        10.1.77.76  3306,33060/tcp  Primary
```

Continue to operate the charm as usual from here or apply further Terraform changes.

## Clean up

To keep the house clean, remove the newly deployed MySQL K8s charm by running
```shell
terraform destroy -var 'model=<model-uuid>'
```

---

Feel free to [contact us](/reference/contacts) if you have any question and collaborate with us on GitHub!
