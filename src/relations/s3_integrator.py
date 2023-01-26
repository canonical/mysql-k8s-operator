# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of a relation with S3 integrator."""

import logging

from charms.data_platform_libs.v0.s3 import CredentialsChangedEvent, S3Requirer
from ops.framework import Object

from constants import (
    DATABASE_BACKUPS_PEER,
    S3_ACCESS_KEY,
    S3_BUCKET_KEY,
    S3_ENDPOINT_KEY,
    S3_INTEGRATOR_RELATION_NAME,
    S3_PATH_KEY,
    S3_REGION_KEY,
    S3_SECRET_KEY,
)

logger = logging.getLogger(__name__)


class MySQLS3Integration(Object):
    """Represents the integration with the S3 Integrator charm."""

    def __init__(self, charm) -> None:
        super().__init__(charm, S3_INTEGRATOR_RELATION_NAME)

        self.charm = charm

        self.s3_integrator = S3Requirer(self.charm, S3_INTEGRATOR_RELATION_NAME)

        self.framework.observe(
            self.s3_integrator.on.credentials_changed, self._on_credentials_changed
        )
        self.framework.observe(self.s3_integrator.on.credentials_gone, self._on_credentials_gone)

    def _on_credentials_changed(self, event: CredentialsChangedEvent) -> None:
        """Handle the credentials changed event.

        Retrieve the S3 credentials passed in by the S3 integrator.
        """
        if not self.charm.unit.is_leader():
            return

        s3_bucket = event.bucket
        s3_endpoint = event.endpoint
        s3_region = event.region
        s3_access_key = event.access_key
        s3_secret_key = event.secret_key
        s3_path = event.path

        self.charm.app_backup_peer_data[S3_BUCKET_KEY] = s3_bucket
        self.charm.app_backup_peer_data[S3_ENDPOINT_KEY] = s3_endpoint
        self.charm.app_backup_peer_data[S3_REGION_KEY] = s3_region
        self.charm.app_backup_peer_data[S3_PATH_KEY] = s3_path

        self.charm.set_secret(
            "app",
            S3_ACCESS_KEY,
            s3_access_key,
            DATABASE_BACKUPS_PEER,
        )
        self.charm.set_secret(
            "app",
            S3_SECRET_KEY,
            s3_secret_key,
            DATABASE_BACKUPS_PEER,
        )

    def _on_credentials_gone(self, _) -> None:
        """Handle the credentials gone event.

        Remove any credentials stored in the backup peer relation databag.
        """
        if not self.charm.unit.is_leader():
            return

        del self.charm.app_backup_peer_data[S3_BUCKET_KEY]
        del self.charm.app_backup_peer_data[S3_ENDPOINT_KEY]
        del self.charm.app_backup_peer_data[S3_REGION_KEY]
        del self.charm.app_backup_peer_data[S3_PATH_KEY]

        self.charm.set_secret(
            "app",
            S3_ACCESS_KEY,
            None,
            DATABASE_BACKUPS_PEER,
        )
        self.charm.set_secret(
            "app",
            S3_SECRET_KEY,
            None,
            DATABASE_BACKUPS_PEER,
        )
