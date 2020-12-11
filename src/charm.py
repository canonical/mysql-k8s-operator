#!/usr/bin/env python3
# Copyright 2020 jose
# See LICENSE file for licensing details.

import logging
import mysql.connector

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    WaitingStatus,
)
from ops.framework import StoredState

logger = logging.getLogger(__name__)
PEER = "mysql"


class MySQLOperatorCharm(CharmBase):
    """
    Charm to run MySQL on Kubernetes.
    """
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.image = OCIImageResource(self, 'mysql-image')
        self.port = self.model.config['port']
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.config_changed, self.on_start)
        self._stored.set_default(things=[])

    def _on_config_changed(self, _):
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

    def _build_pod_spec(self):
        try:
            self.unit.status = WaitingStatus("Fetching image information")
            image_info = self.image.fetch()
        except OCIImageResourceError:
            logging.exception(
                'An error occurred while fetching the image info')
            self.unit.status = BlockedStatus(
                'Error fetching image information')
            return {}

        self.unit.status = WaitingStatus("Assembling pod spec")
        pod_spec = {
            'version': 3,
            'containers': [{
                'name': self.app.name,
                'imageDetails': image_info,
                'ports': [{
                    'containerPort': self.port,
                    'protocol': 'TCP'
                }],
                'envConfig': {
                    'MYSQL_ROOT_PASSWORD': 'Password',
                },
                'kubernetes': {
                    'readinessProbe': {
                        'exec': {
                            'command': [
                                "mysql",
                                "-u", "root",
                                "-h", "127.0.0.1",
                                "-p", "Password",  # FIXME: Harcoded password
                                "-e", "SELECT 1",
                            ]
                        },
                        "timeoutSeconds": 5,
                        "periodSeconds": 5,
                        "initialDelaySeconds": 30,
                    },
                    'livenessProbe': {
                        'exec': {
                            'command': ["mysqladmin", "ping"]
                        },
                        'periodSeconds': 5,
                        'timeoutSeconds': 5,
                        'initialDelaySeconds': 5,
                    }
                },
            }]
        }

        return pod_spec

    # Handles start event
    def on_start(self, event):
        """Initialize MySQL

        This event handler is deferred if initialization of MySQL
        replica set fails. By doing so it is gauranteed that another
        attempt at initialization will be made.
        """
        if not self.unit.is_leader():
            return

        # FIXME: This is awful!!! Only for development purpouses.
        # We need to find a better way to wait for MySQL pod is ready
        import time
        time.sleep(40)

        if not self._mysql_is_ready():
            message = "Waiting for MySQL Service"
            self.unit.status = WaitingStatus(message)
            logger.info(message)
            event.defer()
        else:
            self.unit.status = ActiveStatus("MySQL Service is ready")
            # TODO: If MySQL is up and running we have to create
            # an admin user for InnoDB Cluster on all nodes

    def _mysql_is_ready(self):
        ready = False

        # FIXME: We are harcoding the 0 unit for development porpouses
        # We have to check if MySQL is ready in every unit.
        hostname = self._get_unit_hostname('0')

        try:
            config = {
                'user': 'root',
                'password': 'Password',  # FIXME: Remove harcoded password
                'host': hostname,
            }
            cnx = mysql.connector.connect(**config)
            logger.info("MySQL service is ready.")
            ready = True
        except mysql.connector.Error:
            # TODO: Improve exceptions handling
            logger.info("MySQL service is not ready yet.")
        else:
            cnx.close()

        return ready

    def _get_unit_hostname(self, _id: int) -> str:
        """
        Construct a DNS name for a MySQL unit
        """
        return "{}-{}.{}-endpoints".format(self.model.app.name,
                                           _id,
                                           self.model.app.name)


if __name__ == "__main__":
    main(MySQLOperatorCharm)
