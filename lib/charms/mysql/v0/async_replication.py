# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL async replication module."""

import enum
import json
import logging
import typing
from functools import cached_property

from charms.mysql.v0.mysql import MySQLFencingWritesError, MySQLPromoteClusterToPrimaryError
from ops import (
    ActionEvent,
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    RelationDataContent,
    Secret,
    WaitingStatus,
)
from ops.framework import Object
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed
from typing_extensions import Optional

from constants import (
    BACKUPS_PASSWORD_KEY,
    BACKUPS_USERNAME,
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    MONITORING_PASSWORD_KEY,
    MONITORING_USERNAME,
    ROOT_PASSWORD_KEY,
    ROOT_USERNAME,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "4de21f1a022c4e2c87ac8e672ec16f6a"
LIBAPI = 0
LIBPATCH = 1

PRIMARY_RELATION = "async-primary"
REPLICA_RELATION = "async-replica"


class ClusterSetInstanceState(typing.NamedTuple):
    """Cluster set instance state."""

    cluster_role: str  # primary or replica
    instance_role: str  # primary or secondary
    relation_side: str  # primary or replica


class States(str, enum.Enum):
    """States for the relation."""

    SYNCING = "syncing"  # credentials are being synced
    INITIALIZING = "initializing"  # cluster to be added
    RECOVERING = "recovery"  # replica cluster is being recovered
    READY = "ready"  # cluster set is ready
    FAILED = "failed"  # cluster set is in a failed state


class MySQLAsyncReplication(Object):
    """MySQL async replication base class."""

    def __init__(self, charm: "MySQLOperatorCharm", relation_name: str):
        super().__init__(charm, relation_name)
        self._charm = charm

        # relation broken is observed on all units
        self.framework.observe(
            self._charm.on[PRIMARY_RELATION].relation_broken, self.on_async_relation_broken
        )
        self.framework.observe(
            self._charm.on[REPLICA_RELATION].relation_broken, self.on_async_relation_broken
        )

    @cached_property
    def role(self) -> ClusterSetInstanceState:
        """Current cluster set role of the unit, after the relation is established."""
        is_replica = self._charm._mysql.is_cluster_replica()

        if is_replica:
            cluster_role = "replica"
        elif is_replica is False:
            cluster_role = "primary"
        else:
            cluster_role = "unset"

        _, instance_role = self._charm._mysql.get_member_state()

        if self.model.get_relation(REPLICA_RELATION):
            relation_side = "replica"
        else:
            relation_side = "primary"

        return ClusterSetInstanceState(cluster_role, instance_role, relation_side)

    def get_remote_relation_data(self, relation: Relation) -> Optional[RelationDataContent]:
        """Remote data."""
        if not relation.app:
            return
        return relation.data[relation.app]

    def _on_promote_standby_cluster(self, event: ActionEvent) -> None:
        """Promote a standby cluster to primary."""
        if not self._charm.unit.is_leader():
            event.fail("Only the leader unit can promote a standby cluster")
            return

        if not self._charm._mysql.is_cluster_replica():
            event.fail("Only a standby cluster can be promoted")
            return

        cluster_set_name = event.params.get("cluster-set-name")
        if (
            not cluster_set_name
            or cluster_set_name != self._charm.app_peer_data["cluster-set-domain-name"]
        ):
            event.fail("Invalid cluster set name")
            return

        # promote cluster to primary
        cluster_name = self._charm.app_peer_data["cluster-name"]
        force = event.params.get("force", False)

        try:
            self._charm._mysql.promote_cluster_to_primary(cluster_name, force)
            event.set_results({"message": f"Cluster {cluster_name} promoted to primary"})
        except MySQLPromoteClusterToPrimaryError:
            logger.exception("Failed to promote cluster to primary")
            event.fail("Failed to promote cluster to primary")

    def _on_fence_unfence_writes_action(self, event: ActionEvent) -> None:
        """Fence or unfence writes to a cluster."""
        if (
            event.params.get("cluster-set-name")
            != self._charm.app_peer_data["cluster-set-domain-name"]
        ):
            event.fail("Invalid cluster set name")
            return

        if self.role.cluster_role == "replica":
            event.fail("Only a primary cluster can have writes fenced/unfence")
            return

        try:
            if (
                event.handle.kind == "fence_writes_action"
                and not self._charm._mysql.is_cluster_writes_fenced()
            ):
                logger.info("Fencing writes to the cluster")
                self._charm._mysql.fence_writes()
                event.set_results({"message": "Writes to the cluster are now fenced"})
            elif (
                event.handle.kind == "unfence_writes_action"
                and self._charm._mysql.is_cluster_writes_fenced()
            ):
                logger.info("Unfencing writes to the cluster")
                self._charm._mysql.unfence_writes()
                event.set_results({"message": "Writes to the cluster are now resumed"})
        except MySQLFencingWritesError:
            event.fail("Failed to fence writes. Check logs for details")
            return

    def on_async_relation_broken(self, event):  # noqa: C901
        """Handle the async relation being broken from either side."""
        # Remove the replica cluster, if this is the primary

        if self.role.cluster_role == "replica":
            # The cluster being removed is a replica cluster

            self._charm.unit.status = WaitingStatus("Waiting for cluster to be dissolved")
            try:
                # hold execution until the cluster is dissolved
                for attempt in Retrying(stop=stop_after_attempt(30), wait=wait_fixed(10)):
                    with attempt:
                        if self._charm._mysql.is_instance_in_cluster(self._charm.unit_label):
                            logger.debug("Waiting for cluster to be dissolved")
                            raise Exception
            except RetryError:
                raise

            self._charm.unit.status = BlockedStatus("Standalone read-only unit.")
            # reset flag to allow instances rejoining the cluster
            self._charm.unit_peer_data["member-state"] = "waiting"
            del self._charm.unit_peer_data["unit-initialized"]
            if self._charm.unit.is_leader():
                self._charm.app.status = BlockedStatus("Recreate cluster.")
                logger.info(
                    "\n\tThis is a replica cluster and will be dissolved.\n"
                    "\tThe cluster can be recreated with the `recreate-cluster` action.\n"
                    "\tAfter recreating the cluster, it can be (re)joined to a cluster set"
                )
                # reset the cluster node count flag
                del self._charm.app_peer_data["units-added-to-cluster"]

        elif self.role.cluster_role == "primary":
            if self._charm.unit.is_leader():
                # only leader units can remove replica clusters
                remote_data = self.get_remote_relation_data(event.relation) or {}
                if cluster_name := remote_data.get("cluster-name"):
                    if self._charm._mysql.is_cluster_in_cluster_set(cluster_name):
                        self._charm.unit.status = MaintenanceStatus("Removing replica cluster")
                        logger.debug(f"Removing replica cluster {cluster_name}")
                        self._charm._mysql.remove_replica_cluster(cluster_name)
                        logger.debug(f"Replica cluster {cluster_name} removed")
                        self._charm.unit.status = ActiveStatus(self._charm.active_status_message)
                    else:
                        logger.warning(
                            f"Replica cluster {cluster_name} not found in cluster set, skipping removal"
                        )
                else:
                    # Relation being broken before setup, e.g.: due to replica with user data
                    logger.warning("No cluster name found, skipping removal")
            elif self._charm.unit_peer_data.get("member-state") == "waiting":
                # set member-state to allow status update
                # needed for secondaries status update when removing due to replica with user data
                self._charm.unit_peer_data["member-state"] = "unknown"
            self._charm._on_update_status(None)


class MySQLAsyncReplicationPrimary(MySQLAsyncReplication):
    """MySQL async replication primary side.

    Implements the setup phase of the async replication for the primary side.
    """

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, PRIMARY_RELATION)

        # Actions observed only on the primary side to avoid duplicated execution
        # promotion action
        self.framework.observe(
            self._charm.on.promote_standby_cluster_action, self._on_promote_standby_cluster
        )

        # fence writes action
        self.framework.observe(
            self._charm.on.fence_writes_action, self._on_fence_unfence_writes_action
        )
        # unfence writes action
        self.framework.observe(
            self._charm.on.unfence_writes_action, self._on_fence_unfence_writes_action
        )

        if self._charm.unit.is_leader():
            self.framework.observe(
                self._charm.on[PRIMARY_RELATION].relation_created, self._on_primary_created
            )
            self.framework.observe(
                self._charm.on[PRIMARY_RELATION].relation_changed,
                self._on_primary_relation_changed,
            )

    def get_relation(self, relation_id: int) -> Optional[Relation]:
        """Return the relation."""
        return self.model.get_relation(PRIMARY_RELATION, relation_id)

    def get_local_relation_data(self, relation: Relation) -> Optional[RelationDataContent]:
        """Local data."""
        return relation.data[self.model.app]

    def get_state(self, relation: Relation) -> Optional[States]:
        """State of the relation, on primary side."""
        if not relation:
            return None

        local_data = self.get_local_relation_data(relation)
        remote_data = self.get_remote_relation_data(relation) or {}

        if not local_data:
            return None

        if local_data.get("is-replica") == "true":
            return States.FAILED

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
        if self._charm._mysql.is_cluster_replica():
            logger.error(
                f"This a replica cluster, cannot be related as {PRIMARY_RELATION}. Remove relation."
            )
            self._charm.unit.status = BlockedStatus(
                f"This is a replica cluster. Unrelate from the {PRIMARY_RELATION} relation"
            )
            event.relation.data[self.model.app]["is-replica"] = "true"
            return

        self._charm.app.status = MaintenanceStatus("Setting up async replication")
        # CMR secrets not working: https://bugs.launchpad.net/juju/+bug/2046484
        # logger.debug("Granting secrets access to async replication relation")
        # secret = self._get_secret()
        # secret_id = secret.get_info().id
        # secret.grant(event.relation)

        # logger.debug(f"Sharing {secret_id} with replica cluster")
        # event.relation.data[self.model.app]["secret-id"] = secret_id

        # workaround: using relation data instead of CMR secrets
        secret = self._get_secret()

        logger.debug("Sharing secret with replica cluster")
        event.relation.data[self.model.app]["secret-id"] = json.dumps(secret.get_content())
        event.relation.data[self.model.app]["cluster-name"] = self._charm._mysql.cluster_name

    def _on_primary_relation_changed(self, event):
        """Handle the async_primary relation being changed."""
        state = self.get_state(event.relation)

        if state == States.INITIALIZING:
            # Add replica cluster primary node
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


class MySQLAsyncReplicationReplica(MySQLAsyncReplication):
    """MySQL async replication replica side.

    Implements the setup phase of the async replication for the replica side.
    """

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, REPLICA_RELATION)

        if self._charm.unit.is_leader():
            # leader/primary
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_created, self._on_replica_created
            )
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_changed, self._on_replica_changed
            )
        else:
            # non-leader/secondaries
            self.framework.observe(
                self._charm.on[REPLICA_RELATION].relation_created,
                self._on_replica_secondary_created,
            )
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

        if self.relation_data.get("user-data-found") == "true":
            return States.FAILED

        if self.remote_relation_data.get("secret-id") and not self.relation_data.get("endpoint"):
            # received credentials from primary cluster
            # and did not synced credentials
            return States.SYNCING

        if self.remote_relation_data.get("replica-state") == "initialized":
            # cluster added to cluster-set by primary cluster
            if self._charm.cluster_fully_initialized:
                return States.READY
            return States.RECOVERING
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
        # secret = self._get_secret()
        # return secret.peek_content()
        return json.loads(self.remote_relation_data.get("secret-id", "{}"))

    def _get_endpoint(self) -> str:
        """Get endpoint to be used by the primary cluster.

        This is the address in which the unit must be reachable from the primary cluster.
        Not necessarily the locally resolved address, but an ingress address.
        """
        # TODO: devise method to inform the real address
        # using unit informed address (fqdn or ip)
        return self._charm.unit_address

    def _on_replica_created(self, _):
        """Handle the async_replica relation being created on the leader unit."""
        logger.debug("Checking for user data")
        if self._charm._mysql.get_non_system_databases():
            logger.info(
                "\n\tUser data found, aborting async replication setup."
                "\n\tEnsure the cluster has no user data before trying to join a cluster set."
                "\n\tAfter removing/backing up the data, remove the relation and add it again."
            )
            self._charm.app.status = BlockedStatus("User data found, check instruction in the log")
            self._charm.unit.status = BlockedStatus(
                "User data found, aborting async replication setup"
            )
            self.relation_data["user-data-found"] = "true"
            return

        self._charm.app.status = MaintenanceStatus("Setting up async replication")
        self._charm.unit.status = WaitingStatus("awaiting sync data from primary cluster")

    def _on_replica_changed(self, event):
        """Handle the async_replica relation being changed."""
        state = self.state
        logger.debug(f"Replica cluster {state=}")

        if state == States.SYNCING:
            if not self._charm.cluster_fully_initialized:
                # cluster is not fully initialized
                # avoid race on credentials sync
                logger.debug(
                    "Cluster not fully initialized yet, waiting until all units join the cluster"
                )
                event.defer()
                return
            logger.debug("Syncing credentials from primary cluster")
            self._charm.unit.status = MaintenanceStatus("Syncing credentials")

            credentials = self._async_replication_credentials()
            sync_keys = {
                SERVER_CONFIG_PASSWORD_KEY: SERVER_CONFIG_USERNAME,
                CLUSTER_ADMIN_PASSWORD_KEY: CLUSTER_ADMIN_USERNAME,
                MONITORING_PASSWORD_KEY: MONITORING_USERNAME,
                BACKUPS_PASSWORD_KEY: BACKUPS_USERNAME,
                ROOT_PASSWORD_KEY: ROOT_USERNAME,
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
            # reset the cluster node count flag
            del self._charm.app_peer_data["units-added-to-cluster"]

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
            logger.debug("Replica cluster primary is ready")

            # sync cluster-set domain name across clusters
            if cluster_set_domain_name := self._charm._mysql.get_cluster_set_name():
                self._charm.app_peer_data["cluster-set-domain-name"] = cluster_set_domain_name

            # set the number of units added to the cluster for a single unit replica cluster
            # needed here since it will skip the `RECOVERING` state
            if self._charm.app.planned_units() == 1:
                self._charm.app_peer_data["units-added-to-cluster"] = "1"

            self._charm._on_update_status(None)
        elif state == States.RECOVERING:
            # recoveryng cluster (copying data and/or joining units)
            self._charm.app.status = MaintenanceStatus("Recovering replica cluster")
            self._charm.unit.status = WaitingStatus("Waiting for recovery to complete")
            logger.debug("Awaiting other units to join the cluster")
            # reset the number of units added to the cluster
            # this will trigger secondaries to join the cluster
            node_count = self._charm._mysql.get_cluster_node_count()
            self._charm.app_peer_data["units-added-to-cluster"] = str(node_count)
            event.defer()

    def _on_replica_secondary_created(self, _):
        """Handle the async_replica relation being created for secondaries/non-leader."""
        # set waiting state to inhibit auto recovery, only when not already set
        if not self._charm.unit_peer_data.get("member-state") == "waiting":
            self._charm.unit_peer_data["member-state"] = "waiting"
            self._charm.unit.status = WaitingStatus("waiting replica cluster be configured")

    def _on_replica_secondary_changed(self, _):
        """Reset cluster secondaries to allow cluster rejoin after primary recovery."""
        # the replica state is initialized when the primary cluster finished
        # creating the replica cluster on this cluster primary/leader unit
        if self.remote_relation_data.get(
            "replica-state"
        ) == "initialized" and not self._charm._mysql.is_instance_in_cluster(
            self._charm.unit_label
        ):
            logger.debug("Reset secondary unit to allow cluster rejoin")
            # reset unit flag to allow cluster rejoin after primary recovery
            # the unit will rejoin on the next peer relation changed or update status
            del self._charm.unit_peer_data["unit-initialized"]
            self._charm.unit.status = WaitingStatus("waiting to join the cluster")
