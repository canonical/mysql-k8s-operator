> [Charmed MySQL K8s Tutorial](/t/9677) > 1. Set up your environment

# Set up your environment

In this first step, you will set up a development environment with the required components for deploying Charmed MySQL K8s.

[note]
Before you start, make sure your machine meets the [minimum system requirements](/t/11421).
[/note]

## Summary
* [Set up Multipass](#set-up-multipass)
* [Set up Juju](#set-up-juju)

---

## Set up Multipass
[Multipass](https://multipass.run/) is a quick and easy way to launch virtual machines running Ubuntu. It uses the [cloud-init](https://cloud-init.io/) standard to install and configure all the necessary parts automatically.

Install Multipass from the [snap store](https://snapcraft.io/multipass):
```shell
sudo snap install multipass
```

Launch a new VM using the [`charm-dev`](https://github.com/canonical/multipass-blueprints/blob/main/v1/charm-dev.yaml) cloud-init config:
```shell
multipass launch --cpus 4 --memory 8G --disk 30G --name my-vm charm-dev
```

> All `multipass launch` params are described in the [Multipass documentation](https://multipass.run/docs/launch-command).

The list of [Multipass commands](https://multipass.run/docs/multipass-cli-commands) is short and self-explanatory. For example, to show all running VMs, just run `multipass list`.

As soon as new VM has started, access it with the following command:
```shell
multipass shell my-vm
```
> If at any point you'd like to leave Multipass VM, enter `Ctrl+D` or type `exit`.

All necessary components have been pre-installed inside VM already, like MicroK8s and Juju. The files `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` contain all low-level installation details. 

## Set up Juju

Let's bootstrap Juju to use the local MicroK8s controller. We will call it "overlord", but you can give it any name you'd like.
```shell
juju bootstrap microk8s overlord
```

The controller can work with different [Juju models](https://juju.is/docs/juju/model). Set up a specific model for Charmed MySQL named ‘tutorial’:
```shell
juju add-model tutorial
```

You can now view the model you created above by entering the command `juju status` into the command line. You should see something similar to the following output:

```none
Model    Controller  Cloud/Region         Version  SLA          Timestamp
tutorial overlord    microk8s/localhost   3.1.6    unsupported  23:20:53+01:00

Model "admin/tutorial" is empty.
```

>Next step: [2. Deploy MySQL](/t/9667)