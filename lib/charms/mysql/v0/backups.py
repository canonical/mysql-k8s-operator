# Copyright 2022 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""MySQL helper class for backups and restores.

The `MySQLBackups` class can be instantiated by a MySQL charm , and contains
event handlers for `list-backups`, `create-backup` and `restore` backup actions.
These actions must be added to the actions.yaml file.

An example of instantiating the `MySQLBackups`:

```python
from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.mysql.v0.backups import MySQLBackups
from charms.mysql.v0.backups import MySQLBase


class MySQL(MySQLBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.s3_integrator = S3Requirer(self, "s3-integrator")
        self.backups = MySQLBackups(self, self.s3_integrator)

    @property
    def s3_integrator_relation_exists(self) -> bool:
        # Returns whether a relation with the s3-integrator exists
        return bool(self.model.get_relation(S3_INTEGRATOR_RELATION_NAME))

    def is_unit_blocked(self) -> bool:
        # Returns whether the unit is in blocked state and should run any operations
        return False
```

"""

import datetime
import logging
import pathlib
import re
import typing
from typing import Dict, List, Optional, Tuple

from charms.data_platform_libs.v0.s3 import (
    CredentialsChangedEvent,
    CredentialsGoneEvent,
    S3Requirer,
)
from charms.mysql.v0.mysql import (
    MySQLConfigureInstanceError,
    MySQLCreateClusterError,
    MySQLCreateClusterSetError,
    MySQLDeleteTempBackupDirectoryError,
    MySQLDeleteTempRestoreDirectoryError,
    MySQLEmptyDataDirectoryError,
    MySQLExecuteBackupCommandsError,
    MySQLInitializeJujuOperationsTableError,
    MySQLKillSessionError,
    MySQLNoMemberStateError,
    MySQLOfflineModeAndHiddenInstanceExistsError,
    MySQLPrepareBackupForRestoreError,
    MySQLRescanClusterError,
    MySQLRestoreBackupError,
    MySQLRestorePitrError,
    MySQLRetrieveBackupWithXBCloudError,
    MySQLServiceNotRunningError,
    MySQLSetInstanceOfflineModeError,
    MySQLSetInstanceOptionError,
    MySQLStartMySQLDError,
    MySQLStopMySQLDError,
    MySQLUnableToGetMemberStateError,
)
from charms.mysql.v0.s3_helpers import (
    _construct_endpoint,
    ensure_s3_compatible_group_replication_id,
    fetch_and_check_existence_of_s3_path,
    list_backups_in_s3_path,
    upload_content_to_s3,
)
from ops.charm import ActionEvent
from ops.framework import Object
from ops.jujuversion import JujuVersion
from ops.model import BlockedStatus, MaintenanceStatus

from constants import (
    MYSQL_DATA_DIR,
    PEER,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)

logger = logging.getLogger(__name__)

MYSQL_BACKUPS = "mysql-backups"
S3_INTEGRATOR_RELATION_NAME = "s3-parameters"

# The unique Charmhub library identifier, never change it
LIBID = "183844304be247129572309a5fb1e47c"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 14

ANOTHER_S3_CLUSTER_REPOSITORY_ERROR_MESSAGE = "S3 repository claimed by another cluster"
MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR = (
    "Move restored cluster to another S3 repository"
)

if typing.TYPE_CHECKING:
    from mysql import MySQLCharmBase


class MySQLBackups(Object):
    """Encapsulation of backups for MySQL."""

    def __init__(self, charm: "MySQLCharmBase", s3_integrator: S3Requirer) -> None:
        super().__init__(charm, MYSQL_BACKUPS)

        self.charm = charm
        self.s3_integrator = s3_integrator

        self.framework.observe(self.charm.on.create_backup_action, self._on_create_backup)
        self.framework.observe(self.charm.on.list_backups_action, self._on_list_backups)
        self.framework.observe(self.charm.on.restore_action, self._on_restore)
        self.framework.observe(
            self.s3_integrator.on.credentials_changed, self._on_s3_credentials_changed
        )
        self.framework.observe(self.charm.on.leader_elected, self._on_s3_credentials_changed)
        self.framework.observe(
            self.s3_integrator.on.credentials_gone, self._on_s3_credentials_gone
        )

    # ------------------ Helpers ------------------
    @property
    def _s3_integrator_relation_exists(self) -> bool:
        """Returns whether a relation with the s3-integrator exists."""
        return bool(self.model.get_relation(S3_INTEGRATOR_RELATION_NAME))

    def _retrieve_s3_parameters(self) -> Tuple[Dict[str, str], List[str]]:
        """Retrieve S3 parameters from the S3 integrator relation.

        Returns: tuple of (s3_parameters, missing_required_parameters)
        """
        s3_parameters = self.s3_integrator.get_s3_connection_info()

        required_parameters = [
            "bucket",
            "access-key",
            "secret-key",
        ]
        missing_required_parameters = [
            param for param in required_parameters if not s3_parameters.get(param)
        ]
        if missing_required_parameters:
            logger.warning(
                f"Missing required S3 parameters in relation with S3 integrator: {missing_required_parameters}"
            )
            return {}, missing_required_parameters

        # Add some sensible defaults (as expected by the code) for missing optional parameters
        s3_parameters.setdefault("endpoint", "https://s3.amazonaws.com")
        s3_parameters.setdefault("region", "")
        s3_parameters.setdefault("path", "")
        s3_parameters.setdefault("s3-uri-style", "auto")
        s3_parameters.setdefault("s3-api-version", "auto")

        # Strip whitespaces from all parameters
        for key, value in s3_parameters.items():
            if isinstance(value, str):
                s3_parameters[key] = value.strip()

        # Clean up extra slash symbols to avoid issues on 3rd-party storages
        # like Ceph Object Gateway (radosgw)
        s3_parameters["endpoint"] = s3_parameters["endpoint"].rstrip("/")
        s3_parameters["path"] = s3_parameters["path"].strip("/")
        s3_parameters["bucket"] = s3_parameters["bucket"].strip("/")

        return s3_parameters, []

    @staticmethod
    def _upload_logs_to_s3(
        stdout: str,
        stderr: str,
        log_filename: str,
        s3_parameters: Dict[str, str],
    ) -> bool:
        """Upload logs to S3 at the specified location.

        Args:
            stdout: The stdout logs
            stderr: The stderr logs
            log_filename: The name of the object to upload in S3
            s3_parameters: A dictionary of S3 parameters to use to upload to S3

        Returns: bool indicating success
        """
        logs = f"Stdout:\n{stdout}\n\nStderr:\n{stderr}"
        logger.debug(f"Logs to upload to S3 at location {log_filename}:\n{logs}")

        logger.info(
            f"Uploading logs to S3 at bucket={s3_parameters['bucket']}, location={log_filename}"
        )
        return upload_content_to_s3(logs, log_filename, s3_parameters)

    # ------------------ List Backups ------------------

    @staticmethod
    def _format_backups_list(backup_list: List[Tuple[str, str]]) -> str:
        """Formats the provided list of backups as a table."""
        backups = [f"{'backup-id':<21} | {'backup-type':<12} | backup-status"]

        backups.append("-" * len(backups[0]))
        for backup_id, backup_status in backup_list:
            backups.append(f"{backup_id:<21} | {'physical':<12} | {backup_status}")

        return "\n".join(backups)

    def _on_list_backups(self, event: ActionEvent) -> None:
        """Handle the list backups action.

        List backups available to restore by this application.
        """
        if not self._s3_integrator_relation_exists:
            event.fail("Missing relation with S3 integrator charm")
            return

        try:
            logger.info("Retrieving s3 parameters from the s3-integrator relation")
            s3_parameters, missing_parameters = self._retrieve_s3_parameters()
            if missing_parameters:
                event.fail(f"Missing S3 parameters: {missing_parameters}")
                return

            logger.info("Listing backups in the specified s3 path")
            backups = sorted(list_backups_in_s3_path(s3_parameters), key=lambda pair: pair[0])
            event.set_results({"backups": self._format_backups_list(backups)})
        except Exception as e:
            error_message = (
                getattr(e, "message")
                if hasattr(e, "message")
                else "Failed to retrieve backup ids from S3"
            )
            logger.error(error_message)
            event.fail(error_message)

    # ------------------ Create Backup ------------------

    def _pre_create_backup_checks(self, event: ActionEvent) -> bool:
        """Run some checks before creating the backup.

        Returns: a boolean indicating whether operation should be run.
        """
        if not self._s3_integrator_relation_exists:
            logger.error("Backup failed: missing relation with S3 integrator charm")
            event.fail("Missing relation with S3 integrator charm")
            return False

        if "s3-block-message" in self.charm.app_peer_data:
            logger.error("Backup failed: S3 relation is blocked for write")
            event.fail("S3 relation is blocked for write")
            return False

        if not self.charm._mysql.is_mysqld_running():
            logger.error(f"Backup failed: process mysqld is not running on {self.charm.unit.name}")
            event.fail("Process mysqld not running")
            return False

        return True

    def _on_create_backup(self, event: ActionEvent) -> None:
        """Handle the create backup action."""
        logger.info("A backup has been requested on unit")

        if not self._pre_create_backup_checks(event):
            return

        datetime_backup_requested = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Retrieve and validate missing S3 parameters
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            logger.error(f"Backup failed: missing S3 parameters {missing_parameters}")
            event.fail(f"Missing S3 parameters: {missing_parameters}")
            return

        backup_path = str(pathlib.Path(s3_parameters["path"]) / datetime_backup_requested)

        # Check if this unit can perform backup
        can_unit_perform_backup, validation_message = self._can_unit_perform_backup()
        if not can_unit_perform_backup:
            logger.error(f"Backup failed: {validation_message}")
            event.fail(validation_message or "")
            return

        # Test uploading metadata to S3 to test credentials before backup
        juju_version = JujuVersion.from_environ()
        metadata = (
            f"Date Backup Requested: {datetime_backup_requested}\n"
            f"Model Name: {self.model.name}\n"
            f"Application Name: {self.model.app.name}\n"
            f"Unit Name: {self.charm.unit.name}\n"
            f"Juju Version: {str(juju_version)}\n"
        )

        if not upload_content_to_s3(metadata, f"{backup_path}.metadata", s3_parameters):
            logger.error("Backup failed: Failed to upload metadata to provided S3")
            event.fail("Failed to upload metadata to provided S3")
            return

        # Run operations to prepare for the backup
        success, error_message = self._pre_backup()
        if not success:
            logger.error(f"Backup failed: {error_message}")
            event.fail(error_message or "")
            return

        # Perform the backup
        success, error_message = self._backup(backup_path, s3_parameters)
        if not success:
            logger.error(f"Backup failed: {error_message}")
            event.fail(error_message or "")

            success, error_message = self._post_backup()
            if not success:
                logger.error(f"Backup failed: {error_message}")
                self.charm.unit.status = BlockedStatus(
                    "Failed to create backup; instance in bad state"
                )

            return

        # Run operations to clean up after the backup
        success, error_message = self._post_backup()
        if not success:
            logger.error(f"Backup failed: {error_message}")
            self.charm.unit.status = BlockedStatus(
                "Failed to create backup; instance in bad state"
            )
            event.fail(error_message or "")
            return

        logger.info(f"Backup succeeded: with backup-id {datetime_backup_requested}")
        event.set_results({
            "backup-id": datetime_backup_requested,
        })
        self.charm._on_update_status(None)

    def _can_unit_perform_backup(self) -> Tuple[bool, Optional[str]]:
        """Validates whether this unit can perform a backup.

        Returns: tuple of (success, error_message)
        """
        logger.info("Checking if the unit is waiting to start or restart")
        if self.charm.is_unit_busy():
            return False, "Unit is waiting to start or restart"

        logger.info("Checking if backup already in progress")
        try:
            if self.charm._mysql.offline_mode_and_hidden_instance_exists():
                return False, "Backup already in progress on another unit"
        except MySQLOfflineModeAndHiddenInstanceExistsError:
            return False, "Failed to check if a backup is already in progress"

        logger.info("Checking state and role of unit")

        try:
            state, role = self.charm._mysql.get_member_state()
        except (MySQLNoMemberStateError, MySQLUnableToGetMemberStateError):
            return False, "Error obtaining member state"

        if role == "primary" and self.charm.app.planned_units() > 1:
            return False, "Unit cannot perform backups as it is the cluster primary"

        if state in ["recovering", "offline", "error"]:
            return False, f"Unit cannot perform backups as its state is {state}"

        return True, None

    def _pre_backup(self) -> Tuple[bool, Optional[str]]:
        """Runs operations required before performing a backup.

        Returns: tuple of (success, error_message)
        """
        # Do not set instance offline_mode and do not hide instance from mysqlrouter
        # if there is only one instance in the cluster
        if self.charm.app.planned_units() == 1:
            return True, None

        try:
            logger.info("Setting unit option tag:_hidden")
            self.charm._mysql.set_instance_option("tag:_hidden", "true")
        except MySQLSetInstanceOptionError:
            return False, "Error setting instance option tag:_hidden"

        try:
            logger.info("Setting unit as offline before performing backup")
            self.charm._mysql.set_instance_offline_mode(True)
        except MySQLSetInstanceOfflineModeError:
            self.charm._mysql.set_instance_option("tag:_hidden", "false")
            return False, "Error setting instance as offline before performing backup"

        return True, None

    def _backup(self, backup_path: str, s3_parameters: Dict) -> Tuple[bool, Optional[str]]:
        """Runs the backup operations.

        Args:
            backup_path: The location to upload the backup to
            s3_parameters: Dictionary containing S3 parameters to upload the backup with

        Returns: tuple of (success, error_message)
        """
        try:
            self.charm.unit.status = MaintenanceStatus("Running backup...")
            logger.info("Running the xtrabackup commands")
            stdout, _ = self.charm._mysql.execute_backup_commands(
                backup_path,
                s3_parameters,
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
            "",
            f"{backup_path}.backup.log",
            s3_parameters,
        ):
            return False, "Error uploading logs to S3"

        return True, None

    def _post_backup(self) -> Tuple[bool, Optional[str]]:
        """Runs operations required after performing a backup.

        Returns: tuple of (success, error_message)
        """
        try:
            logger.info("Deleting temp backup directory")
            self.charm._mysql.delete_temp_backup_directory()
        except MySQLDeleteTempBackupDirectoryError:
            return False, "Error deleting temp backup directory"

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

    def _pre_restore_checks(self, event: ActionEvent) -> bool:
        """Run some checks before starting the restore.

        Returns: a boolean indicating whether restore should be run
        """
        if not self._s3_integrator_relation_exists:
            error_message = "Missing relation with S3 integrator charm"
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return False

        if not event.params.get("backup-id"):
            error_message = "Missing backup-id to restore"
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return False

        # Quick check for timestamp format
        restore_to_time = event.params.get("restore-to-time")
        if (
            restore_to_time
            and restore_to_time != "latest"
            and not self._is_mysql_timestamp(restore_to_time)
        ):
            error_message = "Bad restore-to-time format"
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return False

        if not self.charm._mysql.is_server_connectable():
            error_message = "Server running mysqld is not connectable"
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return False

        logger.info("Checking if the unit is waiting to start or restart")
        if self.charm.is_unit_busy():
            error_message = "Unit is waiting to start or restart"
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return False

        logger.info("Checking that the cluster does not have more than one unit")
        if self.charm.app.planned_units() > 1:
            error_message = (
                "Unit cannot restore backup as there are more than one units in the cluster"
            )
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return False

        return True

    def _on_restore(self, event: ActionEvent) -> None:  # noqa: C901
        """Handle the restore backup action event.

        Restore a backup from S3 (parameters for which can retrieved from the
        relation with S3 integrator).
        """
        if not self._pre_restore_checks(event):
            return

        backup_id = event.params["backup-id"].strip().strip("/")
        restore_to_time = event.params.get("restore-to-time")
        logger.info(
            f"A restore with backup-id {backup_id}"
            f"{f' to time point {restore_to_time}' if restore_to_time else ''}"
            f" has been requested on the unit"
        )

        # Retrieve and validate missing S3 parameters
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            logger.error(f"Restore failed: missing S3 parameters {missing_parameters}")
            event.fail(f"Missing S3 parameters: {missing_parameters}")
            return

        # Validate the provided backup id
        logger.info("Validating provided backup-id in the specified s3 path")
        s3_backup_md5 = str(pathlib.Path(s3_parameters["path"]) / f"{backup_id}.md5")
        if not fetch_and_check_existence_of_s3_path(s3_backup_md5, s3_parameters):
            logger.error(f"Restore failed: invalid backup-id {backup_id}")
            event.fail(f"Invalid backup-id: {backup_id}")
            return

        # Run operations to prepare for the restore
        self.charm.unit.status = MaintenanceStatus("Running pre-restore operations")
        success, error_message = self._pre_restore()
        if not success:
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            return

        # Perform the restore
        success, recoverable, error_message = self._restore(backup_id, s3_parameters)
        if not success:
            logger.error(f"Restore failed: {error_message}")
            event.fail(error_message)
            if recoverable:
                self._clean_data_dir_and_start_mysqld()
            else:
                self.charm.unit.status = BlockedStatus(error_message)
            return

        if restore_to_time is not None:
            self.charm.unit.status = MaintenanceStatus("Running point-in-time-recovery operations")
            success, error_message = self._pitr_restore(restore_to_time, s3_parameters)
            if not success:
                logger.error(f"Restore failed: {error_message}")
                event.fail(error_message)
                self.charm.unit.status = BlockedStatus(error_message)
                return

        self.charm.app_peer_data.update({
            "s3-block-message": MOVE_RESTORED_CLUSTER_TO_ANOTHER_S3_REPOSITORY_ERROR,
            "binlogs-collecting": "",
        })
        if not self.charm._mysql.reconcile_binlogs_collection():
            logger.error("Failed to stop binlogs collecting prior to restore")

        # Run post-restore operations
        self.charm.unit.status = MaintenanceStatus("Running post-restore operations")
        success, error_message = self._post_restore()
        if not success:
            logger.error(f"Restore failed: {error_message}")
            self.charm.unit.status = BlockedStatus(error_message)
            event.fail(error_message)
            return

        logger.info("Restore succeeded")
        event.set_results({
            "completed": "ok",
        })
        # update status as soon as possible
        self.charm._on_update_status(None)

    def _pre_restore(self) -> Tuple[bool, str]:
        """Perform operations that need to be done before performing a restore.

        Returns: tuple of (success, error_message)
        """
        if not self.charm._mysql.is_mysqld_running():
            return True, ""

        try:
            logger.info("Stopping mysqld before restoring the backup")
            self.charm._mysql.kill_client_sessions()
            self.charm._mysql.set_instance_offline_mode(True)
            self.charm._mysql.stop_mysqld()
        except MySQLKillSessionError:
            return False, "Failed to kill client sessions"
        except MySQLSetInstanceOfflineModeError:
            return False, "Failed to set instance as offline before restoring the backup"
        except MySQLStopMySQLDError:
            return False, "Failed to stop mysqld"

        return True, ""

    def _restore(self, backup_id: str, s3_parameters: Dict[str, str]) -> Tuple[bool, bool, str]:
        """Run the restore operations.

        Args:
            backup_id: ID of backup to restore
            s3_parameters: Dictionary of S3 parameters to use to restore the backup

        Returns: tuple of (success, recoverable_error, error_message)
        """
        try:
            logger.info(
                "Running xbcloud get commands to retrieve the backup\n"
                "This operation can take long time depending on backup size and network speed"
            )
            self.charm.unit.status = MaintenanceStatus("Downloading backup...")
            stdout, stderr, backup_location = self.charm._mysql.retrieve_backup_with_xbcloud(
                backup_id,
                s3_parameters,
            )
        except MySQLRetrieveBackupWithXBCloudError:
            return False, True, f"Failed to retrieve backup {backup_id}"

        try:
            logger.info("Preparing retrieved backup using xtrabackup prepare")
            self.charm.unit.status = MaintenanceStatus("Preparing for restore backup...")
            stdout, stderr = self.charm._mysql.prepare_backup_for_restore(backup_location)
            logger.debug(f"Stdout of xtrabackup prepare command: {stdout}")
            logger.debug(f"Stderr of xtrabackup prepare command: {stderr}")
        except MySQLPrepareBackupForRestoreError:
            return False, True, f"Failed to prepare backup {backup_id}"

        try:
            logger.info("Removing the contents of the data directory")
            self.charm._mysql.empty_data_files()
        except MySQLEmptyDataDirectoryError:
            return False, False, "Failed to empty the data directory"

        try:
            self.charm.unit.status = MaintenanceStatus("Restoring backup...")
            logger.info("Restoring the backup")
            stdout, stderr = self.charm._mysql.restore_backup(backup_location)
            logger.debug(f"Stdout of xtrabackup move-back command: {stdout}")
            logger.debug(f"Stderr of xtrabackup move-back command: {stderr}")
        except MySQLRestoreBackupError:
            return False, False, f"Failed to restore backup {backup_id}"

        success, error_message = self._clean_data_dir_and_start_mysqld()
        if not success:
            return False, False, error_message

        return True, True, ""

    def _clean_data_dir_and_start_mysqld(self) -> Tuple[bool, str]:
        """Run idempotent operations run after restoring a backup.

        Returns tuple of (success, error_message)
        """
        try:
            self.charm._mysql.delete_temp_restore_directory()
            self.charm._mysql.delete_temp_backup_directory()
            # Old backups may contain the temp backup directory (as previously, the temp
            # backup directory was created in the mysql data directory to reduce IOPS latency)
            self.charm._mysql.delete_temp_backup_directory(from_directory=MYSQL_DATA_DIR)
        except MySQLDeleteTempRestoreDirectoryError:
            return False, "Failed to delete the temp restore directory"
        except MySQLDeleteTempBackupDirectoryError:
            return False, "Failed to delete the temp backup directory"

        try:
            self.charm._mysql.start_mysqld()
        except MySQLStartMySQLDError:
            return False, "Failed to start mysqld"

        return True, ""

    def _pitr_restore(
        self, restore_to_time: str, s3_parameters: Dict[str, str]
    ) -> Tuple[bool, str]:
        try:
            logger.info("Restoring point-in-time-recovery")
            stdout, stderr = self.charm._mysql.restore_pitr(
                host=self.charm.get_unit_address(self.charm.unit, PEER),
                mysql_user=self.charm._mysql.server_config_user,
                password=self.charm._mysql.server_config_password,
                s3_parameters=s3_parameters,
                restore_to_time=restore_to_time,
            )
            logger.debug(f"Stdout of mysql-pitr-helper restore command: {stdout}")
            logger.debug(f"Stderr of mysql-pitr-helper restore command: {stderr}")
        except MySQLRestorePitrError:
            return False, f"Failed to restore point-in-time-recovery to the {restore_to_time}"
        return True, ""

    def _post_restore(self) -> Tuple[bool, str]:
        """Run operations required after restoring a backup.

        Returns: tuple of (success, error_message)
        """
        try:
            logger.info("Configuring instance to be part of an InnoDB cluster")
            self.charm._mysql.configure_instance(create_cluster_admin=False)
            self.charm._mysql.wait_until_mysql_connection()
        except (
            MySQLConfigureInstanceError,
            MySQLServiceNotRunningError,
        ):
            return False, "Failed to configure restored instance for InnoDB cluster"

        try:
            logger.info("Creating cluster on restored node")
            self.charm._mysql.create_cluster(self.charm.unit_label)
            self.charm._mysql.create_cluster_set()
            self.charm._mysql.initialize_juju_units_operations_table()

            self.charm._mysql.rescan_cluster()

        except MySQLCreateClusterError:
            return False, "Failed to create InnoDB cluster on restored instance"
        except MySQLCreateClusterSetError:
            return False, "Failed to create InnoDB cluster-set on restored instance"
        except MySQLInitializeJujuOperationsTableError:
            return False, "Failed to initialize the juju operations table"
        except MySQLRescanClusterError:
            return False, "Failed to rescan the cluster"

        return True, ""

    def _on_s3_credentials_changed(self, event: CredentialsChangedEvent) -> None:
        if not self.charm.unit.is_leader():
            logger.debug("Early exit on _on_s3_credentials_changed: unit is not a leader")
            return

        if not self._s3_integrator_relation_exists:
            logger.debug(
                "Early exit on _on_s3_credentials_changed: s3 integrator relation does not exist"
            )
            return

        if (
            not self.charm._mysql.is_mysqld_running()
            or not self.charm.unit_initialized
            or not self.charm.upgrade.idle
        ):
            logger.debug(
                "Deferring _on_s3_credentials_changed: mysql cluster is not started yet or upgrade is occurring"
            )
            event.defer()
            return

        try:
            self.charm._mysql.wait_until_mysql_connection()
        except MySQLServiceNotRunningError:
            logger.debug(
                "Deferring _on_s3_credentials_changed: mysql cluster is not connectable yet"
            )
            event.defer()
            return

        logger.info("Retrieving s3 parameters from the s3-integrator relation")
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            logger.error(f"Missing S3 parameters: {missing_parameters}")
            return

        logger.info("Ensuring compatibility with the provided S3 repository")
        if ensure_s3_compatible_group_replication_id(
            self.charm._mysql.get_current_group_replication_id(), s3_parameters
        ):
            self.charm.app_peer_data.update({
                "s3-block-message": "",
                "binlogs-collecting": "true",
            })
        else:
            self.charm.app_peer_data.update({
                "s3-block-message": ANOTHER_S3_CLUSTER_REPOSITORY_ERROR_MESSAGE,
                "binlogs-collecting": "",
            })

        if not self.charm._mysql.reconcile_binlogs_collection(
            force_restart=True, ignore_inactive_error=True
        ):
            logger.error("Failed to restart binlogs collecting after S3 relation update")

    def _on_s3_credentials_gone(self, event: CredentialsGoneEvent) -> None:
        if not self.charm.unit.is_leader():
            logger.debug("Early exit on _on_s3_credentials_gone: unit is not a leader")
            return

        self.charm.app_peer_data.update({
            "s3-block-message": "",
            "binlogs-collecting": "",
        })
        try:
            if not self.charm._mysql.reconcile_binlogs_collection():
                logger.error("Failed to stop binlogs collecting after S3 relation depart")
        except Exception as e:
            logger.error(e)
            logger.error(
                "Exception is occurred when trying to stop binlogs collecting after S3 relation depart. It may be a leader departure"
            )

    def get_binlogs_collector_config(self) -> Dict[str, str]:
        """Return binlogs collector service config file.

        Returns: dict of binlogs collector service config
        """
        if not self._s3_integrator_relation_exists:
            logger.error(
                "Cannot get binlogs collector config: s3 integrator relation does not exist"
            )
            return {}

        logger.info("Retrieving s3 parameters from the s3-integrator relation")
        s3_parameters, missing_parameters = self._retrieve_s3_parameters()
        if missing_parameters:
            logger.error(
                f"Cannot get binlogs collector config: Missing S3 parameters: {missing_parameters}"
            )
            return {}

        binlogs_path = s3_parameters["path"].rstrip("/")
        bucket_url = f"{s3_parameters['bucket']}/{binlogs_path}/binlogs"

        return {
            "ENDPOINT": _construct_endpoint(s3_parameters),
            "HOSTS": ",".join(self.charm._mysql.get_cluster_members()),
            "USER": SERVER_CONFIG_USERNAME,
            "PASS": self.charm.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),
            "STORAGE_TYPE": "s3",
            "ACCESS_KEY_ID": s3_parameters["access-key"],
            "SECRET_ACCESS_KEY": s3_parameters["secret-key"],
            "S3_BUCKET_URL": bucket_url,
            "DEFAULT_REGION": s3_parameters["region"],
        }

    def _is_mysql_timestamp(self, timestamp: str) -> bool:
        """Validate the provided timestamp string."""
        if not re.match(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
            timestamp,
        ):
            # regex validation necessary to enforce format is valid both here
            # and for the go `mysql-pitr-helper` binary
            # https://github.com/canonical/mysql-pitr-helper/blob/ed858df5c145b003c9d24223d44b6ea9c7d67888/recoverer/recoverer.go#L194
            return False
        try:
            self._parse_mysql_timestamp(timestamp)
            return True
        except ValueError:
            return False

    def _parse_mysql_timestamp(self, timestamp: str) -> datetime.datetime:
        return datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
