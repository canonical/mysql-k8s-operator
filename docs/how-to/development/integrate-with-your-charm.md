# How to integrate a database with your charm

Charmed MySQL K8s can be integrated with any charmed application that supports its interfaces. This page provides some guidance and resources for charm developers to develop, integrate, and troubleshoot their charm so that it may connect with MySQL.

## Check supported interfaces

First, we recommend that you check [the supported interfaces](/explanation/interfaces-and-endpoints) of the current charm. You have the option to use modern (preferred) or legacy interfaces. 

Most existing charms currently use [ops-lib-pgsql](https://github.com/canonical/ops-lib-pgsql) interface (legacy).

For new charms, **Canonical recommends using [data-platform-libs](https://github.com/canonical/data-platform-libs).**

```{seealso}
[MySQL K8s legacy charm explanation](/explanation/legacy-charm)
```

## Integrate your charm with MySQL

Refer to [mysql-test-app](https://github.com/canonical/mysql-test-app) as a practical example of implementing data-platform-libs interfaces to integrate a charm with Charmed MySQL K8s.

```{seealso}
[Juju documentation > Integration](https://documentation.ubuntu.com/juju/3.6/reference/relation/)
```

## Troubleshooting and testing

* To learn the basics of charm debugging, start with [Juju > How to debug a charm](https://juju.is/docs/sdk/debug-a-charm)
* To troubleshoot Charmed MySQL, see the [Troubleshooting](/reference/troubleshooting/index) page.
* To test the charm, check the [Testing](/reference/software-testing) reference

## FAQ

> *Does the requirer need to set anything in relation data?*

It depends on the interface. Check the `mysql_client` [interface requirements](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/README.md).

> *Is there a charm library available, or does my charm need to compile the mysql relation data on its own?*

Yes, a library is available: [data-platform-libs](https://github.com/canonical/data-platform-libs).

> *How do I obtain the database URL/URI?*

This feature is [planned](https://warthogs.atlassian.net/browse/DPE-2278) but currently missing.

[Contact us](/reference/contacts) if you have any questions, issues and/or ideas!
