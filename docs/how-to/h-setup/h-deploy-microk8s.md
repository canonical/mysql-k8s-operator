# Deploy Charmed MySQL K8s

Please follow the [Tutorial](/t/9677) to deploy the charm on MicroK8s.

Short story for your Ubuntu 22.04 LTS:
```shell
sudo snap install multipass
multipass launch --cpus 4 --memory 8G --disk 30G --name my-vm charm-dev # tune CPU/RAM/HDD accordingly to your needs
multipass shell my-vm

juju add-model mysql
juju deploy mysql-k8s --channel 8.0/stable --trust # --config profile=testing
juju status --watch 1s
```

The expected result:
```shell
Model   Controller  Cloud/Region        Version  SLA          Timestamp
mysql   overlord    microk8s/localhost  2.9.38   unsupported  22:48:57+01:00

App        Version    Status  Scale  Charm      Channel     Rev  Address         Exposed  Message
mysql-k8s  8.0.31     active      3  mysql-k8s  8.0/stable  75   10.152.183.234  no       

Unit          Workload  Agent  Address      Ports  Message
mysql-k8s/0*  active    idle   10.1.84.74          Primary
mysql-k8s/1   active    idle   10.1.84.127
mysql-k8s/2   active    idle   10.1.84.73
```

Check the [Testing](/t/11772) reference to test your deployment.