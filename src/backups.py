# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of backups."""

import datetime
import json
import logging
from typing import Dict, Tuple

from charms.mysql.v0.mysql import (
    MySQLGetMemberStateError,
    MySQLSetInstanceOfflineModeError,
    MySQLSetInstanceOptionError,
)
from ops.charm import ActionEvent, CharmBase
from ops.framework import Object
from ops.jujuversion import JujuVersion

from constants import (
    DATABASE_BACKUPS_PEER,
    S3_ACCESS_KEY,
    S3_BUCKET_KEY,
    S3_ENDPOINT_KEY,
    S3_PATH_KEY,
    S3_REGION_KEY,
    S3_SECRET_KEY,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)
from mysql_k8s_helpers import MySQLExecuteBackupScriptError
from s3_helpers import upload_content_to_s3

logger = logging.getLogger(__name__)

MYSQL_BACKUPS = "mysql-backups"
BACKUPS_KEY = "backups"
UNIT_BACKUPS_KEY = "unit-backups"


class MySQLBackups(Object):
    """Encapsulation of backups for MySQL."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, MYSQL_BACKUPS)

        self.charm = charm

        self.framework.observe(self.charm.on.perform_backup_action, self._on_perform_backup)
        self.framework.observe(self.charm.on.list_backups_action, self._on_list_backups)

        self.framework.observe(
            self.charm.on[DATABASE_BACKUPS_PEER].relation_changed,
            self._on_backup_peer_relation_changed,
        )

    def _on_backup_peer_relation_changed(self, _) -> None:
        """Handle the backup peer relation changed event.

        Collect backup ids from unit peer databags.
        """
        if not self.charm.unit.is_leader():
            return

        backup_ids = set(json.loads(self.charm.app_backup_peer_data.get(BACKUPS_KEY, "[]")))
        length_backup_ids = len(backup_ids)

        for unit in self.charm.backup_peers.units:
            unit_backups = set(
                json.loads(self.charm.backup_peers.data[unit].get(UNIT_BACKUPS_KEY, "[]"))
            )
            backup_ids.update(unit_backups)

        unit_backups = set(
            json.loads(self.charm.unit_backup_peer_data.get(UNIT_BACKUPS_KEY, "[]"))
        )
        backup_ids.update(unit_backups)

        new_length_backup_ids = len(backup_ids)
        if length_backup_ids != new_length_backup_ids:
            logger.info(f"Updating list of backup ids: {backup_ids}")
            self.charm.app_backup_peer_data[BACKUPS_KEY] = json.dumps(list(backup_ids))

    def _on_list_backups(self, event: ActionEvent) -> None:
        """List backups performed by this application."""
        backup_ids = json.loads(self.charm.app_backup_peer_data.get(BACKUPS_KEY, "[]"))
        logger.info(f"Returning backup ids performed by this application: {backup_ids}")
        event.set_results({"backup-ids": backup_ids})

    def _on_perform_backup(self, event: ActionEvent) -> None:
        """Perform backup action."""
        logger.info("A backup has been requested on unit")

        datetime_backup_requested = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

        # Retrieve and validate missing S3 parameters
        s3_parameters = self._retrieve_s3_parameters()
        missing_parameters = [key for key, param in s3_parameters.items() if not param]
        if missing_parameters:
            logger.warning(
                f"Missing S3 parameters while trying to perform a backup: {missing_parameters}"
            )
            event.set_results(
                {
                    "success": False,
                    "message": f"Missing S3 parameters: {missing_parameters}",
                }
            )
            return

        s3_directory = f"{s3_parameters['path']}/{datetime_backup_requested}"

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
            s3_parameters["access_key"],
            s3_parameters["secret_key"],
        )
        if not success:
            event.set_results(
                {
                    "success": False,
                    "message": "Failed to upload metadata provided S3",
                }
            )
            return

        # Check if this unit can perform backup
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

        # Run operations to prepare for the backup
        success, error_message = self._pre_backup()
        if not success:
            logger.warning(error_message)
            event.set_results(
                {
                    "success": False,
                    "message": error_message,
                }
            )

        # Perform the backup
        success, error_message = self._backup(
            s3_parameters["bucket"],
            s3_directory,
            s3_parameters["endpoint"],
            s3_parameters["region"],
            s3_parameters["access_key"],
            s3_parameters["secret_key"],
        )
        if not success:
            logger.warning(error_message)
            event.set_results({"success": False, "message": error_message})

            success, error_message = self._post_backup()
            if not success:
                logger.warning(error_message)

            return

        # Run operations to clean up after the backup
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

        unit_backups = set(
            json.loads(self.charm.unit_backup_peer_data.get(UNIT_BACKUPS_KEY, "[]"))
        )
        unit_backups.add(datetime_backup_requested)
        self.charm.unit_backup_peer_data[UNIT_BACKUPS_KEY] = json.dumps(list(unit_backups))

        event.set_results(
            {
                "success": True,
                "backup-id": datetime_backup_requested,
            }
        )

    def _retrieve_s3_parameters(self) -> Dict:
        """Retrieve S3 parameters from the backups peer relation databag."""
        logger.info(
            "Retrieving S3 parameters from backups peer relation"
            "(populated from relation with S3 integrator)"
        )
        return {
            "bucket": self.charm.app_backup_peer_data.get(S3_BUCKET_KEY),
            "endpoint": self.charm.app_backup_peer_data.get(S3_ENDPOINT_KEY),
            "region": self.charm.app_backup_peer_data.get(S3_REGION_KEY),
            "path": self.charm.app_backup_peer_data.get(S3_PATH_KEY),
            "access_key": self.charm.get_secret(
                "app",
                S3_ACCESS_KEY,
                DATABASE_BACKUPS_PEER,
            ),
            "secret_key": self.charm.get_secret(
                "app",
                S3_SECRET_KEY,
                DATABASE_BACKUPS_PEER,
            ),
        }

    def _can_unit_perform_backup(self) -> Tuple[bool, str]:
        """Validates whether this unit can perform a backup."""
        logger.info("Checking state and role of unit")

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
        logger.info("Setting cluster state as 'backing-up'")
        self.charm.unit_peer_data["cluster-state"] = "backing-up"

        try:
            logger.info("Setting unit option tag:_hidden")
            self.charm._mysql.set_instance_option("tag:_hidden", "true")

            logger.info("Setting unit as offline before performing backup")
            self.charm._mysql.set_instance_offline_mode(True)
        except MySQLSetInstanceOfflineModeError:
            self.charm.unit_peer_data["cluster-state"] = "active"

            return False, "Error setting instance as offline before performing backup"
        except MySQLSetInstanceOptionError:
            self.charm.unit_peer_data["cluster-state"] = "active"

            return False, "Error setting instance option tag:_hidden"

        return True, None

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
            stdout, stderr = self.charm._mysql.execute_backup_script(
                s3_bucket,
                f"{s3_directory}/backup",
                s3_access_key,
                s3_secret_key,
                SERVER_CONFIG_USERNAME,
                self.charm.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),
            )
            logs = f"""Stdout:
{stdout}

Stderr:
{stderr}
            """
            logger.debug(f"Output of xtrabackup: {logs}")

            logger.info("Uploading output of xtrabackup to S3")
            success = upload_content_to_s3(
                logs,
                s3_bucket,
                f"{s3_directory}/xtrabackup.log",
                s3_region,
                s3_endpoint,
                s3_access_key,
                s3_secret_key,
            )
            if not success:
                return False, "Error uploading logs to S3"
        except MySQLExecuteBackupScriptError:
            return False, "Error backing up the database"

        return True, None

    def _post_backup(self) -> Tuple[bool, str]:
        """Runs operations required after performing a backup."""
        logger.info("Setting cluster state as 'active'")
        self.charm.unit_peer_data["cluster-state"] = "active"

        try:
            logger.info("Unsetting unit as offline after performing backup")
            self.charm._mysql.set_instance_offline_mode(False)

            logger.info("Setting unit option tag:_hidden as false")
            self.charm._mysql.set_instance_option("tag:_hidden", "false")
        except MySQLSetInstanceOfflineModeError:
            return False, "Error unsetting instance as offline before performing backup"
        except MySQLSetInstanceOptionError:
            return False, "Error setting instance option tag:_hidden"

        return True, None
