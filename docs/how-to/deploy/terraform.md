
# How to deploy using Terraform

[Terraform](https://www.terraform.io/) is an infrastructure automation tool to provision and manage resources in clouds or data centers.
To deploy Charmed MySQL using Terraform and Juju, you can use the [Juju Terraform Provider](https://registry.terraform.io/providers/juju/juju/latest). 

For an in-depth introduction to the Juju Terraform Provider, read [this Discourse post](https://discourse.charmhub.io/t/6939).

## Install Terraform tooling

This guide assumes Juju is installed, and you have a K8s controller already bootstrapped. For more information, check the [Charmed MySQL K8s tutorial](/tutorial/index).

Let's install Terraform Provider and example modules:
```shell
sudo snap install terraform --classic
```

Switch to the K8s provider and create a new model:
```shell
juju switch microk8s
juju add-model my-model
```

Clone the MySQL K8s operator repository and navigate to the terraform module:
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
terraform plan -var "model_name=my-model"
```

## Apply the deployment

If everything looks correct, deploy the resources (skip the approval):

```shell
terraform apply -auto-approve -var "model_name=my-model"
```

## Check deployment status

Check the deployment status with 

```shell
juju status --model k8s:my-model --watch 1s
```

Sample output:

```shell
Model     Controller      Cloud/Region         Version  SLA          Timestamp
my-model  k8s-controller  microk8s/localhost   3.5.3    unsupported  12:37:25Z

App        Version                  Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.41-0ubuntu0.22.04.1  active      1  mysql-k8s  8.0/stable  255  10.152.183.112  no

Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.77.76         Primary
```

Continue to operate the charm as usual from here or apply further Terraform changes.

## Clean up

To keep the house clean, remove the newly deployed MySQL K8s charm by running
```shell
terraform destroy -var "model_name=my-model"
```

Sample output:
```shell
juju_application.mysql_server: Refreshing state... [id=my-model:mysql-k8s]

Terraform used the selected providers to generate the following execution plan. Resource actions are indicated with the following symbols:
  - destroy

Terraform will perform the following actions:

  # juju_application.mysql_server will be destroyed
  - resource "juju_application" "mysql_server" {
      - constraints = "arch=amd64" -> null
      - id          = "my-model:mysql-k8s" -> null
      - model       = "my-model" -> null
      - name        = "mysql-k8s" -> null
      - placement   = "" -> null
      - storage     = [
          - {
              - count = 1 -> null
              - label = "database" -> null
              - pool  = "kubernetes" -> null
              - size  = "10G" -> null
            },
        ] -> null
      - trust       = true -> null
      - units       = 1 -> null

      - charm {
          - base     = "ubuntu@22.04" -> null
          - channel  = "8.0/stable" -> null
          - name     = "mysql-k8s" -> null
          - revision = 255 -> null
          - series   = "jammy" -> null
        }
    }

Plan: 0 to add, 0 to change, 1 to destroy.

Changes to Outputs:
  - application_name = "mysql" -> null

Do you really want to destroy all resources?
  Terraform will destroy all your managed infrastructure, as shown above.
  There is no undo. Only 'yes' will be accepted to confirm.

  Enter a value: yes

juju_application.mysql_server: Destroying... [id=my-model:mysql-k8s]
juju_application.mysql_server: Destruction complete after 0s

Destroy complete! Resources: 1 destroyed.
```

---

Feel free to [contact us](/reference/contacts) if you have any question and collaborate with us on GitHub!
