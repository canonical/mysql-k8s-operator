#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from mysqlprovider import MySQLProvider
from mysqlserver import MySQL
from oci_image import OCIImageResource
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
)
from ops.pebble import ConnectionError
from ops.framework import StoredState
from typing import Union


logger = logging.getLogger(__name__)
PEER = "mysql"


class MySQLCharm(CharmBase):
    """Charm to run MySQL on Kubernetes."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(mysql_setup={})
        self._stored.set_default(mysql_initialized=False)
        self.image = OCIImageResource(self, "mysql-image")
        self.framework.observe(
            self.on.mysql_pebble_ready, self._setup_pebble_layers
        )
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on[PEER].relation_joined, self._on_peer_relation_joined
        )
        self.framework.observe(
            self.on[PEER].relation_changed, self._on_peer_relation_changed
        )
        self.framework.observe(self.on.update_status, self._on_update_status)
        self._provide_mysql()

    def _setup_pebble_layers(self, event):
        """Setup a new Prometheus pod specification"""
        logger.debug("Configuring Pod...")

        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        self.unit.status = MaintenanceStatus("Setting up containers.")
        container = event.workload
        layer = self._mysql_layer()
        container.add_layer("mysql", layer, combine=True)
        container.autostart()
        self.app.status = ActiveStatus()
        self.unit.status = ActiveStatus()

    def _mysql_layer(self):
        """Construct the pebble layer"""
        logger.debug("Building pebble layer")
        layer = {
            "summary": "MySQL layer",
            "description": "Pebble layer configuration for MySQL",
            "services": {
                "mysql": {
                    "override": "replace",
                    "summary": "mysql daemon",
                    "command": "/usr/sbin/mysqld",
                    "startup": "enabled",
                },
            },
        }

        return layer

    def _on_peer_relation_joined(self, event):
        if not self.unit.is_leader():
            return

        event.relation.data[event.app][
            "MYSQL_ROOT_PASSWORD"
        ] = self._stored.mysql_setup["MYSQL_ROOT_PASSWORD"]
        logger.info("Storing MYSQL_ROOT_PASSWORD in relation data")

    def _on_peer_relation_changed(self, event):
        if event.relation.data[event.app].get("MYSQL_ROOT_PASSWORD"):
            self._stored.mysql_setup[
                "MYSQL_ROOT_PASSWORD"
            ] = event.relation.data[event.app]["MYSQL_ROOT_PASSWORD"]
            logger.info("Storing MYSQL_ROOT_PASSWORD in StoredState")

    def _on_config_changed(self, event):
        """Set a new Juju pod specification"""
        logger.info("Handling config changed")
        container = self.unit.get_container("mysql")

        try:
            service = container.get_service("mysql")
        except ConnectionError:
            logger.info("Pebble API is not yet ready")
            return
        except ModelError:
            logger.info("MySQL service is not yet ready")
            return

        if service.is_running():
            container.stop("mysql")

        container.start("mysql")
        logger.info("Restarted MySQL service")

    # Handles start event
    def _on_start(self, event):
        """Initialize MySQL

        This event handler is deferred if initialization of MySQL
        fails. By doing so it is gauranteed that another
        attempt at initialization will be made.
        """

        if not self.unit.is_leader():
            return

        if not self.mysql.is_ready():
            msg = "Waiting for MySQL Service"
            self.unit.status = WaitingStatus(msg)
            logger.debug(msg)
            event.defer()
            return

        self._on_update_status(event)
        self._stored.mysql_initialized = True
        self.unit.status = ActiveStatus()

    # Handles update-status event
    def _on_update_status(self, event):
        """Set status for all units
        Status may be
        - MySQL is not ready,
        - MySQL is not Initialized
        - Unit is active
        """
        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        if not self.mysql.is_ready():
            status_message = "MySQL not ready yet"
            self.unit.status = WaitingStatus(status_message)
            return

        if not self._stored.mysql_initialized:
            status_message = "MySQL not initialized"
            self.unit.status = WaitingStatus(status_message)
            return

        self.unit.status = ActiveStatus()

    def _provide_mysql(self) -> None:
        if self._stored.mysql_initialized:
            self.mysql_provider = MySQLProvider(
                self, "database", "mysql", self.mysql.version()
            )
            self.mysql_provider.ready()
            logger.info("MySQL Provider is available")

    @property
    def mysql(self) -> MySQL:
        """Returns MySQL object"""
        mysql_config = {
            "app_name": self.model.app.name,
            "host": self.hostname,
            "port": self.model.config["port"],
            "user_name": "root",
            "mysql_root_password": self.mysql_root_password,
        }
        return MySQL(mysql_config)

    @property
    def hostname(self) -> str:
        """Unit hostname"""
        unit_id = self.unit.name.split("/")[1]
        return "{0}-{1}.{0}-endpoints".format(self.model.app.name, unit_id)

    @property
    def mysql_root_password(self) -> Union[str, None]:
        """
        This property return MYSQL_ROOT_PASSWORD from StoredState.
        If the password isn't in StoredState, generates one.
        """

        if not self.unit.is_leader():
            return None

        if "MYSQL_ROOT_PASSWORD" not in self._stored.mysql_setup:
            self._stored.mysql_setup[
                "MYSQL_ROOT_PASSWORD"
            ] = MySQL.new_password(20)

        return self._stored.mysql_setup["MYSQL_ROOT_PASSWORD"]

    @property
    def env_config(self) -> dict:
        """Return the env_config for the Kubernetes pod_spec"""
        config = self.model.config
        env_config = {}

        if config.get("MYSQL_ROOT_PASSWORD"):
            self._stored.mysql_setup["MYSQL_ROOT_PASSWORD"] = config[
                "MYSQL_ROOT_PASSWORD"
            ]
            env_config["MYSQL_ROOT_PASSWORD"] = config["MYSQL_ROOT_PASSWORD"]
        else:
            env_config["MYSQL_ROOT_PASSWORD"] = self.mysql_root_password

        if config.get("MYSQL_USER") and config.get("MYSQL_PASSWORD"):
            env_config["MYSQL_USER"] = config["MYSQL_USER"]
            env_config["MYSQL_PASSWORD"] = config["MYSQL_PASSWORD"]

        if config.get("MYSQL_DATABASE"):
            env_config["MYSQL_DATABASE"] = config["MYSQL_DATABASE"]

        return env_config


if __name__ == "__main__":
    main(MySQLCharm)
