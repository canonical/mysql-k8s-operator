# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL async replication replica side module."""

import enum
import json
import logging
import typing

from ops import ActiveStatus, MaintenanceStatus, Relation, RelationDataContent, WaitingStatus
from ops.framework import Object
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

REPLICA_RELATION = "async-replica"


class States(str, enum.Enum):
    """States of the relation."""

    SYNCING = "syncing"  # credentials are being synced from primary cluster
    INITIALIZING = "initializing"  # cluster set is being initialized
    RECOVERING = "recovery"  # cluster is recovering, need to join all units
    READY = "ready"  # cluster is ready


class MySQLAsyncReplicationReplica(Object):
    """MySQL async replication replica side."""

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, REPLICA_RELATION)
        self._charm = charm

        if self._charm.unit.is_leader():
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_created, self.on_replica_created
            )

            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_changed, self.on_replica_changed
            )

    @property
    def relation(self) -> Optional[Relation]:
        """Relation."""
        return self.model.get_relation(REPLICA_RELATION)

    @property
    def relation_data(self) -> RelationDataContent:
        """Relation data."""
        return self.relation.data[self.model.app]

    @property
    def remote_relation_data(self) -> Optional[RelationDataContent]:
        """Relation data."""
        if not self.relation.app:
            return
        return self.relation.data[self.relation.app]

    @property
    def state(self) -> Optional[States]:
        """State of the relation, on replica side."""
        if not self.relation:
            return None

        if self.remote_relation_data.get("credentials") and not self.relation_data.get("endpoint"):
            # received credentials from primary cluster
            return States.SYNCING

        if self.remote_relation_data.get("replica-state") == "initialized":
            # cluster added to cluster-set by primary cluster
            if self._charm._mysql.get_cluster_node_count() < self.model.app.planned_units():
                return States.RECOVERING
            return States.READY

    @property
    def idle(self) -> bool:
        """Whether the async replication is idle."""
        return self.state in [States.READY, None]

    def on_replica_created(self, _):
        """Handle the async_replica relation being created."""
        self._charm.app.status = MaintenanceStatus("Setting up async replication")

    def on_replica_changed(self, _):
        """Handle the async_replica relation being changed."""
        if self.state == States.SYNCING:
            logger.debug("Syncing credentials from primary cluster")
            self._charm.unit.status = MaintenanceStatus("Syncing credentials")

            credentials = json.loads(self.remote_relation_data["credentials"])
            valid_usernames = {
                SERVER_CONFIG_USERNAME: SERVER_CONFIG_PASSWORD_KEY,
                CLUSTER_ADMIN_USERNAME: CLUSTER_ADMIN_PASSWORD_KEY,
            }

            for user, password in credentials.items():
                self._charm._mysql.update_user_password(user, password)
                self._charm.set_secret("app", valid_usernames[user], password)

            self._charm.unit.status = MaintenanceStatus("Dissolving replica cluster")
            self._charm._mysql.dissolve_cluster()

            self._charm.unit.status = MaintenanceStatus("Populate endpoint")

            self.relation_data["cluster-name"] = self._charm.app_peer_data["cluster-name"]
            self.relation_data["endpoint"] = self._charm._get_unit_fqdn()

            self._charm.unit.status = WaitingStatus("Waiting for primary cluster")
        elif self.state == States.READY:
            logger.debug("Cluster is ready")
            self._charm.app.status = self._charm.unit.status = ActiveStatus()
