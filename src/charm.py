#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from mysqlprovider import MySQLProvider
from mysqlserver import MySQL
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
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
        self._stored.set_default(mysql_setup={})
        self._stored.set_default(mysql_initialized=False)
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

        if self._stored.mysql_initialized:
            self.mysql_provider = MySQLProvider(
                self, "database", self.provides
            )
            self.mysql_provider.ready()
            logger.info("MySQL Provider is available")

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

    def _on_config_changed(self, _):
        """This method handles the .on.config_changed() event"""
        self._configure_pod()

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

    @property
    def mysql(self) -> MySQL:
        """Returns MySQL object"""
        mysql_config = {
            "app_name": self.model.app.name,
            "host": self.hostname,
            "port": self.model.config["port"],
            "user_name": "root",
            "mysql_root_password": self._stored.mysql_setup[
                "MYSQL_ROOT_PASSWORD"
            ],
        }
        return MySQL(mysql_config)

    @property
    def hostname(self) -> str:
        """Unit hostname"""
        unit_id = self.unit.name.split("/")[1]
        return "{0}-{1}.{0}-endpoints".format(self.model.app.name, unit_id)

    @property
    def provides(self) -> dict:
        """Provides dictionary"""
        provides = {
            "provides": {"mysql": self.mysql.version()},
        }
        return provides

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

    def _configure_pod(self):
        """Configure the K8s pod spec for MySQL."""
        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        spec = self._build_pod_spec()
        if not spec:
            return
        self.model.pod.set_spec(spec)
        self.unit.status = ActiveStatus()

    def _build_pod_spec(self) -> dict:
        """This method builds the pod_spec"""
        if not self.unit.is_leader():
            return {}

        try:
            self.unit.status = WaitingStatus("Fetching image information")
            image_info = self.image.fetch()
        except OCIImageResourceError:
            logging.exception(
                "An error occurred while fetching the image info"
            )
            self.unit.status = BlockedStatus(
                "Error fetching image information"
            )
            return {}

        config = self.model.config
        self.unit.status = WaitingStatus("Assembling pod spec")

        pod_spec = {
            "version": 3,
            "containers": [
                {
                    "name": self.app.name,
                    "imageDetails": image_info,
                    "ports": [
                        {"containerPort": config["port"], "protocol": "TCP"}
                    ],
                    "envConfig": self.env_config,
                    "kubernetes": {
                        "readinessProbe": {
                            "exec": {
                                "command": [
                                    "mysqladmin",
                                    "ping",
                                    "-u",
                                    "root",
                                    "-p$(echo $MYSQL_ROOT_PASSWORD)",
                                ]
                            },
                            "initialDelaySeconds": 20,
                            "periodSeconds": 5,
                        },
                        "livenessProbe": {
                            "exec": {
                                "command": [
                                    "mysqladmin",
                                    "ping",
                                    "-u",
                                    "root",
                                    "-p$(echo $MYSQL_ROOT_PASSWORD)",
                                ]
                            },
                            "initialDelaySeconds": 30,
                            "periodSeconds": 10,
                        },
                    },
                }
            ],
        }

        return pod_spec


if __name__ == "__main__":
    main(MySQLCharm)
