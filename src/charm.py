#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import mysql.connector
import random
import re

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    WaitingStatus,
)
from ops.framework import StoredState
from string import ascii_letters, digits

logger = logging.getLogger(__name__)
PEER = "mysql"


class MySQLCharm(CharmBase):
    """Charm to run MySQL on Kubernetes."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(mysql_setup={})
        password = "".join(
            random.choice(ascii_letters + digits) for x in range(20)
        )
        self._stored.set_default(MYSQL_ROOT_PASSWORD=password)
        self.image = OCIImageResource(self, "mysql-image")
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    @property
    def hostname(self) -> str:
        """Return the Kubernetes hostname."""
        unit_number = self._get_unit_number_from_unit_name(self.unit.name)
        return self._get_hostname_from_unit(unit_number)

    @property
    def env_config(self) -> dict:
        """Return the env_config for the Kubernetes pod_spec"""
        config = self.model.config
        env_config = {}

        if config.get("MYSQL_ROOT_PASSWORD"):
            env_config["MYSQL_ROOT_PASSWORD"] = config["MYSQL_ROOT_PASSWORD"]
        else:
            env_config[
                "MYSQL_ROOT_PASSWORD"
            ] = self._stored.MYSQL_ROOT_PASSWORD
            logger.warning(
                "The randomly generated MYSQL_ROOT_PASSWORD is: %s",
                self._stored.MYSQL_ROOT_PASSWORD,
            )
            logger.warning("Please change it as soon as possible!")

        if config.get("MYSQL_USER") and config.get("MYSQL_PASSWORD"):
            env_config["MYSQL_USER"] = config["MYSQL_USER"]
            env_config["MYSQL_PASSWORD"] = config["MYSQL_PASSWORD"]

        if config.get("MYSQL_DATABASE"):
            env_config["MYSQL_DATABASE"] = config["MYSQL_DATABASE"]

        return env_config

    def _on_start(self, event):
        """Initialize MySQL"""

        if not self._mysql_is_ready():
            message = "Waiting for MySQL Service"
            self.unit.status = WaitingStatus(message)
            logger.info(message)
            event.defer()
            return

        self.unit.status = ActiveStatus()

    def _on_config_changed(self, _):
        """This method handles the .on.config_changed() event"""
        self._configure_pod()

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
                }
            ],
        }

        return pod_spec

    def _mysql_is_ready(self) -> bool:
        """Check that every unit has mysql running.

        Until we have a good event-driven way of using the Kubernetes
        readiness probe, we will attempt
        """
        try:
            cnx = self._get_sql_connection_for_host()
            logger.info("MySQL service is ready in %s.", self.hostname)
        except mysql.connector.Error:
            # TODO: Improve exceptions handling
            logger.info("MySQL service is not ready in %s", self.hostname)
            return False
        else:
            cnx.close()

        return True

    def _get_sql_connection_for_host(self):
        """Helper for the _mysql_is_ready() method"""
        config = {
            "user": "root",
            "password": self._stored.MYSQL_ROOT_PASSWORD,
            "host": self.hostname,
            "port": self.model.config["port"],
        }
        return mysql.connector.connect(**config)

    def _get_hostname_from_unit(self, _id: int) -> str:
        """Construct a DNS name for a MySQL unit."""
        return "{0}-{1}.{0}-endpoints".format(self.model.app.name, _id)

    def _get_unit_number_from_unit_name(self, unit_name: str) -> int:
        """Returns the unit number based in the unit name."""
        UNIT_RE = re.compile(".+(?P<unit>[0-9]+)")
        match = UNIT_RE.match(unit_name)

        if match is not None:
            return int(match.group("unit"))
        return None


if __name__ == "__main__":
    main(MySQLCharm)
