#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
high availability of the MySQL charm.
"""

import logging
import re
import secrets
import string
import subprocess
from typing import Dict, Optional

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from literals import (
    CONTINUOUS_WRITE_TABLE_NAME,
    DATABASE_NAME,
    DATABASE_RELATION,
    LEGACY_MYSQL_RELATION,
    PEER,
    PROC_PID_KEY,
    RANDOM_VALUE_KEY,
    RANDOM_VALUE_TABLE_NAME,
)
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import ActiveStatus, Relation, WaitingStatus
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from relations.legacy_mysql import LegacyMySQL

from connector import MySQLConnector  # isort: skip

logger = logging.getLogger(__name__)


class MySQLTestApplication(CharmBase):
    """Application charm that continuously writes to MySQL."""

    def __init__(self, *args):
        super().__init__(*args)

        # Charm events
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)

        # Action handlers
        self.framework.observe(
            getattr(self.on, "clear_continuous_writes_action"),
            self._on_clear_continuous_writes_action,
        )
        self.framework.observe(
            getattr(self.on, "start_continuous_writes_action"),
            self._on_start_continuous_writes_action,
        )
        self.framework.observe(
            getattr(self.on, "stop_continuous_writes_action"),
            self._on_stop_continuous_writes_action,
        )

        self.framework.observe(
            getattr(self.on, "get_inserted_data_action"), self._get_inserted_data
        )

        self.framework.observe(
            getattr(self.on, "get_session_ssl_cipher_action"), self._get_session_ssl_cipher
        )

        self.framework.observe(
            getattr(self.on, "get_server_certificate_action"), self._get_server_certificate
        )

        # Database related events
        self.database = DatabaseRequires(self, "database", DATABASE_NAME)
        self.framework.observe(
            getattr(self.database.on, "database_created"), self._on_database_created
        )
        self.framework.observe(
            getattr(self.database.on, "endpoints_changed"), self._on_endpoints_changed
        )
        self.framework.observe(
            self.on[DATABASE_RELATION].relation_broken, self._on_relation_broken
        )
        self.framework.observe(
            self.on[LEGACY_MYSQL_RELATION].relation_broken, self._on_relation_broken
        )
        # Legacy MySQL/MariaDB Handler
        self.legacy_mysql = LegacyMySQL(self)

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
    def unit_peer_data(self) -> Dict:
        """Application peer relation data object."""
        if self._peers is None:
            return {}

        return self._peers.data[self.unit]

    @property
    def _database_config(self):
        """Returns the database config to use to connect to the MySQL cluster."""
        # identify the database relation
        if self.model.get_relation(DATABASE_RELATION):
            data = list(self.database.fetch_relation_data().values())[0]

            username, password, endpoints = (
                data.get("username"),
                data.get("password"),
                data.get("endpoints"),
            )
        elif self.model.get_relation(LEGACY_MYSQL_RELATION):
            username = self.app_peer_data.get(f"{LEGACY_MYSQL_RELATION}-user")
            password = self.app_peer_data.get(f"{LEGACY_MYSQL_RELATION}-password")
            endpoints = self.app_peer_data.get(f"{LEGACY_MYSQL_RELATION}-host")
            endpoints = f"{endpoints}:3306"
        else:
            return {}
        if None in [username, password, endpoints]:
            return {}

        config = {
            "user": username,
            "password": password,
            "database": DATABASE_NAME,
        }
        if endpoints.startswith("file://"):
            config["unix_socket"] = endpoints[7:]
        else:
            host, port = endpoints.split(":")
            config["host"] = host
            config["port"] = port

        return config

    # ==============
    # Helpers
    # ==============

    def _start_continuous_writes(self, starting_number: int) -> None:
        """Start continuous writes to the MySQL cluster."""
        if not self._database_config:
            # don't start if no database config is available
            logger.debug("Won't start continuous writes: missing database config")
            return

        self._stop_continuous_writes()

        command = [
            "/usr/bin/python3",
            "src/continuous_writes.py",
            self._database_config["user"],
            self._database_config["password"],
            self._database_config["database"],
            CONTINUOUS_WRITE_TABLE_NAME,
            str(starting_number),
        ]

        if "unix_socket" in self._database_config:
            command.append(self._database_config["unix_socket"])
        else:
            command.append(self._database_config["host"])
            command.append(self._database_config["port"])

        # Run continuous writes in the background
        proc = subprocess.Popen(command)

        # Store the continuous writes process id in stored state to be able to stop it later
        self.unit_peer_data[PROC_PID_KEY] = str(proc.pid)
        logger.info("Started continuous writes")

    def _stop_continuous_writes(self) -> Optional[int]:
        """Stop continuous writes to the MySQL cluster and return the last written value."""
        if not self.unit_peer_data.get(PROC_PID_KEY):
            return None

        # Send a SIGKILL to the process and wait for the process to exit
        proc = subprocess.Popen(["pkill", "--signal", "SIGKILL", "-f", "src/continuous_writes.py"])
        proc.communicate()

        del self.unit_peer_data[PROC_PID_KEY]

        last_written_value = -1
        # Query and return the max value inserted in the database
        # (else -1 if unable to query)
        try:
            for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(5)):
                with attempt:
                    last_written_value = self._max_written_value()
        except RetryError as e:
            logger.exception("Unable to query the database", exc_info=e)
        logger.info("Stop continuous writes")
        return last_written_value

    def _max_written_value(self) -> int:
        """Return the max value in the continuous writes table."""
        if not self._database_config:
            return -1

        with MySQLConnector(self._database_config) as cursor:
            cursor.execute(
                f"SELECT MAX(number) FROM `{DATABASE_NAME}`.`{CONTINUOUS_WRITE_TABLE_NAME}`;"
            )
            return cursor.fetchone()[0]

    def _create_random_value_table(self, cursor) -> None:
        """Create a test table in the database."""
        cursor.execute(
            (
                f"CREATE TABLE IF NOT EXISTS `{RANDOM_VALUE_TABLE_NAME}`("
                "id SMALLINT NOT NULL AUTO_INCREMENT, "
                "data VARCHAR(255), "
                "PRIMARY KEY (id))"
            )
        )

    def _insert_random_value(self, cursor, random_value: str) -> None:
        """Insert the provided random value into the test table in the database."""
        cursor.execute(f"INSERT INTO `{RANDOM_VALUE_TABLE_NAME}`(data) VALUES('{random_value}')")

    @staticmethod
    def _generate_random_values(length) -> str:
        choices = string.ascii_letters + string.digits
        return "".join(secrets.choice(choices) for _ in range(length))

    def _write_random_value(self) -> str:
        """Write a random value to the database."""
        if not self._database_config:
            return ""
        random_value = ""
        try:
            for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(5)):
                with attempt:
                    with MySQLConnector(self._database_config) as cursor:
                        self._create_random_value_table(cursor)
                        random_value = self._generate_random_values(10)
                        self._insert_random_value(cursor, random_value)
        except RetryError:
            logger.exception("Unable to write to the database")
            return random_value

        logger.info("Wrote random_value")

        return random_value

    # ==============
    # Handlers
    # ==============
    def _on_start(self, _) -> None:
        """Handle the start event."""
        self.unit.set_workload_version("0.0.2")
        if self._database_config:
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = WaitingStatus()

    def _on_clear_continuous_writes_action(self, _) -> None:
        """Handle the clear continuous writes action event."""
        if not self._database_config:
            return

        self._stop_continuous_writes()
        with MySQLConnector(self._database_config) as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS `{DATABASE_NAME}`.`{CONTINUOUS_WRITE_TABLE_NAME}`;"
            )

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
        if not self._database_config:
            return
        if self.unit.is_leader():
            self.app_peer_data["database-start"] = "true"

    def _on_endpoints_changed(self, _) -> None:
        """Handle the database endpoints changed event."""
        if self.config["auto_start_writes"]:
            count = self._max_written_value()
            self._start_continuous_writes(count + 1)
        else:
            logger.debug("Won't start continuous writes: auto_start_writes is false")

    def _on_peer_relation_changed(self, _) -> None:
        """Handle common post database estabilshed tasks."""
        if self.app_peer_data.get("database-start") == "true":
            if self.config["auto_start_writes"]:
                self._start_continuous_writes(1)
            else:
                logger.debug("Won't start continuous writes: auto_start_writes is false")

            if self.unit.is_leader():
                value = self._write_random_value()
                self.app_peer_data[RANDOM_VALUE_KEY] = value
                # flag should be picked up just once
                self.app_peer_data["database-start"] = "done"

            self.unit.status = ActiveStatus()

    def _on_relation_broken(self, _) -> None:
        """Handle the database relation broken event."""
        self._stop_continuous_writes()
        if self.unit.is_leader():
            self.app_peer_data.pop("database-start", None)
        self.unit.status = WaitingStatus()

    def _get_inserted_data(self, event: ActionEvent) -> None:
        """Get random value inserted into the database."""
        event.set_results({"data": self.app_peer_data.get(RANDOM_VALUE_KEY, "empty")})

    def _get_session_ssl_cipher(self, event: ActionEvent) -> None:
        """Get the SSL cipher used by the session.

        This is useful to check that the connection is (un)encrypted.
        The action has a `use-ssl` parameter that can be used to disable SSL.
        """
        if not self._database_config:
            return event.set_results({"cipher": "noconfig"})

        config = self._database_config.copy()
        if event.params.get("use-ssl") == "disabled":
            config["ssl_disabled"] = True

        try:
            with MySQLConnector(config) as cursor:
                cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                cipher = cursor.fetchone()[1]
        except Exception:
            logger.exception("Unable to get the SSL cipher")
            cipher = "error"

        event.set_results({"cipher": cipher})

    def _get_server_certificate(self, event: ActionEvent) -> None:
        """Get the server certificate."""
        certificate = "error"
        if not self._database_config:
            event.fail()
        else:
            try:
                process = subprocess.run(
                    [
                        "openssl",
                        "s_client",
                        "-starttls",
                        "mysql",
                        "-connect",
                        f"{self._database_config['host']}:{self._database_config['port']}",
                    ],
                    capture_output=True,
                )
                # butchered stdout due non utf chars after the certificate
                raw_output = process.stdout[:2800].decode("utf8")
                matches = re.search(
                    r"^(-----BEGIN C.*END CERTIFICATE-----[,\s])",
                    raw_output,
                    re.MULTILINE | re.DOTALL,
                )
                certificate = matches.group(0)
            except Exception:
                event.fail()

        event.set_results({"certificate": certificate})


if __name__ == "__main__":
    main(MySQLTestApplication)
