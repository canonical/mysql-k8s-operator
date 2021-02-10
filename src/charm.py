#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import random

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
        self.image = OCIImageResource(self, "mysql-image")
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    @property
    def mysql_root_password(self) -> str:
        if "MYSQL_ROOT_PASSWORD" not in self._stored.mysql_setup:
            password = "".join(
                random.choice(ascii_letters + digits) for x in range(20)
            )
            self._stored.mysql_setup["MYSQL_ROOT_PASSWORD"] = password
            logger.warning(
                """The randomly generated MYSQL_ROOT_PASSWORD is: %s""",
                self._stored.mysql_setup["MYSQL_ROOT_PASSWORD"],
            )
            logger.warning("Please change it as soon as possible!")

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
        if not self.unit.is_leader():
            return

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
