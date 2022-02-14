#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for MySQL InnoDB Cluster."""

import logging
import time
from pathlib import Path

from mysqlconnector import MySQLConnector
from ops.charm import CharmBase, WorkloadEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class MysqlOperatorCharm(CharmBase):
    """A Juju Charm for MySQL InnoDB Cluster."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._src_dir = Path(__file__).parent
        self._server_container = "mysql-server"
        self._router_container = "mysql-router"
        self._stored.set_default(root_password="", mysql_password="")

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        pebble_events = [
            self.on.mysql_server_pebble_ready,
            self.on.mysql_router_pebble_ready,
        ]
        for event in pebble_events:
            self.framework.observe(event, self._on_pebble_ready)

    # ---- Event handlers
    def _on_install(self, event: WorkloadEvent) -> None:
        """Ensures the MySQL server instance is configured for an InnoDB Cluster."""
        container = self.unit.get_container(self._server_container)
        if not container.can_connect():
            event.defer()
            return

        # Configure server instance:
        # Push configuration file and instance script to workload container
        self._mysql.configure_server_instance()

    def _on_leader_elected(self, event: WorkloadEvent) -> None:
        """Set all needed passwords for connection and administration."""
        self._stored.root_password = self._root_password
        self._stored.mysql_password = self._mysql_password

    def _on_pebble_ready(self, event: WorkloadEvent) -> None:
        """Updates the Pebble configuration layer when changed."""
        container = event.workload

        # QUESTION: if you check this and defer on_install,
        # is it worth it to check it here as well?
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for pod startup to complete")
            event.defer()
            return

        # Get current config
        current_layer = container.get_plan()
        # Create a new config layer
        new_layer = self._mysql_layer(service=container.name)

        if current_layer.services != new_layer.services:
            container.add_layer(container.name, new_layer, combine=True)
            logging.info("Pebble plan updated with new configuration")
            container.restart(container.name)
            if container.name == "mysql-server":
                if self.unit.is_leader():
                    # TODO: change this sleep for something else that checks
                    # when the service has finished setting up
                    # Related to https://github.com/canonical/pebble/pull/86
                    # and https://github.com/canonical/operator/pull/668
                    time.sleep(30)
                    self._mysql.create_innodb_cluster(self._config["innodb_cluster_name"])
        self.unit.status = ActiveStatus()

    # ---- Helper functions
    def _mysql_layer(self, service: str) -> Layer:
        """Returns a pre-configured Pebble Layer."""
        # FIXME: remove this block and uncomment the below one
        # This is just for testing purposes
        env_config = {
            "MYSQL_USER": self._config["mysql_user"],
            "MYSQL_PASSWORD": "C4n0n1c4l",
            "MYSQL_ROOT_PASSWORD": "C4n0n1c4l",
        }
        # env_config = {
        #     "MYSQL_USER": self._config["mysql_user"],
        #     "MYSQL_PASSWORD": self._config["mysql_password"],
        #     "MYSQL_ROOT_PASSWORD": self._config["root_password"],
        # }

        # FIXME: mysqlrouter cannot be started correctly as it
        # is missing important information on start up.
        layer_config = {
            "summary": "MySQL Router layer",
            "description": "Pebble layer configuration for MySQL Router",
            "services": {
                service: {
                    "override": "replace",
                    "summary": "mysqlsh router",
                    "command": "/run.sh mysqlrouter",
                    "startup": "enabled",
                    "environment": env_config,
                }
            },
        }

        if service == "mysql-server":
            layer_config = {
                "summary": "MySQL Server layer",
                "description": "Pebble layer configuration for MySQL Server",
                "services": {
                    service: {
                        "override": "replace",
                        "summary": "mysql server instance",
                        "command": "docker-entrypoint.sh mysqld",
                        "startup": "enabled",
                        "environment": env_config,
                    }
                },
            }
        return Layer(layer_config)

    # ---- Properties
    @property
    def _config(self):
        """Configuration data for MySQL."""
        config = {
            "innodb_cluster_name": self.model.config["innodb_cluster_name"],
            "mysql_user": "mysql_user",
            "mysql_password": self._mysql_password,
            "mysql_root_password": self._root_password,
        }
        return config

    @property
    def _root_password(self):
        root_password = self._stored.root_password
        if not root_password:
            root_password = MySQLConnector.generate_password()
        return root_password

    @property
    def _mysql_password(self):
        mysql_password = self._stored.mysql_password
        if not mysql_password:
            mysql_password = MySQLConnector.generate_password()
        return mysql_password

    @property
    def _mysql(self):
        return MySQLConnector(self.unit)


if __name__ == "__main__":
    main(MysqlOperatorCharm)
