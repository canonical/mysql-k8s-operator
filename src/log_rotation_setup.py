# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Handler for log rotation setup in relation to COS."""

import logging
import typing

import yaml
from ops.framework import Object

from constants import CONTAINER_NAME, COS_LOGGING_RELATION_NAME

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)

_POSITIONS_FILE = "/opt/promtail/positions.yaml"
_LOGS_SYNCED = "logs_synced"


class LogRotationSetup(Object):
    """Configure logrotation settings in relation to COS integration."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, "log-rotation-setup")

        self.charm = charm

        self.framework.observe(self.charm.on.update_status, self._update_logs_rotation)
        self.framework.observe(
            self.charm.on[COS_LOGGING_RELATION_NAME].relation_created, self._cos_relation_created
        )
        self.framework.observe(
            self.charm.on[COS_LOGGING_RELATION_NAME].relation_broken, self._cos_relation_broken
        )

    @property
    def _logs_are_syncing(self):
        return self.charm.unit_peer_data.get(_LOGS_SYNCED) == "true"

    def setup(self):
        """Setup log rotation."""
        # retention setting
        if self.charm.config.logs_retention_period == "auto":
            retention_period = 1 if self._logs_are_syncing else 3
        else:
            retention_period = int(self.charm.config.logs_retention_period)

        # compression setting
        compress = self._logs_are_syncing or not self.charm.has_cos_relation

        self.charm._mysql.setup_logrotate_config(retention_period, self.charm.text_logs, compress)

    def _update_logs_rotation(self, _):
        """Check for log rotation auto configuration handler.

        Reconfigure log rotation if promtail/gagent start sync.
        """
        if not self.model.get_relation(COS_LOGGING_RELATION_NAME):
            return

        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        if self._logs_are_syncing:
            # reconfiguration done
            return

        not_started_msg = "Log syncing not yet started."
        if not container.exists(_POSITIONS_FILE):
            logger.debug(not_started_msg)
            return

        positions_file = container.pull(_POSITIONS_FILE, encoding="utf-8")
        positions = yaml.safe_load(positions_file.read())

        if sync_files := positions.get("positions"):
            for log_file, line in sync_files.items():
                if "mysql" in log_file and int(line) > 0:
                    break
            else:
                logger.debug(not_started_msg)
                return
        else:
            logger.debug(not_started_msg)
            return

        logger.info("Reconfigure log rotation after logs upload started")
        self.charm.unit_peer_data[_LOGS_SYNCED] = "true"
        self.setup()

    def _cos_relation_created(self, event):
        """Handle relation created."""
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return

        if not self.charm.app_peer_data.get("cluster-name"):
            event.defer()
            logger.info("Cluster name not set, deferring log rotation setup")
            return

        logger.info("Reconfigure log rotation on cos relation created")
        self.setup()

    def _cos_relation_broken(self, _):
        """Unset auto value for log retention."""
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            return
        logger.info("Reconfigure log rotation after logs upload stops")

        del self.charm.unit_peer_data["logs_synced"]
        self.setup()
