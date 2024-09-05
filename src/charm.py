#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging
import random
from socket import getfqdn
from time import sleep
from typing import Optional

import ops
from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.mysql.v0.async_replication import (
    MySQLAsyncReplicationConsumer,
    MySQLAsyncReplicationOffer,
)
from charms.mysql.v0.backups import S3_INTEGRATOR_RELATION_NAME, MySQLBackups
from charms.mysql.v0.mysql import (
    BYTES_1MB,
    MySQLAddInstanceToClusterError,
    MySQLCharmBase,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLGetClusterPrimaryAddressError,
    MySQLGetMySQLVersionError,
    MySQLInitializeJujuOperationsTableError,
    MySQLLockAcquisitionError,
    MySQLNoMemberStateError,
    MySQLRebootFromCompleteOutageError,
    MySQLServiceNotRunningError,
    MySQLSetClusterPrimaryError,
    MySQLUnableToGetMemberStateError,
)
from charms.mysql.v0.tls import MySQLTLS
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from charms.tempo_k8s.v1.charm_tracing import trace_charm
from charms.tempo_k8s.v2.tracing import TracingEndpointRequirer
from ops import EventBase, RelationBrokenEvent, RelationCreatedEvent
from ops.charm import RelationChangedEvent, UpdateStatusEvent
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Container,
    MaintenanceStatus,
    Unit,
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
    PASSWORD_LENGTH,
    PEER,
    ROOT_PASSWORD_KEY,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
    TRACING_PROTOCOL,
    TRACING_RELATION_NAME,
)
from k8s_helpers import KubernetesHelpers
from log_rotate_manager import LogRotateManager
from mysql_k8s_helpers import MySQL, MySQLInitialiseMySQLDError
from relations.mysql import MySQLRelation
from relations.mysql_provider import MySQLProvider
from relations.mysql_root import MySQLRootRelation
from rotate_mysql_logs import RotateMySQLLogs, RotateMySQLLogsCharmEvents
from upgrade import MySQLK8sUpgrade, get_mysql_k8s_dependencies_model
from utils import compare_dictionaries, generate_random_password

logger = logging.getLogger(__name__)


@trace_charm(
    tracing_endpoint="tracing_endpoint",
    extra_types=(
        GrafanaDashboardProvider,
        KubernetesHelpers,
        LogProxyConsumer,
        LogRotateManager,
        MetricsEndpointProvider,
        MySQL,
        MySQLAsyncReplicationConsumer,
        MySQLAsyncReplicationOffer,
        MySQLBackups,
        MySQLConfig,
        MySQLK8sUpgrade,
        MySQLProvider,
        MySQLRelation,
        MySQLRootRelation,
        MySQLTLS,
        RollingOpsManager,
        RotateMySQLLogs,
        S3Requirer,
    ),
)
class MySQLOperatorCharm(MySQLCharmBase, TypedCharmBase[CharmConfig]):
    """Operator framework charm for MySQL."""

    config_type = CharmConfig
    # RotateMySQLLogsCharmEvents needs to be defined on the charm object for
    # the log rotate manager process (which runs juju-run/juju-exec to dispatch
    # a custom event)
    on = RotateMySQLLogsCharmEvents()  # type: ignore

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
        self.replication_offer = MySQLAsyncReplicationOffer(self)
        self.replication_consumer = MySQLAsyncReplicationConsumer(self)

        self.tracing = TracingEndpointRequirer(
            self, protocols=[TRACING_PROTOCOL], relation_name=TRACING_RELATION_NAME
        )

    @property
    def tracing_endpoint(self) -> Optional[str]:
        """Otlp http endpoint for charm instrumentation."""
        if self.tracing.is_ready():
            return self.tracing.get_endpoint(TRACING_PROTOCOL)

    @property
    def _mysql(self) -> MySQL:
        """Returns an instance of the MySQL object from mysql_k8s_helpers."""
        return MySQL(
            self.get_unit_address(),
            self.app_peer_data["cluster-name"],
            self.app_peer_data["cluster-set-domain-name"],
            self.get_secret("app", ROOT_PASSWORD_KEY),  # pyright: ignore [reportArgumentType]
            SERVER_CONFIG_USERNAME,
            self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),  # pyright: ignore [reportArgumentType]
            CLUSTER_ADMIN_USERNAME,
            self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY),  # pyright: ignore [reportArgumentType]
            MONITORING_USERNAME,
            self.get_secret("app", MONITORING_PASSWORD_KEY),  # pyright: ignore [reportArgumentType]
            BACKUPS_USERNAME,
            self.get_secret("app", BACKUPS_PASSWORD_KEY),  # pyright: ignore [reportArgumentType]
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
                        "EXPORTER_USER": MONITORING_USERNAME,
                        "EXPORTER_PASS": self.get_secret("app", MONITORING_PASSWORD_KEY),
                    },
                },
            },
        }
        return Layer(layer)  # pyright: ignore [reportArgumentType]

    @property
    def restart_peers(self) -> Optional[ops.model.Relation]:
        """Retrieve the peer relation."""
        return self.model.get_relation("restart")

    @property
    def unit_address(self) -> str:
        """Return the address of this unit."""
        return self.get_unit_address()

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

    def get_unit_address(self, unit: Optional[Unit] = None) -> str:
        """Get fqdn/address for a unit.

        Translate juju unit name to resolvable hostname.
        """
        if not unit:
            unit = self.unit

        return getfqdn(self.get_unit_hostname(unit.name))

    def is_unit_busy(self) -> bool:
        """Returns whether the unit is busy."""
        return self._is_cluster_blocked()

    def _get_primary_from_online_peer(self) -> Optional[str]:
        """Get the primary address from an online peer."""
        for unit in self.peers.units:
            if self.peers.data[unit].get("member-state") == "online":
                try:
                    return self._mysql.get_cluster_primary_address(
                        connect_instance_address=self.get_unit_address(unit),
                    )
                except MySQLGetClusterPrimaryAddressError:
                    # try next unit
                    continue

    def _is_unit_waiting_to_join_cluster(self) -> bool:
        """Return if the unit is waiting to join the cluster."""
        # check base conditions for join a unit to the cluster
        # - workload accessible
        # - unit waiting flag set
        # - unit configured (users created/unit set to be a cluster node)
        # - unit not node of this cluster or cluster does not report this unit as member
        # - cluster is initialized on any unit
        return (
            self.unit.get_container(CONTAINER_NAME).can_connect()
            and self.unit_peer_data.get("member-state") == "waiting"
            and self.unit_configured
            and (
                not self.unit_initialized
                or not self._mysql.is_instance_in_cluster(self.unit_label)
            )
            and self.cluster_initialized
        )

    def join_unit_to_cluster(self) -> None:
        """Join the unit to the cluster.

        Try to join the unit from the primary unit.
        """
        instance_label = self.unit.name.replace("/", "-")
        instance_address = self.get_unit_address(self.unit)

        if not self._mysql.is_instance_in_cluster(instance_label):
            # Add new instance to the cluster
            try:
                cluster_primary = self._get_primary_from_online_peer()
                if not cluster_primary:
                    self.unit.status = WaitingStatus("waiting to get cluster primary from peers")
                    logger.debug("waiting: unable to retrieve the cluster primary from peers")
                    return

                if (
                    self._mysql.get_cluster_node_count(from_instance=cluster_primary)
                    == GR_MAX_MEMBERS
                ):
                    self.unit.status = WaitingStatus(
                        f"Cluster reached max size of {GR_MAX_MEMBERS} units. Standby."
                    )
                    logger.warning(
                        f"Cluster reached max size of {GR_MAX_MEMBERS} units. This unit will stay as standby."
                    )
                    return

                # If instance is part of a replica cluster, locks are managed by the
                # the primary cluster primary (i.e. cluster set global primary)
                lock_instance = None
                if self._mysql.is_cluster_replica(from_instance=cluster_primary):
                    lock_instance = self._mysql.get_cluster_set_global_primary_address(
                        connect_instance_address=cluster_primary
                    )

                # add random delay to mitigate collisions when multiple units are joining
                # due the difference between the time we test for locks and acquire them
                sleep(random.uniform(0, 1.5))

                if self._mysql.are_locks_acquired(from_instance=lock_instance or cluster_primary):
                    self.unit.status = WaitingStatus("waiting to join the cluster")
                    logger.debug("waiting: cluster lock is held")
                    return

                self.unit.status = MaintenanceStatus("joining the cluster")

                # Stop GR for cases where the instance was previously part of the cluster
                # harmless otherwise
                self._mysql.stop_group_replication()

                # If instance already in cluster, before adding instance to cluster,
                # remove the instance from the cluster and call rescan_cluster()
                # without adding/removing instances to clean up stale users
                if (
                    instance_label
                    in self._mysql.get_cluster_status(from_instance=cluster_primary)[
                        "defaultreplicaset"
                    ]["topology"].keys()
                ):
                    self._mysql.execute_remove_instance(
                        connect_instance=cluster_primary, force=True
                    )
                    self._mysql.rescan_cluster(from_instance=cluster_primary)

                self._mysql.add_instance_to_cluster(
                    instance_address=instance_address,
                    instance_unit_label=instance_label,
                    from_instance=cluster_primary,
                    lock_instance=lock_instance,
                )
                logger.debug(f"Added instance {instance_address} to cluster")
            except MySQLAddInstanceToClusterError:
                logger.debug(f"Unable to add instance {instance_address} to cluster.")
                return
            except MySQLLockAcquisitionError:
                self.unit.status = WaitingStatus("waiting to join the cluster")
                logger.debug("waiting: failed to acquire lock when adding instance to cluster")
                return

        self.unit_peer_data["member-state"] = "online"
        self.unit.status = ActiveStatus(self.active_status_message)
        logger.debug(f"Instance {instance_label} is cluster member")

    def _reconcile_pebble_layer(self, container: Container) -> None:
        """Reconcile pebble layer."""
        current_layer = container.get_plan()
        new_layer = self._pebble_layer

        if new_layer.services != current_layer.services:
            logger.info("Reconciling the pebble layer")

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
        if self.peers.units != self.restart_peers.units:
            # defer restart until all units are in the relation
            logger.debug("Deferring restart until all units are in the relation")
            event.defer()
            return
        if self.peers.units and self._mysql.is_unit_primary(self.unit_label):
            # delay primary on multi units
            restart_states = {
                self.restart_peers.data[unit].get("state", "unset") for unit in self.peers.units
            }
            if restart_states == {"unset"}:
                logger.info("Restarting primary")
            elif restart_states != {"release"}:
                # Wait other units restart first to minimize primary switchover
                message = "Primary restart deferred after other units"
                logger.info(message)
                self.unit.status = WaitingStatus(message)
                event.defer()
                return
        self.unit.status = MaintenanceStatus("restarting MySQL")
        container = self.unit.get_container(CONTAINER_NAME)
        if container.can_connect():
            logger.debug("Restarting mysqld")
            container.pebble.restart_services([MYSQLD_SAFE_SERVICE], timeout=3600)
            sleep(10)
            self._on_update_status(None)

    # =========================================================================
    # Charm event handlers
    # =========================================================================

    def _reconcile_mysqld_exporter(
        self, event: RelationCreatedEvent | RelationBrokenEvent
    ) -> None:
        """Handle a COS relation created or broken event."""
        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            # reconciliation is done on pebble ready
            logger.debug("Skip reconcile mysqld exporter: container not ready")
            return

        if not container.pebble.get_plan():
            # reconciliation is done on pebble ready
            logger.debug("Skip reconcile mysqld exporter: empty pebble layer")
            return

        if not self._mysql.is_data_dir_initialised():
            logger.debug("Skip reconcile mysqld exporter: mysql not initialised")
            return
        self.current_event = event
        self._reconcile_pebble_layer(container)

    def _on_peer_relation_joined(self, _) -> None:
        """Handle the peer relation joined event."""
        # set some initial unit data
        self.unit_peer_data.setdefault("member-role", "unknown")
        self.unit_peer_data.setdefault("member-state", "waiting")

    def _on_config_changed(self, _: EventBase) -> None:  # noqa: C901
        """Handle the config changed event."""
        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            # configuration also take places on pebble ready handler
            return

        if not self._is_peer_data_set:
            # skip when not initialized
            return

        if not self.upgrade.idle:
            # skip when upgrade is in progress
            # the upgrade already restart the daemon
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
            audit_log_enabled=self.config.plugin_audit_enabled,
            audit_log_strategy=self.config.plugin_audit_strategy,
            memory_limit=memory_limit_bytes,
            experimental_max_connections=self.config.experimental_max_connections,
            binlog_retention_days=self.config.binlog_retention_days,
        )

        changed_config = compare_dictionaries(previous_config_dict, new_config_dict)

        if self.mysql_config.keys_requires_restart(changed_config):
            # there are static configurations in changed keys
            logger.info("Persisting configuration changes to file")

            # persist config to file
            self._mysql.write_content_to_file(path=MYSQLD_CONFIG_FILE, content=new_config_content)

            if self._mysql.is_mysqld_running():
                logger.info("Configuration change requires restart")
                if "loose-audit_log_format" in changed_config:
                    # plugins are manipulated running daemon
                    if self.config.plugin_audit_enabled:
                        self._mysql.install_plugins(["audit_log", "audit_log_filter"])
                    else:
                        self._mysql.uninstall_plugins(["audit_log", "audit_log_filter"])
                # restart the service
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
        common_hash = self.generate_random_hash()
        self.app_peer_data.setdefault(
            "cluster-name", self.config.cluster_name or f"cluster-{common_hash}"
        )
        self.app_peer_data.setdefault(
            "cluster-set-domain-name", self.config.cluster_set_name or f"cluster-set-{common_hash}"
        )

    def _open_ports(self) -> None:
        """Open ports if supported.

        Used if `juju expose` ran on application
        """
        if ops.JujuVersion.from_environ().supports_open_port_on_k8s:
            try:
                self.unit.set_ports(3306, 33060)
            except ops.ModelError:
                logger.exception("failed to open port")

    def _write_mysqld_configuration(self):
        """Write the mysqld configuration to the file."""
        memory_limit_bytes = (self.config.profile_limit_memory or 0) * BYTES_1MB
        new_config_content, _ = self._mysql.render_mysqld_configuration(
            profile=self.config.profile,
            audit_log_enabled=self.config.plugin_audit_enabled,
            audit_log_strategy=self.config.plugin_audit_strategy,
            memory_limit=memory_limit_bytes,
            experimental_max_connections=self.config.experimental_max_connections,
            binlog_retention_days=self.config.binlog_retention_days,
        )
        self._mysql.write_content_to_file(path=MYSQLD_CONFIG_FILE, content=new_config_content)

    def _configure_instance(self, container) -> None:
        """Configure the instance for use in Group Replication."""
        # Run mysqld for the first time to
        # bootstrap the data directory and users
        logger.debug("Initializing instance")
        try:
            self._mysql.fix_data_dir(container)
            self._mysql.initialise_mysqld()

            # Add the pebble layer
            logger.debug("Adding pebble layer")
            container.add_layer(MYSQLD_SAFE_SERVICE, self._pebble_layer, combine=True)
            container.restart(MYSQLD_SAFE_SERVICE)

            logger.debug("Waiting for instance to be ready")
            self._mysql.wait_until_mysql_connection(check_port=False)

            logger.info("Configuring instance")
            # Configure all base users and revoke privileges from the root users
            self._mysql.configure_mysql_users(password_needed=False)

            if self.config.plugin_audit_enabled:
                # Enable the audit plugin
                self._mysql.install_plugins(["audit_log", "audit_log_filter"])

            # Configure instance as a cluster node
            self._mysql.configure_instance()
        except (
            MySQLInitialiseMySQLDError,
            MySQLServiceNotRunningError,
            MySQLConfigureMySQLUsersError,
            MySQLConfigureInstanceError,
        ):
            # On any error, reset the data directory so hook is retried
            # on empty data directory
            # https://github.com/canonical/mysql-k8s-operator/issues/447
            self._mysql.reset_data_dir()
            raise

        if self.has_cos_relation:
            if container.get_services(MYSQLD_EXPORTER_SERVICE)[
                MYSQLD_EXPORTER_SERVICE
            ].is_running():
                # Restart exporter service after configuration
                container.restart(MYSQLD_EXPORTER_SERVICE)
            else:
                container.start(MYSQLD_EXPORTER_SERVICE)

        self._open_ports()

        try:
            # Set workload version
            if workload_version := self._mysql.get_mysql_version():
                self.unit.set_workload_version(workload_version)
        except MySQLGetMySQLVersionError:
            # Do not block the charm if the version cannot be retrieved
            pass

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

        if not self.upgrade.idle:
            # when upgrading pebble ready is
            # task delegated to upgrade code
            return

        container = event.workload
        self._write_mysqld_configuration()

        logger.info("Setting up the logrotate configurations")
        self._mysql.setup_logrotate_config()

        if self._mysql.is_data_dir_initialised():
            # Data directory is already initialised, skip configuration
            self.unit.status = MaintenanceStatus("Starting mysqld")
            logger.debug("Data directory is already initialised, skipping configuration")
            self._reconcile_pebble_layer(container)
            return

        self.unit.status = MaintenanceStatus("Initialising mysqld")

        # First run setup
        self._configure_instance(container)

        if not self.unit.is_leader() or (
            self.cluster_initialized and self._get_primary_from_online_peer()
        ):
            # Non-leader units try to join cluster
            self.unit.status = WaitingStatus("Waiting for instance to join the cluster")
            self.unit_peer_data.update({"member-role": "secondary", "member-state": "waiting"})
            self.join_unit_to_cluster()
            return

        try:
            # Create the cluster when is the leader unit
            logger.info(f"Creating cluster {self.app_peer_data['cluster-name']}")
            self.unit.status = MaintenanceStatus("Creating cluster")
            self.create_cluster()
            self.unit.status = ops.ActiveStatus(self.active_status_message)

        except (
            MySQLCreateClusterError,
            MySQLUnableToGetMemberStateError,
            MySQLNoMemberStateError,
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
        if not self._mysql.is_mysqld_running():
            return True

        # retrieve and persist state for every unit
        try:
            state, role = self._mysql.get_member_state()
            self.unit_peer_data["member-state"] = state
            self.unit_peer_data["member-role"] = role
        except (MySQLUnableToGetMemberStateError, MySQLNoMemberStateError):
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

        if state == "offline":
            # Group Replication is active but the member does not belong to any group
            all_states = {
                self.peers.data[unit].get("member-state", "unknown") for unit in self.peers.units
            }

            only_single_node_across_cluster = self.only_single_cluster_node_exists

            # Add state 'offline' for this unit (self.peers.unit does not
            # include this unit)
            if (all_states | {"offline"} == {"offline"} and self.unit.is_leader()) or (
                only_single_node_across_cluster and all_states == {"waiting"}
            ):
                # All instance are off, reboot cluster from outage from the leader unit

                logger.info("Attempting reboot from complete outage.")
                try:
                    if self.unit.is_leader() or only_single_node_across_cluster:
                        self._mysql.reboot_from_complete_outage()
                except MySQLRebootFromCompleteOutageError:
                    logger.error("Failed to reboot cluster from complete outage.")

                    if only_single_node_across_cluster and all_states == {"waiting"}:
                        self._mysql.drop_group_replication_metadata_schema()
                        self.create_cluster()
                        self.unit.status = ActiveStatus(self.active_status_message)
                    else:
                        self.unit.status = BlockedStatus("failed to recover cluster.")

            return True

        return False

    def _is_cluster_blocked(self) -> bool:
        """Performs cluster state checks for the update-status handler.

        Returns: a boolean indicating whether the update-status (caller) should
            no-op and return.
        """
        no_member_state_exists = False
        try:
            member_state, _ = self._mysql.get_member_state()
        except MySQLUnableToGetMemberStateError:
            logger.error("Error getting member state while checking if cluster is blocked")
            self.unit.status = MaintenanceStatus("Unable to get member state")
            return True
        except MySQLNoMemberStateError:
            no_member_state_exists = True

        if no_member_state_exists or member_state == "restarting":
            # avoid changing status while tls is being set up or charm is being initialized
            logger.info(
                f"Unit is waiting or restarting, {member_state=}, {no_member_state_exists=}"
            )
            return True

        # avoid changing status while async replication is setting up
        return not (self.replication_consumer.idle and self.replication_offer.idle)

    def _on_update_status(self, _: Optional[UpdateStatusEvent]) -> None:
        """Handle the update status event."""
        if not self.upgrade.idle:
            # avoid changing status while upgrade is in progress
            logger.debug("Application is upgrading. Skipping.")
            return
        if not self.unit.is_leader() and self._is_unit_waiting_to_join_cluster():
            # join cluster test takes precedence over blocked test
            # due to matching criteria
            self.join_unit_to_cluster()
            return

        if self._is_cluster_blocked():
            return
        del self.restart_peers.data[self.unit]["state"]

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            logger.debug("Cannot connect to pebble in the mysql container")
            return

        if self._handle_potential_cluster_crash_scenario():
            return

        if not self.unit.is_leader():
            return

        self._set_app_status()

    def _set_app_status(self) -> None:
        """Set the application status based on the cluster state."""
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
            self.join_unit_to_cluster()

    def _on_database_storage_detaching(self, _) -> None:
        """Handle the database storage detaching event."""
        # Only executes if the unit was initialised
        if not self.unit_initialized:
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
                    new_primary_address=getfqdn(self.get_unit_hostname(f"{self.app.name}/0"))
                )
            except MySQLSetClusterPrimaryError:
                logger.warning("Failed to switch primary to unit 0")

        # If instance is part of a replica cluster, locks are managed by the
        # the primary cluster primary (i.e. cluster set global primary)
        lock_instance = None
        if self._mysql.is_cluster_replica():
            lock_instance = self._mysql.get_cluster_set_global_primary_address()

        # The following operation uses locks to ensure that only one instance is removed
        # from the cluster at a time (to avoid split-brain or lack of majority issues)
        self._mysql.remove_instance(self.unit_label, lock_instance=lock_instance)

        # Inform other hooks of current status
        self.unit_peer_data["unit-status"] = "removing"


if __name__ == "__main__":
    main(MySQLOperatorCharm)
