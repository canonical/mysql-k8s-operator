# How to deploy using Terraform

[Terraform](https://www.terraform.io/) is an infrastructure automation tool to provision and manage resources in clouds or data centers. To deploy Charmed MySQL K8s using Terraform and Juju, you can use the [Juju Terraform Provider](https://registry.terraform.io/providers/juju/juju/latest). 

The easiest way is to start from [these examples of terraform modules](https://github.com/canonical/terraform-modules) prepared by Canonical. This page will guide you through a deployment using an example module for MySQL on Kubernetes.

For an in-depth introduction to the Juju Terraform Provider, read [this Discourse post](https://discourse.charmhub.io/t/6939).

[note]
**Note**: Storage support was added in [Juju Terraform Provider version 0.13+](https://github.com/juju/terraform-provider-juju/releases/tag/v0.13.0).
[/note]

## Summary
* [Install Terraform tooling](#install-terraform-tooling)
* [Verify the deployment](#verify-the-deployment)
* [Apply the deployment](#apply-the-deployment)
* [Check deployment status](#check-deployment-status)
* [Clean up](#clean-up)
---

## Install Terraform tooling

This guide assumes Juju is installed and you have a K8s controller already bootstrapped. For more information, check the [Set up the environment](/t/9679) tutorial page.

Let's install Terraform Provider and example modules:
```shell
sudo snap install terraform --classic
```
Switch to the K8s provider and create a new model:
```shell
juju switch microk8s
juju add-model my-model
```
Clone examples and navigate to the MySQL machine module:
```shell
git clone https://github.com/canonical/terraform-modules.git
cd terraform-modules/modules/k8s/mysql
```

Initialise the Juju Terraform Provider:
```shell
terraform init
```

## Verify the deployment

Open the `main.tf` file to see the brief contents of the Terraform module:

```tf
resource "juju_application" "k8s_mysql" {
  name  = var.mysql_application_name
  model = var.juju_model_name
  trust = true

  charm {
    name    = "mysql-k8s"
    channel = var.mysql_charm_channel
  }

  units = 1
}
```

Run `terraform plan` to get a preview of the changes that will be made:

```shell
terraform plan -var "juju_model_name=my-model"
```

## Apply the deployment

If everything looks correct, deploy the resources (skip the approval):

```shell
terraform apply -auto-approve -var "juju_model_name=my-model"
```

## Check deployment status

Check the deployment status with 

```shell
juju status --model k8s:my-model --watch 1s
```

Sample output:

```shell
Model      Controller      Cloud/Region        Version  SLA          Timestamp
my-model   k8s-controller  microk8s/localhost  3.5.3    unsupported  12:37:25Z

App        Version                  Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.36-0ubuntu0.22.04.1  active      1  mysql-k8s  8.0/stable  153  10.152.183.112  no

Unit          Workload  Agent  Address     Ports  Message
mysql-k8s/0*  active    idle   10.1.77.76         Primary

```

Continue to operate the charm as usual from here or apply further Terraform changes.

## Clean up

To keep the house clean, remove the newly deployed Charmed PostgreSQL by running
```shell
terraform destroy -var "juju_model_name=my-model"
```

Sample output:
```shell
juju_application.k8s_mysql: Refreshing state... [id=terra-k8s:mysql-k8s]

Terraform used the selected providers to generate the following execution plan. Resource actions are indicated with the following symbols:
  - destroy

Terraform will perform the following actions:

  # juju_application.k8s_mysql will be destroyed
  - resource "juju_application" "k8s_mysql" {
      - constraints = "arch=amd64" -> null
      - id          = "terra-k8s:mysql-k8s" -> null
      - model       = "terra-k8s" -> null
      - name        = "mysql-k8s" -> null
      - placement   = "" -> null
      - storage     = [
          - {
              - count = 1 -> null
              - label = "database-1" -> null
              - pool  = "kubernetes" -> null
              - size  = "1G" -> null
            },
        ] -> null
      - trust       = true -> null
      - units       = 1 -> null

      - charm {
          - base     = "ubuntu@22.04" -> null
          - channel  = "8.0/stable" -> null
          - name     = "mysql-k8s" -> null
          - revision = 153 -> null
          - series   = "jammy" -> null
        }
    }

Plan: 0 to add, 0 to change, 1 to destroy.

Changes to Outputs:
  - application_name = "mysql-k8s" -> null

Do you really want to destroy all resources?
  Terraform will destroy all your managed infrastructure, as shown above.
  There is no undo. Only 'yes' will be accepted to confirm.

  Enter a value: yes

juju_application.k8s_mysql: Destroying... [id=terra-k8s:mysql-k8s]
juju_application.k8s_mysql: Destruction complete after 0s

Destroy complete! Resources: 1 destroyed.
```
---

[note]
For more examples of Terraform modules for K8s, see the other directories in the [`terraform-modules` repository](https://github.com/canonical/terraform-modules/tree/main/modules/k8s).
[/note]

Feel free to [contact us](/t/11868) if you have any question and [collaborate with us on GitHub](https://github.com/canonical/terraform-modules)!