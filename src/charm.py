#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for MySQL."""

import hashlib
import logging
import secrets
import string

from ops.charm import ActionEvent, CharmBase, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

from mysqlsh_helpers import (
    MySQL,
    MySQLBootstrapInstanceError,
    MySQLConfigureInstanceError,
    MySQLConfigureMySQLUsersError,
    MySQLCreateClusterError,
    MySQLPatchDNSSearchesError,
)

logger = logging.getLogger(__name__)

PASSWORD_LENGTH = 24
PEER = "database-peers"
CONFIGURED_FILE = "/var/lib/mysql/charmed"


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
        A length 10 hash based on a random string.
    """
    random_characters = generate_random_password(10)
    return hashlib.md5(random_characters.encode("utf-8")).hexdigest()


class MySQLOperatorCharm(CharmBase):
    """Operator framework charm for MySQL."""

    def __init__(self, *args):
        super().__init__(*args)
        self._mysqld_service = "mysqld"

        # Lifecycle events
        self.framework.observe(self.on.mysql_pebble_ready, self._on_mysql_pebble_ready)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on[PEER].relation_joined, self._on_peer_relation_joined)
        # Actions events
        self.framework.observe(
            self.on.get_generated_passwords_action, self._get_generated_passwords
        )

    @property
    def _peers(self):
        """Retrieve the peer relation (`ops.model.Relation`)."""
        return self.model.get_relation(PEER)

    @property
    def _mysql(self):
        """Returns an instance of the MySQL object from mysqlsh_helpers."""
        peer_data = self._peers.data[self.app]

        return MySQL(
            self._get_hostname_by_unit(self.unit.name),
            peer_data["cluster-name"],
            peer_data["root-password"],
            "serverconfig",
            peer_data["server-config-password"],
            "clusteradmin",
            peer_data["cluster-admin-password"],
            self.unit.get_container("mysql"),
        )

    @property
    def _pebble_layer(self) -> Layer:
        """Return a layer for the pebble service."""
        return Layer(
            {
                "summary": "mysqld layer",
                "description": "pebble config layer for mysqld",
                "services": {
                    self._mysqld_service: {
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

    def _get_hostname_by_unit(self, unit_name: str) -> str:
        """Create a DNS name for a unit.

        Translate juju unit name to resolvable hostname.

        Args:
            unit_name: unit name
        Returns:
            A string representing the hostname of the unit.
        """
        unit_id = unit_name.split("/")[1]
        return f"{self.app.name}-{unit_id}.{self.app.name}-endpoints"

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
                self.config.get("cluster-name") or f"cluster-{generate_random_hash()}"
            )

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

        if not peer_data.get("cluster-name"):
            peer_data["cluster-name"] = (
                self.config.get("cluster-name") or f"cluster-{generate_random_hash()}"
            )

        peer_data["configured"] = "True"

    def _on_mysql_pebble_ready(self, event):
        """Pebble ready handler.

        Define and start a pebble service and bootstrap instance.
        """
        if not self._peers or self._peers.data[self.app].get("configured", "False") != "True":
            self.unit.status = WaitingStatus("Waiting for leader election.")
            logger.debug("Leader not ready yet, waiting...")
            event.defer()
            return

        container = event.workload

        if not container.exists(CONFIGURED_FILE):
            # First run setup
            self.unit.status = MaintenanceStatus("Bootstrapping instance")
            try:
                # Allow mysql instances to reach each other
                self._mysql.patch_dns_searches(self.app.name)

                # Run mysqld for the first time to
                # bootstrap the data directory and users
                logger.debug("Bootstrapping instance")
                self._mysql.bootstrap_instance()

                # Add the pebble layer
                container.add_layer(self._mysqld_service, self._pebble_layer, combine=False)
                container.restart(self._mysqld_service)
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
                MySQLBootstrapInstanceError,
                MySQLPatchDNSSearchesError,
            ) as e:
                self.unit.status = BlockedStatus("Unable to configure instance")
                logger.debug("Unable to configure instance: {}".format(e))
                return

            if self.unit.is_leader():
                try:
                    # Create the cluster when
                    self._mysql.create_cluster()
                except MySQLCreateClusterError as e:
                    self.unit.status = BlockedStatus("Unable to create cluster")
                    logger.debug("Unable to create cluster: {}".format(e))
                    return
            else:
                # When unit is not the leader, it should wait
                # for the leader to configure it a cluster node
                self.unit.status = WaitingStatus("Waiting for peer relation join")

            # Create control file in data directory
            container.push(CONFIGURED_FILE, make_dirs=True, source="configured")

        else:
            # Configure the layer when changed
            current_layer = container.get_plan()
            new_layer = self._pebble_layer

            if new_layer.services != current_layer:
                logger.info("Add pebble layer")
                container.add_layer(self._mysqld_service, new_layer, combine=True)
                container.restart(self._mysqld_service)
                self._mysql._wait_until_mysql_connection()

        self.unit.status = ActiveStatus()

    def _on_peer_relation_joined(self, event: RelationJoinedEvent):
        """Handle the peer relation joined event."""
        # Only leader unit add instances to the cluster
        if not self.unit.is_leader():
            return

        new_instance = self._get_hostname_by_unit(event.unit.name)

        if not self._mysql.is_instance_configured_for_innodb(new_instance):
            event.defer()
            return

        # Add new instance to the cluster
        self._mysql.add_instance_to_cluster(new_instance)
        logger.debug(f"Added instance {new_instance} to cluster")

    # =========================================================================
    # Charm action handlers
    # =========================================================================
    def _get_generated_passwords(self, event: ActionEvent) -> None:
        event.set_results(
            {
                "cluster-admin-password": self._peers.data[self.app]["cluster-admin-password"],
                "root-password": self._peers.data[self.app]["root-password"],
                "server-config-password": self._peers.data[self.app]["server-config-password"],
            }
        )


if __name__ == "__main__":
    main(MySQLOperatorCharm)
