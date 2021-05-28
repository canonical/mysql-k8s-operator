#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from custom_exceptions import MySQLRootPasswordError
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

from ops.framework import StoredState
from typing import Union


logger = logging.getLogger(__name__)
PEER = "mysql"


class MySQLCharm(CharmBase):
    """Charm to run MySQL on Kubernetes."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(
            mysql_setup={"mysql_root_password": False},
            mysql_initialized=False,
        )
        self.image = OCIImageResource(self, "mysql-image")
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

    def _mysql_layer(self):
        """Construct the pebble layer"""
        logger.debug("Building pebble layer")
        return {
            "summary": "MySQL layer",
            "description": "Pebble layer configuration for MySQL",
            "services": {
                "mysql": {
                    "override": "replace",
                    "summary": "mysql service",
                    "command": "docker-entrypoint.sh mysqld",
                    "startup": "enabled",
                    "environment": self.env_config,
                },
            },
        }

    def _on_peer_relation_joined(self, event):
        if not self.unit.is_leader():
            return

        event.relation.data[self.app][
            "mysql_root_password"
        ] = self._stored.mysql_setup["mysql_root_password"]
        logger.info("Storing mysql_root_password in relation data")

    def _on_peer_relation_changed(self, event):
        if event.relation.data[event.app].get("mysql_root_password"):
            self._stored.mysql_setup[
                "mysql_root_password"
            ] = event.relation.data[event.app]["mysql_root_password"]
            logger.info("Storing mysql_root_password in StoredState")

    def _on_config_changed(self, event):
        """Set a new Juju pod specification"""
        self.unit.status = MaintenanceStatus("Setting up containers.")
        self.container = self.unit.get_container(PEER)
        self.services = self.container.get_plan().to_dict().get("services", {})
        self._update_layer(event)

        if self.needs_restart:
            self._restart_service()

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

    def _update_layer(self, event) -> bool:
        """Updates layer"""
        self.needs_restart = False

        try:
            layer = self._mysql_layer()
        except MySQLRootPasswordError as e:
            logger.debug(e)
            event.defer()
            return self.needs_restart

        if (
            not self.services
            or self.services[PEER]["environment"]
            != layer["services"][PEER]["environment"]
        ):
            self.container.add_layer(PEER, layer, combine=True)
            self.needs_restart = True

        return self.needs_restart

    def _restart_service(self):
        """Restarts MySQL Service"""
        try:
            service = self.container.get_service(PEER)
        except ConnectionError:
            logger.info("Pebble API is not yet ready")
            return
        except ModelError:
            logger.info("MySQL service is not yet ready")
            return

        if service.is_running():
            self.container.stop(PEER)

        self.container.start(PEER)
        logger.info("Restarted MySQL service")
        self.unit.status = ActiveStatus()

    @property
    def mysql(self) -> MySQL:
        """Returns MySQL object"""
        mysql_config = {
            "app_name": self.model.app.name,
            "host": self.unit_ip,
            "port": self.model.config["port"],
            "user_name": "root",
            "mysql_root_password": self.mysql_root_password,
        }
        return MySQL(mysql_config)

    @property
    def unit_ip(self) -> str:
        """Returns unit's IP"""
        return str(self.model.get_binding(PEER).network.bind_address)

    @property
    def mysql_root_password(self) -> Union[str, None]:
        """
        This property returns MYSQL_ROOT_PASSWORD from the config,
        if the password isn't in StoredState, generates one.
        """

        password_from_config = self.config["MYSQL_ROOT_PASSWORD"]
        if password_from_config:
            logger.debug("Adding root password from config to stored state")
            self._stored.mysql_setup[
                "mysql_root_password"
            ] = password_from_config
            return self._stored.mysql_setup["mysql_root_password"]

        if self.unit.is_leader():
            if not self._stored.mysql_setup["mysql_root_password"]:
                self._stored.mysql_setup[
                    "mysql_root_password"
                ] = MySQL.new_password(20)
                logger.info("Password generated.")
        else:
            if not self._stored.mysql_setup["mysql_root_password"]:
                raise MySQLRootPasswordError(
                    "MySQL root password should be received through relation data"
                )

        return self._stored.mysql_setup["mysql_root_password"]

    @property
    def env_config(self) -> dict:
        """Return the env_config for pebble layer"""
        config = self.model.config
        env_config = {}
        env_config["MYSQL_ROOT_PASSWORD"] = self.mysql_root_password

        if config.get("MYSQL_USER") and config.get("MYSQL_PASSWORD"):
            env_config["MYSQL_USER"] = config["MYSQL_USER"]
            env_config["MYSQL_PASSWORD"] = config["MYSQL_PASSWORD"]

        if config.get("MYSQL_DATABASE"):
            env_config["MYSQL_DATABASE"] = config["MYSQL_DATABASE"]

        return env_config


if __name__ == "__main__":
    main(MySQLCharm)
