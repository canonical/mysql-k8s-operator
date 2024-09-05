# How to integrate DB with my charm

Please check [the supported interfaces](/t/10249) of the current charm first. You have options to use modern (preferred) or legacy interfaces. Make sure you are familiar with [Juju integration concepts](https://juju.is/docs/juju/integration).

The most existing charms currently use [ops-lib-mysql](https://github.com/canonical/ops-lib-mysql) interface (legacy). Canonical recommends for new charms to use [data-platform-libs](https://github.com/canonical/data-platform-libs) instead. You can take a look at [mysql-test-app](https://github.com/canonical/mysql-test-app) for more practical examples. Consider to [read the great manual about the charm development](https://juju.is/docs/sdk/integrate-your-charm-with-postgresql). The legacy charm details are well described [here](/t/11236).


FAQ:
* Q: Does the requirer need to set anything in relation data?<br/>A: it depends on the interface. Check the `mysql_client` [interface requirements](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/README.md).
* Q: Is there a charm library available, or does my charm need to compile the mysql relation data on its own?<br/>A: Yes, the library is available: [data-platform-libs](https://github.com/canonical/data-platform-libs).
* Q: How do I obtain the database url/uri?<br/>A: [it is planned](https://warthogs.atlassian.net/browse/DPE-2278), but currently missing. Meanwhile use [PostgreSQL as an example](https://charmhub.io/postgresql-k8s/docs/h-develop-mycharm).

Troubleshooting:
* Please start with [Juju troubleshooting guide](https://juju.is/docs/sdk/debug-a-charm).
* Check Charmed MySQL K8s [troubleshooting hints](/t/11886).

[Contact us](/t/11868) if you have any questions, issues and/or ideas!