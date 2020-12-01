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
        # initialize image resource
        self.image = OCIImageResource(self, 'mysql-image')
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
            image_info = self.image.fetch()
        except OCIImageResourceError:
            logging.exception('An error occurred while fetching the image info')
            self.unit.status = BlockedStatus('Error fetching image information')
            return {}

        # baseline pod spec
        spec = {
            'version': 3,
            'containers': [{
                'name': self.app.name,
                'imageDetails': image_info,
                'ports': [{
                    'containerPort': 3306,
                    'protocol': 'TCP'
                }],
                'envConfig': {
                    'MYSQL_ROOT_PASSWORD': 'Password',
                }
            }]
        }

        return spec


if __name__ == "__main__":
    main(MySQLOperatorCharm)
