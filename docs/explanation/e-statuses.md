# Charm Statuses

> :warning: **WARNING** : it is an work-in-progress article. Do NOT use it in production! Contact [Canonical Data Platform team](https://chat.charmhub.io/charmhub/channels/data-platform) if you are interested in the topic.

The charm follows [standard Juju applications statuses](https://juju.is/docs/olm/status-values#heading--application-status). Here you can find the expected end-users reaction on different statuses:

| Juju Status | Message | Expectations | Actions |
|-------|-------|-------|-------|
| **active** | any | Normal charm operations | No actions required |
| **waiting** | any | Charm is waiting for relations to be finished | No actions required |
| **maintenance** | any | Charm is performing the internal maintenance (e.g. cluster re-configuration) | No actions required |
| **blocked** | any | The manual user activity is required! | Follow the message hints (see below) |
| **blocked** | Failed to set up relation | The relation between two applications failed to be created. Most probably it is a regression of the recent changes in applications | Check Juju [debug-log](https://juju.is/docs/olm/juju-debug-log). Increase debug level and reproduce the issue. Report as an issue with debug logs attached (if reproducible). Consider to try previous revision for both applications |
| **blocked** | Failed to initialize mysql relation | The same as "Failed to set up relation" | See "Failed to set up relation" |
| **blocked** | Failed to remove relation user | TODO: clean manually? How to unblock? | |
| **blocked** | Failed to install and configure MySQL | TODO |  |
| **blocked** | Failed to initialize MySQL users | TODO | |
| **blocked** | Failed to configure instance for InnoDB | TODO | |
| **blocked** | Failed to create custom mysqld config | TODO | |
| **blocked** | Failed to connect to MySQL exporter | TODO | |
| **blocked** | Failed to create the InnoDB cluster | TODO | |
| **blocked** | Failed to initialize juju units operations table | TODO | |
| **blocked** | failed to recover cluster. | TODO | |
| **blocked** | Failed to remove relation user | TODO | |
| **blocked** | Failed to initialize shared_db relation | Try to remove and add relations. Report as an issue (with debug logs) if reproducible | |
| **blocked** | Failed to create app user or scoped database | TODO | |
| **blocked** | Failed to delete users for departing unit | TODO | |
| **blocked** | Failed to set TLS configuration | Problems with TLS certifications generation| Remove and add relations with TLS operator. Report as an issue (with debug logs) if reproducible |
| **blocked** | Failed to restore default TLS configuration | TODO | |
| **blocked** | Failed to create backup; instance in bad state | TODO | |
| **blocked** | Failed to re-initialize MySQL data-dir | TODO | |
| **blocked** | Failed to re-initialize MySQL users | TODO | |
| **blocked** | Failed to re-configure instance for InnoDB | TODO | |
| **blocked** | Failed to purge data dir | TODO | |
| **blocked** | Failed to reset root password | TODO | |
| **blocked** | Failed to create custom mysqld config | TODO | |
| **error** | any | An unhanded internal error happened | Read the message hint. Execute `juju resolve <error_unit/0>` after addressing the root of the error state |
| **terminated** | any | The unit is gone and will be cleaned by Juju soon | No actions possible |
| **unknown** | any | Juju doesn't know the charm app/unit status. Possible reason: K8s charm termination in progress. | Manual investigation required if status is permanent |