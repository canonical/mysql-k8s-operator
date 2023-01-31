# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of backups."""

import datetime
import logging
from typing import Dict, List, Tuple

from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.mysql.v0.mysql import (
    MySQLGetMemberStateError,
    MySQLSetInstanceOfflineModeError,
    MySQLSetInstanceOptionError,
)
from ops.charm import ActionEvent, CharmBase
from ops.framework import Object
from ops.jujuversion import JujuVersion

from mysql_k8s_helpers import MySQLExecuteBackupCommandsError
from s3_helpers import list_subdirectories_in_path, upload_content_to_s3

logger = logging.getLogger(__name__)

MYSQL_BACKUPS = "mysql-backups"
BACKUPS_KEY = "backups"
UNIT_BACKUPS_KEY = "unit-backups"


class MySQLBackups(Object):
    """Encapsulation of backups for MySQL."""

    def __init__(self, charm: CharmBase, s3_integrator: S3Requirer) -> None:
        super().__init__(charm, MYSQL_BACKUPS)

        self.charm = charm
        self.s3_integrator = s3_integrator

        self.framework.observe(self.charm.on.create_backup_action, self._on_create_backup)
        self.framework.observe(self.charm.on.list_backups_action, self._on_list_backups)

    def _on_list_backups(self, event: ActionEvent) -> None:
        """Handle the list backups action.

        List backups available to restore by this application.
        """
        try:
            s3_parameters, missing_parameters = self._retrieve_s3_parameters()
            if missing_parameters:
                event.fail(f"Missing S3 parameters: {missing_parameters}")
                return

            backup_ids = list_subdirectories_in_path(
                s3_parameters["bucket"],
                s3_parameters["path"],
                s3_parameters["region"],
                s3_parameters["endpoint"],
                s3_parameters["access-key"],
                s3_parameters["secret-key"],
            )
            event.set_results({"backup-ids": backup_ids})
        except Exception:
            event.fail("Failed to retrieve backup ids from S3")

    def _on_create_backup(self, event: ActionEvent) -> None:
        """Handle the create backup action."""
        logger.info("A backup has been requested on unit")

        datetime_backup_requested = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

        # Retrieve and validate missing S3 parameters
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            event.fail(f"Missing S3 parameters: {missing_parameters}")
            return

        s3_directory = f"{s3_parameters['path']}/{datetime_backup_requested}"

        # Check if this unit can perform backup
        can_unit_perform_backup, validation_message = self._can_unit_perform_backup()
        if not can_unit_perform_backup:
            logger.warning(validation_message)
            event.fail(validation_message)
            return

        # Test uploading metadata to S3 to test credentials before backup
        juju_version = JujuVersion.from_environ()
        metadata = f"""Date Backup Requested: {datetime_backup_requested}
Model Name: {self.model.name}
Application Name: {self.model.app.name}
Unit Name: {self.charm.unit.name}
Juju Version: {str(juju_version)}
"""
        success = upload_content_to_s3(
            metadata,
            s3_parameters["bucket"],
            f"{s3_directory}/metadata",
            s3_parameters["region"],
            s3_parameters["endpoint"],
            s3_parameters["access-key"],
            s3_parameters["secret-key"],
        )
        if not success:
            event.fail("Failed to upload metadata to provided S3")
            return

        # Run operations to prepare for the backup
        success, error_message = self._pre_backup()
        if not success:
            logger.warning(error_message)
            event.fail(error_message)
            return

        # Perform the backup
        success, error_message = self._backup(
            s3_parameters["bucket"],
            s3_directory,
            s3_parameters["endpoint"],
            s3_parameters["region"],
            s3_parameters["access-key"],
            s3_parameters["secret-key"],
        )
        if not success:
            logger.warning(error_message)
            event.fail(error_message)

            success, error_message = self._post_backup()
            if not success:
                logger.warning(error_message)

            return

        # Run operations to clean up after the backup
        success, error_message = self._post_backup()
        if not success:
            logger.warning(error_message)
            event.fail(error_message)
            return

        event.set_results(
            {
                "backup-id": datetime_backup_requested,
            }
        )

    def _retrieve_s3_parameters(self) -> Tuple[Dict, List[str]]:
        """Retrieve S3 parameters from the S3 integrator relation."""
        s3_parameters = self.s3_integrator.get_s3_connection_info()

        required_parameters = [
            "bucket",
            "endpoint",
            "region",
            "path",
            "access-key",
            "secret-key",
        ]
        missing_parameters = [param for param in required_parameters if param not in s3_parameters]
        if missing_parameters:
            logger.warning(
                f"Missing required S3 parameters in relation with S3 integrator: {missing_parameters}"
            )

        return s3_parameters, missing_parameters

    def _can_unit_perform_backup(self) -> Tuple[bool, str]:
        """Validates whether this unit can perform a backup."""
        logger.info("Checking if cluster is in blocked state")
        if self.charm._is_cluster_blocked():
            return False, "Cluster or unit is in a blocking state"

        logger.info("Checking state and role of unit")

        try:
            state, role = self.charm._mysql.get_member_state()
        except MySQLGetMemberStateError:
            return False, "Error obtaining member state"

        if role == "primary" and self.charm.app.planned_units() > 1:
            return False, "Unit cannot perform backups as it is the cluster primary"

        if state in ["recovering", "offline", "error"]:
            return False, f"Unit cannot perform backups as its state is {state}"

        return True, None

    def _pre_backup(self) -> Tuple[bool, str]:
        """Runs operations required before performing a backup."""
        logger.info("Setting cluster state as 'backing-up'")
        self.charm.unit_peer_data["cluster-state"] = "backing-up"

        try:
            logger.info("Setting unit option tag:_hidden")
            self.charm._mysql.set_instance_option("tag:_hidden", "true")
        except MySQLSetInstanceOptionError:
            self.charm.unit_peer_data["cluster-state"] = "active"
            return False, "Error setting instance option tag:_hidden"

        try:
            logger.info("Setting unit as offline before performing backup")
            self.charm._mysql.set_instance_offline_mode(True)
        except MySQLSetInstanceOfflineModeError:
            self.charm.unit_peer_data["cluster-state"] = "active"
            self.charm._mysql.set_instance_option("tag:_hidden", "false")
            return False, "Error setting instance as offline before performing backup"

        return True, None

    def _upload_logs_to_s3(
        self: str,
        stdout: str,
        stderr: str,
        s3_bucket: str,
        log_filename: str,
        s3_region: str,
        s3_endpoint: str,
        s3_access_key: str,
        s3_secret_key: str,
    ) -> bool:
        logs = f"""Stdout:
{stdout}

Stderr:
{stderr}
        """
        logger.debug(f"Output of xtrabackup: {logs}")

        logger.info("Uploading output of xtrabackup to S3")
        return upload_content_to_s3(
            logs,
            s3_bucket,
            log_filename,
            s3_region,
            s3_endpoint,
            s3_access_key,
            s3_secret_key,
        )

    def _backup(
        self,
        s3_bucket: str,
        s3_directory: str,
        s3_endpoint: str,
        s3_region: str,
        s3_access_key: str,
        s3_secret_key: str,
    ) -> None:
        """Runs the backup operations."""
        try:
            logger.info("Running the xtrabackup commands")
            stdout, stderr = self.charm._mysql.execute_backup_commands(
                s3_bucket,
                f"{s3_directory}/backup",
                s3_access_key,
                s3_secret_key,
            )
        except MySQLExecuteBackupCommandsError as e:
            self._upload_logs_to_s3(
                "",
                e.message,
                s3_bucket,
                f"{s3_directory}/xtrabackup.log",
                s3_region,
                s3_endpoint,
                s3_access_key,
                s3_secret_key,
            )
            return False, "Error backing up the database"

        if not self._upload_logs_to_s3(
            stdout,
            stderr,
            s3_bucket,
            f"{s3_directory}/xtrabackup.log",
            s3_region,
            s3_endpoint,
            s3_access_key,
            s3_secret_key,
        ):
            return False, "Error uploading logs to S3"

        return True, None

    def _post_backup(self) -> Tuple[bool, str]:
        """Runs operations required after performing a backup."""
        logger.info("Setting cluster state as 'active'")
        self.charm.unit_peer_data["cluster-state"] = "active"

        try:
            logger.info("Unsetting unit as offline after performing backup")
            self.charm._mysql.set_instance_offline_mode(False)
        except MySQLSetInstanceOfflineModeError:
            return False, "Error unsetting instance as offline before performing backup"

        try:
            logger.info("Setting unit option tag:_hidden as false")
            self.charm._mysql.set_instance_option("tag:_hidden", "false")
        except MySQLSetInstanceOptionError:
            return False, "Error setting instance option tag:_hidden"

        return True, None
