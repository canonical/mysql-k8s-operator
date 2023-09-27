# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Custom event for flushing mysql logs."""

import logging
import subprocess
import tempfile
import typing

import jinja2
from charms.mysql.v0.mysql import MySQLExecError, MySQLTextLogs
from ops.charm import CharmEvents
from ops.framework import EventBase, EventSource, Object

from constants import LOG_ROTATE_CONFIG_FILE

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)


class RotateMySQLLogsEvent(EventBase):
    """A custom event to rotate the mysql logs."""


class RotateMySQLLogsCharmEvents(CharmEvents):
    """A CharmEvent extension to rotate mysql logs.

    Includes :class:`RotateMySQLLogsEvent` in those that can be handled.
    """

    rotate_mysql_logs = EventSource(RotateMySQLLogsEvent)


class RotateMySQLLogs(Object):
    """Encapsulates the rotation of mysql logs."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, "rotate-mysql-logs")

        self.charm = charm

        self.framework.observe(self.charm.on.rotate_mysql_logs, self._rotate_mysql_logs)

    def _rotate_mysql_logs(self, _) -> None:
        """Rotate the mysql logs."""
        try:
            self.charm._mysql._execute_commands(["logrotate", "-f", LOG_ROTATE_CONFIG_FILE])
        except MySQLExecError:
            logger.exception("Failed to rotate mysql logs")
            return

        self.charm._mysql.flush_mysql_logs(MySQLTextLogs.ERROR)
        self.charm._mysql.flush_mysql_logs(MySQLTextLogs.GENERAL)
        self.charm._mysql.flush_mysql_logs(MySQLTextLogs.SLOW)

    def _setup_logrotate_dispatcher(self) -> None:
        """Helper method to help set up a pebble plan for the log rotate dispatcher."""
        with open("templates/logrotate.yaml.j2", "r") as file:
            template = jinja2.Template(file.read())

        rendered = template.render(
            charm_directory=self.charm.charm_dir,
            unit_name=self.charm.unit.name,
        )

        with tempfile.NamedTemporaryFile(mode="w") as file:
            file.write(rendered)
            file.flush()

            subprocess.run(
                ["/charm/bin/pebble", "add", "logrotate", file.name],
                check=True,
            )

        subprocess.run(["/charm/bin/pebble", "replan"], check=True)
