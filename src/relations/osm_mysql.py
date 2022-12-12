# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the legacy osm-mysql relation."""

import json
import logging

from charms.mysql.v0.mysql import (
    MySQLCheckUserExistenceError,
    MySQLDeleteUsersForUnitError,
)
from ops.charm import CharmBase, RelationBrokenEvent, RelationCreatedEvent
from ops.framework import Object
from ops.model import BlockedStatus

from constants import LEGACY_OSM_MYSQL, PASSWORD_LENGTH
from mysql_k8s_helpers import (
    MySQLCreateDatabaseError,
    MySQLCreateUserError,
    MySQLEscalateUserPrivilegesError,
)
from utils import generate_random_password

logger = logging.getLogger(__name__)


class MySQLOSMRelation(Object):
    """Encapsulation of the legacy osm-mysql relation."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, LEGACY_OSM_MYSQL)

        self.charm = charm

        self.framework.observe(self.charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            self.charm.on[LEGACY_OSM_MYSQL].relation_created, self._on_osm_mysql_relation_created
        )
        self.framework.observe(
            self.charm.on[LEGACY_OSM_MYSQL].relation_broken, self._on_osm_mysql_relation_broken
        )

    def _get_password_from_peer_databag(self, username: str) -> str:
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

        Retrieves relation data from the peer relation databag and copies
        the relation data into the new leader unit's databag.
        """
        # Skip if the charm is not past the setup phase (config-changed event not executed yet)
        if not self.charm._is_peer_data_set:
            return

        relation_data = json.loads(self.charm.app_peer_data.get("osm_mysql_relation_data", "{}"))

        for relation in self.charm.model.relations.get(LEGACY_OSM_MYSQL, []):
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

            relation_databag[self.charm.unit]["host"] = primary_address.split(":")[0]

    def _on_osm_mysql_relation_created(self, event: RelationCreatedEvent) -> None:
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

        logger.warning("DEPRECATION WARNING - `osm-mysql` is a legacy interface")

        username = self.charm.config.get("osm-mysql-interface-user")
        database = self.charm.config.get("osm-mysql-interface-database")

        # Ensure that config values exist, else we will be unable to create database and user
        if not username or not database:
            self.charm.unit.status = BlockedStatus("Missing `osm-mysql` relation data")
            return

        user_exists = False
        try:
            user_exists = self.charm._mysql.does_mysql_user_exist(username, "%")
        except MySQLCheckUserExistenceError:
            self.charm.unit.status = BlockedStatus("Failed to check user existence")
            return

        # Only execute if the application user does not exist
        if user_exists:
            osm_mysql_relation_data = self.charm.app_peer_data["osm_mysql_relation_data"]

            updates = json.loads(osm_mysql_relation_data)
            event.relation.data[self.charm.unit].update(updates)

            return

        password = self._get_password_from_peer_databag(username)

        try:
            self.charm._mysql.create_database(database)
            self.charm._mysql.create_user(username, password, "osm-mysql-legacy-relation")
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
            "host": primary_address.split(":")[0],
            "password": password,
            "port": "3306",
            "root_password": self.charm.app_peer_data["root-password"],
            "user": username,
        }

        event.relation.data[self.charm.unit].update(updates)

        # Store the relation data into the peer relation databag
        self.charm.app_peer_data["osm_mysql_relation_data"] = json.dumps(updates)

    def _on_osm_mysql_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the 'mysql' legacy relation broken event.

        Delete the application user created in the relation created
        event handler.
        """
        if not self.charm.unit.is_leader():
            return

        # Only execute if the last `osm-mysql` relation is broken
        # as there can be multiple applications using the same relation interface
        if len(self.charm.model.relations[LEGACY_OSM_MYSQL]) > 1:
            return

        logger.warning("DEPRECATION WARNING - `osm-mysql` is a legacy interface")

        try:
            self.charm._mysql.delete_users_with_label("label", "osm-mysql-legacy-relation")
        except MySQLDeleteUsersForUnitError:
            self.charm.unit.status = BlockedStatus("Failed to delete database users")
