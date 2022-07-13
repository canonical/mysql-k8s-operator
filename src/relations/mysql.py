# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the legacy mysql relation."""

import json
import logging

from ops.charm import RelationBrokenEvent, RelationCreatedEvent
from ops.framework import Object

from constants import LEGACY_MYSQL, PASSWORD_LENGTH
from utils import generate_random_password

logger = logging.getLogger(__name__)


class MySQLRelation(Object):
    """Encapsulation of the legacy mysql relation."""

    def __init__(self, charm):
        super().__init__(charm, LEGACY_MYSQL)

        self.charm = charm

        self.framework.observe(self.charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            self.charm.on[LEGACY_MYSQL].relation_created, self._on_mysql_relation_created
        )

        # TODO: uncomment once https://bugs.launchpad.net/juju/+bug/1951415 has been resolved
        # self.framework.observe(
        #     self.charm.on[LEGACY_MYSQL].relation_broken, self._on_mysql_relation_broken
        # )

    def _get_or_set_password_in_peer_databag(self, username: str) -> str:
        """Get a user's password from the peer databag if it exists, else populate a password.

        Args:
            username: The mysql username

        Returns:
            a string representing the password for the mysql user
        """
        peer_databag = self.charm._peers.data[self.charm.app]

        if peer_databag.get(f"{username}_password"):
            return peer_databag.get(f"{username}_password")

        password = generate_random_password(PASSWORD_LENGTH)
        peer_databag[f"{username}_password"] = password

        return password

    def _on_leader_elected(self, _) -> None:
        """Handle the leader elected event.

        Retrieves relation data from the peer relation databag and copies
        the relation data into the new leader unit's databag.
        """
        # Skip if the charm is not past the setup phase (config-changed event not executed yet)
        if not self.charm._is_peer_data_set:
            return

        relation_data = json.loads(
            self.charm._peers.data[self.charm.app].get("mysql_relation_data")
        )

        for relation in self.charm.model.relations.get(LEGACY_MYSQL, []):
            relation_databag = relation.data

            # Copy relation data into the new leader unit's databag
            for key, value in relation_data.items():
                if relation_databag[self.charm.unit].get(key) != value:
                    relation_databag[self.charm.unit][key] = value

            # Assign the cluster primary's address as the database host
            primary_address = self.charm._mysql.get_cluster_primary_address().split(":")[0]
            relation_databag[self.charm.unit]["host"] = primary_address

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

        username = self.charm.config.get("user")
        database = self.charm.config.get("database")

        if not username or not database:
            event.defer()
            return

        # Only execute if the application user does not exist
        if self.charm._mysql.does_mysql_user_exist(username, "%"):
            return

        password = self._get_or_set_password_in_peer_databag(username)

        self.charm._mysql.create_application_database_and_scoped_user(
            database,
            username,
            password,
            "%",
            "mysql-legacy-relation",
        )

        primary_address = self.charm._mysql.get_cluster_primary_address().split(":")[0]
        updates = {
            "database": database,
            "host": primary_address,
            "password": password,
            "port": "3306",
            "root_password": self.charm._peers.data[self.charm.app]["root-password"],
            "user": username,
        }

        event.relation.data[self.charm.unit].update(updates)

        # Store the relation data into the peer relation databag
        self.charm._peers.data[self.charm.app]["mysql_relation_data"] = json.dumps(updates)

    def _on_mysql_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the 'mysql' legacy relation broken event.

        Delete the application user created in the relation created
        event handler.
        """
        if not self.charm.unit.is_leader():
            return

        logger.warning("DEPRECATION WARNING - `mysql` is a legacy interface")

        self.charm._mysql.delete_users_for_unit("mysql-legacy-relation")
