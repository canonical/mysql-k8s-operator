# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL async replication primary side module."""

import enum
import logging
import typing

from ops import BlockedStatus, MaintenanceStatus, RelationDataContent, Secret
from ops.framework import Object
from ops.model import Relation
from typing_extensions import Optional

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
                self._charm.on[PRIMARY_RELATION].relation_created, self._on_primary_created
            )
            self.framework.observe(
                self._charm.on[PRIMARY_RELATION].relation_changed,
                self._on_primary_relation_changed,
            )
            self.framework.observe(
                self._charm.on[PRIMARY_RELATION].relation_broken, self._on_primary_broken
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
        remote_data = self.get_remote_relation_data(relation) or {}

        if local_data.get("secret-id") and not remote_data.get("endpoint"):
            return States.SYNCING

        if local_data.get("secret-id") and remote_data.get("endpoint"):
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
        if not self.model.unit.is_leader():
            # non leader units are always idle
            return True

        for relation in self.model.relations[PRIMARY_RELATION]:
            if self.get_state(relation) not in [States.READY, None]:
                return False
        return True

    def _get_secret(self) -> Secret:
        """Return async replication necessary secrets."""
        secret = self.model.get_secret(label=f"{self.model.app.name}.app")
        return secret

    def _on_primary_created(self, event):
        """Validate relations and share credentials with replica cluster."""
        self._charm.app.status = MaintenanceStatus("Setting up async replication")

        if self._charm._mysql.is_cluster_replica():
            logger.error(
                f"This a replica cluster, cannot be related as {PRIMARY_RELATION}. Remove relation."
            )
            self._charm.unit.status = BlockedStatus(
                f"This is a replica cluster. Unrelate from the {PRIMARY_RELATION} relation"
            )
            return

        logger.debug("Granting secrets access to async replication relation")
        secret = self._get_secret()
        secret_id = secret.get_info().id
        secret.grant(event.relation)

        logger.debug(f"Sharing {secret_id} with replica cluster")
        event.relation.data[self.model.app]["secret-id"] = secret_id

    def _on_primary_relation_changed(self, event):
        """Handle the async_primary relation being changed."""
        state = self.get_state(event.relation)

        if state == States.INITIALIZING:
            # Add replica cluster primary node
            # TODO: select a secondary as a donor
            logger.debug("Initializing replica cluster")
            self._charm.unit.status = MaintenanceStatus("Adding replica cluster")
            remote_data = self.get_remote_relation_data(event.relation) or {}

            cluster = remote_data["cluster-name"]
            endpoint = remote_data["endpoint"]
            unit_label = remote_data["node-label"]

            logger.debug("Looking for a donor node")
            _, ro, _ = self._charm._mysql.get_cluster_endpoints(get_ips=False)

            if not ro:
                logger.debug(f"Adding replica {cluster=} with {endpoint=}. Primary is the donor")
                self._charm._mysql.create_replica_cluster(
                    endpoint, cluster, instance_label=unit_label
                )
            else:
                donor = ro.split(",")[0]
                logger.debug(f"Adding replica {cluster=} with {endpoint=} using {donor=}")
                self._charm._mysql.create_replica_cluster(
                    endpoint, cluster, instance_label=unit_label, donor=donor
                )

            event.relation.data[self.model.app]["replica-state"] = "initialized"
            logger.debug("Replica cluster created")
            self._charm._on_update_status(None)

        elif state == States.RECOVERING:
            # Recover replica cluster
            self._charm.unit.status = MaintenanceStatus("Replica cluster in recovery")

    def _on_primary_broken(self, event):
        """Handle the async_primary relation being broken."""
        remote_data = self.get_remote_relation_data(event.relation) or {}
        if cluster_name := remote_data.get("cluster-name"):
            self._charm.unit.status = MaintenanceStatus("Removing replica cluster")
            logger.debug(f"Removing replica cluster {cluster_name}")
            self._charm._mysql.remove_replica_cluster(cluster_name)
            logger.debug(f"Replica cluster {cluster_name} removed")
            self._charm._on_update_status(None)
        else:
            logger.warning("No cluster name found, skipping removal")
