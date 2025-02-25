# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Log rotate manager."""

import logging
import os
import signal
import subprocess
import typing

from ops.framework import Object
from ops.model import ActiveStatus

from constants import CONTAINER_NAME

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)


class LogRotateManager(Object):
    """Manages log rotation for the charm.

    Dispatches a custom event every 60s to rotate mysql logs in the workload container.
    """

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, "log-rotate-manager")

        self.charm = charm

    def start_log_rotate_manager(self):
        """Forks off a process that periodically dispatch a custom event to rotate logs."""
        container = self.charm.unit.get_container(CONTAINER_NAME)
        if (
            not isinstance(self.charm.unit.status, ActiveStatus)
            or self.charm.peers is None
            or not container.can_connect()
            or not self.charm.unit_initialized()
        ):
            return

        if "log-rotate-manager-pid" in self.charm.unit_peer_data:
            pid = int(self.charm.unit_peer_data["log-rotate-manager-pid"])
            try:
                os.kill(pid, 0)  # Check if the process exists
                return
            except OSError:
                pass

        logger.info("Starting the log rotate manager")

        # We need to trick Juju into thinking that we are not running
        # in a hook context, as Juju will disallow use of juju-run.
        new_env = os.environ.copy()
        new_env.pop("JUJU_CONTEXT_ID", None)

        # Use Popen instead of run as the log rotate dispatcher is a long running
        # process that shouldn't block the event handler
        process = subprocess.Popen(
            [
                "/usr/bin/python3",
                "scripts/log_rotate_dispatcher.py",
                self.charm.unit.name,
                self.charm.charm_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=new_env,
        )

        self.charm.unit_peer_data.update({"log-rotate-manager-pid": str(process.pid)})
        logger.info(f"Started log rotate manager process with PID {process.pid}")

    def stop_log_rotate_manager(self):
        """Stop the log rotate manager process."""
        if self.charm.peers is None or "log-rotate-manager-pid" not in self.charm.unit_peer_data:
            return

        log_rotate_manager_pid = int(self.charm.unit_peer_data["log-rotate-manager-pid"])

        try:
            os.kill(log_rotate_manager_pid, signal.SIGTERM)
            logger.info(f"Stopped log rotate manager process with PID {log_rotate_manager_pid}")
            del self.charm.unit_peer_data["log-rotate-manager-pid"]
        except OSError:
            pass
