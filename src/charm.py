#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
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


class MySQLCharm(CharmBase):
    """Charm to run MySQL on Kubernetes."""
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.image = OCIImageResource(self, 'mysql-image')
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    @property
    def cluster_size(self) -> int:
        """Return the size of the cluster."""
        rel = self.model.get_relation(PEER)
        return len(rel.units) + 1 if rel is not None else 1

    @property
    def hostnames(self) -> list:
        """Return a list of Kubernetes hostnames."""
        return [self._get_unit_hostname(i) for i in range(self.cluster_size)]

    def _on_start(self, event):
        """Initialize MySQL InnoDB cluster.

        This event handler is deferred if initialization of MySQL
        replica set fails. By doing so it is guaranteed that another
        attempt at initialization will be made.
        """
        if not self.unit.is_leader():
            return

        if not self._mysql_is_ready():
            message = "Waiting for MySQL Service"
            self.unit.status = WaitingStatus(message)
            logger.info(message)
            event.defer()
            return
        else:
            self.unit.status = ActiveStatus("MySQL Service is ready")

        # create admin users on all hosts
        for hostname in self.hostnames:
            self._create_user_on_host(hostname)

    def _create_user_on_host(self, hostname):
        """This method will execute a user creation query for the admin user."""
        logger.warning('Creating user on {}'.format(hostname))
        query = """
                CREATE USER 'idcAdmin'@'%'
                IDENTIFIED BY 'idcAdmin';
                GRANT ALL ON *.* TO 'idcAdmin'@'%'
                WITH GRANT OPTION";
                """

        cnx = self._get_sql_connection_for_host(hostname)
        cur = cnx.cursor()
        cur.execute(query)
        cnx.close()

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

        config = self.model.config
        self.unit.status = WaitingStatus("Assembling pod spec")
        pod_spec = {
            'version': 3,
            'containers': [{
                'name': self.app.name,
                'imageDetails': image_info,
                'ports': [{
                    'containerPort': config['port'],
                    'protocol': 'TCP'
                }],
                'envConfig': {
                    'MYSQL_ROOT_PASSWORD': config['admin-password'],
                },
            }]
        }

        return pod_spec

    def _mysql_is_ready(self):
        """Check that every unit has mysql running.

        Until we have a good event-driven way of using the Kubernetes
        readiness probe, we will attempt
        """
        for hostname in self.hostnames:
            try:
                cnx = self._get_sql_connection_for_host(hostname)
                logger.warning("MySQL service is ready for {}.".format(hostname))
            except mysql.connector.Error:
                # TODO: Improve exceptions handling
                logger.warning("MySQL service is not ready for {}.".format(hostname))
                return False
            else:
                cnx.close()

        return True

    def _get_sql_connection_for_host(self, hostname):
        config = {
            'user': 'root',
            'password': self.model.config['admin-password'],
            'host': hostname,
            'port': self.model.config['port']
        }
        return mysql.connector.connect(**config)

    def _get_unit_hostname(self, _id: int) -> str:
        """Construct a DNS name for a MySQL unit."""
        return "{0}-{1}.{0}-endpoints".format(self.model.app.name, _id)


if __name__ == "__main__":
    main(MySQLCharm)
