# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of backups."""

import logging
from typing import Tuple

from constants import SERVER_CONFIG_USERNAME, SERVER_CONFIG_PASSWORD_KEY
from charms.mysql.v0.mysql import (
    MySQLGetMemberStateError,
    MySQLSetInstanceOfflineModeError,
    MySQLSetInstanceOptionError,
)
from mysql_k8s_helpers import MySQLExecuteBackupScriptError
from ops.charm import ActionEvent, CharmBase
from ops.framework import Object

logger = logging.getLogger(__name__)

MYSQL_BACKUPS = "mysql-backups"


class MySQLBackups(Object):
    """Encapsulation of backups for MySQL."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, MYSQL_BACKUPS)

        self.charm = charm

        self.framework.observe(self.charm.on.perform_backup_action, self._on_perform_backup)

    def _on_perform_backup(self, event: ActionEvent) -> None:
        """Perform backup action."""
        logger.info("A backup has been requested on unit")

        s3_bucket = event.params.get("s3-bucket")
        s3_path = event.params.get("s3-path")
        s3_access_key = event.params.get("s3-access-key")
        s3_secret_key = event.params.get("s3-secret-key")

        if not s3_bucket or not s3_path or not s3_access_key or not s3_secret_key:
            logger.warning("Missing S3 parameters while trying to perform a backup")
            event.set_results(
                {
                    "success": False,
                    "message": "Missing S3 parameters",
                }
            )
            return

        can_unit_perform_backup, validation_message = self._can_unit_perform_backup()
        if not can_unit_perform_backup:
            logger.warning(validation_message)
            event.set_results(
                {
                    "success": False,
                    "message": validation_message,
                }
            )
            return

        success, error_message = self._pre_backup()
        if not success:
            logger.warning(error_message)
            event.set_results(
                {
                    "success": False,
                    "message": error_message,
                }
            )

        success, error_message = self._backup(
            s3_bucket,
            s3_path,
            s3_access_key,
            s3_secret_key,
        )
        if not success:
            logger.warning(error_message)
            event.set_results(
                {
                    "success": False,
                    "message": error_message
                }
            )

            success, error_message = self._post_backup()
            if not success:
                logger.warning(error_message)

            return

        success, error_message = self._post_backup()
        if not success:
            logger.warning(error_message)
            event.set_results(
                {
                    "success": False,
                    "message": error_message,
                }
            )
            return

        event.set_results(
            {
                "success": True,
            }
        )

    def _can_unit_perform_backup(self) -> Tuple[bool, str]:
        """Validates whether this unit can perform a backup."""
        logger.debug("Checking if state and role of unit")

        try:
            state, role = self.charm._mysql.get_member_state()
        except MySQLGetMemberStateError:
            return False, "Error obtaining member state"

        if role == "primary":
            return False, "Unit cannot perform backups as it is the cluster primary"

        if state in ["recovering", "offline", "error"]:
            return False, f"Unit cannot perform backups as its state is {state}"

        return True, None

    def _pre_backup(self) -> Tuple[bool, str]:
        """Runs operations required before performing a backup."""
        logger.debug("Setting cluster state as 'backing-up'")
        self.charm.unit_peer_data["cluster-state"] = "backing-up"

        try:
            logger.debug("Setting unit option tag:_hidden")
            self.charm._mysql.set_instance_option("tag:_hidden", "true")

            logger.debug("Setting unit as offline before performing backup")
            self.charm._mysql.set_instance_offline_mode(True)
        except MySQLSetInstanceOfflineModeError:
            return False, "Error setting instance as offline before performing backup"
        except MySQLSetInstanceOptionError:
            return False, "Error setting instance option tag:_hidden"

        return True, None

    def _backup(
        self, s3_bucket: str, s3_path: str, s3_access_key: str, s3_secret_key: str
    ) -> None:
        """Runs the backup operations."""
        try:
            logger.debug("Running the xtrabackup commands")
            self.charm._mysql.execute_backup_script(
                s3_bucket,
                s3_path,
                s3_access_key,
                s3_secret_key,
                SERVER_CONFIG_USERNAME,
                self.charm.app_peer_data[SERVER_CONFIG_PASSWORD_KEY],
            )
        except MySQLExecuteBackupScriptError:
            return False, "Error backing up the database"

        return True, None

    def _post_backup(self) -> Tuple[bool, str]:
        """Runs operations required after performing a backup."""
        logger.debug("Setting cluster state as 'active'")
        self.charm.unit_peer_data["cluster-state"] = "active"

        try:
            logger.debug("Unsetting unit as offline after performing backup")
            self.charm._mysql.set_instance_offline_mode(False)

            logger.debug("Setting unit option tag:_hidden as false")
            self.charm._mysql.set_instance_option("tag:_hidden", "false")
        except MySQLSetInstanceOfflineModeError:
            return False, "Error unsetting instance as offline before performing backup"
        except MySQLSetInstanceOptionError:
            return False, "Error setting instance option tag:_hidden"

        return True, None