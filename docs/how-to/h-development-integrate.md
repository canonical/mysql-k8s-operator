# How to integrate a database with your charm

Charmed MySQL K8s can be integrated with any charmed application that supports its interfaces. This page provides some guidance and resources for charm developers to develop, integrate, and troubleshoot their charm so that it may connect with MySQL.

## Summary
* Check supported interfaces 
* Integrate your charm with MySQL
* Troubleshooting & testing
* FAQ

---

## Check supported interfaces

First, we recommend that you check [the supported interfaces](/t/10249) of the current charm. You have the option to use modern (preferred) or legacy interfaces. 

Most existing charms currently use [ops-lib-pgsql](https://github.com/canonical/ops-lib-pgsql) interface (legacy). 
> See also: [MySQL K8s legacy charm explanation](/t/11236)

 For new charms, **Canonical recommends using [data-platform-libs](https://github.com/canonical/data-platform-libs).**

## Integrate your charm with MySQL

> See also: 
> * [Juju documentation | Integration](https://juju.is/docs/juju/integration)
> * [Juju documentation | Integrate your charm with PostgreSQL](https://juju.is/docs/sdk/integrate-your-charm-with-postgresql)

Refer to [mysql-test-app](https://github.com/canonical/mysql-test-app) as a practical example of implementing data-platform-libs interfaces to integrate a charm with Charmed MySQL K8s.

## Troubleshooting and testing
* To learn the basics of charm debugging, start with [Juju | How to debug a charm](https://juju.is/docs/sdk/debug-a-charm)
* To troubleshoot Charmed MySQL, see the [Troubleshooting](/t/11886) page.
* To test the charm, check the [Testing](/t/11772) reference

## FAQ
**Does the requirer need to set anything in relation data?**
> It depends on the interface. Check the `mysql_client` [interface requirements](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/README.md).

**Is there a charm library available, or does my charm need to compile the mysql relation data on its own?**
> Yes, a library is available: [data-platform-libs](https://github.com/canonical/data-platform-libs).

**How do I obtain the database url/uri?**
>This feature is [planned](https://warthogs.atlassian.net/browse/DPE-2278) but currently missing.

[Contact us](/t/11868) if you have any questions, issues and/or ideas!