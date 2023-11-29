# Charmed MySQL K8s tutorial

The Charmed MySQL K8s Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MySQL Community Edition](https://www.mysql.com/products/community/) relational database. It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/). As a first step this tutorial shows you how to get Charmed MySQL K8s up and running, but the tutorial does not stop there. Through this tutorial you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transport Layer Security (TLS). In this tutorial we will walk through how to:
- Set up an environment using [Multipass](https://multipass.run/) with [Microk8s](https://microk8s.io/) and [Juju](https://juju.is/).
- Deploy MySQL using a single command.
- Access the admin database directly.
- Add high availability with MySQL InnoDB Cluster, Group Replication.
- Request and change the admin password.
- Automatically create MySQL users via Juju relations.
- Reconfigure TLS certificate in one command.

While this tutorial intends to guide and teach you as you deploy Charmed MySQL K8s, it will be most beneficial if you already have a familiarity with:
- Basic terminal commands.
- MySQL concepts such as replication and users.

## Step-by-step guide

Here’s an overview of the steps required with links to our separate tutorials that deal with each individual step:
* [Set up the environment](/t/9679)
* [Deploy MySQL](/t/9667)
* [Managing your units](/t/9675)
* [Manage passwords](/t/9673)
* [Relate your MySQL to other applications](/t/9671)
* [Enable security](/t/9669)
* [Upgrade charm](/t/11754)
* [Cleanup your environment](/t/9665)