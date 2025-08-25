# Known troubleshooting scenarios

This page lists specific operational issues that we know about, and how to solve them.

[Contact us](/reference/contacts) or [contribute](/how-to/contribute) if there is a scenario you'd like to suggest, or add yourself.

## One offline unit and other units as secondaries

**Problem:** The primary unit went offline and primary reelection failed, rendered remaining units in RO mode.

**Solution:**

1. Restart `mysqld_safe` service on secondaries, i.e.:
    ```shell
    # for each secondarie unit `n`
    juju ssh --container mysql mysql-k8s/n pebble restart mysqld_safe
    ```
2.  Wait update-status hook to trigger recovery. For faster recovery, it's possible to speed up the update-status hook with:
    ```shell
    juju model-config update-status-hook-interval=30s -m mymodel
    # after recovery, set default interval of 5 minutes
    juju model-config update-status-hook-interval=5m -m mymodel
    ```

**Explanation:** When restarting secondaries, all MySQL instance will return as offline, which will trigger a cluster recovery.


## Two primaries, one in "split-brain" state

**Problem:** Original primary had a transitory network cut, and a new primary was elected. On returning, old primary enter split-brain state.

**Solution:**

1. Restart `mysqld_safe` service on secondaries, i.e.:
    ```shell
    # using `n` as the unit in split brain state
    juju ssh --container mysql mysql-k8s/n pebble restart mysqld_safe
    ```
2. Wait unit rejoin the cluster

**Explanation:** On restart, unit will reset it state and try to rejoin the cluster as a secondary.

