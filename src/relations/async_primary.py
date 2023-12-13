# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL async replication primary side module."""

import enum
import json
import logging
import typing

from ops import MaintenanceStatus, RelationDataContent
from ops.framework import Object
from ops.model import Relation
from typing_extensions import Optional

from constants import (
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)

PRIMARY_RELATION = "async-primary"


class States(str, enum.Enum):
    """States for the relation."""

    SYNCING = "syncing"  # credentials are being synced to the replica
    INITIALIZING = "initializing"  # cluster need to be added
    RECOVERING = "recovery"  # replica cluster is being recovered
    READY = "ready"  # replica cluster is ready


class MySQLAsyncReplicationPrimary(Object):
    """MySQL async replication primary side."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, "mysql-async-primary")
        self._charm = charm

        if self._charm.unit.is_leader():
            self.framework.observe(
                self._charm.on[PRIMARY_RELATION].relation_created, self.on_primary_created
            )
            self.framework.observe(
                self._charm.on[PRIMARY_RELATION].relation_changed, self.on_primary_relation_changed
            )

    def get_relation(self, relation_id: int) -> Optional[Relation]:
        """Return the relation."""
        return self.model.get_relation(PRIMARY_RELATION, relation_id)

    def get_local_relation_data(self, relation: Relation) -> Optional[RelationDataContent]:
        """Local data."""
        return relation.data[self.model.app]

    def get_remote_relation_data(self, relation: Relation) -> Optional[RelationDataContent]:
        """Remote data."""
        if not relation.app:
            return
        return relation.data[relation.app]

    def get_state(self, relation: Relation) -> Optional[States]:
        """State of the relation, on primary side."""
        if not relation:
            return None

        local_data = self.get_local_relation_data(relation)
        remote_data = self.get_remote_relation_data(relation)

        if local_data.get("credentials") and not remote_data.get("endpoint"):
            return States.SYNCING

        if local_data.get("credentials") and remote_data.get("endpoint"):
            # evaluate cluster status
            replica_status = self._charm._mysql.get_replica_cluster_status(
                remote_data["cluster-name"]
            )
            if replica_status == "ok":
                return States.READY
            elif replica_status == "unknown":
                return States.INITIALIZING
            else:
                return States.RECOVERING

    @property
    def idle(self) -> bool:
        """Whether the async replication is idle for all related clusters."""
        for relation in self.model.relations[PRIMARY_RELATION]:
            if self.get_state(relation) not in [States.READY, None]:
                return False
        return True

    def on_primary_created(self, event):
        """Handle the async_primary relation being created."""
        self._charm.app.status = MaintenanceStatus("Setting up async replication")

        local_relation_data = self.get_local_relation_data(event.relation)

        logger.debug("Syncing credentials to replica cluster")

        local_relation_data["credentials"] = json.dumps(
            {
                SERVER_CONFIG_USERNAME: self._charm.get_secret("app", SERVER_CONFIG_PASSWORD_KEY),
                CLUSTER_ADMIN_USERNAME: self._charm.get_secret("app", CLUSTER_ADMIN_PASSWORD_KEY),
            }
        )

    def on_primary_relation_changed(self, event):
        """Handle the async_primary relation being changed."""
        state = self.get_state(event.relation)

        if state == States.INITIALIZING:
            # Add replica cluster primary node
            # TODO: select a secondary as a donor
            logger.debug("Initializing replica cluster")
            self._charm.unit.status = MaintenanceStatus("Adding replica cluster")
            cluster_name = self.get_remote_relation_data(event.relation)["cluster-name"]
            endpoint = self.get_remote_relation_data(event.relation)["endpoint"]

            logger.debug(f"Adding replica cluster {cluster_name} with endpoint {endpoint}")
            self._charm._mysql.create_replica_cluster(endpoint, cluster_name)

            local_relation_data = self.get_local_relation_data(event.relation)
            local_relation_data["replica-state"] = "initialized"

        elif state == States.RECOVERING:
            # Recover replica cluster
            self._charm.unit.status = MaintenanceStatus("Replica cluster in recovery")
