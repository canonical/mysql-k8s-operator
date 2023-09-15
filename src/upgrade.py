# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dependency model for MySQL."""

import json
import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    KubernetesClientError,
)
from charms.mysql.v0.mysql import (
    MySQLGetMySQLVersionError,
    MySQLServerNotUpgradableError,
    MySQLSetClusterPrimaryError,
    MySQLSetVariableError,
)
from ops import JujuVersion
from ops.model import BlockedStatus, MaintenanceStatus, RelationDataContent
from pydantic import BaseModel
from tenacity import RetryError, Retrying
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed
from typing_extensions import override

import k8s_helpers

if TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)


RECOVER_ATTEMPTS = 10


class MySQLK8sDependenciesModel(BaseModel):
    """MySQL dependencies model."""

    charm: DependencyModel
    rock: DependencyModel


def get_mysql_k8s_dependencies_model() -> MySQLK8sDependenciesModel:
    """Return the MySQL dependencies model."""
    with open("src/dependency.json") as dependency_file:
        _deps = json.load(dependency_file)
    return MySQLK8sDependenciesModel(**_deps)


class MySQLK8sUpgrade(DataUpgrade):
    """MySQL upgrade class."""

    def __init__(self, charm: "MySQLOperatorCharm", **kwargs) -> None:
        """Initialize the class."""
        super().__init__(charm, **kwargs)
        self.charm = charm

        self.framework.observe(getattr(self.charm.on, "mysql_pebble_ready"), self._on_pebble_ready)
        self.framework.observe(self.charm.on.stop, self._on_stop)
        self.framework.observe(
            self.charm.on[self.relation_name].relation_changed, self._on_upgrade_changed
        )

    @property
    def highest_ordinal(self) -> int:
        """Return the max ordinal."""
        return self.charm.app.planned_units() - 1

    @property
    def unit_upgrade_data(self) -> RelationDataContent:
        """Return the application upgrade data."""
        return self.peer_relation.data[self.charm.unit]

    @override
    def pre_upgrade_check(self) -> None:
        """Run pre-upgrade checks."""
        fail_message = "Pre-upgrade check failed. Cannot upgrade."

        def _count_online_instances(status_dict: dict) -> int:
            """Return the number of online instances from status dict."""
            return [
                item["status"]
                for item in status_dict["defaultreplicaset"]["topology"].values()
                if not item.get("instanceerrors", [])
            ].count("online")

        if cluster_status := self.charm._mysql.get_cluster_status(extended=True):
            if _count_online_instances(cluster_status) < self.charm.app.planned_units():
                # case any not fully online unit is found
                raise ClusterNotReadyError(
                    message=fail_message,
                    cause="Not all units are online",
                    resolution="Ensure all units are online in the cluster",
                )
        else:
            # case cluster status is not available
            # it may be due to the refresh being ran before
            # the pre-upgrade-check action
            raise ClusterNotReadyError(
                message=fail_message,
                cause="Failed to retrieve cluster status",
                resolution="Ensure that mysqld is running for this unit",
            )

        try:
            self._pre_upgrade_prepare()
        except MySQLSetClusterPrimaryError:
            raise ClusterNotReadyError(
                message=fail_message,
                cause="Failed to set primary",
                resolution="Check the cluster status",
            )
        except k8s_helpers.KubernetesClientError:
            raise ClusterNotReadyError(
                message=fail_message,
                cause="Failed to patch statefulset",
                resolution="Check kubernetes access policy",
            )
        except MySQLSetVariableError:
            raise ClusterNotReadyError(
                message=fail_message,
                cause="Failed to set slow shutdown",
                resolution="Check the cluster status",
            )

    @override
    def log_rollback_instructions(self) -> None:
        """Log rollback instructions."""
        juju_version = JujuVersion.from_environ()
        run_action = "run" if juju_version.major > 2 else "run-action"
        logger.critical(
            "\n".join(
                (
                    "Upgrade failed, follow the instructions below to rollback:",
                    f"  1 - Run `juju {run_action} {self.charm.app.name}/leader pre-upgrade-check` to configure rollback",
                    f"  2 - Run `juju refresh --revision <previous-revision> {self.charm.app.name}` to initiate the rollback",
                    f"  3 - Run `juju {run_action} {self.charm.app.name}/leader resume-upgrade` to resume the rollback",
                )
            )
        )

    def _pre_upgrade_prepare(self) -> None:
        """Pre upgrade routine for MySQL.

        Set primary to the first unit to avoid switchover during upgrade,
        patch statefulset `spec.updateStrategy.rollingUpdate.partition` to the last unit
        and set slow shutdown to all instances.
        """
        if self.charm._mysql.get_primary_label() != f"{self.charm.app.name}-0":
            # set the primary to the first unit for switchover mitigation
            new_primary = self.charm._get_unit_fqdn(f"{self.charm.app.name}/0")
            self.charm._mysql.set_cluster_primary(new_primary)

        # set slow shutdown on all instances
        for unit in self.app_units:
            unit_address = self.charm._get_unit_fqdn(unit.name)
            self.charm._mysql.set_dynamic_variable(
                variable="innodb_fast_shutdown", value="0", instance_address=unit_address
            )

        self.charm.k8s_helpers.set_rolling_update_partition(partition=self.highest_ordinal)

    def _on_stop(self, _) -> None:
        """Handle stop event.

        If upgrade is in progress, set unit status.
        """
        try:
            if self.charm.unit_peer_data["unit-status"] == "removing":
                # unit is being removed, noop
                return
        except KeyError:
            # databag gone
            return
        if self.upgrade_stack:
            # upgrade stack set, pre-upgrade-check ran
            self.charm.unit.status = MaintenanceStatus("upgrading unit")

    def _on_upgrade_changed(self, _) -> None:
        """Handle the upgrade changed event.

        Run update status for every unit when the upgrade is completed.
        """
        if not self.upgrade_stack and self.idle:
            self.charm._on_update_status(None)

    def _on_pebble_ready(self, event) -> None:
        """Handle pebble ready event.

        Confirm that unit is healthy and set unit completed.
        """
        if not self.peer_relation:
            logger.debug("Peer relation not yet ready on unit. Deferring event")
            event.defer()
            return

        if self.state not in ["upgrading", "recovery"]:
            return

        try:
            self.charm.unit.set_workload_version(self.charm._mysql.get_mysql_version() or "unset")
        except MySQLGetMySQLVersionError:
            # don't fail on this, just log it
            logger.warning("Failed to get MySQL version")
        try:
            failure_message = "unknown error"
            self._check_server_upgradeability()
            self.charm.unit.status = MaintenanceStatus("recovering unit after upgrade")
            for attempt in Retrying(
                stop=stop_after_attempt(RECOVER_ATTEMPTS), wait=wait_fixed(10)
            ):
                with attempt:
                    self.charm._mysql.hold_if_recovering()
                    if not self.charm._mysql.is_instance_in_cluster(self.charm.unit_label):
                        logger.debug(
                            "Instance not yet back in the cluster."
                            f" Retry {attempt.retry_state.attempt_number}/{RECOVER_ATTEMPTS}"
                        )
                        raise Exception
                    self._complete_upgrade()
                    return
        except MySQLServerNotUpgradableError:
            failure_message = "Incompatible mysql server upgrade"
        except RetryError:
            failure_message = "Unit failed to rejoin the cluster after upgrade"
        logger.error(failure_message)
        self.set_unit_failed()
        self.charm.unit.status = BlockedStatus(
            "upgrade failed. Check logs for rollback instruction"
        )

    def _complete_upgrade(self):
        # complete upgrade for the unit
        logger.debug("Upgraded unit is healthy. Set upgrade state to `completed`")
        self.set_unit_completed()
        if self.charm.unit_label == f"{self.charm.app.name}/1":
            # penultimate unit, reset the primary for faster switchover
            try:
                self.charm._mysql.set_cluster_primary(
                    self.charm._get_unit_fqdn(self.charm.unit.name)
                )
            except MySQLSetClusterPrimaryError:
                logger.debug("Failed to set primary")

    @override
    def _set_rolling_update_partition(self, partition: int) -> None:
        """Set rolling update partition."""
        try:
            self.charm.k8s_helpers.set_rolling_update_partition(partition=partition)
        except k8s_helpers.KubernetesClientError:
            raise KubernetesClientError(
                message="Cannot set rolling update partition",
                cause="Error setting rolling update partition",
                resolution="Check kubernetes access policy",
            )

    def _check_server_upgradeability(self) -> None:
        """Check if the server can be upgraded.

        Use mysql-shell upgrade checker utility to ensure server upgradeability.

        Raises:
            VersionError: If the server is not upgradeable.
        """
        if len(self.upgrade_stack or []) < self.charm.app.planned_units():
            # check is done for 1st upgrading unit
            return
        instance = self.charm._get_unit_fqdn(f"{self.charm.app.name}/0")
        self.charm._mysql.verify_server_upgradable(instance=instance)
        logger.debug("MySQL server is upgradeable")
