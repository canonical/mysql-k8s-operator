#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging
from typing import Dict, Optional

from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.mysql.v0.backups import MySQLBackups
from charms.mysql.v0.mysql import (
    MySQLAddInstanceToClusterError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLGetMemberStateError,
    MySQLGetMySQLVersionError,
    MySQLRebootFromCompleteOutageError,
)
from charms.mysql.v0.tls import MySQLTLS
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from ops.charm import (
    ActionEvent,
    CharmBase,
    LeaderElectedEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
    UpdateStatusEvent,
)
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Container,
    MaintenanceStatus,
    WaitingStatus,
)
from ops.pebble import Layer

from constants import (
    BACKUPS_PASSWORD_KEY,
    BACKUPS_USERNAME,
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    CONTAINER_NAME,
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
    REQUIRED_USERNAMES,
    ROOT_PASSWORD_KEY,
    ROOT_USERNAME,
    S3_INTEGRATOR_RELATION_NAME,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)
from k8s_helpers import KubernetesHelpers
from mysql_k8s_helpers import (
    MySQL,
    MySQLCreateCustomConfigFileError,
    MySQLForceRemoveUnitFromClusterError,
    MySQLGetInnoDBBufferPoolParametersError,
    MySQLInitialiseMySQLDError,
)
from relations.mysql import MySQLRelation
from relations.mysql_provider import MySQLProvider
from relations.osm_mysql import MySQLOSMRelation
from utils import generate_random_hash, generate_random_password

logger = logging.getLogger(__name__)


class MySQLOperatorCharm(CharmBase):
    """Operator framework charm for MySQL."""

    def __init__(self, *args):
        super().__init__(*args)

        # Lifecycle events
        self.framework.observe(self.on.mysql_pebble_ready, self._on_mysql_pebble_ready)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.framework.observe(self.on[PEER].relation_joined, self._on_peer_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)

        # Actions events
        self.framework.observe(self.on.get_cluster_status_action, self._get_cluster_status)
        self.framework.observe(self.on.get_password_action, self._on_get_password)
        self.framework.observe(self.on.set_password_action, self._on_set_password)

        self.k8s_helpers = KubernetesHelpers(self)
        self.mysql_relation = MySQLRelation(self)
        self.database_relation = MySQLProvider(self)
        self.osm_mysql_relation = MySQLOSMRelation(self)
        self.tls = MySQLTLS(self)
        self.s3_integrator = S3Requirer(self, S3_INTEGRATOR_RELATION_NAME)
        self.backups = MySQLBackups(self, self.s3_integrator)
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

    @property
    def peers(self):
        """Retrieve the peer relation (`ops.model.Relation`)."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self) -> Dict:
        """Application peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.app]

    @property
    def unit_peer_data(self) -> Dict:
        """Unit peer relation data object."""
        if self.peers is None:
            return {}

        return self.peers.data[self.unit]

    @property
    def _mysql(self):
        """Returns an instance of the MySQL object from mysql_k8s_helpers."""
        return MySQL(
            self.get_unit_hostname(self.unit.name),
            self.app_peer_data["cluster-name"],
            self.get_secret("app", ROOT_PASSWORD_KEY),
            SERVER_CONFIG_USERNAME,
            self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),
            CLUSTER_ADMIN_USERNAME,
            self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY),
            MONITORING_USERNAME,
            self.get_secret("app", MONITORING_PASSWORD_KEY),
            BACKUPS_USERNAME,
            self.get_secret("app", BACKUPS_PASSWORD_KEY),
            self.unit.get_container("mysql"),
            self.k8s_helpers,
        )

    @property
    def _is_peer_data_set(self):
        return (
            self.app_peer_data.get("cluster-name")
            and self.get_secret("app", ROOT_PASSWORD_KEY)
            and self.get_secret("app", SERVER_CONFIG_PASSWORD_KEY)
            and self.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY)
            and self.app_peer_data.get("allowlist")
        )

    @property
    def cluster_initialized(self):
        """Returns True if the cluster is initialized."""
        return self.app_peer_data.get("units-added-to-cluster", "0") >= "1"

    @property
    def unit_initialized(self):
        """Return True if the unit is initialized."""
        return self.unit_peer_data.get("unit-initialized") == "True"

    @property
    def _pebble_layer(self) -> Layer:
        """Return a layer for the mysqld pebble service."""
        return Layer(
            {
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
                    },
                    MYSQLD_EXPORTER_SERVICE: {
                        "override": "replace",
                        "summary": "mysqld exporter",
                        "command": "/start-mysqld-exporter.sh",
                        "startup": "enabled",
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
        )

    @property
    def active_status_message(self) -> str:
        """Active status message."""
        if self.unit_peer_data.get("member-role") == "primary":
            return "Primary"
        return ""

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

    def _get_unit_fqdn(self, unit_name: str) -> str:
        """Create a fqdn for a unit.

        Translate juju unit name to resolvable hostname.

        Args:
            unit_name: unit name
        Returns:
            A string representing the fqdn of the unit.
        """
        return f"{self.get_unit_hostname(unit_name)}.{self.model.name}.svc.cluster.local"

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Set secret in the secret storage."""
        if scope == "unit":
            if not value:
                del self.unit_peer_data[key]
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                del self.app_peer_data[key]
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")

    def s3_integrator_relation_exists(self) -> bool:
        """Returns whether a relation with the s3-integrator exists."""
        return bool(self.model.get_relation(S3_INTEGRATOR_RELATION_NAME))

    def is_unit_busy(self) -> bool:
        """Returns whether the unit is busy."""
        return self._is_cluster_blocked()

    # =========================================================================
    # Charm event handlers
    # =========================================================================

    def _on_config_changed(self, _) -> None:
        """Handle the config changed event."""
        # Only execute on unit leader
        if not self.unit.is_leader():
            return

        # Set the cluster name in the peer relation databag if it is not already set
        if not self.app_peer_data.get("cluster-name"):
            self.app_peer_data["cluster-name"] = (
                self.config.get("cluster-name") or f"cluster_{generate_random_hash()}"
            )

        # initialise allowlist with leader hostname
        if not self.app_peer_data.get("allowlist"):
            self.app_peer_data["allowlist"] = f"{self._get_unit_fqdn(self.unit.name)}"

    def _on_leader_elected(self, _: LeaderElectedEvent) -> None:
        """Handle the leader elected event.

        Set config values in the peer relation databag if not already set.
        Idempotently remove unreachable instances from the cluster and update
        the allowlist accordingly.
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

    def _configure_instance(self, container) -> bool:
        """Configure the instance for use in Group Replication."""
        try:
            # Run mysqld for the first time to
            # bootstrap the data directory and users
            logger.debug("Initializing instance")
            self._mysql.initialise_mysqld()

            # Add the pebble layer
            logger.debug("Adding pebble layer")
            container.add_layer(MYSQLD_SAFE_SERVICE, self._pebble_layer, combine=False)
            self._mysql.safe_stop_mysqld_safe()
            container.restart(MYSQLD_SAFE_SERVICE)

            logger.debug("Waiting for instance to be ready")
            self._mysql.wait_until_mysql_connection()

            logger.info("Configuring instance")
            # Configure all base users and revoke privileges from the root users
            self._mysql.configure_mysql_users()
            # Configure instance as a cluster node
            self._mysql.configure_instance()
            # Restart exporter service after configuration
            container.restart(MYSQLD_EXPORTER_SERVICE)

            self.unit_peer_data["unit-configured"] = "True"
        except (
            MySQLConfigureInstanceError,
            MySQLConfigureMySQLUsersError,
            MySQLInitialiseMySQLDError,
            MySQLCreateCustomConfigFileError,
        ) as e:
            logger.debug("Unable to configure instance: {}".format(e))
            return False

        try:
            # Set workload version
            workload_version = self._mysql.get_mysql_version()
            self.unit.set_workload_version(workload_version)
        except MySQLGetMySQLVersionError:
            # Do not block the charm if the version cannot be retrieved
            pass

        return True

    def _prepare_configs(self, container: Container) -> bool:
        """Copies files to the workload container.

        Meant to be called from the pebble-ready handler.

        Returns: a boolean indicating if the method was successful.
        """
        if not container.exists(MYSQLD_CONFIG_FILE):
            try:
                (
                    innodb_buffer_pool_size,
                    innodb_buffer_pool_chunk_size,
                ) = self._mysql.get_innodb_buffer_pool_parameters()
            except MySQLGetInnoDBBufferPoolParametersError:
                self.unit.status = BlockedStatus("Error computing innodb_buffer_pool_size")
                return False

            try:
                self._mysql.create_custom_config_file(
                    report_host=self._get_unit_fqdn(self.unit.name),
                    innodb_buffer_pool_size=innodb_buffer_pool_size,
                    innodb_buffer_pool_chunk_size=innodb_buffer_pool_chunk_size,
                )
            except MySQLCreateCustomConfigFileError:
                self.unit.status = BlockedStatus("Failed to copy custom mysql config file")
                return False

        return True

    def _on_mysql_pebble_ready(self, event) -> None:
        """Pebble ready handler.

        Define and start a pebble service and bootstrap instance.
        """
        if not self._is_peer_data_set:
            self.unit.status = WaitingStatus("Waiting for leader election.")
            logger.debug("Leader not ready yet, waiting...")
            event.defer()
            return

        container = event.workload
        if not self._prepare_configs(container):
            return

        self.unit.status = MaintenanceStatus("Initialising mysqld")
        if self.unit_peer_data.get("unit-configured"):
            # Only update pebble layer if unit is already configured for GR
            current_layer = container.get_plan()
            new_layer = self._pebble_layer

            if new_layer.services != current_layer:
                logger.info("Adding pebble layer")

                container.add_layer(MYSQLD_SAFE_SERVICE, new_layer, combine=True)
                container.restart(MYSQLD_SAFE_SERVICE)
                self._mysql.wait_until_mysql_connection()
                self._on_update_status(None)

            return

        # First run setup
        if not self._configure_instance(container):
            self.unit.status = BlockedStatus("Unable to configure instance")
            return

        if not self.unit.is_leader():
            # Non-leader units should wait for leader to add them to the cluster
            self.unit.status = WaitingStatus("Waiting for instance to join the cluster")
            self.unit_peer_data.update({"member-role": "secondary", "member-state": "waiting"})
            return

        try:
            # Create the cluster when is the leader unit
            logger.info("Creating cluster on the leader unit")
            unit_label = self.unit.name.replace("/", "-")
            self._mysql.create_cluster(unit_label)

            # Create control file in data directory
            self.app_peer_data["units-added-to-cluster"] = "1"

            state, role = self._mysql.get_member_state()

            self.unit_peer_data.update(
                {"member-state": state, "member-role": role, "unit-initialized": "True"}
            )

            self.unit.status = ActiveStatus(self.active_status_message)
        except MySQLCreateClusterError as e:
            self.unit.status = BlockedStatus("Unable to create cluster")
            logger.debug("Unable to create cluster: {}".format(e))
        except MySQLGetMemberStateError:
            self.unit.status = BlockedStatus("Unable to query member state and role")

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
            self.unit_peer_data["member-role"] = role
            self.unit_peer_data["member-state"] = state
        except MySQLGetMemberStateError:
            role = self.unit_peer_data["member-role"] = "unknown"
            state = self.unit_peer_data["member-state"] = "gr_inactive"

        logger.info(f"Unit workload member-state is {state} with member-role {role}")

        # set unit status based on member-{state,role}
        self.unit.status = (
            ActiveStatus(self.active_status_message)
            if state == "online"
            else MaintenanceStatus(state if state != "gr_inactive" else "unreachable")
        )

        if state == "recovering":
            return True

        if state in ["offline", "gr_inactive"]:
            # Group Replication is active but the member does not belong to any group
            all_states = {
                self.peers.data[unit].get("member-state", "unknown") for unit in self.peers.units
            }
            # Add state for this unit (self.peers.units does not include this unit)
            all_states.add("offline")
            all_states.add("gr_inactive")

            if all_states == {"offline", "gr_inactive"} and self.unit.is_leader():
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

    def _on_update_status(self, event: UpdateStatusEvent) -> None:
        """Handle the update status event.

        One purpose of this event handler is to ensure that scaled down units are
        removed from the cluster.
        """
        if self._is_cluster_blocked():
            return

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        if self._handle_potential_cluster_crash_scenario():
            return

        if not self.unit.is_leader():
            return

        planned_units = self.app.planned_units()

        cluster_status = self._mysql.get_cluster_status()
        if not cluster_status:
            self.unit.status = BlockedStatus("Failed to get cluster status")
            return

        addresses_of_units_to_remove = [
            member["address"]
            for unit_name, member in cluster_status["defaultreplicaset"]["topology"].items()
            if int(unit_name.split("-")[-1]) >= planned_units
        ]

        if not addresses_of_units_to_remove:
            return

        self.unit.status = MaintenanceStatus("Removing scaled down units from cluster")

        for unit_address in addresses_of_units_to_remove:
            try:
                self._mysql.force_remove_unit_from_cluster(unit_address)
            except MySQLForceRemoveUnitFromClusterError:
                self.unit.status = BlockedStatus("Failed to remove scaled down unit from cluster")
                return

        self.unit.status = ActiveStatus(self.active_status_message)

    def _on_peer_relation_joined(self, event: RelationJoinedEvent):
        """Handle the peer relation joined event."""
        # Only leader unit add instances to the cluster
        if not self.unit.is_leader():
            return

        # only add other units
        if event.unit.name == self.unit.name:
            return

        # Defer run when leader is not active
        if not isinstance(self.unit.status, ActiveStatus):
            event.defer()
            return

        new_instance_fqdn = self._get_unit_fqdn(event.unit.name)
        new_instance_label = event.unit.name.replace("/", "-")

        # Check if new instance is ready to be added to the cluster
        if not self._mysql.is_instance_configured_for_innodb(
            new_instance_fqdn, new_instance_label
        ):
            event.defer()
            return

        # Check if instance was already added to the cluster
        if self._mysql.is_instance_in_cluster(new_instance_label):
            logger.debug(f"Instance {new_instance_fqdn} already in cluster")
            return

        # Add new instance to the cluster
        try:
            cluster_primary = self._mysql.get_cluster_primary_address()
            if not cluster_primary:
                self.unit.status = BlockedStatus("Unable to retrieve the cluster primary")
                return

            self._mysql.add_instance_to_cluster(
                new_instance_fqdn, new_instance_label, from_instance=cluster_primary
            )
            logger.debug(f"Added instance {new_instance_fqdn} to cluster")

            # Update 'units-added-to-cluster' counter in the peer relation databag
            # in order to trigger a relation_changed event which will move the added unit
            # into ActiveStatus
            units_started = int(self.app_peer_data["units-added-to-cluster"])
            self.app_peer_data["units-added-to-cluster"] = str(units_started + 1)

        except MySQLAddInstanceToClusterError:
            logger.debug(f"Unable to add instance {new_instance_fqdn} to cluster.")
            self.unit.status = BlockedStatus("Unable to add instance to cluster")

    def _on_peer_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the relation changed event."""
        # This handler is only taking care of setting
        # active status for secondary units
        if not self._is_peer_data_set:
            # Avoid running too early
            event.defer()
            return

        instance_label = self.unit.name.replace("/", "-")
        # Test if non-leader unit is ready
        if isinstance(self.unit.status, WaitingStatus) and self._mysql.is_instance_in_cluster(
            instance_label
        ):
            self.unit_peer_data["unit-initialized"] = "True"
            self.unit_peer_data["member-state"] = "online"
            self.unit.status = ActiveStatus(self.active_status_message)
            logger.debug(f"Instance {instance_label} is cluster member")

    # =========================================================================
    # Charm action handlers
    # =========================================================================
    def _on_get_password(self, event: ActionEvent) -> None:
        """Action used to retrieve the system user's password."""
        username = event.params.get("username") or ROOT_USERNAME

        if username not in REQUIRED_USERNAMES:
            raise RuntimeError("Invalid username.")

        if username == ROOT_USERNAME:
            secret_key = ROOT_PASSWORD_KEY
        elif username == SERVER_CONFIG_USERNAME:
            secret_key = SERVER_CONFIG_PASSWORD_KEY
        elif username == CLUSTER_ADMIN_USERNAME:
            secret_key = CLUSTER_ADMIN_PASSWORD_KEY
        elif username == BACKUPS_USERNAME:
            secret_key = BACKUPS_PASSWORD_KEY
        else:
            raise RuntimeError("Invalid username.")

        event.set_results({"username": username, "password": self.get_secret("app", secret_key)})

    def _on_set_password(self, event: ActionEvent) -> None:
        """Action used to update/rotate the system user's password."""
        if not self.unit.is_leader():
            raise RuntimeError("set-password action can only be run on the leader unit.")

        username = event.params.get("username") or ROOT_USERNAME

        if username not in REQUIRED_USERNAMES:
            raise RuntimeError("Invalid username.")

        if username == ROOT_USERNAME:
            secret_key = ROOT_PASSWORD_KEY
        elif username == SERVER_CONFIG_USERNAME:
            secret_key = SERVER_CONFIG_PASSWORD_KEY
        elif username == CLUSTER_ADMIN_USERNAME:
            secret_key = CLUSTER_ADMIN_PASSWORD_KEY
        elif username == BACKUPS_USERNAME:
            secret_key = BACKUPS_PASSWORD_KEY
        else:
            raise RuntimeError("Invalid username.")

        new_password = event.params.get("password") or generate_random_password(PASSWORD_LENGTH)

        self._mysql.update_user_password(username, new_password)

        self.set_secret("app", secret_key, new_password)

    def _get_cluster_status(self, event: ActionEvent) -> None:
        """Get the cluster status without topology."""
        status = self._mysql.get_cluster_status()
        if status:
            event.set_results(
                {
                    "success": True,
                    "status": status,
                }
            )
        else:
            event.set_results(
                {
                    "success": False,
                    "message": "Failed to read cluster status.  See logs for more information.",
                }
            )


if __name__ == "__main__":
    main(MySQLOperatorCharm)
