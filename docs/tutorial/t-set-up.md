# Environment Setup

This is part of the [Charmed MySQL K8s Tutorial](/t/9677). Please refer to this page for more information and the overview of the content.

## Minimum requirements
Before we start, make sure your machine meets [the following requirements](/t/11421).

## Multipass environment
[Multipass](https://multipass.run/) is a quick and easy way to launch virtual machines running Ubuntu. It uses "[cloud-init](https://cloud-init.io/)" standard to install and configure all the necessary parts automatically.

Let's install Multipass from [Snap](https://snapcraft.io/multipass) and launch a new VM using "[charm-dev](https://github.com/canonical/multipass-blueprints/blob/main/v1/charm-dev.yaml)" cloud-init config:
```shell
sudo snap install multipass && \
multipass launch --cpus 4 --memory 8G --disk 30G --name my-vm charm-dev
```
*Note: all 'multipass launch' params are [described here](https://multipass.run/docs/launch-command)*.

Multipass [list of commands](https://multipass.run/docs/multipass-cli-commands) is short and self-explanatory, e.g. show all running VMs:
```shell
multipass list
```

As soon as new VM started, enter inside using:
```shell
multipass shell my-vm
```
*Note: if at any point you'd like to leave Multipass VM, enter `Ctrl+d` or type `exit`*.

All the parts have been pre-installed inside VM already, like MicroK8s and Juju (the files '/var/log/cloud-init.log' and '/var/log/cloud-init-output.log' contain all low-level installation details). The Juju controller can work with different models; models host applications such as Charmed MySQL K8s. Set up a specific model for Charmed MySQL K8s named ‘tutorial’:
```shell
juju add-model tutorial
```

You can now view the model you created above by entering the command `juju status` into the command line. You should see the following:
```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
tutorial  overlord    microk8s/localhost  2.9.38   unsupported  22:30:11+01:00
Model "admin/tutorial" is empty.
```