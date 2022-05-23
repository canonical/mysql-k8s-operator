#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import hashlib
import logging
import secrets
import string

from ops.charm import ActionEvent, CharmBase, RelationChangedEvent, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

from mysqlsh_helpers import (
    MySQL,
    MySQLAddInstanceToClusterError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLCreateCustomConfigFileError,
    MySQLInitialiseMySQLDError,
    MySQLUpdateAllowListError,
)

logger = logging.getLogger(__name__)

PASSWORD_LENGTH = 24
PEER = "database-peers"
CONFIGURED_FILE = "/var/lib/mysql/charmed"
MYSQLD_SERVICE = "mysqld"
CLUSTER_ADMIN_USERNAME = "clusteradmin"
SERVER_CONFIG_USERNAME = "serverconfig"


def generate_random_password(length: int) -> str:
    """Randomly generate a string intended to be used as a password.

    Args:
        length: length of the randomly generated string to be returned
    Returns:
        A randomly generated string intended to be used as a password.
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for i in range(length)])


def generate_random_hash() -> str:
    """Generate a hash based on a random string.

    Returns:
        A hash based on a random string.
    """
    random_characters = generate_random_password(10)
    return hashlib.md5(random_characters.encode("utf-8")).hexdigest()


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
        # Actions events
        self.framework.observe(
            self.on.get_cluster_admin_credentials_action, self._on_get_cluster_admin_credentials
        )
        self.framework.observe(
            self.on.get_server_config_credentials_action, self._on_get_server_config_credentials
        )
        self.framework.observe(self.on.get_root_credentials_action, self._on_get_root_credentials)
        self.framework.observe(self.on.get_cluster_status_action, self._get_cluster_status)

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

    def _on_leader_elected(self, _):
        """Handle the leader elected event.

        Set config values in the peer relation databag.
        """
        peer_data = self._peers.data[self.app]

        required_passwords = ["root-password", "server-config-password", "cluster-admin-password"]

        for required_password in required_passwords:
            if not peer_data.get(required_password):
                logger.debug(f"Setting {required_password}")
                password = generate_random_password(PASSWORD_LENGTH)
                peer_data[required_password] = password

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
                self._mysql._wait_until_mysql_connection()
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
            self._mysql._wait_until_mysql_connection()
            logger.info("Configuring instance")
            # Configure all base users and revoke
            # privileges from the root users
            self._mysql.configure_mysql_users()
            # Configure instance as a cluster node
            self._mysql.configure_instance()

        except (
            MySQLConfigureInstanceError,
            MySQLConfigureMySQLUsersError,
            MySQLInitialiseMySQLDError,
            MySQLCreateCustomConfigFileError,
        ) as e:
            self.unit.status = BlockedStatus("Unable to configure instance")
            logger.debug("Unable to configure instance: {}".format(e))
            return

        if self.unit.is_leader():
            try:
                # Create the cluster when is the leader unit
                self._mysql.create_cluster()
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

        new_instance = self._get_unit_fqdn(event.unit.name)

        # Check if new instance is ready to be added to the cluster
        if not self._mysql.is_instance_configured_for_innodb(new_instance):
            event.defer()
            return

        # Check if instance was already added to the cluster
        if self._mysql.is_instance_in_cluster(self._get_unit_hostname(event.unit.name)):
            logger.debug(f"Instance {new_instance} already in cluster")
            return

        # Add new instance to ipAllowlist global variable
        peer_data = self._peers.data[self.app]
        if new_instance not in peer_data.get("allowlist").split(","):
            peer_data["allowlist"] = f"{peer_data['allowlist']},{new_instance}"
            try:
                self._mysql.update_allowlist(peer_data["allowlist"])
            except MySQLUpdateAllowListError:
                logger.debug("Unable to update allowlist")
                event.defer()
                return

        # Add new instance to the cluster
        try:
            self._mysql.add_instance_to_cluster(new_instance)
            logger.debug(f"Added instance {new_instance} to cluster")

            # Update 'units-added-to-cluster' counter in the peer relation databag
            # in order to trigger a relation_changed event which will move the added unit
            # into ActiveStatus
            units_started = int(self._peers.data[self.app]["units-added-to-cluster"])
            self._peers.data[self.app]["units-added-to-cluster"] = str(units_started + 1)

        except MySQLAddInstanceToClusterError:
            logger.debug(f"Unable to add instance {new_instance} to cluster.")
            event.defer()

    def _on_peer_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the relation changed event."""
        # This handler is only taking care of setting
        # active status for secondary units
        if not self._is_peer_data_set:
            # Avoid running too early
            event.defer()
            return

        instance_cluster_address = self._get_unit_hostname(self.unit.name)
        # Test if non-leader unit is ready
        if isinstance(self.unit.status, WaitingStatus) and self._mysql.is_instance_in_cluster(
            instance_cluster_address
        ):
            self.unit.status = ActiveStatus()
            logger.debug(f"Instance {instance_cluster_address} is cluster member")

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
        event.set_results(self._mysql._get_cluster_status())


if __name__ == "__main__":
    main(MySQLOperatorCharm)
