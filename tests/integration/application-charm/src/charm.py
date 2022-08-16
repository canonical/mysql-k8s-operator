#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
the database requires-provides relation.
"""

import logging
from typing import List, Tuple

from charms.data_platform_libs.v0.database_requires import (
    DatabaseCreatedEvent,
    DatabaseEndpointsChangedEvent,
    DatabaseRequires,
)
from connector import MysqlConnector
from ops.charm import CharmBase, RelationChangedEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus

logger = logging.getLogger(__name__)

PEER = "application-peers"
REMOTE = "database"


class ApplicationCharm(CharmBase):
    """Application charm that relates to MySQL charm."""

    def __init__(self, *args):
        super().__init__(*args)

        # Default charm events.
        self.framework.observe(self.on.start, self._on_start)

        # Events related to the requested database
        # (these events are defined in the database requires charm library).
        self.database_name = f'{self.app.name.replace("-", "_")}_test_database'
        self.database = DatabaseRequires(self, REMOTE, self.database_name)
        self.framework.observe(self.database.on.database_created, self._on_database_created)
        self.framework.observe(
            self.database.on.endpoints_changed, self._on_database_endpoints_changed
        )
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)
        self.framework.observe(self.on[REMOTE].relation_broken, self._on_database_broken)

    def _on_start(self, _) -> None:
        """Only sets an waiting status."""
        self.unit.status = WaitingStatus("Waiting for relation")

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Event triggered when a database was created for this application."""
        # Retrieve the credentials using the charm library.
        logger.info("Received database data")

        if not self.unit.is_leader():
            return

        # connection configuration
        config = {
            "user": event.username,
            "password": event.password,
            "host": event.endpoints.split(":")[0],
            "database": self.database_name,
            "raise_on_warnings": False,
        }

        with MysqlConnector(config) as cursor:
            self._create_test_table(cursor)

            self._insert_test_data(
                cursor,
                event.username,
                event.password,
                event.endpoints,
                event.version,
                event.read_only_endpoints,
            )

        self._peers.data[self.app]["inserted"] = "true"
        logger.info("Inserted relation data in database")
        self.unit.status = ActiveStatus()

    def _on_database_endpoints_changed(self, event: DatabaseEndpointsChangedEvent) -> None:
        """Event triggered when the read/write endpoints of the database change."""
        logger.info(f"first database endpoints have been changed to: {event.endpoints}")

    def _on_peer_relation_changed(self, event: RelationChangedEvent):
        """Handle peer relation changed.

        Check relation data against relation data inserted in the database
        from a read-only endpoint.
        """
        if self.unit.is_leader():
            # run from a non leader unit
            # to force consume data from relation databag
            return

        if "inserted" not in self._peers.data[self.app]:
            # run only after flag is set
            event.defer()
            return

        # get remote relation databag
        remote_relation = self.model.get_relation(REMOTE)
        if not remote_relation:
            event.defer()
            return

        remote_data = remote_relation.data[remote_relation.app]

        # parse read-only database host
        ro_database = remote_data["read-only-endpoints"].split(",")[0].split(":")[0]

        config = {
            "user": remote_data["username"],
            "password": remote_data["password"],
            "host": ro_database,
            "database": self.database_name,
            "raise_on_warnings": False,
        }

        with MysqlConnector(config, commit=False) as cursor:
            rows = self._read_test_data(cursor, remote_relation.id)
            first_row = rows[0]
            # username, password, endpoints, version, ro-endpoints
            assert first_row[1] == remote_data["username"]
            assert first_row[2] == remote_data["password"]
            assert first_row[3] == remote_data["endpoints"]
            assert first_row[4] == remote_data["version"]
            assert first_row[5] == remote_data["read-only-endpoints"]

        logger.info("Relation data replicated in the cluster")
        self.unit.status = ActiveStatus()

    def _on_database_broken(self, _):
        """Handle database relation broken."""
        # return to initial status
        self.unit.status = WaitingStatus("Waiting for relation")

        if not self.unit.is_leader():
            return
        # clear flag to allow complete process
        if "inserted" in self._peers.data[self.app]:
            self._peers.data[self.app].pop("inserted")

    def _create_test_table(self, cursor) -> None:
        """Creates a test table in the database."""
        cursor.execute(
            (
                "CREATE TABLE IF NOT EXISTS app_data ("
                "id SMALLINT not null auto_increment,"
                "username VARCHAR(255),"
                "password VARCHAR(255),"
                "endpoints VARCHAR(255),"
                "version VARCHAR(255),"
                "read_only_endpoints VARCHAR(255),"
                "PRIMARY KEY (id))"
            )
        )

    def _insert_test_data(
        self,
        cursor,
        username: str,
        password: str,
        endpoints: str,
        version: str,
        read_only_endpoints: str,
    ) -> None:
        """Inserts test data in the database."""
        cursor.execute(
            " ".join(
                (
                    "INSERT INTO app_data (",
                    "username, password, endpoints, version, read_only_endpoints)",
                    "VALUES (%s, %s, %s, %s, %s)",
                )
            ),
            (username, password, endpoints, version, read_only_endpoints),
        )

    def _read_test_data(self, cursor, relation_id) -> List[Tuple]:
        """Reads test data from the database."""
        cursor.execute(f"SELECT * FROM app_data where username = 'relation-{relation_id}'")
        return cursor.fetchall()

    @property
    def _peers(self):
        """Retrieve the peer relation (`ops.model.Relation`)."""
        return self.model.get_relation(PEER)


if __name__ == "__main__":
    main(ApplicationCharm)
