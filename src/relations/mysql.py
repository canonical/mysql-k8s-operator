# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the legacy mysql relation."""

import json
import logging

from charms.mysql.v0.mysql import (
    MySQLCheckUserExistenceError,
    MySQLCreateApplicationDatabaseAndScopedUserError,
    MySQLDeleteUsersForUnitError,
)
from ops.charm import (
    CharmBase,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
)
from ops.framework import Object
from ops.model import BlockedStatus

from constants import LEGACY_MYSQL, PASSWORD_LENGTH, PEER
from utils import generate_random_password

logger = logging.getLogger(__name__)


class MySQLRelation(Object):
    """Encapsulation of the legacy mysql relation."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, LEGACY_MYSQL)

        self.charm = charm

        self.framework.observe(self.charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            self.charm.on[LEGACY_MYSQL].relation_created, self._on_mysql_relation_created
        )
        self.framework.observe(
            self.charm.on[LEGACY_MYSQL].relation_broken, self._on_mysql_relation_broken
        )
        self.framework.observe(
            self.charm.on[PEER].relation_changed, self._on_peer_relation_changed
        )
        self.framework.observe(self.charm.on.update_status, self._update_status)

    def _get_or_set_password_in_peer_databag(self, username: str) -> str:
        """Get a user's password from the peer databag if it exists, else populate a password.

        Args:
            username: The mysql username

        Returns:
            a string representing the password for the mysql user
        """
        if self.charm.app_peer_data.get(f"{username}_password"):
            return self.charm.app_peer_data.get(f"{username}_password")

        password = generate_random_password(PASSWORD_LENGTH)
        self.charm.app_peer_data[f"{username}_password"] = password

        return password

    def _on_leader_elected(self, _) -> None:
        """Handle the leader elected event.

        Updates a key in the peer relation databag in order to trigger the peer
        relation changed event.
        """
        # Skip if the charm is not past the setup phase (config-changed event not executed yet)
        if not self.charm._is_peer_data_set:
            return

        # Trigger a peer relation changed event in order to refresh the relation data
        leader_elected_count = int(self.charm.app_peer_data.get("leader_elected_count", "1"))
        self.charm.app_peer_data["leader_elected_count"] = str(leader_elected_count + 1)

    def _update_status(self, _) -> None:
        """Handle the update status event.

        Compares the current host (in relation data) with the current primary.
        If they are different, changes a key in the peer relation databag in order
        to trigger the peer relation changed event.
        """
        if not (relation_data := json.loads(self.charm.app_peer_data.get("mysql_relation_data"))):
            return

        host = relation_data["host"]

        primary_address = self.charm._mysql.get_cluster_primary_address()
        if not primary_address:
            self.charm.unit.status = BlockedStatus("Failed to retrieve cluster primary address")
            return

        if host != primary_address.split(":")[0]:
            # Trigger a peer relation changed event in order to refresh the relation data
            update_status_count = int(self.charm.app_peer_data.get("update_status_count", "0"))
            self.charm.app_peer_data["update_status_count"] = str(update_status_count + 1)

    def _on_peer_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the peer relation changed event.

        Stores and refreshes the relation data on all units (as some consumer
        applications retrieve the relation data from random units).
        """
        if not self.charm._is_peer_data_set:
            # Avoid running too early
            event.defer()
            return

        if not (relation_data := self.charm.app_peer_data.get("mysql_relation_data")):
            return

        updates = json.loads(relation_data)

        # Update the host (in case it has changed)
        primary_address = self.charm._mysql.get_cluster_primary_address()
        if not primary_address:
            self.charm.unit.status = BlockedStatus("Failed to retrieve cluster primary address")
            return
        updates["host"] = primary_address.split(":")[0]

        self.model.get_relation(LEGACY_MYSQL).data[self.charm.unit].update(updates)

    def _on_mysql_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handle the legacy 'mysql' relation created event.

        Will set up the database and the scoped application user. The connection
        data (relation data) is then copied into the peer relation databag (to
        be copied over to the new leader unit's databag in case of a new leader
        being elected).
        """
        if not self.charm.unit.is_leader():
            return

        # Wait until on-config-changed event is executed
        # (wait for root password to have been set)
        if not self.charm._is_peer_data_set:
            event.defer()
            return

        logger.warning("DEPRECATION WARNING - `mysql` is a legacy interface")

        username = self.charm.config.get("mysql-interface-user")
        database = self.charm.config.get("mysql-interface-database")

        # Only execute handler if config values are set
        # else we'd be unable to create database and user
        if not username or not database:
            self.charm.unit.status = BlockedStatus("Missing `mysql` relation data")
            return

        user_exists = False
        try:
            user_exists = self.charm._mysql.does_mysql_user_exist(username, "%")
        except MySQLCheckUserExistenceError:
            self.charm.unit.status = BlockedStatus("Failed to check user existence")
            return

        # Only execute if the application user does not exist
        if user_exists:
            return

        password = self._get_or_set_password_in_peer_databag(username)

        try:
            self.charm._mysql.create_application_database_and_scoped_user(
                database,
                username,
                password,
                "%",
                "mysql-legacy-relation",
            )
        except MySQLCreateApplicationDatabaseAndScopedUserError:
            self.charm.unit.status = BlockedStatus(
                "Failed to create application database and scoped user"
            )
            return

        primary_address = self.charm._mysql.get_cluster_primary_address()
        if not primary_address:
            self.charm.unit.status = BlockedStatus("Failed to retrieve cluster primary address")

        updates = {
            "database": database,
            "host": primary_address.split(":")[0],
            "password": password,
            "port": "3306",
            "root_password": self.charm.app_peer_data["root-password"],
            "user": username,
        }

        self.charm.app_peer_data["mysql_relation_data"] = json.dumps(updates)

    def _on_mysql_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the 'mysql' legacy relation broken event.

        Delete the application user created in the relation created
        event handler.
        """
        if not self.charm.unit.is_leader():
            return

        # Only execute if the last `osm-mysql` relation is broken
        # as there can be multiple applications using the same relation interface
        if len(self.charm.model.relations[LEGACY_MYSQL]) > 1:
            return

        logger.warning("DEPRECATION WARNING - `mysql` is a legacy interface")

        try:
            self.charm._mysql.delete_users_for_unit("mysql-legacy-relation")
        except MySQLDeleteUsersForUnitError:
            self.charm.unit.status = BlockedStatus("Failed to delete users for unit")
