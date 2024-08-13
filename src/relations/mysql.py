# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the legacy mysql relation."""

import json
import logging
import typing

from charms.mysql.v0.mysql import (
    MySQLCheckUserExistenceError,
    MySQLCreateApplicationDatabaseAndScopedUserError,
    MySQLDeleteUsersForUnitError,
)
from ops.charm import RelationBrokenEvent, RelationChangedEvent, RelationCreatedEvent
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus

from constants import CONTAINER_NAME, LEGACY_MYSQL, PASSWORD_LENGTH, PEER, ROOT_PASSWORD_KEY
from utils import generate_random_password

logger = logging.getLogger(__name__)

MYSQL_RELATION_DATA_KEY = "mysql_relation_data"
MYSQL_RELATION_USER_KEY = "mysql-interface-user"
MYSQL_RELATION_DATABASE_KEY = "mysql-interface-database"

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm


class MySQLRelation(Object):
    """Encapsulation of the legacy mysql relation."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, LEGACY_MYSQL)

        self.charm = charm

        self.framework.observe(self.charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.charm.on.config_changed, self._on_config_changed)
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

    def _get_or_set_password_in_peer_secrets(self, username: str) -> str:
        """Get a user's password from the peer secrets, if it exists, else populate a password.

        Args:
            username: The mysql username

        Returns:
            a string representing the password for the mysql user
        """
        password_key = f"{username}-password"
        password = self.charm.get_secret("app", password_key)
        if password:
            return password

        password = generate_random_password(PASSWORD_LENGTH)
        self.charm.set_secret("app", password_key, password)
        return password

    def _get_or_generate_username(self, event_relation_id: int) -> str:
        """Retrieve username from databag or config or generate a new one.

        Assumes that the caller is the leader unit.
        """
        return self.charm.app_peer_data.setdefault(
            MYSQL_RELATION_USER_KEY,
            self.charm.config.mysql_interface_user or f"relation-{event_relation_id}",
        )

    def _get_or_generate_database(self, event_relation_id: int) -> str:
        """Retrieve database from databag or config or generate a new one.

        Assumes that the caller is the leader unit.
        """
        return self.charm.app_peer_data.setdefault(
            MYSQL_RELATION_DATABASE_KEY,
            self.charm.config.mysql_interface_database or f"database-{event_relation_id}",
        )

    def _on_config_changed(self, _) -> None:
        """Handle the change of the username/database config."""
        if not self.charm.unit.is_leader():
            return

        if not (
            self.charm.app_peer_data.get(MYSQL_RELATION_USER_KEY)
            and self.charm.app_peer_data.get(MYSQL_RELATION_DATABASE_KEY)
        ):
            return

        if isinstance(self.charm.unit.status, ActiveStatus) and self.model.relations.get(
            LEGACY_MYSQL
        ):
            if (
                self.charm.config.mysql_interface_database
                != self.charm.app_peer_data[MYSQL_RELATION_DATABASE_KEY]
                or self.charm.config.mysql_interface_user
                != self.charm.app_peer_data[MYSQL_RELATION_USER_KEY]
            ):
                self.charm.app.status = BlockedStatus(
                    "Remove and re-relate `mysql` relations in order to change config"
                )

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
        if not (relation_data := self.charm.app_peer_data.get(MYSQL_RELATION_DATA_KEY)):
            return

        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        if not self.charm.unit_initialized:
            # Skip update status for uninitialized unit
            return

        if not self.charm.unit.is_leader():
            return

        host = json.loads(relation_data)["host"]

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
        if not self.model.get_relation(LEGACY_MYSQL):
            return

        if not (self.charm._is_peer_data_set and self.charm.unit_initialized):
            # Avoid running too early
            logger.info("Unit not ready to set `mysql` relation data. Deferring")
            event.defer()
            return

        if not (relation_data := self.charm.app_peer_data.get(MYSQL_RELATION_DATA_KEY)):
            logger.debug("No `mysql` relation data present")
            return

        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            logger.info("Cannot connect to the workload container")
            return

        updates = json.loads(relation_data)

        # Update the host (in case it has changed)
        primary_address = self.charm._mysql.get_cluster_primary_address()
        if not primary_address:
            logger.error("Unable to query the cluster primary address")
            self.charm.unit.status = BlockedStatus("Failed to retrieve cluster primary address")
            return
        updates["host"] = primary_address.split(":")[0]

        self.model.get_relation(LEGACY_MYSQL).data[self.charm.unit].update(updates)

    def _on_mysql_relation_created(self, event: RelationCreatedEvent) -> None:  # noqa: C901
        """Handle the legacy 'mysql' relation created event.

        Will set up the database and the scoped application user. The connection
        data (relation data) is then copied into the peer relation databag (to
        be copied over to the new leader unit's databag in case of a new leader
        being elected).
        """
        if not self.charm.unit.is_leader():
            logger.info("Unit is not leader, nooping `mysql` relation created")
            return

        # Wait until on-config-changed event is executed (for root password to have been set)
        # and for the member to be initialized and online
        if (
            not self.charm._is_peer_data_set
            or not self.charm.unit_initialized
            or self.charm.unit_peer_data.get("member-state") != "online"
        ):
            logger.info("Unit not ready to execute `mysql` relation created. Deferring")
            event.defer()
            return

        logger.warning("DEPRECATION WARNING - `mysql` is a legacy interface")

        username = self._get_or_generate_username(event.relation.id)
        database = self._get_or_generate_database(event.relation.id)

        user_exists = False
        try:
            logger.info(f"Checking if mysql user {username} exists")
            user_exists = self.charm._mysql.does_mysql_user_exist(username, "%")
        except MySQLCheckUserExistenceError:
            self.charm.unit.status = BlockedStatus("Failed to check user existence")
            return

        # Only execute if the application user does not exist
        if user_exists:
            logger.info(f"mysql user {username} exists. nooping")
            mysql_relation_data = self.charm.app_peer_data[MYSQL_RELATION_DATA_KEY]

            updates = json.loads(mysql_relation_data)
            event.relation.data[self.charm.unit].update(updates)

            return

        password = self._get_or_set_password_in_peer_secrets(username)

        try:
            logger.info("Creating application database and scoped user")
            self.charm._mysql.create_application_database_and_scoped_user(
                database,
                username,
                password,
                "%",
                unit_name="mysql-legacy-relation",
            )
        except MySQLCreateApplicationDatabaseAndScopedUserError:
            self.charm.unit.status = BlockedStatus(
                "Failed to create application database and scoped user"
            )
            return

        primary_address = self.charm._mysql.get_cluster_primary_address()
        if not primary_address:
            logger.error("Unable to get cluster primary address")
            self.charm.unit.status = BlockedStatus("Failed to retrieve cluster primary address")

        updates = {
            "database": database,
            "host": primary_address.split(":")[0],
            "password": password,
            "port": "3306",
            "root_password": self.charm.get_secret("app", ROOT_PASSWORD_KEY),
            "user": username,
        }

        self.charm.app_peer_data[MYSQL_RELATION_USER_KEY] = username
        self.charm.app_peer_data[MYSQL_RELATION_DATABASE_KEY] = database

        self.charm.app_peer_data[MYSQL_RELATION_DATA_KEY] = json.dumps(updates)

    def _on_mysql_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the 'mysql' legacy relation broken event.

        Delete the application user created in the relation created
        event handler.
        """
        if not self.charm.unit.is_leader():
            logger.info("Unit is not leader, nooping `mysql` relation broken")
            return

        # Only execute if the last `mysql` relation is broken
        # as there can be multiple applications using the same relation interface
        if len(self.charm.model.relations[LEGACY_MYSQL]) > 1:
            logger.info("More than one `mysql` relations present. Not deleting user for unit")
            return

        logger.warning("DEPRECATION WARNING - `mysql` is a legacy interface")

        try:
            logger.info("Deleting users for unit (`mysql` relation)")
            self.charm._mysql.delete_users_for_unit("mysql-legacy-relation")
        except MySQLDeleteUsersForUnitError:
            self.charm.unit.status = BlockedStatus("Failed to delete users for unit")

        del self.charm.app_peer_data[MYSQL_RELATION_USER_KEY]
        del self.charm.app_peer_data[MYSQL_RELATION_DATABASE_KEY]

        del self.charm.app_peer_data[MYSQL_RELATION_DATA_KEY]

        if isinstance(
            self.charm.app.status, BlockedStatus
        ) and self.charm.app.status.message.startswith(
            "Remove `mysql` relations in order to change"
        ):
            self.charm.app.status = ActiveStatus()
