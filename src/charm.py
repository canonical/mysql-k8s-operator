#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for MySQL InnoDB Cluster."""

import logging
import secrets
import string

from ops.charm import CharmBase, WorkloadEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class MysqlOperatorCharm(CharmBase):
    """A Juju Charm for MySQL InnoDB Cluster."""

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.mysql_server_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.mysql_router_pebble_ready, self._on_pebble_ready)

    # ---- Event handlers
    def _on_start(self, _):
        """Placeholder for StartEvent."""
        pass

    def _on_config_changed(self, _):
        """Placeholder for ConfigChangedEvent."""
        pass

    def _on_pebble_ready(self, event: WorkloadEvent) -> None:
        """Updates the Pebble configuration layer when changed."""
        container = event.workload
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for pod startup to complete")
            event.defer()
            return

        # Get current config
        current_layer = container.get_plan()
        # Create a new config layer
        service_name = container.name
        new_layer = self._mysql_layer(service_name=service_name)

        if current_layer.services != new_layer.services:
            container.add_layer(service_name, new_layer, combine=True)
            logging.info("Pebble plan updated with new configuration")
            container.restart(service_name)

        self.unit.status = ActiveStatus()

    # ---- Helper functions
    def _generate_password(self) -> str:
        """Returns a random 12 alphanumeric string that can be used as password."""
        alphanums = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphanums) for _ in range(12))

    def _mysql_layer(self, service_name: str) -> Layer:
        """Defines a Pebble configuration Layer for mysql services.

        Args:
            service_name: Name of the service the Layer will be configured to.

        Returns:
            A pre-configured Pebble Layer.
        """
        # FIXME: mysqlrouter cannot be started correctly as it
        # is missing important information about the cluster.
        layer_config = {
            "summary": "MySQL Router layer",
            "description": "Pebble layer configuration for MySQL Router",
            "services": {
                service_name: {
                    "override": "replace",
                    "summary": "mysqlsh router",
                    "command": "/run.sh mysqlrouter",
                    "startup": "enabled",
                }
            },
        }

        if service_name == "mysql-server":
            env_config = {
                "MYSQL_USER": self._config["mysql_user"],
                "MYSQL_PASSWORD": self._config["mysql_password"],
                "MYSQL_ROOT_PASSWORD": self._config["mysql_root_password"],
            }

            layer_config = {
                "summary": "MySQL Server layer",
                "description": "Pebble layer configuration for MySQL Server",
                "services": {
                    service_name: {
                        "override": "replace",
                        "summary": "mysql server instance",
                        "command": "docker-entrypoint.sh mysqld",
                        "startup": "enabled",
                        "environment": env_config,
                    }
                },
            }
        return Layer(layer_config)

    # ---- Properties
    @property
    def _config(self):
        """Configuration data for MySQL authentication."""
        config = {
            "mysql_user": "mysql_user",
            "mysql_password": self._generate_password(),
            "mysql_root_password": self._generate_password(),
        }
        return config


if __name__ == "__main__":
    main(MysqlOperatorCharm)
