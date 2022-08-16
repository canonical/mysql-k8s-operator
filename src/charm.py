#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import logging

from charms.mysql.v0.mysql import (
    MySQLAddInstanceToClusterError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLGetMySQLVersionError,
)
from ops.charm import (
    ActionEvent,
    CharmBase,
    LeaderElectedEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
    RelationJoinedEvent,
)
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

from constants import (
    CLUSTER_ADMIN_USERNAME,
    CONFIGURED_FILE,
    MYSQLD_SERVICE,
    PASSWORD_LENGTH,
    PEER,
    SERVER_CONFIG_USERNAME,
)
from mysqlsh_helpers import (
    MySQL,
    MySQLCreateCustomConfigFileError,
    MySQLInitialiseMySQLDError,
    MySQLRemoveInstancesNotOnlineError,
    MySQLRemoveInstancesNotOnlineRetryError,
)
from relations.database import DatabaseRelation
from relations.mysql import MySQLRelation
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

        self.framework.observe(self.on[PEER].relation_joined, self._on_peer_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)
        self.framework.observe(self.on[PEER].relation_departed, self._on_peer_relation_departed)

        # Actions events
        self.framework.observe(
            self.on.get_cluster_admin_credentials_action, self._on_get_cluster_admin_credentials
        )
        self.framework.observe(
            self.on.get_server_config_credentials_action, self._on_get_server_config_credentials
        )
        self.framework.observe(self.on.get_root_credentials_action, self._on_get_root_credentials)
        self.framework.observe(self.on.get_cluster_status_action, self._get_cluster_status)

        self.mysql_relation = MySQLRelation(self)
        self.database_relation = DatabaseRelation(self)

    @property
    def _peers(self):
        """Retrieve the peer relation (`ops.model.Relation`)."""
        return self.model.get_relation(PEER)

    @property
    def _mysql(self):
        """Returns an instance of the MySQL object from mysqlsh_helpers."""
        peer_data = self._peers.data[self.app]

        return MySQL(
            self._get_unit_fqdn(self.unit.name),
            peer_data["cluster-name"],
            peer_data["root-password"],
            SERVER_CONFIG_USERNAME,
            peer_data["server-config-password"],
            CLUSTER_ADMIN_USERNAME,
            peer_data["cluster-admin-password"],
            self.unit.get_container("mysql"),
        )

    @property
    def _is_peer_data_set(self):
        peer_data = self._peers.data[self.app]

        return (
            peer_data.get("cluster-name")
            and peer_data.get("root-password")
            and peer_data.get("server-config-password")
            and peer_data.get("cluster-admin-password")
            and peer_data.get("allowlist")
        )

    @property
    def cluster_initialized(self):
        """Returns True if the cluster is initialized."""
        return self._peers.data[self.app].get("units-added-to-cluster", "0") >= "1"

    @property
    def _pebble_layer(self) -> Layer:
        """Return a layer for the pebble service."""
        return Layer(
            {
                "summary": "mysqld layer",
                "description": "pebble config layer for mysqld",
                "services": {
                    MYSQLD_SERVICE: {
                        "override": "replace",
                        "summary": "mysqld",
                        "command": "mysqld",
                        "startup": "enabled",
                        "user": "mysql",
                        "group": "mysql",
                    }
                },
            }
        )

    def _get_unit_hostname(self, unit_name: str) -> str:
        """Get the hostname.localdomain for a unit.

        Translate juju unit name to hostname.localdomain, necessary
        for correct name resolution under k8s.

        Args:
            unit_name: unit name
        Returns:
            A string representing the hostname.localdomain of the unit.
        """
        return f"{unit_name.replace('/', '-')}.{self.app.name}-endpoints"

    def _get_unit_fqdn(self, unit_name: str) -> str:
        """Create a fqdn for a unit.

        Translate juju unit name to resolvable hostname.

        Args:
            unit_name: unit name
        Returns:
            A string representing the fqdn of the unit.
        """
        return f"{self._get_unit_hostname(unit_name)}.{self.model.name}.svc.cluster.local"

    # =========================================================================
    # Charm event handlers
    # =========================================================================

    def _on_config_changed(self, _) -> None:
        """Handle the config changed event."""
        # Only execute on unit leader
        if not self.unit.is_leader():
            return

        # Set the cluster name in the peer relation databag if it is not already set
        peer_data = self._peers.data[self.app]

        if not peer_data.get("cluster-name"):
            peer_data["cluster-name"] = (
                self.config.get("cluster-name") or f"cluster_{generate_random_hash()}"
            )

        # initialise allowlist with leader hostname
        if not peer_data.get("allowlist"):
            peer_data["allowlist"] = f"{self._get_unit_fqdn(self.unit.name)}"

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handle the leader elected event.

        Set config values in the peer relation databag if not already set.
        Idempotently remove unreachable instances from the cluster and update
        the allowlist accordingly.
        """
        peer_data = self._peers.data[self.app]

        # Set required passwords if not already set
        required_passwords = ["root-password", "server-config-password", "cluster-admin-password"]

        for required_password in required_passwords:
            if not peer_data.get(required_password):
                logger.debug(f"Setting {required_password}")
                password = generate_random_password(PASSWORD_LENGTH)
                peer_data[required_password] = password

        # If this node was elected a leader due to a prior leader unit being down scaled
        if self._is_peer_data_set and self.cluster_initialized:
            self.unit.status = MaintenanceStatus("Removing unreachable instances")

            # Remove unreachable instances from the cluster
            try:
                self._mysql.remove_instances_not_online()
            except (MySQLRemoveInstancesNotOnlineError, MySQLRemoveInstancesNotOnlineRetryError):
                logger.debug("Unable to remove unreachable instances from the cluster")
                self.unit.status = BlockedStatus("Failed to remove unreachable instances")

            self.unit.status = ActiveStatus()

    def _on_mysql_pebble_ready(self, event):
        """Pebble ready handler.

        Define and start a pebble service and bootstrap instance.
        """
        if not self._is_peer_data_set:
            self.unit.status = WaitingStatus("Waiting for leader election.")
            logger.debug("Leader not ready yet, waiting...")
            event.defer()
            return

        container = event.workload

        if container.exists(CONFIGURED_FILE):
            # When reusing a volume
            # Configure the layer when changed
            current_layer = container.get_plan()
            new_layer = self._pebble_layer

            if new_layer.services != current_layer:
                logger.info("Add pebble layer")
                container.add_layer(MYSQLD_SERVICE, new_layer, combine=True)
                container.restart(MYSQLD_SERVICE)
                self._mysql.wait_until_mysql_connection()
            self.unit.status = ActiveStatus()
            return

        # First run setup
        self.unit.status = MaintenanceStatus("Initialising mysqld")
        try:

            # Run mysqld for the first time to
            # bootstrap the data directory and users
            logger.debug("Initialising instance")
            self._mysql.initialise_mysqld()

            # Create custom server config file
            self._mysql.create_custom_config_file(
                report_host=self._get_unit_hostname(self.unit.name)
            )

            # Add the pebble layer
            container.add_layer(MYSQLD_SERVICE, self._pebble_layer, combine=False)
            container.restart(MYSQLD_SERVICE)
            logger.debug("Waiting for instance to be ready")
            self._mysql.wait_until_mysql_connection()
            logger.info("Configuring instance")
            # Configure all base users and revoke
            # privileges from the root users
            self._mysql.configure_mysql_users()
            # Configure instance as a cluster node
            self._mysql.configure_instance()
            # set workload version
            workload_version = self._mysql.get_mysql_version()
            self.unit.set_workload_version(workload_version)

        except (
            MySQLConfigureInstanceError,
            MySQLConfigureMySQLUsersError,
            MySQLInitialiseMySQLDError,
            MySQLCreateCustomConfigFileError,
        ) as e:
            self.unit.status = BlockedStatus("Unable to configure instance")
            logger.debug("Unable to configure instance: {}".format(e))
            return
        except MySQLGetMySQLVersionError:
            # Do not block the charm if the version cannot be retrieved
            pass

        if self.unit.is_leader():
            try:
                # Create the cluster when is the leader unit
                unit_label = self.unit.name.replace("/", "-")
                self._mysql.create_cluster(unit_label)
                # Create control file in data directory
                container.push(CONFIGURED_FILE, make_dirs=True, source="configured")
                self._peers.data[self.app]["units-added-to-cluster"] = "1"
                self.unit.status = ActiveStatus()
            except MySQLCreateClusterError as e:
                self.unit.status = BlockedStatus("Unable to create cluster")
                logger.debug("Unable to create cluster: {}".format(e))
        else:
            # When unit is not the leader, it should wait
            # for the leader to configure it a cluster node
            self.unit.status = WaitingStatus("Waiting for instance to join the cluster")
            # Create control file in data directory
            container.push(CONFIGURED_FILE, make_dirs=True, source="configured")

    def _on_peer_relation_joined(self, event: RelationJoinedEvent):
        """Handle the peer relation joined event."""
        # Only leader unit add instances to the cluster
        if not self.unit.is_leader():
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
            self._mysql.add_instance_to_cluster(new_instance_fqdn, new_instance_label)
            logger.debug(f"Added instance {new_instance_fqdn} to cluster")

            # Update 'units-added-to-cluster' counter in the peer relation databag
            # in order to trigger a relation_changed event which will move the added unit
            # into ActiveStatus
            units_started = int(self._peers.data[self.app]["units-added-to-cluster"])
            self._peers.data[self.app]["units-added-to-cluster"] = str(units_started + 1)

        except MySQLAddInstanceToClusterError:
            logger.debug(f"Unable to add instance {new_instance_fqdn} to cluster.")
            event.defer()

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
            self.unit.status = ActiveStatus()
            logger.debug(f"Instance {instance_label} is cluster member")

    def _on_peer_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle the relation departed event.

        Update the allowlist to remove the departing unit from the leader unit.
        Only on the leader, update the allowlist in the peer relation databag
        and remove unreachable instances from the cluster.
        """
        if not self.unit.is_leader():
            return

        self.unit.status = MaintenanceStatus("Removing unreachable instances")

        try:
            self._mysql.remove_instances_not_online()
        except (MySQLRemoveInstancesNotOnlineError, MySQLRemoveInstancesNotOnlineRetryError):
            logger.debug("Unable to remove unreachable instances from the cluster")
            self.unit.status = BlockedStatus("Failed to remove unreachable instances")

        self.unit.status = ActiveStatus()

    # =========================================================================
    # Charm action handlers
    # =========================================================================
    def _on_get_cluster_admin_credentials(self, event: ActionEvent) -> None:
        """Action used to retrieve the cluster admin credentials."""
        event.set_results(
            {
                "cluster-admin-username": CLUSTER_ADMIN_USERNAME,
                "cluster-admin-password": self._peers.data[self.app].get(
                    "cluster-admin-password", "<to_be_generated>"
                ),
            }
        )

    def _on_get_server_config_credentials(self, event: ActionEvent) -> None:
        """Action used to retrieve the server config credentials."""
        event.set_results(
            {
                "server-config-username": SERVER_CONFIG_USERNAME,
                "server-config-password": self._peers.data[self.app].get(
                    "server-config-password", "<to_be_generated>"
                ),
            }
        )

    def _on_get_root_credentials(self, event: ActionEvent) -> None:
        """Action used to retrieve the root credentials."""
        event.set_results(
            {
                "root-username": "root",
                "root-password": self._peers.data[self.app].get(
                    "root-password", "<to_be_generated>"
                ),
            }
        )

    def _get_cluster_status(self, event: ActionEvent) -> None:
        """Get the cluster status without topology."""
        event.set_results(self._mysql.get_cluster_status())


if __name__ == "__main__":
    main(MySQLOperatorCharm)
