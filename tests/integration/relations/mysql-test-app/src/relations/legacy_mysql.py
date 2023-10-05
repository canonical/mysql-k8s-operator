# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Module for handling legacy MySQL/MariaDB relations."""

import logging

from literals import DATABASE_NAME, LEGACY_MYSQL_RELATION
from ops.framework import Object
from ops.model import BlockedStatus

logger = logging.getLogger(__name__)


class LegacyMySQL(Object):
    """Class for handling legacy MySQL/MariaDB relations."""

    def __init__(self, charm):
        super().__init__(charm, LEGACY_MYSQL_RELATION)
        self.charm = charm

        self.framework.observe(
            charm.on[LEGACY_MYSQL_RELATION].relation_joined, self._on_relation_joined
        )
        self.framework.observe(
            charm.on[LEGACY_MYSQL_RELATION].relation_broken, self._on_relation_broken
        )
        self.framework.observe(
            charm.on.get_legacy_mysql_credentials_action, self._get_legacy_mysql_credentials
        )

    def _on_relation_joined(self, event):
        if not self.charm.unit.is_leader():
            # only leader handles the relation data
            return

        if not self.model.get_relation(LEGACY_MYSQL_RELATION):
            # Relation departed before joined event
            logger.debug("Relation departed")
            return

        # On legacy MariaDB, the relation data is stored on
        # leader unit databag only.
        try:
            relation_data = event.relation.data[event.unit]
        except KeyError:
            logger.debug("Relation departed")
            return

        if "user" not in relation_data:
            if f"{LEGACY_MYSQL_RELATION}-user" in self.charm.app_peer_data:
                # If user set, relation joined already handled
                return
            logger.debug("Mysql legacy relation data not ready yet. Deferring event.")
            event.defer()
            return

        database_name = relation_data["database"]
        if database_name != DATABASE_NAME:
            logger.error(f"Database name must be set to `{DATABASE_NAME}`. Modify the test.")
            self.charm.unit.status = BlockedStatus("Wrong database name")
            return

        # Dump data into peer relation
        self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-user"] = relation_data["user"]
        self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-password"] = relation_data["password"]
        self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-host"] = relation_data["host"]
        self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-database"] = database_name

        # Set database-start to true to trigger common post relation tasks
        self.charm.app_peer_data["database-start"] = "true"

    def _on_relation_broken(self, _):
        if not self.charm.unit.is_leader():
            # only leader handles the relation data
            return
        # Clear data from peer relation
        self.charm.app_peer_data.pop(f"{LEGACY_MYSQL_RELATION}-user", None)
        self.charm.app_peer_data.pop(f"{LEGACY_MYSQL_RELATION}-password", None)
        self.charm.app_peer_data.pop(f"{LEGACY_MYSQL_RELATION}-host", None)
        self.charm.app_peer_data.pop(f"{LEGACY_MYSQL_RELATION}-database", None)

    def _get_legacy_mysql_credentials(self, event) -> None:
        """Retrieve legacy mariadb credentials."""
        event.set_results(
            {
                "username": self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-user"],
                "password": self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-password"],
                "host": self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-host"],
                "database": self.charm.app_peer_data[f"{LEGACY_MYSQL_RELATION}-database"],
            }
        )
