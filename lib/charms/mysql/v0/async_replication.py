# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""MySQL cluster-set async replication module."""

import enum
import logging
import typing
from functools import cached_property
from time import sleep

from charms.mysql.v0.mysql import (
    MySQLPromoteClusterToPrimaryError,
    MySQLRejoinClusterError,
)
from constants import (
    BACKUPS_PASSWORD_KEY,
    BACKUPS_USERNAME,
    CLUSTER_ADMIN_PASSWORD_KEY,
    CLUSTER_ADMIN_USERNAME,
    MONITORING_PASSWORD_KEY,
    MONITORING_USERNAME,
    PEER,
    ROOT_PASSWORD_KEY,
    ROOT_USERNAME,
    SERVER_CONFIG_PASSWORD_KEY,
    SERVER_CONFIG_USERNAME,
)
from mysql_shell.models import (
    ClusterGlobalStatus,
    ClusterRole,
    InstanceRole,
    InstanceState,
)
from ops import (
    ActionEvent,
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    RelationBrokenEvent,
    RelationCreatedEvent,
    RelationDataContent,
    Secret,
    SecretChangedEvent,
    SecretNotFoundError,
    WaitingStatus,
)
from ops.framework import Object
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed

if typing.TYPE_CHECKING:
    from charm import MySQLOperatorCharm

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "4de21f1a022c4e2c87ac8e672ec16f6a"
LIBAPI = 0
LIBPATCH = 12

PYDEPS = ["mysql_shell_client ~= 0.6"]

RELATION_OFFER = "replication-offer"
RELATION_CONSUMER = "replication"


class ClusterSetInstanceState(typing.NamedTuple):
    """Cluster set instance state."""

    cluster_role: str  # primary or replica
    instance_role: str  # primary or secondary
    relation_side: str  # primary or replica


class States(str, enum.Enum):
    """States for the relation."""

    UNINITIALIZED = "uninitialized"  # relation is not initialized
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
            self._charm.on[RELATION_OFFER].relation_broken, self.on_async_relation_broken
        )
        self.framework.observe(
            self._charm.on[RELATION_CONSUMER].relation_broken, self.on_async_relation_broken
        )

    @cached_property
    def role(self) -> ClusterSetInstanceState:
        """Current cluster set role of the unit, after the relation is established."""
        is_replica = self._charm._mysql.is_cluster_replica()

        # TODO:
        #  Remove `.lower()` when migrating to MySQL 8.4
        #  (when breaking changes are allowed)
        if is_replica:
            cluster_role = ClusterRole.REPLICA.lower()
        elif is_replica is False:
            cluster_role = ClusterRole.PRIMARY.lower()
        else:
            # TODO:
            #  Uppercase when migrating to MySQL 8.4
            #  (when breaking changes are allowed)
            cluster_role = "unset"

        instance_role = self._charm._mysql.get_member_role()

        if self.model.get_relation(RELATION_CONSUMER):
            relation_side = RELATION_CONSUMER
        else:
            relation_side = RELATION_OFFER

        # TODO:
        #  Remove `.lower()` when migrating to MySQL 8.4
        #  (when breaking changes are allowed)
        return ClusterSetInstanceState(cluster_role, instance_role.lower(), relation_side)

    @property
    def cluster_name(self) -> str:
        """This cluster name."""
        return self._charm.app_peer_data["cluster-name"]

    @property
    def cluster_set_name(self) -> str:
        """Cluster set name."""
        return self._charm.app_peer_data["cluster-set-domain-name"]

    @property
    def relation(self) -> Relation | None:
        """Relation."""
        return self.model.get_relation(RELATION_OFFER) or self.model.get_relation(
            RELATION_CONSUMER
        )

    @property
    def relation_data(self) -> RelationDataContent | None:
        """Relation data."""
        if not self.relation:
            return
        return self.relation.data[self.model.app]

    @property
    def remote_relation_data(self) -> RelationDataContent | None:
        """Remote relation data."""
        if not self.relation or not self.relation.app:
            return
        return self.relation.data[self.relation.app]

    def _on_promote_to_primary(self, event: ActionEvent) -> None:
        """Promote a standby cluster to primary."""
        if event.params.get("scope") != "cluster":
            return

        if not self._charm.unit.is_leader():
            event.fail("Only the leader unit can promote a standby cluster")
            return

        if not self._charm._mysql.is_cluster_replica():
            event.fail("Only a standby cluster can be promoted")
            return

        # promote cluster to primary
        cluster_name = self.cluster_name
        force = event.params.get("force", False)

        try:
            self._charm._mysql.promote_cluster_to_primary(cluster_name, force)
            message = f"Cluster {cluster_name} promoted to primary"
            logger.info(message)
            event.set_results({"message": message})
            self._charm._on_update_status(None)
            # write counter to propagate status update on the other side
            self.relation_data["switchover"] = str(
                int(self.relation_data.get("switchover", 0)) + 1
            )
        except MySQLPromoteClusterToPrimaryError:
            logger.exception("Failed to promote cluster to primary")
            event.fail("Failed to promote cluster to primary")

    def on_async_relation_broken(self, event: RelationBrokenEvent):  # noqa: C901
        """Handle the async relation being broken from either side."""
        # Remove the replica cluster, if this is the primary

        # TODO:
        #  Remove `.lower()` when migrating to MySQL 8.4
        #  (when breaking changes are allowed)
        if (
            self.role.cluster_role in (ClusterRole.REPLICA.lower(), "unset")
            and not self._charm.removing_unit
        ):
            # The cluster being removed is a replica cluster
            # role is `unset` when the primary cluster dissolved the replica before
            # this hook execution i.e. was faster on running the handler

            self._charm.unit.status = WaitingStatus("Waiting for cluster to be dissolved")
            try:
                # hold execution until the cluster is dissolved
                for attempt in Retrying(stop=stop_after_attempt(30), wait=wait_fixed(10)):
                    with attempt:
                        if self._charm._mysql.is_instance_in_cluster(self._charm.unit_label):
                            logger.debug("Waiting for cluster to be dissolved")
                            raise Exception
            except RetryError:
                self._charm.unit.status = BlockedStatus(
                    "Replica cluster not dissolved after relation broken"
                )
                logger.warning(
                    "Replica cluster not dissolved after relation broken by the primary cluster."
                    "\n\tThis happens when the primary cluster was removed prior to removing the async relation."
                    "\n\tThis cluster can be promoted to primary with the `promote-to-primary` action."
                )
                return

            self._charm.unit.status = BlockedStatus("Standalone read-only unit.")
            # reset flag to allow instances rejoining the cluster
            self._charm.unit_peer_data["member-state"] = "waiting"
            if not self._charm.unit.is_leader():
                # delay non leader to avoid `update_status` running before
                # leader updates app peer data
                sleep(10)
                return
            self._charm.app.status = BlockedStatus("Recreate or rejoin cluster.")
            logger.info(
                "\n\tThis is a replica cluster and will be dissolved.\n"
                "\tThe cluster can be recreated with the `recreate-cluster` action.\n"
                "\tAlternatively the cluster can be rejoined to the cluster set."
            )
            # set flag to persist removed from cluster-set state
            self._charm.app_peer_data["removed-from-cluster-set"] = "true"

        # TODO:
        #  Remove `.lower()` when migrating to MySQL 8.4
        #  (when breaking changes are allowed)
        elif self.role.cluster_role == ClusterRole.PRIMARY.lower():
            if self._charm.unit.is_leader():
                # only leader units can remove replica clusters
                remote_data = event.relation.data.get(event.relation.app) or {}
                if cluster_name := remote_data.get("cluster-name"):
                    if self._charm._mysql.is_cluster_in_cluster_set(cluster_name):
                        self._charm.unit.status = MaintenanceStatus("Removing replica cluster")
                        logger.info(f"Removing replica cluster {cluster_name}")

                        # force removal when cluster is invalidated
                        force = self._charm._mysql.get_replica_cluster_status(cluster_name) in [
                            ClusterGlobalStatus.INVALIDATED,
                            ClusterGlobalStatus.UNKNOWN,
                        ]

                        self._charm._mysql.remove_replica_cluster(cluster_name, force=force)
                        logger.info(f"Replica cluster {cluster_name} removed")
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

        if self._charm.app_peer_data.get("async-ready"):
            # if set reset async-ready flag
            del self._charm.app_peer_data["async-ready"]

    def _on_rejoin_cluster_action(self, event: ActionEvent) -> None:
        """Rejoin cluster to cluster set action handler."""
        cluster = event.params.get("cluster-name")
        if not cluster:
            message = "Invalid/empty cluster name"
            event.fail(message)
            logger.info(message)
            return

        if not self._charm._mysql.is_cluster_in_cluster_set(cluster):
            message = f"Cluster {cluster=} not found in cluster set"
            event.fail(message)
            logger.info(message)
            return

        status = self._charm._mysql.get_replica_cluster_status(cluster)
        if status != ClusterGlobalStatus.INVALIDATED:
            message = f"Cluster {status=}. Only `INVALIDATED` clusters can be rejoined"
            event.fail(message)
            logger.info(message)
            return

        try:
            self._charm._mysql.rejoin_cluster(cluster)
            message = f"{cluster=} rejoined to cluster set"
            logger.info(message)
            event.set_results({"message": message})
        except MySQLRejoinClusterError:
            message = f"Failed to rejoin {cluster=} to the cluster set"
            event.fail(message)
            logger.error(message)


class MySQLAsyncReplicationOffer(MySQLAsyncReplication):
    """MySQL async replication primary side.

    Implements the setup phase of the async replication for the primary side.
    """

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, RELATION_OFFER)

        # Actions observed only on the primary class to avoid duplicated execution
        # promotion action since both classes are always instantiated
        self.framework.observe(
            self._charm.on.promote_to_primary_action, self._on_promote_to_primary
        )

        # rejoin invalidated cluster action
        self.framework.observe(
            self._charm.on.rejoin_cluster_action, self._on_rejoin_cluster_action
        )

        # promote offer side as primary
        self.framework.observe(
            self._charm.on.create_replication_action, self._on_create_replication
        )

        self.framework.observe(
            self._charm.on[RELATION_OFFER].relation_created, self._on_offer_created
        )
        self.framework.observe(
            self._charm.on[RELATION_OFFER].relation_changed,
            self._on_offer_relation_changed,
        )

        self.framework.observe(
            self._charm.on[RELATION_OFFER].relation_broken, self._on_offer_relation_broken
        )

        self.framework.observe(self._charm.on.secret_changed, self._on_secret_change)

    @property
    def state(self) -> States | None:
        """State of the relation, on primary side."""
        if not self.relation:
            return States.UNINITIALIZED

        local_data = self.relation_data
        remote_data = self.remote_relation_data or {}

        if not local_data:
            return States.UNINITIALIZED

        if local_data.get("is-replica") == "true":
            return States.FAILED

        if local_data.get("secret-id") and not remote_data.get("endpoint"):
            return States.SYNCING

        if local_data.get("secret-id") and remote_data.get("endpoint"):
            # evaluate cluster status
            replica_status = self._charm._mysql.get_replica_cluster_status(
                remote_data["cluster-name"]
            )
            if replica_status in (ClusterGlobalStatus.OK, ClusterGlobalStatus.INVALIDATED):
                return States.READY
            elif replica_status == ClusterGlobalStatus.UNKNOWN:
                return States.INITIALIZING
            else:
                return States.RECOVERING
        if self.role.relation_side == RELATION_CONSUMER:
            # if on the consume and is primary
            # the cluster is ready when fully initialized
            if self._charm.cluster_fully_initialized:
                return States.READY
            return States.RECOVERING

    @property
    def idle(self) -> bool:
        """Whether the async replication is idle for all related clusters."""
        if not self.model.unit.is_leader():
            # non leader units are always idle
            return True

        if self._charm.app_peer_data.get("async-ready") == "true":
            # transitional state between relation created and setup_action
            return False

        return self.state in [States.READY, States.UNINITIALIZED]

    @property
    def secret(self) -> Secret | None:
        """Return the async replication secret."""
        if not self.relation:
            return
        if secret_id := self.relation_data.get("secret-id"):
            return self._charm.model.get_secret(id=secret_id)

    def _get_secret(self) -> Secret:
        """Return async replication necessary secrets."""
        app_secret = self._charm.model.get_secret(label=f"{PEER}.{self.model.app.name}.app")
        content = app_secret.peek_content()
        # filter out unnecessary secrets
        shared_content = dict(filter(lambda x: "password" in x[0], content.items()))

        return self._charm.model.app.add_secret(content=shared_content)

    def _on_create_replication(self, event: ActionEvent):
        """Promote the offer side to primary on initial setup."""
        if self._charm.app_peer_data.get("async-ready") != "true":
            event.fail("Relation created but not ready")
            return

        if self.role.relation_side == RELATION_CONSUMER:
            # given that only the offer side of the relation can
            # grant secret permissions for CMR relations, we
            # limit the primary setup to it
            event.fail("Only offer side can be setup as primary cluster")
            return

        if not self._charm.unit.is_leader():
            event.fail("Only the leader unit can promote a cluster")
            return

        if not self._charm.cluster_initialized:
            event.fail("Wait until cluster is initialized")
            return

        if not self.relation:
            event.fail(f"{RELATION_OFFER} relation not found")
            return

        if self.relation_data.get("secret-id"):
            event.fail("Action already run")
            return

        self._charm.app.status = MaintenanceStatus("Setting up replication")
        self._charm.unit.status = MaintenanceStatus("Sharing credentials with replica cluster")
        logger.info("Granting secrets access to replication relation")
        secret = self._get_secret()
        secret_id = secret.id or ""
        secret.grant(self.relation)

        # get workload version
        version = self._charm._mysql.get_mysql_version()

        logger.debug(f"Sharing {secret_id=} with replica cluster")
        # Set variables for credential sync and validations
        self.relation_data.update(  # pyright: ignore[reportCallIssue]
            {
                "secret-id": secret_id,
                "cluster-name": self.cluster_name,
                "mysql-version": version,
                "replication-name": event.params.get("name", "default"),
            }
        )
        # reset async-ready flag set on relation created
        del self._charm.app_peer_data["async-ready"]

    def _on_offer_created(self, event: RelationCreatedEvent):
        """Validate relations and share credentials with replica cluster."""
        if not self._charm.unit.is_leader():
            return

        if (
            isinstance(self._charm.app.status, BlockedStatus)
            and self._charm.app_peer_data.get("removed-from-cluster-set") == "true"
        ):
            # Test for a broken relation on the primary side
            logger.error(
                "Cannot setup async relation with primary cluster in blocked/read-only state\n"
                "Remove the relation."
            )
            message = f"Cluster is in a blocked state. Remove {RELATION_OFFER} relation"
            self._charm.unit.status = BlockedStatus(message)
            self._charm.app.status = BlockedStatus(message)

        if not self.model.get_relation(RELATION_OFFER):
            # safeguard against a deferred event a previous relation.
            logger.error(
                "Relation created running against removed relation.\n"
                f"Remove {RELATION_OFFER} relation and retry."
            )
            self._charm.unit.status = BlockedStatus(f"Remove {RELATION_OFFER} relation and retry")
            return

        if not self._charm.cluster_initialized:
            logger.info("Cluster not initialized, deferring event")
            event.defer()
            return

        if self._charm._mysql.is_cluster_replica():
            logger.error(
                f"This is a replica cluster, cannot be related as {RELATION_OFFER}. Remove relation."
            )
            self._charm.unit.status = BlockedStatus(
                f"This is a replica cluster. Unrelate from the {RELATION_OFFER} relation"
            )
            event.relation.data[self.model.app]["is-replica"] = "true"
            return

        self.relation_data.update(  # pyright: ignore[reportCallIssue]
            {
                "cluster-set-name": self.cluster_set_name,
            }
        )
        # sets ok flag
        self._charm.app_peer_data["async-ready"] = "true"
        message = "Ready to create replication"
        self._charm.unit.status = BlockedStatus(message)
        self._charm.app.status = BlockedStatus(message)

    def _on_offer_relation_changed(self, event):
        """Handle the async_primary relation being changed."""
        if not self._charm.unit.is_leader():
            return

        state = self.state

        if state == States.INITIALIZING:
            # Add replica cluster primary node
            logger.info("Creating replica cluster primary node")
            self._charm.unit.status = MaintenanceStatus("Adding replica cluster")
            remote_data = self.remote_relation_data or {}

            cluster = remote_data["cluster-name"]
            endpoint = remote_data["endpoint"]
            unit_label = remote_data["node-label"]

            logger.debug("Looking for a donor node")
            _, ro, _ = self._charm.get_cluster_endpoints(self.relation.name)

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
            logger.info("Replica cluster created")
            self._charm._on_update_status(None)

        elif state == States.RECOVERING:
            # Recover replica cluster
            self._charm.unit.status = MaintenanceStatus("Replica cluster in recovery")

        elif state == States.READY:
            # trigger update status on relation update when ready
            # speeds up status on switchover
            self._charm._on_update_status(None)

    def _on_offer_relation_broken(self, event: RelationBrokenEvent):
        """Handle the async_primary relation being broken."""
        if self._charm.unit.is_leader():
            # remove relation secret by id
            if secret_id := event.relation.data[self.model.app].get("secret-id"):
                logger.debug("Removing replication secret")
                secret = self._charm.model.get_secret(id=secret_id)
                secret.remove_all_revisions()
            else:
                logger.debug("Secret-id not set, skipping removal")

    def _on_secret_change(self, event: SecretChangedEvent):
        """Propagates the secret being changed."""
        if not self._charm.unit.is_leader():
            return

        if not self.relation:
            return

        if self.state != States.READY:
            # skip secret propagation on setup phase
            return

        if event.secret.label != f"{PEER}.{self.model.app.name}.app":
            # skip if secret is not main application secret
            return

        logger.debug("Updating secret on relation")
        self.secret.set_content(event.secret.peek_content())


class MySQLAsyncReplicationConsumer(MySQLAsyncReplication):
    """MySQL async replication replica side.

    Implements the setup phase of the async replication for the replica side.
    """

    def __init__(self, charm: "MySQLOperatorCharm"):
        super().__init__(charm, RELATION_CONSUMER)

        # leader/primary
        self.framework.observe(
            self._charm.on[RELATION_CONSUMER].relation_created, self._on_consumer_relation_created
        )
        self.framework.observe(
            self._charm.on[RELATION_CONSUMER].relation_changed, self._on_consumer_changed
        )
        # non-leader/secondaries
        self.framework.observe(
            self._charm.on[RELATION_CONSUMER].relation_created,
            self._on_consumer_non_leader_created,
        )
        self.framework.observe(
            self._charm.on[RELATION_CONSUMER].relation_changed,
            self._on_consumer_non_leader_changed,
        )
        self.framework.observe(self._charm.on.secret_changed, self._on_secret_change)

    @property
    def state(self) -> States | None:
        """State of the relation, on consumer side."""
        if not self.relation:
            return None

        if self.relation_data.get("user-data-found") == "true":
            return States.FAILED

        if self.remote_relation_data.get("secret-id") and not self.relation_data.get("endpoint"):
            # received credentials from primary cluster
            # and did not synced credentials
            return States.SYNCING

        if self.model.get_relation(RELATION_CONSUMER):
            if self.replica_initialized:
                # cluster added to cluster-set by primary cluster
                if self._charm.cluster_fully_initialized:
                    return States.READY
                return States.RECOVERING
        else:
            return States.READY

        return States.INITIALIZING

    @property
    def idle(self) -> bool:
        """Whether the async replication is idle."""
        if not self.model.unit.is_leader():
            # non leader units are always idle
            return True

        return self.state in [States.READY, None]

    @property
    def returning_cluster(self) -> bool:
        """Whether to skip checks.

        Used for skipping checks when a replica cluster was removed through broken relation.
        """
        remote_cluster_set_name = self.remote_relation_data.get("cluster-set-name")
        return (
            self._charm.app_peer_data.get("removed-from-cluster-set") == "true"
            and self.cluster_set_name == remote_cluster_set_name
        )

    @property
    def replica_initialized(self) -> bool:
        """Whether the replica cluster was initialized."""
        return self.remote_relation_data.get("replica-state") == "initialized"

    def _check_version(self) -> bool:
        """Check if the MySQL version is compatible with the primary cluster."""
        # TODO:
        #  Remove `.split("-")[0]` when migrating to MySQL 8.4
        #  (when breaking changes are allowed)
        remote_version = self.remote_relation_data.get("mysql-version").split("-")[0]
        local_version = self._charm._mysql.get_mysql_version()

        if not remote_version:
            return False

        if remote_version != local_version:
            logger.error(
                f"Primary cluster MySQL version {remote_version} is not compatible with this"
                f"cluster MySQL version {local_version}"
            )
            return False

        return True

    def _obtain_secret(self) -> Secret:
        """Get secret from primary cluster."""
        secret_id = self.remote_relation_data.get("secret-id")
        return self._charm.model.get_secret(id=secret_id)

    def _async_replication_credentials(self) -> dict[str, str]:
        """Get async replication credentials from primary cluster."""
        secret = self._obtain_secret()
        return secret.peek_content()

    def _get_endpoint(self) -> str | None:
        """Get endpoint to be used by the primary cluster.

        This is the address in which the unit must be reachable from the primary cluster.
        Not necessarily the locally resolved address, but an ingress address.
        """
        if self.relation.name == RELATION_CONSUMER:
            return self._charm.get_unit_address(self._charm.unit, RELATION_CONSUMER)
        if self.relation.name == RELATION_OFFER:
            return self._charm.get_unit_address(self._charm.unit, RELATION_OFFER)

    def _on_consumer_relation_created(self, event):
        """Handle the async_replica relation being created on the leader unit."""
        if not self._charm.unit.is_leader():
            return
        if not self._charm.unit_initialized() and not self.returning_cluster:
            # avoid running too early for non returning clusters
            self._charm.unit.status = BlockedStatus(
                "Wait until unit is initialized before running create-replication on offer side"
            )
            self._charm.app.status = MaintenanceStatus("Setting up replication")
            return
        if self.returning_cluster:
            # flag set on prior async relation broken
            # allows the relation to be created with user data so
            # rejoining to the cluster-set can be done incrementally
            # on incompatible user data, join fallbacks to clone
            logger.debug("User data check skipped")
        else:
            logger.debug("Checking for user data")
            if self._charm._mysql.get_non_system_databases():
                # don't check for user data if skip flag is set
                logger.info(
                    "\n\tUser data found, aborting async replication setup."
                    "\n\tEnsure the cluster has no user data before trying to join a cluster set."
                    "\n\tAfter removing/backing up the data, remove the relation and add it again."
                )
                self._charm.app.status = BlockedStatus(
                    "User data found, check instruction in the log"
                )
                self._charm.unit.status = BlockedStatus(
                    "User data found, aborting async replication setup"
                )
                self.relation_data["user-data-found"] = "true"
                return

        self._charm.app.status = MaintenanceStatus("Setting up replication")
        self._charm.unit.status = WaitingStatus("Awaiting sync data from primary cluster")

    def _on_consumer_changed(self, event):  # noqa: C901
        """Handle the async_replica relation being changed."""
        if not self._charm.unit.is_leader():
            return
        state = self.state
        logger.debug(f"Replica cluster {state.value=}")

        if state == States.SYNCING:
            if self.returning_cluster:
                # when running from and async relation broken
                # re-create the cluster and wait
                logger.debug("Recreating cluster prior to sync credentials")
                self._charm.create_cluster()
                # (re)set flags
                self._charm.app_peer_data.update({
                    "removed-from-cluster-set": "",
                    "rejoin-secondaries": "true",
                })
                event.defer()
                return
            if not self._charm.cluster_fully_initialized:
                # cluster is not fully initialized
                # avoid race on credentials sync
                logger.debug(
                    "Cluster not fully initialized yet, waiting until all units join the cluster"
                )
                self._charm.unit.status = WaitingStatus("Waiting other units join the cluster")
                event.defer()
                return

            if not self._check_version():
                self._charm.unit.status = BlockedStatus(
                    "MySQL version mismatch with primary cluster. Check logs for details"
                )
                logger.error("MySQL version mismatch with primary cluster. Remove relation.")
                return

            logger.debug("Syncing credentials from primary cluster")
            self._charm.unit.status = MaintenanceStatus("Syncing credentials")
            self._charm.app.status = MaintenanceStatus("Setting up replication")

            try:
                credentials = self._async_replication_credentials()
            except SecretNotFoundError:
                logger.debug("Secret not found, deferring event")
                event.defer()
                return
            sync_keys = {
                SERVER_CONFIG_PASSWORD_KEY: SERVER_CONFIG_USERNAME,
                CLUSTER_ADMIN_PASSWORD_KEY: CLUSTER_ADMIN_USERNAME,
                MONITORING_PASSWORD_KEY: MONITORING_USERNAME,
                BACKUPS_PASSWORD_KEY: BACKUPS_USERNAME,
                ROOT_PASSWORD_KEY: ROOT_USERNAME,
            }

            for key, password in credentials.items():
                # sync credentials only for necessary users
                user = sync_keys[key]
                if user == ROOT_USERNAME:
                    # root user is only local
                    self._charm._mysql.update_user_password(user, password, host="localhost")
                else:
                    self._charm._mysql.update_user_password(user, password)
                self._charm.set_secret("app", key, password)
                logger.debug(f"Synced {user=} password")

            self._charm.unit.status = MaintenanceStatus("Dissolving replica cluster")
            logger.info("Dissolving replica cluster")
            self._charm._mysql.dissolve_cluster(force=True)
            # reset force rejoin-secondaries flag
            del self._charm.app_peer_data["rejoin-secondaries"]

            if self.remote_relation_data["cluster-name"] == self.cluster_name:  # pyright: ignore
                # this cluster need a new cluster name
                # we append the model uuid, trimming to a max of 63 characters
                logger.warning(
                    "Cluster name is the same as the primary cluster. Appending model uuid"
                )
                self._charm.app_peer_data["cluster-name"] = (
                    f"{self.cluster_name}{self.model.uuid.replace('-', '')}"[:63]
                )

            self._charm.unit.status = MaintenanceStatus("Populate endpoint")

            # this cluster name is used by the primary cluster to identify the replica cluster
            self.relation_data["cluster-name"] = self.cluster_name
            # the reachable endpoint address
            self.relation_data["endpoint"] = self._get_endpoint()
            # the node label in the replica cluster to be created
            self.relation_data["node-label"] = self._charm.unit_label

            logger.debug("Data for adding replica cluster shared with primary cluster")

            self._charm.unit.status = WaitingStatus("Waiting for primary cluster")
        elif state == States.READY:
            # update status
            logger.info("Replica cluster is ready")

            # sync cluster-set domain name across clusters
            if cluster_set_domain_name := self._charm._mysql.get_cluster_set_name():
                self._charm.app_peer_data["cluster-set-domain-name"] = cluster_set_domain_name

            self._charm._on_update_status(None)
        elif state == States.RECOVERING:
            # recovering cluster (copying data and/or joining units)
            self._charm.app.status = MaintenanceStatus("Recovering replica cluster")
            self._charm.unit.status = WaitingStatus(
                "Waiting for recovery to complete on other units"
            )
            logger.debug("Awaiting other units to join the cluster")

            # TODO:
            #  Remove `.lower()` when migrating to MySQL 8.4
            #  (when breaking changes are allowed)
            # set state flags to allow secondaries to join the cluster
            self._charm.unit_peer_data["member-state"] = InstanceState.ONLINE.lower()
            self._charm.unit_peer_data["member-role"] = InstanceRole.PRIMARY.lower()
            event.defer()

    def _on_consumer_non_leader_created(self, _):
        """Handle the consumer relation being created for secondaries/non-leader."""
        # set waiting state to inhibit auto recovery, only when not already set
        if self._charm.unit.is_leader():
            return
        if self._charm.unit_peer_data.get("member-state") != "waiting":
            self._charm.unit_peer_data["member-state"] = "waiting"
            self._charm.unit.status = WaitingStatus("waiting replica cluster be configured")

    def _on_consumer_non_leader_changed(self, _):
        """Reset cluster secondaries to allow cluster rejoin after primary recovery."""
        # the replica state is initialized when the primary cluster finished
        # creating the replica cluster on this cluster primary/leader unit
        if self._charm.unit.is_leader():
            return
        if (
            self.replica_initialized
            or self._charm.app_peer_data.get("rejoin-secondaries") == "true"
        ) and not self._charm._mysql.is_instance_in_cluster(self._charm.unit_label):
            logger.debug("Reset secondary unit to allow cluster rejoin")
            # reset unit flag to allow cluster rejoin after primary recovery
            # the unit will rejoin on the next peer relation changed or update status
            self._charm.unit_peer_data["member-state"] = "waiting"
            self._charm.unit.status = WaitingStatus("waiting to join the cluster")

    def _on_secret_change(self, event: SecretChangedEvent):
        """Propagates the secret being changed."""
        if not self._charm.unit.is_leader():
            return

        if not self.relation:
            return

        if event.secret.id.removeprefix("secret:") not in self.remote_relation_data.get(
            "secret-id", "dummy"
        ):
            logger.info("Secret not related to replication")
            return

        logger.debug("Propagating secret change from the relation offer")
        credentials = self._async_replication_credentials()

        self._charm.model.get_secret(label=f"{PEER}.{self.model.app.name}.app").set_content(
            credentials
        )
