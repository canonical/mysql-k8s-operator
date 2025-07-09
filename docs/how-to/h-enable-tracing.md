[note]
**Note**: All commands are written for `juju >= v3.1`

If you're using `juju 2.9`, check the [`juju 3.0` Release Notes](https://juju.is/docs/juju/roadmap#heading--juju-3-0-0---22-oct-2022).
[/note]

# Enable Tracing

This guide contains the steps to enable tracing with [Grafana Tempo](https://grafana.com/docs/tempo/latest/) for your MySQL K8s application. 

To summarize:
* [Deploy the Tempo charms and their dependencies in a COS K8s environment](#heading--deploy)
* [Offer interfaces for cross-model integrations](#heading--offer)
* [Consume and integrate cross-model integrations](#heading--consume)
* [View MySQL K8s traces on Grafana](#heading--view)


[note type="caution"]
**Warning:** This is feature is in development. It is **not recommended** for production environments. 

This feature is available for Charmed MySQL K8s revision 146+ only.
[/note]

## Prerequisites
Enabling tracing with Tempo requires that you:
- Have deployed a Charmed MySQL K8s application
  - See [How to manage units](https://discourse.charmhub.io/t/charmed-mysql-k8s-how-to-manage-units/9659)
- Have deployed a 'cos-lite' bundle in a Kubernetes environment
  - See [Getting started on MicroK8s](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s)

---

<a href="#heading--deploy"><h2 id="heading--deploy"> Deploy Tempo </h2></a>

First, switch to the Kubernetes controller where the COS model is deployed:

```shell
juju switch <k8s_controller_name>:<cos_model_name>
```

Then, deploy the dependencies of Tempo following [this tutorial](https://discourse.charmhub.io/t/tutorial-deploy-tempo-ha-on-top-of-cos-lite/15489). In particular, we would want to:
- Deploy the minio charm
- Deploy the s3 integrator charm
- Add a bucket in minio using a python script
- Configure s3 integrator with the minio credentials

Finally, deploy and integrate with Tempo HA in [a monolithic setup](https://discourse.charmhub.io/t/tutorial-deploy-tempo-ha-on-top-of-cos-lite/15489#heading--deploy-monolithic-setup). 


<a href="#heading--offer"><h2 id="heading--offer"> Offer interfaces </h2></a>

Next, offer interfaces for cross-model integrations from the model where Charmed MySQL is deployed.

To offer the Tempo integration, run

```shell
juju offer <tempo_coordinator_k8s_application_name>:tracing
```

Then, switch to the Charmed MySQL K8s model, find the offers, and integrate (relate) with them:

```shell
juju switch <k8s_controller_name>:<mysql_model_name>

juju find-offers <k8s_controller_name>:  
```
> :exclamation: Do not miss the "`:`" in the command above.

Below is a sample output where `k8s` is the K8s controller name and `cos` is the model where `cos-lite` and `tempo-k8s` are deployed:

```shell
Store  URL                            Access  Interfaces
k8s    admin/cos.tempo                admin   tracing:tracing
```

Next, consume this offer so that it is reachable from the current model:

```shell
juju consume k8s:admin/cos.tempo
```

<a href="#heading--consume"><h2 id="heading--consume"> Consume interfaces </h2></a>

First, deploy [Grafana Agent K8s](https://charmhub.io/grafana-agent-k8s) from the `1/stable` channel:

```shell
juju deploy grafana-agent-k8s --channel 1/stable
``` 

Then, integrate Grafana Agent K8s with the consumed interface from the previous section:

```shell
juju integrate grafana-agent-k8s:tracing tempo:tracing
```

Finally, integrate Charmed MySQL K8s with Grafana Agent K8s:

```shell
juju integrate mysql-k8s:tracing grafana-agent-k8s:tracing-provider
```

Wait until the model settles. The following is an example of the `juju status --relations` on the Charmed MySQL K8s model:

```shell
Model     Controller  Cloud/Region        Version  SLA          Timestamp
database  k8s         microk8s/localhost  3.5.4    unsupported  16:33:26Z

SAAS   Status  Store       URL
tempo  active  k8s         admin/cos.tempo

App                Version                  Status  Scale  Charm              Channel      Rev  Address         Exposed  Message
grafana-agent-k8s  0.40.4                   active      1  grafana-agent-k8s  1/stable     115  10.152.183.63   no       grafana-dashboards-provider: off, logging-consumer: off, send-remote-write: off
mysql-k8s          8.0.37-0ubuntu0.22.04.3  active      1  mysql-k8s                         0  10.152.183.135  no       Primary

Unit                  Workload  Agent      Address       Ports  Message
grafana-agent-k8s/0*  active    idle       10.1.241.255         grafana-dashboards-provider: off, logging-consumer: off, send-remote-write: off
mysql-k8s/0*          active    executing  10.1.241.253         Primary

Integration provider                Requirer                   Interface              Type     Message
grafana-agent-k8s:peers             grafana-agent-k8s:peers    grafana_agent_replica  peer     
grafana-agent-k8s:tracing-provider  mysql-k8s:tracing          tracing                regular  
mysql-k8s:database-peers            mysql-k8s:database-peers   mysql_peers            peer     
mysql-k8s:restart                   mysql-k8s:restart          rolling_op             peer     
mysql-k8s:upgrade                   mysql-k8s:upgrade          upgrade                peer     
tempo:tracing                       grafana-agent-k8s:tracing  tracing                regular  

```

[note]
**Note:** All traces are exported to Tempo using HTTP. Support for sending traces via HTTPS is an upcoming feature.
[/note]

<a href="#heading--view"><h2 id="heading--view"> View traces </h2></a>

After this is complete, the Tempo traces will be accessible from Grafana under the `Explore` section with `tempo-k8s` as the data source. You will be able to select `mysql-k8s` as the `Service Name` under the `Search` tab to view traces belonging to Charmed MySQL.

Below is a screenshot demonstrating a Charmed MySQL trace:

![Example MySQL K8s trace with Grafana Tempo|690x382](upload://g5fWq9uz5UM2XXQFTPdeLLSeQHA.jpeg)

Feel free to read through the [Tempo HA documentation](https://discourse.charmhub.io/t/charmed-tempo-ha/15531) at your leisure to explore its deployment and its integrations.