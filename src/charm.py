#!/usr/bin/env python3
# Copyright 2020 jose
# See LICENSE file for licensing details.

import logging

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
        self._stored.set_default(things=[])

    def _on_config_changed(self, _):
        self._configure_pod()

    def _configure_pod(self):
        """Configure the K8s pod spec for Graylog."""
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
                            'command': ["mysql", "-h", "127.0.0.1", "-e", "SELECT 1"]
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


if __name__ == "__main__":
    main(MySQLOperatorCharm)
