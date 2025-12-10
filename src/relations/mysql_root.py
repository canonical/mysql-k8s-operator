# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the legacy mysql-root relation."""

import json
import logging
import typing

from charms.mysql.v0.mysql import MySQLCheckUserExistenceError, MySQLDeleteUsersForUnitError
from ops.charm import (
    LeaderElectedEvent,
    RelationBrokenEvent,
    RelationCreatedEvent,
)
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus

from constants import CONTAINER_NAME, LEGACY_MYSQL_ROOT, PASSWORD_LENGTH, ROOT_PASSWORD_KEY
from mysql_k8s_helpers import (
    MySQLCreateDatabaseError,
    MySQLCreateUserError,
    MySQLEscalateUserPrivilegesError,
)
from utils import generate_random_password

logger = logging.getLogger(__name__)

MYSQL_ROOT_RELATION_DATA_KEY = "mysql_root_relation_data"
MYSQL_ROOT_RELATION_USER_KEY = "mysql-root-interface-user"
MYSQL_ROOT_RELATION_DATABASE_KEY = "mysql-root-interface-database"

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm


class MySQLRootRelation(Object):
    """Encapsulation of the legacy mysql-root relation."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, LEGACY_MYSQL_ROOT)

        self.charm = charm

        self.framework.observe(self.charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.charm.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.charm.on[LEGACY_MYSQL_ROOT].relation_created, self._on_mysql_root_relation_created
        )
        self.framework.observe(
            self.charm.on[LEGACY_MYSQL_ROOT].relation_broken, self._on_mysql_root_relation_broken
        )

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
            MYSQL_ROOT_RELATION_USER_KEY,
            self.charm.config.mysql_root_interface_user or f"relation-{event_relation_id}",
        )

    def _get_or_generate_database(self, event_relation_id: int) -> str:
        """Retrieve database from databag or config or generate a new one.

        Assumes that the caller is the leader unit.
        """
        return self.charm.app_peer_data.setdefault(
            MYSQL_ROOT_RELATION_DATABASE_KEY,
            self.charm.config.mysql_root_interface_database or f"database-{event_relation_id}",
        )

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handle the leader elected event.

        Retrieves relation data from the peer relation databag and copies
        the relation data into the new leader unit's databag.
        """
        # Wait until on-config-changed event is executed (for root password to have been set)
        # and for the member to be initialized and online
        if (
            not self.charm._is_peer_data_set
            or not self.charm.unit_initialized()
            or self.charm.unit_peer_data.get("member-state") != "online"
        ):
            logger.info("Unit not ready to execute `mysql` leader elected. Deferring")
            event.defer()
            return

        relation_data = json.loads(
            self.charm.app_peer_data.get(MYSQL_ROOT_RELATION_DATA_KEY, "{}")
        )

        for relation in self.charm.model.relations.get(LEGACY_MYSQL_ROOT, []):
            relation_databag = relation.data

            # Copy relation data into the new leader unit's databag
            for key, value in relation_data.items():
                if relation_databag[self.charm.unit].get(key) != value:
                    relation_databag[self.charm.unit][key] = value

            # Assign the cluster primary's address as the database host
            primary_address = self.charm._mysql.get_cluster_primary_address()
            if not primary_address:
                self.charm.unit.status = BlockedStatus(
                    "Failed to retrieve cluster primary address"
                )
                return

            relation_databag[self.charm.unit]["host"] = primary_address

    def _on_config_changed(self, _) -> None:
        """Handle the change of the username/database config."""
        if not self.charm.unit.is_leader():
            return

        if not (
            self.charm.app_peer_data.get(MYSQL_ROOT_RELATION_USER_KEY)
            and self.charm.app_peer_data.get(MYSQL_ROOT_RELATION_DATABASE_KEY)
        ):
            return

        active_and_related = isinstance(
            self.charm.unit.status, ActiveStatus
        ) and self.model.relations.get(LEGACY_MYSQL_ROOT)

        if active_and_related and (
            self.charm.config.mysql_root_interface_database
            != self.charm.app_peer_data[MYSQL_ROOT_RELATION_DATABASE_KEY]
            or self.charm.config.mysql_root_interface_user
            != self.charm.app_peer_data[MYSQL_ROOT_RELATION_USER_KEY]
        ):
            self.charm.app.status = BlockedStatus(
                "Remove and re-relate `mysql` relations in order to change config"
            )

    def _on_mysql_root_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handle the legacy 'mysql-root' relation created event.

        Will set up the database and the scoped application user. The connection
        data (relation data) is then copied into the peer relation databag (to
        be copied over to the new leader unit's databag in case of a new leader
        being elected).
        """
        if not self.charm.unit.is_leader():
            return

        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.defer()
            return

        # Wait until on-config-changed event is executed
        # (wait for root password to have been set) or wait until the unit is initialized
        if not (self.charm._is_peer_data_set and self.charm.unit_initialized()):
            event.defer()
            return

        logger.warning("DEPRECATION WARNING - `mysql-root` is a legacy interface")

        username = self._get_or_generate_username(event.relation.id)
        database = self._get_or_generate_database(event.relation.id)

        user_exists = False
        try:
            user_exists = self.charm._mysql.does_mysql_user_exist(username, "%")
        except MySQLCheckUserExistenceError:
            self.charm.unit.status = BlockedStatus("Failed to check user existence")
            return

        # Only execute if the application user does not exist
        # since it could have been created by another related app
        if user_exists:
            mysql_root_relation_data = self.charm.app_peer_data[MYSQL_ROOT_RELATION_DATA_KEY]

            updates = json.loads(mysql_root_relation_data)
            event.relation.data[self.charm.unit].update(updates)

            return

        password = self._get_or_set_password_in_peer_secrets(username)

        try:
            root_password = self.charm.get_secret("app", ROOT_PASSWORD_KEY)
            if not root_password:
                raise MySQLCreateUserError("MySQL root password not found in peer secrets")

            self.charm._mysql.create_database_legacy(database)
            self.charm._mysql.create_user_legacy(username, password, "mysql-root-legacy-relation")
            if not self.charm._mysql.does_mysql_user_exist("root", "%"):
                # create `root@%` user if it doesn't exist
                # this is needed for the `mysql-root` interface to work
                self.charm._mysql.create_user_legacy(
                    "root",
                    root_password,
                    "mysql-root-legacy-relation",
                )
            self.charm._mysql.escalate_user_privileges("root")
            self.charm._mysql.escalate_user_privileges(username)
        except (MySQLCreateDatabaseError, MySQLCreateUserError, MySQLEscalateUserPrivilegesError):
            self.charm.unit.status = BlockedStatus("Failed to create relation database and users")
            return

        primary_address = self.charm._mysql.get_cluster_primary_address()
        if not primary_address:
            self.charm.unit.status = BlockedStatus(
                "Failed to retrieve the cluster primary address"
            )

        updates = {
            "database": database,
            "host": primary_address,
            "password": password,
            "port": "3306",
            "root_password": root_password,
            "user": username,
        }

        event.relation.data[self.charm.unit].update(updates)

        self.charm.app_peer_data[MYSQL_ROOT_RELATION_USER_KEY] = username
        self.charm.app_peer_data[MYSQL_ROOT_RELATION_DATABASE_KEY] = database

        # Store the relation data into the peer relation databag
        self.charm.app_peer_data[MYSQL_ROOT_RELATION_DATA_KEY] = json.dumps(updates)

    def _on_mysql_root_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the 'mysql-root' legacy relation broken event.

        Delete the application user created in the relation created
        event handler.
        """
        if not self.charm.unit.is_leader():
            return

        # Only execute if the last `mysql-root` relation is broken
        # as there can be multiple applications using the same relation interface
        if len(self.charm.model.relations[LEGACY_MYSQL_ROOT]) > 1:
            return

        logger.warning("DEPRECATION WARNING - `mysql-root` is a legacy interface")

        try:
            self.charm._mysql.delete_users_with_label("label", "mysql-root-legacy-relation")
        except MySQLDeleteUsersForUnitError:
            self.charm.unit.status = BlockedStatus("Failed to delete database users")

        del self.charm.app_peer_data[MYSQL_ROOT_RELATION_USER_KEY]
        del self.charm.app_peer_data[MYSQL_ROOT_RELATION_DATABASE_KEY]

        del self.charm.app_peer_data[MYSQL_ROOT_RELATION_DATA_KEY]

        if isinstance(
            self.charm.app.status, BlockedStatus
        ) and self.charm.app.status.message.startswith(
            "Remove `mysql-root` relations in order to change"
        ):
            self.charm.app.status = ActiveStatus()
