# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL async replication replica side module."""

import enum
import logging
import typing

from ops import MaintenanceStatus, Relation, RelationDataContent, Secret, WaitingStatus
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
                self._charm.on[REPLICA_RELATION].relation_created, self._on_replica_created
            )
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_changed, self._on_replica_changed
            )
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_broken, self._on_replica_broken
            )
        else:
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_changed,
                self._on_replica_secondary_changed,
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

        if self.remote_relation_data.get("secret-id") and not self.relation_data.get("endpoint"):
            # received credentials from primary cluster
            # and did not synced credentials
            return States.SYNCING

        if self.remote_relation_data.get("replica-state") == "initialized":
            # cluster added to cluster-set by primary cluster
            if self._charm._mysql.get_cluster_node_count() < self.model.app.planned_units():
                return States.RECOVERING
            return States.READY
        return States.INITIALIZING

    @property
    def idle(self) -> bool:
        """Whether the async replication is idle."""
        if not self.model.unit.is_leader():
            # non leader units are always idle
            return True

        return self.state in [States.READY, None]

    def _get_secret(self) -> Secret:
        """Get secret from primary cluster."""
        secret_id = self.remote_relation_data.get("secret-id")
        return self.model.get_secret(id=secret_id)

    def _async_replication_credentials(self) -> dict[str, str]:
        """Get async replication credentials from primary cluster."""
        secret = self._get_secret()
        return secret.peek_content()

    def _get_endpoint(self) -> str:
        """Get endpoint to be used by the primary cluster.

        This is the address in which the unit must be reachable from the primary cluster.
        Not necessarily the locally resolved address, but an ingress address.
        """
        # TODO: devise method to inform the real address
        # stick to local fqdn for now
        return self._charm._get_unit_fqdn()

    def _on_replica_created(self, _):
        """Handle the async_replica relation being created."""
        self._charm.app.status = MaintenanceStatus("Setting up async replication")

    def _on_replica_changed(self, event):
        """Handle the async_replica relation being changed."""
        state = self.state
        logger.debug(f"Replica state: {state}")

        if state == States.SYNCING:
            logger.debug("Syncing credentials from primary cluster")
            self._charm.unit.status = MaintenanceStatus("Syncing credentials")

            credentials = self._async_replication_credentials()
            sync_keys = {
                SERVER_CONFIG_PASSWORD_KEY: SERVER_CONFIG_USERNAME,
                CLUSTER_ADMIN_PASSWORD_KEY: CLUSTER_ADMIN_USERNAME,
            }

            for key, password in credentials.items():
                # sync credentials only for necessary users
                if key not in sync_keys:
                    continue
                self._charm._mysql.update_user_password(sync_keys[key], password)
                self._charm.set_secret("app", key, password)
                logger.debug(f"Synced {sync_keys[key]} password")

            self._charm.unit.status = MaintenanceStatus("Dissolving replica cluster")
            self._charm._mysql.dissolve_cluster()

            self._charm.unit.status = MaintenanceStatus("Populate endpoint")

            # this cluster name is used by the primary cluster to identify the replica cluster
            self.relation_data["cluster-name"] = self._charm.app_peer_data["cluster-name"]
            # the reachable endpoint address
            self.relation_data["endpoint"] = self._get_endpoint()
            # the node label in the replica cluster to be created
            self.relation_data["node-label"] = self._charm.unit_label

            logger.debug("Data for adding replica cluster shared with primary cluster")

            self._charm.unit.status = WaitingStatus("Waiting for primary cluster")
        elif state == States.READY:
            # update status
            logger.debug("Replica cluster is ready")
            # reset the number of units added to the cluster
            # this will trigger secondaies to join the cluster
            self._charm.app_peer_data["units-added-to-cluster"] = "1"
            self._charm._on_update_status(None)
        elif state == States.RECOVERING:
            # recoveryng cluster (copying data and/or joining units)
            self._charm.unit.status = MaintenanceStatus("Recovering replica cluster")
            logger.debug("Recovering replica cluster")
            event.defer()

    def _on_replica_broken(self, event):
        """Handle the async_replica relation being broken."""
        if self._charm._mysql.is_instance_in_cluster(self._charm.unit_label):
            logger.debug("Replica cluster still active. Waiting for dissolution")
            event.defer()
            return
        # recriate local cluster
        logger.debug("Recreating local cluster")
        self._charm._mysql.create_cluster(self._charm.unit_label)
        self._charm._mysql.create_cluster_set()

    def _on_replica_secondary_changed(self, _):
        """Reset cluster secondaries to allow cluster rejoin after primary recovery."""
        # the replica state is initialized when the primary cluster finished
        # creating the replica cluster on this cluster primary/leader unit
        if self.remote_relation_data.get("replica-state") == "initialized":
            logger.debug("Reset seconday unit to allow cluster rejoin")
            # reset unit flags to allow cluster rejoin after primary recovery
            # the unit will rejoin on the next peer relation changed or update status
            self._charm.unit_peer_data["member-state"] = "waiting"
            del self._charm.unit_peer_data["unit-initialized"]
            self._charm.unit.status = WaitingStatus("waiting to join the cluster")
