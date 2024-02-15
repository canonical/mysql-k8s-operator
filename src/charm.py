#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging
from socket import getfqdn
from typing import Optional

import ops
from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.mysql.v0.backups import MySQLBackups
from charms.mysql.v0.mysql import (
    BYTES_1MB,
    MySQLAddInstanceToClusterError,
    MySQLCharmBase,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLGetClusterPrimaryAddressError,
    MySQLGetMemberStateError,
    MySQLGetMySQLVersionError,
    MySQLInitializeJujuOperationsTableError,
    MySQLLockAcquisitionError,
    MySQLRebootFromCompleteOutageError,
    MySQLSetClusterPrimaryError,
)
from charms.mysql.v0.tls import MySQLTLS
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import EventBase, RelationBrokenEvent, RelationCreatedEvent
from ops.charm import RelationChangedEvent, UpdateStatusEvent
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Container,
    MaintenanceStatus,
    WaitingStatus,
)
from ops.pebble import Layer

from config import CharmConfig, MySQLConfig
from constants import (
    BACKUPS_PASSWORD_KEY,
    BACKUPS_USERNAME,
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    CONTAINER_NAME,
    COS_AGENT_RELATION_NAME,
    GR_MAX_MEMBERS,
    MONITORING_PASSWORD_KEY,
    MONITORING_USERNAME,
    MYSQL_LOG_FILES,
    MYSQL_SYSTEM_GROUP,
    MYSQL_SYSTEM_USER,
    MYSQLD_CONFIG_FILE,
    MYSQLD_EXPORTER_PORT,
    MYSQLD_EXPORTER_SERVICE,
    MYSQLD_SAFE_SERVICE,
    MYSQLD_SOCK_FILE,
    PASSWORD_LENGTH,
    PEER,
    ROOT_PASSWORD_KEY,
    S3_INTEGRATOR_RELATION_NAME,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)
from k8s_helpers import KubernetesHelpers
from log_rotate_manager import LogRotateManager
from mysql_k8s_helpers import (
    MySQL,
    MySQLCreateCustomConfigFileError,
    MySQLInitialiseMySQLDError,
)
from relations.mysql import MySQLRelation
from relations.mysql_provider import MySQLProvider
from relations.mysql_root import MySQLRootRelation
from rotate_mysql_logs import RotateMySQLLogs, RotateMySQLLogsCharmEvents
from upgrade import MySQLK8sUpgrade, get_mysql_k8s_dependencies_model
from utils import compare_dictionaries, generate_random_hash, generate_random_password

logger = logging.getLogger(__name__)


class MySQLOperatorCharm(MySQLCharmBase, TypedCharmBase[CharmConfig]):
    """Operator framework charm for MySQL."""

    config_type = CharmConfig
    # RotateMySQLLogsCharmEvents needs to be defined on the charm object for
    # the log rotate manager process (which runs juju-run/juju-exec to dispatch
    # a custom event)
    on = RotateMySQLLogsCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)

        # Lifecycle events
        self.framework.observe(self.on.mysql_pebble_ready, self._on_mysql_pebble_ready)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(
            self.on.database_storage_detaching, self._on_database_storage_detaching
        )

        self.framework.observe(self.on[PEER].relation_joined, self._on_peer_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)

        self.framework.observe(
            self.on[COS_AGENT_RELATION_NAME].relation_created, self._reconcile_mysqld_exporter
        )
        self.framework.observe(
            self.on[COS_AGENT_RELATION_NAME].relation_broken, self._reconcile_mysqld_exporter
        )

        self.mysql_config = MySQLConfig()
        self.k8s_helpers = KubernetesHelpers(self)
        self.mysql_relation = MySQLRelation(self)
        self.database_relation = MySQLProvider(self)
        self.mysql_root_relation = MySQLRootRelation(self)
        self.tls = MySQLTLS(self)
        self.s3_integrator = S3Requirer(self, S3_INTEGRATOR_RELATION_NAME)
        self.backups = MySQLBackups(self, self.s3_integrator)
        self.upgrade = MySQLK8sUpgrade(
            self,
            dependency_model=get_mysql_k8s_dependencies_model(),
            relation_name="upgrade",
            substrate="k8s",
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            refresh_event=self.on.start,
            jobs=[{"static_configs": [{"targets": [f"*:{MYSQLD_EXPORTER_PORT}"]}]}],
        )
        self.loki_push = LogProxyConsumer(
            self,
            log_files=MYSQL_LOG_FILES,
            relation_name="logging",
            container_name="mysql",
        )
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)

        self.log_rotate_manager = LogRotateManager(self)
        self.log_rotate_manager.start_log_rotate_manager()

        self.rotate_mysql_logs = RotateMySQLLogs(self)

    @property
    def _mysql(self) -> MySQL:
        """Returns an instance of the MySQL object from mysql_k8s_helpers."""
        return MySQL(
            self._get_unit_fqdn(),
            self.app_peer_data["cluster-name"],
            self.app_peer_data["cluster-set-domain-name"],
            self.get_secret("app", ROOT_PASSWORD_KEY),
            SERVER_CONFIG_USERNAME,
            self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),
            CLUSTER_ADMIN_USERNAME,
            self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY),
            MONITORING_USERNAME,
            self.get_secret("app", MONITORING_PASSWORD_KEY),
            BACKUPS_USERNAME,
            self.get_secret("app", BACKUPS_PASSWORD_KEY),
            self.unit.get_container(CONTAINER_NAME),
            self.k8s_helpers,
            self,
        )

    @property
    def _pebble_layer(self) -> Layer:
        """Return a layer for the mysqld pebble service."""
        layer = {
            "summary": "mysqld services layer",
            "description": "pebble config layer for mysqld safe and exporter",
            "services": {
                MYSQLD_SAFE_SERVICE: {
                    "override": "replace",
                    "summary": "mysqld safe",
                    "command": MYSQLD_SAFE_SERVICE,
                    "startup": "enabled",
                    "user": MYSQL_SYSTEM_USER,
                    "group": MYSQL_SYSTEM_GROUP,
                    "kill-delay": "24h",
                },
                MYSQLD_EXPORTER_SERVICE: {
                    "override": "replace",
                    "summary": "mysqld exporter",
                    "command": "/start-mysqld-exporter.sh",
                    "startup": "enabled" if self.has_cos_relation else "disabled",
                    "user": MYSQL_SYSTEM_USER,
                    "group": MYSQL_SYSTEM_GROUP,
                    "environment": {
                        "DATA_SOURCE_NAME": (
                            f"{MONITORING_USERNAME}:"
                            f"{self.get_secret('app', MONITORING_PASSWORD_KEY)}"
                            f"@unix({MYSQLD_SOCK_FILE})/"
                        ),
                    },
                },
            },
        }
        return Layer(layer)

    @property
    def active_status_message(self) -> str:
        """Active status message."""
        if self.unit_peer_data.get("member-role") == "primary":
            return "Primary"
        return ""

    @property
    def restart_peers(self) -> Optional[ops.model.Relation]:
        """Retrieve the peer relation."""
        return self.model.get_relation("restart")

    def get_unit_hostname(self, unit_name: Optional[str] = None) -> str:
        """Get the hostname.localdomain for a unit.

        Translate juju unit name to hostname.localdomain, necessary
        for correct name resolution under k8s.

        Args:
            unit_name: unit name
        Returns:
            A string representing the hostname.localdomain of the unit.
        """
        unit_name = unit_name or self.unit.name
        return f"{unit_name.replace('/', '-')}.{self.app.name}-endpoints"

    def _get_unit_fqdn(self, unit_name: Optional[str] = None) -> str:
        """Create a fqdn for a unit.

        Translate juju unit name to resolvable hostname.

        Args:
            unit_name: unit name
        Returns:
            A string representing the fqdn of the unit.
        """
        return getfqdn(self.get_unit_hostname(unit_name))

    def s3_integrator_relation_exists(self) -> bool:
        """Returns whether a relation with the s3-integrator exists."""
        return bool(self.model.get_relation(S3_INTEGRATOR_RELATION_NAME))

    def is_unit_busy(self) -> bool:
        """Returns whether the unit is busy."""
        return self._is_cluster_blocked()

    def _get_primary_from_online_peer(self) -> Optional[str]:
        """Get the primary address from an online peer."""
        for unit in self.peers.units:
            if self.peers.data[unit].get("member-state") == "online":
                try:
                    return self._mysql.get_cluster_primary_address(
                        connect_instance_address=self._get_unit_fqdn(unit.name),
                    )
                except MySQLGetClusterPrimaryAddressError:
                    # try next unit
                    continue

    def _is_unit_waiting_to_join_cluster(self) -> bool:
        """Return if the unit is waiting to join the cluster."""
        # alternatively, we could check if the instance is configured
        # and have an empty performance_schema.replication_group_members table
        return (
            self.unit.get_container(CONTAINER_NAME).can_connect()
            and self.unit_peer_data.get("member-state") == "waiting"
            and self._mysql.is_data_dir_initialised()
            and not self.unit_peer_data.get("unit-initialized")
        )

    def _join_unit_to_cluster(self) -> None:
        """Join the unit to the cluster.

        Try to join the unit from the primary unit.
        """
        instance_label = self.unit.name.replace("/", "-")
        instance_fqdn = self._get_unit_fqdn(self.unit.name)

        if self._mysql.is_instance_in_cluster(instance_label):
            logger.debug("instance already in cluster")
            return

        # Add new instance to the cluster
        try:
            cluster_primary = self._get_primary_from_online_peer()
            if not cluster_primary:
                self.unit.status = WaitingStatus("waiting to get cluster primary from peers")
                logger.debug("waiting: unable to retrieve the cluster primary from peers")
                return

            if self._mysql.get_cluster_node_count(from_instance=cluster_primary) == GR_MAX_MEMBERS:
                self.unit.status = WaitingStatus(
                    f"Cluster reached max size of {GR_MAX_MEMBERS} units. Standby."
                )
                logger.warning(
                    f"Cluster reached max size of {GR_MAX_MEMBERS} units. This unit will stay as standby."
                )
                return

            if self._mysql.are_locks_acquired(from_instance=cluster_primary):
                self.unit.status = WaitingStatus("waiting to join the cluster")
                logger.debug("waiting: cluster lock is held")
                return

            self.unit.status = MaintenanceStatus("joining the cluster")

            # Stop GR for cases where the instance was previously part of the cluster
            # harmless otherwise
            self._mysql.stop_group_replication()
            self._mysql.add_instance_to_cluster(
                instance_fqdn, instance_label, from_instance=cluster_primary
            )
            logger.debug(f"Added instance {instance_fqdn} to cluster")

            # Update 'units-added-to-cluster' counter in the peer relation databag
            self.unit_peer_data["unit-initialized"] = "True"
            self.unit_peer_data["member-state"] = "online"
            self.unit.status = ActiveStatus(self.active_status_message)
            logger.debug(f"Instance {instance_label} is cluster member")

        except MySQLAddInstanceToClusterError:
            logger.debug(f"Unable to add instance {instance_fqdn} to cluster.")
        except MySQLLockAcquisitionError:
            self.unit.status = WaitingStatus("waiting to join the cluster")
            logger.debug("waiting: failed to acquire lock when adding instance to cluster")

    def _reconcile_pebble_layer(self, container: Container) -> None:
        """Reconcile pebble layer."""
        current_layer = container.get_plan()
        new_layer = self._pebble_layer

        if new_layer.services != current_layer.services:
            logger.info("Adding pebble layer")

            container.add_layer(MYSQLD_SAFE_SERVICE, new_layer, combine=True)
            container.replan()
            self._mysql.wait_until_mysql_connection()

            if (
                not self.has_cos_relation
                and container.get_services(MYSQLD_EXPORTER_SERVICE)[
                    MYSQLD_EXPORTER_SERVICE
                ].is_running()
            ):
                container.stop(MYSQLD_EXPORTER_SERVICE)

            self._on_update_status(None)

    def _restart(self, event: EventBase) -> None:
        """Restart the service."""
        if self._mysql.is_unit_primary(self.unit_label):
            restart_states = {
                self.restart_peers.data[unit].get("state", "unset") for unit in self.peers.units
            }
            if restart_states != {"release"}:
                # Wait other units restart first to minimize primary switchover
                message = "Primary restart deferred after other units"
                logger.info(message)
                self.unit.status = WaitingStatus(message)
                event.defer()
                return
        self.unit.status = MaintenanceStatus("restarting MySQL")
        container = self.unit.get_container(CONTAINER_NAME)
        if container.can_connect():
            container.restart(MYSQLD_SAFE_SERVICE)

    # =========================================================================
    # Charm event handlers
    # =========================================================================

    def _reconcile_mysqld_exporter(
        self, event: RelationCreatedEvent | RelationBrokenEvent
    ) -> None:
        """Handle a COS relation created or broken event."""
        if not self.unit_peer_data.get("unit-initialized"):
            # wait unit initialization to avoid messing
            # with the pebble layer before the unit is initialized
            logger.debug("Defer reconcile mysqld exporter")
            event.defer()
            return

        self.current_event = event

        container = self.unit.get_container(CONTAINER_NAME)
        self._reconcile_pebble_layer(container)

    def _on_peer_relation_joined(self, _) -> None:
        """Handle the peer relation joined event."""
        # set some initial unit data
        self.unit_peer_data.setdefault("member-role", "unknown")
        self.unit_peer_data.setdefault("member-state", "waiting")

    def _on_config_changed(self, event: EventBase) -> None:
        """Handle the config changed event."""
        if not self._is_peer_data_set:
            # skip when not initialized
            return

        if not self.upgrade.idle:
            # skip when upgrade is in progress
            # the upgrade already restart the daemon
            return

        if not self._mysql.is_mysqld_running():
            # defer config-changed event until MySQL is running
            logger.debug("Deferring config-changed event until MySQL is running")
            event.defer()
            return

        config_content = self._mysql.read_file_content(MYSQLD_CONFIG_FILE)
        if not config_content:
            # empty config means not initialized, skipping
            return

        previous_config_dict = self.mysql_config.custom_config(config_content)

        # render the new config
        memory_limit_bytes = (self.config.profile_limit_memory or 0) * BYTES_1MB
        new_config_content, new_config_dict = self._mysql.render_mysqld_configuration(
            profile=self.config.profile,
            memory_limit=memory_limit_bytes,
        )

        changed_config = compare_dictionaries(previous_config_dict, new_config_dict)

        if self.mysql_config.keys_requires_restart(changed_config):
            # there are static configurations in changed keys
            logger.info("Configuration change requires restart")

            # persist config to file
            self._mysql.write_content_to_file(path=MYSQLD_CONFIG_FILE, content=new_config_content)
            self.on[f"{self.restart.name}"].acquire_lock.emit()
            return

        if dynamic_config := self.mysql_config.filter_static_keys(changed_config):
            # if only dynamic config changed, apply it
            logger.info("Configuration does not requires restart")
            for config in dynamic_config:
                self._mysql.set_dynamic_variable(config, new_config_dict[config])

    def _on_leader_elected(self, _) -> None:
        """Handle the leader elected event.

        Set config values in the peer relation databag if not already set.
        """
        # Set required passwords if not already set
        required_passwords = [
            ROOT_PASSWORD_KEY,
            SERVER_CONFIG_PASSWORD_KEY,
            CLUSTER_ADMIN_PASSWORD_KEY,
            MONITORING_PASSWORD_KEY,
            BACKUPS_PASSWORD_KEY,
        ]

        for required_password in required_passwords:
            if not self.get_secret("app", required_password):
                logger.debug(f"Setting {required_password}")
                self.set_secret(
                    "app", required_password, generate_random_password(PASSWORD_LENGTH)
                )

        # Create and set cluster and cluster-set names in the peer relation databag
        common_hash = generate_random_hash()
        self.app_peer_data.setdefault(
            "cluster-name", self.config.cluster_name or f"cluster-{common_hash}"
        )
        self.app_peer_data.setdefault("cluster-set-domain-name", f"cluster-set-{common_hash}")

    def _open_ports(self) -> None:
        """Open ports if supported.

        Used if `juju expose` ran on application
        """
        if ops.JujuVersion.from_environ().supports_open_port_on_k8s:
            try:
                self.unit.set_ports(3306, 33060)
            except ops.ModelError:
                logger.exception("failed to open port")

    def _configure_instance(self, container) -> bool:
        """Configure the instance for use in Group Replication."""
        try:
            # Run mysqld for the first time to
            # bootstrap the data directory and users
            logger.debug("Initializing instance")
            self._mysql.fix_data_dir(container)
            self._mysql.initialise_mysqld()

            # Add the pebble layer
            logger.debug("Adding pebble layer")
            container.add_layer(MYSQLD_SAFE_SERVICE, self._pebble_layer, combine=False)
            container.restart(MYSQLD_SAFE_SERVICE)

            logger.debug("Waiting for instance to be ready")
            self._mysql.wait_until_mysql_connection(check_port=False)

            logger.info("Configuring instance")
            # Configure all base users and revoke privileges from the root users
            self._mysql.configure_mysql_users()
            # Configure instance as a cluster node
            self._mysql.configure_instance()

            if self.has_cos_relation:
                if container.get_services(MYSQLD_EXPORTER_SERVICE)[
                    MYSQLD_EXPORTER_SERVICE
                ].is_running():
                    # Restart exporter service after configuration
                    container.restart(MYSQLD_EXPORTER_SERVICE)
                else:
                    container.start(MYSQLD_EXPORTER_SERVICE)
        except (
            MySQLConfigureInstanceError,
            MySQLConfigureMySQLUsersError,
            MySQLInitialiseMySQLDError,
            MySQLCreateCustomConfigFileError,
        ) as e:
            logger.debug("Unable to configure instance: {}".format(e))
            return False

        self._open_ports()

        try:
            # Set workload version
            if workload_version := self._mysql.get_mysql_version():
                self.unit.set_workload_version(workload_version)
        except MySQLGetMySQLVersionError:
            # Do not block the charm if the version cannot be retrieved
            pass

        return True

    def _mysql_pebble_ready_checks(self, event) -> bool:
        """Executes some checks to see if it is safe to execute the pebble ready handler."""
        if not self._is_peer_data_set:
            self.unit.status = WaitingStatus("Waiting for leader election.")
            logger.debug("Leader not ready yet, waiting...")
            return True

        container = event.workload
        if not container.can_connect():
            logger.debug("Pebble in container not ready, waiting...")
            return True

        return False

    def _on_mysql_pebble_ready(self, event) -> None:
        """Pebble ready handler.

        Define and start a pebble service and bootstrap instance.
        """
        if self._mysql_pebble_ready_checks(event):
            event.defer()
            return

        container = event.workload
        try:
            memory_limit_bytes = (self.config.profile_limit_memory or 0) * BYTES_1MB
            new_config_content, _ = self._mysql.render_mysqld_configuration(
                profile=self.config.profile,
                memory_limit=memory_limit_bytes,
            )
            self._mysql.write_content_to_file(path=MYSQLD_CONFIG_FILE, content=new_config_content)
        except MySQLCreateCustomConfigFileError:
            logger.exception("Unable to write custom config file")
            raise

        logger.info("Setting up the logrotate configurations")
        self._mysql.setup_logrotate_config()

        self.unit_peer_data["unit-status"] = "alive"
        if self._mysql.is_data_dir_initialised():
            # Data directory is already initialised, skip configuration
            logger.debug("Data directory is already initialised, skipping configuration")
            self._reconcile_pebble_layer(container)
            return

        self.unit.status = MaintenanceStatus("Initialising mysqld")

        # First run setup
        if not self._configure_instance(container):
            raise

        if not self.unit.is_leader():
            # Non-leader units should wait for leader to add them to the cluster
            self.unit.status = WaitingStatus("Waiting for instance to join the cluster")
            self.unit_peer_data.update({"member-role": "secondary", "member-state": "waiting"})

            self._join_unit_to_cluster()
            return

        try:
            # Create the cluster when is the leader unit
            logger.info("Creating cluster on the leader unit")
            self._mysql.create_cluster(self.unit_label)
            self._mysql.create_cluster_set()

            self._mysql.initialize_juju_units_operations_table()
            # Start control flag
            self.app_peer_data["units-added-to-cluster"] = "1"

            state, role = self._mysql.get_member_state()

            self.unit_peer_data.update(
                {"member-state": state, "member-role": role, "unit-initialized": "True"}
            )

            self.unit.status = ActiveStatus(self.active_status_message)
        except (
            MySQLCreateClusterError,
            MySQLGetMemberStateError,
            MySQLInitializeJujuOperationsTableError,
            MySQLCreateClusterError,
        ):
            logger.exception("Failed to initialize primary")
            raise

    def _handle_potential_cluster_crash_scenario(self) -> bool:
        """Handle potential full cluster crash scenarios.

        Returns:
            bool indicating whether the caller should return
        """
        if not self.cluster_initialized or not self.unit_peer_data.get("member-role"):
            # health checks are only after cluster and members are initialized
            return True

        if not self._mysql.is_mysqld_running():
            return True

        # retrieve and persist state for every unit
        try:
            state, role = self._mysql.get_member_state()
            self.unit_peer_data["member-state"] = state
            self.unit_peer_data["member-role"] = role
        except MySQLGetMemberStateError:
            logger.error("Error getting member state. Avoiding potential cluster crash recovery")
            self.unit.status = MaintenanceStatus("Unable to get member state")
            return True

        logger.info(f"Unit workload member-state is {state} with member-role {role}")

        # set unit status based on member-{state,role}
        self.unit.status = (
            ActiveStatus(self.active_status_message)
            if state == "online"
            else MaintenanceStatus(state)
        )

        if state == "recovering":
            return True

        if state in ["offline"]:
            # Group Replication is active but the member does not belong to any group
            all_states = {
                self.peers.data[unit].get("member-state", "unknown") for unit in self.peers.units
            }
            # Add state for this unit (self.peers.units does not include this unit)
            all_states.add("offline")

            if all_states == {"offline"} and self.unit.is_leader():
                # All instance are off, reboot cluster from outage from the leader unit

                logger.info("Attempting reboot from complete outage.")
                try:
                    self._mysql.reboot_from_complete_outage()
                except MySQLRebootFromCompleteOutageError:
                    logger.error("Failed to reboot cluster from complete outage.")
                    self.unit.status = BlockedStatus("failed to recover cluster.")

            return True

        return False

    def _is_cluster_blocked(self) -> bool:
        """Performs cluster state checks for the update-status handler.

        Returns: a boolean indicating whether the update-status (caller) should
            no-op and return.
        """
        unit_member_state = self.unit_peer_data.get("member-state")
        if unit_member_state in ["waiting", "restarting"]:
            # avoid changing status while tls is being set up or charm is being initialized
            logger.info(f"Unit state is {unit_member_state}")
            return True

        return False

    def _on_update_status(self, _: Optional[UpdateStatusEvent]) -> None:
        """Handle the update status event."""
        if not self.upgrade.idle:
            # avoid changing status while upgrade is in progress
            logger.debug("Application is upgrading. Skipping.")
            return
        if not self.unit.is_leader() and self._is_unit_waiting_to_join_cluster():
            # join cluster test takes precedence over blocked test
            # due to matching criteria
            self._join_unit_to_cluster()
            return

        if self._is_cluster_blocked():
            return
        del self.restart_peers.data[self.unit]["state"]

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        if self._handle_potential_cluster_crash_scenario():
            return

        if not self.unit.is_leader():
            return

        self._set_app_status()

    def _set_app_status(self) -> None:
        """Set the application status based on the cluster state."""
        nodes = self._mysql.get_cluster_node_count()
        if nodes > 0:
            self.app_peer_data["units-added-to-cluster"] = str(nodes)

        try:
            primary_address = self._mysql.get_cluster_primary_address()
        except MySQLGetClusterPrimaryAddressError:
            return

        if not primary_address:
            return

        # Set active status when primary is known
        self.app.status = ActiveStatus()

    def _on_peer_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the relation changed event."""
        # This handler is only taking care of setting
        # active status for secondary units
        if not self._is_peer_data_set:
            # Avoid running too early
            event.defer()
            return

        if self._is_unit_waiting_to_join_cluster():
            self._join_unit_to_cluster()

    def _on_database_storage_detaching(self, _) -> None:
        """Handle the database storage detaching event."""
        # Only executes if the unit was initialised
        if not self.unit_peer_data.get("unit-initialized"):
            return

        # No need to remove the instance from the cluster if it is not a member of the cluster
        if not self._mysql.is_instance_in_cluster(self.unit_label):
            return

        if (
            self._mysql.get_primary_label() == self.unit_label
            and self.unit.name.split("/")[1] != "0"
        ):
            # Preemptively switch primary to unit 0
            logger.info("Switching primary to unit 0")
            try:
                self._mysql.set_cluster_primary(
                    new_primary_address=self._get_unit_fqdn(f"{self.app.name}/0")
                )
            except MySQLSetClusterPrimaryError:
                logger.warning("Failed to switch primary to unit 0")

        # The following operation uses locks to ensure that only one instance is removed
        # from the cluster at a time (to avoid split-brain or lack of majority issues)
        self._mysql.remove_instance(self.unit_label)

        # Inform other hooks of current status
        self.unit_peer_data["unit-status"] = "removing"


if __name__ == "__main__":
    main(MySQLOperatorCharm)
