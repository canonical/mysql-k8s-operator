#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from mysqlprovider import MySQLProvider
from mysqlserver import MySQL
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
)

logger = logging.getLogger(__name__)
PEER = "mysql"
MYSQL_PORT = 3306


class MySQLCharm(CharmBase):
    """Charm to run MySQL on Kubernetes."""

    _stored = StoredState()
    mysql_provider: MySQLProvider = None

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(
            mysql_initialized=False,
            pebble_ready=False,
        )
        self.framework.observe(
            self.on.mysql_pebble_ready, self._on_pebble_ready
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(
            self.on.create_user_action, self._on_create_user_action
        )
        self.framework.observe(
            self.on.delete_user_action, self._on_delete_user_action
        )
        self.framework.observe(
            self.on.create_database_action, self._on_create_database_action
        )
        self.framework.observe(
            self.on.set_user_password_action, self._on_set_user_password_action
        )
        self._provide_mysql()
        self.container = self.unit.get_container(PEER)

    ##############################################
    #           CHARM HOOKS HANDLERS             #
    ##############################################
    def _on_pebble_ready(self, _):
        self._stored.pebble_ready = True
        self._update_peers()
        self._configure_pod()

    def _on_config_changed(self, _):
        """Set a new Juju pod specification"""
        self._update_peers()
        self._configure_pod()

    def _on_update_status(self, _):
        """Set status for all units
        Status may be
        - MySQL is not ready,
        - MySQL is not Initialized
        - Unit is active
        """

        if not self.mysql.is_ready():
            status_message = "MySQL not ready yet"
            self.unit.status = WaitingStatus(status_message)
            return

        if not self._is_mysql_initialized():
            status_message = "MySQL not initialized"
            self.unit.status = WaitingStatus(status_message)
            return

        self.unit.status = ActiveStatus()

    def _on_create_user_action(self, event):
        """Handle the create_user action."""
        creds = {
            "username": event.params["username"],
            "password": event.params["password"],
            "hostname": "%",
        }

        try:
            self.mysql.new_super_user(creds)
            event.set_results({"username": creds["username"]})
            event.log(f"Username {creds['username']} created")
        except Exception as e:
            logger.error(e)
            event.fail(message=str(e))

    def _on_set_user_password_action(self, event):
        """Handle the set_user_password action."""
        creds = {
            "username": event.params["username"],
            "password": event.params["password"],
            "hostname": "%",
        }

        try:
            self.mysql.set_user_password(creds)
            event.set_results({"username": creds["username"]})
            event.log(f"Pasword for username: {creds['username']} changed")
        except Exception as e:
            logger.error(e)
            event.fail(message=str(e))

    def _on_delete_user_action(self, event):
        """Handle the create_user action."""

        try:
            self.mysql.drop_user(event.params["username"])
            event.set_results({"username": event.params["username"]})
            event.log(f"Username {event.params['username']} deleted")
        except Exception as e:
            logger.error(e)
            event.fail(message=str(e))

    def _on_create_database_action(self, event):
        """Handle the create_user action."""

        try:
            self.mysql.new_database(event.params["database"])
            event.set_results({"database": event.params["database"]})
            event.log(f"Database {event.params['database']} created")
        except Exception as e:
            logger.error(e)
            event.fail(message=str(e))

    ##############################################
    #               PROPERTIES                   #
    ##############################################
    @property
    def mysql(self) -> MySQL:
        """Returns MySQL object"""
        peers_data = self.model.get_relation(PEER).data[self.app]
        mysql_config = {
            "app_name": self.model.app.name,
            "host": self.unit_ip,
            "port": MYSQL_PORT,
            "user_name": "root",
            "mysql_root_password": peers_data["mysql_root_password"],
        }
        return MySQL(mysql_config)

    @property
    def unit_ip(self) -> str:
        """Returns unit's IP"""
        if bind_address := self.model.get_binding(PEER).network.bind_address:
            return str(bind_address)
        return ""

    ##############################################
    #             UTILITY METHODS                #
    ##############################################
    def _mysql_root_password(self) -> str:
        """
        Returns mysql_root_password from the config or generates one.
        """
        return self.config["mysql_root_password"] or MySQL.new_password(20)

    def _update_peers(self):
        if self.unit.is_leader():
            peers_data = self.model.get_relation(PEER).data[self.app]

            if not peers_data.get("mysql_root_password"):
                peers_data["mysql_root_password"] = self._mysql_root_password()

    def _configure_pod(self):
        """Configure the Pebble layer for MySQL."""
        if not self._stored.pebble_ready:
            msg = "Waiting for Pod startup to complete"
            logger.debug(msg)
            self.unit.status = MaintenanceStatus(msg)
            return False

        layer = self._build_pebble_layer()

        if not layer["services"][PEER]["environment"].get(
            "MYSQL_ROOT_PASSWORD", False
        ):
            msg = "Awaiting leader node to set mysql_root_password"
            logger.debug(msg)
            self.unit.status = MaintenanceStatus(msg)
            return False

        services = self.container.get_plan().to_dict().get("services", {})

        if (
            not services
            or services[PEER]["environment"]
            != layer["services"][PEER]["environment"]
        ):
            self.container.add_layer(PEER, layer, combine=True)
            self._restart_service()
            self.unit.status = ActiveStatus()
            return True

    def _build_pebble_layer(self):
        """Construct the pebble layer"""
        logger.debug("Building pebble layer")

        def env_config() -> dict:
            """Return the env_config for pebble layer"""
            config = self.model.config
            peers_data = self.model.get_relation(PEER).data[self.app]
            env_config = {}
            env_config["MYSQL_ROOT_PASSWORD"] = peers_data[
                "mysql_root_password"
            ]

            if (user := config.get("mysql_user")) and (
                password := config.get("mysql_password")
            ):
                env_config["MYSQL_USER"] = user
                env_config["MYSQL_PASSWORD"] = password

            if database := config.get("mysql_database"):
                env_config["MYSQL_DATABASE"] = database

            return env_config

        layer = {
            "summary": "MySQL layer",
            "description": "Pebble layer configuration for MySQL",
            "services": {
                PEER: {
                    "override": "replace",
                    "summary": "mysql service",
                    "command": "docker-entrypoint.sh mysqld",
                    "startup": "enabled",
                    "environment": env_config(),
                }
            },
        }

        return layer

    def _provide_mysql(self) -> None:
        if self._is_mysql_initialized():
            self.mysql_provider = MySQLProvider(
                self, "database", PEER, self.mysql.version()
            )
            self.mysql_provider.ready()
            logger.debug("MySQL Provider is available")

    def _restart_service(self):
        """Restarts MySQL Service"""
        try:
            service = self.container.get_service(PEER)
        except ConnectionError:
            logger.debug("Pebble API is not yet ready")
            return False
        except ModelError:
            logger.debug("MySQL service is not yet ready")
            return False

        if service.is_running():
            self.container.stop(PEER)

        self.container.start(PEER)
        logger.debug("Restarted MySQL service")
        self.unit.status = ActiveStatus()
        self._stored.mysql_initialized = True

    def _is_mysql_initialized(self) -> bool:
        return self._stored.mysql_initialized


if __name__ == "__main__":
    main(MySQLCharm)
