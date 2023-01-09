#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
high availability of the MySQL charm.
"""

import logging
import subprocess
from typing import Dict, Optional

from charms.data_platform_libs.v0.database_requires import DatabaseRequires
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import ActiveStatus, Relation, WaitingStatus
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from connector import MySQLConnector  # isort: skip

logger = logging.getLogger(__name__)

DATABASE_NAME = "continuous_writes_database"
PEER = "application-peers"
PROC_PID_KEY = "proc-pid"
TABLE_NAME = "data"


class ContinuousWritesApplication(CharmBase):
    """Application charm that continuously writes to MySQL."""

    def __init__(self, *args):
        super().__init__(*args)

        # Charm events
        self.framework.observe(self.on.start, self._on_start)

        self.framework.observe(
            self.on.clear_continuous_writes_action, self._on_clear_continuous_writes_action
        )
        self.framework.observe(
            self.on.start_continuous_writes_action, self._on_start_continuous_writes_action
        )
        self.framework.observe(
            self.on.stop_continuous_writes_action, self._on_stop_continuous_writes_action
        )

        # Database related events
        self.database = DatabaseRequires(self, "database", DATABASE_NAME)
        self.framework.observe(self.database.on.database_created, self._on_database_created)
        self.framework.observe(self.database.on.endpoints_changed, self._on_endpoints_changed)

    # ==============
    # Properties
    # ==============

    @property
    def _peers(self) -> Optional[Relation]:
        """Retrieve the peer relation (`ops.model.Relation`)."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self) -> Dict:
        """Application peer relation data object."""
        if self._peers is None:
            return {}

        return self._peers.data[self.app]

    @property
    def _database_config(self):
        """Returns the database config to use to connect to the MySQL cluster."""
        data = list(self.database.fetch_relation_data().values())[0]
        username, password, endpoints = (
            data.get("username"),
            data.get("password"),
            data.get("endpoints"),
        )
        if None in [username, password, endpoints]:
            return {}

        [host, port] = endpoints.split(":")

        return {
            "user": username,
            "password": password,
            "host": host,
            "port": port,
            "database": DATABASE_NAME,
        }

    # ==============
    # Helpers
    # ==============

    def _start_continuous_writes(self, starting_number: int) -> None:
        """Start continuous writes to the MySQL cluster."""
        if not self._database_config:
            return

        self._stop_continuous_writes()

        # Run continuous writes in the background
        proc = subprocess.Popen(
            [
                "/usr/bin/python3",
                "src/continuous_writes.py",
                self._database_config["user"],
                self._database_config["password"],
                self._database_config["host"],
                self._database_config["port"],
                self._database_config["database"],
                TABLE_NAME,
                str(starting_number),
            ]
        )

        # Store the continuous writes process id in stored state to be able to stop it later
        self.app_peer_data[PROC_PID_KEY] = str(proc.pid)

    def _stop_continuous_writes(self) -> Optional[int]:
        """Stop continuous writes to the MySQL cluster and return the last written value."""
        if not self._database_config:
            return None

        if not self.app_peer_data.get(PROC_PID_KEY):
            return None

        # Send a SIGKILL to the process and wait for the process to exit
        proc = subprocess.Popen(["pkill", "--signal", "SIGKILL", "-f", "src/continuous_writes.py"])
        proc.communicate()

        del self.app_peer_data[PROC_PID_KEY]

        # Query and return the max value inserted in the database
        # (else -1 if unable to query)
        try:
            for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(5)):
                with attempt:
                    last_written_value = self._max_written_value()
        except RetryError as e:
            logger.exception("Unable to query the database", exc_info=e)
            return -1

        return last_written_value

    def _max_written_value(self) -> int:
        """Returns the count of rows in the continuous writes table."""
        if not self._database_config:
            return -1

        with MySQLConnector(self._database_config) as cursor:
            cursor.execute(f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{TABLE_NAME}`;")
            return cursor.fetchone()[0]

    # ==============
    # Handlers
    # ==============

    def _on_start(self, _) -> None:
        """Handle the start event."""
        self.unit.status = WaitingStatus()

    def _on_clear_continuous_writes_action(self, _) -> None:
        """Handle the clear continuous writes action event."""
        if not self._database_config:
            return

        self._stop_continuous_writes()
        with MySQLConnector(self._database_config) as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS `{DATABASE_NAME}`.`{TABLE_NAME}`;")

    def _on_start_continuous_writes_action(self, _) -> None:
        """Handle the start continuous writes action event."""
        if not self._database_config:
            return

        self._start_continuous_writes(1)

    def _on_stop_continuous_writes_action(self, event: ActionEvent) -> None:
        """Handle the stop continuous writes action event."""
        if not self._database_config:
            return event.set_results({"writes": 0})

        writes = self._stop_continuous_writes()
        event.set_results({"writes": writes})

    def _on_database_created(self, _) -> None:
        """Handle the database created event."""
        self._start_continuous_writes(1)
        self.unit.status = ActiveStatus()

    def _on_endpoints_changed(self, _) -> None:
        """Handle the database endpoints changed event."""
        count = self._max_written_value()
        self._start_continuous_writes(count + 1)


if __name__ == "__main__":
    main(ContinuousWritesApplication)
