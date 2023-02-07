# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of backups."""

import datetime
import logging
from typing import Dict, List, Tuple

from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.mysql.v0.mysql import (
    MySQLCreateClusterError,
    MySQLGetMemberStateError,
    MySQLSetInstanceOfflineModeError,
    MySQLSetInstanceOptionError,
)
from ops.charm import ActionEvent, CharmBase
from ops.framework import Object
from ops.jujuversion import JujuVersion
from ops.model import BlockedStatus
from ops.pebble import ChangeError

from constants import CONTAINER_NAME, MYSQLD_SERVICE
from mysql_k8s_helpers import (
    MySQLEmptyDataDirectoryError,
    MySQLExecuteBackupCommandsError,
    MySQLPrepareBackupForRestoreError,
    MySQLReconfigureInstanceError,
    MySQLRestoreBackupError,
    MySQLRetrieveBackupWithXBCloudError,
    MySQLServiceNotRunningError,
)
from s3_helpers import (
    check_existence_of_s3_path,
    list_backups_in_s3_path,
    upload_content_to_s3,
)

logger = logging.getLogger(__name__)

MYSQL_BACKUPS = "mysql-backups"


class MySQLBackups(Object):
    """Encapsulation of backups for MySQL."""

    def __init__(self, charm: CharmBase, s3_integrator: S3Requirer) -> None:
        super().__init__(charm, MYSQL_BACKUPS)

        self.charm = charm
        self.s3_integrator = s3_integrator

        self.framework.observe(self.charm.on.create_backup_action, self._on_create_backup)
        self.framework.observe(self.charm.on.list_backups_action, self._on_list_backups)
        self.framework.observe(self.charm.on.restore_backup_action, self._on_restore_backup)

    # ------------------ Helpers ------------------

    def _retrieve_s3_parameters(self) -> Tuple[Dict, List[str]]:
        """Retrieve S3 parameters from the S3 integrator relation."""
        s3_parameters = self.s3_integrator.get_s3_connection_info()

        required_parameters = [
            "bucket",
            "access-key",
            "secret-key",
        ]
        missing_required_parameters = [
            param for param in required_parameters if param not in s3_parameters
        ]
        if missing_required_parameters:
            logger.warning(
                f"Missing required S3 parameters in relation with S3 integrator: {missing_required_parameters}"
            )
            return {}, missing_required_parameters

        # Add some sensible defaults (as expected by the code) for missing optional parameters
        s3_parameters.setdefault("endpoint", "https://s3.amazonaws.com")
        s3_parameters.setdefault("region")
        s3_parameters.setdefault("path", "")

        return s3_parameters, []

    def _upload_logs_to_s3(
        self: str,
        stdout: str,
        stderr: str,
        log_filename: str,
        s3_parameters: Dict,
    ) -> bool:
        logs = f"""Stdout:
{stdout}

Stderr:
{stderr}
        """
        logger.debug(f"Logs to upload to S3 at location {log_filename}:\n{logs}")

        logger.info(
            f"Uploading logs to S3 at bucket={s3_parameters['bucket']}, location={log_filename}"
        )
        return upload_content_to_s3(logs, log_filename, s3_parameters)

    # ------------------ List Backups ------------------

    def _on_list_backups(self, event: ActionEvent) -> None:
        """Handle the list backups action.

        List backups available to restore by this application.
        """
        try:
            logger.info("Retrieving s3 parameters from the s3-integrator relation")
            s3_parameters, missing_parameters = self._retrieve_s3_parameters()
            if missing_parameters:
                event.fail(f"Missing S3 parameters: {missing_parameters}")
                return

            logger.info("Listing backups in the specified s3 path")
            backup_ids = list_backups_in_s3_path(s3_parameters)
            event.set_results({"backup-ids": backup_ids})
        except Exception:
            event.fail("Failed to retrieve backup ids from S3")

    # ------------------ Create Backup ------------------

    def _on_create_backup(self, event: ActionEvent) -> None:
        """Handle the create backup action."""
        logger.info("A backup has been requested on unit")

        if not self.charm.unit.get_container(CONTAINER_NAME).can_connect():
            error_message = f"Container {CONTAINER_NAME} not ready yet!"
            logger.warning(error_message)
            event.fail(error_message)
            return

        datetime_backup_requested = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

        # Retrieve and validate missing S3 parameters
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            event.fail(f"Missing S3 parameters: {missing_parameters}")
            return

        backup_path = f"{s3_parameters['path']}/{datetime_backup_requested}"

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

        if not upload_content_to_s3(metadata, f"{backup_path}.metadata", s3_parameters):
            event.fail("Failed to upload metadata to provided S3")
            return

        # Run operations to prepare for the backup
        success, error_message = self._pre_backup()
        if not success:
            logger.warning(error_message)
            event.fail(error_message)
            return

        # Perform the backup
        success, error_message = self._backup(backup_path, s3_parameters)
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

    def _backup(self, backup_path: str, s3_parameters: Dict) -> Tuple[bool, str]:
        """Runs the backup operations."""
        try:
            logger.info("Running the xtrabackup commands")
            stdout, stderr = self.charm._mysql.execute_backup_commands(
                s3_parameters["bucket"],
                backup_path,
                s3_parameters["access-key"],
                s3_parameters["secret-key"],
                s3_parameters["endpoint"],
            )
        except MySQLExecuteBackupCommandsError as e:
            self._upload_logs_to_s3(
                "",
                e.message,
                f"{backup_path}.backup.log",
                s3_parameters,
            )
            return False, "Error backing up the database"

        if not self._upload_logs_to_s3(
            stdout,
            stderr,
            f"{backup_path}.backup.log",
            s3_parameters,
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

    # ------------------ Perform Restore ------------------

    def _on_restore_backup(self, event: ActionEvent) -> None:
        """Handle the restore backup action event.

        Restore a backup from S3 (parameters for which can retrieved from the
        relation with S3 integrator).
        """
        backup_id = event.params.get("backup-id")
        if not backup_id:
            event.fail("Missing backup-id to restore")
            return

        logger.info(f"A restore with backup-id {backup_id} has been requested on unit")

        if not self.charm.unit.get_container(CONTAINER_NAME).can_connect():
            error_message = f"Container {CONTAINER_NAME} not ready yet!"
            logger.warning(error_message)
            event.fail(error_message)
            return

        # Retrieve and validate missing S3 parameters
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            event.fail(f"Missing S3 parameters: {missing_parameters}")
            return

        # Validate the provided backup id
        logger.info("Validating provided backup-id in the specified s3 path")
        s3_directory = (
            s3_parameters["path"]
            if s3_parameters["path"][-1] == "/"
            else f"{s3_parameters['path']}/"
        )
        s3_backup_md5 = f"{s3_directory}{backup_id}.md5"
        if not check_existence_of_s3_path(s3_parameters, s3_backup_md5):
            event.fail(f"Invalid backup-id: {backup_id}")
            return

        # Check if this unit can restore backup
        can_unit_restore_backup, validation_message = self._can_unit_restore_backup()
        if not can_unit_restore_backup:
            logger.warning(validation_message)
            event.fail(validation_message)
            return

        # Run operations to prepare for the restore
        success, error_message = self._pre_restore()
        if not success:
            logger.warning(error_message)
            event.fail(error_message)
            return

        # Perform the restore
        success, recoverable, error_message = self._restore(backup_id, s3_parameters)
        if not success:
            logger.warning(error_message)
            event.fail(error_message)

            if recoverable:
                logger.info("Setting cluster state as 'active'")
                self.charm.unit_peer_data["cluster-state"] = "active"
            else:
                self.charm.unit.status = BlockedStatus(error_message)

            return

        # Run post-restore operations
        success, error_message = self._post_restore()
        if not success:
            logger.warning(error_message)
            self.charm.unit.status = BlockedStatus(error_message)
            event.fail(error_message)
            return

        event.set_results(
            {
                "completed": "ok",
            }
        )

    def _can_unit_restore_backup(self) -> Tuple[bool, str]:
        """Validates whether this unit can restore a backup."""
        logger.info("Checking if cluster is in blocked state")
        if self.charm._is_cluster_blocked():
            return False, "Cluster or unit is in a blocking state"

        # TODO: Consider what happens if planned_units = 1,
        # but there are more than 1 units in the cluster still
        logger.info("Checking that the cluster does not have more than one unit")
        if self.charm.app.planned_units() > 1:
            return (
                False,
                "Unit cannot restore backup as there are more than one units in the cluster",
            )

        return True, None

    def _pre_restore(self) -> Tuple[bool, str]:
        """Perform operations that need to be done before performing a restore."""
        logger.info("Setting cluster state as 'restoring'")
        self.charm.unit_peer_data["cluster-state"] = "restoring"

        logger.info(f"Stopping service {MYSQLD_SERVICE} in container {CONTAINER_NAME}")
        # TODO: wrap around try/except for ops.model.ModelError?
        container = self.charm.unit.get_container(CONTAINER_NAME)

        try:
            container.stop(MYSQLD_SERVICE)
        except ChangeError as e:
            logger.info("Setting cluster state as 'active'")
            self.charm.unit_peer_data["cluster-state"] = "active"

            error_message = f"Failed to stop service {MYSQLD_SERVICE}"
            logger.exception(error_message, exc_info=e)
            return False, error_message

        return True, None

    def _restore(self, backup_id: str, s3_parameters: Dict) -> Tuple[bool, bool, str]:
        """Run the restore operations."""
        datetime_restore_requested = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

        # TODO: more robustly handle raised errors
        try:
            logger.info("Running xbcloud get commands to retrieve the backup")
            stdout, stderr, backup_location = self.charm._mysql.retrieve_backup_with_xbcloud(
                s3_parameters["bucket"],
                s3_parameters["path"],
                s3_parameters["access-key"],
                s3_parameters["secret-key"],
                backup_id,
            )

            # TODO: come up with naming schema for log files
            logfile_path = f"{s3_parameters['path'].rstrip('/')}/{datetime_restore_requested}.retrieve-{backup_id}.log"
            self._upload_logs_to_s3(stdout, stderr, logfile_path, s3_parameters)
        except MySQLRetrieveBackupWithXBCloudError:
            return False, True, f"Failed to retrieve backup {backup_id}"

        try:
            logger.info("Preparing retrieved backup using xtrabackup prepare")
            stdout, stderr = self.charm._mysql.prepare_backup_for_restore(backup_location)

            logfile_path = f"{s3_parameters['path'].rstrip('/')}/{datetime_restore_requested}.prepare-{backup_id}.log"
            self._upload_logs_to_s3(stdout, stderr, logfile_path, s3_parameters)
        except MySQLPrepareBackupForRestoreError:
            return False, True, f"Failed to prepare backup {backup_id}"

        try:
            logger.info("Removing the contents of the data directory")
            self.charm._mysql.empty_data_directory()
        except MySQLEmptyDataDirectoryError:
            return False, False, "Failed to empty the data directory"

        try:
            logger.info("Restoring the backup")
            stdout, stderr = self.charm._mysql.restore_backup(backup_location)

            logfile_path = f"{s3_parameters['path'].rstrip('/')}/{datetime_restore_requested}.restore-{backup_id}.log"
            self._upload_logs_to_s3(stdout, stderr, logfile_path, s3_parameters)
        except MySQLRestoreBackupError:
            return False, False, f"Failed to restore backup {backup_id}"

        return True, True, None

    def _post_restore(self) -> Tuple[bool, str]:
        """Run operations required after restoring a backup."""
        logger.info(f"Starting service {MYSQLD_SERVICE} in container {CONTAINER_NAME}")
        # TODO: wrap around try/except for ops.model.ModelError
        container = self.charm.unit.get_container(CONTAINER_NAME)

        try:
            container.start(MYSQLD_SERVICE)
            self.charm._mysql.wait_until_mysql_connection()
        except (
            ChangeError,
            MySQLServiceNotRunningError,
        ) as e:
            error_message = f"Failed to start service {MYSQLD_SERVICE}"
            logger.exception(error_message, exc_info=e)
            return False, error_message

        try:
            logger.info("Configuring instance to be part of an InnoDB cluster")
            self.charm._mysql.reconfigure_instance()
        except MySQLReconfigureInstanceError:
            return False, "Failed to configure restored instance for InnoDB cluster"

        self.charm.unit_peer_data["unit-configured"] = "True"

        try:
            logger.info("Creating cluster on restored node")
            unit_label = self.charm.unit.name.replace("/", "-")
            self.charm._mysql.create_cluster(unit_label)

            logger.info("Retrieving instance cluster state and role")
            state, role = self.charm._mysql.get_member_state()
        except MySQLCreateClusterError:
            return False, "Failed to create InnoDB cluster on restored instance"
        except MySQLGetMemberStateError:
            return False, "Failed to retrieve member state in restored instance"

        self.charm.unit_peer_data["member-role"] = role
        self.charm.unit_peer_data["member-state"] = state

        logger.info("Setting cluster state as 'active'")
        self.charm.unit_peer_data["cluster-state"] = "active"

        return True, None
