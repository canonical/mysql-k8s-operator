# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Dependency model for MySQL."""

import json
import logging
from socket import getfqdn
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    KubernetesClientError,
)
from charms.mysql.v0.mysql import (
    MySQLGetMySQLVersionError,
    MySQLPluginInstallError,
    MySQLRebootFromCompleteOutageError,
    MySQLRescanClusterError,
    MySQLServerNotUpgradableError,
    MySQLServiceNotRunningError,
    MySQLSetClusterPrimaryError,
    MySQLSetVariableError,
)
from ops import Container, JujuVersion
from ops.model import BlockedStatus, MaintenanceStatus, RelationDataContent
from ops.pebble import ChangeError
from pydantic import BaseModel
from tenacity import RetryError, Retrying
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed
from typing_extensions import override

import k8s_helpers
from constants import CONTAINER_NAME, MYSQLD_SERVICE

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

        try:
            # ensure cluster node addresses are consistent in cluster metadata
            # https://github.com/canonical/mysql-k8s-operator/issues/327
            self.charm._mysql.rescan_cluster()
        except MySQLRescanClusterError:
            raise ClusterNotReadyError(
                message=fail_message,
                cause="Failed to rescan cluster",
                resolution="Check the cluster status",
            )

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
        if juju_version.major > 2:
            run_action = "run"
            wait = ""
        else:
            run_action = "run-action"
            wait = " --wait"
        logger.critical(
            "\n".join((
                "Upgrade failed, follow the instructions below to rollback:",
                f"  1 - Run `juju {run_action} {self.charm.app.name}/leader pre-upgrade-check{wait}` to configure rollback",
                f"  2 - Run `juju refresh --revision <previous-revision> {self.charm.app.name}` to initiate the rollback",
                f"  3 - Run `juju {run_action} {self.charm.app.name}/leader resume-upgrade{wait}` to resume the rollback",
            ))
        )

    def _pre_upgrade_prepare(self) -> None:
        """Pre upgrade routine for MySQL.

        Set primary to the first unit to avoid switchover during upgrade,
        patch statefulset `spec.updateStrategy.rollingUpdate.partition` to the last unit
        and set slow shutdown to all instances.
        """
        if self.charm._mysql.get_primary_label() != f"{self.charm.app.name}-0":
            # set the primary to the first unit for switchover mitigation
            new_primary = getfqdn(self.charm.get_unit_hostname(f"{self.charm.app.name}/0"))
            self.charm._mysql.set_cluster_primary(new_primary)

        # set slow shutdown on all instances
        for unit in self.app_units:
            unit_address = self.charm.get_unit_address(unit)
            self.charm._mysql.set_dynamic_variable(
                variable="innodb_fast_shutdown", value="0", instance_address=unit_address
            )

        self.charm.k8s_helpers.set_rolling_update_partition(partition=self.highest_ordinal)

    def _on_stop(self, _) -> None:
        """Handle stop event.

        If upgrade is in progress, set unit status.
        """
        if self.charm.removing_unit:
            # unit is being removed, noop
            return
        if self.upgrade_stack:
            # upgrade stack set, pre-upgrade-check ran
            self.charm.unit.status = MaintenanceStatus("upgrading unit")

    def _on_upgrade_changed(self, _) -> None:
        """Handle the upgrade changed event.

        Run update status for every unit when the upgrade is completed.
        """
        if not self.charm.unit.get_container(CONTAINER_NAME).can_connect():
            return
        if not self.upgrade_stack and self.idle and self.charm.unit_initialized:
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

        container = event.workload
        self.charm._write_mysqld_configuration()

        logger.info("Setting up the logrotate configurations")
        self.charm._mysql.setup_logrotate_config()

        try:
            self.charm._reconcile_pebble_layer(container)
            self._check_server_upgradeability()
            self.charm.unit.status = MaintenanceStatus("recovering unit after upgrade")
            if self.charm.app.planned_units() > 1:
                self._recover_multi_unit_cluster()
            else:
                self._recover_single_unit_cluster()
            if self.charm.config.plugin_audit_enabled:
                self.charm._mysql.install_plugins(["audit_log", "audit_log_filter"])
            self._complete_upgrade()
        except MySQLRebootFromCompleteOutageError:
            logger.error("Failed to reboot single unit from outage after upgrade")
            self.set_unit_failed()
            self.charm.unit.status = BlockedStatus(
                "upgrade failed. Check logs for rollback instruction"
            )
        except MySQLPluginInstallError:
            logger.error("Failed to install audit plugin")
            self.set_unit_failed()
            self.charm.unit.status = BlockedStatus(
                "upgrade failed. Check logs for rollback instruction"
            )
        except (
            RetryError,
            MySQLServerNotUpgradableError,
            MySQLServiceNotRunningError,
            ChangeError,
        ):
            # Failed to recover unit
            if (
                not self._check_server_unsupported_downgrade()
                or self.charm.app.planned_units() == 1
            ):
                # don't try to recover single unit cluster or errors other then downgrade
                logger.error("Unit failed to rejoin the cluster after upgrade")
                self.set_unit_failed()
                return
            logger.warning("Downgrade is incompatible. Resetting workload")
            self._reset_on_unsupported_downgrade(container)
            self._complete_upgrade()

    def _recover_multi_unit_cluster(self) -> None:
        logger.info("Recovering unit")
        try:
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
        except RetryError:
            raise

    def _recover_single_unit_cluster(self) -> None:
        """Recover single unit cluster."""
        logger.debug("Recovering single unit cluster")
        self.charm._mysql.reboot_from_complete_outage()

    def _complete_upgrade(self):
        # complete upgrade for the unit
        logger.debug("Upgraded unit is healthy. Set upgrade state to `completed`")
        try:
            self.charm.unit.set_workload_version(self.charm._mysql.get_mysql_version() or "unset")
        except MySQLGetMySQLVersionError:
            # don't fail on this, just log it
            logger.warning("Failed to get MySQL version")
        self.set_unit_completed()
        if self.charm.unit_label == f"{self.charm.app.name}/1":
            # penultimate unit, reset the primary for faster switchover
            try:
                self.charm._mysql.set_cluster_primary(self.charm.get_unit_address(self.charm.unit))
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
        instance = getfqdn(self.charm.get_unit_hostname(f"{self.charm.app.name}/0"))
        self.charm._mysql.verify_server_upgradable(instance=instance)
        logger.info("Check MySQL server upgradeability passed")

    def _check_server_unsupported_downgrade(self) -> bool:
        """Check error log for unsupported downgrade.

        https://dev.mysql.com/doc/mysql-errors/8.0/en/server-error-reference.html
        """
        if log_content := self.charm._mysql.fetch_error_log():
            return "MY-013171" in log_content

        return False

    def _reset_on_unsupported_downgrade(self, container: Container) -> None:
        """Reset the cluster on unsupported downgrade."""
        container.stop(MYSQLD_SERVICE)
        self.charm._mysql.reset_data_dir()
        self.charm._write_mysqld_configuration()
        self.charm._configure_instance(container)
        # reset flags
        self.charm.unit_peer_data.update({"member-role": "secondary", "member-state": "waiting"})
        # rescan is needed to remove the instance old incarnation from the cluster
        leader = self.charm._get_primary_from_online_peer()
        self.charm._mysql.rescan_cluster(from_instance=leader, remove_instances=True)
        # rejoin after
        self.charm.join_unit_to_cluster()
