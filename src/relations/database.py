# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library containing the implementation of the standard relation."""


import logging

from charms.data_platform_libs.v0.database_provides import (
    DatabaseProvides,
    DatabaseRequestedEvent,
)
from charms.mysql.v0.mysql import (
    MySQLClientError,
    MySQLCreateApplicationDatabaseAndScopedUserError,
    MySQLDeleteUserForRelationError,
    MySQLGetClusterMembersAddressesError,
    MySQLGetMySQLVersionError,
    MySQLGrantPrivilegesToUserError,
    MySQLUpgradeUserForMySQLRouterError,
)
from ops.charm import (
    PebbleReadyEvent,
    RelationBrokenEvent,
    RelationDepartedEvent,
    RelationJoinedEvent,
)
from ops.framework import Object
from ops.model import BlockedStatus

from constants import CONTAINER_RESTARTS, DB_RELATION_NAME, PASSWORD_LENGTH, PEER
from utils import generate_random_password

logger = logging.getLogger(__name__)


class DatabaseRelation(Object):
    """Standard database relation class."""

    def __init__(self, charm):
        super().__init__(charm, DB_RELATION_NAME)

        self.charm = charm

        self.database = DatabaseProvides(self.charm, relation_name=DB_RELATION_NAME)
        self.framework.observe(self.database.on.database_requested, self._on_database_requested)

        self.framework.observe(
            self.charm.on[DB_RELATION_NAME].relation_broken, self._on_database_broken
        )

        self.framework.observe(
            self.charm.on[PEER].relation_departed, self._on_peer_relation_departed
        )
        self.framework.observe(self.charm.on[PEER].relation_joined, self._on_peer_relation_joined)
        self.framework.observe(self.charm.on[PEER].relation_changed, self._configure_endpoints)
        self.framework.observe(self.charm.on.leader_elected, self._configure_endpoints)
        self.framework.observe(self.charm.on.mysql_pebble_ready, self._on_mysql_pebble_ready)
        self.framework.observe(self.charm.on.update_status, self._configure_endpoints)

    # =============
    # Helpers
    # =============

    def _get_or_set_password(self, relation) -> str:
        """Retrieve password from cache or generate a new one.

        Args:
            relation (str): The relation for each the password is cached.

        Returns:
            str: The password.
        """
        if password := relation.data[self.charm.app].get("password"):
            return password
        password = generate_random_password(PASSWORD_LENGTH)
        relation.data[self.charm.app]["password"] = password
        return password

    def _update_endpoints(self, relation_id: int) -> None:
        """Updates the endpoints + read-only-endpoints in the relation.

        Args:
            relation_id: The id of the relation for which to update the endpoints
        """
        try:
            logger.debug(f"Updating the endpoints for relation {relation_id}")
            primary_endpoint = self.charm._mysql.get_cluster_primary_address()
            self.database.set_endpoints(relation_id, primary_endpoint)

            logger.debug(f"Updating the read_only_endpoints for relation {relation_id}")
            read_only_endpoints = sorted(
                self.charm._mysql.get_cluster_members_addresses() - {primary_endpoint}
            )
            self.database.set_read_only_endpoints(relation_id, ",".join(read_only_endpoints))
        except MySQLGetClusterMembersAddressesError as e:
            logger.exception("Failed to get cluster members", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to get cluster members")
        except MySQLClientError as e:
            logger.exception("Failed to get primary", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to get primary")

    # =============
    # Handlers
    # =============

    def _on_database_requested(self, event: DatabaseRequestedEvent) -> None:
        """Handle the `database-requested` event."""
        if not self.charm.unit.is_leader():
            return
        # check if cluster is ready and if not, defer
        if not self.charm.cluster_initialized:
            logger.debug("Waiting cluster to be initialized")
            event.defer()
            return

        # get base relation data
        relation_id = event.relation.id
        db_name = event.database
        extra_user_roles = []
        if event.extra_user_roles:
            extra_user_roles = event.extra_user_roles.split(",")
        # user name is derived from the relation id
        db_user = f"relation-{relation_id}"
        db_pass = self._get_or_set_password(event.relation)

        remote_app = event.app.name

        try:
            db_version = self.charm._mysql.get_mysql_version()
            primary_endpoint = self.charm._mysql.get_cluster_primary_address()
            self.database.set_credentials(relation_id, db_user, db_pass)
            self.database.set_endpoints(relation_id, primary_endpoint)
            self.database.set_version(relation_id, db_version)
            # get read only endpoints by removing primary from all members
            read_only_endpoints = sorted(
                self.charm._mysql.get_cluster_members_addresses()
                - {
                    primary_endpoint,
                }
            )

            self.database.set_read_only_endpoints(relation_id, ",".join(read_only_endpoints))
            # TODO:
            # add setup of tls, tls_ca and status
            # add extra roles parsing from relation data
            self.charm._mysql.create_application_database_and_scoped_user(
                db_name, db_user, db_pass, "%", remote_app
            )

            if "mysqlrouter" in extra_user_roles:
                self.charm._mysql.upgrade_user_for_mysqlrouter(db_user, "%")
                self.charm._mysql.grant_privileges_to_user(
                    db_user, "%", ["CREATE USER"], with_grant_option=True
                )

            logger.info(f"Created user for app {remote_app}")
        except (
            MySQLCreateApplicationDatabaseAndScopedUserError,
            MySQLGetMySQLVersionError,
            MySQLGetClusterMembersAddressesError,
            MySQLClientError,
            MySQLUpgradeUserForMySQLRouterError,
            MySQLGrantPrivilegesToUserError,
        ) as e:
            logger.exception("Failed to set up database relation", exc_info=e)
            self.charm.unit.status = BlockedStatus("Failed to create scoped user")

    def _on_mysql_pebble_ready(self, event: PebbleReadyEvent) -> None:
        """Handle the mysql pebble ready event.

        Update a value in the peer app databag to trigger the peer_relation_changed
        handler which will in turn update the endpoints.
        """
        if not self.charm.cluster_initialized:
            return

        charm_unit_label = self.charm.unit.name.replace("/", "-")
        if not self.charm._mysql.is_instance_in_cluster(charm_unit_label):
            logger.debug(f"Unit {self.charm.unit.name} is not yet a member of the cluster")
            event.defer()
            return

        container_restarts = int(self.charm.unit_peer_data.get(CONTAINER_RESTARTS, "0"))
        self.charm.unit_peer_data[CONTAINER_RESTARTS] = str(container_restarts + 1)

        self._configure_endpoints(None)

    def _on_peer_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle the peer relation joined event.

        Update the endpoints + read_only_endpoints.
        """
        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not self.charm.unit.is_leader() or not relations or not self.charm.cluster_initialized:
            return

        event_unit_label = event.unit.name.replace("/", "-")
        if not self.charm._mysql.is_instance_in_cluster(event_unit_label):
            logger.debug(f"Unit {event.unit.name} is not yet a member of the cluster")
            event.defer()
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested has executed
            if relation.id not in relation_data:
                continue

            self._update_endpoints(relation.id)

    def _on_peer_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle the peer relation departed event.

        Update the endpoints + read_only_endpoints.
        """
        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not self.charm.unit.is_leader() or not relations or not self.charm.cluster_initialized:
            return

        departing_unit_name = event.departing_unit.name.replace("/", "-")

        if self.charm._mysql.is_instance_in_cluster(departing_unit_name):
            logger.debug(f"Departing unit {departing_unit_name} still in cluster")
            event.defer()
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested has executed
            if relation.id not in relation_data:
                continue

            self._update_endpoints(relation.id)

    def _configure_endpoints(self, _) -> None:
        """Update the endpoints + read_only_endpoints."""
        relations = self.charm.model.relations.get(DB_RELATION_NAME, [])
        if not self.charm.unit.is_leader() or not relations or not self.charm.cluster_initialized:
            return

        relation_data = self.database.fetch_relation_data()
        for relation in relations:
            # only update endpoints if on_database_requested has executed
            if relation.id not in relation_data:
                continue

            self._update_endpoints(relation.id)

    def _on_database_broken(self, event: RelationBrokenEvent) -> None:
        """Handle the removal of database relation.

        Remove user, keeping database intact.
        """
        if not self.charm.unit.is_leader():
            # run once by the leader
            return

        try:
            relation_id = event.relation.id
            self.charm._mysql.delete_user_for_relation(relation_id)
            logger.info(f"Removed user for relation {relation_id}")
        except MySQLDeleteUserForRelationError:
            logger.error(f"Failed to delete user for relation {relation_id}")
            return
